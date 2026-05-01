"""Optional SMTP notification service used by alerts and scheduler."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, Optional

from loguru import logger

from config import settings


def is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def send_mail(
    *,
    to: Iterable[str],
    subject: str,
    body: str,
    attachments: Optional[Iterable[Path]] = None,
) -> bool:
    """Send a plain-text email. Returns True on success, False otherwise."""
    if not is_configured():
        logger.warning("SMTP not configured; email skipped")
        return False
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)

    for path in attachments or []:
        try:
            with path.open("rb") as f:
                data = f.read()
            msg.add_attachment(data, maintype="application", subtype="octet-stream", filename=path.name)
        except Exception as exc:
            logger.warning(f"Could not attach {path}: {exc!r}")

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        logger.info(f"Email sent to {list(to)} subject={subject!r}")
        return True
    except Exception as exc:
        logger.error(f"SMTP send failed: {exc!r}")
        return False
