"""MBM index endpoints."""
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import require_permission, require_user
from config import settings
from database import get_db
from models.db_models import MBMIndex, User
from models.schemas import MBMOut
from services.mbm import MBMClient, MBMValue

router = APIRouter(
    prefix="/api/mbm",
    tags=["mbm"],
    dependencies=[Depends(require_permission("page.mbm"))],
)


def _upsert(db: Session, val: MBMValue) -> MBMIndex:
    obj = db.execute(
        select(MBMIndex).where(MBMIndex.index_date == val.index_date)
    ).scalars().first()
    if obj:
        obj.ytm_value = val.ytm_value
        obj.duration = val.duration
        obj.mod_duration = val.mod_duration
        obj.source = val.source
    else:
        obj = MBMIndex(
            index_date=val.index_date,
            ytm_value=val.ytm_value,
            duration=val.duration,
            mod_duration=val.mod_duration,
            source=val.source,
        )
        db.add(obj)
    return obj


@router.get("/", response_model=List[MBMOut])
def list_mbm(
    days: Optional[int] = None,
    start_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    since = start_date or (
        date.today() - timedelta(days=days)
        if days is not None
        else settings.kase_mbm_start_date
    )
    return list(db.execute(select(MBMIndex).where(
        MBMIndex.index_date >= since,
    ).order_by(MBMIndex.index_date.desc())).scalars().all())


@router.post("/refresh", response_model=MBMOut)
async def refresh_mbm(
    target_date: Optional[date] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("mbm.refresh")),
):
    """Подтянуть последнее значение MBM с KASE (или строго на ``target_date``)."""
    client = MBMClient()
    if target_date:
        val = await client.fetch_for_date(target_date)
        if val is None:
            raise HTTPException(503, "Не удалось получить значение MBM. Введите вручную.")
        obj = _upsert(db, val)
        db.commit()
        db.refresh(obj)
        return obj

    rows = await client.fetch_history()
    if not rows:
        raise HTTPException(503, "Не удалось получить значение MBM. Введите вручную.")
    saved: List[MBMIndex] = [_upsert(db, v) for v in rows]
    db.commit()
    latest = saved[0]
    db.refresh(latest)
    return latest


@router.post("/backfill", response_model=List[MBMOut])
async def backfill_mbm(
    start_date: date = settings.kase_mbm_start_date,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("mbm.refresh")),
):
    """Скачать с KASE все значения MBM за диапазон [start_date, end_date] и upsert-ить в БД."""
    end_date = end_date or date.today()
    if end_date < start_date:
        raise HTTPException(400, "end_date должен быть ≥ start_date")
    client = MBMClient()
    rows = await client.fetch_history(start=start_date, end=end_date)
    if not rows:
        raise HTTPException(503, "KASE не вернул данных за диапазон.")
    saved: List[MBMIndex] = [_upsert(db, v) for v in rows]
    db.commit()
    for obj in saved:
        db.refresh(obj)
    return saved


@router.post("/manual", response_model=MBMOut)
def manual_mbm(payload: dict, db: Session = Depends(get_db), user: User = Depends(require_permission("mbm.manual"))):
    """Manually upsert MBM values for a date."""
    idx_date = payload.get("index_date")
    if isinstance(idx_date, str):
        idx_date = date.fromisoformat(idx_date)
    val = MBMValue(
        index_date=idx_date,
        ytm_value=payload.get("ytm_value"),
        duration=payload.get("duration"),
        mod_duration=payload.get("mod_duration"),
        source="manual",
    )
    obj = _upsert(db, val)
    db.commit()
    db.refresh(obj)
    return obj
