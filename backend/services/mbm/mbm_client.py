"""MBM (Money Benchmark) — fetch the daily YTM and duration values.

Strategy
--------
1. Try Национальный Банк РК page (HTML scrape).
2. Fallback to KASE indices page.
3. As a last resort allow manual upload via the admin UI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from config import settings


@dataclass
class MBMValue:
    index_date: date
    ytm_value: Optional[float]
    duration: Optional[float]
    source: str


class MBMClient:
    def __init__(self) -> None:
        self.nbrk_url = settings.nbrk_mbm_url
        self.kase_indices_url = settings.kase_indices_url
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept-Language": "ru,en;q=0.8",
        }

    async def fetch_latest(self) -> Optional[MBMValue]:
        async with httpx.AsyncClient(timeout=30.0, headers=self._headers, follow_redirects=True) as cli:
            try:
                v = await self._fetch_nbrk(cli)
                if v:
                    return v
            except Exception as exc:
                logger.warning(f"MBM NBRK fetch failed: {exc!r}")
            try:
                v = await self._fetch_kase(cli)
                if v:
                    return v
            except Exception as exc:
                logger.error(f"MBM KASE fallback failed: {exc!r}")
        return None

    async def _fetch_nbrk(self, cli: httpx.AsyncClient) -> Optional[MBMValue]:
        r = await cli.get(self.nbrk_url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        # Ищем число после слова "MBM" / "доходность" / "YTM"
        text = soup.get_text(" ", strip=True)
        ytm = _extract_pct_after(text, ("MBM", "доходност", "YTM"))
        dur = _extract_after(text, ("дюрац",))
        if ytm is None and dur is None:
            return None
        return MBMValue(
            index_date=date.today(),
            ytm_value=ytm,
            duration=dur,
            source="nbrk_html",
        )

    async def _fetch_kase(self, cli: httpx.AsyncClient) -> Optional[MBMValue]:
        r = await cli.get(self.kase_indices_url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
                if any("mbm" in c.lower() for c in cells):
                    nums = [_to_float(c) for c in cells]
                    nums = [n for n in nums if n is not None]
                    if nums:
                        return MBMValue(
                            index_date=date.today(),
                            ytm_value=nums[0],
                            duration=nums[1] if len(nums) > 1 else None,
                            source="kase_html",
                        )
        return None


def _extract_pct_after(text: str, anchors) -> Optional[float]:
    for anchor in anchors:
        m = re.search(rf"{anchor}[^0-9]{{0,40}}([0-9]+[\.,][0-9]+)\s*%?", text, re.IGNORECASE)
        if m:
            return _to_float(m.group(1))
    return None


def _extract_after(text: str, anchors) -> Optional[float]:
    for anchor in anchors:
        m = re.search(rf"{anchor}[^0-9]{{0,40}}([0-9]+[\.,][0-9]+)", text, re.IGNORECASE)
        if m:
            return _to_float(m.group(1))
    return None


def _to_float(s) -> Optional[float]:
    if s is None or s == "" or s == "-":
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).replace(" ", "").replace("\u00A0", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None
