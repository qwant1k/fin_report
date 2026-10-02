"""Shared maker-checker workflow constants.

A record changes the books only after a second person approves the change.
While a cancellation of an APPROVED record waits for approval
(``PENDING_CANCELLATION``) the record keeps affecting the portfolio — an
unapproved cancellation is itself an unapproved change.
"""
from __future__ import annotations

PENDING = "PENDING_APPROVAL"
PENDING_CANCELLATION = "PENDING_CANCELLATION"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
CANCELLED = "CANCELLED"

WORKFLOW_STATUSES = {PENDING, PENDING_CANCELLATION, APPROVED, REJECTED, CANCELLED}

# Statuses whose records participate in calculations.
EFFECTIVE_STATUSES = (APPROVED, PENDING_CANCELLATION)


def is_effective(status: str | None, is_active: bool | None = True) -> bool:
    return bool(is_active) and (status or APPROVED) in EFFECTIVE_STATUSES
