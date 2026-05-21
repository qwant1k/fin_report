"""Calculation endpoints — trigger portfolio recompute for a date."""
from __future__ import annotations

import time
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import require_user, require_write
from database import get_db
from models.db_models import CalculationRun, User
from models.schemas import CalculateRequest, CalculateResponse
from services.audit import write_audit
from services.calculator.portfolio_calculator import calculate_for_date

router = APIRouter(
    prefix="/api/calculate",
    tags=["calculate"],
    dependencies=[Depends(require_user)],
)


@router.post("/", response_model=CalculateResponse)
def trigger_calc(
    payload: CalculateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_write),
):
    run = CalculationRun(
        run_date=payload.report_date, status="RUNNING",
        triggered_by=user.username,
    )
    db.add(run)
    db.commit()
    t0 = time.perf_counter()
    result = {"cdus_processed": 0, "breaches": 0}
    try:
        result = calculate_for_date(db, payload.report_date, recalculate=payload.recalculate)
        run.status = "OK"
        run.cdus_processed = result["cdus_processed"]
    except Exception as exc:  # pragma: no cover
        run.status = "ERROR"
        run.error_message = str(exc)
        run.finished_at = datetime.utcnow()
        db.commit()
        raise HTTPException(500, f"Ошибка расчёта: {exc}") from exc
    finally:
        run.finished_at = datetime.utcnow()
        write_audit(
            db, user=user.username, action="CALCULATION_RUN",
            entity="CalculationRun", entity_id=run.id,
            details={
                "run_date": payload.report_date.isoformat(),
                "status": run.status,
                "cdus_processed": run.cdus_processed,
                "recalculate": payload.recalculate,
            },
        )
        db.commit()

    return CalculateResponse(
        report_date=payload.report_date,
        cdus_processed=result["cdus_processed"],
        breaches_count=result["breaches"],
        duration_seconds=round(time.perf_counter() - t0, 3),
    )
