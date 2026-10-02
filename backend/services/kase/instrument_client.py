"""KASE instrument data: coupon payment schedule and issue characteristics.

kase.kz is an Angular SSR application; the security page
(«Характеристики ценной бумаги» → «просмотр графика») is filled from public
JSON endpoints of the same site:

* ``GET /api/instruments/coupon-payments/{code}`` →
  ``[{fixation_date, start_date, end_date, rate, index_rate, total_rate}]``
  - ``start_date`` — coupon (payment) date, i.e. the end of the accrual period;
  - ``end_date``   — end of the payment window (corporate bonds: +14 days,
    MUM108_0013: 31.03.24 → 01.04.24 because of the weekend);
  - ``rate`` — fixed rate / margin, ``index_rate`` — index of a floating
    coupon, ``total_rate`` — the coupon rate of the period.
* ``GET /api/instruments/{gsecs|bonds}/{code}/characteristics`` →
  ``{id: {label, value}}`` (nominal, basis, start of circulation, maturity …)
* ``GET /api/instruments/securities/{code}`` (sec_type, issuer, ISIN) and
  ``GET /api/instruments/securities?search={ISIN}`` (ISIN → KASE code).

Parsing is separated from I/O (``parse_*``) so it is unit-tested with real
responses captured from kase.kz (tests/fixtures/kase_api_samples.json).
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from config import settings


@dataclass
class KaseIssue:
    code: str
    isin: Optional[str] = None
    sec_type: Optional[str] = None          # gsec / bond
    name: Optional[str] = None
    issuer: Optional[str] = None
    currency: Optional[str] = None
    nominal: Optional[float] = None
    coupon_rate_pct: Optional[float] = None
    coupon_type: Optional[str] = None       # fix / float / zero
    base: Optional[str] = None
    start_date: Optional[date] = None
    maturity_date: Optional[date] = None
    quotation_type: Optional[str] = None
    frequency: Optional[int] = None
    schedule: List[dict] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


# ───────────────────────── parsing ─────────────────────────

def _iso(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _ru_date(text: str) -> Optional[date]:
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", text or "")
    if not m:
        return None
    y = int(m.group(3))
    y = y + 2000 if y < 100 else y
    try:
        return date(y, int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _ru_number(text: Any) -> Optional[float]:
    if text is None:
        return None
    t = str(text).replace("\xa0", "").replace(" ", "").replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    return float(m.group(0)) if m else None


def parse_coupon_payments(rows: List[dict]) -> List[dict]:
    """KASE rows → schedule rows of ``CouponSchedule`` (rates in %)."""
    out: List[dict] = []
    for i, r in enumerate(sorted(rows or [], key=lambda x: str(x.get("start_date") or "")), start=1):
        pay = _iso(r.get("start_date"))
        if pay is None:
            continue
        total = r.get("total_rate")
        rate = r.get("rate")
        index = r.get("index_rate")
        if total is None and rate is not None:
            total = float(rate) + float(index or 0.0)
        out.append({
            "seq": i,
            "payment_date": pay,
            "payment_end_date": _iso(r.get("end_date")),
            "record_date": _iso(r.get("fixation_date")),
            "rate_pct": float(total) if total is not None else None,
            "margin_pct": float(rate) if rate is not None and index is not None else None,
            "index_rate_pct": float(index) if index is not None else None,
        })
    # The accrual period of a payment is (previous coupon date, this date]; it is
    # derived when calculating (the first one starts at the start of
    # circulation), so rows added or edited by hand keep the chain consistent.
    for row in out:
        row["period_start"] = None
    return out


def _infer_frequency(schedule: List[dict]) -> Optional[int]:
    dates = [r["payment_date"] for r in schedule]
    if len(dates) < 2:
        return None
    gaps = sorted((b - a).days for a, b in zip(dates, dates[1:]))
    median = gaps[len(gaps) // 2]
    for freq, days in ((12, 30), (4, 91), (2, 182), (1, 365)):
        if abs(median - days) <= days * 0.15:
            return freq
    return None


def parse_characteristics(payload: Dict[str, Any], issue: KaseIssue) -> KaseIssue:
    """Fill the issue from the label/value list of «Характеристики ценной бумаги»."""
    fields: Dict[str, str] = {}
    for item in (payload or {}).values():
        if isinstance(item, dict) and item.get("label"):
            fields[str(item["label"]).strip().lower()] = html.unescape(str(item.get("value") or "")).strip()
    issue.raw["characteristics"] = fields

    def get(*needles: str) -> Optional[str]:
        for label, value in fields.items():
            if any(n in label for n in needles):
                return value
        return None

    issue.name = issue.name or get("наименование облигации")
    issue.currency = (get("валюта выпуска") or issue.currency or "").strip().upper()[:8] or None
    issue.nominal = _ru_number(get("номинальная стоимость"))
    isin = get("isin")
    if isin and not issue.isin:
        issue.isin = isin.strip().upper()
    kind = (get("вид купонной ставки") or "").lower()
    name = (issue.name or "").lower()
    if "дисконт" in name:
        issue.coupon_type = "zero"
    elif "плава" in kind or "индекс" in name:
        issue.coupon_type = "float"
    elif kind or "купон" in name:
        issue.coupon_type = "fix"
    rate_text = get("купонная ставка")
    if rate_text:
        parts = [_ru_number(p) for p in rate_text.split("+")]
        parts = [p for p in parts if p is not None]
        issue.coupon_rate_pct = sum(parts) if parts else None
    base = get("расчетный базис")
    if base:
        issue.base = base.lower().replace("actual", "act")
    issue.start_date = _ru_date(get("дата начала обращения") or "")
    maturity = get("дата погашения") or get("период погашения") or ""
    issue.maturity_date = _ru_date(maturity)
    quote = get("предмет котирования")
    issue.quotation_type = quote
    return issue


def parse_security(payload: Dict[str, Any], issue: KaseIssue) -> KaseIssue:
    if not isinstance(payload, dict):
        return issue
    issue.sec_type = payload.get("sec_type") or issue.sec_type
    issue.issuer = payload.get("org_name_ru") or issue.issuer
    issue.currency = issue.currency or payload.get("currency_type")
    nin = (payload.get("ticker") or {}).get("nin")
    if nin and not issue.isin:
        issue.isin = str(nin).strip().upper()
    return issue


def code_from_search(rows: List[dict], isin: str) -> Optional[str]:
    isin = isin.strip().upper()
    for r in rows or []:
        if str(((r.get("ticker") or {}).get("nin")) or "").strip().upper() == isin:
            return r.get("code")
    return None


# ───────────────────────── client ─────────────────────────

class KaseInstrumentClient:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 30.0,
                 transport: Optional[httpx.AsyncBaseTransport] = None):
        self.base = (base_url or settings.kase_api_base_url).rstrip("/")
        self.timeout = timeout
        self.transport = transport
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru,en;q=0.8",
            "Referer": "https://kase.kz/ru/investors/instruments",
        }

    async def _get(self, cli: httpx.AsyncClient, path: str, **params) -> Any:
        r = await cli.get(f"{self.base}/{path.lstrip('/')}", params=params or None)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def resolve_code(self, cli: httpx.AsyncClient, isin: str) -> Optional[str]:
        rows = await self._get(cli, "instruments/securities", search=isin)
        return code_from_search(rows if isinstance(rows, list) else [], isin)

    async def fetch_issue(self, code: Optional[str] = None, isin: Optional[str] = None) -> KaseIssue:
        """Characteristics + coupon schedule of one issue (by KASE code or ISIN)."""
        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers,
                                     follow_redirects=True, transport=self.transport) as cli:
            if not code and isin:
                code = await self.resolve_code(cli, isin)
            if not code:
                raise LookupError(f"KASE: инструмент {isin or ''} не найден")
            issue = KaseIssue(code=code, isin=(isin or None))
            sec = await self._get(cli, f"instruments/securities/{code}")
            if sec is None:
                raise LookupError(f"KASE: инструмент {code} не найден")
            parse_security(sec, issue)
            kinds = ["gsecs", "bonds"] if issue.sec_type != "bond" else ["bonds", "gsecs"]
            for kind in kinds:
                ch = await self._get(cli, f"instruments/{kind}/{code}/characteristics")
                if ch:
                    parse_characteristics(ch, issue)
                    break
            rows = await self._get(cli, f"instruments/coupon-payments/{code}") or []
            issue.schedule = parse_coupon_payments(rows)
            issue.frequency = _infer_frequency(issue.schedule)
            if issue.coupon_type is None:
                issue.coupon_type = "zero" if not issue.schedule else "fix"
            logger.info(f"KASE issue {code}: {len(issue.schedule)} coupon rows, maturity {issue.maturity_date}")
            return issue
