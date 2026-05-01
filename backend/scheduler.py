"""APScheduler — auto-fetch KASE quotes & MBM index daily."""
from __future__ import annotations

import asyncio
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
from services.mbm import MBMClient

scheduler = AsyncIOScheduler(timezone=settings.app_tz)


async def fetch_kase_job():
    logger.info("Scheduled KASE fetch starting…")
    client = KaseClient()
    quotes = await client.fetch_bonds()
    today = date.today()
    with session_scope() as db:
        for q in quotes:
            existing = db.execute(select(KasePrice).where(
                KasePrice.trade_date == today,
                KasePrice.instrument_code == q.instrument_code,
            )).scalars().first()
            if existing:
                existing.close_price = q.close_price
                existing.ytm = q.ytm
                existing.duration = q.duration
                existing.source = q.source
            else:
                db.add(KasePrice(
                    trade_date=today,
                    instrument_code=q.instrument_code,
                    isin=q.isin,
                    instrument_name=q.instrument_name,
                    close_price=q.close_price,
                    ytm=q.ytm,
                    accrued_interest=q.accrued_interest,
                    duration=q.duration,
                    source=q.source,
                ))
    logger.info(f"KASE fetch done: {len(quotes)} rows")


async def fetch_mbm_job():
    logger.info("Scheduled MBM fetch starting…")
    client = MBMClient()
    val = await client.fetch_latest()
    if not val:
        logger.warning("MBM not available")
        return
    with session_scope() as db:
        existing = db.execute(select(MBMIndex).where(MBMIndex.index_date == val.index_date)).scalars().first()
        if existing:
            existing.ytm_value = val.ytm_value
            existing.duration = val.duration
            existing.source = val.source
        else:
            db.add(MBMIndex(
                index_date=val.index_date,
                ytm_value=val.ytm_value,
                duration=val.duration,
                source=val.source,
            ))
    logger.info(f"MBM fetched: ytm={val.ytm_value} dur={val.duration}")


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
