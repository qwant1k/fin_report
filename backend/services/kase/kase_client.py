"""KASE client — fetches bond prices, YTM, accrued interest, duration.

Two-stage strategy:
1. Try the public listing JSON endpoint that powers the bonds page (best effort
   — endpoint may evolve; we look it up via the page's __NUXT__ payload or
   /api/* JSON).
2. Fallback: scrape HTML tables from kase.kz/ru/bonds with BeautifulSoup.

The client is fully async (httpx.AsyncClient) and caches responses for
`KASE_CACHE_TTL_SECONDS` to avoid hammering the site.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from config import settings


@dataclass
class KaseQuote:
    instrument_code: str
    isin: Optional[str] = None
    instrument_name: Optional[str] = None
    close_price: Optional[float] = None
    ytm: Optional[float] = None
    accrued_interest: Optional[float] = None
    duration: Optional[float] = None
    sec_type: Optional[str] = None
    fin_sec_ru: Optional[str] = None
    fin_sec_en: Optional[str] = None
    fin_sec_kz: Optional[str] = None
    org_code: Optional[str] = None
    org_name_ru: Optional[str] = None
    org_name_en: Optional[str] = None
    org_name_kz: Optional[str] = None
    settlement_price: Optional[float] = None
    settlement_dirty_price: Optional[float] = None
    dohod: Optional[float] = None
    dtm: Optional[float] = None
    kase_ytm: Optional[float] = None
    unit_ru: Optional[str] = None
    unit_en: Optional[str] = None
    unit_kz: Optional[str] = None
    raw_data: Dict[str, object] = field(default_factory=dict)
    fetched_at: datetime = datetime.utcnow()
    source: str = "html"


class _Cache:
    def __init__(self, ttl: int) -> None:
        self.ttl = ttl
        self._store: Dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        item = self._store.get(key)
        if not item:
            return None
        ts, val = item
        if time.time() - ts > self.ttl:
            self._store.pop(key, None)
            return None
        return val

    def set(self, key: str, value: object) -> None:
        self._store[key] = (time.time(), value)


class KaseClient:
    """Async HTTP client for KASE."""

    def __init__(self) -> None:
        self.bonds_url = settings.kase_bonds_url
        self.repo_url = settings.kase_repo_url
        self.indices_url = settings.kase_indices_url
        self.cache = _Cache(settings.kase_cache_ttl_seconds)
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "ru,en;q=0.8",
        }

    async def fetch_bonds(self, trade_date: Optional[date] = None) -> List[KaseQuote]:
        cache_key = f"bonds:{trade_date.isoformat() if trade_date else 'latest'}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        quotes: List[KaseQuote] = []
        async with httpx.AsyncClient(timeout=30.0, headers=self._headers, follow_redirects=True) as cli:
            try:
                quotes = await self._try_market_valuations(cli, trade_date)
            except Exception as exc:
                logger.warning(f"KASE market valuations fetch failed: {exc!r}; falling back to legacy JSON/HTML")

            if not quotes:
                try:
                    quotes = await self._try_json(cli)
                except Exception as exc:
                    logger.warning(f"KASE JSON fetch failed: {exc!r}; falling back to HTML")

            if trade_date and not quotes:
                return []
            if trade_date and quotes and quotes[0].source != "market_valuations":
                return []

            if not quotes:
                try:
                    quotes = await self._try_html(cli, self.bonds_url)
                except Exception as exc:
                    logger.error(f"KASE HTML fallback failed: {exc!r}")

        self.cache.set(cache_key, quotes)
        return quotes

    async def fetch_repo_rates(self) -> List[Dict[str, object]]:
        cached = self.cache.get("repo")
        if cached is not None:
            return cached
        out: List[Dict[str, object]] = []
        async with httpx.AsyncClient(timeout=30.0, headers=self._headers, follow_redirects=True) as cli:
            try:
                resp = await cli.get(self.repo_url)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")
                # Generic: парсим первую таблицу со ставками
                table = soup.find("table")
                if table:
                    headers = [th.get_text(strip=True) for th in table.find_all("th")]
                    for tr in table.find_all("tr")[1:]:
                        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                        if cells:
                            out.append(dict(zip(headers, cells)))
            except Exception as exc:
                logger.error(f"KASE repo fetch failed: {exc!r}")
        self.cache.set("repo", out)
        return out

    # ─────────── private ───────────
    async def _try_market_valuations(
        self,
        cli: httpx.AsyncClient,
        target_date: Optional[date] = None,
    ) -> List[KaseQuote]:
        params = {"ordering": "code__nulls_last"}
        if target_date:
            params["date"] = target_date.isoformat()
        r = await cli.get("https://kase.kz/api/indicators/market-valuations/", params=params)
        r.raise_for_status()
        payload = r.json()
        if not isinstance(payload, dict) or not payload:
            return []
        keys = sorted(payload.keys(), reverse=True)
        selected_key = target_date.isoformat() if target_date else keys[0]
        rows = payload.get(selected_key)
        if rows is None:
            logger.warning(
                f"KASE market valuations did not return requested date {selected_key}; "
                f"available dates: {', '.join(keys[:5])}"
            )
            return []
        if not isinstance(rows, list):
            return []
        return [quote for item in rows if (quote := self._market_valuation_to_quote(item))]

    def _market_valuation_to_quote(self, item) -> Optional[KaseQuote]:
        if not isinstance(item, dict):
            return None
        code = item.get("code")
        if not code:
            return None
        dohod = _to_float(item.get("dohod"))
        settlement_price = _to_float(item.get("settlement_price"))
        dtm = _to_float(item.get("dtm"))
        return KaseQuote(
            instrument_code=str(code),
            isin=item.get("isin"),
            instrument_name=item.get("org_name_ru") or item.get("org_name_en") or item.get("org_name_kz"),
            close_price=settlement_price,
            ytm=(dohod / 100.0) if dohod is not None else None,
            accrued_interest=None,
            duration=dtm,
            sec_type=item.get("sec_type"),
            fin_sec_ru=item.get("fin_sec_ru"),
            fin_sec_en=item.get("fin_sec_en"),
            fin_sec_kz=item.get("fin_sec_kz"),
            org_code=item.get("org_code"),
            org_name_ru=item.get("org_name_ru"),
            org_name_en=item.get("org_name_en"),
            org_name_kz=item.get("org_name_kz"),
            settlement_price=settlement_price,
            settlement_dirty_price=_to_float(item.get("settlement_dirty_price")),
            dohod=dohod,
            dtm=dtm,
            kase_ytm=_to_float(item.get("ytm")),
            unit_ru=item.get("unit_ru"),
            unit_en=item.get("unit_en"),
            unit_kz=item.get("unit_kz"),
            raw_data=dict(item),
            source="market_valuations",
        )

    async def _try_json(self, cli: httpx.AsyncClient) -> List[KaseQuote]:
        # KASE often serves data as a JSON endpoint — попытка нескольких известных
        candidates = [
            "https://kase.kz/ru/markets/markets-valuation/market-prices?format=json",
            "https://kase.kz/api/v1/bonds/?format=json",
            "https://kase.kz/api/list/bonds/?format=json",
            "https://kase.kz/ru/bonds/data/",
        ]
        for url in candidates:
            try:
                r = await cli.get(url)
                if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
                    continue
                payload = r.json()
                quotes = self._json_to_quotes(payload)
                if quotes:
                    return quotes
            except Exception:
                continue
        return []

    def _json_to_quotes(self, payload) -> List[KaseQuote]:
        if isinstance(payload, dict):
            for key in ("results", "data", "items", "rows"):
                if key in payload and isinstance(payload[key], list):
                    payload = payload[key]
                    break
        if not isinstance(payload, list):
            return []
        out: List[KaseQuote] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            code = item.get("code") or item.get("ticker") or item.get("symbol")
            if not code:
                continue
            out.append(KaseQuote(
                instrument_code=str(code),
                isin=item.get("isin"),
                instrument_name=item.get("name") or item.get("title"),
                close_price=_to_float(item.get("close") or item.get("price") or item.get("last")),
                ytm=_to_float(item.get("ytm") or item.get("yield")),
                accrued_interest=_to_float(item.get("nki") or item.get("aci")),
                duration=_to_float(item.get("duration")),
                source="api",
            ))
        return out

    async def _try_html(self, cli: httpx.AsyncClient, url: str) -> List[KaseQuote]:
        r = await cli.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        # __NUXT__ payload — иногда содержит готовый список
        nuxt_match = re.search(r"window\.__NUXT__\s*=\s*(\{.*?\});</script>", r.text, re.S)
        if nuxt_match:
            try:
                blob = nuxt_match.group(1)
                data = json.loads(blob)
                quotes = self._extract_from_nuxt(data)
                if quotes:
                    return quotes
            except Exception:
                pass

        out: List[KaseQuote] = []
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if not headers:
                continue
            for tr in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if len(cells) < 3:
                    continue
                row = dict(zip(headers, cells))
                code = row.get("код") or row.get("тикер") or cells[0]
                if not code or len(code) > 30:
                    continue
                close_price = (
                    row.get("рыночная цена")
                    or row.get("закрытие")
                    or row.get("цена")
                    or row.get("last")
                )
                out.append(KaseQuote(
                    instrument_code=str(code).strip(),
                    isin=row.get("isin"),
                    instrument_name=row.get("компания") or row.get("наименование") or row.get("название"),
                    close_price=_to_float(close_price),
                    ytm=_to_float(row.get("доходность до погашения, %") or row.get("ytm") or row.get("доходность")),
                    accrued_interest=_to_float(row.get("нкд")),
                    duration=_to_float(row.get("дюрация")),
                    source="html",
                ))
        return out

    def _extract_from_nuxt(self, data) -> List[KaseQuote]:
        """Recursively look for an array of bond items inside the NUXT blob."""
        out: List[KaseQuote] = []

        def walk(obj):
            if isinstance(obj, dict):
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list) and obj and isinstance(obj[0], dict):
                if any("code" in it or "ticker" in it for it in obj):
                    for it in obj:
                        if not isinstance(it, dict):
                            continue
                        code = it.get("code") or it.get("ticker")
                        if not code:
                            continue
                        out.append(KaseQuote(
                            instrument_code=str(code),
                            isin=it.get("isin"),
                            instrument_name=it.get("name") or it.get("title"),
                            close_price=_to_float(it.get("close") or it.get("last") or it.get("price")),
                            ytm=_to_float(it.get("ytm") or it.get("yield")),
                            accrued_interest=_to_float(it.get("nki") or it.get("aci")),
                            duration=_to_float(it.get("duration")),
                            source="nuxt",
                        ))
                else:
                    for el in obj:
                        walk(el)

        walk(data)
        return out


def _to_float(v) -> Optional[float]:
    if v is None or v == "" or v == "-":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(" ", "").replace("\u00A0", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None
