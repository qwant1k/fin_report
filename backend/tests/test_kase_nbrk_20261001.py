"""KASE coupon schedules / issue parameters, NBRK daily files, Halyk & Centras
Trade Reports (files sent on 01.10.2026).

KASE responses in ``fixtures/kase_api_samples.json`` were captured from
kase.kz (``/api/instruments/...``) on 01.10.2026.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from models.db_models import CashMovement, CDU, CouponSchedule, InstrumentReference, Trade
from services.kase import instrument_client as kc
from services.portfolio import bond_math as bm
from services.portfolio import coupon_schedule as cs

from tests.test_requirements_20260929 import LOG_DIR, _cdu, _upload, stand  # noqa: F401  (fixture)

FIX = json.loads((Path(__file__).parent / "fixtures" / "kase_api_samples.json").read_text(encoding="utf-8"))
needs = pytest.mark.skipif(not (LOG_DIR / "КФГД_20260924.csv").exists(), reason="файлы 01.10.2026 недоступны")


def _transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/api/instruments/", 1)[1]
        key = path + (f"?search={request.url.params['search']}" if "search" in request.url.params else "")
        if key in FIX:
            return httpx.Response(200, json=FIX[key])
        return httpx.Response(404, json={"detail": "Не найдено."})
    return httpx.MockTransport(handler)


def _client() -> kc.KaseInstrumentClient:
    return kc.KaseInstrumentClient(base_url="https://kase.kz/api", transport=_transport())


# ───────────── parsing of real KASE responses ─────────────

def test_coupon_payments_and_characteristics_are_parsed():
    rows = kc.parse_coupon_payments(FIX["coupon-payments/MUM108_0013"])
    assert len(rows) == 9
    assert rows[3]["payment_date"] == date(2024, 3, 31) and rows[3]["payment_end_date"] == date(2024, 4, 1)
    assert {r["rate_pct"] for r in rows} == {11}
    flo = kc.parse_coupon_payments(FIX["coupon-payments/KFUSb46"])
    assert flo[6]["rate_pct"] == pytest.approx(20.66)
    assert (flo[6]["margin_pct"], flo[6]["index_rate_pct"]) == (2.4, 18.26)
    assert flo[0]["record_date"] == date(2023, 5, 24)

    mum = kc.parse_characteristics(FIX["gsecs/MUM108_0013/characteristics"], kc.KaseIssue(code="MUM108_0013"))
    assert (mum.nominal, mum.base, mum.isin) == (1000.0, "30/360", "KZKD00001087")
    assert (mum.start_date, mum.maturity_date, mum.coupon_type) == (date(2020, 3, 31), date(2029, 3, 31), "fix")
    kfus = kc.parse_characteristics(FIX["bonds/KFUSb46/characteristics"], kc.KaseIssue(code="KFUSb46"))
    assert (kfus.coupon_type, kfus.base, kfus.maturity_date) == ("float", "act/365", date(2027, 11, 25))
    assert kfus.coupon_rate_pct == pytest.approx(19.5)
    ntk = kc.parse_characteristics(FIX["gsecs/NTK092_2889/characteristics"], kc.KaseIssue(code="NTK092_2889"))
    assert (ntk.coupon_type, ntk.nominal, ntk.maturity_date) == ("zero", 100.0, date(2026, 12, 17))


def test_issue_is_fetched_by_ticker_and_by_isin():
    issue = asyncio.run(_client().fetch_issue(code="KFUSb46"))
    assert issue.isin == "KZ2C00008928" and issue.frequency == 2 and len(issue.schedule) == 10
    assert issue.issuer == 'АО "Казахстанский фонд устойчивости"'
    by_isin = asyncio.run(_client().fetch_issue(isin="KZKD00001087"))
    assert by_isin.code == "MUM108_0013" and by_isin.frequency == 1


# ───────────── sync into the reference book, manual rows kept ─────────────

def test_kase_sync_fills_reference_and_keeps_manual_rows(stand):
    client, Session, _ = stand
    from services.kase.coupon_sync import fetch_and_apply
    with Session() as db:
        res = asyncio.run(fetch_and_apply(db, "MUM108_0013", "tester", client=_client()))
        db.commit()
        assert res == {"isin": "KZKD00001087", "code": "MUM108_0013", "rows": 9, "coupon_type": "fix",
                       "maturity_date": "2029-03-31"}
        ref = db.execute(select(InstrumentReference).where(InstrumentReference.isin == "KZKD00001087")).scalars().one()
        assert (ref.ticker_kase, ref.nominal, ref.frequency, ref.base) == ("MUM108_0013", 1000.0, 1, "30/360")
    # the user edits a row and adds one (e.g. an announced rate change)
    rows = client.get("/api/securities/reference/KZKD00001087/coupons").json()["rows"]
    rows[6]["rate_pct"] = 12.0
    rows[6]["source"] = "MANUAL"
    rows.append({"payment_date": "2029-09-30", "rate_pct": 12.0, "source": "MANUAL"})
    assert client.put("/api/securities/reference/KZKD00001087/coupons", json={"rows": rows}).status_code == 200
    with Session() as db:
        asyncio.run(fetch_and_apply(db, "KZKD00001087", "tester", client=_client()))
        db.commit()
        sched = db.execute(select(CouponSchedule).where(CouponSchedule.isin == "KZKD00001087")
                           .order_by(CouponSchedule.payment_date)).scalars().all()
    assert len(sched) == 10
    edited = next(r for r in sched if r.payment_date == date(2027, 3, 31))
    assert (edited.rate_pct, edited.source) == (12.0, "MANUAL")
    assert sched[-1].payment_date == date(2029, 9, 30) and sched[-1].source == "MANUAL"
    assert sched[0].source == "KASE"


def test_kase_endpoint_reports_unavailable_site(stand, monkeypatch):
    client, _, _ = stand

    async def boom(self, code=None, isin=None):
        raise httpx.ConnectError("proxy 403")
    monkeypatch.setattr(kc.KaseInstrumentClient, "fetch_issue", boom)
    r = client.post("/api/securities/reference/MUM108_0013/coupons/fetch-kase")
    assert r.status_code == 502 and "KASE" in r.json()["detail"]


# ───────────── calculations by the schedule ─────────────

def _rows(sample: str):
    return [cs.ScheduleRow(payment_date=r["payment_date"], rate=bm.rate_fraction(r["rate_pct"]))
            for r in kc.parse_coupon_payments(FIX[sample])]


def test_schedule_duration_equals_excel_for_fixed_and_uses_period_rates_for_floating():
    fixed = _rows("coupon-payments/MUM108_0013")
    md = cs.schedule_mduration(date(2026, 9, 24), fixed, date(2029, 3, 31), 0.16, bm.BASIS_30E_360, 1)
    assert md == pytest.approx(bm.excel_mduration(date(2026, 9, 24), date(2029, 3, 31), 0.11, 0.16, 1,
                                                  bm.BASIS_30E_360), abs=1e-9)
    flo = _rows("coupon-payments/KFUSb46")
    as_of = date(2026, 9, 24)
    by_schedule = cs.schedule_mduration(as_of, flo, date(2027, 11, 25), 0.16, bm.BASIS_ACT_365, 2)
    flat_low = bm.excel_mduration(as_of, date(2027, 11, 25), 0.10, 0.16, 2, bm.BASIS_ACT_365)
    assert by_schedule is not None and by_schedule < flat_low   # higher coupons → shorter duration
    # НКД of the floating issue on 24.09.2026: the period 25.05.2026 – 25.11.2026 pays 19.5 %
    acc = cs.accrued(1_000_000.0, flo, as_of, bm.BASIS_ACT_365)
    assert acc == pytest.approx(1_000_000 * 0.195 * (as_of - date(2026, 5, 25)).days / 365)


# ───────────── NBRK daily file ─────────────

@needs
def test_nbrk_daily_file_deposits_and_cash(stand):
    client, Session, _ = stand
    r = client.post("/api/primary-data/upload",
                    files={"file": ("КФГД_20260924.csv", (LOG_DIR / "КФГД_20260924.csv").read_bytes())})
    assert r.status_code == 200, r.text
    assert "депозитов 2" in r.json()["message"]
    with Session() as db:
        own = db.query(CDU).filter_by(portfolio_code="310138-1").one()
        spec = db.query(CDU).filter_by(portfolio_code="300138-1").one()
        legs = {(t.cdu_id, t.operation_type): t for t in db.query(Trade).filter_by(is_active=True)}
    assert legs[(own.id, "DEPOSIT_OPEN")].amount_kzt == -7_180_000_000
    assert legs[(own.id, "DEPOSIT_CLOSE")].value_date == date(2026, 10, 1)
    assert legs[(spec.id, "DEPOSIT_CLOSE")].amount_kzt == pytest.approx(42_970_000_000 + 135_773_263.89)
    # interest accrued in the system equals the NBRK figure (base 360)
    from services.portfolio.engine import build_portfolio
    with Session() as db:
        dep = build_portfolio(db, spec.id, date(2026, 10, 1) - __import__("datetime").timedelta(days=0)).deposits
        dep_30 = build_portfolio(db, spec.id, date(2026, 9, 30)).deposits[0]
    assert dep == []                       # repaid on 01.10
    assert dep_30.accrued == pytest.approx(42_970_000_000 * 0.1625 * 6 / 360)
    # re-import is idempotent
    client.post("/api/primary-data/upload",
                files={"file": ("КФГД_20260924.csv", (LOG_DIR / "КФГД_20260924.csv").read_bytes())})
    with Session() as db:
        assert db.query(Trade).filter_by(is_active=True).count() == 4


@needs
def test_nbrk_cash_reconciliation_by_ac_balance(stand):
    client, Session, _ = stand
    for n in ("КФГД_20260924.csv", "КФГД_20260925.csv"):
        client.post("/api/primary-data/upload", files={"file": (n, (LOG_DIR / n).read_bytes())})
    with Session() as db:
        own = db.query(CDU).filter_by(portfolio_code="310138-1").one()
        # our cash = AC balance of 23.09 + movements of 24.09: the placement of the file
        # (−7 180 000 000) and the return of a deposit placed before the first file
        # (not in the sample files) entered by hand with the bank charges.
        for amount, kind in ((7_179_449_722.22, "RECEIPT"), (-491_388.89, "COMMISSION")):
            db.add(CashMovement(cdu_id=own.id, operation_date=date(2026, 9, 24), amount=amount,
                                amount_kzt=amount, currency="KZT", movement_type=kind,
                                basis="Возврат депозита / комиссия", is_manual=True, workflow_status="APPROVED",
                                approved_by="checker", approved_at=datetime.utcnow()))
        db.commit()
        own_id = own.id
    res = client.post("/api/reconciliation/run", json={"cdu_id": own_id, "recon_date": "2026-09-24",
                                                       "recon_type": "nbrk_fallback"}).json()
    assert res["status"] == "OK", res
    assert res["actual_value"] == pytest.approx(104_611_478.69)
    assert "остаток 23.09.2026" in res["details_json"]

    # a missing movement is a real difference now (no more «balance vs itself»)
    with Session() as db:
        db.query(CashMovement).filter_by(cdu_id=own_id, movement_type="COMMISSION").delete()
        db.commit()
    res = client.post("/api/reconciliation/run", json={"cdu_id": own_id, "recon_date": "2026-09-24",
                                                       "recon_type": "nbrk_fallback"}).json()
    assert res["status"] == "MISMATCH" and res["deviation"] == pytest.approx(491_388.89)


# ───────────── Halyk / Centras Trade Reports (п.5 журнала) ─────────────

@needs
def test_halyk_and_centras_repo_cash_on_settlement_dates_and_daily_accrual(stand):
    client, Session, _ = stand
    for n in ("Trade report 2409 2026 Halyk Finance.xlsx", "Trade report 2509 2026 Halyk Finance.xlsx",
              "Trade report_24.09.2026 Centras.xlsx", "Trade report_25.09.2026 Centras.xlsx"):
        body = _upload(client, LOG_DIR / n)
        assert not body.get("warnings"), body["warnings"]      # «Казахстанский тенге» → KZT
    halyk = _cdu(Session, "Halyk Finance")
    centras = _cdu(Session, "Centras Securities")
    with Session() as db:
        cash = {}
        for cm in db.query(CashMovement).filter_by(is_active=True):
            cash[(cm.cdu_id, cm.operation_date)] = cash.get((cm.cdu_id, cm.operation_date), 0) + cm.amount_kzt
        # 24.09: 5 REPO, 25.09: 10 REPO — two legs each, all in KZT
        assert db.query(Trade).filter_by(cdu_id=centras.id, currency="KZT").count() == 30
    assert cash[(halyk.id, date(2026, 9, 24))] == pytest.approx(-3_513_713_003.99)
    assert cash[(centras.id, date(2026, 10, 1))] == pytest.approx(2_007_381_032.71)   # 7-day REPO
    from services.portfolio.engine import build_portfolio
    with Session() as db:
        v25 = sum(p.market_value for p in build_portfolio(db, halyk.id, date(2026, 9, 25)).repos)
        v26 = sum(p.market_value for p in build_portfolio(db, halyk.id, date(2026, 9, 26)).repos)
    assert v25 == pytest.approx(3_515_047_102.50)
    assert v26 - v25 == pytest.approx((3_519_722_532.66 - 3_515_047_102.50) / 3, rel=1e-6)
