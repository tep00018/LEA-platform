"""Course structure and the learner's progress."""

from fastapi import APIRouter, Depends, Query

from src.api import deps
from src.services.container import Services
from src.services.models import CourseOutline, ProgressSummary, WeekMastery

router = APIRouter(prefix="/courses/{code}", tags=["courses"])


@router.get("/outline", response_model=CourseOutline)
def outline(code: str = Depends(deps.enrolled_course), svc: Services = Depends(deps.services)):
    return svc.courses.outline(code)


@router.get("/progress", response_model=ProgressSummary)
def progress(code: str = Depends(deps.enrolled_course), user: str = Depends(deps.current_user),
             svc: Services = Depends(deps.services)):
    return svc.progress.summary(user, code)


@router.get("/mastery", response_model=WeekMastery)
def mastery(code: str = Depends(deps.enrolled_course), user: str = Depends(deps.current_user),
            week: int = Query(ge=1, le=52, description="Week to report (the progress screen's current week)"),
            svc: Services = Depends(deps.services)):
    """Mastery of each objective in the week against its own threshold."""
    return svc.progress.week_mastery(user, code, week)
