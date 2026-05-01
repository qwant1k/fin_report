"""Limit-checking utilities."""
from __future__ import annotations

from typing import Dict, Tuple

from .constants import DEFAULT_LIMITS


def check_limit_status(value_pct: float, min_limit: float, max_limit: float) -> Tuple[str, str]:
    """Return (hard_status, soft_status) ∈ {'ok','breach'} pair."""
    in_range = min_limit <= value_pct <= max_limit
    return ("ok" if in_range else "breach", "ok" if in_range else "breach")


def check_limits(category_pct: Dict[str, float], limits: Dict[str, Tuple[float, float]] | None = None) -> Dict[str, str]:
    """Vector check across categories. Returns category → 'ok'|'breach'."""
    limits = limits or DEFAULT_LIMITS
    out: Dict[str, str] = {}
    for cat, pct in category_pct.items():
        mn, mx = limits.get(cat, (0.0, 1.0))
        out[cat], _ = check_limit_status(pct, mn, mx)
    return out
