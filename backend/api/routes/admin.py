"""Admin endpoints — users management, audit log, system info."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import hash_password, require_admin
from database import get_db
from models.db_models import AuditLog, User
from models.schemas import UserCreate, UserOut

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return db.query(User).order_by(User.username).all()


@router.post("/users", response_model=UserOut)
def create_user(payload: UserCreate, db: Session = Depends(get_db),
                actor: User = Depends(require_admin)):
    if db.query(User).filter_by(username=payload.username).first():
        raise HTTPException(409, "Пользователь существует")
    obj = User(
        username=payload.username,
        full_name=payload.full_name,
        email=payload.email,
        role=payload.role,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(obj)
    db.add(AuditLog(user=actor.username, action="CREATE_USER", entity="User",
                    entity_id=None, details=payload.username))
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db),
                actor: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    if u.username == actor.username:
        raise HTTPException(400, "Нельзя удалить самого себя")
    db.add(AuditLog(user=actor.username, action="DELETE_USER", entity="User",
                    entity_id=user_id, details=u.username))
    db.delete(u)
    db.commit()
    return {"ok": True}


@router.put("/users/{user_id}/role")
def change_role(user_id: int, role: str, db: Session = Depends(get_db),
                actor: User = Depends(require_admin)):
    if role not in ("admin", "analyst", "viewer"):
        raise HTTPException(400, "role ∈ {admin, analyst, viewer}")
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    u.role = role
    db.add(AuditLog(user=actor.username, action="CHANGE_ROLE", entity="User",
                    entity_id=user_id, details=role))
    db.commit()
    return {"ok": True}


@router.get("/audit")
def list_audit(limit: int = 200, db: Session = Depends(get_db),
               user: User = Depends(require_admin)):
    return db.query(AuditLog).order_by(AuditLog.ts.desc()).limit(limit).all()
