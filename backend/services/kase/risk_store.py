"""Persistence of KASE risk-parameter prices («Расчетные цены_ФР»).

Shared by the API (manual refresh / file upload) and the scheduler, so the
daily job loads both market prices and the risk-parameter prices.  Every row
keeps the valuation date of the file and the source it came from.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.db_models import KaseRiskPrice


def apply_risk_quote(obj: KaseRiskPrice, q, source: Optional[str] = None) -> None:
    obj.valuation_date = getattr(q, "valuation_date", None)
    obj.isin = q.isin
    obj.algo = q.algo
    obj.issuer_name = q.issuer_name
    obj.settlement_price = q.settlement_price
    obj.settlement_dirty_price = q.settlement_dirty_price
    obj.dohod = q.dohod
    obj.ytm = q.ytm
    obj.dtm = q.dtm
    obj.unit_ru = q.unit_ru
    obj.raw_data_json = json.dumps(q.raw_data, ensure_ascii=False, default=str) if q.raw_data else None
    obj.source = (source or q.source or "risk_parameters")[:40]
    if hasattr(obj, "fetched_at"):
        obj.fetched_at = datetime.utcnow()


def store_risk_quotes(db: Session, report_date: date, quotes: Iterable, *,
                      source: Optional[str] = None) -> dict:
    """Upsert the table for ``report_date``; the «Дата оценки» of the file is
    kept in ``valuation_date`` and the origin in ``source``."""
    new_rows = updated = 0
    dates: set = set()
    quotes = list(quotes)
    for q in quotes:
        price_date = report_date
        if getattr(q, "valuation_date", None):
            dates.add(q.valuation_date)
        existing = db.execute(select(KaseRiskPrice).where(
            KaseRiskPrice.trade_date == price_date,
            KaseRiskPrice.instrument_code == q.instrument_code,
        )).scalars().first()
        if existing:
            apply_risk_quote(existing, q, source)
            updated += 1
        else:
            obj = KaseRiskPrice(trade_date=price_date, instrument_code=q.instrument_code)
            apply_risk_quote(obj, q, source)
            db.add(obj)
            new_rows += 1
    db.flush()
    return {"fetched": len(quotes), "new_rows": new_rows, "updated": updated,
            "report_date": report_date.isoformat(),
            "valuation_dates": sorted(d.isoformat() for d in dates)}
