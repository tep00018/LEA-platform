"""S5: calibration and sizing (plan), and the refusal to start a run that doesn't fit."""

import json

import pytest
import yaml

from simulation import harness
from simulation.llm.usage_guard import ClaudeStop, UsageLedger
from simulation.settings import load
from simulation.sizing import calibrate, estimate, fit, pilot_rates, plan


@pytest.fixture
def pilot(tmp_path):
    run = tmp_path / "pilot-1"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"run_id": "pilot-1", "learner_weeks_done": 6,
                                                   "openai": {"usd": 0.60}}))
    (run / "events.jsonl").write_text("\n".join(json.dumps({"kind": "learner_week", "seconds": 600}) for _ in range(6)))
    ledger = UsageLedger(tmp_path / "ledger.jsonl")
    for role, calls, usd in (("student", 180, 0.0005), ("judge", 30, 0.05), ("second_judge", 3, 0.25)):
        for _ in range(calls):
            ledger.append({"ts": "2026-09-26T00:00:00+00:00", "run_id": "pilot-1", "role": role, "cost_usd": usd,
                           "input_tokens": 100, "output_tokens": 50})
    ledger.append({"ts": "2026-09-26T00:00:00+00:00", "run_id": "other", "role": "student", "cost_usd": 9})
    return run, ledger


def test_pilot_rates_are_per_learner_week(pilot):
    run, ledger = pilot
    rates = pilot_rates(run, ledger)
    assert rates["learner_weeks"] == 6 and rates["openai_usd_per_learner_week"] == pytest.approx(0.1)
    assert rates["per_learner_week"]["student"]["calls"] == 30
    assert rates["per_learner_week"]["judge"]["usd"] == pytest.approx(0.25)
    assert rates["seconds_per_learner_week"] == 600


def test_calibration_from_usage_percentages(tmp_path):
    out = calibrate(3.0, {"five_hour": 40, "seven_day": 20}, {"five_hour": 55, "seven_day": 23}, "Max 20x",
                    tmp_path / "allowance.yaml")
    assert out["five_hour_usd"] == 20.0 and out["weekly_usd"] == 100.0
    assert yaml.safe_load((tmp_path / "allowance.yaml").read_text())["plan"] == "Max 20x"
    with pytest.raises(ValueError, match="didn't move"):
        calibrate(3.0, {"five_hour": 40, "seven_day": 20}, {"five_hour": 41, "seven_day": 20}, "x", tmp_path / "a.yaml")


def test_estimates_scale_with_learners_weeks_and_judged_share(pilot):
    run, ledger = pilot
    rates = pilot_rates(run, ledger)
    config = load(overrides={"scale": {"learners_per_profile": 8, "weeks": [1, 2, 3, 4, 5, 6]}})
    full = estimate(config, rates)
    assert full["learner_weeks"] == 288 and full["openai_usd"] == pytest.approx(28.8)
    assert full["claude"]["by_role"]["student"]["calls"] == 30 * 288
    half = estimate(config, rates, tutor_share=0.5)
    assert half["claude"]["by_role"]["judge"]["usd"] == pytest.approx(full["claude"]["by_role"]["judge"]["usd"] / 2)
    assert half["claude"]["by_role"]["student"] == full["claude"]["by_role"]["student"]


def test_fit_and_proposed_scale_downs_in_the_plans_order(pilot):
    run, ledger = pilot
    rates = pilot_rates(run, ledger)
    config = load(overrides={"scale": {"learners_per_profile": 8, "weeks": [1, 2, 3, 4, 5, 6]}})
    roomy = plan(config, rates, {"weekly_usd": 10_000, "five_hour_usd": 2_000})
    assert roomy["proposed"]["fits"] and not roomy["alternatives"]
    tight = plan(config, rates, {"weekly_usd": 60, "five_hour_usd": 10})
    assert not tight["proposed"]["fits"]
    changes = [a["change"] for a in tight["alternatives"]]
    assert changes[0].startswith("judge a 50%") and tight["alternatives"][-1]["fits"]
    if len(changes) > 1:
        assert changes[1].startswith("fewer weeks")
    f = fit(estimate(config, rates), config, {"weekly_usd": 100, "five_hour_usd": 20})
    assert f["budget_per_week_usd"] == 50 and f["days"] >= 1


def test_a_run_that_does_not_fit_refuses_to_start(pilot, tmp_path, monkeypatch):
    run, ledger = pilot
    monkeypatch.setattr(harness, "RUNS_DIR", run.parent)
    monkeypatch.setattr(harness, "LEDGER", ledger.path)
    allowance = tmp_path / "allowance.yaml"
    allowance.write_text(yaml.safe_dump({"weekly_usd": 60, "five_hour_usd": 10}))
    monkeypatch.setattr(harness, "ALLOWANCE", allowance)
    config = load(overrides={"usage_credits_confirmed_off": True, "sizing_from": "pilot-1",
                             "claude": {"per_5h_budget": 5, "per_week_budget": 30},
                             "scale": {"learners_per_profile": 8, "weeks": [1, 2, 3, 4, 5, 6]}})
    with pytest.raises(ClaudeStop, match="max_days_per_run"):
        harness.check_fits(config)
    with pytest.raises(ClaudeStop, match="sizing_from"):
        harness.check_fits({**config, "sizing_from": None})
    small = load(overrides={"usage_credits_confirmed_off": True, "sizing_from": "pilot-1",
                            "scale": {"learners_per_profile": 1, "weeks": [1]}})
    assert harness.check_fits(small)["proposed"]["fits"]
