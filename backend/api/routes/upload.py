"""Upload + parse TradeReport files."""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.db_models import CDU, RawTrade, TradeFile
from models.schemas import TradeFileBrief, UploadResponse
from services.parser import TradeReportParser
from services.parser.trade_importer import import_trades_from_parsed

router = APIRouter(prefix="/api/upload", tags=["upload"])


@router.post("/trade-report", response_model=UploadResponse)
async def upload_trade_report(
    file: UploadFile = File(...),
    cdu_id: Optional[int] = Form(None),
    trade_date: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    if not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Принимаются только .xlsx / .xlsm")

    upload_dir = settings.upload_path
    safe_name = file.filename.replace("/", "_").replace("\\", "_")
    target_path = upload_dir / f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    with target_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    parser = TradeReportParser(target_path, original_name=file.filename)
    parsed = parser.parse()

    # ── identify CDU ──
    cdu: Optional[CDU] = None
    if cdu_id:
        cdu = db.get(CDU, cdu_id)
    elif parsed.cdu_prefix:
        cdu = db.query(CDU).filter_by(participant_code_prefix=parsed.cdu_prefix).first()

    if cdu is None:
        # сохранили файл, но без cdu — UI попросит выбрать вручную через PUT
        warning = "Не удалось определить ЧДУ автоматически — выберите его вручную."
        parsed.warnings.append(warning)

    parsed_date: Optional[date] = parsed.trade_date
    if trade_date:
        try:
            parsed_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "trade_date должен быть в формате YYYY-MM-DD")

    if not parsed_date:
        parsed.warnings.append("Не удалось определить дату — задайте её явно.")
        parsed_date = date.today()

    # ── persist ──
    tf = TradeFile(
        cdu_id=cdu.id if cdu else None,
        trade_date=parsed_date,
        filename=file.filename,
        raw_file_path=str(target_path),
        status="PARSED",
        rows_parsed=parsed.rows_parsed,
        rows_skipped=parsed.rows_skipped,
        parse_errors_json=json.dumps({"warnings": parsed.warnings, "skipped": parsed.skipped[:50]}, ensure_ascii=False),
        sha256=parsed.sha256,
    )
    db.add(tf)
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
    db.commit()

    # ── import into Trade ledger (used by Positions / calculations) ──
    if not parsed.cdu_name and cdu:
        parsed.cdu_name = cdu.name
    import_counters = import_trades_from_parsed(
        db, parsed, uploaded_by=None, source_doc_id=tf.id
    )
    tf.status = "IMPORTED"
    db.commit()

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
    )


@router.get("/files", response_model=List[TradeFileBrief])
def list_files(db: Session = Depends(get_db), limit: int = 100):
    rows = db.query(TradeFile).order_by(TradeFile.uploaded_at.desc()).limit(limit).all()
    return rows


@router.put("/files/{file_id}/cdu")
def set_file_cdu(file_id: int, cdu_id: int, db: Session = Depends(get_db)):
    tf = db.get(TradeFile, file_id)
    if not tf:
        raise HTTPException(404, "Файл не найден")
    cdu = db.get(CDU, cdu_id)
    if not cdu:
        raise HTTPException(404, "ЧДУ не найден")
    tf.cdu_id = cdu.id
    for tr in tf.trades:
        tr.cdu_id = cdu.id
    db.commit()
    return {"ok": True, "cdu_id": cdu.id}


@router.post("/files/{file_id}/import")
def import_file_to_trades(file_id: int, db: Session = Depends(get_db)):
    tf = db.get(TradeFile, file_id)
    if not tf:
        raise HTTPException(404, "Файл не найден")
    path = Path(tf.raw_file_path)
    if not path.exists():
        raise HTTPException(404, "Файл на диске не найден")
    parsed = TradeReportParser(path, original_name=tf.filename).parse()
    # Если парсер не определил ЧДУ, но в TradeFile уже назначен — подставим
    if not parsed.cdu_name and tf.cdu_id:
        cdu = db.get(CDU, tf.cdu_id)
        if cdu:
            parsed.cdu_name = cdu.name
    counters = import_trades_from_parsed(db, parsed, uploaded_by=None, source_doc_id=tf.id)
    tf.status = "IMPORTED"
    db.commit()
    return {"ok": True, "trades": counters.get("trades", 0), "warnings": parsed.warnings}


@router.delete("/files/{file_id}")
def delete_file(file_id: int, db: Session = Depends(get_db)):
    from sqlalchemy import update as sa_update
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
    db.commit()
    return {"ok": True, "cdu_id": tf.cdu_id, "trade_date": str(tf.trade_date) if tf.trade_date else None}
