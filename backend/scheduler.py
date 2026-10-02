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
    today = _today()
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
        # risk-parameter prices («Расчетные цены_ФР») — the fallback valuation
        # for bonds without a market price; must be loaded every day as well
        risk_result = {"fetched": 0}
        try:
            from services.kase import KaseRiskClient
            from services.kase.risk_store import store_risk_quotes
            risk_quotes = await KaseRiskClient().fetch_risk_prices(today)
            if risk_quotes:
                risk_result = store_risk_quotes(db, today, risk_quotes, source="kase_gateway")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Scheduled KASE risk-params fetch failed: {exc!r}")
        # coupon schedules of held bonds (floating coupons get a new index
        # value every period) — KASE data, manual rows are kept
        coupon_result = {}
        if settings.kase_coupon_refresh_daily:
            try:
                from services.kase.coupon_sync import fetch_many, held_identifiers
                coupon_result = await fetch_many(db, held_identifiers(db), "scheduler")
                coupon_result = {"updated": len(coupon_result["updated"]), "failed": len(coupon_result["failed"])}
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Scheduled KASE coupon schedule refresh failed: {exc!r}")
        propagation = apply_kase_update(db, report_date=today, actor="scheduler")
    logger.info(f"KASE fetch done: {len(quotes)} rows; risk={risk_result}; coupons={coupon_result}; "
                f"propagation={propagation}")


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


def _today() -> date:
    """Business date in the configured time zone (server may run in UTC)."""
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        return datetime.now(ZoneInfo(settings.app_tz)).date()
    except Exception:  # pragma: no cover - tz database missing
        return date.today()


def _last_automation_date(db) -> date | None:
    from models.db_models import AuditLog
    row = db.execute(select(AuditLog).where(
        AuditLog.action == "DAILY_AUTOMATION",
    ).order_by(AuditLog.ts.desc())).scalars().first()
    if row and row.details:
        try:
            return date.fromisoformat(json.loads(row.details).get("target_date"))
        except (ValueError, TypeError, AttributeError):
            return None
    return None


async def daily_automation_job():
    """Coupons/redemptions → FIFO control → AR closing → portfolio for the day.

    Events are generated for every calendar day since the last successful run
    (max 31 days back), so a server that was down over a weekend does not
    silently skip a coupon or a maturity (they are exact-date events).
    """
    from datetime import timedelta
    from services.audit import write_audit
    from services.calculator.portfolio_calculator import calculate_for_date

    today = _today()
    logger.info(f"Scheduled daily automation starting for {today}…")
    with session_scope() as db:
        last = _last_automation_date(db)
        start = (last + timedelta(days=1)) if last else today
        start = max(start, today - timedelta(days=31))
        day = start
        summary = {}
        while day <= today:
            events = run_daily_auto_events(db, day)
            fifo = process_all_sell_fifo(db, day)
            ar = close_ar_items(db, day)
            calc = calculate_for_date(db, day)
            summary[day.isoformat()] = {"events": events, "fifo": fifo, "ar": ar, "calc": calc}
            write_audit(db, user="scheduler", action="DAILY_AUTOMATION", entity="Automation",
                        details={"target_date": day.isoformat(), "calc": calc})
            db.commit()
            day += timedelta(days=1)
    logger.info(f"Daily automation done: {summary}")


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
