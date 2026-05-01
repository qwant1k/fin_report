"""Export endpoints — XLSX and PDF."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.db_models import GeneratedReport
from services.report import generate_pdf_report, generate_xlsx_report

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/xlsx")
def export_xlsx(report_date: date, db: Session = Depends(get_db)):
    out = generate_xlsx_report(db, report_date, settings.report_path)
    db.add(GeneratedReport(report_date=report_date, report_type="DAILY_XLSX", file_path=str(out)))
    db.commit()
    return FileResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=out.name,
    )


@router.get("/pdf")
def export_pdf(report_date: date, db: Session = Depends(get_db)):
    out = generate_pdf_report(db, report_date, settings.report_path)
    db.add(GeneratedReport(report_date=report_date, report_type="DAILY_PDF", file_path=str(out)))
    db.commit()
    return FileResponse(out, media_type="application/pdf", filename=out.name)


@router.get("/list")
def list_reports(db: Session = Depends(get_db)):
    return db.query(GeneratedReport).order_by(GeneratedReport.generated_at.desc()).limit(200).all()
