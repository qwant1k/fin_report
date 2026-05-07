"""Интеграционный тест бизнес-процесса 6.2.1 «РЕПО (ДУ → Trades/Repo)».

Проверяет полный pipeline на реальном файле Halyk Finance:
    parser → trade_importer → Trade (ledger) + RepoLot (позиции).

Бизнес-инварианты (из «Описание бизнес процессов.MD», раздел 6.2.1):
    A. REPO_OPEN  (К/П = B)  → Amount < 0 (отток), Value date = T
    B. REPO_CLOSE (К/П = S)  → Amount > 0 (приток), Value date = Дата расчетов
    C. Sub-fund = имя ДУ  (Halyk Finance)
    D. Направление: «Покупка» для открытия, «Продажа» для закрытия
    E. RepoLot создаётся для каждой пары открытие/закрытие:
       face_value = Сумма репо, close_value = Сумма выкупа РЕПО,
       repo_rate_pct и term_days проставлены
    F. Идемпотентность: повторный импорт за ту же (CDU, T) не плодит дубликаты
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import database as db_module
from database import Base
from models.db_models import CDU, BondLot, DepositLot, RepoLot, Trade
from services.calculator.constants import DEFAULT_CDU_SEED
from services.parser.trade_importer import import_single_trade_report_xlsx


REAL_FILE = (
    Path(__file__).resolve().parents[2]
    / "Примеры"
    / "Пример 1 Первичка ЧДУ"
    / "Trade report 1009 2025.xlsx"
)


pytestmark = pytest.mark.skipif(
    not REAL_FILE.exists(),
    reason=f"Отсутствует файл примера: {REAL_FILE}",
)


# ─────────── fixtures ───────────
@pytest.fixture()
def in_memory_db(monkeypatch):
    """Изолированная in-memory SQLite БД со всей схемой + seed ЧДУ."""
    # Important: подменяем engine/SessionLocal в модуле database, т.к.
    # trade_importer пользуется ими косвенно через импорт моделей.
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )
    SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", SessionLocal)

    # Импортируем модели и создаём схему на нашем engine.
    from models import db_models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # Seed ЧДУ (Halyk Finance нужен, чтобы импортер нашёл cdu_id)
    # participant_code уникален в БД — у НБ РК два портфеля с одним префиксом,
    # поэтому добавляем суффикс portfolio_code для уникальности.
    with SessionLocal() as db:
        for seed in DEFAULT_CDU_SEED:
            prefix = seed["participant_code_prefix"]
            pcode = seed.get("portfolio_code")
            participant_code = f"{prefix}_{pcode}" if pcode else prefix
            db.add(CDU(
                name=seed["name"],
                short_name=seed["short_name"],
                participant_code=participant_code,
                participant_code_prefix=prefix,
                portfolio_type=seed["portfolio_type"],
                portfolio_code=pcode,
                share_target_pct=seed["share_target_pct"],
                is_active=True,
            ))
        db.commit()

    yield SessionLocal
    engine.dispose()


# ─────────── helpers ───────────
def _repos(db, cdu_id: int):
    return db.execute(
        select(RepoLot)
        .where(RepoLot.cdu_id == cdu_id)
        .order_by(RepoLot.trade_date.asc(), RepoLot.instrument_code.asc())
    ).scalars().all()


def _trades_by_op(db, cdu_id: int, op: str):
    return db.execute(
        select(Trade)
        .where(Trade.cdu_id == cdu_id, Trade.operation_type == op, Trade.is_active == True)
        .order_by(Trade.instrument_code.asc())
    ).scalars().all()


# ─────────── tests ───────────
def test_import_creates_expected_trades_and_repo_lots(in_memory_db):
    """Полный прогон: parser → importer → БД. Проверяем состав записей."""
    SessionLocal = in_memory_db
    with SessionLocal() as db:
        result = import_single_trade_report_xlsx(db, str(REAL_FILE))

    assert result.get("error") is None, result
    assert result["cdu_name"] == "Halyk Finance"
    assert result["trade_date"] == "2025-09-10"
    # В файле 6 исполненных строк, из них REPO_HEADER не попадает в Trades → 4 Trade
    # (2 открытия + 2 закрытия). REPO_HEADER игнорируется (anchor only).
    assert result["trades"] == 4, f"Ожидали 4 Trade, получили {result['trades']}"
    assert result["repo_lots"] == 4  # _repo() вызывается на каждый REPO_OPEN/CLOSE

    with SessionLocal() as db:
        cdu = db.execute(select(CDU).where(CDU.name == "Halyk Finance")).scalars().one()

        opens = _trades_by_op(db, cdu.id, "REPO_OPEN")
        closes = _trades_by_op(db, cdu.id, "REPO_CLOSE")
        assert len(opens) == 2
        assert len(closes) == 2

        # По условию бизнес-процесса: инструменты KFUSb47 и EABRb40
        assert {t.instrument_code for t in opens} == {"KFUSb47", "EABRb40"}
        assert {t.instrument_code for t in closes} == {"KFUSb47", "EABRb40"}


def test_repo_open_is_cash_outflow(in_memory_db):
    """Инвариант A: REPO_OPEN → amount_kzt < 0 (отток), value_date = T."""
    SessionLocal = in_memory_db
    with SessionLocal() as db:
        import_single_trade_report_xlsx(db, str(REAL_FILE))

    with SessionLocal() as db:
        cdu = db.execute(select(CDU).where(CDU.name == "Halyk Finance")).scalars().one()
        opens = _trades_by_op(db, cdu.id, "REPO_OPEN")
        for t in opens:
            assert t.amount_kzt < 0, (
                f"Открытие РЕПО должно быть оттоком (amount<0), "
                f"получили {t.amount_kzt} для {t.instrument_code}"
            )
            # Для открытия Value date должна совпадать с Trade date = T
            assert t.value_date == date(2025, 9, 10), (
                f"Для REPO_OPEN Value date=T (10.09.2025), получили {t.value_date}"
            )
            assert t.direction == "Покупка"
            assert t.instrument_category == "REVERSE_REPO"


def test_repo_close_is_cash_inflow_with_settlement_value_date(in_memory_db):
    """Инвариант B+D: REPO_CLOSE → amount_kzt > 0, Value date = Дата расчетов (11.09)."""
    SessionLocal = in_memory_db
    with SessionLocal() as db:
        import_single_trade_report_xlsx(db, str(REAL_FILE))

    with SessionLocal() as db:
        cdu = db.execute(select(CDU).where(CDU.name == "Halyk Finance")).scalars().one()
        closes = _trades_by_op(db, cdu.id, "REPO_CLOSE")
        for t in closes:
            assert t.amount_kzt > 0, (
                f"Закрытие РЕПО должно быть притоком (amount>0), "
                f"получили {t.amount_kzt} для {t.instrument_code}"
            )
            assert t.value_date == date(2025, 9, 11), (
                f"REPO_CLOSE: Value date должна равняться Дата расчетов (11.09.2025), "
                f"получили {t.value_date}"
            )
            assert t.direction == "Продажа"


def test_repo_lots_have_business_fields_populated(in_memory_db):
    """Инвариант E: RepoLot содержит face_value (Сумма репо), ставку и срок."""
    SessionLocal = in_memory_db
    with SessionLocal() as db:
        import_single_trade_report_xlsx(db, str(REAL_FILE))

    with SessionLocal() as db:
        cdu = db.execute(select(CDU).where(CDU.name == "Halyk Finance")).scalars().one()
        repos = _repos(db, cdu.id)
        # Импортер создаёт по одному RepoLot на каждую пару OPEN/CLOSE
        # (close матчится к открытому). Оба инструмента должны присутствовать.
        lots_with_face = [r for r in repos if r.face_value and r.face_value > 0]
        assert len(lots_with_face) >= 2, (
            f"Ожидали ≥2 репо-лотов с face_value>0, получили {len(lots_with_face)}"
        )
        codes = {r.instrument_code for r in lots_with_face}
        assert codes == {"KFUSb47", "EABRb40"}

        for r in lots_with_face:
            assert r.face_value > 0, f"face_value должен быть > 0 для {r.instrument_code}"
            # Ставка РЕПО указана в исходном файле — должна быть ненулевой
            assert r.repo_rate_pct and r.repo_rate_pct > 0, (
                f"repo_rate_pct должен быть проставлен для {r.instrument_code}"
            )
            assert r.term_days == 1, (
                f"Срок РЕПО в исходных сделках = 1 день, получили {r.term_days}"
            )
            # trade_date = T (10.09.2025)
            assert r.trade_date == date(2025, 9, 10)


def test_repo_lots_get_closed_after_import(in_memory_db):
    """Инвариант E (продолжение): REPO_CLOSE закрывает ранее открытый лот.

    В файле 2 открытия + 2 закрытия (одна дата расчётов 11.09) — после импорта
    по каждому инструменту должен остаться закрытый лот с close_date=11.09.
    """
    SessionLocal = in_memory_db
    with SessionLocal() as db:
        import_single_trade_report_xlsx(db, str(REAL_FILE))

    with SessionLocal() as db:
        cdu = db.execute(select(CDU).where(CDU.name == "Halyk Finance")).scalars().one()
        repos = _repos(db, cdu.id)
        closed = [r for r in repos if r.is_closed]
        # Текущий импортер сопоставляет close с существующим открытым лотом → 2 закрытых.
        assert len(closed) >= 2, (
            f"Ожидали ≥2 закрытых репо-лотов, получили {len(closed)}"
        )
        for r in closed:
            assert r.close_date == date(2025, 9, 11), (
                f"close_date должен быть = Дата расчетов (11.09.2025), "
                f"получили {r.close_date}"
            )
            assert r.close_value and r.close_value > 0


def test_reimport_is_idempotent(in_memory_db):
    """Инвариант F: повторный импорт не плодит дубликаты Trade/RepoLot.

    Поддерживает требование бизнес-процесса «при перезапуске за ту же дату T
    дубликаты не создаются — данные просто обновляются» (раздел 5.4 документа).
    """
    SessionLocal = in_memory_db
    with SessionLocal() as db:
        first = import_single_trade_report_xlsx(db, str(REAL_FILE))
    with SessionLocal() as db:
        second = import_single_trade_report_xlsx(db, str(REAL_FILE))

    assert first["trades"] == second["trades"]

    with SessionLocal() as db:
        cdu = db.execute(select(CDU).where(CDU.name == "Halyk Finance")).scalars().one()
        active_trades = db.execute(
            select(Trade).where(Trade.cdu_id == cdu.id, Trade.is_active == True)
        ).scalars().all()
        # 4 активных Trade (2 OPEN + 2 CLOSE), старые soft-deleted
        assert len(active_trades) == 4, (
            f"После повторного импорта ожидали 4 активных Trade, получили {len(active_trades)}"
        )

        # RepoLot-ы тоже не должны задваиваться: удаляются при переимпорте
        repos = _repos(db, cdu.id)
        # 2 открытия + 2 закрытия = 4 записи RepoLot (close-ветка создаёт свою, если не нашлась открытая в этом импорте)
        # После повторного импорта число лотов не должно превышать число в первом.
        assert len(repos) <= first["repo_lots"], (
            f"Повторный импорт создал лишние RepoLot: было {first['repo_lots']}, стало {len(repos)}"
        )


def test_no_bond_or_deposit_lots_created(in_memory_db):
    """В файле нет покупок ЦБ и депозитов — не должно появляться BondLot/DepositLot."""
    SessionLocal = in_memory_db
    with SessionLocal() as db:
        import_single_trade_report_xlsx(db, str(REAL_FILE))

    with SessionLocal() as db:
        cdu = db.execute(select(CDU).where(CDU.name == "Halyk Finance")).scalars().one()
        bonds = db.execute(select(BondLot).where(BondLot.cdu_id == cdu.id)).scalars().all()
        deps = db.execute(select(DepositLot).where(DepositLot.cdu_id == cdu.id)).scalars().all()
        assert bonds == []
        assert deps == []
