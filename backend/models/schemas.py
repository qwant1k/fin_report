"""Pydantic v2 schemas for API I/O."""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

InstrumentCategory = Literal[
    "CASH",
    "GOV_BONDS",
    "REVERSE_REPO",
    "MFO_BONDS",
    "AGENCY_BONDS",
    "FOREIGN_BONDS",
    "DEPOSIT",
    "RECEIVABLES",
    "OTHER",
]
OperationType = Literal[
    "BUY",
    "SELL",
    "REPO_HEADER",
    "REPO_BUY",
    "REPO_SELL",
    "REPO_OPEN",
    "REPO_CLOSE",
    "COUPON",
    "REDEMPTION",
    "DEPOSIT_OPEN",
    "DEPOSIT_CLOSE",
    "FX_BUY",
    "FX_SELL",
    "CASH_TOPUP",
    "CASH_WITHDRAW",
    "OTHER",
]
PortfolioType = Literal["PRIVATE_CDU", "NBRK_OWN", "NBRK_RESERVE"]
LimitStatus = Literal["ok", "breach", "warn"]
Severity = Literal["INFO", "WARN", "CRITICAL"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ───────── ЧДУ ─────────
class CDUBase(BaseModel):
    name: str
    short_name: str
    participant_code: str
    participant_code_prefix: str
    portfolio_type: str = "PRIVATE_CDU"
    portfolio_code: Optional[str] = None
    share_target_pct: float = 0.0
    contact_email: Optional[str] = None
    contact_manager: Optional[str] = None
    is_active: bool = True


class CDUCreate(CDUBase):
    pass


class CDUUpdate(BaseModel):
    name: Optional[str] = None
    short_name: Optional[str] = None
    participant_code: Optional[str] = None
    participant_code_prefix: Optional[str] = None
    portfolio_type: Optional[str] = None
    portfolio_code: Optional[str] = None
    share_target_pct: Optional[float] = None
    contact_email: Optional[str] = None
    contact_manager: Optional[str] = None
    is_active: Optional[bool] = None


class CDU(ORMModel, CDUBase):
    id: int
    created_at: datetime
    updated_at: datetime


# ───────── Лимиты ─────────
class CDULimitBase(BaseModel):
    cdu_id: int
    instrument_category: InstrumentCategory
    min_limit_pct: float = 0.0
    max_limit_pct: float = 0.0
    hard_limit_pct: float = 0.0
    soft_limit_pct: float = 0.0
    valid_from: date
    valid_to: Optional[date] = None


class CDULimitCreate(CDULimitBase):
    pass


class CDULimit(ORMModel, CDULimitBase):
    id: int


# ───────── Инструменты ─────────
class InstrumentBase(BaseModel):
    code: str
    isin: Optional[str] = None
    name: Optional[str] = None
    category: InstrumentCategory
    rating: Optional[str] = None
    currency: str = "KZT"
    duration_default: Optional[float] = None
    is_active: bool = True


class Instrument(ORMModel, InstrumentBase):
    id: int


# ───────── Загрузки ─────────
class TradeFileBrief(ORMModel):
    id: int
    cdu_id: Optional[int]
    trade_date: date
    filename: str
    uploaded_at: datetime
    uploaded_by: Optional[str] = None
    status: str
    rows_parsed: int
    rows_skipped: int
    sha256: Optional[str] = None


class UploadResponse(BaseModel):
    file_id: int
    cdu_id: Optional[int]
    cdu_name: Optional[str]
    trade_date: date
    rows_parsed: int
    rows_skipped: int
    warnings: List[str] = []
    # Price reconciliation summary against KASE (Phase 2). Filled only after a
    # successful import; ``None`` when the price check could not be executed
    # (no CDU resolved, no KASE data yet, etc.).
    price_check: Optional[dict] = None


# ───────── Position / Summary ─────────
class PortfolioPositionRow(ORMModel):
    id: int
    cdu_id: int
    position_date: date
    instrument_code: Optional[str]
    instrument_category: str
    instrument_name: Optional[str]
    nominal_volume: Optional[float]
    current_price: Optional[float]
    market_value_current: float
    market_value_prev: float
    daily_change: float
    pct_of_total: float
    ytm: Optional[float]
    duration: Optional[float]
    hard_limit_status: Optional[str]
    soft_limit_status: Optional[str]
    free_limit_mln: Optional[float]


class PortfolioSummaryRow(ORMModel):
    id: int
    cdu_id: int
    summary_date: date
    total_mv_prev: float
    total_daily_change: float
    total_mv_current: float
    cdu_share_pct: float
    ytm_weighted: float
    duration_weighted: float
    benchmark_duration: Optional[float]
    duration_status: Optional[str]
    calculated_at: datetime


# ───────── Dashboard ─────────
class CategoryRow(BaseModel):
    category: str
    label: str
    market_value_prev: float
    daily_change: float
    market_value_current: float
    pct_of_total: float
    ytm: Optional[float]
    duration: Optional[float]
    min_limit_pct: float
    max_limit_pct: float
    hard_limit: str
    soft_limit: str
    free_limit_mln: Optional[float]


class CDUBlock(BaseModel):
    cdu_id: int
    cdu_name: str
    cdu_short: str
    rows: List[CategoryRow]
    total_mv_prev: float
    total_daily_change: float
    total_mv_current: float
    total_pct: float
    ytm_weighted: float
    duration_weighted: float
    benchmark_duration: Optional[float]
    duration_lower: Optional[float]
    duration_upper: Optional[float]
    duration_status: Optional[str]
    cdu_share_pct: float


class DashboardResponse(BaseModel):
    report_date: date
    fund_total_mv: float
    fund_total_mv_prev: float
    fund_daily_change: float
    fund_daily_change_pct: float
    fund_ytm_weighted: float
    fund_duration_weighted: float
    benchmark_ytm: Optional[float]
    benchmark_duration: Optional[float]
    breaches_count: int
    # Phase 3 — operational KPIs
    pending_approvals_count: int = 0
    flagged_prices_count: int = 0
    blocks: List[CDUBlock]


# ───────── Алерты ─────────
class AlertOut(ORMModel):
    id: int
    alert_date: date
    cdu_id: Optional[int]
    alert_type: str
    severity: str
    message: str
    is_resolved: bool
    created_at: datetime


# ───────── Auth ─────────
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    full_name: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)


class UserOut(ORMModel):
    id: int
    username: str
    full_name: Optional[str]
    email: Optional[str]
    role: str
    is_active: bool
    created_at: datetime
    permissions: List[str] = Field(default_factory=list)


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: str = "viewer"


class PermissionCatalogItem(BaseModel):
    code: str
    group: str
    label: str


class RoleDefinitionOut(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)
    is_system: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RoleDefinitionCreate(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)
    is_active: bool = True


class RoleDefinitionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[List[str]] = None
    is_active: Optional[bool] = None


# ───────── KASE / MBM ─────────
class KasePriceOut(ORMModel):
    id: int
    trade_date: date
    instrument_code: str
    isin: Optional[str]
    instrument_name: Optional[str]
    close_price: Optional[float]
    ytm: Optional[float]
    accrued_interest: Optional[float]
    duration: Optional[float]
    sec_type: Optional[str] = None
    fin_sec_ru: Optional[str] = None
    fin_sec_en: Optional[str] = None
    fin_sec_kz: Optional[str] = None
    org_code: Optional[str] = None
    org_name_ru: Optional[str] = None
    org_name_en: Optional[str] = None
    org_name_kz: Optional[str] = None
    settlement_price: Optional[float] = None
    settlement_dirty_price: Optional[float] = None
    dohod: Optional[float] = None
    dtm: Optional[float] = None
    kase_ytm: Optional[float] = None
    unit_ru: Optional[str] = None
    unit_en: Optional[str] = None
    unit_kz: Optional[str] = None
    fetched_at: datetime
    source: str


class MBMOut(ORMModel):
    id: int
    index_date: date
    ytm_value: Optional[float]
    duration: Optional[float]
    mod_duration: Optional[float] = None
    source: str
    fetched_at: datetime


# ───────── Формулы ─────────
class FormulaDefinitionOut(ORMModel):
    id: int
    code: str
    name: str
    description: Optional[str]
    target: str
    expression_json: str
    is_active: bool
    version: int
    updated_at: datetime
    updated_by: Optional[str]


class FormulaDefinitionUpsert(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    target: str
    expression_json: str
    is_active: bool = True


# ───────── Generated reports / approval workflow (Phase 3) ─────────
ReportStatus = Literal["draft", "pending_approval", "approved", "rejected"]


class GeneratedReportOut(ORMModel):
    id: int
    report_date: date
    report_type: str
    file_path: str
    generated_at: datetime
    generated_by: Optional[str]
    notes: Optional[str]
    status: ReportStatus
    submitted_by: Optional[str] = None
    submitted_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejection_comment: Optional[str] = None
    version: int = 1
    parent_report_id: Optional[int] = None


class ReportRejectRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)


# ───────── Calculation ─────────
class CalculateRequest(BaseModel):
    report_date: date
    recalculate: bool = False


class CalculateResponse(BaseModel):
    report_date: date
    cdus_processed: int
    breaches_count: int
    duration_seconds: float
