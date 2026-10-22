"""User indicators: validation, preview on data, values for the summary, alerts."""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from services.formulas import expr, fields

UNITS = {"KZT": "₸", "PCT": "%", "NUMBER": "", "DAYS": "дн."}
LEVELS = {"cdu": "по каждому ЧДУ", "fund": "по фонду в целом"}
ALERT_OPS = {">": "больше", "<": "меньше", ">=": "не меньше", "<=": "не больше"}

TEMPLATES: List[Dict[str, Any]] = [
    {"name": "Доля ГЦБ в портфеле ЧДУ", "level": "cdu", "unit": "PCT",
     "expression": "ДОЛЯ([ГЦБ]; [Итого ЧДУ])",
     "description": "Какую часть портфеля занимают государственные облигации"},
    {"name": "Запас до лимита по ГЦБ", "level": "cdu", "unit": "PCT",
     "expression": "[Лимит макс: ГЦБ, %] - ДОЛЯ([ГЦБ]; [Итого ЧДУ])",
     "description": "Сколько процентных пунктов осталось до максимального лимита",
     "alert_op": "<", "alert_threshold": 1},
    {"name": "Запас до лимита по РЕПО, млн ₸", "level": "cdu", "unit": "NUMBER",
     "expression": "([Лимит макс: Обратное РЕПО, %] / 100 * [Итого ЧДУ] - [Обратное РЕПО]) / 1000000",
     "description": "На сколько миллионов тенге ещё можно открыть РЕПО"},
    {"name": "Отклонение дюрации от бенчмарка", "level": "cdu", "unit": "NUMBER",
     "expression": "[Дюрация портфеля] - [Бенчмарк MBM (ModDuration)]",
     "description": "Положительное — портфель длиннее индекса"},
    {"name": "Доля денег без работы", "level": "cdu", "unit": "PCT",
     "expression": "ДОЛЯ([Деньги]; [Итого ЧДУ])", "alert_op": ">", "alert_threshold": 0.1,
     "description": "Деньги на счёте, которые не вложены"},
    {"name": "Доходность фонда без РЕПО", "level": "fund", "unit": "PCT",
     "expression": ("([Доходность: ГЦБ, %] * [ГЦБ] + [Доходность: МФО, %] * [МФО] + "
                    "[Доходность: Агентские облигации, %] * [Агентские облигации]) / "
                    "([ГЦБ] + [МФО] + [Агентские облигации])"),
     "description": "Средневзвешенная доходность облигаций фонда"},
    {"name": "Изменение фонда за день, млн ₸", "level": "fund", "unit": "NUMBER",
     "expression": "[Изменение за день] / 1000000", "description": "Прирост активов фонда за день"},
]


def validate(expression: str, level: str) -> Dict[str, Any]:
    names = fields.field_names(level)
    try:
        tree = expr.parse(expression, names)
    except expr.FormulaError as e:
        return {"ok": False, "error": e.message, "position": e.position}
    used = expr.fields_used(tree)
    return {"ok": True, "pretty": expr.render(tree), "fields": used}


def _evaluate_rows(tree, level: str, as_of: date, db: Session) -> Dict[str, Any]:
    per, fund, names = fields.contexts(db, as_of)
    note = None
    if not per:
        from models.db_models import PortfolioSummary
        last = db.query(PortfolioSummary.summary_date).filter(PortfolioSummary.summary_date <= as_of).order_by(
            PortfolioSummary.summary_date.desc()).first()
        if last is None:
            return {"rows": [], "note": f"Сводка на {as_of:%d.%m.%Y} не рассчитана — нажмите «Пересчитать» в сводке"}
        note = (f"Сводка на {as_of:%d.%m.%Y} не рассчитана — показаны значения "
                f"на последнюю рассчитанную дату {last[0]:%d.%m.%Y}")
        as_of = last[0]
        per, fund, names = fields.contexts(db, as_of)
    contexts = [(cid, names.get(cid), ctx) for cid, ctx in per.items()] if level == "cdu" else [(None, "Фонд", fund)]
    rows = []
    for cid, name, ctx in contexts:
        try:
            value = expr.evaluate(tree, ctx)
            error = None if value is not None else "нет данных для одного из полей"
        except expr.EvalError as e:
            value, error = None, str(e)
        rows.append({
            "cdu_id": cid, "name": name, "value": value, "error": error,
            "substituted": expr.render(tree, ctx),
            "inputs": {f: ctx.get(f) for f in expr.fields_used(tree)},
        })
    rows.sort(key=lambda r: (r["name"] or ""))
    return {"rows": rows, "note": note, "data_date": as_of.isoformat()}


def preview(db: Session, expression: str, level: str, as_of: date) -> Dict[str, Any]:
    check = validate(expression, level)
    if not check["ok"]:
        return {**check, "rows": []}
    tree = expr.parse(expression, fields.field_names(level))
    return {**check, **_evaluate_rows(tree, level, as_of, db), "date": as_of.isoformat()}


def snapshot(ind) -> Dict[str, Any]:
    return {k: getattr(ind, k) for k in (
        "code", "name", "description", "level", "unit", "expression", "decimals", "show_on_dashboard",
        "alert_op", "alert_threshold", "alert_severity", "status")}


def to_dict(ind) -> Dict[str, Any]:
    v = validate(ind.expression, ind.level)
    return {
        "id": ind.id, **snapshot(ind), "version": ind.version,
        "pretty": v.get("pretty"), "valid": v["ok"], "error": v.get("error"),
        "created_by": ind.created_by, "updated_by": ind.updated_by,
        "updated_at": ind.updated_at.isoformat() if ind.updated_at else None,
    }


def make_code(db: Session, name: str) -> str:
    from models.db_models import CustomIndicator
    base = re.sub(r"[^A-Za-z0-9А-Яа-яЁё]+", "_", name).strip("_").upper()[:40] or "IND"
    code, i = base, 1
    while db.query(CustomIndicator).filter_by(code=code).first():
        i += 1
        code = f"{base}_{i}"
    return code


def values_for_date(db: Session, as_of: date, *, only_dashboard: bool = True) -> Dict[str, Any]:
    """Values of active indicators for «Сводка»: per manager and for the fund."""
    from models.db_models import CustomIndicator
    q = db.query(CustomIndicator).filter(CustomIndicator.status == "ACTIVE")
    if only_dashboard:
        q = q.filter(CustomIndicator.show_on_dashboard.is_(True))
    inds = q.order_by(CustomIndicator.name).all()
    if not inds:
        return {"date": as_of.isoformat(), "indicators": [], "by_cdu": {}, "fund": []}
    per, fund_ctx, names = fields.contexts(db, as_of)
    by_cdu: Dict[int, List[dict]] = {}
    fund_vals: List[dict] = []
    meta = []
    for ind in inds:
        try:
            tree = expr.parse(ind.expression, fields.field_names(ind.level))
        except expr.FormulaError:
            continue
        meta.append({"id": ind.id, "name": ind.name, "unit": ind.unit, "level": ind.level,
                     "decimals": ind.decimals, "description": ind.description})
        targets = per.items() if ind.level == "cdu" else [(None, fund_ctx)]
        for cid, ctx in targets:
            try:
                value = expr.evaluate(tree, ctx)
            except expr.EvalError:
                value = None
            item = {"id": ind.id, "name": ind.name, "unit": ind.unit, "decimals": ind.decimals,
                    "value": value, "alert": _breached(ind, value),
                    "substituted": expr.render(tree, ctx), "formula": expr.render(tree)}
            if cid is None:
                fund_vals.append(item)
            else:
                by_cdu.setdefault(cid, []).append(item)
    return {"date": as_of.isoformat(), "indicators": meta, "by_cdu": by_cdu, "fund": fund_vals}


def _breached(ind, value: Optional[float]) -> bool:
    if value is None or not ind.alert_op or ind.alert_threshold is None:
        return False
    t = ind.alert_threshold
    return {">": value > t, "<": value < t, ">=": value >= t, "<=": value <= t}.get(ind.alert_op, False)


def raise_alerts(db: Session, as_of: date) -> int:
    """Notifications of active indicators with a rule (called after the calculation)."""
    from models.db_models import Alert, CustomIndicator
    from services.alerts import auto_resolve_alerts
    auto_resolve_alerts(db, alert_date=as_of, alert_types=("CUSTOM_INDICATOR",))
    inds = db.query(CustomIndicator).filter(
        CustomIndicator.status == "ACTIVE", CustomIndicator.alert_op.is_not(None),
        CustomIndicator.alert_threshold.is_not(None),
    ).all()
    if not inds:
        return 0
    per, fund_ctx, names = fields.contexts(db, as_of)
    n = 0
    for ind in inds:
        try:
            tree = expr.parse(ind.expression, fields.field_names(ind.level))
        except expr.FormulaError:
            continue
        targets = per.items() if ind.level == "cdu" else [(None, fund_ctx)]
        for cid, ctx in targets:
            try:
                value = expr.evaluate(tree, ctx)
            except expr.EvalError:
                continue
            if not _breached(ind, value):
                continue
            unit = UNITS.get(ind.unit, "")
            who = names.get(cid, "Фонд") if cid else "Фонд"
            db.add(Alert(
                alert_date=as_of, cdu_id=cid, alert_type="CUSTOM_INDICATOR",
                severity=ind.alert_severity or "WARN",
                message=(f"{who}: «{ind.name}» = {expr.fmt_number(value, ind.decimals)}{(' ' + unit) if unit else ''} — "
                         f"{ALERT_OPS.get(ind.alert_op, ind.alert_op)} {expr.fmt_number(ind.alert_threshold, ind.decimals)}"),
                details_json=json.dumps({"indicator_id": ind.id, "value": value,
                                         "threshold": ind.alert_threshold, "op": ind.alert_op}, ensure_ascii=False),
            ))
            n += 1
    return n
