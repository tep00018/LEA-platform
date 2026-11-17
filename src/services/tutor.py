"""Tutor mode: a guided conversation through the week's objectives, one at a time.

A learner has at most one tutor session. Each reply is assessed (orchestrator), graded
against the current objective, recorded, and answered with scaffolding chosen for the
learner. When the session finishes or is ended, the learner moves to the next week if a
graded reply in the session completed the current one.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from src.services.courses import CourseService
from src.services.errors import InvalidInput, NoActiveSession, Unavailable
from src.services.learning import LearningService
from src.services.models import LearnerState, QuizState, TutorReply, TutorState
from src.services.session_store import SessionStore

logger = logging.getLogger(__name__)

MAX_REPLY_CHARS = 4000


def _clip(text: Any, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


DEFAULT_MASTERY_THRESHOLD = 0.8  # the tutor's own default for an objective with no threshold


def select_objectives(go_list: List[Dict[str, Any]], mastery: Dict[str, float],
                      missed_go_ids: Iterable[Optional[str]] = ()) -> Tuple[List[Dict[str, Any]], str]:
    """The week's objectives a session should teach, in week order, and why.

    ``quiz_missed``: after a quiz, only the objectives it got wrong. ``unmastered``: otherwise,
    the objectives below their mastery threshold. ``all_mastered``: nothing left to teach, so the
    list is empty and the caller should ask whether a refresher is wanted rather than repeat
    the tutorial."""
    missed = {go for go in missed_go_ids if go}
    if missed:
        chosen = [go for go in go_list if go["go_id"] in missed]
        if chosen:
            return chosen, "quiz_missed"
    chosen = []
    for go in go_list:
        threshold = go.get("mastery_threshold")
        threshold = DEFAULT_MASTERY_THRESHOLD if threshold is None else threshold
        if (mastery.get(go["go_id"]) or 0.0) < threshold:
            chosen.append(go)
    return chosen, ("unmastered" if chosen else "all_mastered")


def quiz_review(quiz: QuizState, go_list: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Notes on a finished quiz for the tutor's prompt, and the opening line of the review
    session. Uses the quiz's stored results as they are; nothing is re-graded."""
    skills = {go.get("go_id"): go.get("skill_name") or go.get("go_id") for go in go_list}
    missed, right, ungraded = [], [], []
    for i, result in enumerate(quiz.results):
        record = quiz.answers[i] if i < len(quiz.answers) else {}
        question = _clip(record.get("question"), 300) or "(question text not kept)"
        skill = skills.get(result.go_id) or result.go_id or "this week's material"
        if not result.graded:
            ungraded.append(f"- {question} (objective: {skill})")
        elif result.correct:
            right.append(f"- {question} (objective: {skill})")
        else:
            expected = result.expected_answer or record.get("correct_answer")
            line = f"- {question} (objective: {skill}). Their answer: {_clip(result.your_answer, 300)}"
            if expected:
                line += f". Correct answer: {_clip(expected, 200)}"
            if result.explanation:
                line += f". Feedback they were given: {_clip(result.explanation, 400)}"
            missed.append((skill, line))

    graded = len(right) + len(missed)
    notes = [f"Week {quiz.week} quiz: {len(right)} of {graded} graded answers correct."]
    if missed:
        notes += ["Missed:"] + [line for _, line in missed]
    if right:
        notes += ["Answered correctly:"] + right
    if ungraded:
        notes += ["Not graded:"] + ungraded
    if not missed:
        notes.append("They missed nothing, so go a little deeper than usual rather than reviewing basics.")

    if missed:
        topics = list(dict.fromkeys(skill for skill, _ in missed))
        named = ", ".join(f"**{t}**" for t in topics[:3]) + (" and more" if len(topics) > 3 else "")
        intro = (f"Let's go over your Week {quiz.week} quiz. You got {len(right)} of {graded} right. "
                 f"The ones to work on were about {named}, so we'll go through just those.")
    elif graded:
        intro = (f"Nice work on your Week {quiz.week} quiz: {len(right)} of {graded} right. "
                 f"Let's go a little deeper this time.")
    else:
        intro = f"Let's go over your Week {quiz.week} quiz."
    return "\n".join(notes), intro


class TutorService:
    KIND = "tutor"

    def __init__(self, tutor_system, learning: LearningService, courses: CourseService, store: SessionStore):
        self.tutor_system = tutor_system
        self.learning = learning
        self.courses = courses
        self.store = store

    def current(self, username: str) -> Optional[TutorState]:
        return self.store.load(TutorState, self.KIND, username)

    def start(self, username: str, course: str, week: int, quiz: Optional[QuizState] = None) -> TutorState:
        """Start a session on the week, or return the one already running for it. With a
        finished ``quiz`` on the same week, always start a fresh session that reviews it."""
        if quiz is not None and (quiz.status != "completed" or (quiz.course, quiz.week) != (course, week)):
            quiz = None
        with self.store.locked(self.KIND, username):
            existing = self.current(username)
            if existing and not existing.completed:
                if (existing.session.course, existing.session.week) == (course, week) and quiz is None:
                    return existing
                # Replacing an unfinished session on another week: a week it completed still counts.
                self._advance_if_ready(username, existing)

            go_list = self.courses.week_objectives(course, week)
            if not go_list:
                raise InvalidInput("No learning objectives found for this week.")
            learner = self.learning.assess(username, course, week, "tutor", "Starting tutor session", {
                "username": username, "course": course, "week": week,
                "session_start_time": datetime.now().isoformat(),
                "tutor_starting": True, "interaction_count": 0, "current_mode": "tutor",
            })
            notes, intro = quiz_review(quiz, go_list) if quiz is not None else (None, None)
            missed = [r.go_id for r in quiz.results if r.graded and not r.correct] if quiz is not None else []
            teach, selection = select_objectives(go_list, self.learning.go_masteries(username, course), missed)
            if selection == "all_mastered":
                state = self._mastered_state(username, course, week, go_list, learner, quiz)
            else:
                session = self.tutor_system.start_tutoring_session(
                    course=course, week=week, username=username, go_list=teach,
                    orchestrator_context=learner.as_context(), quiz_review=notes, review_intro=intro,
                    adaptive_start=False,
                )
                if session is None:
                    raise Unavailable("The tutoring session couldn't start. Please try again.")
                state = TutorState(session=session)
            session = state.session
            self._snapshot_debug_fields(state, learner, username, course)
            self.store.save(state, self.KIND, username)
            self.learning.events.learner(username, course, "tutor_start", mode="tutor", week=week, payload={
                "session_id": session.session_id, "objectives": len(session.go_list),
                "start_index": session.current_go_index, "quiz_review": bool(notes),
                "selection": selection, "week_objectives": len(go_list),
                "skipped_objectives": len(go_list) - len(teach),
                "scaffolding_strategy": session.scaffolding_strategy,
                "scaffolding_intensity": session.scaffolding_intensity,
            })
            return state

    def _mastered_state(self, username: str, course: str, week: int, go_list: List[Dict[str, Any]],
                        learner: LearnerState, quiz: Optional[QuizState]) -> TutorState:
        """Every objective this week is already mastered. Instead of teaching it again, start a
        session that is already complete and says so, and move the learner on as finishing the
        tutorial would have."""
        session = self.tutor_system.start_tutoring_session(
            course=course, week=week, username=username, go_list=go_list,
            orchestrator_context=learner.as_context(), adaptive_start=False,
        )
        if session is None:
            raise Unavailable("The tutoring session couldn't start. Please try again.")
        session.current_go_index = len(session.go_list)
        state = TutorState(session=session, completed=True, week_ready=True)
        state.advanced_to_week = self.learning.advance_week_if_ready(username, course, week)
        opening = (f"You've mastered every concept in Week {week}, and your quiz went well."
                   if quiz is not None else f"You've already mastered every concept in Week {week}.")
        message = (f"{opening} There's no need to repeat the tutorial. "
                   f"Do you want a refresher, or is it safe to move on?")
        if state.advanced_to_week:
            message += f" Week {state.advanced_to_week} is now open."
        message += f" For a refresher, take the Week {week} quiz and I'll go over anything you miss."
        session.conversation_history = [{
            "role": "tutor", "content": message, "timestamp": datetime.now().isoformat(), "go_id": None,
            "scaffolding_strategy": session.scaffolding_strategy,
            "scaffolding_intensity": session.scaffolding_intensity,
        }]
        return state

    def respond(self, username: str, text: str, on_token: Optional[Callable[[str], None]] = None,
                timing: Optional[Dict[str, Any]] = None) -> TutorReply:
        """Grade and answer the learner's reply. With ``on_token`` the tutor's answer is
        streamed piece by piece; ``TutorReply.message`` is always the full final text."""
        text = (text or "").strip()
        if not text:
            raise InvalidInput("Type a reply first.")
        if len(text) > MAX_REPLY_CHARS:
            raise InvalidInput(f"Please keep replies under {MAX_REPLY_CHARS} characters.")
        with self.store.locked(self.KIND, username):
            state = self.current(username)
            if state is None:
                raise NoActiveSession("There's no tutoring session in progress. Start one first.")
            session = state.session
            if state.completed or session.current_go_index >= len(session.go_list):
                return TutorReply(state=state, message=self.tutor_system._get_completed_response(session)["message"])

            learner = self.learning.assess(username, session.course, session.week, "tutor", text,
                                           {**self._context(state), **({"timing": timing} if timing else {})})
            index_before = session.current_go_index
            preview = self.learning.is_preview(username)
            go_before = session.go_list[index_before]["go_id"] if index_before < len(session.go_list) else None
            mastery_before = self.learning.go_mastery(username, session.course, go_before) if preview else None
            content, sources = self.learning.course_content_with_sources(session.course, text)
            result = self.tutor_system.process_student_response(
                session=session, student_input=text,
                rag_content=content,
                orchestrator_context=learner.as_context(), on_token=on_token,
            )
            outcome = self.learning.record(
                username, session.course, session.week, mode="tutor", go_id=result.get("current_go"),
                result={"graded": result.get("graded", False), "correct": result.get("is_correct"),
                        "score": result.get("mastery_score"), "weight": result.get("evidence_weight")},
                question_type="tutor_response", student_response=text,
                details={
                    "session_id": session.session_id, "diagnostic": bool(result.get("diagnostic")),
                    "objective_index": index_before, "advanced": session.current_go_index > index_before,
                    "consecutive_incorrect": session.consecutive_incorrect,
                    "youtube_shown": bool(result.get("youtube_shown")),
                    "youtube_source": result.get("youtube_source"),
                    "scaffolding_strategy": result.get("scaffolding_strategy"),
                    "scaffolding_intensity": result.get("scaffolding_intensity"),
                    "session_complete": bool(result.get("session_complete")),
                    "one_question_extracted": result.get("one_question_extracted"),
                    "one_question_about_objective": result.get("one_question_about_objective"),
                    "one_question_category": result.get("one_question_category"),
                    "recorded_question": result.get("recorded_question"),
                },
            )
            state.week_ready = state.week_ready or outcome.week_ready
            if preview:
                from src.services.preview import learner_summary

                self.learning.explain(username, session.course, {
                    "mode": "tutor", "go_id": result.get("current_go"),
                    "objective": next((g.get("skill_name") for g in session.go_list
                                       if g.get("go_id") == result.get("current_go")), None),
                    "threshold": next((g.get("mastery_threshold") for g in session.go_list
                                       if g.get("go_id") == result.get("current_go")), None),
                    "mastery_before": mastery_before,
                    "mastery_after": self.learning.go_mastery(username, session.course, result.get("current_go")),
                    "graded": bool(result.get("graded")), "correct": result.get("is_correct") if result.get("graded") else None,
                    "score": result.get("mastery_score"), "diagnostic": bool(result.get("diagnostic")),
                    "advanced": session.current_go_index > index_before,
                    "learner": {**learner_summary(learner), "scaffolding": result.get("scaffolding_strategy"),
                                "intensity": result.get("scaffolding_intensity")},
                    "sources": sources,
                })
            if result.get("session_complete"):
                state.completed = True
                self._advance_if_ready(username, state)
            self._snapshot_debug_fields(state, learner, username, session.course)
            self.store.save(state, self.KIND, username)
            return TutorReply(
                state=state, message=result.get("message", ""),
                graded=bool(result.get("graded")), correct=result.get("is_correct") if result.get("graded") else None,
                achievements=outcome.achievements,
            )

    def end(self, username: str) -> Optional[Dict[str, Any]]:
        """End the session; returns its summary (None if there was none)."""
        with self.store.locked(self.KIND, username):
            state = self.current(username)
            if state is None:
                return None
            summary = self.tutor_system.get_session_summary(state.session)
            if not state.completed:
                self._advance_if_ready(username, state)
            summary["advanced_to_week"] = state.advanced_to_week
            self.store.delete(self.KIND, username)
            self.learning.events.learner(
                username, state.session.course, "tutor_end", mode="tutor", week=state.session.week,
                payload={"session_id": state.session.session_id, "completed": state.completed,
                         "quiz_review": bool(state.session.quiz_review),
                         **{k: v for k, v in summary.items() if isinstance(v, (int, float, str, bool, type(None)))}})
            logger.info(f"Tutor session ended: {summary['gos_completed']}/{summary['total_gos']} objectives")
            return summary

    def _advance_if_ready(self, username: str, state: TutorState) -> None:
        if state.week_ready and state.advanced_to_week is None:
            state.advanced_to_week = self.learning.advance_week_if_ready(
                username, state.session.course, state.session.week)

    def _snapshot_debug_fields(self, state: TutorState, learner: LearnerState, username: str, course: str) -> None:
        """Debug/monitoring fields on TutorView (temporary -- may be removed): the current
        objective's mastery and the learner's cognitive load/ZPD as of this turn, so a plain
        GET /tutor between turns still has something to show."""
        cognitive = learner.cognitive_state or {}
        state.last_cognitive_load = cognitive.get("cognitive_load")
        state.last_zpd_score = cognitive.get("zpd_score")
        objective = state.current_objective
        state.current_objective_mastery = (
            self.learning.go_mastery(username, course, objective["go_id"]) if objective else None
        )

    @staticmethod
    def _context(state: TutorState) -> Dict[str, Any]:
        s = state.session
        total = len(s.go_list)
        return {
            "selected_week": s.week,
            "current_mode": "tutor",
            "interaction_count": s.interaction_count + 1,
            "session_progress": s.current_go_index / total * 100 if total else 0.0,
            "completed_objectives": s.current_go_index,
            "total_objectives": total,
            "current_go_id": s.go_list[s.current_go_index]["go_id"],
            "session_start_time": s.start_time.isoformat(),
        }
