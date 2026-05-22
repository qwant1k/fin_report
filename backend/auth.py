"""JWT-based auth and permission-based RBAC for the API."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.db_models import RoleDefinition, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# bcrypt has a hard 72-byte limit on the input password.
_BCRYPT_MAX = 72


def _perm(code: str, group: str, label: str) -> dict[str, str]:
    return {"code": code, "group": group, "label": label}


PERMISSION_CATALOG: tuple[dict[str, str], ...] = (
    _perm("page.dashboard", "Страницы", "Сводка"),
    _perm("page.analytics", "Страницы", "Аналитика"),
    _perm("page.alerts", "Страницы", "Алерты"),
    _perm("page.upload", "Страницы", "Загрузка XLSX"),
    _perm("page.primary_data", "Страницы", "Первичка"),
    _perm("page.reconciliation", "Страницы", "Сверка"),
    _perm("page.history", "Страницы", "История"),
    _perm("page.import", "Страницы", "Импорт истории"),
    _perm("page.reports", "Страницы", "Сводные отчеты"),
    _perm("page.positions", "Страницы", "Позиции"),
    _perm("page.securities", "Страницы", "Справочник ЦБ"),
    _perm("page.risk_report", "Страницы", "Risk Report"),
    _perm("page.kase", "Страницы", "KASE"),
    _perm("page.mbm", "Страницы", "MBM"),
    _perm("page.settings", "Страницы", "ЧДУ и лимиты"),
    _perm("page.data_editor", "Страницы", "Редактор БД"),
    _perm("page.formulas", "Страницы", "Формулы"),
    _perm("page.admin", "Страницы", "Администрирование"),
    _perm("dashboard.calculate", "Сводка", "Пересчитать портфель"),
    _perm("reports.export", "Отчеты", "Сформировать XLSX/PDF"),
    _perm("reports.submit", "Отчеты", "Отправить на согласование"),
    _perm("reports.approve", "Отчеты", "Согласовать отчет"),
    _perm("reports.reject", "Отчеты", "Отклонить отчет"),
    _perm("reports.regenerate", "Отчеты", "Перегенерировать отчет"),
    _perm("reports.delete", "Отчеты", "Удалить отчет"),
    _perm("upload.trade_report", "Загрузка", "Загрузка Trade Report"),
    _perm("primary_data.upload", "Загрузка", "Загрузка первичных данных"),
    _perm("import.run", "Загрузка", "Импорт Risk Report"),
    _perm("reconciliation.run", "Загрузка", "Запуск сверки"),
    _perm("automation.run", "Операции", "Дневная автоматизация"),
    _perm("kase.refresh", "Рынок", "Обновить KASE"),
    _perm("kase.reconcile", "Рынок", "Сверить цены KASE"),
    _perm("kase.manual_price", "Рынок", "Ручная цена KASE"),
    _perm("mbm.refresh", "Рынок", "Обновить MBM"),
    _perm("mbm.manual", "Рынок", "Ручной ввод MBM"),
    _perm("settings.edit", "Настройки", "Редактировать ЧДУ, лимиты и справочники"),
    _perm("cdu_formats.edit", "Настройки", "Настроить форматы файлов ЧДУ"),
    _perm("formulas.edit", "Настройки", "Редактировать формулы"),
    _perm("data_editor.edit", "Настройки", "Редактировать таблицы БД"),
    _perm("securities.edit", "Справочники", "Редактировать справочник ЦБ"),
    _perm("risk_report.notes.edit", "Risk Report", "Редактировать заметки Risk Report"),
    _perm("admin.users.manage", "Администрирование", "Управлять пользователями"),
    _perm("admin.roles.manage", "Администрирование", "Управлять ролями"),
    _perm("admin.audit.view", "Администрирование", "Просмотр аудита"),
)

ALL_PERMISSIONS: tuple[str, ...] = tuple(item["code"] for item in PERMISSION_CATALOG)
PAGE_PERMISSIONS: tuple[str, ...] = tuple(code for code in ALL_PERMISSIONS if code.startswith("page."))

ANALYST_PAGES = (
    "page.dashboard", "page.analytics", "page.alerts", "page.upload",
    "page.primary_data", "page.reconciliation", "page.history", "page.reports",
    "page.positions", "page.securities", "page.risk_report", "page.kase",
    "page.mbm", "page.settings", "page.data_editor",
)
AUDITOR_PAGES = (
    "page.dashboard", "page.analytics", "page.alerts", "page.history",
    "page.reports", "page.positions", "page.securities", "page.risk_report",
    "page.kase", "page.mbm",
)
OPERATOR_PAGES = (
    "page.dashboard", "page.alerts", "page.upload", "page.primary_data",
    "page.reconciliation", "page.history",
)

DEFAULT_ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "admin": ALL_PERMISSIONS,
    "analyst": (
        *ANALYST_PAGES,
        "dashboard.calculate",
        "reports.export", "reports.submit", "reports.regenerate",
        "upload.trade_report", "primary_data.upload", "reconciliation.run",
        "kase.refresh", "kase.reconcile", "kase.manual_price",
        "mbm.refresh", "mbm.manual",
        "settings.edit", "cdu_formats.edit", "data_editor.edit",
        "securities.edit", "risk_report.notes.edit",
    ),
    "operator": (
        *OPERATOR_PAGES,
        "upload.trade_report", "primary_data.upload", "reconciliation.run",
        "dashboard.calculate",
    ),
    "auditor": AUDITOR_PAGES,
    "viewer": AUDITOR_PAGES,
}

DEFAULT_ROLE_META: dict[str, tuple[str, str]] = {
    "admin": ("Администратор", "Полный доступ ко всем страницам и действиям."),
    "analyst": ("Аналитик", "Работа с отчетами, расчетами и справочниками без согласования и администрирования."),
    "operator": ("Оператор", "Загрузка данных, сверка и операционные действия."),
    "auditor": ("Аудитор", "Только просмотр отчетов, справочников и рыночных данных."),
    "viewer": ("Viewer legacy", "Совместимость со старыми пользователями; права аудитора."),
}

# Allowed built-in roles. Custom roles are stored in role_definitions.
ALLOWED_ROLES = {"admin", "analyst", "operator", "auditor", "viewer"}
WRITE_ROLES = {"admin", "analyst", "operator"}
WRITE_PERMISSIONS = {
    code for code in ALL_PERMISSIONS
    if not code.startswith("page.") and not code.startswith("admin.audit")
}


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


def _role_or_alias(role: str) -> str:
    return "auditor" if role == "viewer" else role


def _normalise_permissions(values: Iterable[object]) -> list[str]:
    allowed = set(ALL_PERMISSIONS)
    result: list[str] = []
    for value in values:
        code = str(value).strip()
        if not code:
            continue
        if code == "*" or code in allowed:
            result.append(code)
    return sorted(set(result))


def role_specs() -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    for code in ("admin", "analyst", "operator", "auditor", "viewer"):
        name, description = DEFAULT_ROLE_META[code]
        specs.append({
            "code": code,
            "name": name,
            "description": description,
            "permissions": list(DEFAULT_ROLE_PERMISSIONS[code]),
            "is_system": True,
            "is_active": True,
        })
    return specs


def _permissions_from_json(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return _normalise_permissions(data)


def permissions_for_role(db: Session, role: str | None) -> list[str]:
    role_code = (role or "viewer").strip() or "viewer"
    row = db.query(RoleDefinition).filter_by(code=role_code).first()
    if row is None:
        alias = _role_or_alias(role_code)
        if alias != role_code:
            row = db.query(RoleDefinition).filter_by(code=alias).first()
    if row is not None:
        if not row.is_active:
            return []
        return _permissions_from_json(row.permissions_json)

    fallback = _role_or_alias(role_code)
    return list(DEFAULT_ROLE_PERMISSIONS.get(fallback, DEFAULT_ROLE_PERMISSIONS["auditor"]))


def user_permissions(user: User, db: Session) -> list[str]:
    if user.role == "admin" or user.username == settings.admin_username:
        return list(ALL_PERMISSIONS)
    return permissions_for_role(db, user.role)


def has_permission(user: User, permission: str, db: Session) -> bool:
    permissions = set(user_permissions(user, db))
    return "*" in permissions or permission in permissions


def has_any_permission(user: User, permissions: Sequence[str], db: Session) -> bool:
    current = set(user_permissions(user, db))
    return "*" in current or any(permission in current for permission in permissions)


def require_permission(permission: str):
    def _dep(
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not has_permission(user, permission, db):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Недостаточно прав: {permission}",
            )
        return user

    return _dep


def require_any_permission(*permissions: str):
    allowed = tuple(permissions)

    def _dep(
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not has_any_permission(user, allowed, db):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Недостаточно прав. Требуется одно из: {', '.join(allowed)}",
            )
        return user

    return _dep


def require_admin(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> User:
    if user.role == "admin" or has_any_permission(user, ("admin.users.manage", "admin.roles.manage"), db):
        return user
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Требуются права администратора")


def require_role(*roles: str):
    """Dependency factory: allow only the listed built-in roles.

    ``viewer`` is treated as ``auditor`` for backwards compatibility.
    Prefer ``require_permission`` for new endpoints.
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


def require_write(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> User:
    """Legacy write dependency kept for older tests/routes."""
    if _role_or_alias(user.role) in WRITE_ROLES or has_any_permission(user, tuple(WRITE_PERMISSIONS), db):
        return user
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Запись запрещена для текущей роли",
    )
