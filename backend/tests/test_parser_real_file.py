"""Integration test against the real Trade report attached to the project."""
from datetime import date
from pathlib import Path

import pytest

from services.parser import TradeReportParser

REAL_FILE = (
    Path(__file__).resolve().parents[2]
    / "Примеры"
    / "Пример 1 Первичка ЧДУ"
    / "Trade report 1009 2025.xlsx"
)


@pytest.mark.skipif(not REAL_FILE.exists(), reason="Real trade report file not present")
def test_real_trade_report_parses():
    parser = TradeReportParser(REAL_FILE)
    parsed = parser.parse()

    assert parsed.cdu_prefix == "HALFN"
    assert parsed.cdu_name == "Halyk Finance"
    assert parsed.trade_date == date(2025, 9, 10)
    assert parsed.rows_parsed == 6, "В файле 6 исполненных сделок"
    # 3 ноги REPO: HEADER, BUY, SELL
    op_types = {r.fields["operation_type"] for r in parsed.rows}
    assert {"REPO_HEADER", "REPO_OPEN", "REPO_CLOSE"}.issubset(op_types)
    # Все 6 строк — обратное РЕПО
    cats = {r.fields["instrument_category"] for r in parsed.rows}
    assert cats == {"REVERSE_REPO"}
    # Числа корректно распознались
    sample = parsed.rows[0].fields
    assert sample["price"] == 16.5
    assert sample["volume"] == 2069895028.63
    assert sample["nominal_volume"] == 2069925000
    assert sample["repo_term_days"] == 1


@pytest.mark.skipif(not REAL_FILE.exists(), reason="Real trade report file not present")
def test_real_position_open_on_trade_date():
    """On trade_date 10.09.2025 both REPO positions are still open (close_date=11.09)."""
    from services.calculator.position_builder import build_positions

    parser = TradeReportParser(REAL_FILE)
    parsed = parser.parse()
    rows = [type("Row", (), pr.fields) for pr in parsed.rows]
    positions = build_positions(rows, cdu_id=1, report_date=date(2025, 9, 10))

    repo_positions = [p for p in positions if p.instrument_category == "REVERSE_REPO"]
    assert len(repo_positions) == 2
    codes = {p.instrument_code for p in repo_positions}
    assert codes == {"KFUSb47", "EABRb40"}
    # Открытые позиции должны иметь положительные суммы
    total_open = sum(p.repo_open_sum for p in repo_positions)
    assert total_open > 0


@pytest.mark.skipif(not REAL_FILE.exists(), reason="Real trade report file not present")
def test_real_position_closed_after_settlement():
    """On 12.09.2025 (after П leg settlement on 11.09) positions must be closed."""
    from services.calculator.position_builder import build_positions

    parser = TradeReportParser(REAL_FILE)
    parsed = parser.parse()
    rows = [type("Row", (), pr.fields) for pr in parsed.rows]
    positions = build_positions(rows, cdu_id=1, report_date=date(2025, 9, 12))
    repo_positions = [p for p in positions if p.instrument_category == "REVERSE_REPO"]
    # после settlement все REPO закрыты
    assert all(p.repo_open_sum == 0 for p in repo_positions) or repo_positions == []
