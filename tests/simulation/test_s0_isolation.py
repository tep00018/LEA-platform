"""S0: a simulation run can't reach real Redis or write under data/ (docs/simulation/PLAN.md)."""

import os
import sqlite3
import uuid

import pytest
import redis

from simulation.isolation import FAKE_REDIS_URL, REAL_DATA, IsolationError, RunContext
from simulation.manifest import Manifest
from simulation.settings import load
from tests.test_acceptance_phase1 import given_answer, question_writer

REAL_LOOKING_URL = "redis://real-redis.example.invalid:6379/0"


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv("REDIS_URL", REAL_LOOKING_URL)  # as if .env had been loaded
    return RunContext(f"test-{uuid.uuid4().hex[:6]}", runs_dir=tmp_path / "runs")


def test_the_run_gets_its_own_copy_of_the_course_and_event_log(run):
    with run as ctx:
        assert os.environ["LEA_DATA_DIR"] == str(ctx.data_dir)
        assert os.environ["LEA_EVENTS_DB"] == str(ctx.events_db)
        assert os.environ["LEA_EVENT_SALT"] and os.environ["REDIS_URL"] == FAKE_REDIS_URL
        assert (ctx.data_dir / "kc_models" / "AIML101" / "kc_model_AIML101.json").exists()
        assert (ctx.data_dir / "chroma_data" / "AIML101").is_dir()
        assert ctx.claude_cwd.is_dir() and not any(ctx.claude_cwd.iterdir())
    assert os.environ["REDIS_URL"] == REAL_LOOKING_URL  # restored


def test_the_youtube_key_never_reaches_a_run(run, monkeypatch, tmp_path):
    """A run made real YouTube searches with the researcher's key (quota exhausted, key in a logged URL)."""
    from dotenv import load_dotenv

    monkeypatch.setenv("YOUTUBE_API_KEY", "AIza-not-a-real-key")
    dotenv = tmp_path / ".env"
    dotenv.write_text("YOUTUBE_API_KEY=AIza-from-dotenv" + chr(10))
    with run:
        assert os.environ["YOUTUBE_API_KEY"] == ""
        load_dotenv(dotenv)  # LEA's modules call load_dotenv(); it must not bring the key back
        assert os.environ["YOUTUBE_API_KEY"] == ""
    assert os.environ["YOUTUBE_API_KEY"] == "AIza-not-a-real-key"  # restored


def test_real_redis_is_refused_and_fakeredis_works(run):
    with run:
        with pytest.raises(IsolationError):
            redis.Redis.from_url(REAL_LOOKING_URL).ping()
        with pytest.raises(IsolationError):
            redis.Redis(host="localhost", port=6379).ping()
        fake = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
        fake.set("k", "v")
        assert fake.get("k") == "v"


def test_writes_under_data_are_refused(run):
    probe = REAL_DATA / f"simulation_probe_{uuid.uuid4().hex}.txt"
    try:
        with run:
            with pytest.raises(IsolationError):
                probe.write_text("no")
            with pytest.raises(IsolationError):
                open(REAL_DATA / "course_profiles" / "AIML101.json", "a").close()
            with pytest.raises(IsolationError):
                os.open(probe, os.O_WRONLY | os.O_CREAT)
            with pytest.raises(IsolationError):
                (REAL_DATA / f"probe_dir_{uuid.uuid4().hex}").mkdir()
            with pytest.raises(IsolationError):
                sqlite3.connect(REAL_DATA / "lea_events.db")
            (REAL_DATA / "course_profiles" / "AIML101.json").read_text()  # reading is fine
        assert not probe.exists()
        probe.write_text("allowed again after the run")  # the guard is off outside a run
    finally:
        probe.unlink(missing_ok=True)


def test_lea_runs_inside_the_run_and_leaves_data_alone(run, monkeypatch, fake_llm):
    """LEA's real services (fake LLM, stub retrieval) write only into the run folder."""
    from tests.fakes import StubRAGTool

    monkeypatch.setattr("src.mcp.tool_registry.RAGRetrievalTool", StubRAGTool)
    fake_llm._responder = lambda m: (
        question_writer(m) if ("Return JSON" in m[-1]["content"] or "<answer>" in m[-1]["content"]
                               or "JSON" in m[0]["content"]) else "Tutor says: what is AI?")
    before = {p: p.stat().st_mtime_ns for p in REAL_DATA.rglob("*") if p.is_file()}
    with run as ctx:
        from src.services.container import build_services

        svc = build_services(ctx.redis_url, openai_client=fake_llm)
        user = "sim_advanced_eager_0"
        svc.tutor.start(user, "AIML101", 1)
        svc.tutor.respond(user, "RIGHT answer: AI is machines doing tasks that need intelligence")
        svc.tutor.respond(user, "RIGHT answer: it learns from data")
        svc.tutor.end(user)
        state = svc.quiz.start(user, "AIML101", 1)
        svc.quiz.answer(user, given_answer(state.current_question, True))
        assert svc.events.session_kind(user) in ("real", "simulated")  # tagged by the driver in S3
        assert svc.redis_client.get_redis().keys(f"*{user}*")  # state is in fakeredis
    after = {p: p.stat().st_mtime_ns for p in REAL_DATA.rglob("*") if p.is_file()}
    assert after == before
    assert ctx.events_db.exists()
    written = {p.parent.name for p in ctx.data_dir.rglob("*.csv")}
    assert "decision_logs" in written


def test_manifest_records_what_the_run_used(run):
    config = load()
    with run as ctx:
        m = Manifest.start(ctx.dir, ctx.run_id, config, ctx.data_dir, "AIML101")
    data = m.data
    assert data["config_hash"] and len(data["kc_model_sha256"]) == 64 and len(data["vector_store_sha256"]) == 64
    assert data["git_commit"] and "openai" in data["packages"] and data["claude"]["temperature"].startswith("not")
    again = Manifest.start(ctx.dir, ctx.run_id, config, ctx.data_dir, "AIML101")
    assert again.data["started_at"] == data["started_at"] and again.data["resumes"]


def test_a_run_id_is_a_plain_folder_name(tmp_path):
    for bad in ("../x", "a/b", "", ".hidden", "c:x"):
        with pytest.raises(ValueError):
            RunContext(bad, runs_dir=tmp_path)
