"""Daily control center API."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import require_permission
from database import get_db
from models.db_models import (
    Alert, CDU, GeneratedReport, PortfolioPosition, PortfolioSummary, ReconciliationResult,
    SourceDocument, Trade, TradeFile,
)

router = APIRouter(
    prefix="/api/workday",
    tags=["workday"],
    dependencies=[Depends(require_permission("page.dashboard"))],
)


def _latest_risk_report_date(db: Session) -> Optional[date]:
    latest_doc_date = db.execute(
        select(func.max(SourceDocument.doc_date)).where(
            SourceDocument.doc_type == "RISK_REPORT_XLSM",
            SourceDocument.parse_status == "OK",
            SourceDocument.doc_date.is_not(None),
        )
    ).scalar_one_or_none()
    if latest_doc_date:
        return latest_doc_date

    return db.execute(
        select(func.max(PortfolioPosition.position_date)).where(
            PortfolioPosition.notes == "rr_report_import",
        )
    ).scalar_one_or_none()


@router.get("/summary")
def workday_summary(
    work_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    day = work_date or _latest_risk_report_date(db) or date.today()
    cdus = (
        db.query(CDU)
        .filter(CDU.is_active == True)  # noqa: E712
        .order_by(CDU.portfolio_type.asc(), CDU.short_name.asc())
        .all()
    )
    risk_docs_for_day = (
        db.query(SourceDocument)
        .filter(
            SourceDocument.doc_type == "RISK_REPORT_XLSM",
            SourceDocument.doc_date == day,
            SourceDocument.parse_status == "OK",
        )
        .order_by(SourceDocument.uploaded_at.desc())
        .all()
    )
    latest_risk_doc = risk_docs_for_day[0] if risk_docs_for_day else None
    risk_docs_count = len(risk_docs_for_day)

    cdu_rows = []
    ready_count = 0
    loaded_count = 0
    operations_total = 0
    summaries_total = 0

    for cdu in cdus:
        trade_files = (
            db.query(TradeFile)
            .filter(
                TradeFile.cdu_id == cdu.id, TradeFile.trade_date == day,
                TradeFile.status.notin_(("DELETED", "SUPERSEDED")),
            )
            .order_by(TradeFile.uploaded_at.desc())
            .all()
        )
        docs_count = (
            db.query(func.count(SourceDocument.id))
            .filter(SourceDocument.cdu_id == cdu.id, SourceDocument.doc_date == day)
            .scalar()
            or 0
        )
        trade_count = (
            db.query(func.count(Trade.id))
            .filter(Trade.cdu_id == cdu.id, Trade.trade_date == day, Trade.is_active == True)  # noqa: E712
            .scalar()
            or 0
        )
        flagged_count = (
            db.query(func.count(Trade.id))
            .filter(
                Trade.cdu_id == cdu.id,
                Trade.trade_date == day,
                Trade.is_active == True,  # noqa: E712
                Trade.price_flag == True,  # noqa: E712
            )
            .scalar()
            or 0
        )
        summary = (
            db.query(PortfolioSummary)
            .filter(PortfolioSummary.cdu_id == cdu.id, PortfolioSummary.summary_date == day)
            .first()
        )
        latest_doc = (
            db.query(SourceDocument)
            .filter(SourceDocument.cdu_id == cdu.id)
            .order_by(SourceDocument.uploaded_at.desc())
            .first()
        )
        recon_rows = db.query(ReconciliationResult).filter(
            ReconciliationResult.cdu_id == cdu.id,
            ReconciliationResult.recon_date == day,
        ).all()
        recon_rank = {"MISMATCH": 3, "ERROR": 3, "PENDING": 2, "MISSING": 2, "OK": 1, "MATCHED": 1}
        recon_status = None
        if recon_rows:
            recon_status = max((r.status for r in recon_rows), key=lambda st: recon_rank.get(st, 0))
        open_alerts = db.query(func.count(Alert.id)).filter(
            Alert.cdu_id == cdu.id, Alert.alert_date == day, Alert.is_resolved == False,  # noqa: E712
        ).scalar() or 0
        has_input = bool(trade_files) or docs_count > 0 or trade_count > 0
        has_summary = summary is not None
        display_doc = latest_doc
        effective_docs_count = docs_count
        if has_summary and latest_risk_doc is not None:
            effective_docs_count += risk_docs_count
            if display_doc is None or display_doc.doc_date != day:
                display_doc = latest_risk_doc
        status = "ready" if has_summary else ("loaded" if has_input else "missing")
        if status == "ready":
            ready_count += 1
        if has_input or has_summary:
            loaded_count += 1
        operations_total += trade_count
        summaries_total += 1 if has_summary else 0

        cdu_rows.append({
            "cdu_id": cdu.id,
            "name": cdu.name,
            "short_name": cdu.short_name,
            "portfolio_type": cdu.portfolio_type,
            "trade_files_count": len(trade_files),
            "documents_count": effective_docs_count,
            "operations_count": trade_count,
            "flagged_prices_count": flagged_count,
            "has_summary": has_summary,
            "status": status,
            "last_file": trade_files[0].filename if trade_files else None,
            "last_upload_at": trade_files[0].uploaded_at.isoformat() if trade_files and trade_files[0].uploaded_at else None,
            "latest_document": display_doc.file_name if display_doc else None,
            "latest_document_date": display_doc.doc_date.isoformat() if display_doc and display_doc.doc_date else None,
            "market_value": summary.total_mv_current if summary else None,
            "daily_change": summary.total_daily_change if summary else None,
            "ytm_weighted": summary.ytm_weighted if summary else None,
            "duration_weighted": summary.duration_weighted if summary else None,
            "reconciliation_status": recon_status,
            "open_alerts": open_alerts,
        })

    docs_by_type = [
        {"doc_type": doc_type or "OTHER", "count": count, "rows_imported": rows_imported or 0}
        for doc_type, count, rows_imported in (
            db.query(
                SourceDocument.doc_type,
                func.count(SourceDocument.id),
                func.coalesce(func.sum(SourceDocument.rows_imported), 0),
            )
            .filter(SourceDocument.doc_date == day)
            .group_by(SourceDocument.doc_type)
            .all()
        )
    ]
    recent_documents = [
        {
            "id": doc.id,
            "doc_type": doc.doc_type,
            "file_name": doc.file_name,
            "doc_date": doc.doc_date.isoformat() if doc.doc_date else None,
            "parse_status": doc.parse_status,
            "rows_imported": doc.rows_imported,
            "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        }
        for doc in (
            db.query(SourceDocument)
            .filter(SourceDocument.doc_date == day)
            .order_by(SourceDocument.uploaded_at.desc())
            .limit(12)
            .all()
        )
    ]
    report_rows = (
        db.query(GeneratedReport)
        .filter(GeneratedReport.report_date == day)
        .order_by(GeneratedReport.generated_at.desc())
        .all()
    )
    reports = [
        {
            "id": report.id,
            "report_type": report.report_type,
            "status": report.status,
            "version": report.version,
            "generated_at": report.generated_at.isoformat() if report.generated_at else None,
            "generated_by": report.generated_by,
        }
        for report in report_rows
    ]
    totals = db.execute(
        select(
            func.coalesce(func.sum(PortfolioSummary.total_mv_current), 0.0),
            func.coalesce(func.sum(PortfolioSummary.total_daily_change), 0.0),
        ).where(PortfolioSummary.summary_date == day)
    ).one()

    return {
        "work_date": day.isoformat(),
        "active_cdus": len(cdus),
        "loaded_cdus": loaded_count,
        "ready_cdus": ready_count,
        "operations_count": operations_total,
        "summaries_count": summaries_total,
        "documents_by_type": docs_by_type,
        "recent_documents": recent_documents,
        "reports": reports,
        "fund_total_mv": totals[0],
        "fund_daily_change": totals[1],
        "cdus": cdu_rows,
    }
