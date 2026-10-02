"""CRUD on reference data: ЧДУ, лимиты, инструменты, правила, формулы."""
from __future__ import annotations

import json
from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import require_permission, require_user
from database import get_db
from models.db_models import (
    AccountReceivable,
    CashBalance,
    CDU as CDUModel,
    CDULimit as CDULimitModel,
    FormulaDefinition,
    Instrument,
    InstrumentCategoryRule,
    User,
)
from services.audit import write_audit
from models.schemas import (
    CDU,
    CDUCreate,
    CDULimit,
    CDULimitCreate,
    CDUUpdate,
    FormulaDefinitionOut,
    FormulaDefinitionUpsert,
    Instrument as InstrumentSchema,
)

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(require_user)],
)


# ─────────── ЧДУ ───────────
@router.get("/cdus", response_model=List[CDU])
def list_cdus(db: Session = Depends(get_db)):
    return db.query(CDUModel).order_by(CDUModel.name).all()


@router.post("/cdus", response_model=CDU)
def create_cdu(payload: CDUCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.edit"))):
    if db.query(CDUModel).filter_by(name=payload.name).first():
        raise HTTPException(409, "ЧДУ с таким именем уже существует")
    obj = CDUModel(**payload.model_dump())
    db.add(obj)
    db.flush()
    write_audit(db, user=user.username, action="CDU_CREATED", entity="CDU", entity_id=obj.id,
                details=payload.model_dump())
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/cdus/{cdu_id}", response_model=CDU)
def update_cdu(cdu_id: int, payload: CDUUpdate, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.edit"))):
    obj = db.get(CDUModel, cdu_id)
    if not obj:
        raise HTTPException(404, "ЧДУ не найден")
    changes = payload.model_dump(exclude_unset=True)
    before = {k: getattr(obj, k) for k in changes}
    for k, v in changes.items():
        setattr(obj, k, v)
    write_audit(db, user=user.username, action="CDU_UPDATED", entity="CDU", entity_id=obj.id,
                details={"before": before, "after": changes})
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/cdus/{cdu_id}")
def delete_cdu(cdu_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.edit"))):
    obj = db.get(CDUModel, cdu_id)
    if not obj:
        raise HTTPException(404, "ЧДУ не найден")
    from models.db_models import BondLot, CashSnapshot, PortfolioSummary, Trade
    has_history = any(
        db.query(model).filter(model.cdu_id == cdu_id).first() is not None
        for model in (Trade, BondLot, CashSnapshot, PortfolioSummary)
    )
    if has_history:
        # SQLite does not enforce foreign keys here: a hard delete would leave
        # orphaned trades/lots and break historical reports.  Deactivate.
        obj.is_active = False
        write_audit(db, user=user.username, action="CDU_DEACTIVATED", entity="CDU", entity_id=obj.id,
                    details={"name": obj.name, "reason": "has history"})
        db.commit()
        return {"ok": True, "deactivated": True}
    write_audit(db, user=user.username, action="CDU_DELETED", entity="CDU", entity_id=obj.id,
                details={"name": obj.name})
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ─────────── Лимиты ───────────
@router.get("/limits", response_model=List[CDULimit])
def list_limits(cdu_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(CDULimitModel)
    if cdu_id:
        q = q.filter_by(cdu_id=cdu_id)
    return q.order_by(CDULimitModel.cdu_id, CDULimitModel.instrument_category).all()


@router.post("/limits", response_model=CDULimit)
def create_limit(payload: CDULimitCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.edit"))):
    obj = CDULimitModel(**payload.model_dump())
    db.add(obj)
    db.flush()
    write_audit(db, user=user.username, action="LIMIT_CREATED", entity="CDULimit", entity_id=obj.id,
                details=payload.model_dump())
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/limits/{limit_id}", response_model=CDULimit)
def update_limit(limit_id: int, payload: CDULimitCreate, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("settings.edit"))):
    obj = db.get(CDULimitModel, limit_id)
    if not obj:
        raise HTTPException(404, "Лимит не найден")
    before = {k: getattr(obj, k) for k in payload.model_dump()}
    for k, v in payload.model_dump().items():
        setattr(obj, k, v)
    write_audit(db, user=user.username, action="LIMIT_UPDATED", entity="CDULimit", entity_id=obj.id,
                details={"before": before, "after": payload.model_dump()})
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/limits/{limit_id}")
def delete_limit(limit_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.edit"))):
    obj = db.get(CDULimitModel, limit_id)
    if not obj:
        raise HTTPException(404, "Лимит не найден")
    write_audit(db, user=user.username, action="LIMIT_DELETED", entity="CDULimit", entity_id=obj.id,
                details={"cdu_id": obj.cdu_id, "category": obj.instrument_category,
                         "min": obj.min_limit_pct, "max": obj.max_limit_pct})
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ─────────── Инструменты ───────────
@router.get("/instruments", response_model=List[InstrumentSchema])
def list_instruments(db: Session = Depends(get_db)):
    return db.query(Instrument).order_by(Instrument.code).all()


@router.post("/instruments", response_model=InstrumentSchema)
def create_instrument(payload: InstrumentSchema, db: Session = Depends(get_db),
                      user: User = Depends(require_permission("settings.edit"))):
    obj = Instrument(**payload.model_dump(exclude={"id"}))
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/instruments/{ins_id}", response_model=InstrumentSchema)
def update_instrument(ins_id: int, payload: InstrumentSchema, db: Session = Depends(get_db),
                      user: User = Depends(require_permission("settings.edit"))):
    obj = db.get(Instrument, ins_id)
    if not obj:
        raise HTTPException(404, "Инструмент не найден")
    for k, v in payload.model_dump(exclude={"id"}).items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/instruments/{ins_id}")
def delete_instrument(ins_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.edit"))):
    obj = db.get(Instrument, ins_id)
    if not obj:
        raise HTTPException(404, "Инструмент не найден")
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ─────────── Правила категоризации ───────────
@router.get("/rules")
def list_rules(db: Session = Depends(get_db)):
    return db.query(InstrumentCategoryRule).order_by(InstrumentCategoryRule.priority).all()


@router.post("/rules")
def create_rule(payload: dict, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.edit"))):
    obj = InstrumentCategoryRule(**payload)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, payload: dict, db: Session = Depends(get_db),
                user: User = Depends(require_permission("settings.edit"))):
    obj = db.get(InstrumentCategoryRule, rule_id)
    if not obj:
        raise HTTPException(404, "Правило не найдено")
    for k, v in payload.items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.edit"))):
    obj = db.get(InstrumentCategoryRule, rule_id)
    if not obj:
        raise HTTPException(404, "Правило не найдено")
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ─────────── Формулы ───────────
@router.get("/formulas", response_model=List[FormulaDefinitionOut])
def list_formulas(db: Session = Depends(get_db)):
    return db.query(FormulaDefinition).order_by(FormulaDefinition.code).all()


@router.post("/formulas", response_model=FormulaDefinitionOut)
def upsert_formula(payload: FormulaDefinitionUpsert, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("formulas.edit"))):
    obj = db.query(FormulaDefinition).filter_by(code=payload.code).first()
    # validate JSON
    try:
        json.loads(payload.expression_json)
    except Exception as exc:
        raise HTTPException(400, f"expression_json должен быть валидным JSON: {exc}")
    if obj:
        for k, v in payload.model_dump().items():
            setattr(obj, k, v)
        obj.version += 1
        obj.updated_by = user.username
    else:
        obj = FormulaDefinition(**payload.model_dump(), version=1, updated_by=user.username)
        db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/formulas/{formula_id}")
def delete_formula(formula_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("formulas.edit"))):
    obj = db.get(FormulaDefinition, formula_id)
    if not obj:
        raise HTTPException(404, "Формула не найдена")
    db.delete(obj)
    db.commit()
    return {"ok": True}


# ─────────── Cash balances ───────────
@router.get("/cash-balances")
def list_cash(db: Session = Depends(get_db)):
    return db.query(CashBalance).order_by(CashBalance.balance_date.desc()).limit(500).all()


@router.post("/cash-balances")
def upsert_cash(payload: dict, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.edit"))):
    """Opening cash balance.  Changes the books → requires a second approver:
    the balance is stored as a manual cash movement awaiting approval
    («Операционный учёт»), not as an immediately effective number."""
    from api.routes.accounting import create_cash
    amount = payload.get("amount")
    return create_cash({
        "cdu_id": payload.get("cdu_id"),
        "operation_date": payload.get("balance_date") or payload.get("operation_date"),
        "amount": amount,
        "currency": payload.get("currency") or "KZT",
        "movement_type": "OPENING_BALANCE",
        "basis": payload.get("note") or "Входящий остаток (настройки)",
        "change_reason": payload.get("change_reason") or payload.get("note") or "Ввод входящего остатка",
    }, db=db, user=user)


# ─────────── Receivables ───────────
@router.get("/receivables")
def list_receivables(db: Session = Depends(get_db)):
    return db.query(AccountReceivable).order_by(AccountReceivable.record_date.desc()).limit(500).all()


@router.post("/receivables")
def upsert_receivable(payload: dict, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.edit"))):
    """Receivable entry — routed through the four-eyes workflow of
    «Операционный учёт» (it used to be written as APPROVED immediately)."""
    from api.routes.accounting import create_receivable
    return create_receivable(payload, db=db, user=user)
