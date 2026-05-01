"""Auto-reconciliation engine — Phase B6.

Reconciliation types:
  1. trade_vs_cert      — Trade Report ↔ Exchange Certificate (by deal_id, amount ±0.01)
  2. rr_vs_holdings     — Risk Report / internal ledger ↔ Holdings report (cash + securities + repo + ar + total)
  3. cash_vs_statement  — Cash snapshot ↔ PDF custodian statement (ending balance ±0.01 KZT/USD)
  4. nbrk_fallback      — Cash ↔ КФГД_ГГГГММДД (MODULE=AC, by account)

Tolerances:
  ±0.01 KZT / ±0.01 USD / ±0.000001 price.
"""
from __future__ import annotations
from datetime import date
from typing import Any, Dict, List, Optional
import json
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from models.db_models import (
    CDU, CashSnapshot, PortfolioPosition, PriceReconciliation,
    ReconciliationResult, RepoLot, Trade,
)
from services.calculator.constants import RECON_TOLERANCE_KZT, RECON_TOLERANCE_USD


def run_reconciliation(
    db: Session,
    cdu_id: int,
    recon_date: date,
    recon_type: str,
    *,
    details: Optional[Dict[str, Any]] = None,
) -> ReconciliationResult:
    """Run a single reconciliation check and persist the result."""
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
        result.details_json = json.dumps({"error": str(exc)})

    db.commit()
    return result


# ───────── 1. Trade Report ↔ Certificate (by deal_id) ─────────

def _recon_trade_vs_cert(
    db: Session, result: ReconciliationResult, cdu_id: int, recon_date: date,
) -> None:
    trades = db.execute(select(Trade).where(
        Trade.cdu_id == cdu_id,
        Trade.trade_date == recon_date,
        Trade.operation_type.in_(("BUY", "SELL", "REPO_OPEN", "REPO_CLOSE")),
    )).scalars().all()

    matched = 0
    mismatched = 0
    details: List[Dict] = []
    for t in trades:
        if not t.deal_id:
            continue
        # placeholder: in real life compare with parsed certificate amounts
        details.append({
            "deal_id": t.deal_id,
            "trade_amount": t.amount_kzt,
            "status": "PENDING",
            "note": "Certificate data not linked yet",
        })
    result.expected_value = len(trades)
    result.actual_value = matched
    result.deviation = len(trades) - matched
    result.status = "MATCHED" if mismatched == 0 and len(trades) == matched else "MISMATCH"
    result.details_json = json.dumps({"trades_checked": len(trades), "matched": matched, "items": details})


# ───────── 2. RR / Ledger ↔ Holdings report ─────────

def _recon_rr_vs_holdings(
    db: Session, result: ReconciliationResult, cdu_id: int, recon_date: date,
) -> None:
    # Cash from internal snapshot
    cash_rows = db.execute(select(CashSnapshot).where(
        CashSnapshot.cdu_id == cdu_id,
        CashSnapshot.snapshot_date == recon_date,
    )).scalars().all()
    internal_cash = sum(r.amount for r in cash_rows if r.amount)

    # Securities from PortfolioPosition (holdings report import)
    pos_rows = db.execute(select(PortfolioPosition).where(
        PortfolioPosition.cdu_id == cdu_id,
        PortfolioPosition.position_date == recon_date,
    )).scalars().all()
    internal_securities = sum(r.nominal_volume or 0 for r in pos_rows)

    # REPO open lots
    repo_rows = db.execute(select(RepoLot).where(
        RepoLot.cdu_id == cdu_id,
        RepoLot.trade_date <= recon_date,
        RepoLot.close_date.is_(None),
    )).scalars().all()
    internal_repo = sum(r.face_value or 0 for r in repo_rows)

    total_internal = internal_cash + internal_securities + internal_repo

    result.expected_value = total_internal
    result.actual_value = total_internal  # placeholder until holdings totals parsed
    result.deviation = 0.0
    result.status = "PENDING"
    result.details_json = json.dumps({
        "cash": internal_cash,
        "securities": internal_securities,
        "repo": internal_repo,
        "total": total_internal,
        "note": "Holdings totals not yet parsed — manual check required",
    })


# ───────── 3. Cash ↔ PDF Statement ─────────

def _recon_cash_vs_statement(
    db: Session, result: ReconciliationResult, cdu_id: int, recon_date: date,
) -> None:
    cash_rows = db.execute(select(CashSnapshot).where(
        CashSnapshot.cdu_id == cdu_id,
        CashSnapshot.snapshot_date == recon_date,
    )).scalars().all()

    details: List[Dict] = []
    all_matched = True
    for cr in cash_rows:
        tol = RECON_TOLERANCE_USD if cr.currency == "USD" else RECON_TOLERANCE_KZT
        # placeholder: statement balances not yet linked
        details.append({
            "currency": cr.currency,
            "expected": cr.amount,
            "actual": None,
            "tolerance": tol,
            "status": "PENDING",
        })
    result.status = "PENDING"
    result.details_json = json.dumps({"cash_items": details, "note": "Link statement parser to populate actual"})


# ───────── 4. NBRK fallback (КФГД_ГГГГММДД) ─────────

def _recon_nbrk_fallback(
    db: Session, result: ReconciliationResult, cdu_id: int, recon_date: date,
) -> None:
    cdu = db.get(CDU, cdu_id)
    if not cdu or cdu.portfolio_type not in ("NBRK_OWN", "NBRK_RESERVE"):
        result.status = "ERROR"
        result.details_json = json.dumps({"error": "NBRK fallback only for NBRK portfolios"})
        return

    # placeholder: parse КФГД_ГГГГММДД.xlsx MODULE=AC and compare
    result.status = "PENDING"
    result.details_json = json.dumps({"note": "NBRK AC module parser not yet implemented"})


def reconcile_all_for_date(db: Session, recon_date: date) -> List[ReconciliationResult]:
    """Run all reconciliation types for every active CDU."""
    cdus = db.execute(select(CDU).where(CDU.is_active == True)).scalars().all()
    results: List[ReconciliationResult] = []
    for cdu in cdus:
        for rtype in ("trade_vs_cert", "rr_vs_holdings", "cash_vs_statement", "nbrk_fallback"):
            if rtype == "nbrk_fallback" and cdu.portfolio_type not in ("NBRK_OWN", "NBRK_RESERVE"):
                continue
            res = run_reconciliation(db, cdu.id, recon_date, rtype)
            results.append(res)
    return results
