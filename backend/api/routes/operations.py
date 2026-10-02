"""Operations journal API built on the canonical Trade ledger."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from auth import require_permission
from database import get_db
from models.db_models import CDU, RawTrade, SourceDocument, Trade, TradeFile

router = APIRouter(
    prefix="/api/operations",
    tags=["operations"],
    dependencies=[Depends(require_permission("page.history"))],
)


@router.get("/raw-trades")
def list_raw_trades(
    trade_date: Optional[date] = None,
    from_: Optional[date] = Query(None, alias="from"),
    to_: Optional[date] = Query(None, alias="to"),
    cdu_id: Optional[int] = None,
    q: Optional[str] = None,
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """Return incoming Trade Report rows in a table close to the source file."""
    if trade_date is not None:
        from_ = trade_date
        to_ = trade_date
    if to_ is None:
        to_ = date.today()
    if from_ is None:
        from_ = to_ - timedelta(days=30)

    filters = [RawTrade.trade_date >= from_, RawTrade.trade_date <= to_]
    if cdu_id:
        filters.append(RawTrade.cdu_id == cdu_id)
    if q:
        pattern = f"%{q.strip()}%"
        filters.append(or_(
            RawTrade.instrument_code.ilike(pattern),
            RawTrade.deal_number.ilike(pattern),
            RawTrade.order_number.ilike(pattern),
            RawTrade.regime_code.ilike(pattern),
            RawTrade.participant_code.ilike(pattern),
        ))

    total = db.query(func.count(RawTrade.id)).filter(*filters).scalar() or 0
    rows = (
        db.query(
            RawTrade,
            CDU.name.label("cdu_name"),
            CDU.short_name.label("cdu_short"),
            TradeFile.filename.label("source_file"),
        )
        .outerjoin(CDU, RawTrade.cdu_id == CDU.id)
        .outerjoin(TradeFile, RawTrade.file_id == TradeFile.id)
        .filter(*filters)
        .order_by(RawTrade.trade_date.desc(), RawTrade.id.desc())
        .limit(limit)
        .all()
    )

    return {
        "from": from_.isoformat(),
        "to": to_.isoformat(),
        "rows_total": total,
        "rows": [
            _raw_trade_row(row, cdu_name, cdu_short, source_file)
            for row, cdu_name, cdu_short, source_file in rows
        ],
    }


@router.get("")
def list_operations(
    from_: Optional[date] = Query(None, alias="from"),
    to_: Optional[date] = Query(None, alias="to"),
    cdu_id: Optional[int] = None,
    operation_type: Optional[str] = None,
    q: Optional[str] = None,
    include_inactive: bool = False,
    limit: int = Query(300, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Return a user-facing slice of the operation ledger.

    The table is intentionally based on ``trades`` rather than ``raw_trades``:
    these rows are normalized, auditable and already power lots/holdings.
    """
    if to_ is None:
        to_ = date.today()
    if from_ is None:
        from_ = to_ - timedelta(days=30)

    filters = [Trade.trade_date >= from_, Trade.trade_date <= to_]
    if not include_inactive:
        filters.append(Trade.is_active == True)  # noqa: E712
    if cdu_id:
        filters.append(Trade.cdu_id == cdu_id)
    if operation_type:
        if operation_type == "REPO":
            filters.append(Trade.operation_type.in_(["REPO_OPEN", "REPO_CLOSE"]))
        else:
            filters.append(Trade.operation_type == operation_type)
    if q:
        pattern = f"%{q.strip()}%"
        filters.append(or_(
            Trade.instrument_code.ilike(pattern),
            Trade.isin.ilike(pattern),
            Trade.deal_id.ilike(pattern),
            Trade.description.ilike(pattern),
        ))

    total = db.query(func.count(Trade.id)).filter(*filters).scalar() or 0
    rows = (
        db.query(Trade, CDU.name.label("cdu_name"), CDU.short_name.label("cdu_short"), SourceDocument.file_name.label("source_file"))
        .join(CDU, Trade.cdu_id == CDU.id)
        .outerjoin(SourceDocument, Trade.source_doc_id == SourceDocument.id)
        .filter(*filters)
        .order_by(Trade.trade_date.desc(), Trade.id.desc())
        .limit(limit)
        .all()
    )

    summary_rows = (
        db.query(Trade.operation_type, func.count(Trade.id), func.coalesce(func.sum(Trade.amount_kzt), 0.0))
        .filter(*filters)
        .group_by(Trade.operation_type)
        .all()
    )
    by_operation = [
        {"operation_type": op or "OTHER", "count": count, "amount_kzt": amount}
        for op, count, amount in summary_rows
    ]
    flagged = (
        db.query(func.count(Trade.id))
        .filter(*filters, Trade.price_flag == True)  # noqa: E712
        .scalar()
        or 0
    )

    return {
        "from": from_.isoformat(),
        "to": to_.isoformat(),
        "rows_total": total,
        "rows": [_trade_row(t, cdu_name, cdu_short, source_file) for t, cdu_name, cdu_short, source_file in rows],
        "summary": {
            "by_operation": by_operation,
            "flagged_prices": flagged,
            "net_amount_kzt": sum(item["amount_kzt"] or 0.0 for item in by_operation),
        },
    }


def _raw_trade_row(row: RawTrade, cdu_name: str | None, cdu_short: str | None, source_file: str | None) -> dict:
    return {
        "id": row.id,
        "file_id": row.file_id,
        "cdu_id": row.cdu_id,
        "cdu_name": cdu_name,
        "cdu_short": cdu_short,
        "source_file": source_file,
        "trade_date": row.trade_date.isoformat() if row.trade_date else None,
        "deal_number": row.deal_number,
        "order_number": row.order_number,
        "trade_time": row.trade_time,
        "kp": row.kp,
        "operation_type": row.operation_type,
        "participant_code": row.participant_code,
        "firm_code": row.firm_code,
        "partner_code": row.partner_code,
        "trade_account": row.trade_account,
        "regime_code": row.regime_code,
        "instrument_code": row.instrument_code,
        "instrument_category": row.instrument_category,
        "price": row.price,
        "lots": row.lots,
        "volume": row.volume,
        "settlement_date": row.settlement_date.isoformat() if row.settlement_date else None,
        "accrued_interest_volume": row.accrued_interest_volume,
        "yield_pct": row.yield_pct,
        "period_code": row.period_code,
        "settlement_code": row.settlement_code,
        "type_code": row.type_code,
        "commission_total": row.commission_total,
        "repo_rate_pct": row.repo_rate_pct,
        "repo_sum": row.repo_sum,
        "repo_buyback_sum": row.repo_buyback_sum,
        "repo_term_days": row.repo_term_days,
        "currency_code": row.currency_code,
        "trading_date": row.trading_date.isoformat() if row.trading_date else None,
        "status": row.status,
        "nominal_volume": row.nominal_volume,
        "clearing_account": row.clearing_account,
    }


def _trade_row(trade: Trade, cdu_name: str | None, cdu_short: str | None, source_file: str | None) -> dict:
    return {
        "id": trade.id,
        "cdu_id": trade.cdu_id,
        "cdu_name": cdu_name,
        "cdu_short": cdu_short,
        "trade_date": trade.trade_date.isoformat() if trade.trade_date else None,
        "value_date": trade.value_date.isoformat() if trade.value_date else None,
        "operation_type": trade.operation_type,
        "direction": trade.direction,
        "instrument_kind": trade.instrument_kind,
        "instrument_category": trade.instrument_category,
        "instrument_code": trade.instrument_code,
        "isin": trade.isin,
        "description": trade.description,
        "deal_id": trade.deal_id,
        "portfolio_code": trade.portfolio_code,
        "amount_kzt": trade.amount_kzt,
        "amount_ccy": trade.amount_ccy,
        "currency": trade.currency,
        "quantity": trade.quantity,
        "face_value": trade.face_value,
        "clean_price": trade.clean_price,
        "market_price": trade.market_price,
        "price_original": trade.price_original,
        "price_kase": trade.price_kase,
        "price_final": trade.price_final,
        "price_flag": trade.price_flag,
        "price_diff_pct": trade.price_diff_pct,
        "ytm": trade.ytm,
        "repo_rate_pct": trade.repo_rate_pct,
        "repo_term_days": trade.repo_term_days,
        "commission_total": trade.commission_total,
        "source_doc_id": trade.source_doc_id,
        "source_file": source_file,
        "source_row_idx": trade.source_row_idx,
        "is_manual": trade.is_manual,
        "is_synthetic": trade.is_synthetic,
        "is_active": trade.is_active,
        "created_by": trade.created_by,
        "created_at": trade.created_at.isoformat() if trade.created_at else None,
    }
