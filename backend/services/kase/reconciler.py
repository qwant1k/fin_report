"""Sweep portfolio positions vs KASE prices, populate price_reconciliation."""
from __future__ import annotations

from datetime import date
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.db_models import KasePrice, PortfolioPosition, PriceReconciliation


def reconcile_prices(db: Session, report_date: date) -> List[PriceReconciliation]:
    positions = db.execute(select(PortfolioPosition).where(
        PortfolioPosition.position_date == report_date,
        PortfolioPosition.instrument_code.is_not(None),
    )).scalars().all()
    kase_rows = {kp.instrument_code: kp for kp in db.execute(select(KasePrice).where(
        KasePrice.trade_date == report_date,
    )).scalars().all()}

    out: List[PriceReconciliation] = []
    for pos in positions:
        if not pos.instrument_code or pos.instrument_code not in kase_rows:
            continue
        kase = kase_rows[pos.instrument_code]
        cdu_price = pos.current_price
        kase_price = kase.close_price
        if not (cdu_price and kase_price):
            continue
        dev = abs(cdu_price - kase_price) / kase_price * 100.0
        status = "OK" if dev < 0.1 else ("WARN" if dev < 0.5 else "ERROR")
        rec = PriceReconciliation(
            position_id=pos.id,
            kase_price_id=kase.id,
            cdu_price=cdu_price,
            kase_price=kase_price,
            deviation_pct=dev,
            deviation_kzt=(cdu_price - kase_price),
            status=status,
        )
        db.add(rec)
        out.append(rec)
    db.commit()
    return out
