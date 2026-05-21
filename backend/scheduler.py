"""APScheduler — auto-fetch KASE quotes & MBM index daily."""
from __future__ import annotations

import asyncio
import json
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from sqlalchemy import select

from config import settings
from database import session_scope
from models.db_models import KasePrice, MBMIndex
from services.automation.coupon_redemption_engine import run_daily_auto_events
from services.automation.fifo_engine import process_all_sell_fifo
from services.automation.ar_closer import close_ar_items
from services.kase import KaseClient
from services.kase.propagation import apply_kase_update
from services.mbm import MBMClient

scheduler = AsyncIOScheduler(timezone=settings.app_tz)


async def fetch_kase_job():
    logger.info("Scheduled KASE fetch starting…")
    client = KaseClient()
    today = date.today()
    quotes = await client.fetch_bonds(today)
    with session_scope() as db:
        for q in quotes:
            existing = db.execute(select(KasePrice).where(
                KasePrice.trade_date == today,
                KasePrice.instrument_code == q.instrument_code,
            )).scalars().first()
            if existing:
                _apply_kase_quote(existing, q)
            else:
                obj = KasePrice(
                    trade_date=today,
                    instrument_code=q.instrument_code,
                )
                _apply_kase_quote(obj, q)
                db.add(obj)
        propagation = apply_kase_update(db, report_date=today, actor="scheduler")
    logger.info(f"KASE fetch done: {len(quotes)} rows; propagation={propagation}")


def _apply_kase_quote(obj: KasePrice, q) -> None:
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


async def fetch_mbm_job():
    logger.info("Scheduled MBM fetch starting…")
    client = MBMClient()
    rows = await client.fetch_history()
    if not rows:
        logger.warning("MBM not available")
        return
    with session_scope() as db:
        for val in rows:
            existing = db.execute(select(MBMIndex).where(MBMIndex.index_date == val.index_date)).scalars().first()
            if existing:
                existing.ytm_value = val.ytm_value
                existing.duration = val.duration
                existing.mod_duration = val.mod_duration
                existing.source = val.source
            else:
                db.add(MBMIndex(
                    index_date=val.index_date,
                    ytm_value=val.ytm_value,
                    duration=val.duration,
                    mod_duration=val.mod_duration,
                    source=val.source,
                ))
    val = rows[0]
    logger.info(
        f"MBM fetched: rows={len(rows)} idx={val.ytm_value} dur={val.duration} "
        f"moddur={val.mod_duration} src={val.source}"
    )


async def daily_automation_job():
    today = date.today()
    logger.info(f"Scheduled daily automation starting for {today}…")
    with session_scope() as db:
        events = run_daily_auto_events(db, today)
        fifo = process_all_sell_fifo(db, today)
        ar = close_ar_items(db, today)
    logger.info(f"Daily automation done: events={events}, fifo={fifo}, ar={ar}")


def start_scheduler() -> None:
    kase_h = settings.kase_fetch_cron_hour % 24
    kase_m = settings.kase_fetch_cron_minute % 60
    mbm_total = kase_h * 60 + kase_m + 5
    mbm_h = (mbm_total // 60) % 24
    mbm_m = mbm_total % 60

    scheduler.add_job(
        fetch_kase_job,
        CronTrigger(hour=kase_h, minute=kase_m),
        id="kase_fetch",
        replace_existing=True,
    )
    scheduler.add_job(
        fetch_mbm_job,
        CronTrigger(hour=mbm_h, minute=mbm_m),
        id="mbm_fetch",
        replace_existing=True,
    )
    # Daily automation: 15 min after MBM
    auto_total = mbm_h * 60 + mbm_m + 15
    auto_h = (auto_total // 60) % 24
    auto_m = auto_total % 60
    scheduler.add_job(
        daily_automation_job,
        CronTrigger(hour=auto_h, minute=auto_m),
        id="daily_automation",
        replace_existing=True,
    )
    if not scheduler.running:
        scheduler.start()
    logger.info(
        f"Scheduler started: KASE @{kase_h:02d}:{kase_m:02d}, "
        f"MBM @{mbm_h:02d}:{mbm_m:02d}, AUTO @{auto_h:02d}:{auto_m:02d}"
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
