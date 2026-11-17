"""KC IDs, week progress and scaffolding fading."""

import json

import pytest

from src.core.kc_ids import go_in_week, parent_ids
from src.core.mastery_tracker import MasteryTracker
from src.core.progress_integration import ProgressIntegrationBridge
from src.core.scaffolding_engine import ScaffoldingEngine
from tests.conftest import FIXTURE_DATA

KC = json.loads((FIXTURE_DATA / "kc_models/DEMO101/kc_model_DEMO101.json").read_text())


def test_parent_ids_come_from_the_kc_model():
    assert parent_ids("GO_01_02_003", KC) == ("LO_01_02", 1)


def test_parent_ids_parse_the_naming_scheme_without_a_model():
    assert parent_ids("GO_03_01_001") == ("LO_03_01", 3)
    assert parent_ids("not-a-go") == (None, None)


def test_week_membership_is_exact_not_a_substring_match():
    assert go_in_week("GO_03_01_001", 3)
    assert not go_in_week("GO_03_01_001", 1)  # the old '_01_' substring test said yes


@pytest.fixture
def bridge(lea_redis, fake_llm):
    tracker = MasteryTracker(redis_client=lea_redis)
    return ProgressIntegrationBridge(lea_redis, tracker, kc_model_provider=lambda course: KC)


def _mastery(levels):
    return {"go_masteries": levels, "week_masteries": {}}


def test_week_completion_is_recomputed_not_accumulated(bridge, username):
    week1 = [go["go_id"] for lo in KC["week_navigation"]["week_01"]["learning_objectives"]
             for go in lo["granular_objectives"]]
    summary = _mastery({week1[0]: 0.95, week1[1]: 0.95})
    first = bridge.refresh_week_progress(username, "DEMO101", 1, summary)
    second = bridge.refresh_week_progress(username, "DEMO101", 1, summary)
    assert first["completion"] == pytest.approx(2 / len(week1))
    assert second["completion"] == first["completion"]
    assert second["completion_change"] == 0 and second["newly_completed_gos"] == []


def test_each_objectives_own_threshold_is_used(bridge):
    go = KC["week_navigation"]["week_01"]["learning_objectives"][0]["granular_objectives"][3]
    assert go["mastery_threshold"] == 0.85
    assert bridge.week_status(_mastery({go["go_id"]: 0.84}), "DEMO101", 1)["completed_gos"] == []
    assert bridge.week_status(_mastery({go["go_id"]: 0.86}), "DEMO101", 1)["completed_gos"] == [go["go_id"]]


def test_mastery_in_another_week_does_not_count(bridge):
    week3_go = KC["week_navigation"]["week_03"]["learning_objectives"][0]["granular_objectives"][0]["go_id"]
    assert bridge.week_status(_mastery({week3_go: 1.0}), "DEMO101", 1)["completion"] == 0.0


# --------------------------------------------------------------------------- fading

@pytest.fixture
def engine(lea_redis):
    return ScaffoldingEngine(lea_redis)


def test_fading_holds_while_the_streak_lasts(engine):
    base = engine.get_scaffolding_decision("medium", "medium", "u", "LO_01_01", [])
    faded = engine.get_scaffolding_decision("medium", "medium", "u", "LO_01_01", [True] * base.fade_threshold)
    again = engine.get_scaffolding_decision("medium", "medium", "u", "LO_01_01", [True] * (base.fade_threshold + 1))
    order = ScaffoldingEngine.INTENSITY_LEVELS
    assert order.index(faded.intensity_level) == order.index(base.intensity_level) + 1
    assert again.intensity_level == faded.intensity_level  # the old code dropped back after one call
    assert faded.faded_steps == 1


def test_a_wrong_answer_restores_support(engine):
    base = engine.get_scaffolding_decision("medium", "medium", "u", "LO_01_01", [])
    after_error = engine.get_scaffolding_decision("medium", "medium", "u", "LO_01_01", [True] * 5 + [False])
    assert after_error.intensity_level == base.intensity_level and after_error.faded_steps == 0
