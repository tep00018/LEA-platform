"""Phase 2 robustness: research-log rows, lock renewal, session replacement, consolidation."""

import csv
import json
import time

import pytest

from src.storage.locks import LockBusy, redis_lock
from tests.test_services import COURSE, WEEK1_GOS, answer_current, svc  # noqa: F401 (fixture)


def _rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_research_logs_are_written_with_plain_values(svc, username, data_copy):  # noqa: F811
    state = svc.quiz.start(username, COURSE, 1)
    answer_current(svc, username, state, right=False)

    metrics = [r for f in (data_copy / "motivation_logs").glob("motivation_metrics_*.csv") for r in _rows(f)
               if r["username"] == username]
    assert [r["mode"] for r in metrics] == ["quiz", "quiz"]  # quiz start, then the answer
    assert metrics[-1]["persistence_level"] in {
        "early_abandonment", "decreased_persistence", "maintains_persistence", "enhanced_persistence"}
    assert metrics[-1]["week"] == "1"
    float(metrics[-1]["cognitive_load"]), float(metrics[-1]["zpd_score"])

    decisions = [r for r in _rows(data_copy / "decision_logs" / "cognitive_load_decisions.csv")
                 if r["username"] == username]
    assert [r["mode"] for r in decisions] == ["quiz", "quiz"]
    assert json.loads(decisions[-1]["session_context"])["question_number"] == 1
    scaffolding = [r for r in _rows(data_copy / "decision_logs" / "scaffolding_decisions.csv")
                   if r["username"] == username]
    assert scaffolding and scaffolding[-1]["go_id"] == state.current_question["go_id"]


def test_lock_is_renewed_while_work_runs(svc):  # noqa: F811
    client = svc.redis_client
    with redis_lock(client, "test:renew", timeout=0.3, wait=0, keep_alive=True):
        time.sleep(1.0)  # three times the lock timeout
        with pytest.raises(LockBusy):
            with redis_lock(client, "test:renew", timeout=0.3, wait=0):
                pass
    with redis_lock(client, "test:renew", timeout=0.3, wait=0):  # released afterwards
        pass


def test_replacing_an_unfinished_quiz_keeps_a_completed_week(svc, username):  # noqa: F811
    for go in WEEK1_GOS:
        for _ in range(4):
            svc.orchestrator.record_graded_response(username, COURSE, mode="quiz", go_id=go, correct=True, score=1.0)
    svc.accounts.auth.redis_client.update_user_progress(username=username, course=COURSE, week=1, completion=0.0)

    state = svc.quiz.start(username, COURSE, 1)
    assert answer_current(svc, username, state, right=True).week_ready
    svc.quiz.start(username, COURSE, 2)  # the learner picks week 2 without finishing
    assert svc.progress.current_week(username, COURSE) == 2


def test_consolidation_summarises_and_keeps_newer_memories(svc, username, fake_llm):  # noqa: F811
    from src.storage.consolidation_worker import MemoryConsolidationWorker

    fake_llm._responder = lambda m: "Session summary."
    client = svc.redis_client
    conn = client.get_redis()
    for i in range(5):
        client.store_short_term_memory(username=username, interaction_type="chat", content={"message": f"q{i}"})
    session_id = client.get_active_session(username)
    key = f"memory:short:{username}:{session_id}"
    conn.rpush(key, "not json")  # an unreadable entry is skipped, not fatal

    worker = MemoryConsolidationWorker(client, "sk-test")
    original = worker._generate_summary

    def summary_then_new_memory(memories):
        # A memory arriving while the summary is written must survive the cleanup
        client.store_short_term_memory(username=username, interaction_type="chat", content={"message": "late"})
        return original(memories)

    worker._generate_summary = summary_then_new_memory
    assert worker._consolidate_session(username, session_id)
    remaining = [json.loads(x)["content"]["message"] for x in conn.lrange(key, 0, -1)]
    assert remaining == ["late"]
    assert any(k.startswith(f"memory:long:{username}") for k in conn.keys(f"memory:long:{username}*"))
