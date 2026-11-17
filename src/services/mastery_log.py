"""What to write to the event log when a graded answer moves a learner's mastery.

Two event types, built from the learner's stored mastery before and after the answer:

``mastery_change``  every graded answer: the objective's level before and after, its threshold, whether it
                    is mastered, and the same for its learning objective (mastered when every objective
                    in it is at or above its own threshold).
``mastery_milestone``  only when an objective or learning objective crosses its threshold: ``mastered``
                    or ``lost``. The first ``mastered`` milestone for an id is when it was first reached.

The levels are logged as they were stored, so a learner profile can be rebuilt from the log without
re-running the mastery update rule.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from src.core.kc_ids import parent_ids

DEFAULT_THRESHOLD = 0.8  # the threshold used everywhere else for an objective without one


def lo_objectives(kc_model: Optional[Dict[str, Any]], lo_id: Optional[str]) -> List[Tuple[str, float]]:
    """``[(go_id, threshold), ...]`` for the objectives of one learning objective (empty if unknown)."""
    if not kc_model or not lo_id:
        return []
    for week in (kc_model.get("week_navigation") or {}).values():
        for lo in week.get("learning_objectives", []):
            if lo.get("lo_id") == lo_id:
                return [(go["go_id"], _threshold(go)) for go in lo.get("granular_objectives", [])]
    return []


def _threshold(go: Dict[str, Any]) -> float:
    value = go.get("mastery_threshold")
    return DEFAULT_THRESHOLD if value is None else float(value)


def _mastered(level: Optional[float], threshold: float) -> bool:
    return level is not None and level >= threshold


def mastery_events(go_id: str, before: Dict[str, float], after: Dict[str, float],
                   kc_model: Optional[Dict[str, Any]] = None) -> List[Tuple[str, Dict[str, Any]]]:
    """``[(event type, payload), ...]`` for one graded answer on ``go_id``."""
    lo_id, _ = parent_ids(go_id, kc_model)
    members = lo_objectives(kc_model, lo_id) or [(go_id, DEFAULT_THRESHOLD)]
    threshold = dict(members).get(go_id, DEFAULT_THRESHOLD)
    level_before, level_after = before.get(go_id), after.get(go_id)
    go_before, go_after = _mastered(level_before, threshold), _mastered(level_after, threshold)
    lo_before = all(_mastered(before.get(g), t) for g, t in members)
    lo_after = all(_mastered(after.get(g), t) for g, t in members)

    def rounded(value: Optional[float]) -> Optional[float]:
        return None if value is None else round(float(value), 4)

    events: List[Tuple[str, Dict[str, Any]]] = [("mastery_change", {
        "go": {"level_before": rounded(level_before), "level_after": rounded(level_after), "threshold": threshold,
               "mastered_before": go_before, "mastered_after": go_after},
        "lo": {"id": lo_id, "mastered_before": lo_before, "mastered_after": lo_after,
               "objectives_mastered": sum(_mastered(after.get(g), t) for g, t in members),
               "objectives_total": len(members)},
    })]
    if go_before != go_after:
        events.append(("mastery_milestone", {"scope": "go", "id": go_id, "event": "mastered" if go_after else "lost",
                                             "level": rounded(level_after), "threshold": threshold}))
    if lo_id and lo_before != lo_after:
        events.append(("mastery_milestone", {"scope": "lo", "id": lo_id, "event": "mastered" if lo_after else "lost",
                                             "objectives_mastered": events[0][1]["lo"]["objectives_mastered"],
                                             "objectives_total": len(members)}))
    return events
