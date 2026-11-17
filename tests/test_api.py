"""The HTTP API: auth, isolation between users, every mode, streaming and errors."""

import json
import uuid

import pytest

from src.api.app import create_app
from tests.test_acceptance_phase1 import given_answer, question_writer

COURSE = "DEMO101"


def register_and_login(client, courses=(COURSE,), password="secret123"):
    username = f"api_{uuid.uuid4().hex[:8]}"
    r = client.post("/auth/register", json={"username": username, "full_name": "Api Student",
                                            "password": password, "courses": list(courses)})
    assert r.status_code == 201, r.text
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return username, {"Authorization": f"Bearer {r.json()['token']}"}


def events(response):
    """Parse a server-sent event stream into (event, data) pairs."""
    out = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


# ----------------------------------------------------------------------------- auth


def test_login_me_logout(client):
    username, auth = register_and_login(client)
    me = client.get("/me", headers=auth).json()
    assert me == {"username": username, "full_name": "Api Student", "enrolled_courses": [COURSE], "role": "student"}
    assert client.get("/me/courses", headers=auth).json()[0]["code"] == COURSE

    assert client.post("/auth/logout", headers=auth).status_code == 204
    r = client.get("/me", headers=auth)
    assert r.status_code == 401 and r.headers["WWW-Authenticate"] == "Bearer"


def test_requests_without_a_valid_token_are_rejected(client):
    for method, path in [("get", "/me"), ("get", "/quiz"), ("post", "/tutor/end"),
                         ("get", f"/chat/{COURSE}/messages"), ("get", f"/courses/{COURSE}/progress")]:
        assert getattr(client, method)(path).status_code == 401
        assert getattr(client, method)(path, headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_bad_logins_are_limited_per_username(client):
    username, _ = register_and_login(client)
    for _ in range(5):
        assert client.post("/auth/login", json={"username": username, "password": "wrong"}).status_code == 400
    r = client.post("/auth/login", json={"username": username, "password": "secret123"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_registration_is_validated(client):
    r = client.post("/auth/register", json={"username": "ab", "full_name": "x", "password": "secret123",
                                            "courses": [COURSE]})
    assert r.status_code == 422
    r = client.post("/auth/register", json={"username": "valid_name", "full_name": "x", "password": "secret123",
                                            "courses": ["NOPE999"]})
    assert r.status_code == 400 and "Unknown course" in r.json()["detail"]


# ----------------------------------------------------------------------------- isolation


def test_one_user_cannot_see_or_act_on_anothers_sessions(client):
    _, alice = register_and_login(client)
    _, bob = register_and_login(client)
    assert client.post("/quiz", json={"course": COURSE, "week": 1}, headers=alice).status_code == 200
    client.post(f"/chat/{COURSE}/messages", json={"text": "Alice's question", "week": 1}, headers=alice)

    assert client.get("/quiz", headers=bob).status_code == 404
    assert client.post("/quiz/answer", json={"answer": "A"}, headers=bob).status_code == 404
    assert client.get(f"/chat/{COURSE}/messages", headers=bob).json() == []
    assert client.get("/quiz", headers=alice).status_code == 200


def test_courses_outside_the_enrolment_are_refused(client):
    _, auth = register_and_login(client)
    for path in ["/courses/ZZZ999/outline", "/courses/ZZZ999/progress", "/chat/ZZZ999/messages"]:
        assert client.get(path, headers=auth).status_code == 403
    assert client.post("/quiz", json={"course": "ZZZ999", "week": 1}, headers=auth).status_code == 403
    assert client.get("/courses/..%2Fetc/outline", headers=auth).status_code in (400, 404)


# ----------------------------------------------------------------------------- modes


def test_course_outline_and_progress(client):
    _, auth = register_and_login(client)
    outline = client.get(f"/courses/{COURSE}/outline", headers=auth).json()
    assert [w["number"] for w in outline["weeks"]] == [1, 2, 3] and outline["weeks"][0]["concept_count"] == 11
    progress = client.get(f"/courses/{COURSE}/progress", headers=auth).json()
    assert progress["current_week"] == 1 and progress["week_completion"] == 0.0


def test_quiz_over_http_never_reveals_answers(client):
    _, auth = register_and_login(client)
    quiz = client.post("/quiz", json={"course": COURSE, "week": 1}, headers=auth).json()
    assert quiz["status"] == "question" and quiz["total"] == 11
    question = quiz["question"]
    assert set(question) == {"number", "type", "text", "options", "has_code", "skill_name"}
    assert "correct_answer" not in json.dumps(quiz) and "question_plan" not in quiz

    assert client.post("/quiz", json={"course": COURSE, "week": 9}, headers=auth).status_code == 400
    assert client.post("/quiz/next", headers=auth).status_code == 409  # must answer first

    wrong = {"multiple_choice": "D) d", "true_false": "False"}.get(question["type"], "WRONG answer")
    quiz = client.post("/quiz/answer", json={"answer": wrong}, headers=auth).json()
    assert quiz["status"] == "feedback" and quiz["feedback"]["correct"] is False and quiz["question"] is None
    assert quiz["feedback"]["your_answer"] == wrong
    assert quiz["feedback"]["go_id"]  # which objective it tested, for the results list
    if question["type"] in ("multiple_choice", "true_false"):  # revealed only after answering
        assert quiz["feedback"]["correct_answer"] in ("A", "True")
    assert client.post("/quiz/answer", json={"answer": wrong}, headers=auth).status_code == 409

    quiz = client.post("/quiz/next", headers=auth).json()
    assert quiz["status"] == "question" and quiz["position"] == 2
    quiz = client.post("/quiz/end", headers=auth).json()
    assert quiz["status"] == "completed" and quiz["graded_count"] == 1 and len(quiz["results"]) == 1
    assert client.delete("/quiz", headers=auth).status_code == 204
    assert client.get("/quiz", headers=auth).status_code == 404


def test_review_with_the_tutor_after_a_quiz(client):
    _, auth = register_and_login(client)
    question = client.post("/quiz", json={"course": COURSE, "week": 1}, headers=auth).json()["question"]
    wrong = {"multiple_choice": "D) d", "true_false": "False"}.get(question["type"], "WRONG answer")
    assert client.post("/quiz/answer", json={"answer": wrong}, headers=auth).json()["feedback"]["correct"] is False
    plain = client.post("/tutor", json={"course": COURSE, "week": 1, "review_quiz": True}, headers=auth).json()
    assert plain["quiz_review"] is False  # the quiz isn't finished yet

    client.post("/quiz/end", headers=auth)
    review = client.post("/tutor", json={"course": COURSE, "week": 1, "review_quiz": True}, headers=auth).json()
    assert review["quiz_review"] is True  # a fresh session replaced the plain one
    assert review["messages"][0]["content"].startswith("Let's go over your Week 1 quiz.")
    again = client.post("/tutor", json={"course": COURSE, "week": 1}, headers=auth).json()
    assert again["quiz_review"] is True and again["messages"] == review["messages"]  # resumes the review


def test_tutor_over_http_with_streaming(client, fake_llm):
    _, auth = register_and_login(client)
    session = client.post("/tutor", json={"course": COURSE, "week": 1}, headers=auth).json()
    assert session["objective_index"] == 0 and session["messages"][0]["role"] == "tutor"
    assert "go_list" not in session
    # The app names the support in the header pill: strategy and intensity.
    assert session["scaffolding_strategy"] in {"conceptual", "procedural", "strategic", "metacognitive"}
    assert session["scaffolding_level"] in {"very_high", "high", "medium", "low", "minimal"}

    r = client.post("/tutor/replies", json={"text": "RIGHT answer: machines doing intelligent tasks"},
                    headers=auth)
    assert r.status_code == 200 and r.json()["session"]["objective_index"] == 1

    fake_llm_reply = "Good thinking about narrow AI."
    fake_llm._responder = lambda m: (
        question_writer(m) if ("<answer>" in m[-1]["content"] or "JSON" in m[0]["content"]) else fake_llm_reply)
    r = client.post("/tutor/replies/stream", json={"text": "RIGHT answer: narrow and general"}, headers=auth)
    assert r.headers["content-type"].startswith("text/event-stream")
    evs = events(r)
    tokens = [d["text"] for e, d in evs if e == "token"]
    kind, final = evs[-1]
    assert kind == "done" and len(tokens) > 1 and "".join(tokens) == final["message"] == fake_llm_reply
    assert final["graded"] and final["correct"] is True and final["session"]["objective_index"] == 2

    summary = client.post("/tutor/end", headers=auth).json()
    assert summary["gos_completed"] == 2
    r = client.post("/tutor/replies/stream", json={"text": "hi"}, headers=auth)
    assert r.status_code == 404


def test_chat_over_http_with_memory_and_streaming(client, fake_llm):
    _, auth = register_and_login(client)
    fake_llm._responder = lambda m: "Supervised learning uses labelled data."
    r = client.post(f"/chat/{COURSE}/messages", json={"text": "What is supervised learning?", "week": 1},
                    headers=auth)
    assert r.json() == {"ok": True, "message": "Supervised learning uses labelled data."}

    fake_llm._responder = lambda m: "Spam filtering is one."
    r = client.post(f"/chat/{COURSE}/messages/stream", json={"text": "An example?", "week": 1}, headers=auth)
    evs = events(r)
    assert evs[-1] == ("done", {"ok": True, "message": "Spam filtering is one."})
    assert [m["role"] for m in fake_llm.calls[-1]["messages"]] == ["system", "user", "assistant", "user"]
    assert len(client.get(f"/chat/{COURSE}/messages", headers=auth).json()) == 4

    def boom(messages):
        raise RuntimeError("API down")

    fake_llm._responder = boom
    r = client.post(f"/chat/{COURSE}/messages", json={"text": "Another?", "week": 1}, headers=auth)
    assert r.status_code == 503 and r.json()["code"] == "Unavailable"
    evs = events(client.post(f"/chat/{COURSE}/messages/stream", json={"text": "Another?", "week": 1},
                             headers=auth))
    assert evs[-1][0] == "error" and evs[-1][1]["status"] == 503

    assert client.delete(f"/chat/{COURSE}/messages", headers=auth).status_code == 204
    assert client.get(f"/chat/{COURSE}/messages", headers=auth).json() == []


def test_model_calls_are_rate_limited_per_user(client, monkeypatch):
    from src.api import deps

    monkeypatch.setattr(deps, "MODEL_CALLS_PER_MINUTE", 2)
    _, auth = register_and_login(client)
    body = {"text": "hi", "week": 1}
    codes = [client.post(f"/chat/{COURSE}/messages", json=body, headers=auth).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_health_and_openapi(client):
    assert client.get("/health").json() == {"status": "ok", "redis": True}
    spec = client.get("/openapi.json").json()
    assert "/quiz/answer" in spec["paths"] and "QuizView" in spec["components"]["schemas"]


def test_cors_allows_the_local_flutter_dev_server(client):
    r = client.options("/me", headers={"Origin": "http://localhost:53712", "Access-Control-Request-Method": "GET",
                                      "Access-Control-Request-Headers": "authorization"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:53712"
    r = client.options("/me", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers


def test_cors_preflight_allows_every_method_the_client_uses(client):
    """The Flutter app uses PUT (plan, draft rows, enrolment, owners, audit decisions) and PATCH
    (admin account edits); a browser on another origin must get past the preflight for each."""
    origin = "http://localhost:5100"
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        r = client.options("/teach/courses", headers={
            "Origin": origin, "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type"})
        assert r.status_code == 200, method
        assert method in r.headers["access-control-allow-methods"], method
    r = client.options("/teach/courses", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "PUT"})
    assert "access-control-allow-origin" not in r.headers


def test_quiz_flow_uses_given_answer_helper(client):
    """A correct answer over HTTP is graded correct (exact grading for MC/TF)."""
    _, auth = register_and_login(client)
    quiz = client.post("/quiz", json={"course": COURSE, "week": 1}, headers=auth).json()
    answer = given_answer({"type": quiz["question"]["type"]}, right=True)
    quiz = client.post("/quiz/answer", json={"answer": answer}, headers=auth).json()
    assert quiz["feedback"]["correct"] is True and quiz["correct_count"] == 1


def test_committed_openapi_spec_is_current():
    """docs/api/openapi.json must match the code (run scripts/export_openapi.py)."""
    from pathlib import Path

    committed = json.loads((Path(__file__).parent.parent / "docs" / "api" / "openapi.json").read_text())
    assert committed == create_app().openapi()


# ----------------------------------------------------------------------------- review follow-ups


def test_parallel_guesses_cannot_exceed_the_login_limit(client, services):
    from concurrent.futures import ThreadPoolExecutor

    username, _ = register_and_login(client)
    checked = []
    original = services.accounts.auth.login_user

    def counting(*args, **kwargs):
        checked.append(1)
        return original(*args, **kwargs)

    services.accounts.auth.login_user = counting
    with ThreadPoolExecutor(20) as pool:
        codes = list(pool.map(lambda _: client.post("/auth/login", json={"username": username,
                                                                          "password": "guess"}).status_code,
                              range(20)))
    assert len(checked) <= 5 and codes.count(429) >= 15


def test_one_device_cannot_lock_a_student_out_everywhere(services):
    from src.services.errors import RateLimited

    username = f"lock_{uuid.uuid4().hex[:6]}"
    services.accounts.register(username, "A", "secret123", "secret123", [COURSE])
    for _ in range(5):
        with pytest.raises(Exception):
            services.accounts.login(username, "wrong", address="10.0.0.66")
    with pytest.raises(RateLimited):
        services.accounts.login(username, "secret123", address="10.0.0.66")
    assert services.accounts.login(username, "secret123", address="10.0.0.7")[1]  # the student, elsewhere


def test_simultaneous_registrations_of_one_username(services):
    from concurrent.futures import ThreadPoolExecutor

    username = f"race_{uuid.uuid4().hex[:6]}"
    auth = services.accounts.auth
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda pw: auth.register_user(username, pw, "A", [COURSE]),
                                ["first-pass", "second-pass"]))
    assert [ok for ok, _ in results].count(True) == 1
    winner = "first-pass" if results[0][0] else "second-pass"
    assert auth.login_user(username, winner)[0]


def test_tokens_die_with_the_account_they_were_issued_to(client, services):
    username, auth = register_and_login(client)
    conn = services.redis_client.get_redis()
    conn.hdel(f"user:{username}", "is_active")  # an older record without the flag still works
    assert client.get("/me", headers=auth).status_code == 200
    conn.delete(f"user:{username}")
    services.accounts.register(username, "Someone Else", "secret123", "secret123", [COURSE])
    assert client.get("/me", headers=auth).status_code == 401


def test_errors_inside_a_stream_are_error_events(client, services):
    _, auth = register_and_login(client)
    client.post("/tutor", json={"course": COURSE, "week": 1}, headers=auth)
    username = client.get("/me", headers=auth).json()["username"]
    with services.tutor.store.locked("tutor", username):  # another request is still running
        evs = events(client.post("/tutor/replies/stream", json={"text": "hello"}, headers=auth))
    assert evs == [("error", {"detail": evs[0][1]["detail"], "code": "Busy", "status": 409})]
    r = client.post("/tutor/replies/stream", json={"text": "   "}, headers=auth)
    assert r.status_code == 422 and r.json()["code"] == "ValidationError"


def test_browser_clients_can_read_errors(client, services, monkeypatch):
    origin = {"Origin": "http://localhost:5000"}
    _, auth = register_and_login(client)

    def broken(*args, **kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(services.progress, "summary", broken)
    r = client.get(f"/courses/{COURSE}/progress", headers={**auth, **origin})
    assert r.status_code == 500 and r.json()["code"] == "InternalError"
    assert r.headers["access-control-allow-origin"] == "http://localhost:5000"
    r = client.get("/me", headers=origin)
    assert "WWW-Authenticate" in r.headers["access-control-expose-headers"]
    r = client.post("/auth/login", json={"username": "x"}, headers=origin)
    assert r.status_code == 422 and r.json()["code"] == "ValidationError" and "password" in r.json()["detail"]


def test_account_admin_script(services, monkeypatch, capsys):
    from scripts import manage_account

    username = f"admin_{uuid.uuid4().hex[:6]}"
    services.accounts.register(username, "A", "secret123", "secret123", [COURSE])
    _, token = services.accounts.login(username, "secret123")
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "new-secret")
    assert manage_account.main(["reset-password", username]) == 0
    assert services.accounts.auth.validate_session(token) is None
    assert services.accounts.login(username, "new-secret")[1]
    assert manage_account.main(["deactivate", username]) == 0
    with pytest.raises(Exception):
        services.accounts.login(username, "new-secret")


def test_week_mastery_reports_each_objective_against_its_threshold(client, services):
    username, auth = register_and_login(client)
    for _ in range(4):
        services.orchestrator.record_graded_response(username, COURSE, mode="quiz", go_id="GO_01_01_001",
                                                     correct=True, score=1.0)
    data = client.get(f"/courses/{COURSE}/mastery", params={"week": 1}, headers=auth).json()
    assert data["total"] == 11 and [lo["lo_id"] for lo in data["learning_objectives"]] == \
        ["LO_01_01", "LO_01_02", "LO_01_03"]
    first = data["learning_objectives"][0]["objectives"][0]
    assert first["go_id"] == "GO_01_01_001" and first["threshold"] == 0.6
    assert first["mastery"] > 0.6 and first["mastered"] is True
    untouched = data["learning_objectives"][2]["objectives"][3]
    assert untouched["mastery"] is None and untouched["mastered"] is False
    assert data["mastered_count"] == 1 and abs(data["completion"] - 1 / 11) < 1e-9
    progress = client.get(f"/courses/{COURSE}/progress", headers=auth).json()
    assert progress["completed_gos"] == ["GO_01_01_001"]  # same rule as week completion
    assert client.get(f"/courses/{COURSE}/mastery", params={"week": 9}, headers=auth).status_code == 400
    assert client.get(f"/courses/{COURSE}/mastery", headers=auth).status_code == 422
