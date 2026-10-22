"""Closing of receivables — business process 6.1.8 / 7.1.11.

A receivable («купон/погашение в пути») is closed when the money is actually
received.  Evidence used, in this order:

1. an approved cash movement linked to the same ISIN and manager, dated on/after
   the record date, whose amount matches the open balance within ±0.01
   (one or several movements may add up to the balance — partial receipts
   reduce the balance);
2. otherwise the receivable stays open with the note «Ожидается выписка».

Closing creates an approved ``REPAYMENT`` transaction *without* a new cash leg
(the cash is already in the matched movements), so the AR balance «на дату»
history stays correct and nothing is counted twice.  Differences above the
tolerance are not closed automatically — an alert is raised for ОИиУА.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Dict, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.db_models import AccountReceivable, Alert, CashMovement, ReceivableTransaction
from services.calculator.constants import RECON_TOLERANCE_KZT
from services.workflow import EFFECTIVE_STATUSES


def _balance(db: Session, ar: AccountReceivable, as_of: date) -> float:
    from api.routes.accounting import receivable_balance_as_of
    return receivable_balance_as_of(db, ar, as_of)


def close_ar_items(db: Session, target_date: Optional[date] = None) -> Dict[str, int]:
    as_of = target_date or date.max
    q = select(AccountReceivable).where(
        AccountReceivable.status.in_(("OPEN", "PARTIAL")),
        AccountReceivable.is_active == True,  # noqa: E712
        AccountReceivable.workflow_status.in_(EFFECTIVE_STATUSES),
        AccountReceivable.record_date <= as_of,
    )
    counters = {"closed": 0, "partial": 0, "pending": 0, "mismatch": 0}
    used_movements: set[int] = set()
    for ar in db.execute(q).scalars().all():
        balance = _balance(db, ar, as_of)
        if balance <= RECON_TOLERANCE_KZT:
            ar.status = "CLOSED"
            continue
        if not ar.isin:
            counters["pending"] += 1
            continue
        movements = db.execute(select(CashMovement).where(
            CashMovement.cdu_id == ar.cdu_id,
            CashMovement.related_isin == ar.isin,
            CashMovement.operation_date >= ar.record_date,
            CashMovement.operation_date <= as_of,
            CashMovement.is_active == True,  # noqa: E712
            CashMovement.workflow_status.in_(EFFECTIVE_STATUSES),
            CashMovement.amount_kzt > 0,
            CashMovement.related_receivable_transaction_id.is_(None),
            CashMovement.related_trade_id.is_(None),
        ).order_by(CashMovement.operation_date.asc(), CashMovement.id.asc())).scalars().all()
        movements = [m for m in movements if m.id not in used_movements]
        if not movements:
            ar.notes = "Ожидается выписка"
            counters["pending"] += 1
            continue
        received = sum(float(m.amount_kzt or 0.0) for m in movements)
        last_date = movements[-1].operation_date
        if received > balance + RECON_TOLERANCE_KZT:
            counters["mismatch"] += 1
            db.add(Alert(
                alert_date=last_date, cdu_id=ar.cdu_id, alert_type="AR_MISMATCH", severity="WARN",
                message=(f"Дебиторка {ar.isin}: поступило {received:,.2f}, ожидалось {balance:,.2f} — "
                         "требуется ручная проверка ОИиУА"),
                details_json=json.dumps({
                    "receivable_id": ar.id,
                    "isin": ar.isin,
                    "received": received,
                    "expected": balance,
                    "deviation": received - balance,
                }, ensure_ascii=False),
            ))
            continue
        db.add(ReceivableTransaction(
            receivable_id=ar.id,
            operation_date=last_date,
            operation_type="REPAYMENT",
            amount=received,
            amount_kzt=received,
            currency=ar.currency or "KZT",
            basis="Автоматически: поступление по выписке/движению денег " + ", ".join(f"#{m.id}" for m in movements),
            workflow_status="APPROVED",
            is_active=True,
            created_by="SYSTEM",
            approved_by="SYSTEM",
        ))
        used_movements.update(m.id for m in movements)
        if abs(received - balance) <= RECON_TOLERANCE_KZT:
            ar.status = "CLOSED"
            ar.balance_kzt = 0.0
            ar.actual_value_date = last_date
            ar.notes = None
            counters["closed"] += 1
        else:
            ar.status = "PARTIAL"
            ar.balance_kzt = balance - received
            counters["partial"] += 1
    db.commit()
    logger.info(f"AR close engine: {counters}")
    return counters


def find_matching_cash_for_ar(db: Session, ar: AccountReceivable, **_kwargs):
    """Backward-compatible helper: first matching inflow movement or None."""
    return db.execute(select(CashMovement).where(
        CashMovement.cdu_id == ar.cdu_id,
        CashMovement.related_isin == ar.isin,
        CashMovement.operation_date >= ar.record_date,
        CashMovement.amount_kzt > 0,
        CashMovement.is_active == True,  # noqa: E712
    ).order_by(CashMovement.operation_date.asc())).scalars().first()
