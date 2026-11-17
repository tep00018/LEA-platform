"""Quiz mode: one question per objective in the week, generated adaptively and graded.

A learner has at most one quiz at a time. Its state lives in the session store, so the
quiz survives a page refresh and can be driven by any client. Flow:

    start -> [answer -> next]* -> completed      (or end() at any point)

``answer`` grades, records the result and shows feedback; ``next`` generates the next
question. When the quiz ends, the learner moves to the next week if a graded answer in this
quiz completed the current one.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from src.services.errors import InvalidInput, NoActiveSession, Unavailable, WrongState
from src.services.learning import LearningService
from src.services.models import AnswerFeedback, QuizState
from src.services.session_store import SessionStore

logger = logging.getLogger(__name__)

MAX_ANSWER_CHARS = 4000


class QuizService:
    KIND = "quiz"

    def __init__(self, quiz_system, learning: LearningService, store: SessionStore):
        self.quiz_system = quiz_system
        self.learning = learning
        self.store = store

    # ------------------------------------------------------------------ reads

    def current(self, username: str) -> Optional[QuizState]:
        return self.store.load(QuizState, self.KIND, username)

    def _require(self, username: str) -> QuizState:
        state = self.current(username)
        if state is None:
            raise NoActiveSession("There's no quiz in progress. Start a new quiz.")
        return state

    # ------------------------------------------------------------------ actions

    def start(self, username: str, course: str, week: int) -> QuizState:
        """Start a quiz on the week, or return the one already in progress for it."""
        with self.store.locked(self.KIND, username):
            existing = self.current(username)
            if existing and existing.status != "completed":
                if (existing.course, existing.week) == (course, week):
                    return existing
                # Replacing an unfinished quiz on another week: it ends here, so a week it
                # completed still counts.
                self._finish(username, existing)

            started_at = datetime.now().isoformat()
            learner = self.learning.assess(username, course, week, "quiz", "Starting quiz", {
                "username": username, "course": course, "week": week, "current_mode": "quiz",
                "session_start_time": started_at,
                "interaction_count": 0, "quiz_starting": True,
            })
            data = self.quiz_system.start_quiz(course=course, week=week, username=username,
                                               orchestrator_context=learner.as_context())
            if not data:
                raise Unavailable("The quiz couldn't be prepared. Please try again.")
            state = QuizState.model_validate({**data, "start_time": started_at})
            self.store.save(state, self.KIND, username)
            self.learning.events.learner(username, course, "quiz_start", mode="quiz", week=week,
                                         payload={"quiz_id": state.quiz_id, "questions": state.total})
            logger.info(f"Quiz {state.quiz_id} started: {state.total} questions")
            return state

    def answer(self, username: str, answer: str, timing: Optional[Dict[str, Any]] = None) -> QuizState:
        """Grade the answer to the current question, record it and show feedback."""
        answer = (answer or "").strip()
        if not answer:
            raise InvalidInput("Enter an answer first.")
        if len(answer) > MAX_ANSWER_CHARS:
            raise InvalidInput(f"Please keep answers under {MAX_ANSWER_CHARS} characters.")
        with self.store.locked(self.KIND, username):
            state = self._require(username)
            if state.status != "question":
                raise WrongState("This question has already been answered.")
            question = state.current_question or {}

            learner = self.learning.assess(username, state.course, state.week, "quiz", answer,
                                           {**self._context(state, answer), **({"timing": timing} if timing else {})})
            # The newest assessment guides the questions that follow.
            state.orchestrator_context = learner.as_context()

            data = state.quiz_data()
            result = self.quiz_system.submit_answer(data, answer)
            if not result:
                raise Unavailable("Your answer couldn't be checked. Please submit it again.")
            # Build the new state before recording, so nothing can fail between recording
            # the answer and saving the state that shows it was answered.
            state = QuizState.model_validate({**data, "status": "feedback"})
            feedback = AnswerFeedback.model_validate({
                **result, "go_id": question.get("go_id"), "question_type": question.get("type"),
                "your_answer": answer,
            })
            state.results.append(feedback)
            state.feedback = feedback

            preview = self.learning.is_preview(username)
            mastery_before = self.learning.go_mastery(username, state.course, question.get("go_id")) if preview else None
            outcome = self.learning.record(
                username, state.course, state.week, mode="quiz", go_id=question.get("go_id"),
                result=result, question_type=question.get("type"), student_response=answer,
                details={
                    "quiz_id": state.quiz_id, "question_number": len(state.results),
                    "question": str(question.get("text", ""))[:2000],
                    "options": question.get("options"),
                    "expected_answer": question.get("correct_answer"),
                },
            )
            feedback.achievements = outcome.achievements
            state.week_ready = state.week_ready or outcome.week_ready
            self.store.save(state, self.KIND, username)
            if preview:
                from src.services.preview import learner_summary

                self.learning.explain(username, state.course, {
                    "mode": "quiz", "go_id": question.get("go_id"), "objective": question.get("skill_name"),
                    "question": str(question.get("text", ""))[:300], "question_type": question.get("type"),
                    "mastery_before": mastery_before,
                    "mastery_after": self.learning.go_mastery(username, state.course, question.get("go_id")),
                    "graded": feedback.graded, "correct": feedback.correct, "score": feedback.score,
                    "learner": learner_summary(learner), "sources": [],
                })
            return state

    def next(self, username: str) -> QuizState:
        """Move on from feedback to the next question, or finish the quiz."""
        with self.store.locked(self.KIND, username):
            state = self._require(username)
            if state.status == "completed":
                return state
            if state.status != "feedback":
                raise WrongState("Answer the current question first.")
            data = self.quiz_system.get_next_question(state.quiz_data())
            if data is None:
                return self._finish(username, state)
            state = QuizState.model_validate({**data, "status": "question", "feedback": None})
            self.store.save(state, self.KIND, username)
            return state

    def end(self, username: str) -> Optional[QuizState]:
        """End the quiz early; the results so far stand."""
        with self.store.locked(self.KIND, username):
            state = self.current(username)
            if state is None or state.status == "completed":
                return state
            return self._finish(username, state)

    def discard(self, username: str) -> None:
        """Forget the quiz (after the results are shown, or when the learner leaves it)."""
        with self.store.locked(self.KIND, username):
            self.store.delete(self.KIND, username)

    # ------------------------------------------------------------------ helpers

    def _finish(self, username: str, state: QuizState) -> QuizState:
        state.status = "completed"
        state.feedback = None
        if state.week_ready:
            state.advanced_to_week = self.learning.advance_week_if_ready(username, state.course, state.week)
        self.store.save(state, self.KIND, username)
        self.learning.events.learner(username, state.course, "quiz_end", mode="quiz", week=state.week, payload={
            "quiz_id": state.quiz_id, "questions": state.total, "answered": len(state.results),
            "graded": state.graded_count, "correct": state.correct_count,
            "advanced_to_week": state.advanced_to_week,
        })
        logger.info(f"Quiz {state.quiz_id} finished: {state.correct_count}/{state.graded_count} correct")
        return state

    @staticmethod
    def _context(state: QuizState, answer: str) -> Dict[str, Any]:
        return {
            "quiz_data": state.quiz_data(),
            "current_mode": "quiz",
            "selected_week": state.week,
            "question_number": state.position,
            "total_questions": state.total,
            "current_score": state.correct_count,
            "quiz_history": [r.model_dump() for r in state.results],
            "student_answer": answer,
            "course": state.course,
            "username": state.username,
            "session_start_time": state.start_time or datetime.now().isoformat(),
            "interaction_count": state.position,
            "completion_progress": state.position / max(1, state.total),
            "completed_questions": len(state.results),
            "current_go_id": (state.current_question or {}).get("go_id"),
        }
