"""Regression tests for the audit of 01.10.2026.

Every test pins a defect that was found in the code review together with the
business rule (Описание бизнес процессов.MD) it violated.  Tests that need
the sample documents from «Примеры» are skipped when the files are absent.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from database import Base
from models.db_models import (
    AccountReceivable, BondLot, CashMovement, CashSnapshot, CDU, InstrumentReference,
    KasePrice, PortfolioPosition, RepoLot, SourceDocument, Trade,
)
from services.portfolio import bond_math as bm
from services.portfolio.engine import build_portfolio
from services.parser.classification import detect_cdu_prefix
from services.parser.number_utils import parse_kz_number
from services.parser.trade_report_parser import ParsedRow, ParsedTradeFile

# «Примеры» lies inside the repository or next to it (C:\Projects\Сиуа\KDIF_FIN\Примеры)
EXAMPLES = next((p / "Примеры" for p in Path(__file__).resolve().parents[2:4] if (p / "Примеры").exists()),
                Path(__file__).resolve().parents[2] / "Примеры")


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with Session() as session:
        cdu = CDU(
            name="Halyk Finance", short_name="Halyk", participant_code="HALFN-1",
            participant_code_prefix="HALFN", portfolio_type="PRIVATE_CDU", is_active=True,
        )
        session.add(cdu)
        session.commit()
        yield session, cdu
    engine.dispose()


def _rr_doc(session, d: date) -> SourceDocument:
    doc = SourceDocument(doc_type="RISK_REPORT_XLSM", doc_date=d, file_name="rr.xlsm",
                         file_path="/tmp/rr.xlsm", parse_status="OK")
    session.add(doc)
    session.flush()
    return doc


# ─────────────────────────── bond math vs the Risk Report ───────────────────────────

def test_accrued_and_duration_reproduce_risk_report_30e_360():
    # KZKD00000535 on 31.12.2025 (risk report_31122025_.xlsm, sheet ГЦБ, Halyk):
    # face 6.25 bn, 5.49 %, annual, 30/360 → НКД 260 203 125, MD 1.01435
    acc = bm.accrued_interest(6_250_000_000, 0.0549, date(2025, 12, 31), date(2027, 3, 27), 1,
                              bm.normalize_basis("30/360"), start=date(2012, 3, 27))
    assert acc == pytest.approx(260_203_125.0, abs=1)
    md = bm.excel_mduration(date(2025, 12, 31), date(2027, 3, 27), 0.0549, 0.167620957321651, 1,
                            bm.normalize_basis("30/360"))
    assert md == pytest.approx(1.0143543216114277, abs=1e-3)


def test_coupon_schedule_is_counted_from_start_of_circulation():
    # BTRKb17: start 28.11.2024, semi-annual, maturity 28.03.2026 → coupons on
    # 28.05 / 28.11 (the Risk Report AR sheet shows the 28.11.2025 coupon).
    assert bm.is_coupon_date(date(2025, 11, 28), date(2026, 3, 28), 2, date(2024, 11, 28))
    assert not bm.is_coupon_date(date(2025, 9, 28), date(2026, 3, 28), 2, date(2024, 11, 28))
    assert bm.coupon_schedule(date(2024, 11, 28), date(2026, 3, 28), 2)[-1] == date(2026, 3, 28)


def test_period_coupon_equals_accrued_interest_debet_of_risk_report():
    # KZK200000687, 5 bn × 10.67 % / 2 = 266 750 000 («Accrued interest (debet)»)
    amount = bm.period_coupon_amount(5_000_000_000, 0.1067, date(2025, 7, 21), date(2026, 1, 21),
                                     bm.normalize_basis("30/360"))
    assert amount == pytest.approx(266_750_000.0)


def test_repo_metrics_reproduce_repo_sheet():
    # Tansar repo 120830728: open 29.12.2025, close 05.01.2026, valuation 31.12.2025
    m = bm.repo_metrics(238_038_936.8, 238_824_139.21, date(2025, 12, 29), date(2026, 1, 5),
                        date(2025, 12, 31))
    assert m["accrued"] == pytest.approx(224_343.5457, abs=0.01)
    assert m["ytm"] == pytest.approx(0.17247123272193213, rel=1e-9)
    assert m["duration"] == pytest.approx(0.011683553297239122, rel=1e-6)


# ─────────────────────────── roll-forward engine ───────────────────────────

def _seed_snapshot(session, cdu, base: date):
    doc = _rr_doc(session, base)
    session.add(InstrumentReference(
        isin="KZK200000687", coupon_rate_pct=10.67, frequency=2, base="30/360",
        maturity_date=date(2026, 1, 21), start_date=date(2022, 1, 21), issuer_type="ГЦБ",
    ))
    session.add(BondLot(
        cdu_id=cdu.id, isin="KZK200000687", category="GOV_BONDS",
        trade_date=date(2024, 7, 18), valuation_date=base,
        face_value_current=5_000_000_000, market_price=99.6743,
        accrued_interest=235_629_166.67, market_value=4_983_715_000,
        total_value=5_219_344_166.67, ytm=0.1557, duration=0.0541, source_doc_id=doc.id,
    ))
    session.add(RepoLot(
        cdu_id=cdu.id, deal_id="R1", trade_date=date(2025, 12, 29), valuation_date=base,
        close_date=date(2026, 1, 5), face_value=1_000_000.0, close_value=1_003_000.0,
        market_value=1_000_857.14, source_doc_id=doc.id,
    ))
    session.add(CashSnapshot(cdu_id=cdu.id, snapshot_date=base, currency="KZT",
                             amount=910_169.24, source="rr_import", source_doc_id=doc.id))
    session.commit()


def test_portfolio_does_not_disappear_after_the_risk_report_date(db):
    """Defect: on T+1 without a new Risk Report the bonds and REPO vanished
    (57.5 bn → 0.9 m) and false limit breaches were raised."""
    session, cdu = db
    base = date(2025, 12, 31)
    _seed_snapshot(session, cdu, base)

    same_day = build_portfolio(session, cdu.id, base).by_category()
    assert same_day["GOV_BONDS"]["mv"] == pytest.approx(5_219_344_166.67, abs=0.01)

    later = build_portfolio(session, cdu.id, date(2026, 1, 3))
    cats = later.by_category()
    # the bond is still there, accrued interest grew by 3 days (30E/360)
    expected_accrued = 5_000_000_000 * 0.1067 * bm.days360_e(date(2025, 7, 21), date(2026, 1, 3)) / 360
    assert cats["GOV_BONDS"]["mv"] == pytest.approx(5_000_000_000 * 99.6743 / 100 + expected_accrued, rel=1e-9)
    assert cats["REVERSE_REPO"]["mv"] > 1_000_857.14


def test_snapshot_repo_closing_is_booked_as_cash_until_the_real_movement_arrives(db):
    from services.calculator.portfolio_calculator import _calculate_cdu
    session, cdu = db
    _seed_snapshot(session, cdu, date(2025, 12, 31))
    positions, _ = _calculate_cdu(db=session, cdu=cdu, report_date=date(2026, 1, 6), kase_prices={}, mbm=None)
    by_cat = {p.instrument_category: p.market_value_current for p in positions}
    assert by_cat["REVERSE_REPO"] == 0.0
    assert by_cat["CASH"] == pytest.approx(910_169.24 + 1_003_000.0)

    # once the closing cash movement (Trade Report / statement) is loaded it is not added twice
    session.add(CashMovement(cdu_id=cdu.id, operation_date=date(2026, 1, 5), amount=1_003_000.0,
                             amount_kzt=1_003_000.0, movement_type="REPO_CLOSE", basis="TR",
                             is_manual=False, workflow_status="APPROVED", is_active=True))
    session.commit()
    positions, _ = _calculate_cdu(db=session, cdu=cdu, report_date=date(2026, 1, 6), kase_prices={}, mbm=None)
    by_cat = {p.instrument_category: p.market_value_current for p in positions}
    assert by_cat["CASH"] == pytest.approx(910_169.24 + 1_003_000.0)


def test_fifo_sale_writes_off_the_earliest_lot_without_mutating_snapshots(db):
    session, cdu = db
    base = date(2025, 12, 31)
    _seed_snapshot(session, cdu, base)
    session.add(Trade(
        cdu_id=cdu.id, trade_date=date(2026, 1, 5), value_date=date(2026, 1, 5),
        operation_type="SELL", isin="KZK200000687", instrument_category="GOV_BONDS",
        face_value=1_000_000_000, amount_kzt=1_000_000_000, workflow_status="APPROVED", is_active=True,
    ))
    session.commit()
    state = build_portfolio(session, cdu.id, date(2026, 1, 6))
    assert sum(b.face_value for b in state.bonds) == pytest.approx(4_000_000_000)
    lot = session.execute(select(BondLot)).scalars().one()
    assert lot.face_value_current == 5_000_000_000  # snapshot untouched


def test_kase_dtm_is_not_used_as_duration(db):
    session, cdu = db
    base = date(2025, 12, 31)
    _seed_snapshot(session, cdu, base)
    session.add(KasePrice(trade_date=date(2026, 1, 5), instrument_code="MOM048_0052",
                          isin="KZK200000687", close_price=99.9, ytm=0.15, duration=16.0, dtm=16.0,
                          unit_ru="чистая цена в %"))
    session.commit()
    state = build_portfolio(session, cdu.id, date(2026, 1, 5))
    bond = state.bonds[0]
    assert bond.price == 99.9 and bond.price_source == "market"
    assert bond.duration is not None and bond.duration < 1.0


# ─────────────────────────── importers ───────────────────────────

def test_purchase_cash_includes_accrued_interest_and_manual_cdu_wins(db):
    from services.parser.trade_importer import import_trades_from_parsed
    session, cdu = db
    other = CDU(name="BCC Invest", short_name="BCC", participant_code="BCC-1",
                participant_code_prefix="BCC", portfolio_type="PRIVATE_CDU", is_active=True)
    session.add(other)
    session.commit()
    parsed = ParsedTradeFile(
        cdu_prefix="HALFN", cdu_name="Halyk Finance", trade_date=date(2026, 7, 9),
        rows=[ParsedRow(2, {
            "deal_number": "D1", "operation_type": "BUY", "instrument_code": "MUM072_0016",
            "instrument_category": "GOV_BONDS", "trade_date": date(2026, 7, 9),
            "settlement_date": date(2026, 7, 13), "price": 97.14, "volume": 3_885_600_000.0,
            "accrued_interest_volume": 487_997_333.33, "placement_amount": 4_373_597_333.33,
            "nominal_volume": 4_000_000_000.0, "securities_to_execute": 4_000_000,
            "currency_code": "KZT", "commission_clearing": 10.0, "commission_trading": 5.0,
        })],
        filename="tr.xlsx",
    )
    import_trades_from_parsed(session, parsed, cdu_id=other.id)
    trade = session.execute(select(Trade)).scalars().one()
    assert trade.cdu_id == other.id                       # selected manager is authoritative
    assert trade.amount_kzt == pytest.approx(-4_373_597_333.33)  # «Сумма» with НКД
    assert trade.face_value == pytest.approx(4_000_000_000.0)
    assert trade.quantity == pytest.approx(4_000_000)
    assert trade.clean_price == pytest.approx(97.14)
    assert (trade.commission_clearing, trade.commission_kase) == (10.0, 5.0)


def test_reimport_keeps_manual_and_system_operations(db):
    from services.parser.trade_importer import import_trades_from_parsed
    session, cdu = db
    d = date(2026, 7, 9)
    manual = Trade(cdu_id=cdu.id, trade_date=d, value_date=d, operation_type="BUY", is_manual=True,
                   workflow_status="APPROVED", is_active=True, amount_kzt=-1.0)
    coupon = Trade(cdu_id=cdu.id, trade_date=d, value_date=d, operation_type="COUPON", is_synthetic=True,
                   workflow_status="APPROVED", is_active=True, amount_kzt=1.0, isin="X")
    session.add_all([manual, coupon])
    session.commit()
    parsed = ParsedTradeFile(cdu_prefix="HALFN", cdu_name="Halyk Finance", trade_date=d, rows=[
        ParsedRow(2, {"deal_number": "S1", "operation_type": "SELL", "instrument_code": "MUM1",
                      "trade_date": d, "settlement_date": d, "volume": 100.0, "price": 100.0,
                      "nominal_volume": 100.0, "currency_code": "KZT"}),
    ], filename="tr.xlsx")
    import_trades_from_parsed(session, parsed, cdu_id=cdu.id)
    import_trades_from_parsed(session, parsed, cdu_id=cdu.id)
    session.refresh(manual); session.refresh(coupon)
    assert manual.is_active and coupon.is_active
    assert session.query(Trade).filter_by(deal_id="S1", is_active=True).count() == 1


def test_number_and_cdu_detection_edge_cases():
    assert parse_kz_number("16,55%") == pytest.approx(16.55)
    assert parse_kz_number("1,214.9000") == pytest.approx(1214.9)
    assert parse_kz_number("(1 234,50)") == pytest.approx(-1234.5)
    assert parse_kz_number("1.234.567,89") == pytest.approx(1234567.89)
    # Halyk files carry the clearing member CENTR_K — not a Centras file
    assert detect_cdu_prefix("HALFN0BT13|HALFN|I+1HACE30099", "Trade report 1009 2025.xlsx") == "HALFN"
    assert detect_cdu_prefix("KIBAM0BT11|KIBAM", "сделки.xlsx") == "KIBAM"
    # KASE member CAIFC is Tansar Capital (ex CAIFC Investment Group), not Centras
    from services.parser.classification import DEFAULT_CDU_PREFIXES
    assert DEFAULT_CDU_PREFIXES[detect_cdu_prefix("CAIFC0BT07|CAIFC", "x.xlsx")] == "Tansar Capital"
    assert DEFAULT_CDU_PREFIXES[detect_cdu_prefix("CESEC0BT01|CESEC", "x.xlsx")] == "Centras Securities"


def test_reference_category_has_priority_and_microfinance_is_not_mfo(db):
    from services.portfolio.reference import ReferenceBook
    session, _ = db
    session.add_all([
        InstrumentReference(isin="KZ2C00008951", ticker_kase="KFUSb49",
                            issuer="Казахстанский фонд устойчивости", issuer_type="Агентские"),
        InstrumentReference(isin="KZ2D00009222", ticker_kase="EABRb42",
                            issuer="Евразийский банк развития", issuer_type="МФО"),
    ])
    session.commit()
    refs = ReferenceBook(session)
    assert refs.category("KFUSb49") == "AGENCY_BONDS"
    assert refs.category("EABRb42") == "MFO_BONDS"
    assert refs.category("MFOKb3") == "OTHER"


# ─────────────────────────── primary documents ───────────────────────────

@pytest.mark.skipif(not (EXAMPLES / "Пример 2 Первчика ЧДУ").exists(), reason="examples missing")
def test_reconciliation_files_of_all_managers_are_parsed():
    from services.import_primary.recon_parser import parse_reconciliation_xlsx
    cases = {
        "Пример 1 Первичка ЧДУ/Сверка КФГД за 10.09.2025.xlsx":
            (date(2025, 9, 10), 286_949_138.61, 11_529_489_772.55, 53_606_826_340.5637),
        "Пример 2 Первчика ЧДУ/Сверка КФГД на 11 09 2025 BCC Invest.xlsx":
            (date(2025, 9, 11), 3_146_420.10, 3_485_608_992.47, 51_848_298_721.71),
        "Пример 3 Первичка от ЧДУ/Приложение 3 Сверка за 05.09.2025 г..xlsx":
            (date(2025, 9, 5), 904_950.70, 4_870_027_572.150001, 22_015_157_784.25778),
    }
    for rel, (d, cash, repo, total) in cases.items():
        parsed = parse_reconciliation_xlsx(EXAMPLES / rel)
        assert parsed["report_date"] == d, rel
        assert parsed["totals"]["cash"] == pytest.approx(cash), rel
        assert parsed["totals"]["repo"] == pytest.approx(repo), rel
        assert parsed["totals"]["total"] == pytest.approx(total), rel
        assert parsed["warnings"] == [], rel


@pytest.mark.skipif(not (EXAMPLES / "Пример 2 Первчика ЧДУ").exists(), reason="examples missing")
def test_statements_closing_balance_per_account_and_currency():
    from services.import_primary.statement_parser import parse_pdf_statement
    halyk_cust = parse_pdf_statement(EXAMPLES / "Пример 2 Первчика ЧДУ/11092025 КФГД.pdf")
    assert halyk_cust["closing_by_currency"] == {"USD": 0.0, "KZT": pytest.approx(3_146_420.10)}
    assert "KZ44601A861038135531" in halyk_cust["accounts_found"]
    bcc = parse_pdf_statement(EXAMPLES / "Пример 3 Первичка от ЧДУ/выписка с инвест счета 05.09.2025.pdf")
    assert bcc["closing_by_currency"]["KZT"] == pytest.approx(904_950.70)  # not 904 950.00


# ─────────────────────────── governance ───────────────────────────

def test_report_cannot_be_approved_by_its_author():
    from fastapi import HTTPException
    from models.db_models import GeneratedReport
    from services import report_approval
    report = GeneratedReport(report_date=date(2026, 1, 1), file_path="x", status="pending_approval",
                             generated_by="alice", submitted_by="alice")
    with pytest.raises(HTTPException) as exc:
        report_approval.approve(None, report, actor="alice")  # type: ignore[arg-type]
    assert exc.value.status_code == 409


def test_risk_report_receivable_missing_from_new_snapshot_is_closed(db):
    from services.import_rr.risk_report_importer import _upsert_ar
    from api.routes.accounting import receivable_balance_as_of
    session, cdu = db
    doc1 = _rr_doc(session, date(2025, 11, 28))
    _upsert_ar(session, [{"cdu_name": cdu.name, "isin": "KZ2C00012698", "record_date": date(2025, 11, 28),
                          "balance_kzt": 121_537_500.0, "description": "Сумма купона"}],
               {cdu.name: cdu.id}, doc1.id, date(2025, 11, 28))
    session.commit()
    doc2 = _rr_doc(session, date(2025, 12, 31))
    _upsert_ar(session, [], {cdu.name: cdu.id}, doc2.id, date(2025, 12, 31))
    # the CDU is "present" only when it has rows; emulate another AR row of the CDU
    _upsert_ar(session, [{"cdu_name": cdu.name, "isin": "KZOTHER00001", "record_date": date(2025, 12, 31),
                          "balance_kzt": 1.0}], {cdu.name: cdu.id}, doc2.id, date(2025, 12, 31))
    session.commit()
    ar = session.execute(select(AccountReceivable).where(AccountReceivable.isin == "KZ2C00012698")).scalars().one()
    assert ar.status == "CLOSED"
    assert receivable_balance_as_of(session, ar, date(2025, 12, 30)) == pytest.approx(121_537_500.0)
    assert receivable_balance_as_of(session, ar, date(2025, 12, 31)) == 0.0


# ─────────────────────────── duration corridor & certificates ───────────────────────────

def test_duration_corridor_is_relative_to_benchmark_as_in_risk_report():
    # Report!E18 = D18*0.8, F18 = D18*1.5 («−0,2» / «+0,5» are −20 % / +50 %)
    from services.calculator.constants import duration_band
    lo, hi = duration_band(2.14)
    assert lo == pytest.approx(1.712)
    assert hi == pytest.approx(3.21)
    assert duration_band(None) == (None, None)


def _trade(session, cdu, deal_id, op, amount, d):
    session.add(Trade(cdu_id=cdu.id, trade_date=d, value_date=d, operation_type=op,
                      deal_id=deal_id, amount_kzt=amount, is_active=True, is_manual=False))


def test_certificate_is_bound_by_deal_numbers_and_neighbour_repo_leg_is_not_stolen(db):
    import json
    from models.db_models import ReconciliationResult
    from services.import_primary.binding import bind_orphan_certificates
    from services.reconciliation.engine import _recon_trade_vs_cert
    session, cdu = db
    d = date(2025, 9, 11)
    _trade(session, cdu, "119063203", "REPO_OPEN", -1_735_873_516.98, d)
    _trade(session, cdu, "119063204", "REPO_CLOSE", 1_736_634_447.84, d)
    _trade(session, cdu, "119063206", "REPO_OPEN", -1_730_727_485.76, d)
    meta = {"deal_ids": ["119063203", "119068206"], "deals": [
        {"deal_id": "119063203", "amounts": [1_735_873_516.98], "lines": ["119063203 RepoOpen 1 735 873 516.98"]},
        # OCR garbled one digit of 119063206; the amount (with a lost space) confirms it
        {"deal_id": "119068206", "amounts": [], "lines": ["119068206 RepoOpen 1730727 485.76 11.09.2025"]},
    ]}
    cert = SourceDocument(doc_type="CERTIFICATE", doc_date=d, file_name="cert.png", file_path="/tmp/c.png",
                          parse_status="OK", parse_meta_json=json.dumps(meta))
    session.add(cert)
    session.flush()
    assert bind_orphan_certificates(session, d) == 1
    assert cert.cdu_id == cdu.id

    res = ReconciliationResult(recon_date=d, cdu_id=cdu.id, recon_type="trade_vs_cert")
    _recon_trade_vs_cert(session, res, cdu.id, d)
    items = {i["deal_id"]: i for i in json.loads(res.details_json)["items"]}
    assert items["119063203"]["status"] == "OK"
    assert items["119063206"]["match"] == "ocr≈119068206"
    # the close leg differs from 119063203 by one digit but must NOT match it
    assert items["119063204"]["status"] == "NOT_FOUND"
    assert res.status == "MISMATCH"
