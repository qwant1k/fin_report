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
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, func, inspect, select, text
from sqlalchemy.orm import Session

from auth import require_permission, require_user
from database import get_db
import models.db_models as db_models
from services.audit import write_audit

router = APIRouter(
    prefix="/api/data",
    tags=["data-editor"],
    dependencies=[Depends(require_permission("page.data_editor"))],
)

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
    "cdu_file_formats": db_models.CDUFileFormat,
    "import_jobs": db_models.ImportJob,
}

# These business ledgers have a dedicated four-eyes workflow.  They remain
# visible here for diagnostics but may not be mutated through the generic CRUD
# escape hatch (which would bypass status/audit invariants).
_WORKFLOW_TABLES = {"trades", "accounts_receivable", "cash_balances"}

# Read-only through the generic editor:
# * users / generated_reports — privilege escalation and bypass of the report
#   approval (an approved report is immutable);
# * imported snapshots, lots and calculated results — they are rebuilt by the
#   importers / calculator; a manual change must go through «Операционный
#   учёт» (maker-checker), as required by business process 8.2 E.
_READ_ONLY_TABLES = {
    "users", "generated_reports", "source_documents", "trade_files", "import_jobs",
    "bond_lots", "repo_lots", "deposit_lots", "cash_snapshots", "mv_snapshots",
    "portfolio_positions", "portfolio_summary", "security_holdings",
    "coupon_events", "redemption_events", "price_reconciliation", "alerts",
}

# Columns never exposed by the generic editor.
_HIDDEN_COLUMNS = {"password_hash"}

# ═══════════════════════════════════════════════════════════════════════════
# Human-friendly metadata (labels, groups, hints) for ordinary users
# ═══════════════════════════════════════════════════════════════════════════
_TABLE_INFO: Dict[str, Tuple[str, str, str]] = {
    # slug: (label, group, description)
    "cdu": ("ЧДУ и портфели", "Справочники", "Управляющие (ЧДУ) и портфели НБ РК: названия, коды участника KASE, целевые доли"),
    "cdu_limits": ("Лимиты ЧДУ", "Справочники", "Минимальные/максимальные, жёсткие и мягкие лимиты по категориям с датами действия"),
    "instrument_reference": ("Справочник ЦБ (выпуски)", "Справочники", "Параметры выпусков: ISIN, тикер, номинал, купон, даты, базис"),
    "instruments": ("Инструменты", "Справочники", "Перечень инструментов и их категорий"),
    "instrument_category_rules": ("Правила категорий", "Справочники", "Как бумага относится к категории отчёта (ГЦБ, МФО, агентские…)"),
    "formula_definitions": ("Формулы", "Справочники", "Настройки расчётных формул"),
    "cdu_file_formats": ("Форматы файлов ЧДУ", "Справочники", "Как читать файлы каждого управляющего"),
    "kase_prices": ("Котировки KASE", "Рыночные данные", "Цены закрытия и доходности KASE по датам"),
    "mbm_index": ("Индекс MBM", "Рыночные данные", "Бенчмарк: доходность и дюрация индекса MBM по датам"),
    "fx_rates": ("Курсы валют", "Рыночные данные", "Официальные курсы валют к тенге"),
    "bond_lots": ("Лоты облигаций", "Портфель (импорт и расчёт)", "Бумаги из Risk Report и Trade Report — формируются импортом"),
    "repo_lots": ("Сделки обратного РЕПО", "Портфель (импорт и расчёт)", "РЕПО из Risk Report / Trade Report — формируются импортом"),
    "deposit_lots": ("Депозиты", "Портфель (импорт и расчёт)", "Депозиты из Risk Report и файлов НБ РК"),
    "cash_snapshots": ("Остатки денег (срезы)", "Портфель (импорт и расчёт)", "Остатки денег на дату из Risk Report"),
    "cash_balances": ("Остатки денег (ручные)", "Портфель (импорт и расчёт)", "Остатки, введённые вручную (устаревший способ)"),
    "portfolio_positions": ("Позиции по категориям", "Портфель (импорт и расчёт)", "Результат расчёта: строки сводки по категориям"),
    "portfolio_summary": ("Итоги по ЧДУ", "Портфель (импорт и расчёт)", "Результат расчёта: итоги, доли, YTM, дюрация"),
    "mv_snapshots": ("Стоимость портфелей (MV)", "Портфель (импорт и расчёт)", "Срезы стоимости из Risk Report"),
    "security_holdings": ("Позиции ЦБ по ЧДУ", "Портфель (импорт и расчёт)", "Количество бумаг у управляющих"),
    "risk_report_notes": ("Заметки Risk Report", "Портфель (импорт и расчёт)", "Примечания из Risk Report"),
    "trades": ("Сделки", "Операции", "Сделки из Trade Report и ручные — правка через «Операционный учёт»"),
    "accounts_receivable": ("Дебиторская задолженность", "Операции", "Правка через «Операционный учёт»"),
    "coupon_events": ("Купонные выплаты", "Операции", "Начисленные купоны (дневная автоматизация)"),
    "redemption_events": ("Погашения", "Операции", "Погашения бумаг (дневная автоматизация)"),
    "price_reconciliation": ("Сверка цен с KASE", "Операции", "Расхождения цен сделок с KASE"),
    "alerts": ("Нарушения и предупреждения", "Операции", "Нарушения лимитов и предупреждения расчёта"),
    "source_documents": ("Загруженные документы", "Документы и система", "Все загруженные файлы и результат их разбора"),
    "trade_files": ("Файлы Trade Report", "Документы и система", "Загруженные Trade Report"),
    "generated_reports": ("Выпущенные отчёты", "Документы и система", "Отчёты и их согласование"),
    "import_jobs": ("Пакетные импорты", "Документы и система", "Журнал массовой загрузки"),
    "users": ("Пользователи", "Документы и система", "Учётные записи (правка — в «Настройки → Пользователи»)"),
}

_EDIT_HINT: Dict[str, Tuple[str, str]] = {
    "trades": ("Операционный учёт", "/accounting"),
    "accounts_receivable": ("Операционный учёт", "/accounting"),
    "cash_balances": ("Операционный учёт", "/accounting"),
    "users": ("Настройки", "/settings"),
    "bond_lots": ("Загрузка документов", "/documents"),
    "repo_lots": ("Загрузка документов", "/documents"),
    "deposit_lots": ("Загрузка документов", "/documents"),
    "cash_snapshots": ("Загрузка документов", "/documents"),
    "portfolio_positions": ("Сводка — «Пересчитать»", "/"),
    "portfolio_summary": ("Сводка — «Пересчитать»", "/"),
}

_COLUMN_LABELS: Dict[str, str] = {
    "accrued_interest": "НКД", "actual_value_date": "Факт. дата расчётов", "alert_date": "Дата", "alert_type": "Тип",
    "amount": "Сумма", "amount_ccy": "Сумма в валюте", "amount_kzt": "Сумма, ₸", "approved_at": "Согласовано (когда)",
    "approved_by": "Согласовал", "avg_purchase_price": "Средняя цена покупки", "balance_currency": "Остаток в валюте",
    "balance_date": "Дата остатка", "balance_kzt": "Остаток, ₸", "base": "Базис", "base_code": "Код базиса",
    "benchmark_duration": "Дюрация бенчмарка", "bond_type": "Вид облигации", "calculated_at": "Рассчитано",
    "category": "Категория", "cdu_id": "ЧДУ / портфель", "cdu_share_pct": "Доля в фонде", "change_reason": "Причина изменения",
    "clean_price": "Чистая цена", "close_date": "Дата закрытия", "close_price": "Цена закрытия", "close_value": "Сумма закрытия",
    "close_trade_id": "Сделка закрытия", "code": "Код", "comment": "Комментарий", "commission_total": "Комиссия всего",
    "contact_email": "E-mail", "contact_manager": "Контактное лицо", "counterparty": "Контрагент",
    "coupon_amount": "Сумма купона", "coupon_rate_pct": "Ставка купона, %", "coupon_rate_text": "Ставка купона (текст)",
    "coupon_type": "Вид купона", "created_at": "Создано", "created_by": "Создал", "currency": "Валюта",
    "current_price": "Текущая цена", "daily_change": "Изменение за день", "deal_id": "Номер сделки",
    "decision_comment": "Комментарий решения", "description": "Описание", "direction": "Направление",
    "dirty_price": "Грязная цена", "doc_date": "Дата документа", "doc_type": "Тип документа", "due_date": "Срок",
    "duration": "Дюрация", "email": "E-mail", "event_date": "Дата события", "expected_amount": "Ожидаемая сумма",
    "face_value": "Номинал", "face_value_current": "Номинал (текущий)", "face_value_initial": "Номинал (начальный)",
    "file_name": "Файл", "filename": "Файл", "file_size": "Размер файла", "frequency": "Выплат в год",
    "full_name": "ФИО", "fx_rate": "Курс", "hard_limit_pct": "Жёсткий лимит", "instrument_category": "Категория",
    "instrument_code": "Тикер", "instrument_kind": "Вид инструмента", "instrument_name": "Наименование",
    "interest_rate_pct": "Ставка, %", "is_active": "Активна", "is_manual": "Ручная", "is_resolved": "Решено",
    "isin": "ISIN", "issuer": "Эмитент", "issuer_type": "Тип эмитента", "index_date": "Дата индекса",
    "market_price": "Рыночная цена", "market_value": "Рыночная стоимость", "market_value_current": "Стоимость на дату",
    "market_value_prev": "Стоимость T-1", "maturity_date": "Дата погашения", "max_limit_pct": "Максимум",
    "message": "Сообщение", "min_limit_pct": "Минимум", "mod_duration": "Модиф. дюрация", "name": "Наименование",
    "nominal": "Номинал", "nominal_per_unit": "Номинал 1 бумаги", "nominal_volume": "Объём по номиналу",
    "note": "Примечание", "notes": "Примечания", "open_trade_id": "Сделка открытия", "operation_type": "Операция",
    "participant_code": "Код участника", "participant_code_prefix": "Префикс кода", "pct_of_total": "% портфеля",
    "portfolio_code": "Код портфеля", "report_code": "Код в сводном отчёте",
    "portfolio_type": "Тип портфеля", "position_date": "Дата позиции",
    "price_source": "Источник цены", "principal": "Сумма депозита", "purchase_price": "Цена покупки",
    "quantity": "Количество", "quantity_current": "Количество (текущее)", "rate": "Курс/ставка", "rate_date": "Дата курса",
    "rating": "Рейтинг", "record_date": "Дата признания", "rejected_at": "Отклонено (когда)", "rejected_by": "Отклонил",
    "related_trade_id": "Связанная сделка", "repo_rate_pct": "Ставка РЕПО, %", "repo_term_days": "Срок РЕПО, дн.",
    "report_date": "Отчётная дата", "report_type": "Вид отчёта", "role": "Роль", "rows_imported": "Строк загружено",
    "rows_parsed": "Строк разобрано", "rows_skipped": "Строк пропущено", "security_type": "Тип бумаги",
    "settlement_date": "Дата расчётов", "settlement_price": "Расчётная цена", "severity": "Важность",
    "share_target_pct": "Целевая доля", "short_name": "Краткое имя", "snapshot_date": "Дата среза",
    "soft_limit_pct": "Мягкий лимит", "source": "Источник", "source_doc_id": "Документ-источник",
    "start_date": "Начало обращения", "status": "Статус", "summary_date": "Дата сводки", "term_days": "Срок, дн.",
    "ticker_kase": "Тикер KASE", "total_mv_current": "Итого на дату", "total_mv_prev": "Итого T-1",
    "total_value": "Стоимость с НКД", "trade_date": "Дата сделки", "trade_id": "Сделка", "updated_at": "Изменено",
    "updated_by": "Изменил", "uploaded_at": "Загружено", "uploaded_by": "Загрузил", "username": "Логин",
    "valid_from": "Действует с", "valid_to": "Действует по", "valuation_date": "Дата оценки", "value_date": "Дата расчётов",
    "weight": "Вес", "workflow_status": "Статус согласования", "ytm": "Доходность (YTM)", "ytm_weighted": "YTM портфеля",
    "duration_weighted": "Дюрация портфеля", "nin": "НИН", "last_coupon_date": "Последний купон",
    "next_coupon_date": "Следующий купон", "quotation_type": "Предмет котирования", "rating_source": "Источник рейтинга",
    "rating_agency": "Рейтинговое агентство", "source_updated_at": "Обновлено в источнике", "base_code": "Код базиса", "parse_status": "Статус разбора", "parse_errors": "Ошибки разбора",
}

# technical columns hidden by default in the grid (still available)
_TECHNICAL_COLUMNS = {
    "created_at", "updated_at", "sha256", "file_path", "raw_file_path", "parse_meta_json", "raw_data_json",
    "parse_errors_json", "details_json", "params_json", "expression_json", "coupon_history_json", "log",
    "source_row_idx", "raw_trade_id", "last_synced_at", "fetched_at", "price_checked_at", "field_aliases",
}

_FK_DISPLAY = ("short_name", "name", "file_name", "filename", "username", "isin", "deal_id", "instrument_code")


def _column_label(key: str) -> str:
    return _COLUMN_LABELS.get(key) or key.replace("_", " ").capitalize()


def _slug_for_table(tablename: str) -> Optional[str]:
    for slug, model in _TABLE_REGISTRY.items():
        if getattr(model, "__tablename__", None) == tablename:
            return slug
    return None


def _fk_target(col) -> Optional[str]:
    for fk in col.foreign_keys:
        return _slug_for_table(fk.column.table.name)
    return None


def _display(row: Any) -> str:
    for attr in _FK_DISPLAY:
        value = getattr(row, attr, None)
        if value:
            return str(value)
    return f"#{row.id}"


def _ensure_generic_write_allowed(table: str) -> None:
    if table in _WORKFLOW_TABLES:
        raise HTTPException(
            409,
            "Таблица ведётся через раздел «Операционный учёт» и требует согласования",
        )
    if table in _READ_ONLY_TABLES:
        raise HTTPException(
            409,
            "Таблица доступна только для просмотра: данные формируются импортом/расчётом "
            "или защищены (пользователи, утверждённые отчёты)",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _get_model(table: str) -> Type:
    model = _TABLE_REGISTRY.get(table)
    if model is None:
        raise HTTPException(404, f"Таблица «{table}» не найдена")
    return model


def _model_columns(model: Type) -> List[str]:
    """Return list of simple (non-relationship) column attribute names."""
    mapper = inspect(model)
    return [
        col.key
        for col in mapper.column_attrs
        if col.key != "id" and not col.key.startswith("_") and col.key not in _HIDDEN_COLUMNS
    ]


def _coerce_value(value: Any, column_type: Any, field: str = "") -> Any:
    """Coerce JSON payload values to Python types matching the DB column.

    Raises HTTP 400 with a readable message instead of a server error.
    """
    if value is None:
        return None
    try:
        return _coerce_raw(value, column_type)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"Поле «{_column_label(field)}»: недопустимое значение {value!r}") from exc


def _coerce_raw(value: Any, column_type: Any) -> Any:
    if isinstance(value, str) and value.strip() == "" and not isinstance(column_type, (String, Text)):
        return None
    if isinstance(column_type, DateTime):
        if isinstance(value, str):
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00").replace(" ", "T"))
        return value
    if isinstance(column_type, Date):
        if isinstance(value, str):
            v = value.strip()
            if len(v) == 10 and v[2] == "." and v[5] == ".":          # 24.09.2026
                return datetime.strptime(v, "%d.%m.%Y").date()
            return date.fromisoformat(v[:10])
        if isinstance(value, datetime):
            return value.date()
        return value
    if isinstance(column_type, Boolean):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "да", "yes", "y", "on")
        return bool(value)
    if isinstance(column_type, Integer):
        return int(float(str(value).replace(" ", "").replace(",", ".")))
    if isinstance(column_type, Float):
        return float(str(value).replace(" ", "").replace("\u00a0", "").replace(",", "."))
    if isinstance(column_type, Text):
        return str(value)
    if isinstance(column_type, String):
        return str(value)[:column_type.length] if column_type.length else str(value)
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
        if key in ("page", "page_size", "sort", "order", "search", "_"):
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
        elif isinstance(col_type, DateTime):
            day = _coerce_value(str(val)[:10], Date(), key)
            conditions.append(col >= datetime.combine(day, datetime.min.time()))
            conditions.append(col < datetime.combine(day, datetime.max.time()))
        else:
            conditions.append(col == _coerce_value(val, col_type, key))
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
) -> List[Dict[str, Any]]:
    """Return all whitelisted tables with human-friendly labels, groups and row counts."""
    out = []
    for k, model in _TABLE_REGISTRY.items():
        label, group, description = _TABLE_INFO.get(k, (k, "Прочее", ""))
        try:
            count = db.query(func.count(model.id)).scalar()
        except Exception:  # pragma: no cover - table missing in an old DB
            db.rollback()
            count = None
        hint = _EDIT_HINT.get(k)
        out.append({
            "name": k, "label": label, "group": group, "description": description, "rows": count,
            "read_only": k in _READ_ONLY_TABLES or k in _WORKFLOW_TABLES,
            "edit_hint": {"label": hint[0], "route": hint[1]} if hint else None,
        })
    return out


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
        if attr.key == "id" or attr.key in _HIDDEN_COLUMNS:
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
        default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
        columns.append({
            "name": attr.key,
            "label": _column_label(attr.key),
            "type": type_name,
            "nullable": col.nullable,
            "required": (not col.nullable) and col.default is None and col.server_default is None,
            "default": str(default) if default is not None else None,
            "max_length": getattr(col_type, "length", None),
            "fk_table": _fk_target(col),
            "technical": attr.key in _TECHNICAL_COLUMNS,
        })
    label, group, description = _TABLE_INFO.get(table, (table, "Прочее", ""))
    hint = _EDIT_HINT.get(table)
    return {
        "name": table, "label": label, "group": group, "description": description, "columns": columns,
        "read_only": table in _READ_ONLY_TABLES or table in _WORKFLOW_TABLES,
        "edit_hint": {"label": hint[0], "route": hint[1]} if hint else None,
    }


@router.get("/lookup/{table}")
def lookup(
    table: str,
    search: Optional[str] = Query(None),
    ids: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: db_models.User = Depends(require_user),
) -> List[Dict[str, Any]]:
    """Id → display name pairs of a table, for foreign key drop-downs."""
    model = _get_model(table)
    q = db.query(model)
    if ids:
        wanted = [int(x) for x in ids.split(",") if x.strip().isdigit()]
        q = q.filter(model.id.in_(wanted or [-1]))
    elif search:
        from sqlalchemy import or_
        conds = [getattr(model, a).ilike(f"%{search}%") for a in _FK_DISPLAY if hasattr(model, a)]
        if conds:
            q = q.filter(or_(*conds))
    return [{"id": r.id, "label": _display(r)} for r in q.order_by(model.id.desc()).limit(limit).all()]


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

    # display names of referenced rows (ЧДУ name instead of cdu_id = 3)
    fk_labels: Dict[str, Dict[str, str]] = {}
    mapper = inspect(model)
    for attr in mapper.column_attrs:
        target = _fk_target(attr.columns[0])
        if not target or attr.key in _HIDDEN_COLUMNS:
            continue
        ids = {getattr(r, attr.key) for r in rows if getattr(r, attr.key) is not None}
        if not ids:
            continue
        tmodel = _TABLE_REGISTRY[target]
        fk_labels[attr.key] = {str(t.id): _display(t) for t in db.query(tmodel).filter(tmodel.id.in_(ids)).all()}

    return {
        "data": [_row_to_dict(r, columns) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "fk_labels": fk_labels,
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
        raise HTTPException(404, "Запись не найдена")
    return _row_to_dict(row, _model_columns(model))


@router.post("/tables/{table}", dependencies=[Depends(require_permission("data_editor.edit"))])
def create_row(
    table: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    user: db_models.User = Depends(require_user),
) -> Dict[str, Any]:
    """Insert a new row. Unknown keys are ignored."""
    _ensure_generic_write_allowed(table)
    model = _get_model(table)
    mapper = inspect(model)
    columns = _model_columns(model)

    data: Dict[str, Any] = {}
    for key in columns:
        if key not in payload:
            continue
        prop = mapper.attrs.get(key)
        col_type = getattr(prop, "columns", [None])[0].type if (prop and hasattr(prop, "columns")) else None
        data[key] = _coerce_value(payload[key], col_type, key)

    for attr in mapper.column_attrs:
        col = attr.columns[0]
        if (attr.key != "id" and attr.key not in _HIDDEN_COLUMNS and not col.nullable and col.default is None
                and col.server_default is None and data.get(attr.key) in (None, "")):
            raise HTTPException(400, f"Заполните обязательное поле «{_column_label(attr.key)}»")

    row = model(**data)
    db.add(row)
    _flush_or_400(db)

    actor = user.username if user else None
    write_audit(
        db, user=actor, action="DATA_EDITOR_CREATE",
        entity=table, entity_id=row.id,
        details={"table": table, "data": {k: str(v) for k, v in data.items()}},
    )
    db.commit()
    db.refresh(row)
    return _row_to_dict(row, columns)


@router.patch("/tables/{table}/{row_id}", dependencies=[Depends(require_permission("data_editor.edit"))])
def update_row(
    table: str,
    row_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    user: db_models.User = Depends(require_user),
) -> Dict[str, Any]:
    """Partial update. Unknown keys are ignored."""
    _ensure_generic_write_allowed(table)
    model = _get_model(table)
    row = db.get(model, row_id)
    if not row:
        raise HTTPException(404, "Запись не найдена")

    mapper = inspect(model)
    columns = _model_columns(model)
    changed: Dict[str, Any] = {}

    for key in columns:
        if key not in payload:
            continue
        old = getattr(row, key)
        prop = mapper.attrs.get(key)
        col_type = getattr(prop, "columns", [None])[0].type if (prop and hasattr(prop, "columns")) else None
        new_val = _coerce_value(payload[key], col_type, key)
        col = prop.columns[0] if prop is not None and hasattr(prop, "columns") else None
        if new_val is None and col is not None and not col.nullable:
            raise HTTPException(400, f"Поле «{_column_label(key)}» не может быть пустым")
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
        _flush_or_400(db)
        db.commit()
        db.refresh(row)

    return _row_to_dict(row, columns)


@router.delete("/tables/{table}/{row_id}", dependencies=[Depends(require_permission("data_editor.edit"))])
def delete_row(
    table: str,
    row_id: int,
    db: Session = Depends(get_db),
    user: db_models.User = Depends(require_user),
) -> Dict[str, Any]:
    """Hard delete. Use with caution."""
    _ensure_generic_write_allowed(table)
    model = _get_model(table)
    row = db.get(model, row_id)
    if not row:
        raise HTTPException(404, "Запись не найдена")

    actor = user.username if user else None
    write_audit(
        db, user=actor, action="DATA_EDITOR_DELETE",
        entity=table, entity_id=row_id,
        details={"table": table},
    )
    db.delete(row)
    _flush_or_400(db, deleting=True)
    db.commit()
    return {"ok": True}


def _flush_or_400(db: Session, *, deleting: bool = False) -> None:
    from sqlalchemy.exc import IntegrityError
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        msg = str(exc.orig).lower()
        if deleting or "foreign key" in msg:
            raise HTTPException(409, "Запись используется в других таблицах — сначала измените или удалите связанные записи") from exc
        if "unique" in msg:
            raise HTTPException(409, "Такая запись уже есть (значение должно быть уникальным)") from exc
        if "not null" in msg:
            raise HTTPException(400, "Не заполнено обязательное поле") from exc
        raise HTTPException(400, f"База данных отклонила изменение: {exc.orig}") from exc
