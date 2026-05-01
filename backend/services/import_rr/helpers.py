"""Утилиты для импортёра Risk Report XLSM."""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from openpyxl.worksheet.worksheet import Worksheet

# Шаблон имени файла: risk report_DDMMYYYY_.xlsm  (с подчёркиванием в конце или без)
RR_FILENAME_RE = re.compile(
    r"risk[\s_]*report[\s_]*[-_]?(\d{2})\.?(\d{2})\.?(\d{4})_?",
    re.IGNORECASE,
)


def extract_date_from_filename(file_path: Path | str) -> Optional[date]:
    """Достать дату из имени файла Risk Report.
    Поддерживает: risk report_20102025_.xlsm, risk report 20.10.2025.xlsm и т.п."""
    name = Path(file_path).stem
    m = RR_FILENAME_RE.search(name)
    if not m:
        # Альтернативный шаблон: risk_report_20251020.xlsm
        m2 = re.search(r"(\d{8})", name)
        if m2:
            try:
                s = m2.group(1)
                return date(int(s[4:8]), int(s[2:4]), int(s[0:2]))
            except (ValueError, IndexError):
                pass
        return None
    try:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return date(y, mo, d)
    except ValueError:
        return None


def file_sha256(path: Path) -> str:
    """SHA-256 содержимого файла (для дедупликации источника)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def cell_str(value: Any) -> Optional[str]:
    """Безопасное приведение ячейки к str с обрезкой пробелов."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s and s != "-" else None


def cell_float(value: Any) -> Optional[float]:
    """Распознать число из ячейки (поддерживает каз. формат пробел+запятая)."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if f == f else None  # NaN check
    s = str(value).replace(" ", "").replace("\u00A0", "").replace(",", ".")
    if not s or s == "-":
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def cell_int(value: Any) -> Optional[int]:
    f = cell_float(value)
    return int(round(f)) if f is not None else None


def cell_date(value: Any) -> Optional[date]:
    """Распознать дату — datetime/date/строка ДД.ММ.ГГГГ или ГГГГ-ММ-ДД."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s or s == "-":
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y.%m.%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def normalize_header(s: Any) -> str:
    """Шапка → нижний регистр без множ. пробелов и табов."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).strip().lower())


def find_header_row(ws: Worksheet, *, max_scan: int = 30,
                    must_contain: Iterable[str] = ()) -> Optional[int]:
    """Найти строку с шапкой колонок: первая строка, где встречаются все ключевые слова.

    `must_contain` — нижний регистр; ищется как подстрока в склейке всех ячеек строки.
    """
    needed = [n.lower() for n in must_contain]
    if not needed:
        return None
    upper = min(ws.max_row or 0, max_scan)
    for r in range(1, upper + 1):
        joined = " | ".join(
            normalize_header(ws.cell(r, c).value) for c in range(1, (ws.max_column or 0) + 1)
        )
        if all(k in joined for k in needed):
            return r
    return None


def header_index_map(ws: Worksheet, header_row: int,
                     *, max_col: Optional[int] = None) -> dict[str, int]:
    """Маппинг нормализованной шапки → номер колонки (1-индексный)."""
    out: dict[str, int] = {}
    upper = max_col if max_col is not None else (ws.max_column or 0)
    for c in range(1, upper + 1):
        h = normalize_header(ws.cell(header_row, c).value)
        if h and h not in out:
            out[h] = c
    return out


def find_col(headers: dict[str, int], *aliases: str) -> Optional[int]:
    """Найти колонку по любому из псевдонимов (case-insensitive substring match)."""
    for alias in aliases:
        a = alias.lower()
        if a in headers:
            return headers[a]
    # substring fallback
    for h, c in headers.items():
        for alias in aliases:
            if alias.lower() in h:
                return c
    return None


def iter_data_rows(ws: Worksheet, start_row: int, *, stop_on_empty_a: bool = True):
    """Итератор по строкам данных начиная со start_row.
    Останавливается если в первой колонке N пустых строк подряд."""
    empty_streak = 0
    max_empty = 5
    for r in range(start_row, (ws.max_row or 0) + 1):
        first = ws.cell(r, 1).value
        if first is None or (isinstance(first, str) and not first.strip()):
            empty_streak += 1
            if stop_on_empty_a and empty_streak >= max_empty:
                break
            continue
        empty_streak = 0
        yield r


def normalize_subfund_name(s: Any) -> Optional[str]:
    """Канонизация Sub portfolio name → имя CDU из словаря CDU_NAME_ALIASES."""
    from services.calculator.constants import normalize_cdu_name
    return normalize_cdu_name(cell_str(s))


def safe_sheet(wb, *names: str):
    """Получить лист по любому из имён или None.
    Поиск нечёткий (case-insensitive, без пробелов/двоеточий)."""
    if not wb:
        return None
    targets = [re.sub(r"[\s_:.()-]+", "", n.lower()) for n in names]
    for sheet_name in wb.sheetnames:
        normed = re.sub(r"[\s_:.()-]+", "", sheet_name.lower())
        for t in targets:
            if t and (t == normed or t in normed or normed in t):
                return wb[sheet_name]
    return None
