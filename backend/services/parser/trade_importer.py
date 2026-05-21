"""Import parsed TradeReport rows into `Trade` ledger + side tables."""
from __future__ import annotations
from datetime import date, datetime
from typing import Any, Dict, Optional
from loguru import logger
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session
from models.db_models import BondLot, CDU, DepositLot, RepoLot, Trade
from services.calculator.constants import normalize_cdu_name
from .trade_report_parser import ParsedTradeFile


def import_trades_from_parsed(
    db: Session, parsed: ParsedTradeFile,
    *, uploaded_by: Optional[str] = None,
    source_doc_id: Optional[int] = None,
    commit: bool = True,
) -> Dict[str, int]:
    """Import parsed rows into the Trade ledger.

    Set ``commit=False`` when the caller manages the transaction (e.g. the
    upload route, which needs the full pipeline to be atomic).
    """
    cdu_name = parsed.cdu_name
    cdu_id = None
    if cdu_name:
        canonical = normalize_cdu_name(cdu_name) or str(cdu_name).strip()
        row = db.execute(select(CDU).where(CDU.name == canonical)).scalars().first()
        if row:
            cdu_id = row.id
    if cdu_id is None:
        logger.warning(f"TradeReport {parsed.filename}: CDU not resolved")
        return {"trades": 0, "skipped_no_cdu": len(parsed.rows)}

    trade_date = parsed.trade_date or date.today()

    # ── replace previous import for same CDU+date idempotently ──
    old_trade_ids = db.execute(
        select(Trade.id).where(
            Trade.cdu_id == cdu_id,
            Trade.trade_date == trade_date,
            Trade.is_active == True,
        )
    ).scalars().all()
    if old_trade_ids:
        db.execute(delete(BondLot).where(BondLot.open_trade_id.in_(old_trade_ids)))
        db.execute(delete(RepoLot).where(or_(
            RepoLot.open_trade_id.in_(old_trade_ids),
            RepoLot.close_trade_id.in_(old_trade_ids),
        )))
        db.execute(delete(DepositLot).where(or_(
            DepositLot.open_trade_id.in_(old_trade_ids),
            DepositLot.close_trade_id.in_(old_trade_ids),
        )))
    db.execute(
        update(Trade)
        .where(Trade.cdu_id == cdu_id, Trade.trade_date == trade_date, Trade.is_active == True)
        .values(is_active=False, updated_at=datetime.utcnow())
    )
    db.flush()

    counters = {"trades": 0, "bond_lots": 0, "repo_lots": 0, "deposit_lots": 0}
    for pr in parsed.rows:
        f = pr.fields
        op = f.get("operation_type", "OTHER")
        if op == "REPO_HEADER":
            continue
        deal = str(f.get("deal_number") or "").strip()
        if not deal:
            deal = f"{f.get('order_number') or 'UNK'}_{pr.raw_index}"
        existing = db.execute(select(Trade).where(
            Trade.cdu_id == cdu_id, Trade.deal_id == deal,
            Trade.operation_type == op, Trade.trade_date == trade_date,
        )).scalars().first()
        volume = _f(f.get("volume"))
        price = _f(f.get("price"))
        nominal = _f(f.get("nominal_volume")) or volume
        qty = _f(f.get("lots")) or nominal
        isin = str(f.get("instrument_code") or "").strip()
        currency = str(f.get("currency_code") or "KZT").strip().upper()[:8]
        repo_sum = _f(f.get("repo_sum"))
        repo_buyback_sum = _f(f.get("repo_buyback_sum"))
        amount = volume or 0.0
        if op in ("BUY", "REPO_OPEN", "FX_BUY", "DEPOSIT_OPEN"):
            amount = -abs(amount)
        elif op in ("SELL", "REPO_CLOSE", "FX_SELL", "DEPOSIT_CLOSE"):
            amount = abs(repo_buyback_sum or amount)
        kw = dict(
            cdu_id=cdu_id, deal_id=deal,
            trade_date=trade_date, value_date=_d(f.get("settlement_date")),
            operation_type=op, instrument_code=isin or None,
            instrument_category=f.get("instrument_category") or "OTHER",
            direction="Покупка" if "BUY" in op or "OPEN" in op else ("Продажа" if "SELL" in op or "CLOSE" in op else None),
            amount_kzt=amount,
            amount_ccy=amount,
            quantity=qty, face_value=nominal,
            market_price=price, accrued_interest=_f(f.get("accrued_interest_volume")),
            ytm=_f(f.get("yield_pct")),
            currency=currency, repo_rate_pct=_f(f.get("repo_rate_pct")),
            repo_term_days=f.get("repo_term_days"),
            repo_buyback_sum=repo_buyback_sum,
            commission_total=_f(f.get("commission_total")),
            # Initial price-reconciliation state: capture the original CDU
            # price; ``price_final`` mirrors it until ``apply_kase_prices_to_trades``
            # has had a chance to overwrite it from KASE.
            price_original=price,
            price_final=price,
            price_flag=False,
            source_doc_id=source_doc_id,
            is_active=True,
            created_by=uploaded_by, created_at=datetime.utcnow(),
        )
        if existing:
            for k, v in kw.items():
                setattr(existing, k, v)
            existing.is_active = True
            existing.updated_at = datetime.utcnow()
            trade_obj = existing
        else:
            trade_obj = Trade(**kw)
            db.add(trade_obj)
            db.flush()
        counters["trades"] += 1
        if op == "BUY" and isin and nominal:
            db.add(BondLot(
                cdu_id=cdu_id, isin=isin, category=kw["instrument_category"] or "OTHER",
                trade_date=trade_date, valuation_date=kw.get("value_date") or trade_date,
                quantity_initial=nominal, quantity_current=nominal,
                face_value_initial=nominal, face_value_current=nominal,
                purchase_price=price, open_trade_id=trade_obj.id,
                source_doc_id=source_doc_id,
            ))
            counters["bond_lots"] += 1
        if op in ("REPO_OPEN", "REPO_CLOSE"):
            repo_face = repo_sum if op == "REPO_OPEN" else (repo_buyback_sum or volume or nominal)
            _repo(db, trade_obj, cdu_id, isin, op, repo_face,
                  _f(f.get("repo_rate_pct")), f.get("repo_term_days"),
                  trade_date, source_doc_id)
            counters["repo_lots"] += 1
        if op in ("DEPOSIT_OPEN", "DEPOSIT_CLOSE"):
            _dep(db, trade_obj, cdu_id, op, volume,
                 _f(f.get("repo_rate_pct")), trade_date, source_doc_id)
            counters["deposit_lots"] += 1
    if commit:
        db.commit()
    else:
        db.flush()
    logger.info(f"Trade import: {counters} cdu={cdu_id} date={trade_date}")
    return counters


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return None if v != v else float(v)
    try:
        return float(str(v).replace(" ", "").replace("\u00a0", "").replace(",", "."))
    except (ValueError, TypeError):
        return None


def _d(v: Any) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _repo(db, trade, cdu_id, isin, op, face, rate, term, td, doc_id):
    code = isin or trade.instrument_code
    if op == "REPO_OPEN":
        db.add(RepoLot(
            cdu_id=cdu_id, instrument_code=code, isin=isin,
            trade_date=td, valuation_date=trade.value_date or td,
            face_value=face or 0.0, repo_rate_pct=rate, term_days=term,
            open_trade_id=trade.id, source_doc_id=doc_id,
        ))
    else:
        ex = db.execute(select(RepoLot).where(
            RepoLot.cdu_id == cdu_id, RepoLot.instrument_code == code,
            RepoLot.close_date.is_(None),
        ).order_by(RepoLot.trade_date.asc())).scalars().first()
        close_dt = trade.value_date or td
        if ex:
            ex.close_date = close_dt; ex.close_value = face or ex.face_value; ex.close_trade_id = trade.id; ex.is_closed = True
        else:
            db.add(RepoLot(
                cdu_id=cdu_id, instrument_code=code, isin=isin,
                trade_date=td, valuation_date=td, close_date=close_dt,
                face_value=face or 0.0, close_value=face or 0.0,
                repo_rate_pct=rate, close_trade_id=trade.id, source_doc_id=doc_id,
            ))


def _dep(db, trade, cdu_id, op, principal, rate, td, doc_id):
    if op == "DEPOSIT_OPEN":
        db.add(DepositLot(
            cdu_id=cdu_id, trade_date=td,
            valuation_date=trade.value_date or td,
            principal=principal or 0.0, interest_rate_pct=rate,
            open_trade_id=trade.id, source_doc_id=doc_id,
        ))
    else:
        ex = db.execute(select(DepositLot).where(
            DepositLot.cdu_id == cdu_id, DepositLot.close_date.is_(None),
        ).order_by(DepositLot.trade_date.asc())).scalars().first()
        if ex:
            ex.close_date = td; ex.close_trade_id = trade.id; ex.is_closed = True
        else:
            db.add(DepositLot(
                cdu_id=cdu_id, trade_date=td, valuation_date=td,
                close_date=td, principal=principal or 0.0,
                interest_rate_pct=rate,
                close_trade_id=trade.id, source_doc_id=doc_id,
            ))


def import_single_trade_report_xlsx(
    db: Session, file_path: str, *, uploaded_by: Optional[str] = None,
    source_doc_id: Optional[int] = None,
) -> Dict[str, Any]:
    from .trade_report_parser import TradeReportParser
    parsed = TradeReportParser(file_path).parse()
    if parsed.cdu_name is None:
        return {"error": "CDU not detected", "warnings": parsed.warnings}
    counters = import_trades_from_parsed(db, parsed, uploaded_by=uploaded_by, source_doc_id=source_doc_id)
    return {"cdu_name": parsed.cdu_name,
            "trade_date": parsed.trade_date.isoformat() if parsed.trade_date else None,
            **counters, "warnings": parsed.warnings}
