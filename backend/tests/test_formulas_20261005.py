"""Раздел «Формулы» (05.10.2026): язык формул, параметры расчёта, свои показатели, пояснения."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from models.db_models import Alert, CDU, CalcParameterChange, CustomIndicator, PortfolioPosition, PortfolioSummary
from services.formulas import expr, fields, indicators, params
from tests.test_requirements_20260929 import stand  # noqa: F401

D = date(2026, 9, 30)
DS = D.isoformat()


@pytest.fixture(autouse=True)
def _fresh_params():
    params.reset_cache()
    yield
    params.reset_cache()


# ───────────────────────────── язык формул ─────────────────────────────

NAMES = ["ГЦБ", "Итого ЧДУ", "Деньги"]
CTX = {"ГЦБ": 50.0, "Итого ЧДУ": 200.0, "Деньги": None}


@pytest.mark.parametrize("text, value", [
    ("ДОЛЯ([ГЦБ]; [Итого ЧДУ])", 25.0),
    ("[гцб] * 2", 100.0),                      # регистр полей не важен
    ("ЕСЛИ([ГЦБ] > 10; 1; 0)", 1.0),
    ("1 000 000,5 / 2", 500000.25),            # пробелы в числе и запятая
    ("ОКРУГЛ(2,555; 2)", 2.56),
    ("2^3*-1", -8.0),
    ("СУММ([ГЦБ]; [Деньги])", 50.0),            # пустое поле в сумме пропускается
    ("МИН([ГЦБ]; 10) + МАКС(1; 2; 3)", 13.0),
    ("АБС(-[ГЦБ])", 50.0),
])
def test_expressions_evaluate(text, value):
    assert expr.evaluate(expr.parse(text, NAMES), CTX) == pytest.approx(value)


@pytest.mark.parametrize("text, fragment", [
    ("[ГЦБ]+", "обрывается"),
    ("МАКС(1, 2)", "«;»"),
    ("[X]", "Неизвестное поле"),
    ("ФУ(1)", "Неизвестная функция"),
    ("__import__('os')", ""),
])
def test_expression_errors_are_explained_in_russian(text, fragment):
    with pytest.raises(expr.FormulaError) as e:
        expr.parse(text, NAMES)
    assert fragment in e.value.message


def test_empty_fields_and_division_by_zero():
    assert expr.evaluate(expr.parse("[Деньги] + 1", NAMES), CTX) is None
    with pytest.raises(expr.EvalError):
        expr.evaluate(expr.parse("[ГЦБ] / 0", NAMES), CTX)
    tree = expr.parse("ДОЛЯ([ГЦБ]; [Итого ЧДУ])", NAMES)
    assert expr.render(tree, CTX) == "ДОЛЯ(50; 200)"
    assert expr.fields_used(tree) == ["ГЦБ", "Итого ЧДУ"]


# ───────────────────────────── параметры расчёта ─────────────────────────────

def test_parameters_change_the_engine(stand):
    client, Session, _ = stand
    from services.calculator.constants import duration_band
    assert duration_band(2.0) == pytest.approx((1.6, 3.0))

    r = client.put("/api/formulas/parameters/duration_upper_mult", json={"value": "1,7"})
    assert r.status_code == 400 and "причину" in r.json()["detail"]
    r = client.put("/api/formulas/parameters/duration_upper_mult", json={"value": "abc", "reason": "x"})
    assert r.status_code == 400
    r = client.put("/api/formulas/parameters/duration_upper_mult", json={"value": "1,7", "reason": "Решение ИК"})
    assert r.status_code == 200, r.text
    assert "пересчит" in r.json()["message"]
    assert duration_band(2.0) == pytest.approx((1.6, 3.4))

    r = client.put("/api/formulas/parameters/price_priority", json={"value": "risk_parameters", "reason": "тест"})
    assert r.status_code == 200, r.text
    with Session() as db:
        from services.portfolio.engine import MarketData
        m = MarketData(db, D)
        assert m.order[0] == "risk_parameters"
        hist = db.query(CalcParameterChange).filter_by(code="duration_upper_mult").all()
        assert [(h.old_value, h.new_value, h.reason) for h in hist] == [("1.5", "1.7", "Решение ИК")]

    listing = {p["code"]: p for p in client.get("/api/formulas/parameters").json()}
    assert listing["duration_upper_mult"]["value"] == pytest.approx(1.7)
    assert listing["duration_upper_mult"]["history"]

    r = client.post("/api/formulas/parameters/duration_upper_mult/reset", json={})
    assert r.status_code == 200
    assert duration_band(2.0) == pytest.approx((1.6, 3.0))


def test_tolerance_parameters_reach_reconciliation(stand):
    client, Session, _ = stand
    client.put("/api/formulas/parameters/recon_line_tolerance", json={"value": "100", "reason": "тест"})
    from services.reconciliation import cdu_statement
    with Session() as db:
        cdu_statement._load_tolerances(db)
    assert cdu_statement.LINE_TOL == pytest.approx(100.0)


# ───────────────────────────── свои показатели ─────────────────────────────

def _summary_slice(Session):
    """Two managers with a stored calculation for D (and the previous day)."""
    with Session() as db:
        cdus = db.query(CDU).filter_by(is_active=True).order_by(CDU.id).limit(2).all()
        values = [
            {"GOV_BONDS": 800.0, "REVERSE_REPO": 150.0, "CASH": 50.0},
            {"GOV_BONDS": 300.0, "REVERSE_REPO": 600.0, "CASH": 100.0},
        ]
        for cdu, cats in zip(cdus, values):
            total = sum(cats.values())
            db.add(PortfolioSummary(cdu_id=cdu.id, summary_date=D, total_mv_prev=total - 10,
                                    total_mv_current=total, total_daily_change=10.0,
                                    ytm_weighted=0.15, duration_weighted=2.0, benchmark_duration=2.5))
            for code, _label in fields.CATS:
                v = cats.get(code, 0.0)
                db.add(PortfolioPosition(cdu_id=cdu.id, position_date=D, instrument_code=None,
                                         instrument_category=code, market_value_current=v,
                                         market_value_prev=v, daily_change=0.0,
                                         ytm=0.16 if v and code != "CASH" else None,
                                         duration=1.0 if v and code != "CASH" else None, notes="calculated"))
        db.commit()
        return [(c.id, c.short_name or c.name) for c in cdus]


def test_fields_and_preview_on_calculated_date(stand):
    client, Session, _ = stand
    (a, _), (b, _) = _summary_slice(Session)
    with Session() as db:
        per, fund, _names = fields.contexts(db, D)
    assert per[a]["ГЦБ"] == 800 and per[a]["Итого ЧДУ"] == 1000
    assert per[a]["Доля ЧДУ в фонде, %"] == pytest.approx(50.0)
    assert per[a]["Доходность портфеля, %"] == pytest.approx(15.0)
    assert per[a]["Коридор дюрации: до"] == pytest.approx(2.5 * 1.5)
    assert fund["ГЦБ"] == 1100 and fund["Итого фонда"] == 2000 and fund["Количество ЧДУ"] == 2
    assert fund["Изменение за день"] == pytest.approx(20.0)

    groups = client.get("/api/formulas/fields", params={"level": "cdu"}).json()["groups"]
    assert any(f["name"] == "ГЦБ" for g in groups for f in g["fields"])

    bad = client.post("/api/formulas/validate", json={"expression": "[ГЦБ] +", "level": "cdu"}).json()
    assert bad["ok"] is False and bad["error"]

    p = client.post("/api/formulas/preview", json={"expression": "ДОЛЯ([ГЦБ]; [Итого ЧДУ])",
                                                   "level": "cdu", "date": DS}).json()
    vals = {r["cdu_id"]: r["value"] for r in p["rows"]}
    assert vals == {a: pytest.approx(80.0), b: pytest.approx(30.0)}
    row = next(r for r in p["rows"] if r["cdu_id"] == a)
    assert row["substituted"] == "ДОЛЯ(800; 1 000)"

    empty = client.post("/api/formulas/preview", json={"expression": "[ГЦБ]", "level": "cdu",
                                                       "date": "2020-01-01"}).json()
    assert empty["rows"] == [] and "не рассчитана" in empty["note"]
    later = client.post("/api/formulas/preview", json={"expression": "[ГЦБ]", "level": "cdu",
                                                       "date": "2026-10-05"}).json()
    assert later["data_date"] == DS and len(later["rows"]) == 2 and "30.09.2026" in later["note"]

    for t in client.get("/api/formulas/templates").json():
        assert indicators.validate(t["expression"], t["level"])["ok"], t["name"]


def test_indicator_lifecycle_versions_and_alerts(stand):
    client, Session, _ = stand
    (a, _), (b, _) = _summary_slice(Session)
    r = client.post("/api/formulas/indicators", json={
        "name": "Доля РЕПО", "level": "cdu", "unit": "PCT", "expression": "ДОЛЯ([Обратное РЕПО]; [Итого ЧДУ])",
        "decimals": 1, "alert_op": ">", "alert_threshold": "50",
    })
    assert r.status_code == 200, r.text
    ind = r.json()
    assert ind["status"] == "ACTIVE" and ind["version"] == 1 and ind["valid"]

    dup = client.post("/api/formulas/indicators", json={"name": "Доля РЕПО", "expression": "[ГЦБ]"})
    assert dup.status_code == 400 and "уже есть" in dup.json()["detail"]
    r = client.post("/api/formulas/indicators", json={"name": "Плохой", "expression": "[Нет поля]"})
    assert r.status_code == 400 and "Неизвестное поле" in r.json()["detail"]

    vals = client.get("/api/formulas/indicators/values", params={"date": DS}).json()
    by = {int(k): v for k, v in vals["by_cdu"].items()}
    assert by[a][0]["value"] == pytest.approx(15.0) and by[a][0]["alert"] is False
    assert by[b][0]["value"] == pytest.approx(60.0) and by[b][0]["alert"] is True

    # уведомления создаются при пересчёте
    with Session() as db:
        assert indicators.raise_alerts(db, D) == 1
        db.commit()
        alert = db.query(Alert).filter_by(alert_type="CUSTOM_INDICATOR").one()
        assert alert.cdu_id == b and "Доля РЕПО" in alert.message and "60" in alert.message

    # изменение → версия 2, откат → версия 3 с формулой первой
    r = client.put(f"/api/formulas/indicators/{ind['id']}", json={
        **{k: ind[k] for k in ("name", "level", "unit", "decimals", "alert_op", "alert_threshold")},
        "expression": "ДОЛЯ([ГЦБ]; [Итого ЧДУ])", "comment": "смотрим ГЦБ"})
    assert r.status_code == 200 and r.json()["version"] == 2
    vers = client.get(f"/api/formulas/indicators/{ind['id']}/versions").json()
    assert [v["version"] for v in vers] == [2, 1]
    r = client.post(f"/api/formulas/indicators/{ind['id']}/rollback/1")
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 3 and "Обратное РЕПО" in r.json()["expression"]

    # архив — показатель исчезает из сводки
    client.post(f"/api/formulas/indicators/{ind['id']}/status", json={"status": "ARCHIVED"})
    assert client.get("/api/formulas/indicators/values", params={"date": DS}).json()["indicators"] == []

    # фондовый показатель
    r = client.post("/api/formulas/indicators", json={
        "name": "Фонд, тыс", "level": "fund", "unit": "NUMBER", "expression": "[Итого фонда] / 1000"})
    assert r.status_code == 200, r.text
    vals = client.get("/api/formulas/indicators/values", params={"date": DS}).json()
    assert vals["fund"][0]["value"] == pytest.approx(2.0)
    with Session() as db:
        assert db.query(CustomIndicator).count() == 2


def test_system_formula_cards(stand):
    client, Session, _ = stand
    cards = client.get("/api/formulas/system").json()
    codes = {c["code"] for c in cards}
    assert {"BOND_VALUE", "ACCRUED", "MDURATION", "REPO_VALUE", "CATEGORY_SHARE", "DURATION_CORRIDOR"} <= codes
    (a, _), (b, _) = _summary_slice(Session)
    ex = client.get("/api/formulas/system/FUND_SHARE/example", params={"cdu_id": a, "date": DS}).json()
    assert ex["result"]["value"] == pytest.approx(50.0) == ex["system_value"]
    ex = client.get("/api/formulas/system/DURATION_CORRIDOR/example", params={"cdu_id": a, "date": DS}).json()
    assert ex["result"]["value"] == "в коридоре"
    assert client.get("/api/formulas/system/NOPE/example", params={"cdu_id": a, "date": DS}).status_code == 404
    auto = client.get("/api/formulas/system/FUND_SHARE/example", params={"date": DS}).json()
    assert auto["cdu_id"] in (a, b) and auto["result"]["value"] == pytest.approx(50.0)
    later = client.get("/api/formulas/system/CASH/example", params={"date": "2030-01-01"})
    assert later.status_code == 200 and later.json()["cdu_id"] in (a, b)


RR = Path(__file__).resolve().parents[2] / "Примеры" / "risk report_31122025_.xlsm"


@pytest.mark.skipif(not RR.exists(), reason="Risk Report 31.12.2025 недоступен")
def test_examples_reproduce_system_values_on_real_risk_report(stand):
    client, Session, _ = stand
    from services.import_rr.risk_report_importer import import_risk_report
    from services.formulas import catalog
    rr_date = date(2025, 12, 31)
    with Session() as db:
        r = import_risk_report(db, RR, skip_if_imported=False)
        assert not r.error
        db.commit()
    client.post("/api/calculate/", json={"report_date": rr_date.isoformat()})
    with Session() as db:
        halyk = db.query(CDU).filter(CDU.short_name == "Halyk").one()
        for code in ("BOND_VALUE", "ACCRUED", "MDURATION", "REPO_VALUE", "CASH", "FUND_SHARE"):
            ex = catalog.example(db, code, halyk.id, rr_date, None)
            assert not ex.get("empty"), code
            assert ex["result"]["value"] == pytest.approx(ex["system_value"], rel=1e-6), code
            assert ex["inputs"] and ex["steps"], code
