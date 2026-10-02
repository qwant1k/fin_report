"""One place to find a manager (ЧДУ) by any of its identifiers.

Files name managers in many ways: KASE member codes (HALFN, KIBAM, CAIFC,
DRBES, UDCAP …), the canonical seed name, a legal name typed by a user in
«Настройки» («АО "Сентрас Секьюритиз"»), Cyrillic spelling in the Risk Report.
Lookups by the exact ``CDU.name`` silently lost data as soon as a manager was
renamed, so every importer goes through this module.
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.db_models import CDU
from services.calculator.constants import normalize_cdu_name


def _prefix_canonical(prefix: Optional[str]) -> Optional[str]:
    if not prefix:
        return None
    from services.parser.classification import DEFAULT_CDU_PREFIXES
    name = DEFAULT_CDU_PREFIXES.get(str(prefix).upper())
    return normalize_cdu_name(name) or name if name else normalize_cdu_name(prefix)


def canonical_of(cdu: CDU) -> Optional[str]:
    """Canonical (seed) name of a manager row, whatever it is called now."""
    return (
        normalize_cdu_name(cdu.name)
        or normalize_cdu_name(cdu.short_name)
        or _prefix_canonical(cdu.participant_code_prefix)
    )


def _prefix_group(canonical: str) -> set[str]:
    from services.parser.classification import DEFAULT_CDU_PREFIXES
    return {p.upper() for p, n in DEFAULT_CDU_PREFIXES.items()
            if (normalize_cdu_name(n) or n) == canonical}


def find_cdu(
    db: Session,
    *,
    name: Optional[str] = None,
    prefix: Optional[str] = None,
    include_inactive: bool = False,
) -> Optional[CDU]:
    """Resolve a manager by KASE prefix and/or any spelling of its name."""
    rows: Iterable[CDU] = db.execute(select(CDU).order_by(CDU.id)).scalars().all()
    if not include_inactive:
        active = [c for c in rows if c.is_active]
        rows = active or list(rows)
    rows = list(rows)

    if prefix:
        up = str(prefix).upper()
        for c in rows:
            if (c.participant_code_prefix or "").upper() == up:
                return c
    targets = []
    if prefix:
        targets.append(_prefix_canonical(prefix))
    if name:
        exact = [c for c in rows if c.name == name or c.short_name == name]
        if exact:
            return exact[0]
        targets.append(normalize_cdu_name(name))
    for canonical in [t for t in targets if t]:
        group = _prefix_group(canonical)
        for c in rows:
            if canonical_of(c) == canonical:
                return c
            if (c.participant_code_prefix or "").upper() in group:
                return c
    return None


def cdu_name_map(db: Session) -> Dict[str, int]:
    """{name → id} accepting both the current and the canonical name."""
    out: Dict[str, int] = {}
    canon_count: Dict[str, int] = {}
    rows = db.execute(select(CDU).order_by(CDU.id)).scalars().all()
    for c in rows:
        canonical = canonical_of(c)
        if canonical:
            canon_count[canonical] = canon_count.get(canonical, 0) + 1
    for c in rows:
        out[c.name] = c.id
        canonical = canonical_of(c)
        if canonical and canon_count.get(canonical) == 1:
            out.setdefault(canonical, c.id)
    return out


def resolve_name_id(cdu_map: Dict[str, int], name: Optional[str]) -> Optional[int]:
    if not name:
        return None
    if name in cdu_map:
        return cdu_map[name]
    canonical = normalize_cdu_name(name)
    return cdu_map.get(canonical) if canonical else None
