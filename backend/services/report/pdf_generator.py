"""PDF report — same data as XLSX, simplified table for printing."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    PageBreak,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.db_models import CDU, PortfolioPosition, PortfolioSummary
from services.calculator.constants import CATEGORY_LABELS, CATEGORY_ORDER

# Try to register a Cyrillic-friendly font from common locations
# (Windows/Linux/Docker). Falls back to Helvetica if nothing is found —
# Cyrillic will then render as boxes, but the report still builds.
_FONT_CANDIDATES = [
    ("DejaVu", "C:/Windows/Fonts/DejaVuSans.ttf"),
    ("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ("DejaVu", "/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    ("Arial", "C:/Windows/Fonts/arial.ttf"),
    ("Liberation", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ("FreeSans", "/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
]
BASE_FONT = "Helvetica"
for _name, _path in _FONT_CANDIDATES:
    try:
        if Path(_path).exists():
            pdfmetrics.registerFont(TTFont(_name, _path))
            BASE_FONT = _name
            break
    except Exception:
        continue


def generate_pdf_report(db: Session, report_date: date, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"risk_report_{report_date.strftime('%Y%m%d')}.pdf"

    doc = SimpleDocTemplate(str(out), pagesize=landscape(A4),
                            leftMargin=10 * mm, rightMargin=10 * mm,
                            topMargin=10 * mm, bottomMargin=10 * mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Title"], fontName=BASE_FONT,
                                 fontSize=16, leading=20, textColor=colors.HexColor("#1F6B38"))
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=BASE_FONT, fontSize=12,
                        textColor=colors.white, backColor=colors.HexColor("#1F6B38"),
                        spaceAfter=6, leftIndent=4)
    body = ParagraphStyle("body", parent=styles["Normal"], fontName=BASE_FONT, fontSize=9)

    elems = [Paragraph(f"Сводный отчёт Фонда — {report_date.strftime('%d.%m.%Y')}", title_style)]

    summaries = db.execute(select(PortfolioSummary).where(
        PortfolioSummary.summary_date == report_date,
    )).scalars().all()

    if not summaries:
        elems.append(Paragraph("Нет данных за выбранную дату.", body))
        doc.build(elems)
        return out

    fund_total = sum(s.total_mv_current for s in summaries)
    fund_change = sum(s.total_daily_change for s in summaries)

    elems.append(Spacer(1, 4 * mm))
    elems.append(Paragraph(
        f"Активы Фонда: {fund_total:,.2f} ₸ | Δ за день: {fund_change:,.2f} ₸",
        body))
    elems.append(Spacer(1, 6 * mm))

    headers = ["Instruments", "MV T-1", "Δ", "CMV", "% Total", "YTM", "Duration",
               "Min", "Max", "Hard", "Soft", "Free (млн)"]
    for s in summaries:
        cdu = db.get(CDU, s.cdu_id)
        if not cdu:
            continue
        elems.append(Paragraph(cdu.name, h2))

        positions = db.execute(select(PortfolioPosition).where(
            PortfolioPosition.cdu_id == s.cdu_id,
            PortfolioPosition.position_date == report_date,
        )).scalars().all()
        pos_by_cat = {p.instrument_category: p for p in positions}

        data = [headers]
        for cat in CATEGORY_ORDER:
            p = pos_by_cat.get(cat)
            data.append([
                CATEGORY_LABELS[cat],
                _fmt(p.market_value_prev) if p else "—",
                _fmt(p.daily_change) if p else "—",
                _fmt(p.market_value_current) if p else "—",
                f"{(p.pct_of_total * 100):.2f}%" if p else "—",
                f"{(p.ytm or 0) * 100:.2f}%" if p and p.ytm else "—",
                f"{p.duration:.2f}" if p and p.duration is not None else "—",
                "0%", "—",
                p.hard_limit_status if p else "—",
                p.soft_limit_status if p else "—",
                _fmt(p.free_limit_mln) if p and p.free_limit_mln is not None else "—",
            ])
        data.append([
            "Total:",
            _fmt(s.total_mv_prev),
            _fmt(s.total_daily_change),
            _fmt(s.total_mv_current),
            "100.00%",
            f"{s.ytm_weighted * 100:.2f}%",
            f"{s.duration_weighted:.2f}",
            "", "", "", "", "",
        ])

        table = Table(data, colWidths=[55 * mm, 22 * mm, 18 * mm, 24 * mm, 16 * mm,
                                        14 * mm, 14 * mm, 12 * mm, 12 * mm, 14 * mm,
                                        14 * mm, 18 * mm], repeatRows=1)
        ts = TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), BASE_FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4CAF50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#70AD47")),
            ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
            ("FONTNAME", (0, -1), (-1, -1), BASE_FONT),
        ])
        # mark REPO row yellow (index 3 in CATEGORY_ORDER is REVERSE_REPO=2; offset +1 for header)
        repo_idx = CATEGORY_ORDER.index("REVERSE_REPO") + 1
        ts.add("BACKGROUND", (0, repo_idx), (-1, repo_idx), colors.HexColor("#FFFF00"))
        # mark breach rows red
        for i, cat in enumerate(CATEGORY_ORDER, start=1):
            p = pos_by_cat.get(cat)
            if p and p.hard_limit_status == "breach":
                ts.add("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FF6B6B"))
                ts.add("TEXTCOLOR", (0, i), (-1, i), colors.white)
        table.setStyle(ts)

        elems.append(table)
        elems.append(Spacer(1, 3 * mm))
        elems.append(Paragraph(
            f"Доля в Фонде: {s.cdu_share_pct * 100:.2f}% | "
            f"Duration: {s.duration_weighted:.2f} | "
            f"benchmark: {s.benchmark_duration:.2f} | "
            f"limit: {s.duration_status or '—'}"
            if s.benchmark_duration is not None else
            f"Доля в Фонде: {s.cdu_share_pct * 100:.2f}% | Duration: {s.duration_weighted:.2f}",
            body))
        elems.append(Spacer(1, 8 * mm))

    doc.build(elems)
    return out


def _fmt(v):
    if v is None:
        return "—"
    return f"{v:,.2f}".replace(",", " ")
