"""Exchange-certificate parser (PDF/PNG/DOCX).

Extracts deal_id, isin, amount, date via regex.
Uses Tesseract OCR for images and scanned PDFs.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional
import re
from loguru import logger

DEAL_RE = re.compile(r"(?:сделка|deal)[\s#№]*(\d+)", re.IGNORECASE)
# KASE deal numbers are 9-digit integers (e.g. 119063203)
DEAL_NUMBER_RE = re.compile(r"(?<![\d.,])(\d{9})(?![\d.,])")
AMOUNT_RE = re.compile(r"(\d[\d\s]*(?:\.\d{2})?)\s*(?:тенге|KZT|USD)", re.IGNORECASE)
MONEY_RE = re.compile(r"\d{1,3}(?:[ \u00a0]\d{3})+[.,]\d{2}|\d+[.,]\d{2}")
ISIN_RE = re.compile(r"([A-Z]{2}[A-Z0-9]{9}\d)")
DATE_RE = re.compile(r"(\d{2}[./]\d{2}[./]\d{4})")


def parse_certificate(file_path: Path | str) -> Dict[str, Any]:
    """Extract deal numbers (and the money amounts of their rows).

    Exchange certificates arrive as images (PNG, scanned PDF, DOCX with an
    embedded picture), so the text comes from Tesseract OCR with the Russian
    language pack.  OCR of small table fonts is imperfect: the image is
    upscaled/binarised in several variants and the union of recognised deal
    numbers is returned.  Reconciliation treats a missing deal as «проверить
    вручную», never as an automatic correction.
    """
    p = Path(file_path)
    texts = _extract_texts(p)
    text = "\n".join(t for t in texts if t)
    warnings: List[str] = []
    if not text:
        return {"filename": p.name, "deals": [], "warnings": ["No text extracted (OCR недоступен?)"]}
    if not _has_russian_ocr() and _is_image_based(p):
        warnings.append("Tesseract без русского языкового пакета (rus) — распознавание неполное")

    deals: Dict[str, Dict[str, Any]] = {}
    for chunk in texts:
        for line in (chunk or "").splitlines():
            for deal_id in DEAL_NUMBER_RE.findall(line):
                item = deals.setdefault(deal_id, {"deal_id": deal_id, "amounts": set(), "isins": set(), "lines": []})
                for raw in MONEY_RE.findall(line):
                    value = _money(raw)
                    if value is not None:
                        item["amounts"].add(round(value, 2))
                for isin in ISIN_RE.findall(line):
                    item["isins"].add(isin)
                if len(item["lines"]) < 3:
                    item["lines"].append(line.strip()[:300])
    for deal_id in DEAL_RE.findall(text):
        deals.setdefault(deal_id, {"deal_id": deal_id, "amounts": set(), "isins": set(), "lines": []})

    dates = DATE_RE.findall(text)
    return {
        "filename": p.name,
        "deals": [
            {"deal_id": d["deal_id"], "amounts": sorted(d["amounts"]),
             "isins": sorted(d["isins"]), "lines": d["lines"], "source": "ocr" if _is_image_based(p) else "text"}
            for d in deals.values()
        ],
        "deal_ids": sorted(deals),
        "amounts_found": AMOUNT_RE.findall(text),
        "isins_found": sorted(set(ISIN_RE.findall(text))),
        "dates_found": dates,
        "report_date": _first_date(dates),
        "text_sample": text[:500],
        "warnings": warnings,
    }


def _money(raw: str) -> Optional[float]:
    try:
        return float(raw.replace("\u00a0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _first_date(values: List[str]):
    from datetime import datetime
    for raw in values:
        for fmt in ("%d.%m.%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(raw.replace("/", "."), "%d.%m.%Y").date()
            except ValueError:
                continue
    return None


def _is_image_based(p: Path) -> bool:
    return p.suffix.lower() in (".png", ".jpg", ".jpeg", ".docx", ".pdf")


def _has_russian_ocr() -> bool:
    try:
        import pytesseract
        _configure_tesseract()
        return "rus" in pytesseract.get_languages(config="")
    except Exception:
        return False


def _extract_texts(p: Path) -> List[str]:
    """Plain text when available, otherwise OCR of every embedded image."""
    suffix = p.suffix.lower()
    out: List[str] = []
    if suffix == ".docx":
        text = _extract_docx_text(p)
        if text:
            out.append(text)
        out.extend(_ocr_docx_images(p))
        return out
    if suffix == ".pdf":
        text = _extract_pdf_text(p)
        return [text] if text else []
    if suffix in (".png", ".jpg", ".jpeg"):
        try:
            from PIL import Image
            return _ocr_variants(Image.open(p))
        except Exception as exc:
            logger.warning(f"OCR image failed: {p} — {exc}")
            return []
    return []


def _ocr_docx_images(p: Path) -> List[str]:
    import io
    import zipfile
    out: List[str] = []
    try:
        from PIL import Image
        with zipfile.ZipFile(p) as zf:
            for name in zf.namelist():
                if name.startswith("word/media/") and name.lower().endswith((".png", ".jpg", ".jpeg")):
                    out.extend(_ocr_variants(Image.open(io.BytesIO(zf.read(name)))))
    except Exception as exc:
        logger.warning(f"docx image OCR failed: {p} — {exc}")
    return out


def _ocr_variants(img) -> List[str]:
    """OCR an image in a few upscale/threshold variants (tables with tiny fonts)."""
    try:
        import pytesseract
        from PIL import Image, ImageOps
    except Exception:
        return []
    _configure_tesseract()
    lang = "rus+eng" if _has_russian_ocr() else "eng"
    gray = img.convert("L")
    texts: List[str] = []
    for scale, threshold in ((2, None), (2, 140), (3, 170), (3, None)):
        try:
            work = gray.resize((gray.width * scale, gray.height * scale), Image.LANCZOS)
            work = ImageOps.autocontrast(work)
            if threshold is not None:
                work = work.point(lambda px, t=threshold: 255 if px > t else 0)
            texts.append(pytesseract.image_to_string(work, lang=lang, config="--psm 6"))
        except Exception as exc:
            logger.debug(f"OCR variant failed: {exc}")
    strips = _ocr_table_rows(gray, lang)
    if strips:
        texts.append(strips)
    return texts


def _ocr_table_rows(gray, lang: str, scale: int = 3) -> Optional[str]:
    """Row-by-row OCR of a ruled table.

    Page-level OCR of the KASE certificate tables regularly drops whole rows
    (e.g. RepoClose legs).  The grid lines are detected, vertical lines are
    removed and every strip between two horizontal lines is recognised as a
    single text line (``--psm 7``).
    """
    try:
        import numpy as np
        import pytesseract
        from PIL import Image
    except Exception:
        return None
    try:
        work = gray.resize((gray.width * scale, gray.height * scale), Image.LANCZOS)
        a = np.array(work)
        dark = a < 128
        row_lines = np.where(dark.mean(axis=1) > 0.5)[0]
        col_lines = dark.mean(axis=0) > 0.5
        if len(row_lines) < 3:
            return None          # not a ruled table
        a = a.copy()
        a[:, col_lines] = 255
        bounds, prev = [], 0
        for i in row_lines:
            if i - prev > 10:
                bounds.append((prev + 1, i))
            prev = i
        lines: List[str] = []
        for top, bottom in bounds[:200]:
            strip = Image.fromarray(a[top:bottom, :])
            text = pytesseract.image_to_string(strip, lang=lang, config="--psm 7").strip()
            if text:
                lines.append(text)
        return "\n".join(lines) if lines else None
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Row OCR failed: {exc}")
        return None


def _extract_text(p: Path) -> Optional[str]:
    suffix = p.suffix.lower()
    if suffix == ".docx":
        return _extract_docx_text(p)
    if suffix == ".pdf":
        return _extract_pdf_text(p)
    if suffix in (".png", ".jpg", ".jpeg"):
        return _ocr_image(p)
    return None


def _extract_docx_text(p: Path) -> Optional[str]:
    try:
        from docx import Document
        doc = Document(p)
        parts: List[str] = []
        # Paragraphs
        for para in doc.paragraphs:
            if para.text.strip():
                parts.append(para.text.strip())
        # Tables
        for table in doc.tables:
            for row in table.rows:
                row_text = " ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    parts.append(row_text)
        return "\n".join(parts) if parts else None
    except Exception:
        logger.warning(f"docx read failed: {p}")
        return None


def _extract_pdf_text(p: Path) -> Optional[str]:
    try:
        import pdfplumber
        parts: List[str] = []
        with pdfplumber.open(p) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if text.strip():
                    parts.append(text)
                else:
                    # Scanned PDF — fallback to OCR
                    logger.info(f"Page text empty, trying OCR for: {p}")
                    try:
                        img_text = _ocr_pdf_page(page)
                        if img_text:
                            parts.append(img_text)
                    except Exception as e:
                        logger.debug(f"OCR failed for page: {e}")
        return "\n".join(parts) if parts else None
    except Exception:
        logger.warning(f"pdf read failed: {p}")
        return None


def _configure_tesseract():
    import shutil, os
    tess = shutil.which("tesseract")
    if tess:
        return
    for p in [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Tesseract-OCR\tesseract.exe",
    ]:
        if os.path.exists(p):
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = p
            break


def _ocr_image(p: Path) -> Optional[str]:
    try:
        import pytesseract
        from PIL import Image
        _configure_tesseract()
        texts = _ocr_variants(Image.open(p))
        text = "\n".join(t for t in texts if t and t.strip())
        return text if text.strip() else None
    except Exception as e:
        logger.warning(f"OCR image failed: {p} — {e}")
        return None


def _ocr_pdf_page(page) -> Optional[str]:
    """Convert PDF page to image and OCR."""
    try:
        import pytesseract
        from PIL import Image
        _configure_tesseract()
        img = page.to_image(resolution=300).original
        texts = _ocr_variants(img)
        text = "\n".join(t for t in texts if t and t.strip())
        return text if text.strip() else None
    except Exception as e:
        logger.warning(f"OCR PDF page failed: {e}")
        return None
