"""SQLAlchemy engine, session factory, dependency."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from loguru import logger
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite:///"):
        rel = url.replace("sqlite:///", "", 1)
        Path(rel).parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(settings.database_url)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Context manager for service-level usage."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _apply_dev_migrations() -> None:
    """Light SQLite-only migrations: add missing columns to existing tables.

    Used for the dev workflow where schema evolves rapidly. Does NOT replace
    Alembic for production, but lets us avoid wiping the DB during Phase A→B→C
    development. Columns we know to add since the original v1 schema."""
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "cdu_registry" not in inspector.get_table_names():
        return  # fresh DB, create_all will do the right thing

    existing_cols = {c["name"] for c in inspector.get_columns("cdu_registry")}
    additions: list[tuple[str, str, str]] = []  # (table, column, ddl)

    if "portfolio_type" not in existing_cols:
        additions.append((
            "cdu_registry", "portfolio_type",
            "ALTER TABLE cdu_registry ADD COLUMN portfolio_type VARCHAR(20) DEFAULT 'PRIVATE_CDU'",
        ))
    if "portfolio_code" not in existing_cols:
        additions.append((
            "cdu_registry", "portfolio_code",
            "ALTER TABLE cdu_registry ADD COLUMN portfolio_code VARCHAR(20)",
        ))

    # accounts_receivable table — много новых колонок
    if "accounts_receivable" in inspector.get_table_names():
        ar_cols = {c["name"] for c in inspector.get_columns("accounts_receivable")}
        for col, ddl in [
            ("isin",                "VARCHAR(20)"),
            ("currency",            "VARCHAR(8) DEFAULT 'KZT'"),
            ("amount_kzt",          "FLOAT"),
            ("balance_currency",    "FLOAT"),
            ("balance_kzt",         "FLOAT DEFAULT 0.0"),
            ("actual_value_date",   "DATE"),
            ("related_event_type",  "VARCHAR(20)"),
            ("related_trade_id",    "INTEGER"),
            ("portfolio_code",      "VARCHAR(20)"),
            ("source_doc_id",       "INTEGER"),
            ("notes",               "TEXT"),
            ("updated_at",          "DATETIME"),
        ]:
            if col not in ar_cols:
                additions.append((
                    "accounts_receivable", col,
                    f"ALTER TABLE accounts_receivable ADD COLUMN {col} {ddl}",
                ))

    # trades table — soft-delete columns
    if "trades" in inspector.get_table_names():
        trade_cols = {c["name"] for c in inspector.get_columns("trades")}
        for col, ddl in [
            ("is_active",   "BOOLEAN DEFAULT 1"),
            ("updated_at",  "DATETIME"),
        ]:
            if col not in trade_cols:
                additions.append((
                    "trades", col,
                    f"ALTER TABLE trades ADD COLUMN {col} {ddl}",
                ))

    if not additions:
        return

    with engine.begin() as conn:
        for table, col, ddl in additions:
            try:
                conn.execute(text(ddl))
                logger.info(f"[migrate] {table}.{col} added")
            except Exception as exc:
                logger.warning(f"[migrate] failed {table}.{col}: {exc!r}")


def init_db() -> None:
    """Create all tables (used at app startup)."""
    from models import db_models  # noqa: F401  ensures models are registered
    # 1) Add missing columns first (so create_all sees them)
    _apply_dev_migrations()
    # 2) Create any missing tables
    Base.metadata.create_all(bind=engine)
