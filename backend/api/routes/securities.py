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

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from auth import require_permission, require_user
from database import get_db
from models.db_models import (
    BondLot,
    CDU,
    InstrumentReference,
    PortfolioPosition,
    RepoLot,
    SecurityHolding,
    Trade,
    User,
)
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


def _security_identifiers(h: SecurityHolding) -> set[str]:
    """Return upper-case identifiers that may reference the same security."""
    values = {h.isin, h.instrument_code}
    return {str(v).strip().upper() for v in values if v and str(v).strip()}


def _match_trade_identifiers(identifiers: set[str]):
    return or_(
        func.upper(Trade.isin).in_(identifiers),
        func.upper(Trade.instrument_code).in_(identifiers),
    )


def _match_bond_identifiers(identifiers: set[str]):
    return or_(
        func.upper(BondLot.isin).in_(identifiers),
        func.upper(BondLot.instrument_code).in_(identifiers),
    )


def _match_repo_identifiers(identifiers: set[str]):
    return or_(
        func.upper(RepoLot.isin).in_(identifiers),
        func.upper(RepoLot.instrument_code).in_(identifiers),
        func.upper(RepoLot.deal_id).in_(identifiers),
    )


def _match_position_identifiers(identifiers: set[str]):
    return func.upper(PortfolioPosition.instrument_code).in_(identifiers)


def _trade_price(t: Trade) -> Optional[float]:
    for value in (t.price_final, t.price_kase, t.market_price, t.price_original, t.clean_price):
        if value is not None:
            return value
    return None


def _signed_trade_quantity(t: Trade) -> float:
    qty = float(t.quantity or 0.0)
    if t.operation_type in {"BUY", "REPO_OPEN", "COUPON"}:
        return qty
    if t.operation_type in {"SELL", "REPO_CLOSE", "REDEMPTION"}:
        return -qty
    return 0.0


def _reference_to_dict(ref: Optional[InstrumentReference]) -> Optional[dict[str, Any]]:
    if ref is None:
        return None
    return {
        "isin": ref.isin,
        "nin": ref.nin,
        "ticker_kase": ref.ticker_kase,
        "instrument_name": ref.instrument_name,
        "security_type": ref.security_type,
        "issuer": ref.issuer,
        "issuer_type": ref.issuer_type,
        "bond_type": ref.bond_type,
        "coupon_rate_pct": ref.coupon_rate_pct,
        "coupon_rate_text": ref.coupon_rate_text,
        "coupon_type": ref.coupon_type,
        "float_index": ref.float_index,
        "float_margin_pct": ref.float_margin_pct,
        "frequency": ref.frequency,
        "base": ref.base,
        "base_code": ref.base_code,
        "nominal": ref.nominal,
        "start_date": ref.start_date.isoformat() if ref.start_date else None,
        "maturity_date": ref.maturity_date.isoformat() if ref.maturity_date else None,
        "last_coupon_date": ref.last_coupon_date.isoformat() if ref.last_coupon_date else None,
        "next_coupon_date": ref.next_coupon_date.isoformat() if ref.next_coupon_date else None,
        "quotation_type": ref.quotation_type,
        "currency": ref.currency,
        "rating": ref.rating,
        "rating_source": ref.rating_source,
        "rating_agency": ref.rating_agency,
        "source": ref.source,
        "source_updated_at": ref.source_updated_at.isoformat() if ref.source_updated_at else None,
        "notes": ref.notes,
        "is_active": ref.is_active,
        "updated_at": ref.updated_at.isoformat() if ref.updated_at else None,
        "updated_by": ref.updated_by,
    }


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


# ─────────────── reference book (instruments without a manager) ───────────────

_REF_FIELDS = (
    "ticker_kase", "instrument_name", "security_type", "issuer", "issuer_type", "bond_type",
    "coupon_rate_pct", "coupon_rate_text", "coupon_type", "float_index", "float_margin_pct",
    "frequency", "base", "nominal",
    "quotation_type", "currency", "rating", "rating_agency", "notes",
)
_REF_DATES = ("start_date", "maturity_date", "last_coupon_date", "next_coupon_date")
_CATEGORY_TO_TYPE = {
    "GOV_BONDS": "ГЦБ", "AGENCY_BONDS": "Агентские", "MFO_BONDS": "МФО", "FOREIGN_BONDS": "Ин.ЦБ",
}


def _find_reference(db: Session, identifier: str) -> Optional[InstrumentReference]:
    key = identifier.strip().upper()
    return (
        db.query(InstrumentReference)
        .filter(or_(func.upper(InstrumentReference.isin) == key,
                    func.upper(InstrumentReference.ticker_kase) == key))
        .first()
    )


def upsert_reference(db: Session, payload: dict[str, Any], actor: Optional[str],
                     *, overwrite: bool = True) -> InstrumentReference:
    """Create/update the security master record from a «Справочник ЦБ» form.

    ``overwrite=False`` only fills empty attributes (used when a manager
    holding is saved, so a form never erases data imported from the RR/KASE).
    """
    isin = (payload.get("isin") or "").strip().upper()
    if not isin:
        raise HTTPException(400, "Поле ISIN обязательно")
    ref = _find_reference(db, isin)
    created = ref is None
    if ref is None:
        ref = InstrumentReference(isin=isin, source="MANUAL")
        db.add(ref)
    mapping = dict(payload)
    if "instrument_code" in mapping and "ticker_kase" not in mapping:
        mapping["ticker_kase"] = mapping["instrument_code"]
    if "nominal_per_unit" in mapping and "nominal" not in mapping:
        mapping["nominal"] = mapping["nominal_per_unit"]
    if mapping.get("category") and not mapping.get("bond_type"):
        mapping["bond_type"] = _CATEGORY_TO_TYPE.get(mapping["category"])
    if mapping.get("float_margin_pct") not in (None, ""):
        try:
            mapping["float_margin_pct"] = float(str(mapping["float_margin_pct"]).replace(" ", "").replace(",", "."))
        except ValueError:
            raise HTTPException(400, "Маржа плавающего купона должна быть числом (в процентах)")
    if mapping.get("float_index"):
        mapping["float_index"] = str(mapping["float_index"]).strip().upper()
    for f in ("float_index", "float_margin_pct"):
        # an explicitly emptied field of the form clears the floating-rate settings
        if overwrite and f in mapping and mapping[f] in (None, ""):
            setattr(ref, f, None)
    for f in _REF_FIELDS:
        if f not in mapping or mapping[f] in (None, ""):
            continue
        if overwrite or getattr(ref, f) in (None, ""):
            setattr(ref, f, mapping[f])
    for f in _REF_DATES:
        if mapping.get(f):
            if overwrite or getattr(ref, f) is None:
                setattr(ref, f, _parse_date(mapping[f]))
    ref.updated_by = actor
    db.flush()
    write_audit(db, user=actor, action="REFERENCE_CREATED" if created else "REFERENCE_UPDATED",
                entity="InstrumentReference", entity_id=ref.id, details={"isin": isin})
    return ref


@router.get("/reference", dependencies=[Depends(require_user)])
def list_reference(
    search: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    from models.db_models import CouponSchedule
    q = db.query(InstrumentReference)
    if search:
        pattern = f"%{search.strip()}%"
        q = q.filter(or_(InstrumentReference.isin.ilike(pattern),
                         InstrumentReference.ticker_kase.ilike(pattern),
                         InstrumentReference.instrument_name.ilike(pattern),
                         InstrumentReference.issuer.ilike(pattern)))
    rows = q.order_by(InstrumentReference.isin.asc()).limit(limit).all()
    counts = dict(db.query(CouponSchedule.isin, func.count(CouponSchedule.id))
                  .group_by(CouponSchedule.isin).all())
    out = []
    for r in rows:
        d = _reference_to_dict(r)
        d["id"] = r.id
        d["coupon_schedule_rows"] = counts.get(r.isin, 0)
        out.append(d)
    return out


@router.post("/reference", dependencies=[Depends(require_user), Depends(require_permission("securities.edit"))])
def save_reference(payload: dict[str, Any], db: Session = Depends(get_db),
                   user: User = Depends(require_user)) -> dict[str, Any]:
    ref = upsert_reference(db, payload, user.username if user else None)
    db.commit()
    return _reference_to_dict(ref)


def _schedule_dict(r) -> dict[str, Any]:
    return {
        "id": r.id, "isin": r.isin, "seq": r.seq,
        "period_start": r.period_start.isoformat() if r.period_start else None,
        "payment_date": r.payment_date.isoformat(),
        "record_date": r.record_date.isoformat() if r.record_date else None,
        "payment_end_date": r.payment_end_date.isoformat() if r.payment_end_date else None,
        "rate_pct": r.rate_pct, "margin_pct": r.margin_pct, "index_rate_pct": r.index_rate_pct,
        "amount_per_unit": r.amount_per_unit,
        "source": r.source, "notes": r.notes, "updated_by": r.updated_by,
    }


def _schedule_isin(db: Session, identifier: str) -> str:
    ref = _find_reference(db, identifier)
    return (ref.isin if ref is not None else identifier).strip().upper()


@router.get("/reference/{identifier}/coupons", dependencies=[Depends(require_user)])
def get_coupon_schedule(identifier: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    from models.db_models import CouponSchedule
    isin = _schedule_isin(db, identifier)
    rows = db.query(CouponSchedule).filter(CouponSchedule.isin == isin).order_by(
        CouponSchedule.payment_date.asc()).all()
    return {"isin": isin, "reference": _reference_to_dict(_find_reference(db, isin)),
            "rows": [_schedule_dict(r) for r in rows]}


def _schedule_rows_from_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, r in enumerate(rows or [], start=1):
        pay = _parse_date(r.get("payment_date"))
        if pay is None:
            raise HTTPException(400, f"Строка {i}: не указана дата выплаты")
        rate = r.get("rate_pct")
        amount = r.get("amount_per_unit")
        if rate in (None, "") and r.get("margin_pct") not in (None, "") and r.get("index_rate_pct") not in (None, ""):
            rate = float(r["margin_pct"]) + float(r["index_rate_pct"])   # floating coupon: index + margin
        if rate in (None, "") and amount in (None, ""):
            raise HTTPException(400, f"Строка {i}: укажите ставку или сумму купона")
        out.append({
            "seq": int(r["seq"]) if r.get("seq") not in (None, "") else None,
            "period_start": _parse_date(r.get("period_start")),
            "payment_date": pay,
            "record_date": _parse_date(r.get("record_date")),
            "payment_end_date": _parse_date(r.get("payment_end_date")),
            "rate_pct": float(rate) if rate not in (None, "") else None,
            "margin_pct": float(r["margin_pct"]) if r.get("margin_pct") not in (None, "") else None,
            "index_rate_pct": float(r["index_rate_pct"]) if r.get("index_rate_pct") not in (None, "") else None,
            "amount_per_unit": float(amount) if amount not in (None, "") else None,
            "notes": r.get("notes"),
            "source": str(r.get("source") or "MANUAL")[:20],
        })
    return out


@router.put("/reference/{identifier}/coupons",
            dependencies=[Depends(require_user), Depends(require_permission("securities.edit"))])
def put_coupon_schedule(identifier: str, payload: dict[str, Any], db: Session = Depends(get_db),
                        user: User = Depends(require_user)) -> dict[str, Any]:
    """Replace the whole schedule with the rows edited in the UI."""
    from services.portfolio.coupon_schedule import replace_schedule
    isin = _schedule_isin(db, identifier)
    rows = _schedule_rows_from_payload(payload.get("rows") or [])
    n = replace_schedule(db, isin, rows, source=str(payload.get("source") or "MANUAL")[:20],
                         actor=user.username if user else None)
    write_audit(db, user=user.username if user else None, action="COUPON_SCHEDULE_SAVED",
                entity="CouponSchedule", entity_id=None, details={"isin": isin, "rows": n})
    db.commit()
    return get_coupon_schedule(isin, db)


@router.post("/reference/{identifier}/coupons/generate",
             dependencies=[Depends(require_user), Depends(require_permission("securities.edit"))])
def generate_coupon_schedule(identifier: str, db: Session = Depends(get_db),
                             user: User = Depends(require_user)) -> dict[str, Any]:
    """Pre-fill a regular schedule from the issue parameters (to be checked/edited)."""
    from services.portfolio.coupon_schedule import generate_from_reference
    ref = _find_reference(db, identifier)
    if ref is None:
        raise HTTPException(404, "Инструмент не найден в справочнике")
    rows = generate_from_reference(ref)
    if not rows:
        raise HTTPException(400, "Для автозаполнения нужны дата погашения и периодичность купона")
    return {"isin": ref.isin, "rows": [
        {**r, "period_start": r["period_start"].isoformat() if r["period_start"] else None,
         "payment_date": r["payment_date"].isoformat(), "source": "GENERATED"} for r in rows
    ]}


@router.post("/reference/{identifier}/coupons/fetch-kase",
             dependencies=[Depends(require_user), Depends(require_permission("securities.edit"))])
async def fetch_coupon_schedule_from_kase(identifier: str, db: Session = Depends(get_db),
                                          user: User = Depends(require_user)) -> dict[str, Any]:
    """Download the schedule and issue parameters from kase.kz.

    Rows edited by hand (source MANUAL) are kept.
    """
    from services.kase.coupon_sync import fetch_and_apply
    try:
        result = await fetch_and_apply(db, identifier, user.username if user else None)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:  # noqa: BLE001 — network / KASE errors
        raise HTTPException(502, f"KASE недоступна или вернула ошибку: {exc}")
    write_audit(db, user=user.username if user else None, action="COUPON_SCHEDULE_FROM_KASE",
                entity="CouponSchedule", entity_id=None, details=result)
    db.commit()
    schedule = get_coupon_schedule(result["isin"], db)
    return {**result, **schedule, "rows_count": len(schedule["rows"])}


@router.post("/reference/coupons/fetch-kase-all",
             dependencies=[Depends(require_user), Depends(require_permission("securities.edit"))])
async def fetch_all_coupon_schedules(
    scope: str = Query("held", pattern="^(held|all)$"),
    limit: int = Query(300, ge=1, le=2000),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    """Refresh schedules from KASE for instruments in portfolios (``held``)
    or for the whole reference book (``all``)."""
    from services.kase.coupon_sync import fetch_many, held_identifiers
    if scope == "held":
        idents = held_identifiers(db)
    else:
        idents = [r.ticker_kase or r.isin for r in db.query(InstrumentReference).all()]
    idents = idents[:limit]
    result = await fetch_many(db, idents, user.username if user else None)
    write_audit(db, user=user.username if user else None, action="COUPON_SCHEDULES_FROM_KASE",
                entity="CouponSchedule", entity_id=None,
                details={"scope": scope, "updated": len(result["updated"]), "failed": result["failed"]})
    db.commit()
    return {"requested": len(idents), **result}


@router.post("/reference/coupons/import",
             dependencies=[Depends(require_user), Depends(require_permission("securities.edit"))])
def import_coupon_schedule(
    file: UploadFile = File(...),
    isin: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    """Import schedules from XLSX/CSV (the KASE table «График купонных выплат»).

    Without an instrument column the file belongs to ``isin``; with an
    ISIN/ticker column several issues are imported at once.
    """
    import tempfile
    from pathlib import Path as _Path
    from services.portfolio.coupon_schedule import parse_schedule_grid, read_grid, replace_schedule
    suffix = _Path(file.filename or "x.xlsx").suffix.lower()
    if suffix not in (".xlsx", ".xlsm", ".csv", ".txt"):
        raise HTTPException(400, "Поддерживаются XLSX и CSV")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file.file.read())
        path = _Path(tmp.name)
    try:
        grouped = parse_schedule_grid(read_grid(path))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    finally:
        path.unlink(missing_ok=True)
    result: dict[str, int] = {}
    unknown: list[str] = []
    for key, rows in grouped.items():
        target = key or (isin or "").strip()
        if not target:
            raise HTTPException(400, "В файле нет колонки ISIN/тикер — выберите инструмент перед импортом")
        ref = _find_reference(db, target)
        if ref is None and not (len(target) == 12 and target[:2].isalpha()):
            unknown.append(target)
            continue
        code = ref.isin if ref is not None else target.upper()
        result[code] = replace_schedule(db, code, rows, source="IMPORT",
                                        actor=user.username if user else None)
    write_audit(db, user=user.username if user else None, action="COUPON_SCHEDULE_IMPORTED",
                entity="CouponSchedule", entity_id=None,
                details={"file": file.filename, "imported": result, "unknown": unknown})
    db.commit()
    return {"imported": result, "unknown": unknown}


@router.get("/{holding_id}", dependencies=[Depends(require_user)])
def get_holding(holding_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(SecurityHolding, holding_id)
    if not row:
        raise HTTPException(404, "Запись не найдена")
    return _join_cdu_names(db, [row])[0]


@router.get("/{holding_id}/history", dependencies=[Depends(require_user)])
def holding_history(
    holding_id: int,
    limit: int = Query(120, ge=20, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    row = db.get(SecurityHolding, holding_id)
    if not row:
        raise HTTPException(404, "Запись не найдена")

    identifiers = _security_identifiers(row)
    if not identifiers:
        return {
            "holding_id": holding_id,
            "reference": None,
            "stats": {},
            "timeline": [],
            "snapshots": [],
        }

    ref = (
        db.query(InstrumentReference)
        .filter(or_(
            func.upper(InstrumentReference.isin).in_(identifiers),
            func.upper(InstrumentReference.ticker_kase).in_(identifiers),
        ))
        .order_by(InstrumentReference.isin.asc())
        .first()
    )

    trade_rows = (
        db.query(Trade)
        .filter(
            Trade.cdu_id == row.cdu_id,
            Trade.is_active == True,  # noqa: E712
            _match_trade_identifiers(identifiers),
        )
        .order_by(Trade.value_date.desc(), Trade.trade_date.desc(), Trade.id.desc())
        .all()
    )

    timeline = [
        {
            "id": t.id,
            "kind": "TRADE",
            "date": (t.value_date or t.trade_date).isoformat(),
            "trade_date": t.trade_date.isoformat() if t.trade_date else None,
            "value_date": t.value_date.isoformat() if t.value_date else None,
            "operation_type": t.operation_type,
            "direction": t.direction,
            "quantity": t.quantity,
            "signed_quantity": _signed_trade_quantity(t),
            "face_value": t.face_value,
            "amount_kzt": t.amount_kzt,
            "currency": t.currency,
            "price": _trade_price(t),
            "ytm": t.ytm,
            "repo_rate_pct": t.repo_rate_pct,
            "deal_id": t.deal_id,
            "portfolio_code": t.portfolio_code,
            "description": t.description,
            "is_manual": t.is_manual,
            "is_synthetic": t.is_synthetic,
        }
        for t in trade_rows[:limit]
    ]

    snapshots: list[dict[str, Any]] = []

    bond_rows = (
        db.query(BondLot)
        .filter(BondLot.cdu_id == row.cdu_id, _match_bond_identifiers(identifiers))
        .order_by(BondLot.valuation_date.desc(), BondLot.id.desc())
        .limit(limit)
        .all()
    )
    for lot in bond_rows:
        snapshots.append({
            "id": lot.id,
            "source": "BOND_LOT",
            "source_label": "Лот ЦБ",
            "date": lot.valuation_date.isoformat(),
            "trade_date": lot.trade_date.isoformat() if lot.trade_date else None,
            "quantity": lot.quantity_current,
            "face_value": lot.face_value_current,
            "price": lot.market_price if lot.market_price is not None else lot.purchase_price,
            "market_value": lot.total_value if lot.total_value is not None else lot.market_value,
            "ytm": lot.ytm,
            "duration": lot.duration,
            "status": lot.maturity_status,
            "portfolio_code": lot.portfolio_code,
        })

    repo_rows = (
        db.query(RepoLot)
        .filter(RepoLot.cdu_id == row.cdu_id, _match_repo_identifiers(identifiers))
        .order_by(RepoLot.valuation_date.desc(), RepoLot.id.desc())
        .limit(limit)
        .all()
    )
    for lot in repo_rows:
        snapshots.append({
            "id": lot.id,
            "source": "REPO_LOT",
            "source_label": "REPO",
            "date": lot.valuation_date.isoformat(),
            "trade_date": lot.trade_date.isoformat() if lot.trade_date else None,
            "quantity": lot.face_value,
            "face_value": lot.face_value,
            "price": lot.repo_rate_pct,
            "market_value": lot.market_value if lot.market_value is not None else lot.close_value,
            "ytm": lot.ytm if lot.ytm is not None else lot.repo_rate_pct,
            "duration": lot.duration,
            "status": lot.maturity_status if lot.maturity_status else ("closed" if lot.is_closed else "open"),
            "portfolio_code": lot.portfolio_code,
        })

    position_rows = (
        db.query(PortfolioPosition)
        .filter(PortfolioPosition.cdu_id == row.cdu_id, _match_position_identifiers(identifiers))
        .order_by(PortfolioPosition.position_date.desc(), PortfolioPosition.id.desc())
        .limit(limit)
        .all()
    )
    for pos in position_rows:
        snapshots.append({
            "id": pos.id,
            "source": "POSITION",
            "source_label": "Срез портфеля",
            "date": pos.position_date.isoformat(),
            "trade_date": None,
            "quantity": pos.nominal_volume,
            "face_value": pos.nominal_volume,
            "price": pos.current_price,
            "market_value": pos.market_value_current,
            "ytm": pos.ytm,
            "duration": pos.duration,
            "status": pos.hard_limit_status or pos.soft_limit_status,
            "portfolio_code": None,
        })

    snapshots.sort(key=lambda x: (x["date"], x["source"], x["id"]), reverse=True)
    snapshots = snapshots[:limit]

    all_dates = [
        t.value_date or t.trade_date
        for t in trade_rows
        if (t.value_date or t.trade_date) is not None
    ]
    buy_qty = sum(float(t.quantity or 0.0) for t in trade_rows if t.operation_type in {"BUY", "REPO_OPEN"})
    sell_qty = sum(float(t.quantity or 0.0) for t in trade_rows if t.operation_type in {"SELL", "REPO_CLOSE", "REDEMPTION"})
    stats = {
        "operations_count": len(trade_rows),
        "snapshots_count": len(snapshots),
        "first_date": min(all_dates).isoformat() if all_dates else None,
        "last_date": max(all_dates).isoformat() if all_dates else None,
        "buy_quantity": buy_qty,
        "sell_quantity": sell_qty,
        "net_trade_quantity": buy_qty - sell_qty,
        "cash_flow_kzt": sum(float(t.amount_kzt or 0.0) for t in trade_rows),
    }

    return {
        "holding_id": holding_id,
        "reference": _reference_to_dict(ref),
        "stats": stats,
        "timeline": timeline,
        "snapshots": snapshots,
    }


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
    cdu_id = payload.get("cdu_id") or None
    isin = (payload.get("isin") or "").strip().upper()
    if not isin:
        raise HTTPException(400, "Поле ISIN обязательно")
    if cdu_id is not None:
        cdu_id = int(cdu_id)
        if not db.get(CDU, cdu_id):
            raise HTTPException(404, "ЧДУ не найден")

    # the descriptive attributes always go to the security master used by
    # the calculations; without a manager this is all the record is
    upsert_reference(db, payload, user.username if user else None, overwrite=cdu_id is None)

    existing = db.query(SecurityHolding).filter(
        SecurityHolding.isin == isin,
        SecurityHolding.cdu_id.is_(None) if cdu_id is None else SecurityHolding.cdu_id == cdu_id,
    ).first()
    if existing:
        raise HTTPException(409, {
            "error": "duplicate_holding",
            "message": (f"Запись для {isin} в этом ЧДУ уже существует" if cdu_id
                        else f"Инструмент {isin} без ЧДУ уже есть в справочнике"),
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

    if changed:
        upsert_reference(
            db, {**_to_dict(row), **{k: v for k, v in payload.items() if k not in ("cdu_id",)}},
            user.username if user else None, overwrite=row.cdu_id is None,
        )

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
