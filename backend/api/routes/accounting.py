"""Operational accounting: manual trades, cash and receivables.

All manual records use a four-eyes workflow.  A pending/rejected/cancelled
record is retained for audit but is not included in portfolio calculations.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from auth import has_permission, require_any_permission, require_permission, require_user
from database import get_db
from models.db_models import (
    AccountReceivable, CashMovement, CDU, ReceivableTransaction, RepoLot,
    FXRate, SourceDocument, Trade, User,
)
from services.audit import write_audit
from services.holdings_sync import sync_holdings
from services.workflow import EFFECTIVE_STATUSES


router = APIRouter(
    prefix="/api/accounting",
    tags=["operational-accounting"],
    dependencies=[Depends(require_permission("page.accounting"))],
)

PENDING = "PENDING_APPROVAL"
PENDING_CANCELLATION = "PENDING_CANCELLATION"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
CANCELLED = "CANCELLED"
WORKFLOW_STATUSES = {PENDING, PENDING_CANCELLATION, APPROVED, REJECTED, CANCELLED}

TRADE_TYPES = {
    "BUY", "SELL", "REPO_OPEN", "REPO_CLOSE", "COUPON", "REDEMPTION",
    "DEPOSIT_OPEN", "DEPOSIT_CLOSE", "FX_BUY", "FX_SELL",
    "CASH_TOPUP", "CASH_WITHDRAW", "OTHER",
}
OUTFLOW_TYPES = {"BUY", "REPO_OPEN", "DEPOSIT_OPEN", "FX_BUY", "CASH_WITHDRAW"}
INFLOW_TYPES = {"SELL", "REPO_CLOSE", "COUPON", "REDEMPTION", "DEPOSIT_CLOSE", "FX_SELL", "CASH_TOPUP"}
AR_TX_TYPES = {"REPAYMENT", "WRITE_OFF", "ADJUSTMENT"}


def _as_date(value: Any, field: str, *, required: bool = True) -> Optional[date]:
    if value in (None, ""):
        if required:
            raise HTTPException(400, f"{field} обязателен")
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise HTTPException(400, f"{field}: ожидается YYYY-MM-DD") from exc


def _as_float(value: Any, field: str, *, required: bool = False) -> Optional[float]:
    if value in (None, ""):
        if required:
            raise HTTPException(400, f"{field} обязателен")
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"{field}: ожидается число") from exc


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise HTTPException(400, f"{field} обязателен")
    return text


def _cdu(db: Session, cdu_id: Any) -> CDU:
    try:
        row = db.get(CDU, int(cdu_id))
    except (TypeError, ValueError):
        row = None
    if row is None or not row.is_active:
        raise HTTPException(400, "Выбранный портфель/ЧДУ не найден или неактивен")
    return row


def _to_kzt(
    db: Session, *, amount: float, currency: str, operation_date: date,
    supplied_amount_kzt: Any = None,
) -> float:
    supplied = _as_float(supplied_amount_kzt, "amount_kzt")
    if supplied is not None:
        return supplied
    if currency == "KZT":
        return amount
    fx = db.execute(select(FXRate).where(
        FXRate.currency == currency,
        FXRate.rate_date <= operation_date,
    ).order_by(FXRate.rate_date.desc())).scalars().first()
    if fx is None:
        raise HTTPException(
            400,
            f"Нет курса {currency} на {operation_date:%d.%m.%Y} или ранее; "
            "укажите amount_kzt вручную",
        )
    return amount * fx.rate


def _name_map(db: Session) -> dict[int, str]:
    return {row.id: row.short_name or row.name for row in db.query(CDU).all()}


def _workflow_dict(row: Any) -> dict[str, Any]:
    return {
        "workflow_status": row.workflow_status,
        "is_active": row.is_active,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_by": getattr(row, "updated_by", None),
        "approved_by": row.approved_by,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "rejected_by": row.rejected_by,
        "rejected_at": row.rejected_at.isoformat() if row.rejected_at else None,
        "decision_comment": row.decision_comment,
    }


def _trade_dict(row: Trade, names: dict[int, str]) -> dict[str, Any]:
    return {
        "id": row.id, "cdu_id": row.cdu_id, "cdu_name": names.get(row.cdu_id),
        "trade_date": row.trade_date.isoformat(), "value_date": row.value_date.isoformat(),
        "operation_type": row.operation_type, "instrument_kind": row.instrument_kind,
        "instrument_category": row.instrument_category, "instrument_code": row.instrument_code,
        "isin": row.isin, "description": row.description, "deal_id": row.deal_id,
        "amount_kzt": row.amount_kzt, "amount_ccy": row.amount_ccy,
        "currency": row.currency, "quantity": row.quantity, "face_value": row.face_value,
        "clean_price": row.clean_price, "dirty_price": row.dirty_price,
        "market_price": row.market_price, "accrued_interest": row.accrued_interest,
        "ytm": row.ytm, "repo_rate_pct": row.repo_rate_pct,
        "repo_open_price": row.repo_open_price, "repo_close_price": row.repo_close_price,
        "repo_term_days": row.repo_term_days, "repo_buyback_sum": row.repo_buyback_sum,
        "commission_total": row.commission_total, "notes": row.notes,
        "change_reason": row.change_reason, "is_manual": row.is_manual,
        **_workflow_dict(row),
    }


def _cash_dict(row: CashMovement, names: dict[int, str]) -> dict[str, Any]:
    return {
        "id": row.id, "cdu_id": row.cdu_id, "cdu_name": names.get(row.cdu_id),
        "operation_date": row.operation_date.isoformat(), "amount": row.amount,
        "amount_kzt": row.amount_kzt, "currency": row.currency,
        "movement_type": row.movement_type, "basis": row.basis,
        "related_trade_id": row.related_trade_id, "related_isin": row.related_isin,
        "account": row.account,
        "comment": row.comment, "change_reason": row.change_reason,
        "is_manual": row.is_manual, **_workflow_dict(row),
    }


def _tx_effect(row: ReceivableTransaction) -> float:
    value = row.amount_kzt if row.amount_kzt is not None else row.amount
    if row.operation_type in {"REPAYMENT", "WRITE_OFF"}:
        return -abs(float(value or 0.0))
    return float(value or 0.0)


def receivable_balance_as_of(db: Session, row: AccountReceivable, as_of: date) -> float:
    initial = row.amount_kzt if row.amount_kzt is not None else row.amount
    txs = db.execute(select(ReceivableTransaction).where(
        ReceivableTransaction.receivable_id == row.id,
        ReceivableTransaction.operation_date <= as_of,
        ReceivableTransaction.workflow_status.in_(EFFECTIVE_STATUSES),
        ReceivableTransaction.is_active.is_(True),
    )).scalars().all()
    return max(float(initial or 0.0) + sum(_tx_effect(tx) for tx in txs), 0.0)


def _sync_receivable_current(db: Session, row: AccountReceivable) -> None:
    balance = receivable_balance_as_of(db, row, date.max)
    row.balance_kzt = balance
    row.balance_currency = balance if row.currency == "KZT" else row.balance_currency
    initial = float(row.amount_kzt if row.amount_kzt is not None else row.amount or 0.0)
    if balance <= 0.000001:
        row.status = "CLOSED"
    elif balance < initial:
        row.status = "PARTIAL"
    else:
        row.status = "OPEN"


def _tx_dict(row: ReceivableTransaction) -> dict[str, Any]:
    return {
        "id": row.id, "receivable_id": row.receivable_id,
        "operation_date": row.operation_date.isoformat(),
        "operation_type": row.operation_type, "amount": row.amount,
        "amount_kzt": row.amount_kzt, "currency": row.currency,
        "basis": row.basis, "comment": row.comment, **_workflow_dict(row),
    }


def _receivable_dict(
    db: Session, row: AccountReceivable, names: dict[int, str], as_of: date,
) -> dict[str, Any]:
    txs = db.execute(select(ReceivableTransaction).where(
        ReceivableTransaction.receivable_id == row.id,
    ).order_by(ReceivableTransaction.operation_date.desc(), ReceivableTransaction.id.desc())).scalars().all()
    return {
        "id": row.id, "cdu_id": row.cdu_id, "cdu_name": names.get(row.cdu_id),
        "record_date": row.record_date.isoformat(), "isin": row.isin,
        "counterparty": row.counterparty, "description": row.description,
        "currency": row.currency, "amount": row.amount, "amount_kzt": row.amount_kzt,
        "balance_kzt": receivable_balance_as_of(db, row, as_of),
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "status": row.status, "portfolio_code": row.portfolio_code,
        "notes": row.notes, "change_reason": row.change_reason,
        "is_manual": row.is_manual, "transactions": [_tx_dict(tx) for tx in txs],
        **_workflow_dict(row),
    }


def _repo_dict(row: RepoLot, report_date: date, names: dict[int, str]) -> dict[str, Any]:
    start = row.valuation_date or row.trade_date
    elapsed = max((report_date - start).days, 0)
    if row.term_days:
        elapsed = min(elapsed, row.term_days)
    if row.close_value and row.close_value > row.face_value and row.term_days:
        reward = (row.close_value - row.face_value) * elapsed / row.term_days
    else:
        rate = float(row.repo_rate_pct or 0.0)
        if abs(rate) > 1:
            rate /= 100.0
        reward = float(row.face_value or 0.0) * rate * elapsed / float(row.base or 365)
    return {
        "id": row.id, "cdu_id": row.cdu_id, "cdu_name": names.get(row.cdu_id),
        "deal_id": row.deal_id, "instrument_code": row.instrument_code, "isin": row.isin,
        "open_date": start.isoformat(), "close_date": row.close_date.isoformat() if row.close_date else None,
        "open_amount": row.face_value, "close_amount": row.close_value,
        "repo_rate_pct": row.repo_rate_pct, "term_days": row.term_days,
        "accrued_reward": reward, "value_on_date": float(row.face_value or 0.0) + reward,
    }


@router.get("/overview")
def overview(
    report_date: date = Query(...), cdu_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    names = _name_map(db)
    trade_q = db.query(Trade).filter(Trade.is_manual.is_(True), Trade.trade_date <= report_date)
    cash_q = db.query(CashMovement).filter(CashMovement.operation_date <= report_date)
    ar_q = db.query(AccountReceivable).filter(AccountReceivable.record_date <= report_date)
    repo_q = db.query(RepoLot).filter(
        RepoLot.valuation_date <= report_date,
        or_(RepoLot.close_date.is_(None), RepoLot.close_date > report_date),
    )
    if cdu_id is not None:
        trade_q = trade_q.filter(Trade.cdu_id == cdu_id)
        cash_q = cash_q.filter(CashMovement.cdu_id == cdu_id)
        ar_q = ar_q.filter(AccountReceivable.cdu_id == cdu_id)
        repo_q = repo_q.filter(RepoLot.cdu_id == cdu_id)
    trades = trade_q.order_by(Trade.trade_date.desc(), Trade.id.desc()).limit(500).all()
    cash = cash_q.order_by(CashMovement.operation_date.desc(), CashMovement.id.desc()).limit(500).all()
    receivables = ar_q.order_by(AccountReceivable.record_date.desc(), AccountReceivable.id.desc()).limit(500).all()
    repos = repo_q.order_by(RepoLot.trade_date.desc(), RepoLot.id.desc()).limit(500).all()
    return {
        "report_date": report_date.isoformat(),
        "trades": [_trade_dict(row, names) for row in trades],
        "cash_movements": [_cash_dict(row, names) for row in cash],
        "receivables": [_receivable_dict(db, row, names, report_date) for row in receivables],
        "repo_positions": [_repo_dict(row, report_date, names) for row in repos],
    }


def _trade_values(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    cdu = _cdu(db, payload.get("cdu_id"))
    op = str(payload.get("operation_type") or "").strip().upper()
    if op not in TRADE_TYPES:
        raise HTTPException(400, "Неизвестный вид сделки")
    amount = _as_float(payload.get("amount_kzt"), "amount_kzt", required=True) or 0.0
    if op in OUTFLOW_TYPES:
        amount = -abs(amount)
    elif op in INFLOW_TYPES:
        amount = abs(amount)
    return {
        "cdu_id": cdu.id,
        "trade_date": _as_date(payload.get("trade_date"), "trade_date"),
        "value_date": _as_date(payload.get("value_date"), "value_date"),
        "operation_type": op,
        "direction": "Покупка" if op in OUTFLOW_TYPES else ("Продажа" if op in INFLOW_TYPES else None),
        "instrument_kind": payload.get("instrument_kind"),
        "instrument_category": payload.get("instrument_category") or "OTHER",
        "instrument_code": payload.get("instrument_code") or payload.get("isin"),
        "isin": payload.get("isin"), "description": payload.get("description"),
        "deal_id": payload.get("deal_id"), "amount_kzt": amount,
        "amount_ccy": _as_float(payload.get("amount_ccy"), "amount_ccy") or amount,
        "currency": str(payload.get("currency") or "KZT").strip().upper()[:8],
        "quantity": _as_float(payload.get("quantity"), "quantity"),
        "face_value": _as_float(payload.get("face_value"), "face_value"),
        "clean_price": _as_float(payload.get("clean_price"), "clean_price"),
        "dirty_price": _as_float(payload.get("dirty_price"), "dirty_price"),
        "market_price": _as_float(payload.get("market_price"), "market_price"),
        "accrued_interest": _as_float(payload.get("accrued_interest"), "accrued_interest"),
        "ytm": _as_float(payload.get("ytm"), "ytm"),
        "repo_rate_pct": _as_float(payload.get("repo_rate_pct"), "repo_rate_pct"),
        "repo_open_price": _as_float(payload.get("repo_open_price"), "repo_open_price"),
        "repo_close_price": _as_float(payload.get("repo_close_price"), "repo_close_price"),
        "repo_term_days": int(payload["repo_term_days"]) if payload.get("repo_term_days") not in (None, "") else None,
        "repo_buyback_sum": _as_float(payload.get("repo_buyback_sum"), "repo_buyback_sum"),
        "commission_total": _as_float(payload.get("commission_total"), "commission_total"),
        "notes": payload.get("notes"),
        "change_reason": _required_text(payload.get("change_reason"), "Основание/причина"),
    }


@router.post("/trades", dependencies=[Depends(require_permission("manual.trades.manage"))])
def create_trade(payload: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(require_user)):
    values = _trade_values(db, payload)
    row = Trade(**values, is_manual=True, is_active=True, workflow_status=PENDING,
                created_by=user.username, updated_by=user.username)
    db.add(row); db.flush()
    write_audit(db, user=user.username, action="MANUAL_TRADE_CREATED", entity="Trade", entity_id=row.id, details=values)
    db.commit(); db.refresh(row)
    return _trade_dict(row, _name_map(db))


@router.patch("/trades/{row_id}", dependencies=[Depends(require_permission("manual.trades.manage"))])
def update_trade(row_id: int, payload: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(require_user)):
    row = db.get(Trade, row_id)
    if not row or not row.is_manual:
        raise HTTPException(404, "Ручная сделка не найдена")
    values = _trade_values(db, {**_trade_dict(row, {}), **payload})
    before = {key: getattr(row, key) for key in values}
    for key, value in values.items(): setattr(row, key, value)
    row.workflow_status = PENDING; row.updated_by = user.username
    row.approved_by = None; row.approved_at = None; row.decision_comment = None
    # The previously approved derived cash leg must stop affecting the
    # portfolio while the amended trade is awaiting a second pair of eyes.
    _upsert_trade_cash(db, row)
    write_audit(db, user=user.username, action="MANUAL_TRADE_UPDATED", entity="Trade", entity_id=row.id,
                details={"before": {k: str(v) for k, v in before.items()}, "after": {k: str(v) for k, v in values.items()}})
    db.commit(); db.refresh(row)
    return _trade_dict(row, _name_map(db))


_OUTFLOW_TYPES = {"PAYMENT", "COMMISSION", "WITHDRAWAL", "FEE"}
_INFLOW_TYPES = {"RECEIPT", "COUPON", "REDEMPTION", "CONTRIBUTION", "INITIAL_BALANCE"}


@router.get("/accounts")
def known_accounts(cdu_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Accounts of a manager known from bound custodian statements and earlier movements."""
    import json as _json
    out: dict[str, dict[str, Any]] = {}
    q = select(SourceDocument).where(SourceDocument.doc_type == "STATEMENT_PDF",
                                     SourceDocument.cdu_id.is_not(None))
    if cdu_id:
        q = q.where(SourceDocument.cdu_id == cdu_id)
    for doc in db.execute(q).scalars():
        try:
            meta = _json.loads(doc.parse_meta_json or "{}")
        except ValueError:
            continue
        for sec in meta.get("sections") or []:
            acc = sec.get("account")
            if acc:
                out.setdefault(acc, {"account": acc, "currency": sec.get("currency"),
                                     "cdu_id": doc.cdu_id, "source": "statement"})
    q2 = select(CashMovement.account, CashMovement.currency, CashMovement.cdu_id).where(
        CashMovement.account.is_not(None)).distinct()
    if cdu_id:
        q2 = q2.where(CashMovement.cdu_id == cdu_id)
    for acc, cur, cid in db.execute(q2).all():
        out.setdefault(acc, {"account": acc, "currency": cur, "cdu_id": cid, "source": "manual"})
    return sorted(out.values(), key=lambda x: x["account"])


def _cash_values(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    cdu = _cdu(db, payload.get("cdu_id"))
    operation_date = _as_date(payload.get("operation_date"), "operation_date")
    amount = _as_float(payload.get("amount"), "amount", required=True) or 0.0
    if abs(amount) < 0.000001:
        raise HTTPException(400, "Сумма движения не может быть нулевой")
    currency = str(payload.get("currency") or "KZT").strip().upper()[:8]
    movement_type = _required_text(payload.get("movement_type"), "Вид движения").upper()
    # the sign follows the kind of movement (users type amounts without a sign)
    if movement_type in _OUTFLOW_TYPES:
        amount = -abs(amount)
    elif movement_type in _INFLOW_TYPES:
        amount = abs(amount)
    account = str(payload.get("account") or "").strip().upper().replace(" ", "") or None
    if account and len(account) > 40:
        raise HTTPException(400, "Номер счёта слишком длинный")
    return {
        "cdu_id": cdu.id, "operation_date": operation_date, "account": account,
        "amount": amount, "amount_kzt": _to_kzt(
            db, amount=amount, currency=currency, operation_date=operation_date,
            supplied_amount_kzt=payload.get("amount_kzt"),
        ),
        "currency": currency,
        "movement_type": movement_type,
        "basis": _required_text(payload.get("basis"), "Назначение платежа"),
        "related_trade_id": payload.get("related_trade_id"), "related_isin": payload.get("related_isin"),
        "comment": payload.get("comment"),
        "change_reason": _required_text(payload.get("change_reason") or payload.get("basis"), "Причина"),
    }


@router.post("/cash-movements", dependencies=[Depends(require_permission("manual.cash.manage"))])
def create_cash(payload: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(require_user)):
    values = _cash_values(db, payload)
    row = CashMovement(**values, is_manual=True, is_active=True, workflow_status=PENDING,
                       created_by=user.username, updated_by=user.username)
    db.add(row); db.flush()
    write_audit(db, user=user.username, action="MANUAL_CASH_CREATED", entity="CashMovement", entity_id=row.id, details=values)
    db.commit(); db.refresh(row)
    return _cash_dict(row, _name_map(db))


@router.patch("/cash-movements/{row_id}", dependencies=[Depends(require_permission("manual.cash.manage"))])
def update_cash(row_id: int, payload: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(require_user)):
    row = db.get(CashMovement, row_id)
    if not row or not row.is_manual:
        raise HTTPException(404, "Ручное движение не найдено")
    current = _cash_dict(row, {})
    values = _cash_values(db, {**current, **payload})
    before = {key: getattr(row, key) for key in values}
    for key, value in values.items(): setattr(row, key, value)
    row.workflow_status = PENDING; row.updated_by = user.username
    row.approved_by = None; row.approved_at = None; row.decision_comment = None
    write_audit(db, user=user.username, action="MANUAL_CASH_UPDATED", entity="CashMovement", entity_id=row.id,
                details={"before": {k: str(v) for k, v in before.items()}, "after": {k: str(v) for k, v in values.items()}})
    db.commit(); db.refresh(row)
    return _cash_dict(row, _name_map(db))


def _receivable_values(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    cdu = _cdu(db, payload.get("cdu_id"))
    record_date = _as_date(payload.get("record_date"), "record_date")
    amount = _as_float(payload.get("amount"), "amount", required=True) or 0.0
    if amount <= 0:
        raise HTTPException(400, "Первоначальная сумма должна быть больше нуля")
    currency = str(payload.get("currency") or "KZT").strip().upper()[:8]
    amount_kzt = _to_kzt(
        db, amount=amount, currency=currency, operation_date=record_date,
        supplied_amount_kzt=payload.get("amount_kzt"),
    )
    return {
        "cdu_id": cdu.id, "record_date": record_date,
        "isin": payload.get("isin"), "counterparty": _required_text(payload.get("counterparty"), "Контрагент"),
        "description": _required_text(payload.get("description"), "Основание возникновения"),
        "currency": currency, "amount": amount, "amount_kzt": amount_kzt,
        "balance_currency": amount, "balance_kzt": amount_kzt or 0.0,
        "due_date": _as_date(payload.get("due_date"), "due_date", required=False),
        "portfolio_code": payload.get("portfolio_code"), "notes": payload.get("notes"),
        "change_reason": _required_text(payload.get("change_reason") or payload.get("description"), "Причина"),
    }


@router.post("/receivables", dependencies=[Depends(require_permission("manual.receivables.manage"))])
def create_receivable(payload: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(require_user)):
    values = _receivable_values(db, payload)
    row = AccountReceivable(**values, status="OPEN", is_manual=True, is_active=True,
                            workflow_status=PENDING, created_by=user.username, updated_by=user.username)
    db.add(row); db.flush()
    write_audit(db, user=user.username, action="RECEIVABLE_CREATED", entity="AccountReceivable", entity_id=row.id, details=values)
    db.commit(); db.refresh(row)
    return _receivable_dict(db, row, _name_map(db), date.today())


@router.patch("/receivables/{row_id}", dependencies=[Depends(require_permission("manual.receivables.manage"))])
def update_receivable(row_id: int, payload: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(require_user)):
    row = db.get(AccountReceivable, row_id)
    if not row or not row.is_manual:
        raise HTTPException(404, "Дебиторская задолженность не найдена")
    current = _receivable_dict(db, row, {}, date.today())
    values = _receivable_values(db, {**current, **payload})
    before = {key: getattr(row, key) for key in values}
    for key, value in values.items(): setattr(row, key, value)
    row.workflow_status = PENDING; row.updated_by = user.username
    row.approved_by = None; row.approved_at = None; row.decision_comment = None
    write_audit(db, user=user.username, action="RECEIVABLE_UPDATED", entity="AccountReceivable", entity_id=row.id,
                details={"before": {k: str(v) for k, v in before.items()}, "after": {k: str(v) for k, v in values.items()}})
    db.commit(); db.refresh(row)
    return _receivable_dict(db, row, _name_map(db), date.today())


@router.post("/receivables/{row_id}/transactions", dependencies=[Depends(require_permission("manual.receivables.manage"))])
def create_receivable_transaction(row_id: int, payload: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(require_user)):
    parent = db.get(AccountReceivable, row_id)
    if not parent or not parent.is_active:
        raise HTTPException(404, "Дебиторская задолженность не найдена")
    op = str(payload.get("operation_type") or "").strip().upper()
    if op not in AR_TX_TYPES:
        raise HTTPException(400, "Операция должна быть REPAYMENT, WRITE_OFF или ADJUSTMENT")
    amount = _as_float(payload.get("amount"), "amount", required=True) or 0.0
    if op != "ADJUSTMENT" and amount <= 0:
        raise HTTPException(400, "Сумма погашения/списания должна быть больше нуля")
    operation_date = _as_date(payload.get("operation_date"), "operation_date")
    currency = str(payload.get("currency") or parent.currency).strip().upper()[:8]
    row = ReceivableTransaction(
        receivable_id=parent.id,
        operation_date=operation_date,
        operation_type=op, amount=amount,
        amount_kzt=_to_kzt(
            db, amount=amount, currency=currency, operation_date=operation_date,
            supplied_amount_kzt=payload.get("amount_kzt"),
        ),
        currency=currency,
        basis=_required_text(payload.get("basis"), "Основание"), comment=payload.get("comment"),
        workflow_status=PENDING, is_active=True, created_by=user.username,
    )
    db.add(row); db.flush()
    write_audit(db, user=user.username, action="RECEIVABLE_TRANSACTION_CREATED",
                entity="ReceivableTransaction", entity_id=row.id,
                details={"receivable_id": parent.id, "operation_type": op, "amount": amount})
    db.commit(); db.refresh(row)
    return _tx_dict(row)


# ───────────────────── «Новая операция»: one form for all manual operations ─────────────────────
#
# The user picks the purpose of the operation (поступление денег, покупка ЦБ,
# закрытие дебиторки, …); the purpose decides which ledger records are created.
# Only the date and the amount are required.  Without a manager the operation
# is booked in the fund's own portfolio («Собственные активы», NBRK_OWN), so it
# still takes part in the fund total.  As every manual record it waits for the
# approval of a second user and changes the books only after that.

OPERATION_PURPOSES: list[dict[str, Any]] = [
    {"code": "CASH_RECEIPT", "label": "Поступление денег", "group": "Деньги", "kind": "cash",
     "movement_type": "RECEIPT", "sign": 1, "hint": "Зачисление на счёт: возврат средств, перевод, прочие поступления"},
    {"code": "CONTRIBUTION", "label": "Передача средств в управление (взнос)", "group": "Деньги", "kind": "cash",
     "movement_type": "CONTRIBUTION", "sign": 1, "hint": "Фонд перечислил деньги в портфель ЧДУ"},
    {"code": "COUPON", "label": "Получение купона", "group": "Деньги", "kind": "cash",
     "movement_type": "COUPON", "sign": 1, "hint": "Купон по бумаге — укажите ISIN, если известен"},
    {"code": "OPENING_BALANCE", "label": "Входящий остаток денег", "group": "Деньги", "kind": "cash",
     "movement_type": "INITIAL_BALANCE", "sign": 1, "hint": "Начальный остаток, если среза на дату нет"},
    {"code": "CASH_PAYMENT", "label": "Оплата / списание денег", "group": "Деньги", "kind": "cash",
     "movement_type": "PAYMENT", "sign": -1, "hint": "Списание со счёта: оплата услуг, налоги и т.п."},
    {"code": "WITHDRAWAL", "label": "Изъятие средств из управления", "group": "Деньги", "kind": "cash",
     "movement_type": "WITHDRAWAL", "sign": -1, "hint": "Возврат денег из портфеля ЧДУ в фонд"},
    {"code": "COMMISSION", "label": "Комиссия", "group": "Деньги", "kind": "cash",
     "movement_type": "COMMISSION", "sign": -1, "hint": "Комиссии биржи, кастодиана, брокера"},
    {"code": "SECURITY_BUY", "label": "Покупка ценной бумаги", "group": "Ценные бумаги", "kind": "trade",
     "operation_type": "BUY", "sign": -1, "hint": "Бумага попадёт в портфель на дату расчётов, деньги спишутся"},
    {"code": "SECURITY_SELL", "label": "Продажа ценной бумаги", "group": "Ценные бумаги", "kind": "trade",
     "operation_type": "SELL", "sign": 1, "hint": "Бумага списывается по FIFO, деньги поступают"},
    {"code": "REDEMPTION", "label": "Погашение ценной бумаги", "group": "Ценные бумаги", "kind": "trade",
     "operation_type": "REDEMPTION", "sign": 1, "hint": "Бумага выбывает, номинал поступает деньгами"},
    {"code": "RECEIVABLE_CLOSE", "label": "Закрытие дебиторской задолженности", "group": "Дебиторка",
     "kind": "receivable_close", "sign": 1,
     "hint": "Погашение дебиторки деньгами. Если задолженность не выбрана — гасятся открытые по очереди (FIFO)"},
    {"code": "RECEIVABLE_OPEN", "label": "Возникновение дебиторской задолженности", "group": "Дебиторка",
     "kind": "receivable_open", "sign": 1, "hint": "Например, купон или погашение не поступили в срок"},
    {"code": "CORRECTION", "label": "Корректировка остатка денег (±)", "group": "Прочее", "kind": "cash",
     "movement_type": "CORRECTION", "sign": 0, "hint": "Укажите сумму со знаком: «−» уменьшает остаток"},
    {"code": "OTHER", "label": "Прочая операция с деньгами (±)", "group": "Прочее", "kind": "cash",
     "movement_type": "OTHER", "sign": 0, "hint": "Укажите сумму со знаком"},
]
_PURPOSE = {p["code"]: p for p in OPERATION_PURPOSES}


@router.get("/operation-purposes")
def operation_purposes(db: Session = Depends(get_db)):
    own = _fund_portfolio(db, required=False)
    return {"purposes": OPERATION_PURPOSES,
            "default_portfolio": ({"id": own.id, "name": own.name} if own is not None else None)}


def _fund_portfolio(db: Session, *, required: bool = True) -> Optional[CDU]:
    row = db.execute(select(CDU).where(
        CDU.portfolio_type == "NBRK_OWN", CDU.is_active.is_(True),
    ).order_by(CDU.id.asc())).scalars().first()
    if row is None and required:
        raise HTTPException(400, "Не выбран ЧДУ/портфель, а портфель «Собственные активы» не найден — выберите портфель")
    return row


def _open_receivables(db: Session, cdu_id: int, as_of: date) -> list[AccountReceivable]:
    rows = db.execute(select(AccountReceivable).where(
        AccountReceivable.cdu_id == cdu_id, AccountReceivable.is_active.is_(True),
        AccountReceivable.workflow_status.in_(EFFECTIVE_STATUSES),
        AccountReceivable.record_date <= as_of,
    ).order_by(AccountReceivable.due_date.asc().nulls_last(), AccountReceivable.record_date.asc(),
               AccountReceivable.id.asc())).scalars().all()
    return [r for r in rows if receivable_balance_as_of(db, r, as_of) > 0.005]


@router.get("/open-receivables")
def open_receivables(cdu_id: Optional[int] = None, as_of: Optional[date] = None, db: Session = Depends(get_db)):
    as_of = as_of or date.today()
    cdu = db.get(CDU, cdu_id) if cdu_id else _fund_portfolio(db, required=False)
    if cdu is None:
        return []
    return [{"id": r.id, "counterparty": r.counterparty, "description": r.description,
             "record_date": r.record_date.isoformat(), "due_date": r.due_date.isoformat() if r.due_date else None,
             "isin": r.isin, "balance_kzt": receivable_balance_as_of(db, r, as_of)}
            for r in _open_receivables(db, cdu.id, as_of)]


@router.post("/operations", dependencies=[Depends(require_any_permission(
    "manual.cash.manage", "manual.trades.manage", "manual.receivables.manage"))])
def create_operation(payload: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Create the ledger records for an operation of the given purpose (four-eyes)."""
    purpose = _PURPOSE.get(str(payload.get("purpose") or "").strip().upper())
    if purpose is None:
        raise HTTPException(400, "Выберите назначение операции")
    needed = {"trade": "manual.trades.manage", "receivable_close": "manual.receivables.manage",
              "receivable_open": "manual.receivables.manage"}.get(purpose["kind"], "manual.cash.manage")
    if not has_permission(user, needed, db):
        raise HTTPException(403, "Недостаточно прав для операции этого вида")
    op_date = _as_date(payload.get("operation_date"), "Дата операции")
    amount = _as_float(payload.get("amount"), "Сумма")
    quantity = _as_float(payload.get("quantity"), "quantity")
    price = _as_float(payload.get("price"), "price")
    currency = str(payload.get("currency") or "KZT").strip().upper()[:8] or "KZT"
    if payload.get("cdu_id") not in (None, "", 0, "0"):
        cdu = _cdu(db, payload.get("cdu_id"))
        portfolio_note = None
    else:
        cdu = _fund_portfolio(db)
        portfolio_note = f"ЧДУ не указан — операция учтена в портфеле «{cdu.short_name or cdu.name}»"
    text = str(payload.get("purpose_text") or "").strip() or purpose["label"]
    comment = str(payload.get("comment") or "").strip() or None
    isin = str(payload.get("isin") or "").strip().upper() or None
    account = payload.get("account")
    created: list[dict[str, Any]] = []

    if purpose["kind"] == "trade":
        from services.portfolio.reference import ReferenceBook
        if not isin:
            raise HTTPException(400, "Для операции с ценной бумагой укажите ISIN или тикер")
        refs = ReferenceBook(db)
        ref = refs.get(isin)
        nominal = float(ref.nominal) if ref is not None and ref.nominal else None
        face = _as_float(payload.get("face_value"), "face_value")
        if face is None and quantity is not None and nominal:
            face = quantity * nominal
        if amount is None and face is not None and price is not None:
            amount = face * price / 100.0
        if amount is None:
            raise HTTPException(400, "Укажите сумму операции (или номинал/количество и цену)")
        values = _trade_values(db, {
            "cdu_id": cdu.id, "operation_type": purpose["operation_type"],
            "trade_date": op_date, "value_date": payload.get("value_date") or op_date,
            "instrument_category": payload.get("instrument_category") or refs.category(isin, "GOV_BONDS"),
            "instrument_code": (ref.ticker_kase if ref is not None and ref.ticker_kase else isin),
            "isin": (ref.isin if ref is not None else isin), "description": text,
            "amount_kzt": amount, "currency": currency, "quantity": quantity, "face_value": face,
            "clean_price": price, "deal_id": payload.get("deal_id"), "notes": comment,
            "ytm": payload.get("ytm"), "change_reason": text,
        })
        row = Trade(**values, is_manual=True, is_active=True, workflow_status=PENDING,
                    created_by=user.username, updated_by=user.username)
        db.add(row); db.flush()
        write_audit(db, user=user.username, action="MANUAL_TRADE_CREATED", entity="Trade", entity_id=row.id,
                    details={**{k: str(v) for k, v in values.items()}, "purpose": purpose["code"]})
        created.append({"entity": "trades", "id": row.id})
    elif purpose["kind"] == "receivable_close":
        if amount is None or amount <= 0:
            raise HTTPException(400, "Укажите сумму погашения")
        targets: list[AccountReceivable]
        if payload.get("receivable_id"):
            parent = db.get(AccountReceivable, int(payload["receivable_id"]))
            if parent is None or not parent.is_active:
                raise HTTPException(404, "Дебиторская задолженность не найдена")
            targets = [parent]
        else:
            targets = _open_receivables(db, cdu.id, op_date)
            if not targets:
                raise HTTPException(400, "У портфеля нет открытой дебиторской задолженности на эту дату")
        left = amount
        for i, parent in enumerate(targets):
            balance = receivable_balance_as_of(db, parent, op_date)
            part = left if (i == len(targets) - 1 or payload.get("receivable_id")) else min(left, balance)
            if part <= 0.005:
                break
            tx = ReceivableTransaction(
                receivable_id=parent.id, operation_date=op_date, operation_type="REPAYMENT",
                amount=part, amount_kzt=_to_kzt(db, amount=part, currency=currency, operation_date=op_date),
                currency=currency, basis=text, comment=comment,
                workflow_status=PENDING, is_active=True, created_by=user.username,
            )
            db.add(tx); db.flush()
            write_audit(db, user=user.username, action="RECEIVABLE_TRANSACTION_CREATED",
                        entity="ReceivableTransaction", entity_id=tx.id,
                        details={"receivable_id": parent.id, "operation_type": "REPAYMENT", "amount": part,
                                 "purpose": purpose["code"]})
            created.append({"entity": "receivable-transactions", "id": tx.id, "receivable_id": parent.id})
            left -= part
    elif purpose["kind"] == "receivable_open":
        if amount is None or amount <= 0:
            raise HTTPException(400, "Укажите сумму дебиторской задолженности")
        values = _receivable_values(db, {
            "cdu_id": cdu.id, "record_date": op_date, "amount": amount, "currency": currency,
            "counterparty": payload.get("counterparty") or "не указан", "description": text,
            "isin": isin, "due_date": payload.get("due_date"), "notes": comment, "change_reason": text,
        })
        row = AccountReceivable(**values, status="OPEN", is_manual=True, is_active=True,
                                workflow_status=PENDING, created_by=user.username, updated_by=user.username)
        db.add(row); db.flush()
        write_audit(db, user=user.username, action="RECEIVABLE_CREATED", entity="AccountReceivable",
                    entity_id=row.id, details={k: str(v) for k, v in values.items()})
        created.append({"entity": "receivables", "id": row.id})
    else:
        if amount is None:
            raise HTTPException(400, "Укажите сумму")
        values = _cash_values(db, {
            "cdu_id": cdu.id, "operation_date": op_date, "amount": amount, "currency": currency,
            "movement_type": purpose["movement_type"], "basis": text, "account": account,
            "related_isin": isin, "comment": comment, "change_reason": text,
            "amount_kzt": payload.get("amount_kzt"),
        })
        row = CashMovement(**values, is_manual=True, is_active=True, workflow_status=PENDING,
                           created_by=user.username, updated_by=user.username)
        db.add(row); db.flush()
        write_audit(db, user=user.username, action="MANUAL_CASH_CREATED", entity="CashMovement",
                    entity_id=row.id, details={**{k: str(v) for k, v in values.items()}, "purpose": purpose["code"]})
        created.append({"entity": "cash-movements", "id": row.id})

    db.commit()
    message = (f"«{purpose['label']}» сохранена и ждёт согласования вторым пользователем. "
               "После согласования она войдёт в сводку и отчёт.")
    return {"ok": True, "purpose": purpose["code"], "cdu_id": cdu.id, "cdu_name": cdu.short_name or cdu.name,
            "created": created, "message": message, "portfolio_note": portfolio_note}


def _operation_date(row: Any) -> Optional[date]:
    if isinstance(row, Trade):
        return min(row.trade_date, row.value_date or row.trade_date)
    if isinstance(row, AccountReceivable):
        return row.record_date
    return getattr(row, "operation_date", None)


def _recalculate_after(db: Session, start: Optional[date]) -> list[str]:
    """Refresh the already calculated summaries affected by an approved change."""
    if start is None:
        return []
    from models.db_models import PortfolioSummary
    from services.calculator.portfolio_calculator import calculate_for_date
    later = set(db.execute(select(PortfolioSummary.summary_date).where(
        PortfolioSummary.summary_date > start,
    )).scalars())
    dates = [start] + sorted(later)[:30]
    done: list[str] = []
    for d in dates:
        try:
            calculate_for_date(db, d, recalculate=True)
            db.commit()
            done.append(d.isoformat())
        except Exception as exc:  # the approval itself is already saved
            db.rollback()
            from loguru import logger
            logger.warning(f"recalculation after approval failed for {d}: {exc!r}")
            break
    return done


ENTITY_MAP = {
    "trades": Trade,
    "cash-movements": CashMovement,
    "receivables": AccountReceivable,
    "receivable-transactions": ReceivableTransaction,
}


def _workflow_row(db: Session, entity: str, row_id: int):
    model = ENTITY_MAP.get(entity)
    if model is None:
        raise HTTPException(404, "Неизвестный тип операции")
    row = db.get(model, row_id)
    if row is None:
        raise HTTPException(404, "Операция не найдена")
    return row


def _audit_entity(entity: str) -> str:
    return ENTITY_MAP[entity].__name__


def _upsert_trade_cash(db: Session, trade: Trade) -> None:
    movement = db.execute(select(CashMovement).where(
        CashMovement.related_trade_id == trade.id,
    )).scalars().first()
    if trade.workflow_status not in EFFECTIVE_STATUSES or not trade.is_active or not trade.amount_kzt:
        if movement:
            movement.is_active = False; movement.workflow_status = trade.workflow_status
        return
    values = {
        "cdu_id": trade.cdu_id, "operation_date": trade.value_date,
        "amount": trade.amount_ccy if trade.amount_ccy is not None else trade.amount_kzt,
        "amount_kzt": trade.amount_kzt, "currency": trade.currency,
        "movement_type": trade.operation_type, "basis": f"По сделке {trade.deal_id or trade.id}",
        "related_isin": trade.isin or trade.instrument_code, "is_manual": False,
        "workflow_status": trade.workflow_status, "is_active": True,
        "approved_by": trade.approved_by, "approved_at": trade.approved_at,
        "created_by": trade.created_by,
    }
    if movement:
        for key, value in values.items(): setattr(movement, key, value)
    else:
        db.add(CashMovement(**values, related_trade_id=trade.id))


def _sync_receivable_transaction_cash(
    db: Session, row: ReceivableTransaction, parent: AccountReceivable,
) -> None:
    movement = db.execute(select(CashMovement).where(
        CashMovement.related_receivable_transaction_id == row.id,
    )).scalars().first()
    if row.operation_type != "REPAYMENT" or row.workflow_status not in EFFECTIVE_STATUSES or not row.is_active:
        if movement:
            movement.is_active = False
            movement.workflow_status = row.workflow_status
        return
    values = {
        "cdu_id": parent.cdu_id, "operation_date": row.operation_date,
        "amount": abs(row.amount), "amount_kzt": abs(row.amount_kzt or row.amount),
        "currency": row.currency, "movement_type": "RECEIVABLE_REPAYMENT",
        "basis": row.basis, "comment": row.comment, "is_manual": False,
        "workflow_status": APPROVED, "is_active": True,
        "created_by": row.created_by, "approved_by": row.approved_by,
        "approved_at": row.approved_at,
    }
    if movement:
        for key, value in values.items():
            setattr(movement, key, value)
    else:
        db.add(CashMovement(
            **values, related_receivable_transaction_id=row.id,
        ))


@router.post("/{entity}/{row_id}/approve", dependencies=[Depends(require_permission("manual.operations.approve"))])
def approve(entity: str, row_id: int, payload: dict[str, Any] | None = None,
            db: Session = Depends(get_db), user: User = Depends(require_user)):
    row = _workflow_row(db, entity, row_id)
    if row.workflow_status not in {PENDING, PENDING_CANCELLATION}:
        raise HTTPException(409, "Операция не ожидает согласования")
    if user.username in {row.created_by, getattr(row, "updated_by", None)}:
        raise HTTPException(409, "Создатель или редактор операции не может сам её согласовать")
    now = datetime.utcnow()
    previous = row.workflow_status
    row.workflow_status = CANCELLED if previous == PENDING_CANCELLATION else APPROVED
    row.is_active = row.workflow_status == APPROVED
    row.approved_by = user.username; row.approved_at = now
    row.decision_comment = (payload or {}).get("comment")
    row.rejected_by = None; row.rejected_at = None
    if isinstance(row, Trade):
        _upsert_trade_cash(db, row)
    elif isinstance(row, ReceivableTransaction):
        parent = db.get(AccountReceivable, row.receivable_id)
        if parent:
            db.flush()   # the balance query must see the new status of this transaction
            _sync_receivable_current(db, parent)
            _sync_receivable_transaction_cash(db, row, parent)
    write_audit(db, user=user.username, action="MANUAL_OPERATION_APPROVED",
                entity=_audit_entity(entity), entity_id=row.id,
                details={"previous_status": previous, "status": row.workflow_status,
                         "comment": row.decision_comment})
    db.commit()
    if isinstance(row, Trade):
        sync_holdings(db, cdu_id=row.cdu_id, actor=user.username); db.commit()
    recalculated = _recalculate_after(db, _operation_date(row))
    return {"ok": True, "status": row.workflow_status, "recalculated_dates": recalculated}


@router.post("/{entity}/{row_id}/reject", dependencies=[Depends(require_permission("manual.operations.approve"))])
def reject(entity: str, row_id: int, payload: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(require_user)):
    row = _workflow_row(db, entity, row_id)
    if row.workflow_status not in {PENDING, PENDING_CANCELLATION}:
        raise HTTPException(409, "Операция не ожидает согласования")
    if user.username in {row.created_by, getattr(row, "updated_by", None)}:
        raise HTTPException(409, "Создатель или редактор операции не может сам её отклонить")
    comment = _required_text(payload.get("comment"), "Комментарий")
    previous = row.workflow_status
    row.workflow_status = APPROVED if previous == PENDING_CANCELLATION else REJECTED
    row.is_active = row.workflow_status == APPROVED
    row.rejected_by = user.username; row.rejected_at = datetime.utcnow(); row.decision_comment = comment
    if isinstance(row, Trade):
        _upsert_trade_cash(db, row)
    elif isinstance(row, ReceivableTransaction):
        parent = db.get(AccountReceivable, row.receivable_id)
        if parent:
            db.flush()   # the balance query must see the new status of this transaction
            _sync_receivable_current(db, parent)
            _sync_receivable_transaction_cash(db, row, parent)
    write_audit(db, user=user.username, action="MANUAL_OPERATION_REJECTED",
                entity=_audit_entity(entity), entity_id=row.id,
                details={"previous_status": previous, "status": row.workflow_status, "comment": comment})
    db.commit()
    return {"ok": True, "status": row.workflow_status}


@router.delete("/{entity}/{row_id}", dependencies=[Depends(require_permission("manual.operations.cancel"))])
def cancel(entity: str, row_id: int, payload: dict[str, Any] | None = None,
           db: Session = Depends(get_db), user: User = Depends(require_user)):
    row = _workflow_row(db, entity, row_id)
    if row.workflow_status in {CANCELLED, PENDING_CANCELLATION}:
        raise HTTPException(409, "Операция уже аннулирована или ожидает аннулирования")
    reason = _required_text((payload or {}).get("comment"), "Причина аннулирования")
    if row.workflow_status == APPROVED:
        # Maker-checker: the cancellation is itself a change of the books and
        # takes effect only after a second person approves it.  Until then
        # the operation keeps participating in calculations.
        row.workflow_status = PENDING_CANCELLATION
        row.is_active = True
        if hasattr(row, "updated_by"): row.updated_by = user.username
    else:
        row.workflow_status = CANCELLED; row.is_active = False
    row.decision_comment = reason
    if isinstance(row, Trade):
        _upsert_trade_cash(db, row)
    elif isinstance(row, ReceivableTransaction):
        parent = db.get(AccountReceivable, row.receivable_id)
        if parent:
            db.flush()   # the balance query must see the new status of this transaction
            _sync_receivable_current(db, parent)
            _sync_receivable_transaction_cash(db, row, parent)
    write_audit(db, user=user.username, action="MANUAL_OPERATION_CANCEL_REQUESTED",
                entity=_audit_entity(entity), entity_id=row.id,
                details={"status": row.workflow_status, "reason": reason})
    db.commit()
    return {"ok": True, "status": row.workflow_status}
