"""Application configuration loaded from environment / .env file."""
from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
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

    # Database
    database_url: str = "sqlite:///./data/fund_reporting.db"

    # Storage
    upload_dir: str = "./data/uploads"
    report_dir: str = "./data/reports"
    log_dir: str = "./data/logs"

    # KASE
    kase_bonds_url: str = "https://kase.kz/ru/bonds/"
    kase_repo_url: str = "https://kase.kz/ru/repo/"
    kase_indices_url: str = "https://kase.kz/ru/indices/"
    kase_cache_ttl_seconds: int = 1800

    # MBM
    nbrk_mbm_url: str = "https://nationalbank.kz/ru/page/mbm"
    nbrk_rates_url: str = "https://nationalbank.kz/ru/rates/"

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

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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
