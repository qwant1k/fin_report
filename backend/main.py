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
    import_routes,
    automation,
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
    upload,
)
from config import settings
from database import init_db, session_scope
from scheduler import start_scheduler, stop_scheduler
from seed import seed_initial_data


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application starting…")
    init_db()
    with session_scope() as db:
        seed_initial_data(db)
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
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", tags=["meta"])
    def health():
        return {"status": "ok", "app_env": settings.app_env}

    # Routes
    app.include_router(auth.router)
    app.include_router(upload.router)
    app.include_router(import_routes.router)
    app.include_router(primary_data_routes.router)
    app.include_router(calculate.router)
    app.include_router(dashboard.router)
    app.include_router(analytics.router)
    app.include_router(automation.router)
    app.include_router(kase.router)
    app.include_router(positions.router)
    app.include_router(reconciliation.router)
    app.include_router(mbm.router)
    app.include_router(export.router)
    app.include_router(reports.router)
    app.include_router(settings_routes.router)
    app.include_router(cdu_formats.router)
    app.include_router(securities.router)
    app.include_router(risk_report.router)
    app.include_router(data_editor.router)
    app.include_router(admin.router)

    return app


app = create_app()
