"""Securities holdings aggregator.

Maintains the ``security_holdings`` table — a materialised view of the
current state of every security the system has ever traded, aggregated
from active ``Trade`` rows. Called after every TradeReport import for
the touched CDU, and exposed manually via ``POST /api/securities/sync``
for full rebuilds.

The catalogue is a **full library** of securities, not just currently
open positions: a row exists for every distinct ``(cdu_id, security_key)``
seen in any active trade. ``quantity`` shows the current net position
(zero for fully closed instruments).

Security key
------------
Some operation types (notably REPO_OPEN / REPO_CLOSE for reverse-repo
collateral) carry the instrument's exchange ticker in ``instrument_code``
but leave ``isin`` empty. So we use a composite key::

    security_key = trade.isin OR trade.instrument_code

The holding row's ``isin`` column stores this key (real ISIN when known,
falls back to the ticker). ``instrument_code`` is kept separately when
both are present.

Sync rules
----------
* AUTO rows are owned by this service:
    - any (cdu, key) ever traded → upsert (quantity may be 0)
    - row is dropped only when NO active trades reference the security
      for that CDU anymore (e.g. after a hard delete of trades)
* MANUAL rows are owned by the user:
    - never auto-deleted
    - their pricing fields (``last_kase_price``, ``last_kase_date``,
      ``market_value``) are still refreshed so the UI always shows
      live market data

Quantity formula
----------------
For each (cdu_id, security_key) over ``Trade.is_active=True``::

    qty_in  = Σ quantity for op_type ∈ {BUY, REPO_OPEN}
    qty_out = Σ quantity for op_type ∈ {SELL, REPO_CLOSE, REDEMPTION}
    qty     = qty_in - qty_out

    avg_purchase_price = Σ(BUY.quantity * BUY.price_final) / Σ BUY.quantity
                         (price_final → clean_price → market_price)

REPO_OPEN/CLOSE pairs are kept symmetric so a closed reverse-repo nets
to zero — but the row stays in the catalogue as historical evidence.

Market data
-----------
``last_kase_price`` is taken from the most recent ``KasePrice.close_price``
matching the holding's ``isin`` or ``instrument_code``. ``market_value``
is computed as ``quantity * last_kase_price`` when both are present.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional, Tuple

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.db_models import (
    BondLot,
    KasePrice,
    PortfolioPosition,
    RepoLot,
    SecurityHolding,
    SourceDocument,
    Trade,
)


# Trade operations that increase/decrease the net position. Anything outside
# these sets contributes only to metadata (name, category, etc.).
_QTY_IN = {"BUY", "REPO_OPEN"}
_QTY_OUT = {"SELL", "REPO_CLOSE", "REDEMPTION"}
_EPS = 1e-9


def _security_key(t: Trade) -> Optional[str]:
    """The catalogue identifier for a trade row: real ISIN if known, else ticker."""
    if t.isin:
        return t.isin.strip().upper() or None
    if t.instrument_code:
        return t.instrument_code.strip() or None
    return None


def _source_doc_types(db: Session) -> Dict[int, str]:
    rows = db.execute(select(SourceDocument.id, SourceDocument.doc_type)).all()
    return {int(row.id): str(row.doc_type or "") for row in rows if row.id is not None}


def _is_trade_report_source(source_doc_types: Dict[int, str], source_doc_id: Optional[int]) -> bool:
    return source_doc_id is not None and source_doc_types.get(source_doc_id) == "TRADE_REPORT"


def _latest_baseline_dates(
    db: Session,
    cdu_id: Optional[int],
    source_doc_types: Dict[int, str],
) -> Dict[int, object]:
    dates: Dict[int, object] = {}

    def remember(cid: int, d: object) -> None:
        if d is None:
            return
        if cdu_id is not None and cid != cdu_id:
            return
        current = dates.get(cid)
        if current is None or d > current:
            dates[cid] = d

    bond_stmt = select(BondLot)
    repo_stmt = select(RepoLot)
    pos_stmt = select(PortfolioPosition).where(PortfolioPosition.instrument_code.is_not(None))
    if cdu_id is not None:
        bond_stmt = bond_stmt.where(BondLot.cdu_id == cdu_id)
        repo_stmt = repo_stmt.where(RepoLot.cdu_id == cdu_id)
        pos_stmt = pos_stmt.where(PortfolioPosition.cdu_id == cdu_id)

    for lot in db.execute(bond_stmt).scalars():
        if not _is_trade_report_source(source_doc_types, lot.source_doc_id):
            remember(lot.cdu_id, lot.valuation_date)
    for lot in db.execute(repo_stmt).scalars():
        if not _is_trade_report_source(source_doc_types, lot.source_doc_id):
            remember(lot.cdu_id, lot.valuation_date)
    for pos in db.execute(pos_stmt).scalars():
        remember(pos.cdu_id, pos.position_date)

    return dates


def _blank_position(cdu_id: int, key_id: str) -> dict:
    return {
        "qty": 0.0,
        "buy_qty": 0.0,
        "buy_value": 0.0,
        "instrument_code": key_id,
        "instrument_name": None,
        "category": None,
        "currency": "KZT",
        "nominal_per_unit": None,
        "has_real_isin": False,
        "last_trade_price": None,
        "last_trade_date": None,
        "market_value": None,
        "price_is_pct": False,
    }


def _position_bucket(positions: Dict[Tuple[int, str], dict], cdu_id: int, key_id: str) -> dict:
    return positions.setdefault((cdu_id, key_id), _blank_position(cdu_id, key_id))


def _load_baseline_positions(
    db: Session,
    cdu_id: Optional[int],
    baseline_dates: Dict[int, object],
    source_doc_types: Dict[int, str],
) -> Dict[Tuple[int, str], dict]:
    positions: Dict[Tuple[int, str], dict] = {}
    if not baseline_dates:
        return positions

    bond_stmt = select(BondLot)
    repo_stmt = select(RepoLot)
    pos_stmt = select(PortfolioPosition).where(PortfolioPosition.instrument_code.is_not(None))
    if cdu_id is not None:
        bond_stmt = bond_stmt.where(BondLot.cdu_id == cdu_id)
        repo_stmt = repo_stmt.where(RepoLot.cdu_id == cdu_id)
        pos_stmt = pos_stmt.where(PortfolioPosition.cdu_id == cdu_id)

    for lot in db.execute(bond_stmt).scalars():
        if _is_trade_report_source(source_doc_types, lot.source_doc_id):
            continue
        if baseline_dates.get(lot.cdu_id) != lot.valuation_date:
            continue
        key_id = (lot.isin or lot.instrument_code or "").strip()
        if not key_id:
            continue
        key = key_id.upper() if lot.isin else key_id
        pos = _position_bucket(positions, lot.cdu_id, key)
        qty = float(lot.quantity_current or 0.0)
        if abs(qty) < _EPS:
            qty = float(lot.face_value_current or 0.0)
        pos["qty"] += qty
        pos["buy_qty"] += abs(qty)
        price = lot.market_price or lot.purchase_price
        if price is not None:
            pos["buy_value"] += abs(qty) * float(price)
            pos["last_trade_price"] = float(price)
            pos["last_trade_date"] = lot.valuation_date
            pos["price_is_pct"] = True
        mv = lot.market_value if lot.market_value is not None else lot.total_value
        if mv is not None:
            pos["market_value"] = float(pos.get("market_value") or 0.0) + float(mv)
        pos["instrument_code"] = lot.instrument_code or lot.isin
        pos["category"] = lot.category or pos.get("category")
        pos["nominal_per_unit"] = lot.nominal_per_unit or pos.get("nominal_per_unit")
        pos["has_real_isin"] = bool(lot.isin)

    for lot in db.execute(repo_stmt).scalars():
        if _is_trade_report_source(source_doc_types, lot.source_doc_id):
            continue
        if baseline_dates.get(lot.cdu_id) != lot.valuation_date:
            continue
        key_id = (lot.isin or lot.instrument_code or lot.deal_id or "").strip()
        if not key_id:
            continue
        key = key_id.upper() if lot.isin else key_id
        pos = _position_bucket(positions, lot.cdu_id, key)
        qty = float(lot.face_value or 0.0)
        pos["qty"] += qty
        pos["instrument_code"] = lot.instrument_code or lot.isin or lot.deal_id
        pos["category"] = "REVERSE_REPO"
        pos["last_trade_price"] = lot.repo_rate_pct
        pos["last_trade_date"] = lot.valuation_date
        mv = lot.market_value if lot.market_value is not None else (lot.close_value or lot.face_value)
        if mv is not None:
            pos["market_value"] = float(pos.get("market_value") or 0.0) + float(mv)
        pos["has_real_isin"] = bool(lot.isin)

    for p in db.execute(pos_stmt).scalars():
        if baseline_dates.get(p.cdu_id) != p.position_date:
            continue
        key_id = (p.instrument_code or "").strip()
        if not key_id:
            continue
        pos = _position_bucket(positions, p.cdu_id, key_id)
        qty = float(p.nominal_volume or 0.0)
        if abs(qty) < _EPS:
            continue
        pos["qty"] += qty
        pos["instrument_code"] = p.instrument_code
        pos["instrument_name"] = p.instrument_name or pos.get("instrument_name")
        pos["category"] = p.instrument_category or pos.get("category")
        pos["last_trade_price"] = p.current_price
        pos["last_trade_date"] = p.position_date
        pos["market_value"] = float(pos.get("market_value") or 0.0) + float(p.market_value_current or 0.0)

    return positions


def _aggregate_positions(
    db: Session, cdu_id: Optional[int],
) -> Dict[Tuple[int, str], dict]:
    """Build ``{(cdu_id, security_key): position_dict}`` from active trades.

    ``position_dict`` contains: ``qty``, ``buy_qty``, ``buy_value``,
    ``instrument_code``, ``instrument_name``, ``category``, ``currency``,
    ``nominal_per_unit``, ``has_real_isin`` (so the caller knows whether
    the stored key is a real ISIN or a ticker fallback).

    Every active Trade row contributes to the catalogue regardless of
    its operation type — operations outside ``_QTY_IN/_QTY_OUT`` only
    update metadata so we still register e.g. COUPON-only securities.
    """
    source_doc_types = _source_doc_types(db)
    baseline_dates = _latest_baseline_dates(db, cdu_id, source_doc_types)
    positions = _load_baseline_positions(db, cdu_id, baseline_dates, source_doc_types)

    stmt = select(Trade).where(Trade.is_active == True)  # noqa: E712
    if cdu_id is not None:
        stmt = stmt.where(Trade.cdu_id == cdu_id)
    stmt = stmt.order_by(Trade.value_date.asc(), Trade.trade_date.asc(), Trade.id.asc())

    for t in db.execute(stmt).scalars():
        trade_effective_date = t.value_date or t.trade_date
        baseline_date = baseline_dates.get(t.cdu_id)
        if baseline_date is not None and trade_effective_date <= baseline_date:
            continue

        key_id = _security_key(t)
        if not key_id:
            continue
        pos = _position_bucket(positions, t.cdu_id, key_id)
        if not pos.get("instrument_code") or pos.get("instrument_code") == key_id:
            pos["instrument_code"] = t.instrument_code or key_id
        pos["instrument_name"] = pos.get("instrument_name") or t.description
        pos["category"] = pos.get("category") or t.instrument_category
        pos["currency"] = t.currency or pos.get("currency") or "KZT"
        pos["nominal_per_unit"] = pos.get("nominal_per_unit") or t.nominal_per_unit
        if t.isin:
            pos["has_real_isin"] = True

        qty = float(t.quantity or 0)
        signed_qty = 0.0
        if qty and t.operation_type in _QTY_IN:
            signed_qty = qty
            pos["qty"] += signed_qty
            if t.operation_type == "BUY":
                pos["buy_qty"] += qty
                # Weighted-average purchase price uses the post-flagger
                # ``price_final`` when available, falling back to clean → market.
                unit_price = t.price_final or t.clean_price or t.market_price
                if unit_price is not None:
                    pos["buy_value"] += qty * float(unit_price)
        elif qty and t.operation_type in _QTY_OUT:
            signed_qty = -qty
            pos["qty"] += signed_qty

        amount = t.repo_buyback_sum or t.amount_kzt or t.amount_ccy or t.face_value
        if signed_qty and amount is not None:
            pos["market_value"] = float(pos.get("market_value") or 0.0) + (
                (1 if signed_qty > 0 else -1) * abs(float(amount or 0.0))
            )

        # Last-write-wins for descriptive fields — newer trades overwrite older.
        if t.instrument_code:
            pos["instrument_code"] = t.instrument_code
        if t.description and not pos.get("instrument_name"):
            # Keep the first descriptive name; ledgers often shorten it later.
            pos["instrument_name"] = t.description
        elif t.description and len(t.description) > len(pos.get("instrument_name") or ""):
            pos["instrument_name"] = t.description
        if t.instrument_category:
            pos["category"] = t.instrument_category
        if t.nominal_per_unit is not None:
            pos["nominal_per_unit"] = t.nominal_per_unit
        trade_price = t.price_final or t.price_kase or t.market_price or t.price_original or t.clean_price
        if trade_price is not None:
            pos["last_trade_price"] = float(trade_price)
            pos["last_trade_date"] = t.value_date or t.trade_date

    return positions


def _build_kase_index(db: Session) -> Dict[str, KasePrice]:
    """Latest KASE quote per identifier (instrument_code and ISIN).

    For each identifier we keep the row with the most recent ``trade_date``.
    """
    rows = db.execute(
        select(KasePrice).order_by(KasePrice.trade_date.asc())
    ).scalars()
    idx: Dict[str, KasePrice] = {}
    for kp in rows:
        # Sorted ascending → later assignments overwrite earlier ones, so the
        # last value seen for a given key is the freshest.
        if kp.instrument_code:
            idx[kp.instrument_code.upper()] = kp
        if kp.isin:
            idx[kp.isin.upper()] = kp
    return idx


def _resolve_market_data(
    kase_idx: Dict[str, KasePrice],
    instrument_code: Optional[str],
    isin: Optional[str],
) -> Tuple[Optional[float], Optional[object]]:
    if instrument_code:
        kp = kase_idx.get(instrument_code.upper())
        if kp and kp.close_price is not None:
            return kp.close_price, kp.trade_date
    if isin:
        kp = kase_idx.get(isin.upper())
        if kp and kp.close_price is not None:
            return kp.close_price, kp.trade_date
    return None, None


def _value_from_price(pos: dict, quantity: float, price: Optional[float]) -> Optional[float]:
    if price is None:
        return None
    if pos.get("category") == "REVERSE_REPO":
        return None
    divisor = 100.0 if pos.get("price_is_pct") else 1.0
    return quantity * price / divisor


def sync_holdings(
    db: Session,
    *,
    cdu_id: Optional[int] = None,
    actor: Optional[str] = None,
) -> dict:
    """Rebuild ``security_holdings`` for one CDU (or all when ``cdu_id`` is None).

    Returns counters: ``upserted``, ``deleted``, ``manual_refreshed``.
    The caller manages the transaction commit.
    """
    counters = {"upserted": 0, "deleted": 0, "manual_refreshed": 0}
    positions = _aggregate_positions(db, cdu_id)
    kase_idx = _build_kase_index(db)
    now = datetime.utcnow()

    # 1) Existing holdings in scope (so we know what to delete or refresh).
    stmt = select(SecurityHolding)
    if cdu_id is not None:
        stmt = stmt.where(SecurityHolding.cdu_id == cdu_id)
    existing: Dict[Tuple[int, str], SecurityHolding] = {
        (h.cdu_id, h.isin): h for h in db.execute(stmt).scalars()
    }

    # 2) Upsert AUTO rows from the aggregation. Every (cdu, key) seen in an
    # active trade gets a row — even when net qty is 0 (closed position) —
    # so the catalogue keeps historical securities visible.
    for (cdu, key_id), pos in positions.items():
        net_qty = pos["qty"]
        row = existing.get((cdu, key_id))

        avg_price = (
            pos["buy_value"] / pos["buy_qty"] if pos["buy_qty"] > 0 else None
        )
        kase_price, kase_date = _resolve_market_data(
            kase_idx, pos.get("instrument_code"), key_id if pos.get("has_real_isin") else None,
        )
        last_price, last_date = kase_price, kase_date
        if last_price is None and pos.get("last_trade_price") is not None:
            last_price = pos.get("last_trade_price")
            last_date = pos.get("last_trade_date")

        if abs(net_qty or 0.0) < _EPS:
            if row is not None and row.source == "AUTO":
                db.delete(row)
                counters["deleted"] += 1
            elif row is not None:
                row.last_kase_price = last_price
                row.last_kase_date = last_date
                row.market_value = _value_from_price(pos, row.quantity or 0.0, kase_price)
                row.last_synced_at = now
                counters["manual_refreshed"] += 1
            existing.pop((cdu, key_id), None)
            continue

        # KASE is authoritative for market value when a matching quote exists.
        # Historical/imported market_value is only a fallback for instruments
        # without KASE pricing (or non-price instruments such as reverse repo).
        market_value = _value_from_price(pos, net_qty, kase_price)
        if market_value is None:
            market_value = pos.get("market_value")
            if market_value is None or abs(float(market_value or 0.0)) < _EPS:
                market_value = _value_from_price(pos, net_qty, last_price)

        if row is None:
            row = SecurityHolding(
                cdu_id=cdu,
                isin=key_id,
                source="AUTO",
            )
            db.add(row)

        # MANUAL rows: never overwrite quantity/avg_price, just refresh market data.
        if row.source != "MANUAL":
            row.quantity = net_qty
            row.avg_purchase_price = avg_price
            row.instrument_code = pos.get("instrument_code") or row.instrument_code
            row.instrument_name = pos.get("instrument_name") or row.instrument_name
            row.category = pos.get("category") or row.category
            row.currency = pos.get("currency") or row.currency or "KZT"
            row.nominal_per_unit = pos.get("nominal_per_unit") or row.nominal_per_unit

        row.last_kase_price = last_price
        row.last_kase_date = last_date
        row.market_value = market_value if row.source != "MANUAL" else (
            _value_from_price(pos, row.quantity or 0.0, kase_price)
        )
        row.last_synced_at = now
        if actor and row.source != "MANUAL":
            row.updated_by = actor

        counters["upserted"] += 1
        existing.pop((cdu, key_id), None)

    # 3) Anything still in ``existing`` had no active trades. Delete AUTO,
    # refresh prices for MANUAL.
    for row in list(existing.values()):
        if row.source == "AUTO":
            db.delete(row)
            counters["deleted"] += 1
        else:
            last_price, last_date = _resolve_market_data(
                kase_idx, row.instrument_code, row.isin,
            )
            row.last_kase_price = last_price
            row.last_kase_date = last_date
            row.market_value = (
                (row.quantity or 0) * last_price if last_price is not None else None
            )
            row.last_synced_at = now
            counters["manual_refreshed"] += 1

    db.flush()
    logger.info(
        f"Holdings sync cdu={cdu_id or 'ALL'}: {counters}"
    )
    return counters
