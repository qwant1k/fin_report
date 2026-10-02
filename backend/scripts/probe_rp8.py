"""TEMPORARY probe #8: download the risk .xls workbook and dump its sheets
and the 'Расчетные цены_ФР' table using xlrd.

Requires: xlrd (pip install xlrd)
Run:  py -3 scripts\\probe_rp8.py
"""
from __future__ import annotations

import ssl
from datetime import date, timedelta
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
BASE = "https://kase.kz"


def fetch(url: str):
    req = Request(url, headers={"User-Agent": UA, "Referer": f"{BASE}/ru/markets/markets-valuation/risk-parameters"})
    try:
        with urlopen(req, timeout=60, context=_CTX) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except Exception as exc:  # noqa: BLE001
        return None, repr(exc), b""


def main() -> None:
    import xlrd  # type: ignore

    today = date.today()
    content = None
    used = None
    for delta in range(0, 10):
        d = today - timedelta(days=delta)
        url = f"{BASE}/ru/app-gateway/documents/risk/{d.strftime('%d.%m.%Y')}"
        status, ct, body = fetch(url)
        if status == 200 and body[:2] == b"\xd0\xcf":
            content, used = body, d
            print(f"downloaded {url} len={len(body)} ct={ct}")
            with open(f"scripts/_risk_{d.strftime('%Y%m%d')}.xls", "wb") as fh:
                fh.write(body)
            print(f"saved -> scripts/_risk_{d.strftime('%Y%m%d')}.xls")
            break
        print(f"[{status}] {url}")
    if content is None:
        print("no file found")
        return

    book = xlrd.open_workbook(file_contents=content)
    names = book.sheet_names()
    print("\nSHEETS:", names)
    target = None
    for n in names:
        low = n.lower().replace("ё", "е")
        if "расчет" in low and "цен" in low:
            target = n
            break
    if not target:
        for n in names:
            if "фр" in n.lower():
                target = n
                break
    print("TARGET SHEET:", target)
    if not target:
        print("!! could not find target by name; dumping every sheet's header row:")
        for n in names:
            sh = book.sheet_by_name(n)
            row0 = [sh.cell_value(0, c) for c in range(sh.ncols)] if sh.nrows else []
            print(f"  {n!r} dims={sh.nrows}x{sh.ncols} row0={row0}")
        return
    sh = book.sheet_by_name(target)
    print(f"DIMS: {sh.nrows} rows x {sh.ncols} cols")
    for r in range(min(sh.nrows, 20)):
        print(f"  row[{r}]:", [sh.cell_value(r, c) for c in range(sh.ncols)])


if __name__ == "__main__":
    main()
