"""Парсеры конкретных листов Risk Report XLSM.

Каждая функция принимает worksheet и возвращает структурированный список словарей
для дальнейшего сохранения в БД. Импортёр-оркестратор вызывает их по очереди.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from loguru import logger
from openpyxl.worksheet.worksheet import Worksheet

from .helpers import (
    cell_date,
    cell_float,
    cell_int,
    cell_str,
    find_col,
    find_header_row,
    header_index_map,
    iter_data_rows,
    normalize_subfund_name,
)


# ──────────────────────────────────────────────────────────────────────────
# Cash sheet — снимок денежных остатков (по ДУ × дата × валюта)
# ──────────────────────────────────────────────────────────────────────────
def parse_cash_sheet(ws: Worksheet, *, fallback_date: Optional[date] = None) -> list[dict]:
    """Лист `Cash`. Ожидаемые колонки: Дата, Sub-fund / Sub portfolio name, Currency / Валюта, Amount / Cash.

    Ищем шапку гибко — Risk Report может иметь разные расположения.
    """
    header_row = find_header_row(ws, must_contain=("sub",))
    if header_row is None:
        # Альтернативный поиск по словам "дата", "остаток"
        header_row = find_header_row(ws, must_contain=("дата",))
    if header_row is None:
        logger.debug(f"Cash sheet: header not found")
        return []

    headers = header_index_map(ws, header_row)
    col_date = find_col(headers, "дата", "date", "valuation date")
    col_sub = find_col(headers, "sub portfolio name", "sub-fund", "sub fund", "ду")
    col_ccy = find_col(headers, "currency", "валюта", "ccy")
    col_amt = find_col(headers, "amount", "остаток", "cash", "сумма", "value")

    if not col_sub or not col_amt:
        logger.debug(f"Cash sheet: required columns not found "
                     f"(sub={col_sub}, amt={col_amt})")
        return []

    out: list[dict] = []
    for r in iter_data_rows(ws, header_row + 1):
        sub = normalize_subfund_name(ws.cell(r, col_sub).value)
        if not sub:
            continue
        amt = cell_float(ws.cell(r, col_amt).value)
        if amt is None:
            continue
        d = cell_date(ws.cell(r, col_date).value) if col_date else fallback_date
        if d is None:
            d = fallback_date
        if d is None:
            continue
        ccy = cell_str(ws.cell(r, col_ccy).value) if col_ccy else "KZT"
        out.append({
            "snapshot_date": d,
            "cdu_name": sub,
            "currency": (ccy or "KZT").upper()[:8],
            "amount": amt,
            "src_row": r,
        })
    return out


# ──────────────────────────────────────────────────────────────────────────
# MV sheet — портфельные метрики
# ──────────────────────────────────────────────────────────────────────────
def parse_mv_sheet(ws: Worksheet, *, fallback_date: Optional[date] = None) -> list[dict]:
    """Лист `MV`. Ожидаемые колонки: Дата, Sub-fund, Cash flow, Market Value, Return."""
    header_row = find_header_row(ws, must_contain=("sub",))
    if header_row is None:
        header_row = find_header_row(ws, must_contain=("market value",))
    if header_row is None:
        logger.debug("MV sheet: header not found")
        return []

    headers = header_index_map(ws, header_row)
    col_date = find_col(headers, "дата", "date", "valuation date")
    col_sub = find_col(headers, "sub portfolio name", "sub-fund", "sub fund", "ду")
    col_cf = find_col(headers, "cash flow", "денежный поток")
    col_mv = find_col(headers, "market value", "рыночная стоимость", "mv total")
    col_ret = find_col(headers, "return", "доходность")
    col_ytm = find_col(headers, "ytm", "wa-ytm", "weighted average ytm")
    col_dur = find_col(headers, "duration", "wa-duration", "weighted average duration")

    if not col_sub or not col_mv:
        return []

    out: list[dict] = []
    for r in iter_data_rows(ws, header_row + 1):
        sub = normalize_subfund_name(ws.cell(r, col_sub).value)
        if not sub:
            continue
        d = cell_date(ws.cell(r, col_date).value) if col_date else fallback_date
        if d is None:
            d = fallback_date
        if d is None:
            continue
        out.append({
            "snapshot_date": d,
            "cdu_name": sub,
            "cash_flow": cell_float(ws.cell(r, col_cf).value) if col_cf else None,
            "market_value_total": cell_float(ws.cell(r, col_mv).value) or 0.0,
            "return_pct": cell_float(ws.cell(r, col_ret).value) if col_ret else None,
            "ytm_weighted": cell_float(ws.cell(r, col_ytm).value) if col_ytm else None,
            "duration_weighted": cell_float(ws.cell(r, col_dur).value) if col_dur else None,
            "src_row": r,
        })
    return out


# ──────────────────────────────────────────────────────────────────────────
# Справочник — instrument reference
# ──────────────────────────────────────────────────────────────────────────
def parse_reference_sheet(ws: Worksheet) -> list[dict]:
    """Лист `Справочник` — каталог выпусков ЦБ."""
    header_row = find_header_row(ws, must_contain=("isin",))
    if header_row is None:
        return []

    headers = header_index_map(ws, header_row)
    col_isin = find_col(headers, "isin")
    col_ticker = find_col(headers, "ticker of kase", "ticker", "тикер")
    col_name = find_col(headers, "name", "наименование", "название")
    col_issuer = find_col(headers, "issuer", "эмитент")
    col_btype = find_col(headers, "bond type", "type", "тип")
    col_coupon = find_col(headers, "coupon", "купон")
    col_freq = find_col(headers, "frequency", "частота")
    col_base = find_col(headers, "base", "базис")
    col_nominal = find_col(headers, "nominal", "номинал")
    col_start = find_col(headers, "start date", "дата выпуска")
    col_maturity = find_col(headers, "maturity", "дата погашения")
    col_currency = find_col(headers, "currency", "валюта")

    if not col_isin:
        return []

    out: list[dict] = []
    for r in iter_data_rows(ws, header_row + 1):
        isin = cell_str(ws.cell(r, col_isin).value)
        if not isin or len(isin) < 6:
            continue
        out.append({
            "isin": isin,
            "ticker_kase": cell_str(ws.cell(r, col_ticker).value) if col_ticker else None,
            "instrument_name": cell_str(ws.cell(r, col_name).value) if col_name else None,
            "issuer": cell_str(ws.cell(r, col_issuer).value) if col_issuer else None,
            "bond_type": cell_str(ws.cell(r, col_btype).value) if col_btype else None,
            "coupon_rate_pct": cell_float(ws.cell(r, col_coupon).value) if col_coupon else None,
            "frequency": cell_int(ws.cell(r, col_freq).value) if col_freq else None,
            "base": cell_str(ws.cell(r, col_base).value) if col_base else None,
            "nominal": cell_float(ws.cell(r, col_nominal).value) if col_nominal else None,
            "start_date": cell_date(ws.cell(r, col_start).value) if col_start else None,
            "maturity_date": cell_date(ws.cell(r, col_maturity).value) if col_maturity else None,
            "currency": (cell_str(ws.cell(r, col_currency).value) or "KZT").upper()[:8] if col_currency else "KZT",
            "src_row": r,
        })
    return out


# ──────────────────────────────────────────────────────────────────────────
# FX rates — Нацбанк Казахстана, Доллар США
# ──────────────────────────────────────────────────────────────────────────
def parse_fx_sheet(ws: Worksheet) -> list[dict]:
    """Лист курсов USD/KZT от НБ РК. Ожидаемые колонки: Дата, Курс."""
    header_row = find_header_row(ws, must_contain=("дата",))
    if header_row is None:
        header_row = find_header_row(ws, must_contain=("курс",))
    if header_row is None:
        return []

    headers = header_index_map(ws, header_row)
    col_date = find_col(headers, "дата", "date")
    col_rate = find_col(headers, "курс", "rate", "официальный курс")
    if not col_date or not col_rate:
        return []

    out: list[dict] = []
    for r in iter_data_rows(ws, header_row + 1):
        d = cell_date(ws.cell(r, col_date).value)
        rate = cell_float(ws.cell(r, col_rate).value)
        if d is None or rate is None or rate <= 0:
            continue
        out.append({"rate_date": d, "currency": "USD", "rate": rate, "src_row": r})
    return out


# ──────────────────────────────────────────────────────────────────────────
# MBM Index history
# ──────────────────────────────────────────────────────────────────────────
def parse_mbm_sheet(ws: Worksheet) -> list[dict]:
    """Лист с историей MBM (KASE индекс)."""
    header_row = find_header_row(ws, must_contain=("дата",))
    if header_row is None:
        header_row = find_header_row(ws, must_contain=("date",))
    if header_row is None:
        return []

    headers = header_index_map(ws, header_row)
    col_date = find_col(headers, "дата", "date")
    col_ytm = find_col(headers, "ytm", "доходность", "yield")
    col_dur = find_col(headers, "duration", "дюрация")
    if not col_date:
        return []

    out: list[dict] = []
    for r in iter_data_rows(ws, header_row + 1):
        d = cell_date(ws.cell(r, col_date).value)
        if d is None:
            continue
        out.append({
            "index_date": d,
            "ytm_value": cell_float(ws.cell(r, col_ytm).value) if col_ytm else None,
            "duration": cell_float(ws.cell(r, col_dur).value) if col_dur else None,
        })
    return out


# ──────────────────────────────────────────────────────────────────────────
# Bond lots — ГЦБ / Агентские / МФО / Ин.ЦБ
# ──────────────────────────────────────────────────────────────────────────
def parse_bond_lots_sheet(ws: Worksheet, *, category: str,
                         fallback_date: Optional[date] = None) -> list[dict]:
    """Парсер любого из листов: ГЦБ / Агентские / МФО / Ин. ЦБ.

    Все они имеют схожую структуру: Sub portfolio name, ISIN, Trade date,
    Settlement date, Face value, Market price, Market value, YTM, Duration,
    Maturity, Last coupon date, Maturity status, etc.
    """
    header_row = find_header_row(ws, must_contain=("isin",))
    if header_row is None:
        return []

    headers = header_index_map(ws, header_row)
    col_isin = find_col(headers, "isin")
    col_sub = find_col(headers, "sub portfolio name", "sub-fund", "ду")
    col_trade = find_col(headers, "trade date", "дата сделки")
    col_settle = find_col(headers, "settlement date", "valuation date", "дата расчёта")
    col_face = find_col(headers, "face value", "номинал")
    col_qty = find_col(headers, "кол-во бумаг", "quantity", "кол-во")
    col_purch = find_col(headers, "purchase price", "цена покупки", "чистая цена")
    col_mprice = find_col(headers, "market price", "рыночная цена")
    col_acc = find_col(headers, "accrued interest", "нкд")
    col_mv = find_col(headers, "market value", "рыночная стоимость")
    col_total = find_col(headers, "total value")
    col_weight = find_col(headers, "weight", "вес")
    col_ytm = find_col(headers, "ytm", "доходность")
    col_dur = find_col(headers, "duration", "дюрация")
    col_maturity = find_col(headers, "maturity", "дата погашения")
    col_lastcoupon = find_col(headers, "last coupon date")
    col_status = find_col(headers, "maturity status", "статус")

    if not col_isin or not col_sub:
        return []

    out: list[dict] = []
    for r in iter_data_rows(ws, header_row + 1):
        isin = cell_str(ws.cell(r, col_isin).value)
        if not isin:
            continue
        sub = normalize_subfund_name(ws.cell(r, col_sub).value)
        if not sub:
            continue
        face = cell_float(ws.cell(r, col_face).value) if col_face else None
        # Если лот списан в 0 — пропустим
        if face is not None and abs(face) < 0.01:
            continue
        out.append({
            "category": category,
            "isin": isin,
            "cdu_name": sub,
            "trade_date": cell_date(ws.cell(r, col_trade).value) if col_trade else fallback_date,
            "valuation_date": cell_date(ws.cell(r, col_settle).value) if col_settle else fallback_date,
            "face_value": face,
            "quantity": cell_float(ws.cell(r, col_qty).value) if col_qty else None,
            "purchase_price": cell_float(ws.cell(r, col_purch).value) if col_purch else None,
            "market_price": cell_float(ws.cell(r, col_mprice).value) if col_mprice else None,
            "accrued_interest": cell_float(ws.cell(r, col_acc).value) if col_acc else None,
            "market_value": cell_float(ws.cell(r, col_mv).value) if col_mv else None,
            "total_value": cell_float(ws.cell(r, col_total).value) if col_total else None,
            "weight": cell_float(ws.cell(r, col_weight).value) if col_weight else None,
            "ytm": cell_float(ws.cell(r, col_ytm).value) if col_ytm else None,
            "duration": cell_float(ws.cell(r, col_dur).value) if col_dur else None,
            "maturity_date": cell_date(ws.cell(r, col_maturity).value) if col_maturity else None,
            "last_coupon_date": cell_date(ws.cell(r, col_lastcoupon).value) if col_lastcoupon else None,
            "maturity_status": cell_str(ws.cell(r, col_status).value) if col_status else None,
            "src_row": r,
        })
    return out


# ──────────────────────────────────────────────────────────────────────────
# REPO open positions
# ──────────────────────────────────────────────────────────────────────────
def parse_repo_sheet(ws: Worksheet, *, fallback_date: Optional[date] = None) -> list[dict]:
    header_row = find_header_row(ws, must_contain=("close date",))
    if header_row is None:
        header_row = find_header_row(ws, must_contain=("face value",))
    if header_row is None:
        return []

    headers = header_index_map(ws, header_row)
    col_sub = find_col(headers, "sub portfolio name", "sub-fund")
    col_code = find_col(headers, "instrument code", "тикер", "ticker")
    col_isin = find_col(headers, "isin")
    col_trade = find_col(headers, "trade date")
    col_val = find_col(headers, "valuation date")
    col_close = find_col(headers, "close date")
    col_face = find_col(headers, "face value")
    col_closeval = find_col(headers, "close value")
    col_rate = find_col(headers, "repo rate", "ставка репо")
    col_acc = find_col(headers, "accrued interest")
    col_term = find_col(headers, "term", "срок")
    col_mv = find_col(headers, "market value")

    if not col_sub or not col_face:
        return []

    out: list[dict] = []
    for r in iter_data_rows(ws, header_row + 1):
        sub = normalize_subfund_name(ws.cell(r, col_sub).value)
        if not sub:
            continue
        face = cell_float(ws.cell(r, col_face).value) or 0.0
        if abs(face) < 0.01:
            continue
        out.append({
            "cdu_name": sub,
            "instrument_code": cell_str(ws.cell(r, col_code).value) if col_code else None,
            "isin": cell_str(ws.cell(r, col_isin).value) if col_isin else None,
            "trade_date": cell_date(ws.cell(r, col_trade).value) if col_trade else fallback_date,
            "valuation_date": cell_date(ws.cell(r, col_val).value) if col_val else fallback_date,
            "close_date": cell_date(ws.cell(r, col_close).value) if col_close else None,
            "face_value": face,
            "close_value": cell_float(ws.cell(r, col_closeval).value) if col_closeval else None,
            "repo_rate_pct": cell_float(ws.cell(r, col_rate).value) if col_rate else None,
            "accrued_interest": cell_float(ws.cell(r, col_acc).value) if col_acc else None,
            "term_days": cell_int(ws.cell(r, col_term).value) if col_term else None,
            "market_value": cell_float(ws.cell(r, col_mv).value) if col_mv else None,
            "src_row": r,
        })
    return out


# ──────────────────────────────────────────────────────────────────────────
# Deposits — НБ РК
# ──────────────────────────────────────────────────────────────────────────
def parse_dep_sheet(ws: Worksheet, *, fallback_date: Optional[date] = None) -> list[dict]:
    header_row = find_header_row(ws, must_contain=("principal",))
    if header_row is None:
        header_row = find_header_row(ws, must_contain=("interest rate",))
    if header_row is None:
        return []

    headers = header_index_map(ws, header_row)
    col_sub = find_col(headers, "sub portfolio name", "sub-fund")
    col_trade = find_col(headers, "trade date")
    col_val = find_col(headers, "valuation date")
    col_close = find_col(headers, "close date")
    col_principal = find_col(headers, "principal", "номинал")
    col_rate = find_col(headers, "interest rate", "ставка")
    col_acc = find_col(headers, "accrued interest")
    col_mv = find_col(headers, "market value")

    if not col_sub or not col_principal:
        return []

    out: list[dict] = []
    for r in iter_data_rows(ws, header_row + 1):
        sub = normalize_subfund_name(ws.cell(r, col_sub).value)
        if not sub:
            continue
        principal = cell_float(ws.cell(r, col_principal).value) or 0.0
        if abs(principal) < 0.01:
            continue
        out.append({
            "cdu_name": sub,
            "trade_date": cell_date(ws.cell(r, col_trade).value) if col_trade else fallback_date,
            "valuation_date": cell_date(ws.cell(r, col_val).value) if col_val else fallback_date,
            "close_date": cell_date(ws.cell(r, col_close).value) if col_close else None,
            "principal": principal,
            "interest_rate_pct": cell_float(ws.cell(r, col_rate).value) if col_rate else None,
            "accrued_interest": cell_float(ws.cell(r, col_acc).value) if col_acc else None,
            "market_value": cell_float(ws.cell(r, col_mv).value) if col_mv else None,
            "src_row": r,
        })
    return out


# ──────────────────────────────────────────────────────────────────────────
# Accounts receivable
# ──────────────────────────────────────────────────────────────────────────
def parse_ar_sheet(ws: Worksheet, *, fallback_date: Optional[date] = None) -> list[dict]:
    header_row = find_header_row(ws, must_contain=("isin",))
    if header_row is None:
        header_row = find_header_row(ws, must_contain=("остаток",))
    if header_row is None:
        return []

    headers = header_index_map(ws, header_row)
    col_du = find_col(headers, "ду", "sub-fund", "sub portfolio name")
    col_name = find_col(headers, "наименование", "description")
    col_isin = find_col(headers, "isin")
    col_ccy = find_col(headers, "валюта", "currency")
    col_record_date = find_col(headers, "дата постановки", "record date")
    col_balance_ccy = find_col(headers, "остаток в валюте", "balance currency")
    col_balance_kzt = find_col(headers, "остаток в тенге", "остаток в kzt", "balance kzt")
    col_due = find_col(headers, "дата завершения", "due date", "ожидаемая дата")

    if not col_isin or (not col_balance_kzt and not col_balance_ccy):
        return []

    out: list[dict] = []
    for r in iter_data_rows(ws, header_row + 1):
        isin = cell_str(ws.cell(r, col_isin).value)
        if not isin or len(isin) < 6:
            continue
        balance_kzt = cell_float(ws.cell(r, col_balance_kzt).value) if col_balance_kzt else 0.0
        balance_ccy = cell_float(ws.cell(r, col_balance_ccy).value) if col_balance_ccy else None
        if (balance_kzt is None or abs(balance_kzt) < 0.01) and \
           (balance_ccy is None or abs(balance_ccy or 0) < 0.01):
            continue
        sub = normalize_subfund_name(ws.cell(r, col_du).value) if col_du else None
        out.append({
            "cdu_name": sub,
            "isin": isin,
            "description": cell_str(ws.cell(r, col_name).value) if col_name else None,
            "currency": (cell_str(ws.cell(r, col_ccy).value) or "KZT").upper()[:8] if col_ccy else "KZT",
            "record_date": cell_date(ws.cell(r, col_record_date).value) if col_record_date else fallback_date,
            "balance_currency": balance_ccy,
            "balance_kzt": balance_kzt or 0.0,
            "due_date": cell_date(ws.cell(r, col_due).value) if col_due else None,
            "src_row": r,
        })
    return out


# ──────────────────────────────────────────────────────────────────────────
# Report sheet — извлечь Report!B2 (дату) и итоговые суммы по ЧДУ
# ──────────────────────────────────────────────────────────────────────────
def get_report_date(ws: Worksheet) -> Optional[date]:
    """Достать отчётную дату из Report!B2 (по соглашению из бизнес-процесса)."""
    if ws is None:
        return None
    return cell_date(ws.cell(2, 2).value)
