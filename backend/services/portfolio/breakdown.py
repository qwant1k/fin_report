"""Full drill-down («расшифровка») of a dashboard category row.

For every category of the summary (Cash, ГЦБ, REPO, …) returns the items that
make up the amount, with dates and the origin of each figure — which document
(Risk Report, Trade Report, НБ РК file, statement) or manual operation it came
from, which price was applied and where the price came from.  The figures are
produced by the same code as the summary itself (portfolio engine and the cash
/ receivable helpers of the calculator), so the items always add up to the row.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.db_models import (
    CDU, AccountReceivable, CashBalance, CashMovement, CashSnapshot, FXRate,
    InstrumentReference, PortfolioPosition, ReceivableTransaction, SourceDocument, Trade,
)
from services.calculator.constants import CATEGORY_LABELS
from services.workflow import CANCELLED, EFFECTIVE_STATUSES, REJECTED

DOC_TYPE_LABEL = {
    "RISK_REPORT_XLSM": "Risk Report",
    "TRADE_REPORT": "Trade Report",
    "HOLDINGS": "Holdings (отчёт ЧДУ)",
    "RECONCILIATION": "Акт сверки",
    "CERTIFICATE": "Биржевое свидетельство",
    "STATEMENT_PDF": "Выписка по счёту",
    "NBRK_DAILY": "НБ РК",
    "OTHER": "Документ",
}

PRICE_SOURCE_LABEL = {
    "risk_report": "Risk Report на дату среза",
    "risk_report_carry": "цена из Risk Report (нет свежей цены KASE)",
    "market": "KASE — рыночная цена",
    "market_stale": "KASE — рыночная цена прошлой даты",
    "risk_parameters": "KASE — цена по риск-параметрам",
    "risk_parameters_stale": "KASE — риск-параметры прошлой даты",
    "purchase": "цена приобретения",
    "amortized": "амортизация дисконта по доходности покупки",
    "par": "номинал (нет цены)",
    "par_matured": "номинал — срок погашения наступил",
}

ORIGIN_LABEL = {
    "risk_report": "Risk Report (срез)",
    "trade": "Trade Report / импорт",
    "manual": "Ручная операция",
}

MOVEMENT_LABEL = {
    "RECEIPT": "Поступление",
    "INITIAL_BALANCE": "Входящий остаток",
    "OPENING_BALANCE": "Входящий остаток",
    "CONTRIBUTION": "Взнос в портфель",
    "COUPON": "Купон",
    "REDEMPTION": "Погашение",
    "PAYMENT": "Списание",
    "WITHDRAWAL": "Изъятие из портфеля",
    "COMMISSION": "Комиссия",
    "CORRECTION": "Корректировка",
    "OTHER": "Прочее",
    "SECURITY_PURCHASE": "Покупка ЦБ",
    "SECURITY_SALE": "Продажа ЦБ",
    "REPO_OPEN": "Открытие РЕПО",
    "REPO_CLOSE": "Закрытие РЕПО",
    "DEPOSIT_OPEN": "Размещение депозита",
    "DEPOSIT_CLOSE": "Возврат депозита",
    "FX_BUY": "Покупка валюты",
    "FX_SELL": "Продажа валюты",
    "RECEIVABLE_REPAYMENT": "Погашение дебиторки",
    # cash legs of manual trades carry the trade operation type
    "BUY": "Покупка ЦБ",
    "SELL": "Продажа ЦБ",
    "CASH_TOPUP": "Пополнение",
    "CASH_WITHDRAW": "Вывод средств",
}

WORKFLOW_LABEL = {
    "APPROVED": "согласовано",
    "PENDING_APPROVAL": "ждёт согласования",
    "PENDING_CANCELLATION": "ждёт отмены",
    "REJECTED": "отклонено",
    "CANCELLED": "отменено",
}

BOND_CATEGORIES = ("GOV_BONDS", "MFO_BONDS", "AGENCY_BONDS", "FOREIGN_BONDS", "OTHER")


def _d(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


class _Sources:
    """Lazy cache of source documents and trades for labelling."""

    def __init__(self, db: Session):
        self.db = db
        self._docs: Dict[int, Optional[SourceDocument]] = {}
        self._trades: Dict[int, Optional[Trade]] = {}

    def doc(self, doc_id: Optional[int]) -> Optional[SourceDocument]:
        if not doc_id:
            return None
        if doc_id not in self._docs:
            self._docs[doc_id] = self.db.get(SourceDocument, doc_id)
        return self._docs[doc_id]

    def trade(self, trade_id: Optional[int]) -> Optional[Trade]:
        if not trade_id:
            return None
        if trade_id not in self._trades:
            self._trades[trade_id] = self.db.get(Trade, trade_id)
        return self._trades[trade_id]

    def describe(self, *, doc_id: Optional[int] = None, trade_id: Optional[int] = None,
                 origin: Optional[str] = None, snapshot_date: Optional[date] = None,
                 is_manual: bool = False, author: Optional[str] = None,
                 status: Optional[str] = None) -> dict:
        trade = self.trade(trade_id)
        if trade is not None:
            doc_id = doc_id or trade.source_doc_id
            is_manual = is_manual or bool(trade.is_manual)
            author = author or trade.created_by
            status = status or trade.workflow_status
        doc = self.doc(doc_id)
        if is_manual or origin == "manual":
            kind = "manual"
            label = "Ручная операция"
            if trade is not None:
                label += f" №{trade.id}"
            if author:
                label += f" ({author})"
        elif doc is not None:
            kind = (doc.doc_type or "OTHER").lower()
            label = DOC_TYPE_LABEL.get(doc.doc_type or "OTHER", doc.doc_type or "Документ")
            if origin == "risk_report" and snapshot_date:
                label += f" на {snapshot_date:%d.%m.%Y}"
        elif origin == "risk_report":
            kind, label = "risk_report_xlsm", "Risk Report" + (f" на {snapshot_date:%d.%m.%Y}" if snapshot_date else "")
        elif trade is not None and trade.is_synthetic:
            kind = "auto"
            label = {"COUPON": "Автоматически: купон по графику",
                     "REDEMPTION": "Автоматически: погашение"}.get(trade.operation_type, "Автоматически")
        elif trade is not None:
            kind, label = "trade", "Сделка из Trade Report"
        else:
            kind, label = "unknown", "Источник не указан"
        return {
            "kind": kind,
            "label": label,
            "doc_id": doc.id if doc is not None else None,
            "file_name": doc.file_name if doc is not None else None,
            "doc_date": _d(doc.doc_date) if doc is not None else None,
            "uploaded_at": doc.uploaded_at.isoformat() if doc is not None and doc.uploaded_at else None,
            "trade_id": trade.id if trade is not None else None,
            "deal_id": trade.deal_id if trade is not None else None,
            "status": status,
            "status_label": WORKFLOW_LABEL.get(status or "", None),
        }


def _ref_names(db: Session, idents: Iterable[str]) -> Dict[str, InstrumentReference]:
    keys = sorted({(i or "").upper() for i in idents if i})
    if not keys:
        return {}
    out: Dict[str, InstrumentReference] = {}
    for ref in db.execute(select(InstrumentReference).where(
        (InstrumentReference.isin.in_(keys)) | (InstrumentReference.ticker_kase.in_(keys)),
    )).scalars():
        if ref.isin:
            out[ref.isin.upper()] = ref
        if ref.ticker_kase:
            out[ref.ticker_kase.upper()] = ref
    return out


def _summary_value(db: Session, cdu_id: int, category: str, as_of: date) -> Optional[float]:
    row = db.execute(select(PortfolioPosition).where(
        PortfolioPosition.cdu_id == cdu_id,
        PortfolioPosition.position_date == as_of,
        PortfolioPosition.instrument_category == category,
        PortfolioPosition.instrument_code.is_(None),
    )).scalars().first()
    return float(row.market_value_current) if row is not None else None


def _pending_trades(db: Session, src: _Sources, cdu_id: int, as_of: date,
                    categories: Iterable[str], operation_types: Optional[Iterable[str]] = None) -> List[dict]:
    q = select(Trade).where(
        Trade.cdu_id == cdu_id, Trade.is_manual.is_(True), Trade.is_active.is_(True),
        Trade.workflow_status.not_in(EFFECTIVE_STATUSES + (REJECTED, CANCELLED)),
        Trade.trade_date <= as_of,
        Trade.instrument_category.in_(list(categories)),
    )
    if operation_types:
        q = q.where(Trade.operation_type.in_(list(operation_types)))
    out = []
    for t in db.execute(q.order_by(Trade.trade_date.asc())).scalars():
        out.append({
            "id": t.id, "date": _d(t.trade_date), "value_date": _d(t.value_date),
            "operation_type": t.operation_type, "code": t.instrument_code or t.isin,
            "amount_kzt": t.amount_kzt, "face_value": t.face_value, "quantity": t.quantity,
            "comment": t.notes or t.description,
            "source": src.describe(trade_id=t.id, is_manual=True),
        })
    return out


# ───────────────────────────── securities ─────────────────────────────

def _bond_items(db: Session, src: _Sources, state, category: str) -> List[dict]:
    lots = [b for b in state.bonds if b.category == category and abs(b.total_value_kzt) > 1e-9]
    refs = _ref_names(db, [b.isin for b in lots] + [b.ticker for b in lots if b.ticker])
    items = []
    for b in lots:
        ref = refs.get((b.isin or "").upper()) or refs.get((b.ticker or "").upper())
        items.append({
            "code": b.ticker or b.isin,
            # ISIN from the Справочник ЦБ (the lot may carry only a ticker)
            "isin": (ref.isin if ref is not None and ref.isin else b.isin),
            "name": (ref.instrument_name if ref is not None else None),
            "issuer": (ref.issuer if ref is not None else None),
            "currency": b.currency,
            "quantity": (b.face_value / b.unit_nominal) if b.unit_nominal else None,
            "unit_nominal": b.unit_nominal,
            "face_value": b.face_value,
            "purchase_price": b.purchase_price,
            "price": b.price,
            "price_source": b.price_source,
            "price_source_label": PRICE_SOURCE_LABEL.get(b.price_source or "", b.price_source),
            "price_date": _d(b.price_date),
            "accrued": b.accrued,
            "clean_value": b.clean_value,
            "total_value": b.total_value,
            "fx_rate": b.fx_rate,
            "value_kzt": b.total_value_kzt,
            "ytm": b.ytm,
            "duration": b.duration,
            "trade_date": _d(b.trade_date),
            "settlement_date": _d(b.settlement_date),
            "maturity_date": _d(b.maturity_date),
            "coupon_rate_pct": (ref.coupon_rate_pct if ref is not None else None),
            "origin": b.origin,
            "origin_label": ORIGIN_LABEL.get(b.origin, b.origin),
            "source": src.describe(doc_id=b.source_doc_id, trade_id=b.trade_id, origin=b.origin,
                                   snapshot_date=b.snapshot_date),
            "warnings": list(b.warnings),
        })
    items.sort(key=lambda x: -abs(x["value_kzt"]))
    return items


def _money_market_items(src: _Sources, items_in, as_of: date, base_date: Optional[date],
                        db: Optional[Session] = None) -> List[dict]:
    items = []
    items_in = [m for m in items_in if abs(m.market_value) >= 1e-9]
    refs = _ref_names(db, [m.collateral for m in items_in if m.collateral]) if db is not None else {}
    for m in items_in:
        ref = refs.get((m.collateral or "").upper())
        days_total = (m.close_date - m.open_date).days if m.close_date and m.open_date else None
        days_passed = (as_of - m.open_date).days if m.open_date else None
        items.append({
            "code": m.identifier or m.deal_id,
            "deal_id": m.deal_id,
            "collateral": m.collateral,
            "collateral_ticker": (ref.ticker_kase if ref is not None and ref.ticker_kase else m.collateral),
            "isin": (ref.isin if ref is not None else (
                m.collateral if m.collateral and len(m.collateral) == 12 and m.collateral[:2].isalpha() else None)),
            "quantity": m.quantity,
            "open_date": _d(m.open_date),
            "close_date": _d(m.close_date),
            "days_total": days_total,
            "days_passed": days_passed,
            "open_amount": m.open_amount,
            "close_amount": m.close_amount,
            # RR «Repo» sheet often has no «Interest rate»: the rate implied by the
            # open / close amounts of the deal is shown instead
            "rate": m.rate if m.rate is not None else (
                (m.close_amount / m.open_amount - 1.0) * (m.base or 366) / days_total
                if m.close_amount and m.open_amount and days_total else None),
            "base": m.base,
            "accrued": m.accrued,
            "value_kzt": m.market_value,
            "ytm": m.ytm,
            "duration": m.duration,
            "origin": m.origin,
            "origin_label": ORIGIN_LABEL.get(m.origin, m.origin),
            "source": src.describe(doc_id=m.source_doc_id, trade_id=m.trade_id, origin=m.origin,
                                   snapshot_date=base_date if m.origin == "risk_report" else None),
            "warnings": list(m.warnings),
        })
    items.sort(key=lambda x: (x["close_date"] or "9999", -abs(x["value_kzt"])))
    return items


# ───────────────────────────── cash ─────────────────────────────

def _fx(db: Session, currency: str, on: date) -> float:
    fx = db.execute(select(FXRate).where(
        FXRate.currency == currency, FXRate.rate_date <= on,
    ).order_by(FXRate.rate_date.desc())).scalars().first()
    return float(fx.rate) if fx else 1.0


def _cash_breakdown(db: Session, src: _Sources, cdu_id: int, as_of: date, state) -> dict:
    from services.calculator.portfolio_calculator import (
        _latest_cash_snapshot_total, cash_movement_lines, implied_cash_lines,
    )

    snap_date, snap_total = _latest_cash_snapshot_total(db, cdu_id, as_of, state.base_date)
    legacy = db.execute(select(CashBalance).where(
        CashBalance.cdu_id == cdu_id, CashBalance.balance_date <= as_of,
    ).order_by(CashBalance.balance_date.desc())).scalars().first()

    opening: dict = {"date": None, "total": 0.0, "lines": [], "label": "Нет входящего остатка"}
    base_date: Optional[date] = None
    if snap_total is not None and (legacy is None or legacy.balance_date <= snap_date):
        base_date = snap_date
        books = CashSnapshot.source.is_(None) | (CashSnapshot.source != "holdings_report_xlsx")
        lines = []
        for row in db.execute(select(CashSnapshot).where(
            CashSnapshot.cdu_id == cdu_id, CashSnapshot.snapshot_date == snap_date, books,
        )).scalars():
            ccy = (row.currency or "KZT").upper()
            kzt = row.amount_kzt if row.amount_kzt is not None else (
                (row.amount or 0.0) * (1.0 if ccy == "KZT" else _fx(db, ccy, snap_date)))
            lines.append({
                "currency": ccy, "amount": row.amount, "amount_kzt": kzt,
                "account": row.portfolio_code,
                "source": src.describe(doc_id=row.source_doc_id,
                                       origin="risk_report" if row.source == "rr_import" else None,
                                       snapshot_date=snap_date),
            })
        opening = {"date": _d(snap_date), "total": float(snap_total), "lines": lines,
                   "label": f"Остаток на {snap_date:%d.%m.%Y}"}
    elif legacy is not None:
        base_date = legacy.balance_date
        opening = {"date": _d(legacy.balance_date), "total": float(legacy.amount or 0.0),
                   "lines": [{"currency": "KZT", "amount": legacy.amount, "amount_kzt": legacy.amount,
                              "account": None, "source": {"kind": "legacy", "label": legacy.note or "Остаток (ручной ввод)"}}],
                   "label": f"Остаток на {legacy.balance_date:%d.%m.%Y}"}

    movements = []
    for row, value in cash_movement_lines(db, cdu_id, as_of, base_date):
        movements.append(_movement_out(src, row, value, counted=True))
    implied = []
    for flow in implied_cash_lines(db, cdu_id, state.implied_cash, base_date):
        implied.append({
            "date": _d(flow["date"]), "kind": flow["kind"],
            "label": "Закрытие РЕПО" if flow["kind"] == "REPO_CLOSE" else "Возврат депозита",
            "reference": flow["reference"], "amount_kzt": flow["amount"], "counted": flow["counted"],
            "note": ("учтено по данным Risk Report — подтверждающее движение денег не загружено"
                     if flow["counted"] else "уже учтено движением денег из документа"),
        })

    pending = []
    for row in db.execute(select(CashMovement).where(
        CashMovement.cdu_id == cdu_id, CashMovement.is_active.is_(True),
        CashMovement.operation_date <= as_of,
        CashMovement.workflow_status.not_in(EFFECTIVE_STATUSES + (REJECTED, CANCELLED)),
    ).order_by(CashMovement.operation_date.asc())).scalars():
        pending.append(_movement_out(src, row, float(row.amount_kzt if row.amount_kzt is not None else row.amount or 0.0),
                                     counted=False))

    total = opening["total"] + sum(m["amount_kzt"] for m in movements) + sum(
        i["amount_kzt"] for i in implied if i["counted"])
    return {"opening": opening, "movements": movements, "implied": implied,
            "pending": pending, "total": total, "base_date": _d(base_date)}


def _movement_out(src: _Sources, row: CashMovement, value: float, *, counted: bool) -> dict:
    return {
        "id": row.id,
        "date": _d(row.operation_date),
        "movement_type": row.movement_type,
        "type_label": MOVEMENT_LABEL.get(row.movement_type, row.movement_type),
        "purpose": row.basis,
        "comment": row.comment,
        "account": row.account,
        "amount": row.amount,
        "currency": row.currency,
        "amount_kzt": value,
        "related_isin": row.related_isin,
        "is_manual": bool(row.is_manual),
        "counted": counted,
        "source": src.describe(doc_id=row.source_doc_id, trade_id=row.related_trade_id,
                               is_manual=bool(row.is_manual), author=row.created_by,
                               status=row.workflow_status),
    }


# ───────────────────────────── receivables ─────────────────────────────

def _receivables(db: Session, src: _Sources, cdu_id: int, as_of: date,
                 base_date: Optional[date] = None) -> dict:
    from services.calculator.portfolio_calculator import _receivable_balance_as_of, auto_ar_inside_slice

    items, pending = [], []
    for ar in db.execute(select(AccountReceivable).where(
        AccountReceivable.cdu_id == cdu_id, AccountReceivable.is_active.is_(True),
        AccountReceivable.record_date <= as_of,
    ).order_by(AccountReceivable.record_date.asc())).scalars():
        effective = ar.workflow_status in EFFECTIVE_STATUSES
        if not effective and ar.workflow_status in (REJECTED, CANCELLED):
            continue
        if auto_ar_inside_slice(ar, base_date):
            continue
        txs = []
        last_tx: Optional[date] = None
        for tx in db.execute(select(ReceivableTransaction).where(
            ReceivableTransaction.receivable_id == ar.id, ReceivableTransaction.is_active.is_(True),
            ReceivableTransaction.operation_date <= as_of,
        ).order_by(ReceivableTransaction.operation_date.asc())).scalars():
            if tx.workflow_status in (REJECTED, CANCELLED):
                continue
            value = float(tx.amount_kzt if tx.amount_kzt is not None else tx.amount or 0.0)
            txs.append({
                "id": tx.id, "date": _d(tx.operation_date), "operation_type": tx.operation_type,
                "type_label": {"REPAYMENT": "Погашение", "ADJUSTMENT": "Корректировка",
                               "WRITE_OFF": "Списание"}.get(tx.operation_type, tx.operation_type),
                "amount_kzt": value if tx.operation_type == "ADJUSTMENT" else -abs(value),
                "basis": tx.basis, "counted": tx.workflow_status in EFFECTIVE_STATUSES,
                "status_label": WORKFLOW_LABEL.get(tx.workflow_status, tx.workflow_status),
            })
            if tx.workflow_status in EFFECTIVE_STATUSES:
                last_tx = max(last_tx or tx.operation_date, tx.operation_date)
        initial = float(ar.amount_kzt if ar.amount_kzt is not None else ar.amount or 0.0)
        balance = _receivable_balance_as_of(db, ar, as_of) if effective else initial
        item = {
            "id": ar.id, "record_date": _d(ar.record_date), "due_date": _d(ar.due_date),
            "counterparty": ar.counterparty, "description": ar.description, "isin": ar.isin,
            "currency": ar.currency, "initial_kzt": initial, "balance_kzt": balance,
            "status": ar.status, "transactions": txs, "counted": effective,
            "source": src.describe(doc_id=ar.source_doc_id, trade_id=ar.related_trade_id,
                                   is_manual=bool(ar.is_manual), author=ar.created_by,
                                   status=ar.workflow_status),
        }
        if not effective:
            pending.append(item)
        elif balance > 0.005 or (last_tx and last_tx >= as_of - timedelta(days=31)):
            items.append(item)
    total = sum(i["balance_kzt"] for i in items)
    return {"items": items, "pending": pending, "total": total}


# ───────────────────────────── entry point ─────────────────────────────

def category_breakdown(db: Session, cdu_id: int, category: str, as_of: date) -> dict:
    from services.portfolio.engine import build_portfolio

    category = (category or "").upper()
    cdu = db.get(CDU, cdu_id)
    src = _Sources(db)
    state = build_portfolio(db, cdu_id, as_of)
    out: dict = {
        "cdu_id": cdu_id,
        "cdu_name": cdu.name if cdu is not None else None,
        "category": category,
        "label": CATEGORY_LABELS.get(category, category),
        "as_of": as_of.isoformat(),
        "base_date": _d(state.base_date),
        "summary_value": _summary_value(db, cdu_id, category, as_of),
        "kind": "bonds",
        "items": [],
        "pending": [],
        "notes": [],
    }
    if category == "CASH":
        cash = _cash_breakdown(db, src, cdu_id, as_of, state)
        out.update(kind="cash", cash=cash, total=cash["total"], pending=cash["pending"])
        out["notes"].append(
            "Остаток = входящий остаток из последнего среза + согласованные движения после него "
            "(+ закрытия РЕПО/депозитов из среза, если подтверждающее движение денег ещё не загружено)."
        )
        if not cash["opening"]["lines"]:
            out["notes"].append(
                "Входящий остаток денег не загружен — загрузите Risk Report или внесите его через "
                "«Новая операция → Входящий остаток денег»."
            )
    elif category == "RECEIVABLES":
        rec = _receivables(db, src, cdu_id, as_of, state.base_date)
        out.update(kind="receivables", items=rec["items"], pending=rec["pending"], total=rec["total"])
        out["notes"].append("Остаток = первоначальная сумма − согласованные погашения ± корректировки на дату.")
    elif category in ("REVERSE_REPO", "DEPOSIT"):
        items = _money_market_items(src, state.repos if category == "REVERSE_REPO" else state.deposits,
                                    as_of, state.base_date, db)
        out.update(kind="money_market", items=items, total=sum(i["value_kzt"] for i in items))
        out["pending"] = _pending_trades(db, src, cdu_id, as_of, [category])
        out["notes"].append(
            "Стоимость = сумма открытия + вознаграждение, начисленное линейно на дату "
            + ("(база 366)." if category == "REVERSE_REPO" else "(база 360/365 по сделке).")
        )
    else:
        items = _bond_items(db, src, state, category)
        out.update(kind="bonds", items=items, total=sum(i["value_kzt"] for i in items))
        out["pending"] = _pending_trades(db, src, cdu_id, as_of, [category], ("BUY", "SELL", "REDEMPTION"))
        out["notes"].append(
            "Стоимость = номинал × чистая цена % + НКД (по графику купонов), × курс для валютных бумаг."
        )
    if state.base_date:
        out["notes"].append(f"База расчёта — срез Risk Report на {state.base_date:%d.%m.%Y}, "
                            "далее операции из Trade Report, выписок и ручных операций.")
    else:
        out["notes"].append("Risk Report для ЧДУ не загружен — позиции собраны только из сделок и операций.")
    sv = out["summary_value"]
    if sv is not None and abs(sv - out["total"]) > max(1.0, abs(sv) * 1e-6):
        out["notes"].append(
            f"Сводка на дату рассчитана раньше ({sv:,.2f}); после последних изменений сумма — "
            f"{out['total']:,.2f}. Нажмите «Пересчитать»."
        )
    return out
