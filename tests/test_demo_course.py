"""The DEMO101 test course (tests/fixtures/data) is loadable."""

import json

import chromadb

from src.core.kc_model_loader import KCModelLoader
from src.storage.redis_client import LEARedisClient
from tests.conftest import FIXTURE_DATA


def test_demo_kc_model_has_expected_structure():
    path = FIXTURE_DATA / "kc_models/DEMO101/kc_model_DEMO101.json"
    model = json.loads(path.read_text())
    assert "course_info" in model
    assert "week_navigation" in model


def test_kc_loader_loads_demo_course(redis_url):
    loader = KCModelLoader(LEARedisClient(redis_url), module="DEMO101")
    model = loader.load_course_model("DEMO101")
    assert model, "KC model for DEMO101 should load"
    assert model.get("course_info", {}).get("course_code", "DEMO101") == "DEMO101"


def test_demo_vector_store_opens():
    from src.core.course_registry import default_registry

    client = chromadb.PersistentClient(path=str(default_registry().vector_store_path("DEMO101")))
    names = [c if isinstance(c, str) else c.name for c in client.list_collections()]
    assert "DEMO101" in names
    assert client.get_collection("DEMO101").count() >= 2
