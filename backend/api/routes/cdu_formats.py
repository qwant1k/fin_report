"""CRUD для CDU-специфичных форматов файла (маппинг колонок).

Эндпоинты позволяют настраивать переопределения имён колонок для каждого CDU.
Оператор может читать, аналитик/админ — создавать, редактировать, удалять.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import require_user, require_write
from database import SessionLocal
from models.db_models import CDU, CDUFileFormat, User

router = APIRouter(prefix="/api/cdu-formats", tags=["CDU File Formats"])

# ─────────────── deps ───────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ─────────────── schemas ───────────────

# ─────────────── helper ───────────────

def _to_dict(cff: CDUFileFormat) -> dict[str, Any]:
    return {
        "id": cff.id,
        "cdu_id": cff.cdu_id,
        "cdu_name": cff.cdu.name if cff.cdu else None,
        "field_aliases": json.loads(cff.field_aliases) if cff.field_aliases else {},
        "header_row_index": cff.header_row_index,
        "is_active": cff.is_active,
        "updated_by": cff.updated_by,
        "updated_at": cff.updated_at.isoformat() if cff.updated_at else None,
    }

# ─────────────── routes ───────────────

@router.get("/", dependencies=[Depends(require_user)])
def list_cdu_formats(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Все активные форматы с именами CDU."""
    rows = db.query(CDUFileFormat).all()
    return [_to_dict(r) for r in rows]

@router.get("/{cdu_id}", dependencies=[Depends(require_user)])
def get_cdu_format(cdu_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Формат конкретного CDU (или пустой dict, если не настроен)."""
    row = db.query(CDUFileFormat).filter(CDUFileFormat.cdu_id == cdu_id).first()
    if not row:
        return {"cdu_id": cdu_id, "field_aliases": {}, "header_row_index": 0, "is_active": True}
    return _to_dict(row)

@router.post("/{cdu_id}", dependencies=[Depends(require_user), Depends(require_write)])
def create_or_update_cdu_format(
    cdu_id: int,
    data: dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    """Создать или полностью заменить формат CDU."""
    cdu = db.query(CDU).filter(CDU.id == cdu_id).first()
    if not cdu:
        raise HTTPException(404, detail="CDU not found")

    aliases = data.get("field_aliases", {})
    if not isinstance(aliases, dict):
        raise HTTPException(400, detail="field_aliases must be a dict")

    header_row_index = data.get("header_row_index", 0)
    is_active = data.get("is_active", True)

    existing = db.query(CDUFileFormat).filter(CDUFileFormat.cdu_id == cdu_id).first()
    if existing:
        existing.field_aliases = json.dumps(aliases, ensure_ascii=False)
        existing.header_row_index = int(header_row_index)
        existing.is_active = bool(is_active)
        existing.updated_by = user.username if user else "system"
        db.commit()
        db.refresh(existing)
        return _to_dict(existing)

    row = CDUFileFormat(
        cdu_id=cdu_id,
        field_aliases=json.dumps(aliases, ensure_ascii=False),
        header_row_index=int(header_row_index),
        is_active=bool(is_active),
        updated_by=user.username if user else "system",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_dict(row)

@router.patch("/{cdu_id}", dependencies=[Depends(require_user), Depends(require_write)])
def patch_cdu_format(
    cdu_id: int,
    data: dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    """Частично обновить формат CDU."""
    row = db.query(CDUFileFormat).filter(CDUFileFormat.cdu_id == cdu_id).first()
    if not row:
        raise HTTPException(404, detail="Format not found")

    if "field_aliases" in data:
        aliases = data["field_aliases"]
        if not isinstance(aliases, dict):
            raise HTTPException(400, detail="field_aliases must be a dict")
        row.field_aliases = json.dumps(aliases, ensure_ascii=False)
    if "header_row_index" in data:
        row.header_row_index = int(data["header_row_index"])
    if "is_active" in data:
        row.is_active = bool(data["is_active"])
    row.updated_by = user.username if user else "system"
    db.commit()
    db.refresh(row)
    return _to_dict(row)

@router.delete("/{cdu_id}", dependencies=[Depends(require_user), Depends(require_write)])
def delete_cdu_format(cdu_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Удалить формат CDU."""
    row = db.query(CDUFileFormat).filter(CDUFileFormat.cdu_id == cdu_id).first()
    if not row:
        raise HTTPException(404, detail="Format not found")
    db.delete(row)
    db.commit()
    return {"detail": "deleted", "cdu_id": cdu_id}
