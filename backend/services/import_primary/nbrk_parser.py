"""Daily file of the National Bank (КФГД_ГГГГММДД.csv) — business process 7.2.

The file is a «;»-separated CSV in UTF-16 (KASE/T24 export) with the columns
MODULE; T24 ID; ISIN / NIN; COUNTERPARTY; TRANS.TYPE; CCY.1; CCY.2;
TRADE.DATE; VALUE.DATE.BUY; VALUE.DATE.SELL; MATURITY.DATE; NOMINAL; BUY.AMT;
SELL.AMT; RATE; PRICE.1; PRICE.2; ACCRUED.AMT; AMOUNT.DUE; PORTFOLIO; …; YTM.

Modules:

* ``AC`` — accounts.  For the date TRADE.DATE (the business day before the
  file date): NOMINAL = balance, BUY.AMT = outflows, SELL.AMT = inflows.
  Accounts (ISIN/NIN): 28077 — own assets KZT (310138-1), 12831 — special
  reserve KZT (300138-1), 30872 — special reserve USD at Euroclear.
  Used for the cash reconciliation when the statement is missing (БП 7.3 B).
* ``MM`` / «Размещ. депоз.» — deposit with the NBRK (7.2.4): opening on
  VALUE.DATE.BUY for −NOMINAL, closing on MATURITY.DATE for
  +(NOMINAL + ACCRUED.AMT); one DepositLot (base 360).
* ``RP`` / «CRR» — reverse REPO (7.2.1): −BUY.AMT on VALUE.DATE.BUY,
  +SELL.AMT on MATURITY.DATE.
* ``SC`` / «BUY»/«SEL» — purchase/sale of securities (7.2.2/7.2.3/7.2.5/7.2.6):
  ∓AMOUNT.DUE (× rate for USD), USD securities belong to the special reserve.
* ``FX`` — currency deals (7.2.7/7.2.8): reported for manual processing
  (the direction must be checked against AC/30872, no sample files yet).

Portfolio mapping (Sub-fund): 310138-1 → собственные, 300138-1 → спецрезерв.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from models.db_models import (
    BondLot, CashMovement, CashSnapshot, CDU, DepositLot, FXRate, RepoLot, Trade,
)

OWN, RESERVE = "310138-1", "300138-1"
ACCOUNT_PORTFOLIO = {
    "28077": (OWN, "KZT"),
    "12831": (RESERVE, "KZT"),
    "30872": (RESERVE, "USD"),
}
FILE_RE = re.compile(r"(?i)(?:^|[^a-zа-я])(кфгд|kfgd)_(\d{8})(?!\d)")


# ───────────────────────── parsing ─────────────────────────

def _decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    t = str(v).strip().replace("\xa0", "").replace(" ", "")
    if not t:
        return None
    if "," in t and "." not in t:
        t = t.replace(",", ".")
    else:
        t = t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def _date(v: Any) -> Optional[date]:
    t = str(v or "").strip()
    if re.fullmatch(r"\d{8}", t) and t != "00000000":
        try:
            return datetime.strptime(t, "%Y%m%d").date()
        except ValueError:
            return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def file_date_from_name(name: str) -> Optional[date]:
    m = FILE_RE.search(Path(name).stem)
    return _date(m.group(2)) if m else None


def looks_like_nbrk_file(name: str, raw: Optional[bytes] = None) -> bool:
    if FILE_RE.search(Path(name).stem):
        return True
    if raw:
        head = _decode(raw[:4000])
        return "MODULE" in head and "T24 ID" in head and "PORTFOLIO" in head
    return False


def parse_nbrk_bytes(raw: bytes, file_name: str = "") -> Dict[str, Any]:
    text = _decode(raw)
    reader = csv.reader(io.StringIO(text), delimiter=";")
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("Файл НБ РК пуст")
    header = [h.strip().upper() for h in rows[0]]
    if "MODULE" not in header:
        raise ValueError("Не найден заголовок MODULE — это не файл КФГД_ГГГГММДД")
    items: List[Dict[str, str]] = []
    for r in rows[1:]:
        item = {header[i]: (r[i].strip() if i < len(r) else "") for i in range(len(header))}
        if item.get("MODULE"):
            items.append(item)
    accounts = []
    for it in items:
        if it["MODULE"].upper() != "AC" or not it.get("ISIN / NIN"):
            continue
        acc = it["ISIN / NIN"]
        portfolio, ccy = ACCOUNT_PORTFOLIO.get(acc, (None, it.get("CCY.1") or None))
        accounts.append({
            "account": acc, "counterparty": it.get("COUNTERPARTY"), "currency": it.get("CCY.1") or ccy,
            "portfolio": portfolio, "date": _date(it.get("TRADE.DATE")),
            "balance": _num(it.get("NOMINAL")), "outflow": _num(it.get("BUY.AMT")),
            "inflow": _num(it.get("SELL.AMT")), "amount_due": _num(it.get("AMOUNT.DUE")),
        })
    return {
        "file_name": file_name,
        "file_date": file_date_from_name(file_name) or max(
            (d for d in (_date(i.get("TRADE.DATE")) for i in items) if d), default=None),
        "items": items,
        "accounts": accounts,
    }


# ───────────────────────── import ─────────────────────────

def _cdu_for_portfolio(db: Session, portfolio: Optional[str]) -> Optional[CDU]:
    if not portfolio:
        return None
    code = portfolio.strip()
    return db.execute(select(CDU).where(or_(
        CDU.portfolio_code == code, CDU.participant_code.like(f"%{code}%"),
    ))).scalars().first()


def _fx(db: Session, currency: str, on: date) -> Optional[float]:
    if currency in ("KZT", "", None):
        return 1.0
    row = db.execute(select(FXRate).where(
        FXRate.currency == currency, FXRate.rate_date <= on,
    ).order_by(FXRate.rate_date.desc())).scalars().first()
    return float(row.rate) if row and row.rate else None


def _replace_trade(db: Session, cdu_id: int, deal_id: str) -> None:
    """Re-import: drop the previous version of an imported NBRK deal."""
    for t in db.execute(select(Trade).where(
        Trade.cdu_id == cdu_id, Trade.deal_id == deal_id, Trade.is_manual.is_(False),
        Trade.is_active.is_(True),
    )).scalars():
        t.is_active = False
        for cm in db.execute(select(CashMovement).where(CashMovement.related_trade_id == t.id)).scalars():
            cm.is_active = False
        for model in (DepositLot, RepoLot):
            for lot in db.execute(select(model).where(or_(
                model.open_trade_id == t.id, model.close_trade_id == t.id,
            ))).scalars():
                db.delete(lot)
        for lot in db.execute(select(BondLot).where(BondLot.open_trade_id == t.id)).scalars():
            db.delete(lot)
    db.flush()


def _trade(db: Session, *, cdu_id: int, deal_id: str, op: str, trade_date: date, value_date: date,
           amount_kzt: float, currency: str = "KZT", amount_ccy: Optional[float] = None,
           fx_rate: float = 1.0, category: str, isin: Optional[str] = None, doc_id: Optional[int],
           description: str, **extra) -> Trade:
    t = Trade(
        cdu_id=cdu_id, trade_date=trade_date, value_date=value_date, operation_type=op,
        instrument_category=category, isin=isin, instrument_code=isin, deal_id=deal_id,
        amount_kzt=amount_kzt, amount_ccy=amount_ccy if amount_ccy is not None else amount_kzt,
        currency=currency, fx_rate=fx_rate, description=description,
        is_manual=False, is_active=True, workflow_status="APPROVED",
        approved_by="SYSTEM", approved_at=datetime.utcnow(), source_doc_id=doc_id,
        created_by="nbrk_import", **extra,
    )
    db.add(t)
    db.flush()
    db.add(CashMovement(
        cdu_id=cdu_id, operation_date=value_date, amount=amount_kzt, amount_kzt=amount_kzt,
        currency="KZT", movement_type={
            "DEPOSIT_OPEN": "DEPOSIT_OPEN", "DEPOSIT_CLOSE": "DEPOSIT_CLOSE",
            "REPO_OPEN": "REPO_OPEN", "REPO_CLOSE": "REPO_CLOSE",
            "BUY": "SECURITY_PURCHASE", "SELL": "SECURITY_SALE",
        }.get(op, "OTHER"),
        basis=f"Файл НБ РК: {description}", related_trade_id=t.id, related_isin=isin,
        source_doc_id=doc_id, is_manual=False, workflow_status="APPROVED",
        approved_by="SYSTEM", approved_at=datetime.utcnow(),
    ))
    return t


def _store_account_balances(db: Session, accounts: List[Dict[str, Any]],
                            source_doc_id: Optional[int]) -> int:
    """AC rows → opening cash of the NBRK portfolios.

    The balance of an account on TRADE.DATE (end of the previous business day)
    is the cash of the portfolio («Собственные активы» / «Спецрезерв»); the
    deposits and REPO of the file move it from the next day on.  Without it the
    portfolio had only the outflows of the placements and its value in
    «Сводка» was close to zero.
    """
    n = 0
    for acc in accounts:
        if acc.get("date") is None or acc.get("balance") is None:
            continue
        cdu = _cdu_for_portfolio(db, acc.get("portfolio"))
        if cdu is None:
            continue
        currency = (acc.get("currency") or "KZT").upper()
        row = db.execute(select(CashSnapshot).where(
            CashSnapshot.cdu_id == cdu.id,
            CashSnapshot.snapshot_date == acc["date"],
            CashSnapshot.currency == currency,
            CashSnapshot.portfolio_code == acc.get("account"),
        )).scalars().first()
        if row is None:
            row = CashSnapshot(cdu_id=cdu.id, snapshot_date=acc["date"], currency=currency,
                               portfolio_code=acc.get("account"))
            db.add(row)
        row.amount = float(acc["balance"])
        row.amount_kzt = None if currency != "KZT" else float(acc["balance"])
        row.source = "nbrk_ac"
        row.source_doc_id = source_doc_id
        n += 1
    return n


def import_nbrk_file(db: Session, file_path: str | Path, *, source_doc_id: Optional[int] = None,
                     actor: Optional[str] = None, file_name: Optional[str] = None) -> Dict[str, Any]:
    path = Path(file_path)
    parsed = parse_nbrk_bytes(path.read_bytes(), file_name or path.name)
    counters: Dict[str, Any] = {
        "file_date": parsed["file_date"], "report_date": parsed["file_date"],
        "deposits": 0, "repos": 0, "securities": 0, "fx_manual": 0, "trades": 0,
        "accounts": parsed["accounts"], "warnings": [],
    }
    from services.portfolio.reference import ReferenceBook
    refs = ReferenceBook(db)
    for it in parsed["items"]:
        module = it["MODULE"].upper()
        ttype = (it.get("TRANS.TYPE") or "").strip()
        t24 = it.get("T24 ID") or ""
        portfolio = it.get("PORTFOLIO") or None
        trade_date = _date(it.get("TRADE.DATE")) or parsed["file_date"]
        if module == "AC":
            continue
        if module == "FX":
            counters["fx_manual"] += 1
            counters["warnings"].append(
                f"FX {t24}: валютная сделка {it.get('BUY.AMT')} {it.get('CCY.1')} / {it.get('SELL.AMT')} — "
                "отразите вручную (направление сверяется с AC/30872, примеров файла ещё нет)")
            continue
        currency = (it.get("CCY.1") or "KZT").upper()
        if module == "SC" and currency == "USD":
            portfolio = RESERVE           # USD securities: special reserve (БП 7.2.5)
        cdu = _cdu_for_portfolio(db, portfolio)
        if cdu is None:
            counters["warnings"].append(f"{module} {t24}: портфель {portfolio!r} не найден — строка пропущена")
            continue

        if module == "MM" and "депоз" in ttype.lower():
            nominal = _num(it.get("NOMINAL")) or 0.0
            accrued = _num(it.get("ACCRUED.AMT")) or 0.0
            rate = _num(it.get("RATE"))
            vbuy = _date(it.get("VALUE.DATE.BUY")) or trade_date
            mat = _date(it.get("MATURITY.DATE"))
            for suffix in ("-O", "-C"):
                _replace_trade(db, cdu.id, f"{t24}{suffix}")
            term = (mat - vbuy).days if mat else None
            open_t = _trade(db, cdu_id=cdu.id, deal_id=f"{t24}-O", op="DEPOSIT_OPEN", trade_date=trade_date,
                            value_date=vbuy, amount_kzt=-nominal, category="DEPOSIT", doc_id=source_doc_id,
                            description=f"Размещение депозита НБ РК {t24}", interest_rate_pct=rate,
                            deposit_principal=nominal, deposit_term_days=term)
            close_t = None
            if mat:
                close_t = _trade(db, cdu_id=cdu.id, deal_id=f"{t24}-C", op="DEPOSIT_CLOSE",
                                 trade_date=trade_date, value_date=mat, amount_kzt=nominal + accrued,
                                 category="DEPOSIT", doc_id=source_doc_id,
                                 description=f"Возврат депозита НБ РК {t24}", interest_rate_pct=rate,
                                 deposit_principal=nominal, deposit_term_days=term)
            db.add(DepositLot(
                cdu_id=cdu.id, deal_id=t24, trade_date=vbuy, valuation_date=vbuy, close_date=mat,
                principal=nominal, interest_rate_pct=rate, base=360, term_days=term,
                accrued_interest=None, portfolio_code=portfolio,
                open_trade_id=open_t.id, close_trade_id=close_t.id if close_t else None,
                is_closed=False, source_doc_id=source_doc_id,
            ))
            counters["deposits"] += 1
            counters["trades"] += 2 if close_t else 1
            continue

        if module == "RP" and ttype.upper() == "CRR":
            buy = abs(_num(it.get("BUY.AMT")) or 0.0)
            sell = abs(_num(it.get("SELL.AMT")) or 0.0)
            vbuy = _date(it.get("VALUE.DATE.BUY")) or trade_date
            mat = _date(it.get("MATURITY.DATE"))
            isin = it.get("ISIN / NIN") or None
            rate = _num(it.get("RATE"))
            for suffix in ("-O", "-C"):
                _replace_trade(db, cdu.id, f"{t24}{suffix}")
            open_t = _trade(db, cdu_id=cdu.id, deal_id=f"{t24}-O", op="REPO_OPEN", trade_date=trade_date,
                            value_date=vbuy, amount_kzt=-buy, category="REVERSE_REPO", isin=isin,
                            doc_id=source_doc_id, description=f"Обратное РЕПО НБ РК {t24} {isin or ''}",
                            repo_rate_pct=rate, repo_buyback_sum=sell,
                            repo_term_days=(mat - vbuy).days if mat else None)
            close_t = None
            if mat:
                close_t = _trade(db, cdu_id=cdu.id, deal_id=f"{t24}-C", op="REPO_CLOSE", trade_date=trade_date,
                                 value_date=mat, amount_kzt=sell, category="REVERSE_REPO", isin=isin,
                                 doc_id=source_doc_id, description=f"Закрытие обратного РЕПО НБ РК {t24}",
                                 repo_rate_pct=rate)
            db.add(RepoLot(
                cdu_id=cdu.id, instrument_code=isin, isin=isin, deal_id=t24, trade_date=trade_date,
                valuation_date=vbuy, close_date=mat, face_value=buy, close_value=sell,
                repo_rate_pct=rate, base=366, term_days=(mat - vbuy).days if mat else None,
                portfolio_code=portfolio, open_trade_id=open_t.id,
                close_trade_id=close_t.id if close_t else None, source_doc_id=source_doc_id,
            ))
            counters["repos"] += 1
            counters["trades"] += 2 if close_t else 1
            continue

        if module == "SC" and ttype.upper() in ("BUY", "SEL"):
            is_buy = ttype.upper() == "BUY"
            isin = (it.get("ISIN / NIN") or "").strip().upper() or None
            due = abs(_num(it.get("AMOUNT.DUE")) or 0.0)
            vdate = _date(it.get("VALUE.DATE.BUY" if is_buy else "VALUE.DATE.SELL")) or trade_date
            fx = _fx(db, currency, vdate)
            if fx is None:
                counters["warnings"].append(f"SC {t24}: нет курса {currency} на {vdate} — сделка пропущена (E002)")
                continue
            nominal = _num(it.get("NOMINAL"))
            ref = refs.get(isin)
            category = refs.category(isin, "FOREIGN_BONDS" if currency == "USD" else "GOV_BONDS")
            unit = float(ref.nominal) if ref is not None and ref.nominal else None
            _replace_trade(db, cdu.id, t24)
            t = _trade(db, cdu_id=cdu.id, deal_id=t24, op="BUY" if is_buy else "SELL",
                       trade_date=trade_date, value_date=vdate,
                       amount_kzt=(-due if is_buy else due) * fx, amount_ccy=-due if is_buy else due,
                       currency=currency, fx_rate=fx, category=category, isin=isin, doc_id=source_doc_id,
                       description=f"{'Покупка' if is_buy else 'Продажа'} {isin} номинала {nominal}",
                       face_value=nominal, quantity=(nominal / unit) if nominal and unit else None,
                       nominal_per_unit=unit, clean_price=_num(it.get("PRICE.1")), ytm=_num(it.get("YTM")))
            if ref is None:
                counters["warnings"].append(f"SC {t24}: ISIN {isin} нет в справочнике — дополните (E004)")
            counters["securities"] += 1
            counters["trades"] += 1
            continue

        counters["warnings"].append(f"{module} {t24}: тип операции {ttype!r} не поддерживается — строка пропущена")
    counters["cash_balances"] = _store_account_balances(db, parsed["accounts"], source_doc_id)
    db.flush()
    logger.info(f"NBRK file {parsed['file_name']}: { {k: v for k, v in counters.items() if k != 'accounts'} }")
    return counters
