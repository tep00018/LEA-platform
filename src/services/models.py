"""Typed models passed between the services and their clients (Streamlit now, the API later).

Everything here is plain data that round-trips through JSON, so sessions can be stored in
Redis between requests and sent over HTTP unchanged.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field

from src.tutor.simple_tutor_system import TutorSession


def to_jsonable(value: Any) -> Any:
    """Convert orchestrator output (dataclasses, enums, datetimes, tuples) to JSON types."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k.value if isinstance(k, Enum) else k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


# --------------------------------------------------------------------------- learner state


class LearnerState(BaseModel):
    """The orchestrator's assessment of the learner for one interaction.

    Quiz and Tutor read ``motivation_state``, ``scaffolding_strategy`` and
    ``cognitive_state["cognitive_load"]`` from it when generating content.
    """

    model_config = ConfigDict(extra="allow")

    processing_successful: bool = False
    motivation_state: str = "motivation_plateau"
    cognitive_state: Dict[str, Any] = Field(default_factory=dict)
    motivation_metrics: Dict[str, Any] = Field(default_factory=dict)
    motivation_feedback: Dict[str, Any] = Field(default_factory=dict)
    scaffolding_strategy: Dict[str, Any] = Field(default_factory=dict)
    adaptive_context: Dict[str, Any] = Field(default_factory=dict)
    orchestrator_guidance: str = ""

    @classmethod
    def from_orchestrator(cls, result: Optional[Dict[str, Any]]) -> "LearnerState":
        data = to_jsonable(result or {})
        # The mastery snapshot inside the cognitive state is large and is re-read when needed.
        if isinstance(data.get("cognitive_state"), dict):
            data["cognitive_state"].pop("mastery_data", None)
        return cls.model_validate(data)

    def as_context(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


# --------------------------------------------------------------------------- accounts & courses


class UserProfile(BaseModel):
    username: str
    full_name: str = ""
    enrolled_courses: List[str] = Field(default_factory=list)
    role: Literal["student", "teacher", "admin"] = Field(
        "student", description="student (default), teacher (owns courses) or admin")


class LearningObjectiveInfo(BaseModel):
    id: str
    title: str
    concept_count: int


class WeekOutline(BaseModel):
    number: int
    title: str
    learning_objectives: List[LearningObjectiveInfo] = Field(default_factory=list)

    @computed_field
    @property
    def concept_count(self) -> int:
        return sum(lo.concept_count for lo in self.learning_objectives)


class CourseOutline(BaseModel):
    code: str
    name: str
    weeks: List[WeekOutline] = Field(default_factory=list)

    def week(self, number: int) -> Optional[WeekOutline]:
        return next((w for w in self.weeks if w.number == number), None)


class ProgressSummary(BaseModel):
    course: str
    current_week: int = 1
    week_completion: float = 0.0
    completed_gos: List[str] = Field(default_factory=list)
    total_gos: int = 0
    ready_for_next_week: bool = False


class ObjectiveMastery(BaseModel):
    go_id: str
    skill_name: str
    mastery: Optional[float] = Field(None, description="None until the learner has a graded answer on it")
    threshold: float = Field(description="Mastery needed for this objective (from the KC model)")
    mastered: bool


class LearningObjectiveMastery(BaseModel):
    lo_id: str
    title: str
    objectives: List[ObjectiveMastery]


class WeekMastery(BaseModel):
    """Mastery of each granular objective in one week, grouped by learning objective."""

    course: str
    week: int
    completion: float = Field(description="Share of the week's objectives mastered (0-1)")
    mastered_count: int
    total: int
    learning_objectives: List[LearningObjectiveMastery]


class RecordOutcome(BaseModel):
    """What changed after a graded answer was recorded."""

    recorded: bool = False
    achievements: List[str] = Field(default_factory=list)
    week_ready: bool = False


# --------------------------------------------------------------------------- chat


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    message: str
    timestamp: float


class ChatState(BaseModel):
    username: str
    course: str
    messages: List[ChatMessage] = Field(default_factory=list)
    # Questions asked in the current sitting (Q in the cognitive-load formula). A sitting
    # ends after CHAT_SITTING_GAP seconds without a message.
    turns: int = 0
    last_activity: float = 0.0
    sitting_started: float = 0.0  # messages since then are the model's conversation context


class ChatReply(BaseModel):
    ok: bool
    message: str


# --------------------------------------------------------------------------- quiz


class AnswerFeedback(BaseModel):
    """The graded result of one quiz answer as shown to the student."""

    model_config = ConfigDict(extra="allow")

    graded: bool = False
    correct: Optional[bool] = None
    score: Optional[float] = None
    explanation: str = ""
    go_id: Optional[str] = None
    question_type: Optional[str] = None
    your_answer: str = ""
    expected_answer: Optional[str] = None  # set by exact grading (multiple choice letter, True/False)
    achievements: List[str] = Field(default_factory=list)


QuizStatus = Literal["question", "feedback", "completed"]


class QuizState(BaseModel):
    """One quiz, stored between requests.

    The fields up to ``motivation_tracking`` are the quiz dict SimpleQuizSystem works on;
    the rest is what the service adds (feedback, results, completion).
    """

    model_config = ConfigDict(extra="allow")

    quiz_id: str
    username: str
    course: str
    week: int
    question_plan: List[Dict[str, Any]]
    current_question_index: int = 0
    current_question: Optional[Dict[str, Any]] = None
    answers: List[Dict[str, Any]] = Field(default_factory=list)
    start_time: str = ""
    orchestrator_context: Optional[Dict[str, Any]] = None
    trackers: Dict[str, Any] = Field(default_factory=dict)
    motivation_tracking: Dict[str, Any] = Field(default_factory=dict)

    status: QuizStatus = "question"
    feedback: Optional[AnswerFeedback] = None
    results: List[AnswerFeedback] = Field(default_factory=list)
    week_ready: bool = False                 # a graded answer in this quiz completed the week
    advanced_to_week: Optional[int] = None   # set when the quiz ends and the learner moves on

    @property
    def position(self) -> int:
        """1-based number of the current question."""
        return self.current_question_index + 1

    @property
    def total(self) -> int:
        return len(self.question_plan)

    @property
    def correct_count(self) -> int:
        return sum(1 for r in self.results if r.correct is True)

    @property
    def graded_count(self) -> int:
        return sum(1 for r in self.results if r.correct is not None)

    def quiz_data(self) -> Dict[str, Any]:
        """The dict SimpleQuizSystem expects (it mutates and returns it)."""
        return self.model_dump(mode="json")


# --------------------------------------------------------------------------- tutor


class TutorState(BaseModel):
    session: TutorSession
    completed: bool = False
    week_ready: bool = False
    advanced_to_week: Optional[int] = None
    # Debug/monitoring snapshot (temporary -- see TutorView), refreshed on every start()/respond()
    # so a plain GET /tutor between turns still has something to show.
    current_objective_mastery: Optional[float] = None
    last_cognitive_load: Optional[float] = None
    last_zpd_score: Optional[float] = None

    @property
    def progress_percent(self) -> float:
        total = len(self.session.go_list)
        return 100.0 * min(self.session.current_go_index, total) / total if total else 0.0

    @property
    def current_objective(self) -> Optional[Dict[str, Any]]:
        s = self.session
        return s.go_list[s.current_go_index] if s.current_go_index < len(s.go_list) else None


class TutorReply(BaseModel):
    state: TutorState
    message: str
    graded: bool = False
    correct: Optional[bool] = None
    achievements: List[str] = Field(default_factory=list)
