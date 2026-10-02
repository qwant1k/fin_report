"""Security master (Справочник) helpers shared by importers and the engine.

* ``ReferenceBook`` — in-memory index of ``InstrumentReference`` by ISIN and
  KASE ticker (Trade Reports carry tickers, Risk Report lots carry ISINs).
* ``category_from_reference`` — category by the business-process rule 6.2.2 D
  (type of issuer), which has priority over ticker-prefix heuristics.
"""
from __future__ import annotations

from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.db_models import InstrumentReference, KasePrice

BOND_CATEGORIES = ("GOV_BONDS", "AGENCY_BONDS", "MFO_BONDS", "FOREIGN_BONDS")

_TYPE_TO_CATEGORY = {
    "гцб": "GOV_BONDS",
    "государственные": "GOV_BONDS",
    "агентские": "AGENCY_BONDS",
    "агентсткие": "AGENCY_BONDS",
    "мфо": "MFO_BONDS",
    "международные финансовые организации": "MFO_BONDS",
    "ин. цб": "FOREIGN_BONDS",
    "ин.цб": "FOREIGN_BONDS",
    "иностранные": "FOREIGN_BONDS",
    "бумаги местных исполнительных органов": "GOV_BONDS",
    "мио": "GOV_BONDS",
}

# Issuer keywords (business process 6.2.2 D).  Order matters: the more
# specific multilateral names are checked before generic «банк развития».
_ISSUER_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("MFO_BONDS", (
        "евразийский банк развития", "азиатский банк развития",
        "европейский банк реконструкции", "международная финансовая корпорация",
        "международный банк реконструкции", "исламский банк развития",
        "eurasian development bank", "asian development bank", "ebrd",
        "international finance corporation",
    )),
    ("GOV_BONDS", (
        "министерство финансов", "национальный банк республики казахстан",
        "национальный банк рк", "нбрк", "акимат",
    )),
    ("AGENCY_BONDS", (
        "kegoc", "банк развития казахстана", "отбасы", "жилищный строительный",
        "казахстанский фонд устойчивости", "темір жолы", "темир жолы",
        "байтерек", "самрук", "аграрная кредитная", "фонд развития предпринимательства",
        "даму", "казахстанская жилищная компания", "қазақстан темір жолы",
    )),
)

# Ticker prefixes — only a fallback when the Справочник has no answer.
# Note: KASE tickers starting with «MFO»/«MF» belong to МИКРОфинансовые
# организации (corporate risk!), they must NOT be classified as МФО
# (international financial organisations).
_TICKER_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("GOV_BONDS", ("MUM", "MOM", "MKM", "MEU", "MUJ", "MTM", "MTC", "NTK", "KZ_MGB", "KZ_MUM")),
    ("AGENCY_BONDS", ("KFUS", "BTRK", "BRKZ", "KEGC", "ZHSS", "TMJL", "SKKZ", "AGKK", "DAMU")),
    ("MFO_BONDS", ("EABR", "ASDB", "EBRD", "IFC", "IBRD", "ISDB")),
)


def category_from_type_text(text: Optional[str]) -> Optional[str]:
    key = (text or "").strip().lower()
    if not key:
        return None
    if key in _TYPE_TO_CATEGORY:
        return _TYPE_TO_CATEGORY[key]
    for needle, category in _TYPE_TO_CATEGORY.items():
        if needle in key:
            return category
    return None


def category_from_issuer(issuer: Optional[str]) -> Optional[str]:
    haystack = (issuer or "").strip().lower().replace("ё", "е")
    if not haystack:
        return None
    for category, needles in _ISSUER_RULES:
        if any(n in haystack for n in needles):
            return category
    return None


def category_from_ticker(ticker: Optional[str], isin: Optional[str] = None) -> Optional[str]:
    code = (ticker or "").strip().upper()
    for category, prefixes in _TICKER_RULES:
        if code.startswith(prefixes):
            return category
    isin_u = (isin or code).strip().upper()
    if isin_u.startswith(("XS", "US")) and len(isin_u) == 12:
        return "FOREIGN_BONDS"
    if isin_u.startswith(("KZK", "KZW1")):
        return "GOV_BONDS"
    return None


def category_from_reference(ref: Optional[InstrumentReference]) -> Optional[str]:
    if ref is None:
        return None
    for text in (ref.issuer_type, ref.bond_type):
        category = category_from_type_text(text)
        if category:
            return category
    category = category_from_issuer(ref.issuer)
    if category:
        return category
    return None


class ReferenceBook:
    """Cached lookup of the security master by ISIN or KASE ticker."""

    def __init__(self, db: Session):
        self.db = db
        self._by_isin: Dict[str, InstrumentReference] = {}
        self._by_ticker: Dict[str, InstrumentReference] = {}
        self._ticker_to_isin: Dict[str, str] = {}
        self._schedules: Optional[dict] = None
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        for ref in self.db.execute(select(InstrumentReference)).scalars():
            if ref.isin:
                self._by_isin[ref.isin.strip().upper()] = ref
            if ref.ticker_kase:
                self._by_ticker[ref.ticker_kase.strip().upper()] = ref
                if ref.isin:
                    self._ticker_to_isin[ref.ticker_kase.strip().upper()] = ref.isin.strip().upper()
        # KASE quotes carry both identifiers — use them to fill the gaps.
        rows = self.db.execute(
            select(KasePrice.instrument_code, KasePrice.isin)
            .where(KasePrice.isin.is_not(None))
            .distinct()
        ).all()
        for code, isin in rows:
            if code and isin:
                self._ticker_to_isin.setdefault(code.strip().upper(), isin.strip().upper())
        self._loaded = True

    def get(self, identifier: Optional[str]) -> Optional[InstrumentReference]:
        if not identifier:
            return None
        self._load()
        key = identifier.strip().upper()
        ref = self._by_isin.get(key) or self._by_ticker.get(key)
        if ref is None and key in self._ticker_to_isin:
            ref = self._by_isin.get(self._ticker_to_isin[key])
        return ref

    def schedule(self, identifier: Optional[str]) -> list:
        """Coupon payment schedule of the issue (empty when not maintained)."""
        if not identifier:
            return []
        if self._schedules is None:
            from services.portfolio.coupon_schedule import load_all
            self._schedules = load_all(self.db)
        if not self._schedules:
            return []
        key = identifier.strip().upper()
        rows = self._schedules.get(key)
        if rows is None:
            ref = self.get(key)
            if ref is not None:
                rows = self._schedules.get((ref.isin or "").strip().upper()) \
                    or self._schedules.get((ref.ticker_kase or "").strip().upper())
        return rows or []

    def isin_for(self, identifier: Optional[str]) -> Optional[str]:
        """Resolve a ticker (or ISIN) to an ISIN; returns None when unknown."""
        if not identifier:
            return None
        self._load()
        key = identifier.strip().upper()
        if key in self._by_isin:
            return key
        if key in self._ticker_to_isin:
            return self._ticker_to_isin[key]
        if len(key) == 12 and key[:2].isalpha() and key[-1].isdigit():
            return key  # looks like an ISIN already
        return None

    def category(self, identifier: Optional[str], fallback: Optional[str] = None,
                 *, ticker: Optional[str] = None) -> str:
        ref = self.get(identifier) or self.get(ticker)
        category = category_from_reference(ref)
        if category:
            return category
        category = category_from_ticker(ticker or identifier, identifier)
        if category:
            return category
        return fallback or "OTHER"


def resolve_category(db: Session, identifier: Optional[str], fallback: Optional[str] = None,
                     *, ticker: Optional[str] = None) -> str:
    return ReferenceBook(db).category(identifier, fallback, ticker=ticker)

