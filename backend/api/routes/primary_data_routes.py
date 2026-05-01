"""API endpoints for primary data import from custodians (ЧДУ / НБ РК).

Supported files (auto-detected by filename):
  - Trade Report XLSX       (trade_report_* / *сделки*.xlsx / *trade*report*.xlsx)
  - Holdings report XLSX    (*holdings* / *позиции*)
  - Exchange certificate    (*биржев* / *certificate* / *.pdf/.png/.docx)
  - Reconciliation XLSX     (*сверка* / *recon*)
  - PDF statement           (*выписка* / *statement* / *.pdf)
  - Risk Report XLSM        (handled by existing import_routes — kept separate)
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, BackgroundTasks
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select

from database import get_db
from auth import require_admin
from database import SessionLocal
from models.db_models import ImportJob, SourceDocument
from services.parser.trade_importer import import_single_trade_report_xlsx
from services.import_primary.holdings_parser import import_holdings_xlsx
from services.import_primary.cert_parser import parse_certificate
from services.import_primary.recon_parser import parse_reconciliation_xlsx
from services.import_primary.statement_parser import parse_pdf_statement

router = APIRouter(prefix="/api/primary-data", tags=["primary-data"])


class ImportResponse(BaseModel):
    job_id: int
    status: str
    message: str
    counters: dict = {}


@router.post("/upload", response_model=ImportResponse)
async def upload_primary_data(
    file: UploadFile = File(...),
    db=Depends(get_db),
    user: str = Depends(require_admin),
):
    """Upload a single primary-data file and import immediately."""
    original_name = file.filename or "unnamed"
    file_type = _detect_file_type(original_name)

    if file_type == "unknown":
        raise HTTPException(400, f"Cannot detect file type for '{original_name}'")

    # Save to temp
    suffix = Path(original_name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    # SHA256 + dedup
    import hashlib
    sha = hashlib.sha256(content).hexdigest()
    dup = db.query(SourceDocument).filter_by(file_sha256=sha).first()
    if dup:
        os.unlink(tmp_path)
        return ImportResponse(
            job_id=-1, status="skipped",
            message=f"Duplicate of already imported document id={dup.id} ({dup.filename})",
        )

    # Record SourceDocument
    src = SourceDocument(
        filename=original_name, file_type=file_type,
        file_sha256=sha, file_size=len(content),
        source_cdu=None,  # resolved by parser
        import_status="importing", imported_by=user,
        imported_at=datetime.utcnow(),
    )
    db.add(src); db.flush()

    # ImportJob
    job = ImportJob(
        job_type="primary_data", source_doc_id=src.id,
        status="running", started_at=datetime.utcnow(),
        filename=original_name, uploaded_by=user,
    )
    db.add(job); db.flush()

    try:
        counters = _run_import(db, tmp_path, file_type, src.id, user)
        src.import_status = "completed"
        job.status = "completed"
        job.finished_at = datetime.utcnow()
        job.records_inserted = counters.get("trades", 0) + counters.get("positions", 0)
        msg = f"Imported {file_type}: {counters}"
    except Exception as exc:
        logger.exception("Primary data import failed")
        src.import_status = "error"
        job.status = "failed"
        job.finished_at = datetime.utcnow()
        job.error_message = str(exc)[:4000]
        msg = f"Import failed: {exc}"
        counters = {}
    finally:
        db.commit()
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return ImportResponse(job_id=job.id, status=job.status, message=msg, counters=counters)


@router.post("/bulk-folder")
async def bulk_import_primary_folder(
    folder_path: str,
    background_tasks: BackgroundTasks,
    user: str = Depends(require_admin),
):
    """Queue a folder for background import (admin only)."""
    from api.routes.import_routes import _bulk_import_job  # reuse helper
    job = ImportJob(
        job_type="primary_bulk", status="queued",
        started_at=datetime.utcnow(), folder_path=folder_path,
        uploaded_by=user,
    )
    db = next(get_db())
    db.add(job); db.commit(); db.refresh(job)
    background_tasks.add_task(_bulk_primary_job, job.id, folder_path, user)
    return {"job_id": job.id, "status": "queued"}


# ───────── helpers ─────────

def _detect_file_type(filename: str) -> str:
    f = filename.lower()
    if any(k in f for k in ("trade report", "trade_report", "сделки", "trade")) and f.endswith(".xlsx"):
        return "trade_report"
    if any(k in f for k in ("holdings", "позиции")) and f.endswith(".xlsx"):
        return "holdings"
    if any(k in f for k in ("сверка", "recon", "reconciliation")) and f.endswith(".xlsx"):
        return "reconciliation"
    if any(k in f for k in ("биржев", "certificate", "cert")) and any(f.endswith(e) for e in (".pdf", ".png", ".docx")):
        return "exchange_certificate"
    if any(k in f for k in ("выписка", "statement")) and f.endswith(".pdf"):
        return "pdf_statement"
    return "unknown"


def _run_import(db, tmp_path: str, file_type: str, source_doc_id: int, user: str):
    if file_type == "trade_report":
        return import_single_trade_report_xlsx(db, tmp_path, uploaded_by=user, source_doc_id=source_doc_id)
    if file_type == "holdings":
        return import_holdings_xlsx(db, tmp_path, uploaded_by=user, source_doc_id=source_doc_id)
    if file_type == "reconciliation":
        return parse_reconciliation_xlsx(tmp_path)
    if file_type == "exchange_certificate":
        return parse_certificate(tmp_path)
    if file_type == "pdf_statement":
        return parse_pdf_statement(tmp_path)
    raise ValueError(f"Unsupported file_type {file_type}")


@router.get("/documents")
def list_source_documents(limit: int = 50, db: Session = Depends(get_db)):
    try:
        from models.db_models import CDU
        rows = db.execute(
            select(SourceDocument, CDU.name.label("cdu_name"))
            .outerjoin(CDU, SourceDocument.cdu_id == CDU.id)
            .order_by(SourceDocument.uploaded_at.desc())
            .limit(limit)
        ).all()
        return [
            {
                "id": r.SourceDocument.id,
                "filename": r.SourceDocument.file_name,
                "file_type": r.SourceDocument.doc_type,
                "file_size": r.SourceDocument.file_size,
                "import_status": r.SourceDocument.parse_status,
                "imported_at": r.SourceDocument.uploaded_at.isoformat() if r.SourceDocument.uploaded_at else None,
                "imported_by": r.SourceDocument.uploaded_by,
                "source_cdu": r.cdu_name,
            }
            for r in rows
        ]
    except Exception as exc:
        logger.exception("Error listing source documents")
        raise HTTPException(500, f"Server error: {exc}")


def _bulk_primary_job(job_id: int, folder_path: str, user: str):
    db = SessionLocal()
    try:
        job = db.query(ImportJob).get(job_id)
        if not job:
            return
        job.status = "running"
        db.commit()
        p = Path(folder_path)
        if not p.exists():
            raise FileNotFoundError(f"Folder not found: {folder_path}")

        total_counters: dict = {}
        for f in sorted(p.iterdir()):
            if f.is_dir():
                continue
            ft = _detect_file_type(f.name)
            if ft == "unknown":
                continue
            try:
                counters = _run_import(db, str(f), ft, None, user)
                for k, v in counters.items():
                    total_counters[k] = total_counters.get(k, 0) + (v if isinstance(v, int) else 0)
            except Exception as exc:
                logger.warning(f"Failed to import {f.name}: {exc}")

        job.status = "completed"
        job.finished_at = datetime.utcnow()
        job.records_inserted = total_counters.get("trades", 0)
        db.commit()
    except Exception as exc:
        logger.exception("Bulk primary import failed")
        job = db.query(ImportJob).get(job_id)
        if job:
            job.status = "failed"
            job.error_message = str(exc)[:4000]
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
