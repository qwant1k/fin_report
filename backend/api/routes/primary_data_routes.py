"""API endpoints for primary-data import from custodians (ЧДУ / НБ РК)."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import require_admin
from config import settings
from database import SessionLocal, get_db
from models.db_models import CDU, ImportJob, SourceDocument, User
from services.calculator.constants import normalize_cdu_name
from services.import_primary.cert_parser import parse_certificate
from services.import_primary.holdings_parser import import_holdings_xlsx
from services.import_primary.recon_parser import parse_reconciliation_xlsx
from services.import_primary.statement_parser import parse_pdf_statement
from services.parser.trade_importer import import_single_trade_report_xlsx

router = APIRouter(prefix="/api/primary-data", tags=["primary-data"])


class ImportResponse(BaseModel):
    job_id: int
    status: str
    message: str
    counters: dict = Field(default_factory=dict)


@router.post("/upload", response_model=ImportResponse)
async def upload_primary_data(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Upload one primary-data file, save it for audit, and import immediately."""
    original_name = file.filename or "unnamed"
    file_type = _detect_file_type(original_name)
    if file_type == "unknown":
        raise HTTPException(400, f"Cannot detect file type for '{original_name}'")

    target_dir = settings.upload_path / "primary_data" / file_type
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = original_name.replace("/", "_").replace("\\", "_")
    target = target_dir / f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    with target.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    content = target.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    duplicate = db.execute(
        select(SourceDocument).where(
            SourceDocument.sha256 == sha,
            SourceDocument.parse_status == "OK",
        )
    ).scalars().first()
    if duplicate:
        return ImportResponse(
            job_id=-1,
            status="SKIPPED",
            message=f"Duplicate of already imported document id={duplicate.id} ({duplicate.file_name})",
        )

    source_doc = SourceDocument(
        doc_type=_to_doc_type(file_type),
        cdu_id=None,
        doc_date=None,
        file_name=original_name,
        file_path=str(target),
        sha256=sha,
        file_size=len(content),
        uploaded_by=user.username,
        parse_status="PENDING",
    )
    db.add(source_doc)
    db.flush()

    job = ImportJob(
        job_type="FOLDER_PRIMARY",
        status="RUNNING",
        triggered_by=user.username,
        files_total=1,
        params_json=json.dumps({"source_doc_id": source_doc.id, "file_name": original_name}, ensure_ascii=False),
    )
    db.add(job)
    db.flush()

    try:
        counters = _run_import(db, str(target), file_type, source_doc.id, user.username)
        _finalize_source_doc(db, source_doc, counters)
        job.status = "DONE"
        job.finished_at = datetime.utcnow()
        job.files_done = 1
        job.rows_imported = source_doc.rows_imported
        message = f"Imported {file_type}: {counters}"
    except Exception as exc:
        logger.exception("Primary data import failed")
        source_doc.parse_status = "ERROR"
        source_doc.parsed_at = datetime.utcnow()
        source_doc.parse_errors = str(exc)[:4000]
        job.status = "FAILED"
        job.finished_at = datetime.utcnow()
        job.files_failed = 1
        job.log = str(exc)[:4000]
        counters = {}
        message = f"Import failed: {exc}"
    finally:
        db.commit()

    return ImportResponse(job_id=job.id, status=job.status, message=message, counters=counters)


@router.post("/bulk-folder")
async def bulk_import_primary_folder(
    payload: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Queue recursive folder import for primary-data packages."""
    folder_path = payload.get("folder_path")
    if not folder_path:
        raise HTTPException(400, "folder_path обязателен")
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(400, f"Папка не найдена или не является директорией: {folder}")

    job = ImportJob(
        job_type="FOLDER_PRIMARY",
        status="RUNNING",
        triggered_by=user.username,
        params_json=json.dumps({"folder_path": str(folder)}, ensure_ascii=False),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    background_tasks.add_task(_bulk_primary_job, job.id, str(folder), user.username)
    return {"job_id": job.id, "status": job.status}


@router.get("/documents")
def list_source_documents(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.execute(
        select(SourceDocument, CDU.name.label("cdu_name"))
        .outerjoin(CDU, SourceDocument.cdu_id == CDU.id)
        .order_by(SourceDocument.uploaded_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": row.SourceDocument.id,
            "filename": row.SourceDocument.file_name,
            "file_type": row.SourceDocument.doc_type,
            "file_size": row.SourceDocument.file_size,
            "import_status": row.SourceDocument.parse_status,
            "imported_at": row.SourceDocument.uploaded_at.isoformat() if row.SourceDocument.uploaded_at else None,
            "imported_by": row.SourceDocument.uploaded_by,
            "source_cdu": row.cdu_name,
            "doc_date": row.SourceDocument.doc_date.isoformat() if row.SourceDocument.doc_date else None,
            "rows_imported": row.SourceDocument.rows_imported,
        }
        for row in rows
    ]


def _detect_file_type(filename: str) -> str:
    f = filename.lower()
    if any(k in f for k in ("trade report", "trade_report", "сделки", "trade")) and f.endswith((".xlsx", ".xlsm")):
        return "trade_report"
    if any(k in f for k in ("holdings", "позиции", "отчет об активах", "активах")) and f.endswith(".xlsx"):
        return "holdings"
    if any(k in f for k in ("сверка", "recon", "reconciliation")) and f.endswith(".xlsx"):
        return "reconciliation"
    if any(k in f for k in ("биржев", "certificate", "cert")) and f.endswith((".pdf", ".png", ".jpg", ".jpeg", ".docx")):
        return "exchange_certificate"
    if any(k in f for k in ("выписка", "statement")) and f.endswith(".pdf"):
        return "pdf_statement"
    return "unknown"


def _run_import(db: Session, file_path: str, file_type: str, source_doc_id: int | None, user: str) -> dict:
    if file_type == "trade_report":
        return import_single_trade_report_xlsx(db, file_path, uploaded_by=user, source_doc_id=source_doc_id)
    if file_type == "holdings":
        return import_holdings_xlsx(db, file_path, uploaded_by=user, source_doc_id=source_doc_id)
    if file_type == "reconciliation":
        return parse_reconciliation_xlsx(file_path)
    if file_type == "exchange_certificate":
        return parse_certificate(file_path)
    if file_type == "pdf_statement":
        return parse_pdf_statement(file_path)
    raise ValueError(f"Unsupported file_type {file_type}")


def _to_doc_type(file_type: str) -> str:
    return {
        "trade_report": "TRADE_REPORT",
        "holdings": "HOLDINGS",
        "reconciliation": "RECONCILIATION",
        "exchange_certificate": "CERTIFICATE",
        "pdf_statement": "STATEMENT_PDF",
    }.get(file_type, "OTHER")


def _finalize_source_doc(db: Session, source_doc: SourceDocument, counters: dict) -> None:
    source_doc.parse_status = "OK"
    source_doc.parsed_at = datetime.utcnow()
    source_doc.parse_meta_json = json.dumps(counters, ensure_ascii=False, default=str)
    source_doc.rows_imported = _count_rows(counters)

    cdu_name = counters.get("cdu_name")
    if cdu_name:
        canonical = normalize_cdu_name(cdu_name) or cdu_name
        cdu = db.execute(select(CDU).where(CDU.name == canonical)).scalars().first()
        if cdu:
            source_doc.cdu_id = cdu.id

    report_date = counters.get("trade_date") or counters.get("report_date")
    if hasattr(report_date, "isoformat"):
        source_doc.doc_date = report_date
    elif isinstance(report_date, str):
        try:
            source_doc.doc_date = datetime.fromisoformat(report_date).date()
        except ValueError:
            pass


def _count_rows(counters: dict) -> int:
    total = 0
    for key in ("trades", "cash_snapshots", "portfolio_positions", "rows_parsed"):
        value = counters.get(key)
        if isinstance(value, int):
            total += value
    return total


def _bulk_primary_job(job_id: int, folder_path: str, user: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(ImportJob, job_id)
        if not job:
            return
        files = [p for p in sorted(Path(folder_path).rglob("*")) if p.is_file()]
        job.files_total = len(files)
        db.commit()

        total_rows = 0
        for path in files:
            file_type = _detect_file_type(path.name)
            if file_type == "unknown":
                continue
            try:
                counters = _run_import(db, str(path), file_type, None, user)
                total_rows += _count_rows(counters)
                job.files_done += 1
            except Exception as exc:
                job.files_failed += 1
                job.log = (job.log or "") + f"\n[ERR] {path}: {exc}"
                logger.warning(f"Failed to import {path.name}: {exc}")
            db.commit()

        job.rows_imported = total_rows
        job.status = "DONE" if job.files_failed == 0 else "PARTIAL"
        job.finished_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        logger.exception("Bulk primary import failed")
        job = db.get(ImportJob, job_id)
        if job:
            job.status = "FAILED"
            job.finished_at = datetime.utcnow()
            job.log = (job.log or "") + f"\n[FATAL] {exc}"
            db.commit()
    finally:
        db.close()
