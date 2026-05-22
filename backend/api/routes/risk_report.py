"""Risk Report viewer + manual notes/overrides.

Endpoints
---------
GET  /api/risk-report/dates                       Distinct report dates with row counts.
GET  /api/risk-report/snapshot                    Full read-only snapshot for one date.
GET  /api/risk-report/notes                       List notes (filters: date, cdu, section).
POST /api/risk-report/notes                       Create a note/override (write).
PATCH /api/risk-report/notes/{id}                 Update existing note (write).
DELETE /api/risk-report/notes/{id}                Delete a note (write).
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import require_permission, require_user
from database import get_db
from models.db_models import (
    CDU,
    BondLot,
    CashSnapshot,
    PortfolioPosition,
    PortfolioSummary,
    RiskReportNote,
    User,
)
from services.audit import write_audit


router = APIRouter(
    prefix="/api/risk-report",
    tags=["Risk Report"],
    dependencies=[Depends(require_permission("page.risk_report"))],
)


# ─────────────── helpers ───────────────


def _note_to_dict(n: RiskReportNote) -> dict[str, Any]:
    try:
        override = json.loads(n.override_value) if n.override_value else None
    except json.JSONDecodeError:
        override = n.override_value
    return {
        "id": n.id,
        "report_date": n.report_date.isoformat() if n.report_date else None,
        "cdu_id": n.cdu_id,
        "section": n.section,
        "field_key": n.field_key,
        "override_value": override,
        "comment": n.comment,
        "version": n.version,
        "created_by": n.created_by,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "updated_by": n.updated_by,
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


# ─────────────── snapshot (read-only view) ───────────────


@router.get("/dates")
def list_dates(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Distinct snapshot dates that have any data the editor can show.

    Aggregates over ``portfolio_summaries`` since that's the canonical
    per-day summary table populated by the RR importer.
    """
    rows = (
        db.query(
            PortfolioSummary.summary_date.label("d"),
            func.count(PortfolioSummary.id).label("rows"),
            func.sum(PortfolioSummary.total_mv_current).label("total"),
        )
        .group_by(PortfolioSummary.summary_date)
        .order_by(PortfolioSummary.summary_date.desc())
        .limit(60)
        .all()
    )
    return [
        {
            "report_date": r.d.isoformat() if r.d else None,
            "rows": r.rows,
            "total_value": float(r.total or 0),
        }
        for r in rows
    ]


@router.get("/snapshot")
def snapshot(
    report_date: date = Query(..., description="Дата RR в формате YYYY-MM-DD"),
    cdu_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Composite read-only view of imported RR data + attached notes.

    Returns ``summary`` (per-CDU totals), ``positions`` (bond lots), ``cash``
    (cash snapshots) and ``notes`` so the UI can render side-by-side.
    """
    sum_q = db.query(PortfolioSummary).filter(PortfolioSummary.summary_date == report_date)
    pos_q = db.query(PortfolioPosition).filter(PortfolioPosition.position_date == report_date)
    lot_q = db.query(BondLot).filter(BondLot.valuation_date == report_date)
    cash_q = db.query(CashSnapshot).filter(CashSnapshot.snapshot_date == report_date)
    note_q = db.query(RiskReportNote).filter(RiskReportNote.report_date == report_date)
    if cdu_id is not None:
        sum_q = sum_q.filter(PortfolioSummary.cdu_id == cdu_id)
        pos_q = pos_q.filter(PortfolioPosition.cdu_id == cdu_id)
        lot_q = lot_q.filter(BondLot.cdu_id == cdu_id)
        cash_q = cash_q.filter(CashSnapshot.cdu_id == cdu_id)
        note_q = note_q.filter(RiskReportNote.cdu_id == cdu_id)

    cdus = {c.id: c.short_name or c.name for c in db.query(CDU).all()}

    def _cdu_name(cid: Optional[int]) -> Optional[str]:
        return cdus.get(cid) if cid is not None else None

    return {
        "report_date": report_date.isoformat(),
        "cdu_id": cdu_id,
        "summary": [
            {
                "id": s.id,
                "cdu_id": s.cdu_id,
                "cdu_name": _cdu_name(s.cdu_id),
                "total_mv_prev": s.total_mv_prev,
                "total_mv_current": s.total_mv_current,
                "total_daily_change": s.total_daily_change,
                "cdu_share_pct": s.cdu_share_pct,
                "ytm_weighted": s.ytm_weighted,
                "duration_weighted": s.duration_weighted,
                "benchmark_duration": s.benchmark_duration,
                "duration_status": s.duration_status,
            }
            for s in sum_q.all()
        ],
        "positions": [
            {
                "id": p.id,
                "cdu_id": p.cdu_id,
                "cdu_name": _cdu_name(p.cdu_id),
                "instrument_code": p.instrument_code,
                "instrument_name": p.instrument_name,
                "category": p.instrument_category,
                "nominal_volume": p.nominal_volume,
                "current_price": p.current_price,
                "accrued_interest": p.accrued_interest,
                "market_value_current": p.market_value_current,
                "market_value_prev": p.market_value_prev,
                "daily_change": p.daily_change,
                "pct_of_total": p.pct_of_total,
                "ytm": p.ytm,
                "duration": p.duration,
            }
            for p in pos_q.all()
        ],
        "bond_lots": [
            {
                "id": l.id,
                "cdu_id": l.cdu_id,
                "cdu_name": _cdu_name(l.cdu_id),
                "isin": l.isin,
                "instrument_code": l.instrument_code,
                "category": l.category,
                "quantity": l.quantity_current,
                "market_price": l.market_price,
                "market_value": l.market_value,
                "ytm": l.ytm,
                "duration": l.duration,
            }
            for l in lot_q.all()
        ],
        "cash": [
            {
                "id": c.id,
                "cdu_id": c.cdu_id,
                "cdu_name": _cdu_name(c.cdu_id),
                "currency": c.currency,
                "amount": c.amount,
                "portfolio_code": c.portfolio_code,
            }
            for c in cash_q.all()
        ],
        "notes": [_note_to_dict(n) for n in note_q.all()],
    }


# ─────────────── notes CRUD ───────────────


@router.get("/notes")
def list_notes(
    report_date: Optional[date] = Query(None),
    cdu_id: Optional[int] = Query(None),
    section: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    q = db.query(RiskReportNote)
    if report_date is not None:
        q = q.filter(RiskReportNote.report_date == report_date)
    if cdu_id is not None:
        q = q.filter(RiskReportNote.cdu_id == cdu_id)
    if section:
        q = q.filter(RiskReportNote.section == section)
    return [_note_to_dict(n) for n in q.order_by(RiskReportNote.updated_at.desc()).all()]


def _encode_override(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


_SECTIONS = {"summary", "positions", "cash", "stress", "other"}


@router.post("/notes", dependencies=[Depends(require_permission("risk_report.notes.edit"))])
def create_note(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    report_date_raw = payload.get("report_date")
    if not report_date_raw:
        raise HTTPException(400, "report_date обязателен")
    try:
        report_date_v = date.fromisoformat(str(report_date_raw))
    except ValueError:
        raise HTTPException(400, "Неверный формат report_date")
    section = (payload.get("section") or "other").strip()
    if section not in _SECTIONS:
        raise HTTPException(400, f"section должен быть одним из {sorted(_SECTIONS)}")
    field_key = (payload.get("field_key") or "").strip()
    if not field_key:
        raise HTTPException(400, "field_key обязателен")

    n = RiskReportNote(
        report_date=report_date_v,
        cdu_id=payload.get("cdu_id"),
        source_doc_id=payload.get("source_doc_id"),
        section=section,
        field_key=field_key,
        override_value=_encode_override(payload.get("override_value")),
        comment=payload.get("comment"),
        created_by=user.username if user else None,
        updated_by=user.username if user else None,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    write_audit(
        db, user=user.username if user else None, action="RR_NOTE_CREATED",
        entity="RiskReportNote", entity_id=n.id,
        details={"report_date": str(report_date_v), "section": section, "field_key": field_key},
    )
    db.commit()
    return _note_to_dict(n)


@router.patch("/notes/{note_id}", dependencies=[Depends(require_permission("risk_report.notes.edit"))])
def update_note(
    note_id: int,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    n = db.get(RiskReportNote, note_id)
    if not n:
        raise HTTPException(404, "Заметка не найдена")
    changed: dict[str, Any] = {}
    for field in ("comment",):
        if field in payload and payload[field] != getattr(n, field):
            changed[field] = {"from": getattr(n, field), "to": payload[field]}
            setattr(n, field, payload[field])
    if "override_value" in payload:
        new_enc = _encode_override(payload["override_value"])
        if new_enc != n.override_value:
            changed["override_value"] = {"from": n.override_value, "to": new_enc}
            n.override_value = new_enc
    if "section" in payload and payload["section"] in _SECTIONS and payload["section"] != n.section:
        changed["section"] = {"from": n.section, "to": payload["section"]}
        n.section = payload["section"]

    if changed:
        n.version = (n.version or 1) + 1
        n.updated_by = user.username if user else None
        db.commit()
        db.refresh(n)
        write_audit(
            db, user=user.username if user else None, action="RR_NOTE_UPDATED",
            entity="RiskReportNote", entity_id=n.id,
            details={"changes": changed, "version": n.version},
        )
        db.commit()
    return _note_to_dict(n)


@router.delete("/notes/{note_id}", dependencies=[Depends(require_permission("risk_report.notes.edit"))])
def delete_note(
    note_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    n = db.get(RiskReportNote, note_id)
    if not n:
        raise HTTPException(404, "Заметка не найдена")
    write_audit(
        db, user=user.username if user else None, action="RR_NOTE_DELETED",
        entity="RiskReportNote", entity_id=note_id,
        details={"report_date": str(n.report_date), "field_key": n.field_key},
    )
    db.delete(n)
    db.commit()
    return {"ok": True}
