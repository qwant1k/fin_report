"""Главный оркестратор импорта Risk Report XLSM в БД.

Идемпотентность: для каждой пары (cdu_id, snapshot_date, ...) делается upsert,
повторный запуск за ту же дату не создаёт дубликатов (соответствует требованию
бизнес-процесса 5.4 "Про повторный запуск").
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

from loguru import logger
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.db_models import (
    AccountReceivable,
    BondLot,
    CashSnapshot,
    CDU,
    DepositLot,
    FXRate,
    ImportJob,
    InstrumentReference,
    MBMIndex,
    MVSnapshot,
    RepoLot,
    SourceDocument,
)

from .helpers import (
    extract_date_from_filename,
    file_sha256,
    safe_sheet,
)
from .sheet_parsers import (
    get_report_date,
    parse_ar_sheet,
    parse_bond_lots_sheet,
    parse_cash_sheet,
    parse_dep_sheet,
    parse_fx_sheet,
    parse_mbm_sheet,
    parse_mv_sheet,
    parse_reference_sheet,
    parse_repo_sheet,
)


@dataclass
class ImportResult:
    """Сводка по результату одного файла."""
    file_path: Path
    file_date: Optional[date] = None
    source_doc_id: Optional[int] = None
    cash_rows: int = 0
    mv_rows: int = 0
    reference_rows: int = 0
    fx_rows: int = 0
    mbm_rows: int = 0
    bond_lots: int = 0
    repo_lots: int = 0
    deposit_lots: int = 0
    ar_rows: int = 0
    skipped: bool = False
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    def total_rows(self) -> int:
        return (self.cash_rows + self.mv_rows + self.reference_rows + self.fx_rows
                + self.mbm_rows + self.bond_lots + self.repo_lots
                + self.deposit_lots + self.ar_rows)

    def to_log_line(self) -> str:
        if self.error:
            return f"[ERR ] {self.file_path.name}: {self.error}"
        if self.skipped:
            return f"[SKIP] {self.file_path.name}: {self.warnings[0] if self.warnings else 'duplicate'}"
        return (f"[OK  ] {self.file_path.name} ({self.file_date}): "
                f"cash={self.cash_rows} mv={self.mv_rows} ref={self.reference_rows} "
                f"fx={self.fx_rows} mbm={self.mbm_rows} bonds={self.bond_lots} "
                f"repo={self.repo_lots} dep={self.deposit_lots} ar={self.ar_rows}")


# ═══════════════════════════════════════════════════════════════════════════
# Single-file import
# ═══════════════════════════════════════════════════════════════════════════
def import_risk_report(
    db: Session,
    file_path: Path | str,
    *,
    uploaded_by: Optional[str] = None,
    skip_if_imported: bool = True,
) -> ImportResult:
    """Импорт одного XLSM-файла Risk Report в БД.

    Возвращает `ImportResult`. Все исключения ловит и записывает в `error`.
    """
    fp = Path(file_path)
    res = ImportResult(file_path=fp)

    try:
        # 1. Дата отчёта
        file_date = extract_date_from_filename(fp)

        # 2. Дедупликация по sha256 (если такой файл уже импортирован — пропустить)
        sha = file_sha256(fp) if fp.exists() else None
        if skip_if_imported and sha:
            existing = db.execute(select(SourceDocument).where(
                SourceDocument.sha256 == sha,
                SourceDocument.parse_status == "OK",
            )).scalars().first()
            if existing:
                res.skipped = True
                res.warnings.append(f"уже импортирован, source_doc_id={existing.id}")
                res.source_doc_id = existing.id
                res.file_date = existing.doc_date
                return res

        # 3. Создать SourceDocument запись
        sd = SourceDocument(
            doc_type="RISK_REPORT_XLSM",
            cdu_id=None,
            doc_date=file_date,
            file_name=fp.name,
            file_path=str(fp.resolve()),
            sha256=sha,
            file_size=fp.stat().st_size if fp.exists() else None,
            uploaded_by=uploaded_by,
            parse_status="PENDING",
        )
        db.add(sd)
        db.flush()
        res.source_doc_id = sd.id

        # 4. Открыть книгу (read_only + data_only — формулы как значения)
        wb = load_workbook(fp, read_only=True, data_only=True, keep_vba=False)

        # 5. Уточнить дату через Report!B2
        report_ws = safe_sheet(wb, "Report")
        report_b2 = get_report_date(report_ws) if report_ws else None
        if report_b2 and not file_date:
            file_date = report_b2
        if file_date is None:
            file_date = report_b2 or date.today()
        res.file_date = file_date
        sd.doc_date = file_date

        # 6. Кеш: имя CDU → id
        cdu_map = {c.name: c.id for c in db.execute(select(CDU)).scalars().all()}

        # 7. Парсеры по листам
        # 7.1 Cash
        cash_ws = safe_sheet(wb, "Cash")
        if cash_ws is not None:
            rows = parse_cash_sheet(cash_ws, fallback_date=file_date)
            res.cash_rows = _upsert_cash(db, rows, cdu_map, sd.id)

        # 7.2 MV
        mv_ws = safe_sheet(wb, "MV")
        if mv_ws is not None:
            rows = parse_mv_sheet(mv_ws, fallback_date=file_date)
            res.mv_rows = _upsert_mv(db, rows, cdu_map, sd.id)

        # 7.3 Справочник
        ref_ws = safe_sheet(wb, "Справочник", "Spravochnik", "Reference")
        if ref_ws is not None:
            rows = parse_reference_sheet(ref_ws)
            res.reference_rows = _upsert_reference(db, rows)

        # 7.4 FX
        fx_ws = safe_sheet(wb, "Нацбанк Казахстана, Доллар США_",
                           "Нацбанк", "Доллар США", "USD KZT")
        if fx_ws is not None:
            rows = parse_fx_sheet(fx_ws)
            res.fx_rows = _upsert_fx(db, rows)

        # 7.5 MBM (история)
        mbm_ws = safe_sheet(wb, "MBM index - с 1 апреля 2024 г",
                            "MBM index", "MBM Index")
        if mbm_ws is not None:
            rows = parse_mbm_sheet(mbm_ws)
            res.mbm_rows = _upsert_mbm(db, rows)

        # 7.6 Bond lots
        for sheet_name, category in [
            ("ГЦБ",       "GOV_BONDS"),
            ("Агентские", "AGENCY_BONDS"),
            ("МФО",       "MFO_BONDS"),
            ("Ин. ЦБ",    "FOREIGN_BONDS"),
            ("Ин.ЦБ",     "FOREIGN_BONDS"),
            ("In CB",     "FOREIGN_BONDS"),
        ]:
            ws = safe_sheet(wb, sheet_name)
            if ws is None:
                continue
            rows = parse_bond_lots_sheet(ws, category=category, fallback_date=file_date)
            if rows:
                res.bond_lots += _upsert_bond_lots(db, rows, cdu_map, sd.id, file_date)

        # 7.7 REPO lots
        repo_ws = safe_sheet(wb, "Repo")
        if repo_ws is not None:
            rows = parse_repo_sheet(repo_ws, fallback_date=file_date)
            res.repo_lots = _upsert_repo_lots(db, rows, cdu_map, sd.id, file_date)

        # 7.8 Deposit lots
        dep_ws = safe_sheet(wb, "Dep", "Депозит")
        if dep_ws is not None:
            rows = parse_dep_sheet(dep_ws, fallback_date=file_date)
            res.deposit_lots = _upsert_deposit_lots(db, rows, cdu_map, sd.id, file_date)

        # 7.9 AR
        ar_ws = safe_sheet(wb, "Accounts receivable", "Дебиторская задолженность",
                           "Дебиторка")
        if ar_ws is not None:
            rows = parse_ar_sheet(ar_ws, fallback_date=file_date)
            res.ar_rows = _upsert_ar(db, rows, cdu_map, sd.id)

        # 8. Финализация
        wb.close()
        sd.parsed_at = datetime.utcnow()
        sd.parse_status = "OK"
        sd.rows_imported = res.total_rows()
        sd.parse_meta_json = json.dumps({
            "cash": res.cash_rows, "mv": res.mv_rows, "ref": res.reference_rows,
            "fx": res.fx_rows, "mbm": res.mbm_rows, "bonds": res.bond_lots,
            "repo": res.repo_lots, "dep": res.deposit_lots, "ar": res.ar_rows,
        }, ensure_ascii=False)
        db.commit()

    except Exception as exc:
        logger.exception(f"import_risk_report failed for {fp}")
        db.rollback()
        res.error = repr(exc)
        # Best-effort: пометить SourceDocument как ERROR (уже создан)
        try:
            if res.source_doc_id:
                sd2 = db.get(SourceDocument, res.source_doc_id)
                if sd2:
                    sd2.parse_status = "ERROR"
                    sd2.parse_errors = repr(exc)[:1000]
                    sd2.parsed_at = datetime.utcnow()
                    db.commit()
        except Exception:
            pass

    return res


# ═══════════════════════════════════════════════════════════════════════════
# Bulk folder import
# ═══════════════════════════════════════════════════════════════════════════
def import_folder(
    db: Session,
    folder: Path | str,
    *,
    uploaded_by: Optional[str] = None,
    job: Optional[ImportJob] = None,
    pattern: str = "**/*.xlsm",
) -> ImportJob:
    """Рекурсивно импортирует все XLSM-файлы из папки.

    Если `job` не передан, создаётся новый. Прогресс пишется в `job.files_done` и т.д.
    """
    folder_p = Path(folder)
    files: list[Path] = sorted(folder_p.glob(pattern))

    if job is None:
        job = ImportJob(
            job_type="HISTORIC_RR",
            status="RUNNING",
            triggered_by=uploaded_by,
            files_total=len(files),
            params_json=json.dumps({"folder": str(folder_p), "pattern": pattern}),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
    else:
        job.files_total = len(files)
        job.status = "RUNNING"
        db.commit()

    log_lines: list[str] = []
    total_rows = 0
    failed = 0

    for i, fp in enumerate(files, start=1):
        # Свежая сессия не нужна — мы внутри Session, но коммиты атомарны
        result = import_risk_report(db, fp, uploaded_by=uploaded_by)
        log_lines.append(result.to_log_line())
        if result.error:
            failed += 1
        else:
            total_rows += result.total_rows()

        # Обновлять прогресс каждые 5 файлов или в конце
        if i % 5 == 0 or i == len(files):
            job.files_done = i
            job.files_failed = failed
            job.rows_imported = total_rows
            job.log = "\n".join(log_lines[-200:])  # последние 200 строк
            db.commit()

    job.finished_at = datetime.utcnow()
    job.status = "DONE" if failed == 0 else ("PARTIAL" if failed < len(files) else "FAILED")
    job.files_done = len(files)
    job.files_failed = failed
    job.rows_imported = total_rows
    job.log = "\n".join(log_lines)
    db.commit()
    db.refresh(job)
    return job


# ═══════════════════════════════════════════════════════════════════════════
# Internal upsert helpers
# ═══════════════════════════════════════════════════════════════════════════
def _resolve_cdu_id(cdu_map: dict[str, int], name: Optional[str]) -> Optional[int]:
    if not name:
        return None
    return cdu_map.get(name)


def _upsert_cash(db: Session, rows: list[dict], cdu_map: dict[str, int],
                 source_doc_id: int) -> int:
    cnt = 0
    for r in rows:
        cdu_id = _resolve_cdu_id(cdu_map, r["cdu_name"])
        if not cdu_id:
            continue
        existing = db.execute(select(CashSnapshot).where(
            CashSnapshot.cdu_id == cdu_id,
            CashSnapshot.snapshot_date == r["snapshot_date"],
            CashSnapshot.currency == r["currency"],
        )).scalars().first()
        if existing:
            existing.amount = r["amount"]
            existing.source = "rr_import"
            existing.source_doc_id = source_doc_id
        else:
            db.add(CashSnapshot(
                cdu_id=cdu_id,
                snapshot_date=r["snapshot_date"],
                currency=r["currency"],
                amount=r["amount"],
                source="rr_import",
                source_doc_id=source_doc_id,
            ))
        cnt += 1
    return cnt


def _upsert_mv(db: Session, rows: list[dict], cdu_map: dict[str, int],
               source_doc_id: int) -> int:
    cnt = 0
    for r in rows:
        cdu_id = _resolve_cdu_id(cdu_map, r["cdu_name"])
        if not cdu_id:
            continue
        existing = db.execute(select(MVSnapshot).where(
            MVSnapshot.cdu_id == cdu_id,
            MVSnapshot.snapshot_date == r["snapshot_date"],
        )).scalars().first()
        kwargs = dict(
            cash_flow=r.get("cash_flow"),
            market_value_total=r["market_value_total"],
            return_pct=r.get("return_pct"),
            ytm_weighted=r.get("ytm_weighted"),
            duration_weighted=r.get("duration_weighted"),
            source="rr_import",
            source_doc_id=source_doc_id,
        )
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
        else:
            db.add(MVSnapshot(
                cdu_id=cdu_id,
                snapshot_date=r["snapshot_date"],
                **kwargs,
            ))
        cnt += 1
    return cnt


def _upsert_reference(db: Session, rows: list[dict]) -> int:
    cnt = 0
    for r in rows:
        existing = db.execute(select(InstrumentReference).where(
            InstrumentReference.isin == r["isin"],
        )).scalars().first()
        if existing:
            for k in ("ticker_kase", "instrument_name", "issuer", "bond_type",
                     "coupon_rate_pct", "frequency", "base", "nominal",
                     "start_date", "maturity_date", "currency"):
                v = r.get(k)
                if v is not None:
                    setattr(existing, k, v)
        else:
            db.add(InstrumentReference(**{k: v for k, v in r.items() if k != "src_row"}))
        cnt += 1
    return cnt


def _upsert_fx(db: Session, rows: list[dict]) -> int:
    cnt = 0
    for r in rows:
        existing = db.execute(select(FXRate).where(
            FXRate.rate_date == r["rate_date"],
            FXRate.currency == r["currency"],
        )).scalars().first()
        if existing:
            existing.rate = r["rate"]
            existing.source = "nbrk_rr"
        else:
            db.add(FXRate(
                rate_date=r["rate_date"],
                currency=r["currency"],
                rate=r["rate"],
                source="nbrk_rr",
            ))
        cnt += 1
    return cnt


def _upsert_mbm(db: Session, rows: list[dict]) -> int:
    cnt = 0
    for r in rows:
        existing = db.execute(select(MBMIndex).where(
            MBMIndex.index_date == r["index_date"],
        )).scalars().first()
        if existing:
            if r.get("ytm_value") is not None:
                existing.ytm_value = r["ytm_value"]
            if r.get("duration") is not None:
                existing.duration = r["duration"]
            existing.source = "rr_import"
        else:
            db.add(MBMIndex(
                index_date=r["index_date"],
                ytm_value=r.get("ytm_value"),
                duration=r.get("duration"),
                source="rr_import",
            ))
        cnt += 1
    return cnt


def _upsert_bond_lots(db: Session, rows: list[dict], cdu_map: dict[str, int],
                      source_doc_id: int, snapshot_date: date) -> int:
    """Лоты ЦБ — снимок состояния портфеля на snapshot_date.
    Идемпотентность: ключ (cdu_id, isin, valuation_date, source_doc_id)."""
    cnt = 0
    for r in rows:
        cdu_id = _resolve_cdu_id(cdu_map, r["cdu_name"])
        if not cdu_id:
            continue
        val_date = r.get("valuation_date") or snapshot_date
        existing = db.execute(select(BondLot).where(
            BondLot.cdu_id == cdu_id,
            BondLot.isin == r["isin"],
            BondLot.valuation_date == val_date,
        )).scalars().first()
        face = r.get("face_value") or 0.0
        qty = r.get("quantity") or 0.0
        kwargs = dict(
            category=r["category"],
            trade_date=r.get("trade_date") or val_date,
            valuation_date=val_date,
            quantity_initial=qty,
            quantity_current=qty,
            face_value_initial=face,
            face_value_current=face,
            purchase_price=r.get("purchase_price"),
            market_price=r.get("market_price"),
            accrued_interest=r.get("accrued_interest"),
            market_value=r.get("market_value"),
            total_value=r.get("total_value"),
            weight=r.get("weight"),
            ytm=r.get("ytm"),
            duration=r.get("duration"),
            maturity_status=r.get("maturity_status"),
            source_doc_id=source_doc_id,
        )
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
        else:
            db.add(BondLot(cdu_id=cdu_id, isin=r["isin"], **kwargs))
        cnt += 1
    return cnt


def _upsert_repo_lots(db: Session, rows: list[dict], cdu_map: dict[str, int],
                      source_doc_id: int, snapshot_date: date) -> int:
    cnt = 0
    for r in rows:
        cdu_id = _resolve_cdu_id(cdu_map, r["cdu_name"])
        if not cdu_id:
            continue
        val_date = r.get("valuation_date") or snapshot_date
        # Ключ: cdu_id + instrument_code + valuation_date
        existing = db.execute(select(RepoLot).where(
            RepoLot.cdu_id == cdu_id,
            RepoLot.instrument_code == r.get("instrument_code"),
            RepoLot.valuation_date == val_date,
            RepoLot.face_value == r["face_value"],
        )).scalars().first()
        kwargs = dict(
            instrument_code=r.get("instrument_code"),
            isin=r.get("isin"),
            trade_date=r.get("trade_date") or val_date,
            valuation_date=val_date,
            close_date=r.get("close_date"),
            face_value=r["face_value"],
            close_value=r.get("close_value"),
            repo_rate_pct=r.get("repo_rate_pct"),
            accrued_interest=r.get("accrued_interest"),
            term_days=r.get("term_days"),
            market_value=r.get("market_value"),
            source_doc_id=source_doc_id,
        )
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
        else:
            db.add(RepoLot(cdu_id=cdu_id, **kwargs))
        cnt += 1
    return cnt


def _upsert_deposit_lots(db: Session, rows: list[dict], cdu_map: dict[str, int],
                         source_doc_id: int, snapshot_date: date) -> int:
    cnt = 0
    for r in rows:
        cdu_id = _resolve_cdu_id(cdu_map, r["cdu_name"])
        if not cdu_id:
            continue
        val_date = r.get("valuation_date") or snapshot_date
        existing = db.execute(select(DepositLot).where(
            DepositLot.cdu_id == cdu_id,
            DepositLot.valuation_date == val_date,
            DepositLot.principal == r["principal"],
        )).scalars().first()
        kwargs = dict(
            trade_date=r.get("trade_date") or val_date,
            valuation_date=val_date,
            close_date=r.get("close_date"),
            principal=r["principal"],
            interest_rate_pct=r.get("interest_rate_pct"),
            accrued_interest=r.get("accrued_interest"),
            market_value=r.get("market_value"),
            source_doc_id=source_doc_id,
        )
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
        else:
            db.add(DepositLot(cdu_id=cdu_id, **kwargs))
        cnt += 1
    return cnt


def _upsert_ar(db: Session, rows: list[dict], cdu_map: dict[str, int],
               source_doc_id: int) -> int:
    cnt = 0
    for r in rows:
        cdu_id = _resolve_cdu_id(cdu_map, r["cdu_name"])
        if not cdu_id:
            # Для НБ РК вкладок AR может не содержать ДУ — пропускаем строки без cdu
            continue
        rec_date = r.get("record_date")
        if not rec_date:
            continue
        existing = db.execute(select(AccountReceivable).where(
            AccountReceivable.cdu_id == cdu_id,
            AccountReceivable.isin == r["isin"],
            AccountReceivable.record_date == rec_date,
        )).scalars().first()
        kwargs = dict(
            isin=r["isin"],
            description=r.get("description"),
            currency=r.get("currency", "KZT"),
            balance_currency=r.get("balance_currency"),
            balance_kzt=r.get("balance_kzt", 0.0),
            amount=r.get("balance_kzt") or 0.0,
            due_date=r.get("due_date"),
            status="OPEN",
            source_doc_id=source_doc_id,
        )
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
        else:
            db.add(AccountReceivable(
                cdu_id=cdu_id,
                record_date=rec_date,
                **kwargs,
            ))
        cnt += 1
    return cnt
