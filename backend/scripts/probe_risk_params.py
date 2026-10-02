"""TEMPORARY probe: discover KASE risk-parameter file structure.

Read-only. Downloads the KASE Clearing Center daily risk-parameter workbook
and reports: HTTP status, content-type, magic bytes, sheet names, and the
header + first rows of the "Расчетные цены_ФР" sheet.

Run:
    .venv\\Scripts\\python.exe scripts\\probe_risk_params.py
"""
from __future__ import annotations

import io
from datetime import date, timedelta

import httpx

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru,en;q=0.8",
}

TARGET_SHEET_HINTS = ("расчетные цены", "расчётные цены", "_фр")


def magic(content: bytes) -> str:
    if content[:2] == b"PK":
        return "xlsx/zip (PK)"
    if content[:4] == b"\xd0\xcf\x11\xe0":
        return "OLE2 .xls (D0 CF 11 E0)"
    head = content[:64].decode("latin-1", "replace")
    return f"unknown; head={head!r}"


def candidate_urls(d: date) -> list[str]:
    ddmmyy = d.strftime("%d%m%y")
    return [
        f"https://kacc.kase.kz/ru/risk-parameters/rp{ddmmyy}.xls",
        f"https://kacc.kase.kz/en/risk-parameters/rp{ddmmyy}.xls",
        f"https://kacc.kase.kz/ru/risk-parameters/rp{ddmmyy}.xlsx",
    ]


def dump_xlsx(content: bytes) -> None:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    print("  SHEETS:", wb.sheetnames)
    target = None
    for name in wb.sheetnames:
        low = name.lower().replace("ё", "е")
        if any(h in low for h in TARGET_SHEET_HINTS):
            target = name
            break
    if not target:
        print("  !! target sheet not found by hints; dumping each sheet's first row")
        for name in wb.sheetnames:
            ws = wb[name]
            first = next(ws.iter_rows(values_only=True), None)
            print(f"   - {name!r}: {first}")
        return
    print(f"  TARGET SHEET: {target!r}")
    ws = wb[target]
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        print(f"   row[{i}]: {row}")
        if i >= 12:
            break


def main() -> None:
    today = date.today()
    print(f"today={today.isoformat()}")
    with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as cli:
        for delta in range(0, 15):
            d = today - timedelta(days=delta)
            for url in candidate_urls(d):
                try:
                    r = cli.get(url)
                except Exception as exc:
                    print(f"[ERR ] {url} -> {exc!r}")
                    continue
                ct = r.headers.get("content-type", "")
                if r.status_code != 200 or not r.content:
                    print(f"[{r.status_code}] {url} ct={ct} len={len(r.content)}")
                    continue
                print(f"[200 ] {url} ct={ct} len={len(r.content)} magic={magic(r.content)}")
                out_path = f"scripts/_sample_rp_{d.strftime('%d%m%y')}.bin"
                with open(out_path, "wb") as fh:
                    fh.write(r.content)
                print(f"  saved -> {out_path}")
                if r.content[:2] == b"PK":
                    try:
                        dump_xlsx(r.content)
                    except Exception as exc:
                        print(f"  xlsx parse failed: {exc!r}")
                else:
                    print("  (not xlsx; need xls reader — reporting magic only)")
                return
    print("No risk-parameter file found in the last 15 days.")


if __name__ == "__main__":
    main()
