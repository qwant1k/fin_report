"""Alert CRUD helpers used by routes and the calculator."""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.db_models import Alert, CDU
from services import email_service


def create_alert(
    db: Session,
    *,
    alert_date: date,
    cdu_id: Optional[int],
    alert_type: str,
    severity: str,
    message: str,
    details_json: Optional[str] = None,
) -> Alert:
    a = Alert(
        alert_date=alert_date,
        cdu_id=cdu_id,
        alert_type=alert_type,
        severity=severity,
        message=message,
        details_json=details_json,
    )
    db.add(a)
    db.commit()
    db.refresh(a)

    # Send email for CRITICAL/WARN alerts if SMTP configured and CDU has email
    if severity in ("CRITICAL", "WARN") and email_service.is_configured():
        try:
            recipients: list[str] = []
            if cdu_id:
                cdu = db.get(CDU, cdu_id)
                if cdu and cdu.contact_email:
                    recipients.append(cdu.contact_email)
            if recipients:
                email_service.send_mail(
                    to=recipients,
                    subject=f"[KDIF] {severity}: {alert_type}",
                    body=f"{message}\n\nДата: {alert_date}\nТип: {alert_type}\nSeverity: {severity}\n",
                )
        except Exception as exc:
            logger.warning(f"Alert email skipped: {exc!r}")

    return a


def list_alerts(
    db: Session,
    *,
    only_unresolved: bool = False,
    cdu_id: Optional[int] = None,
    since: Optional[date] = None,
    limit: int = 200,
) -> List[Alert]:
    q = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if only_unresolved:
        q = q.where(Alert.is_resolved.is_(False))
    if cdu_id:
        q = q.where(Alert.cdu_id == cdu_id)
    if since:
        q = q.where(Alert.alert_date >= since)
    return list(db.execute(q).scalars().all())


def resolve_alert(db: Session, alert_id: int) -> Optional[Alert]:
    a = db.get(Alert, alert_id)
    if not a:
        return None
    a.is_resolved = True
    a.resolved_at = datetime.utcnow()
    db.commit()
    return a
