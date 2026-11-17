"""Course structure (weeks, objectives) from the KC models."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List

from src.core.course_registry import CourseRegistry
from src.core.validation import course_code as valid_course_code
from src.services.errors import InvalidInput
from src.services.models import CourseOutline, LearningObjectiveInfo, WeekOutline

logger = logging.getLogger(__name__)


def lo_display_title(lo: Dict[str, Any]) -> str:
    """The name to show students for a learning objective.

    KC models keep the full objective as ``title`` (model prompts use it) and may carry a
    ``short_title`` for display. The model generator fills ``short_title`` by cutting the
    title to 50 characters plus "...", so a short title that is only that truncation is
    ignored in favour of the full title.
    """
    title = lo.get("title") or lo.get("objective_name") or "Learning Objective"
    short = (lo.get("short_title") or "").strip()
    if not short or (short.endswith("...") and title.startswith(short[:-3])):
        return title
    return short


class CourseService:
    def __init__(self, registry: CourseRegistry, kc_loader_factory: Callable[[str], Any]):
        self.registry = registry
        self._kc_loader_factory = kc_loader_factory
        self._loaders: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def available(self) -> List[str]:
        """Courses offered at registration: every course with a KC model."""
        return self.registry.available_courses()

    def kc_loader(self, course: str):
        try:
            course = valid_course_code(course)
        except ValueError as e:
            raise InvalidInput(str(e)) from None
        with self._lock:
            if course not in self._loaders:
                self._loaders[course] = self._kc_loader_factory(course)
            return self._loaders[course]

    def outline(self, course: str) -> CourseOutline:
        try:
            kc_model = self.kc_loader(course).load_course_model(course)
        except FileNotFoundError:
            raise InvalidInput(f"No course model for {course}.") from None
        weeks = []
        for week_data in kc_model.get("week_navigation", {}).values():
            number = int(week_data["week_number"])
            title = week_data.get("week_display") or (
                f"Week {number}: " + week_data.get("week_name", week_data.get("topic", f"Week {number}")))
            weeks.append(WeekOutline(number=number, title=title, learning_objectives=[
                LearningObjectiveInfo(
                    id=lo["lo_id"],
                    title=lo_display_title(lo),
                    concept_count=len(lo.get("granular_objectives", [])),
                )
                for lo in week_data.get("learning_objectives", [])
            ]))
        weeks.sort(key=lambda w: w.number)
        return CourseOutline(code=course, name=self.registry.profile(course).display_name, weeks=weeks)

    def week_objectives(self, course: str, week: int) -> List[Dict[str, Any]]:
        """The week's granular objectives in teaching order, as the tutor uses them."""
        try:
            week_content = self.kc_loader(course).get_week_content(course, week)
        except (FileNotFoundError, KeyError, ValueError):
            raise InvalidInput(f"{course} has no week {week}.") from None
        return [
            {"go_id": go.go_id, "skill_name": go.skill_name, "description": go.description,
             "content_keywords": go.content_keywords, "mastery_threshold": go.mastery_threshold}
            for lo in week_content.learning_objectives for go in lo.granular_objectives
        ]
