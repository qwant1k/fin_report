"""Calculate CMV, Daily Change, YTM, Duration, % of total and limits.

Glossary
--------
CMV  — Current Market Value
MV_T1 — Market Value yesterday
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from models.db_models import (
    AccountReceivable,
    Alert,
    BondLot,
    CashBalance,
    CashMovement,
    CashSnapshot,
    CDU,
    CDULimit,
    DepositLot,
    FXRate,
    KasePrice,
    MBMIndex,
    MVSnapshot,
    PortfolioPosition,
    PortfolioSummary,
    RawTrade,
    ReceivableTransaction,
    RepoLot,
    Trade,
)

from .constants import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    DEFAULT_LIMITS,
    duration_band,
)
from .limit_checker import LimitSpec, check_limit_spec, check_limit_status
from .position_builder import PositionAggregate, build_positions
from services.portfolio.engine import MarketData, build_portfolio, _non_snapshot_doc_ids
from services.portfolio.reference import ReferenceBook
from services.workflow import EFFECTIVE_STATUSES


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def _cmv_for_position(
    p: PositionAggregate,
    kase_prices: Dict[str, KasePrice],
    fx_rates: Optional[Dict[str, float]] = None,
) -> float:
    """Return CMV for a position."""
    currency = (getattr(p, "currency", None) or "KZT").upper()
    fx_rate = 1.0 if currency == "KZT" else float((fx_rates or {}).get(currency, 1.0))
    if p.instrument_category == "REVERSE_REPO":
        # До даты закрытия показываем вложенную сумму плюс начисленное на
        # отчётную дату вознаграждение.  Полная сумма выкупа становится cash
        # flow только на value date закрывающей ноги.
        return (p.repo_open_sum + p.repo_accrued_interest) * fx_rate
    # Bonds: nominal × price/100 + НКД (price priority: KASE > last trade)
    price = None
    if p.instrument_code and p.instrument_code in kase_prices:
        price = kase_prices[p.instrument_code].close_price
    if price is None:
        price = p.last_price
    if price is None:
        # fallback: нет цены — стоимость по номиналу
        return (p.nominal_volume + (p.accrued_interest or 0.0)) * fx_rate
    return (p.nominal_volume * price / 100.0 + (p.accrued_interest or 0.0)) * fx_rate


def _fx_rates_for_date(db: Session, report_date: date) -> Dict[str, float]:
    """Return the latest available FX rate for every currency as of a date."""
    rows = db.execute(select(FXRate).where(
        FXRate.rate_date <= report_date,
    ).order_by(FXRate.currency.asc(), FXRate.rate_date.desc())).scalars().all()
    rates: Dict[str, float] = {"KZT": 1.0}
    for row in rows:
        rates.setdefault((row.currency or "KZT").upper(), float(row.rate or 1.0))
    return rates


def _ytm_for_position(p: PositionAggregate, kase_prices: Dict[str, KasePrice]) -> Optional[float]:
    if p.instrument_code and p.instrument_code in kase_prices:
        kp = kase_prices[p.instrument_code]
        if kp.ytm is not None:
            return _rate_fraction(kp.ytm)
    return _rate_fraction(p.ytm)


def _rate_fraction(value: Optional[float]) -> Optional[float]:
    """Return a rate in the application's canonical fractional form.

    KASE and current imports store 6.66% as ``0.0666``.  Older imported
    workbooks sometimes stored the visually displayed number (``6.66``), so
    normalising at the calculation boundary keeps historical data safe too.
    """
    if value is None:
        return None
    number = float(value)
    return number / 100.0 if abs(number) > 1.0 else number


def _duration_for_position(p: PositionAggregate, kase_prices: Dict[str, KasePrice]) -> Optional[float]:
    if p.instrument_category == "REVERSE_REPO":
        return p.duration
    # KasePrice.duration historically stored KASE ``dtm`` (days to maturity),
    # never a duration in years — do not use it.
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
        ytm = _rate_fraction(lot.ytm)
        if ytm is not None:
            bucket["ytm_w"] += ytm * mv
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
        if lot.market_value is not None:
            mv = lot.market_value
        else:
            principal = lot.face_value or 0.0
            open_date = lot.valuation_date or lot.trade_date
            elapsed_days = max((report_date - open_date).days, 0)
            if lot.term_days:
                elapsed_days = min(elapsed_days, lot.term_days)
            if lot.close_value is not None and lot.term_days:
                accrued = (lot.close_value - principal) * elapsed_days / lot.term_days
            else:
                rate_for_accrual = _rate_fraction(lot.repo_rate_pct) or 0.0
                accrued = principal * rate_for_accrual * elapsed_days / 365.0
            mv = principal + accrued
        if not mv:
            continue
        bucket = out.setdefault("REVERSE_REPO", {"mv": 0.0, "ytm_w": 0.0, "ytm_weight": 0.0,
                                                  "dur_w": 0.0, "dur_weight": 0.0, "lots": 0})
        bucket["mv"] += mv
        bucket["lots"] += 1
        rate = _rate_fraction(lot.repo_rate_pct)
        if rate is not None:
            bucket["ytm_w"] += rate * mv
            bucket["ytm_weight"] += mv
        if lot.term_days:
            dur = lot.term_days / 365.0
            bucket["dur_w"] += dur * mv
            bucket["dur_weight"] += mv

    # Deposits from Risk Report are position lots too; without this the
    # historical import stores them, but the dashboard portfolio does not see
    # them when Report sheet rows are absent.
    deposit_rows = db.execute(select(DepositLot).where(
        DepositLot.cdu_id == cdu_id,
        DepositLot.valuation_date == report_date,
    )).scalars().all()
    for lot in deposit_rows:
        if lot.close_date and lot.close_date <= report_date:
            continue
        mv = lot.market_value or ((lot.principal or 0.0) + (lot.accrued_interest or 0.0))
        if not mv:
            continue
        bucket = out.setdefault("DEPOSIT", {"mv": 0.0, "ytm_w": 0.0, "ytm_weight": 0.0,
                                            "dur_w": 0.0, "dur_weight": 0.0, "lots": 0})
        bucket["mv"] += mv
        bucket["lots"] += 1
        rate = _rate_fraction(lot.ytm if lot.ytm is not None else lot.interest_rate_pct)
        if rate is not None:
            bucket["ytm_w"] += rate * mv
            bucket["ytm_weight"] += mv
        dur = lot.duration
        if dur is None and lot.term_days:
            dur = lot.term_days / 365.0
        if dur is not None:
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


def _latest_cash_snapshot_total(
    db: Session, cdu_id: int, report_date: date,
) -> Tuple[Optional[date], Optional[float]]:
    # Holdings-report cash is the manager's external view (reconciliation
    # input), not the fund's books.
    books = CashSnapshot.source.is_(None) | (CashSnapshot.source != "holdings_report_xlsx")
    snapshot_date = db.execute(select(CashSnapshot.snapshot_date).where(
        CashSnapshot.cdu_id == cdu_id,
        CashSnapshot.snapshot_date <= report_date,
        books,
    ).order_by(CashSnapshot.snapshot_date.desc())).scalar()
    if snapshot_date is None:
        return None, None

    rows = db.execute(select(CashSnapshot).where(
        CashSnapshot.cdu_id == cdu_id,
        CashSnapshot.snapshot_date == snapshot_date,
        books,
    )).scalars().all()
    total = 0.0
    for row in rows:
        if row.amount_kzt is not None:
            total += row.amount_kzt
            continue
        currency = (row.currency or "KZT").upper()
        if currency == "KZT":
            total += row.amount or 0.0
            continue
        fx = db.execute(select(FXRate).where(
            FXRate.currency == currency,
            FXRate.rate_date <= snapshot_date,
        ).order_by(FXRate.rate_date.desc())).scalars().first()
        total += (row.amount or 0.0) * (fx.rate if fx else 1.0)
    return snapshot_date, total


def _manual_trade_rows(db: Session, cdu_id: int, report_date: date) -> list[SimpleNamespace]:
    rows = db.execute(select(Trade).where(
        Trade.cdu_id == cdu_id,
        Trade.is_manual.is_(True),
        Trade.is_active.is_(True),
        Trade.workflow_status.in_(EFFECTIVE_STATUSES),
        Trade.trade_date <= report_date,
    )).scalars().all()
    out: list[SimpleNamespace] = []
    for row in rows:
        out.append(SimpleNamespace(
            operation_type=row.operation_type,
            order_number=row.deal_id or f"MANUAL-{row.id}",
            instrument_code=row.instrument_code or row.isin,
            instrument_category=row.instrument_category or "OTHER",
            trade_date=row.trade_date,
            trading_date=row.trade_date,
            settlement_date=row.value_date,
            nominal_volume=row.face_value if row.face_value is not None else row.quantity,
            price=row.price_final or row.market_price or row.clean_price,
            yield_pct=row.ytm,
            accrued_interest_volume=row.accrued_interest,
            repo_sum=abs(row.amount_kzt or 0.0) if row.operation_type == "REPO_OPEN" else None,
            repo_buyback_sum=(
                row.repo_buyback_sum or abs(row.amount_kzt or 0.0)
                if row.operation_type == "REPO_CLOSE" else row.repo_buyback_sum
            ),
            repo_term_days=row.repo_term_days,
            repo_rate_pct=row.repo_rate_pct,
            currency=row.currency,
        ))
    return out


def _approved_cash_delta(
    db: Session, cdu_id: int, report_date: date, base_date: Optional[date],
) -> float:
    rows = db.execute(select(CashMovement).where(
        CashMovement.cdu_id == cdu_id,
        CashMovement.operation_date <= report_date,
        CashMovement.workflow_status.in_(EFFECTIVE_STATUSES),
        CashMovement.is_active.is_(True),
    )).scalars().all()
    total = 0.0
    for row in rows:
        # Imported movements are already contained in an RR/cash snapshot on
        # the same date; manual corrections intentionally apply on that date.
        if base_date and row.operation_date < base_date:
            continue
        if base_date and row.operation_date == base_date and not row.is_manual:
            continue
        value = row.amount_kzt
        if value is None:
            value = row.amount
            if (row.currency or "KZT").upper() != "KZT":
                fx = db.execute(select(FXRate).where(
                    FXRate.currency == row.currency.upper(),
                    FXRate.rate_date <= row.operation_date,
                ).order_by(FXRate.rate_date.desc())).scalars().first()
                value *= fx.rate if fx else 1.0
        total += float(value or 0.0)
    return total


def _implied_cash(
    db: Session,
    cdu_id: int,
    flows: List[dict],
    cash_snapshot_date: Optional[date],
    warnings: List[str],
) -> float:
    """Book cash from snapshot REPO/deposits that closed after the snapshot.

    If the real movement (from a Trade Report / statement / manual entry) is
    already in ``cash_movements`` for that date and amount, nothing is added —
    otherwise the money would disappear from the portfolio on the close date.
    """
    total = 0.0
    for flow in flows:
        if cash_snapshot_date is not None and flow["date"] <= cash_snapshot_date:
            continue  # the cash snapshot already contains it
        amount = float(flow["amount"] or 0.0)
        exists = db.execute(select(CashMovement.id).where(
            CashMovement.cdu_id == cdu_id,
            CashMovement.operation_date == flow["date"],
            CashMovement.is_active.is_(True),
            CashMovement.workflow_status.in_(EFFECTIVE_STATUSES),
            CashMovement.amount_kzt.between(amount - 1.0, amount + 1.0),
        ).limit(1)).scalar()
        if exists:
            continue
        total += amount
        warnings.append(
            f"{flow['kind']} {flow['reference']} {flow['date']:%d.%m.%Y}: поступление {amount:,.2f} "
            "учтено по данным Risk Report — подтверждающее движение денег не загружено"
        )
    return total


def _receivable_balance_as_of(db: Session, row: AccountReceivable, report_date: date) -> float:
    initial = row.amount_kzt if row.amount_kzt is not None else row.amount
    txs = db.execute(select(ReceivableTransaction).where(
        ReceivableTransaction.receivable_id == row.id,
        ReceivableTransaction.operation_date <= report_date,
        ReceivableTransaction.workflow_status.in_(EFFECTIVE_STATUSES),
        ReceivableTransaction.is_active.is_(True),
    )).scalars().all()
    balance = float(initial or 0.0)
    for tx in txs:
        value = float(tx.amount_kzt if tx.amount_kzt is not None else tx.amount or 0.0)
        balance += value if tx.operation_type == "ADJUSTMENT" else -abs(value)
    return max(balance, 0.0)


# ─────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────

def _has_manual_changes(db: Session, report_date: date) -> bool:
    effective = EFFECTIVE_STATUSES
    return db.execute(select(Trade.id).where(
        Trade.is_manual.is_(True), Trade.is_active.is_(True),
        Trade.workflow_status.in_(effective), Trade.trade_date <= report_date,
    ).limit(1)).scalar() is not None or db.execute(select(CashMovement.id).where(
        CashMovement.is_manual.is_(True), CashMovement.is_active.is_(True),
        CashMovement.workflow_status.in_(effective), CashMovement.operation_date <= report_date,
    ).limit(1)).scalar() is not None or db.execute(select(AccountReceivable.id).where(
        AccountReceivable.is_manual.is_(True), AccountReceivable.is_active.is_(True),
        AccountReceivable.workflow_status.in_(effective),
        AccountReceivable.record_date <= report_date,
    ).limit(1)).scalar() is not None or db.execute(
        select(ReceivableTransaction.id)
        .join(AccountReceivable, AccountReceivable.id == ReceivableTransaction.receivable_id)
        .where(
            ReceivableTransaction.is_active.is_(True),
            ReceivableTransaction.workflow_status.in_(effective),
            ReceivableTransaction.operation_date <= report_date,
            AccountReceivable.is_active.is_(True),
            AccountReceivable.workflow_status.in_(effective),
        ).limit(1)
    ).scalar() is not None


def calculate_for_date(db: Session, report_date: date, *, recalculate: bool = False) -> dict:
    """Build all PortfolioPosition + PortfolioSummary rows for `report_date`.

    * If a Risk Report «Report» sheet was imported for the date and there are no
      approved manual corrections, the imported slice is authoritative and is
      kept untouched (re-running is a no-op — business process 5.4).
    * Otherwise the portfolio is rolled forward from the latest Risk Report
      snapshot with the Trade ledger and revalued at the prices of the date
      (``services.portfolio.engine``).  Previous calculated rows of the date are
      replaced, so a re-run never creates duplicates.

    Returns counters: {"cdus_processed": int, "breaches": int, "warnings": int}.
    """
    report_summaries = db.execute(select(PortfolioSummary).where(
        PortfolioSummary.summary_date == report_date,
    )).scalars().all()
    report_positions = db.execute(select(PortfolioPosition).where(
        PortfolioPosition.position_date == report_date,
        PortfolioPosition.notes == "rr_report_import",
    )).scalars().all()
    if report_summaries and report_positions and not _has_manual_changes(db, report_date):
        # The imported Risk Report sheet is the authoritative view of the day
        # (values are kept), but the limits and the benchmark corridor are
        # checked against the reference book in force on the date.
        breaches = _recheck_imported_slice(db, report_date, report_summaries)
        return {
            "cdus_processed": len({s.cdu_id for s in report_summaries}),
            "breaches": breaches,
            "warnings": 0,
            "source": "risk_report",
        }

    # Idempotent re-run: drop the previously calculated slice of the date.
    db.query(PortfolioPosition).filter(
        PortfolioPosition.position_date == report_date,
        PortfolioPosition.instrument_code.is_(None),   # keep imported instrument rows (Holdings)
    ).delete(synchronize_session=False)
    db.query(PortfolioSummary).filter_by(summary_date=report_date).delete()
    db.query(Alert).filter(
        Alert.alert_date == report_date,
        Alert.alert_type.in_(("LIMIT_BREACH", "DURATION_BREACH", "VALUATION_WARNINGS")),
    ).delete(synchronize_session=False)
    db.flush()

    cdus = db.query(CDU).filter_by(is_active=True).all()
    cdus_processed = 0
    total_breaches = 0
    total_warnings = 0
    fund_total_cmv = 0.0

    # Pre-load KASE prices for the date (kept for backward compatibility)
    kase_rows = db.query(KasePrice).filter_by(trade_date=report_date).all()
    kase_prices: Dict[str, KasePrice] = {kp.instrument_code: kp for kp in kase_rows}
    refs = ReferenceBook(db)
    market = MarketData(db, report_date)
    excluded_docs = _non_snapshot_doc_ids(db)

    # Pre-load MBM benchmark
    mbm = db.query(MBMIndex).filter(MBMIndex.index_date <= report_date).order_by(
        MBMIndex.index_date.desc()).first()

    # ── Pass 1: build per-CDU portfolios, compute totals ──
    cdu_summaries: List[Tuple[CDU, PortfolioSummary, List[PortfolioPosition], List[str]]] = []

    for cdu in cdus:
        positions, summary = _calculate_cdu(
            db=db,
            cdu=cdu,
            report_date=report_date,
            kase_prices=kase_prices,
            mbm=mbm,
            refs=refs,
            market=market,
            excluded_docs=excluded_docs,
        )
        warnings = getattr(summary, "_warnings", [])
        # Skip CDUs with zero portfolio (no trades, no cash, no receivables)
        if summary.total_mv_current == 0 and not any(
            (p.market_value_current or 0.0) != 0.0 for p in positions
        ):
            continue
        cdu_summaries.append((cdu, summary, positions, warnings))
        fund_total_cmv += summary.total_mv_current

    # ── Pass 2: cdu_share_pct, % of total inside CDU, persist, alerts ──
    for cdu, summary, positions, warnings in cdu_summaries:
        summary.cdu_share_pct = (summary.total_mv_current / fund_total_cmv) if fund_total_cmv else 0.0
        total_breaches += _apply_limit_checks(db, cdu, summary, positions, report_date)

        if warnings:
            unique = list(dict.fromkeys(warnings))
            total_warnings += len(unique)
            db.add(Alert(
                alert_date=report_date,
                cdu_id=cdu.id,
                alert_type="VALUATION_WARNINGS",
                severity="WARN",
                message=(
                    f"{cdu.short_name}: {len(unique)} предупреждени(й) оценки — "
                    + "; ".join(unique[:3]) + ("…" if len(unique) > 3 else "")
                ),
                details_json=json.dumps(unique[:200], ensure_ascii=False),
            ))

        db.add(summary)
        cdus_processed += 1

    db.commit()

    if total_breaches:
        _send_breach_digest(db, report_date, total_breaches)

    return {
        "cdus_processed": cdus_processed,
        "breaches": total_breaches,
        "warnings": total_warnings,
        "source": "engine",
    }


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
    refs: Optional[ReferenceBook] = None,
    market: Optional[MarketData] = None,
    excluded_docs: Optional[List[int]] = None,
) -> Tuple[List[PortfolioPosition], PortfolioSummary]:
    """Compute category positions + summary for a single CDU on a single date.

    Securities, REPO and deposits come from the portfolio engine (Risk Report
    snapshot rolled forward with the Trade ledger and revalued on the date);
    cash = latest cash snapshot + approved cash movements after it;
    receivables = approved AR balances as of the date.
    """
    state = build_portfolio(
        db, cdu.id, report_date,
        refs=refs, market=market, excluded_docs=excluded_docs,
    )
    by_cat = state.by_category()

    # Cash balance — prefer imported daily snapshots, fallback to legacy balances.
    cash_snapshot_date, cash_snapshot_total = _latest_cash_snapshot_total(db, cdu.id, report_date)
    cash = db.execute(select(CashBalance).where(
        CashBalance.cdu_id == cdu.id,
        CashBalance.balance_date <= report_date,
    ).order_by(CashBalance.balance_date.desc())).scalars().first()

    receivables = db.execute(select(AccountReceivable).where(
        AccountReceivable.cdu_id == cdu.id,
        AccountReceivable.record_date <= report_date,
        AccountReceivable.workflow_status.in_(EFFECTIVE_STATUSES),
        AccountReceivable.is_active.is_(True),
    )).scalars().all()
    receivable_total = sum(_receivable_balance_as_of(db, ar, report_date) for ar in receivables)

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
            notes="calculated",
        )

    # cash
    if cash_snapshot_total is not None and (cash is None or cash.balance_date <= cash_snapshot_date):
        category_rows["CASH"].market_value_current = cash_snapshot_total
    elif cash:
        category_rows["CASH"].market_value_current = cash.amount or 0.0
        cash_snapshot_date = cash.balance_date
    category_rows["CASH"].market_value_current += _approved_cash_delta(
        db, cdu.id, report_date, cash_snapshot_date,
    )
    warnings = list(state.warnings)
    category_rows["CASH"].market_value_current += _implied_cash(
        db, cdu.id, state.implied_cash, cash_snapshot_date, warnings,
    )

    category_rows["RECEIVABLES"].market_value_current = receivable_total

    for cat, agg in by_cat.items():
        target = cat if cat in category_rows else None
        if target is None:
            warnings.append(
                f"Категория «{cat}» ({agg['lots']} поз., {agg['mv']:,.0f} KZT) не входит в структуру отчёта — "
                "проверьте тип бумаги в справочнике"
            )
            continue
        row = category_rows[target]
        row.market_value_current += agg["mv"]
        row.nominal_volume = (row.nominal_volume or 0.0) + agg["face"]
        row.ytm = agg["ytm"]
        row.duration = agg["duration"]

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
            PortfolioPosition.instrument_code.is_(None),
        )).scalars().all()

    prev_by_cat = {p.instrument_category: p.market_value_current for p in prev_positions}
    for cat, row in category_rows.items():
        row.market_value_prev = prev_by_cat.get(cat, 0.0)
        row.daily_change = row.market_value_current - row.market_value_prev

    # Weighted YTM / Duration по портфелю (без учёта Cash и Receivables —
    # требование журнала 17.07).  NB: формулы Risk Report (Report!G14, H14,
    # C18) делят на итог ЧДУ, включая деньги и дебиторку; методику нужно
    # подтвердить — см. отчёт аудита 01.10.2026.
    weighting_cats = [
        "GOV_BONDS", "REVERSE_REPO", "MFO_BONDS", "AGENCY_BONDS",
        "FOREIGN_BONDS", "DEPOSIT",
    ]
    weight_ytm = sum(category_rows[c].market_value_current for c in weighting_cats if category_rows[c].ytm is not None)
    weight_dur = sum(category_rows[c].market_value_current for c in weighting_cats if category_rows[c].duration is not None)
    ytm_w = sum(
        (category_rows[c].ytm or 0.0) * category_rows[c].market_value_current
        for c in weighting_cats if category_rows[c].ytm is not None
    ) / weight_ytm if weight_ytm else 0.0
    dur_w = sum(
        (category_rows[c].duration or 0.0) * category_rows[c].market_value_current
        for c in weighting_cats if category_rows[c].duration is not None
    ) / weight_dur if weight_dur else 0.0

    summary = PortfolioSummary(
        cdu_id=cdu.id,
        summary_date=report_date,
        total_mv_prev=prev_summary.total_mv_current if prev_summary else 0.0,
        total_mv_current=total_cmv,
        total_daily_change=total_cmv - (prev_summary.total_mv_current if prev_summary else 0.0),
        cdu_share_pct=0.0,  # filled later
        ytm_weighted=ytm_w,
        duration_weighted=dur_w,
        benchmark_duration=_benchmark_duration(mbm),
        duration_status=None,
    )
    summary._warnings = warnings  # transient, consumed by calculate_for_date

    return list(category_rows.values()), summary


def _benchmark_duration(mbm: Optional[MBMIndex]) -> Optional[float]:
    """Benchmark for the portfolio *modified* duration.

    The Risk Report compares modified duration of the portfolio with the MBM
    index; prefer the index modified duration and fall back to Macaulay.
    """
    if mbm is None:
        return None
    if mbm.mod_duration is not None:
        return mbm.mod_duration
    return mbm.duration


def _load_limit_specs(db: Session, cdu_id: int, report_date: date) -> Dict[str, LimitSpec]:
    """Limits of the reference book («Лимиты ЧДУ») in force on ``report_date``.

    For every category the version with the latest ``valid_from`` not after
    the date (and not expired) wins; categories without a version in force
    fall back to the investment-policy defaults.
    """
    rows = db.execute(select(CDULimit).where(
        CDULimit.cdu_id == cdu_id,
        CDULimit.valid_from <= report_date,
        or_(CDULimit.valid_to.is_(None), CDULimit.valid_to >= report_date),
    ).order_by(CDULimit.valid_from.asc(), CDULimit.id.asc())).scalars().all()
    out: Dict[str, LimitSpec] = {
        cat: LimitSpec(mn, mx, mx, mx, source="default") for cat, (mn, mx) in DEFAULT_LIMITS.items()
    }
    for r in rows:       # later versions overwrite earlier ones
        mn = float(r.min_limit_pct or 0.0)
        mx = float(r.max_limit_pct if r.max_limit_pct is not None else 1.0)
        out[r.instrument_category] = LimitSpec(
            mn, mx,
            float(r.hard_limit_pct) if r.hard_limit_pct else mx,
            float(r.soft_limit_pct) if r.soft_limit_pct else mx,
            source="reference", valid_from=r.valid_from,
        )
    return out


def _load_limits(db: Session, cdu_id: int, report_date: date) -> Dict[str, Tuple[float, float]]:
    return {cat: (sp.min_pct, sp.max_pct) for cat, sp in _load_limit_specs(db, cdu_id, report_date).items()}


def _benchmark_for(db: Session, report_date: date) -> Optional[float]:
    """MBM index *modified* duration published for the date (or the last before it)."""
    mbm = db.query(MBMIndex).filter(MBMIndex.index_date <= report_date).order_by(
        MBMIndex.index_date.desc()).first()
    return _benchmark_duration(mbm)


def _apply_limit_checks(db: Session, cdu: CDU, summary: PortfolioSummary,
                        positions: List[PortfolioPosition], report_date: date) -> int:
    """Hard/soft limit statuses, duration corridor and alerts for one manager."""
    breaches = 0
    specs = _load_limit_specs(db, cdu.id, report_date)
    total = summary.total_mv_current or 0.0
    for pos in positions:
        if pos.instrument_code is not None:
            continue
        if total:
            pos.pct_of_total = (pos.market_value_current or 0.0) / total
        spec = specs.get(pos.instrument_category) or LimitSpec(0.0, 1.0, 1.0, 1.0)
        hard, soft = check_limit_spec(pos.pct_of_total or 0.0, spec)
        pos.hard_limit_status = hard
        pos.soft_limit_status = soft
        pos.free_limit_mln = (total * spec.hard_pct - (pos.market_value_current or 0.0)) / 1_000_000.0
        db.add(pos)
        if hard == "breach" or soft == "breach":
            kind = "жёсткий" if hard == "breach" else "мягкий"
            db.add(Alert(
                alert_date=report_date,
                cdu_id=cdu.id,
                alert_type="LIMIT_BREACH",
                severity="CRITICAL" if hard == "breach" else "WARN",
                message=(
                    f"{cdu.short_name}: {CATEGORY_LABELS.get(pos.instrument_category, pos.instrument_category)} "
                    f"{(pos.pct_of_total or 0)*100:.2f}% — нарушен {kind} лимит "
                    f"[{spec.min_pct*100:.2f}%; {(spec.hard_pct if hard == 'breach' else spec.soft_pct)*100:.2f}%]"
                    + ("" if spec.source == "reference" else " (лимит по умолчанию: в справочнике нет версии на дату)")
                ),
            ))
            breaches += 1

    bench = _benchmark_for(db, report_date)
    if bench is not None:
        summary.benchmark_duration = bench
    if summary.benchmark_duration is not None:
        lo, hi = duration_band(summary.benchmark_duration)
        summary.duration_status = "ok" if lo <= (summary.duration_weighted or 0.0) <= hi else "breach"
        if summary.duration_status == "breach":
            db.add(Alert(
                alert_date=report_date,
                cdu_id=cdu.id,
                alert_type="DURATION_BREACH",
                severity="WARN",
                message=(
                    f"{cdu.short_name}: дюрация {summary.duration_weighted or 0:.2f} вне диапазона "
                    f"[{lo:.2f}; {hi:.2f}] (MBM ModDuration={summary.benchmark_duration:.2f})"
                ),
            ))
            breaches += 1
    return breaches


def _recheck_imported_slice(db: Session, report_date: date,
                            summaries: List[PortfolioSummary]) -> int:
    db.query(Alert).filter(
        Alert.alert_date == report_date,
        Alert.alert_type.in_(("LIMIT_BREACH", "DURATION_BREACH")),
    ).delete(synchronize_session=False)
    breaches = 0
    for summary in summaries:
        cdu = db.get(CDU, summary.cdu_id)
        if cdu is None:
            continue
        positions = db.execute(select(PortfolioPosition).where(
            PortfolioPosition.cdu_id == cdu.id,
            PortfolioPosition.position_date == report_date,
            PortfolioPosition.instrument_code.is_(None),
        )).scalars().all()
        breaches += _apply_limit_checks(db, cdu, summary, positions, report_date)
    db.commit()
    return breaches


# ─────────────────────────────────────────────────────────────────────────
# Stand-alone helper used by routes/dashboard
# ─────────────────────────────────────────────────────────────────────────

def calculate_portfolio(rows: List[RawTrade], cdu_id: int, report_date: date) -> List[PositionAggregate]:
    """Convenience — used by tests."""
    return build_positions(rows, cdu_id=cdu_id, report_date=report_date)
