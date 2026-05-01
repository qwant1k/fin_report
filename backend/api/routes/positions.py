"""Positions as-of-date endpoint — returns net holdings per ISIN/CDU
aggregated from trades up to a target date, with last-update badge.
"""
from __future__ import annotations
from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session
from database import get_db
from models.db_models import CDU, Trade

router = APIRouter(prefix="/api/positions", tags=["positions"])


class PositionRow(BaseModel):
    cdu_id: int
    cdu_name: str
    isin: str
    instrument_category: Optional[str]
    instrument_code: Optional[str]
    description: Optional[str]
    net_quantity: float
    net_face_value: float
    last_trade_date: Optional[date]


class PositionsAsOfResponse(BaseModel):
    as_of_date: date
    cdu_id: Optional[int]
    last_update_date: Optional[date]
    rows: List[PositionRow]


def _net_expr():
    """SQL expression for signed quantity based on operation_type."""
    return func.coalesce(
        func.sum(
            case(
                (Trade.operation_type.in_(["BUY", "COUPON", "REPO_CLOSE"]), Trade.quantity),
                (Trade.operation_type.in_(["SELL", "REDEMPTION", "REPO_OPEN"]), -Trade.quantity),
                else_=0,
            )
        ),
        0.0,
    )


def _net_face_expr():
    return func.coalesce(
        func.sum(
            case(
                (Trade.operation_type.in_(["BUY", "COUPON", "REPO_CLOSE"]), Trade.face_value),
                (Trade.operation_type.in_(["SELL", "REDEMPTION", "REPO_OPEN"]), -Trade.face_value),
                else_=0,
            )
        ),
        0.0,
    )


@router.get("/as-of", response_model=PositionsAsOfResponse)
def positions_as_of(
    as_of: date = Query(..., description="Состояние на дату (включительно)"),
    cdu_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    # --- global last_update for the CDU (max trade_date <= as_of) ---
    last_update_sub = select(
        func.max(Trade.trade_date).label("last_update")
    ).where(Trade.trade_date <= as_of, Trade.is_active == True)
    if cdu_id:
        last_update_sub = last_update_sub.where(Trade.cdu_id == cdu_id)
    last_update_row = db.execute(last_update_sub).scalar()

    # --- per-ISIN / instrument aggregation ---
    isin_col = func.coalesce(Trade.isin, Trade.instrument_code, "—").label("isin")
    stmt = select(
        Trade.cdu_id,
        isin_col,
        Trade.instrument_category,
        func.max(Trade.instrument_code).label("instrument_code"),
        func.max(Trade.description).label("description"),
        _net_expr().label("net_quantity"),
        _net_face_expr().label("net_face_value"),
        func.max(Trade.trade_date).label("last_trade_date"),
    ).where(
        Trade.trade_date <= as_of,
        Trade.is_active == True,
    )
    if cdu_id:
        stmt = stmt.where(Trade.cdu_id == cdu_id)

    stmt = stmt.group_by(
        Trade.cdu_id,
        isin_col,
        Trade.instrument_category,
    ).having(
        or_(_net_expr() != 0, _net_face_expr() != 0)
    ).order_by(Trade.cdu_id, isin_col)

    rows_raw = db.execute(stmt).all()

    # Fetch CDU names
    cdu_ids = {r.cdu_id for r in rows_raw}
    cdu_map = {}
    if cdu_ids:
        cdu_map = {
            c.id: c.name
            for c in db.execute(select(CDU).where(CDU.id.in_(cdu_ids))).scalars().all()
        }

    rows: List[PositionRow] = []
    for r in rows_raw:
        rows.append(PositionRow(
            cdu_id=r.cdu_id,
            cdu_name=cdu_map.get(r.cdu_id, str(r.cdu_id)),
            isin=r.isin,
            instrument_category=r.instrument_category,
            instrument_code=r.instrument_code,
            description=r.description,
            net_quantity=round(r.net_quantity, 6),
            net_face_value=round(r.net_face_value, 2),
            last_trade_date=r.last_trade_date,
        ))

    return PositionsAsOfResponse(
        as_of_date=as_of,
        cdu_id=cdu_id,
        last_update_date=last_update_row,
        rows=rows,
    )
