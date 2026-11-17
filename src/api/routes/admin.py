"""Admin: accounts, roles and course ownership. Every route needs an admin (403 otherwise)."""

from fastapi import APIRouter, Depends

from src.api import deps
from src.api.schemas import AdminUserOut, OwnersOut, StaffCreateIn, UserUpdateIn
from src.services.container import Services

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(deps.require_admin)])


@router.get("/users", response_model=list[AdminUserOut])
def users(svc: Services = Depends(deps.services)):
    """Every account, with its role, status and the courses it owns."""
    return svc.staff.users()


@router.post("/users", response_model=AdminUserOut, status_code=201)
def create_staff(body: StaffCreateIn, admin: str = Depends(deps.require_admin), svc: Services = Depends(deps.services)):
    """Create a teacher (or admin) account. There is no self-service teacher sign-up."""
    return svc.staff.create_staff(admin, body.username, body.full_name, body.password, body.role)


@router.patch("/users/{username}", response_model=AdminUserOut)
def update_user(username: str, body: UserUpdateIn, admin: str = Depends(deps.require_admin),
                svc: Services = Depends(deps.services)):
    """Change an account's role, deactivate it (which signs it out everywhere) or reactivate
    it, or mark it a test account. The last active admin can't be demoted or deactivated."""
    return svc.staff.update_user(admin, username, role=body.role, active=body.active, session_kind=body.session_kind)


@router.put("/users/{username}/courses/{code}", response_model=AdminUserOut)
def add_user_course(username: str, code: str, admin: str = Depends(deps.require_admin),
                    svc: Services = Depends(deps.services)):
    """Enroll any account in a course on their behalf. Idempotent."""
    return svc.staff.add_course(admin, username, code)


@router.delete("/users/{username}/courses/{code}", response_model=AdminUserOut)
def remove_user_course(username: str, code: str, admin: str = Depends(deps.require_admin),
                       svc: Services = Depends(deps.services)):
    """Un-enrol any account from a course. Their progress in it isn't deleted."""
    return svc.staff.remove_course(admin, username, code)


@router.get("/courses/{code}/owners", response_model=OwnersOut)
def owners(code: str, svc: Services = Depends(deps.services)):
    return OwnersOut(course=code.upper(), owners=svc.staff.owners(code))


@router.put("/courses/{code}/owners/{username}", response_model=OwnersOut)
def add_owner(code: str, username: str, admin: str = Depends(deps.require_admin),
              svc: Services = Depends(deps.services)):
    """Make a teacher an owner of the course (they must already be a teacher or admin)."""
    return OwnersOut(course=code.upper(), owners=svc.staff.add_owner(admin, code, username))


@router.delete("/courses/{code}/owners/{username}", response_model=OwnersOut)
def remove_owner(code: str, username: str, admin: str = Depends(deps.require_admin),
                 svc: Services = Depends(deps.services)):
    return OwnersOut(course=code.upper(), owners=svc.staff.remove_owner(admin, code, username))
