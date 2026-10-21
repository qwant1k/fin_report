"""Productivity UX contracts: quick approvals, express audit and What-If."""
from __future__ import annotations

from datetime import date

import pytest

from models.db_models import CDU, PortfolioPosition, PortfolioSummary, Trade
from services.anomaly_audit import audit_uploaded_trades
from tests.test_requirements_20260929 import stand  # noqa: F401


def _first_cdu(Session) -> CDU:
    with Session() as db:
        return db.query(CDU).order_by(CDU.id).first()


def test_quick_approval_queue_marks_own_operation_and_backend_blocks_it(stand):
    client, Session, current = stand
    cdu = _first_cdu(Session)
    created = client.post("/api/accounting/cash-movements", json={
        "cdu_id": cdu.id,
        "operation_date": "2026-10-21",
        "amount": 1_000_000,
        "currency": "KZT",
        "movement_type": "RECEIPT",
        "basis": "UX-тест очереди согласования",
        "change_reason": "Проверка 4-Eyes",
    })
    assert created.status_code == 200, created.text

    own_queue = client.get("/api/approvals")
    assert own_queue.status_code == 200, own_queue.text
    task = next(item for item in own_queue.json()["items"] if item["entity_id"] == created.json()["id"])
    assert task["own_operation"] is True
    assert task["can_approve"] is False
    assert task["before"] and task["after"]
    assert client.post(f"/api/accounting/cash-movements/{created.json()['id']}/approve", json={}).status_code == 409

    current["user"] = "checker"
    checker_task = next(item for item in client.get("/api/approvals").json()["items"] if item["entity_id"] == created.json()["id"])
    assert checker_task["own_operation"] is False
    assert checker_task["can_approve"] is True
    approved = client.post(f"/api/accounting/cash-movements/{created.json()['id']}/approve", json={})
    assert approved.status_code == 200, approved.text


def test_express_audit_returns_price_and_amount_cards(stand):
    _client, Session, _current = stand
    cdu = _first_cdu(Session)
    with Session() as db:
        db.add(Trade(
            cdu_id=cdu.id, trade_date=date(2026, 10, 20), value_date=date(2026, 10, 20),
            operation_type="BUY", instrument_code="TEST", amount_kzt=-100_000,
            source_doc_id=1, is_active=True,
        ))
        db.add(Trade(
            cdu_id=cdu.id, trade_date=date(2026, 10, 21), value_date=date(2026, 10, 21),
            operation_type="BUY", instrument_code="TEST", amount_kzt=-200_000,
            source_doc_id=2, is_active=True, price_flag=True,
            price_original=110.0, price_kase=100.0, price_diff_pct=0.10,
        ))
        db.commit()
        cards = audit_uploaded_trades(
            db, cdu_id=cdu.id, source_doc_id=2, trade_date=date(2026, 10, 21),
        )
    assert {card["kind"] for card in cards} == {"price", "amount"}
    assert all(card["title"] and card["message"] for card in cards)


def test_what_if_returns_deltas_without_persisting_trade(stand):
    client, Session, _current = stand
    cdu = _first_cdu(Session)
    on = date(2026, 10, 21)
    with Session() as db:
        db.add(PortfolioSummary(
            cdu_id=cdu.id, summary_date=on, total_mv_current=1_000.0,
            total_mv_prev=1_000.0, duration_weighted=2.0,
        ))
        db.add_all([
            PortfolioPosition(
                cdu_id=cdu.id, position_date=on, instrument_category="GOV_BONDS",
                market_value_current=600.0, pct_of_total=0.6, duration=2.0,
            ),
            PortfolioPosition(
                cdu_id=cdu.id, position_date=on, instrument_category="CASH",
                market_value_current=400.0, pct_of_total=0.4, duration=None,
            ),
        ])
        db.commit()
        before_count = db.query(Trade).count()

    response = client.post("/api/dashboard/what-if", json={
        "report_date": on.isoformat(),
        "cdu_id": cdu.id,
        "operation_type": "BUY",
        "category": "GOV_BONDS",
        "amount_kzt": 100.0,
        "duration": 4.0,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["persisted"] is False
    assert body["portfolio"]["duration_before"] == pytest.approx(2.0)
    assert body["portfolio"]["duration_after"] == pytest.approx((2 * 600 + 4 * 100) / 700)
    assert body["limit"]["pct_after"] == pytest.approx(700 / 1100)
    with Session() as db:
        assert db.query(Trade).count() == before_count


def test_cdu_can_be_added_manually_with_validation_and_clear_duplicate_error(stand):
    client, Session, _current = stand
    payload = {
        "name": "  АО «Тестовое управление»  ",
        "short_name": "  Тест УА  ",
        "participant_code": "  TEST01  ",
        "participant_code_prefix": "  TEST  ",
        "portfolio_type": "PRIVATE_CDU",
        "portfolio_code": None,
        "share_target_pct": 12.5,
        "contact_email": "  reports@example.kz  ",
        "contact_manager": "  Тестовый менеджер  ",
        "is_active": True,
    }

    created = client.post("/api/settings/cdus", json=payload)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["name"] == "АО «Тестовое управление»"
    assert body["short_name"] == "Тест УА"
    assert body["participant_code"] == "TEST01"
    assert body["contact_email"] == "reports@example.kz"

    duplicate = {**payload, "name": "ао «тестовое управление»", "participant_code": "OTHER01"}
    conflict = client.post("/api/settings/cdus", json=duplicate)
    assert conflict.status_code == 409
    assert "уже используется" in conflict.json()["detail"]

    invalid = {**payload, "name": "   ", "participant_code": "OTHER02"}
    rejected = client.post("/api/settings/cdus", json=invalid)
    assert rejected.status_code == 422

    with Session() as db:
        assert db.query(CDU).filter(CDU.participant_code == "TEST01").count() == 1
