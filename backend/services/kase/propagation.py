"""Apply freshly loaded KASE prices to dependent portfolio data."""
from __future__ import annotations

from datetime import date
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from models.db_models import (
    BondLot,
    GeneratedReport,
    KasePrice,
    PortfolioPosition,
    PortfolioSummary,
    RepoLot,
    Trade,
)
from services.calculator.constants import CATEGORY_ORDER
from services.holdings_sync import sync_holdings
from services.kase.reconciler import reconcile_prices
from services.kase.trade_price_flagger import apply_kase_prices_to_trades
from services.report import generate_pdf_report, generate_xlsx_report


def _kase_index(rows: list[KasePrice]) -> Dict[str, KasePrice]:
    idx: Dict[str, KasePrice] = {}
    for row in rows:
        if row.instrument_code:
            idx[row.instrument_code.upper()] = row
        if row.isin:
            idx[row.isin.upper()] = row
    return idx


def _lookup_kase(
    idx: Dict[str, KasePrice],
    instrument_code: Optional[str],
    isin: Optional[str],
) -> Optional[KasePrice]:
    if instrument_code:
        found = idx.get(instrument_code.upper())
        if found:
            return found
    if isin:
        return idx.get(isin.upper())
    return None


def _repriced_market_value(lot: BondLot, price: float) -> float:
    face = float(lot.face_value_current or lot.quantity_current or 0.0)
    accrued = float(lot.accrued_interest or 0.0)
    return face * price / 100.0 + accrued


def _weighted(values: list[tuple[Optional[float], float]]) -> Optional[float]:
    weight = sum(w for v, w in values if v is not None and w)
    if not weight:
        return None
    return sum(float(v) * w for v, w in values if v is not None and w) / weight


def _reprice_bond_lots(
    db: Session,
    *,
    report_date: date,
    kase_idx: Dict[str, KasePrice],
) -> int:
    updated = 0
    lots = db.execute(select(BondLot).where(
        BondLot.valuation_date == report_date,
    )).scalars().all()
    for lot in lots:
        kp = _lookup_kase(kase_idx, lot.instrument_code, lot.isin)
        if not kp or kp.close_price is None:
            continue
        lot.market_price = kp.close_price
        lot.market_value = _repriced_market_value(lot, float(kp.close_price))
        lot.total_value = lot.market_value
        if kp.ytm is not None:
            lot.ytm = kp.ytm
        if kp.duration is not None:
            lot.duration = kp.duration
        updated += 1
    return updated


def _rebuild_summary_from_lots(db: Session, *, report_date: date) -> dict[str, int]:
    positions_updated = 0
    summaries_updated = 0

    summaries = db.execute(select(PortfolioSummary).where(
        PortfolioSummary.summary_date == report_date,
    )).scalars().all()

    for summary in summaries:
        positions = db.execute(select(PortfolioPosition).where(
            PortfolioPosition.cdu_id == summary.cdu_id,
            PortfolioPosition.position_date == report_date,
        )).scalars().all()
        pos_by_cat = {
            p.instrument_category: p
            for p in positions
            if p.instrument_code is None
        }

        for cat in CATEGORY_ORDER:
            pos = pos_by_cat.get(cat)
            if not pos:
                continue
            if cat == "REVERSE_REPO":
                repo_lots = db.execute(select(RepoLot).where(
                    RepoLot.cdu_id == summary.cdu_id,
                    RepoLot.valuation_date == report_date,
                )).scalars().all()
                if not repo_lots:
                    continue
                mv = sum(float(l.market_value or l.close_value or l.face_value or 0.0) for l in repo_lots)
                ytm = _weighted([
                    (l.ytm if l.ytm is not None else l.repo_rate_pct, float(l.market_value or l.close_value or l.face_value or 0.0))
                    for l in repo_lots
                ])
                duration = _weighted([
                    (
                        l.duration if l.duration is not None else ((l.term_days / 365.0) if l.term_days else None),
                        float(l.market_value or l.close_value or l.face_value or 0.0),
                    )
                    for l in repo_lots
                ])
            else:
                bond_lots = db.execute(select(BondLot).where(
                    BondLot.cdu_id == summary.cdu_id,
                    BondLot.valuation_date == report_date,
                    BondLot.category == cat,
                )).scalars().all()
                if not bond_lots:
                    continue
                mv = sum(float(l.market_value or l.total_value or l.face_value_current or 0.0) for l in bond_lots)
                ytm = _weighted([
                    (l.ytm, float(l.market_value or l.total_value or l.face_value_current or 0.0))
                    for l in bond_lots
                ])
                duration = _weighted([
                    (l.duration, float(l.market_value or l.total_value or l.face_value_current or 0.0))
                    for l in bond_lots
                ])

            old_mv = float(pos.market_value_current or 0.0)
            pos.market_value_current = mv
            pos.daily_change = mv - float(pos.market_value_prev or 0.0)
            pos.ytm = ytm
            pos.duration = duration
            if abs(old_mv - mv) > 0.000001:
                positions_updated += 1

        total = sum(float(p.market_value_current or 0.0) for p in positions)
        prev_summary = db.execute(select(PortfolioSummary).where(
            PortfolioSummary.cdu_id == summary.cdu_id,
            PortfolioSummary.summary_date < report_date,
        ).order_by(PortfolioSummary.summary_date.desc())).scalars().first()
        summary.total_mv_current = total
        summary.total_mv_prev = prev_summary.total_mv_current if prev_summary else summary.total_mv_prev
        summary.total_daily_change = total - float(summary.total_mv_prev or 0.0)

        weight_cats = {"GOV_BONDS", "REVERSE_REPO", "MFO_BONDS", "AGENCY_BONDS"}
        weighted_positions = [p for p in positions if p.instrument_category in weight_cats]
        weight = sum(float(p.market_value_current or 0.0) for p in weighted_positions)
        if weight:
            summary.ytm_weighted = sum(
                float(p.ytm or 0.0) * float(p.market_value_current or 0.0)
                for p in weighted_positions
            ) / weight
            summary.duration_weighted = sum(
                float(p.duration or 0.0) * float(p.market_value_current or 0.0)
                for p in weighted_positions
            ) / weight

        for p in positions:
            p.pct_of_total = float(p.market_value_current or 0.0) / total if total else 0.0

        summaries_updated += 1

    fund_total = sum(float(s.total_mv_current or 0.0) for s in summaries)
    for summary in summaries:
        summary.cdu_share_pct = float(summary.total_mv_current or 0.0) / fund_total if fund_total else 0.0

    return {"portfolio_positions": positions_updated, "portfolio_summaries": summaries_updated}


def _reconcile_trades(db: Session, *, report_date: date, actor: Optional[str]) -> dict[str, int]:
    cdu_ids = [
        row[0]
        for row in db.execute(select(Trade.cdu_id).where(
            Trade.trade_date == report_date,
            Trade.is_active == True,  # noqa: E712
        ).distinct()).all()
    ]
    total = {"checked": 0, "flagged": 0, "missing_kase": 0, "not_applicable": 0}
    for cdu_id in cdu_ids:
        counters = apply_kase_prices_to_trades(
            db,
            cdu_id=cdu_id,
            trade_date=report_date,
            actor=actor,
        )
        for key in total:
            total[key] += counters.get(key, 0)
    return total


def _regenerate_mutable_reports(db: Session, *, report_date: date) -> dict[str, int]:
    regenerated = 0
    skipped_locked = 0
    rows = db.execute(select(GeneratedReport).where(
        GeneratedReport.report_date == report_date,
    )).scalars().all()
    for row in rows:
        if row.status not in {"draft", "rejected"}:
            skipped_locked += 1
            continue
        if row.report_type == "DAILY_PDF":
            out = generate_pdf_report(db, report_date, settings.report_path)
        else:
            out = generate_xlsx_report(db, report_date, settings.report_path)
        row.file_path = str(out)
        row.version = (row.version or 1) + 1
        row.status = "draft"
        regenerated += 1
    return {"regenerated": regenerated, "skipped_locked": skipped_locked}


def apply_kase_update(
    db: Session,
    *,
    report_date: date,
    actor: Optional[str] = None,
    regenerate_reports: bool = True,
) -> dict:
    """Propagate KASE prices into trades, holdings, summaries and reports.

    The caller owns the transaction commit.
    """
    kase_rows = list(db.execute(select(KasePrice).where(
        KasePrice.trade_date == report_date,
    )).scalars().all())
    kase_idx = _kase_index(kase_rows)

    bond_lots = _reprice_bond_lots(db, report_date=report_date, kase_idx=kase_idx)
    summary_updates = _rebuild_summary_from_lots(db, report_date=report_date)
    trade_check = _reconcile_trades(db, report_date=report_date, actor=actor)
    reconciliation_rows = reconcile_prices(db, report_date, commit=False)
    holdings = sync_holdings(db, actor=actor)
    reports = (
        _regenerate_mutable_reports(db, report_date=report_date)
        if regenerate_reports else {"regenerated": 0, "skipped_locked": 0}
    )
    db.flush()

    return {
        "kase_rows": len(kase_rows),
        "bond_lots_repriced": bond_lots,
        "portfolio_positions_updated": summary_updates["portfolio_positions"],
        "portfolio_summaries_updated": summary_updates["portfolio_summaries"],
        "price_reconciliation_rows": len(reconciliation_rows),
        "trade_price_check": trade_check,
        "holdings_sync": holdings,
        "reports": reports,
    }
