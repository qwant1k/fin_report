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
    type_code: Optional[str] = None,
) -> str:
    """Map raw row attributes to canonical operation type used internally."""
    r = (regime or "").strip().upper()
    k = (kp or "").strip().upper()
    ccy = (currency_code or "").strip().upper()
    code = (instrument_code or "").strip().upper()
    t = (type_code or "").strip()

    # 1. REPO. KASE exports use two variants:
    #    Halyk: Разм / К / П
    #    BCC/Centras: S(G) / B(H) / S(h), where the first S is a header.
    if r in ("EBRP", "EBWP", "REPO"):
        if t == "G" or k in ("РАЗМ", "РАЗМ.", "PLACEMENT"):
            return "REPO_HEADER"
        if t == "H" or k in ("К", "B"):
            return "REPO_OPEN"
        if t == "h" or k in ("П", "S"):
            return "REPO_CLOSE"
        return "REPO_HEADER"

    # 2. FX (валютные сделки).  Валюта расчётов сама по себе не является
    # признаком FX: обычная покупка иностранной облигации также может
    # рассчитываться в USD/EUR.  Поэтому используем режим торгов либо явно
    # валютный код инструмента (например USDKZT_TOM).
    fx_currency = r"(?:USD|EUR|GBP|CNY|RUB|KZT)"
    is_fx_instrument = bool(re.match(rf"^{fx_currency}{fx_currency}(?:_|$)", code))
    if r.startswith(("FX", "FXDE", "FXSW")) or is_fx_instrument:
        if k in ("К", "B"):
            return "FX_BUY"
        if k in ("П", "S"):
            return "FX_SELL"

    # 3. Депозиты (T-Bill, DEP, MMKT и т.п.)
    is_deposit_account = "DEP" in clearing_account.upper() if clearing_account else False
    if (
        r in ("T-BILL", "DEP", "MMKT", "DEPOSIT", "TREASURY", "NOTES")
        or is_deposit_account
        or (code and code.startswith(("DEP", "TB")))
    ):
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
    CategoryRule(10, "Reverse REPO (биржевое)", "REVERSE_REPO", regimes=("EBRP", "EBWP", "REPO")),
    CategoryRule(15, "Foreign bonds / Eurobonds", "FOREIGN_BONDS",
                 code_regex=r"^(XS|US)[A-Z0-9]{9}\d$"),
    CategoryRule(17, "Deposits / T-Bills", "DEPOSIT",
                 regimes=("T-BILL", "DEP", "MMKT", "TREASURY", "NOTES")),
    # ГЦБ: МЕОКАМ/МЕУКАМ/МЕККАМ/МУИКАМ Минфина, ноты НБРК, облигации МИО.
    CategoryRule(20, "ГЦБ (МФ РК, НБ РК, МИО)", "GOV_BONDS",
                 code_prefixes=("MUM", "MOM", "MKM", "MEU", "MUJ", "MTM", "MTC", "NTK", "KZ_MGB", "MFRK")),
    # Агентские (квазигосударственный сектор).  KFUS — АО «Казахстанский фонд
    # устойчивости» (КФУ) по п. 6.2.2 D относится к Агентским, не к ГЦБ.
    CategoryRule(30, "Агентские облигации (квазигоссектор)", "AGENCY_BONDS",
                 code_prefixes=("KFUS", "BTRK", "BRKZ", "KEGC", "ZHSS", "TMJL", "SKKZ", "AGKK", "DAMU")),
    # МФО = международные финансовые организации (ЕАБР, АБР, ЕБРР, IFC).
    # ВНИМАНИЕ: тикеры KASE «MFO…/MF…» — это МИКРОфинансовые организации,
    # они сюда не относятся.
    CategoryRule(40, "МФО (международные финансовые организации)", "MFO_BONDS",
                 code_prefixes=("EABR", "ASDB", "EBRD", "IFCN", "IBRD")),
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
    "KIBAM": "BCC Invest",          # код участника KASE «BCC Invest» (KIBAM0BT11)
    "JUSAN": "Jusan Invest",
    "JYS":   "Jusan Invest",
    # KASE: CAIFC — АО «Tansar Capital» (бывш. CAIFC Investment Group),
    # CESEC — АО «Centras Securities».
    "CAIFC": "Tansar Capital",
    "CESEC": "Centras Securities",
    "CENTR": "Centras Securities",
    "TANSAR":"Tansar Capital",
    "TANSA": "Tansar Capital",
    "TANSR": "Tansar Capital",
    "ALATAU": "Alatau City Invest",
    "DRBES": "Alatau City Invest",  # код участника KASE «Alatau City Invest» (DRBES0BT08)
    "ALATA": "Alatau City Invest",
    "ACI":   "Alatau City Invest",
    "UDCAP": "UD Capital",
    "UD":    "UD Capital",
    "310138":"НБ РК (Собственные средства)",   # собст портфель
    "300138":"НБ РК (Специальный резерв)",      # спец портфель
}

# Short prefixes produce false positives inside other codes (e.g. «UD» in
# «STUDY», «ACI» in «PLACING»), so they must start a token.
_TOKEN_START_PREFIXES = {"UD", "ACI", "BCC", "JYS"}


def _match_prefix(src: str) -> Optional[str]:
    for prefix in sorted(DEFAULT_CDU_PREFIXES, key=lambda p: -len(p)):
        if prefix in _TOKEN_START_PREFIXES:
            if re.search(rf"(^|[^A-Z0-9]){re.escape(prefix)}", src):
                return prefix
        elif prefix in src:
            return prefix
    return None


def detect_cdu_prefix(participant_code: Optional[str], filename: str) -> Optional[str]:
    """Detect CDU prefix from participant code or filename.

    Приоритет: идентификаторы из файла (код участника / фирмы / торговый
    счёт), затем имя файла.  Более длинные совпадения побеждают
    (например HALFN перед HALY).  Код клиринговой фирмы сюда передавать
    нельзя: «CENTR_K» — клиринговый член для нескольких управляющих.
    """
    participant_src = (participant_code or "").upper()
    filename_src = (filename or "").upper()
    if participant_src:
        found = _match_prefix(participant_src)
        if found:
            return found
    if re.search(r"(^|[^A-Z0-9])JI([^A-Z0-9]|$)", filename_src):
        return "JUSAN"
    return _match_prefix(filename_src)
