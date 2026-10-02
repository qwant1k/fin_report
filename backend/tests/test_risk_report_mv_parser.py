from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from openpyxl import load_workbook

from services.import_rr.risk_report_importer import _load_risk_workbook
from services.import_rr.helpers import materialize_sheet
from services.import_rr.sheet_parsers import parse_cash_sheet, parse_mv_sheet, parse_report_sheet


EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "Примеры"
REAL_RISK_REPORT = EXAMPLES_DIR / "risk report_09112025_.xlsm"
REAL_RISK_REPORT_3112 = EXAMPLES_DIR / "risk report_31122025_.xlsm"


@pytest.mark.skipif(not REAL_RISK_REPORT.exists(), reason="Real risk report example file not present")
def test_mv_wide_header_uses_actual_cdu_row_not_portfolio_owner_row():
    wb = load_workbook(REAL_RISK_REPORT, read_only=True, data_only=True, keep_vba=False)
    try:
        mv_rows = parse_mv_sheet(materialize_sheet(wb["MV"]))
        cash_rows = parse_cash_sheet(materialize_sheet(wb["Cash"]))
    finally:
        wb.close()

    mv_keys = Counter((row["snapshot_date"], row["cdu_name"]) for row in mv_rows)
    cash_cdus = {row["cdu_name"] for row in cash_rows}
    mv_cdus = {row["cdu_name"] for row in mv_rows}

    assert mv_rows
    assert not [key for key, count in mv_keys.items() if count > 1]
    assert mv_cdus == cash_cdus
    assert "НБ РК — Собственные активы" not in mv_cdus


@pytest.mark.skipif(not REAL_RISK_REPORT_3112.exists(), reason="Real 31.12 risk report example file not present")
def test_report_sheet_ignores_right_side_helper_table():
    wb = _load_risk_workbook(REAL_RISK_REPORT_3112, password="7")
    try:
        rows = parse_report_sheet(materialize_sheet(wb["Report"]))
    finally:
        wb.close()

    summaries = [row for row in rows if row.get("kind") == "summary"]
    positions = [row for row in rows if row.get("kind") == "position"]
    summary_keys = Counter((row["snapshot_date"], row["cdu_name"]) for row in summaries)

    assert len(summaries) == 6
    assert len(positions) == 36
    assert not [key for key, count in summary_keys.items() if count > 1]
    assert all((row.get("ytm_weighted") or 0) > 0 for row in summaries)
    assert all((row.get("duration_weighted") or 0) > 0 for row in summaries)
