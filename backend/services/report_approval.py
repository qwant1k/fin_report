"""Approval state-machine for ``GeneratedReport``.

State diagram::

    draft ──submit──▶ pending_approval ──approve──▶ approved (terminal/immutable)
                                       └─reject──▶ rejected ──submit──▶ pending_approval

Rules
-----
* ``approved`` rows are immutable: status, file_path, content cannot change.
  Re-running a report after approval MUST create a new row (parent_report_id
  set, version bumped).
* ``regenerate`` is only allowed while ``status in {draft, rejected}``.
* All transitions emit an ``AuditLog`` entry.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.db_models import GeneratedReport
from services.audit import write_audit


_ALLOWED_TRANSITIONS = {
    "draft": {"pending_approval"},
    "pending_approval": {"approved", "rejected"},
    "approved": set(),  # terminal
    "rejected": {"pending_approval"},
}


def _ensure_transition(current: str, target: str) -> None:
    if target not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "invalid_transition",
                "message": f"Переход {current!r} → {target!r} запрещён.",
                "from": current,
                "to": target,
            },
        )


def submit(db: Session, report: GeneratedReport, *, actor: str) -> GeneratedReport:
    _ensure_transition(report.status or "draft", "pending_approval")
    report.status = "pending_approval"
    report.submitted_by = actor
    report.submitted_at = datetime.utcnow()
    # Re-submission after rejection clears the rejection metadata so the new
    # cycle is unambiguous.
    report.rejected_by = None
    report.rejected_at = None
    report.rejection_comment = None
    write_audit(
        db, user=actor, action="REPORT_SUBMITTED",
        entity="GeneratedReport", entity_id=report.id,
        details={"report_date": str(report.report_date), "version": report.version},
    )
    return report


def approve(db: Session, report: GeneratedReport, *, actor: str) -> GeneratedReport:
    _ensure_transition(report.status or "draft", "approved")
    report.status = "approved"
    report.approved_by = actor
    report.approved_at = datetime.utcnow()
    write_audit(
        db, user=actor, action="REPORT_APPROVED",
        entity="GeneratedReport", entity_id=report.id,
        details={
            "report_date": str(report.report_date),
            "version": report.version,
            "submitted_by": report.submitted_by,
        },
    )
    return report


def reject(
    db: Session, report: GeneratedReport, *, actor: str, comment: str,
) -> GeneratedReport:
    _ensure_transition(report.status or "draft", "rejected")
    if not comment or not comment.strip():
        raise HTTPException(400, "Комментарий обязателен для отклонения отчёта")
    report.status = "rejected"
    report.rejected_by = actor
    report.rejected_at = datetime.utcnow()
    report.rejection_comment = comment.strip()
    write_audit(
        db, user=actor, action="REPORT_REJECTED",
        entity="GeneratedReport", entity_id=report.id,
        details={
            "report_date": str(report.report_date),
            "version": report.version,
            "comment": report.rejection_comment,
            "submitted_by": report.submitted_by,
        },
    )
    return report


def ensure_mutable(report: GeneratedReport, *, action: str = "modify") -> None:
    """Raise 409 if the row is locked (approved). Used by delete/regenerate."""
    if (report.status or "draft") == "approved":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "report_locked",
                "message": f"Отчёт #{report.id} утверждён и не может быть {action}.",
                "approved_by": report.approved_by,
                "approved_at": report.approved_at.isoformat() if report.approved_at else None,
            },
        )


def can_be_regenerated(report: GeneratedReport) -> bool:
    return (report.status or "draft") in {"draft", "rejected"}
