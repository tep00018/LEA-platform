"""B6: student analytics (definitions, suppression, real vs simulated, API)."""

import json

import pytest

from src.onboarding import analytics_compute as C
from src.onboarding.simulate import seed
from tests.conftest import FIXTURE_DATA
from tests.test_api import register_and_login

COURSE = "DEMO101"
DEMO = json.loads((FIXTURE_DATA / "kc_models/DEMO101/kc_model_DEMO101.json").read_text())
GO = next(g for w in DEMO["week_navigation"].values() for lo in w["learning_objectives"] for g in lo["granular_objectives"])


def answer(learner, correct, *, go=GO["go_id"], mode="quiz", score=None, payload=None, i=0):
    return {"type": "answer", "go_id": go, "username_hash": learner, "correct": int(correct), "mode": mode,
            "score": score, "payload_json": json.dumps(payload or {}), "ts": f"2026-09-01T10:00:{i:02d}+00:00"}


def cohort(n, pattern):
    """n learners, each with the given list of outcomes."""
    return [answer(f"s{s}", c, i=k) for s in range(n) for k, c in enumerate(pattern)]


# ---------------------------------------------------------------------------- definitions


def test_fewer_than_five_students_is_not_enough_evidence():
    stats = C.objective_stats(GO, C.graded_attempts(cohort(4, [1, 1, 1]))[GO["go_id"]])
    assert stats["band"] == "insufficient" and stats["suppressed"] is True
    assert stats["students"] is None and stats["first_attempt_accuracy"] is None and stats["graded_attempts"] is None
    assert all(p["error_rate"] is None for p in stats["curve"])


def test_bands_first_attempt_accuracy_and_attempts_to_master():
    go = {**GO, "mastery_threshold": 0.7}
    mastered = C.objective_stats(go, C.graded_attempts(cohort(6, [0, 1, 1, 1]))[go["go_id"]])
    assert mastered["band"] == "mastered" and mastered["students"] == 6
    assert mastered["first_attempt_accuracy"] == 0.0 and mastered["attempts_to_master"] == 4.0  # last three reach 0.7 on attempt 4
    struggling = C.objective_stats(go, C.graded_attempts(cohort(6, [0, 0, 1, 0]))[go["go_id"]])
    assert struggling["band"] == "struggling"
    mixed = cohort(3, [1, 1, 1]) + [answer(f"t{s}", c, i=k) for s in range(3) for k, c in enumerate([0, 1, 1])]  # 0.67: neither
    assert C.objective_stats(go, C.graded_attempts(mixed)[go["go_id"]])["band"] == "developing"


def test_learning_curve_and_its_verdict():
    flat = C.graded_attempts(cohort(6, [0, 0, 0, 0]))[GO["go_id"]]
    points = C.curve(flat)
    assert [p["error_rate"] for p in points] == [1.0, 1.0, 1.0, 1.0] and C.verdict(points) == "flat"
    learning = C.graded_attempts(cohort(6, [0, 0, 1, 1]))[GO["go_id"]]
    assert C.verdict(C.curve(learning)) == "declining"
    pooled = C.course_curve({"a": C.graded_attempts(cohort(3, [0, 0]))[GO["go_id"]],
                             "b": {f"x{i}": [{"correct": 1}] for i in range(3)}})
    assert pooled[0] == {"opportunity": 1, "students": 6, "error_rate": 0.5}
    assert pooled[1]["error_rate"] is None  # only 3 students got a second go
    short = C.graded_attempts(cohort(6, [0, 1]))[GO["go_id"]]
    assert C.verdict(C.curve(short)) is None  # too few points


def test_ungraded_warm_ups_and_other_objectives_do_not_count():
    rows = cohort(6, [1, 1]) + [{**answer("s0", 0), "correct": None}, answer("s0", 0, go="GO_09_09_009")]
    by_go = C.graded_attempts(rows)
    assert len(by_go[GO["go_id"]]["s0"]) == 2 and "GO_09_09_009" in by_go


def test_common_wrong_answers_group_by_the_option_chosen():
    options = ["A) Right", "B) Misconception", "C) Other"]
    rows = [answer(f"s{i}", 0, payload={"response": "B", "options": options}, i=i) for i in range(5)]
    rows += [answer("s9", 0, payload={"response": "C", "options": options})]
    result = C.wrong_answers(C.graded_attempts(rows)[GO["go_id"]])
    assert result["suppressed"] is False and result["students"] == 6
    assert result["answers"][0] == {"answer": "Misconception", "share": round(5 / 6, 3), "count": 5}
    few = C.wrong_answers(C.graded_attempts(rows[:3])[GO["go_id"]])
    assert few == {"suppressed": True, "students": None, "answers": []}


def test_tutor_struggle_counts_streaks_videos_and_stuck_sessions():
    rows = [answer(f"s{i}", 0, mode="tutor", payload={"consecutive_incorrect": 3, "youtube_shown": i < 2,
                                                       "session_id": f"t{i}", "advanced": False}) for i in range(5)]
    rows += [{"type": "tutor_end", "payload_json": json.dumps({"session_id": "t0"}), "username_hash": "s0"}]
    s = C.struggle(rows)[GO["go_id"]]
    assert s == {"streak_students": 5, "video_students": 2, "sessions_left_stuck": 1}


def test_needs_attention_names_its_driver_and_suggests_an_action():
    stats = C.objective_stats(GO, C.graded_attempts(cohort(6, [0, 0, 0, 0]))[GO["go_id"]])
    att = C.attention(stats, None)
    assert att["level"] == "high" and att["driver"] in ("low first-attempt accuracy", "a flat learning curve")
    note = C.suggestion(stats, att, None, "Week01-LectureA-Intro.pptx")
    assert "Week01-LectureA-Intro.pptx" in note
    easy = C.objective_stats(GO, C.graded_attempts(cohort(6, [1, 1, 1]))[GO["go_id"]])
    assert C.attention(easy, None)["level"] == "low" and C.suggestion(easy, C.attention(easy, None), None, None) is None


# ---------------------------------------------------------------------------- API


@pytest.fixture
def teacher(client, services):
    username, headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{username}", "role", "teacher")
    services.staff.add_owner("admin", COURSE, username)
    return username, headers


def test_overview_is_real_students_only_and_suppresses_small_numbers(client, teacher, services):
    _, headers = teacher
    r = client.get(f"/teach/courses/{COURSE}/analytics", headers=headers).json()
    assert r["kind"] == "real" and r["suppressed"] is True and r["students"] is None
    assert all(o["band"] == "insufficient" and o["students"] is None for o in r["objectives"])

    seed(services.events, DEMO, COURSE, students=12, weeks=1)
    real = client.get(f"/teach/courses/{COURSE}/analytics", headers=headers).json()
    assert real["suppressed"] is True  # simulated students never show as real
    sim = client.get(f"/teach/courses/{COURSE}/analytics", params={"kind": "simulated", "week": 1}, headers=headers).json()
    assert sim["students"] == 12 and sim["suppressed"] is False and sim["usage"]["active_students"] == 12
    assert {o["week"] for o in sim["objectives"]} == {1}
    assert sum(sim["bands"].values()) == len(sim["objectives"])
    scores = [o["attention"]["score"] for o in sim["objectives"]]
    assert scores == sorted(scores, reverse=True)  # most in need first
    assert client.get(f"/teach/courses/{COURSE}/analytics", params={"kind": "test"}, headers=headers).status_code == 422


def test_objective_detail_curves_export_and_test_accounts(client, teacher, services):
    _, headers = teacher
    seed(services.events, DEMO, COURSE, students=10, weeks=1, rng_seed=3)
    sim = client.get(f"/teach/courses/{COURSE}/analytics", params={"kind": "simulated"}, headers=headers).json()
    go_id = sim["objectives"][0]["go_id"]
    d = client.get(f"/teach/courses/{COURSE}/analytics/objectives/{go_id}", params={"kind": "simulated"},
                   headers=headers).json()
    assert d["week"] == 1 and d["course_curve"][0]["students"] == 10
    assert d["curve"] and d["curve"][0]["opportunity"] == 1 and d["attention"]["level"] in ("high", "medium", "low")
    assert d["wrong_answers"]["suppressed"] in (True, False) and "struggle" in d
    csv_text = client.get(f"/teach/courses/{COURSE}/analytics/curves.csv", params={"kind": "simulated"},
                          headers=headers).text
    assert csv_text.startswith("KC (granular objective),Objective name,Week,Opportunity,Students,Error rate")
    assert "sim." not in csv_text  # aggregated only
    assert client.get(f"/teach/courses/{COURSE}/analytics/objectives/GO_99_99_999", headers=headers).status_code == 404

    # A test account's activity never reaches analytics, whatever it does
    student, student_headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{student}", "session_kind", "test")
    services.events.forget_kind(student)
    client.post("/quiz", json={"course": COURSE, "week": 1}, headers=student_headers)
    rows = services.analytics.rows(COURSE, "real")
    assert all(r["username_hash"] != services.events.pseudonym(student) for r in rows)


def test_chat_topics_need_five_students_report_agreement_and_hide_small_topics(client, teacher, services, fake_llm):
    _, headers = teacher
    before = client.get(f"/teach/courses/{COURSE}/analytics/chat-topics", params={"kind": "simulated"}, headers=headers).json()
    assert before["result"] is None
    seed(services.events, DEMO, COURSE, students=15, weeks=3, rng_seed=5)
    status = client.get(f"/teach/courses/{COURSE}/analytics/chat-topics", params={"kind": "simulated"}, headers=headers).json()
    assert status["can_run"] and status["usd"] < 0.05
    n = status["questions"]
    go_id = next(iter(DEMO["week_navigation"].values()))["learning_objectives"][0]["granular_objectives"][0]["go_id"]
    fake_llm._responder = lambda m: json.dumps(
        {"topics": [{"label": "Big topic", "go_id": go_id, "questions": list(range(n)), "paraphrases": ["Why?"]},
                    {"label": "Tiny", "go_id": None, "questions": [], "paraphrases": []}]}
        if "group" in m[0]["content"] else {"assignments": {str(i): go_id if i % 4 else None for i in range(n)}})
    r = client.post(f"/teach/courses/{COURSE}/analytics/chat-topics", params={"kind": "simulated"}, headers=headers)
    assert r.status_code == 200, r.text
    result = r.json()
    assert [t["label"] for t in result["topics"]] == ["Big topic"]  # fewer than 5 students: hidden
    assert result["agreement"] == pytest.approx(sum(1 for i in range(n) if i % 4) / n, abs=0.001)
    d = client.get(f"/teach/courses/{COURSE}/analytics/objectives/{go_id}", params={"kind": "simulated"},
                   headers=headers).json()
    assert d["chat_topics"][0]["label"] == "Big topic"


def test_explainer_is_a_draft(client, teacher, fake_llm):
    _, headers = teacher
    fake_llm._responder = lambda m: "Gradient descent moves against the slope."
    r = client.post(f"/teach/courses/{COURSE}/analytics/objectives/{GO['go_id']}/explainer", headers=headers).json()
    assert r["text"] == "Gradient descent moves against the slope." and "never publishes" in r["note"]


def test_views_are_logged_and_other_teachers_are_kept_out(client, teacher, services):
    username, headers = teacher
    client.get(f"/teach/courses/{COURSE}/analytics", headers=headers)
    views = services.events.log.query("type = 'analytics_view'")
    assert views and views[-1]["actor"] == username
    other, other_headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{other}", "role", "teacher")
    assert client.get(f"/teach/courses/{COURSE}/analytics", headers=other_headers).status_code == 403
