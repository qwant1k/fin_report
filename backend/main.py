"""FastAPI application entry-point."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from api.routes import (
    admin,
    analytics,
    auth,
    calculate,
    cdu_formats,
    dashboard,
    export,
    formulas,
    import_routes,
    automation,
    accounting,
    approvals,
    operations,
    kase,
    positions,
    primary_data_routes,
    reconciliation,
    mbm,
    reports,
    data_editor,
    risk_report,
    securities,
    settings as settings_routes,
    tonia,
    upload,
    workday,
)
from config import settings
from database import init_db, session_scope
from scheduler import start_scheduler, stop_scheduler
from seed import seed_startup_data


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application starting…")
    from config import insecure_settings
    weak = insecure_settings()
    if weak:
        logger.critical(
            "Небезопасная конфигурация: значения по умолчанию для "
            + ", ".join(weak)
            + " — задайте их в .env (JWT_SECRET, SECRET_KEY, ADMIN_PASSWORD)."
        )
    init_db()
    with session_scope() as db:
        seed_startup_data(db, settings.initial_data_mode)
    if settings.app_env != "test":
        start_scheduler()
    yield
    stop_scheduler()
    logger.info("Application stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Fund Reporting — КФГД",
        version="1.0.0",
        description="Автоматизация обработки TradeReport от ЧДУ и сводных отчётов Фонда.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_origin_regex=settings.cors_origin_regex_value,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", tags=["meta"])
    def health():
        from config import insecure_settings
        return {
            "status": "ok",
            "app_env": settings.app_env,
            "insecure_defaults": bool(insecure_settings()),
        }

    # Routes
    app.include_router(auth.router)
    app.include_router(upload.router)
    app.include_router(import_routes.router)
    app.include_router(primary_data_routes.router)
    app.include_router(calculate.router)
    app.include_router(dashboard.router)
    app.include_router(analytics.router)
    app.include_router(automation.router)
    app.include_router(workday.router)
    app.include_router(operations.router)
    app.include_router(accounting.router)
    app.include_router(approvals.router)
    app.include_router(kase.router)
    app.include_router(positions.router)
    app.include_router(reconciliation.router)
    app.include_router(mbm.router)
    app.include_router(tonia.router)
    app.include_router(export.router)
    app.include_router(reports.router)
    app.include_router(settings_routes.router)
    app.include_router(cdu_formats.router)
    app.include_router(securities.router)
    app.include_router(risk_report.router)
    app.include_router(data_editor.router)
    app.include_router(formulas.values_router)
    app.include_router(formulas.router)
    app.include_router(admin.router)

    return app


app = create_app()
