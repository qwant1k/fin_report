"""Endpoints для импорта Risk Report XLSM (одиночный + bulk-папка) и просмотра ImportJob."""
from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import require_admin
from config import settings
from database import SessionLocal, get_db
from models.db_models import ImportJob, SourceDocument, User
from services.import_rr import (
    import_folder,
    import_risk_report,
)

router = APIRouter(prefix="/api/import", tags=["import"])


# ─────────── Single-file upload (XLSM Risk Report) ───────────
@router.post("/risk-report")
async def upload_single_rr(
    file: UploadFile = File(...),
    skip_if_imported: bool = Form(True),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Загрузка одного Risk Report XLSM. Сохраняется в uploads/risk_reports/, импортируется синхронно."""
    if not file.filename.lower().endswith(('.xlsm', '.xlsx')):
        raise HTTPException(400, "Принимаются только XLSM/XLSX файлы")

    target_dir = settings.upload_path / "risk_reports"
    target_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    target = target_dir / f"{ts}_{file.filename}"
    with target.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    result = import_risk_report(
        db, target,
        uploaded_by=user.username,
        skip_if_imported=skip_if_imported,
    )
    return {
        "file_path": str(target),
        "file_date": result.file_date.isoformat() if result.file_date else None,
        "source_doc_id": result.source_doc_id,
        "skipped": result.skipped,
        "error": result.error,
        "warnings": result.warnings,
        "rows": {
            "cash": result.cash_rows,
            "mv": result.mv_rows,
            "reference": result.reference_rows,
            "fx": result.fx_rows,
            "mbm": result.mbm_rows,
            "bond_lots": result.bond_lots,
            "repo_lots": result.repo_lots,
            "deposit_lots": result.deposit_lots,
            "accounts_receivable": result.ar_rows,
            "report_summaries": result.report_summaries,
            "report_positions": result.report_positions,
        },
    }


# ─────────── Bulk folder import (background) ───────────
@router.post("/risk-report/bulk-folder")
async def import_rr_folder(
    payload: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Запустить bulk-импорт всех XLSM-файлов из указанной папки на сервере.

    Запрос: { "folder_path": "...", "pattern": "**/*.xlsm" }
    Возвращает job_id; обрабатывается в фоне.
    """
    folder_str = payload.get("folder_path")
    if not folder_str:
        raise HTTPException(400, "folder_path обязателен")
    folder = Path(folder_str)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(400, f"Папка не найдена или не является директорией: {folder}")

    pattern = payload.get("pattern", "**/*.xlsm")

    # Создать ImportJob сразу, чтобы фронт мог поллить
    job = ImportJob(
        job_type="HISTORIC_RR",
        status="RUNNING",
        triggered_by=user.username,
        params_json=json.dumps({"folder": str(folder), "pattern": pattern}),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id

    def _run():
        # Открыть отдельную сессию для фоновой задачи
        with SessionLocal() as bg_db:
            try:
                fresh_job = bg_db.get(ImportJob, job_id)
                import_folder(
                    bg_db, folder,
                    uploaded_by=user.username,
                    job=fresh_job,
                    pattern=pattern,
                )
            except Exception as exc:
                logger.exception(f"Bulk import job {job_id} failed")
                fresh_job = bg_db.get(ImportJob, job_id)
                if fresh_job:
                    fresh_job.status = "FAILED"
                    fresh_job.finished_at = datetime.utcnow()
                    fresh_job.log = (fresh_job.log or "") + f"\n[FATAL] {exc!r}"
                    bg_db.commit()

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "RUNNING", "folder": str(folder)}


# ─────────── ImportJob status / list ───────────
@router.get("/jobs")
def list_jobs(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.execute(
        select(ImportJob).order_by(ImportJob.started_at.desc()).limit(limit)
    ).scalars().all()
    return [
        {
            "id": j.id,
            "job_type": j.job_type,
            "status": j.status,
            "triggered_by": j.triggered_by,
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            "files_total": j.files_total,
            "files_done": j.files_done,
            "files_failed": j.files_failed,
            "rows_imported": j.rows_imported,
        }
        for j in rows
    ]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    j = db.get(ImportJob, job_id)
    if not j:
        raise HTTPException(404, "ImportJob не найден")
    return {
        "id": j.id,
        "job_type": j.job_type,
        "status": j.status,
        "triggered_by": j.triggered_by,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        "files_total": j.files_total,
        "files_done": j.files_done,
        "files_failed": j.files_failed,
        "rows_imported": j.rows_imported,
        "log": j.log or "",
        "params": json.loads(j.params_json) if j.params_json else None,
    }


# ─────────── SourceDocument browse ───────────
@router.get("/documents")
def list_documents(
    doc_type: Optional[str] = None,
    cdu_id: Optional[int] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    q = select(SourceDocument).order_by(SourceDocument.uploaded_at.desc()).limit(limit)
    if doc_type:
        q = q.where(SourceDocument.doc_type == doc_type)
    if cdu_id:
        q = q.where(SourceDocument.cdu_id == cdu_id)
    rows = db.execute(q).scalars().all()
    return [
        {
            "id": d.id,
            "doc_type": d.doc_type,
            "cdu_id": d.cdu_id,
            "doc_date": d.doc_date.isoformat() if d.doc_date else None,
            "file_name": d.file_name,
            "file_path": d.file_path,
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            "uploaded_by": d.uploaded_by,
            "parsed_at": d.parsed_at.isoformat() if d.parsed_at else None,
            "parse_status": d.parse_status,
            "rows_imported": d.rows_imported,
        }
        for d in rows
    ]
