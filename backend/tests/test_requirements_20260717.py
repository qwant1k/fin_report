from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.routes.accounting import (
    approve, cancel, create_cash, create_trade, overview,
    receivable_balance_as_of, reject,
)
from api.routes.dashboard import dashboard_summary
from database import Base
from models.db_models import (
    AccountReceivable, BondLot, CashBalance, CashMovement, CDU, FXRate, KasePrice,
    InstrumentReference, KaseRiskPrice, PortfolioPosition, PortfolioSummary,
    ReceivableTransaction, RepoLot, Trade, User,
)
from services.calculator.portfolio_calculator import _calculate_cdu, _cmv_for_position
from services.calculator.position_builder import PositionAggregate, build_positions
from services.parser.trade_report_parser import ParsedRow, ParsedTradeFile, TradeReportParser
from services.parser.trade_importer import _ensure_instrument_reference, import_trades_from_parsed
from services.kase.propagation import _reprice_bond_lots
from services.kase.risk_client import parse_risk_price_rows


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as session:
        cdu = CDU(
            name="Centras Securities", short_name="Centras",
            participant_code="CENTR-01", participant_code_prefix="CENTR",
            portfolio_type="PRIVATE_CDU", share_target_pct=0.0, is_active=True,
        )
        creator = User(username="operator", password_hash="x", role="operator", is_active=True)
        approver = User(username="analyst", password_hash="x", role="analyst", is_active=True)
        session.add_all([cdu, creator, approver]); session.commit()
        yield session, cdu, creator, approver
    engine.dispose()


@pytest.mark.parametrize(("firm_code", "expected_name"), [
    ("CENTR-01", "Centras Securities"),
    ("TANSR-01", "Tansar Capital"),
    ("ALATAU-01", "Alatau City Invest"),
])
def test_parser_detects_cdu_by_firm_code_and_normalises_percent(
    tmp_path, firm_code, expected_name,
):
    wb = Workbook(); ws = wb.active
    ws.append([
        "К/П", "Код режима", "Код инструмента", "Статус", "Код участника",
        "Код фирмы", "Торговый счет", "Объем", "Дата торгов", "Дата расчетов",
        "Доходность", "Ставка РЕПО, %",
    ])
    ws.append(["К", "T+", "KZTEST", "M", "UNKNOWN", firm_code, "ACC", 1000,
               "17.07.2026", "20.07.2026", 6.66, 15.25])
    ws.append(["?", "UNSUPPORTED", "KZTEST2", "M", "UNKNOWN", firm_code, "ACC", 1000,
               "17.07.2026", "20.07.2026", None, None])
    path = tmp_path / "neutral.xlsx"; wb.save(path)

    parsed = TradeReportParser(path).parse()

    assert parsed.cdu_name == expected_name
    assert parsed.rows[0].fields["yield_pct"] == pytest.approx(0.0666)
    assert parsed.rows[0].fields["repo_rate_pct"] == pytest.approx(0.1525)
    assert parsed.rows[1].fields["operation_type"] == "OTHER"
    assert parsed.warnings


def test_repo_uses_open_amount_plus_accrual_until_close():
    rows = [
        {
            "operation_type": "REPO_OPEN", "order_number": "R1",
            "instrument_code": "KZ1", "instrument_category": "REVERSE_REPO",
            "trade_date": date(2026, 7, 1), "settlement_date": date(2026, 7, 1),
            "repo_sum": 1_000_000.0, "repo_rate_pct": 0.10,
            "repo_term_days": 10,
        },
        {
            "operation_type": "REPO_CLOSE", "order_number": "R1",
            "instrument_code": "KZ1", "instrument_category": "REVERSE_REPO",
            "trade_date": date(2026, 7, 1), "settlement_date": date(2026, 7, 11),
            "repo_buyback_sum": 1_002_739.726,
        },
    ]
    position = build_positions(rows, cdu_id=1, report_date=date(2026, 7, 6))[0]

    assert position.repo_open_sum == 1_000_000.0
    assert position.repo_accrued_interest == pytest.approx(1_369.863, rel=1e-5)
    assert _cmv_for_position(position, {}) == pytest.approx(1_001_369.863, rel=1e-5)
    assert build_positions(rows, cdu_id=1, report_date=date(2026, 7, 11)) == []


def test_repo_keeps_multiple_deals_with_the_same_order_number_separate():
    rows = []
    for instrument, amount, buyback in (("KZ1", 1_000_000.0, 1_001_000.0),
                                         ("KZ2", 2_000_000.0, 2_002_000.0)):
        common = {
            "order_number": "SAME-ORDER", "instrument_code": instrument,
            "instrument_category": "REVERSE_REPO", "trade_date": date(2026, 7, 1),
            "repo_sum": amount, "repo_buyback_sum": buyback, "repo_term_days": 1,
        }
        rows.extend([
            {**common, "operation_type": "REPO_HEADER", "settlement_date": date(2026, 7, 1)},
            {**common, "operation_type": "REPO_OPEN", "settlement_date": date(2026, 7, 1)},
            {**common, "operation_type": "REPO_CLOSE", "settlement_date": date(2026, 7, 2)},
        ])

    positions = build_positions(rows, cdu_id=1, report_date=date(2026, 7, 1))
    assert {p.instrument_code for p in positions} == {"KZ1", "KZ2"}
    assert sum(p.repo_open_sum for p in positions) == 3_000_000.0
    assert build_positions(rows, cdu_id=1, report_date=date(2026, 7, 2)) == []


def test_manual_cash_requires_another_user_and_affects_calculation(db):
    session, cdu, creator, approver = db
    session.add(CashBalance(cdu_id=cdu.id, balance_date=date(2026, 7, 16), currency="KZT", amount=1000.0))
    session.commit()
    row = create_cash({
        "cdu_id": cdu.id, "operation_date": "2026-07-17", "amount": 250,
        "currency": "KZT", "movement_type": "CORRECTION",
        "basis": "Выписка кастодиана", "change_reason": "Корректировка факта",
    }, db=session, user=creator)
    assert row["workflow_status"] == "PENDING_APPROVAL"

    with pytest.raises(HTTPException) as exc:
        approve("cash-movements", row["id"], {}, db=session, user=creator)
    assert exc.value.status_code == 409

    approve("cash-movements", row["id"], {}, db=session, user=approver)
    positions, _ = _calculate_cdu(
        db=session, cdu=cdu, report_date=date(2026, 7, 17), kase_prices={}, mbm=None,
    )
    cash = next(p for p in positions if p.instrument_category == "CASH")
    assert cash.market_value_current == 1250.0


def test_foreign_currency_manual_cash_uses_latest_rate(db):
    session, cdu, creator, _ = db
    session.add(FXRate(
        rate_date=date(2026, 7, 16), currency="USD", rate=520.0, source="NBRK",
    ))
    session.commit()
    row = create_cash({
        "cdu_id": cdu.id, "operation_date": "2026-07-17", "amount": -10,
        "currency": "USD", "movement_type": "PAYMENT",
        "basis": "Комиссия", "change_reason": "Банковская выписка",
    }, db=session, user=creator)
    assert row["amount_kzt"] == -5200.0


def test_receivable_balance_is_historical_as_of_selected_date(db):
    session, cdu, _, _ = db
    ar = AccountReceivable(
        cdu_id=cdu.id, record_date=date(2026, 7, 1), counterparty="Контрагент",
        description="Купон", amount=1000.0, amount_kzt=1000.0,
        balance_kzt=700.0, currency="KZT", status="PARTIAL",
        workflow_status="APPROVED", is_active=True,
    )
    session.add(ar); session.flush()
    session.add(ReceivableTransaction(
        receivable_id=ar.id, operation_date=date(2026, 7, 10),
        operation_type="REPAYMENT", amount=300.0, amount_kzt=300.0,
        currency="KZT", basis="Платёж", workflow_status="APPROVED", is_active=True,
    ))
    session.commit()

    assert receivable_balance_as_of(session, ar, date(2026, 7, 9)) == 1000.0
    assert receivable_balance_as_of(session, ar, date(2026, 7, 10)) == 700.0


def test_trade_cancellation_disables_and_rejection_restores_derived_cash(db):
    session, cdu, creator, approver = db
    trade = create_trade({
        "cdu_id": cdu.id, "trade_date": "2026-07-17", "value_date": "2026-07-20",
        "operation_type": "BUY", "instrument_category": "GOV_BONDS",
        "isin": "KZTEST000001", "amount_kzt": 1_000_000,
        "currency": "KZT", "change_reason": "Внебиржевая сделка",
    }, db=session, user=creator)
    approve("trades", trade["id"], {}, db=session, user=approver)
    movement = session.query(CashMovement).filter_by(related_trade_id=trade["id"]).one()
    assert movement.is_active is True
    assert movement.amount_kzt == -1_000_000

    # Maker-checker: an unapproved cancellation request does not change the
    # books — the trade and its cash leg stay effective until approved.
    cancel("trades", trade["id"], {"comment": "Ошибочная сделка"}, db=session, user=creator)
    session.refresh(movement)
    assert movement.is_active is True
    assert movement.workflow_status == "PENDING_CANCELLATION"

    reject("trades", trade["id"], {"comment": "Сделка подтверждена"}, db=session, user=approver)
    session.refresh(movement)
    assert movement.is_active is True
    assert movement.workflow_status == "APPROVED"

    # A cancellation approved by a second person removes the cash leg.
    cancel("trades", trade["id"], {"comment": "Ошибочная сделка"}, db=session, user=creator)
    approve("trades", trade["id"], {}, db=session, user=approver)
    session.refresh(movement)
    assert movement.is_active is False
    assert movement.workflow_status == "CANCELLED"


def test_risk_parameter_price_parsing_and_market_first_hierarchy(db):
    rows = [
        ["Дата оценки"], [46223.0], [],
        ["№ п/п", "Торговый код", "ISIN", "Алгоритмы и параметры расчета ЦБ",
         "Краткое наименование эмитента", "Расчетная цена", "Расчетная грязная",
         "Доходность до погашения. % годовых", "Дней до погашения", "Единица измерения цены"],
        [1, "MARKET1", "KZ0000000001", "algo", "Issuer", 95.0, 96.0, 6.66, 500, "%"],
    ]
    parsed = parse_risk_price_rows(rows, fallback_date=date(2026, 7, 20))
    assert parsed[0].settlement_price == 95.0
    assert parsed[0].ytm == pytest.approx(0.0666)

    session, cdu, _, _ = db
    for code in ("MARKET1", "RISK2", "PURCHASE3"):
        session.add(BondLot(
            cdu_id=cdu.id, isin=code, instrument_code=code, category="GOV_BONDS",
            trade_date=date(2026, 7, 1), valuation_date=date(2026, 7, 20),
            quantity_initial=1000, quantity_current=1000,
            face_value_initial=1000, face_value_current=1000, purchase_price=90,
        ))
    session.commit()
    market = KasePrice(
        trade_date=date(2026, 7, 20), instrument_code="MARKET1",
        close_price=101.0, ytm=0.05,
    )
    market_shadow_risk = KaseRiskPrice(
        trade_date=date(2026, 7, 20), instrument_code="MARKET1",
        settlement_price=95.0, ytm=0.0666,
    )
    risk = KaseRiskPrice(
        trade_date=date(2026, 7, 20), instrument_code="RISK2",
        settlement_price=98.0, ytm=0.07,
    )
    counters = _reprice_bond_lots(
        session, report_date=date(2026, 7, 20),
        kase_idx={"MARKET1": market},
        risk_idx={"MARKET1": market_shadow_risk, "RISK2": risk},
    )
    lots = {lot.instrument_code: lot for lot in session.query(BondLot).all()}
    assert counters == {"market": 1, "risk_parameters": 1, "unchanged": 1}
    assert (lots["MARKET1"].market_price, lots["MARKET1"].price_source) == (101.0, "market")
    assert (lots["RISK2"].market_price, lots["RISK2"].price_source) == (98.0, "risk_parameters")
    assert lots["PURCHASE3"].market_price is None


def test_existing_incomplete_reference_is_enriched_from_kase(db):
    session, _, _, _ = db
    ref = InstrumentReference(
        isin="KZKD00001319", ticker_kase="MUM072_0016", issuer="Минфин",
        source="MANUAL",
    )
    quote = KasePrice(
        trade_date=date(2026, 7, 9), instrument_code="MUM072_0016",
        isin="KZKD00001319", instrument_name="Минфин",
        org_name_ru="Минфин", fin_sec_ru="государственные ценные бумаги",
        unit_ru="чистая цена в %", close_price=97.14, ytm=0.1438,
    )
    session.add_all([ref, quote]); session.commit()

    created, complete = _ensure_instrument_reference(session, "MUM072_0016")

    assert created is False
    assert complete is True
    assert ref.instrument_name == "Минфин"
    assert ref.security_type == "государственные ценные бумаги"
    assert ref.source == "KASE_MARKET"


def test_fund_ytm_uses_instrument_value_not_cash_balance(db):
    session, first_cdu, _, _ = db
    second_cdu = CDU(
        name="Tansar Capital", short_name="Tansar",
        participant_code="TANSR-01", participant_code_prefix="TANSR",
        portfolio_type="PRIVATE_CDU", share_target_pct=0.0, is_active=True,
    )
    session.add(second_cdu); session.flush()
    report_date = date(2026, 7, 17)
    session.add_all([
        PortfolioSummary(
            cdu_id=first_cdu.id, summary_date=report_date,
            total_mv_current=1_000.0, ytm_weighted=0.10, duration_weighted=1.0,
        ),
        PortfolioSummary(
            cdu_id=second_cdu.id, summary_date=report_date,
            total_mv_current=100.0, ytm_weighted=0.20, duration_weighted=2.0,
        ),
        PortfolioPosition(
            cdu_id=first_cdu.id, position_date=report_date,
            instrument_category="GOV_BONDS", market_value_current=100.0,
            ytm=0.10, duration=1.0,
        ),
        PortfolioPosition(
            cdu_id=first_cdu.id, position_date=report_date,
            instrument_category="CASH", market_value_current=900.0,
        ),
        PortfolioPosition(
            cdu_id=second_cdu.id, position_date=report_date,
            instrument_category="GOV_BONDS", market_value_current=100.0,
            ytm=0.20, duration=2.0,
        ),
    ])
    session.commit()

    payload = dashboard_summary(
        report_date=report_date, from_=None, to_=None, db=session,
    )

    assert payload.fund_ytm_weighted == pytest.approx(0.15)
    assert payload.fund_duration_weighted == pytest.approx(1.5)


def test_repo_lots_with_same_security_are_matched_by_order(db):
    session, cdu, _, _ = db
    report_date = date(2026, 7, 17)

    def repo_row(index, order, operation, amount, buyback, settlement):
        return ParsedRow(index, {
            "deal_number": f"{order}-{operation}",
            "order_number": order,
            "operation_type": operation,
            "instrument_code": "KZ-SAME",
            "instrument_category": "REVERSE_REPO",
            "trade_date": report_date,
            "settlement_date": settlement,
            "repo_sum": amount,
            "repo_buyback_sum": buyback,
            "repo_rate_pct": 0.10,
            "repo_term_days": 10,
            "volume": buyback if operation == "REPO_CLOSE" else amount,
            "currency_code": "KZT",
        })

    parsed = ParsedTradeFile(
        cdu_prefix="CENTR", cdu_name=cdu.name, trade_date=report_date,
        rows=[
            repo_row(2, "ORDER-1", "REPO_OPEN", 1_000.0, 1_010.0, report_date),
            repo_row(3, "ORDER-2", "REPO_OPEN", 2_000.0, 2_040.0, report_date),
            repo_row(4, "ORDER-2", "REPO_CLOSE", 2_000.0, 2_040.0, date(2026, 7, 27)),
            repo_row(5, "ORDER-1", "REPO_CLOSE", 1_000.0, 1_010.0, date(2026, 7, 27)),
        ],
        filename="same-security.xlsx",
    )

    import_trades_from_parsed(session, parsed)
    lots = session.query(RepoLot).order_by(RepoLot.deal_id).all()

    assert len(lots) == 2
    assert [(row.deal_id, row.face_value, row.close_value) for row in lots] == [
        ("ORDER-1", 1_000.0, 1_010.0),
        ("ORDER-2", 2_000.0, 2_040.0),
    ]


def test_import_preserves_row_dates_and_converts_foreign_cash(db):
    session, cdu, _, _ = db
    session.add(FXRate(
        rate_date=date(2026, 7, 20), currency="USD", rate=520.0, source="NBRK",
    ))
    session.commit()
    parsed = ParsedTradeFile(
        cdu_prefix="CENTR", cdu_name=cdu.name, trade_date=date(2026, 7, 17),
        rows=[
            ParsedRow(2, {
                "deal_number": "BUY-USD", "operation_type": "BUY",
                "instrument_code": "US0001", "instrument_category": "FOREIGN_BONDS",
                "trade_date": date(2026, 7, 18), "settlement_date": date(2026, 7, 20),
                "volume": 1_000.0, "nominal_volume": 1_000.0,
                "price": 100.0, "currency_code": "USD",
            }),
            ParsedRow(3, {
                "deal_number": "SELL-KZT", "operation_type": "SELL",
                "instrument_code": "KZ0001", "instrument_category": "GOV_BONDS",
                "trade_date": date(2026, 7, 19), "settlement_date": date(2026, 7, 21),
                "volume": 2_000.0, "nominal_volume": 2_000.0,
                "price": 100.0, "currency_code": "KZT",
            }),
        ],
        filename="mixed-dates.xlsx",
    )

    import_trades_from_parsed(session, parsed)
    trades = {row.deal_id: row for row in session.query(Trade).all()}
    movements = {
        row.related_trade_id: row for row in session.query(CashMovement).all()
    }

    assert trades["BUY-USD"].trade_date == date(2026, 7, 18)
    assert trades["SELL-KZT"].trade_date == date(2026, 7, 19)
    assert trades["BUY-USD"].amount_ccy == -1_000.0
    assert trades["BUY-USD"].amount_kzt == -520_000.0
    assert trades["BUY-USD"].fx_rate == 520.0
    assert movements[trades["BUY-USD"].id].amount_kzt == -520_000.0


def test_foreign_bond_cmv_uses_report_date_fx_rate():
    position = PositionAggregate(
        cdu_id=1, instrument_code="US0001", instrument_category="FOREIGN_BONDS",
        currency="USD", nominal_volume=1_000.0, last_price=95.0,
        accrued_interest=5.0,
    )

    assert _cmv_for_position(position, {}, {"USD": 520.0}) == pytest.approx(496_600.0)


def test_repo_overview_starts_on_value_date(db):
    session, cdu, _, _ = db
    session.add(RepoLot(
        cdu_id=cdu.id, deal_id="FUTURE", instrument_code="KZ1",
        trade_date=date(2026, 7, 17), valuation_date=date(2026, 7, 20),
        face_value=1_000.0, repo_rate_pct=0.10, term_days=5,
    ))
    session.commit()

    before = overview(report_date=date(2026, 7, 19), cdu_id=cdu.id, db=session)
    opened = overview(report_date=date(2026, 7, 20), cdu_id=cdu.id, db=session)

    assert before["repo_positions"] == []
    assert [row["deal_id"] for row in opened["repo_positions"]] == ["FUTURE"]
