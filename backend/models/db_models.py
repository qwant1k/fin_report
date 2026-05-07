"""SQLAlchemy ORM models — full schema as described in the spec."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


# ─────────────── REFERENCE: ЧДУ (Custodian / Investment Manager / NBRK Portfolio) ───────────────
class CDU(Base):
    """Носитель портфеля: ЧДУ или портфель НБ РК (собст/спец)."""
    __tablename__ = "cdu_registry"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    short_name: Mapped[str] = mapped_column(String(40), nullable=False)
    participant_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    participant_code_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    # PRIVATE_CDU | NBRK_OWN | NBRK_RESERVE
    portfolio_type: Mapped[str] = mapped_column(String(20), default="PRIVATE_CDU", index=True)
    # Для НБ РК — портфельный код в файле КФГД_ГГГГММДД (PORTFOLIO):
    # 310138-1 → собст, 300138-1 → спец
    portfolio_code: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    share_target_pct: Mapped[float] = mapped_column(Float, default=0.0)
    contact_email: Mapped[Optional[str]] = mapped_column(String(120))
    contact_manager: Mapped[Optional[str]] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    limits: Mapped[list["CDULimit"]] = relationship(back_populates="cdu", cascade="all, delete-orphan")
    files: Mapped[list["TradeFile"]] = relationship(back_populates="cdu", cascade="all, delete-orphan")


# ─────────────── REFERENCE: Лимиты по категориям инструментов ───────────────
class CDULimit(Base):
    __tablename__ = "cdu_limits"

    id: Mapped[int] = mapped_column(primary_key=True)
    cdu_id: Mapped[int] = mapped_column(ForeignKey("cdu_registry.id", ondelete="CASCADE"), index=True)
    instrument_category: Mapped[str] = mapped_column(String(40), nullable=False)
    min_limit_pct: Mapped[float] = mapped_column(Float, default=0.0)
    max_limit_pct: Mapped[float] = mapped_column(Float, default=0.0)
    hard_limit_pct: Mapped[float] = mapped_column(Float, default=0.0)
    soft_limit_pct: Mapped[float] = mapped_column(Float, default=0.0)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)

    cdu: Mapped["CDU"] = relationship(back_populates="limits")

    __table_args__ = (
        Index("ix_cdu_limit_cat", "cdu_id", "instrument_category"),
    )


# ─────────────── REFERENCE: Справочник инструментов / категорий ───────────────
class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    isin: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40), nullable=False)  # CASH/GOV_BONDS/...
    rating: Mapped[Optional[str]] = mapped_column(String(10))
    currency: Mapped[str] = mapped_column(String(8), default="KZT")
    duration_default: Mapped[Optional[float]] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ─────────────── REFERENCE: Категории + правила маппинга ───────────────
class InstrumentCategoryRule(Base):
    """Правило маппинга кода инструмента/режима в категорию (drag&drop редактируется)."""
    __tablename__ = "instrument_category_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    match_regime_in: Mapped[Optional[str]] = mapped_column(String(120))   # CSV
    match_code_prefix: Mapped[Optional[str]] = mapped_column(String(60))
    match_code_regex: Mapped[Optional[str]] = mapped_column(String(200))
    target_category: Mapped[str] = mapped_column(String(40), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# ─────────────── Файлы от ЧДУ ───────────────
class TradeFile(Base):
    __tablename__ = "trade_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    cdu_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    raw_file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="UPLOADED")  # UPLOADED/PARSED/ERROR/CALCULATED
    rows_parsed: Mapped[int] = mapped_column(Integer, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0)
    parse_errors_json: Mapped[Optional[str]] = mapped_column(Text)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    cdu: Mapped[Optional["CDU"]] = relationship(back_populates="files")
    trades: Mapped[list["RawTrade"]] = relationship(back_populates="file", cascade="all, delete-orphan")


# ─────────────── Сырые сделки ───────────────
class RawTrade(Base):
    __tablename__ = "raw_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("trade_files.id", ondelete="CASCADE"), index=True)
    cdu_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)

    deal_number: Mapped[Optional[str]] = mapped_column(String(40))      # Сделка №
    order_number: Mapped[Optional[str]] = mapped_column(String(40), index=True)  # Заявка №
    trade_time: Mapped[Optional[str]] = mapped_column(String(20))
    kp: Mapped[Optional[str]] = mapped_column(String(8))                # Разм/К/П
    operation_type: Mapped[Optional[str]] = mapped_column(String(20), index=True)  # BUY/SELL/REPO_OPEN/REPO_CLOSE/OTHER

    participant_code: Mapped[Optional[str]] = mapped_column(String(40))
    firm_code: Mapped[Optional[str]] = mapped_column(String(40))
    partner_code: Mapped[Optional[str]] = mapped_column(String(40))
    trade_account: Mapped[Optional[str]] = mapped_column(String(40))
    regime_code: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    instrument_code: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    instrument_category: Mapped[Optional[str]] = mapped_column(String(40), index=True)

    price: Mapped[Optional[float]] = mapped_column(Float)
    lots: Mapped[Optional[float]] = mapped_column(Float)
    volume: Mapped[Optional[float]] = mapped_column(Float)
    settlement_date: Mapped[Optional[date]] = mapped_column(Date)
    accrued_interest_volume: Mapped[Optional[float]] = mapped_column(Float)
    yield_pct: Mapped[Optional[float]] = mapped_column(Float)

    period_code: Mapped[Optional[str]] = mapped_column(String(20))
    redemption_price: Mapped[Optional[float]] = mapped_column(Float)
    settlement_code: Mapped[Optional[str]] = mapped_column(String(20))
    type_code: Mapped[Optional[str]] = mapped_column(String(20))
    commission_total: Mapped[Optional[float]] = mapped_column(Float)
    repo_rate_pct: Mapped[Optional[float]] = mapped_column(Float)
    accrued_interest_volume_repo: Mapped[Optional[float]] = mapped_column(Float)
    repo_sum: Mapped[Optional[float]] = mapped_column(Float)
    repo_buyback_sum: Mapped[Optional[float]] = mapped_column(Float)
    repo_term_days: Mapped[Optional[int]] = mapped_column(Integer)
    initial_discount_pct: Mapped[Optional[float]] = mapped_column(Float)
    discount_lower_pct: Mapped[Optional[float]] = mapped_column(Float)
    discount_upper_pct: Mapped[Optional[float]] = mapped_column(Float)

    commission_clearing: Mapped[Optional[float]] = mapped_column(Float)
    commission_trading: Mapped[Optional[float]] = mapped_column(Float)
    commission_tech: Mapped[Optional[float]] = mapped_column(Float)
    client_code: Mapped[Optional[str]] = mapped_column(String(40))
    currency_code: Mapped[Optional[str]] = mapped_column(String(8))
    system_link: Mapped[Optional[str]] = mapped_column(String(80))
    settlement_org: Mapped[Optional[str]] = mapped_column(String(40))
    trading_date: Mapped[Optional[date]] = mapped_column(Date)
    clearing_firm_code: Mapped[Optional[str]] = mapped_column(String(40))
    activity_flag: Mapped[Optional[str]] = mapped_column(String(20))
    status: Mapped[Optional[str]] = mapped_column(String(8), index=True)
    nominal_volume: Mapped[Optional[float]] = mapped_column(Float)
    clearing_account: Mapped[Optional[str]] = mapped_column(String(40))
    placement_price: Mapped[Optional[float]] = mapped_column(Float)
    placement_amount: Mapped[Optional[float]] = mapped_column(Float)
    placement_price_kzt: Mapped[Optional[float]] = mapped_column(Float)
    redemption_price_kzt: Mapped[Optional[float]] = mapped_column(Float)
    securities_to_execute: Mapped[Optional[float]] = mapped_column(Float)

    file: Mapped["TradeFile"] = relationship(back_populates="trades")

    __table_args__ = (
        Index("ix_raw_trade_date_cdu", "trade_date", "cdu_id"),
    )


# ─────────────── Позиции и итоги ───────────────
class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    cdu_id: Mapped[int] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    position_date: Mapped[date] = mapped_column(Date, index=True)
    instrument_code: Mapped[Optional[str]] = mapped_column(String(40))
    instrument_category: Mapped[str] = mapped_column(String(40), index=True)
    instrument_name: Mapped[Optional[str]] = mapped_column(String(200))
    nominal_volume: Mapped[Optional[float]] = mapped_column(Float)
    current_price: Mapped[Optional[float]] = mapped_column(Float)
    accrued_interest: Mapped[Optional[float]] = mapped_column(Float)
    market_value_current: Mapped[float] = mapped_column(Float, default=0.0)
    market_value_prev: Mapped[float] = mapped_column(Float, default=0.0)
    daily_change: Mapped[float] = mapped_column(Float, default=0.0)
    pct_of_total: Mapped[float] = mapped_column(Float, default=0.0)
    ytm: Mapped[Optional[float]] = mapped_column(Float)
    duration: Mapped[Optional[float]] = mapped_column(Float)
    hard_limit_status: Mapped[Optional[str]] = mapped_column(String(10))
    soft_limit_status: Mapped[Optional[str]] = mapped_column(String(10))
    free_limit_mln: Mapped[Optional[float]] = mapped_column(Float)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_pos_cdu_date_cat", "cdu_id", "position_date", "instrument_category"),
    )


class PortfolioSummary(Base):
    __tablename__ = "portfolio_summary"

    id: Mapped[int] = mapped_column(primary_key=True)
    cdu_id: Mapped[int] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    summary_date: Mapped[date] = mapped_column(Date, index=True)
    total_mv_prev: Mapped[float] = mapped_column(Float, default=0.0)
    total_daily_change: Mapped[float] = mapped_column(Float, default=0.0)
    total_mv_current: Mapped[float] = mapped_column(Float, default=0.0)
    cdu_share_pct: Mapped[float] = mapped_column(Float, default=0.0)
    ytm_weighted: Mapped[float] = mapped_column(Float, default=0.0)
    duration_weighted: Mapped[float] = mapped_column(Float, default=0.0)
    benchmark_duration: Mapped[Optional[float]] = mapped_column(Float)
    duration_status: Mapped[Optional[str]] = mapped_column(String(10))
    calculated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("cdu_id", "summary_date", name="uq_portfolio_summary_cdu_date"),
    )


# ─────────────── KASE котировки и сверка ───────────────
class KasePrice(Base):
    __tablename__ = "kase_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    instrument_code: Mapped[str] = mapped_column(String(40), index=True)
    isin: Mapped[Optional[str]] = mapped_column(String(20))
    instrument_name: Mapped[Optional[str]] = mapped_column(String(200))
    close_price: Mapped[Optional[float]] = mapped_column(Float)
    ytm: Mapped[Optional[float]] = mapped_column(Float)
    accrued_interest: Mapped[Optional[float]] = mapped_column(Float)
    duration: Mapped[Optional[float]] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    source: Mapped[str] = mapped_column(String(40), default="api")

    __table_args__ = (
        UniqueConstraint("trade_date", "instrument_code", name="uq_kase_price_date_code"),
    )


class PriceReconciliation(Base):
    __tablename__ = "price_reconciliation"

    id: Mapped[int] = mapped_column(primary_key=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("portfolio_positions.id", ondelete="CASCADE"), index=True)
    kase_price_id: Mapped[Optional[int]] = mapped_column(ForeignKey("kase_prices.id"))
    cdu_price: Mapped[Optional[float]] = mapped_column(Float)
    kase_price: Mapped[Optional[float]] = mapped_column(Float)
    deviation_pct: Mapped[Optional[float]] = mapped_column(Float)
    deviation_kzt: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(10), default="OK")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ─────────────── MBM индекс ───────────────
class MBMIndex(Base):
    __tablename__ = "mbm_index"

    id: Mapped[int] = mapped_column(primary_key=True)
    index_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    ytm_value: Mapped[Optional[float]] = mapped_column(Float)
    duration: Mapped[Optional[float]] = mapped_column(Float)
    mod_duration: Mapped[Optional[float]] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40), default="manual")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ─────────────── Алерты ───────────────
class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_date: Mapped[date] = mapped_column(Date, index=True)
    cdu_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    alert_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10), default="INFO")  # INFO/WARN/CRITICAL
    message: Mapped[str] = mapped_column(Text)
    details_json: Mapped[Optional[str]] = mapped_column(Text)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ─────────────── Сформированные отчёты ───────────────
class GeneratedReport(Base):
    __tablename__ = "generated_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    report_type: Mapped[str] = mapped_column(String(20), default="DAILY")
    file_path: Mapped[str] = mapped_column(String(500))
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    generated_by: Mapped[Optional[str]] = mapped_column(String(80))
    notes: Mapped[Optional[str]] = mapped_column(Text)


# ─────────────── Дебиторская задолженность ───────────────
class AccountReceivable(Base):
    __tablename__ = "accounts_receivable"

    id: Mapped[int] = mapped_column(primary_key=True)
    cdu_id: Mapped[int] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    record_date: Mapped[date] = mapped_column(Date, index=True)  # дата постановки на учёт = T
    isin: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    counterparty: Mapped[Optional[str]] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(8), default="KZT")
    amount: Mapped[float] = mapped_column(Float, default=0.0)             # начальная сумма (валюта)
    amount_kzt: Mapped[Optional[float]] = mapped_column(Float)            # KZT-эквивалент
    balance_currency: Mapped[Optional[float]] = mapped_column(Float)      # текущий остаток в валюте
    balance_kzt: Mapped[float] = mapped_column(Float, default=0.0)        # текущий остаток в KZT
    due_date: Mapped[Optional[date]] = mapped_column(Date)                # ожидаемая дата
    actual_value_date: Mapped[Optional[date]] = mapped_column(Date)       # фактическая дата поступления
    status: Mapped[str] = mapped_column(String(20), default="OPEN")       # OPEN/CLOSED/PARTIAL/PENDING
    related_event_type: Mapped[Optional[str]] = mapped_column(String(20)) # COUPON/REDEMPTION/OTHER
    related_trade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trades.id"))
    portfolio_code: Mapped[Optional[str]] = mapped_column(String(20))     # для НБ РК (собст/спец)
    source_doc_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_documents.id"))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_ar_cdu_isin_date", "cdu_id", "isin", "record_date"),
    )


# ─────────────── Cash остатки ─────────────── 
class CashBalance(Base):
    __tablename__ = "cash_balances"

    id: Mapped[int] = mapped_column(primary_key=True)
    cdu_id: Mapped[int] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    balance_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="KZT")
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[Optional[str]] = mapped_column(String(200))

    __table_args__ = (
        UniqueConstraint("cdu_id", "balance_date", "currency", name="uq_cash_cdu_date_ccy"),
    )


# ─────────────── Пользователи ───────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(150))
    email: Mapped[Optional[str]] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # admin/analyst/viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


# ─────────────── Аудит-лог ───────────────
class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    user: Mapped[Optional[str]] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(40))
    entity: Mapped[Optional[str]] = mapped_column(String(60))
    entity_id: Mapped[Optional[int]] = mapped_column(Integer)
    details: Mapped[Optional[str]] = mapped_column(Text)


# ─────────────── Формулы (drag&drop конструктор) ───────────────
class FormulaDefinition(Base):
    """Декларативное описание формулы для расчёта. Редактируется в админке drag&drop."""
    __tablename__ = "formula_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)
    target: Mapped[str] = mapped_column(String(40))      # CMV/YTM/DURATION/PCT/...
    expression_json: Mapped[str] = mapped_column(Text)    # AST из drag&drop конструктора
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[Optional[str]] = mapped_column(String(80))


# ─────────────── Снимки расчётов ───────────────
class CalculationRun(Base):
    """Каждый запуск расчёта — для аудита и idempotent rerun."""
    __tablename__ = "calculation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    triggered_by: Mapped[Optional[str]] = mapped_column(String(80))
    cdus_processed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)


# ═══════════════════════════════════════════════════════════════════════════
# Phase A: расширенная модель для полного бизнес-процесса
# ═══════════════════════════════════════════════════════════════════════════


# ─────────────── Источник первичного документа ───────────────
class SourceDocument(Base):
    """Любой импортированный файл (Trade Report, Holdings, биржевик, выписка,
    Risk Report XLSM, КФГД_ГГГГММДД и т.п.). Используется для аудита и
    привязки конкретных строк Trades/AR/Lots/Snapshots к их источнику."""
    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    # TRADE_REPORT / HOLDINGS / CERTIFICATE_PDF / CERTIFICATE_PNG / CERTIFICATE_DOCX
    # / RECONCILIATION / STATEMENT_PDF / RISK_REPORT_XLSM / NBRK_KFGD / OTHER
    doc_type: Mapped[str] = mapped_column(String(40), index=True)
    cdu_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    doc_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    file_name: Mapped[str] = mapped_column(String(300))
    file_path: Mapped[str] = mapped_column(String(800))
    sha256: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(80))
    parsed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    parse_status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING/OK/ERROR/SKIPPED
    parse_meta_json: Mapped[Optional[str]] = mapped_column(Text)
    parse_errors: Mapped[Optional[str]] = mapped_column(Text)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_srcdoc_type_cdu_date", "doc_type", "cdu_id", "doc_date"),
    )


# ─────────────── Trades — единый журнал операций (источник истины) ───────────────
class Trade(Base):
    """Главный журнал. Каждая операция (BUY/SELL/REPO/COUPON/REDEMPTION/DEPOSIT/FX/CASH)
    — одна строка. Используется как источник истины для всех расчётов и сверок."""
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    cdu_id: Mapped[int] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)              # T
    value_date: Mapped[date] = mapped_column(Date, index=True)              # дата расчётов
    # BUY / SELL / REPO_OPEN / REPO_CLOSE / COUPON / REDEMPTION /
    # DEPOSIT_OPEN / DEPOSIT_CLOSE / FX_BUY / FX_SELL / CASH_TOPUP / CASH_WITHDRAW / OTHER
    operation_type: Mapped[str] = mapped_column(String(20), index=True)
    direction: Mapped[Optional[str]] = mapped_column(String(20))            # Покупка/Продажа (для REPO)
    # BOND / REPO / DEPOSIT / CASH / FX
    instrument_kind: Mapped[Optional[str]] = mapped_column(String(20))
    # CASH / GOV_BONDS / AGENCY_BONDS / MFO_BONDS / FOREIGN_BONDS / REVERSE_REPO / DEPOSIT
    instrument_category: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    instrument_code: Mapped[Optional[str]] = mapped_column(String(40), index=True)  # тикер
    isin: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    deal_id: Mapped[Optional[str]] = mapped_column(String(40), index=True)   # биржевой ID
    portfolio_code: Mapped[Optional[str]] = mapped_column(String(20))        # для НБ РК

    # Cash flow
    amount_kzt: Mapped[float] = mapped_column(Float, default=0.0)            # знаковый: -отток / +приток
    amount_ccy: Mapped[Optional[float]] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="KZT")
    fx_rate: Mapped[Optional[float]] = mapped_column(Float)

    # Quantity / nominal
    quantity: Mapped[Optional[float]] = mapped_column(Float)                 # кол-во бумаг
    nominal_per_unit: Mapped[Optional[float]] = mapped_column(Float)
    face_value: Mapped[Optional[float]] = mapped_column(Float)               # quantity * nominal

    # Price / yield
    clean_price: Mapped[Optional[float]] = mapped_column(Float)              # чистая
    dirty_price: Mapped[Optional[float]] = mapped_column(Float)              # грязная
    market_price: Mapped[Optional[float]] = mapped_column(Float)             # рыночная при сделке
    accrued_interest: Mapped[Optional[float]] = mapped_column(Float)
    ytm: Mapped[Optional[float]] = mapped_column(Float)
    interest_rate_pct: Mapped[Optional[float]] = mapped_column(Float)        # для депозитов

    # REPO-specific
    repo_rate_pct: Mapped[Optional[float]] = mapped_column(Float)
    repo_open_price: Mapped[Optional[float]] = mapped_column(Float)
    repo_close_price: Mapped[Optional[float]] = mapped_column(Float)
    repo_term_days: Mapped[Optional[int]] = mapped_column(Integer)
    repo_buyback_sum: Mapped[Optional[float]] = mapped_column(Float)

    # Deposit-specific
    deposit_principal: Mapped[Optional[float]] = mapped_column(Float)
    deposit_term_days: Mapped[Optional[int]] = mapped_column(Integer)

    # Commissions
    commission_clearing: Mapped[Optional[float]] = mapped_column(Float)
    commission_kase: Mapped[Optional[float]] = mapped_column(Float)
    commission_total: Mapped[Optional[float]] = mapped_column(Float)

    # Audit
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)        # сгенерировано системой (купон/погашение)
    source_doc_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_documents.id"), index=True)
    source_row_idx: Mapped[Optional[int]] = mapped_column(Integer)            # № строки в исходном файле
    raw_trade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("raw_trades.id"))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by: Mapped[Optional[str]] = mapped_column(String(80))

    __table_args__ = (
        Index("ix_trades_cdu_date_op", "cdu_id", "trade_date", "operation_type"),
        Index("ix_trades_isin_date", "isin", "trade_date"),
        Index("ix_trades_dealid", "deal_id"),
    )


# ─────────────── Cash snapshot — ежедневные остатки ───────────────
class CashSnapshot(Base):
    """Снимок остатка денежных средств на дату T в разрезе ЧДУ/портфеля и валюты.
    Аналог листа `Cash` в Risk Report. Заполняется макросом «Space X» в оригинале."""
    __tablename__ = "cash_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    cdu_id: Mapped[int] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="KZT")
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    amount_kzt: Mapped[Optional[float]] = mapped_column(Float)
    fx_rate: Mapped[Optional[float]] = mapped_column(Float)
    portfolio_code: Mapped[Optional[str]] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(40), default="rr_import")
    source_doc_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_documents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("cdu_id", "snapshot_date", "currency", "portfolio_code",
                         name="uq_cashsnap_cdu_date_ccy_pf"),
    )


# ─────────────── MV snapshot — ежедневный портфельный срез ───────────────
class MVSnapshot(Base):
    """Снимок портфельных метрик на дату T (аналог листа `MV` в Risk Report)."""
    __tablename__ = "mv_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    cdu_id: Mapped[int] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    portfolio_code: Mapped[Optional[str]] = mapped_column(String(20))

    cash_flow: Mapped[Optional[float]] = mapped_column(Float)
    market_value_total: Mapped[float] = mapped_column(Float, default=0.0)
    market_value_cash: Mapped[Optional[float]] = mapped_column(Float)
    market_value_securities: Mapped[Optional[float]] = mapped_column(Float)  # ГЦБ+Агентские+МФО+Ин.ЦБ
    market_value_repo: Mapped[Optional[float]] = mapped_column(Float)
    market_value_deposit: Mapped[Optional[float]] = mapped_column(Float)
    market_value_ar: Mapped[Optional[float]] = mapped_column(Float)
    return_pct: Mapped[Optional[float]] = mapped_column(Float)
    ytm_weighted: Mapped[Optional[float]] = mapped_column(Float)
    duration_weighted: Mapped[Optional[float]] = mapped_column(Float)

    source: Mapped[str] = mapped_column(String(40), default="rr_import")
    source_doc_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_documents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("cdu_id", "snapshot_date", "portfolio_code",
                         name="uq_mvsnap_cdu_date_pf"),
    )


# ─────────────── Справочник эмиссий (InstrumentReference) ───────────────
class InstrumentReference(Base):
    """Справочник выпусков ЦБ — единый каталог по ISIN (см. лист `Справочник` в RR)."""
    __tablename__ = "instrument_reference"

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    nin: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    ticker_kase: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    instrument_name: Mapped[Optional[str]] = mapped_column(String(300))
    issuer: Mapped[Optional[str]] = mapped_column(String(200))
    bond_type: Mapped[Optional[str]] = mapped_column(String(40))    # ГЦБ/Агентские/МФО/Ин.ЦБ
    # Coupon
    coupon_rate_pct: Mapped[Optional[float]] = mapped_column(Float)
    coupon_type: Mapped[Optional[str]] = mapped_column(String(20))  # fix/float/zero
    frequency: Mapped[Optional[int]] = mapped_column(Integer)       # 1/2/4
    base: Mapped[Optional[str]] = mapped_column(String(20))         # 30/360, act/360, act/act
    base_code: Mapped[Optional[str]] = mapped_column(String(10))
    nominal: Mapped[Optional[float]] = mapped_column(Float)
    # Dates
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    maturity_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    last_coupon_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    next_coupon_date: Mapped[Optional[date]] = mapped_column(Date)
    # Misc
    currency: Mapped[str] = mapped_column(String(8), default="KZT")
    rating: Mapped[Optional[str]] = mapped_column(String(10))
    coupon_history_json: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[Optional[str]] = mapped_column(String(80))


# ─────────────── BondLot — лот ЦБ (1 покупка = 1 лот; FIFO при продаже) ───────────────
class BondLot(Base):
    __tablename__ = "bond_lots"

    id: Mapped[int] = mapped_column(primary_key=True)
    cdu_id: Mapped[int] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    isin: Mapped[str] = mapped_column(String(20), index=True)
    instrument_code: Mapped[Optional[str]] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(40), index=True)   # GOV_BONDS/AGENCY_BONDS/MFO_BONDS/FOREIGN_BONDS

    trade_date: Mapped[date] = mapped_column(Date, index=True)
    valuation_date: Mapped[date] = mapped_column(Date, index=True)
    settlement_date: Mapped[Optional[date]] = mapped_column(Date)

    quantity_initial: Mapped[float] = mapped_column(Float, default=0.0)
    quantity_current: Mapped[float] = mapped_column(Float, default=0.0)
    nominal_per_unit: Mapped[Optional[float]] = mapped_column(Float)
    face_value_initial: Mapped[float] = mapped_column(Float, default=0.0)
    face_value_current: Mapped[float] = mapped_column(Float, default=0.0)

    purchase_price: Mapped[Optional[float]] = mapped_column(Float)
    market_price: Mapped[Optional[float]] = mapped_column(Float)
    accrued_interest: Mapped[Optional[float]] = mapped_column(Float)
    market_value: Mapped[Optional[float]] = mapped_column(Float)
    total_value: Mapped[Optional[float]] = mapped_column(Float)
    weight: Mapped[Optional[float]] = mapped_column(Float)
    ytm: Mapped[Optional[float]] = mapped_column(Float)
    duration: Mapped[Optional[float]] = mapped_column(Float)

    maturity_status: Mapped[Optional[str]] = mapped_column(String(20))  # active/matured/выбыл
    portfolio_code: Mapped[Optional[str]] = mapped_column(String(20))
    open_trade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trades.id"))
    source_doc_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_documents.id"))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_bondlot_cdu_isin_date", "cdu_id", "isin", "valuation_date"),
    )


# ─────────────── RepoLot — открытое REPO ───────────────
class RepoLot(Base):
    __tablename__ = "repo_lots"

    id: Mapped[int] = mapped_column(primary_key=True)
    cdu_id: Mapped[int] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    instrument_code: Mapped[Optional[str]] = mapped_column(String(40))
    isin: Mapped[Optional[str]] = mapped_column(String(20))
    deal_id: Mapped[Optional[str]] = mapped_column(String(40), index=True)

    trade_date: Mapped[date] = mapped_column(Date, index=True)
    valuation_date: Mapped[date] = mapped_column(Date, index=True)
    close_date: Mapped[Optional[date]] = mapped_column(Date, index=True)

    face_value: Mapped[float] = mapped_column(Float, default=0.0)        # сумма репо (открытие)
    close_value: Mapped[Optional[float]] = mapped_column(Float)          # сумма выкупа
    repo_rate_pct: Mapped[Optional[float]] = mapped_column(Float)
    base: Mapped[int] = mapped_column(Integer, default=366)
    accrued_interest: Mapped[Optional[float]] = mapped_column(Float)
    term_days: Mapped[Optional[int]] = mapped_column(Integer)
    market_value: Mapped[Optional[float]] = mapped_column(Float)
    weight: Mapped[Optional[float]] = mapped_column(Float)
    ytm: Mapped[Optional[float]] = mapped_column(Float)
    duration: Mapped[Optional[float]] = mapped_column(Float)
    maturity_status: Mapped[Optional[str]] = mapped_column(String(20))

    portfolio_code: Mapped[Optional[str]] = mapped_column(String(20))
    open_trade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trades.id"))
    close_trade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trades.id"))
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    source_doc_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_documents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_repo_cdu_date", "cdu_id", "valuation_date"),
    )


# ─────────────── DepositLot — депозит (для НБ РК) ───────────────
class DepositLot(Base):
    __tablename__ = "deposit_lots"

    id: Mapped[int] = mapped_column(primary_key=True)
    cdu_id: Mapped[int] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    deal_id: Mapped[Optional[str]] = mapped_column(String(40))
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    valuation_date: Mapped[date] = mapped_column(Date, index=True)
    close_date: Mapped[Optional[date]] = mapped_column(Date, index=True)

    principal: Mapped[float] = mapped_column(Float, default=0.0)
    interest_rate_pct: Mapped[Optional[float]] = mapped_column(Float)
    base: Mapped[int] = mapped_column(Integer, default=360)
    term_days: Mapped[Optional[int]] = mapped_column(Integer)
    accrued_interest: Mapped[Optional[float]] = mapped_column(Float)
    market_value: Mapped[Optional[float]] = mapped_column(Float)
    weight: Mapped[Optional[float]] = mapped_column(Float)
    duration: Mapped[Optional[float]] = mapped_column(Float)
    ytm: Mapped[Optional[float]] = mapped_column(Float)
    maturity_status: Mapped[Optional[str]] = mapped_column(String(20))

    portfolio_code: Mapped[Optional[str]] = mapped_column(String(20))
    open_trade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trades.id"))
    close_trade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trades.id"))
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    source_doc_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_documents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ─────────────── FXRate — курсы НБ РК ───────────────
class FXRate(Base):
    __tablename__ = "fx_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    rate: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40), default="nbrk")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("rate_date", "currency", name="uq_fx_date_ccy"),
    )


# ─────────────── Coupon / Redemption events ───────────────
class CouponEvent(Base):
    """Событие купонной выплаты по позиции на дату T (Last coupon date = T)."""
    __tablename__ = "coupon_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    cdu_id: Mapped[int] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    isin: Mapped[str] = mapped_column(String(20), index=True)
    event_date: Mapped[date] = mapped_column(Date, index=True)         # = T (last coupon)
    expected_amount: Mapped[float] = mapped_column(Float)               # из Accrued interest (debet)
    coupon_rate_pct: Mapped[Optional[float]] = mapped_column(Float)
    base: Mapped[Optional[str]] = mapped_column(String(20))
    value_date: Mapped[Optional[date]] = mapped_column(Date)            # End of last coupon (KASE)
    actual_value_date: Mapped[Optional[date]] = mapped_column(Date)
    portfolio_code: Mapped[Optional[str]] = mapped_column(String(20))
    trade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trades.id"))
    ar_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts_receivable.id"))
    status: Mapped[str] = mapped_column(String(20), default="PLANNED")  # PLANNED/PAID/PENDING/PARTIAL
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("cdu_id", "isin", "event_date", "portfolio_code",
                         name="uq_coupon_event"),
    )


class RedemptionEvent(Base):
    """Событие погашения по позиции на дату T (Maturity = T)."""
    __tablename__ = "redemption_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    cdu_id: Mapped[int] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    isin: Mapped[str] = mapped_column(String(20), index=True)
    event_date: Mapped[date] = mapped_column(Date, index=True)         # Maturity = T
    face_value: Mapped[float] = mapped_column(Float)                    # номинал к погашению
    coupon_amount: Mapped[Optional[float]] = mapped_column(Float)       # купон по погашаемой бумаге
    coupon_base: Mapped[Optional[str]] = mapped_column(String(20))
    value_date: Mapped[Optional[date]] = mapped_column(Date)
    actual_value_date: Mapped[Optional[date]] = mapped_column(Date)
    portfolio_code: Mapped[Optional[str]] = mapped_column(String(20))
    trade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trades.id"))
    coupon_trade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trades.id"))
    ar_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts_receivable.id"))
    status: Mapped[str] = mapped_column(String(20), default="PLANNED")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("cdu_id", "isin", "event_date", "portfolio_code",
                         name="uq_redemption_event"),
    )


# ─────────────── ReconciliationResult — результаты сверок ───────────────
class ReconciliationResult(Base):
    """Результат любой автосверки (Trade↔биржевик / RR↔файл сверки / Cash↔выписка)."""
    __tablename__ = "reconciliation_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    recon_date: Mapped[date] = mapped_column(Date, index=True)
    cdu_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cdu_registry.id"), index=True)
    # TRADE_VS_CERT / RR_VS_RECONCILIATION / CASH_VS_STATEMENT / NBRK_AC_FALLBACK
    recon_type: Mapped[str] = mapped_column(String(40), index=True)
    field: Mapped[Optional[str]] = mapped_column(String(80))            # Cash / ЦБ / Repo / AR / Total / DealID
    key_id: Mapped[Optional[str]] = mapped_column(String(80))            # DealID / ISIN / счёт
    expected_value: Mapped[Optional[float]] = mapped_column(Float)
    actual_value: Mapped[Optional[float]] = mapped_column(Float)
    deviation: Mapped[Optional[float]] = mapped_column(Float)
    tolerance: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="OK")        # OK/WARN/MISMATCH/MISSING
    source_doc_a_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_documents.id"))
    source_doc_b_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_documents.id"))
    details_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ─────────────── ImportJob — групповой импорт (история) ───────────────
class ImportJob(Base):
    """Запуск bulk-импорта (например, исторических Risk Report за полугодие)."""
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(40), index=True)        # HISTORIC_RR / FOLDER_PRIMARY
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")   # RUNNING/DONE/FAILED/PARTIAL
    triggered_by: Mapped[Optional[str]] = mapped_column(String(80))
    files_total: Mapped[int] = mapped_column(Integer, default=0)
    files_done: Mapped[int] = mapped_column(Integer, default=0)
    files_failed: Mapped[int] = mapped_column(Integer, default=0)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    log: Mapped[Optional[str]] = mapped_column(Text)
    params_json: Mapped[Optional[str]] = mapped_column(Text)

