"""JWT-based auth for the admin API."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.db_models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# bcrypt has a hard 72-byte limit on the input password.
_BCRYPT_MAX = 72


def hash_password(p: str) -> str:
    pw = p.encode("utf-8")[:_BCRYPT_MAX]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        pw = plain.encode("utf-8")[:_BCRYPT_MAX]
        return bcrypt.checkpw(pw, hashed.encode("utf-8"))
    except Exception:
        return False


def create_token(*, sub: str, role: str) -> str:
    payload = {
        "sub": sub,
        "role": role,
        "exp": datetime.utcnow() + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Returns the current user or None if anonymous (so endpoints may decide)."""
    if not token:
        return None
    try:
        payload = decode_token(token)
        sub = payload.get("sub")
    except JWTError:
        return None
    if not sub:
        return None
    return db.query(User).filter_by(username=sub, is_active=True).first()


def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Требуются права администратора")
    return user


# ─────────────── 4-role RBAC (Phase 2 / PR-3) ───────────────
# Allowed roles. ``viewer`` is kept as a backwards-compat alias for ``auditor``
# (read-only). Old DB rows with role="viewer" are still accepted everywhere a
# read access is needed.
ALLOWED_ROLES = {"admin", "analyst", "operator", "auditor", "viewer"}
WRITE_ROLES = {"admin", "analyst", "operator"}


def _role_or_alias(role: str) -> str:
    return "auditor" if role == "viewer" else role


def require_role(*roles: str):
    """Dependency factory: allow only the listed roles.

    Example: ``Depends(require_role("admin", "analyst"))``.
    ``viewer`` is treated as ``auditor`` for backwards compatibility.
    """
    allowed = set(roles)

    def _dep(user: User = Depends(require_user)) -> User:
        actual = _role_or_alias(user.role)
        if actual not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Недостаточно прав. Требуется одна из ролей: {', '.join(sorted(allowed))}",
            )
        return user

    return _dep


def require_write(user: User = Depends(require_user)) -> User:
    """Any role that can mutate data (admin/analyst/operator)."""
    if _role_or_alias(user.role) not in WRITE_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Только аудитор: запись запрещена",
        )
    return user
