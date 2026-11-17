"""Shared fixtures: an in-process Redis (fakeredis) and a test environment.

No test here calls OpenAI: OPENAI_API_KEY is set to a dummy value so clients can be
constructed, and every test only exercises code paths that don't send requests.
"""

from pathlib import Path

import fakeredis
import pytest
import redis

REPO_ROOT = Path(__file__).resolve().parent.parent
# DEMO101, the synthetic course the tests are written against (it left data/ in Phase 6)
FIXTURE_DATA = REPO_ROOT / "tests" / "fixtures" / "data"
# The open course, copied from data/ so its smoke test runs against what is committed
OPEN_COURSE = "AIML101"


FAKE_REDIS_URL = "redis://fake-redis.test:6379/0"
_FAKE_SERVER = fakeredis.FakeServer()


@pytest.fixture(scope="session")
def redis_url():
    """An in-process Redis (fakeredis) reachable through any redis.from_url(FAKE_REDIS_URL).

    In-process fakeredis is used rather than its TCP server, whose replies for missing
    keys the redis client can't parse (which would hide the code's missing-key paths).
    """
    patcher = pytest.MonkeyPatch()
    original = redis.Redis.from_url.__func__

    def from_url(cls, url, **kwargs):
        if str(url).startswith(FAKE_REDIS_URL):
            return fakeredis.FakeRedis(server=_FAKE_SERVER, decode_responses=kwargs.get("decode_responses", False))
        return original(cls, url, **kwargs)

    patcher.setattr(redis.Redis, "from_url", classmethod(from_url))
    yield FAKE_REDIS_URL
    patcher.undo()


@pytest.fixture(scope="session", autouse=True)
def data_copy(tmp_path_factory):
    """Run against a copy of the test data (DEMO101 from tests/fixtures/data, plus AIML101
    from data/), so tests never modify committed files (a Chroma query rewrites the
    store's index files) and never see private courses."""
    import os
    import shutil

    from src.core.course_registry import default_registry

    target = tmp_path_factory.mktemp("lea") / "data"
    shutil.copytree(FIXTURE_DATA, target)
    source = REPO_ROOT / "data"
    for sub in ("kc_models", "chroma_data", "md_docs"):
        shutil.copytree(source / sub / OPEN_COURSE, target / sub / OPEN_COURSE)
    shutil.copy2(source / "course_profiles" / f"{OPEN_COURSE}.json", target / "course_profiles")
    shutil.copy2(source / "metadata" / f"doc_metadata_{OPEN_COURSE}.json", target / "metadata")
    previous = os.environ.get("LEA_DATA_DIR")
    os.environ["LEA_DATA_DIR"] = str(target)
    default_registry.cache_clear()
    yield target
    if previous is None:
        os.environ.pop("LEA_DATA_DIR", None)
    else:
        os.environ["LEA_DATA_DIR"] = previous
    default_registry.cache_clear()


@pytest.fixture(autouse=True)
def test_env(redis_url, monkeypatch, tmp_path):
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    # Every test gets its own event log, so tests can read exactly what they wrote.
    monkeypatch.setenv("LEA_EVENT_SALT", "test-salt-not-secret")
    monkeypatch.setenv("LEA_EVENTS_DB", str(tmp_path / "lea_events.db"))
    # Blank, not deleted: load_dotenv() (called by LEA's modules) never overrides a variable that is
    # already set, so the real key in .env can't come back and make a test search YouTube for real.
    monkeypatch.setenv("YOUTUBE_API_KEY", "")
    yield


# --- Backend fixtures -----------------------------------------------------------------

import uuid  # noqa: E402

from tests.fakes import FakeLLM, StubRAGTool  # noqa: E402


@pytest.fixture
def username():
    return f"student_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def lea_redis(redis_url):
    from src.storage.redis_client import LEARedisClient

    return LEARedisClient(redis_url)


@pytest.fixture
def fake_llm(monkeypatch):
    """Route every OpenAI client LEA creates to one scripted FakeLLM (default reply: 'OK')."""
    llm = FakeLLM()
    factory = lambda *args, **kwargs: llm  # noqa: E731
    import openai

    monkeypatch.setattr(openai, "OpenAI", factory)
    for module in ("src.core.mastery_tracker", "src.quiz.simple_quiz_system", "src.storage.consolidation_worker",
                   "src.services.container"):
        mod = __import__(module, fromlist=["OpenAI"])
        if hasattr(mod, "OpenAI"):
            monkeypatch.setattr(mod, "OpenAI", factory)
    return llm


@pytest.fixture
def mcp_server(lea_redis, monkeypatch, fake_llm):
    monkeypatch.setattr("src.mcp.tool_registry.RAGRetrievalTool", StubRAGTool)
    from src.mcp.mcp_server import LEAMCPServer

    return LEAMCPServer(lea_redis)


@pytest.fixture
def orchestrator(mcp_server, lea_redis):
    from src.core.agent_orchestrator_mcp import LEAOrchestratorMCP
    from src.core.scaffolding_engine import ScaffoldingEngine

    orch = LEAOrchestratorMCP(mcp_server, lea_redis)
    orch.scaffolding_engine = ScaffoldingEngine(lea_redis)
    return orch


@pytest.fixture
def services(redis_url, fake_llm, monkeypatch):
    """The full service container on fakeredis, the scripted LLM and the stub retrieval tool."""
    monkeypatch.setattr("src.mcp.tool_registry.RAGRetrievalTool", StubRAGTool)
    from src.services.container import build_services

    return build_services(redis_url, openai_client=fake_llm)


@pytest.fixture
def client(services, fake_llm):
    """The API over the service container (no background work)."""
    from fastapi.testclient import TestClient

    from src.api.app import create_app
    from tests.test_acceptance_phase1 import question_writer

    fake_llm._responder = lambda m: (
        question_writer(m) if ("Return JSON" in m[-1]["content"] or "<answer>" in m[-1]["content"]
                               or "JSON" in m[0]["content"])
        else "LEA says hello."
    )
    conn = services.redis_client.get_redis()
    for key in conn.keys("ratelimit:*"):  # the in-process Redis is shared by all tests
        conn.delete(key)
    with TestClient(create_app(services, start_background_work=False)) as c:
        yield c
