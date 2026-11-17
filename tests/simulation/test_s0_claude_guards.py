"""S0: the Claude CLI client and the subscription guards (docs/simulation/PLAN.md, section 6).

A fake ``claude`` (tests/simulation/fake_claude.py) scripts the stream-json output,
including ``rate_limit_event`` lines. No network.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from simulation.llm.claude_cli import ClaudeCallError, ClaudeCLI, subprocess_env
from simulation.llm.usage_guard import (ClaudePause, ClaudeStop, GuardSettings, UsageGuard, UsageLedger, preflight,
                                        run_with_pauses)
from simulation.settings import ConfigError, load

FAKE = [sys.executable, str(Path(__file__).with_name("fake_claude.py"))]
T0 = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


def settings(**over):
    base = dict(per_5h_budget=None, per_week_budget=None, pause_at_5h=0.8, pause_at_week=0.6, run_hours=None,
                max_calls_per_run=400)
    return GuardSettings(**{**base, **over})


@pytest.fixture
def make(tmp_path):
    def make(scenario=None, clock=None, run_id="run1", **over):
        cwd = tmp_path / "claude_cwd"
        cwd.mkdir(exist_ok=True)
        if scenario is not None:
            (cwd / "scenario.json").write_text(json.dumps(scenario))
        ledger = UsageLedger(tmp_path / "ledger.jsonl")
        guard = UsageGuard(settings(**over), ledger, run_id, events_path=tmp_path / "usage_events.jsonl",
                           clock=clock or Clock())
        return ClaudeCLI(guard, ledger, cwd, executable=FAKE, concurrency=2)
    return make


def calls(client):
    return [json.loads(x) for x in (client.cwd / "calls.jsonl").read_text().splitlines()]


def ask(client, **kw):
    return client.call("Say OK", system_prompt="Role prompt", model="haiku", role="student", **kw)


# ---------------------------------------------------------------------------- the client


def test_anthropic_credentials_and_host_session_variables_never_reach_claude(make, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL",
                 "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "anthropic_api_key"):
        monkeypatch.setenv(name, "must-not-leak")
    env = subprocess_env()
    assert not [k for k in env if k.upper().startswith(("ANTHROPIC", "CLAUDE"))]
    assert "PATH" in {k.upper() for k in env}
    client = make([{}])
    ask(client)
    seen = {k.upper() for k in calls(client)[0]["env"]}
    assert not [k for k in seen if k.startswith(("ANTHROPIC", "CLAUDE"))]


def test_extended_thinking_is_switched_off_only_when_asked_and_recorded(make, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    assert "MAX_THINKING_TOKENS" not in subprocess_env()
    assert subprocess_env(max_thinking_tokens=0)["MAX_THINKING_TOKENS"] == "0"
    assert subprocess_env(max_thinking_tokens=2048)["MAX_THINKING_TOKENS"] == "2048"
    assert not [k for k in subprocess_env(max_thinking_tokens=0) if k.upper().startswith(("ANTHROPIC", "CLAUDE"))]
    off, default = make([{}], run_id="think-off"), make([{}], run_id="think-default")
    off.call("hi", system_prompt="r", model="haiku", role="student", max_thinking_tokens=0)
    default.call("hi", system_prompt="r", model="haiku", role="judge")
    seen = calls(off)  # both clients share one working directory: the calls arrive in order
    assert "MAX_THINKING_TOKENS" in seen[0]["env"] and "MAX_THINKING_TOKENS" not in seen[1]["env"]
    row = off.ledger.records()[0]
    assert row["max_thinking_tokens"] == 0 and "thinking_tokens" in row


def test_a_clean_call_uses_the_subscription_flags_and_stdin(make):
    client = make([{"result": "OK"}])
    result = ask(client, effort="low", json_schema={"type": "object"})
    argv = calls(client)[0]["argv"]
    assert "-p" in argv and "--safe-mode" in argv and "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    assert argv[argv.index("--tools") + 1] == "" and argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--effort") + 1] == "low" and "--json-schema" in argv
    assert "--bare" not in argv and "Say OK" not in " ".join(argv)  # the prompt goes through stdin
    assert calls(client)[0]["stdin"] == "Say OK"
    assert not list(client.cwd.glob("*.md"))  # the system prompt file is removed
    assert result.text == "OK" and result.model.startswith("claude-haiku") and result.cost_usd == 0.001
    row = client.ledger.records()[0]
    assert row["role"] == "student" and row["model"] == result.model and row["input_tokens"] == 10


def test_structured_output_is_returned(make):
    result = ask(make([{"structured": {"verdict": "yes"}}]), json_schema={"type": "object"})
    assert result.structured == {"verdict": "yes"}


def test_an_api_key_login_stops_the_run_and_nothing_falls_back(make):
    client = make([{"api_key_source": "ANTHROPIC_API_KEY"}, {}])
    with pytest.raises(ClaudeStop, match="apiKeySource"):
        ask(client)
    assert len(client.ledger.records()) == 1  # recorded, then stopped
    with pytest.raises(ClaudeStop):
        ask(client)  # stays stopped
    assert len(calls(client)) == 1


def test_a_call_without_an_init_event_stops(make):
    with pytest.raises(ClaudeStop, match="init"):
        ask(make([{"init": False}]))


def test_a_failed_call_is_an_error_not_a_default(make):
    with pytest.raises(ClaudeCallError):
        ask(make([{"is_error": True, "result": "model overloaded", "exit": 1}]))


def test_billing_errors_stop_the_run(make):
    with pytest.raises(ClaudeStop, match="billing"):
        ask(make([{"is_error": True, "result": "You have reached your spend limit for usage credits", "exit": 1}]))


# ---------------------------------------------------------------------------- Anthropic's signals


def test_overage_in_use_stops_everything_at_once(make):
    client = make([{"rate_limits": [{"status": "allowed", "isUsingOverage": True, "rateLimitType": "five_hour"}]}, {}])
    with pytest.raises(ClaudeStop, match="isUsingOverage"):
        ask(client)
    with pytest.raises(ClaudeStop):
        ask(client)
    assert len(calls(client)) == 1
    logged = [json.loads(x) for x in Path(client.guard.events_path).read_text().splitlines()]
    assert logged[0]["kind"] == "rate_limit_event" and logged[-1]["kind"] == "stop"


def test_rejected_pauses_until_reset_plus_two_minutes_then_resumes(make):
    clock = Clock()
    resets = T0 + timedelta(hours=2)
    client = make([{"rate_limits": [{"status": "rejected", "rateLimitType": "five_hour",
                                     "resetsAt": resets.timestamp()}]}, {"result": "back"}], clock=clock)
    with pytest.raises(ClaudePause) as paused:
        ask(client)
    assert paused.value.until == resets + timedelta(minutes=2)
    with pytest.raises(ClaudePause):
        ask(client)  # still paused: nothing is sent
    assert len(calls(client)) == 1
    clock.now = resets + timedelta(minutes=3)
    assert ask(client).text == "back"


def test_warnings_pause_at_the_thresholds_and_unknown_utilization_is_not_safe(make):
    resets = (T0 + timedelta(hours=1)).timestamp()
    low = make([{"rate_limits": [{"status": "allowed_warning", "rateLimitType": "five_hour", "utilization": 0.5,
                                  "resetsAt": resets}]}])
    assert ask(low).text == "OK"
    for info in ({"status": "allowed_warning", "rateLimitType": "five_hour", "utilization": 0.85},
                 {"status": "allowed_warning", "rateLimitType": "seven_day", "utilization": 0.65},
                 {"status": "allowed_warning", "rateLimitType": "five_hour"}):
        client = make([{"rate_limits": [{**info, "resetsAt": resets}]}], run_id=str(info))
        with pytest.raises(ClaudePause):
            ask(client)
    weekly_ok = make([{"rate_limits": [{"status": "allowed_warning", "rateLimitType": "seven_day",
                                        "utilization": 0.55, "resetsAt": resets}]}], run_id="w")
    assert ask(weekly_ok).text == "OK"


def test_per_window_utilization_on_every_event_pauses_at_the_thresholds(make):
    """As seen live (Claude Code 2.1.282): status allowed, with unifiedWindows."""
    five_reset, week_reset = (T0 + timedelta(hours=2)).timestamp(), (T0 + timedelta(days=3)).timestamp()
    seen_live = {"status": "allowed", "resetsAt": five_reset, "rateLimitType": "five_hour",
                 "overageStatus": "rejected", "overageDisabledReason": "out_of_credits", "isUsingOverage": False,
                 "unifiedWindows": {"five_hour": {"utilization": 0.4, "resetsAt": five_reset},
                                    "seven_day": {"utilization": 0.24, "resetsAt": week_reset}}}
    assert ask(make([{"rate_limits": [seen_live]}])).text == "OK"
    busy_week = {**seen_live, "unifiedWindows": {"five_hour": {"utilization": 0.4, "resetsAt": five_reset},
                                                 "seven_day": {"utilization": 0.61, "resetsAt": week_reset}}}
    with pytest.raises(ClaudePause, match="seven_day") as paused:
        ask(make([{"rate_limits": [busy_week]}], run_id="week"))
    assert paused.value.until == datetime.fromtimestamp(week_reset, timezone.utc)
    busy_5h = {**seen_live, "unifiedWindows": {"five_hour": {"utilization": 0.8, "resetsAt": five_reset}}}
    with pytest.raises(ClaudePause, match="five_hour"):
        ask(make([{"rate_limits": [busy_5h]}], run_id="5h"))


# ---------------------------------------------------------------------------- our own budgets


def test_the_rolling_5_hour_and_weekly_budgets_pause_until_spend_ages_out(make):
    clock = Clock()
    client = make([{"cost": 0.6}], clock=clock, per_5h_budget=1.0, per_week_budget=5.0)
    ask(client)
    clock.sleep(60)
    ask(client)  # spent 1.2 in the window now
    with pytest.raises(ClaudePause, match="per_5h_budget") as paused:
        ask(client)
    assert paused.value.until == T0 + timedelta(hours=5, seconds=1)  # when the first call ages out
    clock.now = paused.value.until
    ask(client)

    week = make([{"cost": 3.0}], clock=Clock(), run_id="week", per_week_budget=5.0)
    ask(week)
    ask(week)
    with pytest.raises(ClaudePause, match="per_week_budget"):
        ask(week)


def test_run_hours_are_respected(make):
    local_noon = datetime(2026, 9, 26, 12, 0).astimezone()
    clock = Clock(local_noon.astimezone(timezone.utc))
    client = make([{}], clock=clock, run_hours="23:00-07:00")
    with pytest.raises(ClaudePause) as paused:
        ask(client)
    assert paused.value.until.astimezone().hour == 23
    clock.now = paused.value.until + timedelta(minutes=5)
    ask(client)


def test_the_call_cap_is_a_hard_stop(make):
    client = make([{}], max_calls_per_run=2)
    ask(client)
    ask(client)
    with pytest.raises(ClaudeStop, match="max_calls_per_run"):
        ask(client)


def test_a_paused_run_resumes_afterwards(make):
    clock = Clock()
    resets = (T0 + timedelta(minutes=30)).timestamp()
    client = make([{"rate_limits": [{"status": "rejected", "rateLimitType": "five_hour", "resetsAt": resets}]},
                   {"result": "resumed"}], clock=clock)
    done = []

    def learner_week():
        done.append(ask(client).text)
        return done[-1]

    assert run_with_pauses(learner_week, sleep=clock.sleep, clock=clock) == "resumed"
    assert clock.now >= datetime.fromtimestamp(resets, timezone.utc) + timedelta(minutes=2)


# ---------------------------------------------------------------------------- starting a run


def test_no_run_starts_without_the_usage_credits_confirmation(tmp_path):
    allowance = tmp_path / "allowance.yaml"
    config = load(overrides={"pilot": True})
    assert config["usage_credits_confirmed_off"] is False  # the default until the owner says so
    with pytest.raises(ClaudeStop, match="Usage credits"):
        preflight(config, allowance)
    preflight(load(overrides={"pilot": True, "usage_credits_confirmed_off": True}), allowance)  # a pilot may run
    main = load(overrides={"usage_credits_confirmed_off": True})
    with pytest.raises(ClaudeStop, match="calibration"):
        preflight(main, allowance)
    allowance.write_text("weekly_usd: 100\n")
    with pytest.raises(ClaudeStop, match="budget"):
        preflight(main, allowance)
    preflight(load(overrides={"usage_credits_confirmed_off": True,
                              "claude": {"per_5h_budget": 5, "per_week_budget": 50}}), allowance)


def test_config_rejects_typos_and_bad_values():
    with pytest.raises(ConfigError, match="Unknown"):
        load(overrides={"claude": {"per_5h_budjet": 1}})
    with pytest.raises(ConfigError):
        load(overrides={"claude": {"pause_at_5h": 1.5}})
    with pytest.raises(ConfigError):
        load(overrides={"claude": {"run_hours": "11pm-7am"}})
    with pytest.raises(ConfigError):
        load(overrides={"usage_credits_confirmed_off": "yes"})
