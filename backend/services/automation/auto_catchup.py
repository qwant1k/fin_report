"""Catch-up of coupon / redemption events for every date that needs them.

The daily job (18:20) generates the events of *today* only.  Data of past
periods (a Risk Report of June, Trade Reports of September uploaded in
October) would never get their coupons and redemptions — the money of a
matured note stayed «in the bond».  Before a summary is calculated, the
events of every coupon / maturity date between the first slice and the
report date are generated (idempotent), and a date is processed again only
when the data it depends on changed.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Set

from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

EVENT_DOC_TYPES = ("RISK_REPORT_XLSM", "TRADE_REPORT", "NBRK_DAILY", "NBRK_KFGD", "TONIA_COMPOUNDED", "HOLDINGS")

from models.db_models import (  # noqa: E402
    AutoEventDay,
    FXRate,
    BondLot,
    CouponSchedule,
    InstrumentReference,
    SourceDocument,
    Trade,
)
from services.portfolio import bond_math as bm


def data_stamp(db: Session) -> str:
    """Fingerprint of everything the events depend on (not the events themselves)."""
    from services.formulas import params
    params.refresh(db, force=True)
    # only documents that change holdings, reference data or rates (not certificates,
    # statements or reconciliation files — they would re-run the whole history)
    docs = db.execute(select(func.max(SourceDocument.id), func.count(SourceDocument.id)).where(
        SourceDocument.doc_type.in_(EVENT_DOC_TYPES),
    )).one()
    trades = db.execute(select(func.max(Trade.id), func.count(Trade.id), func.max(Trade.updated_at)).where(
        or_(Trade.is_synthetic.is_(False), Trade.is_synthetic.is_(None)),
        Trade.is_active.is_(True),
    )).one()
    fx = db.execute(select(func.max(FXRate.id), func.count(FXRate.id))).one()
    approved = db.execute(select(func.count(Trade.id)).where(
        or_(Trade.is_synthetic.is_(False), Trade.is_synthetic.is_(None)),
        Trade.workflow_status == "APPROVED",
    )).scalar()
    refs = db.execute(select(func.count(InstrumentReference.id),
                             func.max(InstrumentReference.updated_at))).one()
    sched = db.execute(select(func.count(CouponSchedule.id), func.max(CouponSchedule.updated_at))).one()
    return hashlib.sha1("|".join(str(x) for x in (
        *docs, *trades, approved, *fx, refs[0], refs[1], *sched,
        params.get("coupon_settlement"), params.get("float_fix_lag_days"),
    )).encode("utf-8")).hexdigest()


def _held_identifiers(db: Session) -> Set[str]:
    out: Set[str] = set()
    for isin, code in db.execute(select(BondLot.isin, BondLot.instrument_code).distinct()).all():
        for v in (isin, code):
            if v:
                out.add(v.strip().upper())
    for isin, code in db.execute(select(Trade.isin, Trade.instrument_code).where(
        Trade.operation_type.in_(("BUY", "SELL")),
    ).distinct()).all():
        for v in (isin, code):
            if v:
                out.add(v.strip().upper())
    return out


def candidate_dates(db: Session, start: date, end: date) -> List[date]:
    """Coupon and maturity dates of the securities ever held, within (start, end]."""
    held = _held_identifiers(db)
    if not held:
        return []
    from services.portfolio.reference import ReferenceBook
    refs = ReferenceBook(db)
    out: Set[date] = set()
    seen: Set[int] = set()
    for ident in held:
        ref = refs.get(ident)
        if ref is None or ref.id in seen:
            continue
        seen.add(ref.id)
        if ref.maturity_date and start < ref.maturity_date <= end:
            out.add(ref.maturity_date)
        schedule = refs.schedule(ref.isin)
        if schedule:
            dates: Iterable[date] = (r.payment_date for r in schedule)
        elif ref.maturity_date and ref.frequency:
            try:
                dates = bm.coupon_schedule(ref.start_date, ref.maturity_date, int(ref.frequency))
            except Exception:  # noqa: BLE001 — broken reference parameters
                dates = []
        else:
            dates = []
        for d in dates:
            if start < d <= end:
                out.add(d)
    return sorted(out)


def _window_start(db: Session, up_to: date) -> Optional[date]:
    """Start of the roll-forward window of ``up_to``: the earliest Risk Report
    slice used by a manager on that date (events before a slice are inside it),
    or the first deal of a manager without a slice."""
    from models.db_models import CDU
    from services.portfolio.engine import base_date_for
    starts: List[date] = []
    for cdu in db.query(CDU).filter(CDU.is_active.is_(True)).all():
        base = base_date_for(db, cdu.id, up_to)
        if base is None:
            base = db.execute(select(func.min(Trade.value_date)).where(
                Trade.cdu_id == cdu.id,
                or_(Trade.is_synthetic.is_(False), Trade.is_synthetic.is_(None)),
            )).scalar()
            if base is not None:
                base = base - timedelta(days=1)
        if base is not None:
            starts.append(base)
    return min(starts) if starts else None


def ensure_auto_events(db: Session, up_to: date) -> Dict[str, int]:
    """Generate coupon / redemption events of all dates ≤ ``up_to`` not yet processed
    with the current data.  Returns counters; never raises (logged instead)."""
    from services.automation.coupon_redemption_engine import run_daily_auto_events

    first = _window_start(db, up_to)
    if first is None or first >= up_to:
        return {"dates": 0, "processed": 0}
    stamp = data_stamp(db)
    done = {row.event_date: row for row in db.execute(select(AutoEventDay).where(
        AutoEventDay.event_date > first, AutoEventDay.event_date <= up_to,
    )).scalars()}
    dates = set(candidate_dates(db, first, up_to))
    # dates processed before with other data and dates that still hold events:
    # a coupon / maturity date that moved (new KASE schedule, corrected maturity)
    # must be run again so that its old events are deactivated
    dates.update(d for d, row in done.items() if row.data_stamp != stamp)
    dates.update(db.execute(select(Trade.trade_date).where(
        Trade.is_synthetic.is_(True), Trade.is_active.is_(True),
        Trade.operation_type.in_(("COUPON", "REDEMPTION")),
        Trade.trade_date > first, Trade.trade_date <= up_to,
    ).distinct()).scalars())
    dates = sorted(dates)
    processed = 0
    for d in dates:
        row = done.get(d)
        if row is not None and row.data_stamp == stamp:
            continue
        try:
            run_daily_auto_events(db, d)     # commits
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning(f"Auto events for {d} failed: {exc!r}")
            continue
        row = db.get(AutoEventDay, d)
        if row is None:
            db.add(AutoEventDay(event_date=d, data_stamp=stamp))
        else:
            row.data_stamp = stamp
        db.commit()
        processed += 1
    if processed:
        logger.info(f"Auto events catch-up up to {up_to}: {processed} of {len(dates)} dates processed")
    return {"dates": len(dates), "processed": processed}
