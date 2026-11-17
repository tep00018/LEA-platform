"""Quiz mode. A learner has at most one quiz; these endpoints act on it.

Flow: ``POST /quiz`` → (``POST /quiz/answer`` → ``POST /quiz/next``)* → status
``completed``. ``POST /quiz/end`` stops early; ``DELETE /quiz`` forgets it.
"""

from fastapi import APIRouter, Depends, Response, status

from src.api import deps
from src.api.schemas import AnswerIn, QuizView, StartIn
from src.services.container import Services
from src.services.errors import NoActiveSession

router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.get("", response_model=QuizView)
def current(user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    state = svc.quiz.current(user)
    if state is None:
        raise NoActiveSession("There's no quiz in progress.")
    return QuizView.of(state)


@router.post("", response_model=QuizView)
def start(body: StartIn, user: str = Depends(deps.model_budget), svc: Services = Depends(deps.services)):
    """Start a quiz on the week, or return the one already in progress for it."""
    course = deps.require_enrolled(user, body.course, svc)
    deps.require_week(course, body.week, svc)
    return QuizView.of(svc.quiz.start(user, course, body.week))


@router.post("/answer", response_model=QuizView)
def answer(body: AnswerIn, user: str = Depends(deps.model_budget), svc: Services = Depends(deps.services)):
    """Answer the current question. The response has status ``feedback``."""
    return QuizView.of(svc.quiz.answer(user, body.answer, timing=body.timing.model_dump() if body.timing else None))


@router.post("/next", response_model=QuizView)
def next_question(user: str = Depends(deps.model_budget), svc: Services = Depends(deps.services)):
    """After feedback: the next question, or the results (status ``completed``)."""
    return QuizView.of(svc.quiz.next(user))


@router.post("/end", response_model=QuizView)
def end(user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    state = svc.quiz.end(user)
    if state is None:
        raise NoActiveSession("There's no quiz in progress.")
    return QuizView.of(state)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def discard(user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    svc.quiz.discard(user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
