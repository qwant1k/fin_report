"""Reports listing — generated XLSX/PDF + raw data exports."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from models.db_models import GeneratedReport, RawTrade

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/")
def list_generated(db: Session = Depends(get_db)):
    return db.query(GeneratedReport).order_by(GeneratedReport.generated_at.desc()).limit(200).all()


@router.get("/{report_id}/download")
def download(report_id: int, db: Session = Depends(get_db)):
    obj = db.get(GeneratedReport, report_id)
    if not obj:
        raise HTTPException(404, "Отчёт не найден")
    return FileResponse(obj.file_path, filename=obj.file_path.split("/")[-1].split("\\")[-1])


@router.get("/raw-trades")
def list_raw_trades(report_date: date | None = None, cdu_id: int | None = None,
                    limit: int = 500, db: Session = Depends(get_db)):
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
