"""S4: judges, rubrics, reliability sampling and the labelling sheet (no network)."""

import csv
import json
import re
from types import SimpleNamespace

import pytest

from simulation.harness import load_bank, run
from simulation.judges import (KINDS, Judge, build_units, judge_run, labelling_sheet, load_rubrics, plan_judging,
                               read_events, read_labels, stratified_sample, validate)
from simulation.llm.claude_cli import ClaudeCallError
from simulation.settings import load
from tests.simulation.test_s3_drivers import FakeStudent, factory, pilot  # noqa: F401 (fixtures)

RUBRICS = load_rubrics()
BLIND_WORDS = ("advanced_eager", "Advanced Eager", "capable_disengaged", "novice", "p_know", "known", "intent",
               "engagement", "hidden", "mastery", "zpd", "scaffold", "sim_", "profile", "struggling")


@pytest.fixture
def events(pilot, factory, tmp_path):  # noqa: F811
    result = run(pilot, "judged", services_factory=factory, claude_client=FakeStudent(), runs_dir=tmp_path / "runs",
                 log=lambda m: None)
    return result["dir"], read_events(f"{result['dir']}/events.jsonl")


@pytest.fixture
def units(events):
    return build_units(events[1], {1: "Week 1 lecture text about AI."}, load_bank("AIML101"))


def ids_in(prompt, pattern):
    return [m for m in re.findall(pattern, prompt)]


class ScriptedJudge:
    """Answers any judge prompt validly, or with scripted failures first."""

    def __init__(self, failures=0, fail_with="invalid"):
        self.prompts, self.failures, self.fail_with, self.roles = [], failures, fail_with, []

    def call(self, prompt, *, system_prompt, model, role, json_schema=None, effort=None, max_thinking_tokens=None):
        self.prompts.append(prompt)
        self.roles.append((role, model))
        self.thinking = getattr(self, "thinking", []) + [max_thinking_tokens]
        if len(self.prompts) <= self.failures:
            if self.fail_with == "error":
                raise ClaudeCallError("overloaded")
            return SimpleNamespace(structured={"wrong": []}, text="", model="claude-sonnet-x", cost_usd=0.01)
        list_key = next(iter(json_schema["properties"]))
        item = json_schema["properties"][list_key]["items"]
        if list_key == "replies":
            ids = [int(i) for i in re.findall(r"TUTOR REPLY (\d+):", prompt)]
        elif list_key == "items":
            ids = [int(i) for i in re.findall(r"QUIZ ITEM (\d+) ", prompt)]
        elif list_key == "exchanges":
            ids = [int(i) for i in re.findall(r"--- Exchange (\d+) ---", prompt)]
        elif list_key == "follow_ups":
            ids = [int(i) for i in re.findall(r"FOLLOW-UP (\d+) ---", prompt)]
        else:
            ids = re.findall(r"ANSWER (\w+) ---", prompt)
        rows = []
        for i in ids:
            row = {"id": i}
            for k, spec in item["properties"].items():
                if k == "id":
                    continue
                row[k] = spec["enum"][0] if "enum" in spec else 4
            rows.append(row)
        return SimpleNamespace(structured={list_key: rows}, text="", model=f"claude-{model}-x", cost_usd=0.01)


def test_rubrics_are_versioned_with_definitions_and_two_examples_each():
    assert set(RUBRICS) == {"M0a", "M3", "M16", "M17", "M18", "SC3"}
    for r in RUBRICS.values():
        assert r["version"] >= 1
        for item in (r.get("items") or {}).values():
            assert item["yes_if"] and item["no_if"] and len(item["examples"]) == 2
    assert set(RUBRICS["M17"]["scale"]) == {1, 2, 3, 4, 5} and len(RUBRICS["M17"]["examples"]) == 2


def test_units_come_from_saved_events_and_prompts_are_blind(units):
    assert units["tutor"] and units["quiz"] and units["chat"] and units["fidelity"]
    for kind, group in units.items():
        for unit in group:
            prompt = KINDS[kind]["prompt"](unit, RUBRICS)
            for word in BLIND_WORDS:
                assert word.lower() not in prompt.lower(), (kind, word)
    fid = [a for u in units["fidelity"] for a in u["answers"]]
    assert fid and all(a["reference"] for a in fid)  # bank references, never LEA's


def test_one_call_per_unit_and_values_for_every_unit(units):
    client = ScriptedJudge()
    judge = Judge(client, "sonnet", rubrics=RUBRICS)
    for kind, group in units.items():
        for unit in group:
            record = judge.judge(kind, unit)
            assert record["values"] is not None and record["attempts"] == 1
            assert set(record["values"]) == {str(i) for i in KINDS[kind]["ids"](unit)}
            assert record["rubric_versions"] and record["model"] == "claude-sonnet-x"
    assert len(client.prompts) == sum(len(g) for g in units.values())


def test_invalid_output_is_retried_once_then_missing_never_a_default(units):
    unit = units["tutor"][0]
    retried = Judge(ScriptedJudge(failures=1), "sonnet", rubrics=RUBRICS).judge("tutor", unit)
    assert retried["values"] is not None and retried["attempts"] == 2
    missing = Judge(ScriptedJudge(failures=2), "sonnet", rubrics=RUBRICS).judge("tutor", unit)
    assert missing["values"] is None and missing["attempts"] == 2 and "schema" in missing["missing_reason"]
    errored = Judge(ScriptedJudge(failures=2, fail_with="error"), "sonnet", rubrics=RUBRICS).judge("quiz", units["quiz"][0])
    assert errored["values"] is None and "call failed" in errored["missing_reason"]


def test_validation_catches_missing_units_and_bad_values(units):
    unit = units["tutor"][0]
    schema = KINDS["tutor"]["schema"](unit, RUBRICS)
    ids = KINDS["tutor"]["ids"](unit)
    good = {"replies": [{"id": i, **{k: "yes" for k in RUBRICS["M16"]["items"]}, "coherence": 4} for i in ids]}
    assert validate(good, schema, "replies", ids) is None
    assert "units" in validate({"replies": good["replies"][1:]}, schema, "replies", ids) if len(ids) > 1 else True
    bad = json.loads(json.dumps(good))
    bad["replies"][0]["coherence"] = 7
    assert "schema" in validate(bad, schema, "replies", ids)
    bad["replies"][0]["coherence"] = 4
    bad["replies"][0]["explains_why"] = "maybe"
    assert "schema" in validate(bad, schema, "replies", ids)


def test_reliability_samples_are_stratified_and_seeded():
    units = [{"key": f"{p}-{i}", "profile": p} for p in "abcdef" for i in range(20)]
    sample = stratified_sample(units, 0.10, seed=3)
    assert len(sample) == 12 and {u["profile"] for u in sample} == set("abcdef")
    assert sample == stratified_sample(units, 0.10, seed=3) and sample != stratified_sample(units, 0.10, seed=4)
    small = stratified_sample([{"key": "x", "profile": "a"}], 0.10, seed=1)
    assert len(small) == 1  # every stratum at least once
    jobs = plan_judging({"tutor": units, "quiz": [], "chat": [], "fidelity": []}, seed=1)
    main = [j for j in jobs if j[2] == 0 and j[3] == "judge"]
    repeats = [j for j in jobs if j[2] > 0]
    second = [j for j in jobs if j[3] == "second_judge"]
    assert len(main) == 120 and len(repeats) == 2 * 12 and len(second) == 12
    half = plan_judging({"tutor": units, "quiz": [], "chat": [], "fidelity": []}, tutor_share=0.5, seed=1)
    assert len([j for j in half if j[2] == 0 and j[3] == "judge"]) == 60


def test_the_labelling_sheet_is_random_blind_and_reads_back(units, tmp_path):
    path = tmp_path / "sheet.csv"
    n = labelling_sheet(units, path, tutor=5, quiz=4, chat=3)
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    assert n == len(rows) == 5 + 4 + min(3, sum(len(u["follow_ups"]) for u in units["chat"]))
    assert {r["kind"] for r in rows} == {"tutor_turn", "quiz_item", "chat_follow_up"}
    assert [r["kind"] for r in rows] != sorted(r["kind"] for r in rows)  # shuffled
    assert all(not r["label_1"] for r in rows)  # the judge's answers are not in it
    text = path.read_text(encoding="utf-8").lower()
    assert not any(w in text for w in ("p_know", "intent", "profile", "sim_"))
    rows[0]["label_1"], rows[0]["label_coherence"] = "Yes", "4"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    labels = read_labels(path)
    key = json.load(open(tmp_path / "sheet_key.json"))
    assert labels[key[rows[0]["item_id"]]] == {"label_1": "yes", "label_coherence": "4"}
    assert all(re.fullmatch(r"L[0-9a-f]{10}", r["item_id"]) for r in rows)


def test_a_run_is_judged_from_saved_events_without_lea(events, fake_llm):
    run_dir, _ = events
    calls_before = len(fake_llm.calls)
    client = ScriptedJudge()
    summary = judge_run(run_dir, load(overrides={"pilot": True}), client, load_bank("AIML101"), pass_id="p1")
    assert len(fake_llm.calls) == calls_before  # no LEA/OpenAI calls
    assert summary["missing"] == 0 and summary["jobs"] == len(client.prompts)
    roles = {r for r, _ in client.roles}
    assert roles == {"judge", "second_judge"} and ("second_judge", "opus") in client.roles
    assert set(client.thinking) == {None}  # judges keep the model's default reasoning
    records = read_events(f"{run_dir}/judgements.jsonl")
    assert {r["pass_id"] for r in records} == {"p1"} and max(r["repeat"] for r in records) == 2
    assert summary["sheet_rows"] > 0
    again = judge_run(run_dir, load(overrides={"pilot": True}), ScriptedJudge(), load_bank("AIML101"),
                      pass_id="p2", reliability=False, sheet=False)
    assert again["jobs"] == sum(v for k, v in summary["units"].items() if k != "support") + 6  # SC3 judges a 20% sample (min one per profile)
    cfg = load(overrides={"pilot": True, "claude": {"judge_max_thinking_tokens": 1024}})
    tuned = ScriptedJudge()
    judge_run(run_dir, cfg, tuned, load_bank("AIML101"), pass_id="p3", reliability=False, sheet=False)
    assert set(tuned.thinking) == {1024}
