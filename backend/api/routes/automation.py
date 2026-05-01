"""API endpoints for daily automation (Phase C5): coupons, redemptions, FIFO, AR closing."""
from __future__ import annotations
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from auth import require_admin
from models.db_models import ImportJob
from services.automation.coupon_redemption_engine import run_daily_auto_events
from services.automation.fifo_engine import process_all_sell_fifo
from services.automation.ar_closer import close_ar_items

router = APIRouter(prefix="/api/automation", tags=["automation"])


class DailyRunRequest(BaseModel):
    target_date: date


class DailyRunResponse(BaseModel):
    target_date: str
    coupons: dict
    redemptions: dict
    fifo: dict
    ar_close: dict


@router.post("/daily-run", response_model=DailyRunResponse)
def daily_run(
    req: DailyRunRequest,
    db: Session = Depends(get_db),
    user: str = Depends(require_admin),
):
    """Run all daily automation engines for target_date."""
    try:
        coupons = run_daily_auto_events(db, req.target_date)
        fifo = process_all_sell_fifo(db, req.target_date)
        ar = close_ar_items(db, req.target_date)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return DailyRunResponse(
        target_date=req.target_date.isoformat(),
        coupons=coupons.get("coupons", {}),
        redemptions=coupons.get("redemptions", {}),
        fifo=fifo,
        ar_close=ar,
    )


@router.post("/fifo-run")
def fifo_run(
    target_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: str = Depends(require_admin),
):
    return process_all_sell_fifo(db, target_date)


@router.post("/ar-close")
def ar_close(
    target_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: str = Depends(require_admin),
):
    return close_ar_items(db, target_date)
