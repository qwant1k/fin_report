"""Раздел «Формулы»: как считается, параметры расчёта, пользовательские показатели."""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth import require_permission, require_user
from database import get_db
from models.db_models import CustomIndicator, CustomIndicatorVersion, User
from services.audit import write_audit
from services.formulas import catalog, expr, fields, indicators, params

router = APIRouter(prefix="/api/formulas", tags=["formulas"],
                   dependencies=[Depends(require_permission("page.formulas"))])
EDIT = Depends(require_permission("formulas.edit"))

# Values of the indicators are shown in «Сводка», so they are available to
# everyone who sees the summary (not only to users of the «Формулы» page).
values_router = APIRouter(prefix="/api/formulas", tags=["formulas"],
                          dependencies=[Depends(require_permission("page.dashboard"))])


@values_router.get("/indicators/values")
def indicator_values(as_of: date = Query(..., alias="date"), db: Session = Depends(get_db)):
    return indicators.values_for_date(db, as_of)


# ───────────────────────────── как считается ─────────────────────────────

@router.get("/system")
def system_formulas(db: Session = Depends(get_db)):
    params.refresh(db, force=True)
    return catalog.listing()


@router.get("/system/{code}/example")
def system_example(code: str, cdu_id: Optional[int] = None, as_of: date = Query(..., alias="date"),
                   item: Optional[str] = None, db: Session = Depends(get_db)):
    if cdu_id is None:
        # by default — the largest calculated portfolio of the date (the example is never empty for no reason)
        from models.db_models import CDU, PortfolioSummary
        row = db.query(PortfolioSummary).filter(PortfolioSummary.summary_date <= as_of).order_by(
            PortfolioSummary.summary_date.desc(), PortfolioSummary.total_mv_current.desc()).first()
        first = db.query(CDU.id).filter(CDU.is_active.is_(True)).order_by(CDU.id).first()
        cdu_id = row.cdu_id if row else (first[0] if first else None)
    if cdu_id is None:
        raise HTTPException(404, "Нет ни одного ЧДУ")
    try:
        return {**catalog.example(db, code, cdu_id, as_of, item), "cdu_id": cdu_id}
    except KeyError:
        raise HTTPException(404, "Формула не найдена")


# ───────────────────────────── параметры ─────────────────────────────

@router.get("/parameters")
def list_parameters(db: Session = Depends(get_db)):
    return params.listing(db)


@router.put("/parameters/{code}", dependencies=[EDIT])
def update_parameter(code: str, payload: Dict[str, Any], db: Session = Depends(get_db),
                     user: User = Depends(require_user)):
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "Укажите причину изменения — она сохранится в истории")
    try:
        old = params.get(code)
        value = params.set_value(db, code, payload.get("value"), reason=reason, actor=user.username)
    except KeyError:
        raise HTTPException(404, "Параметр не найден")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    write_audit(db, user=user.username, action="CALC_PARAMETER_CHANGED", entity="CalcParameter", entity_id=None,
                details={"code": code, "old": str(old), "new": str(value), "reason": reason})
    db.commit()
    return {"ok": True, "code": code, "value": value,
            "message": "Параметр сохранён. Он применяется при следующем пересчёте — пересчитайте сводку за нужные даты."}


@router.post("/parameters/{code}/reset", dependencies=[EDIT])
def reset_parameter(code: str, payload: Dict[str, Any], db: Session = Depends(get_db),
                    user: User = Depends(require_user)):
    try:
        default = params.definition(code).default
    except KeyError:
        raise HTTPException(404, "Параметр не найден")
    return update_parameter(code, {"value": default, "reason": payload.get("reason") or "Возврат к значению по умолчанию"},
                            db, user)


# ───────────────────────────── показатели ─────────────────────────────

@router.get("/fields")
def field_catalog(level: str = Query("cdu", pattern="^(cdu|fund)$")):
    groups: Dict[str, list] = {}
    for f in fields.catalog(level):
        groups.setdefault(f.group, []).append({"name": f.name, "unit": f.unit, "description": f.description})
    functions = [{"name": n, "signature": sig, "help": h} for n, (_, _, _, sig, h) in expr.FUNCTIONS.items()]
    return {"level": level, "groups": [{"group": g, "fields": v} for g, v in groups.items()], "functions": functions}


@router.get("/templates")
def templates():
    return indicators.TEMPLATES


@router.post("/validate")
def validate(payload: Dict[str, Any]):
    return indicators.validate(str(payload.get("expression") or ""), _level(payload.get("level")))


@router.post("/preview")
def preview(payload: Dict[str, Any], db: Session = Depends(get_db)):
    try:
        as_of = date.fromisoformat(str(payload.get("date")))
    except ValueError:
        raise HTTPException(400, "Укажите дату")
    return indicators.preview(db, str(payload.get("expression") or ""), _level(payload.get("level")), as_of)


def _level(v: Any) -> str:
    return "fund" if v == "fund" else "cdu"


@router.get("/indicators")
def list_indicators(db: Session = Depends(get_db)):
    rows = db.query(CustomIndicator).filter(CustomIndicator.status != "DELETED").order_by(
        CustomIndicator.status, CustomIndicator.name).all()
    return [indicators.to_dict(r) for r in rows]


def _apply(db: Session, ind: CustomIndicator, payload: Dict[str, Any]) -> None:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Укажите название показателя")
    same = db.query(CustomIndicator).filter(CustomIndicator.name == name, CustomIndicator.status != "ARCHIVED")
    if ind.id is not None:
        same = same.filter(CustomIndicator.id != ind.id)
    if same.first() is not None:
        raise HTTPException(400, f"Показатель «{name}» уже есть — выберите его в списке слева или задайте другое название")
    level = _level(payload.get("level"))
    expression = str(payload.get("expression") or "").strip()
    check = indicators.validate(expression, level)
    if not check["ok"]:
        raise HTTPException(400, f"Формула: {check['error']}")
    unit = payload.get("unit") if payload.get("unit") in indicators.UNITS else "NUMBER"
    op = payload.get("alert_op") or None
    if op is not None and op not in indicators.ALERT_OPS:
        raise HTTPException(400, "Неизвестное условие уведомления")
    threshold = payload.get("alert_threshold")
    if op and threshold in (None, ""):
        raise HTTPException(400, "Укажите порог для уведомления")
    ind.name = name
    ind.description = (payload.get("description") or "").strip() or None
    ind.level = level
    ind.unit = unit
    ind.expression = expression
    ind.decimals = max(0, min(int(payload.get("decimals") if payload.get("decimals") is not None else 2), 6))
    ind.show_on_dashboard = bool(payload.get("show_on_dashboard", True))
    ind.alert_op = op
    ind.alert_threshold = float(str(threshold).replace(",", ".")) if op else None
    ind.alert_severity = (payload.get("alert_severity") or "WARN") if op else None


def _version(db: Session, ind: CustomIndicator, user: str, comment: Optional[str]) -> None:
    db.add(CustomIndicatorVersion(indicator_id=ind.id, version=ind.version,
                                  snapshot_json=json.dumps(indicators.snapshot(ind), ensure_ascii=False),
                                  comment=comment, created_by=user))


@router.post("/indicators", dependencies=[EDIT])
def create_indicator(payload: Dict[str, Any], db: Session = Depends(get_db), user: User = Depends(require_user)):
    ind = CustomIndicator(code="tmp", name="", expression="", created_by=user.username, updated_by=user.username,
                          status="ACTIVE" if payload.get("activate", True) else "DRAFT", version=1)
    _apply(db, ind, payload)
    ind.code = indicators.make_code(db, ind.name)
    db.add(ind)
    db.flush()
    _version(db, ind, user.username, payload.get("comment") or "Создан")
    write_audit(db, user=user.username, action="INDICATOR_CREATED", entity="CustomIndicator", entity_id=ind.id,
                details=indicators.snapshot(ind))
    db.commit()
    return indicators.to_dict(ind)


@router.put("/indicators/{ind_id}", dependencies=[EDIT])
def update_indicator(ind_id: int, payload: Dict[str, Any], db: Session = Depends(get_db),
                     user: User = Depends(require_user)):
    ind = db.get(CustomIndicator, ind_id)
    if ind is None:
        raise HTTPException(404, "Показатель не найден")
    before = indicators.snapshot(ind)
    _apply(db, ind, payload)
    if "activate" in payload:
        ind.status = "ACTIVE" if payload["activate"] else "DRAFT"
    if indicators.snapshot(ind) != before:
        ind.version += 1
        ind.updated_by = user.username
        _version(db, ind, user.username, payload.get("comment"))
        write_audit(db, user=user.username, action="INDICATOR_UPDATED", entity="CustomIndicator", entity_id=ind.id,
                    details={"before": before, "after": indicators.snapshot(ind)})
    db.commit()
    return indicators.to_dict(ind)


@router.post("/indicators/{ind_id}/status", dependencies=[EDIT])
def set_status(ind_id: int, payload: Dict[str, Any], db: Session = Depends(get_db), user: User = Depends(require_user)):
    ind = db.get(CustomIndicator, ind_id)
    if ind is None:
        raise HTTPException(404, "Показатель не найден")
    status = payload.get("status")
    if status not in ("ACTIVE", "DRAFT", "ARCHIVED"):
        raise HTTPException(400, "Неизвестный статус")
    ind.status = status
    ind.updated_by = user.username
    write_audit(db, user=user.username, action="INDICATOR_STATUS", entity="CustomIndicator", entity_id=ind.id,
                details={"status": status})
    db.commit()
    return indicators.to_dict(ind)


@router.get("/indicators/{ind_id}/versions")
def versions(ind_id: int, db: Session = Depends(get_db)):
    rows = db.query(CustomIndicatorVersion).filter_by(indicator_id=ind_id).order_by(
        CustomIndicatorVersion.version.desc(), CustomIndicatorVersion.id.desc()).all()
    return [{"version": r.version, "snapshot": json.loads(r.snapshot_json), "comment": r.comment,
             "created_by": r.created_by, "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]


@router.post("/indicators/{ind_id}/rollback/{version}", dependencies=[EDIT])
def rollback(ind_id: int, version: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    row = db.query(CustomIndicatorVersion).filter_by(indicator_id=ind_id, version=version).order_by(
        CustomIndicatorVersion.id.desc()).first()
    if row is None:
        raise HTTPException(404, "Версия не найдена")
    snap = json.loads(row.snapshot_json)
    snap.pop("code", None)
    status = snap.pop("status", None)
    return update_indicator(ind_id, {**snap, "activate": status == "ACTIVE",
                                     "comment": f"Возврат к версии {version}"}, db, user)
