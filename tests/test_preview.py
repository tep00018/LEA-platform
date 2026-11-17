"""B7: "Try as a student" (sandbox account, explanations, reset)."""

import json

import pytest

from src.services.preview import preview_username
from tests.test_acceptance_phase1 import given_answer
from tests.test_api import register_and_login
from tests.test_onboarding import new_code

COURSE = "DEMO101"


@pytest.fixture
def teacher(client, services):
    username, headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{username}", "role", "teacher")
    services.staff.add_owner("admin", COURSE, username)
    return username, headers


def start(client, headers, code=COURSE):
    r = client.post(f"/teach/courses/{code}/preview", headers=headers)
    assert r.status_code == 200, r.text
    return r.json(), {"Authorization": f"Bearer {r.json()['token']}"}


def explain(client, headers):
    return client.get(f"/teach/courses/{COURSE}/preview/explain", headers=headers).json()


def test_the_sandbox_is_a_test_student_enrolled_in_the_course(client, teacher, services):
    username, headers = teacher
    session, preview = start(client, headers)
    assert session["username"] == preview_username(username) == f"{username}.preview"
    me = client.get("/me", headers=preview).json()
    assert me["username"] == session["username"] and me["role"] == "student" and COURSE in me["enrolled_courses"]
    assert services.events.session_kind(session["username"]) == "test"
    assert client.get("/teach/courses", headers=preview).status_code == 403  # the sandbox is a student
    again, _ = start(client, headers)  # reused, not duplicated
    assert again["username"] == session["username"]


def test_preview_turns_are_explained_to_the_teacher_only(client, teacher, services):
    _, headers = teacher
    _, preview = start(client, headers)
    client.post("/tutor", json={"course": COURSE, "week": 1}, headers=preview)
    r = client.post("/tutor/replies", json={"text": "RIGHT answer: machines doing intelligent tasks"}, headers=preview)
    assert r.status_code == 200 and "debug" not in r.text and "learner" not in r.json()  # the student view is unchanged

    quiz = client.post("/quiz", json={"course": COURSE, "week": 1}, headers=preview).json()
    client.post("/quiz/answer", json={"answer": given_answer({"type": quiz["question"]["type"]}, right=True)},
                headers=preview)
    client.post(f"/chat/{COURSE}/messages", json={"text": "What is AI?", "week": 1}, headers=preview)

    turns = explain(client, headers)
    assert [t["mode"] for t in turns] == ["chat", "quiz", "tutor"]  # newest first
    tutor = turns[2]
    assert tutor["go_id"] and tutor["objective"] and tutor["diagnostic"] is True and tutor["threshold"]
    assert set(tutor["learner"]) >= {"zpd", "cognitive_load", "motivation", "scaffolding", "intensity"}
    assert isinstance(tutor["sources"], list)
    quiz_turn = turns[1]
    assert quiz_turn["graded"] is True and quiz_turn["correct"] is True and quiz_turn["mastery_after"] is not None


def test_real_students_leave_no_explanations(client, services):
    student, headers = register_and_login(client)
    client.post("/tutor", json={"course": COURSE, "week": 1}, headers=headers)
    client.post("/tutor/replies", json={"text": "RIGHT answer: machines doing intelligent tasks"}, headers=headers)
    assert not services.redis_client.get_redis().exists(f"preview:explain:{student}")


def test_reset_forgets_the_course_but_keeps_the_account(client, teacher, services):
    username, headers = teacher
    session, preview = start(client, headers)
    account = session["username"]
    client.post("/tutor", json={"course": COURSE, "week": 1}, headers=preview)
    client.post("/tutor/replies", json={"text": "RIGHT answer: machines doing intelligent tasks"}, headers=preview)
    conn = services.redis_client.get_redis()
    conn.set(f"mastery:{account}:OTH101", json.dumps({"go_masteries": {"GO_01_01_001": 0.5}}))
    assert conn.exists(f"evidence:{account}:{COURSE}")

    assert client.post(f"/teach/courses/{COURSE}/preview/reset", headers=headers).status_code == 204
    assert not conn.exists(f"evidence:{account}:{COURSE}") and not conn.exists(f"lea:session:tutor:{account}")
    assert explain(client, headers) == []
    assert conn.exists(f"mastery:{account}:OTH101")  # another course's data stays
    assert client.get("/me", headers=preview).status_code == 200  # still logged in


def test_preview_needs_a_published_model_and_ownership(client, teacher, services):
    _, headers = teacher
    code = new_code()
    client.post("/teach/courses", json={"code": code, "name": "Unpublished", "discipline": "computing", "weeks": 1},
                headers=headers)
    r = client.post(f"/teach/courses/{code}/preview", headers=headers)
    assert r.status_code == 400 and "Publish" in r.json()["detail"]
    other, other_headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{other}", "role", "teacher")
    for path in ("", "/reset", "/explain", "/probes"):
        method = "get" if path in ("/explain", "/probes") else "post"
        assert client.request(method, f"/teach/courses/{COURSE}/preview{path}", headers=other_headers).status_code == 403


def test_probes_cover_the_week(client, teacher):
    _, headers = teacher
    probes = client.get(f"/teach/courses/{COURSE}/preview/probes", params={"week": 1}, headers=headers).json()
    ids = [p["id"] for p in probes]
    assert ids[:5] == ["diagnostic", "wrong-twice", "off-topic", "give-answer", "hint"]
    assert any(i.startswith("ask-LO_01_") for i in ids)


def test_long_teacher_names_still_fit():
    name = preview_username("t" * 32)
    assert len(name) <= 32 and name.endswith(".preview")
