"""Reconciliation of OUR portfolio with the manager's reconciliation file
(«Сверка КФГД на дату», business process 6.5).

Our side is the portfolio as the system calculates it on the date (the same
engine as the summary and the report: Risk Report snapshot rolled forward with
Trade Reports, statements and approved manual operations, revalued on the
date).  The manager's side is the parsed workbook (``recon_parser``).

The comparison is done line by line:

* securities — by ISIN (lots of one issue are summed on both sides):
  quantity, nominal, clean price, accrued coupon, market value;
* reverse REPO — by deal: open date + open amount (collateral ISIN preferred):
  close date, close amount, accrued reward, current value;
* cash, receivables — balances;
* section totals and «Итого активов».

Every difference gets a plain-language explanation, so the operator sees what
to ask the manager (or what to fix in our data) without opening both files.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

LINE_TOL = 1.0          # ₸ for amounts of one line  (parameter «recon_line_tolerance»)
PRICE_TOL = 0.00005     # % of nominal               (parameter «recon_price_tolerance»)
QTY_TOL = 0.5           # securities


def _load_tolerances(db: Session) -> None:
    global LINE_TOL, PRICE_TOL
    from services.formulas import params
    params.refresh(db, force=True)
    LINE_TOL = float(params.get("recon_line_tolerance"))
    PRICE_TOL = float(params.get("recon_price_tolerance"))


def _fmt(v: Optional[float], digits: int = 2) -> str:
    if v is None:
        return "—"
    s = f"{v:,.{digits}f}".replace(",", " ").replace(".", ",")
    return s


def _amount_tol(*values: Optional[float], lots: int = 1) -> float:
    return max(LINE_TOL, 0.5 * max(lots, 1)) if LINE_TOL >= 0.5 else LINE_TOL


def _diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a - b


# ───────────────────────────── our side ─────────────────────────────

def _our_side(db: Session, cdu_id: int, as_of: date):
    from services.portfolio.breakdown import _Sources, _cash_breakdown, _receivables
    from services.portfolio.engine import build_portfolio
    from services.portfolio.reference import ReferenceBook

    refs = ReferenceBook(db)
    state = build_portfolio(db, cdu_id, as_of, refs=refs)
    src = _Sources(db)
    cash = _cash_breakdown(db, src, cdu_id, as_of, state)
    receivables = _receivables(db, src, cdu_id, as_of)
    return refs, state, cash, receivables


def _key(refs, ident: Optional[str]) -> str:
    ident = (ident or "").strip().upper()
    return (refs.isin_for(ident) or ident) if ident else ""


# ───────────────────────────── securities ─────────────────────────────

_PRICE_SOURCE = {
    "risk_report": "Risk Report", "risk_report_carry": "Risk Report (старая цена)",
    "market": "KASE рыночная", "market_stale": "KASE рыночная прошлой даты",
    "risk_parameters": "KASE риск-параметры", "risk_parameters_stale": "KASE риск-параметры прошлой даты",
    "purchase": "цена покупки", "amortized": "амортизация дисконта", "par": "номинал", "par_matured": "номинал (погашена)",
}


def _securities(refs, state, file_lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ours: Dict[str, Dict[str, Any]] = {}
    for b in state.bonds:
        if abs(b.total_value_kzt) < 1e-9 and b.face_value <= 0.005:
            continue
        k = _key(refs, b.isin) or _key(refs, b.ticker)
        row = ours.setdefault(k, {
            "isin": k, "ticker": b.ticker, "category": b.category, "lots": 0, "quantity": 0.0,
            "face_value": 0.0, "price_w": 0.0, "accrued": 0.0, "value": 0.0, "qty_known": True,
            "price_sources": set(), "price_date": None, "warnings": [],
        })
        row["lots"] += 1
        if b.unit_nominal:
            row["quantity"] += b.face_value / b.unit_nominal
        else:
            row["qty_known"] = False
        row["face_value"] += b.face_value * b.fx_rate
        if b.price is not None:
            row["price_w"] += b.price * b.face_value
        row["accrued"] += b.accrued * b.fx_rate
        row["value"] += b.total_value_kzt
        if b.price_source:
            row["price_sources"].add(_PRICE_SOURCE.get(b.price_source, b.price_source))
        if b.price_date:
            row["price_date"] = b.price_date.isoformat()
        row["warnings"].extend(b.warnings)

    theirs: Dict[str, Dict[str, Any]] = {}
    for x in file_lines:
        k = _key(refs, x["isin"])
        row = theirs.setdefault(k, {
            "isin": x["isin"], "name": x.get("name"), "lots": 0, "quantity": 0.0, "face_value": 0.0,
            "price_w": 0.0, "price_face": 0.0, "accrued": 0.0, "value": 0.0, "rows": [],
            "maturity_date": x.get("maturity_date"), "rate_pct": x.get("rate_pct"),
        })
        row["lots"] += 1
        row["quantity"] += x.get("quantity") or 0.0
        row["face_value"] += x.get("face_value") or 0.0
        if x.get("price") is not None and x.get("face_value"):
            row["price_w"] += x["price"] * x["face_value"]
            row["price_face"] += x["face_value"]
        row["accrued"] += x.get("accrued") or 0.0
        row["value"] += x.get("value") or 0.0
        row["rows"].append(x.get("row"))

    out: List[Dict[str, Any]] = []
    for k in sorted(set(ours) | set(theirs), key=lambda z: -max(
            abs(ours.get(z, {}).get("value", 0.0)), abs(theirs.get(z, {}).get("value", 0.0)))):
        o, t = ours.get(k), theirs.get(k)
        line: Dict[str, Any] = {"isin": k, "ticker": o["ticker"] if o else None,
                                "name": t["name"] if t else None,
                                "category": o["category"] if o else None}
        if o:
            line["ours"] = {
                "lots": o["lots"], "quantity": o["quantity"] if o["qty_known"] else None,
                "face_value": o["face_value"],
                "price": (o["price_w"] / (o["face_value"] or 1.0)) if o["price_w"] else None,
                "accrued": o["accrued"], "value": o["value"],
                "price_source": ", ".join(sorted(o["price_sources"])) or None, "price_date": o["price_date"],
            }
        if t:
            line["cdu"] = {
                "lots": t["lots"], "quantity": t["quantity"], "face_value": t["face_value"],
                "price": (t["price_w"] / t["price_face"]) if t["price_face"] else None,
                "accrued": t["accrued"], "value": t["value"], "rows": t["rows"],
                "maturity_date": t["maturity_date"], "rate_pct": t["rate_pct"],
            }
        reasons: List[str] = []
        fields: List[str] = []
        if o and t and line["ours"]["quantity"] is None and t["quantity"] and t["face_value"]:
            # nominal of one security is not in our reference book — take it from the file
            line["ours"]["quantity"] = o["face_value"] / (t["face_value"] / t["quantity"])
            line["ours"]["quantity_from_cdu_nominal"] = True
        if o and t:
            lots = max(o["lots"], t["lots"])
            oq, tq = line["ours"]["quantity"], t["quantity"]
            if oq is not None and abs(oq - tq) > QTY_TOL:
                fields.append("quantity")
                reasons.append(f"Количество: у ЧДУ {_fmt(tq, 0)}, у нас {_fmt(oq, 0)} (Δ {_fmt(oq - tq, 0)})")
            if abs(o["face_value"] - t["face_value"]) > _amount_tol(lots=lots) and "quantity" not in fields:
                fields.append("face_value")
                reasons.append(f"Номинал: у ЧДУ {_fmt(t['face_value'])}, у нас {_fmt(o['face_value'])}")
            op, tp = line["ours"]["price"], line["cdu"]["price"]
            if op is not None and tp is not None and abs(op - tp) > PRICE_TOL:
                fields.append("price")
                src = line["ours"]["price_source"]
                pdate = line["ours"]["price_date"]
                pdate = f"{pdate[8:10]}.{pdate[5:7]}.{pdate[:4]}" if pdate else ""
                reasons.append(f"Цена: у ЧДУ {_fmt(tp, 4)}, у нас {_fmt(op, 4)}"
                               + (f" ({src}{', ' + pdate if pdate else ''})" if src else ""))
            if abs(o["accrued"] - t["accrued"]) > _amount_tol(lots=lots):
                fields.append("accrued")
                reasons.append(f"НКД: у ЧДУ {_fmt(t['accrued'])}, у нас {_fmt(o['accrued'])} (Δ {_fmt(o['accrued'] - t['accrued'])})")
            dv = o["value"] - t["value"]
            if abs(dv) > _amount_tol(lots=lots):
                fields.append("value")
                if not reasons:
                    reasons.append(f"Стоимость отличается на {_fmt(dv)} при одинаковых количестве, цене и НКД — "
                                   "проверьте округление/курс")
            line["delta_value"] = dv
            line["status"] = "DIFF" if fields else "OK"
        elif o:
            line["delta_value"] = o["value"]
            line["status"] = "ONLY_OURS"
            reasons.append("Есть у нас, нет в файле ЧДУ — продана/погашена у ЧДУ или сделка не отражена у нас")
        else:
            line["delta_value"] = -t["value"]
            line["status"] = "ONLY_CDU"
            reasons.append("Есть в файле ЧДУ, нет у нас — не загружен Trade Report о покупке или бумага не попала в срез")
        line["fields"] = fields
        line["reasons"] = reasons
        out.append(line)
    return out


# ───────────────────────────── reverse REPO ─────────────────────────────

def _repos(refs, state, file_lines: List[Dict[str, Any]], as_of: date) -> List[Dict[str, Any]]:
    ours = list(state.repos)
    used: set = set()
    out: List[Dict[str, Any]] = []
    for x in file_lines:
        if x.get("closed"):
            out.append({
                "status": "CLOSED", "cdu": x, "ours": None, "isin": x.get("isin"),
                "reasons": [f"Закрыта {x['close_date']} — в стоимость портфеля на дату не входит"],
                "fields": [], "delta_value": 0.0,
            })
            continue
        cands = [
            (i, m) for i, m in enumerate(ours)
            if i not in used and m.open_date and m.open_date.isoformat() == x["open_date"]
            and abs(m.open_amount - x["open_amount"]) <= max(LINE_TOL, 1e-6 * x["open_amount"])
        ]
        coll = _key(refs, x.get("isin"))
        cands.sort(key=lambda im: (0 if _key(refs, im[1].collateral or im[1].identifier) == coll else 1,
                                   abs(im[1].open_amount - x["open_amount"])))
        if not cands:
            out.append({"status": "ONLY_CDU", "cdu": x, "ours": None, "isin": x.get("isin"),
                        "delta_value": -(x["value_effective"]),
                        "fields": [], "reasons": ["Есть в файле ЧДУ, нет у нас — не загружен Trade Report с открытием РЕПО"]})
            continue
        i, m = cands[0]
        used.add(i)
        our = {
            "deal_id": m.deal_id, "collateral": m.collateral or m.identifier, "quantity": m.quantity,
            "open_date": m.open_date.isoformat() if m.open_date else None,
            "close_date": m.close_date.isoformat() if m.close_date else None,
            "open_amount": m.open_amount, "close_amount": m.close_amount,
            "rate_pct": (m.rate * 100.0) if m.rate is not None else None,
            "accrued": m.accrued, "value": m.market_value,
        }
        fields, reasons = [], []
        if x.get("close_date") and our["close_date"] and x["close_date"] != our["close_date"]:
            fields.append("close_date")
            reasons.append(f"Дата закрытия: у ЧДУ {x['close_date']}, у нас {our['close_date']}")
        if x.get("close_amount") is not None and our["close_amount"] is not None and \
                abs(x["close_amount"] - our["close_amount"]) > LINE_TOL:
            fields.append("close_amount")
            reasons.append(f"Сумма закрытия: у ЧДУ {_fmt(x['close_amount'])}, у нас {_fmt(our['close_amount'])}")
        if abs((x.get("accrued") or 0.0) - our["accrued"]) > LINE_TOL:
            fields.append("accrued")
            reasons.append(f"Начисленное вознаграждение: у ЧДУ {_fmt(x.get('accrued'))}, у нас {_fmt(our['accrued'])}")
        dv = our["value"] - x["value_effective"]
        if abs(dv) > LINE_TOL:
            fields.append("value")
            if "accrued" not in fields:
                reasons.append(f"Текущая стоимость отличается на {_fmt(dv)}")
        if coll and our["collateral"] and _key(refs, our["collateral"]) != coll:
            reasons.append(f"Залог: у ЧДУ {x.get('isin')}, у нас {our['collateral']}")
        out.append({"status": "DIFF" if fields else "OK", "cdu": x, "ours": our, "isin": x.get("isin"),
                    "delta_value": dv, "fields": fields, "reasons": reasons})
    for i, m in enumerate(ours):
        if i in used or abs(m.market_value) < 1e-9:
            continue
        out.append({
            "status": "ONLY_OURS", "cdu": None, "isin": m.collateral or m.identifier,
            "ours": {"deal_id": m.deal_id, "collateral": m.collateral or m.identifier,
                     "open_date": m.open_date.isoformat() if m.open_date else None,
                     "close_date": m.close_date.isoformat() if m.close_date else None,
                     "open_amount": m.open_amount, "close_amount": m.close_amount,
                     "rate_pct": (m.rate * 100.0) if m.rate is not None else None,
                     "accrued": m.accrued, "value": m.market_value, "quantity": m.quantity},
            "delta_value": m.market_value, "fields": [],
            "reasons": ["Есть у нас, нет в файле ЧДУ — проверьте дату закрытия сделки"],
        })
    return out


# ───────────────────────────── entry point ─────────────────────────────

def compare(db: Session, cdu_id: int, as_of: date, parsed: Dict[str, Any]) -> Dict[str, Any]:
    _load_tolerances(db)
    refs, state, cash, receivables = _our_side(db, cdu_id, as_of)
    securities = _securities(refs, state, parsed.get("securities") or [])
    repos = _repos(refs, state, parsed.get("repos") or [], as_of)

    totals = parsed.get("totals") or {}
    our_sec = sum(b.total_value_kzt for b in state.bonds)
    our_repo = sum(m.market_value for m in state.repos)
    our_dep = sum(m.market_value for m in state.deposits)
    our_cash = cash["total"]
    our_ar = receivables["total"]

    from services.portfolio.engine import MarketData
    market = MarketData(db, as_of)
    cdu_cash = 0.0
    for c in parsed.get("cash") or []:
        fx, _ = market.fx_rate(c["currency"])
        cdu_cash += c["amount"] * (1.0 if c["currency"] == "KZT" else fx)

    cdu_total = totals.get("total")
    our_total = our_sec + our_repo + our_dep + our_cash + our_ar
    summary = []
    for key, label, ours_v, cdu_v in (
        ("securities", "Ценные бумаги", our_sec, totals.get("securities_lines", totals.get("securities"))),
        ("repo", "Обратное РЕПО", our_repo, totals.get("repo_lines", totals.get("repo"))),
        ("cash", "Деньги на счетах", our_cash, cdu_cash),
        ("ar", "Дебиторская задолженность", our_ar, totals.get("ar")),
        ("deposits", "Депозиты", our_dep, 0.0 if our_dep else None),
        ("total", "Итого активов", our_total, cdu_total),
    ):
        if key == "deposits" and not our_dep:
            continue
        d = _diff(ours_v, cdu_v)
        summary.append({
            "key": key, "label": label, "ours": ours_v, "cdu": cdu_v, "delta": d,
            "status": "MISSING" if cdu_v is None else ("OK" if abs(d) <= LINE_TOL else "DIFF"),
        })

    counts = {
        "securities_ok": sum(1 for s in securities if s["status"] == "OK"),
        "securities_diff": sum(1 for s in securities if s["status"] != "OK"),
        "repos_ok": sum(1 for r in repos if r["status"] in ("OK", "CLOSED")),
        "repos_diff": sum(1 for r in repos if r["status"] not in ("OK", "CLOSED")),
    }
    ok = all(s["status"] == "OK" for s in summary) and counts["securities_diff"] == 0 and counts["repos_diff"] == 0

    notes = []
    if state.base_date:
        notes.append(f"Наш расчёт: срез Risk Report на {state.base_date:%d.%m.%Y}"
                     + (" + операции после него, оценка на дату сверки" if state.base_date != as_of else ""))
    else:
        notes.append("Наш расчёт: Risk Report для ЧДУ не загружен — позиции собраны из сделок и операций")
    if totals.get("liabilities"):
        notes.append(f"Кредиторская задолженность (комиссии) по файлу ЧДУ {_fmt(totals['liabilities'])} ₸ — "
                     "в системе не ведётся, показана для информации")

    return {
        "status": "OK" if ok else "MISMATCH",
        "our_total": our_total,
        "cdu_total": cdu_total,
        "delta_total": _diff(our_total, cdu_total),
        "summary": summary,
        "securities": securities,
        "repos": repos,
        "cash": {
            "ours": our_cash, "cdu": cdu_cash, "cdu_lines": parsed.get("cash") or [],
            "ours_opening": cash["opening"], "ours_movements": len(cash["movements"]),
            "delta": our_cash - cdu_cash, "status": "OK" if abs(our_cash - cdu_cash) <= LINE_TOL else "DIFF",
        },
        "receivables": {
            "ours": our_ar, "cdu": totals.get("ar"),
            "ours_lines": [{"counterparty": i["counterparty"], "balance_kzt": i["balance_kzt"],
                            "record_date": i["record_date"]} for i in receivables["items"]],
            "cdu_lines": parsed.get("receivables") or [],
        },
        "liabilities": {"lines": parsed.get("liabilities") or [], "total": totals.get("liabilities"),
                        "net_assets": totals.get("net_assets")},
        "counts": counts,
        "notes": notes,
        "file_warnings": parsed.get("warnings") or [],
        "base_date": state.base_date.isoformat() if state.base_date else None,
    }
