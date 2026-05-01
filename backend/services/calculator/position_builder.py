"""Build the position book from raw trade rows.

REPO model
----------
Каждая EBRP/REPO заявка состоит из трёх строк, относящихся к одной «Заявке №»:
  - "Разм"  (REPO_HEADER) — анкер заявки, описывает условия;
  - "К"     (REPO_BUY)    — нога принятия бумаг (открытие позиции на trading_date);
  - "П"     (REPO_SELL)   — нога возврата       (закрытие на settlement_date_П).

Позиция считается **открытой**, если report_date < settlement_date "П"-ноги
(или если "П"-нога вовсе не зафиксирована).

Bonds (BUY/SELL): чистый номинал = Σ(BUY) − Σ(SELL) по коду инструмента.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional


@dataclass
class PositionAggregate:
    cdu_id: int
    instrument_code: Optional[str]
    instrument_category: str
    instrument_name: Optional[str] = None

    # для бумаг
    nominal_volume: float = 0.0
    last_price: Optional[float] = None
    accrued_interest: float = 0.0

    # для РЕПО
    repo_open_sum: float = 0.0           # Σ Сумма РЕПО ещё не закрытых
    repo_buyback_sum: float = 0.0        # Σ Сумма выкупа РЕПО ещё не закрытых
    repo_term_days_avg: Optional[float] = None
    repo_rate_pct_avg: Optional[float] = None
    open_orders: List[str] = field(default_factory=list)

    # YTM weighted-helpers
    ytm: Optional[float] = None
    duration: Optional[float] = None

    # raw rows that contributed
    contributing_rows: int = 0


def _get(row: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def build_positions(
    rows: Iterable[Any],
    cdu_id: int,
    report_date: date,
) -> List[PositionAggregate]:
    """Build aggregated portfolio positions for one CDU on `report_date`.

    Each `row` may be either a SQLAlchemy `RawTrade` instance or a plain dict
    with the same field names used by the parser.
    """
    rows_list = list(rows)

    # ── 1. REPO matching by order_number ──
    # «Разм» (REPO_HEADER) — анкер. «П» (REPO_SELL) — определяет дату закрытия.
    # Позиция открыта, пока report_date < settlement_date_П.
    repo_orders: Dict[str, Dict[str, Any]] = {}
    repo_closed: set[str] = set()

    for r in rows_list:
        op = _get(r, "operation_type")
        order = _get(r, "order_number")
        if not order:
            continue
        order_key = str(order)
        if op == "REPO_HEADER":
            repo_orders.setdefault(order_key, {})
            repo_orders[order_key].update({
                "instrument_code": _get(r, "instrument_code"),
                "instrument_category": _get(r, "instrument_category", "REVERSE_REPO"),
                "repo_sum": float(_get(r, "repo_sum") or 0),
                "repo_buyback_sum": float(_get(r, "repo_buyback_sum") or 0),
                "repo_term_days": _get(r, "repo_term_days"),
                "repo_rate_pct": _get(r, "repo_rate_pct"),
                "yield_pct": _get(r, "yield_pct"),
                "open_date": _get(r, "trading_date") or _get(r, "trade_date"),
            })
        elif op == "REPO_BUY":
            repo_orders.setdefault(order_key, {})
            repo_orders[order_key].update({
                "instrument_code": _get(r, "instrument_code"),
                "instrument_category": _get(r, "instrument_category", "REVERSE_REPO"),
                "open_date": _get(r, "settlement_date") or _get(r, "trading_date"),
                "repo_sum": float(_get(r, "repo_sum") or 0)
                            or repo_orders[order_key].get("repo_sum", 0.0),
                "yield_pct": _get(r, "yield_pct") or repo_orders[order_key].get("yield_pct"),
            })
        elif op == "REPO_SELL":
            repo_orders.setdefault(order_key, {})
            close_date = _get(r, "settlement_date")
            repo_orders[order_key]["close_date"] = close_date
            repo_orders[order_key].setdefault(
                "repo_buyback_sum",
                float(_get(r, "repo_buyback_sum") or 0)
                or float(_get(r, "volume") or 0),
            )
            if close_date and close_date <= report_date:
                repo_closed.add(order_key)

    # ── 2. Build aggregates ──
    positions: Dict[tuple, PositionAggregate] = {}

    def _agg(cat: str, code: Optional[str]) -> PositionAggregate:
        key = (cat, code or "_total_")
        if key not in positions:
            positions[key] = PositionAggregate(
                cdu_id=cdu_id,
                instrument_code=code,
                instrument_category=cat,
            )
        return positions[key]

    # 2a — Open REPO positions (close_date > report_date or absent)
    repo_term_acc = 0.0
    repo_term_w = 0.0
    repo_rate_acc = 0.0
    repo_rate_w = 0.0
    for order, ro in repo_orders.items():
        if order in repo_closed:
            continue
        # требуем хотя бы одну из ног (REPO_BUY): если есть только Разм без К — нет открытой позиции
        if "repo_sum" not in ro or not ro["repo_sum"]:
            continue
        a = _agg(ro.get("instrument_category") or "REVERSE_REPO", ro.get("instrument_code"))
        a.repo_open_sum += ro["repo_sum"]
        a.repo_buyback_sum += float(ro.get("repo_buyback_sum") or 0)
        a.contributing_rows += 1
        a.open_orders.append(str(order))
        # weighted helpers
        days = ro.get("repo_term_days")
        sum_w = ro["repo_sum"]
        if days is not None and sum_w:
            repo_term_acc += float(days) * sum_w
            repo_term_w += sum_w
        rate = ro.get("repo_rate_pct") or ro.get("yield_pct")
        if rate is not None and sum_w:
            repo_rate_acc += float(rate) * sum_w
            repo_rate_w += sum_w

    # 2b — Securities BUY/SELL (накопление чистого номинала)
    last_prices: Dict[str, float] = {}
    last_yields: Dict[str, float] = {}
    last_aci: Dict[str, float] = {}
    for r in rows_list:
        op = _get(r, "operation_type")
        if op not in ("BUY", "SELL"):
            continue
        cat = _get(r, "instrument_category", "OTHER")
        if cat == "REVERSE_REPO":
            continue
        code = _get(r, "instrument_code")
        a = _agg(cat, code)
        nominal = float(_get(r, "nominal_volume") or 0)
        if op == "SELL":
            nominal = -nominal
        a.nominal_volume += nominal
        a.contributing_rows += 1
        # последняя цена / YTM / НКД
        price = _get(r, "price")
        if price is not None and code:
            last_prices[code] = float(price)
        ytm = _get(r, "yield_pct")
        if ytm is not None and code:
            last_yields[code] = float(ytm)
        aci = _get(r, "accrued_interest_volume")
        if aci is not None and code:
            last_aci[code] = float(aci)

    # 2c — apply последние цены / YTM
    for (cat, code), a in positions.items():
        if code and code in last_prices:
            a.last_price = last_prices[code]
        if code and code in last_yields:
            a.ytm = last_yields[code]
        if code and code in last_aci:
            a.accrued_interest = last_aci[code]

    # 2d — взвешенные параметры РЕПО
    for (cat, code), a in positions.items():
        if cat == "REVERSE_REPO":
            if repo_term_w:
                a.repo_term_days_avg = repo_term_acc / repo_term_w
            if repo_rate_w:
                a.repo_rate_pct_avg = repo_rate_acc / repo_rate_w
            if a.repo_term_days_avg:
                a.duration = a.repo_term_days_avg / 365.0
            if a.ytm is None:
                a.ytm = a.repo_rate_pct_avg

    return [a for a in positions.values() if (
        a.repo_open_sum != 0 or abs(a.nominal_volume) > 1e-6
    )]
