"""Reconciliation XLSX parser — Phase B4 placeholder.

Expected layout (from ЧДУ):
  - Rows with Cash, ΣSecurities, REPO, AR, Total
  - We extract these totals and compare with Risk Report / internal ledger.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
from openpyxl import load_workbook
from loguru import logger


def parse_reconciliation_xlsx(file_path: Path | str) -> Dict[str, Any]:
    wb = load_workbook(Path(file_path), data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    totals: Dict[str, float] = {}
    for row in rows:
        if not row or len(row) < 2:
            continue
        label = str(row[0]).strip().lower() if row[0] else ""
        val = _to_float(row[1])
        if val is None:
            continue
        if "cash" in label or "деньги" in label:
            totals["cash"] = val
        elif "цб" in label or "security" in label or "ценные" in label:
            totals["securities"] = val
        elif "репо" in label or "repo" in label:
            totals["repo"] = val
        elif "дебитор" in label or "ar" in label or "задолжен" in label:
            totals["ar"] = val
        elif "итог" in label or "total" in label or "всего" in label:
            totals["total"] = val
    return {"totals": totals, "rows_parsed": len(rows)}


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return None if v != v else float(v)
    try:
        s = str(v).replace(" ", "").replace("\u00a0", "").replace(",", ".")
        return float(s)
    except (ValueError, TypeError):
        return None
