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

if settings.database_url.startswith("sqlite"):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
        # WAL lets the scheduler write while users read; busy_timeout avoids
        # «database is locked» errors on concurrent writes.
        cursor = dbapi_connection.cursor()
        try:
            if ":memory:" not in settings.database_url:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000")
        finally:
            cursor.close()

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
    if "report_code" not in existing_cols:
        additions.append((
            "cdu_registry", "report_code",
            "ALTER TABLE cdu_registry ADD COLUMN report_code VARCHAR(40)",
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
            ("workflow_status",     "VARCHAR(24) DEFAULT 'APPROVED'"),
            ("is_manual",           "BOOLEAN DEFAULT 0"),
            ("is_active",           "BOOLEAN DEFAULT 1"),
            ("created_by",          "VARCHAR(80)"),
            ("updated_by",          "VARCHAR(80)"),
            ("approved_by",         "VARCHAR(80)"),
            ("approved_at",         "DATETIME"),
            ("rejected_by",         "VARCHAR(80)"),
            ("rejected_at",         "DATETIME"),
            ("decision_comment",    "TEXT"),
            ("change_reason",       "TEXT"),
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
            ("workflow_status",  "VARCHAR(24) DEFAULT 'APPROVED'"),
            ("updated_by",       "VARCHAR(80)"),
            ("approved_by",      "VARCHAR(80)"),
            ("approved_at",      "DATETIME"),
            ("rejected_by",      "VARCHAR(80)"),
            ("rejected_at",      "DATETIME"),
            ("decision_comment", "TEXT"),
            ("change_reason",    "TEXT"),
        ]:
            if col not in trade_cols:
                additions.append((
                    "trades", col,
                    f"ALTER TABLE trades ADD COLUMN {col} {ddl}",
                ))

    # bond_lots — record which source priced each lot (market | risk_parameters)
    if "bond_lots" in inspector.get_table_names():
        bl_cols = {c["name"] for c in inspector.get_columns("bond_lots")}
        if "price_source" not in bl_cols:
            additions.append((
                "bond_lots", "price_source",
                "ALTER TABLE bond_lots ADD COLUMN price_source VARCHAR(20)",
            ))

    if "instrument_reference" in inspector.get_table_names():
        ref_cols = {c["name"] for c in inspector.get_columns("instrument_reference")}
        for col, ddl in [
            ("security_type",     "VARCHAR(80)"),
            ("issuer_type",       "VARCHAR(80)"),
            ("coupon_rate_text",  "VARCHAR(120)"),
            ("quotation_type",    "VARCHAR(80)"),
            ("rating_source",     "VARCHAR(300)"),
            ("rating_agency",     "VARCHAR(80)"),
            ("source",            "VARCHAR(80)"),
            ("source_updated_at", "DATETIME"),
            ("float_index",       "VARCHAR(12)"),
            ("float_margin_pct",  "FLOAT"),
        ]:
            if col not in ref_cols:
                additions.append((
                    "instrument_reference", col,
                    f"ALTER TABLE instrument_reference ADD COLUMN {col} {ddl}",
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

    # KasePrice.duration used to be filled with KASE «dtm» (days to maturity),
    # which then polluted weighted durations.  Clear those values once.
    if "kase_prices" in inspector.get_table_names():
        with engine.begin() as conn:
            fixed = conn.execute(text(
                "UPDATE kase_prices SET duration = NULL "
                "WHERE duration IS NOT NULL AND (duration = dtm OR duration > 100)"
            )).rowcount
            if fixed:
                logger.info(f"[migrate] kase_prices.duration cleared for {fixed} rows (was dtm)")

    if "coupon_schedule" in inspector.get_table_names():
        cs_cols = {c["name"] for c in inspector.get_columns("coupon_schedule")}
        for col in ("margin_pct", "index_rate_pct"):
            if col not in cs_cols:
                additions.append(("coupon_schedule", col, f"ALTER TABLE coupon_schedule ADD COLUMN {col} FLOAT"))

    if "cash_movements" in inspector.get_table_names():
        cm_cols = {c["name"] for c in inspector.get_columns("cash_movements")}
        if "account" not in cm_cols:
            additions.append((
                "cash_movements", "account",
                "ALTER TABLE cash_movements ADD COLUMN account VARCHAR(40)",
            ))

    if additions:
        with engine.begin() as conn:
            for table, col, ddl in additions:
                try:
                    conn.execute(text(ddl))
                    logger.info(f"[migrate] {table}.{col} added")
                except Exception as exc:
                    logger.warning(f"[migrate] failed {table}.{col}: {exc!r}")

    # Legacy production databases stored the Risk Report code (SR_PAM_*) in
    # portfolio_type.  Preserve that code separately and restore the actual
    # business type so the reference API remains valid without changing CDU IDs.
    with engine.begin() as conn:
        fixed_cdus = conn.execute(text("""
            UPDATE cdu_registry
               SET report_code = COALESCE(NULLIF(report_code, ''), portfolio_type, portfolio_code),
                   portfolio_type = 'PRIVATE_CDU'
             WHERE portfolio_type LIKE 'SR_PAM_%'
        """)).rowcount
        if fixed_cdus:
            logger.info(f"[migrate] normalized {fixed_cdus} legacy CDU registry rows")

        # Old limit imports used the visible Russian caption as the key.  The
        # calculator and API use stable category codes; values themselves stay
        # untouched.
        if "cdu_limits" in inspector.get_table_names():
            fixed_limits = conn.execute(text("""
                UPDATE cdu_limits
                   SET instrument_category = CASE
                       WHEN TRIM(instrument_category) = 'Cash' THEN 'CASH'
                       WHEN instrument_category LIKE 'Государственные облигации%' THEN 'GOV_BONDS'
                       WHEN instrument_category LIKE 'Обратное REP%' THEN 'REVERSE_REPO'
                       WHEN instrument_category LIKE 'МФО (%' THEN 'MFO_BONDS'
                       WHEN instrument_category LIKE 'Агентские облигации%' THEN 'AGENCY_BONDS'
                       WHEN instrument_category LIKE 'Иностранные ЦБ%' THEN 'FOREIGN_BONDS'
                       WHEN instrument_category LIKE 'Депозит%' THEN 'DEPOSIT'
                       WHEN instrument_category LIKE 'Дебиторская задолженность%' THEN 'RECEIVABLES'
                       WHEN instrument_category LIKE 'Прочее%' THEN 'OTHER'
                       ELSE instrument_category
                   END
                 WHERE instrument_category NOT IN (
                     'CASH', 'GOV_BONDS', 'REVERSE_REPO', 'MFO_BONDS',
                     'AGENCY_BONDS', 'FOREIGN_BONDS', 'DEPOSIT',
                     'RECEIVABLES', 'OTHER'
                 )
            """)).rowcount
            if fixed_limits:
                logger.info(f"[migrate] normalized {fixed_limits} legacy CDU limit categories")


def init_db() -> None:
    """Create all tables (used at app startup)."""
    from models import db_models  # noqa: F401  ensures models are registered
    # 1) Add missing columns first (so create_all sees them)
    _apply_dev_migrations()
    # 2) Create any missing tables
    Base.metadata.create_all(bind=engine)
    # 3) Table rebuilds SQLite cannot do with ALTER
    _rebuild_nullable_columns()


def _rebuild_nullable_columns() -> None:
    """security_holdings.cdu_id became optional (instrument of the reference
    book without a manager).  SQLite cannot drop NOT NULL, so the table is
    rebuilt once, keeping all rows."""
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "security_holdings" not in inspector.get_table_names():
        return
    cols = {c["name"]: c for c in inspector.get_columns("security_holdings")}
    if "cdu_id" not in cols or cols["cdu_id"].get("nullable", True):
        return
    from models import db_models
    table = db_models.SecurityHolding.__table__
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        for (name,) in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='security_holdings' "
            "AND name NOT LIKE 'sqlite_autoindex%'"
        )).fetchall():
            conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
        conn.execute(text("ALTER TABLE security_holdings RENAME TO security_holdings_old"))
        table.create(bind=conn)
        new_cols = [c.name for c in table.columns]
        common = [c for c in new_cols if c in cols]
        col_list = ", ".join(f'"{c}"' for c in common)
        conn.execute(text(
            f"INSERT INTO security_holdings ({col_list}) SELECT {col_list} FROM security_holdings_old"
        ))
        conn.execute(text("DROP TABLE security_holdings_old"))
    logger.info("[migrate] security_holdings.cdu_id is now optional")
