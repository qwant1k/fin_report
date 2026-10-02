"""Coupon and redemption events — business process 6.1.6–6.1.7, 7.1.7–7.1.10.

For every CDU and every bond held at the end of T−1 (portfolio engine):

* **Coupon** — when T is a coupon date of the issue (schedule from the
  Справочник: start of circulation, frequency, maturity).  Amount = the full
  coupon of the period (RR «Accrued interest (debet)») computed with the
  issue day-count basis (30/360 = 30E/360, actual/360, actual/365,
  actual/actual split by calendar year as described in the process).
* **Redemption** — when maturity = T: face value of the position.  The coupon
  of the last period is the coupon event of the same day (no double count).

Settlement:
* ГЦБ — cash on T (Value date = T, synthetic Trade + cash movement).
* Агентские / МФО / Ин. ЦБ — the payment window ends after T (KASE schedule),
  so the amount is booked as a receivable («Сумма вознаграждения в пути по
  ISIN …» / «Сумма погашения в пути по ISIN …») and becomes cash when the
  receivable is repaid.  No cash is invented before it arrives.

Idempotent: re-running T updates the same synthetic trades / events / AR and
deactivates synthetic rows of T that are no longer justified (e.g. the bond
was sold before the record date).  Historical Risk Report lots are never
modified.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.db_models import (
    AccountReceivable,
    CashMovement,
    CDU,
    CouponEvent,
    RedemptionEvent,
    Trade,
)
from services.portfolio import bond_math as bm
from services.portfolio.engine import MarketData, build_portfolio
from services.portfolio.reference import ReferenceBook

CASH_ON_T_CATEGORIES = {"GOV_BONDS"}


def _day_count(start: date, end: date, base: str) -> float:
    """Kept for backward compatibility (used by older callers/tests)."""
    return bm.day_count(start, end, bm.normalize_basis(base))


def _calc_coupon_amount(
    face_value: float,
    coupon_rate_pct: float,
    days: float,
    base_days: float = 360.0,
) -> float:
    return face_value * (coupon_rate_pct / 100.0) * (days / base_days)


def _upsert_synthetic_trade(
    db: Session,
    *,
    cdu_id: int,
    trade_date: date,
    value_date: date,
    operation_type: str,
    isin: str,
    instrument_category: str,
    amount_kzt: float,
    amount_ccy: Optional[float] = None,
    currency: str = "KZT",
    quantity: Optional[float] = None,
    face_value: Optional[float] = None,
    notes: str = "",
    instrument_code: Optional[str] = None,
    book_cash: bool = True,
) -> Trade:
    """Idempotent synthetic trade upsert (key: CDU, T, operation, ISIN)."""
    existing = db.execute(select(Trade).where(
        Trade.cdu_id == cdu_id,
        Trade.trade_date == trade_date,
        Trade.operation_type == operation_type,
        Trade.isin == isin,
        Trade.is_synthetic == True,  # noqa: E712
    )).scalars().first()
    values = dict(
        value_date=value_date,
        amount_kzt=amount_kzt,
        amount_ccy=amount_ccy,
        currency=currency,
        quantity=quantity,
        face_value=face_value,
        instrument_kind="BOND",
        instrument_category=instrument_category,
        instrument_code=instrument_code,
        notes=notes,
        description=notes,
        workflow_status="APPROVED",
        approved_by="SYSTEM",
        approved_at=datetime.utcnow(),
        is_active=True,
    )
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
        trade = existing
    else:
        trade = Trade(
            cdu_id=cdu_id, trade_date=trade_date, operation_type=operation_type,
            isin=isin, is_synthetic=True, is_manual=False, created_by="SYSTEM",
            direction="Продажа", **values,
        )
        db.add(trade)
    db.flush()
    _upsert_cash_movement(db, trade, active=book_cash)
    return trade


def _upsert_cash_movement(db: Session, trade: Trade, *, active: bool = True) -> None:
    movement = db.execute(select(CashMovement).where(
        CashMovement.related_trade_id == trade.id,
    )).scalars().first()
    values = {
        "cdu_id": trade.cdu_id,
        "operation_date": trade.value_date,
        "amount": trade.amount_ccy if trade.amount_ccy is not None else trade.amount_kzt,
        "amount_kzt": trade.amount_kzt,
        "currency": trade.currency,
        "movement_type": trade.operation_type,
        "basis": trade.notes or f"Автоматически по операции {trade.operation_type}",
        "related_isin": trade.isin,
        "is_manual": False,
        "workflow_status": "APPROVED",
        "is_active": bool(active and trade.is_active),
        "approved_by": "SYSTEM",
        "created_by": "SYSTEM",
    }
    if movement:
        for key, value in values.items():
            setattr(movement, key, value)
    elif active:
        db.add(CashMovement(**values, related_trade_id=trade.id))


def _upsert_ar(
    db: Session,
    *,
    cdu_id: int,
    record_date: date,
    isin: str,
    amount: float,
    currency: str,
    related_event_type: str,
    related_trade_id: int,
    due_date: Optional[date] = None,
    amount_kzt: Optional[float] = None,
    description: Optional[str] = None,
) -> AccountReceivable:
    existing = db.execute(select(AccountReceivable).where(
        AccountReceivable.cdu_id == cdu_id,
        AccountReceivable.isin == isin,
        AccountReceivable.record_date == record_date,
        AccountReceivable.related_event_type == related_event_type,
        AccountReceivable.is_manual == False,  # noqa: E712
    )).scalars().first()
    kzt = amount_kzt if amount_kzt is not None else amount
    if existing:
        existing.amount = amount
        existing.amount_kzt = kzt
        existing.currency = currency
        existing.balance_currency = amount if currency != "KZT" else None
        existing.balance_kzt = kzt
        existing.due_date = due_date
        existing.related_trade_id = related_trade_id
        existing.description = description or existing.description
        existing.is_active = True
        if existing.status not in ("CLOSED", "PARTIAL"):
            existing.status = "OPEN"
        db.flush()
        return existing

    ar = AccountReceivable(
        cdu_id=cdu_id,
        record_date=record_date,
        isin=isin,
        amount=amount,
        amount_kzt=kzt,
        currency=currency,
        balance_currency=amount if currency != "KZT" else None,
        balance_kzt=kzt,
        due_date=due_date,
        description=description,
        related_event_type=related_event_type,
        related_trade_id=related_trade_id,
        status="OPEN",
        workflow_status="APPROVED",
        is_manual=False,
        is_active=True,
        created_by="SYSTEM",
        approved_by="SYSTEM",
        notes="Ожидается выписка",
    )
    db.add(ar)
    db.flush()
    return ar


def _holdings_before(db: Session, cdu_id: int, target_date: date, refs: ReferenceBook,
                     market: MarketData) -> Dict[str, dict]:
    """Face value per ISIN held at the end of T−1 (record date)."""
    state = build_portfolio(db, cdu_id, target_date - timedelta(days=1), refs=refs, market=market)
    out: Dict[str, dict] = {}
    for lot in state.bonds:
        if lot.face_value <= 0.005:
            continue
        row = out.setdefault(lot.isin, {
            "face": 0.0, "category": lot.category, "currency": lot.currency,
            "ticker": lot.ticker,
        })
        row["face"] += lot.face_value
    return out


def _fx(db: Session, currency: str, on: date) -> float:
    if (currency or "KZT").upper() == "KZT":
        return 1.0
    from models.db_models import FXRate
    row = db.execute(select(FXRate).where(
        FXRate.currency == currency.upper(), FXRate.rate_date <= on,
    ).order_by(FXRate.rate_date.desc())).scalars().first()
    return float(row.rate) if row and row.rate else 1.0


def run_daily_auto_events(db: Session, target_date: date) -> Dict[str, Dict[str, int]]:
    """Generate coupon and redemption events of ``target_date`` for all CDUs."""
    refs = ReferenceBook(db)
    market = MarketData(db, target_date - timedelta(days=1))
    coupons = {"events": 0, "trades": 0, "ar_created": 0, "skipped": 0, "deactivated": 0}
    redemptions = {"events": 0, "trades": 0, "ar_created": 0, "coupon_trades": 0, "skipped": 0, "deactivated": 0}
    touched: set[int] = set()

    for cdu in db.query(CDU).filter_by(is_active=True).all():
        holdings = _holdings_before(db, cdu.id, target_date, refs, market)
        for isin, h in holdings.items():
            ref = refs.get(isin) or refs.get(h.get("ticker"))
            if ref is None or not ref.maturity_date:
                continue
            face = h["face"]
            category = h["category"]
            currency = (h["currency"] or "KZT").upper()
            fx = _fx(db, currency, target_date)
            cash_now = category in CASH_ON_T_CATEGORIES
            rate = bm.rate_fraction(ref.coupon_rate_pct) or 0.0
            freq = int(ref.frequency) if ref.frequency else None
            basis = bm.normalize_basis(ref.base)

            # ── coupon ──
            # the schedule of the reference book (if maintained) has priority
            schedule = refs.schedule(isin) or refs.schedule(h.get("ticker"))
            sched_hit = None
            if schedule:
                from services.portfolio import coupon_schedule as cs
                sched_hit = cs.coupon_on(schedule, target_date, face, basis,
                                         start=ref.start_date, nominal=ref.nominal)
            is_coupon_day = (sched_hit is not None) if schedule else (
                rate > 0 and freq and bm.is_coupon_date(target_date, ref.maturity_date, freq, ref.start_date))
            if is_coupon_day:
                if sched_hit is not None:
                    amount, prev, sched_rate = sched_hit
                    rate = sched_rate if sched_rate is not None else rate
                else:
                    prev = bm.previous_coupon_date(target_date, ref.maturity_date, freq, ref.start_date)
                    amount = bm.period_coupon_amount(face, rate, prev, target_date, basis) if prev else None
                if prev is None or amount is None:
                    coupons["skipped"] += 1
                else:
                    trade = _upsert_synthetic_trade(
                        db, cdu_id=cdu.id, trade_date=target_date, value_date=target_date,
                        operation_type="COUPON", isin=isin, instrument_category=category,
                        amount_kzt=amount * fx, amount_ccy=amount, currency=currency,
                        face_value=face, instrument_code=h.get("ticker"),
                        notes=f"Купон {isin}: {face:,.2f} × {rate:.4%} за {prev:%d.%m.%Y}–{target_date:%d.%m.%Y} ({ref.base or '30/360'})",
                        book_cash=cash_now,
                    )
                    touched.add(trade.id)
                    coupons["trades"] += 1
                    ev = db.execute(select(CouponEvent).where(
                        CouponEvent.cdu_id == cdu.id, CouponEvent.isin == isin,
                        CouponEvent.event_date == target_date,
                    )).scalars().first()
                    if ev is None:
                        ev = CouponEvent(cdu_id=cdu.id, isin=isin, event_date=target_date,
                                         expected_amount=amount, status="PLANNED")
                        db.add(ev)
                        coupons["events"] += 1
                    ev.expected_amount = amount
                    ev.coupon_rate_pct = rate * 100
                    ev.base = ref.base
                    ev.value_date = target_date
                    ev.trade_id = trade.id
                    if not cash_now:
                        ar = _upsert_ar(
                            db, cdu_id=cdu.id, record_date=target_date, isin=isin,
                            amount=amount, amount_kzt=amount * fx, currency=currency,
                            related_event_type="COUPON", related_trade_id=trade.id,
                            description=f"Сумма вознаграждения в пути по ISIN {isin}",
                        )
                        ev.ar_id = ar.id
                        ev.status = "PENDING"
                        coupons["ar_created"] += 1
                    else:
                        ev.status = "PAID"

            # ── redemption ──
            if ref.maturity_date == target_date:
                trade = _upsert_synthetic_trade(
                    db, cdu_id=cdu.id, trade_date=target_date, value_date=target_date,
                    operation_type="REDEMPTION", isin=isin, instrument_category=category,
                    amount_kzt=face * fx, amount_ccy=face, currency=currency,
                    face_value=face, instrument_code=h.get("ticker"),
                    notes=f"Погашение {isin}: номинал {face:,.2f}",
                    book_cash=cash_now,
                )
                touched.add(trade.id)
                redemptions["trades"] += 1
                ev = db.execute(select(RedemptionEvent).where(
                    RedemptionEvent.cdu_id == cdu.id, RedemptionEvent.isin == isin,
                    RedemptionEvent.event_date == target_date,
                )).scalars().first()
                if ev is None:
                    ev = RedemptionEvent(cdu_id=cdu.id, isin=isin, event_date=target_date,
                                         face_value=face, status="PLANNED")
                    db.add(ev)
                    redemptions["events"] += 1
                ev.face_value = face
                ev.value_date = target_date
                ev.trade_id = trade.id
                coupon_trade = db.execute(select(Trade).where(
                    Trade.cdu_id == cdu.id, Trade.trade_date == target_date,
                    Trade.operation_type == "COUPON", Trade.isin == isin,
                    Trade.is_synthetic == True,  # noqa: E712
                    Trade.is_active == True,  # noqa: E712
                )).scalars().first()
                if coupon_trade is not None:
                    ev.coupon_trade_id = coupon_trade.id
                    ev.coupon_amount = coupon_trade.amount_ccy
                    redemptions["coupon_trades"] += 1
                if not cash_now:
                    ar = _upsert_ar(
                        db, cdu_id=cdu.id, record_date=target_date, isin=isin,
                        amount=face, amount_kzt=face * fx, currency=currency,
                        related_event_type="REDEMPTION", related_trade_id=trade.id,
                        description=f"Сумма погашения в пути по ISIN {isin}",
                    )
                    ev.ar_id = ar.id
                    ev.status = "PENDING"
                    redemptions["ar_created"] += 1
                else:
                    ev.status = "PAID"

    # Synthetic rows of T that are no longer justified → deactivate.
    stale = db.execute(select(Trade).where(
        Trade.trade_date == target_date,
        Trade.is_synthetic == True,  # noqa: E712
        Trade.is_active == True,  # noqa: E712
        Trade.operation_type.in_(("COUPON", "REDEMPTION")),
    )).scalars().all()
    for trade in stale:
        if trade.id in touched:
            continue
        trade.is_active = False
        _upsert_cash_movement(db, trade, active=False)
        for ar in db.execute(select(AccountReceivable).where(
            AccountReceivable.related_trade_id == trade.id,
            AccountReceivable.is_manual == False,  # noqa: E712
        )).scalars():
            ar.is_active = False
        (coupons if trade.operation_type == "COUPON" else redemptions)["deactivated"] += 1

    db.commit()
    logger.info(f"Auto events for {target_date}: coupons={coupons} redemptions={redemptions}")
    return {"coupons": coupons, "redemptions": redemptions}


def generate_coupon_trades(db: Session, target_date: date) -> Dict[str, int]:
    return run_daily_auto_events(db, target_date)["coupons"]


def generate_redemption_trades(db: Session, target_date: date) -> Dict[str, int]:
    return run_daily_auto_events(db, target_date)["redemptions"]


def run_auto_events_range(db: Session, date_from: date, date_to: date) -> Dict[str, int]:
    """Catch-up helper: run the events for every calendar day of a period."""
    totals = {"days": 0, "coupons": 0, "redemptions": 0}
    d = date_from
    while d <= date_to:
        res = run_daily_auto_events(db, d)
        totals["days"] += 1
        totals["coupons"] += res["coupons"]["trades"]
        totals["redemptions"] += res["redemptions"]["trades"]
        d += timedelta(days=1)
    return totals
