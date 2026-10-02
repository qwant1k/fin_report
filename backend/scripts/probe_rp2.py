"""TEMPORARY probe #2 (stdlib only): find KASE risk-parameters API/XLS endpoint.

Read-only. 1) fetches the risk-parameters SPA page and greps for hints,
2) tries JSON API candidates and prints structure,
3) tries XLS export candidates and reports magic + sheet names.

Run:  py -3 scripts\\probe_rp2.py
"""
from __future__ import annotations

import io
import json
import re
import ssl
import zipfile
from datetime import date
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

TODAY = date.today().isoformat()


def fetch(url: str, accept: str = "*/*"):
    req = Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "ru,en;q=0.8",
        "Accept": accept,
        "Referer": "https://kase.kz/ru/markets/markets-valuation/risk-parameters",
    })
    try:
        with urlopen(req, timeout=40, context=_CTX) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except Exception as exc:  # noqa: BLE001
        return None, repr(exc), b""


def grep_page() -> None:
    print("=== PAGE HTML ===")
    status, ct, content = fetch("https://kase.kz/ru/markets/markets-valuation/risk-parameters", "text/html")
    print(f"status={status} ct={ct} len={len(content)}")
    if not content:
        return
    text = content.decode("utf-8", "replace")
    hints = set()
    for m in re.finditer(r"[\"'](/?api/[^\"']+|https?://[^\"']*risk[^\"']*|[^\"']*\.xlsx?[^\"']*)[\"']", text, re.I):
        hints.add(m.group(1))
    for h in sorted(hints)[:60]:
        print("  hint:", h)


def show_json(content: bytes) -> None:
    try:
        data = json.loads(content)
    except Exception as exc:  # noqa: BLE001
        print("   not JSON:", repr(exc), content[:120])
        return
    if isinstance(data, dict):
        keys = list(data.keys())
        print("   dict keys:", keys[:10], "..." if len(keys) > 10 else "")
        # market-valuations style: {date: [rows]}
        for k in keys[:1]:
            v = data[k]
            if isinstance(v, list) and v and isinstance(v[0], dict):
                print(f"   sample row keys for [{k!r}]:", list(v[0].keys()))
                print("   sample row:", json.dumps(v[0], ensure_ascii=False)[:600])
            else:
                print(f"   [{k!r}] ->", json.dumps(v, ensure_ascii=False)[:300])
    elif isinstance(data, list) and data:
        print("   list len:", len(data))
        if isinstance(data[0], dict):
            print("   row keys:", list(data[0].keys()))
            print("   sample row:", json.dumps(data[0], ensure_ascii=False)[:600])


def show_xlsx(content: bytes) -> None:
    z = zipfile.ZipFile(io.BytesIO(content))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    names = [s.get("name") for s in wb.find(f"{{{NS_MAIN}}}sheets")]
    print("   SHEETS:", names)


def try_endpoints() -> None:
    print("\n=== JSON candidates ===")
    json_urls = [
        "https://kase.kz/api/indicators/risk-parameters/",
        "https://kase.kz/api/indicators/risk-parameters/?ordering=code__nulls_last",
        f"https://kase.kz/api/indicators/risk-parameters/?date={TODAY}",
        "https://kase.kz/api/indicators/risk-parameter/",
        "https://kase.kz/api/indicators/risk-params/",
        "https://kase.kz/api/indicators/market-valuations/risk-parameters/",
        "https://kase.kz/api/v1/risk-parameters/",
    ]
    for url in json_urls:
        status, ct, content = fetch(url, "application/json")
        print(f"[{status}] {url} ct={ct} len={len(content)}")
        if status == 200 and content and "json" in ct.lower():
            show_json(content)

    print("\n=== XLS candidates ===")
    xls_urls = [
        "https://kase.kz/api/indicators/risk-parameters/xls",
        "https://kase.kz/api/indicators/risk-parameters/xls/",
        f"https://kase.kz/api/indicators/risk-parameters/archive-xls?{urlencode({'start_date': TODAY, 'end_date': TODAY, 'language': 'ru'})}",
        f"https://kase.kz/api/indicators/risk-parameters/xls?{urlencode({'date': TODAY, 'language': 'ru'})}",
        "https://kase.kz/api/indicators/risk-parameters/export/",
        f"https://kase.kz/api/indicators/risk-parameters/export-xls?{urlencode({'date': TODAY})}",
    ]
    for url in xls_urls:
        status, ct, content = fetch(url)
        head = content[:2]
        print(f"[{status}] {url} ct={ct} len={len(content)} magic={head!r}")
        if status == 200 and head == b"PK":
            try:
                show_xlsx(content)
                with open("scripts/_sample_rp_api.xlsx", "wb") as fh:
                    fh.write(content)
                print("   saved -> scripts/_sample_rp_api.xlsx")
            except Exception as exc:  # noqa: BLE001
                print("   xlsx parse failed:", repr(exc))


if __name__ == "__main__":
    grep_page()
    try_endpoints()
