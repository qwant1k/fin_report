"""Application configuration loaded from environment / .env file."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


_BACKEND_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    # ``.env`` is looked up both in the project root (where .env.example and
    # docker-compose expect it) and in backend/ (current working directory of
    # «uvicorn main:app»); the later file wins.  Previously only ./.env was
    # read, so running from backend/ silently used the insecure defaults.
    model_config = SettingsConfigDict(
        env_file=(str(_BACKEND_DIR.parent / ".env"), str(_BACKEND_DIR / ".env"), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_tz: str = "Asia/Almaty"
    secret_key: str = "change-me-please-32chars-min-1234567890"
    initial_data_mode: str = "full"

    # Database
    database_url: str = "sqlite:///./data/fund_reporting.db"

    # Storage
    upload_dir: str = "./data/uploads"
    report_dir: str = "./data/reports"
    log_dir: str = "./data/logs"
    risk_report_password: str = "7"

    # KASE
    kase_bonds_url: str = "https://kase.kz/ru/markets/markets-valuation/market-prices"
    kase_repo_url: str = "https://kase.kz/ru/repo/"
    kase_indices_url: str = "https://kase.kz/ru/indices/"
    kase_risk_params_url: str = "https://kase.kz/ru/app-gateway/documents/risk"
    kase_cache_ttl_seconds: int = 1800
    # KASE public JSON API used by kase.kz itself (Angular SSR):
    #   /api/instruments/coupon-payments/{code}
    #   /api/instruments/{gsecs|bonds}/{code}/characteristics
    #   /api/instruments/securities/{code} · /api/instruments/securities?search={isin}
    kase_api_base_url: str = "https://kase.kz/api"
    # refresh coupon schedules of held instruments with the daily KASE job
    kase_coupon_refresh_daily: bool = True
    kase_tonia_xlsx_url: str = "https://kase.kz/api/indicators/tonia-compounded/archive-xls"
    kase_tonia_start_date: date = date(2024, 1, 1)
    kase_tonia_fetch_daily: bool = True
    kase_tonia_cron_hour: int = 20
    kase_tonia_cron_minute: int = 10
    kase_tonia_lookback_days: int = 7

    # Price reconciliation tolerance vs KASE (fraction, 0.0001 = 0.01% = 1 bp).
    # If |price_cdu - price_kase| / price_kase > tolerance, Trade.price_flag is
    # set, price_final is replaced with price_kase, and the change is audited.
    price_tolerance_pct: float = 0.0001
    # Express audit after Trade Report upload. Amounts are compared with the
    # average of earlier comparable operations (25% by default).
    upload_amount_tolerance_pct: float = 0.25
    upload_anomaly_history_limit: int = 20

    # MBM
    nbrk_mbm_url: str = "https://nationalbank.kz/ru/page/mbm"
    nbrk_rates_url: str = "https://nationalbank.kz/ru/rates/"
    kase_mbm_xlsx_url: str = "https://kase.kz/api/indicators/mbm-index/archive-xls"
    kase_mbm_start_date: date = date(2020, 1, 1)

    # Scheduler
    kase_fetch_cron_hour: int = 18
    kase_fetch_cron_minute: int = 0

    # SMTP
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "fund-reporting@kdif.kz"

    # Auth
    admin_username: str = "admin"
    admin_password: str = "admin"
    jwt_secret: str = "please-change-me-jwt-secret-32-chars"
    jwt_ttl_minutes: int = 120

    # CORS
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    cors_origin_regex: str = ""

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cors_origin_regex_value(self) -> str | None:
        explicit = self.cors_origin_regex.strip()
        if explicit:
            return explicit
        if self.app_env == "development":
            return r"https?://(localhost|127\.0\.0\.1):\d+"
        return None

    @property
    def upload_path(self) -> Path:
        p = Path(self.upload_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def report_path(self) -> Path:
        p = Path(self.report_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def log_path(self) -> Path:
        p = Path(self.log_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()

_INSECURE_DEFAULTS = {
    "jwt_secret": "please-change-me-jwt-secret-32-chars",
    "secret_key": "change-me-please-32chars-min-1234567890",
    "admin_password": "admin",
}


def insecure_settings() -> List[str]:
    """Names of security settings still equal to the published defaults."""
    return [name for name, value in _INSECURE_DEFAULTS.items() if getattr(settings, name) == value]
