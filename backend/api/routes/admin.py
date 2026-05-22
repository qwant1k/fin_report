"""Admin endpoints: users, roles, permissions and audit log."""
from __future__ import annotations

import json
import re
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import (
    ALL_PERMISSIONS,
    PERMISSION_CATALOG,
    hash_password,
    require_any_permission,
    require_permission,
    user_permissions,
)
from database import get_db
from models.db_models import AuditLog, RoleDefinition, User
from models.schemas import (
    PermissionCatalogItem,
    RoleDefinitionCreate,
    RoleDefinitionOut,
    RoleDefinitionUpdate,
    UserCreate,
    UserOut,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

ROLE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def _validate_permissions(permissions: list[str]) -> list[str]:
    allowed = set(ALL_PERMISSIONS)
    cleaned = sorted({p.strip() for p in permissions if p and p.strip()})
    unknown = [p for p in cleaned if p not in allowed]
    if unknown:
        raise HTTPException(400, f"Unknown permissions: {', '.join(unknown)}")
    return cleaned


def _role_to_dict(role: RoleDefinition) -> dict:
    try:
        permissions = json.loads(role.permissions_json or "[]")
    except json.JSONDecodeError:
        permissions = []
    if not isinstance(permissions, list):
        permissions = []
    allowed = set(ALL_PERMISSIONS)
    return {
        "id": role.id,
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "permissions": sorted({str(p).strip() for p in permissions if str(p).strip() in allowed}),
        "is_system": role.is_system,
        "is_active": role.is_active,
        "created_at": role.created_at,
        "updated_at": role.updated_at,
    }


def _user_to_dict(user: User, db: Session) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "permissions": user_permissions(user, db),
    }


def _ensure_role_assignable(db: Session, role_code: str) -> None:
    role = db.query(RoleDefinition).filter_by(code=role_code, is_active=True).first()
    if not role:
        raise HTTPException(400, "Role is not active or does not exist")


@router.get("/permissions", response_model=List[PermissionCatalogItem])
def list_permissions(
    user: User = Depends(require_permission("admin.roles.manage")),
):
    return list(PERMISSION_CATALOG)


@router.get("/roles", response_model=List[RoleDefinitionOut])
def list_roles(
    db: Session = Depends(get_db),
    user: User = Depends(require_any_permission("admin.roles.manage", "admin.users.manage")),
):
    rows = db.query(RoleDefinition).order_by(RoleDefinition.is_system.desc(), RoleDefinition.code).all()
    return [_role_to_dict(row) for row in rows]


@router.post("/roles", response_model=RoleDefinitionOut)
def create_role(
    payload: RoleDefinitionCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("admin.roles.manage")),
):
    code = payload.code.strip().lower()
    if not ROLE_CODE_RE.match(code):
        raise HTTPException(400, "Role code must be 2-40 chars: lowercase latin letters, digits, underscore")
    if db.query(RoleDefinition).filter_by(code=code).first():
        raise HTTPException(409, "Role already exists")
    permissions = _validate_permissions(payload.permissions)
    obj = RoleDefinition(
        code=code,
        name=payload.name.strip() or code,
        description=payload.description,
        permissions_json=json.dumps(permissions, ensure_ascii=False),
        is_system=False,
        is_active=payload.is_active,
    )
    db.add(obj)
    db.add(AuditLog(user=actor.username, action="CREATE_ROLE", entity="RoleDefinition",
                    entity_id=None, details=code))
    db.commit()
    db.refresh(obj)
    return _role_to_dict(obj)


@router.patch("/roles/{role_id}", response_model=RoleDefinitionOut)
def update_role(
    role_id: int,
    payload: RoleDefinitionUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("admin.roles.manage")),
):
    obj = db.get(RoleDefinition, role_id)
    if not obj:
        raise HTTPException(404, "Role not found")
    if payload.name is not None:
        obj.name = payload.name.strip() or obj.code
    if payload.description is not None:
        obj.description = payload.description
    if payload.permissions is not None:
        if obj.is_system:
            raise HTTPException(400, "System role permissions are managed by the application")
        obj.permissions_json = json.dumps(_validate_permissions(payload.permissions), ensure_ascii=False)
    if payload.is_active is not None:
        if obj.is_system and not payload.is_active:
            raise HTTPException(400, "System role cannot be disabled")
        obj.is_active = payload.is_active
    db.add(AuditLog(user=actor.username, action="UPDATE_ROLE", entity="RoleDefinition",
                    entity_id=role_id, details=obj.code))
    db.commit()
    db.refresh(obj)
    return _role_to_dict(obj)


@router.delete("/roles/{role_id}")
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("admin.roles.manage")),
):
    obj = db.get(RoleDefinition, role_id)
    if not obj:
        raise HTTPException(404, "Role not found")
    if obj.is_system:
        raise HTTPException(400, "System role cannot be deleted")
    if db.query(User).filter_by(role=obj.code).first():
        raise HTTPException(409, "Role is assigned to users")
    db.add(AuditLog(user=actor.username, action="DELETE_ROLE", entity="RoleDefinition",
                    entity_id=role_id, details=obj.code))
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.get("/users", response_model=List[UserOut])
def list_users(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("admin.users.manage")),
):
    return [_user_to_dict(u, db) for u in db.query(User).order_by(User.username).all()]


@router.post("/users", response_model=UserOut)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("admin.users.manage")),
):
    _ensure_role_assignable(db, payload.role)
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
    return _user_to_dict(obj, db)


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("admin.users.manage")),
):
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
def change_role(
    user_id: int,
    role: str,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("admin.users.manage")),
):
    _ensure_role_assignable(db, role)
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    u.role = role
    db.add(AuditLog(user=actor.username, action="CHANGE_ROLE", entity="User",
                    entity_id=user_id, details=role))
    db.commit()
    return {"ok": True}


@router.get("/audit")
def list_audit(
    limit: int = 200,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("admin.audit.view")),
):
    return db.query(AuditLog).order_by(AuditLog.ts.desc()).limit(limit).all()
