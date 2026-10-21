"""Manual operations of any purpose and the full drill-down of summary rows (02.10.2026)."""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from models.db_models import (
    AccountReceivable, CashMovement, CDU, InstrumentReference, PortfolioPosition, Trade,
)
from tests.test_requirements_20260929 import UD_24, _cdu, _upload, needs_files, stand  # noqa: F401

D = "2026-09-15"


def _approve(client, current, entity, row_id):
    current["user"] = "checker"
    r = client.post(f"/api/accounting/{entity}/{row_id}/approve", json={})
    current["user"] = "maker"
    assert r.status_code == 200, r.text
    return r.json()


def _cash(Session, cdu_id, on=date(2026, 9, 15)):
    with Session() as db:
        row = db.execute(select(PortfolioPosition).where(
            PortfolioPosition.cdu_id == cdu_id, PortfolioPosition.position_date == on,
            PortfolioPosition.instrument_category == "CASH", PortfolioPosition.instrument_code.is_(None),
        )).scalars().first()
        return row.market_value_current if row else None


def _own(Session):
    with Session() as db:
        return db.query(CDU).filter_by(portfolio_type="NBRK_OWN").first()


def test_purposes_are_listed_with_the_default_portfolio(stand):
    client, Session, _ = stand
    data = client.get("/api/accounting/operation-purposes").json()
    codes = {p["code"] for p in data["purposes"]}
    assert {"CASH_RECEIPT", "SECURITY_BUY", "RECEIVABLE_CLOSE"} <= codes
    assert data["default_portfolio"]["id"] == _own(Session).id


def test_operation_without_manager_counts_in_summary_after_approval(stand):
    client, Session, current = stand
    own = _own(Session)
    r = client.post("/api/accounting/operations", json={
        "purpose": "CASH_RECEIPT", "operation_date": D, "amount": "2 500 000",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cdu_id"] == own.id and body["portfolio_note"]
    mv_id = body["created"][0]["id"]
    with Session() as db:
        mv = db.get(CashMovement, mv_id)
        assert (mv.amount, mv.movement_type, mv.basis, mv.workflow_status) == (
            2_500_000, "RECEIPT", "Поступление денег", "PENDING_APPROVAL")

    # summary exists; pending operation is not counted but is shown in the drill-down
    client.post("/api/calculate/", json={"report_date": D, "recalculate": True})
    assert not _cash(Session, own.id)
    bd = client.get("/api/dashboard/category-breakdown",
                    params={"cdu_id": own.id, "category": "CASH", "date": D}).json()
    assert bd["total"] == 0 and len(bd["pending"]) == 1
    assert bd["pending"][0]["source"]["kind"] == "manual"

    res = _approve(client, current, "cash-movements", mv_id)
    assert D in res["recalculated_dates"]          # the summary is refreshed automatically
    assert _cash(Session, own.id) == pytest.approx(2_500_000)
    bd = client.get("/api/dashboard/category-breakdown",
                    params={"cdu_id": own.id, "category": "CASH", "date": D}).json()
    assert bd["kind"] == "cash" and bd["total"] == pytest.approx(2_500_000)
    m = bd["cash"]["movements"][0]
    assert (m["type_label"], m["purpose"], m["is_manual"]) == ("Поступление", "Поступление денег", True)
    assert bd["summary_value"] == pytest.approx(bd["total"])


def test_security_purchase_operation_creates_position_and_cash_leg(stand):
    client, Session, current = stand
    aci = _cdu(Session, "Alatau City Invest")
    with Session() as db:
        db.add(InstrumentReference(isin="KZKD00001087", ticker_kase="MUM108_0013", nominal=1000.0,
                                   coupon_rate_pct=11.0, frequency=1, base="30/360",
                                   start_date=date(2020, 3, 31), maturity_date=date(2029, 3, 31),
                                   security_type="ГЦБ", source="MANUAL"))
        db.commit()
    r = client.post("/api/accounting/operations", json={
        "cdu_id": aci.id, "purpose": "SECURITY_BUY", "operation_date": D, "isin": "MUM108_0013",
        "quantity": 1000, "price": 98.5,
    })
    assert r.status_code == 200, r.text
    tid = r.json()["created"][0]["id"]
    with Session() as db:
        t = db.get(Trade, tid)
        assert (t.operation_type, t.isin, t.face_value, t.amount_kzt) == ("BUY", "KZKD00001087", 1_000_000, -985_000)
    _approve(client, current, "trades", tid)
    bd = client.get("/api/dashboard/category-breakdown",
                    params={"cdu_id": aci.id, "category": t.instrument_category, "date": D}).json()
    assert len(bd["items"]) == 1
    item = bd["items"][0]
    assert item["face_value"] == pytest.approx(1_000_000) and item["quantity"] == pytest.approx(1000)
    assert item["source"]["kind"] == "manual" and item["settlement_date"] == D
    cash = client.get("/api/dashboard/category-breakdown",
                      params={"cdu_id": aci.id, "category": "CASH", "date": D}).json()
    assert cash["total"] == pytest.approx(-985_000)
    assert cash["cash"]["movements"][0]["type_label"] == "Покупка ЦБ"


def test_receivable_close_without_choice_repays_open_receivables_fifo(stand):
    client, Session, current = stand
    aci = _cdu(Session, "Alatau City Invest")
    ids = []
    for amount, d in ((300.0, "2026-09-01"), (500.0, "2026-09-05")):
        r = client.post("/api/accounting/operations", json={
            "cdu_id": aci.id, "purpose": "RECEIVABLE_OPEN", "operation_date": d, "amount": amount,
            "counterparty": "Эмитент", "purpose_text": "Купон не поступил",
        })
        assert r.status_code == 200, r.text
        ids.append(r.json()["created"][0]["id"])
        _approve(client, current, "receivables", ids[-1])
    r = client.post("/api/accounting/operations", json={
        "cdu_id": aci.id, "purpose": "RECEIVABLE_CLOSE", "operation_date": D, "amount": 600,
    })
    assert r.status_code == 200, r.text
    created = r.json()["created"]
    assert [c["receivable_id"] for c in created] == ids
    for c in created:
        _approve(client, current, "receivable-transactions", c["id"])
    bd = client.get("/api/dashboard/category-breakdown",
                    params={"cdu_id": aci.id, "category": "RECEIVABLES", "date": D}).json()
    balances = {i["id"]: i["balance_kzt"] for i in bd["items"]}
    assert balances[ids[0]] == pytest.approx(0) and balances[ids[1]] == pytest.approx(200)
    assert bd["total"] == pytest.approx(200)
    cash = client.get("/api/dashboard/category-breakdown",
                      params={"cdu_id": aci.id, "category": "CASH", "date": D}).json()
    assert cash["total"] == pytest.approx(600)
    with Session() as db:
        assert db.get(AccountReceivable, ids[0]).status == "CLOSED"


def test_operation_validation_messages(stand):
    client, _, _ = stand
    assert client.post("/api/accounting/operations", json={"operation_date": D}).status_code == 400
    r = client.post("/api/accounting/operations", json={"purpose": "CASH_RECEIPT", "operation_date": D})
    assert r.status_code == 400 and "сумм" in r.json()["detail"].lower()
    r = client.post("/api/accounting/operations", json={"purpose": "SECURITY_BUY", "operation_date": D, "amount": 1})
    assert r.status_code == 400 and "ISIN" in r.json()["detail"]


@needs_files
def test_repo_breakdown_shows_dates_sources_and_adds_up(stand):
    client, Session, _ = stand
    _upload(client, UD_24)
    ud = _cdu(Session, "UD Capital")
    client.post("/api/calculate/", json={"report_date": "2026-09-24", "recalculate": True})
    bd = client.get("/api/dashboard/category-breakdown",
                    params={"cdu_id": ud.id, "category": "REVERSE_REPO", "date": "2026-09-24"}).json()
    assert bd["kind"] == "money_market" and len(bd["items"]) == 4
    assert bd["total"] == pytest.approx(bd["summary_value"], abs=0.05)
    it = bd["items"][0]
    assert it["open_date"] and it["close_date"] and it["rate"]
    assert it["source"]["label"] == "Trade Report" and it["source"]["file_name"].endswith(".xlsx")
    cash = client.get("/api/dashboard/category-breakdown",
                      params={"cdu_id": ud.id, "category": "CASH", "date": "2026-09-24"}).json()
    assert cash["total"] == pytest.approx(cash["summary_value"], abs=0.05)
    assert all(m["source"]["file_name"] for m in cash["cash"]["movements"])


# ───────────── DB editor ─────────────

def test_data_editor_meta_has_russian_labels_groups_and_fk(stand):
    client, Session, _ = stand
    tables = client.get("/api/data/tables").json()
    limits = next(t for t in tables if t["name"] == "cdu_limits")
    assert limits["label"] == "Лимиты ЧДУ" and limits["group"] == "Справочники" and limits["rows"] > 0
    trades = next(t for t in tables if t["name"] == "trades")
    assert trades["read_only"] and trades["edit_hint"]["route"] == "/accounting"
    meta = client.get("/api/data/tables/cdu_limits/meta").json()
    cdu_col = next(c for c in meta["columns"] if c["name"] == "cdu_id")
    assert cdu_col["label"] == "ЧДУ / портфель" and cdu_col["fk_table"] == "cdu"
    rows = client.get("/api/data/tables/cdu_limits", params={"page_size": 5}).json()
    some = rows["data"][0]
    assert rows["fk_labels"]["cdu_id"][str(some["cdu_id"])]
    lookup = client.get("/api/data/lookup/cdu", params={"search": "Halyk"}).json()
    assert lookup and "Halyk" in lookup[0]["label"]


def test_data_editor_edits_with_readable_errors(stand):
    client, Session, _ = stand
    # dates typed as dd.mm.yyyy, numbers with a comma, booleans as text
    r = client.post("/api/data/tables/fx_rates", json={"currency": "USD", "rate_date": "24.09.2026", "rate": "512,35"})
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["rate"] == 512.35 and row["rate_date"] == "2026-09-24"
    # a field can be cleared (nullable) / cannot be cleared (required)
    bad = client.patch(f"/api/data/tables/fx_rates/{row['id']}", json={"rate": "abc"})
    assert bad.status_code == 400 and "Курс" in bad.json()["detail"]
    empty = client.patch(f"/api/data/tables/fx_rates/{row['id']}", json={"currency": None})
    assert empty.status_code == 400
    # duplicate → 409 with a message, not a server error
    dup = client.post("/api/data/tables/fx_rates", json={"currency": "USD", "rate_date": "2026-09-24", "rate": 1})
    assert dup.status_code in (200, 409)
    # filters coerce types
    found = client.get("/api/data/tables/fx_rates", params={"rate_date": "2026-09-24"}).json()
    assert found["total"] >= 1
    # required field missing on create
    miss = client.post("/api/data/tables/fx_rates", json={"currency": "EUR"})
    assert miss.status_code == 400 and "обязательное" in miss.json()["detail"]
