"""API endpoints for auto-reconciliation (Phase B6)."""
from __future__ import annotations
from datetime import date
from typing import List, Optional
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from auth import require_permission, require_user
from models.db_models import CDU, ReconciliationResult, SourceDocument
from services.reconciliation.engine import reconcile_all_for_date, run_reconciliation

router = APIRouter(
    prefix="/api/reconciliation",
    tags=["reconciliation"],
    dependencies=[Depends(require_permission("page.reconciliation"))],
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
    user: str = Depends(require_permission("reconciliation.run")),
):
    """Run a single reconciliation check."""
    res = run_reconciliation(db, req.cdu_id, req.recon_date, req.recon_type)
    return _to_dto(res)


@router.post("/run-all")
def run_all_recon(
    recon_date: date = Query(...),
    db: Session = Depends(get_db),
    user: str = Depends(require_permission("reconciliation.run")),
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


RECON_TYPES = [
    {"code": "rr_vs_holdings", "label": "Наш расчёт ↔ файл сверки ЧДУ", "main": True},
    {"code": "cash_vs_statement", "label": "Деньги ↔ выписка кастодиана"},
    {"code": "trade_vs_cert", "label": "Trade Report ↔ биржевые свидетельства"},
    {"code": "nbrk_fallback", "label": "Деньги ↔ КФГД_ГГГГММДД (НБ РК)"},
]


@router.get("/overview")
def recon_overview(recon_date: date = Query(...), db: Session = Depends(get_db)):
    """Matrix «ЧДУ × вид сверки» for the date + uploaded reconciliation files."""
    cdus = db.execute(select(CDU).where(CDU.is_active.is_(True)).order_by(CDU.id)).scalars().all()
    results = db.execute(select(ReconciliationResult).where(
        ReconciliationResult.recon_date == recon_date,
    )).scalars().all()
    by_cdu: dict = {}
    for r in results:
        by_cdu.setdefault(r.cdu_id, {})[r.recon_type] = {
            "id": r.id, "status": r.status, "deviation": r.deviation,
            "expected": r.expected_value, "actual": r.actual_value,
            "note": (json.loads(r.details_json or "{}") or {}).get("note"),
            "counts": (json.loads(r.details_json or "{}") or {}).get("counts"),
        }
    docs = db.execute(select(SourceDocument).where(
        SourceDocument.doc_type == "RECONCILIATION",
    ).order_by(SourceDocument.uploaded_at.desc(), SourceDocument.id.desc()).limit(300)).scalars().all()
    files_for_date: dict = {}
    for d in docs:
        if d.doc_date == recon_date and d.cdu_id and d.cdu_id not in files_for_date and d.parse_status == "OK":
            files_for_date[d.cdu_id] = {"doc_id": d.id, "file_name": d.file_name,
                                        "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None}
    unbound = [{"doc_id": d.id, "file_name": d.file_name, "doc_date": d.doc_date.isoformat() if d.doc_date else None,
                "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
                "cdu_name_in_file": (json.loads(d.parse_meta_json or "{}") or {}).get("cdu_name")}
               for d in docs if d.parse_status == "OK" and (d.cdu_id is None or d.doc_date is None)]
    other_dates = sorted({d.doc_date.isoformat() for d in docs if d.doc_date and d.cdu_id and d.parse_status == "OK"},
                         reverse=True)[:12]
    return {
        "date": recon_date.isoformat(),
        "types": RECON_TYPES,
        "rows": [{
            "cdu_id": c.id, "cdu_name": c.short_name or c.name, "portfolio_type": c.portfolio_type,
            "file": files_for_date.get(c.id), "results": by_cdu.get(c.id, {}),
        } for c in cdus],
        "unbound_files": unbound,
        "file_dates": other_dates,
    }


@router.get("/result/{result_id}")
def recon_result(result_id: int, db: Session = Depends(get_db)):
    r = db.get(ReconciliationResult, result_id)
    if r is None:
        raise HTTPException(404, "Результат сверки не найден")
    cdu = db.get(CDU, r.cdu_id) if r.cdu_id else None
    return {**_to_dto(r), "cdu_name": (cdu.short_name or cdu.name) if cdu else None,
            "details": json.loads(r.details_json or "{}")}


@router.get("/result/{result_id}/export")
def recon_export(result_id: int, db: Session = Depends(get_db)):
    """Excel with the line-by-line comparison — to send to the manager."""
    from services.reconciliation.export import reconciliation_xlsx
    r = db.get(ReconciliationResult, result_id)
    if r is None or r.recon_type != "rr_vs_holdings":
        raise HTTPException(404, "Результат построчной сверки не найден")
    cdu = db.get(CDU, r.cdu_id) if r.cdu_id else None
    data = reconciliation_xlsx(json.loads(r.details_json or "{}"), cdu_name=(cdu.name if cdu else ""),
                               recon_date=r.recon_date)
    name = f"sverka_{(cdu.short_name if cdu else 'cdu')}_{r.recon_date:%Y%m%d}.xlsx"
    from urllib.parse import quote
    return StreamingResponse(io.BytesIO(data),
                             media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
