"""KASE quotes endpoints."""
from __future__ import annotations

from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models.db_models import KasePrice, User
from models.schemas import KasePriceOut
from services.kase import KaseClient
from services.kase.reconciler import reconcile_prices

router = APIRouter(prefix="/api/kase", tags=["kase"])


@router.get("/prices", response_model=List[KasePriceOut])
def list_prices(report_date: date | None = None, db: Session = Depends(get_db)):
    q = select(KasePrice).order_by(KasePrice.trade_date.desc(), KasePrice.instrument_code).limit(1000)
    if report_date:
        q = q.where(KasePrice.trade_date == report_date)
    return list(db.execute(q).scalars().all())


@router.post("/refresh")
async def refresh_kase(report_date: date = Query(...), db: Session = Depends(get_db),
                       user: User = Depends(require_admin)):
    client = KaseClient()
    quotes = await client.fetch_bonds()
    saved = 0
    for q in quotes:
        existing = db.execute(select(KasePrice).where(
            KasePrice.trade_date == report_date,
            KasePrice.instrument_code == q.instrument_code,
        )).scalars().first()
        if existing:
            existing.close_price = q.close_price
            existing.ytm = q.ytm
            existing.accrued_interest = q.accrued_interest
            existing.duration = q.duration
            existing.source = q.source
        else:
            db.add(KasePrice(
                trade_date=report_date,
                instrument_code=q.instrument_code,
                isin=q.isin,
                instrument_name=q.instrument_name,
                close_price=q.close_price,
                ytm=q.ytm,
                accrued_interest=q.accrued_interest,
                duration=q.duration,
                source=q.source,
            ))
            saved += 1
    db.commit()
    return {"fetched": len(quotes), "new_rows": saved, "report_date": report_date}


@router.post("/reconcile")
def reconcile(report_date: date, db: Session = Depends(get_db),
              user: User = Depends(require_admin)):
    rows = reconcile_prices(db, report_date)
    return {"checked": len(rows)}


@router.post("/prices/manual")
def add_manual_price(payload: dict, db: Session = Depends(get_db),
                     user: User = Depends(require_admin)):
    """Allow manual input of KASE quote when scrape failed."""
    price = KasePrice(**payload, source="manual")
    db.add(price)
    db.commit()
    db.refresh(price)
    return price
