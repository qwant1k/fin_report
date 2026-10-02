"""KASE quotes endpoints."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import require_permission, require_user
from database import get_db
from models.db_models import KasePrice, KaseRiskPrice, User
from models.schemas import KasePriceOut, KaseRiskPriceOut
from services.kase import KaseClient, KaseRiskClient
from services.kase.propagation import apply_kase_update
from services.kase.reconciler import reconcile_prices
from services.audit import write_audit

router = APIRouter(
    prefix="/api/kase",
    tags=["kase"],
    dependencies=[Depends(require_permission("page.kase"))],
)


def _apply_quote(obj: KasePrice, q) -> None:
    obj.isin = q.isin
    obj.instrument_name = q.instrument_name
    obj.close_price = q.close_price
    obj.ytm = q.ytm
    obj.accrued_interest = q.accrued_interest
    obj.duration = q.duration
    obj.sec_type = q.sec_type
    obj.fin_sec_ru = q.fin_sec_ru
    obj.fin_sec_en = q.fin_sec_en
    obj.fin_sec_kz = q.fin_sec_kz
    obj.org_code = q.org_code
    obj.org_name_ru = q.org_name_ru
    obj.org_name_en = q.org_name_en
    obj.org_name_kz = q.org_name_kz
    obj.settlement_price = q.settlement_price
    obj.settlement_dirty_price = q.settlement_dirty_price
    obj.dohod = q.dohod
    obj.dtm = q.dtm
    obj.kase_ytm = q.kase_ytm
    obj.unit_ru = q.unit_ru
    obj.unit_en = q.unit_en
    obj.unit_kz = q.unit_kz
    obj.raw_data_json = json.dumps(q.raw_data, ensure_ascii=False) if q.raw_data else None
    obj.source = q.source


def _apply_risk_quote(obj: KaseRiskPrice, q) -> None:
    obj.valuation_date = q.valuation_date
    obj.isin = q.isin
    obj.algo = q.algo
    obj.issuer_name = q.issuer_name
    obj.settlement_price = q.settlement_price
    obj.settlement_dirty_price = q.settlement_dirty_price
    obj.dohod = q.dohod
    obj.ytm = q.ytm
    obj.dtm = q.dtm
    obj.unit_ru = q.unit_ru
    obj.raw_data_json = json.dumps(q.raw_data, ensure_ascii=False) if q.raw_data else None
    obj.source = q.source


def _store_risk_quotes(db: Session, report_date: date, quotes, source: str = "kase_gateway") -> dict:
    """Upsert the full 'Расчетные цены_ФР' table for report_date."""
    from services.kase.risk_store import store_risk_quotes
    return store_risk_quotes(db, report_date, quotes, source=source)


@router.get("/prices", response_model=List[KasePriceOut])
def list_prices(report_date: date | None = None, db: Session = Depends(get_db)):
    q = select(KasePrice).order_by(KasePrice.trade_date.desc(), KasePrice.instrument_code)
    if report_date:
        q = q.where(KasePrice.trade_date == report_date)
    else:
        q = q.limit(5000)
    return list(db.execute(q).scalars().all())


@router.post("/refresh")
async def refresh_kase(report_date: date = Query(...), db: Session = Depends(get_db),
                       user: User = Depends(require_permission("kase.refresh"))):
    client = KaseClient()
    quotes = await client.fetch_bonds(report_date)
    if not quotes:
        raise HTTPException(503, "KASE не вернул рыночные цены за выбранную дату.")
    saved = 0
    for q in quotes:
        existing = db.execute(select(KasePrice).where(
            KasePrice.trade_date == report_date,
            KasePrice.instrument_code == q.instrument_code,
        )).scalars().first()
        if existing:
            _apply_quote(existing, q)
        else:
            obj = KasePrice(
                trade_date=report_date,
                instrument_code=q.instrument_code,
            )
            _apply_quote(obj, q)
            db.add(obj)
            saved += 1

    # Best-effort: also pull the risk-parameter "Расчетные цены_ФР" workbook so
    # the market→risk fallback has data. A missing/failed file must not abort
    # the market-price refresh.
    risk_result = {"fetched": 0, "new_rows": 0}
    try:
        risk_quotes = await KaseRiskClient().fetch_risk_prices(report_date)
        if risk_quotes:
            risk_result = _store_risk_quotes(db, report_date, risk_quotes)
            db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"KASE risk-params refresh failed for {report_date}: {exc!r}")

    propagation = apply_kase_update(
        db,
        report_date=report_date,
        actor=user.username if user else None,
    )
    db.commit()
    return {
        "fetched": len(quotes),
        "new_rows": saved,
        "risk": risk_result,
        "report_date": report_date,
        "propagation": propagation,
    }


@router.post("/reconcile")
def reconcile(report_date: date, db: Session = Depends(get_db),
              user: User = Depends(require_permission("kase.reconcile"))):
    rows = reconcile_prices(db, report_date)
    return {"checked": len(rows)}


@router.post("/prices/manual")
def add_manual_price(payload: dict, db: Session = Depends(get_db),
                     user: User = Depends(require_permission("kase.manual_price"))):
    """Allow manual/external input of a quote when KASE scrape failed."""
    trade_date = payload.get("trade_date")
    if isinstance(trade_date, str):
        trade_date = date.fromisoformat(trade_date)
    instrument_code = str(payload.get("instrument_code") or "").strip()
    if not trade_date or not instrument_code:
        raise HTTPException(400, "trade_date and instrument_code are required")

    source = str(payload.get("source") or "manual").strip().lower()
    if source not in {"manual", "external", "risk_parameters"}:
        source = "manual"

    existing = db.execute(select(KasePrice).where(
        KasePrice.trade_date == trade_date,
        KasePrice.instrument_code == instrument_code,
    )).scalars().first()
    price = existing or KasePrice(trade_date=trade_date, instrument_code=instrument_code)

    for field in (
        "isin", "instrument_name", "close_price", "ytm", "accrued_interest",
        "duration", "settlement_price", "settlement_dirty_price", "dohod", "dtm",
        "kase_ytm", "unit_ru", "sec_type", "fin_sec_ru",
    ):
        if field in payload:
            setattr(price, field, payload[field])
    price.source = source
    price.fetched_at = datetime.utcnow()
    if existing is None:
        db.add(price)
    db.flush()
    propagation = apply_kase_update(
        db,
        report_date=price.trade_date,
        actor=user.username if user else None,
    )
    db.commit()
    db.refresh(price)
    return {"price": price, "propagation": propagation}


@router.get("/risk/prices", response_model=List[KaseRiskPriceOut])
def list_risk_prices(
    report_date: date | None = None,
    q: str | None = Query(None, description="filter by code / isin / issuer"),
    db: Session = Depends(get_db),
):
    """List stored 'Расчетные цены_ФР' rows (risk-parameter settlement prices)."""
    query = select(KaseRiskPrice).order_by(
        KaseRiskPrice.trade_date.desc(), KaseRiskPrice.instrument_code,
    )
    if report_date:
        query = query.where(KaseRiskPrice.trade_date == report_date)
    else:
        query = query.limit(5000)
    rows = list(db.execute(query).scalars().all())
    if q:
        needle = q.strip().lower()
        rows = [
            r for r in rows
            if needle in (r.instrument_code or "").lower()
            or needle in (r.isin or "").lower()
            or needle in (r.issuer_name or "").lower()
        ]
    return rows


@router.post("/risk/upload")
async def upload_risk_prices(
    file: UploadFile = File(...),
    report_date: Optional[str] = Form(None),
    propagate: bool = Form(True),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("kase.refresh")),
):
    """Load the KASE risk-parameter workbook («Расчетные цены_ФР», .xls/.xlsx)
    downloaded by the user — for servers without access to kase.kz."""
    from services.kase.risk_client import parse_risk_prices_xls
    content = await file.read()
    if not content:
        raise HTTPException(400, "Пустой файл")
    rd = date.fromisoformat(report_date) if report_date else None
    try:
        quotes = parse_risk_prices_xls(content, fallback_date=rd)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Не удалось прочитать файл риск-параметров: {exc}")
    if not quotes:
        raise HTTPException(400, "В файле не найден лист «Расчетные цены_ФР» или он пуст")
    rd = rd or quotes[0].valuation_date
    if rd is None:
        raise HTTPException(400, "В файле нет «Дата оценки» — укажите дату")
    result = _store_risk_quotes(db, rd, quotes, source=f"file:{(file.filename or '')[:34]}")
    propagation = apply_kase_update(db, report_date=rd, actor=user.username if user else None) if propagate else None
    write_audit(db, user=user.username if user else None, action="KASE_RISK_PRICES_UPLOADED",
                entity="KaseRiskPrice", entity_id=None, details={"file": file.filename, **result})
    db.commit()
    return {"report_date": rd, "risk": result, "propagation": propagation}


@router.post("/risk/refresh")
async def refresh_risk_prices(
    report_date: date = Query(...),
    propagate: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("kase.refresh")),
):
    """Download the 'Расчетные цены_ФР' workbook for report_date, store the full
    table, then (optionally) re-run propagation so the market→risk fallback is
    applied to bond lots and summaries."""
    quotes = await KaseRiskClient().fetch_risk_prices(report_date)
    if not quotes:
        raise HTTPException(
            503,
            "KASE не вернул файл риск-параметров (Расчетные цены_ФР) за выбранную дату.",
        )
    result = _store_risk_quotes(db, report_date, quotes)
    db.flush()
    propagation = None
    if propagate:
        propagation = apply_kase_update(
            db, report_date=report_date, actor=user.username if user else None,
        )
    db.commit()
    return {"report_date": report_date, "risk": result, "propagation": propagation}
