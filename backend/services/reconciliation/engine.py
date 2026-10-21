"""Auto-reconciliation engine (business process 6.4, 6.5, 6.5.1, 7.3).

Reconciliation types:
  1. trade_vs_cert      — Trade ledger ↔ exchange certificates by deal number
                          (certificates are images → OCR; a deal that is not
                          recognised is reported for manual check).
  2. rr_vs_holdings     — calculated portfolio (Report) ↔ manager reconciliation
                          file: Cash, ЦБ (ГЦБ+Агентские+МФО), Обратное REPO,
                          Дебиторка, Итого (6.5).
  3. cash_vs_statement  — Cash (KZT) ↔ closing balance of the custodian
                          statement for the date (6.5.1).
  4. nbrk_fallback      — NBRK portfolios: cash vs AC balances of КФГД_ГГГГММДД.

Results are idempotent: a re-run for the same CDU/date/type replaces the
previous result instead of appending a new row (business process 5.4).
Tolerance: ±0.01 KZT.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.db_models import (
    CDU, PortfolioPosition, ReconciliationResult, SourceDocument, Trade,
)
from services.calculator.constants import RECON_TOLERANCE_KZT

SECURITIES_CATEGORIES = ("GOV_BONDS", "AGENCY_BONDS", "MFO_BONDS", "FOREIGN_BONDS")


def run_reconciliation(
    db: Session,
    cdu_id: int,
    recon_date: date,
    recon_type: str,
    *,
    details: Optional[Dict[str, Any]] = None,
) -> ReconciliationResult:
    """Run a single reconciliation check and persist (replace) the result."""
    db.query(ReconciliationResult).filter(
        ReconciliationResult.cdu_id == cdu_id,
        ReconciliationResult.recon_date == recon_date,
        ReconciliationResult.recon_type == recon_type,
    ).delete(synchronize_session=False)
    result = ReconciliationResult(
        cdu_id=cdu_id,
        recon_date=recon_date,
        recon_type=recon_type,
        status="PENDING",
        details_json=json.dumps(details or {}),
    )
    db.add(result)
    db.flush()

    try:
        if recon_type == "trade_vs_cert":
            _recon_trade_vs_cert(db, result, cdu_id, recon_date)
        elif recon_type == "rr_vs_holdings":
            _recon_rr_vs_holdings(db, result, cdu_id, recon_date)
        elif recon_type == "cash_vs_statement":
            _recon_cash_vs_statement(db, result, cdu_id, recon_date)
        elif recon_type == "nbrk_fallback":
            _recon_nbrk_fallback(db, result, cdu_id, recon_date)
        else:
            result.status = "ERROR"
            result.details_json = json.dumps({"error": f"Unknown recon_type {recon_type}"})
    except Exception as exc:
        logger.exception("Reconciliation failed")
        result.status = "ERROR"
        result.details_json = json.dumps({"error": str(exc)}, ensure_ascii=False)

    _sync_alert(db, result)
    db.commit()
    return result


_RECON_LABELS = {
    "trade_vs_cert": "Trade Report ↔ биржевые свидетельства",
    "rr_vs_holdings": "Наш расчёт ↔ файл сверки ЧДУ",
    "cash_vs_statement": "Деньги ↔ выписка кастодиана",
    "nbrk_fallback": "Деньги ↔ КФГД_ГГГГММДД",
}


def _sync_alert(db: Session, result: ReconciliationResult) -> None:
    """BP 8.3: a discrepancy raises a notification for ОИиУА (idempotent)."""
    from models.db_models import Alert
    alert_type = f"RECON_{result.recon_type.upper()}"[:40]
    db.query(Alert).filter(
        Alert.alert_date == result.recon_date,
        Alert.cdu_id == result.cdu_id,
        Alert.alert_type == alert_type,
        Alert.is_resolved.is_(False),
    ).delete(synchronize_session=False)
    if result.status != "MISMATCH":
        return
    cdu = db.get(CDU, result.cdu_id) if result.cdu_id else None
    deviation = f" Δ={result.deviation:,.2f}" if result.deviation is not None else ""
    db.add(Alert(
        alert_date=result.recon_date,
        cdu_id=result.cdu_id,
        alert_type=alert_type,
        severity="CRITICAL",
        message=f"{cdu.short_name if cdu else ''}: расхождение «{_RECON_LABELS.get(result.recon_type, result.recon_type)}»{deviation}",
        details_json=result.details_json,
    ))


# ───────── helpers ─────────

def _docs(db: Session, doc_type: str, cdu_id: int) -> List[SourceDocument]:
    return db.execute(select(SourceDocument).where(
        SourceDocument.doc_type == doc_type,
        SourceDocument.cdu_id == cdu_id,
        SourceDocument.parse_status == "OK",
    ).order_by(SourceDocument.uploaded_at.desc(), SourceDocument.id.desc())).scalars().all()


def _meta(doc: SourceDocument) -> Dict[str, Any]:
    try:
        return json.loads(doc.parse_meta_json or "{}")
    except (TypeError, ValueError):
        return {}


def _internal_portfolio(db: Session, cdu_id: int, recon_date: date) -> Optional[Dict[str, float]]:
    """Report categories of the CDU for the date (calculating them if needed)."""
    rows = db.execute(select(PortfolioPosition).where(
        PortfolioPosition.cdu_id == cdu_id,
        PortfolioPosition.position_date == recon_date,
        PortfolioPosition.instrument_code.is_(None),
    )).scalars().all()
    if not rows:
        from services.calculator.portfolio_calculator import calculate_for_date
        calculate_for_date(db, recon_date)
        rows = db.execute(select(PortfolioPosition).where(
            PortfolioPosition.cdu_id == cdu_id,
            PortfolioPosition.position_date == recon_date,
            PortfolioPosition.instrument_code.is_(None),
        )).scalars().all()
    if not rows:
        return None
    by_cat: Dict[str, float] = {}
    for row in rows:
        by_cat[row.instrument_category] = by_cat.get(row.instrument_category, 0.0) + float(row.market_value_current or 0.0)
    internal = {
        "cash": by_cat.get("CASH", 0.0),
        "securities": sum(by_cat.get(c, 0.0) for c in SECURITIES_CATEGORIES),
        "repo": by_cat.get("REVERSE_REPO", 0.0),
        "ar": by_cat.get("RECEIVABLES", 0.0),
    }
    internal["total"] = sum(by_cat.values())
    return internal


# ───────── 1. Trade ledger ↔ exchange certificates ─────────

def _close_enough(a: str, b: str, max_diff: int = 1) -> bool:
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= max_diff


def _amount_in_deal(amount: Optional[float], deal: Dict[str, Any]) -> bool:
    """Is the trade amount printed in the certificate row?

    OCR often loses or adds a space inside «2 124 850 129.34», so besides the
    parsed numbers the digits of the amount are searched in the row text.
    """
    if not amount:
        return False
    value = abs(float(amount))
    if any(abs(value - float(a)) <= RECON_TOLERANCE_KZT for a in deal.get("amounts") or []):
        return True
    digits = f"{value:.2f}".replace(".", "")
    for line in deal.get("lines") or []:
        if digits in re.sub(r"[^0-9]", "", str(line)):
            return True
    return False


def _recon_trade_vs_cert(
    db: Session, result: ReconciliationResult, cdu_id: int, recon_date: date,
) -> None:
    trades = db.execute(select(Trade).where(
        Trade.cdu_id == cdu_id,
        Trade.trade_date == recon_date,
        Trade.is_active.is_(True),
        Trade.is_manual.is_(False),
        Trade.operation_type.in_(("BUY", "SELL", "REPO_OPEN", "REPO_CLOSE")),
    )).scalars().all()
    from services.import_primary.binding import bind_orphan_certificates
    bind_orphan_certificates(db, recon_date)
    certs = [d for d in _docs(db, "CERTIFICATE", cdu_id) if d.doc_date in (None, recon_date)]
    cert_deals: Dict[str, Dict[str, Any]] = {}
    for doc in certs:
        for deal in _meta(doc).get("deals") or []:
            cert_deals.setdefault(str(deal.get("deal_id")), deal)

    items: List[Dict[str, Any]] = []
    matched = fuzzy = missing = 0
    # Exact numbers first: both legs of a REPO have consecutive deal numbers,
    # so a one-digit OCR tolerance must never steal the neighbour leg.
    exact_ids = {(t.deal_id or "").strip() for t in trades} & set(cert_deals)
    unused = set(cert_deals) - exact_ids
    for t in trades:
        deal_id = (t.deal_id or "").strip()
        if not deal_id:
            continue
        found = cert_deals.get(deal_id)
        how = "exact"
        if found is None:
            # OCR may garble up to two digits; the amount must then confirm it
            near = sorted(k for k in unused if _close_enough(k, deal_id, 2)
                          and _amount_in_deal(t.amount_kzt, cert_deals[k]))
            if len(near) == 1:
                found, how = cert_deals[near[0]], f"ocr≈{near[0]}"
                unused.discard(near[0])
        if found is None:
            missing += 1
            items.append({"deal_id": deal_id, "operation": t.operation_type,
                          "amount": t.amount_kzt, "status": "NOT_FOUND"})
            continue
        amount_ok = _amount_in_deal(t.amount_kzt, found)
        if how == "exact":
            matched += 1
        else:
            fuzzy += 1
        items.append({
            "deal_id": deal_id, "operation": t.operation_type, "match": how,
            "amount": t.amount_kzt, "amount_status": "OK" if amount_ok else "CHECK",
            "status": "OK" if (how == "exact" and amount_ok) else "CHECK",
        })

    result.expected_value = len([t for t in trades if t.deal_id])
    result.actual_value = matched + fuzzy
    result.deviation = missing
    if not trades:
        result.status = "OK"
        note = "Сделок за дату нет"
    elif not certs:
        result.status = "PENDING"
        note = "Биржевые свидетельства за дату не загружены"
    elif not cert_deals:
        result.status = "PENDING"
        note = "Не удалось распознать номера сделок в свидетельствах (OCR) — сверьте вручную"
    else:
        result.status = "OK" if missing == 0 and all(i["status"] == "OK" for i in items) else "MISMATCH"
        note = "Свидетельства распознаны OCR: статус CHECK требует визуальной проверки"
    result.source_doc_b_id = certs[0].id if certs else None
    result.details_json = json.dumps({
        "trades_checked": len(trades), "matched": matched, "matched_fuzzy": fuzzy,
        "not_found": missing, "items": items, "note": note,
    }, ensure_ascii=False, default=str)


# ───────── 2. Report ↔ manager reconciliation file ─────────

def recon_document_for(db: Session, cdu_id: int, recon_date: date) -> Optional[SourceDocument]:
    """The latest manager reconciliation file for the CDU and the date."""
    return next((d for d in _docs(db, "RECONCILIATION", cdu_id) if d.doc_date == recon_date), None)


def parsed_recon_document(db: Session, doc: SourceDocument) -> Dict[str, Any]:
    """Parsed content of a reconciliation file; files uploaded before the
    line-by-line parser existed are parsed again from the stored copy."""
    meta = _meta(doc)
    if "securities" not in meta and doc.file_path:
        from pathlib import Path
        from services.import_primary.recon_parser import parse_reconciliation_xlsx
        path = Path(doc.file_path)
        if path.exists():
            fresh = json.loads(json.dumps(parse_reconciliation_xlsx(path), default=str))
            doc.parse_meta_json = json.dumps(fresh, ensure_ascii=False)
            meta = fresh
    return meta


def _recon_rr_vs_holdings(
    db: Session, result: ReconciliationResult, cdu_id: int, recon_date: date,
) -> None:
    """Our portfolio on the date ↔ the manager's reconciliation file, line by line."""
    from services.reconciliation.cdu_statement import compare

    recon_doc = recon_document_for(db, cdu_id, recon_date)
    if recon_doc is None:
        result.status = "PENDING"
        result.details_json = json.dumps({
            "note": "Файл сверки ЧДУ за дату не загружен — загрузите его в «Загрузка документов»",
        }, ensure_ascii=False)
        return
    parsed = parsed_recon_document(db, recon_doc)
    if not parsed.get("securities") and not parsed.get("repos") and not (parsed.get("totals") or {}).get("total"):
        result.status = "ERROR"
        result.source_doc_b_id = recon_doc.id
        result.details_json = json.dumps({
            "note": "В файле сверки не найдены таблицы ЦБ / РЕПО / «Итого активов»",
            "file_warnings": parsed.get("warnings") or [],
        }, ensure_ascii=False)
        return

    report = compare(db, cdu_id, recon_date, parsed)
    report["file"] = {
        "doc_id": recon_doc.id, "file_name": recon_doc.file_name,
        "uploaded_at": recon_doc.uploaded_at.isoformat() if recon_doc.uploaded_at else None,
        "uploaded_by": recon_doc.uploaded_by, "sheet": parsed.get("sheet"),
        "cdu_name_in_file": parsed.get("cdu_name"),
    }
    result.expected_value = report["our_total"]
    result.actual_value = report["cdu_total"]
    result.deviation = report["delta_total"]
    result.tolerance = 1.0
    result.status = report["status"]
    result.source_doc_b_id = recon_doc.id
    result.details_json = json.dumps(report, ensure_ascii=False, default=str)


# ───────── 3. Cash ↔ custodian statement ─────────

def _statement_for(db: Session, cdu_id: int, recon_date: date) -> Optional[SourceDocument]:
    for doc in _docs(db, "STATEMENT_PDF", cdu_id):
        meta = _meta(doc)
        sections = meta.get("sections") or []
        froms = [s.get("period_from") for s in sections if s.get("period_from")]
        tos = [s.get("period_to") for s in sections if s.get("period_to")]
        if froms and tos:
            if min(froms) <= recon_date.isoformat() <= max(tos):
                return doc
        elif doc.doc_date == recon_date:
            return doc
    return None


def _recon_cash_vs_statement(
    db: Session, result: ReconciliationResult, cdu_id: int, recon_date: date,
) -> None:
    internal = _internal_portfolio(db, cdu_id, recon_date)
    doc = _statement_for(db, cdu_id, recon_date)
    if doc is None:
        result.status = "PENDING"
        result.expected_value = internal["cash"] if internal else None
        result.details_json = json.dumps({
            "note": "Выписка кастодиана за дату не загружена (или не привязана к ЧДУ)",
        }, ensure_ascii=False)
        return
    meta = _meta(doc)
    statement_kzt = (meta.get("closing_by_currency") or {}).get("KZT")
    if statement_kzt is None or internal is None:
        result.status = "PENDING"
        result.details_json = json.dumps({"note": "В выписке не найден KZT-счёт или портфель не рассчитан"},
                                         ensure_ascii=False)
        return
    deviation = internal["cash"] - float(statement_kzt)
    result.expected_value = internal["cash"]
    result.actual_value = float(statement_kzt)
    result.deviation = deviation
    result.tolerance = RECON_TOLERANCE_KZT
    result.status = "OK" if abs(deviation) <= RECON_TOLERANCE_KZT else "MISMATCH"
    result.source_doc_b_id = doc.id
    result.details_json = json.dumps({
        "accounts": [s.get("account") for s in meta.get("sections") or [] if s.get("currency") == "KZT"],
        "custodian": meta.get("custodian"),
        "statement_period": [meta.get("sections", [{}])[0].get("period_from"),
                             meta.get("sections", [{}])[0].get("period_to")],
    }, ensure_ascii=False, default=str)


# ───────── 4. NBRK fallback (КФГД_ГГГГММДД) ─────────

def _nbrk_balances(db: Session, recon_date: date) -> List[Dict[str, Any]]:
    """AC rows (balances) of the NBRK daily files dated ``recon_date``."""
    out: List[Dict[str, Any]] = []
    for doc in db.execute(select(SourceDocument).where(
        SourceDocument.doc_type == "NBRK_DAILY", SourceDocument.parse_status == "OK",
    ).order_by(SourceDocument.id.desc())).scalars():
        for acc in _meta(doc).get("accounts") or []:
            if str(acc.get("date") or "")[:10] == recon_date.isoformat():
                out.append({**acc, "doc_id": doc.id})
    return out


def _recon_nbrk_fallback(
    db: Session, result: ReconciliationResult, cdu_id: int, recon_date: date,
) -> None:
    """БП 7.3 B: cash of an NBRK portfolio vs the AC balance of КФГД_ГГГГММДД.

    310138-1 (own assets) ↔ account 28077, 300138-1 (special reserve) ↔ 12831
    (KZT).  The USD account 30872 is shown for information.
    """
    cdu = db.get(CDU, cdu_id)
    if not cdu or cdu.portfolio_type not in ("NBRK_OWN", "NBRK_RESERVE"):
        result.status = "ERROR"
        result.details_json = json.dumps({"error": "NBRK fallback only for NBRK portfolios"})
        return
    portfolio = cdu.portfolio_code or ("310138-1" if cdu.portfolio_type == "NBRK_OWN" else "300138-1")
    balances = [b for b in _nbrk_balances(db, recon_date) if b.get("portfolio") == portfolio]
    kzt = next((b for b in balances if (b.get("currency") or "KZT") == "KZT"), None)
    if kzt is None:
        result.status = "PENDING"
        result.details_json = json.dumps({"note": f"Нет файла НБ РК с остатками (AC) на {recon_date:%d.%m.%Y}"},
                                         ensure_ascii=False)
        return
    # Our cash: the previous account balance rolled forward with the movements
    # of the books (the AC balance of the date itself is the opening cash of
    # the portfolio, so comparing with it would always match).
    from services.calculator.portfolio_calculator import cash_movement_lines
    from models.db_models import CashSnapshot
    prev_date = db.execute(select(CashSnapshot.snapshot_date).where(
        CashSnapshot.cdu_id == cdu_id, CashSnapshot.source == "nbrk_ac",
        CashSnapshot.snapshot_date < recon_date, CashSnapshot.currency == "KZT",
    ).order_by(CashSnapshot.snapshot_date.desc())).scalar()
    if prev_date is None:
        internal = _internal_portfolio(db, cdu_id, recon_date)
        if internal is None:
            result.status = "PENDING"
            result.details_json = json.dumps({"note": "Портфель на дату не рассчитан"}, ensure_ascii=False)
            return
        our_cash, basis_note = internal["cash"], "денег портфеля на дату"
    else:
        prev_total = sum(float(r.amount_kzt if r.amount_kzt is not None else r.amount or 0.0)
                         for r in db.execute(select(CashSnapshot).where(
                             CashSnapshot.cdu_id == cdu_id, CashSnapshot.source == "nbrk_ac",
                             CashSnapshot.snapshot_date == prev_date, CashSnapshot.currency == "KZT",
                         )).scalars())
        moves = [(m, v) for m, v in cash_movement_lines(db, cdu_id, recon_date, prev_date)
                 if (m.currency or "KZT").upper() == "KZT"]
        our_cash = prev_total + sum(v for _, v in moves)
        basis_note = f"остаток {prev_date:%d.%m.%Y} + движения ({len(moves)})"
    statement = float(kzt.get("balance") or 0.0)
    internal = {"cash": our_cash}
    deviation = internal["cash"] - statement
    from services.formulas import params              # БП 7.3: ≤ 1 KZT or ≤ 0.01 % (editable)
    params.refresh(db, force=True)
    tolerance = max(float(params.get("nbrk_recon_abs")), abs(statement) * float(params.get("nbrk_recon_pct")) / 100.0)
    result.expected_value = internal["cash"]
    result.actual_value = statement
    result.deviation = deviation
    result.tolerance = tolerance
    result.status = "OK" if abs(deviation) <= tolerance else "MISMATCH"
    result.source_doc_b_id = kzt.get("doc_id")
    result.details_json = json.dumps({
        "account": kzt.get("account"), "counterparty": kzt.get("counterparty"),
        "nbrk_balance_kzt": statement, "outflow": kzt.get("outflow"), "inflow": kzt.get("inflow"),
        "our_basis": basis_note,
        "other_accounts": [b for b in balances if b is not kzt],
    }, ensure_ascii=False, default=str)


def reconcile_all_for_date(db: Session, recon_date: date) -> List[ReconciliationResult]:
    """Run all reconciliation types for every active CDU."""
    cdus = db.execute(select(CDU).where(CDU.is_active == True)).scalars().all()  # noqa: E712
    results: List[ReconciliationResult] = []
    for cdu in cdus:
        for rtype in ("trade_vs_cert", "rr_vs_holdings", "cash_vs_statement", "nbrk_fallback"):
            if rtype == "nbrk_fallback" and cdu.portfolio_type not in ("NBRK_OWN", "NBRK_RESERVE"):
                continue
            res = run_reconciliation(db, cdu.id, recon_date, rtype)
            results.append(res)
    return results
