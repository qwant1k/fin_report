"""Synchronization and compatibility helpers for the CDU reference book."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from models.db_models import CDU, CDULimit
from services.calculator.constants import DEFAULT_CDU_SEED, DEFAULT_LIMITS
from services.cdu_lookup import find_cdu


VALID_PORTFOLIO_TYPES = {"PRIVATE_CDU", "NBRK_OWN", "NBRK_RESERVE"}


def normalize_limit_category(value: str | None) -> str | None:
    """Convert old visible captions to stable calculator category keys."""
    raw = (value or "").strip()
    if not raw:
        return None
    if raw in {*DEFAULT_LIMITS, "OTHER"}:
        return raw
    checks = (
        ("cash", "CASH"),
        ("государственные облигации", "GOV_BONDS"),
        ("обратное repo", "REVERSE_REPO"),
        ("обратное репо", "REVERSE_REPO"),
        ("мфо (", "MFO_BONDS"),
        ("агентские облигации", "AGENCY_BONDS"),
        ("иностранные цб", "FOREIGN_BONDS"),
        ("депозит", "DEPOSIT"),
        ("дебиторская задолженность", "RECEIVABLES"),
        ("прочее", "OTHER"),
    )
    lowered = raw.casefold()
    for prefix, category in checks:
        if lowered.startswith(prefix):
            return category
    return raw


def sync_standard_cdus(db: Session) -> dict[str, Any]:
    """Add missing standard managers without replacing existing production rows.

    Existing IDs, legal names, participant codes and history remain unchanged.
    Legacy ``SR_PAM_*`` values are moved into ``report_code`` and each manager
    receives any missing standard limit categories.
    """
    created_names: list[str] = []
    updated_names: list[str] = []
    limits_created = 0
    used_codes = {code for (code,) in db.query(CDU.participant_code).all() if code}

    for spec in DEFAULT_CDU_SEED:
        cdu = find_cdu(db, name=spec["name"], include_inactive=True)
        changed = False
        if cdu is None:
            suffix = spec.get("portfolio_code") or "0BT"
            base_code = f"{spec['participant_code_prefix']}-{suffix}"
            participant_code = base_code
            number = 1
            while participant_code in used_codes:
                number += 1
                participant_code = f"{base_code}-{number}"
            used_codes.add(participant_code)
            cdu = CDU(
                name=spec["name"],
                short_name=spec["short_name"],
                participant_code=participant_code,
                participant_code_prefix=spec["participant_code_prefix"],
                report_code=spec.get("report_code"),
                portfolio_type=spec.get("portfolio_type", "PRIVATE_CDU"),
                portfolio_code=spec.get("portfolio_code"),
                share_target_pct=spec["share_target_pct"],
                is_active=True,
            )
            db.add(cdu)
            db.flush()
            created_names.append(cdu.short_name)
        else:
            for field in (
                "name", "short_name", "participant_code", "participant_code_prefix",
                "report_code", "portfolio_code", "contact_email", "contact_manager",
            ):
                current = getattr(cdu, field)
                if not isinstance(current, str):
                    continue
                cleaned = current.strip()
                normalized_value = cleaned or None
                if field in {"name", "short_name", "participant_code", "participant_code_prefix"}:
                    normalized_value = cleaned
                if current != normalized_value:
                    setattr(cdu, field, normalized_value)
                    changed = True
            legacy_code = None
            if (cdu.portfolio_type or "").startswith("SR_PAM_"):
                legacy_code = cdu.portfolio_type
            elif (cdu.portfolio_code or "").startswith("SR_PAM_"):
                legacy_code = cdu.portfolio_code
            wanted_report_code = legacy_code or spec.get("report_code")
            if wanted_report_code and not cdu.report_code:
                cdu.report_code = wanted_report_code
                changed = True
            if cdu.portfolio_type not in VALID_PORTFOLIO_TYPES:
                cdu.portfolio_type = spec.get("portfolio_type", "PRIVATE_CDU")
                changed = True
            if spec.get("portfolio_type") in {"NBRK_OWN", "NBRK_RESERVE"}:
                if cdu.portfolio_type != spec["portfolio_type"]:
                    cdu.portfolio_type = spec["portfolio_type"]
                    changed = True
                if cdu.portfolio_code != spec.get("portfolio_code"):
                    cdu.portfolio_code = spec.get("portfolio_code")
                    changed = True
            if changed:
                updated_names.append(cdu.short_name)

        existing_categories: set[str] = set()
        for limit in db.query(CDULimit).filter(CDULimit.cdu_id == cdu.id).all():
            normalized = normalize_limit_category(limit.instrument_category)
            if normalized and normalized != limit.instrument_category:
                limit.instrument_category = normalized
            if normalized:
                existing_categories.add(normalized)
        for category, (minimum, maximum) in DEFAULT_LIMITS.items():
            if category in existing_categories:
                continue
            db.add(CDULimit(
                cdu_id=cdu.id,
                instrument_category=category,
                min_limit_pct=minimum,
                max_limit_pct=maximum,
                hard_limit_pct=maximum,
                soft_limit_pct=maximum,
                valid_from=date.today(),
            ))
            limits_created += 1

    db.flush()
    return {
        "created": len(created_names),
        "updated": len(updated_names),
        "limits_created": limits_created,
        "created_names": created_names,
        "updated_names": updated_names,
        "total": db.query(CDU).count(),
    }
