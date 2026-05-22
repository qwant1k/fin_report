"""Positions as-of-date endpoint.

The UI needs actual holdings, not just signed Trade rows. Prefer imported
position snapshots/lots, then fall back to Trade aggregation for outright
BUY/SELL flows.
"""
from __future__ import annotations
from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from auth import require_permission
from database import get_db
from models.db_models import BondLot, CDU, PortfolioPosition, RepoLot, Trade

router = APIRouter(
    prefix="/api/positions",
    tags=["positions"],
    dependencies=[Depends(require_permission("page.positions"))],
)


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
                (Trade.operation_type.in_(["BUY", "COUPON", "REPO_OPEN"]), Trade.quantity),
                (Trade.operation_type.in_(["SELL", "REDEMPTION", "REPO_CLOSE"]), -Trade.quantity),
                else_=0,
            )
        ),
        0.0,
    )


def _net_face_expr():
    return func.coalesce(
        func.sum(
            case(
                (Trade.operation_type.in_(["BUY", "COUPON", "REPO_OPEN"]), Trade.face_value),
                (Trade.operation_type.in_(["SELL", "REDEMPTION", "REPO_CLOSE"]), -Trade.face_value),
                else_=0,
            )
        ),
        0.0,
    )


def _net_value_expr():
    return func.coalesce(
        func.sum(
            case(
                (Trade.operation_type == "REPO_OPEN", -Trade.amount_kzt),
                (Trade.operation_type == "REPO_CLOSE", -Trade.amount_kzt),
                (Trade.operation_type.in_(["BUY", "COUPON"]), Trade.face_value),
                (Trade.operation_type.in_(["SELL", "REDEMPTION"]), -Trade.face_value),
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
    # --- global last_update across all position sources ---
    last_update_sub = select(func.max(Trade.trade_date)).where(Trade.trade_date <= as_of, Trade.is_active == True)
    if cdu_id:
        last_update_sub = last_update_sub.where(Trade.cdu_id == cdu_id)
    last_update_candidates = [db.execute(last_update_sub).scalar()]
    pos_last = select(func.max(PortfolioPosition.position_date)).where(PortfolioPosition.position_date <= as_of)
    repo_last = select(func.max(RepoLot.trade_date)).where(RepoLot.trade_date <= as_of)
    bond_last = select(func.max(BondLot.valuation_date)).where(BondLot.valuation_date <= as_of)
    if cdu_id:
        pos_last = pos_last.where(PortfolioPosition.cdu_id == cdu_id)
        repo_last = repo_last.where(RepoLot.cdu_id == cdu_id)
        bond_last = bond_last.where(BondLot.cdu_id == cdu_id)
    last_update_candidates.extend([
        db.execute(pos_last).scalar(),
        db.execute(repo_last).scalar(),
        db.execute(bond_last).scalar(),
    ])
    last_update_row = max([d for d in last_update_candidates if d is not None], default=None)

    cdu_map = {c.id: c.name for c in db.execute(select(CDU)).scalars().all()}
    rows: List[PositionRow] = []
    seen: set[tuple[int, str, str]] = set()

    def add_row(
        *,
        cdu_id_value: int,
        isin: str,
        category: Optional[str],
        code: Optional[str],
        description: Optional[str],
        quantity: float,
        face_value: float,
        last_trade_date: Optional[date],
    ) -> None:
        if abs(quantity or 0.0) < 1e-9 and abs(face_value or 0.0) < 1e-9:
            return
        key = (cdu_id_value, isin or "—", category or "")
        if key in seen:
            return
        seen.add(key)
        rows.append(PositionRow(
            cdu_id=cdu_id_value,
            cdu_name=cdu_map.get(cdu_id_value, str(cdu_id_value)),
            isin=isin or "—",
            instrument_category=category,
            instrument_code=code,
            description=description,
            net_quantity=round(quantity or 0.0, 6),
            net_face_value=round(face_value or 0.0, 2),
            last_trade_date=last_trade_date,
        ))

    # 1) Latest imported Holdings/Risk Report position snapshot <= as_of.
    latest_pos_date = db.execute(pos_last).scalar()
    if latest_pos_date:
        pos_stmt = select(PortfolioPosition).where(PortfolioPosition.position_date == latest_pos_date)
        if cdu_id:
            pos_stmt = pos_stmt.where(PortfolioPosition.cdu_id == cdu_id)
        for p in db.execute(pos_stmt).scalars().all():
            if p.instrument_code is None and (p.nominal_volume or 0.0) == 0.0:
                continue
            add_row(
                cdu_id_value=p.cdu_id,
                isin=p.instrument_code or p.instrument_category,
                category=p.instrument_category,
                code=p.instrument_code,
                description=p.instrument_name,
                quantity=p.nominal_volume or 0.0,
                face_value=p.nominal_volume or p.market_value_current or 0.0,
                last_trade_date=p.position_date,
            )

    # 2) Lot tables created from Trade Report imports and Risk Report imports.
    bond_stmt = select(BondLot).where(
        BondLot.valuation_date <= as_of,
        BondLot.face_value_current != 0,
    )
    if cdu_id:
        bond_stmt = bond_stmt.where(BondLot.cdu_id == cdu_id)
    for lot in db.execute(bond_stmt).scalars().all():
        add_row(
            cdu_id_value=lot.cdu_id,
            isin=lot.isin,
            category=lot.category,
            code=lot.instrument_code or lot.isin,
            description=lot.notes,
            quantity=lot.quantity_current or 0.0,
            face_value=lot.face_value_current or 0.0,
            last_trade_date=lot.trade_date,
        )

    repo_stmt = select(RepoLot).where(
        RepoLot.trade_date <= as_of,
        or_(RepoLot.close_date.is_(None), RepoLot.close_date > as_of),
    )
    if cdu_id:
        repo_stmt = repo_stmt.where(RepoLot.cdu_id == cdu_id)
    for lot in db.execute(repo_stmt).scalars().all():
        code = lot.instrument_code or lot.isin or lot.deal_id or "REPO"
        add_row(
            cdu_id_value=lot.cdu_id,
            isin=lot.isin or code,
            category="REVERSE_REPO",
            code=code,
            description="Открытое обратное REPO",
            quantity=lot.face_value or 0.0,
            face_value=lot.close_value or lot.face_value or 0.0,
            last_trade_date=lot.trade_date,
        )

    # 3) Fallback: Trade ledger, value-date aware.
    isin_col = func.coalesce(Trade.isin, Trade.instrument_code, "—").label("isin")
    stmt = select(
        Trade.cdu_id,
        isin_col,
        Trade.instrument_category,
        func.max(Trade.instrument_code).label("instrument_code"),
        func.max(Trade.description).label("description"),
        _net_expr().label("net_quantity"),
        _net_value_expr().label("net_face_value"),
        func.max(Trade.trade_date).label("last_trade_date"),
    ).where(
        Trade.value_date <= as_of,
        Trade.is_active == True,
        Trade.operation_type.in_(["BUY", "SELL", "REDEMPTION", "REPO_OPEN", "REPO_CLOSE"]),
    )
    if cdu_id:
        stmt = stmt.where(Trade.cdu_id == cdu_id)

    stmt = stmt.group_by(
        Trade.cdu_id,
        isin_col,
        Trade.instrument_category,
    ).having(
        or_(_net_expr() != 0, _net_value_expr() != 0)
    ).order_by(Trade.cdu_id, isin_col)

    for r in db.execute(stmt).all():
        add_row(
            cdu_id_value=r.cdu_id,
            isin=r.isin,
            category=r.instrument_category,
            code=r.instrument_code,
            description=r.description,
            quantity=r.net_quantity,
            face_value=r.net_face_value,
            last_trade_date=r.last_trade_date,
        )

    return PositionsAsOfResponse(
        as_of_date=as_of,
        cdu_id=cdu_id,
        last_update_date=last_update_row,
        rows=sorted(rows, key=lambda x: (x.cdu_id, x.instrument_category or "", x.isin)),
    )
