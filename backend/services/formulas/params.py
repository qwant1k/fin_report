"""Calculation parameters editable in «Формулы → Параметры расчёта».

The formulas of the fund (accrued interest, value of a bond, MDURATION, REPO,
deposits, limits) reproduce the Risk Report and are not editable; their
numeric parameters are.  Every parameter has a definition here (label, unit,
bounds, default, where it is used); a value changed by a user is stored in
``calc_parameters`` with the history in ``calc_parameter_changes``.

Values are cached in-process and refreshed from the database at the start of
every calculation (``refresh(db)``), so a change applies to the next recalc.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ParamDef:
    code: str
    label: str
    group: str
    unit: str                      # "×", "₸", "%", "дн.", "" or "choice"
    default: Any
    description: str
    used_in: str
    kind: str = "float"            # float | int | choice
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    formula: Optional[str] = None  # system formula code that uses it


PARAMS: List[ParamDef] = [
    ParamDef("duration_lower_mult", "Нижняя граница коридора дюрации", "Дюрация и бенчмарк", "×", 0.8,
             "Нижняя граница = ModDuration индекса MBM × этот множитель (в Risk Report «−0,2»).",
             "Сводка: статус дюрации портфеля, отчёт", min=0.1, max=1.0, formula="DURATION_CORRIDOR"),
    ParamDef("duration_upper_mult", "Верхняя граница коридора дюрации", "Дюрация и бенчмарк", "×", 1.5,
             "Верхняя граница = ModDuration индекса MBM × этот множитель (в Risk Report «+0,5»).",
             "Сводка: статус дюрации портфеля, отчёт", min=1.0, max=5.0, formula="DURATION_CORRIDOR"),
    ParamDef("price_priority", "Какую цену KASE брать первой", "Цены и оценка", "choice", "market",
             "Если на дату есть и рыночная цена, и цена по риск-параметрам, используется выбранная.",
             "Оценка облигаций", kind="choice",
             choices=(("market", "Рыночную, затем по риск-параметрам"),
                      ("risk_parameters", "По риск-параметрам, затем рыночную")),
             formula="BOND_VALUE"),
    ParamDef("max_stale_price_days", "Сколько дней можно брать старую цену", "Цены и оценка", "дн.", 14,
             "Если цены на дату нет, берётся последняя цена не старше этого числа дней; иначе — цена Risk Report.",
             "Оценка облигаций", kind="int", min=0, max=90, formula="BOND_VALUE"),
    ParamDef("repo_default_base", "База дней РЕПО (если не указана)", "РЕПО и депозиты", "дн.", 366,
             "Число дней в году для начисления вознаграждения РЕПО, если в сделке база не указана.",
             "Стоимость РЕПО", kind="int", min=360, max=366, formula="REPO_VALUE"),
    ParamDef("deposit_default_base", "База дней депозита (если не указана)", "РЕПО и депозиты", "дн.", 360,
             "Число дней в году для начисления процентов по депозиту, если в сделке база не указана (НБ РК — 360).",
             "Стоимость депозита", kind="int", min=360, max=366, formula="DEPOSIT_VALUE"),
    ParamDef("coupon_settlement", "Как отражать купон в дату выплаты", "Купоны и погашения", "choice", "receivable",
             "Через дебиторку: в плановую дату купон становится дебиторской задолженностью, деньги поступают, "
             "когда пользователь укажет фактическую дату поступления. Сразу деньгами: купон ГЦБ зачисляется "
             "на счёт в плановую дату (агентские, МФО и иностранные — всегда через дебиторку).",
             "Автоматические события «Купон»", kind="choice",
             choices=(("receivable", "Через дебиторку, деньги — по факту поступления"),
                      ("cash", "Купон ГЦБ сразу деньгами в дату выплаты"))),
    ParamDef("float_fix_lag_days", "Фиксация плавающей ставки, дней до начала периода", "Купоны и погашения", "дн.", 0,
             "Купон с плавающей ставкой = индикатор TONIA Compounded (TCR) + маржа выпуска. Значение индикатора берётся "
             "на дату начала купонного периода минус это число дней (если на дату значения нет — последнее до неё).",
             "Купоны и НКД облигаций с плавающей ставкой", kind="int", min=0, max=30),
    ParamDef("recon_line_tolerance", "Допуск сверки с ЧДУ по строке", "Сверка", "₸", 1.0,
             "Разница стоимости, НКД, суммы РЕПО меньше допуска считается совпадением.",
             "Сверка «Наш расчёт ↔ файл ЧДУ»", min=0.0, max=1000.0),
    ParamDef("recon_price_tolerance", "Допуск сверки цены", "Сверка", "%", 0.00005,
             "Разница чистой цены (в % от номинала) меньше допуска считается совпадением.",
             "Сверка «Наш расчёт ↔ файл ЧДУ»", min=0.0, max=1.0),
    ParamDef("nbrk_recon_abs", "Допуск сверки денег НБ РК, ₸", "Сверка", "₸", 1.0,
             "Деньги портфеля НБ РК ↔ остаток счёта в КФГД_ГГГГММДД: допуск в тенге (БП 7.3).",
             "Сверка «Деньги ↔ КФГД_ГГГГММДД»", min=0.0, max=1_000_000.0),
    ParamDef("nbrk_recon_pct", "Допуск сверки денег НБ РК, %", "Сверка", "%", 0.01,
             "Тот же допуск в процентах от остатка; берётся больший из двух.",
             "Сверка «Деньги ↔ КФГД_ГГГГММДД»", min=0.0, max=5.0),
]
_BY_CODE: Dict[str, ParamDef] = {p.code: p for p in PARAMS}

_values: Dict[str, Any] = {}
_loaded_at: float = 0.0
TTL_SECONDS = 5.0


def definition(code: str) -> ParamDef:
    if code not in _BY_CODE:
        raise KeyError(f"Неизвестный параметр {code}")
    return _BY_CODE[code]


def convert(code: str, raw: Any) -> Any:
    """Validate and convert a value typed by a user; ValueError with a readable message."""
    p = definition(code)
    if p.kind == "choice":
        allowed = [c for c, _ in p.choices]
        if str(raw) not in allowed:
            raise ValueError(f"«{p.label}»: выберите одно из значений")
        return str(raw)
    try:
        number = float(str(raw).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError(f"«{p.label}»: нужно число") from None
    if p.min is not None and number < p.min or p.max is not None and number > p.max:
        raise ValueError(f"«{p.label}»: допустимо от {p.min:g} до {p.max:g}")
    return int(round(number)) if p.kind == "int" else number


def refresh(db: Optional[Session], *, force: bool = False) -> None:
    global _values, _loaded_at
    if db is None or (not force and time.monotonic() - _loaded_at < TTL_SECONDS):
        return
    from models.db_models import CalcParameter
    try:
        rows = db.query(CalcParameter).all()
    except Exception:  # noqa: BLE001 — table not created yet in an old database
        return
    values: Dict[str, Any] = {}
    for row in rows:
        if row.code in _BY_CODE:
            try:
                values[row.code] = convert(row.code, row.value_text)
            except ValueError:
                continue
    _values = values
    _loaded_at = time.monotonic()


def get(code: str) -> Any:
    p = definition(code)
    return _values.get(code, p.default)


def reset_cache() -> None:
    global _values, _loaded_at
    _values = {}
    _loaded_at = 0.0


def set_value(db: Session, code: str, raw: Any, *, reason: Optional[str], actor: Optional[str]) -> Any:
    from models.db_models import CalcParameter, CalcParameterChange
    value = convert(code, raw)
    row = db.get(CalcParameter, code)
    old = row.value_text if row is not None else str(definition(code).default)
    text = str(value)
    if row is None:
        row = CalcParameter(code=code, value_text=text, updated_by=actor)
        db.add(row)
    else:
        row.value_text = text
        row.updated_by = actor
    db.add(CalcParameterChange(code=code, old_value=old, new_value=text, reason=reason, changed_by=actor))
    db.flush()
    refresh(db, force=True)
    return value


def listing(db: Session) -> List[dict]:
    from models.db_models import CalcParameter, CalcParameterChange
    refresh(db, force=True)
    stored = {r.code: r for r in db.query(CalcParameter).all()}
    history: Dict[str, List[dict]] = {}
    for ch in db.query(CalcParameterChange).order_by(CalcParameterChange.changed_at.desc(),
                                                     CalcParameterChange.id.desc()).limit(300):
        history.setdefault(ch.code, []).append({
            "old": ch.old_value, "new": ch.new_value, "reason": ch.reason, "by": ch.changed_by,
            "at": ch.changed_at.isoformat() if ch.changed_at else None,
        })
    out = []
    for p in PARAMS:
        row = stored.get(p.code)
        out.append({
            "code": p.code, "label": p.label, "group": p.group, "unit": p.unit, "kind": p.kind,
            "default": p.default, "value": get(p.code), "min": p.min, "max": p.max,
            "choices": [{"value": c, "label": l} for c, l in p.choices],
            "description": p.description, "used_in": p.used_in, "formula": p.formula,
            "is_default": row is None or get(p.code) == p.default,
            "updated_by": row.updated_by if row else None,
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
            "history": history.get(p.code, [])[:10],
        })
    return out
