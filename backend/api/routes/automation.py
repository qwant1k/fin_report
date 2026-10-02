"""API endpoints for daily automation (Phase C5): coupons, redemptions, FIFO, AR closing."""
from __future__ import annotations
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from auth import require_permission, require_user
from models.db_models import ImportJob
from services.automation.coupon_redemption_engine import run_daily_auto_events
from services.automation.fifo_engine import process_all_sell_fifo
from services.automation.ar_closer import close_ar_items

router = APIRouter(
    prefix="/api/automation",
    tags=["automation"],
    dependencies=[Depends(require_user)],
)


class DailyRunRequest(BaseModel):
    target_date: date
    # optional: run every day of [date_from, target_date] (catch-up)
    date_from: Optional[date] = None


class DailyRunResponse(BaseModel):
    target_date: str
    coupons: dict
    redemptions: dict
    fifo: dict
    ar_close: dict
    calculation: dict = {}
    days: int = 1


@router.post("/daily-run", response_model=DailyRunResponse)
def daily_run(
    req: DailyRunRequest,
    db: Session = Depends(get_db),
    user=Depends(require_permission("automation.run")),
):
    """Coupons/redemptions → FIFO control → AR closing → portfolio calculation.

    With ``date_from`` every calendar day of the period is processed in order
    (coupon/maturity events are exact-date events and must not be skipped).
    """
    from datetime import timedelta
    from services.audit import write_audit
    from services.calculator.portfolio_calculator import calculate_for_date

    start = req.date_from or req.target_date
    if start > req.target_date:
        raise HTTPException(400, "date_from не может быть позже target_date")
    if (req.target_date - start).days > 92:
        raise HTTPException(400, "Период догоняющего запуска не более 92 дней")
    coupons_total: dict = {}
    redemptions_total: dict = {}
    fifo_total: dict = {}
    ar_total: dict = {}
    calc: dict = {}
    days = 0
    try:
        day = start
        while day <= req.target_date:
            events = run_daily_auto_events(db, day)
            fifo = process_all_sell_fifo(db, day)
            ar = close_ar_items(db, day)
            calc = calculate_for_date(db, day)
            for total, part in ((coupons_total, events.get("coupons", {})),
                                (redemptions_total, events.get("redemptions", {})),
                                (fifo_total, fifo), (ar_total, ar)):
                for key, value in part.items():
                    total[key] = total.get(key, 0) + value
            write_audit(db, user=getattr(user, "username", None), action="DAILY_AUTOMATION",
                        entity="Automation", details={"target_date": day.isoformat(), "calc": calc})
            db.commit()
            day += timedelta(days=1)
            days += 1
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    return DailyRunResponse(
        target_date=req.target_date.isoformat(),
        coupons=coupons_total,
        redemptions=redemptions_total,
        fifo=fifo_total,
        ar_close=ar_total,
        calculation=calc,
        days=days,
    )


@router.post("/fifo-run")
def fifo_run(
    target_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: str = Depends(require_permission("automation.run")),
):
    return process_all_sell_fifo(db, target_date)


@router.post("/ar-close")
def ar_close(
    target_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: str = Depends(require_permission("automation.run")),
):
    return close_ar_items(db, target_date)
