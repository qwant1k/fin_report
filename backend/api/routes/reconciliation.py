"""API endpoints for auto-reconciliation (Phase B6)."""
from __future__ import annotations
from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from auth import require_admin, require_user
from models.db_models import ReconciliationResult
from services.reconciliation.engine import reconcile_all_for_date, run_reconciliation

router = APIRouter(
    prefix="/api/reconciliation",
    tags=["reconciliation"],
    dependencies=[Depends(require_user)],
)


class ReconItem(BaseModel):
    id: int
    cdu_id: Optional[int]
    recon_date: date
    recon_type: str
    status: str
    expected_value: Optional[float]
    actual_value: Optional[float]
    deviation: Optional[float]
    tolerance: Optional[float]
    details_json: Optional[str]
    created_at: str


class ReconRunRequest(BaseModel):
    cdu_id: int
    recon_date: date
    recon_type: str


@router.post("/run", response_model=ReconItem)
def run_single_recon(
    req: ReconRunRequest,
    db: Session = Depends(get_db),
    user: str = Depends(require_admin),
):
    """Run a single reconciliation check."""
    res = run_reconciliation(db, req.cdu_id, req.recon_date, req.recon_type)
    return _to_dto(res)


@router.post("/run-all")
def run_all_recon(
    recon_date: date = Query(...),
    db: Session = Depends(get_db),
    user: str = Depends(require_admin),
):
    """Run all reconciliation types for every active CDU."""
    results = reconcile_all_for_date(db, recon_date)
    return {"date": recon_date.isoformat(), "results": [_to_dto(r) for r in results]}


@router.get("/list", response_model=List[ReconItem])
def list_recon(
    cdu_id: Optional[int] = None,
    recon_date: Optional[date] = None,
    recon_type: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(ReconciliationResult)
    if cdu_id:
        q = q.filter(ReconciliationResult.cdu_id == cdu_id)
    if recon_date:
        q = q.filter(ReconciliationResult.recon_date == recon_date)
    if recon_type:
        q = q.filter(ReconciliationResult.recon_type == recon_type)
    if status:
        q = q.filter(ReconciliationResult.status == status)
    q = q.order_by(ReconciliationResult.created_at.desc())
    return [_to_dto(r) for r in q.limit(200).all()]


def _to_dto(r: ReconciliationResult) -> dict:
    return {
        "id": r.id,
        "cdu_id": r.cdu_id,
        "recon_date": r.recon_date,
        "recon_type": r.recon_type,
        "status": r.status,
        "expected_value": r.expected_value,
        "actual_value": r.actual_value,
        "deviation": r.deviation,
        "tolerance": r.tolerance,
        "details_json": r.details_json,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
