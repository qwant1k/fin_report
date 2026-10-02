"""TEMPORARY probe (stdlib only): discover KASE risk-parameter file structure.

Read-only. Downloads the KASE Clearing Center daily risk-parameter workbook
and reports: HTTP status, content-type, magic bytes, sheet names, and the
header + first rows of the "Расчетные цены_ФР" sheet. Uses only the standard
library so it runs without the project venv.

Run:
    py -3 scripts\\probe_rp_stdlib.py
"""
from __future__ import annotations

import io
import ssl
import zipfile
from datetime import date, timedelta
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
TARGET_HINTS = ("расчетные цены", "расчётные цены", "_фр")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def magic(content: bytes) -> str:
    if content[:2] == b"PK":
        return "xlsx/zip (PK)"
    if content[:4] == b"\xd0\xcf\x11\xe0":
        return "OLE2 .xls (D0 CF 11 E0)"
    return f"unknown; head={content[:48]!r}"


def fetch(url: str):
    req = Request(url, headers={"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})
    try:
        with urlopen(req, timeout=30, context=_CTX) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except Exception as exc:  # noqa: BLE001
        return None, repr(exc), b""


def col_idx(ref: str) -> int:
    letters = "".join(c for c in ref if c.isalpha())
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
    return idx - 1


def read_shared(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    out: list[str] = []
    for si in root.findall(f"{{{NS_MAIN}}}si"):
        parts = [t.text or "" for t in si.iter(f"{{{NS_MAIN}}}t")]
        out.append("".join(parts))
    return out


def list_sheets(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    relmap = {rel.get("Id"): rel.get("Target") for rel in rels}
    sheets: list[tuple[str, str]] = []
    for s in wb.find(f"{{{NS_MAIN}}}sheets"):
        name = s.get("name")
        rid = s.get(f"{{{NS_REL}}}id")
        target = relmap.get(rid, "")
        if target and not target.startswith("/"):
            target = "xl/" + target.lstrip("/")
        sheets.append((name, target.lstrip("/")))
    return sheets


def dump_sheet(z: zipfile.ZipFile, target: str, shared: list[str], limit: int = 14) -> None:
    root = ET.fromstring(z.read(target))
    sd = root.find(f"{{{NS_MAIN}}}sheetData")
    if sd is None:
        print("   (no sheetData)")
        return
    for i, row in enumerate(sd.findall(f"{{{NS_MAIN}}}row")):
        cells: dict[int, str] = {}
        for c in row.findall(f"{{{NS_MAIN}}}c"):
            ref = c.get("r", "")
            t = c.get("t", "")
            v = c.find(f"{{{NS_MAIN}}}v")
            is_node = c.find(f"{{{NS_MAIN}}}is")
            if t == "s" and v is not None:
                val = shared[int(v.text)] if v.text and int(v.text) < len(shared) else ""
            elif t == "inlineStr" and is_node is not None:
                val = "".join(tn.text or "" for tn in is_node.iter(f"{{{NS_MAIN}}}t"))
            elif v is not None:
                val = v.text
            else:
                val = ""
            cells[col_idx(ref)] = val
        if cells:
            width = max(cells) + 1
            print(f"   row[{i}]:", [cells.get(j, None) for j in range(width)])
        if i >= limit:
            break


def candidates(d: date) -> list[str]:
    ddmmyy = d.strftime("%d%m%y")
    return [
        f"https://kacc.kase.kz/ru/risk-parameters/rp{ddmmyy}.xls",
        f"https://kacc.kase.kz/en/risk-parameters/rp{ddmmyy}.xls",
        f"https://kacc.kase.kz/ru/risk-parameters/rp{ddmmyy}.xlsx",
    ]


def main() -> None:
    today = date.today()
    print(f"today={today.isoformat()}")
    for delta in range(0, 15):
        d = today - timedelta(days=delta)
        for url in candidates(d):
            status, ct, content = fetch(url)
            if status != 200 or not content:
                print(f"[{status}] {url} ({ct})")
                continue
            print(f"[200] {url} ct={ct} len={len(content)} magic={magic(content)}")
            out_path = f"scripts/_sample_rp_{d.strftime('%d%m%y')}.bin"
            with open(out_path, "wb") as fh:
                fh.write(content)
            print(f"  saved -> {out_path}")
            if content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(content))
                shared = read_shared(z)
                sheets = list_sheets(z)
                print("  SHEETS:", [s[0] for s in sheets])
                target = next(
                    (
                        tgt
                        for nm, tgt in sheets
                        if any(h in nm.lower().replace("ё", "е") for h in TARGET_HINTS)
                    ),
                    None,
                )
                if target:
                    name = next(nm for nm, tgt in sheets if tgt == target)
                    print(f"  TARGET SHEET: {name!r} -> {target}")
                    dump_sheet(z, target, shared)
                else:
                    print("  !! target sheet not found; first row of each sheet:")
                    for nm, tgt in sheets:
                        if tgt:
                            print(f"   - {nm!r}")
                            dump_sheet(z, tgt, shared, limit=1)
            else:
                print("  (not xlsx; cannot parse with stdlib — magic reported above)")
            return
    print("No risk-parameter file found in the last 15 days.")


if __name__ == "__main__":
    main()
