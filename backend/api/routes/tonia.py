"""«Рынок → TONIA Compounded»: import of the KASE file and the stored values."""
from __future__ import annotations

from datetime import date
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import require_permission
from config import settings
from database import get_db
from models.db_models import InstrumentReference, ToniaCompounded, User
from services.market import tonia

router = APIRouter(prefix="/api/tonia", tags=["tonia"],
                   dependencies=[Depends(require_permission("page.kase"))])

KASE_PAGE = "https://kase.kz/ru/indexes-and-indicators/repo/tonia-compounded"


@router.get("/")
def list_values(date_from: Optional[date] = Query(None, alias="from"), date_to: Optional[date] = Query(None, alias="to"),
                limit: int = Query(400, ge=1, le=5000), db: Session = Depends(get_db)):
    q = select(ToniaCompounded)
    if date_from:
        q = q.where(ToniaCompounded.calc_date >= date_from)
    if date_to:
        q = q.where(ToniaCompounded.calc_date <= date_to)
    by_date: dict = {}
    for r in db.execute(q.order_by(ToniaCompounded.calc_date.desc())).scalars():
        row = by_date.setdefault(r.calc_date, {"date": r.calc_date.isoformat(), "updated_at": None, "updated_by": None})
        row[r.indicator] = r.value
        if r.updated_at and (row["updated_at"] is None or r.updated_at.isoformat() > row["updated_at"]):
            row["updated_at"] = r.updated_at.isoformat()
            row["updated_by"] = r.updated_by
    rows = list(by_date.values())[:limit]
    floats = db.execute(select(InstrumentReference.isin, InstrumentReference.ticker_kase,
                               InstrumentReference.float_index, InstrumentReference.float_margin_pct,
                               InstrumentReference.coupon_rate_text).where(
        (InstrumentReference.float_index.is_not(None)) | (InstrumentReference.coupon_type == "float"),
    )).all()
    issues = []
    for isin, ticker, index, margin, text in floats:
        if not index:
            index, detected = tonia.detect_index(text)
            margin = margin if margin is not None else detected
        issues.append({"isin": isin, "ticker": ticker, "index": index, "margin_pct": margin, "coupon_text": text})
    issues.sort(key=lambda i: (i["index"] is None, i["ticker"] or i["isin"]))
    total = db.execute(select(func.count(func.distinct(ToniaCompounded.calc_date)))).scalar() or 0
    return {
        "rows": rows,
        "total_dates": total,
        "kase_page": KASE_PAGE,
        "float_issues": issues,
        "auto_fetch": {
            "enabled": settings.kase_tonia_fetch_daily,
            "time": f"{settings.kase_tonia_cron_hour % 24:02d}:{settings.kase_tonia_cron_minute % 60:02d}",
            "timezone": settings.app_tz,
        },
    }


@router.post("/upload")
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db),
                 user: User = Depends(require_permission("kase.refresh"))):
    name = file.filename or "tonia.xlsx"
    if not name.lower().endswith((".xlsx", ".xlsm", ".xls")):
        raise HTTPException(400, "Нужен Excel-файл со страницы KASE «TONIA Compounded»")
    raw = await file.read()
    try:
        counters = tonia.import_archive(
            db,
            raw,
            filename=name,
            actor=user.username,
            source="kase_xlsx",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Не удалось прочитать файл: {exc}")
    db.commit()
    period = (f"{counters['date_from']:%d.%m.%Y}" if counters["date_from"] == counters["date_to"]
              else f"{counters['date_from']:%d.%m.%Y}–{counters['date_to']:%d.%m.%Y}")
    return {**counters,
            "message": (f"TONIA Compounded за {period}: дат {counters['dates']}, новых значений "
                        f"{counters['inserted']}, обновлено {counters['updated']}. Плавающие купоны "
                        "пересчитаются при следующем расчёте сводки.")}


@router.post("/refresh")
async def refresh_from_kase(db: Session = Depends(get_db),
                            user: User = Depends(require_permission("kase.refresh"))):
    try:
        counters = await tonia.refresh_from_kase(db, actor=user.username)
    except (httpx.HTTPError, ValueError) as exc:
        db.rollback()
        raise HTTPException(502, f"KASE TONIA Compounded недоступна: {exc}")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(502, f"Не удалось обновить TONIA Compounded: {exc}")
    db.commit()
    period = (f"{counters['date_from']:%d.%m.%Y}" if counters["date_from"] == counters["date_to"]
              else f"{counters['date_from']:%d.%m.%Y}–{counters['date_to']:%d.%m.%Y}")
    return {
        **counters,
        "message": (
            f"TONIA Compounded обновлена с KASE за {period}: "
            f"новых значений {counters['inserted']}, изменено {counters['updated']}."
        ),
    }


@router.get("/value")
def value_on(indicator: str = Query(...), on: date = Query(..., alias="date"), db: Session = Depends(get_db)):
    found = tonia.ToniaBook(db).value_on(indicator, on)
    if found is None:
        raise HTTPException(404, f"Нет значений {indicator} на {on:%d.%m.%Y} и раньше")
    return {"indicator": indicator.upper(), "date": found[0].isoformat(), "value": found[1],
            "requested": on.isoformat(), "carried": found[0] != on}
