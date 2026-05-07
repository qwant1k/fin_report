"""Normalisation of Kazakhstani number / date strings produced by KASE exports."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

# Whitespace characters that may appear as thousands separators
_WS_RE = re.compile(r"[\s\u00A0\u202F\u2009]")


def parse_kz_number(value: Any) -> Optional[float]:
    """Parse a number that may use space as thousands separator and comma as decimal.

    Examples:
        "2 069 895 029"   -> 2069895029.0
        "16,5"            -> 16.5
        "12 000 590,78"   -> 12000590.78
        "-"               -> None
        ""                -> None
        "  "              -> None
        12.5              -> 12.5
        None              -> None
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s in {"-", "—", "–", "n/a", "N/A"}:
        return None
    s = _WS_RE.sub("", s)
    s = s.replace(",", ".")
    # numbers occasionally come as "1.234.567,89" with both separators — handle gracefully
    if s.count(".") > 1:
        last = s.rfind(".")
        s = s[:last].replace(".", "") + s[last:]
    try:
        return float(s)
    except ValueError:
        return None


def parse_kz_date(value: Any) -> Optional[date]:
    """Parse a date that may come as datetime, "DD.MM.YYYY" or "YYYY-MM-DD"."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        # Excel serial date (Windows 1900 date system). Real KASE/ЧДУ files
        # sometimes store dates as numbers when the cell style is lost.
        if 1 <= float(value) <= 60000:
            return (datetime(1899, 12, 30) + timedelta(days=float(value))).date()
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_int(value: Any) -> Optional[int]:
    """Parse integer value (uses parse_kz_number then int())."""
    f = parse_kz_number(value)
    if f is None:
        return None
    try:
        return int(round(f))
    except (TypeError, ValueError):
        return None


def s(value: Any) -> Optional[str]:
    """Trim string, return None for empty / placeholders."""
    if value is None:
        return None
    out = str(value).strip()
    if not out or out in {"-", "—", "–"}:
        return None
    return out
