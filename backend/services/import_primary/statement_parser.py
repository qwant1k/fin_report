"""PDF bank-statement parser (custodian statements: BCC, Halyk).

Extracts ending cash balances per currency from PDF text using regex.
Also extracts account numbers (KZ...) and document dates.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional
import re
from loguru import logger

# Balance patterns: Исходящее сальдо / Шығыс сальдо / Closing balance / Остаток
BALANCE_RE = re.compile(
    r"(?:исходящее\s*сальдо|шығыс\s*сальдо|closing\s*balance|остаток)[^\d]*"
    r"(\d[\d\s]*(?:\.\d{2})?)",
    re.IGNORECASE,
)
# Amount with currency nearby
AMOUNT_CCY_RE = re.compile(
    r"(\d[\d\s]*(?:\.\d{2})?)\s*(?:тенге|KZT|USD|EUR)",
    re.IGNORECASE,
)
ACCOUNT_RE = re.compile(r"(KZ\d{20})")
DATE_RE = re.compile(
    r"(?:Дата формирования|Кұрылған күні|Дата)\s*[:\-]?\s*(\d{2}[./]\d{2}[./]\d{4})",
    re.IGNORECASE,
)


def parse_pdf_statement(file_path: Path | str) -> Dict[str, Any]:
    p = Path(file_path)
    text = _extract_pdf_text(p)
    if not text:
        return {"balances": [], "warnings": ["No text extracted"]}

    balances: List[Dict] = []
    accounts = ACCOUNT_RE.findall(text)
    dates = DATE_RE.findall(text)

    # Search for outgoing balance lines (Исходящее сальдо)
    for m in BALANCE_RE.finditer(text):
        amount_str = m.group(1).replace(" ", "").replace("\u00a0", "").replace(",", ".")
        try:
            amount = float(amount_str)
        except ValueError:
            continue
        # Currency detection from surrounding text
        snippet = text[max(0, m.start() - 50): m.end() + 50].upper()
        ccy = "KZT"
        if "USD" in snippet or "$" in snippet:
            ccy = "USD"
        elif "EUR" in snippet or "€" in snippet:
            ccy = "EUR"
        balances.append({"currency": ccy, "amount": amount, "context": snippet.strip()})

    # Also try to find total/credit lines near table footer
    total_re = re.compile(r"(?:Жиынтығы|Итого|Total)[:\s]*([\d\s.,]+)", re.IGNORECASE)
    for m in total_re.finditer(text):
        amount_str = m.group(1).replace(" ", "").replace("\u00a0", "").replace(",", ".")
        try:
            amount = float(amount_str)
        except ValueError:
            continue
        snippet = text[max(0, m.start() - 30): m.end() + 30].upper()
        ccy = "KZT"
        if "USD" in snippet:
            ccy = "USD"
        balances.append({"currency": ccy, "amount": amount, "context": snippet.strip(), "type": "total"})

    return {
        "filename": p.name,
        "accounts_found": list(dict.fromkeys(accounts)),
        "dates_found": dates,
        "balances": balances,
        "text_sample": text[:800],
    }


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
                    # Fallback: try OCR if page has no extractable text (scanned PDF)
                    logger.info(f"Page has no text, may be scanned: {p}")
        return "\n".join(parts) if parts else None
    except Exception:
        logger.warning(f"pdf read failed: {p}")
        return None
