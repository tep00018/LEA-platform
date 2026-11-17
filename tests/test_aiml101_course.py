"""Smoke test for AIML101, the open demo course (committed under data/, copied for tests)."""

import json
import re

import chromadb
import pytest

from src.core.course_registry import default_registry
from tests.conftest import REPO_ROOT

CODE = "AIML101"
SOURCES = REPO_ROOT / "data" / "course_sources" / CODE
GENERIC = {"define", "explain", "identify", "understand", "analysis", "application", "utilization", "basics",
           "process", "fundamentals", "structure", "functionality", "techniques", "methods", "mechanics", "steps",
           "execution", "support", "and", "of", "the", "to", "vs", "with", "from", "for", "systems", "system",
           "model", "models", "compare", "differentiate", "distinguish", "implement", "detect", "prevent",
           "mitigation", "strategies", "ai", "ml"}


@pytest.fixture(scope="module")
def model():
    kc = default_registry().kc_model(CODE)
    assert kc, "AIML101's KC model should load"
    return kc


def gos(model):
    return [(week, lo, go) for week in model["week_navigation"].values()
            for lo in week["learning_objectives"] for go in lo["granular_objectives"]]


def test_the_course_loads_with_six_weeks_and_a_valid_profile(model):
    registry = default_registry()
    assert CODE in registry.available_courses()
    weeks = sorted(w["week_number"] for w in model["week_navigation"].values())
    assert 5 <= len(weeks) <= 6 and weeks == list(range(1, len(weeks) + 1))
    profile = registry.profile(CODE)
    assert profile.from_file and profile.name.startswith("Introduction to AI and Machine Learning")
    # allows_code is off for now (research, 2026-09-28): a course-blind coding question built a
    # toy Weak-vs-Strong-AI example on a false premise -- see docs/STATUS.md's open item for a
    # per-GO "does the lesson passage itself contain code" rule instead of this course-wide gate.
    assert not profile.allows_code and profile.code_language is None and profile.discipline == "computing"


def test_objectives_have_titles_unique_ids_and_sane_thresholds(model):
    items = gos(model)
    ids = [go["go_id"] for _, _, go in items]
    assert len(ids) == len(set(ids)) == 63
    lookup = model["quick_lookup"]
    for week, lo, go in items:
        assert re.fullmatch(r"GO_\d{2}_\d{2}_\d{3}", go["go_id"])
        assert lookup["go_by_id"][go["go_id"]]["parent_lo_id"] == lo["lo_id"]
        assert lookup["week_by_lo_id"][lo["lo_id"]]["week_number"] == week["week_number"]
        assert 0.5 <= go["mastery_threshold"] <= 0.85
        # The approved objective text and a short title, not the generator's CamelCase concept names
        assert " " in lo["title"] and 1 <= len(lo["short_title"].split()) <= 5
        assert not re.search(r"[a-z][A-Z]|_", lo["short_title"])


def test_every_objective_has_indexed_content_in_its_week(model):
    """Offline stand-in for retrieval (which needs OpenAI): every week has chunks, and each
    GO's key terms appear in its week's indexed text."""
    store = chromadb.PersistentClient(path=str(default_registry().vector_store_path(CODE)))
    got = store.get_collection(CODE).get(include=["documents", "metadatas"])
    text = {}
    for doc, meta in zip(got["documents"], got["metadatas"]):
        week = int(meta["source_file"][4:6])
        text[week] = text.get(week, "") + " " + doc.lower()
    assert sorted(text) == sorted(w["week_number"] for w in model["week_navigation"].values())
    missing = []
    for week, _, go in gos(model):
        words = [w for w in re.findall(r"[a-z][a-z\-/]+", go["skill_name"].lower()) if len(w) > 1]
        terms = [w for w in words if w not in GENERIC and len(w) > 2] or words
        if not any(t in text[week["week_number"]] or t.rstrip("s") in text[week["week_number"]] for t in terms):
            missing.append(go["go_id"])
    assert missing == []


def test_licences_attribution_and_question_bank(model):
    attribution = (SOURCES / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "392d0df1b2647cbee104942390551f1ed9e072c8" in attribution  # AI for Beginners
    assert "de2d4e12236445198213a0711855e348e7253cd4" in attribution  # ML for Beginners
    for name in ("LICENSE-AI-For-Beginners.txt", "LICENSE-ML-For-Beginners.txt", "LICENSE-ML-For-Beginners-quiz-app.txt"):
        assert "MIT License" in (SOURCES / name).read_text(encoding="utf-8")
    assert not list((REPO_ROOT / "data" / "org_docs" / CODE).glob("*.png"))  # no images

    bank = json.loads((SOURCES / "question_bank.json").read_text(encoding="utf-8"))
    go_week = {go["go_id"]: week["week_number"] for week, _, go in gos(model)}
    assert bank["format"] == "lea-reference-question-bank/1" and len(bank["questions"]) >= 60
    for q in bank["questions"]:
        assert 0 <= q["correct_index"] < len(q["options"]) and q["type"] in ("multiple_choice", "true_false")
        assert go_week[q["go_id"]] == q["week"] and q["tagging"]["reviewed"] is False
