"""Domain constants for the portfolio calculator."""
from __future__ import annotations

import re

from typing import Dict, List

# Order in which categories are shown in the report (matches Excel layout)
CATEGORY_ORDER: List[str] = [
    "CASH",
    "GOV_BONDS",
    "REVERSE_REPO",
    "MFO_BONDS",
    "AGENCY_BONDS",
    "FOREIGN_BONDS",
    "DEPOSIT",
    "RECEIVABLES",
]

# Russian labels exactly like in the original risk report
CATEGORY_LABELS: Dict[str, str] = {
    "CASH": "Cash",
    "GOV_BONDS": "Государственные облигации (МФ РК)",
    "REVERSE_REPO": "Обратное REPO",
    "MFO_BONDS": "МФО (не ниже «А-»)",
    "AGENCY_BONDS": "Агентские облигации (не ниже «BB-»)",
    "FOREIGN_BONDS": "Иностранные ЦБ (USD)",
    "DEPOSIT": "Депозиты",
    "RECEIVABLES": "Дебиторская задолженность",
    "OTHER": "Прочее",
}

# Default limits derived from the original risk_report.xlsm formulas
# (min_pct, max_pct).  Hard/Soft mirror max by default; admin can edit.
DEFAULT_LIMITS: Dict[str, tuple[float, float]] = {
    "CASH":          (0.0, 0.001),   # 0.1%
    "GOV_BONDS":     (0.0, 1.0),     # 100%
    "REVERSE_REPO":  (0.0, 0.5),     # 50%
    "MFO_BONDS":     (0.0, 0.075),   # 7.5%
    "AGENCY_BONDS":  (0.0, 0.075),   # 7.5%
    "FOREIGN_BONDS": (0.0, 1.0),     # 100% (только для НБ РК спецрезерв)
    "DEPOSIT":       (0.0, 1.0),     # 100% (только для НБ РК)
    "RECEIVABLES":   (0.0, 1.0),     # 100%
}

# Portfolio types — для разных бизнес-правил
PORTFOLIO_TYPE_PRIVATE_CDU = "PRIVATE_CDU"   # частный доверительный управляющий
PORTFOLIO_TYPE_NBRK_OWN = "NBRK_OWN"         # НБ РК собственные активы
PORTFOLIO_TYPE_NBRK_RESERVE = "NBRK_RESERVE" # НБ РК спецрезерв

# Duration vs benchmark (Risk Report, Report!E18/F18): the corridor is
# relative — «−0,2» / «+0,5» in the header mean −20 % / +50 % of the MBM
# duration: lower = benchmark × 0.8, upper = benchmark × 1.5.
DURATION_LOWER_MULT = 0.8
DURATION_UPPER_MULT = 1.5
# kept for backward compatibility of imports (relative offsets)
DURATION_LOWER_OFFSET = DURATION_LOWER_MULT - 1.0
DURATION_UPPER_OFFSET = DURATION_UPPER_MULT - 1.0


def duration_band(benchmark):
    """(lower, upper) duration corridor for a benchmark duration, or (None, None)."""
    if benchmark is None:
        return None, None
    from services.formulas import params      # editable in «Формулы → Параметры расчёта»
    return benchmark * params.get("duration_lower_mult"), benchmark * params.get("duration_upper_mult")

# Tolerance for reconciliation (per spec section 8)
RECON_TOLERANCE_KZT = 0.01    # ±0.01 KZT
RECON_TOLERANCE_USD = 0.01    # ±0.01 USD
RECON_TOLERANCE_PRICE = 0.000001  # ±0.000001 цены
RECON_TOLERANCE_PCT = 0.0001  # 0.01% (для процентов)

# 7 ЧДУ + 2 портфеля НБ РК. Доли — округлено до 1/6 ≈ 16.67% по умолчанию,
# реальные share_target_pct редактируются в админке.
DEFAULT_CDU_SEED = [
    # Частные ДУ
    {
        "name": "Halyk Finance", "short_name": "Halyk",
        "participant_code_prefix": "HALFN", "share_target_pct": 0.1667,
        "report_code": "SR_PAM_HALFN",
        "portfolio_type": PORTFOLIO_TYPE_PRIVATE_CDU, "portfolio_code": None,
    },
    {
        "name": "BCC Invest", "short_name": "BCC",
        "participant_code_prefix": "BCC", "share_target_pct": 0.1667,
        "report_code": "SR_PAM_BCC",
        "portfolio_type": PORTFOLIO_TYPE_PRIVATE_CDU, "portfolio_code": None,
    },
    {
        "name": "Jusan Invest", "short_name": "Jusan",
        "participant_code_prefix": "JUSAN", "share_target_pct": 0.1667,
        "report_code": "SR_PAM_JUSAN",
        "portfolio_type": PORTFOLIO_TYPE_PRIVATE_CDU, "portfolio_code": None,
    },
    {
        "name": "Centras Securities", "short_name": "Centras",
        "participant_code_prefix": "CENTR", "share_target_pct": 0.1667,
        "report_code": "SR_PAM_CESEC",
        "portfolio_type": PORTFOLIO_TYPE_PRIVATE_CDU, "portfolio_code": None,
    },
    {
        "name": "Tansar Capital", "short_name": "Tansar",
        "participant_code_prefix": "TANSR", "share_target_pct": 0.1667,
        "report_code": "SR_PAM_CAIFC",
        "portfolio_type": PORTFOLIO_TYPE_PRIVATE_CDU, "portfolio_code": None,
    },
    {
        "name": "Alatau City Invest", "short_name": "Alatau",
        "participant_code_prefix": "ALATAU", "share_target_pct": 0.0,
        "report_code": "SR_PAM_ACI",
        "portfolio_type": PORTFOLIO_TYPE_PRIVATE_CDU, "portfolio_code": None,
    },
    {
        "name": "UD Capital", "short_name": "UD Capital",
        "participant_code_prefix": "UDCAP", "share_target_pct": 0.1667,
        "report_code": "SR_PAM_UDCAP",
        "portfolio_type": PORTFOLIO_TYPE_PRIVATE_CDU, "portfolio_code": None,
    },
    # Портфели НБ РК
    {
        "name": "НБ РК — Собственные активы", "short_name": "НБ РК (собст)",
        "participant_code_prefix": "NBRK", "share_target_pct": 0.0,
        "report_code": None,
        "portfolio_type": PORTFOLIO_TYPE_NBRK_OWN, "portfolio_code": "310138-1",
    },
    {
        "name": "НБ РК — Спецрезерв", "short_name": "НБ РК (спец)",
        "participant_code_prefix": "NBRK", "share_target_pct": 0.0,
        "report_code": None,
        "portfolio_type": PORTFOLIO_TYPE_NBRK_RESERVE, "portfolio_code": "300138-1",
    },
]

# Маппинг PORTFOLIO кода НБ РК на portfolio_type
NBRK_PORTFOLIO_MAP: Dict[str, str] = {
    "310138-1": PORTFOLIO_TYPE_NBRK_OWN,
    "300138-1": PORTFOLIO_TYPE_NBRK_RESERVE,
}

# Sub-fund алиасы (как в Risk Report) для ЧДУ → каноническое имя
CDU_NAME_ALIASES: Dict[str, str] = {
    # ЧДУ (латиница, кириллица, юридические названия)
    "halyk finance": "Halyk Finance",
    "halfn": "Halyk Finance",
    "halyk": "Halyk Finance",
    "hf": "Halyk Finance",
    "халык финанс": "Halyk Finance",
    "народного банка казахстана": "Halyk Finance",
    "bcc invest": "BCC Invest",
    "bcc": "BCC Invest",
    "бцк инвест": "BCC Invest",
    "kibam": "BCC Invest",
    "jusan invest": "Jusan Invest",
    "jusan": "Jusan Invest",
    "ji": "Jusan Invest",            # «Приложение 3 Сверка_JI_…»
    "jysan": "Jusan Invest",
    "жусан": "Jusan Invest",
    "centras": "Centras Securities",
    "centras securities": "Centras Securities",
    "centr": "Centras Securities",
    "cesec": "Centras Securities",
    "сентрас": "Centras Securities",  # русская транслитерация в Risk Report
    "сентрас секьюритиз": "Centras Securities",
    "tansar": "Tansar Capital",
    "tansar capital": "Tansar Capital",
    "тансар": "Tansar Capital",
    "caifc": "Tansar Capital",
    "alatau": "Alatau City Invest",
    "alatau city invest": "Alatau City Invest",
    "alatau citi invest": "Alatau City Invest",
    "alatau invest": "Alatau City Invest",
    "алатау": "Alatau City Invest",
    "drbes": "Alatau City Invest",
    "aci": "Alatau City Invest",
    "ud capital": "UD Capital",
    "udcap": "UD Capital",
    "ud": "UD Capital",
    "юди капитал": "UD Capital",
    # Портфели НБ РК
    "собст": "НБ РК — Собственные активы",
    "собственные": "НБ РК — Собственные активы",
    "собственные активы": "НБ РК — Собственные активы",
    "собственные средства": "НБ РК — Собственные активы",
    "специальный": "НБ РК — Спецрезерв",
    "специальный резерв": "НБ РК — Спецрезерв",
    "спецрезерв": "НБ РК — Спецрезерв",
    "соб": "НБ РК — Собственные активы",
    "own": "НБ РК — Собственные активы",
    "спец": "НБ РК — Спецрезерв",
    "сп": "НБ РК — Спецрезерв",
    "reserve": "НБ РК — Спецрезерв",
    "spec": "НБ РК — Спецрезерв",
}


def normalize_cdu_name(raw: str | None) -> str | None:
    """Привести любое представление ЧДУ к каноническому имени из DEFAULT_CDU_SEED.

    Понимает юридические названия («АО "Сентрас Секьюритиз"», «АО "Дочерняя
    организация Народного Банка Казахстана "Halyk Finance"»), кириллицу и коды
    участников KASE.  Псевдонимы ищутся целыми словами, длинные — первыми,
    поэтому «ud» не срабатывает внутри «Study», а «сп» — внутри «Сентрас».
    """
    if not raw:
        return None
    key = re.sub(r"[«»\"'`“”„.,()]+", " ", str(raw).strip().lower().replace("ё", "е"))
    key = re.sub(r"\s+", " ", key).strip()
    if key in CDU_NAME_ALIASES:
        return CDU_NAME_ALIASES[key]
    if key in {v.lower() for v in CDU_NAME_ALIASES.values()}:
        return next(v for v in CDU_NAME_ALIASES.values() if v.lower() == key)
    for alias in sorted(CDU_NAME_ALIASES, key=len, reverse=True):
        if re.search(rf"(?<![0-9a-zа-я]){re.escape(alias)}(?![0-9a-zа-я])", key):
            return CDU_NAME_ALIASES[alias]
    return None
    key = str(raw).strip().lower()
    if key in CDU_NAME_ALIASES:
        return CDU_NAME_ALIASES[key]
    # Проверим вхождение — например, в Sub portfolio name = "UD Capital, KZT"
    for alias, canonical in CDU_NAME_ALIASES.items():
        if alias in key:
            return canonical
    return None
