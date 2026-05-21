"""Dashboard summary endpoint — full data for the React dashboard."""
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import require_user

from database import get_db
from models.db_models import (
    Alert,
    BondLot,
    CDU,
    CDULimit,
    GeneratedReport,
    MBMIndex,
    MVSnapshot,
    PortfolioPosition,
    PortfolioSummary,
    RepoLot,
    SourceDocument,
    Trade,
)
from models.schemas import (
    AlertOut,
    CategoryRow,
    CDUBlock,
    DashboardResponse,
)
from services.calculator.constants import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    DEFAULT_LIMITS,
    DURATION_LOWER_OFFSET,
    DURATION_UPPER_OFFSET,
)


def _source_doc_types(db: Session) -> dict[int, str]:
    rows = db.execute(select(SourceDocument.id, SourceDocument.doc_type)).all()
    return {int(row.id): str(row.doc_type or "") for row in rows if row.id is not None}


def _is_trade_report_source(source_doc_types: dict[int, str], source_doc_id: Optional[int]) -> bool:
    return source_doc_id is not None and source_doc_types.get(source_doc_id) == "TRADE_REPORT"


router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(require_user)],
)


@router.get("/summary", response_model=DashboardResponse)
def dashboard_summary(
    report_date: Optional[date] = Query(None),
    from_: Optional[date] = Query(None, alias="from"),
    to_: Optional[date] = Query(None, alias="to"),
    db: Session = Depends(get_db),
):
    if to_ is not None:
        report_date = to_
    if report_date is None:
        report_date = date.today()

    # As-of dashboard: each CDU can have its own latest available calculated
    # slice. If Halyk was calculated on 10.09 and BCC on 11.09, the main report
    # should show all three blocks instead of only the global latest date.
    # When `from_` is provided, we restrict to the latest slice that falls
    # within [from_, to_] so the dashboard shows only data inside the period.
    def _query_summaries(upper: date, lower: Optional[date]):
        stmt = select(PortfolioSummary).where(PortfolioSummary.summary_date <= upper)
        if lower is not None:
            stmt = stmt.where(PortfolioSummary.summary_date >= lower)
        stmt = stmt.order_by(
            PortfolioSummary.cdu_id.asc(),
            PortfolioSummary.summary_date.desc(),
        )
        return db.execute(stmt).scalars().all()

    all_summaries = _query_summaries(report_date, from_)
    if not all_summaries and from_ is None:
        latest = db.execute(
            select(PortfolioSummary).order_by(PortfolioSummary.summary_date.desc())
        ).scalars().first()
        if latest:
            report_date = latest.summary_date
            all_summaries = _query_summaries(report_date, None)

    summaries_by_cdu: dict[int, PortfolioSummary] = {}
    for summary in all_summaries:
        summaries_by_cdu.setdefault(summary.cdu_id, summary)
    summaries = list(summaries_by_cdu.values())
    if summaries:
        report_date = max(s.summary_date for s in summaries)
    blocks: List[CDUBlock] = []
    fund_total = 0.0
    fund_total_prev = 0.0
    fund_change = 0.0
    fund_ytm_w = 0.0
    fund_dur_w = 0.0
    weight_total = 0.0
    breaches = 0

    mbm = db.execute(select(MBMIndex).where(MBMIndex.index_date <= report_date).order_by(
        MBMIndex.index_date.desc())).scalars().first()

    for s in summaries:
        cdu = db.get(CDU, s.cdu_id)
        if not cdu:
            continue
        position_date = s.summary_date
        positions = db.execute(select(PortfolioPosition).where(
            PortfolioPosition.cdu_id == s.cdu_id,
            PortfolioPosition.position_date == position_date,
        )).scalars().all()
        pos_by_cat = {p.instrument_category: p for p in positions}
        limits_q = db.execute(select(CDULimit).where(CDULimit.cdu_id == cdu.id)).scalars().all()
        limits_map = {l.instrument_category: (l.min_limit_pct, l.max_limit_pct) for l in limits_q}

        report_imported = bool(positions) and all(
            (p.notes == "rr_report_import") for p in positions
        )
        category_order = (
            [cat for cat in CATEGORY_ORDER if cat in pos_by_cat]
            if report_imported else CATEGORY_ORDER
        )

        rows: List[CategoryRow] = []
        for cat in category_order:
            p = pos_by_cat.get(cat)
            mn, mx = limits_map.get(cat, DEFAULT_LIMITS.get(cat, (0.0, 1.0)))
            rows.append(CategoryRow(
                category=cat,
                label=CATEGORY_LABELS[cat],
                market_value_prev=p.market_value_prev if p else 0.0,
                daily_change=p.daily_change if p else 0.0,
                market_value_current=p.market_value_current if p else 0.0,
                pct_of_total=p.pct_of_total if p else 0.0,
                ytm=p.ytm if p else None,
                duration=p.duration if p else None,
                min_limit_pct=mn,
                max_limit_pct=mx,
                hard_limit=p.hard_limit_status if p else "ok",
                soft_limit=p.soft_limit_status if p else "ok",
                free_limit_mln=p.free_limit_mln if p else None,
            ))
            if p and p.hard_limit_status == "breach":
                breaches += 1

        bd = s.benchmark_duration
        block = CDUBlock(
            cdu_id=cdu.id,
            cdu_name=cdu.name,
            cdu_short=cdu.short_name,
            rows=rows,
            total_mv_prev=s.total_mv_prev,
            total_daily_change=s.total_daily_change,
            total_mv_current=s.total_mv_current,
            total_pct=1.0,
            ytm_weighted=s.ytm_weighted,
            duration_weighted=s.duration_weighted,
            benchmark_duration=bd,
            duration_lower=(bd + DURATION_LOWER_OFFSET) if bd is not None else None,
            duration_upper=(bd + DURATION_UPPER_OFFSET) if bd is not None else None,
            duration_status=s.duration_status,
            cdu_share_pct=s.cdu_share_pct,
        )
        blocks.append(block)

        fund_total += s.total_mv_current
        fund_total_prev += s.total_mv_prev
        fund_change += s.total_daily_change
        fund_ytm_w += s.ytm_weighted * s.total_mv_current
        fund_dur_w += s.duration_weighted * s.total_mv_current
        weight_total += s.total_mv_current

    blocks.sort(key=lambda block: block.total_mv_current, reverse=True)

    # Operational KPIs (Phase 3)
    pending_approvals_count = db.execute(
        select(func.count(GeneratedReport.id)).where(
            GeneratedReport.status == "pending_approval"
        )
    ).scalar() or 0
    flagged_prices_count = db.execute(
        select(func.count(Trade.id)).where(
            Trade.price_flag == True,  # noqa: E712
            Trade.is_active == True,   # noqa: E712
            Trade.trade_date == report_date,
        )
    ).scalar() or 0

    return DashboardResponse(
        report_date=report_date,
        fund_total_mv=fund_total,
        fund_total_mv_prev=fund_total_prev,
        fund_daily_change=fund_change,
        fund_daily_change_pct=(fund_change / fund_total_prev) if fund_total_prev else 0.0,
        fund_ytm_weighted=(fund_ytm_w / weight_total) if weight_total else 0.0,
        fund_duration_weighted=(fund_dur_w / weight_total) if weight_total else 0.0,
        benchmark_ytm=mbm.ytm_value if mbm else None,
        benchmark_duration=mbm.duration if mbm else None,
        breaches_count=breaches,
        pending_approvals_count=pending_approvals_count,
        flagged_prices_count=flagged_prices_count,
        blocks=blocks,
    )


@router.get("/instrument-details")
def instrument_details(
    cdu_id: int = Query(...),
    category: str = Query(...),
    from_: Optional[date] = Query(None, alias="from"),
    to_: Optional[date] = Query(None, alias="to"),
    db: Session = Depends(get_db),
):
    """Instrument-level drill-down for dashboard category rows.

    Returns one row per instrument for the selected CDU/category/period. The
    dashboard prefers position lots/snapshots and falls back to Trade Report
    cash movements when no position rows exist for the category.
    """
    if to_ is None:
        to_ = date.today()
    if from_ is None:
        from_ = _earliest_data_date(db) or to_

    details: dict[str, dict] = {}

    def acc(
        code: str,
        *,
        isin: Optional[str] = None,
        name: Optional[str] = None,
        quantity: Optional[float] = None,
        face_value: Optional[float] = None,
        amount: Optional[float] = None,
        ytm: Optional[float] = None,
        duration: Optional[float] = None,
        first_date: Optional[date] = None,
        last_date: Optional[date] = None,
        operations: int = 1,
    ) -> None:
        key = code or isin or "—"
        row = details.setdefault(key, {
            "instrument_code": code or isin or "—",
            "isin": isin,
            "instrument_name": name,
            "category": category,
            "quantity": 0.0,
            "face_value": 0.0,
            "amount": 0.0,
            "ytm_weighted_sum": 0.0,
            "duration_weighted_sum": 0.0,
            "ytm_weight": 0.0,
            "duration_weight": 0.0,
            "first_date": first_date,
            "last_date": last_date,
            "operations": 0,
        })
        row["isin"] = row["isin"] or isin
        row["instrument_name"] = row["instrument_name"] or name
        row["quantity"] += float(quantity or 0.0)
        row["face_value"] += float(face_value or 0.0)
        row["amount"] += float(amount or 0.0)
        weight = abs(float(amount if amount is not None else face_value or 0.0))
        if ytm is not None and weight:
            row["ytm_weighted_sum"] += float(ytm) * weight
            row["ytm_weight"] += weight
        if duration is not None and weight:
            row["duration_weighted_sum"] += float(duration) * weight
            row["duration_weight"] += weight
        if first_date and (row["first_date"] is None or first_date < row["first_date"]):
            row["first_date"] = first_date
        if last_date and (row["last_date"] is None or last_date > row["last_date"]):
            row["last_date"] = last_date
        row["operations"] += operations

    position_rows_found = False
    trade_rows_found = False
    source_doc_types = _source_doc_types(db)
    baseline_date: Optional[date] = None

    if category == "REVERSE_REPO":
        repo_dates = [
            lot.valuation_date
            for lot in db.execute(
                select(RepoLot).where(
                    RepoLot.cdu_id == cdu_id,
                    RepoLot.valuation_date <= to_,
                )
            ).scalars()
            if not _is_trade_report_source(source_doc_types, lot.source_doc_id)
        ]
        baseline_date = max(repo_dates) if repo_dates else None
        if baseline_date is not None:
            for lot in db.execute(
                select(RepoLot).where(
                    RepoLot.cdu_id == cdu_id,
                    RepoLot.valuation_date == baseline_date,
                )
            ).scalars():
                if _is_trade_report_source(source_doc_types, lot.source_doc_id):
                    continue
                position_rows_found = True
                acc(
                    lot.instrument_code or lot.isin or lot.deal_id or "REPO",
                    isin=lot.isin,
                    name="Открытое обратное REPO",
                    quantity=lot.face_value,
                    face_value=lot.face_value,
                    amount=lot.market_value or lot.close_value or lot.face_value,
                    ytm=lot.ytm or lot.repo_rate_pct,
                    duration=lot.duration or ((lot.term_days / 365.0) if lot.term_days else None),
                    first_date=lot.trade_date,
                    last_date=lot.valuation_date,
                    operations=0,
                )
    elif category not in ("CASH", "RECEIVABLES"):
        dates: list[date] = []
        dates.extend(
            lot.valuation_date
            for lot in db.execute(
                select(BondLot).where(
                    BondLot.cdu_id == cdu_id,
                    BondLot.category == category,
                    BondLot.valuation_date <= to_,
                )
            ).scalars()
            if not _is_trade_report_source(source_doc_types, lot.source_doc_id)
        )
        dates.extend(
            p.position_date
            for p in db.execute(
                select(PortfolioPosition).where(
                    PortfolioPosition.cdu_id == cdu_id,
                    PortfolioPosition.instrument_category == category,
                    PortfolioPosition.instrument_code.is_not(None),
                    PortfolioPosition.position_date <= to_,
                )
            ).scalars()
        )
        baseline_date = max(dates) if dates else None
        if baseline_date is not None:
            for lot in db.execute(
                select(BondLot).where(
                    BondLot.cdu_id == cdu_id,
                    BondLot.category == category,
                    BondLot.valuation_date == baseline_date,
                )
            ).scalars():
                if _is_trade_report_source(source_doc_types, lot.source_doc_id):
                    continue
                position_rows_found = True
                qty = float(lot.quantity_current or 0.0)
                if abs(qty) < 1e-9:
                    qty = float(lot.face_value_current or 0.0)
                acc(
                    lot.instrument_code or lot.isin,
                    isin=lot.isin,
                    name=lot.notes,
                    quantity=qty,
                    face_value=lot.face_value_current,
                    amount=lot.market_value or lot.total_value or lot.face_value_current,
                    ytm=lot.ytm,
                    duration=lot.duration,
                    first_date=lot.trade_date,
                    last_date=lot.valuation_date,
                    operations=0,
                )
            for p in db.execute(
                select(PortfolioPosition).where(
                    PortfolioPosition.cdu_id == cdu_id,
                    PortfolioPosition.instrument_category == category,
                    PortfolioPosition.instrument_code.is_not(None),
                    PortfolioPosition.position_date == baseline_date,
                )
            ).scalars():
                position_rows_found = True
                acc(
                    p.instrument_code,
                    name=p.instrument_name,
                    quantity=p.nominal_volume,
                    face_value=p.nominal_volume,
                    amount=p.market_value_current,
                    ytm=p.ytm,
                    duration=p.duration,
                    first_date=p.position_date,
                    last_date=p.position_date,
                    operations=0,
                )

    trade_q = select(Trade).where(
        Trade.cdu_id == cdu_id,
        Trade.instrument_category == category,
        Trade.is_active == True,
        Trade.value_date <= to_,
    )
    for t in db.execute(trade_q).scalars().all():
        trade_effective_date = t.value_date or t.trade_date
        if baseline_date is not None and trade_effective_date <= baseline_date:
            continue
        sign = 0
        if t.operation_type in ("BUY", "REPO_OPEN", "FX_BUY", "DEPOSIT_OPEN"):
            sign = 1
        elif t.operation_type in ("SELL", "REPO_CLOSE", "REDEMPTION", "FX_SELL", "DEPOSIT_CLOSE"):
            sign = -1
        if sign == 0:
            continue
        trade_rows_found = True
        signed_amount = (
            t.repo_buyback_sum
            or t.amount_kzt
            or t.amount_ccy
            or t.face_value
            or 0.0
        )
        acc(
            t.instrument_code or t.isin or t.deal_id or "—",
            isin=t.isin,
            name=t.description,
            quantity=sign * abs(float(t.quantity or 0.0)),
            face_value=sign * abs(float(t.face_value or 0.0)),
            amount=sign * abs(float(signed_amount or 0.0)),
            ytm=t.ytm or t.repo_rate_pct,
            duration=(t.repo_term_days / 365.0) if t.repo_term_days else None,
            first_date=t.trade_date,
            last_date=t.value_date,
        )

    if not trade_rows_found and not position_rows_found and category == "REVERSE_REPO":
        repo_q = select(RepoLot).where(
            RepoLot.cdu_id == cdu_id,
            RepoLot.trade_date <= to_,
            (RepoLot.close_date.is_(None) | (RepoLot.close_date >= from_)),
        )
        for lot in db.execute(repo_q).scalars().all():
            if _is_trade_report_source(source_doc_types, lot.source_doc_id):
                continue
            if not position_rows_found:
                details.clear()
                position_rows_found = True
            acc(
                lot.instrument_code or lot.isin or lot.deal_id or "REPO",
                isin=lot.isin,
                name="Открытое обратное REPO",
                quantity=lot.face_value,
                face_value=lot.face_value,
                amount=lot.close_value or lot.face_value,
                ytm=lot.ytm or lot.repo_rate_pct,
                duration=lot.duration or ((lot.term_days / 365.0) if lot.term_days else None),
                first_date=lot.trade_date,
                last_date=lot.close_date or lot.valuation_date,
                operations=0,
            )

    if not trade_rows_found and not position_rows_found and category not in ("REVERSE_REPO", "CASH", "RECEIVABLES"):
        bond_q = select(BondLot).where(
            BondLot.cdu_id == cdu_id,
            BondLot.category == category,
            BondLot.valuation_date >= from_,
            BondLot.valuation_date <= to_,
        )
        for lot in db.execute(bond_q).scalars().all():
            if _is_trade_report_source(source_doc_types, lot.source_doc_id):
                continue
            if not position_rows_found:
                details.clear()
                position_rows_found = True
            qty = float(lot.quantity_current or 0.0)
            if abs(qty) < 1e-9:
                qty = float(lot.face_value_current or 0.0)
            acc(
                lot.instrument_code or lot.isin,
                isin=lot.isin,
                name=lot.notes,
                quantity=qty,
                face_value=lot.face_value_current,
                amount=lot.market_value or lot.total_value or lot.face_value_current,
                ytm=lot.ytm,
                duration=lot.duration,
                first_date=lot.trade_date,
                last_date=lot.valuation_date,
                operations=0,
            )

    out = []
    for row in details.values():
        if (
            category not in ("CASH", "RECEIVABLES")
            and abs(float(row.get("quantity") or 0.0)) < 1e-9
            and abs(float(row.get("face_value") or 0.0)) < 1e-9
        ):
            continue
        if (
            abs(float(row.get("quantity") or 0.0)) < 1e-9
            and abs(float(row.get("face_value") or 0.0)) < 1e-9
            and abs(float(row.get("amount") or 0.0)) < 1e-9
        ):
            continue
        ytm_weight = row.pop("ytm_weight") or 0.0
        duration_weight = row.pop("duration_weight") or 0.0
        ytm_sum = row.pop("ytm_weighted_sum")
        dur_sum = row.pop("duration_weighted_sum")
        row["ytm"] = (ytm_sum / ytm_weight) if ytm_weight else None
        row["duration"] = (dur_sum / duration_weight) if duration_weight else None
        row["first_date"] = row["first_date"].isoformat() if row["first_date"] else None
        row["last_date"] = row["last_date"].isoformat() if row["last_date"] else None
        out.append(row)

    return {
        "cdu_id": cdu_id,
        "category": category,
        "from": from_.isoformat(),
        "to": to_.isoformat(),
        "rows": sorted(out, key=lambda x: -abs(x["amount"])),
    }


def _earliest_data_date(db: Session) -> Optional[date]:
    dates = [
        db.execute(select(PortfolioSummary.summary_date).order_by(PortfolioSummary.summary_date.asc())).scalar(),
        db.execute(select(Trade.value_date).where(Trade.value_date.is_not(None)).order_by(Trade.value_date.asc())).scalar(),
        db.execute(select(RepoLot.trade_date).order_by(RepoLot.trade_date.asc())).scalar(),
        db.execute(select(BondLot.valuation_date).order_by(BondLot.valuation_date.asc())).scalar(),
    ]
    return min([d for d in dates if d is not None], default=None)


@router.get("/alerts", response_model=List[AlertOut])
def alerts(
    only_unresolved: bool = Query(False),
    cdu_id: Optional[int] = Query(None),
    since_days: int = Query(30),
    db: Session = Depends(get_db),
):
    since = date.today() - timedelta(days=since_days)
    q = select(Alert).where(Alert.alert_date >= since).order_by(Alert.created_at.desc()).limit(500)
    if only_unresolved:
        q = q.where(Alert.is_resolved.is_(False))
    if cdu_id:
        q = q.where(Alert.cdu_id == cdu_id)
    return list(db.execute(q).scalars().all())


@router.put("/alerts/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(alert_id: int, db: Session = Depends(get_db)):
    from services.alerts import resolve_alert as _resolve
    a = _resolve(db, alert_id)
    if not a:
        from fastapi import HTTPException
        raise HTTPException(404, "Алерт не найден")
    return a


@router.get("/history")
def dashboard_history(
    days: int = Query(90),
    from_: Optional[date] = Query(None, alias="from"),
    to_: Optional[date] = Query(None, alias="to"),
    cdu_ids: Optional[str] = Query(None),
    portfolio_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    upper = to_ or date.today()
    lower = from_ if from_ is not None else (upper - timedelta(days=days))
    selected_cdu_ids = {
        int(x) for x in cdu_ids.split(",")
        if x.strip().isdigit()
    } if cdu_ids else set()

    def cdu_allowed(cdu: Optional[CDU]) -> bool:
        if cdu is None:
            return False
        if selected_cdu_ids and cdu.id not in selected_cdu_ids:
            return False
        if portfolio_type and cdu.portfolio_type != portfolio_type:
            return False
        return True

    rows = db.execute(select(PortfolioSummary).where(
        PortfolioSummary.summary_date >= lower,
        PortfolioSummary.summary_date <= upper,
    ).order_by(PortfolioSummary.summary_date.asc())).scalars().all()
    out = []
    summary_keys: set[tuple[int, date]] = set()
    for s in rows:
        cdu = db.get(CDU, s.cdu_id)
        if not cdu_allowed(cdu):
            continue
        summary_keys.add((s.cdu_id, s.summary_date))
        out.append({
            "date": s.summary_date.isoformat(),
            "cdu_id": s.cdu_id,
            "cdu_short": cdu.short_name if cdu else "",
            "total_mv": s.total_mv_current,
            "ytm": s.ytm_weighted,
            "duration": s.duration_weighted,
            "benchmark_duration": s.benchmark_duration,
        })
    mv_rows = db.execute(select(MVSnapshot).where(
        MVSnapshot.snapshot_date >= lower,
        MVSnapshot.snapshot_date <= upper,
    ).order_by(MVSnapshot.snapshot_date.asc())).scalars().all()
    for s in mv_rows:
        if (s.cdu_id, s.snapshot_date) in summary_keys:
            continue
        cdu = db.get(CDU, s.cdu_id)
        if not cdu_allowed(cdu):
            continue
        out.append({
            "date": s.snapshot_date.isoformat(),
            "cdu_id": s.cdu_id,
            "cdu_short": cdu.short_name if cdu else "",
            "total_mv": s.market_value_total,
            "ytm": s.ytm_weighted,
            "duration": s.duration_weighted,
            "benchmark_duration": None,
        })
    return sorted(out, key=lambda x: (x["date"], x["cdu_id"]))
