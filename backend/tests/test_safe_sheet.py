"""Регрессионные тесты для services.import_rr.helpers.safe_sheet.

История бага: substring-резолвер возвращал лист ``Report`` при запросе
``Repo`` (потому что ``"repo" in "report"``), из-за чего парсер REPO-лотов
получал данные с другого листа и стабильно возвращал 0 строк.
"""
from __future__ import annotations

from openpyxl import Workbook

from services.import_rr.helpers import safe_sheet


def _wb_with(*sheet_names: str) -> Workbook:
    wb = Workbook()
    # Workbook создаётся с дефолтным листом 'Sheet' — переименуем под первое имя
    first, *rest = sheet_names
    wb.active.title = first
    for n in rest:
        wb.create_sheet(n)
    return wb


def test_repo_does_not_collide_with_report():
    wb = _wb_with("Report", "Repo")
    ws = safe_sheet(wb, "Repo")
    assert ws is not None and ws.title == "Repo"


def test_repo_resolved_when_report_listed_first():
    wb = _wb_with("Report", "Cash", "MV", "Repo", "ГЦБ")
    assert safe_sheet(wb, "Repo").title == "Repo"
    assert safe_sheet(wb, "Report").title == "Report"


def test_exact_match_wins_over_substring():
    wb = _wb_with("MBM index history", "MBM index")
    # Точное совпадение ('MBM index') должно вернуть точный лист, а не 'MBM index history'
    assert safe_sheet(wb, "MBM index").title == "MBM index"


def test_alias_fallback_still_works():
    """Если точного нет — допускается prefix match (target → префикс листа)."""
    wb = _wb_with("MBM index - с 1 апреля 2024 г")
    assert safe_sheet(wb, "MBM index").title.startswith("MBM index")


def test_typo_alias_agentstkie():
    wb = _wb_with("Агентсткие")  # типичная опечатка в файлах
    assert safe_sheet(wb, "Агентские", "Агентсткие").title == "Агентсткие"


def test_returns_none_when_not_found():
    wb = _wb_with("Cash", "MV")
    assert safe_sheet(wb, "Repo") is None


def test_first_target_wins_when_multiple_match():
    wb = _wb_with("Cash", "MV")
    # Если оба имени присутствуют, вернётся лист, нормализованное имя которого
    # соответствует ПЕРВОМУ совпавшему target в первом проходе.
    ws = safe_sheet(wb, "Cash", "MV")
    assert ws.title == "Cash"
