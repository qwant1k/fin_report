"""Classify operation type and instrument category by raw row attributes.

The rules can be overridden in the database (InstrumentCategoryRule) to make
the classification editable from the admin UI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

# ───────── Operation type ─────────
# Семантика (Phase B):
#   REPO/EBRP — 2 строки (К = открытие, П = закрытие). Строка "Разм" игнорируется
#   (только анкер).
#   BUY / SELL — обычные биржевые сделки.
#   FX_BUY / FX_SELL — валютные сделки (режимы FXDE, FXSW и т.п.).
#   DEPOSIT_OPEN / DEPOSIT_CLOSE — размещение/возврат депозита (режим T-Bill, депозит).
#   COUPON / REDEMPTION — генерируются движком Phase C, не приходят из TradeReport.
#   CASH_TOPUP / CASH_WITHDRAW — корреспонденция с NBRK.
def classify_operation(
    regime: Optional[str],
    kp: Optional[str],
    instrument_code: Optional[str] = None,
    currency_code: Optional[str] = None,
    clearing_account: Optional[str] = None,
) -> str:
    """Map raw row attributes to canonical operation type used internally."""
    r = (regime or "").strip().upper()
    k = (kp or "").strip()
    ccy = (currency_code or "").strip().upper()
    code = (instrument_code or "").strip().upper()

    # 1. REPO / EBRP
    if r in ("EBRP", "REPO"):
        if k in ("К", "B"):
            return "REPO_OPEN"
        if k in ("П", "S"):
            return "REPO_CLOSE"
        # Разм — анкер без движения, будет отфильтрован при записи в Trade
        return "REPO_HEADER"

    # 2. FX (валютные сделки)
    if r.startswith(("FX", "FXDE", "FXSW")) or ccy in ("USD", "EUR", "GBP", "CNY"):
        if k in ("К", "B"):
            return "FX_BUY"
        if k in ("П", "S"):
            return "FX_SELL"

    # 3. Депозиты (T-Bill, DEP, MMKT и т.п.)
    if r in ("T-BILL", "DEP", "MMKT", "DEPOSIT", "TREASURY", "NOTES") or \
       "DEP" in clearing_account.upper() if clearing_account else False or \
       (code and code.startswith(("DEP", "TB"))):
        if k in ("К", "B"):
            return "DEPOSIT_OPEN"
        if k in ("П", "S"):
            return "DEPOSIT_CLOSE"

    # 4. Стандартные сделки с ЦБ
    if k in ("К", "B"):
        return "BUY"
    if k in ("П", "S"):
        return "SELL"

    return "OTHER"


# ───────── Instrument category — default rules ─────────
@dataclass(frozen=True)
class CategoryRule:
    priority: int
    name: str
    target_category: str
    regimes: tuple = ()
    code_prefixes: tuple = ()
    code_regex: Optional[str] = None

    def match(self, regime: Optional[str], code: Optional[str]) -> bool:
        r = (regime or "").strip().upper()
        c = (code or "").strip()
        if self.regimes and r in self.regimes:
            return True
        if self.code_prefixes and any(c.startswith(p) for p in self.code_prefixes):
            return True
        if self.code_regex and re.match(self.code_regex, c):
            return True
        return False


DEFAULT_RULES: List[CategoryRule] = [
    CategoryRule(10, "Reverse REPO (биржевое)", "REVERSE_REPO", regimes=("EBRP", "REPO")),
    CategoryRule(15, "Foreign bonds / Eurobonds", "FOREIGN_BONDS",
                 code_prefixes=("XS", "US", "RU", "XS2", "XS3", "XS4", "XS5", "XS6", "XS7", "XS8", "XS9")),
    CategoryRule(17, "Deposits / T-Bills", "DEPOSIT",
                 regimes=("T-BILL", "DEP", "MMKT", "TREASURY", "NOTES")),
    CategoryRule(20, "ГЦБ МФ РК (KFUS*)", "GOV_BONDS", code_prefixes=("KFUS", "MFRK")),
    CategoryRule(30, "Агентские облигации (EABR*)", "AGENCY_BONDS", code_prefixes=("EABR", "EAB")),
    CategoryRule(40, "МФО облигации (MFO*)", "MFO_BONDS", code_prefixes=("MFO",)),
    CategoryRule(90, "Прочее", "OTHER"),
]


def classify_instrument(
    regime: Optional[str],
    code: Optional[str],
    rules: Optional[Iterable[CategoryRule]] = None,
) -> str:
    """Pick the highest-priority matching category rule."""
    rules_list = sorted(rules or DEFAULT_RULES, key=lambda x: x.priority)
    for rule in rules_list:
        if rule.match(regime, code):
            return rule.target_category
    return "OTHER"


# ───────── ЧДУ identification ─────────
# Порядок важен: более специфичные префиксы идут раньше (HALFN перед HALYK).
DEFAULT_CDU_PREFIXES: dict[str, str] = {
    "HALFN": "Halyk Finance",
    "HALY":  "Halyk Finance",
    "BCC":   "BCC Invest",
    "JUSAN": "Jusan Invest",
    "JYS":   "Jusan Invest",
    "CAIFC": "Centras Securities",
    "CENTR": "Centras Securities",
    "TANSAR":"Tansar Capital",
    "TANSA": "Tansar Capital",
    "UDCAP": "UD Capital",
    "UD":    "UD Capital",
    "310138":"НБ РК (Собственные средства)",   # собст портфель
    "300138":"НБ РК (Специальный резерв)",      # спец портфель
}


def detect_cdu_prefix(participant_code: Optional[str], filename: str) -> Optional[str]:
    """Detect CDU prefix from participant code or filename.

    Приоритет: более длинные совпадения побеждают (например HALFN перед HALY).
    """
    src = (participant_code or "").upper() + "|" + (filename or "").upper()
    # Сортируем по убыванию длины для greedy matching
    for prefix in sorted(DEFAULT_CDU_PREFIXES, key=lambda p: -len(p)):
        if prefix in src:
            return prefix
    return None
