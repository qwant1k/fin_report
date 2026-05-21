"""Centralised AuditLog helper.

Used by upload, calculate, KASE/MBM refresh, price-reconciliation and other
flows to record an immutable trail of user/system actions.

The helper does NOT commit — callers are expected to commit as part of
their own transaction so the audit row stays atomic with the change it
describes.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.db_models import AuditLog


def write_audit(
    db: Session,
    *,
    user: Optional[str],
    action: str,
    entity: Optional[str] = None,
    entity_id: Optional[int] = None,
    details: Any = None,
) -> AuditLog:
    """Append a single AuditLog row.

    Parameters
    ----------
    user:
        Username of the actor (or ``None`` for system jobs).
    action:
        Short verb, SCREAMING_SNAKE_CASE, e.g. ``UPLOAD_TRADE_REPORT``,
        ``PRICE_REPLACED_FROM_KASE``, ``REPORT_APPROVED``.
    entity / entity_id:
        Optional pointer to the affected row.
    details:
        Free-form payload. If a dict/list — serialised to JSON; otherwise
        cast to ``str``.
    """
    if isinstance(details, (dict, list)):
        payload = json.dumps(details, ensure_ascii=False, default=str)
    elif details is None:
        payload = None
    else:
        payload = str(details)

    row = AuditLog(
        user=user,
        action=action,
        entity=entity,
        entity_id=entity_id,
        details=payload,
    )
    db.add(row)
    return row
