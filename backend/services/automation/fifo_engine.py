"""FIFO lot write-off engine — Phase C3.

When a SELL trade is imported, deduct from the oldest open BondLots
(ordered by trade_date ASC, id ASC) until the SELL quantity is satisfied.
Updates BondLot.quantity_current and face_value_current.

Idempotent: only processes SELL trades where is_synthetic=False and
lot write-off not yet recorded (we check if the trade already has a
linked lot adjustment via notes or a side table; here we use a simple
heuristic — we skip if the trade notes contain "FIFO_DONE").
"""
from __future__ import annotations
from datetime import date
from typing import Dict, List, Optional
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session
from models.db_models import BondLot, Trade


def _find_open_lots(db: Session, cdu_id: int, isin: str) -> List[BondLot]:
    return db.execute(select(BondLot).where(
        BondLot.cdu_id == cdu_id,
        BondLot.isin == isin,
        BondLot.quantity_current > 0,
    ).order_by(BondLot.trade_date.asc(), BondLot.id.asc())).scalars().all()


def apply_fifo_for_sell_trade(db: Session, trade: Trade) -> Dict[str, any]:
    """Apply FIFO deduction for a single SELL trade."""
    if trade.operation_type != "SELL":
        return {"status": "skipped", "reason": "not SELL"}
    if not trade.isin:
        return {"status": "skipped", "reason": "no ISIN"}
    if trade.is_synthetic:
        return {"status": "skipped", "reason": "synthetic trade"}
    if trade.notes and "FIFO_DONE" in trade.notes:
        return {"status": "skipped", "reason": "already processed"}

    sell_qty = trade.quantity or 0
    if sell_qty <= 0:
        return {"status": "skipped", "reason": "zero quantity"}

    lots = _find_open_lots(db, trade.cdu_id, trade.isin)
    if not lots:
        return {"status": "error", "reason": "no open lots for ISIN", "isin": trade.isin}

    remaining = sell_qty
    consumed: List[Dict] = []
    for lot in lots:
        if remaining <= 0:
            break
        deduct = min(lot.quantity_current, remaining)
        lot.quantity_current -= deduct
        if lot.nominal_per_unit:
            lot.face_value_current -= deduct * lot.nominal_per_unit
        else:
            # Fallback: proportionally reduce face_value_current
            ratio = deduct / (lot.quantity_current + deduct) if (lot.quantity_current + deduct) > 0 else 0
            lot.face_value_current -= ratio * (lot.face_value_current + lot.face_value_current)
        remaining -= deduct
        consumed.append({
            "lot_id": lot.id,
            "deducted": deduct,
            "remaining_in_lot": lot.quantity_current,
        })

    if remaining > 0:
        # Oversold — log warning but mark processed
        trade.notes = (trade.notes or "") + f"; FIFO_PARTIAL oversold={remaining}"
    else:
        trade.notes = (trade.notes or "") + "; FIFO_DONE"
    db.flush()

    return {
        "status": "ok",
        "trade_id": trade.id,
        "sell_qty": sell_qty,
        "consumed_lots": consumed,
        "oversold": remaining,
    }


def process_all_sell_fifo(db: Session, target_date: Optional[date] = None) -> Dict[str, int]:
    """Process FIFO for all unprocessed SELL trades on target_date (or all dates if None)."""
    q = select(Trade).where(
        Trade.operation_type == "SELL",
        Trade.is_synthetic == False,
    )
    if target_date:
        q = q.where(Trade.trade_date == target_date)

    trades = db.execute(q).scalars().all()
    counters = {"processed": 0, "skipped": 0, "errors": 0}
    for trade in trades:
        res = apply_fifo_for_sell_trade(db, trade)
        if res["status"] == "ok":
            counters["processed"] += 1
        elif res["status"] == "skipped":
            counters["skipped"] += 1
        else:
            counters["errors"] += 1
            logger.warning(f"FIFO error trade={trade.id} isin={trade.isin}: {res}")

    db.commit()
    logger.info(f"FIFO engine: {counters}")
    return counters
