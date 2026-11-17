"""B2: roles, course ownership and the admin endpoints."""

import os
import uuid

import pytest

from src.storage.event_log import EventLog
from tests.test_api import register_and_login

PASSWORD = "secret123"


def make(services, username, role):
    services.redis_client.get_redis().hset(f"user:{username}", "role", role)


def login(client, username, password=PASSWORD):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def admin(client, services):
    username, headers = register_and_login(client)
    make(services, username, "admin")
    return username, headers


def new_teacher(client, admin_headers):
    username = f"teach_{uuid.uuid4().hex[:6]}"
    r = client.post("/admin/users", json={"username": username, "full_name": "Tess Teacher",
                                          "password": "long-enough-1"}, headers=admin_headers)
    assert r.status_code == 201, r.text
    return username, login(client, username, "long-enough-1")


def staff_routes(client):
    for route in client.app.routes:
        if getattr(route, "path", "").startswith(("/admin", "/teach")):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                yield method, route.path.replace("{code}", "AIML101").replace("{username}", "someone")


def test_students_get_403_on_every_teach_and_admin_route(client):
    _, student = register_and_login(client)
    routes = list(staff_routes(client))
    assert len(routes) >= 7
    for method, path in routes:
        r = client.request(method, path, json={}, headers=student)
        assert r.status_code == 403, (method, path, r.status_code)
        assert r.json()["code"] == "NotPermitted"
        assert client.request(method, path, json={}).status_code == 401  # and no login at all


def test_me_reports_the_role(client, services):
    username, headers = register_and_login(client)
    assert client.get("/me", headers=headers).json()["role"] == "student"
    make(services, username, "teacher")
    assert client.get("/me", headers=headers).json()["role"] == "teacher"


def test_an_admin_creates_a_teacher_who_can_log_in(client, admin):
    _, admin_headers = admin
    username, teacher = new_teacher(client, admin_headers)
    me = client.get("/me", headers=teacher).json()
    assert me["role"] == "teacher" and me["enrolled_courses"] == []
    listed = {u["username"]: u for u in client.get("/admin/users", headers=admin_headers).json()}
    assert listed[username]["role"] == "teacher" and listed[username]["active"] is True
    assert "password_hash" not in str(listed)
    r = client.post("/admin/users", json={"username": username, "full_name": "Again", "password": "long-enough-1"},
                    headers=admin_headers)
    assert r.status_code == 400  # username taken
    assert client.post("/admin/users", json={"username": "x_" + uuid.uuid4().hex[:6], "full_name": "S",
                                             "password": "long-enough-1", "role": "student"},
                       headers=admin_headers).status_code == 422  # staff only


def test_teachers_reach_only_the_courses_they_own(client, admin):
    _, admin_headers = admin
    alice, alice_h = new_teacher(client, admin_headers)
    bob, bob_h = new_teacher(client, admin_headers)
    r = client.put(f"/admin/courses/AIML101/owners/{alice}", headers=admin_headers)
    assert r.status_code == 200 and alice in r.json()["owners"]
    client.put(f"/admin/courses/DEMO101/owners/{bob}", headers=admin_headers)

    mine = client.get("/teach/courses", headers=alice_h).json()
    assert [c["code"] for c in mine] == ["AIML101"]
    assert mine[0]["weeks"] == 6 and mine[0]["granular_objectives"] == 63 and mine[0]["has_content"] is True
    assert client.get("/teach/courses/AIML101", headers=alice_h).status_code == 200
    assert client.get("/teach/courses/aiml101", headers=alice_h).status_code == 200  # codes are normalised
    for code in ("DEMO101", "NOPE999", "not-a-code"):  # another teacher's, unknown, invalid: all the same 403
        assert client.get(f"/teach/courses/{code}", headers=alice_h).status_code == 403
    assert client.get("/teach/courses/AIML101", headers=bob_h).status_code == 403

    everything = {c["code"] for c in client.get("/teach/courses", headers=admin_headers).json()}
    assert {"AIML101", "DEMO101"} <= everything
    assert client.get("/teach/courses/DEMO101", headers=admin_headers).status_code == 200

    r = client.delete(f"/admin/courses/AIML101/owners/{alice}", headers=admin_headers)
    assert alice not in r.json()["owners"]
    assert client.get("/teach/courses/AIML101", headers=alice_h).status_code == 403
    assert client.delete(f"/admin/courses/AIML101/owners/{alice}", headers=admin_headers).status_code == 404


def test_only_staff_can_own_courses(client, admin):
    _, admin_headers = admin
    student, _ = register_and_login(client)
    assert client.put(f"/admin/courses/AIML101/owners/{student}", headers=admin_headers).status_code == 400
    assert client.put("/admin/courses/AIML101/owners/nobody_here", headers=admin_headers).status_code == 404
    assert client.patch("/admin/users/nobody_here", json={"role": "teacher"}, headers=admin_headers).status_code == 404


def test_deactivating_signs_out_everywhere_and_reactivating_restores(client, admin):
    admin_name, admin_headers = admin
    teacher, teacher_h = new_teacher(client, admin_headers)
    r = client.patch(f"/admin/users/{teacher}", json={"active": False}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["active"] is False
    assert client.get("/me", headers=teacher_h).status_code == 401
    assert client.post("/auth/login", json={"username": teacher, "password": "long-enough-1"}).status_code != 200
    client.patch(f"/admin/users/{teacher}", json={"active": True}, headers=admin_headers)
    login(client, teacher, "long-enough-1")
    assert client.patch(f"/admin/users/{admin_name}", json={"active": False},
                        headers=admin_headers).status_code == 400  # not yourself


def test_the_last_active_admin_stays_an_admin(client, admin, services):
    admin_name, admin_headers = admin
    conn = services.redis_client.get_redis()
    others = [u["username"] for u in services.staff.users() if u["role"] == "admin" and u["username"] != admin_name]
    for other in others:  # the in-process Redis is shared by all tests
        conn.hset(f"user:{other}", "role", "teacher")
    try:
        r = client.patch(f"/admin/users/{admin_name}", json={"role": "teacher"}, headers=admin_headers)
        assert r.status_code == 400 and "at least one active admin" in r.json()["detail"]
        second, _ = new_teacher(client, admin_headers)
        client.patch(f"/admin/users/{second}", json={"role": "admin"}, headers=admin_headers)
        assert client.patch(f"/admin/users/{admin_name}", json={"role": "teacher"},
                            headers=admin_headers).json()["role"] == "teacher"
        assert client.get("/admin/users", headers=admin_headers).status_code == 403  # no longer an admin
    finally:
        for other in others:
            conn.hset(f"user:{other}", "role", "admin")


def test_staff_actions_are_in_the_audit_trail(client, admin):
    admin_name, admin_headers = admin
    teacher, _ = new_teacher(client, admin_headers)
    client.put(f"/admin/courses/AIML101/owners/{teacher}", headers=admin_headers)
    audit = EventLog(os.environ["LEA_EVENTS_DB"]).query("actor IS NOT NULL")
    assert [(r["type"], r["actor"], r["course"]) for r in audit] == [
        ("staff_create_account", admin_name, None), ("staff_add_owner", admin_name, "AIML101")]
    assert all(r["session_kind"] == "real" and r["mode"] == "admin" for r in audit)


def test_manage_account_makes_the_first_admin(services):
    import scripts.manage_account as manage

    username = f"host_{uuid.uuid4().hex[:6]}"
    services.staff.auth.register_user(username, PASSWORD, "First Admin", [])
    assert manage.main(["make-admin", username]) == 0
    assert services.staff.role(username) == "admin"
    assert manage.main(["make-teacher", username]) == 0 and services.staff.role(username) == "teacher"
    assert manage.main(["make-student", username]) == 0 and services.staff.role(username) == "student"
