"""FIFO write-off — business process 6.2.3 D / 7.2.3 C / 7.2.6 C.

The write-off itself is performed by the portfolio engine every time a
portfolio is built (``services.portfolio.engine._fifo_write_off``): sales
reduce the earliest lots first (by settlement date, then entry order) and the
stored lots are never mutated, so re-imports and back-dated corrections are
always consistent.

This module keeps the public API used by the scheduler / automation endpoint
and turns it into a *control*: for the SELL trades of a date it checks that
the full nominal could be written off and reports oversold positions
(«недостаточно остатка для списания» → error in the process description).
"""
from __future__ import annotations

import json
from datetime import date
from typing import Dict, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.db_models import Alert, CDU, Trade
from services.portfolio.engine import build_portfolio
from services.workflow import EFFECTIVE_STATUSES


def process_all_sell_fifo(db: Session, target_date: Optional[date] = None) -> Dict[str, int]:
    """Validate FIFO write-off of SELL trades settled on ``target_date``."""
    q = select(Trade).where(
        Trade.operation_type == "SELL",
        Trade.is_synthetic == False,  # noqa: E712
        Trade.is_active == True,  # noqa: E712
        Trade.workflow_status.in_(EFFECTIVE_STATUSES),
    )
    if target_date:
        q = q.where(Trade.value_date == target_date)
    trades = db.execute(q).scalars().all()
    counters = {"processed": 0, "skipped": 0, "errors": 0}
    by_cdu: Dict[int, list] = {}
    for trade in trades:
        by_cdu.setdefault(trade.cdu_id, []).append(trade)
    for cdu_id, cdu_trades in by_cdu.items():
        as_of = max(t.value_date for t in cdu_trades)
        state = build_portfolio(db, cdu_id, as_of)
        problems = [w for w in state.warnings if "недостаточно остатка" in w or "не определён номинал" in w]
        trade_ids = {f"#{t.id}" for t in cdu_trades}
        relevant = [w for w in problems if any(tid in w for tid in trade_ids)]
        counters["processed"] += len(cdu_trades) - len(relevant)
        counters["errors"] += len(relevant)
        if relevant:
            cdu = db.get(CDU, cdu_id)
            db.add(Alert(
                alert_date=as_of, cdu_id=cdu_id, alert_type="FIFO_SHORTFALL", severity="CRITICAL",
                message=f"{cdu.short_name if cdu else cdu_id}: " + "; ".join(relevant[:3]),
                details_json=json.dumps({
                    "problems": relevant[:20],
                    "trade_ids": sorted(trade_ids),
                    "explanation": "Для продажи недостаточно подтверждённого остатка по методу FIFO.",
                }, ensure_ascii=False),
            ))
            for w in relevant:
                logger.warning(f"FIFO: {w}")
    db.commit()
    logger.info(f"FIFO control: {counters}")
    return counters
