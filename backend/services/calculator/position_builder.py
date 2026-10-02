"""Build the position book from raw trade rows.

REPO model
----------
Каждая EBRP/REPO заявка состоит из трёх строк, относящихся к одной «Заявке №»:
  - "Разм"  (REPO_HEADER) — анкер заявки, описывает условия;
  - "К"/B   (REPO_OPEN)   — нога принятия бумаг (открытие позиции на trading_date);
  - "П"/S   (REPO_CLOSE)  — нога возврата       (закрытие на settlement_date_П).

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
    currency: str = "KZT"

    # для бумаг
    nominal_volume: float = 0.0
    last_price: Optional[float] = None
    accrued_interest: float = 0.0

    # для РЕПО
    repo_open_sum: float = 0.0           # Σ Сумма РЕПО ещё не закрытых
    repo_buyback_sum: float = 0.0        # Σ Сумма выкупа РЕПО ещё не закрытых
    repo_accrued_interest: float = 0.0   # начислено на выбранную отчётную дату
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
    # «Разм»/G (REPO_HEADER) — анкер. REPO_CLOSE определяет дату закрытия.
    # Позиция открыта, пока report_date < settlement_date_П.
    # One order number can contain several independent REPO triplets.  Keep a
    # separate internal occurrence key and match legs to a compatible group.
    repo_orders: Dict[str, Dict[str, Any]] = {}
    groups_by_order: Dict[str, List[tuple[str, Dict[str, Any]]]] = defaultdict(list)
    repo_closed: set[str] = set()

    def _new_repo_group(order: str) -> tuple[str, Dict[str, Any]]:
        key = f"{order}#{len(groups_by_order[order]) + 1}"
        group: Dict[str, Any] = {"display_order": order}
        repo_orders[key] = group
        groups_by_order[order].append((key, group))
        return key, group

    def _repo_group(order: str, op: str, row: Any) -> tuple[str, Dict[str, Any]]:
        if op == "REPO_HEADER":
            return _new_repo_group(order)
        candidates = []
        for index, (key, group) in enumerate(groups_by_order[order]):
            if op == "REPO_OPEN" and group.get("_has_open"):
                continue
            if op == "REPO_CLOSE" and group.get("_has_close"):
                continue
            score = index
            if op == "REPO_CLOSE" and group.get("_has_open"):
                score += 100
            for field in ("instrument_code", "repo_sum", "repo_buyback_sum", "repo_term_days"):
                left, right = group.get(field), _get(row, field)
                if left not in (None, "", 0) and right not in (None, "", 0):
                    score += 10 if str(left) == str(right) else -100
            candidates.append((score, key, group))
        if not candidates:
            return _new_repo_group(order)
        _, key, group = max(candidates, key=lambda item: item[0])
        return key, group

    for r in rows_list:
        op = _get(r, "operation_type")
        if op not in ("REPO_HEADER", "REPO_OPEN", "REPO_CLOSE"):
            continue
        order = _get(r, "order_number")
        if not order:
            continue
        order_key, repo_group = _repo_group(str(order), op, r)
        if op == "REPO_HEADER":
            repo_group.update({
                "instrument_code": _get(r, "instrument_code"),
                "instrument_category": _get(r, "instrument_category", "REVERSE_REPO"),
                "repo_sum": float(_get(r, "repo_sum") or 0),
                "repo_buyback_sum": float(_get(r, "repo_buyback_sum") or 0),
                "repo_term_days": _get(r, "repo_term_days"),
                "repo_rate_pct": _get(r, "repo_rate_pct"),
                "yield_pct": _get(r, "yield_pct"),
                "open_date": _get(r, "trading_date") or _get(r, "trade_date"),
                "_has_header": True,
            })
        elif op == "REPO_OPEN":
            repo_group.update({
                "instrument_code": _get(r, "instrument_code"),
                "instrument_category": _get(r, "instrument_category", "REVERSE_REPO"),
                "open_date": _get(r, "settlement_date") or _get(r, "trading_date"),
                "repo_sum": float(_get(r, "repo_sum") or 0)
                            or repo_group.get("repo_sum", 0.0),
                "yield_pct": _get(r, "yield_pct") or repo_group.get("yield_pct"),
                "repo_rate_pct": _get(r, "repo_rate_pct") or repo_group.get("repo_rate_pct"),
                "repo_term_days": _get(r, "repo_term_days") or repo_group.get("repo_term_days"),
                "repo_buyback_sum": float(_get(r, "repo_buyback_sum") or 0)
                                    or repo_group.get("repo_buyback_sum", 0.0),
                "_has_open": True,
            })
        elif op == "REPO_CLOSE":
            close_date = _get(r, "settlement_date")
            repo_group["close_date"] = close_date
            repo_group["_has_close"] = True
            close_value = (
                float(_get(r, "repo_buyback_sum") or 0)
                or float(_get(r, "volume") or 0)
            )
            if close_value:
                repo_group["repo_buyback_sum"] = close_value
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
    repo_term_acc: Dict[tuple, float] = defaultdict(float)
    repo_term_w: Dict[tuple, float] = defaultdict(float)
    repo_rate_acc: Dict[tuple, float] = defaultdict(float)
    repo_rate_w: Dict[tuple, float] = defaultdict(float)
    for order, ro in repo_orders.items():
        if order in repo_closed:
            continue
        open_date = ro.get("open_date")
        if open_date and open_date > report_date:
            continue
        # требуем хотя бы одну из ног (REPO_OPEN): если есть только заголовок без открытия — нет позиции
        if "repo_sum" not in ro or not ro["repo_sum"]:
            continue
        a = _agg(ro.get("instrument_category") or "REVERSE_REPO", ro.get("instrument_code"))
        aggregate_key = (a.instrument_category, a.instrument_code or "_total_")
        a.repo_open_sum += ro["repo_sum"]
        a.repo_buyback_sum += float(ro.get("repo_buyback_sum") or 0)
        elapsed_days = max((report_date - open_date).days, 0) if open_date else 0
        term_days = ro.get("repo_term_days")
        buyback_sum = float(ro.get("repo_buyback_sum") or 0)
        if buyback_sum > ro["repo_sum"] and term_days:
            elapsed_days = min(elapsed_days, int(term_days))
            accrued = (buyback_sum - ro["repo_sum"]) * elapsed_days / int(term_days)
        else:
            rate = float(ro.get("repo_rate_pct") or ro.get("yield_pct") or 0.0)
            # Compatibility with rows imported before percentage
            # normalisation was introduced.
            if abs(rate) > 1:
                rate /= 100.0
            accrued = ro["repo_sum"] * rate * elapsed_days / 365.0
        a.repo_accrued_interest += accrued
        a.contributing_rows += 1
        a.open_orders.append(str(ro.get("display_order") or order))
        # weighted helpers
        days = ro.get("repo_term_days")
        sum_w = ro["repo_sum"]
        if days is not None and sum_w:
            repo_term_acc[aggregate_key] += float(days) * sum_w
            repo_term_w[aggregate_key] += sum_w
        rate = ro.get("repo_rate_pct") or ro.get("yield_pct")
        if rate is not None and sum_w:
            repo_rate_acc[aggregate_key] += float(rate) * sum_w
            repo_rate_w[aggregate_key] += sum_w

    # 2b — Securities BUY/SELL (накопление чистого номинала)
    last_prices: Dict[str, float] = {}
    last_yields: Dict[str, float] = {}
    last_aci: Dict[str, float] = {}
    last_currencies: Dict[str, str] = {}
    for r in rows_list:
        op = _get(r, "operation_type")
        if op not in ("BUY", "SELL"):
            continue
        effective_date = _get(r, "settlement_date") or _get(r, "trade_date")
        if effective_date and effective_date > report_date:
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
        currency = _get(r, "currency") or _get(r, "currency_code")
        if currency and code:
            last_currencies[code] = str(currency).strip().upper()

    # 2c — apply последние цены / YTM
    for (cat, code), a in positions.items():
        if code and code in last_prices:
            a.last_price = last_prices[code]
        if code and code in last_yields:
            a.ytm = last_yields[code]
        if code and code in last_aci:
            a.accrued_interest = last_aci[code]
        if code and code in last_currencies:
            a.currency = last_currencies[code]

    # 2d — взвешенные параметры РЕПО
    for (cat, code), a in positions.items():
        if cat == "REVERSE_REPO":
            aggregate_key = (cat, code)
            if repo_term_w[aggregate_key]:
                a.repo_term_days_avg = repo_term_acc[aggregate_key] / repo_term_w[aggregate_key]
            if repo_rate_w[aggregate_key]:
                a.repo_rate_pct_avg = repo_rate_acc[aggregate_key] / repo_rate_w[aggregate_key]
            if a.repo_term_days_avg:
                a.duration = a.repo_term_days_avg / 365.0
            if a.ytm is None:
                a.ytm = a.repo_rate_pct_avg

    return [a for a in positions.values() if (
        a.repo_open_sum != 0 or abs(a.nominal_volume) > 1e-6
    )]
