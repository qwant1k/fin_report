"""Upload + parse TradeReport files."""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from loguru import logger
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from auth import require_permission, require_user
from config import settings
from database import get_db
from models.db_models import CashMovement, CDU, SourceDocument, Trade, TradeFile, User
from models.schemas import TradeFileBrief, UploadResponse
from services.audit import write_audit
from services.calculator.constants import normalize_cdu_name
from services.kase import apply_kase_prices_to_trades
from services.holdings_sync import sync_holdings
from services.parser.trade_importer import import_trades_from_parsed
from services.parser.trade_ingest import ingest_trade_report, parse_with_cdu_overrides, resolve_cdu

router = APIRouter(
    prefix="/api/upload",
    tags=["upload"],
    dependencies=[Depends(require_permission("page.upload"))],
)

_DUPLICATE_ACTIONS = ("replace", "new_version")


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        logger.warning(f"Could not unlink temp upload {path}")


def _resolve_cdu(db: Session, **kwargs) -> Optional[CDU]:
    return resolve_cdu(db, **kwargs)


def _deactivate_file_trades(db: Session, tf: TradeFile) -> None:
    """Deactivate ledger rows (and their cash legs) imported from ``tf``."""
    doc_ids = [
        d.id for d in db.query(SourceDocument).filter_by(doc_type="TRADE_REPORT", sha256=tf.sha256).all()
    ] if tf.sha256 else []
    if not doc_ids:
        return
    trade_ids = [t.id for t in db.query(Trade).filter(
        Trade.source_doc_id.in_(doc_ids),
        Trade.is_manual == False,  # noqa: E712
        Trade.is_active == True,  # noqa: E712
    ).all()]
    if not trade_ids:
        return
    db.execute(
        sa_update(Trade).where(Trade.id.in_(trade_ids))
        .values(is_active=False, updated_at=datetime.utcnow())
    )
    db.execute(
        sa_update(CashMovement).where(
            CashMovement.related_trade_id.in_(trade_ids),
            CashMovement.is_manual == False,  # noqa: E712
        ).values(is_active=False)
    )


@router.post("/trade-report", response_model=UploadResponse)
def upload_trade_report(
    file: UploadFile = File(...),
    cdu_id: Optional[int] = Form(None),
    trade_date: Optional[str] = Form(None),
    on_duplicate: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("upload.trade_report")),
):
    """Upload a Trade Report XLSX/XLSM, parse, persist and import into the
    Trade ledger as a single atomic transaction.

    Behaviour on duplicate (same SHA-256 already present):

    * ``on_duplicate=None`` → ``409 Conflict`` with metadata of the existing
      file so the UI can prompt the user.
    * ``on_duplicate="replace"`` → soft-deactivate previous Trade rows for
      that ``cdu+date``, hard-delete the previous ``TradeFile`` (and its raw
      rows + on-disk file) and any matching ``SourceDocument``, then proceed.
    * ``on_duplicate="new_version"`` → ignore the duplicate and persist a new
      version with its own ``uploaded_at`` timestamp.
    """
    if not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Принимаются только .xlsx / .xlsm")

    if on_duplicate is not None and on_duplicate not in _DUPLICATE_ACTIONS:
        raise HTTPException(
            400,
            f"on_duplicate должен быть пустым или одним из: {', '.join(_DUPLICATE_ACTIONS)}",
        )

    upload_dir = settings.upload_path
    safe_name = file.filename.replace("/", "_").replace("\\", "_")
    target_path = upload_dir / f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    with target_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    parsed = _parse_with_cdu_overrides(target_path, file.filename, db)
    actor = user.username if user else None

    # ── duplicate detection (idempotency by SHA-256) ──
    duplicate: Optional[TradeFile] = None
    if parsed.sha256:
        duplicate = (
            db.query(TradeFile)
            .filter(TradeFile.sha256 == parsed.sha256, TradeFile.status != "DELETED")
            .order_by(TradeFile.id.desc())
            .first()
        )

    if duplicate is not None:
        if on_duplicate is None:
            _safe_unlink(target_path)
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "duplicate_file",
                    "message": "Файл с таким содержимым уже загружен. Выберите действие: «Заменить» или «Загрузить как новую версию».",
                    "existing": {
                        "file_id": duplicate.id,
                        "filename": duplicate.filename,
                        "uploaded_at": duplicate.uploaded_at.isoformat() if duplicate.uploaded_at else None,
                        "uploaded_by": duplicate.uploaded_by,
                        "cdu_id": duplicate.cdu_id,
                        "trade_date": duplicate.trade_date.isoformat() if duplicate.trade_date else None,
                        "status": duplicate.status,
                        "rows_parsed": duplicate.rows_parsed,
                    },
                },
            )
        if on_duplicate == "replace":
            # Soft-deactivate previous Trade rows so calculations re-build
            # cleanly from the new upload.
            _deactivate_file_trades(db, duplicate)
            # Wipe the previous on-disk file and related SourceDocument(s).
            try:
                if duplicate.raw_file_path:
                    Path(duplicate.raw_file_path).unlink(missing_ok=True)
            except Exception:
                logger.warning(f"Could not remove previous upload {duplicate.raw_file_path}")
            db.query(SourceDocument).filter_by(
                doc_type="TRADE_REPORT", sha256=parsed.sha256,
            ).delete(synchronize_session=False)
            previous_id = duplicate.id
            db.delete(duplicate)
            db.flush()
            write_audit(
                db, user=actor, action="UPLOAD_REPLACE_DUPLICATE",
                entity="TradeFile", entity_id=previous_id,
                details={"sha256": parsed.sha256, "filename": file.filename},
            )
        # on "new_version" we simply continue — both files coexist.

    parsed_date: Optional[date] = None
    if trade_date:
        try:
            parsed_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
        except ValueError:
            _safe_unlink(target_path)
            raise HTTPException(400, "Дата сделки должна быть в формате ГГГГ-ММ-ДД")

    # ── persist + import (single transaction) ──
    try:
        result = ingest_trade_report(
            db,
            path=target_path,
            original_name=file.filename,
            actor=actor,
            cdu_id=cdu_id,
            trade_date=parsed_date,
            parsed=parsed if not cdu_id else None,
        )
        tf, cdu = result.trade_file, result.cdu
        write_audit(
            db, user=actor, action="UPLOAD_TRADE_REPORT",
            entity="TradeFile", entity_id=tf.id,
            details={
                "filename": file.filename,
                "cdu_id": cdu.id if cdu else None,
                "trade_date": result.trade_date.isoformat(),
                "rows_parsed": result.parsed.rows_parsed,
                "rows_skipped": result.parsed.rows_skipped,
                "trades_imported": result.counters.get("trades", 0),
                "superseded_files": result.superseded_file_ids,
                "on_duplicate": on_duplicate,
                "sha256": result.parsed.sha256,
                "price_check": result.price_check,
            },
        )
        db.commit()
    except HTTPException:
        db.rollback()
        _safe_unlink(target_path)
        raise
    except Exception as exc:
        db.rollback()
        _safe_unlink(target_path)
        logger.exception("Trade report upload failed")
        raise HTTPException(500, f"Ошибка обработки файла: {exc}") from exc

    parsed = result.parsed
    if result.counters.get("trades", 0) == 0 and not parsed.warnings:
        parsed.warnings.append("Не удалось импортировать сделки в Trade (возможно, ЧДУ не определён)")
    if result.superseded_file_ids:
        parsed.warnings.append(
            f"Предыдущие файлы этого ЧДУ за ту же дату помечены как заменённые: {result.superseded_file_ids}"
        )

    return UploadResponse(
        file_id=tf.id,
        cdu_id=cdu.id if cdu else None,
        cdu_name=cdu.name if cdu else parsed.cdu_name,
        trade_date=result.trade_date,
        rows_parsed=parsed.rows_parsed,
        rows_skipped=parsed.rows_skipped,
        warnings=parsed.warnings,
        price_check=result.price_check,
        anomalies=result.anomalies,
    )


@router.get("/files", response_model=List[TradeFileBrief])
def list_files(db: Session = Depends(get_db), limit: int = 100):
    rows = db.query(TradeFile).order_by(TradeFile.uploaded_at.desc()).limit(limit).all()
    return rows


@router.get("/files/{file_id}/status")
def get_file_status(file_id: int, db: Session = Depends(get_db)) -> dict:
    """Lightweight status endpoint for UI polling.

    Returns the current ingestion status (``UPLOADED`` / ``PARSED`` /
    ``IMPORTED`` / ``ERROR`` / ``DELETED``) plus parsing counters so the
    frontend can show live progress while the user works on other tasks.
    """
    tf = db.get(TradeFile, file_id)
    if not tf:
        raise HTTPException(404, "Файл не найден")
    return {
        "file_id": tf.id,
        "filename": tf.filename,
        "status": tf.status,
        "cdu_id": tf.cdu_id,
        "trade_date": tf.trade_date.isoformat() if tf.trade_date else None,
        "rows_parsed": tf.rows_parsed,
        "rows_skipped": tf.rows_skipped,
        "uploaded_at": tf.uploaded_at.isoformat() if tf.uploaded_at else None,
        "uploaded_by": tf.uploaded_by,
        "sha256": tf.sha256,
    }


@router.put("/files/{file_id}/cdu")
def set_file_cdu(
    file_id: int, cdu_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("upload.trade_report")),
):
    tf = db.get(TradeFile, file_id)
    if not tf:
        raise HTTPException(404, "Файл не найден")
    cdu = db.get(CDU, cdu_id)
    if not cdu:
        raise HTTPException(404, "ЧДУ не найден")
    tf.cdu_id = cdu.id
    for tr in tf.trades:
        tr.cdu_id = cdu.id
    if tf.sha256:
        for doc in db.query(SourceDocument).filter_by(doc_type="TRADE_REPORT", sha256=tf.sha256).all():
            doc.cdu_id = cdu.id
    import_counters = {"trades": 0}
    path = Path(tf.raw_file_path)
    if path.exists():
        actor = user.username if user else None
        parsed = _parse_with_cdu_overrides(path, tf.filename, db, known_cdu_id=cdu.id)
        parsed.cdu_name = cdu.name
        if tf.trade_date:
            parsed.trade_date = tf.trade_date
        source_doc = None
        if tf.sha256:
            source_doc = db.query(SourceDocument).filter_by(
                doc_type="TRADE_REPORT", sha256=tf.sha256,
            ).first()
        if source_doc is None:
            source_doc = SourceDocument(
                doc_type="TRADE_REPORT",
                cdu_id=cdu.id,
                doc_date=tf.trade_date,
                file_name=tf.filename,
                file_path=tf.raw_file_path,
                sha256=tf.sha256,
                file_size=path.stat().st_size if path.exists() else None,
                uploaded_by=actor,
                parsed_at=datetime.utcnow(),
                parse_status="OK",
                parse_meta_json=json.dumps({"trade_file_id": tf.id}, ensure_ascii=False),
            )
            db.add(source_doc)
            db.flush()
        source_doc.cdu_id = cdu.id
        source_doc.doc_date = tf.trade_date
        import_counters = import_trades_from_parsed(
            db, parsed,
            uploaded_by=actor,
            source_doc_id=source_doc.id,
            commit=False,
            cdu_id=cdu.id,
        )
        source_doc.rows_imported = import_counters.get("trades", 0)
        source_doc.parse_status = "OK"
        tf.status = "IMPORTED"
        if import_counters.get("trades", 0) > 0:
            apply_kase_prices_to_trades(
                db, cdu_id=cdu.id, trade_date=tf.trade_date, actor=actor,
            )
            try:
                sync_holdings(db, cdu_id=cdu.id, actor=actor)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Holdings sync failed for cdu={cdu.id}: {exc!r}")
    write_audit(
        db, user=user.username if user else None,
        action="TRADE_FILE_SET_CDU", entity="TradeFile", entity_id=tf.id,
        details={
            "cdu_id": cdu.id,
            "cdu_name": cdu.name,
            "trades_imported": import_counters.get("trades", 0),
        },
    )
    db.commit()
    return {"ok": True, "cdu_id": cdu.id, "trades": import_counters.get("trades", 0)}


@router.post("/files/{file_id}/import")
def import_file_to_trades(
    file_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("upload.trade_report")),
):
    tf = db.get(TradeFile, file_id)
    if not tf:
        raise HTTPException(404, "Файл не найден")
    path = Path(tf.raw_file_path)
    if not path.exists():
        raise HTTPException(404, "Файл на диске не найден")
    actor = user.username if user else None
    parsed = _parse_with_cdu_overrides(path, tf.filename, db, known_cdu_id=tf.cdu_id)
    if not parsed.cdu_name and tf.cdu_id:
        cdu = db.get(CDU, tf.cdu_id)
        if cdu:
            parsed.cdu_name = cdu.name
    source_doc = db.query(SourceDocument).filter_by(
        doc_type="TRADE_REPORT", sha256=tf.sha256,
    ).first()
    try:
        if source_doc is None:
            source_doc = SourceDocument(
                doc_type="TRADE_REPORT",
                cdu_id=tf.cdu_id,
                doc_date=tf.trade_date,
                file_name=tf.filename,
                file_path=tf.raw_file_path,
                sha256=tf.sha256,
                file_size=path.stat().st_size if path.exists() else None,
                uploaded_by=actor,
                parsed_at=datetime.utcnow(),
                parse_status="OK",
                parse_meta_json=json.dumps({"trade_file_id": tf.id}, ensure_ascii=False),
            )
            db.add(source_doc)
            db.flush()
        if tf.trade_date:
            parsed.trade_date = tf.trade_date
        counters = import_trades_from_parsed(
            db, parsed,
            uploaded_by=actor,
            source_doc_id=source_doc.id,
            commit=False,
            cdu_id=tf.cdu_id,
        )
        source_doc.rows_imported = counters.get("trades", 0)
        tf.status = "IMPORTED"
        write_audit(
            db, user=actor, action="TRADE_FILE_REIMPORT",
            entity="TradeFile", entity_id=tf.id,
            details={"trades": counters.get("trades", 0)},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Trade file re-import failed")
        raise HTTPException(500, f"Ошибка повторного импорта: {exc}") from exc
    return {"ok": True, "trades": counters.get("trades", 0), "warnings": parsed.warnings}


@router.delete("/files/{file_id}")
def delete_file(
    file_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("upload.trade_report")),
):
    tf = db.get(TradeFile, file_id)
    if not tf:
        raise HTTPException(404, "Файл не найден")
    # soft-delete the Trade ledger rows imported from this file only
    # (manual operations and system coupon/redemption events are untouched)
    _deactivate_file_trades(db, tf)
    try:
        Path(tf.raw_file_path).unlink(missing_ok=True)
    except Exception:
        pass
    tf.status = "DELETED"
    write_audit(
        db, user=user.username if user else None,
        action="TRADE_FILE_DELETE", entity="TradeFile", entity_id=tf.id,
        details={"filename": tf.filename, "cdu_id": tf.cdu_id,
                 "trade_date": str(tf.trade_date) if tf.trade_date else None},
    )
    db.commit()
    return {"ok": True, "cdu_id": tf.cdu_id, "trade_date": str(tf.trade_date) if tf.trade_date else None}


# ─────────────── CDU format override helper ───────────────

def _parse_with_cdu_overrides(
    file_path: Path,
    original_name: str,
    db: Session,
    known_cdu_id: Optional[int] = None,
) -> Any:
    return parse_with_cdu_overrides(file_path, original_name, db, known_cdu_id=known_cdu_id)
