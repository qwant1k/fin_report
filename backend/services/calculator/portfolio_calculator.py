"""Calculate CMV, Daily Change, YTM, Duration, % of total and limits.

Glossary
--------
CMV  — Current Market Value
MV_T1 — Market Value yesterday
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.db_models import (
    AccountReceivable,
    Alert,
    BondLot,
    CashBalance,
    CashSnapshot,
    CDU,
    CDULimit,
    KasePrice,
    MBMIndex,
    MVSnapshot,
    PortfolioPosition,
    PortfolioSummary,
    RawTrade,
    RepoLot,
)

from .constants import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    DEFAULT_LIMITS,
    DURATION_LOWER_OFFSET,
    DURATION_UPPER_OFFSET,
)
from .limit_checker import check_limit_status
from .position_builder import PositionAggregate, build_positions


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def _cmv_for_position(p: PositionAggregate, kase_prices: Dict[str, KasePrice]) -> float:
    """Return CMV for a position."""
    if p.instrument_category == "REVERSE_REPO":
        # Сумма выкупа = гарантированный возврат при закрытии РЕПО
        if p.repo_buyback_sum:
            return p.repo_buyback_sum
        return p.repo_open_sum
    # Bonds: nominal × price/100 + НКД (price priority: KASE > last trade)
    price = None
    if p.instrument_code and p.instrument_code in kase_prices:
        price = kase_prices[p.instrument_code].close_price
    if price is None:
        price = p.last_price
    if price is None:
        # fallback: нет цены — стоимость по номиналу
        return p.nominal_volume + (p.accrued_interest or 0.0)
    return p.nominal_volume * price / 100.0 + (p.accrued_interest or 0.0)


def _ytm_for_position(p: PositionAggregate, kase_prices: Dict[str, KasePrice]) -> Optional[float]:
    if p.instrument_code and p.instrument_code in kase_prices:
        kp = kase_prices[p.instrument_code]
        if kp.ytm is not None:
            return kp.ytm
    return p.ytm


def _duration_for_position(p: PositionAggregate, kase_prices: Dict[str, KasePrice]) -> Optional[float]:
    if p.instrument_category == "REVERSE_REPO":
        return p.duration
    if p.instrument_code and p.instrument_code in kase_prices:
        kp = kase_prices[p.instrument_code]
        if kp.duration is not None:
            return kp.duration
    return p.duration


def _load_rr_snapshot_categories(
    db: Session, cdu_id: int, report_date: date
) -> Dict[str, dict]:
    """Считать категориальные агрегаты из RR-снимков (BondLot + RepoLot) на дату.

    Возвращает ``{category: {"mv": float, "ytm": float|None, "duration": float|None,
    "lots": int}}`` — значения уже усреднены (взвешены по market_value).

    Используется в ``_calculate_cdu`` как авторитетный источник позиций когда
    Risk Report импортирован, но Trade Report (RawTrade) на эту дату нет.
    """
    out: Dict[str, dict] = {}

    # ── BondLot per category (GOV_BONDS, AGENCY_BONDS, MFO_BONDS, FOREIGN_BONDS) ──
    bond_rows = db.execute(select(BondLot).where(
        BondLot.cdu_id == cdu_id,
        BondLot.valuation_date == report_date,
    )).scalars().all()
    for lot in bond_rows:
        cat = lot.category
        if not cat:
            continue
        mv = lot.market_value or lot.total_value or lot.face_value_current or 0.0
        if not mv:
            continue
        bucket = out.setdefault(cat, {"mv": 0.0, "ytm_w": 0.0, "ytm_weight": 0.0,
                                     "dur_w": 0.0, "dur_weight": 0.0, "lots": 0})
        bucket["mv"] += mv
        bucket["lots"] += 1
        if lot.ytm is not None:
            bucket["ytm_w"] += lot.ytm * mv
            bucket["ytm_weight"] += mv
        if lot.duration is not None:
            bucket["dur_w"] += lot.duration * mv
            bucket["dur_weight"] += mv

    # ── RepoLot → REVERSE_REPO (только открытые на report_date) ──
    repo_rows = db.execute(select(RepoLot).where(
        RepoLot.cdu_id == cdu_id,
        RepoLot.valuation_date == report_date,
    )).scalars().all()
    for lot in repo_rows:
        # Открытое РЕПО: ещё не закрылось к report_date
        if lot.close_date and lot.close_date <= report_date:
            continue
        mv = lot.market_value or lot.close_value or lot.face_value or 0.0
        if not mv:
            continue
        bucket = out.setdefault("REVERSE_REPO", {"mv": 0.0, "ytm_w": 0.0, "ytm_weight": 0.0,
                                                  "dur_w": 0.0, "dur_weight": 0.0, "lots": 0})
        bucket["mv"] += mv
        bucket["lots"] += 1
        rate = lot.repo_rate_pct
        if rate is not None:
            bucket["ytm_w"] += rate * mv
            bucket["ytm_weight"] += mv
        if lot.term_days:
            dur = lot.term_days / 365.0
            bucket["dur_w"] += dur * mv
            bucket["dur_weight"] += mv

    # ── Усредняем ──
    result: Dict[str, dict] = {}
    for cat, b in out.items():
        result[cat] = {
            "mv": b["mv"],
            "ytm": (b["ytm_w"] / b["ytm_weight"]) if b["ytm_weight"] else None,
            "duration": (b["dur_w"] / b["dur_weight"]) if b["dur_weight"] else None,
            "lots": b["lots"],
        }
    return result


# ─────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────

def calculate_for_date(db: Session, report_date: date, *, recalculate: bool = False) -> dict:
    """Build all PortfolioPosition + PortfolioSummary rows for `report_date`.

    Returns counters: {"cdus_processed": int, "breaches": int}.
    """
    report_summaries = db.execute(select(PortfolioSummary).where(
        PortfolioSummary.summary_date == report_date,
    )).scalars().all()
    report_positions = db.execute(select(PortfolioPosition).where(
        PortfolioPosition.position_date == report_date,
        PortfolioPosition.notes == "rr_report_import",
    )).scalars().all()
    if recalculate and report_summaries and report_positions:
        # The first Risk Report sheet is the authoritative dashboard view.
        # Keep it intact when a user presses "Recalculate" after import.
        return {
            "cdus_processed": len({s.cdu_id for s in report_summaries}),
            "breaches": 0,
        }

    if recalculate:
        db.query(PortfolioPosition).filter_by(position_date=report_date).delete()
        db.query(PortfolioSummary).filter_by(summary_date=report_date).delete()
        db.query(Alert).filter_by(alert_date=report_date).delete()
        db.commit()

    cdus = db.query(CDU).filter_by(is_active=True).all()
    cdus_processed = 0
    total_breaches = 0
    fund_total_cmv = 0.0
    summaries: List[PortfolioSummary] = []

    # Pre-load KASE prices for the date
    kase_rows = db.query(KasePrice).filter_by(trade_date=report_date).all()
    kase_prices: Dict[str, KasePrice] = {kp.instrument_code: kp for kp in kase_rows}

    # Pre-load MBM benchmark
    mbm = db.query(MBMIndex).filter(MBMIndex.index_date <= report_date).order_by(
        MBMIndex.index_date.desc()).first()

    # ── Pass 1: build per-CDU portfolios, compute totals, persist positions ──
    cdu_summaries: List[Tuple[CDU, PortfolioSummary, List[PortfolioPosition]]] = []

    for cdu in cdus:
        positions, summary = _calculate_cdu(
            db=db,
            cdu=cdu,
            report_date=report_date,
            kase_prices=kase_prices,
            mbm=mbm,
        )
        # Skip CDUs with zero portfolio (no trades, no cash, no receivables)
        if summary.total_mv_current == 0 and not any(
            (p.market_value_current or 0.0) != 0.0 for p in positions
        ):
            continue
        cdu_summaries.append((cdu, summary, positions))
        fund_total_cmv += summary.total_mv_current

    # ── Pass 2: cdu_share_pct, % of total inside CDU, persist, alerts ──
    for cdu, summary, positions in cdu_summaries:
        # доля ЧДУ в Фонде
        summary.cdu_share_pct = (summary.total_mv_current / fund_total_cmv) if fund_total_cmv else 0.0

        # лимиты per category
        limits = _load_limits(db, cdu.id, report_date)

        for pos in positions:
            # % of total внутри ЧДУ
            pos.pct_of_total = (pos.market_value_current / summary.total_mv_current) if summary.total_mv_current else 0.0
            mn, mx = limits.get(pos.instrument_category, (0.0, 1.0))
            hard, soft = check_limit_status(pos.pct_of_total, mn, mx)
            pos.hard_limit_status = hard
            pos.soft_limit_status = soft
            pos.free_limit_mln = (summary.total_mv_current * mx - pos.market_value_current) / 1_000_000.0

            db.add(pos)

            if hard == "breach" or soft == "breach":
                db.add(Alert(
                    alert_date=report_date,
                    cdu_id=cdu.id,
                    alert_type="LIMIT_BREACH",
                    severity="CRITICAL" if hard == "breach" else "WARN",
                    message=(
                        f"{cdu.short_name}: {CATEGORY_LABELS.get(pos.instrument_category, pos.instrument_category)} "
                        f"{pos.pct_of_total*100:.2f}% не в диапазоне [{mn*100:.2f}%; {mx*100:.2f}%]"
                    ),
                ))
                total_breaches += 1

        # duration vs benchmark
        if summary.benchmark_duration is not None:
            lo = summary.benchmark_duration + DURATION_LOWER_OFFSET
            hi = summary.benchmark_duration + DURATION_UPPER_OFFSET
            summary.duration_status = "ok" if lo <= summary.duration_weighted <= hi else "breach"
            if summary.duration_status == "breach":
                db.add(Alert(
                    alert_date=report_date,
                    cdu_id=cdu.id,
                    alert_type="DURATION_BREACH",
                    severity="WARN",
                    message=(
                        f"{cdu.short_name}: дюрация {summary.duration_weighted:.2f} вне диапазона "
                        f"[{lo:.2f}; {hi:.2f}] (benchmark={summary.benchmark_duration:.2f})"
                    ),
                ))
                total_breaches += 1

        db.add(summary)
        cdus_processed += 1

    db.commit()

    # Best-effort digest email (does nothing if SMTP is not configured)
    if total_breaches:
        _send_breach_digest(db, report_date, total_breaches)

    return {"cdus_processed": cdus_processed, "breaches": total_breaches}


def _send_breach_digest(db: Session, report_date: date, total_breaches: int) -> None:
    from services import email_service  # local import to avoid cycles
    from loguru import logger
    if not email_service.is_configured():
        return
    try:
        rows = db.execute(select(Alert).where(Alert.alert_date == report_date)).scalars().all()
        cdus = db.query(CDU).filter(CDU.contact_email.is_not(None), CDU.is_active.is_(True)).all()
        if not cdus or not rows:
            return
        body_lines = [f"За {report_date} зафиксировано {total_breaches} нарушений лимитов:\n"]
        for r in rows:
            body_lines.append(f"  • [{r.severity}] {r.message}")
        body = "\n".join(body_lines)
        recipients = [c.contact_email for c in cdus if c.contact_email]
        email_service.send_mail(
            to=recipients,
            subject=f"[KDIF] Сводка нарушений за {report_date.strftime('%d.%m.%Y')}",
            body=body,
        )
    except Exception as exc:
        logger.warning(f"Digest email skipped: {exc!r}")


# ─────────────────────────────────────────────────────────────────────────
# Per-CDU calculation
# ─────────────────────────────────────────────────────────────────────────

def _calculate_cdu(
    *,
    db: Session,
    cdu: CDU,
    report_date: date,
    kase_prices: Dict[str, KasePrice],
    mbm: Optional[MBMIndex],
) -> Tuple[List[PortfolioPosition], PortfolioSummary]:
    """Compute positions + summary for a single CDU on a single date."""
    # raw trades (за все даты ≤ report_date — для сохранения открытых РЕПО и накопленных позиций)
    raw_rows = db.execute(
        select(RawTrade).where(
            RawTrade.cdu_id == cdu.id,
            RawTrade.trade_date <= report_date,
            RawTrade.status.in_(("+", "M")),
        )
    ).scalars().all()

    aggregates = build_positions(raw_rows, cdu_id=cdu.id, report_date=report_date)

    # Cash balance — prefer imported daily snapshots, fallback to legacy balances.
    cash_snapshot = db.execute(select(CashSnapshot).where(
        CashSnapshot.cdu_id == cdu.id,
        CashSnapshot.snapshot_date <= report_date,
    ).order_by(CashSnapshot.snapshot_date.desc())).scalars().first()
    cash = db.execute(select(CashBalance).where(
        CashBalance.cdu_id == cdu.id,
        CashBalance.balance_date <= report_date,
    ).order_by(CashBalance.balance_date.desc())).scalars().first()

    # Receivables — суммируем открытые
    receivable_sum = db.execute(select(AccountReceivable).where(
        AccountReceivable.cdu_id == cdu.id,
        AccountReceivable.record_date <= report_date,
        AccountReceivable.status == "OPEN",
    )).scalars().all()
    receivable_total = sum((ar.amount or 0.0) for ar in receivable_sum)

    # ── собираем category-level rows ──
    category_rows: Dict[str, PortfolioPosition] = {}

    for cat in CATEGORY_ORDER:
        category_rows[cat] = PortfolioPosition(
            cdu_id=cdu.id,
            position_date=report_date,
            instrument_code=None,
            instrument_category=cat,
            instrument_name=CATEGORY_LABELS.get(cat),
            nominal_volume=0.0,
            current_price=None,
            accrued_interest=0.0,
            market_value_current=0.0,
            market_value_prev=0.0,
            daily_change=0.0,
            ytm=None,
            duration=None,
        )

    # cash
    if cash_snapshot:
        category_rows["CASH"].market_value_current = cash_snapshot.amount_kzt or cash_snapshot.amount or 0.0
    elif cash:
        category_rows["CASH"].market_value_current = cash.amount or 0.0

    # receivables
    category_rows["RECEIVABLES"].market_value_current = receivable_total

    # ── RR-snapshot (BondLot + RepoLot) — авторитет на report_date ──
    # Если за дату есть импортированные лоты, ИХ категории (GOV_BONDS,
    # AGENCY_BONDS, MFO_BONDS, FOREIGN_BONDS, REVERSE_REPO) считаются
    # достоверным срезом портфеля и перекрывают агрегаты из RawTrade.
    rr_snap = _load_rr_snapshot_categories(db, cdu.id, report_date)
    rr_filled: set[str] = set()
    for cat, agg in rr_snap.items():
        if cat not in category_rows:
            continue
        category_rows[cat].market_value_current = agg["mv"]
        category_rows[cat].ytm = agg["ytm"]
        category_rows[cat].duration = agg["duration"]
        rr_filled.add(cat)

    # bonds & repo from RawTrade aggregates (только для категорий не покрытых RR)
    cmv_per_inst: List[Tuple[str, float, Optional[float], Optional[float]]] = []
    for a in aggregates:
        cat = a.instrument_category if a.instrument_category in category_rows else "OTHER"
        if cat == "OTHER" or cat in rr_filled:
            continue
        cmv = _cmv_for_position(a, kase_prices)
        ytm = _ytm_for_position(a, kase_prices)
        dur = _duration_for_position(a, kase_prices)
        category_rows[cat].market_value_current += cmv
        if ytm is not None and cmv:
            category_rows[cat].ytm = (category_rows[cat].ytm or 0.0) + ytm * cmv
        if dur is not None and cmv:
            category_rows[cat].duration = (category_rows[cat].duration or 0.0) + dur * cmv
        cmv_per_inst.append((cat, cmv, ytm, dur))

    # Normalise YTM/Duration (we accumulated weighted sums above; divide by category CMV).
    # Категории, заполненные RR-снимком, уже усреднены — не пересчитываем их.
    for cat, row in category_rows.items():
        if cat in rr_filled:
            continue
        if row.market_value_current and row.ytm is not None:
            row.ytm = row.ytm / row.market_value_current
        if row.market_value_current and row.duration is not None:
            row.duration = row.duration / row.market_value_current

    total_cmv = sum(r.market_value_current for r in category_rows.values())

    # Previous date snapshot
    prev_summary = db.execute(select(PortfolioSummary).where(
        PortfolioSummary.cdu_id == cdu.id,
        PortfolioSummary.summary_date < report_date,
    ).order_by(PortfolioSummary.summary_date.desc())).scalars().first()
    prev_positions = []
    if prev_summary:
        prev_positions = db.execute(select(PortfolioPosition).where(
            PortfolioPosition.cdu_id == cdu.id,
            PortfolioPosition.position_date == prev_summary.summary_date,
        )).scalars().all()

    prev_by_cat = {p.instrument_category: p.market_value_current for p in prev_positions}
    for cat, row in category_rows.items():
        row.market_value_prev = prev_by_cat.get(cat, 0.0)
        row.daily_change = row.market_value_current - row.market_value_prev

    # Weighted YTM / Duration по портфелю (без учёта Cash и Receivables)
    weighting_cats = ["GOV_BONDS", "REVERSE_REPO", "MFO_BONDS", "AGENCY_BONDS"]
    weight_total = sum(category_rows[c].market_value_current for c in weighting_cats)
    ytm_w = sum(
        (category_rows[c].ytm or 0.0) * category_rows[c].market_value_current
        for c in weighting_cats
    ) / weight_total if weight_total else 0.0
    dur_w = sum(
        (category_rows[c].duration or 0.0) * category_rows[c].market_value_current
        for c in weighting_cats
    ) / weight_total if weight_total else 0.0

    summary = PortfolioSummary(
        cdu_id=cdu.id,
        summary_date=report_date,
        total_mv_prev=prev_summary.total_mv_current if prev_summary else 0.0,
        total_mv_current=total_cmv,
        total_daily_change=total_cmv - (prev_summary.total_mv_current if prev_summary else 0.0),
        cdu_share_pct=0.0,  # filled later
        ytm_weighted=ytm_w,
        duration_weighted=dur_w,
        benchmark_duration=mbm.duration if mbm else None,
        duration_status=None,
    )

    return list(category_rows.values()), summary


def _load_limits(db: Session, cdu_id: int, report_date: date) -> Dict[str, Tuple[float, float]]:
    rows = db.execute(select(CDULimit).where(
        CDULimit.cdu_id == cdu_id,
        CDULimit.valid_from <= report_date,
    )).scalars().all()
    out: Dict[str, Tuple[float, float]] = dict(DEFAULT_LIMITS)
    for r in rows:
        if r.valid_to and r.valid_to < report_date:
            continue
        out[r.instrument_category] = (r.min_limit_pct, r.max_limit_pct)
    return out


# ─────────────────────────────────────────────────────────────────────────
# Stand-alone helper used by routes/dashboard
# ─────────────────────────────────────────────────────────────────────────

def calculate_portfolio(rows: List[RawTrade], cdu_id: int, report_date: date) -> List[PositionAggregate]:
    """Convenience — used by tests."""
    return build_positions(rows, cdu_id=cdu_id, report_date=report_date)
