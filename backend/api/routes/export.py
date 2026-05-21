"""Export endpoints — XLSX and PDF."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from auth import require_user, require_write
from config import settings
from database import get_db
from models.db_models import GeneratedReport, User
from services.audit import write_audit
from services.report import generate_pdf_report, generate_xlsx_report

router = APIRouter(
    prefix="/api/export",
    tags=["export"],
    dependencies=[Depends(require_user)],
)


def _latest_for(db: Session, *, report_date: date, report_type: str) -> "GeneratedReport | None":
    return (
        db.query(GeneratedReport)
        .filter(
            GeneratedReport.report_date == report_date,
            GeneratedReport.report_type == report_type,
        )
        .order_by(GeneratedReport.version.desc(), GeneratedReport.id.desc())
        .first()
    )


def _persist_export(
    db: Session, *, user: User, report_date: date, report_type: str, out_path: str,
) -> GeneratedReport:
    """Persist a freshly generated report.

    If a previous version exists for the same (date, type):
      * approved → create a new ``GeneratedReport`` row with version+1 and
        ``parent_report_id`` pointing at the approved one (immutability of
        the approved row is preserved).
      * draft/rejected/pending_approval → keep the existing row but rewrite
        ``file_path``, bump version and reset to ``draft`` so the workflow
        starts over with the new content.
    """
    prev = _latest_for(db, report_date=report_date, report_type=report_type)
    if prev is not None and (prev.status or "draft") == "approved":
        rep = GeneratedReport(
            report_date=report_date,
            report_type=report_type,
            file_path=out_path,
            generated_by=user.username,
            status="draft",
            version=(prev.version or 1) + 1,
            parent_report_id=prev.id,
        )
        db.add(rep)
    elif prev is not None:
        prev.file_path = out_path
        prev.generated_by = user.username
        prev.version = (prev.version or 1) + 1
        prev.status = "draft"
        prev.submitted_by = None
        prev.submitted_at = None
        prev.rejected_by = None
        prev.rejected_at = None
        prev.rejection_comment = None
        rep = prev
    else:
        rep = GeneratedReport(
            report_date=report_date,
            report_type=report_type,
            file_path=out_path,
            generated_by=user.username,
            status="draft",
            version=1,
        )
        db.add(rep)
    db.flush()
    return rep


@router.get("/xlsx")
def export_xlsx(
    report_date: date,
    db: Session = Depends(get_db),
    user: User = Depends(require_write),
):
    out = generate_xlsx_report(db, report_date, settings.report_path)
    rep = _persist_export(
        db, user=user, report_date=report_date,
        report_type="DAILY_XLSX", out_path=str(out),
    )
    write_audit(
        db, user=user.username, action="EXPORT_XLSX",
        entity="GeneratedReport", entity_id=rep.id,
        details={
            "report_date": report_date.isoformat(),
            "version": rep.version,
            "parent_report_id": rep.parent_report_id,
            "path": str(out),
        },
    )
    db.commit()
    return FileResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=out.name,
    )


@router.get("/pdf")
def export_pdf(
    report_date: date,
    db: Session = Depends(get_db),
    user: User = Depends(require_write),
):
    out = generate_pdf_report(db, report_date, settings.report_path)
    rep = _persist_export(
        db, user=user, report_date=report_date,
        report_type="DAILY_PDF", out_path=str(out),
    )
    write_audit(
        db, user=user.username, action="EXPORT_PDF",
        entity="GeneratedReport", entity_id=rep.id,
        details={
            "report_date": report_date.isoformat(),
            "version": rep.version,
            "parent_report_id": rep.parent_report_id,
            "path": str(out),
        },
    )
    db.commit()
    return FileResponse(out, media_type="application/pdf", filename=out.name)


@router.get("/list")
def list_reports(db: Session = Depends(get_db)):
    return db.query(GeneratedReport).order_by(GeneratedReport.generated_at.desc()).limit(200).all()
