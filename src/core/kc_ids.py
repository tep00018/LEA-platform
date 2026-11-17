"""Resolve Knowledge Component relationships (GO -> LO -> week).

KC models carry a ``quick_lookup`` section (``go_by_id``, ``week_by_lo_id``) that is the
source of truth. When a model is unavailable, IDs are parsed from the naming scheme the
onboarding pipeline generates: ``GO_<week>_<lo>_<n>`` and ``LO_<week>_<lo>``.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Tuple

_GO_PATTERN = re.compile(r"^GO_(\d{2})_(\d{2})_\d+$")
_LO_PATTERN = re.compile(r"^LO_(\d{2})_(\d{2})$")


def parent_ids(go_id: str, kc_model: Optional[dict[str, Any]] = None) -> Tuple[Optional[str], Optional[int]]:
    """Return ``(lo_id, week_number)`` for a granular objective, or ``(None, None)``."""
    if kc_model:
        lookup = kc_model.get("quick_lookup", {})
        go = lookup.get("go_by_id", {}).get(go_id)
        if go and go.get("parent_lo_id"):
            lo_id = go["parent_lo_id"]
            week = lookup.get("week_by_lo_id", {}).get(lo_id, {}).get("week_number")
            if week is None:
                week = week_of_lo(lo_id)
            return lo_id, week
    match = _GO_PATTERN.match(go_id or "")
    if match:
        week, lo = match.groups()
        return f"LO_{week}_{lo}", int(week)
    return None, None


def week_of_lo(lo_id: str) -> Optional[int]:
    match = _LO_PATTERN.match(lo_id or "")
    return int(match.group(1)) if match else None


def go_in_week(go_id: str, week: int, kc_model: Optional[dict[str, Any]] = None) -> bool:
    """True if the GO belongs to ``week`` (exact match, never a substring test)."""
    _, go_week = parent_ids(go_id, kc_model)
    return go_week == week


def gos_for_week(kc_model: dict[str, Any], week: int) -> list[dict[str, Any]]:
    """All granular objectives of a week, in KC-model order."""
    week_data = kc_model.get("week_navigation", {}).get(f"week_{week:02d}", {})
    return [go for lo in week_data.get("learning_objectives", []) for go in lo.get("granular_objectives", [])]
