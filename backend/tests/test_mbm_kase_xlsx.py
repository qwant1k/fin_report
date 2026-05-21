"""Tests for KASE MBM XLSX archive parser + client integration.

Источник фикстуры: эндпоинт KASE
``https://kase.kz/api/indicators/mbm-index/archive-xls?start_date=2026-05-01&end_date=2026-05-07&language=ru``
сохранён в ``tests/fixtures/mbm_kase_archive.xlsx`` (3 строки данных:
06.05.2026 / 05.05.2026 / 04.05.2026).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from services.mbm.mbm_client import (
    DEFAULT_MBM_START_DATE,
    MBMClient,
    parse_kase_mbm_xlsx,
    _to_float,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mbm_kase_archive.xlsx"


# ─────────── _to_float ───────────
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1,214.9000", 1214.9),       # KASE XLSX format
        ("1 214,90", 1214.9),         # Russian format
        ("2.5100", 2.51),
        ("\u00A02,51", 2.51),         # NBSP + comma
        ("-", None),
        ("", None),
        (None, None),
        (2.18, 2.18),                 # already a number
    ],
)
def test_to_float_handles_both_formats(raw, expected):
    assert _to_float(raw) == expected


# ─────────── parse_kase_mbm_xlsx ───────────
@pytest.mark.skipif(not FIXTURE.exists(), reason="MBM fixture missing")
def test_parse_real_kase_mbm_archive():
    rows = parse_kase_mbm_xlsx(FIXTURE.read_bytes())
    assert len(rows) == 3, f"Ожидали 3 строки, получили {len(rows)}"
    # Сортировка по убыванию даты.
    assert rows[0].index_date == date(2026, 5, 6)
    assert rows[1].index_date == date(2026, 5, 5)
    assert rows[2].index_date == date(2026, 5, 4)
    # Числовые значения распознаны корректно (формат "1,214.9000").
    assert rows[0].ytm_value == pytest.approx(1214.9)
    assert rows[1].ytm_value == pytest.approx(1216.0)
    assert rows[2].ytm_value == pytest.approx(1214.46)
    # Duration / ModDuration постоянны в этой выборке.
    assert all(r.duration == pytest.approx(2.51) for r in rows)
    assert all(r.mod_duration == pytest.approx(2.18) for r in rows)
    assert all(r.source == "kase_xlsx" for r in rows)


def test_parse_skips_header_and_empty_rows():
    """Заголовок с диапазоном дат и пустые хвостовые строки не должны попадать в результат."""
    if not FIXTURE.exists():
        pytest.skip("MBM fixture missing")
    rows = parse_kase_mbm_xlsx(FIXTURE.read_bytes())
    # ни одна строка не должна иметь None-дату или быть Заголовком.
    assert all(r.index_date is not None for r in rows)
    assert all(r.ytm_value is not None for r in rows)


# ─────────── MBMClient (mocked) ───────────
@pytest.mark.skipif(not FIXTURE.exists(), reason="MBM fixture missing")
@pytest.mark.asyncio
async def test_client_fetch_latest_uses_kase_xlsx_first():
    """fetch_latest() должна вернуть строку с самой свежей датой из XLSX-архива."""
    client = MBMClient()
    fixture_bytes = FIXTURE.read_bytes()

    class _FakeResp:
        status_code = 200
        headers = {"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
        content = fixture_bytes

        def raise_for_status(self):
            pass

    get = AsyncMock(return_value=_FakeResp())
    with patch("httpx.AsyncClient.get", new=get):
        latest = await client.fetch_latest()

    params = get.await_args.kwargs["params"]
    assert params["start_date"] == DEFAULT_MBM_START_DATE.strftime("%Y-%m-%d")
    assert params["end_date"] == date.today().strftime("%Y-%m-%d")
    assert latest is not None
    assert latest.index_date == date(2026, 5, 6)
    assert latest.ytm_value == pytest.approx(1214.9)
    assert latest.duration == pytest.approx(2.51)
    assert latest.mod_duration == pytest.approx(2.18)
    assert latest.source == "kase_xlsx"


@pytest.mark.skipif(not FIXTURE.exists(), reason="MBM fixture missing")
@pytest.mark.asyncio
async def test_client_fetch_for_date_returns_exact_match():
    client = MBMClient()
    fixture_bytes = FIXTURE.read_bytes()

    class _FakeResp:
        status_code = 200
        headers = {"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
        content = fixture_bytes

        def raise_for_status(self):
            pass

    get = AsyncMock(return_value=_FakeResp())
    with patch("httpx.AsyncClient.get", new=get):
        v = await client.fetch_for_date(date(2026, 5, 5))

    params = get.await_args.kwargs["params"]
    assert params["start_date"] == "2026-05-05"
    assert params["end_date"] == "2026-05-05"
    assert v is not None
    assert v.index_date == date(2026, 5, 5)
    assert v.ytm_value == pytest.approx(1216.0)
