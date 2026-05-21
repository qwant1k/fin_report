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

from auth import require_user

from database import get_db
from models.db_models import (
    BondLot,
    CashSnapshot,
    CDU,
    DepositLot,
    MVSnapshot,
    PortfolioPosition,
    PortfolioSummary,
    RepoLot,
)

router = APIRouter(
    prefix="/api/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_user)],
)

CATEGORY_LABELS = {
    "TOTAL": "Итого",
    "CASH": "Cash",
    "GOV_BONDS": "Государственные облигации (МФ РК)",
    "REVERSE_REPO": "Обратное REPO",
    "MFO_BONDS": "МФО",
    "AGENCY_BONDS": "Агентские облигации",
    "FOREIGN_BONDS": "Иностранные ЦБ",
    "DEPOSIT": "Депозиты",
    "RECEIVABLES": "Дебиторская задолженность",
}


def _resolve_period(from_: Optional[date], to_: Optional[date],
                    days: Optional[int]) -> tuple[date, date]:
    if from_ and to_:
        return from_, to_
    end = to_ or date.today()
    start = from_ or (end - timedelta(days=days or 90))
    return start, end


def _latest_data_date(db: Session) -> Optional[date]:
    candidates = [
        db.execute(select(func.max(PortfolioSummary.summary_date))).scalar_one_or_none(),
        db.execute(select(func.max(MVSnapshot.snapshot_date))).scalar_one_or_none(),
        db.execute(select(func.max(PortfolioPosition.position_date))).scalar_one_or_none(),
        db.execute(select(func.max(CashSnapshot.snapshot_date))).scalar_one_or_none(),
        db.execute(select(func.max(BondLot.valuation_date))).scalar_one_or_none(),
        db.execute(select(func.max(RepoLot.valuation_date))).scalar_one_or_none(),
    ]
    dates = [d for d in candidates if d is not None]
    return max(dates) if dates else None


def _earliest_data_date(db: Session) -> Optional[date]:
    candidates = [
        db.execute(select(func.min(PortfolioSummary.summary_date))).scalar_one_or_none(),
        db.execute(select(func.min(MVSnapshot.snapshot_date))).scalar_one_or_none(),
        db.execute(select(func.min(PortfolioPosition.position_date))).scalar_one_or_none(),
        db.execute(select(func.min(CashSnapshot.snapshot_date))).scalar_one_or_none(),
        db.execute(select(func.min(BondLot.valuation_date))).scalar_one_or_none(),
        db.execute(select(func.min(RepoLot.valuation_date))).scalar_one_or_none(),
    ]
    dates = [d for d in candidates if d is not None]
    return min(dates) if dates else None


def _resolve_period_for_db(
    db: Session,
    from_: Optional[date],
    to_: Optional[date],
    days: Optional[int],
) -> tuple[date, date]:
    if from_ and to_:
        return from_, to_
    end = to_ or _latest_data_date(db) or date.today()
    start = from_ or (end - timedelta(days=days or 90))
    return start, end


def _parse_csv_ints(value: Optional[str]) -> list[int]:
    if not value:
        return []
    return [int(x) for x in value.split(",") if x.strip().isdigit()]


def _parse_csv_strings(value: Optional[str]) -> set[str]:
    if not value:
        return set()
    return {x.strip() for x in value.split(",") if x.strip()}


def _row_metric(row: dict, metric: str) -> Optional[float]:
    if metric in ("market_value", "mv"):
        return row.get("market_value")
    if metric == "daily_change":
        return row.get("daily_change")
    if metric == "ytm":
        return row.get("ytm")
    if metric == "duration":
        return row.get("duration")
    if metric == "pct":
        return row.get("pct")
    if metric == "cash_flow":
        return row.get("cash_flow")
    if metric == "return_pct":
        return row.get("return_pct")
    if metric == "count":
        return 1.0
    return row.get("market_value")


def _apply_common_filters(
    rows: list[dict],
    *,
    cdu_ids: list[int],
    categories: set[str],
    portfolio_type: Optional[str],
    min_value: Optional[float],
    max_value: Optional[float],
    metric: str,
) -> list[dict]:
    out = []
    for row in rows:
        if cdu_ids and row.get("cdu_id") not in cdu_ids:
            continue
        if categories and row.get("category") not in categories:
            continue
        if portfolio_type and row.get("portfolio_type") != portfolio_type:
            continue
        metric_value = _row_metric(row, metric)
        if min_value is not None and (metric_value is None or metric_value < min_value):
            continue
        if max_value is not None and (metric_value is None or metric_value > max_value):
            continue
        row["metric_value"] = metric_value
        out.append(row)
    return out


@router.get("/meta")
def analytics_meta(db: Session = Depends(get_db)):
    min_date = _earliest_data_date(db)
    max_date = _latest_data_date(db)
    cdus = db.execute(select(CDU).order_by(CDU.portfolio_type, CDU.name)).scalars().all()
    categories = sorted({
        "TOTAL",
        *[
            c for (c,) in db.execute(
                select(PortfolioPosition.instrument_category).distinct()
            ).all() if c
        ],
        *[
            c for (c,) in db.execute(select(BondLot.category).distinct()).all() if c
        ],
        "CASH",
        "REVERSE_REPO",
    })
    return {
        "min_date": min_date.isoformat() if min_date else None,
        "max_date": max_date.isoformat() if max_date else None,
        "sources": [
            {"value": "summary", "label": "Итоги ЧДУ"},
            {"value": "positions", "label": "Категории Report"},
            {"value": "mv", "label": "История MV"},
            {"value": "cash", "label": "Cash"},
            {"value": "lots", "label": "Лоты инструментов"},
        ],
        "metrics": [
            {"value": "market_value", "label": "Market value"},
            {"value": "daily_change", "label": "Daily change"},
            {"value": "ytm", "label": "YTM"},
            {"value": "duration", "label": "Duration"},
            {"value": "pct", "label": "Доля"},
            {"value": "cash_flow", "label": "Cash flow"},
            {"value": "return_pct", "label": "Return"},
            {"value": "count", "label": "Количество"},
        ],
        "group_by": [
            {"value": "date", "label": "Дата"},
            {"value": "cdu", "label": "ЧДУ"},
            {"value": "category", "label": "Категория"},
            {"value": "portfolio_type", "label": "Тип портфеля"},
            {"value": "instrument", "label": "Инструмент"},
        ],
        "categories": [
            {"value": cat, "label": CATEGORY_LABELS.get(cat, cat)}
            for cat in categories
        ],
        "cdus": [
            {
                "id": c.id,
                "name": c.name,
                "short_name": c.short_name,
                "portfolio_type": c.portfolio_type,
                "portfolio_code": c.portfolio_code,
                "is_active": c.is_active,
            }
            for c in cdus
        ],
    }


@router.get("/workbench")
def analytics_workbench(
    source: str = Query("positions"),
    metric: str = Query("market_value"),
    group_by: str = Query("date,cdu,category"),
    from_: Optional[date] = Query(None, alias="from"),
    to_: Optional[date] = Query(None, alias="to"),
    days: Optional[int] = Query(180),
    cdu_ids: Optional[str] = Query(None),
    categories: Optional[str] = Query(None),
    portfolio_type: Optional[str] = Query(None),
    min_value: Optional[float] = Query(None),
    max_value: Optional[float] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    sort: str = Query("date_asc"),
    db: Session = Depends(get_db),
):
    start, end = _resolve_period_for_db(db, from_, to_, days)
    ids = _parse_csv_ints(cdu_ids)
    category_set = _parse_csv_strings(categories)
    raw_rows = _load_workbench_rows(db, source, start, end)
    filtered = _apply_common_filters(
        raw_rows,
        cdu_ids=ids,
        categories=category_set,
        portfolio_type=portfolio_type,
        min_value=min_value,
        max_value=max_value,
        metric=metric,
    )
    groups = [g.strip() for g in group_by.split(",") if g.strip()]
    grouped = _group_workbench_rows(filtered, groups, metric)
    reverse = sort in ("value_desc", "date_desc")
    if sort.startswith("value"):
        grouped.sort(key=lambda x: x.get("metric_value") or 0.0, reverse=reverse)
    else:
        grouped.sort(key=lambda x: (x.get("date") or "", x.get("cdu_short") or "", x.get("category") or ""), reverse=reverse)
    return {
        "source": source,
        "metric": metric,
        "group_by": groups,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "rows_total": len(grouped),
        "rows": grouped[:limit],
    }


def _load_workbench_rows(db: Session, source: str, start: date, end: date) -> list[dict]:
    if source == "summary":
        rows = db.execute(select(PortfolioSummary, CDU).join(CDU, PortfolioSummary.cdu_id == CDU.id).where(
            PortfolioSummary.summary_date >= start,
            PortfolioSummary.summary_date <= end,
        )).all()
        return [
            {
                "date": s.summary_date.isoformat(),
                "cdu_id": s.cdu_id,
                "cdu_name": c.name,
                "cdu_short": c.short_name,
                "portfolio_type": c.portfolio_type,
                "category": "TOTAL",
                "instrument": "TOTAL",
                "market_value": s.total_mv_current,
                "daily_change": s.total_daily_change,
                "pct": s.cdu_share_pct,
                "ytm": s.ytm_weighted,
                "duration": s.duration_weighted,
            }
            for s, c in rows
        ]
    if source == "mv":
        rows = db.execute(select(MVSnapshot, CDU).join(CDU, MVSnapshot.cdu_id == CDU.id).where(
            MVSnapshot.snapshot_date >= start,
            MVSnapshot.snapshot_date <= end,
        )).all()
        return [
            {
                "date": s.snapshot_date.isoformat(),
                "cdu_id": s.cdu_id,
                "cdu_name": c.name,
                "cdu_short": c.short_name,
                "portfolio_type": c.portfolio_type,
                "category": "TOTAL",
                "instrument": "MV",
                "market_value": s.market_value_total,
                "cash_flow": s.cash_flow,
                "return_pct": s.return_pct,
                "ytm": s.ytm_weighted,
                "duration": s.duration_weighted,
            }
            for s, c in rows
        ]
    if source == "cash":
        rows = db.execute(select(CashSnapshot, CDU).join(CDU, CashSnapshot.cdu_id == CDU.id).where(
            CashSnapshot.snapshot_date >= start,
            CashSnapshot.snapshot_date <= end,
        )).all()
        return [
            {
                "date": s.snapshot_date.isoformat(),
                "cdu_id": s.cdu_id,
                "cdu_name": c.name,
                "cdu_short": c.short_name,
                "portfolio_type": c.portfolio_type,
                "category": "CASH",
                "instrument": s.currency,
                "market_value": s.amount_kzt or s.amount or 0.0,
            }
            for s, c in rows
        ]
    if source == "lots":
        rows: list[dict] = []
        for lot, c in db.execute(select(BondLot, CDU).join(CDU, BondLot.cdu_id == CDU.id).where(
            BondLot.valuation_date >= start,
            BondLot.valuation_date <= end,
        )).all():
            rows.append({
                "date": lot.valuation_date.isoformat(),
                "cdu_id": lot.cdu_id,
                "cdu_name": c.name,
                "cdu_short": c.short_name,
                "portfolio_type": c.portfolio_type,
                "category": lot.category,
                "instrument": lot.instrument_code or lot.isin,
                "isin": lot.isin,
                "market_value": lot.market_value or lot.total_value or lot.face_value_current or 0.0,
                "ytm": lot.ytm,
                "duration": lot.duration,
            })
        for lot, c in db.execute(select(RepoLot, CDU).join(CDU, RepoLot.cdu_id == CDU.id).where(
            RepoLot.valuation_date >= start,
            RepoLot.valuation_date <= end,
        )).all():
            rows.append({
                "date": lot.valuation_date.isoformat(),
                "cdu_id": lot.cdu_id,
                "cdu_name": c.name,
                "cdu_short": c.short_name,
                "portfolio_type": c.portfolio_type,
                "category": "REVERSE_REPO",
                "instrument": lot.instrument_code or lot.isin or lot.deal_id,
                "isin": lot.isin,
                "market_value": lot.market_value or lot.close_value or lot.face_value or 0.0,
                "ytm": lot.ytm or lot.repo_rate_pct,
                "duration": lot.duration or ((lot.term_days / 365.0) if lot.term_days else None),
            })
        for lot, c in db.execute(select(DepositLot, CDU).join(CDU, DepositLot.cdu_id == CDU.id).where(
            DepositLot.valuation_date >= start,
            DepositLot.valuation_date <= end,
        )).all():
            rows.append({
                "date": lot.valuation_date.isoformat(),
                "cdu_id": lot.cdu_id,
                "cdu_name": c.name,
                "cdu_short": c.short_name,
                "portfolio_type": c.portfolio_type,
                "category": "DEPOSIT",
                "instrument": "Deposit",
                "market_value": lot.market_value or lot.principal or 0.0,
                "ytm": lot.interest_rate_pct,
            })
        return rows

    rows = db.execute(select(PortfolioPosition, CDU).join(CDU, PortfolioPosition.cdu_id == CDU.id).where(
        PortfolioPosition.position_date >= start,
        PortfolioPosition.position_date <= end,
    )).all()
    return [
        {
            "date": p.position_date.isoformat(),
            "cdu_id": p.cdu_id,
            "cdu_name": c.name,
            "cdu_short": c.short_name,
            "portfolio_type": c.portfolio_type,
            "category": p.instrument_category,
            "instrument": p.instrument_name or p.instrument_category,
            "market_value": p.market_value_current,
            "daily_change": p.daily_change,
            "pct": p.pct_of_total,
            "ytm": p.ytm,
            "duration": p.duration,
        }
        for p, c in rows
    ]


def _group_workbench_rows(rows: list[dict], groups: list[str], metric: str) -> list[dict]:
    if not groups:
        groups = ["date"]
    buckets: dict[tuple, dict] = {}
    for row in rows:
        key_values = []
        for group in groups:
            if group == "cdu":
                key_values.append(row.get("cdu_id"))
            else:
                key_values.append(row.get(group))
        key = tuple(key_values)
        bucket = buckets.setdefault(key, {
            "date": row.get("date") if "date" in groups else None,
            "cdu_id": row.get("cdu_id") if "cdu" in groups else None,
            "cdu_name": row.get("cdu_name") if "cdu" in groups else None,
            "cdu_short": row.get("cdu_short") if "cdu" in groups else None,
            "portfolio_type": row.get("portfolio_type") if ("portfolio_type" in groups or "cdu" in groups) else None,
            "category": row.get("category") if "category" in groups else None,
            "instrument": row.get("instrument") if "instrument" in groups else None,
            "metric_value": 0.0,
            "market_value": 0.0,
            "daily_change": 0.0,
            "ytm_weighted_sum": 0.0,
            "ytm_weight": 0.0,
            "duration_weighted_sum": 0.0,
            "duration_weight": 0.0,
            "count": 0,
        })
        metric_value = _row_metric(row, metric)
        if metric == "count":
            bucket["metric_value"] += 1.0
        elif metric_value is not None:
            if metric in ("ytm", "duration", "return_pct", "pct"):
                bucket["metric_value"] += float(metric_value)
            else:
                bucket["metric_value"] += float(metric_value)
        mv = row.get("market_value") or 0.0
        bucket["market_value"] += mv
        bucket["daily_change"] += row.get("daily_change") or 0.0
        if row.get("ytm") is not None and mv:
            bucket["ytm_weighted_sum"] += row["ytm"] * abs(mv)
            bucket["ytm_weight"] += abs(mv)
        if row.get("duration") is not None and mv:
            bucket["duration_weighted_sum"] += row["duration"] * abs(mv)
            bucket["duration_weight"] += abs(mv)
        bucket["count"] += 1

    out = []
    for bucket in buckets.values():
        if metric in ("ytm", "duration", "return_pct", "pct") and bucket["count"]:
            bucket["metric_value"] = bucket["metric_value"] / bucket["count"]
        bucket["ytm"] = (
            bucket["ytm_weighted_sum"] / bucket["ytm_weight"]
            if bucket["ytm_weight"] else None
        )
        bucket["duration"] = (
            bucket["duration_weighted_sum"] / bucket["duration_weight"]
            if bucket["duration_weight"] else None
        )
        bucket.pop("ytm_weighted_sum")
        bucket.pop("ytm_weight")
        bucket.pop("duration_weighted_sum")
        bucket.pop("duration_weight")
        out.append(bucket)
    return out


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
    start, end = _resolve_period_for_db(db, from_, to_, days)

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
    start, end = _resolve_period_for_db(db, from_, to_, days)

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
    start, end = _resolve_period_for_db(db, from_, to_, days)

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
    start, end = _resolve_period_for_db(db, from_, to_, days)

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
