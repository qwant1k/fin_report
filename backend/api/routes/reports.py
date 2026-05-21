"""Reports listing — generated XLSX/PDF + approval workflow.

Approval rules (see ``services/report_approval.py``):
    draft → submit → pending_approval → approve → approved (immutable)
                                       → reject → rejected → submit → pending_approval
    regenerate is allowed only while status ∈ {draft, rejected}.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from auth import require_admin, require_user, require_write
from config import settings
from database import get_db
from models.db_models import GeneratedReport, RawTrade, User
from models.schemas import GeneratedReportOut, ReportRejectRequest
from services.audit import write_audit
from services.report import generate_pdf_report, generate_xlsx_report
from services.report_approval import (
    approve as approve_report,
    can_be_regenerated,
    ensure_mutable,
    reject as reject_report,
    submit as submit_report,
)

router = APIRouter(
    prefix="/api/reports",
    tags=["reports"],
    dependencies=[Depends(require_user)],
)


@router.get("/", response_model=List[GeneratedReportOut])
def list_generated(
    status: Optional[str] = Query(None),
    report_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(GeneratedReport)
    if status:
        q = q.filter(GeneratedReport.status == status)
    if report_type:
        q = q.filter(GeneratedReport.report_type == report_type)
    return q.order_by(GeneratedReport.generated_at.desc()).limit(500).all()


@router.get("/{report_id}", response_model=GeneratedReportOut)
def get_report(report_id: int, db: Session = Depends(get_db)):
    obj = db.get(GeneratedReport, report_id)
    if not obj:
        raise HTTPException(404, "Отчёт не найден")
    return obj


@router.get("/{report_id}/download")
def download(report_id: int, db: Session = Depends(get_db)):
    obj = db.get(GeneratedReport, report_id)
    if not obj:
        raise HTTPException(404, "Отчёт не найден")
    if not Path(obj.file_path).exists():
        raise HTTPException(404, "Файл отчёта не найден на диске")
    return FileResponse(obj.file_path, filename=Path(obj.file_path).name)


@router.post("/{report_id}/submit", response_model=GeneratedReportOut)
def submit(
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_write),
):
    obj = db.get(GeneratedReport, report_id)
    if not obj:
        raise HTTPException(404, "Отчёт не найден")
    submit_report(db, obj, actor=user.username)
    db.commit()
    db.refresh(obj)
    return obj


@router.post("/{report_id}/approve", response_model=GeneratedReportOut)
def approve(
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    obj = db.get(GeneratedReport, report_id)
    if not obj:
        raise HTTPException(404, "Отчёт не найден")
    approve_report(db, obj, actor=user.username)
    db.commit()
    db.refresh(obj)
    return obj


@router.post("/{report_id}/reject", response_model=GeneratedReportOut)
def reject(
    report_id: int,
    payload: ReportRejectRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    obj = db.get(GeneratedReport, report_id)
    if not obj:
        raise HTTPException(404, "Отчёт не найден")
    reject_report(db, obj, actor=user.username, comment=payload.comment)
    db.commit()
    db.refresh(obj)
    return obj


@router.post("/{report_id}/regenerate", response_model=GeneratedReportOut)
def regenerate(
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_write),
):
    """Re-run generation for a draft/rejected report.

    Bumps ``version`` in place and overwrites the on-disk file. Refused for
    approved/pending rows — for those, generate a brand new report via
    ``/api/export/{xlsx,pdf}`` (which creates a child row with
    ``parent_report_id`` set).
    """
    obj = db.get(GeneratedReport, report_id)
    if not obj:
        raise HTTPException(404, "Отчёт не найден")
    if not can_be_regenerated(obj):
        raise HTTPException(
            409,
            f"Регенерация запрещена в статусе {obj.status!r}. "
            f"Создайте новую версию через /api/export.",
        )
    if obj.report_type == "DAILY_PDF":
        out = generate_pdf_report(db, obj.report_date, settings.report_path)
    else:
        out = generate_xlsx_report(db, obj.report_date, settings.report_path)
    obj.file_path = str(out)
    obj.version = (obj.version or 1) + 1
    obj.status = "draft"
    write_audit(
        db, user=user.username, action="REPORT_REGENERATED",
        entity="GeneratedReport", entity_id=obj.id,
        details={
            "report_date": str(obj.report_date),
            "report_type": obj.report_type,
            "new_version": obj.version,
        },
    )
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{report_id}")
def delete_report(
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    obj = db.get(GeneratedReport, report_id)
    if not obj:
        raise HTTPException(404, "Отчёт не найден")
    ensure_mutable(obj, action="удалён")
    try:
        Path(obj.file_path).unlink(missing_ok=True)
    except Exception:
        pass
    write_audit(
        db, user=user.username, action="REPORT_DELETED",
        entity="GeneratedReport", entity_id=obj.id,
        details={"report_date": str(obj.report_date), "type": obj.report_type},
    )
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.get("/raw-trades")
def list_raw_trades(
    report_date: date | None = None, cdu_id: int | None = None,
    limit: int = 500, db: Session = Depends(get_db),
):
    q = db.query(RawTrade).order_by(RawTrade.trade_date.desc(), RawTrade.id.desc()).limit(limit)
    if report_date:
        q = q.filter_by(trade_date=report_date)
    if cdu_id:
        q = q.filter_by(cdu_id=cdu_id)
    return [
        {
            "id": t.id,
            "trade_date": t.trade_date.isoformat() if t.trade_date else None,
            "cdu_id": t.cdu_id,
            "operation_type": t.operation_type,
            "instrument_code": t.instrument_code,
            "instrument_category": t.instrument_category,
            "regime_code": t.regime_code,
            "kp": t.kp,
            "price": t.price,
            "volume": t.volume,
            "nominal_volume": t.nominal_volume,
            "yield_pct": t.yield_pct,
            "repo_rate_pct": t.repo_rate_pct,
            "repo_term_days": t.repo_term_days,
            "repo_sum": t.repo_sum,
            "repo_buyback_sum": t.repo_buyback_sum,
            "status": t.status,
            "order_number": t.order_number,
        }
        for t in q.all()
    ]
