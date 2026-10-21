"""Single entry point for ingesting a Trade Report file.

Used by both upload paths («TradeReport» page and «Первичка»), so a file
loaded through either screen ends up in exactly the same tables: TradeFile +
RawTrade (source view), SourceDocument (audit), Trade ledger + cash
movements + lots (calculations), KASE price check and holdings sync.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from models.db_models import CDU, CDUFileFormat, RawTrade, SourceDocument, TradeFile
from services.calculator.constants import normalize_cdu_name

from .trade_importer import import_trades_from_parsed
from .trade_report_parser import ParsedTradeFile, TradeReportParser

ACTIVE_FILE_STATUSES = ("UPLOADED", "PARSED", "IMPORTED", "CALCULATED", "ERROR")


@dataclass
class IngestResult:
    trade_file: TradeFile
    source_doc: SourceDocument
    cdu: Optional[CDU]
    trade_date: date
    parsed: ParsedTradeFile
    counters: Dict[str, int] = field(default_factory=dict)
    price_check: Optional[dict] = None
    anomalies: List[dict] = field(default_factory=list)
    superseded_file_ids: List[int] = field(default_factory=list)


def resolve_cdu(
    db: Session,
    *,
    cdu_id: Optional[int] = None,
    cdu_prefix: Optional[str] = None,
    cdu_name: Optional[str] = None,
) -> Optional[CDU]:
    if cdu_id:
        return db.get(CDU, cdu_id)
    from services.cdu_lookup import find_cdu
    return find_cdu(db, name=cdu_name, prefix=cdu_prefix)


def parse_with_cdu_overrides(
    file_path: Path,
    original_name: str,
    db: Session,
    known_cdu_id: Optional[int] = None,
) -> ParsedTradeFile:
    """Parse a trade report applying the per-CDU column mapping / header row."""
    first = TradeReportParser(file_path, original_name=original_name).parse()
    cdu_id = known_cdu_id
    if cdu_id is None:
        cdu = resolve_cdu(db, cdu_prefix=first.cdu_prefix, cdu_name=first.cdu_name)
        if cdu:
            cdu_id = cdu.id
            first.cdu_name = first.cdu_name or cdu.name
    if cdu_id is None:
        return first

    fmt = (
        db.query(CDUFileFormat)
        .filter(CDUFileFormat.cdu_id == cdu_id, CDUFileFormat.is_active.is_(True))
        .first()
    )
    if not fmt:
        return first
    try:
        alias_overrides: dict[str, tuple[str, ...]] = {}
        if fmt.field_aliases:
            raw_aliases: dict[str, Any] = json.loads(fmt.field_aliases)
            for key, aliases in raw_aliases.items():
                if isinstance(aliases, list):
                    alias_overrides[key] = tuple(str(a) for a in aliases if a)
                elif isinstance(aliases, str):
                    alias_overrides[key] = (aliases,)
        header_idx = fmt.header_row_index if fmt.header_row_index else None
        if not alias_overrides and header_idx is None:
            return first
        second = TradeReportParser(
            file_path,
            original_name=original_name,
            alias_overrides=alias_overrides or None,
            header_row_index=header_idx,
        ).parse()
        if first.cdu_prefix and not second.cdu_prefix:
            second.cdu_prefix = first.cdu_prefix
        if first.cdu_name and not second.cdu_name:
            second.cdu_name = first.cdu_name
        return second
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to apply CDU format overrides for CDU {cdu_id}: {exc!r}")
    return first


def supersede_previous_files(
    db: Session, *, cdu_id: int, trade_dates: set[date], keep_file_id: int,
) -> List[int]:
    """Mark older Trade Report files of the same CDU/date(s) as SUPERSEDED.

    The Trade ledger already keeps only the latest import of a CDU/date; this
    keeps the source view (RawTrade, operations journal) consistent with it,
    so a corrected file never doubles the operations.
    """
    if not trade_dates:
        return []
    rows = db.query(TradeFile).filter(
        TradeFile.cdu_id == cdu_id,
        TradeFile.trade_date.in_(trade_dates),
        TradeFile.id != keep_file_id,
        TradeFile.status.in_(ACTIVE_FILE_STATUSES),
    ).all()
    for row in rows:
        row.status = "SUPERSEDED"
    return [row.id for row in rows]


def ingest_trade_report(
    db: Session,
    *,
    path: Path,
    original_name: str,
    actor: Optional[str],
    cdu_id: Optional[int] = None,
    trade_date: Optional[date] = None,
    parsed: Optional[ParsedTradeFile] = None,
    run_price_check: bool = True,
) -> IngestResult:
    """Persist and import one Trade Report.  The caller commits."""
    from services.holdings_sync import sync_holdings
    from services.kase import apply_kase_prices_to_trades

    parsed = parsed or parse_with_cdu_overrides(path, original_name, db, known_cdu_id=cdu_id)
    cdu = resolve_cdu(db, cdu_id=cdu_id, cdu_prefix=parsed.cdu_prefix, cdu_name=parsed.cdu_name)
    if cdu is None:
        parsed.warnings.append("Не удалось определить ЧДУ автоматически — выберите его вручную.")
    else:
        # The resolved/selected manager is authoritative for every table.
        parsed.cdu_name = cdu.name

    parsed_date = trade_date or parsed.trade_date
    if trade_date is not None:
        parsed.trade_date = trade_date
    if not parsed_date:
        parsed.warnings.append("Не удалось определить дату — задайте её явно.")
        parsed_date = date.today()
        parsed.trade_date = parsed_date

    tf = TradeFile(
        cdu_id=cdu.id if cdu else None,
        trade_date=parsed_date,
        filename=original_name,
        raw_file_path=str(path),
        status="PARSED",
        rows_parsed=parsed.rows_parsed,
        rows_skipped=parsed.rows_skipped,
        parse_errors_json=json.dumps(
            {"warnings": parsed.warnings, "skipped": parsed.skipped[:50]},
            ensure_ascii=False,
        ),
        sha256=parsed.sha256,
        uploaded_by=actor,
    )
    db.add(tf)
    db.flush()

    source_doc = SourceDocument(
        doc_type="TRADE_REPORT",
        cdu_id=cdu.id if cdu else None,
        doc_date=parsed_date,
        file_name=original_name,
        file_path=str(path),
        sha256=parsed.sha256,
        file_size=path.stat().st_size if path.exists() else None,
        uploaded_by=actor,
        parsed_at=datetime.utcnow(),
        parse_status="OK",
        parse_meta_json=json.dumps(
            {"trade_file_id": tf.id, "warnings": parsed.warnings, "skipped": parsed.skipped[:50]},
            ensure_ascii=False,
        ),
        rows_imported=parsed.rows_parsed,
    )
    db.add(source_doc)
    db.flush()

    for pr in parsed.rows:
        f = pr.fields
        db.add(RawTrade(
            file_id=tf.id,
            cdu_id=cdu.id if cdu else None,
            trade_date=f.get("trade_date") or parsed_date,
            **{key: f.get(key) for key in _RAW_FIELDS},
        ))

    result = IngestResult(
        trade_file=tf, source_doc=source_doc, cdu=cdu,
        trade_date=parsed_date, parsed=parsed,
    )
    if cdu is None:
        result.counters = {"trades": 0, "skipped_no_cdu": len(parsed.rows)}
        return result

    result.counters = import_trades_from_parsed(
        db, parsed,
        uploaded_by=actor,
        source_doc_id=source_doc.id,
        commit=False,
        cdu_id=cdu.id,
    )
    tf.status = "IMPORTED"
    source_doc.rows_imported = result.counters.get("trades", 0)
    trade_dates = {pr.fields.get("trade_date") or parsed_date for pr in parsed.rows} or {parsed_date}
    result.superseded_file_ids = supersede_previous_files(
        db, cdu_id=cdu.id, trade_dates=trade_dates, keep_file_id=tf.id,
    )

    if run_price_check and result.counters.get("trades", 0) > 0:
        result.price_check = apply_kase_prices_to_trades(
            db, cdu_id=cdu.id, trade_date=parsed_date, actor=actor,
        )
    if result.counters.get("trades", 0) > 0:
        from services.anomaly_audit import audit_uploaded_trades
        db.flush()
        result.anomalies = audit_uploaded_trades(
            db,
            cdu_id=cdu.id,
            source_doc_id=source_doc.id,
            trade_date=parsed_date,
        )
    try:
        sync_holdings(db, cdu_id=cdu.id, actor=actor)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Holdings sync failed for cdu={cdu.id}: {exc!r}")
    # certificates uploaded before this Trade Report can now be bound by deal numbers
    from services.import_primary.binding import bind_orphan_certificates
    db.flush()
    for d in trade_dates:
        bind_orphan_certificates(db, d)
    return result


_RAW_FIELDS = (
    "deal_number", "order_number", "trade_time", "kp", "operation_type",
    "participant_code", "firm_code", "partner_code", "trade_account",
    "regime_code", "instrument_code", "instrument_category", "price", "lots",
    "volume", "settlement_date", "accrued_interest_volume", "yield_pct",
    "period_code", "redemption_price", "settlement_code", "type_code",
    "commission_total", "repo_rate_pct", "accrued_interest_volume_repo",
    "repo_sum", "repo_buyback_sum", "repo_term_days", "initial_discount_pct",
    "discount_lower_pct", "discount_upper_pct", "commission_clearing",
    "commission_trading", "commission_tech", "client_code", "currency_code",
    "system_link", "settlement_org", "trading_date", "clearing_firm_code",
    "activity_flag", "status", "nominal_volume", "clearing_account",
    "placement_price", "placement_amount", "placement_price_kzt",
    "redemption_price_kzt", "securities_to_execute",
)
