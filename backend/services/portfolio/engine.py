"""Portfolio engine: holdings of a CDU on any date T and their valuation.

Business process 6.1.1: RR(T) is RR(T−1) plus the operations of day T,
revalued at the prices of day T.  The engine reproduces this roll-forward:

1. **Base slice** — the latest Risk Report snapshot ≤ T imported for the
   CDU (``BondLot``/``RepoLot``/``DepositLot`` rows of a ``RISK_REPORT_XLSM``
   source document).  Without a snapshot the base is empty.
2. **Movements** — effective operations of the ``Trade`` ledger whose value
   date lies in (base, T]: purchases create lots («1 сделка = 1 лот»),
   sales are written off FIFO, redemptions close the lots, REPO/deposits are
   opened/closed by their lots.
3. **Valuation at T** — price hierarchy market → risk parameters → last
   available market price (stale) → snapshot price → purchase price;
   accrued interest and modified duration with the workbook formulas
   (see ``bond_math``), FX conversion at the NBRK rate on T.

The engine never mutates stored lots, so historical snapshots stay intact
and any date can be recalculated idempotently.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from models.db_models import (
    BondLot,
    DepositLot,
    FXRate,
    KasePrice,
    KaseRiskPrice,
    PortfolioPosition,
    RepoLot,
    SourceDocument,
    Trade,
)
from services.workflow import EFFECTIVE_STATUSES

from . import bond_math as bm
from .reference import ReferenceBook

RR_DOC_TYPE = "RISK_REPORT_XLSM"
BOND_CATEGORIES = ("GOV_BONDS", "AGENCY_BONDS", "MFO_BONDS", "FOREIGN_BONDS")
MAX_STALE_PRICE_DAYS = 14
_RETIRED_STATUSES = ("погашено", "выбыл", "погашен", "matured", "redeemed")


# ════════════════════════════ data classes ════════════════════════════

@dataclass
class BondPosition:
    cdu_id: int
    isin: str
    ticker: Optional[str]
    category: str
    currency: str
    face_value: float
    trade_date: Optional[date]
    settlement_date: Optional[date]
    purchase_price: Optional[float] = None
    origin: str = "risk_report"          # risk_report | trade | manual
    trade_id: Optional[int] = None
    seq: int = 0
    snapshot_date: Optional[date] = None
    snapshot_price: Optional[float] = None
    snapshot_accrued: Optional[float] = None
    snapshot_total: Optional[float] = None
    snapshot_ytm: Optional[float] = None
    snapshot_duration: Optional[float] = None
    trade_ytm: Optional[float] = None
    unit_nominal: Optional[float] = None   # face value of one security
    source_doc_id: Optional[int] = None    # document the lot came from (RR / Trade Report / ...)
    # valuation (filled by ``value_bond``)
    maturity_date: Optional[date] = None
    price: Optional[float] = None
    price_source: Optional[str] = None
    price_date: Optional[date] = None
    accrued: float = 0.0
    clean_value: float = 0.0
    total_value: float = 0.0              # in instrument currency
    fx_rate: float = 1.0
    total_value_kzt: float = 0.0
    ytm: Optional[float] = None
    duration: Optional[float] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class MoneyMarketPosition:
    kind: str                              # REPO | DEPOSIT
    cdu_id: int
    identifier: Optional[str]
    deal_id: Optional[str]
    open_date: date
    close_date: Optional[date]
    open_amount: float
    close_amount: Optional[float]
    rate: Optional[float]
    base: int
    origin: str
    quantity: Optional[float] = None       # securities received as collateral
    collateral: Optional[str] = None       # ticker / ISIN of the collateral
    source_doc_id: Optional[int] = None
    trade_id: Optional[int] = None
    accrued: float = 0.0
    market_value: float = 0.0
    ytm: Optional[float] = None
    duration: Optional[float] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class PortfolioState:
    cdu_id: int
    as_of: date
    base_date: Optional[date]
    bonds: List[BondPosition] = field(default_factory=list)
    repos: List[MoneyMarketPosition] = field(default_factory=list)
    deposits: List[MoneyMarketPosition] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # Cash flows implied by snapshot positions that matured in (base, T]
    # (e.g. a reverse REPO from the Risk Report closed on T−2).  The
    # calculator books them unless the real cash movement is already loaded.
    implied_cash: List[dict] = field(default_factory=list)

    def by_category(self) -> Dict[str, dict]:
        """Category aggregates weighted by total value (as the RR «Weight»)."""
        out: Dict[str, dict] = {}

        def bucket(cat: str) -> dict:
            return out.setdefault(cat, {
                "mv": 0.0, "ytm_w": 0.0, "ytm_wt": 0.0,
                "dur_w": 0.0, "dur_wt": 0.0, "lots": 0, "face": 0.0,
            })

        for b in self.bonds:
            if abs(b.total_value_kzt) < 1e-9:
                continue
            row = bucket(b.category)
            row["mv"] += b.total_value_kzt
            row["face"] += b.face_value * b.fx_rate
            row["lots"] += 1
            if b.ytm is not None:
                row["ytm_w"] += b.ytm * b.total_value_kzt
                row["ytm_wt"] += b.total_value_kzt
            if b.duration is not None:
                row["dur_w"] += b.duration * b.total_value_kzt
                row["dur_wt"] += b.total_value_kzt
        for kind, items in (("REVERSE_REPO", self.repos), ("DEPOSIT", self.deposits)):
            for m in items:
                if abs(m.market_value) < 1e-9:
                    continue
                row = bucket(kind)
                row["mv"] += m.market_value
                row["face"] += m.open_amount
                row["lots"] += 1
                if m.ytm is not None:
                    row["ytm_w"] += m.ytm * m.market_value
                    row["ytm_wt"] += m.market_value
                if m.duration is not None:
                    row["dur_w"] += m.duration * m.market_value
                    row["dur_wt"] += m.market_value
        result: Dict[str, dict] = {}
        for cat, row in out.items():
            result[cat] = {
                "mv": row["mv"],
                "face": row["face"],
                "ytm": row["ytm_w"] / row["ytm_wt"] if row["ytm_wt"] else None,
                "duration": row["dur_w"] / row["dur_wt"] if row["dur_wt"] else None,
                "lots": row["lots"],
            }
        return result


# ════════════════════════════ market data ════════════════════════════

class MarketData:
    """Prices and FX rates around ``as_of`` loaded once per calculation."""

    def __init__(self, db: Session, as_of: date, *, stale_days: Optional[int] = None):
        from services.formulas import params
        params.refresh(db, force=True)
        if stale_days is None:
            stale_days = int(params.get("max_stale_price_days"))
        self.stale_days = stale_days
        order = ("market", "risk_parameters")
        self.order = order if params.get("price_priority") == "market" else tuple(reversed(order))
        self.as_of = as_of
        lower = as_of - timedelta(days=stale_days)
        self.market: Dict[str, KasePrice] = {}
        self.risk: Dict[str, KaseRiskPrice] = {}
        for row in db.execute(select(KasePrice).where(
            KasePrice.trade_date >= lower, KasePrice.trade_date <= as_of,
        ).order_by(KasePrice.trade_date.asc())).scalars():
            for key in (row.instrument_code, row.isin):
                if key:
                    self.market[key.strip().upper()] = row
        for row in db.execute(select(KaseRiskPrice).where(
            KaseRiskPrice.trade_date >= lower, KaseRiskPrice.trade_date <= as_of,
        ).order_by(KaseRiskPrice.trade_date.asc())).scalars():
            for key in (row.instrument_code, row.isin):
                if key:
                    self.risk[key.strip().upper()] = row
        self.fx: Dict[str, float] = {"KZT": 1.0}
        for row in db.execute(select(FXRate).where(
            FXRate.rate_date <= as_of,
        ).order_by(FXRate.rate_date.asc())).scalars():
            if row.rate:
                self.fx[(row.currency or "KZT").upper()] = float(row.rate)

    def fx_rate(self, currency: Optional[str]) -> Tuple[float, bool]:
        code = (currency or "KZT").upper()
        if code == "KZT":
            return 1.0, True
        rate = self.fx.get(code)
        return (rate, True) if rate else (1.0, False)

    def quote(self, *identifiers: Optional[str]) -> Tuple[Optional[object], Optional[str]]:
        tables = {"market": self.market, "risk_parameters": self.risk}
        for source in self.order:
            table = tables[source]
            for ident in identifiers:
                if not ident:
                    continue
                row = table.get(ident.strip().upper())
                if row is None:
                    continue
                price = row.close_price if source == "market" else row.settlement_price
                if price is None:
                    continue
                if row.trade_date == self.as_of:
                    return row, source
        # stale fallback — the freshest price of either family within the window
        best = None
        best_source = None
        for source in self.order:
            table = tables[source]
            for ident in identifiers:
                if not ident:
                    continue
                row = table.get(ident.strip().upper())
                if row is None:
                    continue
                price = row.close_price if source == "market" else row.settlement_price
                if price is None:
                    continue
                if best is None or row.trade_date > best.trade_date:
                    best, best_source = row, source + "_stale"
        return best, best_source


def _price_pct(row: object, nominal: Optional[float], source: str) -> Optional[float]:
    """Clean price in % of face; converts quotes given in tenge per security."""
    price = getattr(row, "close_price", None) if source.startswith("market") else getattr(row, "settlement_price", None)
    if price is None:
        return None
    unit = (getattr(row, "unit_ru", None) or "").lower()
    if not unit or "%" in unit:
        return float(price)
    if "грязн" in unit:
        return None  # dirty price in tenge — cannot be applied to a clean % model safely
    if "тенге" in unit and nominal:
        return float(price) / float(nominal) * 100.0
    return None


# ════════════════════════════ base slice ════════════════════════════

def _non_snapshot_doc_ids(db: Session) -> List[int]:
    """Ids of documents whose lots are *not* snapshots (Trade Reports etc.).

    A lot is a Risk Report snapshot
    when it is not linked to a ledger trade and does not come from a Trade
    Report document (legacy rows without ``source_doc_id`` are snapshots too).
    """
    return list(db.execute(select(SourceDocument.id).where(
        SourceDocument.doc_type != RR_DOC_TYPE,
    )).scalars())


def _snapshot_filter(model, non_rr_ids: List[int]):  # noqa: D401
    cond = model.open_trade_id.is_(None)
    if hasattr(model, "close_trade_id"):
        cond = cond & model.close_trade_id.is_(None)
    if non_rr_ids:
        cond = cond & or_(model.source_doc_id.is_(None), model.source_doc_id.not_in(non_rr_ids))
    return cond


def base_date_for(db: Session, cdu_id: int, as_of: date, excluded_docs: Optional[List[int]] = None) -> Optional[date]:
    """Latest Risk Report snapshot date ≤ ``as_of`` for the CDU."""
    excluded_docs = excluded_docs if excluded_docs is not None else _non_snapshot_doc_ids(db)
    candidates: List[date] = []
    for model in (BondLot, RepoLot, DepositLot):
        value = db.execute(select(func.max(model.valuation_date)).where(
            model.cdu_id == cdu_id,
            model.valuation_date <= as_of,
            _snapshot_filter(model, excluded_docs),
        )).scalar()
        if value:
            candidates.append(value)
    if candidates:
        return max(candidates)
    # cash-only CDU: the Report sheet still fixes the slice date
    value = db.execute(select(func.max(PortfolioPosition.position_date)).where(
        PortfolioPosition.cdu_id == cdu_id,
        PortfolioPosition.position_date <= as_of,
        PortfolioPosition.notes == "rr_report_import",
    )).scalar()
    return value


def _is_retired(status: Optional[str]) -> bool:
    text = (status or "").strip().lower()
    return any(s in text for s in _RETIRED_STATUSES)


# ════════════════════════════ engine ════════════════════════════

def build_portfolio(
    db: Session,
    cdu_id: int,
    as_of: date,
    *,
    refs: Optional[ReferenceBook] = None,
    market: Optional[MarketData] = None,
    excluded_docs: Optional[List[int]] = None,
) -> PortfolioState:
    refs = refs or ReferenceBook(db)
    market = market or MarketData(db, as_of)
    excluded_docs = excluded_docs if excluded_docs is not None else _non_snapshot_doc_ids(db)
    base = base_date_for(db, cdu_id, as_of, excluded_docs)
    state = PortfolioState(cdu_id=cdu_id, as_of=as_of, base_date=base)

    seq = 0
    lots_by_isin: Dict[str, List[BondPosition]] = defaultdict(list)

    # ── 1. base bond lots ──
    if base is not None:
        rows = db.execute(select(BondLot).where(
            BondLot.cdu_id == cdu_id,
            BondLot.valuation_date == base,
            _snapshot_filter(BondLot, excluded_docs),
        ).order_by(BondLot.trade_date.asc(), BondLot.id.asc())).scalars().all()
        for lot in rows:
            face = float(lot.face_value_current or 0.0)
            if face <= 0 or _is_retired(lot.maturity_status):
                continue
            isin = (lot.isin or lot.instrument_code or "").strip().upper()
            ref = refs.get(isin) or refs.get(lot.instrument_code)
            seq += 1
            pos = BondPosition(
                cdu_id=cdu_id, isin=isin,
                ticker=(lot.instrument_code or (ref.ticker_kase if ref else None)),
                category=lot.category or refs.category(isin),
                currency=((ref.currency if ref else None) or ("USD" if lot.category == "FOREIGN_BONDS" else "KZT")).upper(),
                face_value=face,
                trade_date=lot.trade_date, settlement_date=lot.settlement_date or lot.trade_date,
                purchase_price=lot.purchase_price,
                origin="risk_report", seq=seq,
                source_doc_id=lot.source_doc_id,
                snapshot_date=base,
                snapshot_price=lot.market_price,
                snapshot_accrued=lot.accrued_interest,
                snapshot_total=lot.total_value if lot.total_value is not None else lot.market_value,
                snapshot_ytm=bm.rate_fraction(lot.ytm),
                snapshot_duration=lot.duration,
                unit_nominal=(float(lot.nominal_per_unit) if lot.nominal_per_unit
                              else (float(ref.nominal) if ref is not None and ref.nominal else None)),
            )
            lots_by_isin[isin].append(pos)

    # ── 2. bond movements from the Trade ledger ──
    trade_q = select(Trade).where(
        Trade.cdu_id == cdu_id,
        Trade.is_active.is_(True),
        Trade.workflow_status.in_(EFFECTIVE_STATUSES),
        Trade.value_date <= as_of,
        Trade.operation_type.in_(("BUY", "SELL", "REDEMPTION")),
    )
    if base is not None:
        # Operations settled on/before the snapshot are already inside it;
        # approved manual corrections dated on the snapshot day are applied on top.
        trade_q = trade_q.where(or_(
            Trade.value_date > base,
            (Trade.value_date == base) & Trade.is_manual.is_(True),
        ))
    trades = db.execute(trade_q.order_by(
        Trade.value_date.asc(), Trade.trade_date.asc(), Trade.id.asc(),
    )).scalars().all()
    for t in trades:
        if (t.instrument_category or "") in ("REVERSE_REPO", "DEPOSIT", "CASH"):
            continue
        ident = (t.isin or t.instrument_code or "").strip()
        if not ident:
            state.warnings.append(f"Сделка #{t.id} ({t.operation_type}) без ISIN/тикера — не учтена в позиции")
            continue
        isin = refs.isin_for(ident) or ident.upper()
        ref = refs.get(isin) or refs.get(t.instrument_code)
        face = _trade_face(t, ref)
        if t.operation_type == "BUY":
            if not face:
                state.warnings.append(
                    f"Покупка #{t.id} {ident}: не удалось определить номинал (нет «Объем по номиналу» и номинала в справочнике)"
                )
                continue
            seq += 1
            category = t.instrument_category if t.instrument_category in BOND_CATEGORIES else refs.category(isin, t.instrument_category, ticker=t.instrument_code)
            lots_by_isin[isin].append(BondPosition(
                cdu_id=cdu_id, isin=isin,
                ticker=t.instrument_code or (ref.ticker_kase if ref else None),
                category=category,
                currency=(t.currency or (ref.currency if ref else None) or "KZT").upper(),
                face_value=face,
                trade_date=t.trade_date, settlement_date=t.value_date,
                purchase_price=t.clean_price or t.price_final or t.market_price,
                origin="manual" if t.is_manual else "trade",
                trade_id=t.id, seq=seq, source_doc_id=t.source_doc_id,
                trade_ytm=bm.rate_fraction(t.ytm),
                unit_nominal=(face / abs(float(t.quantity)) if t.quantity
                              else (float(ref.nominal) if ref is not None and ref.nominal else None)),
            ))
        elif t.operation_type == "SELL":
            if not face:
                state.warnings.append(f"Продажа #{t.id} {ident}: не определён номинал — списание не выполнено")
                continue
            left = _fifo_write_off(lots_by_isin.get(isin, []), face)
            if left > 0.005:
                state.warnings.append(
                    f"Продажа #{t.id} {ident}: недостаточно остатка для списания FIFO, не хватает {left:,.2f} номинала"
                )
        elif t.operation_type == "REDEMPTION":
            lots = lots_by_isin.get(isin, [])
            if face:
                _fifo_write_off(lots, face)
            else:
                for lot in lots:
                    lot.face_value = 0.0

    # ── 3. valuation ──
    coupon_trades = _coupon_trade_index(db, cdu_id, base, as_of)
    for isin, lots in lots_by_isin.items():
        for lot in lots:
            if lot.face_value <= 0.005:
                continue
            ref = refs.get(isin) or refs.get(lot.ticker)
            schedule = refs.schedule(isin) or refs.schedule(lot.ticker)
            value_bond(lot, ref, market, as_of, schedule)
            _check_coupons(lot, ref, base, as_of, coupon_trades, schedule)
            state.bonds.append(lot)

    # ── 4. money market ──
    state.repos = _repos(db, cdu_id, base, as_of, excluded_docs, state)
    state.deposits = _deposits(db, cdu_id, base, as_of, excluded_docs, state)
    for b in state.bonds:
        state.warnings.extend(b.warnings)
    return state


def _trade_face(t: Trade, ref) -> Optional[float]:
    if t.face_value:
        return abs(float(t.face_value))
    nominal = t.nominal_per_unit or (ref.nominal if ref is not None else None)
    if t.quantity and nominal:
        return abs(float(t.quantity) * float(nominal))
    return None


def _fifo_write_off(lots: List[BondPosition], amount: float) -> float:
    """Reduce ``amount`` of face value from the earliest lots; return the shortfall."""
    remaining = float(amount)
    for lot in sorted(lots, key=lambda l: (l.settlement_date or l.trade_date or date.min, l.seq)):
        if remaining <= 0.005:
            break
        if lot.face_value <= 0.005:
            continue
        deduct = min(lot.face_value, remaining)
        lot.face_value -= deduct
        remaining -= deduct
    return max(remaining, 0.0)


def value_bond(lot: BondPosition, ref, market: MarketData, as_of: date,
               schedule: Optional[list] = None) -> None:
    """Fill valuation fields of a lot on ``as_of``.

    ``schedule`` — coupon payment schedule of the issue (Справочник ЦБ); when
    given it defines coupon periods and rates instead of the regular schedule.
    """
    maturity = ref.maturity_date if ref is not None else None
    lot.maturity_date = maturity
    coupon = bm.rate_fraction(ref.coupon_rate_pct) if ref is not None else None
    freq = ref.frequency if ref is not None else None
    basis = bm.normalize_basis(ref.base if ref is not None else None)
    start = ref.start_date if ref is not None else None
    nominal = ref.nominal if ref is not None else None
    fx, fx_ok = market.fx_rate(lot.currency)
    lot.fx_rate = fx
    if not fx_ok:
        lot.warnings.append(f"{lot.isin}: нет курса {lot.currency} на {as_of:%d.%m.%Y} — оценка по курсу 1")

    # Snapshot day: keep the exact Risk Report figures.
    if lot.origin == "risk_report" and lot.snapshot_date == as_of and lot.snapshot_total is not None:
        lot.price = lot.snapshot_price
        lot.price_source = "risk_report"
        lot.price_date = as_of
        lot.accrued = float(lot.snapshot_accrued or 0.0)
        lot.total_value = float(lot.snapshot_total)
        lot.clean_value = lot.total_value - lot.accrued
        lot.total_value_kzt = lot.total_value * fx
        lot.ytm = lot.snapshot_ytm
        lot.duration = lot.snapshot_duration
        return

    # Matured but redemption not booked: keep at par, flag for the operator.
    if maturity is not None and maturity <= as_of:
        lot.price = 100.0
        lot.price_source = "par_matured"
        lot.price_date = maturity
        lot.accrued = 0.0
        lot.clean_value = lot.face_value
        lot.total_value = lot.face_value
        lot.total_value_kzt = lot.total_value * fx
        lot.ytm = None
        lot.duration = 0.0
        lot.warnings.append(
            f"{lot.isin}: дата погашения {maturity:%d.%m.%Y} наступила, но операция «Погашение» не отражена — "
            "бумага оценена по номиналу, запустите дневную автоматизацию"
        )
        return

    quote, source = market.quote(lot.ticker, lot.isin)
    price = _price_pct(quote, nominal, source) if quote is not None else None
    ytm = None
    if price is not None:
        lot.price_source = source
        lot.price_date = getattr(quote, "trade_date", None)
        ytm = bm.rate_fraction(getattr(quote, "ytm", None))
        if source.endswith("_stale"):
            lot.warnings.append(
                f"{lot.isin}: нет цены KASE на {as_of:%d.%m.%Y}, использована цена за {lot.price_date:%d.%m.%Y}"
            )
    elif lot.snapshot_price is not None:
        price = lot.snapshot_price
        lot.price_source = "risk_report_carry"
        lot.price_date = lot.snapshot_date
        lot.warnings.append(f"{lot.isin}: нет цены KASE ≤ {market.stale_days} дн., оставлена цена Risk Report")
    elif lot.purchase_price is not None:
        price = lot.purchase_price
        lot.price_source = "purchase"
        lot.price_date = lot.trade_date
        accreted = _discount_accretion(lot, coupon, maturity, as_of)
        if accreted is not None:
            price, maturity = accreted
            lot.maturity_date = maturity
            lot.price_source = "amortized"
            lot.warnings.append(
                f"{lot.isin}: нет рыночной цены — дисконт амортизирован по доходности покупки "
                f"{(lot.trade_ytm or 0) * 100:.2f}% (погашение {maturity:%d.%m.%Y})"
            )
        else:
            lot.warnings.append(f"{lot.isin}: нет рыночной цены, оценка по цене приобретения")
    else:
        price = 100.0
        lot.price_source = "par"
        lot.warnings.append(f"{lot.isin}: нет ни одной цены — оценка по номиналу")
    lot.price = price

    schedule = schedule if schedule is not None else []
    if lot.price_source == "amortized":
        accrued = 0.0          # discount instrument: the yield is inside the price
    elif schedule:
        from services.portfolio import coupon_schedule as cs
        accrued = cs.accrued(lot.face_value, schedule, as_of, basis, start=start, nominal=nominal)
        rate_now = cs.current_rate(schedule, as_of)
        if rate_now is not None:
            coupon = rate_now   # floating / indexed coupon: duration on the current rate
    else:
        accrued = bm.accrued_interest(lot.face_value, coupon, as_of, maturity, freq, basis, start=start)
    if accrued is None:
        accrued = _carry_accrued(lot, coupon, as_of)
    lot.accrued = accrued
    lot.clean_value = lot.face_value * price / 100.0
    lot.total_value = lot.clean_value + accrued
    lot.total_value_kzt = lot.total_value * fx

    lot.ytm = ytm if ytm is not None else (lot.snapshot_ytm if lot.snapshot_ytm is not None else lot.trade_ytm)
    duration = None
    if schedule and lot.ytm is not None and lot.price_source != "amortized":
        from services.portfolio import coupon_schedule as cs
        duration = cs.schedule_mduration(as_of, schedule, maturity, lot.ytm, basis,
                                         int(freq) if freq else None)
    if duration is None and maturity is not None and lot.ytm is not None:
        if freq and coupon:
            duration = bm.excel_mduration(as_of, maturity, coupon, lot.ytm, int(freq), basis)
        else:
            duration = bm.zero_coupon_mduration(as_of, maturity, lot.ytm)
    if duration is None and lot.snapshot_duration is not None and lot.snapshot_date:
        duration = max(lot.snapshot_duration - (as_of - lot.snapshot_date).days / 365.0, 0.0)
    lot.duration = duration


def _discount_accretion(lot: BondPosition, coupon: Optional[float], maturity: Optional[date],
                        as_of: date) -> Optional[Tuple[float, date]]:
    """Price of a discount instrument (NBRK notes NTK…, zero-coupon) held without
    a market quote: the purchase yield is kept constant (money-market convention
    P = 100 / (1 + y·t/365)).  When the maturity is unknown it is implied by the
    purchase price and yield of the deal.  Returns (price %, maturity) or None.
    """
    y = lot.trade_ytm
    p0 = lot.purchase_price
    settle = lot.settlement_date or lot.trade_date
    if coupon or not y or y <= 0 or not p0 or p0 <= 0 or p0 >= 100 or settle is None:
        return None
    if maturity is None:
        days0 = (100.0 / p0 - 1.0) * 365.0 / y
        if days0 <= 0 or days0 > 3660:
            return None
        maturity = settle + timedelta(days=int(round(days0)))
    days = (maturity - as_of).days
    if days <= 0:
        return None
    return 100.0 / (1.0 + y * days / 365.0), maturity


def _carry_accrued(lot: BondPosition, coupon: Optional[float], as_of: date) -> float:
    """Fallback when the coupon schedule is unknown: roll the snapshot НКД."""
    if lot.snapshot_accrued is None or lot.snapshot_date is None:
        if coupon is None:
            lot.warnings.append(f"{lot.isin}: нет параметров купона в справочнике — НКД не рассчитан")
        return 0.0
    days = (as_of - lot.snapshot_date).days
    extra = lot.face_value * (coupon or 0.0) * days / 365.0
    lot.warnings.append(f"{lot.isin}: график купонов неизвестен, НКД экстраполирован от Risk Report")
    return float(lot.snapshot_accrued) + extra


def _coupon_trade_index(db: Session, cdu_id: int, base: Optional[date], as_of: date) -> set:
    q = select(Trade.isin, Trade.instrument_code, Trade.trade_date).where(
        Trade.cdu_id == cdu_id,
        Trade.operation_type == "COUPON",
        Trade.is_active.is_(True),
        Trade.trade_date <= as_of,
    )
    if base is not None:
        q = q.where(Trade.trade_date > base)
    out = set()
    for isin, code, d in db.execute(q).all():
        for key in (isin, code):
            if key:
                out.add((key.strip().upper(), d))
    return out


def _check_coupons(lot: BondPosition, ref, base: Optional[date], as_of: date, index: set,
                   schedule: Optional[list] = None) -> None:
    if schedule:
        dates = [r.payment_date for r in schedule]
    elif ref is None or not ref.maturity_date or not ref.frequency or not ref.coupon_rate_pct:
        return
    else:
        dates = bm.coupon_schedule(ref.start_date, ref.maturity_date, int(ref.frequency))
    lower = max(d for d in (base, lot.settlement_date) if d is not None) if (base or lot.settlement_date) else None
    if lower is None:
        return
    for d in dates:
        if lower < d <= as_of:
            keys = {(lot.isin, d)}
            if lot.ticker:
                keys.add((lot.ticker.strip().upper(), d))
            if not keys & index:
                lot.warnings.append(
                    f"{lot.isin}: купон за {d:%d.%m.%Y} не отражён в Trades — запустите дневную автоматизацию"
                )


# ════════════════════════════ REPO / deposits ════════════════════════════

def _effective_trade_ids(db: Session, ids: Iterable[int]) -> set:
    ids = [i for i in ids if i]
    if not ids:
        return set()
    return set(db.execute(select(Trade.id).where(
        Trade.id.in_(ids),
        Trade.is_active.is_(True),
        Trade.workflow_status.in_(EFFECTIVE_STATUSES),
    )).scalars())


def _repos(db: Session, cdu_id: int, base: Optional[date], as_of: date,
           excluded_docs: List[int], state: PortfolioState) -> List[MoneyMarketPosition]:
    out: List[MoneyMarketPosition] = []
    # a) snapshot lots open at the base date
    if base is not None:
        for lot in db.execute(select(RepoLot).where(
            RepoLot.cdu_id == cdu_id, RepoLot.valuation_date == base,
            _snapshot_filter(RepoLot, excluded_docs),
        )).scalars():
            open_date = lot.trade_date or base
            close_date = lot.close_date
            if close_date is None and lot.term_days:
                close_date = open_date + timedelta(days=int(lot.term_days))
            if close_date is not None and close_date <= as_of:
                if close_date > base:
                    amount = lot.close_value
                    if amount is None:
                        amount = _repo_position(lot, open_date, close_date, close_date, origin="risk_report").market_value
                    state.implied_cash.append({
                        "date": close_date, "amount": float(amount or 0.0), "kind": "REPO_CLOSE",
                        "reference": lot.deal_id or lot.instrument_code or str(lot.id),
                    })
                continue
            pos = _repo_position(lot, open_date, close_date, as_of, origin="risk_report")
            if as_of == base and lot.market_value is not None:
                pos.market_value = float(lot.market_value)
                pos.accrued = float(lot.accrued_interest or (pos.market_value - pos.open_amount))
                if lot.ytm is not None:
                    pos.ytm = bm.rate_fraction(lot.ytm)
                if lot.duration is not None:
                    pos.duration = lot.duration
            if close_date is None:
                pos.warnings.append(
                    f"РЕПО {lot.instrument_code or lot.deal_id or lot.id}: дата закрытия неизвестна "
                    "(Risk Report импортирован до исправления парсера) — переимпортируйте Risk Report"
                )
                if as_of > base:
                    state.warnings.extend(pos.warnings)
            out.append(pos)
    # b) lots opened by Trade Reports / manual operations after the base date
    q = select(RepoLot).where(
        RepoLot.cdu_id == cdu_id,
        RepoLot.open_trade_id.is_not(None),
        RepoLot.valuation_date <= as_of,
    )
    if base is not None:
        q = q.where(RepoLot.valuation_date > base)
    lots = db.execute(q).scalars().all()
    effective = _effective_trade_ids(db, [l.open_trade_id for l in lots] + [l.close_trade_id for l in lots])
    open_trades = {t.id: t for t in db.execute(select(Trade).where(
        Trade.id.in_([l.open_trade_id for l in lots] or [-1]),
    )).scalars()}
    for lot in lots:
        if lot.open_trade_id not in effective:
            continue
        close_date = lot.close_date
        if lot.close_trade_id and lot.close_trade_id not in effective:
            close_date = None
        if close_date is None and lot.term_days:
            close_date = (lot.valuation_date or lot.trade_date) + timedelta(days=int(lot.term_days))
        if close_date is not None and close_date <= as_of:
            continue
        pos = _repo_position(lot, lot.valuation_date or lot.trade_date, close_date, as_of, origin="trade")
        ot = open_trades.get(lot.open_trade_id)
        if ot is not None:
            pos.quantity = abs(float(ot.quantity)) if ot.quantity else None
            pos.collateral = ot.isin or ot.instrument_code
            pos.deal_id = pos.deal_id or ot.deal_id
        out.append(pos)
    # c) manual REPO_OPEN trades without a lot
    linked = set(db.execute(select(RepoLot.open_trade_id).where(
        RepoLot.cdu_id == cdu_id, RepoLot.open_trade_id.is_not(None),
    )).scalars())
    q = select(Trade).where(
        Trade.cdu_id == cdu_id, Trade.operation_type == "REPO_OPEN",
        Trade.is_manual.is_(True), Trade.is_active.is_(True),
        Trade.workflow_status.in_(EFFECTIVE_STATUSES), Trade.value_date <= as_of,
    )
    if base is not None:
        q = q.where(Trade.value_date > base)
    for t in db.execute(q).scalars():
        if t.id in linked:
            continue
        open_amount = abs(t.amount_kzt or 0.0)
        close_date = t.value_date + timedelta(days=int(t.repo_term_days)) if t.repo_term_days else None
        closing = db.execute(select(Trade).where(
            Trade.cdu_id == cdu_id, Trade.operation_type == "REPO_CLOSE",
            Trade.is_active.is_(True), Trade.workflow_status.in_(EFFECTIVE_STATUSES),
            or_(Trade.deal_id == t.deal_id, Trade.instrument_code == t.instrument_code),
            Trade.value_date >= t.value_date,
        ).order_by(Trade.value_date.asc())).scalars().first() if (t.deal_id or t.instrument_code) else None
        if closing is not None:
            close_date = closing.value_date
        if close_date is not None and close_date <= as_of:
            continue
        metrics = bm.repo_metrics(
            open_amount, t.repo_buyback_sum, t.value_date, close_date, as_of,
            rate=bm.rate_fraction(t.repo_rate_pct), base=_repo_base(None),
        )
        out.append(MoneyMarketPosition(
            kind="REPO", cdu_id=cdu_id, identifier=t.instrument_code or t.isin,
            deal_id=t.deal_id, open_date=t.value_date, close_date=close_date,
            open_amount=open_amount, close_amount=t.repo_buyback_sum,
            rate=bm.rate_fraction(t.repo_rate_pct), base=_repo_base(None), origin="manual",
            trade_id=t.id, source_doc_id=t.source_doc_id,
            quantity=abs(float(t.quantity)) if t.quantity else None,
            collateral=t.isin or t.instrument_code,
            accrued=metrics["accrued"], market_value=metrics["market_value"],
            ytm=metrics["ytm"], duration=metrics["duration"],
        ))
    return out


def _repo_base(value: Optional[int]) -> int:
    from services.formulas import params
    return int(value or params.get("repo_default_base"))


def _deposit_base(value: Optional[int]) -> int:
    from services.formulas import params
    return int(value or params.get("deposit_default_base"))


def _repo_position(lot: RepoLot, open_date: date, close_date: Optional[date], as_of: date,
                   *, origin: str) -> MoneyMarketPosition:
    rate = bm.rate_fraction(lot.repo_rate_pct)
    metrics = bm.repo_metrics(
        float(lot.face_value or 0.0), lot.close_value, open_date, close_date, as_of,
        rate=rate, base=_repo_base(lot.base),
    )
    return MoneyMarketPosition(
        kind="REPO", cdu_id=lot.cdu_id, identifier=lot.instrument_code or lot.isin,
        deal_id=lot.deal_id, open_date=open_date, close_date=close_date,
        open_amount=float(lot.face_value or 0.0), close_amount=lot.close_value,
        rate=rate, base=_repo_base(lot.base), origin=origin,
        source_doc_id=lot.source_doc_id, trade_id=lot.open_trade_id,
        accrued=metrics["accrued"], market_value=metrics["market_value"],
        ytm=metrics["ytm"] if metrics["ytm"] is not None else bm.rate_fraction(lot.ytm),
        duration=metrics["duration"],
        collateral=(lot.isin or (lot.instrument_code if lot.instrument_code != lot.deal_id else None)),
    )


def _deposits(db: Session, cdu_id: int, base: Optional[date], as_of: date,
              excluded_docs: List[int], state: PortfolioState) -> List[MoneyMarketPosition]:
    out: List[MoneyMarketPosition] = []
    rows: List[Tuple[DepositLot, str]] = []
    if base is not None:
        rows.extend((lot, "risk_report") for lot in db.execute(select(DepositLot).where(
            DepositLot.cdu_id == cdu_id, DepositLot.valuation_date == base,
            _snapshot_filter(DepositLot, excluded_docs),
        )).scalars())
    q = select(DepositLot).where(
        DepositLot.cdu_id == cdu_id,
        DepositLot.open_trade_id.is_not(None),
        DepositLot.valuation_date <= as_of,
    )
    if base is not None:
        q = q.where(DepositLot.valuation_date > base)
    trade_lots = db.execute(q).scalars().all()
    effective = _effective_trade_ids(db, [l.open_trade_id for l in trade_lots])
    rows.extend((lot, "trade") for lot in trade_lots if lot.open_trade_id in effective)
    for lot, origin in rows:
        open_date = lot.trade_date or lot.valuation_date
        close_date = lot.close_date
        rate = bm.rate_fraction(lot.interest_rate_pct)
        if close_date is not None and close_date <= as_of:
            if origin == "risk_report" and base is not None and close_date > base:
                closing = bm.deposit_metrics(float(lot.principal or 0.0), rate, open_date, close_date, close_date,
                                             base=_deposit_base(lot.base))
                state.implied_cash.append({
                    "date": close_date, "amount": closing["market_value"], "kind": "DEPOSIT_CLOSE",
                    "reference": lot.deal_id or str(lot.id),
                })
            continue
        metrics = bm.deposit_metrics(float(lot.principal or 0.0), rate, open_date, close_date, as_of,
                                     base=_deposit_base(lot.base))
        pos = MoneyMarketPosition(
            kind="DEPOSIT", cdu_id=cdu_id, identifier=lot.deal_id, deal_id=lot.deal_id,
            open_date=open_date, close_date=close_date,
            open_amount=float(lot.principal or 0.0), close_amount=None, rate=rate,
            base=_deposit_base(lot.base), origin=origin,
            source_doc_id=lot.source_doc_id, trade_id=lot.open_trade_id,
            accrued=metrics["accrued"], market_value=metrics["market_value"],
            ytm=metrics["ytm"], duration=metrics["duration"],
        )
        if origin == "risk_report" and as_of == base:
            if lot.market_value is not None:
                pos.market_value = float(lot.market_value)
            elif lot.accrued_interest is not None:
                pos.accrued = float(lot.accrued_interest)
                pos.market_value = pos.open_amount + pos.accrued
        out.append(pos)
    return out
