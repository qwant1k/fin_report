"""Import parsed TradeReport rows into `Trade` ledger + side tables."""
from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional
from loguru import logger
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session
from models.db_models import (
    BondLot, CashMovement, CDU, DepositLot, FXRate, InstrumentReference, KasePrice,
    RepoLot, Trade,
)
from services.calculator.constants import normalize_cdu_name
from services.portfolio.reference import ReferenceBook
from .trade_report_parser import ParsedTradeFile


def import_trades_from_parsed(
    db: Session, parsed: ParsedTradeFile,
    *, uploaded_by: Optional[str] = None,
    source_doc_id: Optional[int] = None,
    commit: bool = True,
    cdu_id: Optional[int] = None,
) -> Dict[str, int]:
    """Import parsed rows into the Trade ledger.

    ``cdu_id`` (when given) is authoritative — e.g. the manager chosen by the
    user in the UI overrides the automatic detection.

    Set ``commit=False`` when the caller manages the transaction (e.g. the
    upload route, which needs the full pipeline to be atomic).

    Re-importing the same CDU/date replaces the previous *imported* rows only;
    manual operations (four-eyes workflow) and system-generated coupon /
    redemption events of that date are never touched.
    """
    if cdu_id is None:
        cdu_name = parsed.cdu_name
        if cdu_name:
            from services.cdu_lookup import find_cdu
            row = find_cdu(db, name=str(cdu_name).strip())
            if row:
                cdu_id = row.id
    if cdu_id is None:
        logger.warning(f"TradeReport {parsed.filename}: CDU not resolved")
        return {"trades": 0, "skipped_no_cdu": len(parsed.rows)}

    trade_date = parsed.trade_date
    if trade_date is None:
        parsed.warnings.append("Дата торгов не определена — использована дата загрузки; проверьте файл")
        trade_date = date.today()
    import_dates = {
        _d(pr.fields.get("trade_date"))
        or _d(pr.fields.get("trading_date"))
        or trade_date
        for pr in parsed.rows
    }

    # ── replace previous *imported* rows for same CDU+date idempotently ──
    imported_filter = (
        Trade.cdu_id == cdu_id,
        Trade.trade_date.in_(import_dates),
        Trade.is_active == True,  # noqa: E712
        Trade.is_manual == False,  # noqa: E712
        Trade.is_synthetic == False,  # noqa: E712
    )
    old_trade_ids = db.execute(select(Trade.id).where(*imported_filter)).scalars().all()
    if old_trade_ids:
        db.execute(delete(CashMovement).where(
            CashMovement.related_trade_id.in_(old_trade_ids),
            CashMovement.is_manual == False,  # noqa: E712
        ))
        db.execute(delete(BondLot).where(BondLot.open_trade_id.in_(old_trade_ids)))
        # A REPO lot opened by an older file keeps living when only its
        # closing leg is re-imported: detach the close instead of deleting.
        db.execute(delete(RepoLot).where(RepoLot.open_trade_id.in_(old_trade_ids)))
        db.execute(update(RepoLot).where(
            RepoLot.close_trade_id.in_(old_trade_ids),
        ).values(close_trade_id=None, is_closed=False))
        db.execute(delete(DepositLot).where(DepositLot.open_trade_id.in_(old_trade_ids)))
        db.execute(update(DepositLot).where(
            DepositLot.close_trade_id.in_(old_trade_ids),
        ).values(close_trade_id=None, is_closed=False, close_date=None))
    db.execute(
        update(Trade)
        .where(*imported_filter)
        .values(is_active=False, updated_at=datetime.utcnow())
    )
    db.flush()

    refs = ReferenceBook(db)
    counters = {
        "trades": 0, "bond_lots": 0, "repo_lots": 0,
        "deposit_lots": 0, "cash_movements": 0,
        "references_created": 0, "references_incomplete": 0,
        "fx_rates_missing": 0, "face_value_derived": 0,
    }
    for pr in parsed.rows:
        f = pr.fields
        op = f.get("operation_type", "OTHER")
        if op == "REPO_HEADER":
            continue
        deal = str(f.get("deal_number") or "").strip()
        if not deal:
            deal = f"{f.get('order_number') or 'UNK'}_{pr.raw_index}"
        row_trade_date = (
            _d(f.get("trade_date")) or _d(f.get("trading_date")) or trade_date
        )
        value_date = _d(f.get("settlement_date")) or row_trade_date
        existing = db.execute(select(Trade).where(
            Trade.cdu_id == cdu_id, Trade.deal_id == deal,
            Trade.operation_type == op, Trade.trade_date == row_trade_date,
            Trade.is_manual == False,  # noqa: E712
        )).scalars().first()
        volume = _f(f.get("volume"))
        price = _f(f.get("price"))
        accrued_volume = _f(f.get("accrued_interest_volume"))
        settlement_amount = _f(f.get("placement_amount"))
        code = str(f.get("instrument_code") or "").strip()
        isin = refs.isin_for(code) if code else None
        currency = str(f.get("currency_code") or "KZT").strip().upper()[:8]
        repo_sum = _f(f.get("repo_sum"))
        repo_buyback_sum = _f(f.get("repo_buyback_sum"))
        quantity = _f(f.get("securities_to_execute")) or _f(f.get("lots"))

        # Face value (номинал) of the deal.  «Объем по номиналу» is not
        # reliable for every instrument (e.g. KZ_23_3504: 53 621 for 53 621
        # securities), so cross-check it with Объем ≈ номинал × цена / 100.
        nominal = _f(f.get("nominal_volume"))
        face = nominal
        if op in ("BUY", "SELL") and volume and price:
            derived = volume * 100.0 / price
            if not nominal or abs(nominal * price / 100.0 - volume) > max(1.0, abs(volume) * 0.01):
                ref = refs.get(isin or code)
                if quantity and ref is not None and ref.nominal:
                    face = quantity * float(ref.nominal)
                else:
                    face = derived
                counters["face_value_derived"] += 1

        # Cash amount: BP 6.2.2 — Amount = «Сумма» (with НКД) × (−1) for a
        # purchase; «Объем» is the clean volume and excludes accrued interest.
        if op in ("BUY", "SELL"):
            gross = settlement_amount
            if gross is None and volume is not None:
                gross = volume + (accrued_volume or 0.0)
            amount = gross or 0.0
        elif op == "REPO_OPEN":
            amount = repo_sum or settlement_amount or volume or 0.0
        elif op == "REPO_CLOSE":
            amount = repo_buyback_sum or settlement_amount or volume or 0.0
        else:
            amount = settlement_amount or volume or 0.0
        if op in ("BUY", "REPO_OPEN", "FX_BUY", "DEPOSIT_OPEN"):
            amount = -abs(amount)
        elif op in ("SELL", "REPO_CLOSE", "FX_SELL", "DEPOSIT_CLOSE"):
            amount = abs(amount)
        amount_kzt, fx_rate = _amount_to_kzt(db, amount, currency, value_date)
        if currency != "KZT" and fx_rate is None:
            counters["fx_rates_missing"] += 1

        if op.startswith("REPO"):
            category = "REVERSE_REPO"
        elif op.startswith("DEPOSIT"):
            category = "DEPOSIT"
        elif op.startswith("FX"):
            category = "CASH"
        else:
            category = refs.category(isin or code, f.get("instrument_category"), ticker=code)

        commission_clearing = _f(f.get("commission_clearing"))
        commission_trading = _f(f.get("commission_trading"))
        kw = dict(
            cdu_id=cdu_id, deal_id=deal,
            trade_date=row_trade_date, value_date=value_date,
            operation_type=op, instrument_code=code or None,
            isin=isin,
            instrument_kind=(
                "REPO" if op.startswith("REPO") else "DEPOSIT" if op.startswith("DEPOSIT")
                else "FX" if op.startswith("FX") else "BOND"
            ),
            instrument_category=category or "OTHER",
            direction="Покупка" if "BUY" in op or "OPEN" in op else ("Продажа" if "SELL" in op or "CLOSE" in op else None),
            amount_kzt=amount_kzt,
            amount_ccy=amount,
            fx_rate=fx_rate,
            quantity=quantity, face_value=face,
            clean_price=price if op in ("BUY", "SELL") else None,
            accrued_interest=accrued_volume,
            ytm=_f(f.get("yield_pct")),
            currency=currency, repo_rate_pct=_f(f.get("repo_rate_pct")),
            repo_open_price=_f(f.get("placement_price_kzt")) if op.startswith("REPO") else None,
            repo_close_price=_f(f.get("redemption_price_kzt")) if op.startswith("REPO") else None,
            repo_term_days=f.get("repo_term_days"),
            repo_buyback_sum=repo_buyback_sum,
            commission_clearing=commission_clearing,
            commission_kase=commission_trading,
            commission_total=_f(f.get("commission_total")),
            # Initial price-reconciliation state: capture the original CDU
            # price; ``price_final`` mirrors it until ``apply_kase_prices_to_trades``
            # has had a chance to compare it with KASE.
            price_original=price,
            price_final=price,
            price_flag=False,
            source_doc_id=source_doc_id,
            is_active=True,
            is_manual=False,
            is_synthetic=False,
            workflow_status="APPROVED",
            approved_by="SYSTEM",
            approved_at=datetime.utcnow(),
            created_by=uploaded_by, created_at=datetime.utcnow(),
            source_row_idx=pr.raw_index,
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
        if amount:
            db.add(CashMovement(
                cdu_id=cdu_id,
                operation_date=trade_obj.value_date or row_trade_date,
                amount=amount,
                amount_kzt=amount_kzt,
                currency=currency,
                movement_type=_cash_movement_type(op),
                basis=f"Автоматически по сделке {deal}",
                related_trade_id=trade_obj.id,
                related_isin=isin or code or None,
                source_doc_id=source_doc_id,
                is_manual=False,
                workflow_status="APPROVED",
                approved_by="SYSTEM",
                approved_at=datetime.utcnow(),
                created_by=uploaded_by or "SYSTEM",
            ))
            counters["cash_movements"] += 1
        if op in ("BUY", "SELL") and code:
            created, complete = _ensure_instrument_reference(db, isin or code)
            counters["references_created"] += int(created)
            counters["references_incomplete"] += int(not complete)
        if op == "BUY" and code and face:
            db.add(BondLot(
                cdu_id=cdu_id, isin=isin or code, instrument_code=code,
                category=category or "OTHER",
                trade_date=row_trade_date, valuation_date=kw.get("value_date") or row_trade_date,
                settlement_date=value_date,
                quantity_initial=quantity or 0.0, quantity_current=quantity or 0.0,
                face_value_initial=face, face_value_current=face,
                purchase_price=price, open_trade_id=trade_obj.id,
                source_doc_id=source_doc_id,
            ))
            counters["bond_lots"] += 1
        if op in ("REPO_OPEN", "REPO_CLOSE"):
            repo_face = repo_sum if op == "REPO_OPEN" else (repo_buyback_sum or volume or nominal)
            master = str(f.get("repo_master_deal") or "").strip()
            if master.endswith(".0"):
                master = master[:-2]
            order_key = str(f.get("order_number") or deal).strip()
            if order_key.endswith(".0"):
                order_key = order_key[:-2]
            _repo(db, trade_obj, cdu_id, code, op, repo_face,
                  _f(f.get("repo_rate_pct")), f.get("repo_term_days"),
                  row_trade_date, source_doc_id,
                  master if master.isdigit() else order_key,
                  buyback=repo_buyback_sum,
                  fallback_key=order_key if master.isdigit() else None)
            counters["repo_lots"] += 1
        if op in ("DEPOSIT_OPEN", "DEPOSIT_CLOSE"):
            _dep(db, trade_obj, cdu_id, op, abs(amount) or volume,
                 _f(f.get("repo_rate_pct")) or _f(f.get("yield_pct")),
                 row_trade_date, source_doc_id)
            counters["deposit_lots"] += 1
    if commit:
        db.commit()
    else:
        db.flush()
    if counters["references_incomplete"]:
        parsed.warnings.append(
            f"Для {counters['references_incomplete']} выпуск(ов) KASE не вернула "
            "полные реквизиты: созданы записи справочника для ручного дополнения."
        )
    if counters["fx_rates_missing"]:
        parsed.warnings.append(
            f"Для {counters['fx_rates_missing']} валютных сделок не найден курс на дату расчётов; "
            "сумма в тенге временно рассчитана по курсу 1."
        )
    if counters["face_value_derived"]:
        parsed.warnings.append(
            f"Для {counters['face_value_derived']} сделок «Объем по номиналу» не согласуется с объёмом и ценой — "
            "номинал рассчитан как количество × номинал справочника (или объём / цена × 100)."
        )
    logger.info(f"Trade import: {counters} cdu={cdu_id} date={trade_date}")
    return counters


def _cash_movement_type(operation_type: str) -> str:
    return {
        "BUY": "SECURITY_PURCHASE",
        "SELL": "SECURITY_SALE",
        "REPO_OPEN": "REPO_OPEN",
        "REPO_CLOSE": "REPO_CLOSE",
        "COUPON": "COUPON",
        "REDEMPTION": "REDEMPTION",
        "DEPOSIT_OPEN": "DEPOSIT_OPEN",
        "DEPOSIT_CLOSE": "DEPOSIT_CLOSE",
        "FX_BUY": "FX_BUY",
        "FX_SELL": "FX_SELL",
    }.get(operation_type, "OTHER")


def _ensure_instrument_reference(db: Session, identifier: str) -> tuple[bool, bool]:
    """Create a non-duplicating reference entry from available KASE data.

    The online refresh remains the authoritative enrichment path.  During a
    Trade Report import we use already loaded KASE data immediately; when it
    is unavailable we retain a minimal, clearly sourced record for authorised
    manual completion instead of silently losing the instrument.
    """
    key = identifier.strip()
    ref = db.execute(select(InstrumentReference).where(or_(
        InstrumentReference.isin == key,
        InstrumentReference.ticker_kase == key,
    ))).scalars().first()
    quote = db.execute(select(KasePrice).where(or_(
        KasePrice.isin == key,
        KasePrice.instrument_code == key,
    )).order_by(KasePrice.trade_date.desc())).scalars().first()
    if ref:
        if quote:
            ref.isin = quote.isin or ref.isin or key
            ref.ticker_kase = quote.instrument_code or ref.ticker_kase or key
            ref.instrument_name = quote.instrument_name or ref.instrument_name
            ref.issuer = (
                quote.org_name_ru or quote.org_name_en or quote.org_name_kz or ref.issuer
            )
            ref.security_type = (
                quote.fin_sec_ru or quote.fin_sec_en or quote.fin_sec_kz
                or quote.sec_type or ref.security_type
            )
            ref.quotation_type = (
                quote.unit_ru or quote.unit_en or quote.unit_kz or ref.quotation_type
            )
            ref.source = "KASE_MARKET"
            ref.source_updated_at = datetime.utcnow()
            ref.updated_by = "SYSTEM"
            db.flush()
        return False, bool(ref.instrument_name and ref.issuer)
    ref = InstrumentReference(
        isin=(quote.isin if quote and quote.isin else key),
        ticker_kase=(quote.instrument_code if quote else key),
        instrument_name=(quote.instrument_name if quote else None),
        issuer=(
            quote.org_name_ru or quote.org_name_en or quote.org_name_kz
            if quote else None
        ),
        security_type=(
            quote.fin_sec_ru or quote.fin_sec_en or quote.fin_sec_kz or quote.sec_type
            if quote else None
        ),
        quotation_type=(quote.unit_ru or quote.unit_en or quote.unit_kz if quote else None),
        currency="KZT",
        source="KASE_MARKET" if quote else "TRADE_REPORT_PENDING_ENRICHMENT",
        source_updated_at=datetime.utcnow(),
        updated_by="SYSTEM",
    )
    db.add(ref)
    db.flush()
    return True, bool(ref.instrument_name and ref.issuer)


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
    from .number_utils import parse_kz_date
    return parse_kz_date(v)


def _amount_to_kzt(
    db: Session, amount: float, currency: str, operation_date: date,
) -> tuple[float, Optional[float]]:
    code = (currency or "KZT").upper()
    if code == "KZT":
        return amount, 1.0
    fx = db.execute(select(FXRate).where(
        FXRate.currency == code,
        FXRate.rate_date <= operation_date,
    ).order_by(FXRate.rate_date.desc())).scalars().first()
    if fx is None:
        return amount, None
    rate = float(fx.rate or 1.0)
    return amount * rate, rate


def _repo(db, trade, cdu_id, code, op, face, rate, term, td, doc_id, deal_id, *, buyback=None,
          fallback_key=None):
    """Create/close the REPO lot.

    The legs are linked by the head deal number («Витринная сделка»); files
    without that column (and lots created by older versions) fall back to the
    order number («Заявка №») plus the instrument.

    The opening leg already carries the buy-back amount and term, so the lot
    knows its expected close date even before the closing leg is imported.
    """
    if op == "REPO_OPEN":
        open_date = trade.value_date or td
        db.flush()
        # the closing leg may come first in the file — attach to its lot
        orphan = None
        for key in [k for k in (deal_id, fallback_key) if k]:
            orphan = db.execute(select(RepoLot).where(
                RepoLot.cdu_id == cdu_id, RepoLot.instrument_code == code,
                RepoLot.deal_id == key, RepoLot.open_trade_id.is_(None),
                RepoLot.close_trade_id.is_not(None),
            )).scalars().first()
            if orphan:
                break
        if orphan is not None:
            orphan.deal_id = deal_id
            orphan.isin = orphan.isin or trade.isin
            orphan.trade_date = td
            orphan.valuation_date = open_date
            orphan.face_value = face or 0.0
            orphan.close_value = orphan.close_value or buyback
            orphan.repo_rate_pct = rate
            orphan.term_days = term
            orphan.open_trade_id = trade.id
            orphan.source_doc_id = doc_id
            return
        db.add(RepoLot(
            cdu_id=cdu_id, instrument_code=code, isin=trade.isin,
            deal_id=deal_id,
            trade_date=td, valuation_date=open_date,
            close_date=(open_date + timedelta(days=int(term))) if term else None,
            face_value=face or 0.0, close_value=buyback,
            repo_rate_pct=rate, term_days=term,
            open_trade_id=trade.id, source_doc_id=doc_id,
        ))
    else:
        db.flush()
        ex = None
        for key in [k for k in (deal_id, fallback_key) if k]:
            ex = db.execute(select(RepoLot).where(
                RepoLot.cdu_id == cdu_id, RepoLot.instrument_code == code,
                RepoLot.deal_id == key,
                RepoLot.close_trade_id.is_(None),
            ).order_by(RepoLot.trade_date.asc())).scalars().first()
            if ex:
                break
        close_dt = trade.value_date or td
        if ex:
            ex.close_date = close_dt
            ex.close_value = face or ex.close_value or ex.face_value
            ex.close_trade_id = trade.id
            ex.is_closed = True
        else:
            db.add(RepoLot(
                cdu_id=cdu_id, instrument_code=code, isin=trade.isin,
                deal_id=deal_id,
                trade_date=td, valuation_date=td, close_date=close_dt,
                face_value=face or 0.0, close_value=face or 0.0,
                repo_rate_pct=rate, close_trade_id=trade.id, source_doc_id=doc_id,
                is_closed=True,
            ))


def _dep(db, trade, cdu_id, op, principal, rate, td, doc_id):
    if op == "DEPOSIT_OPEN":
        db.add(DepositLot(
            cdu_id=cdu_id, deal_id=trade.deal_id, trade_date=td,
            valuation_date=trade.value_date or td,
            principal=principal or 0.0, interest_rate_pct=rate,
            open_trade_id=trade.id, source_doc_id=doc_id,
        ))
    else:
        close_dt = trade.value_date or td
        candidates = db.execute(select(DepositLot).where(
            DepositLot.cdu_id == cdu_id,
            DepositLot.close_trade_id.is_(None),
            DepositLot.valuation_date <= close_dt,
        ).order_by(DepositLot.trade_date.asc())).scalars().all()
        # Prefer the deposit with the same deal id, then the one whose
        # principal is closest to the returned amount (principal + interest).
        ex = next((c for c in candidates if trade.deal_id and c.deal_id == trade.deal_id), None)
        if ex is None and candidates:
            ex = min(candidates, key=lambda c: abs((principal or 0.0) - (c.principal or 0.0)))
        if ex:
            ex.close_date = close_dt
            ex.close_trade_id = trade.id
            ex.is_closed = True
        else:
            db.add(DepositLot(
                cdu_id=cdu_id, deal_id=trade.deal_id, trade_date=td, valuation_date=td,
                close_date=close_dt, principal=principal or 0.0,
                interest_rate_pct=rate,
                close_trade_id=trade.id, source_doc_id=doc_id, is_closed=True,
            ))


def import_single_trade_report_xlsx(
    db: Session, file_path: str, *, uploaded_by: Optional[str] = None,
    source_doc_id: Optional[int] = None,
) -> Dict[str, Any]:
    from .trade_report_parser import TradeReportParser
    parsed = TradeReportParser(file_path).parse()
    if parsed.cdu_name is None:
        return {"error": "ЧДУ не удалось определить", "warnings": parsed.warnings}
    counters = import_trades_from_parsed(db, parsed, uploaded_by=uploaded_by, source_doc_id=source_doc_id)
    return {"cdu_name": parsed.cdu_name,
            "trade_date": parsed.trade_date.isoformat() if parsed.trade_date else None,
            **counters, "warnings": parsed.warnings}
