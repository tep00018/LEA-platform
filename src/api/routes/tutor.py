"""Tutor mode. A learner has at most one tutor session; these endpoints act on it."""

from fastapi import APIRouter, Depends, Response

from src.api import deps
from src.api.schemas import TutorIn, TutorStartIn, TutorReplyOut, TutorSummaryOut, TutorView
from src.api.streaming import stream
from src.services.container import Services
from src.services.errors import NoActiveSession
from src.services.models import TutorReply

router = APIRouter(prefix="/tutor", tags=["tutor"])


def _reply(reply: TutorReply) -> TutorReplyOut:
    return TutorReplyOut(message=reply.message, graded=reply.graded, correct=reply.correct,
                         achievements=reply.achievements, session=TutorView.of(reply.state))


def _require_session(user: str, svc: Services) -> None:
    if svc.tutor.current(user) is None:
        raise NoActiveSession("There's no tutoring session in progress.")


@router.get("", response_model=TutorView)
def current(user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    state = svc.tutor.current(user)
    if state is None:
        raise NoActiveSession("There's no tutoring session in progress.")
    return TutorView.of(state)


@router.post("", response_model=TutorView)
def start(body: TutorStartIn, user: str = Depends(deps.model_budget), svc: Services = Depends(deps.services)):
    """Start a session on the week (or return the one running for it). The first tutor
    message asks what the student already knows. With ``review_quiz`` and a finished quiz on
    the same week, a fresh session starts that knows the quiz results (``quiz_review`` in the
    answer says whether it did); otherwise this is an ordinary start."""
    course = deps.require_enrolled(user, body.course, svc)
    deps.require_week(course, body.week, svc)
    quiz = svc.quiz.current(user) if body.review_quiz else None
    return TutorView.of(svc.tutor.start(user, course, body.week, quiz=quiz))


@router.post("/replies", response_model=TutorReplyOut)
def reply(body: TutorIn, user: str = Depends(deps.model_budget), svc: Services = Depends(deps.services)):
    return _reply(svc.tutor.respond(user, body.text, timing=body.timing.model_dump() if body.timing else None))


@router.post("/replies/stream", response_class=Response,
             responses={200: {"content": {"text/event-stream": {}},
                              "description": "Server-sent events: `token` ({text}) while the tutor writes, "
                                             "then `done` (TutorReplyOut) or `error` ({detail, code, status})."}})
def reply_streamed(body: TutorIn, user: str = Depends(deps.model_budget), svc: Services = Depends(deps.services)):
    _require_session(user, svc)
    return stream(lambda on_token: svc.tutor.respond(user, body.text, on_token=on_token,
                                                    timing=body.timing.model_dump() if body.timing else None),
                  lambda r: _reply(r).model_dump(mode="json"))


@router.post("/end", response_model=TutorSummaryOut)
def end(user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    summary = svc.tutor.end(user)
    if summary is None:
        raise NoActiveSession("There's no tutoring session in progress.")
    return TutorSummaryOut.of(summary)
