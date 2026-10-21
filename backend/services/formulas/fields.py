"""Fields available in user indicators and their values on a date.

Values come from the calculated summary of the date (the same numbers as
«Сводка» and the report): category values of every manager, totals, yields,
durations, the MBM benchmark and the limits in force.  Percentages are given
in percent (12.5 means 12,5 %), amounts in tenge.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

CATS: List[Tuple[str, str]] = [
    ("CASH", "Деньги"),
    ("GOV_BONDS", "ГЦБ"),
    ("REVERSE_REPO", "Обратное РЕПО"),
    ("MFO_BONDS", "МФО"),
    ("AGENCY_BONDS", "Агентские облигации"),
    ("FOREIGN_BONDS", "Иностранные ЦБ"),
    ("DEPOSIT", "Депозиты"),
    ("RECEIVABLES", "Дебиторка"),
]
SECURITIES = ("GOV_BONDS", "MFO_BONDS", "AGENCY_BONDS", "FOREIGN_BONDS")
YIELD_CATS = ("GOV_BONDS", "REVERSE_REPO", "MFO_BONDS", "AGENCY_BONDS", "FOREIGN_BONDS", "DEPOSIT")


@dataclass(frozen=True)
class Field:
    name: str
    group: str
    unit: str        # KZT | PCT | NUMBER
    description: str


def catalog(level: str) -> List[Field]:
    whole = "ЧДУ" if level == "cdu" else "фонда"
    out: List[Field] = []
    for code, label in CATS:
        out.append(Field(label, "Стоимость по категориям", "KZT",
                         f"Стоимость категории «{label}» {'портфеля ЧДУ' if level == 'cdu' else 'по всем ЧДУ'} на дату, ₸"))
    out += [
        Field("Ценные бумаги всего", "Стоимость по категориям", "KZT", "ГЦБ + МФО + Агентские + Иностранные ЦБ, ₸"),
        Field(f"Итого {whole}", "Итоги", "KZT", f"Итого активов {whole} на дату, ₸"),
        Field(f"Итого {whole} вчера", "Итоги", "KZT", f"Итого {whole} на предыдущую рассчитанную дату, ₸"),
        Field("Изменение за день", "Итоги", "KZT", "Итого на дату − итого вчера, ₸"),
    ]
    if level == "cdu":
        out += [
            Field("Итого фонда", "Итоги", "KZT", "Итого по всем ЧДУ и портфелям НБ РК, ₸"),
            Field("Доля ЧДУ в фонде, %", "Итоги", "PCT", "Итого ЧДУ ÷ Итого фонда × 100"),
        ]
    else:
        out.append(Field("Количество ЧДУ", "Итоги", "NUMBER", "Сколько портфелей рассчитано на дату"))
    out += [
        Field(f"Доходность {'портфеля' if level == 'cdu' else 'фонда'}, %", "Доходность и дюрация", "PCT",
              "Средневзвешенная доходность (YTM) по стоимости, без денег и дебиторки"),
        Field(f"Дюрация {'портфеля' if level == 'cdu' else 'фонда'}", "Доходность и дюрация", "NUMBER",
              "Средневзвешенная модифицированная дюрация, лет"),
        Field("Бенчмарк MBM (ModDuration)", "Доходность и дюрация", "NUMBER", "ModDuration индекса MBM на дату"),
        Field("Коридор дюрации: от", "Доходность и дюрация", "NUMBER", "Бенчмарк × нижний множитель (параметр расчёта)"),
        Field("Коридор дюрации: до", "Доходность и дюрация", "NUMBER", "Бенчмарк × верхний множитель (параметр расчёта)"),
    ]
    for code, label in CATS:
        if code in YIELD_CATS:
            out.append(Field(f"Доходность: {label}, %", "Доходность и дюрация по категориям", "PCT",
                             f"Средневзвешенная доходность категории «{label}»"))
            out.append(Field(f"Дюрация: {label}", "Доходность и дюрация по категориям", "NUMBER",
                             f"Средневзвешенная дюрация категории «{label}»"))
    if level == "cdu":
        for code, label in CATS:
            out.append(Field(f"Лимит макс: {label}, %", "Лимиты (справочник)", "PCT",
                             f"Максимальная доля «{label}» по лимитам, действующим на дату"))
            out.append(Field(f"Лимит мин: {label}, %", "Лимиты (справочник)", "PCT",
                             f"Минимальная доля «{label}» по лимитам, действующим на дату"))
    return out


def field_names(level: str) -> List[str]:
    return [f.name for f in catalog(level)]


# ───────────────────────────── values ─────────────────────────────

def _summaries(db: Session, as_of: date):
    from models.db_models import CDU, PortfolioPosition, PortfolioSummary
    sums = db.execute(select(PortfolioSummary).where(PortfolioSummary.summary_date == as_of)).scalars().all()
    rows = db.execute(select(PortfolioPosition).where(
        PortfolioPosition.position_date == as_of, PortfolioPosition.instrument_code.is_(None),
    )).scalars().all()
    cdus = {c.id: c for c in db.query(CDU).all()}
    by_cdu: Dict[int, Dict[str, object]] = {}
    for r in rows:
        by_cdu.setdefault(r.cdu_id, {})[r.instrument_category] = r
    return sums, by_cdu, cdus


def _pct(v: Optional[float]) -> Optional[float]:
    return None if v is None else v * 100.0


def contexts(db: Session, as_of: date) -> Tuple[Dict[int, Dict[str, Optional[float]]], Dict[str, Optional[float]], Dict[int, str]]:
    """(per-manager values, fund values, manager names) for the calculated date."""
    from services.calculator.constants import duration_band
    from services.calculator.portfolio_calculator import _load_limit_specs
    from services.formulas import params

    params.refresh(db, force=True)
    sums, by_cdu, cdus = _summaries(db, as_of)
    fund_total = sum(s.total_mv_current or 0.0 for s in sums)
    names: Dict[int, str] = {}
    per: Dict[int, Dict[str, Optional[float]]] = {}
    fund: Dict[str, Optional[float]] = {}
    w_ytm = w_dur = 0.0
    sum_ytm = sum_dur = 0.0
    cat_acc: Dict[str, List[Tuple[float, Optional[float], Optional[float]]]] = {}
    benchmark = None
    for s in sums:
        cdu = cdus.get(s.cdu_id)
        names[s.cdu_id] = (cdu.short_name or cdu.name) if cdu else str(s.cdu_id)
        rows = by_cdu.get(s.cdu_id, {})
        ctx: Dict[str, Optional[float]] = {}
        for code, label in CATS:
            r = rows.get(code)
            v = float(r.market_value_current or 0.0) if r is not None else 0.0
            ctx[label] = v
            fund[label] = (fund.get(label) or 0.0) + v
            if code in YIELD_CATS:
                ytm = _pct(r.ytm) if r is not None and r.ytm is not None else None
                dur = r.duration if r is not None else None
                ctx[f"Доходность: {label}, %"] = ytm
                ctx[f"Дюрация: {label}"] = dur
                cat_acc.setdefault(label, []).append((v, ytm, dur))
        ctx["Ценные бумаги всего"] = sum(ctx[l] or 0.0 for c, l in CATS if c in SECURITIES)
        ctx["Итого ЧДУ"] = s.total_mv_current
        ctx["Итого ЧДУ вчера"] = s.total_mv_prev
        ctx["Изменение за день"] = s.total_daily_change
        ctx["Итого фонда"] = fund_total
        ctx["Доля ЧДУ в фонде, %"] = (s.total_mv_current / fund_total * 100.0) if fund_total else None
        ctx["Доходность портфеля, %"] = _pct(s.ytm_weighted)
        ctx["Дюрация портфеля"] = s.duration_weighted
        ctx["Бенчмарк MBM (ModDuration)"] = s.benchmark_duration
        lo, hi = duration_band(s.benchmark_duration)
        ctx["Коридор дюрации: от"], ctx["Коридор дюрации: до"] = lo, hi
        benchmark = benchmark if benchmark is not None else s.benchmark_duration
        specs = _load_limit_specs(db, s.cdu_id, as_of)
        for code, label in CATS:
            spec = specs.get(code)
            ctx[f"Лимит макс: {label}, %"] = _pct(spec.max_pct) if spec else None
            ctx[f"Лимит мин: {label}, %"] = _pct(spec.min_pct) if spec else None
        per[s.cdu_id] = ctx
        total = s.total_mv_current or 0.0
        if s.ytm_weighted is not None and total:
            w_ytm += total
            sum_ytm += _pct(s.ytm_weighted) * total
        if s.duration_weighted is not None and total:
            w_dur += total
            sum_dur += s.duration_weighted * total
        fund["Итого фонда вчера"] = (fund.get("Итого фонда вчера") or 0.0) + (s.total_mv_prev or 0.0)

    if sums:
        fund["Ценные бумаги всего"] = sum(fund.get(l) or 0.0 for c, l in CATS if c in SECURITIES)
        fund["Итого фонда"] = fund_total
        fund["Изменение за день"] = fund_total - (fund.get("Итого фонда вчера") or 0.0)
        fund["Количество ЧДУ"] = float(len(sums))
        fund["Доходность фонда, %"] = sum_ytm / w_ytm if w_ytm else None
        fund["Дюрация фонда"] = sum_dur / w_dur if w_dur else None
        fund["Бенчмарк MBM (ModDuration)"] = benchmark
        lo, hi = duration_band(benchmark)
        fund["Коридор дюрации: от"], fund["Коридор дюрации: до"] = lo, hi
        for label, items in cat_acc.items():
            wy = sum(v for v, y, _ in items if y is not None and v)
            wd = sum(v for v, _, d in items if d is not None and v)
            fund[f"Доходность: {label}, %"] = (sum(v * y for v, y, _ in items if y is not None and v) / wy) if wy else None
            fund[f"Дюрация: {label}"] = (sum(v * d for v, _, d in items if d is not None and v) / wd) if wd else None
    return per, fund, names
