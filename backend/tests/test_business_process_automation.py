from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import database as db_module
from database import Base
from models.db_models import (
    CDU,
    CashSnapshot,
    PortfolioPosition,
    PortfolioSummary,
    RepoLot,
    SourceDocument,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from api.routes.dashboard import dashboard_summary
from services.calculator.portfolio_calculator import calculate_for_date
from services.calculator.constants import DEFAULT_CDU_SEED
from services.import_primary.holdings_parser import import_holdings_xlsx, parse_holdings_xlsx
from services.import_primary.recon_parser import parse_reconciliation_xlsx
from services.import_rr.risk_report_importer import import_risk_report
from services.reconciliation.engine import run_reconciliation


EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "Примеры"
REAL_HOLDINGS_FILE = EXAMPLES_DIR / "Пример 3 Первичка от ЧДУ" / "Приложение 2 Holdings report 05.09.2025.xlsx"
REAL_RECON_FILE = EXAMPLES_DIR / "Пример 1 Первичка ЧДУ" / "Сверка КФГД за 10.09.2025.xlsx"
REAL_RISK_REPORT = EXAMPLES_DIR / "risk report_09112025_.xlsm"


@pytest.fixture()
def in_memory_db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", SessionLocal)

    from models import db_models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        for seed in DEFAULT_CDU_SEED:
            prefix = seed["participant_code_prefix"]
            portfolio_code = seed.get("portfolio_code")
            participant_code = f"{prefix}_{portfolio_code}" if portfolio_code else prefix
            db.add(
                CDU(
                    name=seed["name"],
                    short_name=seed["short_name"],
                    participant_code=participant_code,
                    participant_code_prefix=prefix,
                    portfolio_type=seed["portfolio_type"],
                    portfolio_code=portfolio_code,
                    share_target_pct=seed["share_target_pct"],
                    is_active=True,
                )
            )
        db.commit()

    yield SessionLocal
    engine.dispose()


def test_dashboard_summary_respects_selected_period(in_memory_db):
    session_local = in_memory_db

    with session_local() as db:
        halyk = db.execute(select(CDU).where(CDU.name == "Halyk Finance")).scalars().one()
        bcc = db.execute(select(CDU).where(CDU.name == "BCC Invest")).scalars().one()

        db.add_all(
            [
                PortfolioSummary(
                    cdu_id=halyk.id,
                    summary_date=date(2025, 9, 10),
                    total_mv_prev=90.0,
                    total_daily_change=10.0,
                    total_mv_current=100.0,
                    cdu_share_pct=0.0,
                    ytm_weighted=0.10,
                    duration_weighted=1.0,
                ),
                PortfolioSummary(
                    cdu_id=halyk.id,
                    summary_date=date(2025, 9, 11),
                    total_mv_prev=100.0,
                    total_daily_change=20.0,
                    total_mv_current=120.0,
                    cdu_share_pct=0.0,
                    ytm_weighted=0.11,
                    duration_weighted=1.1,
                ),
                PortfolioSummary(
                    cdu_id=bcc.id,
                    summary_date=date(2025, 9, 10),
                    total_mv_prev=180.0,
                    total_daily_change=20.0,
                    total_mv_current=200.0,
                    cdu_share_pct=0.0,
                    ytm_weighted=0.12,
                    duration_weighted=1.2,
                ),
            ]
        )
        db.commit()

        same_day = dashboard_summary(
            from_=date(2025, 9, 11),
            to_=date(2025, 9, 11),
            db=db,
        )
        two_day_window = dashboard_summary(
            from_=date(2025, 9, 10),
            to_=date(2025, 9, 11),
            db=db,
        )

    assert same_day.report_date == date(2025, 9, 11)
    assert [block.cdu_name for block in same_day.blocks] == ["Halyk Finance"]
    assert same_day.fund_total_mv == 120.0

    assert two_day_window.report_date == date(2025, 9, 11)
    assert {block.cdu_name for block in two_day_window.blocks} == {"Halyk Finance", "BCC Invest"}
    assert two_day_window.fund_total_mv == 320.0


@pytest.mark.skipif(not REAL_RISK_REPORT.exists(), reason="Real risk report example file not present")
def test_risk_report_import_populates_dashboard_from_report_sheet(in_memory_db):
    session_local = in_memory_db

    with session_local() as db:
        result = import_risk_report(db, REAL_RISK_REPORT, skip_if_imported=False)

        assert result.error is None
        assert result.file_date == date(2025, 10, 20)
        assert result.report_summaries == 6
        assert result.report_positions == 36

        halyk_cdu = db.execute(select(CDU).where(CDU.name == "Halyk Finance")).scalars().one()
        halyk_cash = db.execute(select(CashSnapshot).where(
            CashSnapshot.cdu_id == halyk_cdu.id,
            CashSnapshot.snapshot_date == date(2025, 10, 20),
        )).scalars().one()
        assert halyk_cash.amount == pytest.approx(85_161.88)

        calc_result = calculate_for_date(db, date(2025, 10, 20), recalculate=True)
        assert calc_result["cdus_processed"] == 6

        response = dashboard_summary(
            report_date=date(2025, 10, 20),
            from_=None,
            to_=None,
            db=db,
        )

    assert response.report_date == date(2025, 10, 20)
    assert len(response.blocks) == 6
    assert response.fund_total_mv == pytest.approx(218_720_804_792.9392)
    halyk = next(block for block in response.blocks if block.cdu_name == "Halyk Finance")
    rows = {row.category: row.market_value_current for row in halyk.rows}
    assert rows["CASH"] == pytest.approx(85_161.88)
    assert rows["GOV_BONDS"] == pytest.approx(40_591_953_972.22222)
    assert rows["REVERSE_REPO"] == pytest.approx(12_026_501_592.518572)


@pytest.mark.skipif(not REAL_HOLDINGS_FILE.exists(), reason="Real holdings example file not present")
def test_holdings_import_real_file_is_idempotent(in_memory_db):
    session_local = in_memory_db
    parsed = parse_holdings_xlsx(REAL_HOLDINGS_FILE)
    unique_isins = {row["isin"] for row in parsed["positions"]}

    with session_local() as db:
        first = import_holdings_xlsx(db, REAL_HOLDINGS_FILE, uploaded_by="pytest")
        second = import_holdings_xlsx(db, REAL_HOLDINGS_FILE, uploaded_by="pytest")

        tansar = db.execute(select(CDU).where(CDU.name == "Tansar Capital")).scalars().one()
        cash_rows = db.execute(
            select(CashSnapshot).where(
                CashSnapshot.cdu_id == tansar.id,
                CashSnapshot.snapshot_date == date(2025, 9, 5),
            )
        ).scalars().all()
        position_rows = db.execute(
            select(PortfolioPosition).where(
                PortfolioPosition.cdu_id == tansar.id,
                PortfolioPosition.position_date == date(2025, 9, 5),
            )
        ).scalars().all()

    assert parsed["cdu_name"] == "Tansar Capital"
    assert first["cash_snapshots"] == 1
    assert second["cash_snapshots"] == 1
    assert len(cash_rows) == 1
    assert cash_rows[0].currency == "KZT"
    assert cash_rows[0].amount == pytest.approx(904950.7)
    assert len(position_rows) == len(unique_isins)
    assert any(row.instrument_category == "REVERSE_REPO" for row in position_rows)
    assert any(row.instrument_category == "GOV_BONDS" for row in position_rows)


@pytest.mark.skipif(not REAL_RECON_FILE.exists(), reason="Real reconciliation example file not present")
def test_rr_vs_holdings_reconciliation_matches_real_recon_file(in_memory_db):
    session_local = in_memory_db
    parsed = parse_reconciliation_xlsx(REAL_RECON_FILE)
    totals = parsed["totals"]
    recon_date = parsed["report_date"]

    with session_local() as db:
        halyk = db.execute(select(CDU).where(CDU.name == "Halyk Finance")).scalars().one()

        db.add(
            CashSnapshot(
                cdu_id=halyk.id,
                snapshot_date=recon_date,
                currency="KZT",
                amount=totals["cash"],
                source="pytest",
            )
        )
        db.add(
            PortfolioPosition(
                cdu_id=halyk.id,
                position_date=recon_date,
                instrument_code="SEC_TOTAL",
                instrument_category="GOV_BONDS",
                instrument_name="Securities total",
                nominal_volume=totals["securities"],
                market_value_current=0.0,
            )
        )
        db.add(
            RepoLot(
                cdu_id=halyk.id,
                instrument_code="REPO_TOTAL",
                trade_date=recon_date,
                valuation_date=recon_date,
                face_value=totals["repo"],
                source_doc_id=None,
            )
        )
        db.add(
            SourceDocument(
                doc_type="RECONCILIATION",
                cdu_id=halyk.id,
                doc_date=recon_date,
                file_name=REAL_RECON_FILE.name,
                file_path=str(REAL_RECON_FILE),
                parse_status="OK",
                parse_meta_json=json.dumps(parsed, ensure_ascii=False, default=str),
                rows_imported=parsed["rows_parsed"],
            )
        )
        db.commit()

        result = run_reconciliation(db, halyk.id, recon_date, "rr_vs_holdings")

    assert parsed["warnings"] == []
    assert result.status == "OK"
    assert result.expected_value == pytest.approx(totals["total"])
    assert result.actual_value == pytest.approx(totals["total"])
    assert result.deviation == pytest.approx(0.0)
