"""Bond / money-market math reproducing the Risk Report (Excel) formulas.

All rates are fractions (0.1067 == 10.67 %).  Amounts are in the currency of
the instrument.  The functions are pure and side-effect free so they can be
unit-tested against values taken from the real Risk Report workbook.

Conventions confirmed on «risk report_31122025_.xlsm»:

* ``30/360`` in the workbook is Excel basis 4 (European 30E/360):
  KZKD00000535, 6.25 bn, 5.49 %, prev coupon 27.03.2025 → accrued on
  31.12.2025 = 6.25e9 × 0.0549 × 273 / 360 = 260 203 125 (RR value).
* «Modified duration» = Excel ``MDURATION`` with the same basis.
* Reverse REPO: accrued is linear between open and close amounts,
  YTM = (close/open − 1) × 366 / term, MD = remaining_days / 365 / (1 + YTM).
"""
from __future__ import annotations

import calendar
from datetime import date
from typing import List, Optional, Tuple

# ───────────────────────── day-count basis ─────────────────────────

BASIS_30E_360 = 4      # Excel basis 4 — European 30/360
BASIS_ACT_ACT = 1
BASIS_ACT_360 = 2
BASIS_ACT_365 = 3
BASIS_30_365 = 30365   # non-Excel: 30/360 day count over a 365 year


def normalize_basis(raw: Optional[str]) -> int:
    """Map the textual «Base» of the Справочник to an Excel-like basis code."""
    text = (raw or "").strip().lower().replace(" ", "").replace("act", "actual")
    text = text.replace("actualual", "actual")
    if not text:
        return BASIS_30E_360
    if text in {"30/360", "30e/360", "30/360e", "4", "0"}:
        return BASIS_30E_360
    if text in {"30/365"}:
        return BASIS_30_365
    if text in {"actual/360", "a/360", "2"}:
        return BASIS_ACT_360
    if text in {"actual/365", "a/365", "actual/365f", "3"}:
        return BASIS_ACT_365
    if text in {"actual/actual", "a/a", "1", "actual/actual(icma)", "actual/actual(isda)"}:
        return BASIS_ACT_ACT
    return BASIS_30E_360


def days360_e(d1: date, d2: date) -> int:
    """Excel DAYS360(d1, d2, TRUE) — European method."""
    day1 = min(d1.day, 30)
    day2 = min(d2.day, 30)
    return (d2.year - d1.year) * 360 + (d2.month - d1.month) * 30 + (day2 - day1)


def is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def year_days(year: int) -> int:
    return 366 if is_leap(year) else 365


def day_count(d1: date, d2: date, basis: int) -> int:
    if basis in (BASIS_30E_360, BASIS_30_365):
        return days360_e(d1, d2)
    return (d2 - d1).days


def _year_fraction_act_act_split(d1: date, d2: date) -> float:
    """Actual/actual as described in the business process: split by calendar year."""
    if d2 <= d1:
        return 0.0
    total = 0.0
    cursor = d1
    while cursor < d2:
        year_end = date(cursor.year, 12, 31)
        boundary = min(d2, date(cursor.year + 1, 1, 1))
        total += (boundary - cursor).days / year_days(cursor.year)
        cursor = boundary
        if cursor > year_end and cursor >= d2:
            break
    return total


def year_fraction(d1: date, d2: date, basis: int) -> float:
    if basis == BASIS_30E_360:
        return days360_e(d1, d2) / 360.0
    if basis == BASIS_30_365:
        return days360_e(d1, d2) / 365.0
    if basis == BASIS_ACT_360:
        return (d2 - d1).days / 360.0
    if basis == BASIS_ACT_365:
        return (d2 - d1).days / 365.0
    return _year_fraction_act_act_split(d1, d2)


# ───────────────────────── coupon schedule ─────────────────────────

def add_months(d: date, months: int, *, eom: bool = False) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    day = last if eom else min(d.day, last)
    return date(year, month, day)


def _is_eom(d: date) -> bool:
    return d.day == calendar.monthrange(d.year, d.month)[1]


def coupon_dates_around(
    settlement: date, maturity: date, frequency: int,
    start: Optional[date] = None,
) -> Tuple[Optional[date], Optional[date], int]:
    """Return (previous coupon date, next coupon date, coupons remaining).

    Kazakhstani issues pay coupons every 12/frequency months counted from the
    start of circulation («дата начала обращения»), the last period may be
    short (e.g. BTRKb17: start 28.11.2024, coupons 28.05/28.11, maturity
    28.03.2026).  When ``start`` is known the schedule is therefore built
    forward from it; otherwise it is generated backwards from maturity
    (Excel COUPPCD/COUPNCD/COUPNUM).  On a coupon date that date is the
    *previous* coupon (accrued interest is zero on the payment date).
    """
    if not maturity or not frequency or frequency <= 0 or settlement >= maturity:
        return None, None, 0
    step = 12 // int(frequency) if 12 % int(frequency) == 0 else 6
    if start is not None and start < maturity and start <= settlement:
        eom = _is_eom(start)
        k = 0
        prev = start
        while True:
            nxt = add_months(start, step * (k + 1), eom=eom)
            if nxt >= maturity:
                nxt = maturity
            if nxt > settlement:
                remaining = 1
                probe = nxt
                j = k + 1
                while probe < maturity and remaining < 2000:
                    j += 1
                    probe = min(add_months(start, step * j, eom=eom), maturity)
                    remaining += 1
                return prev, nxt, remaining
            prev = nxt
            k += 1
            if k > 2000:
                return None, None, 0
    eom = _is_eom(maturity)
    n = 0
    current = maturity
    while True:
        prev = add_months(maturity, -step * (n + 1), eom=eom)
        if prev <= settlement:
            return prev, current, n + 1
        n += 1
        current = prev
        if n > 2000:  # defensive: 2000 periods is far beyond any real bond
            return None, None, 0


def coupon_schedule(
    start: Optional[date], maturity: date, frequency: int,
) -> List[date]:
    """All coupon dates (ascending) after ``start`` up to and including maturity."""
    if not maturity or not frequency:
        return []
    step = 12 // int(frequency) if 12 % int(frequency) == 0 else 6
    out: List[date] = []
    if start is not None and start < maturity:
        eom = _is_eom(start)
        k = 1
        while True:
            d = add_months(start, step * k, eom=eom)
            if d >= maturity:
                out.append(maturity)
                break
            out.append(d)
            k += 1
            if k > 2000:
                break
        return out
    eom = _is_eom(maturity)
    for k in range(0, 200):
        out.append(add_months(maturity, -step * k, eom=eom))
    return sorted(out)


def is_coupon_date(d: date, maturity: Optional[date], frequency: Optional[int],
                   start: Optional[date] = None) -> bool:
    if not maturity or not frequency:
        return False
    if d > maturity:
        return False
    if start is not None and d <= start:
        return False
    prev, _nxt, _n = coupon_dates_around(d, maturity, int(frequency), start)
    return prev == d or d == maturity


def previous_coupon_date(
    d: date, maturity: Optional[date], frequency: Optional[int],
    start: Optional[date] = None,
) -> Optional[date]:
    """Coupon date strictly before ``d`` (the start of the period that ends on/after d)."""
    if not maturity or not frequency:
        return None
    if d > maturity:
        d = maturity
    prev, _nxt, _n = coupon_dates_around(d - _one_day(), maturity, int(frequency), start)
    if prev is None:
        return None
    if start is not None and prev < start:
        return start
    return prev


def _one_day():
    from datetime import timedelta
    return timedelta(days=1)


# ───────────────────────── accrued interest ─────────────────────────

def accrued_interest(
    face_value: float,
    coupon_rate: Optional[float],
    settlement: date,
    maturity: Optional[date],
    frequency: Optional[int],
    basis: int,
    *,
    start: Optional[date] = None,
) -> Optional[float]:
    """НКД на дату ``settlement`` (Accrued interest column of the RR)."""
    if not face_value or coupon_rate is None or not maturity or not frequency:
        return None
    if coupon_rate == 0:
        return 0.0
    if settlement >= maturity:
        return 0.0
    prev, nxt, _ = coupon_dates_around(settlement, maturity, int(frequency), start)
    if prev is None:
        return None
    if basis == BASIS_ACT_ACT:
        # ICMA style: coupon/frequency × elapsed / period length.  For a period
        # inside one year this equals the business-process formula
        # FV × r × days / YearDays; for cross-year periods we use the
        # year-split formula explicitly required by the process description.
        return face_value * coupon_rate * _year_fraction_act_act_split(prev, settlement)
    return face_value * coupon_rate * year_fraction(prev, settlement, basis)


def period_coupon_amount(
    face_value: float,
    coupon_rate: float,
    period_start: date,
    period_end: date,
    basis: int,
) -> float:
    """Coupon for one full period (Accrued interest (debet) / coupon on redemption)."""
    if basis == BASIS_ACT_ACT:
        return face_value * coupon_rate * _year_fraction_act_act_split(period_start, period_end)
    return face_value * coupon_rate * year_fraction(period_start, period_end, basis)


# ───────────────────────── duration ─────────────────────────

def _coupdays(pcd: date, ncd: date, basis: int, frequency: int) -> float:
    if basis in (BASIS_30E_360, BASIS_ACT_360):
        return 360.0 / frequency
    if basis in (BASIS_ACT_365, BASIS_30_365):
        return 365.0 / frequency
    return float((ncd - pcd).days)


def excel_duration(
    settlement: date,
    maturity: date,
    coupon_rate: float,
    yld: float,
    frequency: int,
    basis: int,
) -> Optional[float]:
    """Macaulay duration (years) exactly as Excel DURATION()."""
    if not maturity or settlement >= maturity or frequency not in (1, 2, 4, 12):
        return None
    pcd, ncd, n = coupon_dates_around(settlement, maturity, frequency)
    if pcd is None or ncd is None or n <= 0:
        return None
    e = _coupdays(pcd, ncd, basis, frequency)
    dsc = day_count(settlement, ncd, basis)
    if e <= 0:
        return None
    frac = dsc / e
    y = yld / frequency
    c = coupon_rate * 100.0 / frequency
    if 1 + y <= 0:
        return None
    num = 0.0
    den = 0.0
    for k in range(1, n + 1):
        t = k - 1 + frac
        disc = (1 + y) ** t
        cf = c + (100.0 if k == n else 0.0)
        num += t * cf / disc
        den += cf / disc
    if den == 0:
        return None
    return num / den / frequency


def excel_mduration(
    settlement: date,
    maturity: date,
    coupon_rate: float,
    yld: float,
    frequency: int,
    basis: int,
) -> Optional[float]:
    d = excel_duration(settlement, maturity, coupon_rate, yld, frequency, basis)
    if d is None:
        return None
    return d / (1 + yld / frequency)


def zero_coupon_mduration(settlement: date, maturity: date, yld: float) -> Optional[float]:
    if not maturity or settlement >= maturity:
        return None
    t = (maturity - settlement).days / 365.0
    return t / (1 + (yld or 0.0))


# ───────────────────────── money market ─────────────────────────

def repo_metrics(
    open_amount: float,
    close_amount: Optional[float],
    open_date: date,
    close_date: Optional[date],
    valuation_date: date,
    *,
    rate: Optional[float] = None,
    base: int = 366,
) -> dict:
    """Value of an open reverse REPO on ``valuation_date`` (RR «Repo» sheet).

    accrued = (close − open) × elapsed / term (linear, as in the workbook);
    when the close amount is unknown, accrue ``open × rate × elapsed / base``.
    """
    term = (close_date - open_date).days if close_date else None
    elapsed = max((valuation_date - open_date).days, 0)
    if term:
        elapsed = min(elapsed, term)
    accrued = 0.0
    ytm = None
    if close_amount and term and open_amount:
        accrued = (close_amount - open_amount) * elapsed / term
        ytm = (close_amount / open_amount - 1.0) * base / term
    elif rate:
        accrued = open_amount * rate * elapsed / base
        ytm = rate
    remaining = max((close_date - valuation_date).days, 0) if close_date else None
    md = None
    if remaining is not None:
        md = remaining / 365.0 / (1 + (ytm or 0.0))
    return {
        "accrued": accrued,
        "market_value": (open_amount or 0.0) + accrued,
        "ytm": ytm,
        "duration": md,
        "term_days": term,
        "remaining_days": remaining,
    }


def deposit_metrics(
    principal: float,
    rate: Optional[float],
    open_date: date,
    close_date: Optional[date],
    valuation_date: date,
    *,
    base: int = 360,
) -> dict:
    elapsed = max((valuation_date - open_date).days, 0)
    if close_date:
        elapsed = min(elapsed, (close_date - open_date).days)
    accrued = (principal or 0.0) * (rate or 0.0) * elapsed / base
    remaining = max((close_date - valuation_date).days, 0) if close_date else None
    md = remaining / 365.0 / (1 + (rate or 0.0)) if remaining is not None else None
    return {
        "accrued": accrued,
        "market_value": (principal or 0.0) + accrued,
        "ytm": rate,
        "duration": md,
    }


def rate_fraction(value: Optional[float]) -> Optional[float]:
    """Normalise a rate to a fraction (6.66 → 0.0666, 0.0666 → 0.0666)."""
    if value is None:
        return None
    number = float(value)
    return number / 100.0 if abs(number) > 1.0 else number
