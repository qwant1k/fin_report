"""Synchronisation of the security master (Справочник ЦБ) with kase.kz.

For an issue the coupon payment schedule and the issue parameters (nominal,
basis, start of circulation, maturity, coupon type/rate, issuer) are
downloaded from the KASE JSON API and stored:

* ``InstrumentReference`` — parameters (overwritten by KASE data, since KASE is
  the registrar's publication; notes and rating are not touched);
* ``CouponSchedule`` — rows with ``source='KASE'``; rows edited or added by a
  user (``source='MANUAL'``) are kept and win for their payment date.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from models.db_models import BondLot, InstrumentReference, SecurityHolding, Trade
from services.kase.instrument_client import KaseInstrumentClient, KaseIssue
from services.portfolio.coupon_schedule import replace_schedule



def _is_isin(value: str) -> bool:
    v = (value or "").strip().upper()
    return len(v) == 12 and v[:2].isalpha() and v[-1].isdigit()


def find_reference(db: Session, identifier: str) -> Optional[InstrumentReference]:
    key = (identifier or "").strip().upper()
    if not key:
        return None
    return db.execute(select(InstrumentReference).where(or_(
        func.upper(InstrumentReference.isin) == key,
        func.upper(InstrumentReference.ticker_kase) == key,
    ))).scalars().first()


def apply_issue(db: Session, issue: KaseIssue, actor: Optional[str]) -> InstrumentReference:
    """Upsert the reference record from KASE data; returns it."""
    ref = None
    if issue.isin:
        ref = find_reference(db, issue.isin)
    if ref is None:
        ref = find_reference(db, issue.code)
    if ref is None:
        ref = InstrumentReference(isin=(issue.isin or issue.code).upper(), source="KASE")
        db.add(ref)
    elif issue.isin and ref.isin != issue.isin and not _is_isin(ref.isin or ""):
        ref.isin = issue.isin            # placeholder (ticker) replaced by the real ISIN
    ref.ticker_kase = issue.code
    for attr, value in (
        ("instrument_name", issue.name), ("issuer", issue.issuer), ("currency", issue.currency),
        ("nominal", issue.nominal), ("base", issue.base), ("start_date", issue.start_date),
        ("maturity_date", issue.maturity_date), ("coupon_type", issue.coupon_type),
        ("frequency", issue.frequency), ("quotation_type", issue.quotation_type),
    ):
        if value not in (None, ""):
            setattr(ref, attr, value)
    if issue.coupon_type == "zero":
        ref.coupon_rate_pct = 0.0
        ref.security_type = ref.security_type or "дисконтная"
    elif issue.coupon_rate_pct is not None:
        ref.coupon_rate_pct = issue.coupon_rate_pct
    if issue.coupon_type == "float":
        last = next((r for r in reversed(issue.schedule) if r.get("margin_pct") is not None), None)
        if last is not None:
            ref.coupon_rate_text = f"индекс + {last['margin_pct']:g}%"
    ref.source = "KASE"
    ref.source_updated_at = datetime.utcnow()
    ref.updated_by = actor
    db.flush()
    return ref


async def fetch_and_apply(db: Session, identifier: str, actor: Optional[str] = None,
                          client: Optional[KaseInstrumentClient] = None) -> dict:
    """Download one issue from KASE and store parameters + schedule."""
    client = client or KaseInstrumentClient()
    ident = (identifier or "").strip()
    ref = find_reference(db, ident)
    code = (ref.ticker_kase if ref is not None and ref.ticker_kase else None)
    isin = (ref.isin if ref is not None and _is_isin(ref.isin or "") else None)
    if code is None and not _is_isin(ident):
        code = ident
    if isin is None and _is_isin(ident):
        isin = ident.upper()
    issue = await client.fetch_issue(code=code, isin=isin)
    ref = apply_issue(db, issue, actor)
    n = replace_schedule(db, ref.isin, issue.schedule, source="KASE", actor=actor, keep_manual=True) \
        if issue.schedule else 0
    return {"isin": ref.isin, "code": issue.code, "rows": n, "coupon_type": issue.coupon_type,
            "maturity_date": issue.maturity_date.isoformat() if issue.maturity_date else None}


async def fetch_many(db: Session, identifiers: Iterable[str], actor: Optional[str] = None,
                     concurrency: int = 4, client: Optional[KaseInstrumentClient] = None) -> dict:
    """Download many issues (bounded concurrency); DB writes stay sequential."""
    client = client or KaseInstrumentClient()
    sem = asyncio.Semaphore(concurrency)
    idents = list(dict.fromkeys(i.strip() for i in identifiers if i and i.strip()))
    plan: List[tuple] = []
    for ident in idents:
        ref = find_reference(db, ident)
        code = ref.ticker_kase if ref is not None and ref.ticker_kase else (None if _is_isin(ident) else ident)
        isin = ref.isin if ref is not None and _is_isin(ref.isin or "") else (ident.upper() if _is_isin(ident) else None)
        plan.append((ident, code, isin))

    async def one(code, isin):
        async with sem:
            return await client.fetch_issue(code=code, isin=isin)

    results = await asyncio.gather(*(one(c, i) for _, c, i in plan), return_exceptions=True)
    ok: Dict[str, int] = {}
    failed: Dict[str, str] = {}
    for (ident, _, _), res in zip(plan, results):
        if isinstance(res, Exception):
            failed[ident] = str(res)[:200]
            continue
        ref = apply_issue(db, res, actor)
        ok[ref.isin] = replace_schedule(db, ref.isin, res.schedule, source="KASE", actor=actor,
                                        keep_manual=True) if res.schedule else 0
    logger.info(f"KASE coupon sync: ok={len(ok)} failed={len(failed)}")
    return {"updated": ok, "failed": failed}


def held_identifiers(db: Session) -> List[str]:
    """ISINs / tickers of bonds currently present in any portfolio source."""
    idents: set = set()
    latest = db.execute(select(func.max(BondLot.valuation_date))).scalar()
    if latest is not None:
        for isin, code in db.execute(select(BondLot.isin, BondLot.instrument_code).where(
            BondLot.valuation_date == latest, BondLot.face_value_current > 0,
        )).all():
            idents.add((code or isin or "").strip())
    for isin, code in db.execute(select(Trade.isin, Trade.instrument_code).where(
        Trade.operation_type == "BUY", Trade.is_active.is_(True),
    )).all():
        idents.add((code or isin or "").strip())
    for isin, code in db.execute(select(SecurityHolding.isin, SecurityHolding.instrument_code).where(
        SecurityHolding.quantity != 0,
    )).all():
        idents.add((code or isin or "").strip())
    return sorted(i for i in idents if i)
