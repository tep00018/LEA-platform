"""The durable event log (B1): what each student action writes, pseudonyms, test accounts,
research exports, and durability. Every test gets its own database (see conftest)."""

import csv
import os
from pathlib import Path

import pytest

from src.services.events import EventRecorder, research_learners
from src.storage.event_log import EventLog
from tests.test_acceptance_phase1 import given_answer, question_writer

COURSE = "DEMO101"
PASSWORD = "correct-horse-1"


@pytest.fixture
def svc(services, fake_llm):
    fake_llm._responder = lambda m: (
        question_writer(m) if ("Return JSON" in m[-1]["content"] or "<answer>" in m[-1]["content"]
                               or "JSON" in m[0]["content"])
        else "Tutor says: what is AI?"
    )
    return services


def register(svc, username, full_name="Robin Quill"):
    svc.accounts.register(username, full_name, PASSWORD, PASSWORD, [COURSE])


def events(svc, **match):
    rows = svc.events.log.query()
    return [r for r in rows if all(r[k] == v for k, v in match.items())]


def set_kind(svc, username, kind):
    svc.redis_client.get_redis().hset(f"user:{username}", "session_kind", kind)
    svc.events.forget_kind(username)


def csv_text(folder: Path) -> str:
    return "".join(p.read_text(encoding="utf-8", errors="ignore") for p in folder.rglob("*.csv"))


def test_a_quiz_writes_start_answers_and_end(svc, username):
    register(svc, username)
    state = svc.quiz.start(username, COURSE, 1)
    question = state.current_question
    svc.quiz.answer(username, given_answer(question, right=False))
    svc.quiz.end(username)

    me = svc.events.pseudonym(username)
    assert [r["type"] for r in events(svc, username_hash=me) if r["type"].startswith("quiz")] == ["quiz_start", "quiz_end"]
    [answer] = events(svc, username_hash=me, type="answer")
    assert answer["mode"] == "quiz" and answer["session_kind"] == "real" and answer["correct"] == 0
    assert answer["go_id"] == question["go_id"] and answer["lo_id"] and answer["week"] == 1
    assert answer["kc_version"] == svc.registry.kc_version(COURSE) and len(answer["kc_version"]) == 12
    assert question["text"][:40] in answer["payload_json"] and '"question_number": 1' in answer["payload_json"]
    assert events(svc, username_hash=me, type="learner_state")  # the adaptive assessment
    end = events(svc, username_hash=me, type="quiz_end")[0]
    assert '"graded": 1' in end["payload_json"] and '"correct": 0' in end["payload_json"]


def test_learners_are_pseudonymous(svc, username):
    register(svc, username)
    svc.quiz.start(username, COURSE, 1)
    svc.tutor.start(username, COURSE, 1)
    svc.tutor.respond(username, "RIGHT answer: AI is machines doing tasks that need intelligence")
    db = Path(os.environ["LEA_EVENTS_DB"])
    raw = b"".join(p.read_bytes() for p in (db, Path(f"{db}-wal")) if p.exists())
    assert b"quiz_start" in raw and b"tutor_start" in raw
    assert username.encode() not in raw
    assert svc.events.pseudonym(username) != svc.events.pseudonym(username + "x")
    other = EventRecorder(None, "another-salt")
    assert other.pseudonym(username) != svc.events.pseudonym(username)  # the salt matters


def test_a_tutor_session_writes_start_replies_and_end(svc, username):
    register(svc, username)
    svc.tutor.start(username, COURSE, 1)
    svc.tutor.respond(username, "RIGHT answer: AI is machines doing tasks that need intelligence")
    svc.tutor.end(username)

    me = svc.events.pseudonym(username)
    types = [r["type"] for r in events(svc, username_hash=me) if r["type"] in ("tutor_start", "answer", "tutor_end")]
    assert types == ["tutor_start", "answer", "tutor_end"]
    [reply] = events(svc, username_hash=me, type="answer")
    assert reply["mode"] == "tutor" and reply["correct"] is None  # the diagnostic opener isn't graded
    assert '"diagnostic": true' in reply["payload_json"] and '"consecutive_incorrect"' in reply["payload_json"]
    assert '"youtube_shown": false' in reply["payload_json"]


def test_chat_questions_are_kept_with_the_students_own_name_removed(svc, username, fake_llm):
    register(svc, username, full_name="Robin Quill")
    fake_llm._responder = lambda m: "Machine learning is learning from data."
    svc.chat.send(username, COURSE, 1, f"I'm Robin Quill ({username}). What is machine learning?")

    [question] = events(svc, username_hash=svc.events.pseudonym(username), type="chat_question")
    assert question["mode"] == "chat" and question["week"] == 1
    assert "Robin" not in question["payload_json"] and "Quill" not in question["payload_json"]
    assert username not in question["payload_json"] and "What is machine learning?" in question["payload_json"]
    assert "not fully anonymised" in question["payload_json"]


def test_test_accounts_are_tagged_and_kept_out_of_the_research_csvs(svc, username, data_copy):
    register(svc, username)
    set_kind(svc, username, "test")
    svc.quiz.start(username, COURSE, 1)
    svc.tutor.start(username, COURSE, 1)
    svc.tutor.respond(username, "RIGHT answer: AI is machines doing tasks that need intelligence")

    mine = events(svc, username_hash=svc.events.pseudonym(username))
    assert mine and {r["session_kind"] for r in mine} == {"test"}
    assert username not in csv_text(data_copy / "decision_logs") + csv_text(data_copy / "motivation_logs")


def test_real_accounts_still_reach_the_research_csvs(svc, username, data_copy):
    register(svc, username)
    svc.quiz.start(username, COURSE, 1)
    assert username in csv_text(data_copy / "motivation_logs")  # unchanged from before B1


def test_research_export_has_only_consented_real_learners(svc, tmp_path):
    names = {k: f"{k}_{os.urandom(3).hex()}" for k in ("agreed", "declined", "tester", "sim")}
    for name in names.values():
        register(svc, name)
    conn = svc.redis_client.get_redis()
    conn.hset(f"user:{names['agreed']}", "research_consent", "true")
    conn.hset(f"user:{names['declined']}", "research_consent", "false")
    conn.hset(f"user:{names['tester']}", "research_consent", "true")
    set_kind(svc, names["tester"], "test")
    set_kind(svc, names["sim"], "simulated")
    for name in names.values():
        svc.quiz.start(name, COURSE, 1)
    svc.events.staff("host:admin", "account_set_kind", payload={"username": names["tester"]})

    learners = research_learners(svc.events)
    real = tmp_path / "real.csv"
    svc.events.log.export_csv(real, kinds=["real", "test"], learners=learners)  # test is never exported
    rows = list(csv.DictReader(real.open(encoding="utf-8")))
    assert rows and {r["username_hash"] for r in rows} == {svc.events.pseudonym(names["agreed"])}
    assert {r["session_kind"] for r in rows} == {"real"} and "actor" not in rows[0]

    sim = tmp_path / "sim.csv"
    svc.events.log.export_csv(sim, kinds=["simulated"], learners=learners)
    assert {r["username_hash"] for r in csv.DictReader(sim.open(encoding="utf-8"))} == {svc.events.pseudonym(names["sim"])}
    with pytest.raises(ValueError):
        svc.events.log.export_csv(tmp_path / "x.csv", kinds=["test"])


def test_the_log_survives_a_restart(tmp_path):
    path = tmp_path / "events.db"
    log = EventLog(path)
    log.append(type="answer", session_kind="real", course=COURSE, username_hash="abc", mode="quiz", correct=True)
    log.close()
    reopened = EventLog(path)
    reopened.append(type="answer", session_kind="real", course=COURSE, username_hash="abc", mode="quiz", correct=False)
    assert [(r["id"], r["correct"]) for r in reopened.query()] == [(1, 1), (2, 0)]


def test_a_broken_log_never_breaks_a_student(svc, username):
    register(svc, username)
    svc.events.log.close()  # every write now fails
    state = svc.quiz.start(username, COURSE, 1)
    assert state.status == "question" and svc.events.log.failed_writes > 0


def test_without_a_salt_the_log_is_off_and_lea_still_works(monkeypatch, redis_url, fake_llm, username):
    monkeypatch.delenv("LEA_EVENT_SALT")
    monkeypatch.setattr("src.mcp.tool_registry.RAGRetrievalTool", __import__("tests.fakes").fakes.StubRAGTool)
    from src.services.container import build_services

    services = build_services(redis_url, openai_client=fake_llm)
    assert services.events.enabled is False
    register(services, username)
    fake_llm._responder = lambda m: question_writer(m)
    assert services.quiz.start(username, COURSE, 1).status == "question"


def test_manage_account_sets_kind_and_consent_and_audits_it(svc, username, monkeypatch):
    register(svc, username)
    import scripts.manage_account as manage

    assert manage.main(["set-kind", username, "test"]) == 0
    assert manage.main(["consent", username, "yes"]) == 0
    conn = svc.redis_client.get_redis()
    assert conn.hget(f"user:{username}", "session_kind") == "test"
    assert conn.hget(f"user:{username}", "research_consent") == "true"
    assert manage.main(["consent", username, "unset"]) == 0
    assert conn.hget(f"user:{username}", "research_consent") is None
    with pytest.raises(SystemExit):
        manage.main(["set-kind", username, "teacher"])

    audit = EventLog(os.environ["LEA_EVENTS_DB"]).query("actor IS NOT NULL")
    assert [r["type"] for r in audit] == ["account_set_kind", "account_consent", "account_consent"]
    assert all(r["actor"].startswith("host:") and username in r["payload_json"] for r in audit)



def test_manage_account_delete_removes_every_key_of_the_account(svc, username):
    register(svc, username)
    other = username + "x"
    register(svc, other)
    svc.quiz.start(username, COURSE, 1)
    conn = svc.redis_client.get_redis()
    import scripts.manage_account as manage

    assert manage.account_keys(conn, username) and f"user:{username}" in manage.account_keys(conn, username)
    assert manage.main(["delete", username, "--yes"]) == 0
    assert manage.account_keys(conn, username) == [] and conn.exists(f"user:{other}")
    [audit] = EventLog(os.environ["LEA_EVENTS_DB"]).query("actor IS NOT NULL")
    assert audit["type"] == "account_delete"
