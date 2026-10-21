"""Parser of the reconciliation workbook sent by a manager («Сверка КФГД …»,
«Приложение 3 Сверка»).

Every manager fills the same template (business process 6.5 B), but with its
own layout: an extra «№» column, nominal per security instead of the total,
rates as 0.1067 instead of 10.67, dates as text, totals with or without the
«ИТОГО» label.  The parser therefore finds tables by their headers and maps
columns by header text, never by fixed cells.

Extracted (all amounts in tenge):

* ``securities`` — lines of the «ЦБ» table: ISIN, quantity, total nominal,
  coupon rate, purchase date, maturity, clean purchase cost, clean price,
  dirty price, accrued coupon, market value;
* ``cash`` — balances of «Остатки на инвест. счетах» by currency/account;
* ``repos`` — lines of «Обратное репо»: ISIN, quantity, open/close dates and
  amounts, rate, accrued reward, current value;
* ``receivables`` — lines of «Прочие активы (дебиторская задолженность)»;
* ``liabilities`` — commissions and other payables (information only);
* ``totals`` — section totals as stated in the file (``*_file``) and as the sum
  of the parsed lines; ``total`` is «Итого активов».
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

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
CURRENCIES = ("KZT", "USD", "EUR", "RUB", "CNY", "GBP")


class ProtectedWorkbookError(ValueError):
    """The workbook is encrypted with a password."""


# ───────────────────────────── cell helpers ─────────────────────────────

def _norm(value: Any) -> str:
    text = str(value or "").lower().replace("ё", "е").replace("\xa0", " ")
    text = re.sub(r"[\s\-–—.,:;«»\"'()_]+", " ", text)
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
    if isinstance(value, (datetime, date)):
        return None
    text = str(value).replace("\xa0", "").replace(" ", "").strip()
    if not text or text in ("-", "–", "—"):
        return None
    if "," in text and "." in text:
        text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    text = text.rstrip("%")
    try:
        return float(text)
    except ValueError:
        return None


def _to_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def _cell(row: List[Any], col: Optional[int]) -> Any:
    if col is None or col >= len(row):
        return None
    return row[col]


def _isin(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip().upper().replace(" ", "")
    return text if ISIN_RE.match(text) else None


def _row_texts(row: List[Any]) -> List[str]:
    return [_norm(v) for v in row if isinstance(v, str) and v.strip()]


def _find(grid: Grid, *needles: str, start_row: int = 0, end_row: Optional[int] = None) -> Optional[Tuple[int, int]]:
    for r in range(start_row, min(end_row if end_row is not None else len(grid), len(grid))):
        for c, value in enumerate(grid[r]):
            if isinstance(value, str):
                text = _norm(value)
                if any(_similar(text, _norm(n)) for n in needles):
                    return r, c
    return None


def _first_number_right(row: List[Any], c: int) -> Optional[float]:
    for value in row[c + 1:]:
        n = _num(value)
        if n is not None:
            return n
    return None


def _header_map(row: List[Any], spec: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]]) -> Dict[str, int]:
    """Column index for every field: (needles, excluded words)."""
    out: Dict[str, int] = {}
    for c, value in enumerate(row):
        if not isinstance(value, str):
            continue
        text = _norm(value)
        for field, (needles, excluded) in spec.items():
            if field in out:
                continue
            if any(n in text for n in needles) and not any(x in text for x in excluded):
                out[field] = c
                break
    return out


# ───────────────────────────── sections ─────────────────────────────

SEC_SPEC = {
    "name": (("наименование эмитента", "наименование"), ()),
    "isin": (("isin",), ()),
    "quantity": (("количество",), ()),
    "nominal": (("номинальн",), ()),
    "rate": (("ставка",), ()),
    "purchase_date": (("дата зачисления", "приобрет"), ()),
    "maturity_date": (("дата погашения",), ()),
    "purchase_cost": (("покупная",), ()),
    "dirty_price": (("грязная",), ()),
    "price": (("расчетная цена", "цена"), ("грязная", "покупная")),
    "accrued": (("накопленный купон", "накопленное", "нкд"), ()),
    "value": (("суммарно текущая", "рыночная стоимость", "текущая рыночная"), ()),
    "weight": (("вес",), ()),
}

REPO_SPEC = {
    "name": (("наименование",), ()),
    "isin": (("isin", "нин"), ()),
    "quantity": (("количество",), ()),
    "currency": (("валюта",), ()),
    "open_date": (("дата открытия",), ()),
    "close_date": (("дата закрытия",), ()),
    "open_price": (("цена открытия",), ()),
    "close_price": (("цена закрытия",), ()),
    "open_amount": (("сумма открытия",), ()),
    "close_amount": (("сумма закрытия",), ()),
    "rate": (("ставка",), ()),
    "accrued": (("начисленн",), ()),
    "value": (("текущая стоимость", "суммарная текущая"), ()),
}

AR_SPEC = {
    "name": (("наименование",), ()),
    "currency": (("валюта",), ()),
    "record_date": (("дата постановки",), ()),
    "quantity": (("количество",), ()),
    "amount_ccy": (("остаток в валюте",), ()),
    "amount_kzt": (("остаток в тенге",), ()),
}

_STOP_SEC = ("остатки на инвест", "обратное репо", "прочие активы", "итого активов")
_STOP_REPO = ("прочие активы", "итого активов", "кредиторская")


def _is_total_row(row: List[Any]) -> bool:
    return any(t.startswith(("итого", "всего", "total")) for t in _row_texts(row))


def _hits_stop(row: List[Any], stops: Tuple[str, ...]) -> bool:
    return any(any(s in t for s in stops) for t in _row_texts(row))


def _rate_pct(value: Any) -> Optional[float]:
    n = _num(value)
    if n is None:
        return None
    return round(n * 100.0, 10) if 0 < abs(n) < 1 else n


def _parse_securities(grid: Grid, warnings: List[str]) -> Tuple[List[Dict[str, Any]], Optional[float], Optional[int]]:
    header_r = None
    for r, row in enumerate(grid):
        texts = _row_texts(row)
        if any("isin" in t for t in texts) and any("количество" in t for t in texts) and \
                any("рыночн" in t or "суммарно" in t for t in texts):
            header_r = r
            break
    if header_r is None:
        warnings.append("Не найдена таблица «ЦБ» (заголовок с ISIN, количеством и рыночной стоимостью)")
        return [], None, None
    cols = _header_map(grid[header_r], SEC_SPEC)
    lines: List[Dict[str, Any]] = []
    file_total: Optional[float] = None
    end_r = header_r
    for r in range(header_r + 1, len(grid)):
        row = grid[r]
        if _hits_stop(row, _STOP_SEC):
            end_r = r
            break
        isin = _isin(_cell(row, cols.get("isin")))
        if isin is None:
            # footer: «ИТОГО» or an unlabeled line with the total of the value column
            value = _num(_cell(row, cols.get("value")))
            if value is not None and lines and file_total is None and (
                _is_total_row(row) or _cell(row, cols.get("isin")) in (None, "")
            ):
                file_total = value
            end_r = r
            continue
        qty = _num(_cell(row, cols.get("quantity")))
        nominal_raw = _num(_cell(row, cols.get("nominal")))
        dirty = _num(_cell(row, cols.get("dirty_price")))
        value = _num(_cell(row, cols.get("value")))
        face = _total_nominal(qty, nominal_raw, dirty, value)
        lines.append({
            "row": r + 1,
            "name": str(_cell(row, cols.get("name")) or "").strip() or None,
            "isin": isin,
            "quantity": qty,
            "face_value": face,
            "rate_pct": _rate_pct(_cell(row, cols.get("rate"))),
            "purchase_date": _iso(_to_date(_cell(row, cols.get("purchase_date")))),
            "maturity_date": _iso(_to_date(_cell(row, cols.get("maturity_date")))),
            "purchase_cost": _num(_cell(row, cols.get("purchase_cost"))),
            "price": _num(_cell(row, cols.get("price"))),
            "dirty_price": dirty,
            "accrued": _num(_cell(row, cols.get("accrued"))),
            "value": value,
        })
        end_r = r
    return lines, file_total, end_r


def _total_nominal(qty: Optional[float], nominal: Optional[float], dirty: Optional[float],
                   value: Optional[float]) -> Optional[float]:
    """«Номинальная стоимость» is the total of the line, but some managers put
    the nominal of one security there (Tansar: 1000).  Pick the reading that
    agrees with value = nominal × dirty price."""
    if nominal is None:
        return None
    if qty in (None, 0):
        return nominal
    candidates = [nominal, nominal * qty]
    if dirty and value:
        return min(candidates, key=lambda f: abs(f * dirty / 100.0 - value))
    return nominal * qty if nominal < qty else nominal


def _parse_cash(grid: Grid, start: int) -> List[Dict[str, Any]]:
    hit = _find(grid, "остатки на инвест", "остатки на инвестиционных", start_row=max(start - 2, 0))
    if not hit:
        return []
    lr, _ = hit
    out: List[Dict[str, Any]] = []
    for r in range(lr, min(lr + 6, len(grid))):
        row = grid[r]
        if r > lr and _hits_stop(row, ("обратное репо", "прочие активы", "итого активов")):
            break
        for c, value in enumerate(row):
            if not isinstance(value, str):
                continue
            text = value.strip().upper()
            if text in CURRENCIES:
                amount = _first_number_right(row, c)
                if amount is not None:
                    out.append({"currency": text, "account": None, "amount": amount, "row": r + 1})
                break
            if re.match(r"^KZ\d{2}[0-9A-Z]{10,30}$", text.replace(" ", "")):
                amount = _first_number_right(row, c)
                if amount is not None and out:
                    out[-1]["account"] = text.replace(" ", "")
                break
    return out


def _parse_repos(grid: Grid, start: int, warnings: List[str]) -> Tuple[List[Dict[str, Any]], Optional[float]]:
    header_r = None
    for r in range(start, len(grid)):
        texts = _row_texts(grid[r])
        if any("дата открытия" in t for t in texts) and any("сумма открытия" in t for t in texts):
            header_r = r
            break
    if header_r is None:
        return [], None
    cols = _header_map(grid[header_r], REPO_SPEC)
    lines: List[Dict[str, Any]] = []
    file_total: Optional[float] = None
    for r in range(header_r + 1, len(grid)):
        row = grid[r]
        if _hits_stop(row, _STOP_REPO):
            break
        open_date = _to_date(_cell(row, cols.get("open_date")))
        open_amount = _num(_cell(row, cols.get("open_amount")))
        if open_date is None or open_amount is None:
            value = _num(_cell(row, cols.get("value")))
            if _is_total_row(row) or (lines and value is not None and file_total is None):
                file_total = value if value is not None else file_total
            continue
        lines.append({
            "row": r + 1,
            "name": str(_cell(row, cols.get("name")) or "").strip() or None,
            "isin": _isin(_cell(row, cols.get("isin"))) or (str(_cell(row, cols.get("isin")) or "").strip() or None),
            "quantity": _num(_cell(row, cols.get("quantity"))),
            "currency": str(_cell(row, cols.get("currency")) or "KZT").strip().upper(),
            "open_date": _iso(open_date),
            "close_date": _iso(_to_date(_cell(row, cols.get("close_date")))),
            "open_price": _num(_cell(row, cols.get("open_price"))),
            "close_price": _num(_cell(row, cols.get("close_price"))),
            "open_amount": open_amount,
            "close_amount": _num(_cell(row, cols.get("close_amount"))),
            "rate_pct": _rate_pct(_cell(row, cols.get("rate"))),
            "accrued": _num(_cell(row, cols.get("accrued"))) or 0.0,
            "value": _num(_cell(row, cols.get("value"))),
        })
    return lines, file_total


def _parse_receivables(grid: Grid, start: int) -> Tuple[List[Dict[str, Any]], Optional[float]]:
    hit = _find(grid, "прочие активы", start_row=start)
    if not hit:
        return [], None
    header_r = None
    for r in range(hit[0], min(hit[0] + 4, len(grid))):
        if any("остаток в тенге" in t for t in _row_texts(grid[r])):
            header_r = r
            break
    if header_r is None:
        return [], None
    cols = _header_map(grid[header_r], AR_SPEC)
    lines: List[Dict[str, Any]] = []
    file_total: Optional[float] = None
    for r in range(header_r + 1, len(grid)):
        row = grid[r]
        if _hits_stop(row, ("итого активов", "кредиторская")):
            break
        amount = _num(_cell(row, cols.get("amount_kzt")))
        name = _cell(row, cols.get("name"))
        if _is_total_row(row):
            file_total = amount if amount is not None else file_total
            continue
        if amount is None or not (isinstance(name, str) and name.strip()):
            continue
        lines.append({
            "row": r + 1, "name": name.strip(),
            "currency": str(_cell(row, cols.get("currency")) or "KZT").strip().upper(),
            "record_date": _iso(_to_date(_cell(row, cols.get("record_date")))),
            "amount_ccy": _num(_cell(row, cols.get("amount_ccy"))),
            "amount_kzt": amount,
        })
    return lines, file_total


_LIAB_NEEDLES = ("комиссия", "клиринговый сбор", "кредиторская задолженность", "остаток прочих обязательств")


def _parse_liabilities(grid: Grid, start: int) -> Tuple[List[Dict[str, Any]], Optional[float], Optional[float]]:
    hit = _find(grid, "кредиторская задолженност", start_row=start)
    if not hit:
        return [], None, None
    out: List[Dict[str, Any]] = []
    total = None
    for r in range(hit[0] + 1, len(grid)):
        row = grid[r]
        for c, value in enumerate(row):
            if not isinstance(value, str):
                continue
            text = _norm(value)
            if text.startswith("итого") and "чист" not in text:
                total = _first_number_right(row, c)
                break
            if any(text.startswith(n) for n in _LIAB_NEEDLES):
                amount = _first_number_right(row, c)
                out.append({"name": value.strip(), "amount": amount or 0.0, "row": r + 1})
                break
    net = None
    hit_net = _find(grid, "итого чистых активов", "чистые активы", start_row=hit[0])
    if hit_net:
        net = _first_number_right(grid[hit_net[0]], hit_net[1])
    return [x for x in out if x["amount"]], total, net


def _money(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


# ───────────────────────────── header data ─────────────────────────────

def _report_date(grid: Grid, file_name: str) -> Optional[date]:
    hit = _find(grid, "отчетная дата", "дата сверки", "на дату", "по состоянию на", end_row=8)
    if hit:
        r, c = hit
        for value in grid[r][c + 1:]:
            d = _to_date(value)
            if d:
                return d
    for r in range(min(5, len(grid))):
        for value in grid[r]:
            d = _to_date(value) if isinstance(value, (datetime, date)) or (
                isinstance(value, str) and re.match(r"^\d{2}\.\d{2}\.\d{4}$", value.strip())) else None
            if d:
                return d
    m = re.search(r"(\d{2})[.\s_](\d{2})[.\s_](\d{2,4})(?!\d)", file_name)
    if m:
        year = int(m.group(3))
        year = year + 2000 if year < 100 else year
        try:
            return date(year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def _cdu_name(grid: Grid, file_name: str) -> Optional[str]:
    hit = _find(grid, "наименование доверительного управляющего", "доверительный управляющий", end_row=5)
    if hit:
        r, c = hit
        for value in grid[r][c + 1:]:
            if isinstance(value, str) and value.strip():
                return value.strip()
    # «Сентрас Секьюритиз | 31.12.2025» in the first cell
    first = grid[0][0] if grid and grid[0] else None
    if isinstance(first, str) and normalize_cdu_name(first):
        return first.strip()
    return normalize_cdu_name(Path(file_name).stem)


# ───────────────────────────── entry points ─────────────────────────────

def parse_reconciliation_grid(grid: Grid, file_name: str = "") -> Dict[str, Any]:
    warnings: List[str] = []
    report_date = _report_date(grid, file_name)
    securities, sec_file_total, sec_end = _parse_securities(grid, warnings)
    after_sec = sec_end or 0
    cash = _parse_cash(grid, after_sec)
    repos, repo_file_total = _parse_repos(grid, after_sec, warnings)
    # deals closed on/before the report date are shown by some managers with
    # the close amount, by others with 0; they are not assets any more
    for x in repos:
        x["closed"] = bool(report_date and x["close_date"] and x["close_date"] <= report_date.isoformat())
        x["value_effective"] = 0.0 if x["closed"] else (x["value"] if x["value"] is not None else
                                                         x["open_amount"] + (x["accrued"] or 0.0))
    receivables, ar_file_total = _parse_receivables(grid, after_sec)
    liabilities, liab_total, net_assets = _parse_liabilities(grid, after_sec)

    total_hit = _find(grid, "итого активов", start_row=after_sec)
    total_assets = _first_number_right(grid[total_hit[0]], total_hit[1]) if total_hit else None

    sec_sum = sum(x["value"] or 0.0 for x in securities)
    repo_sum = sum(x["value_effective"] for x in repos)
    cash_kzt = sum(x["amount"] for x in cash if x["currency"] == "KZT")
    ar_sum = sum(x["amount_kzt"] for x in receivables)
    totals: Dict[str, Any] = {
        "securities": sec_file_total if sec_file_total is not None else sec_sum,
        "cash": cash_kzt,
        "repo": repo_file_total if repo_file_total is not None else repo_sum,
        "ar": ar_file_total if ar_file_total is not None else ar_sum,
        "securities_lines": sec_sum,
        "repo_lines": repo_sum,
    }
    if total_assets is not None:
        totals["total"] = total_assets
    if liab_total is not None:
        totals["liabilities"] = liab_total
    if net_assets is not None:
        totals["net_assets"] = net_assets

    if sec_file_total is not None and abs(sec_file_total - sec_sum) > 1.0:
        warnings.append(f"В файле итог ЦБ {_money(sec_file_total)} не равен сумме строк {_money(sec_sum)}")
    if repo_file_total is not None and abs(repo_file_total - repo_sum) > 1.0:
        warnings.append(f"В файле итог РЕПО {_money(repo_file_total)} не равен сумме строк {_money(repo_sum)}")
    if total_assets is not None:
        components = totals["securities"] + totals["cash"] + totals["repo"] + totals["ar"]
        if abs(components - total_assets) > 1.0:
            warnings.append(
                f"«Итого активов» в файле ({_money(total_assets)}) не равно сумме разделов ({_money(components)})"
            )
    else:
        warnings.append("Не найдено «Итого активов»")
    if not cash:
        warnings.append("Не найден остаток денег («Остатки на инвест. счетах»)")
    empty = sum(1 for x in securities if x["value"] is None or not x["face_value"])
    if empty:
        warnings.append(
            f"В {empty} строках ЦБ пусты номинал или рыночная стоимость — если там формулы, "
            "откройте файл в Excel, сохраните и загрузите снова"
        )

    return {
        "cdu_name": _cdu_name(grid, file_name),
        "report_date": report_date,
        "totals": totals,
        "securities": securities,
        "cash": cash,
        "repos": repos,
        "receivables": receivables,
        "liabilities": liabilities,
        "rows_parsed": len(securities) + len(repos) + len(receivables) + len(cash),
        "warnings": warnings,
    }


def _pick_sheet(wb) -> Any:
    """The template sheet («ДУ», «Лист1» …): the first one with the ЦБ table."""
    for ws in wb.worksheets:
        if ws.max_row and ws.max_row > 2000:
            continue                                    # price lists (KASE / risk prices)
        for row in ws.iter_rows(min_row=1, max_row=15, values_only=True):
            texts = " ".join(_norm(v) for v in row if isinstance(v, str))
            if "isin" in texts and ("рыночн" in texts or "количество" in texts):
                return ws
    return wb.worksheets[0]


def _is_encrypted(path: Path) -> bool:
    with open(path, "rb") as fh:
        return fh.read(8) == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" and path.suffix.lower() in (".xlsx", ".xlsm")


def parse_reconciliation_xlsx(file_path: Path | str) -> Dict[str, Any]:
    path = Path(file_path)
    if _is_encrypted(path):
        raise ProtectedWorkbookError(
            "Файл сверки защищён паролем (зашифрован). Откройте его в Excel, снимите пароль "
            "(Файл → Сведения → Защита книги → Зашифровать паролем → пусто) и загрузите снова."
        )
    wb = load_workbook(path, data_only=True)
    try:
        ws = _pick_sheet(wb)
        grid: Grid = [list(row or ()) for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    result = parse_reconciliation_grid(grid, path.name)
    result["sheet"] = ws.title
    return result
