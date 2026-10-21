"""Unified quick queue for the four-eyes workflow in the global header."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import has_permission, require_user
from database import get_db
from models.db_models import (
    AccountReceivable,
    AuditLog,
    CashMovement,
    CDU,
    GeneratedReport,
    ReceivableTransaction,
    Trade,
    User,
)


router = APIRouter(prefix="/api/approvals", tags=["approvals"])
PENDING_STATUSES = {"PENDING_APPROVAL", "PENDING_CANCELLATION"}

ENTITY_CONFIG = (
    ("trades", Trade, "Сделка"),
    ("cash-movements", CashMovement, "Движение денег"),
    ("receivables", AccountReceivable, "Дебиторская задолженность"),
    ("receivable-transactions", ReceivableTransaction, "Операция по дебиторке"),
)

FIELD_LABELS = {
    "operation_type": "Операция",
    "movement_type": "Вид движения",
    "instrument_code": "Инструмент",
    "isin": "ISIN",
    "amount_kzt": "Сумма, ₸",
    "amount": "Сумма",
    "trade_date": "Дата сделки",
    "operation_date": "Дата операции",
    "record_date": "Дата признания",
    "value_date": "Дата расчётов",
    "counterparty": "Контрагент",
    "basis": "Основание",
    "change_reason": "Причина",
}


def _text(value: Any) -> str:
    if value in (None, ""):
        return "—"
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", " ")
    return str(value)


def _current_fields(row: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    for key in FIELD_LABELS:
        if hasattr(row, key):
            value = getattr(row, key)
            if value not in (None, ""):
                values[FIELD_LABELS[key]] = _text(value)
    return dict(list(values.items())[:6])


def _latest_diff(db: Session, entity: str, row_id: int) -> tuple[dict[str, str], dict[str, str]] | None:
    audit = db.execute(select(AuditLog).where(
        AuditLog.entity == entity,
        AuditLog.entity_id == row_id,
    ).order_by(AuditLog.id.desc())).scalars().first()
    if not audit or not audit.details:
        return None
    try:
        payload = json.loads(audit.details)
    except (TypeError, json.JSONDecodeError):
        return None
    before = payload.get("before") if isinstance(payload, dict) else None
    after = payload.get("after") if isinstance(payload, dict) else None
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None
    keys = [key for key in FIELD_LABELS if key in before or key in after][:6]
    return (
        {FIELD_LABELS[key]: _text(before.get(key)) for key in keys},
        {FIELD_LABELS[key]: _text(after.get(key)) for key in keys},
    )


def _operation_task(db: Session, row: Any, entity: str, label: str, user: User, names: dict[int, str]) -> dict[str, Any]:
    parent = db.get(AccountReceivable, row.receivable_id) if isinstance(row, ReceivableTransaction) else None
    cdu_id = parent.cdu_id if parent else row.cdu_id
    creator = getattr(row, "created_by", None)
    editor = getattr(row, "updated_by", None)
    own = user.username in {creator, editor}
    status = row.workflow_status
    current = _current_fields(row)
    if status == "PENDING_CANCELLATION":
        before = {"Статус": "Согласовано", **current}
        after = {"Статус": "Аннулировано", "Причина": _text(getattr(row, "decision_comment", None))}
    else:
        diff = _latest_diff(db, row.__class__.__name__, row.id)
        before, after = diff if diff else ({"Состояние": "Записи не было"}, current)
    title_value = (
        getattr(row, "instrument_code", None)
        or getattr(row, "isin", None)
        or getattr(row, "counterparty", None)
        or getattr(row, "basis", None)
        or f"#{row.id}"
    )
    changed_at = getattr(row, "updated_at", None) or getattr(row, "created_at", None)
    return {
        "key": f"operation:{entity}:{row.id}",
        "kind": "operation",
        "entity": entity,
        "entity_id": row.id,
        "type_label": label,
        "title": _text(title_value),
        "subtitle": names.get(cdu_id, "Портфель не указан"),
        "status": status,
        "requested_by": editor or creator,
        "requested_at": changed_at.isoformat() if isinstance(changed_at, datetime) else None,
        "own_operation": own,
        "can_approve": not own,
        "can_reject": not own,
        "before": before,
        "after": after,
    }


@router.get("")
def approval_queue(db: Session = Depends(get_db), user: User = Depends(require_user)):
    tasks: list[dict[str, Any]] = []
    names = {row.id: row.short_name or row.name for row in db.query(CDU).all()}

    if has_permission(user, "manual.operations.approve", db):
        for entity, model, label in ENTITY_CONFIG:
            rows = db.execute(select(model).where(
                model.workflow_status.in_(PENDING_STATUSES),
            ).order_by(model.id.desc()).limit(100)).scalars().all()
            tasks.extend(_operation_task(db, row, entity, label, user, names) for row in rows)

    can_report_approve = has_permission(user, "reports.approve", db)
    can_report_reject = has_permission(user, "reports.reject", db)
    if can_report_approve or can_report_reject:
        reports = db.execute(select(GeneratedReport).where(
            GeneratedReport.status == "pending_approval",
        ).order_by(GeneratedReport.submitted_at.desc(), GeneratedReport.id.desc()).limit(100)).scalars().all()
        for row in reports:
            own = user.username in {row.generated_by, row.submitted_by}
            tasks.append({
                "key": f"report:{row.id}",
                "kind": "report",
                "entity": "reports",
                "entity_id": row.id,
                "type_label": "Отчёт",
                "title": f"{row.report_type} за {row.report_date:%d.%m.%Y}",
                "subtitle": f"Версия {row.version}",
                "status": row.status,
                "requested_by": row.submitted_by,
                "requested_at": row.submitted_at.isoformat() if row.submitted_at else None,
                "own_operation": own,
                "can_approve": can_report_approve and not own,
                "can_reject": can_report_reject and not own,
                "before": {"Статус": "Черновик", "Версия": str(row.version)},
                "after": {"Статус": "На согласовании", "Дата отчёта": row.report_date.isoformat()},
            })

    tasks.sort(key=lambda item: item.get("requested_at") or "", reverse=True)
    return {"count": len(tasks), "items": tasks}
