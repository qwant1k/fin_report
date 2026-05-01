"""Dashboard summary endpoint — full data for the React dashboard."""
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models.db_models import (
    Alert,
    CDU,
    CDULimit,
    MBMIndex,
    PortfolioPosition,
    PortfolioSummary,
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

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardResponse)
def dashboard_summary(
    report_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    if report_date is None:
        last = db.execute(select(PortfolioSummary).order_by(PortfolioSummary.summary_date.desc())
                          ).scalars().first()
        report_date = last.summary_date if last else date.today()

    summaries = db.execute(select(PortfolioSummary).where(
        PortfolioSummary.summary_date == report_date,
    )).scalars().all()
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
        positions = db.execute(select(PortfolioPosition).where(
            PortfolioPosition.cdu_id == s.cdu_id,
            PortfolioPosition.position_date == report_date,
        )).scalars().all()
        pos_by_cat = {p.instrument_category: p for p in positions}
        limits_q = db.execute(select(CDULimit).where(CDULimit.cdu_id == cdu.id)).scalars().all()
        limits_map = {l.instrument_category: (l.min_limit_pct, l.max_limit_pct) for l in limits_q}

        rows: List[CategoryRow] = []
        for cat in CATEGORY_ORDER:
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
        blocks=blocks,
    )


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
def dashboard_history(days: int = Query(90), db: Session = Depends(get_db)):
    since = date.today() - timedelta(days=days)
    rows = db.execute(select(PortfolioSummary).where(
        PortfolioSummary.summary_date >= since,
    ).order_by(PortfolioSummary.summary_date.asc())).scalars().all()
    out = []
    for s in rows:
        cdu = db.get(CDU, s.cdu_id)
        out.append({
            "date": s.summary_date.isoformat(),
            "cdu_id": s.cdu_id,
            "cdu_short": cdu.short_name if cdu else "",
            "total_mv": s.total_mv_current,
            "ytm": s.ytm_weighted,
            "duration": s.duration_weighted,
            "benchmark_duration": s.benchmark_duration,
        })
    return out
