"""Analytics endpoints — графики и тренды на основе MV/Cash snapshots.

В отличие от /api/dashboard/history (который читает PortfolioSummary —
данные дневного расчёта), эти endpoints читают MVSnapshot/CashSnapshot —
данные импорта исторических Risk Report. Это позволяет видеть всю
6-месячную историю даже без ежедневного расчёта в системе.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import get_db
from models.db_models import (
    BondLot,
    CashSnapshot,
    CDU,
    DepositLot,
    MVSnapshot,
    RepoLot,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _resolve_period(from_: Optional[date], to_: Optional[date],
                    days: Optional[int]) -> tuple[date, date]:
    if from_ and to_:
        return from_, to_
    end = to_ or date.today()
    start = from_ or (end - timedelta(days=days or 90))
    return start, end


# ─────────── Portfolio MV trend (per CDU per date) ───────────
@router.get("/portfolio-trend")
def portfolio_trend(
    from_: Optional[date] = Query(None, alias="from"),
    to_: Optional[date] = Query(None, alias="to"),
    days: Optional[int] = Query(180),
    cdu_ids: Optional[str] = Query(None, description="CSV list of cdu_id"),
    portfolio_type: Optional[str] = Query(None,
        description="PRIVATE_CDU/NBRK_OWN/NBRK_RESERVE"),
    db: Session = Depends(get_db),
):
    """История MV по ЧДУ за период из MVSnapshot."""
    start, end = _resolve_period(from_, to_, days)

    q = select(MVSnapshot, CDU).join(CDU, MVSnapshot.cdu_id == CDU.id).where(
        MVSnapshot.snapshot_date >= start,
        MVSnapshot.snapshot_date <= end,
    ).order_by(MVSnapshot.snapshot_date.asc())

    if cdu_ids:
        ids = [int(x) for x in cdu_ids.split(",") if x.strip().isdigit()]
        if ids:
            q = q.where(MVSnapshot.cdu_id.in_(ids))
    if portfolio_type:
        q = q.where(CDU.portfolio_type == portfolio_type)

    rows = db.execute(q).all()
    return [
        {
            "date": s.snapshot_date.isoformat(),
            "cdu_id": s.cdu_id,
            "cdu_name": cdu.name,
            "cdu_short": cdu.short_name,
            "portfolio_type": cdu.portfolio_type,
            "market_value_total": s.market_value_total,
            "cash_flow": s.cash_flow,
            "return_pct": s.return_pct,
            "ytm_weighted": s.ytm_weighted,
            "duration_weighted": s.duration_weighted,
        }
        for s, cdu in rows
    ]


# ─────────── Fund-level aggregated trend ───────────
@router.get("/fund-trend")
def fund_trend(
    from_: Optional[date] = Query(None, alias="from"),
    to_: Optional[date] = Query(None, alias="to"),
    days: Optional[int] = Query(180),
    portfolio_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Агрегированный тренд по всему Фонду = Σ MV всех ЧДУ за дату."""
    start, end = _resolve_period(from_, to_, days)

    base = select(
        MVSnapshot.snapshot_date.label("d"),
        func.sum(MVSnapshot.market_value_total).label("mv_total"),
        func.avg(MVSnapshot.ytm_weighted).label("ytm_avg"),
        func.avg(MVSnapshot.duration_weighted).label("dur_avg"),
        func.count(MVSnapshot.id).label("cdu_count"),
    ).where(
        MVSnapshot.snapshot_date >= start,
        MVSnapshot.snapshot_date <= end,
    ).group_by(MVSnapshot.snapshot_date).order_by(MVSnapshot.snapshot_date.asc())

    if portfolio_type:
        base = base.join(CDU, MVSnapshot.cdu_id == CDU.id).where(
            CDU.portfolio_type == portfolio_type
        )

    rows = db.execute(base).all()
    return [
        {
            "date": r.d.isoformat(),
            "market_value_total": float(r.mv_total or 0),
            "ytm_weighted": float(r.ytm_avg) if r.ytm_avg is not None else None,
            "duration_weighted": float(r.dur_avg) if r.dur_avg is not None else None,
            "cdu_count": int(r.cdu_count),
        }
        for r in rows
    ]


# ─────────── Cash trend ───────────
@router.get("/cash-trend")
def cash_trend(
    from_: Optional[date] = Query(None, alias="from"),
    to_: Optional[date] = Query(None, alias="to"),
    days: Optional[int] = Query(180),
    cdu_ids: Optional[str] = Query(None),
    currency: str = Query("KZT"),
    db: Session = Depends(get_db),
):
    """История Cash по ЧДУ × дата × валюта (по умолчанию KZT)."""
    start, end = _resolve_period(from_, to_, days)

    q = select(CashSnapshot, CDU).join(CDU, CashSnapshot.cdu_id == CDU.id).where(
        CashSnapshot.snapshot_date >= start,
        CashSnapshot.snapshot_date <= end,
        CashSnapshot.currency == currency,
    ).order_by(CashSnapshot.snapshot_date.asc())

    if cdu_ids:
        ids = [int(x) for x in cdu_ids.split(",") if x.strip().isdigit()]
        if ids:
            q = q.where(CashSnapshot.cdu_id.in_(ids))

    rows = db.execute(q).all()
    return [
        {
            "date": s.snapshot_date.isoformat(),
            "cdu_id": s.cdu_id,
            "cdu_short": cdu.short_name,
            "currency": s.currency,
            "amount": s.amount,
        }
        for s, cdu in rows
    ]


# ─────────── Category breakdown on a date ───────────
@router.get("/category-breakdown")
def category_breakdown(
    on_date: Optional[date] = Query(None, alias="date"),
    cdu_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Состав портфеля по категориям на конкретную дату.

    Берём BondLot (по category), RepoLot (REVERSE_REPO), DepositLot (DEPOSIT),
    CashSnapshot (CASH). Возвращает массив { category, market_value, count }.
    """
    if on_date is None:
        # Последняя доступная дата по MVSnapshot
        last = db.execute(
            select(func.max(MVSnapshot.snapshot_date))
        ).scalar_one_or_none()
        on_date = last or date.today()

    breakdown: dict[str, dict] = {}

    def _accumulate(cat: str, mv: Optional[float]):
        if mv is None or mv == 0:
            return
        b = breakdown.setdefault(cat, {"market_value": 0.0, "count": 0})
        b["market_value"] += float(mv)
        b["count"] += 1

    # BondLot — по category
    bl_q = select(BondLot).where(BondLot.valuation_date == on_date)
    if cdu_id:
        bl_q = bl_q.where(BondLot.cdu_id == cdu_id)
    for bl in db.execute(bl_q).scalars().all():
        _accumulate(bl.category, bl.market_value or bl.face_value_current or 0)

    # RepoLot
    rl_q = select(RepoLot).where(RepoLot.valuation_date == on_date)
    if cdu_id:
        rl_q = rl_q.where(RepoLot.cdu_id == cdu_id)
    for rl in db.execute(rl_q).scalars().all():
        _accumulate("REVERSE_REPO", rl.market_value or rl.face_value or 0)

    # DepositLot
    dl_q = select(DepositLot).where(DepositLot.valuation_date == on_date)
    if cdu_id:
        dl_q = dl_q.where(DepositLot.cdu_id == cdu_id)
    for dl in db.execute(dl_q).scalars().all():
        _accumulate("DEPOSIT", dl.market_value or dl.principal or 0)

    # Cash (KZT only — для USD конвертация не делается на этом этапе)
    c_q = select(CashSnapshot).where(
        CashSnapshot.snapshot_date == on_date,
        CashSnapshot.currency == "KZT",
    )
    if cdu_id:
        c_q = c_q.where(CashSnapshot.cdu_id == cdu_id)
    for c in db.execute(c_q).scalars().all():
        _accumulate("CASH", c.amount)

    total = sum(b["market_value"] for b in breakdown.values()) or 1.0
    return {
        "date": on_date.isoformat(),
        "cdu_id": cdu_id,
        "total_market_value": total,
        "breakdown": [
            {
                "category": cat,
                "market_value": data["market_value"],
                "pct": data["market_value"] / total if total else 0.0,
                "count": data["count"],
            }
            for cat, data in sorted(
                breakdown.items(), key=lambda kv: -kv[1]["market_value"]
            )
        ],
    }


# ─────────── Period summary statistics ───────────
@router.get("/period-summary")
def period_summary(
    from_: Optional[date] = Query(None, alias="from"),
    to_: Optional[date] = Query(None, alias="to"),
    days: Optional[int] = Query(180),
    portfolio_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Сводка за период: начальное/конечное MV, изменение, средняя YTM/Duration."""
    start, end = _resolve_period(from_, to_, days)

    base = select(
        MVSnapshot.snapshot_date.label("d"),
        func.sum(MVSnapshot.market_value_total).label("mv_total"),
        func.avg(MVSnapshot.ytm_weighted).label("ytm_avg"),
        func.avg(MVSnapshot.duration_weighted).label("dur_avg"),
    ).where(
        MVSnapshot.snapshot_date >= start,
        MVSnapshot.snapshot_date <= end,
    ).group_by(MVSnapshot.snapshot_date).order_by(MVSnapshot.snapshot_date.asc())

    if portfolio_type:
        base = base.join(CDU, MVSnapshot.cdu_id == CDU.id).where(
            CDU.portfolio_type == portfolio_type
        )

    rows = db.execute(base).all()
    if not rows:
        return {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "data_points": 0,
        }

    first_mv = float(rows[0].mv_total or 0)
    last_mv = float(rows[-1].mv_total or 0)
    delta = last_mv - first_mv
    delta_pct = (delta / first_mv) if first_mv else 0.0

    # Best/worst day deltas
    daily_deltas = []
    for i in range(1, len(rows)):
        prev = float(rows[i - 1].mv_total or 0)
        cur = float(rows[i].mv_total or 0)
        if prev > 0:
            daily_deltas.append({
                "date": rows[i].d.isoformat(),
                "delta": cur - prev,
                "delta_pct": (cur - prev) / prev,
            })

    best = max(daily_deltas, key=lambda x: x["delta_pct"]) if daily_deltas else None
    worst = min(daily_deltas, key=lambda x: x["delta_pct"]) if daily_deltas else None

    avg_ytm = sum(float(r.ytm_avg) for r in rows if r.ytm_avg is not None) / max(
        sum(1 for r in rows if r.ytm_avg is not None), 1
    ) if any(r.ytm_avg is not None for r in rows) else None
    avg_dur = sum(float(r.dur_avg) for r in rows if r.dur_avg is not None) / max(
        sum(1 for r in rows if r.dur_avg is not None), 1
    ) if any(r.dur_avg is not None for r in rows) else None

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "data_points": len(rows),
        "mv_start": first_mv,
        "mv_end": last_mv,
        "mv_delta": delta,
        "mv_delta_pct": delta_pct,
        "best_day": best,
        "worst_day": worst,
        "avg_ytm": avg_ytm,
        "avg_duration": avg_dur,
    }


# ─────────── CDU list with portfolio type ───────────
@router.get("/cdus")
def list_cdus(db: Session = Depends(get_db)):
    """Список ЧДУ с типом портфеля для фильтров на фронте."""
    rows = db.execute(select(CDU).order_by(CDU.portfolio_type, CDU.name)).scalars().all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "short_name": c.short_name,
            "portfolio_type": c.portfolio_type,
            "portfolio_code": c.portfolio_code,
            "is_active": c.is_active,
        }
        for c in rows
    ]
