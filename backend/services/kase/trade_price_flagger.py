"""Trade-level price reconciliation against KASE market valuations.

Pipeline (per upload, per CDU, per trade_date)
==============================================

1. Pre-load all ``KasePrice`` rows for ``trade_date`` once.
2. For every active ``Trade`` of the CDU on that date that has a non-zero
   ``price_original`` and a recognisable ``instrument_code``/``isin``:
     * Resolve the matching KASE quote (by ``instrument_code`` first,
       fall back to ``isin``).
     * ``diff_pct = |price_original - price_kase| / price_kase``
     * If ``diff_pct > tolerance``:
         - ``price_flag = True``
         - ``price_final = price_kase``           (← KASE wins)
         - emit an ``AuditLog`` row with the before/after values
       Otherwise:
         - ``price_flag = False``
         - ``price_final = price_original``
3. ``price_kase`` and ``price_checked_at`` are always stored, even when no
   replacement happens — this lets the UI distinguish "checked, OK" from
   "not checked yet".

The function returns a small ``Counters`` dict so the caller (upload route,
nightly job, manual recompute) can surface the result.

It does NOT commit — the caller manages the transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from models.db_models import KasePrice, Trade
from services.audit import write_audit


@dataclass
class PriceFlagResult:
    trade_id: int
    instrument_code: Optional[str]
    isin: Optional[str]
    price_original: Optional[float]
    price_kase: Optional[float]
    price_final: Optional[float]
    diff_pct: Optional[float]
    flagged: bool


def _build_kase_index(rows: Iterable[KasePrice]) -> Dict[str, KasePrice]:
    """Index KASE rows by instrument_code AND isin so trade lookups can hit
    either identifier with the same dict."""
    idx: Dict[str, KasePrice] = {}
    for kp in rows:
        if kp.instrument_code:
            idx.setdefault(kp.instrument_code.upper(), kp)
        if kp.isin:
            idx.setdefault(kp.isin.upper(), kp)
    return idx


def _lookup_kase(
    idx: Dict[str, KasePrice],
    instrument_code: Optional[str],
    isin: Optional[str],
) -> Optional[KasePrice]:
    if instrument_code and instrument_code.upper() in idx:
        return idx[instrument_code.upper()]
    if isin and isin.upper() in idx:
        return idx[isin.upper()]
    return None


# Operation types where market_price is meaningful for reconciliation.
# REPO/DEPOSIT/FX/CASH/COUPON/REDEMPTION operate on amounts, not on price/100.
_PRICE_BEARING_OPS = {"BUY", "SELL"}


def apply_kase_prices_to_trades(
    db: Session,
    *,
    cdu_id: int,
    trade_date: date,
    tolerance: Optional[float] = None,
    actor: Optional[str] = None,
) -> Dict[str, int]:
    """Compare each trade's CDU price to KASE; replace + flag on deviation.

    Parameters
    ----------
    db:
        SQLAlchemy session (caller commits).
    cdu_id, trade_date:
        Scope of the comparison.
    tolerance:
        Fraction of price (``0.0001`` = 0.01% = 1 bp). Defaults to
        ``settings.price_tolerance_pct``.
    actor:
        Username recorded in AuditLog rows. ``None`` for system jobs.

    Returns
    -------
    Dict with counters: ``checked``, ``flagged``, ``missing_kase``,
    ``not_applicable``.
    """
    tol = tolerance if tolerance is not None else settings.price_tolerance_pct
    if tol < 0:
        tol = 0.0

    trades: List[Trade] = list(db.execute(
        select(Trade).where(
            Trade.cdu_id == cdu_id,
            Trade.trade_date == trade_date,
            Trade.is_active == True,  # noqa: E712
        )
    ).scalars())

    if not trades:
        return {"checked": 0, "flagged": 0, "missing_kase": 0, "not_applicable": 0}

    kase_rows = list(db.execute(
        select(KasePrice).where(KasePrice.trade_date == trade_date)
    ).scalars())
    kase_idx = _build_kase_index(kase_rows)

    now = datetime.utcnow()
    counters = {"checked": 0, "flagged": 0, "missing_kase": 0, "not_applicable": 0}

    for trade in trades:
        if (trade.operation_type or "").upper() not in _PRICE_BEARING_OPS:
            counters["not_applicable"] += 1
            continue
        price_original = trade.price_original
        if price_original is None:
            price_original = trade.market_price
        if price_original is None or price_original == 0:
            counters["not_applicable"] += 1
            continue

        kp = _lookup_kase(kase_idx, trade.instrument_code, trade.isin)
        trade.price_original = price_original
        trade.price_checked_at = now

        if kp is None or kp.close_price is None or kp.close_price == 0:
            # No KASE reference — keep original, do not flag.
            trade.price_kase = kp.close_price if kp else None
            trade.price_final = price_original
            trade.price_flag = False
            trade.price_diff_pct = None
            counters["missing_kase"] += 1
            continue

        diff_pct = abs(price_original - kp.close_price) / abs(kp.close_price)
        trade.price_kase = kp.close_price
        trade.price_diff_pct = diff_pct
        counters["checked"] += 1

        if diff_pct > tol:
            trade.price_flag = True
            trade.price_final = kp.close_price
            counters["flagged"] += 1
            write_audit(
                db, user=actor, action="PRICE_REPLACED_FROM_KASE",
                entity="Trade", entity_id=trade.id,
                details={
                    "instrument_code": trade.instrument_code,
                    "isin": trade.isin,
                    "trade_date": trade_date.isoformat(),
                    "price_original": price_original,
                    "price_kase": kp.close_price,
                    "price_final": kp.close_price,
                    "diff_pct": round(diff_pct, 8),
                    "tolerance_pct": tol,
                    "kase_source": kp.source,
                },
            )
        else:
            trade.price_flag = False
            trade.price_final = price_original

    logger.info(
        f"Price flagger cdu={cdu_id} date={trade_date} tol={tol}: {counters}"
    )
    return counters
