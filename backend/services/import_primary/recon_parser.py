"""Parser of the reconciliation workbook sent by a manager («Сверка КФГД …»).

Implements business process 6.5 B — anchors instead of fixed cells, because
every manager has its own layout:

* B.1 Cash — the number next to the cell «KZT» located within two rows /
  columns of the label «Остатки на инвест. счетах».
* B.2 Securities — total of the column «Суммарно-текущая рыночная стоимость»
  of the «ЦБ» table (footer row «ИТОГО» or an unlabeled footer; if there is
  no footer, the sum of the data rows).
* B.3 Reverse REPO — total of «Суммарная текущая стоимость, в тг».
* B.4 Receivables — total of «Остаток в тенге» in «Прочие активы …».
* B.5 Total — the number to the right of «Итого активов».

Labels are compared case/space-insensitively with a small fuzzy tolerance.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import load_workbook

from services.calculator.constants import normalize_cdu_name

Grid = List[List[Any]]


def _norm(value: Any) -> str:
    text = str(value or "").lower().replace("ё", "е").replace("\xa0", " ")
    text = re.sub(r"[\s\-–—.,:;«»\"'()]+", " ", text)
    return text.strip()


def _similar(text: str, needle: str) -> bool:
    if needle in text:
        return True
    if len(needle) >= 15 and len(text) >= 10:
        return SequenceMatcher(None, text[: len(needle) + 5], needle).ratio() >= 0.85
    return False


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if value != value else float(value)
    text = str(value).replace("\xa0", "").replace(" ", "").strip()
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _find(grid: Grid, *needles: str, start_row: int = 0) -> Optional[Tuple[int, int]]:
    for r in range(start_row, len(grid)):
        for c, value in enumerate(grid[r]):
            if isinstance(value, str):
                text = _norm(value)
                if any(_similar(text, _norm(n)) for n in needles):
                    return r, c
    return None


def _first_number_right(grid: Grid, r: int, c: int) -> Optional[float]:
    for value in grid[r][c + 1:]:
        n = _num(value)
        if n is not None:
            return n
    return None


def _column_total(grid: Grid, header_r: int, col: int, key_col: Optional[int],
                  stop_needles: Tuple[str, ...]) -> Optional[float]:
    """Footer total of a column; falls back to the sum of the data rows."""
    data_sum = 0.0
    has_data = False
    for r in range(header_r + 1, len(grid)):
        row = grid[r]
        texts = [_norm(v) for v in row if isinstance(v, str) and v.strip()]
        if any(any(_similar(t, _norm(s)) for s in stop_needles) for t in texts):
            break
        value = _num(row[col]) if col < len(row) else None
        key = row[key_col] if key_col is not None and key_col < len(row) else None
        key_text = _norm(key) if isinstance(key, str) else ""
        is_footer = (
            any(t in ("итого", "итого:", "всего", "total") for t in texts)
            or (key_col is not None and (key is None or key_text in ("", "итого")) and value is not None and has_data)
        )
        if is_footer and value is not None:
            return value
        if value is not None and not is_footer:
            data_sum += value
            has_data = True
        if not any(v not in (None, "") for v in row) and has_data:
            # blank line after the table body
            continue
    return data_sum if has_data else None


def _report_date(grid: Grid, file_name: str) -> Optional[date]:
    hit = _find(grid, "дата сверки", "на дату", "по состоянию на")
    if hit:
        r, c = hit
        for value in grid[r][c + 1:]:
            d = _to_date(value)
            if d:
                return d
    # a real date cell in the first rows (numbers are NOT taken as Excel serials)
    for r in range(min(5, len(grid))):
        for value in grid[r]:
            if isinstance(value, (datetime, date)):
                return value.date() if isinstance(value, datetime) else value
    m = re.search(r"(\d{2})[.\s_](\d{2})[.\s_](\d{4})", file_name)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def _to_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _cdu_name(grid: Grid, file_name: str) -> Optional[str]:
    hit = _find(grid, "наименование доверительного управляющего", "доверительный управляющий")
    if hit:
        r, c = hit
        for value in grid[r][c + 1:]:
            if isinstance(value, str) and value.strip():
                return value.strip()
    canonical = normalize_cdu_name(Path(file_name).stem)
    return canonical


def parse_reconciliation_grid(grid: Grid, file_name: str = "") -> Dict[str, Any]:
    totals: Dict[str, float] = {}
    warnings: List[str] = []

    # B.2 securities
    sec_header = _find(grid, "суммарно-текущая рыночная стоимость", "суммарно текущая рыночная стоимость")
    if sec_header:
        hr, hc = sec_header
        isin_col = None
        for c, value in enumerate(grid[hr]):
            if isinstance(value, str) and "isin" in value.lower():
                isin_col = c
                break
        total = _column_total(grid, hr, hc, isin_col, ("остатки на инвест", "обратное репо"))
        if total is not None:
            totals["securities"] = total

    # B.1 cash: «KZT» near «Остатки на инвест. счетах»
    cash_label = _find(grid, "остатки на инвест счетах", "остатки на инвестиционных счетах")
    if cash_label:
        lr, lc = cash_label
        found = None
        for r in range(lr, min(lr + 3, len(grid))):
            for c in range(0, min(len(grid[r]), lc + 4)):
                value = grid[r][c]
                if isinstance(value, str) and value.strip().upper() == "KZT":
                    found = _first_number_right(grid, r, c)
                    if found is not None:
                        break
            if found is not None:
                break
        if found is not None:
            totals["cash"] = found

    # B.3 reverse REPO
    repo_header = _find(grid, "суммарная текущая стоимость, в тг", "суммарная текущая стоимость в тг")
    if repo_header:
        hr, hc = repo_header
        isin_col = None
        for c, value in enumerate(grid[hr]):
            if isinstance(value, str) and ("isin" in value.lower() or "нин" in value.lower()):
                isin_col = c
                break
        total = _column_total(grid, hr, hc, isin_col, ("прочие активы", "итого активов"))
        totals["repo"] = total or 0.0

    # B.4 receivables
    ar_label = _find(grid, "прочие активы")
    if ar_label:
        ar_header = _find(grid, "остаток в тенге", start_row=ar_label[0])
        if ar_header and ar_header[0] - ar_label[0] <= 3:
            hr, hc = ar_header
            total = _column_total(grid, hr, hc, None, ("итого активов", "кредиторская"))
            totals["ar"] = total or 0.0
        else:
            totals["ar"] = 0.0

    # B.5 total assets
    total_label = _find(grid, "итого активов")
    if total_label:
        value = _first_number_right(grid, *total_label)
        if value is not None:
            totals["total"] = value

    for key in ("cash", "securities", "repo", "ar", "total"):
        if key not in totals:
            warnings.append(f"Не найден итог сверки: {key}")
    if {"cash", "securities", "repo", "ar", "total"} <= totals.keys():
        components = totals["cash"] + totals["securities"] + totals["repo"] + totals["ar"]
        if abs(components - totals["total"]) > 1.0:
            warnings.append(
                f"Итого активов в файле ({totals['total']:,.2f}) не равно сумме составляющих "
                f"({components:,.2f}) — проверьте файл ЧДУ"
            )
    return {
        "cdu_name": _cdu_name(grid, file_name),
        "report_date": _report_date(grid, file_name),
        "totals": totals,
        "rows_parsed": len(grid),
        "warnings": warnings,
    }


def parse_reconciliation_xlsx(file_path: Path | str) -> Dict[str, Any]:
    path = Path(file_path)
    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        grid: Grid = [list(row or ()) for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    return parse_reconciliation_grid(grid, path.name)
