"""TEMPORARY probe #7: find date format for getArchiveXls + download the risk
workbook from app-gateway/documents/risk/{date} and dump its sheets.

Run:  py -3 scripts\\probe_rp7.py
"""
from __future__ import annotations

import io
import re
import ssl
import zipfile
from datetime import date, timedelta
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
BASE = "https://kase.kz"
NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
TARGET_HINTS = ("расчетные цены", "расчётные цены", "_фр", "фр")
CHUNKS = ["chunk-2GK3KLX2.js"]


def fetch(url: str, accept: str = "*/*"):
    req = Request(url, headers={"User-Agent": UA, "Accept": accept,
                                "Referer": f"{BASE}/ru/markets/markets-valuation/risk-parameters"})
    try:
        with urlopen(req, timeout=60, context=_CTX) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except Exception as exc:  # noqa: BLE001
        return None, repr(exc), b""


def grep_callsites() -> None:
    print("=== call sites for getArchiveXls / app-gateway / downloadFile ===")
    for ch in CHUNKS:
        _, _, body = fetch(f"{BASE}/{ch}")
        text = body.decode("utf-8", "replace")
        text = re.sub(r"[ \t]{2,}", " ", text)
        for kw in ("getArchiveXls(", "app-gateway", "downloadFile(", "documents/risk", "documents/wapr", "selectedDate", "format(\"YYYY", "DD.MM.YYYY"):
            for m in list(re.finditer(re.escape(kw), text))[:3]:
                s = max(0, m.start() - 160)
                e = min(len(text), m.end() + 160)
                print(f"[{kw}] …{text[s:e]}…")


def list_sheets_and_dump(content: bytes) -> None:
    z = zipfile.ZipFile(io.BytesIO(content))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    relmap = {r.get("Id"): r.get("Target") for r in rels}
    sheets = []
    for s in wb.find(f"{{{NS_MAIN}}}sheets"):
        tgt = relmap.get(s.get(f"{{{NS_REL}}}id"), "")
        if tgt and not tgt.startswith("/"):
            tgt = "xl/" + tgt.lstrip("/")
        sheets.append((s.get("name"), tgt.lstrip("/")))
    print("  SHEETS:", [s[0] for s in sheets])
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        sroot = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in sroot.findall(f"{{{NS_MAIN}}}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS_MAIN}}}t")))

    def col_idx(ref):
        letters = "".join(c for c in ref if c.isalpha())
        idx = 0
        for ch in letters:
            idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
        return idx - 1

    target = next((t for n, t in sheets if any(h in (n or "").lower().replace("ё", "е") for h in ("расчетные цены", "_фр"))), None)
    if not target:
        target = next((t for n, t in sheets if "фр" in (n or "").lower()), None)
    if not target and sheets:
        print("  (target sheet not matched; dumping first sheet)")
        target = sheets[0][1]
    name = next((n for n, t in sheets if t == target), "?")
    print(f"  DUMP SHEET: {name!r}")
    root = ET.fromstring(z.read(target))
    sd = root.find(f"{{{NS_MAIN}}}sheetData")
    for i, row in enumerate(sd.findall(f"{{{NS_MAIN}}}row")):
        cells = {}
        for c in row.findall(f"{{{NS_MAIN}}}c"):
            v = c.find(f"{{{NS_MAIN}}}v")
            if c.get("t") == "s" and v is not None and v.text:
                val = shared[int(v.text)] if int(v.text) < len(shared) else ""
            elif v is not None:
                val = v.text
            else:
                val = ""
            cells[col_idx(c.get("r", "A1"))] = val
        if cells:
            print(f"   row[{i}]:", [cells.get(j) for j in range(max(cells) + 1)])
        if i >= 16:
            break


def probe_download() -> None:
    print("\n=== probing app-gateway/documents/risk/{date} ===")
    today = date.today()
    fmts = ["%Y-%m-%d", "%d.%m.%Y", "%d_%m_%Y", "%Y%m%d", "%d%m%y"]
    for delta in range(0, 12):
        d = today - timedelta(days=delta)
        for lang in ("ru", "en"):
            for fmt in fmts:
                ds = d.strftime(fmt)
                url = f"{BASE}/{lang}/app-gateway/documents/risk/{ds}"
                status, ct, content = fetch(url)
                magic = content[:2]
                if status == 200 and content:
                    print(f"[200] {url} ct={ct} len={len(content)} magic={magic!r}")
                    if magic == b"PK":
                        with open(f"scripts/_risk_{d.strftime('%Y%m%d')}.xlsx", "wb") as fh:
                            fh.write(content)
                        print(f"  saved -> scripts/_risk_{d.strftime('%Y%m%d')}.xlsx")
                        try:
                            list_sheets_and_dump(content)
                        except Exception as exc:  # noqa: BLE001
                            print("  parse failed:", repr(exc))
                        return
                else:
                    print(f"[{status}] {url} ({ct if status is None else ''})")


if __name__ == "__main__":
    grep_callsites()
    probe_download()
