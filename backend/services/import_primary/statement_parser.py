"""PDF bank / custodian statement parser (BCC, Halyk, NBRK Excel-like PDFs).

Business process 6.5.1: take the number to the right of «Исходящее сальдо:»
(«Исходящий остаток:») inside the section whose «Счет (валюта)» is KZT.  If
there are several KZT accounts — sum them (8.2 D).

The statement is split into sections (one per account); every section yields
its account (IBAN), currency, opening and closing balance.  Incoming balances
are never taken for the closing one, decimals with 1–2 digits are kept
(«904950.7» → 904 950.70), and IBANs with letters (KZ29601A86…) are recognised.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

_NUM = r"-?\d[\d\s ]*(?:[.,]\d{1,2})?"

CLOSING_RE = re.compile(
    r"(?:исходящ(?:ее|ий)\s*(?:сальдо|остаток)|шығыс\s*сальдо|closing\s*balance)\s*:?\s*(" + _NUM + r")",
    re.IGNORECASE,
)
OPENING_RE = re.compile(
    r"(?:входящ(?:ее|ий)\s*(?:сальдо|остаток)|кіріс\s*сальдо|opening\s*balance)\s*:?\s*(" + _NUM + r")",
    re.IGNORECASE,
)
# Kazakhstani IBAN: KZ + 2 check digits + 16 alphanumerics
ACCOUNT_RE = re.compile(r"\b(KZ\d{2}[0-9A-Z]{16})\b")
CURRENCY_RE = re.compile(r"\b(KZT|USD|EUR|RUB|CNY|GBP)\b")
SECTION_START_RE = re.compile(
    r"(?:сч[её]т\s*\(\s*валюта\s*\)|валютасы\s*/\s*валюта|выписка\s+по\s+сч[её]ту)",
    re.IGNORECASE,
)
PERIOD_RE = re.compile(
    r"(?:c|с|за\s+период:?)\s*(\d{2}\.\d{2}\.\d{4})\s*(?:по|-|—)\s*(\d{2}\.\d{2}\.\d{4})",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"Дата\s+остатка\s*[:\-]?\s*(\d{2}[./]\d{2}[./]\d{4})",
    re.IGNORECASE,
)

_CUSTODIAN_HINTS = (
    ("BCC", ("центркредит", "centercredit", "bcc")),
    ("HALYK", ("народный банк", "halyk", "халык")),
    ("NBRK", ("национальный банк", "nationalbank")),
)


def _to_number(raw: str) -> Optional[float]:
    text = raw.replace(" ", "").replace(" ", "").strip()
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    elif "," in text and "." in text:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _to_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    for fmt in ("%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _split_sections(text: str) -> List[str]:
    starts = [m.start() for m in SECTION_START_RE.finditer(text)]
    if not starts:
        return [text]
    sections: List[str] = []
    # text before the first header belongs to the first section (title, client…)
    bounds = starts + [len(text)]
    for i in range(len(starts)):
        begin = 0 if i == 0 else bounds[i]
        sections.append(text[begin:bounds[i + 1]])
    return sections


def parse_statement_text(text: str) -> Dict[str, Any]:
    sections_out: List[Dict[str, Any]] = []
    for section in _split_sections(text):
        closing = CLOSING_RE.search(section)
        if not closing:
            continue
        opening = OPENING_RE.search(section)
        header_zone = section[: closing.start()]
        account = ACCOUNT_RE.search(header_zone) or ACCOUNT_RE.search(section)
        currency = None
        currency_line = re.search(
            r"(?:сч[её]т\s*\(\s*валюта\s*\)[^\n]*|валюта\s*:\s*[A-Z]{3})", header_zone, re.IGNORECASE,
        )
        if currency_line:
            found = CURRENCY_RE.search(currency_line.group(0).upper())
            currency = found.group(1) if found else None
        if currency is None:
            found = CURRENCY_RE.search(header_zone.upper())
            currency = found.group(1) if found else "KZT"
        period = PERIOD_RE.search(section)
        balance_date = DATE_RE.search(section)
        sections_out.append({
            "account": account.group(1) if account else None,
            "currency": currency,
            "opening_balance": _to_number(opening.group(1)) if opening else None,
            "closing_balance": _to_number(closing.group(1)),
            "period_from": _to_date(period.group(1)) if period else None,
            "period_to": _to_date(period.group(2)) if period else None,
            "balance_date": _to_date(balance_date.group(1)) if balance_date else None,
        })

    lower = text.lower()
    custodian = next((name for name, hints in _CUSTODIAN_HINTS if any(h in lower for h in hints)), None)
    statement_date = None
    for item in sections_out:
        # balances are «as of» the end of the statement period
        statement_date = item["period_to"] or item["balance_date"] or statement_date
    totals: Dict[str, float] = {}
    for item in sections_out:
        if item["closing_balance"] is None:
            continue
        totals[item["currency"]] = totals.get(item["currency"], 0.0) + item["closing_balance"]
    return {
        "sections": sections_out,
        "closing_by_currency": totals,
        "custodian": custodian,
        "report_date": statement_date,
        # Backwards-compatible shape used by older UI code.
        "balances": [
            {"currency": s["currency"], "amount": s["closing_balance"], "account": s["account"], "type": "closing"}
            for s in sections_out
        ],
        "accounts_found": [s["account"] for s in sections_out if s["account"]],
    }


def parse_pdf_statement(file_path: Path | str) -> Dict[str, Any]:
    p = Path(file_path)
    text = _extract_pdf_text(p)
    if not text:
        return {"balances": [], "sections": [], "closing_by_currency": {},
                "warnings": ["Не удалось извлечь текст из PDF (скан без OCR?)"], "filename": p.name}
    result = parse_statement_text(text)
    result["filename"] = p.name
    result["text_sample"] = text[:800]
    if not result["sections"]:
        result["warnings"] = ["Не найдено «Исходящее сальдо / Исходящий остаток»"]
    return result


def looks_like_statement(text: str) -> bool:
    low = (text or "").lower()
    return bool(CLOSING_RE.search(text or "")) or ("выписка" in low and "остаток" in low)


def _extract_pdf_text(p: Path) -> Optional[str]:
    try:
        import pdfplumber
        parts: List[str] = []
        with pdfplumber.open(p) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if text:
                    parts.append(text)
                else:
                    logger.info(f"Page has no text, may be scanned: {p}")
        return "\n".join(parts) if parts else None
    except Exception:
        logger.warning(f"pdf read failed: {p}")
        return None
