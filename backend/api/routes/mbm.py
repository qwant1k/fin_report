"""MBM index endpoints."""
from __future__ import annotations

from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models.db_models import MBMIndex, User
from models.schemas import MBMOut
from services.mbm import MBMClient

router = APIRouter(prefix="/api/mbm", tags=["mbm"])


@router.get("/", response_model=List[MBMOut])
def list_mbm(days: int = 90, db: Session = Depends(get_db)):
    since = date.today() - timedelta(days=days)
    return list(db.execute(select(MBMIndex).where(
        MBMIndex.index_date >= since,
    ).order_by(MBMIndex.index_date.desc())).scalars().all())


@router.post("/refresh", response_model=MBMOut)
async def refresh_mbm(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    client = MBMClient()
    val = await client.fetch_latest()
    if val is None:
        raise HTTPException(503, "Не удалось получить значение MBM. Введите вручную.")
    obj = db.execute(select(MBMIndex).where(MBMIndex.index_date == val.index_date)).scalars().first()
    if obj:
        obj.ytm_value = val.ytm_value
        obj.duration = val.duration
        obj.source = val.source
    else:
        obj = MBMIndex(
            index_date=val.index_date,
            ytm_value=val.ytm_value,
            duration=val.duration,
            source=val.source,
        )
        db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.post("/manual", response_model=MBMOut)
def manual_mbm(payload: dict, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Manually upsert MBM values for a date."""
    idx_date = payload.get("index_date")
    if isinstance(idx_date, str):
        idx_date = date.fromisoformat(idx_date)
    obj = db.execute(select(MBMIndex).where(MBMIndex.index_date == idx_date)).scalars().first()
    if obj:
        obj.ytm_value = payload.get("ytm_value")
        obj.duration = payload.get("duration")
        obj.source = "manual"
    else:
        obj = MBMIndex(
            index_date=idx_date,
            ytm_value=payload.get("ytm_value"),
            duration=payload.get("duration"),
            source="manual",
        )
        db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
