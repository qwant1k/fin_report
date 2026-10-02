"""Limit-checking utilities."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional, Tuple

from .constants import DEFAULT_LIMITS


@dataclass
class LimitSpec:
    """A limit of the reference book: policy range plus hard/soft ceilings."""
    min_pct: float
    max_pct: float
    hard_pct: float
    soft_pct: float
    source: str = "reference"
    valid_from: Optional[date] = None


def check_limit_spec(value_pct: float, spec: LimitSpec, eps: float = 1e-9) -> Tuple[str, str]:
    """(hard, soft): hard — outside [min; hard ceiling], soft — above the soft
    (early-warning) ceiling or below the minimum."""
    below = value_pct < spec.min_pct - eps
    hard = "breach" if below or value_pct > spec.hard_pct + eps else "ok"
    soft = "breach" if below or value_pct > spec.soft_pct + eps else "ok"
    return hard, soft


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
