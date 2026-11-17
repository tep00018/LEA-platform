"""The adaptive loop shared by Quiz and Tutor: assess the learner, then record graded answers.

Assessment (orchestrator) happens before content is generated for a learner turn; recording
happens after the answer is graded. Recording updates the evidence list, mastery and the
week's progress, in that order. Both are also written to the durable event log.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.core.agent_orchestrator_mcp import InteractionType
from src.core.research_logs import log_motivation_metrics
from src.services.events import EventRecorder, disabled
from src.services.mastery_log import mastery_events
from src.services.models import LearnerState, RecordOutcome

logger = logging.getLogger(__name__)

INTERACTION_TYPES = {
    "quiz": InteractionType.QUIZ_ANSWER,
    "tutor": InteractionType.TUTOR_RESPONSE,
    "chat": InteractionType.CHAT_QUERY,
}


class LearningService:
    def __init__(self, orchestrator, progress_bridge, data_dir=None, events: EventRecorder | None = None):
        self.orchestrator = orchestrator
        self.progress = progress_bridge
        self._data_dir = data_dir
        self.events = events or disabled()
        self.preview = None  # PreviewService: explanations of a teacher's preview turns

    def assess(self, username: str, course: str, week: int, mode: str, student_input: str,
               session_context: Dict[str, Any]) -> LearnerState:
        """Run the orchestrator for one learner turn and log the motivation metrics.

        Never raises: if the assessment fails the orchestrator's neutral fallback state is
        returned (``processing_successful`` False), exactly as the Streamlit app did before.
        """
        try:
            result = self.orchestrator.process_interaction(
                username=username, course=course, interaction_type=INTERACTION_TYPES[mode],
                student_input=student_input, current_mode=mode, session_context=session_context,
            )
        except Exception as e:
            logger.error(f"Learner assessment failed for {username}/{course}: {e}")
            result = self.orchestrator._get_fallback_response(mode)
        state = LearnerState.from_orchestrator(result)
        if state.processing_successful:
            if not self.events.is_test(username):
                log_motivation_metrics(state.as_context(), username, course, week, mode, data_dir=self._data_dir)
            self.events.learner(username, course, "learner_state", mode=mode, week=week, payload={
                "motivation_state": state.motivation_state,
                "motivation_metrics": state.motivation_metrics,
                "cognitive_state": state.cognitive_state,
                "scaffolding_strategy": state.scaffolding_strategy,
            })
        return state

    def record(self, username: str, course: str, week: int, *, mode: str, go_id: Optional[str],
               result: Dict[str, Any], question_type: Optional[str] = None,
               student_response: str = "", details: Optional[Dict[str, Any]] = None) -> RecordOutcome:
        """Record one answer. Ungraded results (grading failed, or the tutor's diagnostic
        opener) are kept as attempts but change neither mastery nor ZPD. ``details`` go
        only to the event log (which question, the expected answer, and so on)."""
        graded = bool(result.get("graded", False)) and result.get("correct") is not None
        self.events.learner(
            username, course, "answer", mode=mode, week=week, go_id=go_id,
            correct=result.get("correct") if graded else None,
            score=result.get("score") if graded else None, question_type=question_type,
            payload={"graded": graded, "response": self.events.scrub(student_response, username),
                     **(details or {})},
        )
        track = graded and bool(go_id)
        before = self.go_masteries(username, course) if track else {}
        try:
            self.orchestrator.record_graded_response(
                username, course, mode=mode, go_id=go_id,
                correct=result.get("correct") if graded else None,
                score=result.get("score") if graded else None,
                question_type=question_type, student_response=student_response,
                weight=result.get("weight") if graded else None,
            )
        except Exception as e:
            logger.error(f"Recording graded {mode} answer failed for {username}/{course}: {e}")
            return RecordOutcome(recorded=False)
        if not graded:
            return RecordOutcome(recorded=True)
        if track:
            self._log_mastery(username, course, week, mode, go_id, before)

        progress = self.progress.refresh_week_progress(username, course, week)
        return RecordOutcome(
            recorded=True,
            achievements=list(progress.get("achievements", [])),
            week_ready=bool(progress.get("week_advancement_ready")),
        )

    def _log_mastery(self, username: str, course: str, week: int, mode: str, go_id: str,
                     before: Dict[str, float]) -> None:
        """Write the mastery change this graded answer caused (see ``mastery_log``). Never raises."""
        try:
            after = self.go_masteries(username, course)
            kc_model = self.progress.kc_model_provider(course)
            for event_type, payload in mastery_events(go_id, before, after, kc_model):
                self.events.learner(username, course, event_type, mode=mode, week=week, go_id=go_id, payload=payload)
        except Exception as e:
            logger.warning(f"Mastery change not logged for {username}/{course}/{go_id}: {e}")

    def advance_week_if_ready(self, username: str, course: str, week: int) -> Optional[int]:
        """Move the learner on if the week is complete; returns the new week or None."""
        try:
            outcome = self.progress.advance_week_if_ready(username, course, week)
        except Exception as e:
            logger.error(f"Week advancement check failed for {username}/{course}: {e}")
            return None
        return outcome.get("next_week") if outcome.get("advanced") else None

    def course_content(self, course: str, query: str, max_results: int = 3) -> str:
        """Retrieved course material for a prompt; empty when nothing can be retrieved, so an
        error message never ends up inside a prompt (the failure is logged)."""
        return self.course_content_with_sources(course, query, max_results)[0]

    def course_content_with_sources(self, course: str, query: str, max_results: int = 3):
        """``course_content`` and the sources it came from ({source, excerpt})."""
        result = self.orchestrator.mcp_client.get_course_content_via_rag(
            query=query, course=course, max_results=max_results)
        if not result.get("success"):
            logger.warning(f"Course content retrieval failed for {course}: {result.get('error')}")
            return "", []
        return result.get("content", ""), result.get("sources", [])

    # ------------------------------------------------------------------ teacher preview

    def is_preview(self, username: str) -> bool:
        return self.preview is not None and self.preview.is_preview(username)

    def go_mastery(self, username: str, course: str, go_id: Optional[str]) -> Optional[float]:
        """A learner's stored mastery on one objective (for the preview explanation)."""
        if not go_id:
            return None
        try:
            import json

            raw = self.orchestrator.redis_client.get_redis().get(f"mastery:{username}:{course}")
            value = (json.loads(raw) if raw else {}).get("go_masteries", {}).get(go_id)
            return value.get("level") if isinstance(value, dict) else value
        except Exception:
            return None

    def go_masteries(self, username: str, course: str) -> Dict[str, float]:
        """Stored mastery level for every objective the learner has evidence on (empty if none
        or unreadable)."""
        try:
            import json

            raw = self.orchestrator.redis_client.get_redis().get(f"mastery:{username}:{course}")
            stored = (json.loads(raw) if raw else {}).get("go_masteries", {})
            return {go: (v.get("level") if isinstance(v, dict) else v) for go, v in stored.items()
                    if (v.get("level") if isinstance(v, dict) else v) is not None}
        except Exception:
            return {}

    def explain(self, username: str, course: str, turn: Dict[str, Any]) -> None:
        if self.preview is not None:
            try:
                self.preview.record(username, course, turn)
            except Exception as e:
                logger.warning(f"Preview explanation not recorded: {e}")
