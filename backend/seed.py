"""Seed initial reference data (CDU, limits, admin user, formula defaults)."""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy.orm import Session

from auth import hash_password
from config import settings
from models.db_models import (
    CDU,
    CDULimit,
    FormulaDefinition,
    InstrumentCategoryRule,
    User,
)
from services.calculator.constants import DEFAULT_CDU_SEED, DEFAULT_LIMITS


def seed_initial_data(db: Session) -> None:
    _seed_admin(db)
    _seed_cdus(db)
    _seed_rules(db)
    _seed_formulas(db)


def _seed_admin(db: Session) -> None:
    if db.query(User).filter_by(username=settings.admin_username).first():
        return
    db.add(User(
        username=settings.admin_username,
        full_name="Administrator",
        email=None,
        password_hash=hash_password(settings.admin_password),
        role="admin",
        is_active=True,
    ))
    db.commit()


def _seed_cdus(db: Session) -> None:
    """Идемпотентный seed: добавляет только отсутствующих ЧДУ/портфели НБ РК."""
    today = date.today()
    existing_names = {n for (n,) in db.query(CDU.name).all()}
    used_codes = {c for (c,) in db.query(CDU.participant_code).all()}
    for spec in DEFAULT_CDU_SEED:
        if spec["name"] in existing_names:
            continue
        # participant_code должен быть уникальным даже у двух портфелей НБ РК
        suffix = spec.get("portfolio_code") or "0BT"
        base_code = f"{spec['participant_code_prefix']}-{suffix}"
        code = base_code
        i = 1
        while code in used_codes:
            i += 1
            code = f"{base_code}-{i}"
        used_codes.add(code)

        cdu = CDU(
            name=spec["name"],
            short_name=spec["short_name"],
            participant_code=code,
            participant_code_prefix=spec["participant_code_prefix"],
            portfolio_type=spec.get("portfolio_type", "PRIVATE_CDU"),
            portfolio_code=spec.get("portfolio_code"),
            share_target_pct=spec["share_target_pct"],
            is_active=True,
        )
        db.add(cdu)
        db.flush()
        for cat, (mn, mx) in DEFAULT_LIMITS.items():
            db.add(CDULimit(
                cdu_id=cdu.id,
                instrument_category=cat,
                min_limit_pct=mn,
                max_limit_pct=mx,
                hard_limit_pct=mx,
                soft_limit_pct=mx,
                valid_from=today,
            ))
    db.commit()


def _seed_rules(db: Session) -> None:
    if db.query(InstrumentCategoryRule).count() > 0:
        return
    rules = [
        # Reverse REPO режимы — расширенный список (EBRP/REPO/REPS — KASE)
        ("Reverse REPO", 10, "EBRP,REPO,REPS,Reverse,REVR", None, None, "REVERSE_REPO"),
        # ГЦБ — Министерство финансов РК (KZ-MTS, KZTS, KZ-MGB)
        ("ГЦБ МФ РК", 20, None, "KFUS,MGB,MOM,MUM,MKM,KZ_MGB", None, "GOV_BONDS"),
        # Агентские (KEGOC, БРК, Отбасы, КФУ, ҚТЖ, Байтерек, Самрук-Қазына)
        ("Агентские", 30, None,
         "EABR,EAB,KEGC,BRKZ,DBKZ,KZAR,SMRK,SAMR,SKZ,BAIT,KZBN,OFKZ,OFK,KFUS_AG",
         None, "AGENCY_BONDS"),
        # МФО (ЕБРР, АБР, ЕАБР, IFC и др.)
        ("МФО", 40, None, "MFO,EBRR,EBR,EABR,IFC,ADB,WBI,ABRD", None, "MFO_BONDS"),
        # Иностранные ЦБ (USD) — обычно US Treasuries (US**)
        ("Ин. ЦБ (USD)", 50, None, "US,UST,USTRES", r"^US[0-9A-Z]{6,}", "FOREIGN_BONDS"),
        # Депозиты (используется только для НБ РК)
        ("Депозит", 60, "MM,DEP", None, None, "DEPOSIT"),
        # OTHER fallback
        ("OTHER", 99, None, None, None, "OTHER"),
    ]
    for name, prio, regimes, prefix, regex, target in rules:
        db.add(InstrumentCategoryRule(
            priority=prio,
            name=name,
            match_regime_in=regimes,
            match_code_prefix=prefix,
            match_code_regex=regex,
            target_category=target,
            is_active=True,
        ))
    db.commit()


def _seed_formulas(db: Session) -> None:
    if db.query(FormulaDefinition).count() > 0:
        return
    defaults = [
        {
            "code": "CMV_BONDS",
            "name": "CMV облигаций",
            "description": "nominal × price/100 + accrued_interest",
            "target": "CMV",
            "expression_json": json.dumps({
                "op": "ADD",
                "args": [
                    {"op": "MUL", "args": [
                        {"var": "nominal_volume"},
                        {"op": "DIV", "args": [{"var": "price"}, {"const": 100}]},
                    ]},
                    {"var": "accrued_interest"},
                ],
            }),
        },
        {
            "code": "CMV_REPO",
            "name": "CMV reverse-REPO",
            "description": "Сумма выкупа РЕПО (гарантированный возврат)",
            "target": "CMV",
            "expression_json": json.dumps({"var": "repo_buyback_sum"}),
        },
        {
            "code": "DURATION_REPO",
            "name": "Дюрация РЕПО",
            "description": "Срок РЕПО / 365",
            "target": "DURATION",
            "expression_json": json.dumps({
                "op": "DIV",
                "args": [{"var": "repo_term_days"}, {"const": 365}],
            }),
        },
        {
            "code": "PORTFOLIO_YTM",
            "name": "Взвешенный YTM портфеля",
            "description": "Σ ytm_i × cmv_i / total_cmv",
            "target": "YTM",
            "expression_json": json.dumps({
                "op": "WEIGHTED_AVG",
                "field": "ytm",
                "weight": "market_value_current",
            }),
        },
    ]
    for spec in defaults:
        db.add(FormulaDefinition(**spec, is_active=True, version=1))
    db.commit()
