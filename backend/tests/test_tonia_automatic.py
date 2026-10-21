"""Automatic KASE TONIA Compounded download and idempotent import."""
from __future__ import annotations

import io
from datetime import date

import httpx
import pytest
from openpyxl import Workbook

from models.db_models import SourceDocument, ToniaCompounded
from services.market import tonia
from tests.test_requirements_20260929 import stand  # noqa: F401


def _archive_bytes(*days: date) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append([f"TONIA Compounded {days[0]} - {days[-1]}"])
    ws.append(["Дата расчетов", "TCR_1M", "TCR_3M", "TCR_6M", "TCI"])
    for n, day in enumerate(days):
        ws.append([day.strftime("%d.%m.%Y"), 16.1 + n, 16.4 + n, 17.4 + n, 2.27 + n])
    stream = io.BytesIO()
    wb.save(stream)
    wb.close()
    return stream.getvalue()


@pytest.mark.asyncio
async def test_tonia_client_uses_official_archive_parameters():
    payload = _archive_bytes(date(2026, 10, 18), date(2026, 10, 19))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/indicators/tonia-compounded/archive-xls"
        assert request.url.params["start_date"] == "2026-10-18"
        assert request.url.params["end_date"] == "2026-10-19"
        assert request.url.params["language"] == "ru"
        return httpx.Response(
            200,
            content=payload,
            headers={"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        )

    client = tonia.ToniaClient(
        url="https://kase.kz/api/indicators/tonia-compounded/archive-xls",
        transport=httpx.MockTransport(handler),
    )
    assert await client.fetch_archive(date(2026, 10, 18), date(2026, 10, 19)) == payload


@pytest.mark.asyncio
async def test_tonia_client_rejects_non_excel_response():
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200,
        text="temporary maintenance",
        headers={"Content-Type": "text/html"},
    ))
    client = tonia.ToniaClient(url="https://kase.kz/api/test", transport=transport)
    with pytest.raises(ValueError, match="не в формате XLSX"):
        await client.fetch_archive(date(2026, 10, 19), date(2026, 10, 19))


def test_refresh_endpoint_imports_and_deduplicates_archive(stand, monkeypatch):
    api, Session, _ = stand
    payload = _archive_bytes(date(2026, 10, 18), date(2026, 10, 19))

    async def fake_fetch(self, start, end):
        assert start <= date(2026, 10, 18)
        assert end >= date(2026, 10, 19)
        return payload

    monkeypatch.setattr(tonia.ToniaClient, "fetch_archive", fake_fetch)
    first = api.post("/api/tonia/refresh")
    assert first.status_code == 200, first.text
    assert first.json()["inserted"] == 8

    second = api.post("/api/tonia/refresh")
    assert second.status_code == 200, second.text
    assert second.json()["inserted"] == 0
    assert second.json()["updated"] == 0
    assert second.json()["unchanged"] == 8
    assert second.json()["duplicate_document"] is True

    with Session() as db:
        assert db.query(ToniaCompounded).count() == 8
        assert db.query(SourceDocument).filter_by(doc_type="TONIA_COMPOUNDED").count() == 1
