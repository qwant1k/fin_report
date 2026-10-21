"""«Как считается» — the formulas of the fund with live examples on real data.

The formulas themselves are fixed (they reproduce the Risk Report workbook);
each card explains the formula in plain words, shows which parameters can be
changed, and recalculates an example step by step on the portfolio of a
chosen manager and date, next to the value the system actually uses.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from services.formulas.expr import fmt_number as fn

BASIS_LABEL = {4: "30/360", 1: "фактические дни (act/act)", 2: "act/360", 3: "act/365", 30365: "30/365"}

F = lambda label: {"t": "field", "v": label}          # noqa: E731
O = lambda op: {"t": "op", "v": op}                    # noqa: E731
N = lambda num: {"t": "num", "v": num}                 # noqa: E731
P = lambda label, code: {"t": "param", "v": label, "code": code}   # noqa: E731

SYSTEM: List[Dict[str, Any]] = [
    {"code": "BOND_VALUE", "group": "Ценные бумаги", "title": "Стоимость облигации",
     "tokens": [F("Номинал"), O("×"), F("Чистая цена, %"), O("÷"), N("100"), O("+"), F("НКД"),
                O("×"), F("Курс валюты")],
     "plain": "Номинал позиции умножается на чистую цену в процентах, к результату прибавляется накопленный "
              "купонный доход. Для бумаг в долларах результат переводится в тенге по курсу на дату.",
     "where": "Сводка, позиции, отчёт; категории ГЦБ, МФО, Агентские, Иностранные ЦБ",
     "source": "Risk Report, листы ГЦБ/МФО: «Суммарно-текущая рыночная стоимость»",
     "price_rule": "Цена: KASE на дату (порядок — параметр), иначе последняя цена не старше N дней, "
                   "иначе цена Risk Report, иначе цена покупки (для дисконтных — амортизация).",
     "params": ["price_priority", "max_stale_price_days"]},
    {"code": "ACCRUED", "group": "Ценные бумаги", "title": "НКД — накопленный купонный доход",
     "tokens": [F("Номинал"), O("×"), F("Ставка купона"), O("×"), F("Дней с начала купонного периода"),
                O("÷"), F("Дней в году по базису")],
     "plain": "Купон «копится» каждый день с последней выплаты. Ставка берётся из графика купонов "
              "(для плавающего купона — ставка текущего периода), дни считаются по базису выпуска.",
     "where": "Стоимость облигации, сверка с ЧДУ",
     "source": "Справочник ЦБ → график купонных выплат (KASE), базис выпуска", "params": []},
    {"code": "MDURATION", "group": "Ценные бумаги", "title": "Модифицированная дюрация",
     "tokens": [{"t": "fn", "v": "МДЛИТ"}, O("("), F("Дата"), O(";"), F("Погашение"), O(";"), F("Купон"),
                O(";"), F("Доходность"), O(";"), F("Выплат в год"), O(";"), F("Базис"), O(")")],
     "plain": "Средний срок до получения денег по бумаге, с поправкой на доходность — как функция МДЛИТ "
              "(MDURATION) в Excel. Чем больше дюрация, тем сильнее цена реагирует на изменение ставок.",
     "where": "Дюрация категорий и портфеля, сравнение с бенчмарком",
     "source": "Risk Report: МДЛИТ по каждой бумаге; при графике купонов — по фактическим будущим выплатам",
     "params": []},
    {"code": "REPO_VALUE", "group": "РЕПО и депозиты", "title": "Стоимость обратного РЕПО",
     "tokens": [F("Сумма открытия"), O("+"), O("("), F("Сумма закрытия"), O("−"), F("Сумма открытия"), O(")"),
                O("×"), F("Дней прошло"), O("÷"), F("Срок сделки, дней")],
     "plain": "Вознаграждение по РЕПО начисляется равномерно каждый день от открытия до закрытия. "
              "Если сумма закрытия неизвестна — по ставке: сумма × ставка × дней ÷ база.",
     "where": "Категория «Обратное РЕПО»", "source": "Risk Report, лист РЕПО", "params": ["repo_default_base"]},
    {"code": "DEPOSIT_VALUE", "group": "РЕПО и депозиты", "title": "Стоимость депозита",
     "tokens": [F("Сумма депозита"), O("+"), F("Сумма депозита"), O("×"), F("Ставка"), O("×"),
                F("Дней прошло"), O("÷"), P("База дней", "deposit_default_base")],
     "plain": "Проценты по депозиту начисляются ежедневно на сумму размещения.",
     "where": "Категория «Депозиты»", "source": "Файлы НБ РК КФГД_ГГГГММДД, Risk Report",
     "params": ["deposit_default_base"]},
    {"code": "CASH", "group": "Деньги", "title": "Остаток денег",
     "tokens": [F("Входящий остаток"), O("+"), F("Поступления"), O("−"), F("Списания")],
     "plain": "Берётся последний срез денег (Risk Report), к нему прибавляются все согласованные движения после "
              "него: расчёты по сделкам, купоны, ручные операции.",
     "where": "Категория «Деньги»", "source": "Risk Report, Trade Report, выписки, ручные операции", "params": []},
    {"code": "CATEGORY_SHARE", "group": "Портфель и лимиты", "title": "Доля категории и проверка лимита",
     "tokens": [F("Стоимость категории"), O("÷"), F("Итого ЧДУ"), O("×"), N("100"),
                {"t": "text", "v": "сравнивается с"}, F("Лимит мин"), {"t": "text", "v": "…"}, F("Лимит макс")],
     "plain": "Доля категории в портфеле ЧДУ сравнивается с лимитами справочника, действующими на дату. "
              "Выше жёсткого лимита — нарушение, выше мягкого — предупреждение.",
     "where": "Сводка: колонки «% портф.», Hard, Soft; алерты", "source": "Справочник лимитов ЧДУ", "params": []},
    {"code": "PORTFOLIO_YTM", "group": "Портфель и лимиты", "title": "Доходность и дюрация портфеля",
     "tokens": [{"t": "fn", "v": "Σ"}, O("("), F("Доходность категории"), O("×"), F("Стоимость категории"), O(")"),
                O("÷"), {"t": "fn", "v": "Σ"}, F("Стоимость категории")],
     "plain": "Средневзвешенное по стоимости значение по категориям с доходностью (ЦБ, РЕПО, депозиты); "
              "деньги и дебиторка не участвуют. Так же считается дюрация портфеля.",
     "where": "Сводка: строка Total, бенчмарк", "source": "Risk Report, Report!G14, H14", "params": []},
    {"code": "DURATION_CORRIDOR", "group": "Портфель и лимиты", "title": "Коридор дюрации относительно бенчмарка",
     "tokens": [F("Бенчмарк MBM"), O("×"), P("нижний множитель", "duration_lower_mult"), {"t": "text", "v": "≤"},
                F("Дюрация портфеля"), {"t": "text", "v": "≤"}, F("Бенчмарк MBM"), O("×"),
                P("верхний множитель", "duration_upper_mult")],
     "plain": "Дюрация портфеля должна быть внутри коридора вокруг ModDuration индекса MBM на дату.",
     "where": "Сводка: «Duration портфеля / benchmark MBM / диапазон»", "source": "Risk Report, Report!E18/F18",
     "params": ["duration_lower_mult", "duration_upper_mult"]},
    {"code": "FUND_SHARE", "group": "Портфель и лимиты", "title": "Доля ЧДУ в фонде",
     "tokens": [F("Итого ЧДУ"), O("÷"), F("Итого фонда"), O("×"), N("100")],
     "plain": "Какую часть активов фонда держит управляющий.", "where": "Сводка: «Доля в Фонде»",
     "source": "Risk Report, Report", "params": []},
]
_BY_CODE = {s["code"]: s for s in SYSTEM}


def listing() -> List[Dict[str, Any]]:
    from services.formulas import params
    out = []
    for s in SYSTEM:
        out.append({**s, "param_values": [
            {"code": c, "label": params.definition(c).label, "value": params.get(c), "unit": params.definition(c).unit}
            for c in s["params"]]})
    return out


# ───────────────────────────── examples ─────────────────────────────

def _inp(label: str, value: Any, unit: str = "", source: Optional[str] = None) -> Dict[str, Any]:
    return {"label": label, "value": value, "unit": unit, "source": source}


def example(db: Session, code: str, cdu_id: int, as_of: date, item: Optional[str] = None) -> Dict[str, Any]:
    if code not in _BY_CODE:
        raise KeyError(code)
    if code in ("CATEGORY_SHARE", "PORTFOLIO_YTM", "DURATION_CORRIDOR", "FUND_SHARE"):
        return _summary_example(db, code, cdu_id, as_of)
    from services.portfolio.engine import build_portfolio
    from services.portfolio.reference import ReferenceBook
    refs = ReferenceBook(db)
    state = build_portfolio(db, cdu_id, as_of, refs=refs)
    if code in ("BOND_VALUE", "ACCRUED", "MDURATION"):
        bonds = [b for b in state.bonds if b.total_value_kzt]
        if not bonds:
            return {"empty": "У ЧДУ нет облигаций на эту дату"}
        bonds.sort(key=lambda x: -x.total_value_kzt)
        seen: Dict[str, int] = {}
        keyed = []
        for x in bonds:                       # one ISIN may be held in several lots
            seen[x.isin] = seen.get(x.isin, 0) + 1
            keyed.append((x.isin if seen[x.isin] == 1 else f"{x.isin}#{seen[x.isin]}", x))
        lots = {i: sum(1 for k, x in keyed if x.isin == i) for i in seen}
        choices = [{"value": k, "label": (f"{x.ticker or x.isin}" + (f" (лот {k.split('#')[1] if '#' in k else 1})"
                                                                     if lots[x.isin] > 1 else "")
                                          + f" · {fn(x.total_value_kzt, 0)} ₸")} for k, x in keyed]
        key_b = next(((k, x) for k, x in keyed if item and k == item), keyed[0])
        b = key_b[1]
        ref = refs.get(b.isin) or refs.get(b.ticker)
        out = {"choices": choices, "item": key_b[0], "item_label": f"{b.ticker or ''} {b.isin}".strip()}
        if code == "BOND_VALUE":
            out.update(_bond_value(b))
        elif code == "ACCRUED":
            out.update(_accrued(b, ref, refs, as_of))
        else:
            out.update(_mduration(b, ref, as_of))
        return out
    if code in ("REPO_VALUE", "DEPOSIT_VALUE"):
        items = state.repos if code == "REPO_VALUE" else state.deposits
        items = [m for m in items if m.market_value]
        if not items:
            return {"empty": "Нет открытых сделок на эту дату"}
        items.sort(key=lambda x: -x.market_value)
        seen: Dict[str, int] = {}
        keyed = []
        for x in items:
            base = f"{x.deal_id or x.identifier}|{x.open_date}"
            seen[base] = seen.get(base, 0) + 1
            keyed.append((base if seen[base] == 1 else f"{base}#{seen[base]}", x))
        choices = [{"value": k, "label": f"{x.deal_id or x.identifier} · {fn(x.open_amount, 0)} ₸"} for k, x in keyed]
        k, m = next(((k, x) for k, x in keyed if item and k == item), keyed[0])
        out = {"choices": choices, "item": k, "item_label": m.deal_id or m.identifier}
        out.update(_money_market(m, as_of, code))
        return out
    if code == "CASH":
        from services.portfolio.breakdown import _Sources, _cash_breakdown
        cash = _cash_breakdown(db, _Sources(db), cdu_id, as_of, state)
        inflow = sum(m["amount_kzt"] for m in cash["movements"] if m["amount_kzt"] > 0)
        outflow = -sum(m["amount_kzt"] for m in cash["movements"] if m["amount_kzt"] < 0)
        implied = sum(i["amount_kzt"] for i in cash["implied"] if i["counted"])
        inputs = [_inp("Входящий остаток", cash["opening"]["total"], "₸", cash["opening"]["label"]),
                  _inp("Поступления", inflow + implied, "₸", f"{sum(1 for m in cash['movements'] if m['amount_kzt'] > 0)} движений"),
                  _inp("Списания", outflow, "₸", f"{sum(1 for m in cash['movements'] if m['amount_kzt'] < 0)} движений")]
        value = cash["opening"]["total"] + inflow + implied - outflow
        return {"inputs": inputs,
                "steps": [f"{fn(cash['opening']['total'])} + {fn(inflow + implied)} − {fn(outflow)} = {fn(value)}"],
                "result": {"label": "Остаток денег", "value": value, "unit": "₸"},
                "system_value": cash["total"]}
    return {"empty": "Пример недоступен"}


def _bond_value(b) -> Dict[str, Any]:
    from services.formulas.params import get
    src = {"risk_report": "Risk Report", "market": "KASE рыночная", "risk_parameters": "KASE риск-параметры",
           "market_stale": "KASE рыночная (прошлая дата)", "risk_parameters_stale": "KASE риск-параметры (прошлая дата)",
           "risk_report_carry": "Risk Report (свежей цены нет)", "purchase": "цена покупки",
           "amortized": "амортизация дисконта", "par": "номинал", "par_matured": "номинал (погашена)"}
    price_src = src.get(b.price_source or "", b.price_source)
    if b.price_date:
        price_src += f", {b.price_date:%d.%m.%Y}"
    inputs = [_inp("Номинал", b.face_value, b.currency, f"{fn(b.face_value / b.unit_nominal, 0)} шт × {fn(b.unit_nominal, 0)}"
                   if b.unit_nominal else None),
              _inp("Чистая цена, %", b.price, "%", price_src),
              _inp("НКД", b.accrued, b.currency, "по графику купонов / параметрам выпуска"),
              _inp("Курс валюты", b.fx_rate, "", "1 для тенге")]
    clean = b.face_value * (b.price or 0.0) / 100.0
    value = (clean + b.accrued) * b.fx_rate
    steps = [f"{fn(b.face_value)} × {fn(b.price, 4)} ÷ 100 = {fn(clean)}",
             f"{fn(clean)} + {fn(b.accrued)} = {fn(clean + b.accrued)}"]
    if b.fx_rate != 1.0:
        steps.append(f"{fn(clean + b.accrued)} × {fn(b.fx_rate, 4)} = {fn(value)} ₸")
    return {"inputs": inputs, "steps": steps, "result": {"label": "Стоимость", "value": value, "unit": "₸"},
            "system_value": b.total_value_kzt,
            "note": f"Параметры: сначала берётся {'рыночная' if get('price_priority') == 'market' else 'по риск-параметрам'} "
                    f"цена KASE; старая цена допускается до {get('max_stale_price_days')} дн."}


def _accrued(b, ref, refs, as_of: date) -> Dict[str, Any]:
    from services.portfolio import bond_math as bm
    from services.portfolio import coupon_schedule as cs
    if b.price_source == "amortized":
        return {"empty": "Дисконтная бумага: доход заложен в цену, НКД = 0"}
    if b.snapshot_date == as_of and b.origin == "risk_report":
        note = "На дату среза НКД взят из Risk Report; ниже — как он получается по формуле."
    else:
        note = None
    basis = bm.normalize_basis(ref.base if ref is not None else None)
    schedule = refs.schedule(b.isin) or refs.schedule(b.ticker)
    begin = None
    rate = None
    source = None
    if schedule:
        begin, row = cs.period_around(schedule, as_of, ref.start_date if ref else None)
        rate = row.rate if row is not None else None
        source = "график купонов"
    if rate is None and ref is not None:
        rate = bm.rate_fraction(ref.coupon_rate_pct)
        begin = begin or bm.previous_coupon_date(as_of, ref.maturity_date, ref.frequency, ref.start_date)
        source = "параметры выпуска"
    if rate is None or begin is None:
        return {"empty": "Нет ставки или графика купонов в справочнике ЦБ — НКД берётся из Risk Report"}
    days = bm.day_count(begin, as_of, basis)
    yf = bm.year_fraction(begin, as_of, basis)
    year = round(days / yf) if yf else None
    value = b.face_value * rate * yf
    inputs = [_inp("Номинал", b.face_value, b.currency),
              _inp("Ставка купона", rate * 100, "%", source),
              _inp("Дней с начала купонного периода", days, "дн.", f"с {begin:%d.%m.%Y} по {as_of:%d.%m.%Y}"),
              _inp("Дней в году по базису", year, "дн.", BASIS_LABEL.get(basis, str(basis)))]
    return {"inputs": inputs,
            "steps": [f"{fn(b.face_value)} × {fn(rate * 100, 4)}% × {days} ÷ {year} = {fn(value)}"],
            "result": {"label": "НКД", "value": value, "unit": b.currency},
            "system_value": b.accrued, "note": note}


def _mduration(b, ref, as_of: date) -> Dict[str, Any]:
    from services.portfolio import bond_math as bm
    if b.duration is None:
        return {"empty": "Для бумаги нет доходности или даты погашения — дюрация не рассчитана"}
    basis = bm.normalize_basis(ref.base if ref is not None else None)
    coupon = (ref.coupon_rate_pct if ref is not None else None)
    freq = ref.frequency if ref is not None else None
    maturity = b.maturity_date or (ref.maturity_date if ref else None)
    inputs = [_inp("Дата", as_of.strftime("%d.%m.%Y")),
              _inp("Погашение", maturity.strftime("%d.%m.%Y") if maturity else "—"),
              _inp("Купон", coupon, "%", "справочник ЦБ / график купонов"),
              _inp("Доходность", (b.ytm or 0) * 100, "%", "KASE / Risk Report"),
              _inp("Выплат в год", freq, ""),
              _inp("Базис", BASIS_LABEL.get(basis, basis), "")]
    return {"inputs": inputs,
            "steps": [f"МДЛИТ({as_of:%d.%m.%Y}; {maturity:%d.%m.%Y}; {fn(coupon, 2)}%; {fn((b.ytm or 0) * 100, 2)}%; "
                      f"{freq or '—'}; {BASIS_LABEL.get(basis, basis)}) = {fn(b.duration, 4)}" if maturity else
                      f"Дюрация = {fn(b.duration, 4)}"],
            "result": {"label": "Модифицированная дюрация", "value": b.duration, "unit": "лет"},
            "system_value": b.duration,
            "note": "Excel: =МДЛИТ(дата; погашение; купон; доходность; частота; базис). "
                    "Если в справочнике есть график купонов, используются фактические будущие выплаты."}


def _money_market(m, as_of: date, code: str) -> Dict[str, Any]:
    passed = (as_of - m.open_date).days if m.open_date else 0
    total = (m.close_date - m.open_date).days if m.close_date and m.open_date else None
    if code == "REPO_VALUE" and m.close_amount and total:
        reward = (m.close_amount - m.open_amount) * min(passed, total) / total
        inputs = [_inp("Сумма открытия", m.open_amount, "₸"), _inp("Сумма закрытия", m.close_amount, "₸"),
                  _inp("Дней прошло", passed, "дн.", f"с {m.open_date:%d.%m.%Y}"),
                  _inp("Срок сделки, дней", total, "дн.", f"до {m.close_date:%d.%m.%Y}")]
        steps = [f"({fn(m.close_amount)} − {fn(m.open_amount)}) × {passed} ÷ {total} = {fn(reward)}",
                 f"{fn(m.open_amount)} + {fn(reward)} = {fn(m.open_amount + reward)}"]
        value = m.open_amount + reward
    else:
        rate = m.rate or 0.0
        reward = m.open_amount * rate * passed / m.base
        inputs = [_inp("Сумма" + (" открытия" if code == "REPO_VALUE" else " депозита"), m.open_amount, "₸"),
                  _inp("Ставка", rate * 100, "%"), _inp("Дней прошло", passed, "дн.", f"с {m.open_date:%d.%m.%Y}"),
                  _inp("База дней", m.base, "дн.", "из сделки или параметр расчёта")]
        steps = [f"{fn(m.open_amount)} × {fn(rate * 100, 4)}% × {passed} ÷ {m.base} = {fn(reward)}",
                 f"{fn(m.open_amount)} + {fn(reward)} = {fn(m.open_amount + reward)}"]
        value = m.open_amount + reward
    return {"inputs": inputs, "steps": steps,
            "result": {"label": "Стоимость на дату", "value": value, "unit": "₸"}, "system_value": m.market_value}


def _summary_example(db: Session, code: str, cdu_id: int, as_of: date) -> Dict[str, Any]:
    from services.formulas import fields, params
    per, fund, names = fields.contexts(db, as_of)
    ctx = per.get(cdu_id)
    if ctx is None:
        return {"empty": f"Сводка на {as_of:%d.%m.%Y} для ЧДУ не рассчитана — нажмите «Пересчитать» в сводке"}
    total = ctx["Итого ЧДУ"] or 0.0
    if code == "FUND_SHARE":
        value = (total / ctx["Итого фонда"] * 100) if ctx["Итого фонда"] else None
        return {"inputs": [_inp("Итого ЧДУ", total, "₸"), _inp("Итого фонда", ctx["Итого фонда"], "₸")],
                "steps": [f"{fn(total)} ÷ {fn(ctx['Итого фонда'])} × 100 = {fn(value, 4)}%"],
                "result": {"label": "Доля в фонде", "value": value, "unit": "%"},
                "system_value": ctx["Доля ЧДУ в фонде, %"]}
    if code == "DURATION_CORRIDOR":
        b = ctx["Бенчмарк MBM (ModDuration)"]
        if b is None:
            return {"empty": "Нет индекса MBM на дату"}
        lo, hi = params.get("duration_lower_mult"), params.get("duration_upper_mult")
        dur = ctx["Дюрация портфеля"]
        inside = dur is not None and b * lo <= dur <= b * hi
        return {"inputs": [_inp("Бенчмарк MBM", b, "", "ModDuration индекса на дату"),
                           _inp("нижний множитель", lo, "×", "параметр расчёта"),
                           _inp("верхний множитель", hi, "×", "параметр расчёта"),
                           _inp("Дюрация портфеля", dur, "")],
                "steps": [f"{fn(b, 4)} × {fn(lo, 2)} = {fn(b * lo, 4)}", f"{fn(b, 4)} × {fn(hi, 2)} = {fn(b * hi, 4)}",
                          f"{fn(b * lo, 4)} ≤ {fn(dur, 4)} ≤ {fn(b * hi, 4)} — {'внутри коридора' if inside else 'ВНЕ коридора'}"],
                "result": {"label": "Статус", "value": "в коридоре" if inside else "нарушение", "unit": ""}}
    rows = []
    for c_code, label in fields.CATS:
        v = ctx.get(label) or 0.0
        if code == "CATEGORY_SHARE":
            share = v / total * 100 if total else None
            mn, mx = ctx.get(f"Лимит мин: {label}, %"), ctx.get(f"Лимит макс: {label}, %")
            ok = share is None or ((mn is None or share >= mn - 1e-9) and (mx is None or share <= mx + 1e-9))
            rows.append({"Категория": label, "Стоимость, ₸": v, "Доля, %": share, "Лимит мин, %": mn,
                         "Лимит макс, %": mx, "Статус": "в пределах" if ok else "нарушение"})
        elif c_code in fields.YIELD_CATS and v:
            rows.append({"Категория": label, "Стоимость, ₸": v, "Доходность, %": ctx.get(f"Доходность: {label}, %"),
                         "Дюрация": ctx.get(f"Дюрация: {label}")})
    if code == "CATEGORY_SHARE":
        return {"table": rows, "steps": [f"Доля = стоимость категории ÷ {fn(total)} × 100"],
                "result": {"label": "Итого ЧДУ", "value": total, "unit": "₸"}}
    wy = sum(r["Стоимость, ₸"] for r in rows if r["Доходность, %"] is not None)
    ytm = sum(r["Стоимость, ₸"] * r["Доходность, %"] for r in rows if r["Доходность, %"] is not None) / wy if wy else None
    wd = sum(r["Стоимость, ₸"] for r in rows if r["Дюрация"] is not None)
    dur = sum(r["Стоимость, ₸"] * r["Дюрация"] for r in rows if r["Дюрация"] is not None) / wd if wd else None
    from models.db_models import PortfolioPosition
    imported = db.query(PortfolioPosition.id).filter(
        PortfolioPosition.cdu_id == cdu_id, PortfolioPosition.position_date == as_of,
        PortfolioPosition.notes == "rr_report_import").first() is not None
    return {"table": rows,
            "note": ("На эту дату итоги взяты из импортированного Risk Report: системное значение посчитано в Excel "
                     "по позициям, поэтому возможна разница в последних знаках.") if imported else None,
            "steps": [f"Доходность = Σ(доходность × стоимость) ÷ {fn(wy)} = {fn(ytm, 4)}%",
                      f"Дюрация = Σ(дюрация × стоимость) ÷ {fn(wd)} = {fn(dur, 4)}"],
            "result": {"label": "Доходность портфеля", "value": ytm, "unit": "%"},
            "system_value": ctx["Доходность портфеля, %"],
            "extra": {"label": "Дюрация портфеля", "value": dur, "system_value": ctx["Дюрация портфеля"]}}
