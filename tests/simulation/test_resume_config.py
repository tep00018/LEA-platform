"""Resuming a run may raise its limits, never change what its learners do."""

import copy
import json

import pytest

from simulation.manifest import Manifest, resume_changes
from simulation.settings import ConfigError, load


def started(tmp_path, config):
    data = tmp_path / "data" / "kc_models" / "AIML101"
    data.mkdir(parents=True)
    (data / "kc_model_AIML101.json").write_text("{}")
    return Manifest.start(tmp_path, "r1", config, tmp_path / "data", "AIML101")


def test_a_resume_can_raise_the_call_cap_and_it_is_recorded(tmp_path):
    original = load(overrides={"pilot": True, "usage_credits_confirmed_off": True})
    m = started(tmp_path, original)
    assert m.data["config"]["claude"]["max_calls_per_run"] == 400
    raised = copy.deepcopy(original)
    raised["claude"]["max_calls_per_run"] = 900
    again = Manifest.start(tmp_path, "r1", raised, tmp_path / "data", "AIML101")
    assert again.data["started_at"] == m.data["started_at"]  # the original record is kept
    assert again.data["config"]["claude"]["max_calls_per_run"] == 900  # what `judge` reads back
    assert again.data["config_hash"] != m.data["config_hash"]
    change = again.data["resumes"][-1]["changed"]
    assert change == {"claude.max_calls_per_run": {"from": 400, "to": 900}}
    assert json.loads((tmp_path / "manifest.json").read_text())["config"]["claude"]["max_calls_per_run"] == 900


def test_a_resume_with_nothing_changed_records_nothing_changed(tmp_path):
    config = load(overrides={"pilot": True})
    started(tmp_path, config)
    assert Manifest.start(tmp_path, "r1", config, tmp_path / "data", "AIML101").data["resumes"][-1]["changed"] == {}


@pytest.mark.parametrize("path,value", [
    (("seed",), 1),
    (("scale", "learners_per_profile"), 9),
    (("scale", "weeks"), [1, 2]),
    (("learner", "difficulty_jitter_sd"), 0.9),
    (("profiles", "novice_variable", "theta"), 0.0),
    (("claude", "student_model"), "sonnet"),
    (("course",), "ZZZ999"),
])
def test_a_resume_that_would_change_the_learners_is_refused(tmp_path, path, value):
    original = load(overrides={"pilot": True})
    started(tmp_path, original)
    changed = copy.deepcopy(original)
    node = changed
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(ConfigError, match="can't be resumed"):
        Manifest.start(tmp_path, "r1", changed, tmp_path / "data", "AIML101")
    assert Manifest(tmp_path / "manifest.json").data["config"] == original  # the saved config is untouched


def test_settings_added_since_the_run_began_are_allowed_and_recorded():
    old = load(overrides={"pilot": True})
    del old["claude"]["student_max_thinking_tokens"]
    del old["metrics"]
    changes = resume_changes(old, load(overrides={"pilot": True}))
    assert changes["claude.student_max_thinking_tokens"] == {"from": None, "to": 0}
    assert "metrics.tutor_reply_word_limit" in changes
