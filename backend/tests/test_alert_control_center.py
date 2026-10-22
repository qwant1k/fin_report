from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.routes.dashboard import resolve_alert, take_alert_in_work
from database import Base
from models.db_models import Alert, AuditLog, CDU, User
from models.schemas import AlertActionRequest
from services.alerts import auto_resolve_alerts


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed(db: Session, *, severity: str = "CRITICAL") -> tuple[Alert, User]:
    cdu = CDU(
        name="Тестовый управляющий",
        short_name="Тест",
        participant_code="TEST-01",
        participant_code_prefix="TEST",
        is_active=True,
    )
    user = User(
        username="controller",
        full_name="Контролёр",
        password_hash="not-used",
        role="analyst",
        is_active=True,
    )
    db.add_all([cdu, user])
    db.flush()
    alert = Alert(
        alert_date=date(2026, 10, 22),
        cdu_id=cdu.id,
        alert_type="LIMIT_BREACH",
        severity=severity,
        message="Превышен лимит",
        details_json='{"actual_pct": 82.4, "maximum_pct": 80}',
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert, user


def test_alert_workflow_requires_comment_for_critical_and_writes_audit(db: Session):
    alert, user = _seed(db)

    taken = take_alert_in_work(alert.id, db=db, user=user)
    assert taken["status"] == "IN_PROGRESS"
    assert taken["assigned_to"] == user.username
    assert taken["action_path"].startswith("/positions?")
    assert taken["details"]["actual_pct"] == 82.4

    with pytest.raises(HTTPException) as exc:
        resolve_alert(alert.id, AlertActionRequest(), db=db, user=user)
    assert exc.value.status_code == 400

    resolved = resolve_alert(
        alert.id,
        AlertActionRequest(comment="Доля приведена к нормативу"),
        db=db,
        user=user,
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_by"] == user.username
    assert resolved["resolution_comment"] == "Доля приведена к нормативу"
    assert len(db.execute(select(AuditLog).where(AuditLog.entity == "Alert")).scalars().all()) == 2


def test_recalculation_auto_resolves_without_deleting_history(db: Session):
    alert, _user = _seed(db, severity="WARN")
    count = auto_resolve_alerts(
        db,
        alert_date=alert.alert_date,
        alert_types=("LIMIT_BREACH",),
    )
    db.commit()

    stored = db.get(Alert, alert.id)
    assert count == 1
    assert stored is not None
    assert stored.is_resolved is True
    assert stored.status == "RESOLVED"
    assert stored.resolved_by == "SYSTEM"
    assert "автоматически" in stored.resolution_comment
