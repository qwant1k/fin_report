"""REST API for the SecurityHolding catalogue.

Endpoints
---------
GET  /api/securities/                List with filters (cdu, category, search, source).
GET  /api/securities/summary         KPI-style aggregates (count, total market value).
POST /api/securities/                Create a MANUAL holding.
GET  /api/securities/{id}            Single holding.
PATCH /api/securities/{id}           Update (any field). MANUAL-only for quantity/avg.
DELETE /api/securities/{id}          Delete (MANUAL only — AUTO are managed by sync).
POST /api/securities/sync            Trigger a full rebuild (admin/write).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from auth import require_permission, require_user
from database import get_db
from models.db_models import CDU, SecurityHolding, User
from services.audit import write_audit
from services.holdings_sync import sync_holdings


router = APIRouter(
    prefix="/api/securities",
    tags=["Securities catalogue"],
    dependencies=[Depends(require_permission("page.securities"))],
)


# ─────────────── helpers ───────────────

def _to_dict(h: SecurityHolding, cdu_name: Optional[str] = None) -> dict[str, Any]:
    return {
        "id": h.id,
        "cdu_id": h.cdu_id,
        "cdu_name": cdu_name,
        "isin": h.isin,
        "instrument_code": h.instrument_code,
        "instrument_name": h.instrument_name,
        "category": h.category,
        "currency": h.currency,
        "quantity": h.quantity,
        "avg_purchase_price": h.avg_purchase_price,
        "last_kase_price": h.last_kase_price,
        "last_kase_date": h.last_kase_date.isoformat() if h.last_kase_date else None,
        "market_value": h.market_value,
        "nominal_per_unit": h.nominal_per_unit,
        "coupon_rate_pct": h.coupon_rate_pct,
        "maturity_date": h.maturity_date.isoformat() if h.maturity_date else None,
        "source": h.source,
        "notes": h.notes,
        "last_synced_at": h.last_synced_at.isoformat() if h.last_synced_at else None,
        "updated_at": h.updated_at.isoformat() if h.updated_at else None,
        "updated_by": h.updated_by,
    }


def _join_cdu_names(db: Session, rows: list[SecurityHolding]) -> list[dict[str, Any]]:
    """Attach CDU display names without N+1 queries."""
    cdu_ids = {h.cdu_id for h in rows}
    if not cdu_ids:
        return [_to_dict(h) for h in rows]
    name_by_id = {
        c.id: c.short_name or c.name
        for c in db.query(CDU).filter(CDU.id.in_(cdu_ids)).all()
    }
    return [_to_dict(h, name_by_id.get(h.cdu_id)) for h in rows]


# ─────────────── routes ───────────────

@router.get("/", dependencies=[Depends(require_user)])
def list_holdings(
    cdu_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    source: Optional[str] = Query(None, regex="^(AUTO|MANUAL)$"),
    search: Optional[str] = Query(None, description="ISIN / code / name substring"),
    only_with_qty: bool = Query(False, description="Скрыть позиции с нулевым количеством"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    q = db.query(SecurityHolding)
    if cdu_id is not None:
        q = q.filter(SecurityHolding.cdu_id == cdu_id)
    if category:
        q = q.filter(SecurityHolding.category == category)
    if source:
        q = q.filter(SecurityHolding.source == source)
    if only_with_qty:
        q = q.filter(SecurityHolding.quantity != 0)
    if search:
        pattern = f"%{search.strip()}%"
        q = q.filter(or_(
            SecurityHolding.isin.ilike(pattern),
            SecurityHolding.instrument_code.ilike(pattern),
            SecurityHolding.instrument_name.ilike(pattern),
        ))
    rows = q.order_by(
        SecurityHolding.category.asc().nullslast(),
        SecurityHolding.isin.asc(),
    ).all()
    return _join_cdu_names(db, rows)


@router.get("/summary", dependencies=[Depends(require_user)])
def summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Aggregate counters for UI KPI cards."""
    rows = db.query(SecurityHolding).all()
    total_value = sum(r.market_value or 0 for r in rows)
    by_category: dict[str, dict[str, float]] = {}
    for r in rows:
        bucket = by_category.setdefault(
            r.category or "OTHER", {"count": 0, "value": 0.0},
        )
        bucket["count"] += 1
        bucket["value"] += r.market_value or 0
    return {
        "total_count": len(rows),
        "total_market_value": total_value,
        "auto_count": sum(1 for r in rows if r.source == "AUTO"),
        "manual_count": sum(1 for r in rows if r.source == "MANUAL"),
        "by_category": [
            {"category": k, "count": v["count"], "market_value": v["value"]}
            for k, v in sorted(by_category.items())
        ],
    }


@router.get("/{holding_id}", dependencies=[Depends(require_user)])
def get_holding(holding_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(SecurityHolding, holding_id)
    if not row:
        raise HTTPException(404, "Запись не найдена")
    return _join_cdu_names(db, [row])[0]


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


_EDITABLE_FIELDS = (
    "isin", "instrument_code", "instrument_name", "category", "currency",
    "quantity", "avg_purchase_price", "last_kase_price",
    "nominal_per_unit", "coupon_rate_pct", "notes",
)


@router.post("/", dependencies=[Depends(require_user), Depends(require_permission("securities.edit"))])
def create_manual_holding(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    cdu_id = payload.get("cdu_id")
    isin = (payload.get("isin") or "").strip().upper()
    if not cdu_id or not isin:
        raise HTTPException(400, "Поля cdu_id и isin обязательны")
    if not db.get(CDU, cdu_id):
        raise HTTPException(404, "CDU не найден")

    existing = db.query(SecurityHolding).filter_by(cdu_id=cdu_id, isin=isin).first()
    if existing:
        raise HTTPException(409, {
            "error": "duplicate_holding",
            "message": f"Запись для {isin} в этом CDU уже существует",
            "id": existing.id,
            "source": existing.source,
        })

    row = SecurityHolding(
        cdu_id=cdu_id,
        isin=isin,
        source="MANUAL",
        updated_by=user.username if user else None,
    )
    for f in _EDITABLE_FIELDS:
        if f == "isin":
            continue
        if f in payload:
            setattr(row, f, payload[f])
    if "maturity_date" in payload:
        row.maturity_date = _parse_date(payload["maturity_date"])

    db.add(row)
    db.commit()
    db.refresh(row)
    write_audit(
        db, user=user.username if user else None, action="HOLDING_CREATED",
        entity="SecurityHolding", entity_id=row.id,
        details={"isin": isin, "cdu_id": cdu_id, "quantity": row.quantity},
    )
    db.commit()
    return _join_cdu_names(db, [row])[0]


@router.patch("/{holding_id}", dependencies=[Depends(require_user), Depends(require_permission("securities.edit"))])
def update_holding(
    holding_id: int,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    row = db.get(SecurityHolding, holding_id)
    if not row:
        raise HTTPException(404, "Запись не найдена")

    # AUTO rows: only descriptive fields (notes, category, instrument_name) can
    # be edited. Quantity-bearing fields stay read-only — they're recomputed
    # by the sync job.
    auto_locked = {"quantity", "avg_purchase_price"}
    changed: dict[str, Any] = {}
    for f in _EDITABLE_FIELDS:
        if f not in payload:
            continue
        if row.source == "AUTO" and f in auto_locked:
            continue
        old = getattr(row, f)
        new = payload[f]
        if old != new:
            setattr(row, f, new)
            changed[f] = {"from": old, "to": new}
    if "maturity_date" in payload:
        new = _parse_date(payload["maturity_date"])
        if row.maturity_date != new:
            changed["maturity_date"] = {
                "from": row.maturity_date.isoformat() if row.maturity_date else None,
                "to": new.isoformat() if new else None,
            }
            row.maturity_date = new

    # Recompute market_value if either side changed.
    if row.last_kase_price is not None and row.quantity is not None:
        row.market_value = row.quantity * row.last_kase_price

    row.updated_by = user.username if user else None
    db.commit()
    db.refresh(row)

    if changed:
        write_audit(
            db, user=user.username if user else None, action="HOLDING_UPDATED",
            entity="SecurityHolding", entity_id=row.id,
            details={"changes": changed, "source": row.source},
        )
        db.commit()
    return _join_cdu_names(db, [row])[0]


@router.delete("/{holding_id}", dependencies=[Depends(require_user), Depends(require_permission("securities.edit"))])
def delete_holding(
    holding_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    row = db.get(SecurityHolding, holding_id)
    if not row:
        raise HTTPException(404, "Запись не найдена")
    if row.source == "AUTO":
        raise HTTPException(
            409,
            {
                "error": "auto_managed",
                "message": "Запись управляется автосинхронизацией и не может быть удалена вручную. "
                           "Удалите соответствующие сделки или сведите позицию к нулю.",
            },
        )
    write_audit(
        db, user=user.username if user else None, action="HOLDING_DELETED",
        entity="SecurityHolding", entity_id=row.id,
        details={"isin": row.isin, "cdu_id": row.cdu_id},
    )
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/sync", dependencies=[Depends(require_user), Depends(require_permission("securities.edit"))])
def trigger_sync(
    cdu_id: Optional[int] = Query(None, description="Только для конкретного CDU"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    """Force a holdings rebuild from current Trade data."""
    counters = sync_holdings(db, cdu_id=cdu_id, actor=user.username if user else None)
    db.commit()
    return counters
