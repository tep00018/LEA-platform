"""Request bodies and the views the API returns.

Views are shaped for clients: a quiz question never includes its answer, and internal
state (question plans, grader details, learner-state snapshots) stays on the server.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from src.services.models import AnswerFeedback, QuizState, TutorState, UserProfile

MAX_TEXT = 4000

# Surrounding whitespace is stripped before the length checks, so "   " is rejected up
# front (as a 422) rather than inside a stream.
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT)]


# --------------------------------------------------------------------------- requests


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    full_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=6, max_length=128)
    courses: List[str] = Field(min_length=1, max_length=20)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class StartIn(BaseModel):
    course: str = Field(min_length=1, max_length=16)
    week: int = Field(ge=1, le=52)


class TimingIn(BaseModel):
    """What the client measured about how the answer was given. All optional; used only to estimate
    cognitive load (see src/core/cognitive_load.py). Times are milliseconds."""
    response_ms: Optional[float] = Field(default=None, ge=0, description="Question shown to answer submitted")
    typing_ms: Optional[float] = Field(default=None, ge=0, description="First keystroke to submit")
    chars: Optional[int] = Field(default=None, ge=0, description="Characters in the submitted answer")
    prompt_chars: Optional[int] = Field(default=None, ge=0, description="Characters in what the student was answering")
    elapsed_ms: Optional[float] = Field(default=None, ge=0, description="Time on task in this session so far")
    hint_requested: bool = False
    effort_rating: Optional[int] = Field(default=None, ge=-2, le=2,
                                         description="Compared with the last objective: -2 much easier .. 2 much harder")


class AnswerIn(BaseModel):
    answer: Text
    timing: Optional[TimingIn] = None


class ChatIn(BaseModel):
    text: Text
    week: int = Field(ge=1, le=52, description="The week the student is studying (context for the answer)")


class TutorStartIn(StartIn):
    review_quiz: bool = Field(
        False, description="Review the student's just-finished quiz on this week: the tutor starts a "
                           "fresh session that knows what they got right and wrong")


class TutorIn(BaseModel):
    text: Text
    timing: Optional[TimingIn] = None


class StaffCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    full_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=256)
    role: Literal["teacher", "admin"] = "teacher"


class UserUpdateIn(BaseModel):
    role: Optional[Literal["student", "teacher", "admin"]] = None
    active: Optional[bool] = Field(None, description="false deactivates the account and signs it out everywhere")
    session_kind: Optional[Literal["real", "test", "simulated"]] = Field(
        None, description="test: the account's activity stays out of research logs, analytics and exports")


class CourseCreateIn(BaseModel):
    code: str = Field(min_length=5, max_length=8, description="2-4 letters and 3 digits, e.g. AIML101")
    name: str = Field(min_length=1, max_length=120)
    discipline: str = Field(description="computing, mathematics, science, engineering, social_science, humanities, "
                                        "business, health, education, arts or other")
    allows_code: bool = False
    code_language: Optional[str] = Field(None, max_length=30, description="Needed when allows_code is true")
    weeks: int = Field(ge=1, le=20)


class WeekPlanIn(BaseModel):
    week: int = Field(ge=1, le=20)
    title: str = Field(min_length=1, max_length=120)
    objectives: List[str] = Field(description="Full-sentence learning objectives, 1-12 per week")


class PlanIn(BaseModel):
    weeks: List[WeekPlanIn]


class JobIn(BaseModel):
    steps: Optional[List[Literal["convert", "transcribe", "embed", "kc_draft", "profile", "verify"]]] = Field(
        None, description="Default: all six, in order")


class KCRow(BaseModel):
    """One granular objective in a KC draft. Leave go_id (and lo_id, for a new learning
    objective) empty for new rows: LEA assigns IDs."""
    go_id: Optional[str] = None
    week: int = Field(ge=1, le=52)
    week_title: str = ""
    lo_id: Optional[str] = None
    lo_title: str
    lo_short_title: str = ""
    skill_name: str
    description: str = ""
    cognitive_level: str = Field(description="Remember, Understand, Apply, Analyze, Evaluate or Create")
    mastery_threshold: float
    keywords: List[str] = Field(default_factory=list)
    prerequisites: List[str] = Field(default_factory=list, description="GO IDs in this model")
    prerequisite_notes: List[str] = Field(default_factory=list, description="Prerequisites that aren't objectives here")
    split_from: Optional[str] = Field(None, description="A published GO this new row replaces (with its other parts)")
    merged_from: List[str] = Field(default_factory=list, description="Published GOs this new row replaces")
    provenance: Optional[Dict[str, Any]] = Field(None, description="Read-only: the best-matching course excerpt")


class KCRowsIn(BaseModel):
    rows: List[KCRow]


class DraftIn(BaseModel):
    source: str = Field("published", description="'published', or 'job:<id>' for an onboarding job's draft")
    replace: bool = False


class PublishIn(BaseModel):
    note: str = Field("", max_length=500)


# --------------------------------------------------------------------------- responses


class MessageOut(BaseModel):
    message: str


class LoginOut(BaseModel):
    token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Seconds until the token expires if unused; each use renews it")
    user: UserProfile


class CourseOut(BaseModel):
    code: str
    name: str


class CourseEnrollIn(BaseModel):
    code: str = Field(min_length=5, max_length=8, description="A course from GET /courses")


class ErrorOut(BaseModel):
    detail: str
    code: str


class QuestionView(BaseModel):
    number: int
    type: Literal["multiple_choice", "true_false", "fill_in_blank", "open_ended"]
    text: str
    options: List[str] = Field(default_factory=list)
    has_code: bool = False
    skill_name: str = ""


class FeedbackView(BaseModel):
    graded: bool
    correct: Optional[bool] = Field(description="None when the answer couldn't be graded (it doesn't count)")
    score: Optional[float]
    explanation: str
    your_answer: str = ""
    correct_answer: Optional[str] = Field(
        None, description="After answering, for multiple choice (the option letter) and true/false")
    achievements: List[str] = Field(default_factory=list)
    go_id: Optional[str] = Field(None, description="The objective the question tested")

    @classmethod
    def of(cls, f: AnswerFeedback) -> "FeedbackView":
        return cls(graded=f.graded, correct=f.correct, score=f.score, explanation=f.explanation,
                   your_answer=f.your_answer, correct_answer=f.expected_answer if f.graded else None,
                   achievements=f.achievements, go_id=f.go_id)


class QuizView(BaseModel):
    quiz_id: str
    course: str
    week: int
    status: Literal["question", "feedback", "completed"]
    position: int
    total: int
    correct_count: int
    graded_count: int
    question: Optional[QuestionView] = Field(None, description="Present while status is 'question'")
    feedback: Optional[FeedbackView] = Field(None, description="Present while status is 'feedback'")
    results: List[FeedbackView] = Field(default_factory=list, description="Every answer so far")
    advanced_to_week: Optional[int] = None

    @classmethod
    def of(cls, s: QuizState) -> "QuizView":
        question = None
        if s.status == "question" and s.current_question:
            q = s.current_question
            question = QuestionView(number=s.position, type=q.get("type", "multiple_choice"),
                                    text=q.get("text", ""), options=list(q.get("options") or []),
                                    has_code=bool(q.get("has_code")), skill_name=q.get("skill_name", ""))
        return cls(
            quiz_id=s.quiz_id, course=s.course, week=s.week, status=s.status, position=s.position,
            total=s.total, correct_count=s.correct_count, graded_count=s.graded_count, question=question,
            feedback=FeedbackView.of(s.feedback) if s.status == "feedback" and s.feedback else None,
            results=[FeedbackView.of(r) for r in s.results], advanced_to_week=s.advanced_to_week,
        )


class ObjectiveView(BaseModel):
    go_id: str
    skill_name: str
    description: str = ""


class TutorMessageView(BaseModel):
    role: Literal["student", "tutor"]
    content: str
    timestamp: str


class TutorView(BaseModel):
    session_id: str
    course: str
    week: int
    completed: bool
    progress_percent: float
    objective_index: int
    objectives_total: int
    current_objective: Optional[ObjectiveView]
    scaffolding_level: str = Field(description="Support intensity: very_high, high, medium, low or minimal")
    scaffolding_strategy: str = Field(
        "", description="How the tutor is scaffolding: conceptual, procedural, strategic or metacognitive")
    messages: List[TutorMessageView]
    advanced_to_week: Optional[int] = None
    quiz_review: bool = Field(False, description="The session is reviewing a quiz the student just took")
    current_objective_mastery: Optional[float] = Field(
        None, description="Debug/monitoring (temporary): the current objective's mastery level, 0-1")
    cognitive_load: Optional[float] = Field(
        None, description="Debug/monitoring (temporary): the learner's cognitive load as of the last turn")
    zpd_score: Optional[float] = Field(
        None, description="Debug/monitoring (temporary): the learner's ZPD score as of the last turn")

    @classmethod
    def of(cls, s: TutorState) -> "TutorView":
        session = s.session
        objective = s.current_objective
        return cls(
            session_id=session.session_id, course=session.course, week=session.week, completed=s.completed,
            progress_percent=s.progress_percent, objective_index=session.current_go_index,
            objectives_total=len(session.go_list),
            current_objective=ObjectiveView(go_id=objective["go_id"], skill_name=objective.get("skill_name", ""),
                                            description=objective.get("description", "")) if objective else None,
            scaffolding_level=session.scaffolding_level,
            scaffolding_strategy=session.scaffolding_strategy,
            messages=[TutorMessageView(role="student" if m.get("role") == "student" else "tutor",
                                       content=m.get("content", ""), timestamp=str(m.get("timestamp", "")))
                      for m in session.conversation_history],
            advanced_to_week=s.advanced_to_week,
            quiz_review=bool(session.quiz_review),
            current_objective_mastery=s.current_objective_mastery,
            cognitive_load=s.last_cognitive_load,
            zpd_score=s.last_zpd_score,
        )


class TutorReplyOut(BaseModel):
    message: str
    graded: bool
    correct: Optional[bool]
    achievements: List[str]
    session: TutorView


class TutorSummaryOut(BaseModel):
    total_gos: int
    gos_completed: int
    gos_mastered: int
    accuracy: float
    interaction_count: int
    advanced_to_week: Optional[int] = None

    @classmethod
    def of(cls, summary: Dict[str, Any]) -> "TutorSummaryOut":
        return cls(**{k: summary.get(k) for k in cls.model_fields})


class AdminUserOut(BaseModel):
    username: str
    full_name: str
    role: Literal["student", "teacher", "admin"]
    active: bool
    session_kind: Literal["real", "test", "simulated"]
    created_at: str
    enrolled_courses: List[str]
    owned_courses: List[str]


class OwnersOut(BaseModel):
    course: str
    owners: List[str]


class TeachCourseOut(BaseModel):
    code: str
    name: str
    owners: List[str]
    managed: bool = Field(False, description="Set up in the Teacher area (uploads and jobs); false for courses "
                                             "onboarded by hand")
    uploads: int = 0
    active_job: Optional[str] = Field(None, description="The job using the course now, if any")
    has_kc_model: bool = Field(description="A published KC model is installed")
    has_content: bool = Field(description="The course's retrieval library exists")
    weeks: int
    learning_objectives: int
    granular_objectives: int


class CourseMetaOut(BaseModel):
    code: str
    name: str
    discipline: str
    allows_code: bool
    code_language: Optional[str]
    weeks: int
    created_by: str
    created_at: str


class WeekPlanOut(BaseModel):
    week: int
    title: str
    objectives: List[str]


class PlanOut(BaseModel):
    weeks: List[WeekPlanOut]
    updated_by: str = ""
    updated_at: str = ""


class UploadOut(BaseModel):
    name: str
    size: int
    sha256: str
    week: Optional[int]
    kind: Optional[str]
    uploaded_by: str
    uploaded_at: str
    linked_relpath: Optional[str] = Field(
        None, description="Set when this upload came from a linked materials source, its path there")


class MaterialsSourceIn(BaseModel):
    type: Literal["folder"] = "folder"
    path: str = Field(min_length=1, description="A subfolder under LEA_COURSE_MATERIALS_ROOT")


class MaterialsSourceOut(BaseModel):
    type: str
    path: str


class MaterialsFolderOut(BaseModel):
    name: str


class SyncPreviewEntryOut(BaseModel):
    relpath: str
    name: str
    size: int
    status: Literal["new", "changed", "unchanged", "removed", "rejected"]
    reason: Optional[str] = None


class SyncPreviewOut(BaseModel):
    entries: List[SyncPreviewEntryOut]
    new: int
    changed: int
    unchanged: int
    removed: int
    rejected: int


class CostEstimateOut(BaseModel):
    usd: float = Field(description="Upper-end estimate of the OpenAI cost")
    per_step: Dict[str, float]
    files: int
    documents: int
    media: int
    images: int
    model_calls: int
    notes: List[str]


class JobOut(BaseModel):
    id: str
    course: str
    status: Literal["awaiting_confirmation", "queued", "running", "succeeded", "failed", "cancelled"]
    step: Optional[str] = None
    step_label: str = ""
    percent: float
    steps: List[str]
    estimate: CostEstimateOut
    result: Dict[str, Any]
    error: Optional[str] = None
    created_by: str
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    log: List[str] = Field(default_factory=list, description="The latest log lines")


class KCIssue(BaseModel):
    row: Optional[int] = Field(None, description="1-based row, or null for the whole model")
    field: str
    message: str
    level: Literal["error", "warning"]


class IssuesOut(BaseModel):
    issues: List[KCIssue]


class DraftOut(BaseModel):
    course: str
    source: str
    based_on: Optional[int] = Field(None, description="The published version the draft started from")
    created_by: str
    created_at: str
    updated_by: str
    updated_at: str
    saves: int
    rows: List[KCRow]
    issues: List[KCIssue]


class KCVersionOut(BaseModel):
    version: int
    live: bool
    published_at: str = ""
    published_by: str = ""
    note: str = ""
    objectives: int = 0
    changes: Optional[Dict[str, int]] = None


class KCOverviewOut(BaseModel):
    published_version: Optional[int]
    versions: List[KCVersionOut]
    draft: Optional[Dict[str, Any]] = Field(None, description="source, based_on, updated_at, saves; null if none")


class KCDiffOut(BaseModel):
    added: List[Dict[str, Any]]
    changed: List[Dict[str, Any]]
    retired: List[Dict[str, Any]]
    splits: List[Dict[str, Any]]
    merges: List[Dict[str, Any]]
    counts: Dict[str, int]
    impact: Dict[str, Any] = Field(description="Students with mastery on retired, split or merged objectives")


class KCImportOut(BaseModel):
    draft: DraftOut
    diff: KCDiffOut


class PublishOut(BaseModel):
    version: int
    changes: Dict[str, int]
    impact: Dict[str, Any]
    mastery_records_migrated: int


class PreviewSessionOut(BaseModel):
    username: str = Field(description="The sandbox account, <teacher>.preview (tagged test)")
    token: str = Field(description="Use it for the student endpoints while previewing; keep your own for /teach")
    course: str
    version: int = Field(description="The published KC version the preview uses")
    expires_at: str


class PreviewSourceOut(BaseModel):
    source: str
    excerpt: str


class PreviewTurnOut(BaseModel):
    at: str
    course: str
    mode: Literal["tutor", "quiz", "chat"]
    go_id: Optional[str] = None
    objective: Optional[str] = None
    threshold: Optional[float] = None
    question: Optional[str] = None
    mastery_before: Optional[float] = None
    mastery_after: Optional[float] = None
    graded: bool = False
    correct: Optional[bool] = None
    score: Optional[float] = None
    diagnostic: bool = False
    advanced: bool = False
    learner: Dict[str, Any] = Field(default_factory=dict, description="zpd, cognitive_load, motivation, scaffolding, intensity")
    sources: List[PreviewSourceOut] = Field(default_factory=list)


class ProbeOut(BaseModel):
    id: str
    text: str


class AuditTargetOut(BaseModel):
    kind: Literal["file", "objective", "question", "week"]
    ref: str


class AuditFindingOut(BaseModel):
    key: str = Field(description="Stable across runs: the same problem keeps its key")
    check: str = Field(description="accessibility, questions, bloom, coverage, redundancy, prerequisites, alignment, "
                                   "readability")
    severity: Literal["high", "medium", "low", "info"]
    title: str
    explanation: str
    evidence: str
    target: AuditTargetOut
    tier: Literal["well_supported", "rule_based", "moderate", "experimental", "informational"] = Field(
        description="How well this kind of check is validated")
    llm: bool = Field(description="An LLM judgement (a suggestion)")
    weight: int = 1
    status: Literal["open", "accepted", "dismissed"] = "open"
    note: str = ""
    new: bool = Field(False, description="Not in the run before this one")


class AuditRunOut(BaseModel):
    id: str
    course: str
    kc_version: int
    ran_at: str
    ran_by: str
    counts: Dict[str, int]
    total: int
    reviewed: int = 0
    skipped: List[str] = Field(default_factory=list, description="Checks that couldn't run, and why")
    findings: List[AuditFindingOut] = Field(default_factory=list)
    resolved_since_last: List[Dict[str, str]] = Field(default_factory=list)


class AuditRunSummaryOut(BaseModel):
    id: str
    kc_version: int
    ran_at: str
    ran_by: str
    counts: Dict[str, int]
    total: int


class AuditEstimateOut(BaseModel):
    usd: float
    objectives: int
    notes: List[str]


class DecisionIn(BaseModel):
    status: Literal["accepted", "dismissed", "open"]
    note: str = Field("", max_length=500)


class CurvePointOut(BaseModel):
    opportunity: int
    students: int
    error_rate: Optional[float] = Field(description="Null when fewer than 5 students reached this opportunity")


class AttentionOut(BaseModel):
    score: Optional[float] = None
    level: Optional[Literal["high", "medium", "low"]] = None
    driver: Optional[str] = Field(None, description="The factor that contributed most")
    factors: Dict[str, float] = Field(default_factory=dict)


class ObjectiveStatsOut(BaseModel):
    go_id: str
    skill_name: str
    week: int
    lo_id: str
    threshold: float
    band: Literal["mastered", "developing", "struggling", "insufficient"]
    students: Optional[int] = Field(description="Null when fewer than 5 (suppressed)")
    suppressed: bool
    graded_attempts: Optional[int] = None
    first_attempt_accuracy: Optional[float] = None
    attempts_to_master: Optional[float] = None
    curve_verdict: Optional[Literal["flat", "declining", "rising"]] = None
    attention: AttentionOut


class UsageOut(BaseModel):
    active_students: Optional[int] = None
    sessions: Optional[int] = None
    chat_questions: Optional[int] = None
    hours: Optional[float] = None
    suppressed: bool


class AnalyticsOverviewOut(BaseModel):
    course: str
    kind: Literal["real", "simulated"]
    week: Optional[int] = None
    min_students: int
    students: Optional[int] = None
    suppressed: bool
    bands: Dict[str, int]
    objectives: List[ObjectiveStatsOut]
    usage: UsageOut
    kc_version: int


class WrongAnswerOut(BaseModel):
    answer: str
    share: float
    count: int


class WrongAnswersOut(BaseModel):
    suppressed: bool
    students: Optional[int] = None
    answers: List[WrongAnswerOut]


class StruggleOut(BaseModel):
    streak_students: Optional[int] = None
    video_students: Optional[int] = None
    sessions_left_stuck: Optional[int] = None
    suppressed: bool


class ChatTopicOut(BaseModel):
    label: str
    go_id: Optional[str] = None
    students: int
    questions: int
    paraphrases: List[str]


class ObjectiveDetailOut(BaseModel):
    go_id: str
    skill_name: str
    description: str = ""
    kind: Literal["real", "simulated"]
    threshold: float
    band: Literal["mastered", "developing", "struggling", "insufficient"]
    students: Optional[int] = None
    suppressed: bool
    graded_attempts: Optional[int] = None
    first_attempt_accuracy: Optional[float] = None
    attempts_to_master: Optional[float] = None
    week: Optional[int] = None
    curve: List[CurvePointOut]
    course_curve: List[CurvePointOut] = Field(default_factory=list, description="Every objective pooled: the "
                                              "course's typical curve")
    curve_verdict: Optional[Literal["flat", "declining", "rising"]] = None
    attention: AttentionOut
    wrong_answers: WrongAnswersOut
    struggle: StruggleOut
    chat_topics: List[ChatTopicOut]
    suggestion: Optional[str] = Field(None, description="A drafted note for the teacher; never applied by LEA")


class ChatTopicsResultOut(BaseModel):
    ran_at: str
    kind: str
    model: str
    questions: int
    agreement: Optional[float] = Field(None, description="Share of questions two independent passes mapped to the "
                                                         "same objective")
    topics: List[ChatTopicOut]


class ChatTopicsOut(BaseModel):
    result: Optional[ChatTopicsResultOut] = None
    questions: int
    students: Optional[int] = None
    usd: float
    can_run: bool


class ExplainerOut(BaseModel):
    go_id: str
    text: str
    model: str
    note: str



# ---------------------------------------------------------------------------- videos for stuck students


class VideoIn(BaseModel):
    go_id: str = Field(description="The objective the video helps with")
    url: str = Field(description="A YouTube video link (watch, youtu.be, embed or shorts)")
    note: str = Field("", description="Shown to the student under the link, e.g. 'Watch from 3:20' (up to 200 characters)")


class VideoOut(BaseModel):
    id: str = Field(description="The YouTube video ID")
    url: str
    title: str
    channel: str = ""
    note: str = ""
    added_by: str
    added_at: str


class VideoMoveIn(BaseModel):
    direction: Literal["up", "down"]


class ObjectiveVideosOut(BaseModel):
    go_id: str
    week: int
    lo_id: str
    skill_name: str
    videos: List[VideoOut] = Field(description="In the order students see them (the first three are shown)")
    student_gets: Literal["curated", "search", "links"] = Field(
        description="What a stuck student is shown: the instructor's videos, an automatic YouTube search, or "
                    "generic search links (no API key, or search is paused because the daily quota is used up)")
    help_shown_students: Optional[int] = Field(
        description="Real students shown video help here in the last 30 days: 0 if none, null when 1 to 4 (withheld, "
                    "as in Analytics)")


class VideoSearchOut(BaseModel):
    enabled: bool = Field(description="Is automatic YouTube search configured (an API key is set)?")
    quota_paused_until: Optional[str] = Field(None, description="Automatic search is paused until then: YouTube's "
                                                                "daily quota is used up")
    cached_searches: int = Field(description="Objectives whose search results are cached for a week")


class VideosOverviewOut(BaseModel):
    course: str
    max_per_objective: int
    search: VideoSearchOut
    curated_objectives: int
    help_window_days: int
    help_shown_times: Optional[int] = Field(
        description="Times video help was shown to real students in that window; null when fewer than 5 students")
    objectives: List[ObjectiveVideosOut]
