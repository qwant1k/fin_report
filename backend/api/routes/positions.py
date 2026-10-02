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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import require_permission
from database import get_db
from models.db_models import CDU, Trade

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
    # valuation on the date (portfolio engine)
    price: Optional[float] = None
    price_source: Optional[str] = None
    accrued_interest: Optional[float] = None
    market_value: Optional[float] = None
    ytm: Optional[float] = None
    duration: Optional[float] = None
    lots: int = 0


class PositionsAsOfResponse(BaseModel):
    as_of_date: date
    cdu_id: Optional[int]
    last_update_date: Optional[date]
    rows: List[PositionRow]
    base_dates: dict = {}
    warnings: List[str] = []


@router.get("/as-of", response_model=PositionsAsOfResponse)
def positions_as_of(
    as_of: date = Query(..., description="Состояние на дату (включительно)"),
    cdu_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Holdings on a date: latest Risk Report slice rolled forward with the
    Trade ledger (FIFO), revalued on the date — the same engine as the
    portfolio calculation, so the page and the report never disagree.

    Lots of the same ISIN are aggregated (a Risk Report keeps «1 сделка = 1
    лот»; all lots are counted, not just the first one).
    """
    from services.portfolio.engine import MarketData, build_portfolio
    from services.portfolio.reference import ReferenceBook

    cdus = db.execute(select(CDU).where(CDU.is_active.is_(True))).scalars().all()
    if cdu_id:
        cdus = [c for c in cdus if c.id == cdu_id]
    refs = ReferenceBook(db)
    market = MarketData(db, as_of)
    rows: List[PositionRow] = []
    base_dates: dict = {}
    warnings: List[str] = []
    last_dates: List[date] = []
    for cdu in cdus:
        state = build_portfolio(db, cdu.id, as_of, refs=refs, market=market)
        if state.base_date:
            base_dates[cdu.short_name or cdu.name] = state.base_date.isoformat()
            last_dates.append(state.base_date)
        warnings.extend(f"{cdu.short_name}: {w}" for w in state.warnings[:50])
        agg: dict = {}
        for b in state.bonds:
            key = (b.isin, b.category)
            row = agg.setdefault(key, {
                "isin": b.isin, "category": b.category, "code": b.ticker,
                "face": 0.0, "qty": 0.0, "mv": 0.0, "acc": 0.0, "ytm_w": 0.0, "dur_w": 0.0,
                "w": 0.0, "price": b.price, "source": b.price_source, "last": None, "lots": 0,
                "name": None,
            })
            row["face"] += b.face_value
            if b.unit_nominal:
                row["qty"] += b.face_value / float(b.unit_nominal)
            row["mv"] += b.total_value_kzt
            row["acc"] += b.accrued * b.fx_rate
            row["lots"] += 1
            if b.ytm is not None:
                row["ytm_w"] += b.ytm * b.total_value_kzt
            if b.duration is not None:
                row["dur_w"] += b.duration * b.total_value_kzt
            row["w"] += b.total_value_kzt
            d = b.settlement_date or b.trade_date
            if d and (row["last"] is None or d > row["last"]):
                row["last"] = d
            ref = refs.get(b.isin)
            if ref is not None:
                row["name"] = ref.instrument_name or ref.issuer
        for row in agg.values():
            rows.append(PositionRow(
                cdu_id=cdu.id, cdu_name=cdu.name, isin=row["isin"],
                instrument_category=row["category"], instrument_code=row["code"],
                description=row["name"], net_quantity=round(row["qty"], 6),
                net_face_value=round(row["face"], 2), last_trade_date=row["last"],
                price=row["price"], price_source=row["source"],
                accrued_interest=round(row["acc"], 2), market_value=round(row["mv"], 2),
                ytm=(row["ytm_w"] / row["w"]) if row["w"] else None,
                duration=(row["dur_w"] / row["w"]) if row["w"] else None,
                lots=row["lots"],
            ))
        for m in state.repos + state.deposits:
            rows.append(PositionRow(
                cdu_id=cdu.id, cdu_name=cdu.name,
                isin=m.identifier or m.deal_id or ("REPO" if m.kind == "REPO" else "DEPOSIT"),
                instrument_category="REVERSE_REPO" if m.kind == "REPO" else "DEPOSIT",
                instrument_code=m.deal_id,
                description=(
                    f"Обратное РЕПО до {m.close_date:%d.%m.%Y}" if m.kind == "REPO" and m.close_date
                    else ("Обратное РЕПО" if m.kind == "REPO" else "Депозит")
                ),
                net_quantity=round(m.quantity or 0.0, 6), net_face_value=round(m.open_amount, 2),
                last_trade_date=m.open_date, accrued_interest=round(m.accrued, 2),
                market_value=round(m.market_value, 2), ytm=m.ytm, duration=m.duration, lots=1,
                price_source=m.origin,
            ))

    last_trade = db.execute(select(func.max(Trade.value_date)).where(
        Trade.value_date <= as_of, Trade.is_active.is_(True),
        *( [Trade.cdu_id == cdu_id] if cdu_id else [] ),
    )).scalar()
    if last_trade:
        last_dates.append(last_trade)
    return PositionsAsOfResponse(
        as_of_date=as_of,
        cdu_id=cdu_id,
        last_update_date=max(last_dates) if last_dates else None,
        rows=sorted(rows, key=lambda x: (x.cdu_id, x.instrument_category or "", x.isin)),
        base_dates=base_dates,
        warnings=warnings[:300],
    )
