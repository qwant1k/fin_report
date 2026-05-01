"""Auto-coupon and auto-redemption engine — Phase C1/C2.

Rules:
  - last_coupon_date = T → synthetic Trade "COUPON" + AR if value_date > T
  - maturity_date = T → synthetic Trade "REDEMPTION" + AR
    If coupon_rate > 0 → separate Trade "COUPON" from last_coupon_date to maturity
      with day-count basis (30/360, act/360, act/act).

Idempotent: upsert by (cdu_id, isin, event_date, operation_type, is_synthetic=True).
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session
from models.db_models import (
    AccountReceivable,
    BondLot,
    CDU,
    CouponEvent,
    InstrumentReference,
    RedemptionEvent,
    Trade,
)


def _day_count(start: date, end: date, base: str) -> float:
    if base in ("30/360", "30/360E"):
        # 30/360 bond basis
        d1 = min(start.day, 30)
        d2 = end.day if d1 < 30 else min(end.day, 30)
        return (360 * (end.year - start.year)
                + 30 * (end.month - start.month)
                + (d2 - d1))
    if base in ("act/360", "ACT/360"):
        return (end - start).days
    if base in ("act/act", "ACT/ACT"):
        # Simplified: actual days in year
        year_days = 366 if (start.year % 4 == 0 and (start.year % 100 != 0 or start.year % 400 == 0)) else 365
        return (end - start).days
    # Default fallback
    return (end - start).days


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
) -> Trade:
    """Idempotent synthetic trade upsert."""
    existing = db.execute(select(Trade).where(
        Trade.cdu_id == cdu_id,
        Trade.trade_date == trade_date,
        Trade.operation_type == operation_type,
        Trade.isin == isin,
        Trade.is_synthetic == True,
    )).scalars().first()
    if existing:
        existing.value_date = value_date
        existing.amount_kzt = amount_kzt
        existing.amount_ccy = amount_ccy
        existing.currency = currency
        existing.quantity = quantity
        existing.face_value = face_value
        existing.instrument_category = instrument_category
        existing.notes = notes
        db.flush()
        return existing

    t = Trade(
        cdu_id=cdu_id,
        trade_date=trade_date,
        value_date=value_date,
        operation_type=operation_type,
        instrument_kind="BOND",
        instrument_category=instrument_category,
        isin=isin,
        amount_kzt=amount_kzt,
        amount_ccy=amount_ccy,
        currency=currency,
        quantity=quantity,
        face_value=face_value,
        is_synthetic=True,
        notes=notes,
    )
    db.add(t)
    db.flush()
    return t


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
) -> AccountReceivable:
    existing = db.execute(select(AccountReceivable).where(
        AccountReceivable.cdu_id == cdu_id,
        AccountReceivable.isin == isin,
        AccountReceivable.record_date == record_date,
        AccountReceivable.related_event_type == related_event_type,
    )).scalars().first()
    if existing:
        existing.amount = amount
        existing.currency = currency
        existing.balance_currency = amount
        existing.due_date = due_date
        existing.related_trade_id = related_trade_id
        existing.status = "OPEN"
        db.flush()
        return existing

    ar = AccountReceivable(
        cdu_id=cdu_id,
        record_date=record_date,
        isin=isin,
        amount=amount,
        currency=currency,
        balance_currency=amount,
        balance_kzt=amount,  # simplification: KZT for KZT bonds; for USD use fx rate later
        due_date=due_date,
        related_event_type=related_event_type,
        related_trade_id=related_trade_id,
        status="OPEN",
    )
    db.add(ar)
    db.flush()
    return ar


def generate_coupon_trades(db: Session, target_date: date) -> Dict[str, int]:
    """For every ISIN with last_coupon_date == target_date, create synthetic COUPON trade + AR."""
    counters = {"events": 0, "trades": 0, "ar_created": 0, "skipped": 0}

    refs = db.execute(select(InstrumentReference).where(
        InstrumentReference.last_coupon_date == target_date,
        InstrumentReference.is_active == True,
    )).scalars().all()

    for ref in refs:
        isin = ref.isin
        # Find open lots per CDU
        lots = db.execute(select(BondLot).where(
            BondLot.isin == isin,
            BondLot.quantity_current > 0,
        )).scalars().all()

        # Group by cdu_id
        cdu_lots: Dict[int, List[BondLot]] = {}
        for lot in lots:
            cdu_lots.setdefault(lot.cdu_id, []).append(lot)

        for cdu_id, lot_list in cdu_lots.items():
            total_face = sum(l.face_value_current or 0 for l in lot_list)
            if total_face <= 0:
                continue

            # Determine coupon amount
            rate = ref.coupon_rate_pct or 0.0
            # Assume coupon period = 1 year / frequency
            freq = ref.frequency or 2
            base_str = ref.base or "30/360"
            days = _day_count(
                target_date.replace(year=target_date.year - 1) if freq == 1 else
                target_date - timedelta(days=180) if freq == 2 else
                target_date - timedelta(days=90),
                target_date,
                base_str,
            )
            base_days = 360.0 if base_str in ("30/360", "act/360") else 365.0
            coupon_amt = _calc_coupon_amount(total_face, rate, days, base_days)

            if coupon_amt <= 0:
                counters["skipped"] += 1
                continue

            # Upsert CouponEvent
            ev = db.execute(select(CouponEvent).where(
                CouponEvent.cdu_id == cdu_id,
                CouponEvent.isin == isin,
                CouponEvent.event_date == target_date,
            )).scalars().first()
            if not ev:
                ev = CouponEvent(
                    cdu_id=cdu_id,
                    isin=isin,
                    event_date=target_date,
                    expected_amount=coupon_amt,
                    coupon_rate_pct=rate,
                    base=base_str,
                    status="PLANNED",
                )
                db.add(ev)
                db.flush()
                counters["events"] += 1

            # Trade
            value_date = target_date  # KASE usually T+2, but we'll use T for simplicity; AR logic below
            trade = _upsert_synthetic_trade(
                db,
                cdu_id=cdu_id,
                trade_date=target_date,
                value_date=value_date,
                operation_type="COUPON",
                isin=isin,
                instrument_category=ref.bond_type or "OTHER",
                amount_kzt=coupon_amt,
                amount_ccy=coupon_amt,
                currency=ref.currency or "KZT",
                face_value=total_face,
                notes=f"Auto-coupon {rate}% base={base_str}",
            )
            counters["trades"] += 1

            # Update event trade_id
            ev.trade_id = trade.id

            # AR if value_date > target_date (rare for coupon, but per spec)
            if value_date > target_date:
                _upsert_ar(
                    db,
                    cdu_id=cdu_id,
                    record_date=target_date,
                    isin=isin,
                    amount=coupon_amt,
                    currency=ref.currency or "KZT",
                    related_event_type="COUPON",
                    related_trade_id=trade.id,
                    due_date=value_date,
                )
                counters["ar_created"] += 1

    db.commit()
    logger.info(f"Coupon engine for {target_date}: {counters}")
    return counters


def generate_redemption_trades(db: Session, target_date: date) -> Dict[str, int]:
    """For every ISIN with maturity_date == target_date, create REDEMPTION trade + optional COUPON + AR."""
    counters = {"events": 0, "trades": 0, "ar_created": 0, "coupon_trades": 0, "skipped": 0}

    refs = db.execute(select(InstrumentReference).where(
        InstrumentReference.maturity_date == target_date,
        InstrumentReference.is_active == True,
    )).scalars().all()

    for ref in refs:
        isin = ref.isin
        lots = db.execute(select(BondLot).where(
            BondLot.isin == isin,
            BondLot.quantity_current > 0,
        )).scalars().all()

        cdu_lots: Dict[int, List[BondLot]] = {}
        for lot in lots:
            cdu_lots.setdefault(lot.cdu_id, []).append(lot)

        for cdu_id, lot_list in cdu_lots.items():
            total_face = sum(l.face_value_current or 0 for l in lot_list)
            if total_face <= 0:
                continue

            # Mark lots as matured (optional: set quantity_current = 0)
            for lot in lot_list:
                lot.quantity_current = 0
                lot.face_value_current = 0
                lot.maturity_status = "matured"

            # Redemption Event
            ev = db.execute(select(RedemptionEvent).where(
                RedemptionEvent.cdu_id == cdu_id,
                RedemptionEvent.isin == isin,
                RedemptionEvent.event_date == target_date,
            )).scalars().first()
            if not ev:
                ev = RedemptionEvent(
                    cdu_id=cdu_id,
                    isin=isin,
                    event_date=target_date,
                    face_value=total_face,
                    status="PLANNED",
                )
                db.add(ev)
                db.flush()
                counters["events"] += 1

            # Redemption Trade (face value back)
            value_date = target_date
            trade = _upsert_synthetic_trade(
                db,
                cdu_id=cdu_id,
                trade_date=target_date,
                value_date=value_date,
                operation_type="REDEMPTION",
                isin=isin,
                instrument_category=ref.bond_type or "OTHER",
                amount_kzt=total_face,
                amount_ccy=total_face,
                currency=ref.currency or "KZT",
                face_value=total_face,
                notes="Auto-redemption",
            )
            counters["trades"] += 1
            ev.trade_id = trade.id

            # AR for redemption principal
            if value_date > target_date:
                _upsert_ar(
                    db,
                    cdu_id=cdu_id,
                    record_date=target_date,
                    isin=isin,
                    amount=total_face,
                    currency=ref.currency or "KZT",
                    related_event_type="REDEMPTION",
                    related_trade_id=trade.id,
                    due_date=value_date,
                )
                counters["ar_created"] += 1

            # Separate coupon from last_coupon_date to maturity if coupon_rate > 0
            rate = ref.coupon_rate_pct or 0.0
            if rate > 0 and ref.last_coupon_date:
                base_str = ref.base or "30/360"
                days = _day_count(ref.last_coupon_date, target_date, base_str)
                base_days = 360.0 if base_str in ("30/360", "act/360") else 365.0
                coupon_amt = _calc_coupon_amount(total_face, rate, days, base_days)

                if coupon_amt > 0:
                    cp_trade = _upsert_synthetic_trade(
                        db,
                        cdu_id=cdu_id,
                        trade_date=target_date,
                        value_date=value_date,
                        operation_type="COUPON",
                        isin=isin,
                        instrument_category=ref.bond_type or "OTHER",
                        amount_kzt=coupon_amt,
                        amount_ccy=coupon_amt,
                        currency=ref.currency or "KZT",
                        face_value=total_face,
                        notes=f"Auto-coupon on redemption {rate}% base={base_str} days={days}",
                    )
                    counters["coupon_trades"] += 1
                    ev.coupon_trade_id = cp_trade.id

                    # AR for coupon on redemption
                    if value_date > target_date:
                        _upsert_ar(
                            db,
                            cdu_id=cdu_id,
                            record_date=target_date,
                            isin=isin,
                            amount=coupon_amt,
                            currency=ref.currency or "KZT",
                            related_event_type="COUPON",
                            related_trade_id=cp_trade.id,
                            due_date=value_date,
                        )
                        counters["ar_created"] += 1

    db.commit()
    logger.info(f"Redemption engine for {target_date}: {counters}")
    return counters


def run_daily_auto_events(db: Session, target_date: date) -> Dict[str, Dict[str, int]]:
    """Run both coupon and redemption engines for target_date."""
    return {
        "coupons": generate_coupon_trades(db, target_date),
        "redemptions": generate_redemption_trades(db, target_date),
    }
