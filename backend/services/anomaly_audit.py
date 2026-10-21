"""Fast, read-only anomaly checks for a freshly imported Trade Report."""
from __future__ import annotations

from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from models.db_models import Trade


def _trade_label(row: Trade) -> str:
    return row.instrument_code or row.isin or row.deal_id or f"Операция #{row.id}"


def audit_uploaded_trades(
    db: Session,
    *,
    cdu_id: int,
    source_doc_id: int,
    trade_date,
) -> list[dict[str, Any]]:
    """Return concise cards for price and amount deviations.

    The check does not change imported data. Price deviations reuse the KASE
    reconciliation result. Amount deviations compare a row with earlier active
    rows of the same CDU, operation type and instrument.
    """
    current = list(db.execute(select(Trade).where(
        Trade.cdu_id == cdu_id,
        Trade.source_doc_id == source_doc_id,
        Trade.is_active.is_(True),
    )).scalars())
    anomalies: list[dict[str, Any]] = []

    for row in current:
        if row.price_flag and row.price_original is not None and row.price_kase is not None:
            anomalies.append({
                "kind": "price",
                "severity": "warning",
                "title": f"Цена {_trade_label(row)} отличается от KASE",
                "message": (
                    f"В файле {row.price_original:,.4f}; KASE {row.price_kase:,.4f}; "
                    f"отклонение {(row.price_diff_pct or 0) * 100:.2f}%."
                ),
                "actual": row.price_original,
                "baseline": row.price_kase,
                "deviation_pct": row.price_diff_pct,
                "tolerance_pct": settings.price_tolerance_pct,
                "source": "KASE",
                "trade_id": row.id,
            })

        amount = abs(float(row.amount_kzt or 0.0))
        if amount <= 0:
            continue
        history_stmt = select(Trade).where(
            Trade.cdu_id == cdu_id,
            Trade.is_active.is_(True),
            Trade.source_doc_id != source_doc_id,
            Trade.trade_date < trade_date,
            Trade.operation_type == row.operation_type,
        )
        if row.instrument_code:
            history_stmt = history_stmt.where(Trade.instrument_code == row.instrument_code)
        elif row.isin:
            history_stmt = history_stmt.where(Trade.isin == row.isin)
        else:
            history_stmt = history_stmt.where(Trade.instrument_code.is_(None), Trade.isin.is_(None))
        history = list(db.execute(
            history_stmt.order_by(Trade.trade_date.desc(), Trade.id.desc()).limit(
                max(1, settings.upload_anomaly_history_limit)
            )
        ).scalars())
        samples = [abs(float(item.amount_kzt or 0.0)) for item in history if item.amount_kzt]
        if not samples:
            continue
        baseline = mean(samples)
        if baseline <= 0:
            continue
        deviation = abs(amount - baseline) / baseline
        if deviation <= settings.upload_amount_tolerance_pct:
            continue
        anomalies.append({
            "kind": "amount",
            "severity": "critical" if deviation >= settings.upload_amount_tolerance_pct * 2 else "warning",
            "title": f"Сумма {_trade_label(row)} нетипична",
            "message": (
                f"В файле {amount:,.2f} ₸; среднее по {len(samples)} прошлым операциям "
                f"{baseline:,.2f} ₸; отклонение {deviation * 100:.1f}%."
            ),
            "actual": amount,
            "baseline": baseline,
            "deviation_pct": deviation,
            "tolerance_pct": settings.upload_amount_tolerance_pct,
            "source": "Предыдущие отчёты",
            "trade_id": row.id,
            "samples": len(samples),
        })

    return sorted(anomalies, key=lambda item: float(item.get("deviation_pct") or 0), reverse=True)[:20]
