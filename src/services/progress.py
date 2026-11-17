"""Where a learner is in a course."""

from __future__ import annotations

from src.services.courses import lo_display_title
from src.services.errors import InvalidInput
from src.services.models import LearningObjectiveMastery, ObjectiveMastery, ProgressSummary, WeekMastery


class ProgressService:
    def __init__(self, progress_bridge):
        self.bridge = progress_bridge

    def summary(self, username: str, course: str) -> ProgressSummary:
        data = self.bridge.get_progress_summary(username, course)
        if "error" in data:
            return ProgressSummary(course=course)
        return ProgressSummary(
            course=course,
            current_week=int(data.get("current_week", 1)),
            week_completion=float(data.get("week_completion", 0.0)),
            completed_gos=list(data.get("completed_gos", [])),
            total_gos=int(data.get("total_gos", 0)),
            ready_for_next_week=bool(data.get("ready_for_next_week", False)),
        )

    def current_week(self, username: str, course: str) -> int:
        return self.summary(username, course).current_week

    def week_mastery(self, username: str, course: str, week: int) -> WeekMastery:
        """Each objective's mastery against its own threshold, as week completion counts it."""
        kc_model = self.bridge.kc_model_provider(course) or {}
        week_data = kc_model.get("week_navigation", {}).get(f"week_{week:02d}")
        if not week_data:
            raise InvalidInput(f"{course} has no week {week}.")
        levels = self.bridge.mastery_summary(username, course).get("go_masteries", {})
        default = self.bridge.DEFAULT_GO_THRESHOLD
        los = []
        for lo in week_data.get("learning_objectives", []):
            items = []
            for go in lo.get("granular_objectives", []):
                level = levels.get(go["go_id"])
                level = float(level) if isinstance(level, (int, float)) else None
                threshold = float(go.get("mastery_threshold", default))
                items.append(ObjectiveMastery(go_id=go["go_id"], skill_name=go.get("skill_name", go["go_id"]),
                                              mastery=level, threshold=threshold,
                                              mastered=level is not None and level >= threshold))
            los.append(LearningObjectiveMastery(lo_id=lo["lo_id"], title=lo_display_title(lo), objectives=items))
        total = sum(len(lo.objectives) for lo in los)
        mastered = sum(o.mastered for lo in los for o in lo.objectives)
        return WeekMastery(course=course, week=week, completion=mastered / total if total else 0.0,
                           mastered_count=mastered, total=total, learning_objectives=los)
