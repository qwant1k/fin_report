"""Integration tests for upload idempotency via SHA-256.

Exercises the three flows of POST /api/upload/trade-report:

* First upload of a fresh file → 200 OK.
* Re-upload of the exact same bytes (same SHA-256) without ``on_duplicate``
  → 409 Conflict with structured ``detail`` payload for the UI prompt.
* Re-upload with ``on_duplicate=replace`` → previous trades soft-deactivated,
  old TradeFile hard-deleted, new file persisted.
* Re-upload with ``on_duplicate=new_version`` → both TradeFiles coexist.

The test uses FastAPI's dependency_overrides to swap out auth and database
deps so we don't need a real JWT or persistent DB.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import database as db_module
from auth import require_user, require_write
from database import Base, get_db
from main import create_app
from models.db_models import CDU, SecurityHolding, Trade, TradeFile, User


# ─────────────── fixtures ───────────────

@pytest.fixture()
def app_and_db(monkeypatch, tmp_path):
    """Create a fresh app wired to an in-memory DB with auth bypassed."""
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # share one connection across threads (FastAPI threadpool)
    )
    SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", SessionLocal)
    Base.metadata.create_all(bind=engine)

    # Seed a CDU and admin user.
    with SessionLocal() as db:
        cdu = CDU(
            name="Test CDU", short_name="TST",
            participant_code="TST_001", participant_code_prefix="TST",
            portfolio_type="PRIVATE_CDU", share_target_pct=10.0, is_active=True,
        )
        db.add(cdu)
        db.add(User(
            username="admin", password_hash="x", role="admin", is_active=True,
        ))
        db.commit()
        admin_user = db.query(User).filter_by(username="admin").first()

    # Point the upload directory at a temp dir. ``upload_path`` is a derived
    # property; the underlying writable field is ``upload_dir``.
    from config import settings as app_settings
    monkeypatch.setattr(app_settings, "upload_dir", str(tmp_path))

    app = create_app()

    # Override auth + db deps so requests pass through.
    def _override_db():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    def _fake_user():
        # Re-fetch in a fresh session each call so SQLAlchemy state is clean.
        with SessionLocal() as s:
            return s.query(User).filter_by(username="admin").first()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[require_user] = _fake_user
    app.dependency_overrides[require_write] = _fake_user

    yield app, SessionLocal
    engine.dispose()


def _build_xlsx_bytes(deal_number: str = "1") -> bytes:
    """Minimal trade report XLSX with the headers the parser expects."""
    wb = Workbook()
    ws = wb.active
    ws.append([
        "Сделка №", "Заявка №", "Время", "КП",
        "Режим торгов", "Код инструмента", "Статус",
        "Код участника", "Счёт", "Объем",
    ])
    ws.append([
        deal_number, "1", "10:00:00", "К",
        "T+0", "MOM_b1", "EXECUTED",
        "TST_001", "111-T0", "1000",
    ])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _build_unmapped_repo_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append([
        "сделка №", "заявка №", "время", "к/п", "код режима",
        "код инструмента", "статус", "код участника", "торговый счет",
        "объем", "дата торгов", "дата расчетов", "тип (код)",
        "сумма репо", "сумма выкупа репо", "лоты",
    ])
    ws.append([
        "100", "200", "10:00:00", "B", "EBRP",
        "KFUSb48", "M", "DRBES0BT05", "I+1DRCE30100",
        1000, "24.10.2025", "24.10.2025", "H",
        1000, 1010, 10,
    ])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ─────────────── tests ───────────────


class TestUploadIdempotency:
    def test_first_upload_succeeds(self, app_and_db):
        app, _ = app_and_db
        client = TestClient(app)
        body = _build_xlsx_bytes()
        resp = client.post(
            "/api/upload/trade-report",
            files={"file": ("trades.xlsx", body,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert resp.status_code == 200, resp.text

    def test_duplicate_without_action_returns_409(self, app_and_db):
        app, _ = app_and_db
        client = TestClient(app)
        body = _build_xlsx_bytes()
        files = {"file": ("trades.xlsx", body,
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        # First upload — OK.
        assert client.post("/api/upload/trade-report", files=files).status_code == 200
        # Second upload of the same bytes — must be rejected with structured detail.
        resp = client.post(
            "/api/upload/trade-report",
            files={"file": ("trades.xlsx", body,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["error"] == "duplicate_file"
        assert "existing" in detail
        assert detail["existing"]["filename"] == "trades.xlsx"

    def test_duplicate_replace_removes_previous_file(self, app_and_db):
        app, SessionLocal = app_and_db
        client = TestClient(app)
        body = _build_xlsx_bytes()

        client.post(
            "/api/upload/trade-report",
            files={"file": ("trades.xlsx", body, "application/octet-stream")},
        )

        with SessionLocal() as db:
            assert db.query(TradeFile).filter(TradeFile.status != "DELETED").count() == 1

        resp = client.post(
            "/api/upload/trade-report",
            data={"on_duplicate": "replace"},
            files={"file": ("trades.xlsx", body, "application/octet-stream")},
        )
        assert resp.status_code == 200, resp.text

        with SessionLocal() as db:
            # Replace deletes the old TradeFile row outright; only one active remains.
            active = db.query(TradeFile).filter(TradeFile.status != "DELETED").all()
            assert len(active) == 1

    def test_duplicate_new_version_keeps_both(self, app_and_db):
        app, SessionLocal = app_and_db
        client = TestClient(app)
        body = _build_xlsx_bytes()

        client.post(
            "/api/upload/trade-report",
            files={"file": ("trades.xlsx", body, "application/octet-stream")},
        )
        resp = client.post(
            "/api/upload/trade-report",
            data={"on_duplicate": "new_version"},
            files={"file": ("trades.xlsx", body, "application/octet-stream")},
        )
        assert resp.status_code == 200, resp.text

        with SessionLocal() as db:
            rows = db.query(TradeFile).filter(TradeFile.status != "DELETED").all()
            assert len(rows) == 2
            # Both rows share the same SHA-256.
            assert rows[0].sha256 == rows[1].sha256

    def test_set_file_cdu_reimports_unresolved_upload(self, app_and_db):
        app, SessionLocal = app_and_db
        client = TestClient(app)
        body = _build_unmapped_repo_xlsx()

        upload = client.post(
            "/api/upload/trade-report",
            data={"trade_date": "2025-10-24"},
            files={"file": ("unmapped.xlsx", body, "application/octet-stream")},
        )
        assert upload.status_code == 200, upload.text
        file_id = upload.json()["file_id"]
        assert upload.json()["cdu_id"] is None

        with SessionLocal() as db:
            cdu_id = db.query(CDU).filter_by(name="Test CDU").one().id
            assert db.query(Trade).count() == 0

        assigned = client.put(f"/api/upload/files/{file_id}/cdu", params={"cdu_id": cdu_id})
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["trades"] == 1

        with SessionLocal() as db:
            trade = db.query(Trade).filter_by(cdu_id=cdu_id, trade_date=date(2025, 10, 24)).one()
            assert trade.instrument_code == "KFUSb48"
            assert db.query(SecurityHolding).filter_by(cdu_id=cdu_id, isin="KFUSb48").count() == 1
