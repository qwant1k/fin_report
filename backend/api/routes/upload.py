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

from auth import require_user
from config import settings
from database import get_db
from models.db_models import CDU, CDUFileFormat, RawTrade, SourceDocument, Trade, TradeFile, User
from models.schemas import TradeFileBrief, UploadResponse
from services.audit import write_audit
from services.calculator.constants import normalize_cdu_name
from services.kase import apply_kase_prices_to_trades
from services.holdings_sync import sync_holdings
from services.parser import TradeReportParser
from services.parser.trade_importer import import_trades_from_parsed

router = APIRouter(
    prefix="/api/upload",
    tags=["upload"],
    dependencies=[Depends(require_user)],
)

_DUPLICATE_ACTIONS = ("replace", "new_version")


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        logger.warning(f"Could not unlink temp upload {path}")


def _resolve_cdu(
    db: Session,
    *,
    cdu_id: Optional[int] = None,
    cdu_prefix: Optional[str] = None,
    cdu_name: Optional[str] = None,
) -> Optional[CDU]:
    if cdu_id:
        return db.get(CDU, cdu_id)
    if cdu_prefix:
        cdu = db.query(CDU).filter_by(participant_code_prefix=cdu_prefix).first()
        if cdu:
            return cdu
    canonical = normalize_cdu_name(cdu_name)
    if canonical:
        return db.query(CDU).filter_by(name=canonical).first()
    return None


@router.post("/trade-report", response_model=UploadResponse)
async def upload_trade_report(
    file: UploadFile = File(...),
    cdu_id: Optional[int] = Form(None),
    trade_date: Optional[str] = Form(None),
    on_duplicate: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
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
            if duplicate.cdu_id and duplicate.trade_date:
                db.execute(
                    sa_update(Trade)
                    .where(
                        Trade.cdu_id == duplicate.cdu_id,
                        Trade.trade_date == duplicate.trade_date,
                        Trade.is_active == True,
                    )
                    .values(is_active=False, updated_at=datetime.utcnow())
                )
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

    # ── identify CDU ──
    cdu = _resolve_cdu(
        db,
        cdu_id=cdu_id,
        cdu_prefix=parsed.cdu_prefix,
        cdu_name=parsed.cdu_name,
    )

    if cdu is None:
        parsed.warnings.append("Не удалось определить ЧДУ автоматически — выберите его вручную.")

    if cdu is not None and not parsed.cdu_name:
        parsed.cdu_name = cdu.name

    parsed_date: Optional[date] = parsed.trade_date
    if trade_date:
        try:
            parsed_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
        except ValueError:
            _safe_unlink(target_path)
            raise HTTPException(400, "trade_date должен быть в формате YYYY-MM-DD")

    if not parsed_date:
        parsed.warnings.append("Не удалось определить дату — задайте её явно.")
        parsed_date = date.today()

    # ── persist (single transaction) ──
    tf = TradeFile(
        cdu_id=cdu.id if cdu else None,
        trade_date=parsed_date,
        filename=file.filename,
        raw_file_path=str(target_path),
        status="PARSED",
        rows_parsed=parsed.rows_parsed,
        rows_skipped=parsed.rows_skipped,
        parse_errors_json=json.dumps(
            {"warnings": parsed.warnings, "skipped": parsed.skipped[:50]},
            ensure_ascii=False,
        ),
        sha256=parsed.sha256,
        uploaded_by=actor,
    )

    try:
        db.add(tf)
        db.flush()

        source_doc = SourceDocument(
            doc_type="TRADE_REPORT",
            cdu_id=cdu.id if cdu else None,
            doc_date=parsed_date,
            file_name=file.filename,
            file_path=str(target_path),
            sha256=parsed.sha256,
            file_size=target_path.stat().st_size if target_path.exists() else None,
            uploaded_by=actor,
            parsed_at=datetime.utcnow(),
            parse_status="OK",
            parse_meta_json=json.dumps(
                {"trade_file_id": tf.id, "warnings": parsed.warnings, "skipped": parsed.skipped[:50]},
                ensure_ascii=False,
            ),
            rows_imported=parsed.rows_parsed,
        )
        db.add(source_doc)
        db.flush()

        for pr in parsed.rows:
            f = pr.fields
            db.add(RawTrade(
                file_id=tf.id,
                cdu_id=cdu.id if cdu else None,
                trade_date=f.get("trade_date") or parsed_date,
                deal_number=f.get("deal_number"),
                order_number=f.get("order_number"),
                trade_time=f.get("trade_time"),
                kp=f.get("kp"),
                operation_type=f.get("operation_type"),
                participant_code=f.get("participant_code"),
                firm_code=f.get("firm_code"),
                partner_code=f.get("partner_code"),
                trade_account=f.get("trade_account"),
                regime_code=f.get("regime_code"),
                instrument_code=f.get("instrument_code"),
                instrument_category=f.get("instrument_category"),
                price=f.get("price"),
                lots=f.get("lots"),
                volume=f.get("volume"),
                settlement_date=f.get("settlement_date"),
                accrued_interest_volume=f.get("accrued_interest_volume"),
                yield_pct=f.get("yield_pct"),
                period_code=f.get("period_code"),
                redemption_price=f.get("redemption_price"),
                settlement_code=f.get("settlement_code"),
                type_code=f.get("type_code"),
                commission_total=f.get("commission_total"),
                repo_rate_pct=f.get("repo_rate_pct"),
                accrued_interest_volume_repo=f.get("accrued_interest_volume_repo"),
                repo_sum=f.get("repo_sum"),
                repo_buyback_sum=f.get("repo_buyback_sum"),
                repo_term_days=f.get("repo_term_days"),
                initial_discount_pct=f.get("initial_discount_pct"),
                discount_lower_pct=f.get("discount_lower_pct"),
                discount_upper_pct=f.get("discount_upper_pct"),
                commission_clearing=f.get("commission_clearing"),
                commission_trading=f.get("commission_trading"),
                commission_tech=f.get("commission_tech"),
                client_code=f.get("client_code"),
                currency_code=f.get("currency_code"),
                system_link=f.get("system_link"),
                settlement_org=f.get("settlement_org"),
                trading_date=f.get("trading_date"),
                clearing_firm_code=f.get("clearing_firm_code"),
                activity_flag=f.get("activity_flag"),
                status=f.get("status"),
                nominal_volume=f.get("nominal_volume"),
                clearing_account=f.get("clearing_account"),
                placement_price=f.get("placement_price"),
                placement_amount=f.get("placement_amount"),
                placement_price_kzt=f.get("placement_price_kzt"),
                redemption_price_kzt=f.get("redemption_price_kzt"),
                securities_to_execute=f.get("securities_to_execute"),
            ))

        # ── import into Trade ledger (atomic with the rest) ──
        if not parsed.cdu_name and cdu:
            parsed.cdu_name = cdu.name
        import_counters = import_trades_from_parsed(
            db, parsed,
            uploaded_by=actor,
            source_doc_id=source_doc.id,
            commit=False,
        )
        tf.status = "IMPORTED"

        # ── price reconciliation vs KASE (within same transaction) ──
        price_check: Optional[dict] = None
        if cdu is not None and import_counters.get("trades", 0) > 0:
            price_check = apply_kase_prices_to_trades(
                db, cdu_id=cdu.id, trade_date=parsed_date, actor=actor,
            )

        # ── refresh aggregated SecurityHoldings for this CDU ──
        if cdu is not None:
            try:
                sync_holdings(db, cdu_id=cdu.id, actor=actor)
            except Exception as exc:  # noqa: BLE001
                # Holdings sync is non-critical for the upload itself; log and
                # continue so the user still sees a successful import.
                logger.warning(f"Holdings sync failed for cdu={cdu.id}: {exc!r}")

        write_audit(
            db, user=actor, action="UPLOAD_TRADE_REPORT",
            entity="TradeFile", entity_id=tf.id,
            details={
                "filename": file.filename,
                "cdu_id": cdu.id if cdu else None,
                "trade_date": parsed_date.isoformat(),
                "rows_parsed": parsed.rows_parsed,
                "rows_skipped": parsed.rows_skipped,
                "trades_imported": import_counters.get("trades", 0),
                "on_duplicate": on_duplicate,
                "sha256": parsed.sha256,
                "price_check": price_check,
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

    if import_counters.get("trades", 0) == 0 and not parsed.warnings:
        parsed.warnings.append("Не удалось импортировать сделки в Trade (возможно, ЧДУ не определён)")

    return UploadResponse(
        file_id=tf.id,
        cdu_id=cdu.id if cdu else None,
        cdu_name=cdu.name if cdu else parsed.cdu_name,
        trade_date=parsed_date,
        rows_parsed=parsed.rows_parsed,
        rows_skipped=parsed.rows_skipped,
        warnings=parsed.warnings,
        price_check=price_check,
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
    user: User = Depends(require_user),
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
    user: User = Depends(require_user),
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
        counters = import_trades_from_parsed(
            db, parsed,
            uploaded_by=actor,
            source_doc_id=source_doc.id,
            commit=False,
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
    user: User = Depends(require_user),
):
    tf = db.get(TradeFile, file_id)
    if not tf:
        raise HTTPException(404, "Файл не найден")
    # soft-delete related Trade ledger rows
    if tf.cdu_id and tf.trade_date:
        db.execute(
            sa_update(Trade)
            .where(Trade.cdu_id == tf.cdu_id, Trade.trade_date == tf.trade_date, Trade.is_active == True)
            .values(is_active=False, updated_at=datetime.utcnow())
        )
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
    """Parse trade report, applying per-CDU column-mapping overrides if present.

    1. First pass without overrides to detect CDU (if not known).
    2. Lookup ``CDUFileFormat`` for that CDU.
    3. If active overrides exist → second pass with ``alias_overrides``.
    """
    # First pass — identify CDU prefix.
    first = TradeReportParser(file_path, original_name=original_name).parse()
    cdu_id = known_cdu_id

    if cdu_id is None and first.cdu_prefix:
        cdu = (
            db.query(CDU)
            .filter(CDU.participant_code_prefix == first.cdu_prefix)
            .first()
        )
        if cdu:
            cdu_id = cdu.id
            first.cdu_name = first.cdu_name or cdu.name

    # No overrides possible without a known CDU.
    if cdu_id is None:
        return first

    # Lookup CDU-specific format overrides.
    fmt = (
        db.query(CDUFileFormat)
        .filter(CDUFileFormat.cdu_id == cdu_id, CDUFileFormat.is_active.is_(True))
        .first()
    )
    if not fmt or not fmt.field_aliases:
        return first

    try:
        raw_aliases: dict[str, Any] = json.loads(fmt.field_aliases)
        alias_overrides: dict[str, tuple[str, ...]] = {}
        for key, aliases in raw_aliases.items():
            if isinstance(aliases, list):
                alias_overrides[key] = tuple(str(a) for a in aliases if a)
            elif isinstance(aliases, str):
                alias_overrides[key] = (aliases,)
        if alias_overrides:
            second = TradeReportParser(
                file_path,
                original_name=original_name,
                alias_overrides=alias_overrides,
            ).parse()
            # Preserve CDU metadata from first pass.
            if first.cdu_prefix:
                second.cdu_prefix = first.cdu_prefix
            if first.cdu_name:
                second.cdu_name = first.cdu_name
            return second
    except Exception as exc:
        logger.warning(
            f"Failed to apply CDU format overrides for CDU {cdu_id}: {exc!r}"
        )
    return first
