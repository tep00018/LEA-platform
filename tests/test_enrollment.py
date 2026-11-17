"""Adding or removing a course on an already-existing account: self-service (/me/courses)
and admin-driven (/admin/users/{username}/courses/{code}). See src/services/accounts.py's
add_course/remove_course and src/services/staff.py's counterparts."""

import json


from tests.conftest import OPEN_COURSE
from tests.test_api import COURSE, register_and_login
from tests.test_staff import admin, make  # noqa: F401 (shared fixture)


def test_a_student_can_add_and_remove_a_course_themselves(client, services):
    username, auth = register_and_login(client)
    assert [c["code"] for c in client.get("/me/courses", headers=auth).json()] == [COURSE]

    r = client.post("/me/courses", json={"code": OPEN_COURSE}, headers=auth)
    assert r.status_code == 201, r.text
    assert {c["code"] for c in r.json()} == {COURSE, OPEN_COURSE}
    # Persisted, not just in the response:
    assert {c["code"] for c in client.get("/me/courses", headers=auth).json()} == {COURSE, OPEN_COURSE}

    r = client.delete(f"/me/courses/{OPEN_COURSE}", headers=auth)
    assert r.status_code == 200 and [c["code"] for c in r.json()] == [COURSE]


def test_adding_a_course_is_idempotent_and_unknown_courses_are_refused(client):
    _, auth = register_and_login(client)
    for _ in range(2):
        assert client.post("/me/courses", json={"code": OPEN_COURSE}, headers=auth).status_code == 201
    codes = [c["code"] for c in client.get("/me/courses", headers=auth).json()]
    assert sorted(codes) == sorted({COURSE, OPEN_COURSE})  # no duplicate

    r = client.post("/me/courses", json={"code": "NOPE01"}, headers=auth)
    assert r.status_code == 400 and "Unknown course" in r.json()["detail"]


def test_removing_a_course_never_reaches_zero_by_force_but_is_allowed(client):
    """Removing your only course is allowed (NoCoursesError is a client-side concern)."""
    _, auth = register_and_login(client)
    r = client.delete(f"/me/courses/{COURSE}", headers=auth)
    assert r.status_code == 200 and r.json() == []


def test_self_service_enrollment_is_logged_to_the_event_log(client, services):
    username, auth = register_and_login(client)
    client.post("/me/courses", json={"code": OPEN_COURSE}, headers=auth)
    client.delete(f"/me/courses/{OPEN_COURSE}", headers=auth)
    rows = services.events.log.query("type LIKE 'course_self_%'")
    assert [r["type"] for r in rows] == ["course_self_enroll", "course_self_unenroll"]
    assert all(r["course"] == OPEN_COURSE for r in rows)


def test_an_admin_can_add_and_remove_a_course_for_any_account(client, admin, services):  # noqa: F811
    _, admin_headers = admin
    student, _ = register_and_login(client)

    r = client.put(f"/admin/users/{student}/courses/{OPEN_COURSE}", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert sorted(r.json()["enrolled_courses"]) == sorted({COURSE, OPEN_COURSE})

    r = client.delete(f"/admin/users/{student}/courses/{OPEN_COURSE}", headers=admin_headers)
    assert r.status_code == 200 and r.json()["enrolled_courses"] == [COURSE]

    rows = services.events.log.query("type LIKE 'staff_%_course'", ())
    assert {r["type"] for r in rows} == {"staff_add_course", "staff_remove_course"}
    assert all(json.loads(r["payload_json"])["username"] == student for r in rows)


def test_a_teacher_cannot_manage_enrollment_only_an_admin_can(client, services):
    teacher, teacher_headers = register_and_login(client)
    make(services, teacher, "teacher")
    student, _ = register_and_login(client)
    r = client.put(f"/admin/users/{student}/courses/{OPEN_COURSE}", headers=teacher_headers)
    assert r.status_code == 403


def test_admin_enrollment_refuses_an_unknown_course_or_account(client, admin):  # noqa: F811
    _, admin_headers = admin
    student, _ = register_and_login(client)
    assert client.put(f"/admin/users/{student}/courses/NOPE01", headers=admin_headers).status_code == 400
    assert client.put("/admin/users/nobody_here/courses/" + OPEN_COURSE, headers=admin_headers).status_code == 404
