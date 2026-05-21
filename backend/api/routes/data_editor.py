"""Generic data editor — CRUD for whitelisted tables.

Provides a uniform REST interface so the frontend can build one reusable
admin grid for any table without custom endpoints per entity.

Security
--------
* Only ``admin`` / ``analyst`` may write (POST/PATCH/DELETE).
* ``viewer`` may read (GET).
* Tables not in ``_TABLE_REGISTRY`` return 404.
* System tables (AuditLog, RawTrade, etc.) are deliberately excluded.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Type

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, inspect, select, text
from sqlalchemy.orm import Session

from auth import require_user, require_write
from database import get_db
import models.db_models as db_models
from services.audit import write_audit

router = APIRouter(prefix="/api/data", tags=["data-editor"])

# ═══════════════════════════════════════════════════════════════════════════
# Table registry — maps public slug → SQLAlchemy model class
# ═══════════════════════════════════════════════════════════════════════════
_TABLE_REGISTRY: Dict[str, Type] = {
    "cdu": db_models.CDU,
    "cdu_limits": db_models.CDULimit,
    "instruments": db_models.Instrument,
    "instrument_category_rules": db_models.InstrumentCategoryRule,
    "instrument_reference": db_models.InstrumentReference,
    "kase_prices": db_models.KasePrice,
    "mbm_index": db_models.MBMIndex,
    "fx_rates": db_models.FXRate,
    "bond_lots": db_models.BondLot,
    "repo_lots": db_models.RepoLot,
    "deposit_lots": db_models.DepositLot,
    "cash_snapshots": db_models.CashSnapshot,
    "cash_balances": db_models.CashBalance,
    "portfolio_positions": db_models.PortfolioPosition,
    "portfolio_summary": db_models.PortfolioSummary,
    "mv_snapshots": db_models.MVSnapshot,
    "security_holdings": db_models.SecurityHolding,
    "risk_report_notes": db_models.RiskReportNote,
    "trades": db_models.Trade,
    "accounts_receivable": db_models.AccountReceivable,
    "alerts": db_models.Alert,
    "coupon_events": db_models.CouponEvent,
    "redemption_events": db_models.RedemptionEvent,
    "price_reconciliation": db_models.PriceReconciliation,
    "generated_reports": db_models.GeneratedReport,
    "source_documents": db_models.SourceDocument,
    "trade_files": db_models.TradeFile,
    "users": db_models.User,
    "formula_definitions": db_models.FormulaDefinition,
    "cdU_file_formats": db_models.CDUFileFormat,
    "import_jobs": db_models.ImportJob,
}


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _get_model(table: str) -> Type:
    model = _TABLE_REGISTRY.get(table)
    if model is None:
        raise HTTPException(404, f"Table '{table}' not found or not editable")
    return model


def _model_columns(model: Type) -> List[str]:
    """Return list of simple (non-relationship) column attribute names."""
    mapper = inspect(model)
    return [
        col.key
        for col in mapper.column_attrs
        if col.key != "id" and not col.key.startswith("_")
    ]


def _coerce_value(value: Any, column_type: Any) -> Any:
    """Coerce JSON payload values to Python types matching the DB column."""
    if value is None:
        return None
    if isinstance(column_type, (DateTime, Date)):
        if isinstance(value, str):
            # ISO-8601 date or datetime
            if "T" in value or " " in value:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            return date.fromisoformat(value)
        return value
    if isinstance(column_type, Boolean):
        return bool(value)
    if isinstance(column_type, Integer):
        return int(value) if value != "" else None
    if isinstance(column_type, Float):
        return float(value) if value != "" else None
    if isinstance(column_type, Text):
        return str(value) if value is not None else None
    if isinstance(column_type, String):
        return str(value)[:column_type.length] if value is not None else None
    return value


def _serialize_value(value: Any) -> Any:
    """Serialize a model attribute for JSON response."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _row_to_dict(row: Any, columns: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"id": getattr(row, "id", None)}
    for c in columns:
        out[c] = _serialize_value(getattr(row, c, None))
    return out


def _build_filters(model: Type, params: Dict[str, Any]) -> List:
    """Build SQLAlchemy binary expressions from query params."""
    conditions = []
    mapper = inspect(model)
    for key, val in params.items():
        if key in ("page", "page_size", "sort", "order", "search"):
            continue
        if val is None or val == "":
            continue
        col = getattr(model, key, None)
        if col is None:
            continue
        # Simple equality for numbers/dates; ilike for strings
        prop = mapper.attrs.get(key)
        if prop is None:
            continue
        col_type = getattr(prop, "columns", [None])[0].type if hasattr(prop, "columns") else None
        if isinstance(col_type, (String, Text)):
            conditions.append(col.ilike(f"%{val}%"))
        elif isinstance(col_type, (Date, DateTime)):
            conditions.append(col == _coerce_value(val, col_type))
        else:
            conditions.append(col == val)
    return conditions


# ═══════════════════════════════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════════════════════════════

class TableMeta(BaseModel):
    name: str
    label: str
    columns: List[Dict[str, Any]]


class ListResponse(BaseModel):
    data: List[Dict[str, Any]]
    total: int
    page: int
    page_size: int


# ═══════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/tables")
def list_tables(
    db: Session = Depends(get_db),
    user: db_models.User = Depends(require_user),
) -> List[Dict[str, str]]:
    """Return all whitelisted tables with human-friendly labels."""
    labels = {
        "cdu": "ЧДУ (портфели)",
        "cdu_limits": "Лимиты ЧДУ",
        "instruments": "Инструменты",
        "instrument_category_rules": "Правила категорий",
        "instrument_reference": "Справочник выпусков",
        "kase_prices": "Котировки KASE",
        "mbm_index": "Индекс MBM",
        "fx_rates": "Курсы валют",
        "bond_lots": "Лоты облигаций",
        "repo_lots": "REPO лоты",
        "deposit_lots": "Депозитные лоты",
        "cash_snapshots": "Cash снимки",
        "cash_balances": "Cash остатки",
        "portfolio_positions": "Позиции портфеля",
        "portfolio_summary": "Сводка портфеля",
        "mv_snapshots": "MV снимки",
        "security_holdings": "Holdings ЦБ",
        "risk_report_notes": "Заметки RR",
        "trades": "Сделки",
        "accounts_receivable": "Дебиторка",
        "alerts": "Алерты",
        "coupon_events": "Купоны",
        "redemption_events": "Погашения",
        "price_reconciliation": "Сверка цен",
        "generated_reports": "Отчёты",
        "source_documents": "Источники",
        "trade_files": "Файлы сделок",
        "users": "Пользователи",
        "formula_definitions": "Формулы",
        "cdU_file_formats": "Форматы файлов ЧДУ",
        "import_jobs": "Импорты",
    }
    return [
        {"name": k, "label": labels.get(k, k)}
        for k in _TABLE_REGISTRY.keys()
    ]


@router.get("/tables/{table}/meta")
def table_meta(
    table: str,
    db: Session = Depends(get_db),
    user: db_models.User = Depends(require_user),
) -> Dict[str, Any]:
    """Return column metadata for a given table (types, nullable, defaults)."""
    model = _get_model(table)
    mapper = inspect(model)
    columns: List[Dict[str, Any]] = []
    for attr in mapper.column_attrs:
        if attr.key == "id":
            continue
        col = attr.columns[0]
        col_type = col.type
        type_name = "string"
        if isinstance(col_type, Integer):
            type_name = "integer"
        elif isinstance(col_type, Float):
            type_name = "float"
        elif isinstance(col_type, Boolean):
            type_name = "boolean"
        elif isinstance(col_type, DateTime):
            type_name = "datetime"
        elif isinstance(col_type, Date):
            type_name = "date"
        elif isinstance(col_type, Text):
            type_name = "text"
        columns.append({
            "name": attr.key,
            "type": type_name,
            "nullable": col.nullable,
            "default": str(col.default.arg) if col.default else None,
        })
    return {"name": table, "label": table, "columns": columns}


@router.get("/tables/{table}")
def list_rows(
    table: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort: Optional[str] = Query(None),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: db_models.User = Depends(require_user),
) -> Dict[str, Any]:
    """Paginated list with filtering, sorting and generic search."""
    model = _get_model(table)
    columns = _model_columns(model)

    q = db.query(model)

    # Column-specific filters from query params
    filters = _build_filters(model, dict(request.query_params))
    for f in filters:
        q = q.filter(f)

    # Generic search across string columns
    if search:
        mapper = inspect(model)
        search_conds = []
        for attr in mapper.column_attrs:
            col_type = attr.columns[0].type
            if isinstance(col_type, (String, Text)):
                search_conds.append(getattr(model, attr.key).ilike(f"%{search}%"))
        if search_conds:
            from sqlalchemy import or_
            q = q.filter(or_(*search_conds))

    # Sorting
    if sort and hasattr(model, sort):
        col = getattr(model, sort)
        q = q.order_by(col.desc() if order == "desc" else col.asc())
    else:
        q = q.order_by(model.id.desc())

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "data": [_row_to_dict(r, columns) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/tables/{table}/{row_id}")
def get_row(
    table: str,
    row_id: int,
    db: Session = Depends(get_db),
    user: db_models.User = Depends(require_user),
) -> Dict[str, Any]:
    """Single row by PK."""
    model = _get_model(table)
    row = db.get(model, row_id)
    if not row:
        raise HTTPException(404, "Row not found")
    return _row_to_dict(row, _model_columns(model))


@router.post("/tables/{table}", dependencies=[Depends(require_write)])
def create_row(
    table: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    user: db_models.User = Depends(require_user),
) -> Dict[str, Any]:
    """Insert a new row. Unknown keys are ignored."""
    model = _get_model(table)
    mapper = inspect(model)
    columns = _model_columns(model)

    data: Dict[str, Any] = {}
    for key in columns:
        if key not in payload:
            continue
        prop = mapper.attrs.get(key)
        col_type = getattr(prop, "columns", [None])[0].type if (prop and hasattr(prop, "columns")) else None
        data[key] = _coerce_value(payload[key], col_type)

    row = model(**data)
    db.add(row)
    db.flush()

    actor = user.username if user else None
    write_audit(
        db, user=actor, action="DATA_EDITOR_CREATE",
        entity=table, entity_id=row.id,
        details={"table": table, "data": {k: str(v) for k, v in data.items()}},
    )
    db.commit()
    db.refresh(row)
    return _row_to_dict(row, columns)


@router.patch("/tables/{table}/{row_id}", dependencies=[Depends(require_write)])
def update_row(
    table: str,
    row_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    user: db_models.User = Depends(require_user),
) -> Dict[str, Any]:
    """Partial update. Unknown keys are ignored."""
    model = _get_model(table)
    row = db.get(model, row_id)
    if not row:
        raise HTTPException(404, "Row not found")

    mapper = inspect(model)
    columns = _model_columns(model)
    changed: Dict[str, Any] = {}

    for key in columns:
        if key not in payload:
            continue
        old = getattr(row, key)
        prop = mapper.attrs.get(key)
        col_type = getattr(prop, "columns", [None])[0].type if (prop and hasattr(prop, "columns")) else None
        new_val = _coerce_value(payload[key], col_type)
        if new_val != old:
            changed[key] = {"from": _serialize_value(old), "to": _serialize_value(new_val)}
            setattr(row, key, new_val)

    if changed:
        actor = user.username if user else None
        write_audit(
            db, user=actor, action="DATA_EDITOR_UPDATE",
            entity=table, entity_id=row_id,
            details={"table": table, "changes": changed},
        )
        db.commit()
        db.refresh(row)

    return _row_to_dict(row, columns)


@router.delete("/tables/{table}/{row_id}", dependencies=[Depends(require_write)])
def delete_row(
    table: str,
    row_id: int,
    db: Session = Depends(get_db),
    user: db_models.User = Depends(require_user),
) -> Dict[str, Any]:
    """Hard delete. Use with caution."""
    model = _get_model(table)
    row = db.get(model, row_id)
    if not row:
        raise HTTPException(404, "Row not found")

    actor = user.username if user else None
    write_audit(
        db, user=actor, action="DATA_EDITOR_DELETE",
        entity=table, entity_id=row_id,
        details={"table": table},
    )
    db.delete(row)
    db.commit()
    return {"ok": True}
