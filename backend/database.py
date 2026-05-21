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

    # mbm_index — добавлен столбец mod_duration
    if "mbm_index" in inspector.get_table_names():
        mbm_cols = {c["name"] for c in inspector.get_columns("mbm_index")}
        if "mod_duration" not in mbm_cols:
            additions.append((
                "mbm_index", "mod_duration",
                "ALTER TABLE mbm_index ADD COLUMN mod_duration FLOAT",
            ))

    # trades table — soft-delete columns
    if "kase_prices" in inspector.get_table_names():
        kase_cols = {c["name"] for c in inspector.get_columns("kase_prices")}
        for col, ddl in [
            ("sec_type",                 "VARCHAR(30)"),
            ("fin_sec_ru",               "VARCHAR(200)"),
            ("fin_sec_en",               "VARCHAR(200)"),
            ("fin_sec_kz",               "VARCHAR(200)"),
            ("org_code",                 "VARCHAR(40)"),
            ("org_name_ru",              "VARCHAR(300)"),
            ("org_name_en",              "VARCHAR(300)"),
            ("org_name_kz",              "VARCHAR(300)"),
            ("settlement_price",         "FLOAT"),
            ("settlement_dirty_price",   "FLOAT"),
            ("dohod",                    "FLOAT"),
            ("dtm",                      "FLOAT"),
            ("kase_ytm",                 "FLOAT"),
            ("unit_ru",                  "VARCHAR(120)"),
            ("unit_en",                  "VARCHAR(120)"),
            ("unit_kz",                  "VARCHAR(120)"),
            ("raw_data_json",            "TEXT"),
        ]:
            if col not in kase_cols:
                additions.append((
                    "kase_prices", col,
                    f"ALTER TABLE kase_prices ADD COLUMN {col} {ddl}",
                ))

    # generated_reports — добавлен approval workflow
    if "generated_reports" in inspector.get_table_names():
        gr_cols = {c["name"] for c in inspector.get_columns("generated_reports")}
        for col, ddl in [
            ("status",            "VARCHAR(20) DEFAULT 'draft'"),
            ("submitted_by",      "VARCHAR(80)"),
            ("submitted_at",      "DATETIME"),
            ("approved_by",       "VARCHAR(80)"),
            ("approved_at",       "DATETIME"),
            ("rejected_by",       "VARCHAR(80)"),
            ("rejected_at",       "DATETIME"),
            ("rejection_comment", "TEXT"),
            ("version",           "INTEGER DEFAULT 1"),
            ("parent_report_id",  "INTEGER"),
        ]:
            if col not in gr_cols:
                additions.append((
                    "generated_reports", col,
                    f"ALTER TABLE generated_reports ADD COLUMN {col} {ddl}",
                ))

    # trades table — добавлены столбцы
    if "trades" in inspector.get_table_names():
        trade_cols = {c["name"] for c in inspector.get_columns("trades")}
        for col, ddl in [
            ("is_active",        "BOOLEAN DEFAULT 1"),
            ("updated_at",       "DATETIME"),
            # Phase 2 — price reconciliation vs KASE
            ("price_original",   "FLOAT"),
            ("price_kase",       "FLOAT"),
            ("price_final",      "FLOAT"),
            ("price_flag",       "BOOLEAN DEFAULT 0"),
            ("price_diff_pct",   "FLOAT"),
            ("price_checked_at", "DATETIME"),
        ]:
            if col not in trade_cols:
                additions.append((
                    "trades", col,
                    f"ALTER TABLE trades ADD COLUMN {col} {ddl}",
                ))

    # Phase 3 — CDU-specific file format overrides
    if "cdu_file_formats" not in inspector.get_table_names():
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE cdu_file_formats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cdu_id INTEGER NOT NULL UNIQUE,
                    field_aliases TEXT,
                    header_row_index INTEGER DEFAULT 0,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_by VARCHAR(80),
                    FOREIGN KEY (cdu_id) REFERENCES cdu_registry(id) ON DELETE CASCADE
                )
            """))
        logger.info("[migrate] cdu_file_formats created")

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
