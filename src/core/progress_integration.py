# File: src/core/progress_integration.py
"""Week progress derived from mastery.

Week completion is recomputed from scratch on every update: the share of the week's
granular objectives (from the KC model) whose mastery has reached that objective's own
``mastery_threshold``. Because it is a recomputation rather than an increment, repeated
calls cannot inflate it, and it goes down if mastery drops.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from src.core.kc_ids import gos_for_week
from src.storage.locks import redis_lock

logger = logging.getLogger(__name__)

KCModelProvider = Callable[[str], Optional[Dict[str, Any]]]


class ProgressIntegrationBridge:
    DEFAULT_GO_THRESHOLD = 0.8       # used when a GO has no mastery_threshold in the KC model
    WEEK_COMPLETION_THRESHOLD = 0.75  # share of a week's GOs mastered to be ready to move on

    def __init__(self, redis_client, mastery_tracker, kc_model_provider: Optional[KCModelProvider] = None):
        self.redis_client = redis_client
        self.mastery_tracker = mastery_tracker
        if kc_model_provider is None:
            from src.core.course_registry import default_registry

            kc_model_provider = default_registry().kc_model
        self.kc_model_provider = kc_model_provider

    # ------------------------------------------------------------------ calculations

    def mastery_summary(self, username: str, course: str) -> Dict[str, Any]:
        return self.mastery_tracker.get_mastery_summary(username, course)

    def week_status(self, mastery_summary: Dict[str, Any], course: str, week: int) -> Dict[str, Any]:
        kc_model = self.kc_model_provider(course) or {}
        week_gos = gos_for_week(kc_model, week)
        go_masteries = mastery_summary.get("go_masteries", {})

        completed: List[str] = []
        for go in week_gos:
            level = go_masteries.get(go["go_id"])
            if isinstance(level, (int, float)) and level >= go.get("mastery_threshold", self.DEFAULT_GO_THRESHOLD):
                completed.append(go["go_id"])

        total = len(week_gos)
        completion = len(completed) / total if total else 0.0
        return {
            "week": week,
            "total_gos": total,
            "completed_gos": completed,
            "completion": completion,
            "week_mastery": mastery_summary.get("week_masteries", {}).get(week, 0.0),
            "ready_for_next_week": total > 0 and completion >= self.WEEK_COMPLETION_THRESHOLD,
        }

    # ------------------------------------------------------------------ updates

    def refresh_week_progress(
        self, username: str, course: str, week: int, mastery_summary: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Recompute and store the week's completion. Never advances the week."""
        try:
            with redis_lock(self.redis_client, f"progress:{username}:{course}"):
                # Read mastery inside the lock, so an older reading can't overwrite a newer one.
                summary = mastery_summary if mastery_summary is not None else self.mastery_summary(username, course)
                status = self.week_status(summary, course, week)
                return self._store_week_status(username, course, week, status)
        except Exception as e:
            logger.error(f"Progress refresh failed for {username}/{course} week {week}: {e}")
            return {"progress_updated": False, "error": str(e)}

    def _store_week_status(self, username: str, course: str, week: int, status: Dict[str, Any]) -> Dict[str, Any]:
        progress = self.redis_client.get_user_progress(username).get(course, {})
        on_this_week = progress.get("week", week) == week
        previous_completion = progress.get("completion", 0.0) if on_this_week else 0.0
        previous_completed = set(progress.get("completed_gos", [])) if on_this_week else set()
        if on_this_week:
            # Only the learner's current week is stored; practising another week changes nothing.
            self._write_progress(username, course, {
                **progress, "week": week, "completion": status["completion"],
                "completed_gos": status["completed_gos"],
            })

        newly = [go for go in status["completed_gos"] if go not in previous_completed]
        return {
            "progress_updated": True,
            "completion": status["completion"],
            "completion_change": status["completion"] - previous_completion,
            "completed_gos": status["completed_gos"],
            "newly_completed_gos": newly,
            "total_gos": status["total_gos"],
            "achievements": [f"Mastered {go}" for go in newly],
            "week_advancement_ready": status["ready_for_next_week"],
            "next_week": week + 1 if status["ready_for_next_week"] else None,
        }

    def advance_week_if_ready(self, username: str, course: str, week: int) -> Dict[str, Any]:
        """Move the learner to the next week if this week is complete and they are still on it."""
        status = self.week_status(self.mastery_summary(username, course), course, week)
        if not status["ready_for_next_week"]:
            return {"advanced": False, "completion": status["completion"]}

        kc_model = self.kc_model_provider(course) or {}
        total_weeks = kc_model.get("course_info", {}).get("total_weeks") or len(kc_model.get("week_navigation", {}))
        next_week = week + 1
        with redis_lock(self.redis_client, f"progress:{username}:{course}"):
            current = self.redis_client.get_user_progress(username).get(course, {}).get("week", 1)
            if current > week or (total_weeks and week >= total_weeks):
                return {"advanced": False, "completion": status["completion"]}
            self.redis_client.update_user_progress(username=username, course=course, week=next_week, completion=0.0)
        logger.info(f"Advanced {username} in {course} to week {next_week}")
        return {"advanced": True, "next_week": next_week, "completion": status["completion"]}

    def _write_progress(self, username: str, course: str, progress: Dict[str, Any]) -> None:
        progress = {**progress, "last_updated": datetime.now().isoformat()}
        self.redis_client.get_redis().hset(f"progress:{username}", course, json.dumps(progress))

    # ------------------------------------------------------------------ read models

    def get_progress_summary(self, username: str, course: str) -> Dict[str, Any]:
        try:
            course_progress = self.redis_client.get_user_progress(username).get(course, {})
            current_week = course_progress.get("week", 1)
            summary = self.mastery_summary(username, course)
            status = self.week_status(summary, course, current_week)
            return {
                "current_week": current_week,
                "week_completion": status["completion"],
                "completed_gos": status["completed_gos"],
                "total_gos": status["total_gos"],
                "last_updated": course_progress.get("last_updated", ""),
                "week_masteries": summary.get("week_masteries", {}),
                "go_masteries": summary.get("go_masteries", {}),
                "total_interactions": summary.get("total_interactions", 0),
                "ready_for_next_week": status["ready_for_next_week"],
            }
        except Exception as e:
            logger.error(f"Failed to get progress summary: {e}")
            return {"error": str(e)}
