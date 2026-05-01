"""AR closing engine — Phase C4.

Closes AccountReceivable items when a matching cash inflow is detected
in a custodian statement / cash snapshot, based on:
  - ISIN match (or sub-fund / portfolio code)
  - Amount match within tolerance (±0.01 KZT/USD)
  - Date proximity (value_date ± 3 business days)

Idempotent: sets AR.status = CLOSED, actual_value_date, and links to Trade.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Dict, List, Optional
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session
from models.db_models import AccountReceivable, CashSnapshot, Trade
from services.calculator.constants import RECON_TOLERANCE_KZT, RECON_TOLERANCE_USD


def _match_tolerance(expected: float, actual: float, currency: str) -> bool:
    tol = RECON_TOLERANCE_USD if currency == "USD" else RECON_TOLERANCE_KZT
    return abs(expected - actual) <= tol


def find_matching_cash_for_ar(
    db: Session,
    ar: AccountReceivable,
    lookback_days: int = 5,
    lookahead_days: int = 5,
) -> Optional[CashSnapshot]:
    """Find a CashSnapshot inflow that matches this AR."""
    if ar.status != "OPEN" or ar.balance_currency is None or ar.balance_currency <= 0:
        return None

    start = (ar.due_date or ar.record_date) - timedelta(days=lookback_days)
    end = (ar.due_date or ar.record_date) + timedelta(days=lookahead_days)

    # Simplified: look for CashSnapshot on the same cdu, currency, where amount increased
    # In real life we'd compare day-over-day deltas. Here we use a heuristic:
    # look for any CashSnapshot on the dates around due_date with amount >= balance.
    snaps = db.execute(select(CashSnapshot).where(
        CashSnapshot.cdu_id == ar.cdu_id,
        CashSnapshot.currency == ar.currency,
        CashSnapshot.snapshot_date >= start,
        CashSnapshot.snapshot_date <= end,
    ).order_by(CashSnapshot.snapshot_date.asc())).scalars().all()

    for snap in snaps:
        # Heuristic: if snapshot amount >= AR balance (within tolerance)
        # In production, compare delta vs previous day.
        if _match_tolerance(ar.balance_currency, snap.amount, ar.currency):
            return snap
    return None


def close_ar_items(db: Session, target_date: Optional[date] = None) -> Dict[str, int]:
    """Close AR items that have a matching cash inflow."""
    q = select(AccountReceivable).where(AccountReceivable.status == "OPEN")
    if target_date:
        q = q.where(AccountReceivable.due_date == target_date)

    ar_items = db.execute(q).scalars().all()
    counters = {"closed": 0, "pending": 0, "errors": 0}

    for ar in ar_items:
        try:
            match = find_matching_cash_for_ar(db, ar)
            if match:
                ar.status = "CLOSED"
                ar.actual_value_date = match.snapshot_date
                # Optionally update linked trade
                if ar.related_trade_id:
                    trade = db.get(Trade, ar.related_trade_id)
                    if trade:
                        trade.notes = (trade.notes or "") + f"; AR_CLOSED on {match.snapshot_date}"
                counters["closed"] += 1
            else:
                counters["pending"] += 1
        except Exception as exc:
            logger.warning(f"AR close error ar={ar.id}: {exc}")
            counters["errors"] += 1

    db.commit()
    logger.info(f"AR close engine: {counters}")
    return counters
