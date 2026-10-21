from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
import database as db_module
from database import Base
from models.db_models import (
    BondLot,
    CDU,
    CashSnapshot,
    DepositLot,
    MVSnapshot,
    PortfolioPosition,
    PortfolioSummary,
    RepoLot,
    SourceDocument,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from api.routes.dashboard import dashboard_summary
from api.routes.analytics import fund_trend, portfolio_trend
from api.routes.workday import workday_summary
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


def test_analytics_trend_prefers_portfolio_summary_over_mv_snapshot(in_memory_db):
    session_local = in_memory_db
    day = date(2025, 12, 31)

    with session_local() as db:
        halyk = db.execute(select(CDU).where(CDU.name == "Halyk Finance")).scalars().one()
        bcc = db.execute(select(CDU).where(CDU.name == "BCC Invest")).scalars().one()
        db.add(PortfolioSummary(
            cdu_id=halyk.id,
            summary_date=day,
            total_mv_prev=100.0,
            total_daily_change=20.0,
            total_mv_current=120.0,
            cdu_share_pct=0.0,
            ytm_weighted=0.10,
            duration_weighted=1.0,
        ))
        db.add(MVSnapshot(
            cdu_id=halyk.id,
            snapshot_date=day,
            market_value_total=999.0,
            source="rr_import",
        ))
        db.add(MVSnapshot(
            cdu_id=bcc.id,
            snapshot_date=day,
            market_value_total=50.0,
            source="rr_import",
        ))
        db.commit()

        fund_rows = fund_trend(from_=day, to_=day, days=None, db=db)
        cdu_rows = portfolio_trend(from_=day, to_=day, days=None, db=db)

    assert fund_rows == [{
        "date": day.isoformat(),
        "market_value_total": 170.0,
        "ytm_weighted": 0.10,
        "duration_weighted": 1.0,
        "cdu_count": 2,
    }]
    by_cdu = {row["cdu_name"]: row["market_value_total"] for row in cdu_rows}
    assert by_cdu == {"Halyk Finance": 120.0, "BCC Invest": 50.0}


def test_workday_defaults_to_latest_risk_report_and_shows_rr_source(in_memory_db):
    session_local = in_memory_db
    latest_rr_day = date(2025, 12, 31)

    with session_local() as db:
        halyk = db.execute(select(CDU).where(CDU.name == "Halyk Finance")).scalars().one()
        db.add_all([
            SourceDocument(
                doc_type="RISK_REPORT_XLSM",
                doc_date=date(2025, 12, 30),
                file_name="risk report_30122025_.xlsm",
                file_path="/tmp/risk report_30122025_.xlsm",
                parse_status="OK",
                rows_imported=10,
            ),
            SourceDocument(
                doc_type="RISK_REPORT_XLSM",
                doc_date=latest_rr_day,
                file_name="risk report_31122025_.xlsm",
                file_path="/tmp/risk report_31122025_.xlsm",
                parse_status="OK",
                rows_imported=20,
            ),
            PortfolioSummary(
                cdu_id=halyk.id,
                summary_date=latest_rr_day,
                total_mv_prev=100.0,
                total_daily_change=20.0,
                total_mv_current=120.0,
                cdu_share_pct=0.0,
                ytm_weighted=0.10,
                duration_weighted=1.0,
            ),
            PortfolioSummary(
                cdu_id=halyk.id,
                summary_date=date(2026, 6, 8),
                total_mv_prev=900.0,
                total_daily_change=99.0,
                total_mv_current=999.0,
                cdu_share_pct=0.0,
                ytm_weighted=0.01,
                duration_weighted=0.1,
            ),
        ])
        db.commit()

        payload = workday_summary(work_date=None, db=db)

    row = next(item for item in payload["cdus"] if item["cdu_id"] == halyk.id)
    assert payload["work_date"] == latest_rr_day.isoformat()
    assert payload["fund_total_mv"] == 120.0
    assert row["status"] == "ready"
    assert row["documents_count"] == 1
    assert row["latest_document"] == "risk report_31122025_.xlsm"
    assert row["market_value"] == 120.0
    assert row["ytm_weighted"] == 0.10
    assert row["duration_weighted"] == 1.0


def test_duplicate_risk_report_refreshes_portfolio_from_imported_balances(in_memory_db, tmp_path):
    session_local = in_memory_db
    report_date = date(2025, 12, 31)
    fp = tmp_path / "risk report_31122025_.xlsm"
    fp.write_bytes(b"already imported")
    sha = hashlib.sha256(fp.read_bytes()).hexdigest()

    with session_local() as db:
        halyk = db.execute(select(CDU).where(CDU.name == "Halyk Finance")).scalars().one()
        db.add(SourceDocument(
            doc_type="RISK_REPORT_XLSM",
            doc_date=report_date,
            file_name=fp.name,
            file_path=str(fp),
            sha256=sha,
            parse_status="OK",
            parse_meta_json=json.dumps({
                "report_dates": [report_date.isoformat()],
                "report_t1_checked": True,
            }),
        ))
        db.add(CashSnapshot(
            cdu_id=halyk.id,
            snapshot_date=report_date,
            currency="KZT",
            amount=1000.0,
            source="rr_import",
        ))
        db.add(CashSnapshot(
            cdu_id=halyk.id,
            snapshot_date=report_date,
            currency="USD",
            amount=10.0,
            amount_kzt=5000.0,
            source="rr_import",
        ))
        db.add(BondLot(
            cdu_id=halyk.id,
            isin="KZTEST",
            instrument_code="KZTEST",
            category="GOV_BONDS",
            trade_date=report_date,
            valuation_date=report_date,
            quantity_current=1.0,
            face_value_current=10_000.0,
            market_value=10_500.0,
            ytm=12.0,
            duration=2.0,
        ))
        db.add(RepoLot(
            cdu_id=halyk.id,
            instrument_code="REPO1",
            trade_date=report_date,
            valuation_date=report_date,
            face_value=20_000.0,
            market_value=20_300.0,
            repo_rate_pct=13.0,
            term_days=30,
        ))
        db.add(DepositLot(
            cdu_id=halyk.id,
            trade_date=report_date,
            valuation_date=report_date,
            principal=30_000.0,
            accrued_interest=250.0,
            interest_rate_pct=14.0,
            term_days=90,
        ))
        db.commit()

        result = import_risk_report(db, fp, skip_if_imported=True)
        positions = db.execute(select(PortfolioPosition).where(
            PortfolioPosition.cdu_id == halyk.id,
            PortfolioPosition.position_date == report_date,
        )).scalars().all()
        summary = db.execute(select(PortfolioSummary).where(
            PortfolioSummary.cdu_id == halyk.id,
            PortfolioSummary.summary_date == report_date,
        )).scalars().one()

    by_category = {p.instrument_category: p.market_value_current for p in positions}
    assert result.skipped is True
    assert result.portfolio_cdus == 1
    assert by_category["CASH"] == pytest.approx(6000.0)
    assert by_category["GOV_BONDS"] == pytest.approx(10_500.0)
    assert by_category["REVERSE_REPO"] == pytest.approx(20_300.0)
    assert by_category["DEPOSIT"] == pytest.approx(30_250.0)
    assert summary.total_mv_current == pytest.approx(67_050.0)


@pytest.mark.skipif(not REAL_RISK_REPORT.exists(), reason="Real risk report example file not present")
def test_risk_report_import_populates_dashboard_from_report_sheet(in_memory_db):
    session_local = in_memory_db

    with session_local() as db:
        result = import_risk_report(db, REAL_RISK_REPORT, skip_if_imported=False)

        assert result.error is None
        assert result.file_date == date(2025, 10, 20)
        assert result.report_dates == [date(2025, 10, 19), date(2025, 10, 20)]
        assert result.report_summaries == 12
        assert result.report_positions == 72

        halyk_cdu = db.execute(select(CDU).where(CDU.name == "Halyk Finance")).scalars().one()
        halyk_cash = db.execute(select(CashSnapshot).where(
            CashSnapshot.cdu_id == halyk_cdu.id,
            CashSnapshot.snapshot_date == date(2025, 10, 20),
        )).scalars().one()
        assert halyk_cash.amount == pytest.approx(85_161.88)

        calc_result = calculate_for_date(db, date(2025, 10, 20), recalculate=True)
        assert calc_result["cdus_processed"] == 6

        t1_summary_count = db.execute(select(PortfolioSummary).where(
            PortfolioSummary.summary_date == date(2025, 10, 19),
        )).scalars().all()
        t1_position_count = db.execute(select(PortfolioPosition).where(
            PortfolioPosition.position_date == date(2025, 10, 19),
            PortfolioPosition.notes == "rr_report_import",
        )).scalars().all()
        assert len(t1_summary_count) == 6
        assert len(t1_position_count) == 36

        t1_response = dashboard_summary(
            report_date=date(2025, 10, 19),
            from_=None,
            to_=None,
            db=db,
        )

        response = dashboard_summary(
            report_date=date(2025, 10, 20),
            from_=None,
            to_=None,
            db=db,
        )

    assert t1_response.report_date == date(2025, 10, 19)
    assert len(t1_response.blocks) == 6
    assert response.report_date == date(2025, 10, 20)
    assert len(response.blocks) == 6
    assert response.fund_total_mv == pytest.approx(218_720_804_792.9392)
    halyk = next(block for block in response.blocks if block.cdu_name == "Halyk Finance")
    rows = {row.category: row.market_value_current for row in halyk.rows}
    assert rows["CASH"] == pytest.approx(85_161.88)
    assert rows["GOV_BONDS"] == pytest.approx(40_591_953_972.22222)
    assert rows["REVERSE_REPO"] == pytest.approx(12_026_501_592.518572)


@pytest.mark.skipif(not REAL_RISK_REPORT.exists(), reason="Real risk report example file not present")
def test_risk_report_reupload_records_history_and_replaces_previous_slice(in_memory_db):
    session_local = in_memory_db

    with session_local() as db:
        first = import_risk_report(db, REAL_RISK_REPORT, skip_if_imported=False)
        assert first.error is None
        assert first.source_doc_id is not None

        halyk = db.execute(select(CDU).where(CDU.name == "Halyk Finance")).scalars().one()
        db.add_all([
            PortfolioPosition(
                cdu_id=halyk.id,
                position_date=date(2025, 10, 20),
                instrument_code=None,
                instrument_category="STALE_RR_CATEGORY",
                instrument_name="stale row from previous upload",
                nominal_volume=0.0,
                accrued_interest=0.0,
                market_value_current=123.0,
                market_value_prev=0.0,
                daily_change=0.0,
                pct_of_total=0.0,
                hard_limit_status="ok",
                soft_limit_status="ok",
                notes="rr_report_import",
            ),
            BondLot(
                cdu_id=halyk.id,
                isin="STALE-RR-LOT",
                instrument_code="STALE-RR-LOT",
                category="GOV_BONDS",
                trade_date=date(2025, 10, 20),
                valuation_date=date(2025, 10, 20),
                quantity_current=1.0,
                face_value_current=1.0,
                market_value=1.0,
                source_doc_id=first.source_doc_id,
            ),
        ])
        db.commit()

        docs_before = db.execute(select(func.count()).select_from(SourceDocument)).scalar_one()
        second = import_risk_report(db, REAL_RISK_REPORT, skip_if_imported=False)
        docs_after = db.execute(select(func.count()).select_from(SourceDocument)).scalar_one()
        stale_positions = db.execute(select(PortfolioPosition).where(
            PortfolioPosition.position_date == date(2025, 10, 20),
            PortfolioPosition.instrument_category == "STALE_RR_CATEGORY",
        )).scalars().all()
        stale_lots = db.execute(select(BondLot).where(
            BondLot.valuation_date == date(2025, 10, 20),
            BondLot.isin == "STALE-RR-LOT",
        )).scalars().all()
        positions_count = db.execute(select(func.count()).select_from(PortfolioPosition).where(
            PortfolioPosition.position_date == date(2025, 10, 20),
            PortfolioPosition.notes == "rr_report_import",
        )).scalar_one()

    assert second.error is None
    assert second.skipped is False
    assert second.source_doc_id != first.source_doc_id
    assert docs_after == docs_before + 1
    assert stale_positions == []
    assert stale_lots == []
    assert positions_count == 36


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
        # Internal books for the date: a Risk Report slice whose market values
        # equal the manager's file (BP 6.5 compares *market values*, not
        # nominal amounts).
        db.add(
            BondLot(
                cdu_id=halyk.id,
                isin="KZSEC0000001",
                category="GOV_BONDS",
                trade_date=recon_date,
                valuation_date=recon_date,
                face_value_current=totals["securities"],
                market_value=totals["securities"],
                total_value=totals["securities"],
            )
        )
        db.add(
            RepoLot(
                cdu_id=halyk.id,
                instrument_code="REPO_TOTAL",
                trade_date=recon_date,
                valuation_date=recon_date,
                face_value=totals["repo"],
                market_value=totals["repo"],
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
    # section totals agree, but the reconciliation is line by line (since 05.10.2026):
    # one synthetic lot «KZSEC0000001» is not the manager's issues
    details = json.loads(result.details_json)
    assert all(s["status"] == "OK" for s in details["summary"])
    assert result.status == "MISMATCH"
    assert {s["status"] for s in details["securities"]} == {"ONLY_OURS", "ONLY_CDU"}
    assert result.expected_value == pytest.approx(totals["total"])
    assert result.actual_value == pytest.approx(totals["total"])
    assert abs(result.deviation) <= 0.01  # rounding of the manager's «Итого активов»
