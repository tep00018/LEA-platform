"""S2: the question bank builder (no network: a fake client writes the entries)."""

import json
import re
from types import SimpleNamespace

import pytest

from simulation.bank import build, check_entries, load_inputs, plan_calls, spot_check_sheet
from simulation.isolation import REAL_DATA


def entry(go, source, quote, **over):
    return {"go_id": go, "questions": [
        {"text": f"What does {go} mean in practice?", "kind": "question", "follows": None},
        {"text": f"How would I use {go} on a real problem?", "kind": "question", "follows": None},
        {"text": "Can you give me an example of that?", "kind": "follow_up", "follows": 0}],
        "reference_answer": "It is the idea the lesson explains, with the reason it matters and how it is used here.",
        "source_file": source, "source_quote": quote,
        "misconceptions": [{"text": "It is the same as memorising data.", "basis": "common_error"},
                           {"text": "It only works for images.", "basis": "quiz_distractor"}], **over}


class FakeClient:
    """Answers each prompt with valid entries for the GOs it lists (or scripted bad ones)."""

    def __init__(self, bad_first=False):
        self.prompts, self.bad_first = [], bad_first

    def call(self, prompt, **kw):
        self.prompts.append(prompt)
        gos = re.findall(r"^- (GO_\d\d_\d\d_\d\d\d) ", prompt, re.M)
        name, text = re.search(r"=== (.+?) ===\n(.+)", prompt).groups()
        quote = " ".join(text.split()[:10])
        entries = [entry(g, name, quote) for g in gos]
        if self.bad_first and len(self.prompts) == 1:
            entries[0]["source_file"] = "Nope.md"
        return SimpleNamespace(structured={"entries": entries}, text="", model="claude-sonnet-test",
                               cost_usd=0.01, usage={}, init={"claude_code_version": "test"})


@pytest.fixture(scope="module")
def inputs():
    return load_inputs(REAL_DATA, "AIML101")


def test_inputs_use_the_vector_store_file_names(inputs):
    names = {n for week in inputs["lessons"].values() for n in week}
    assert "Week02-LabA-Animal-Expert-System.ipynb" in names and "Week01-LectureA-Introduction-To-AI.md" in names
    assert len(inputs["rows"]) == 63 and inputs["quiz"]


def test_the_plan_splits_only_large_weeks(inputs):
    calls = plan_calls(inputs)
    assert sorted(g for c in calls for g in (r["go_id"] for r in c["rows"])) == sorted(r["go_id"] for r in inputs["rows"])
    assert [c["week"] for c in calls] == [1, 2, 3, 4, 5, 5, 6]


def test_the_checks_catch_what_matters(inputs):
    call = plan_calls(inputs)[0]
    lessons = inputs["lessons"][1]
    name = "Week01-LectureA-Introduction-To-AI.md"
    quote = " ".join(lessons[name].split()[20:32])
    good = [entry(r["go_id"], name, quote) for r in call["rows"]]
    assert check_entries(good, call, lessons) == []
    assert check_entries(good[1:], call, lessons)  # a GO missing
    for bad in ({"source_file": "Week09-Nothing.md"}, {"source_quote": "words that are not in the lesson at all ok"},
                {"misconceptions": [{"text": "x", "basis": "lesson"}]},
                {"reference_answer": "Too short."},
                {"questions": [{"text": "Question one here?", "kind": "question", "follows": None}] * 3}):
        broken = [dict(good[0], **bad)] + good[1:]
        assert check_entries(broken, call, lessons), bad


def test_a_build_writes_every_go_and_retries_a_bad_reply_once(inputs):
    client = FakeClient(bad_first=True)
    bank = build(client, REAL_DATA, "AIML101", "sonnet", concurrency=1)
    assert len(bank["entries"]) == 63 and len({e["go_id"] for e in bank["entries"]}) == 63
    assert len(client.prompts) == 8  # 7 calls, one retried
    assert "previous reply had these problems" in client.prompts[1]
    assert bank["generator"]["models"] == ["claude-sonnet-test"] and bank["api_equivalent_usd"] == 0.08
    assert bank["spot_check"]["status"] == "pending" and len(bank["spot_check"]["sample"]) == 20
    sheet = spot_check_sheet(bank)
    assert sheet.count("## ") == 20 and "- [ ] The misconceptions are plausible" in sheet
    json.dumps(bank)  # serialisable


def test_a_failed_week_keeps_the_others_and_a_rebuild_redoes_only_it(inputs, tmp_path):
    class BrokenWeek6(FakeClient):
        def call(self, prompt, **kw):
            result = super().call(prompt, **kw)
            if "Week 6:" in prompt:
                result.structured["entries"] = result.structured["entries"][1:]  # a GO missing
            return result

    broken = BrokenWeek6()
    with pytest.raises(RuntimeError, match="Unfinished.*week 6"):
        build(broken, REAL_DATA, "AIML101", "sonnet", concurrency=1, checkpoint_dir=tmp_path)
    assert len(broken.prompts) == 8  # 6 calls passed, week 6 tried twice
    assert len(list(tmp_path.glob("*.json"))) == 6
    again = FakeClient()
    bank = build(again, REAL_DATA, "AIML101", "sonnet", concurrency=1, checkpoint_dir=tmp_path)
    assert len(again.prompts) == 1 and "Week 6:" in again.prompts[0]  # only the missing week
    assert len(bank["entries"]) == 63 and sum(1 for c in bank["calls"] if c.get("reused")) == 6


def test_a_quote_that_still_does_not_match_is_flagged_not_fatal(inputs, tmp_path):
    class BadQuote(FakeClient):
        def call(self, prompt, **kw):
            result = super().call(prompt, **kw)
            if "Week 1:" in prompt:
                result.structured["entries"][0]["source_quote"] = "these words do not appear in any lesson file"
            return result

    bank = build(BadQuote(), REAL_DATA, "AIML101", "sonnet", concurrency=1, checkpoint_dir=tmp_path)
    assert len(bank["entries"]) == 63 and len(bank["needs_review"]) == 1
    flagged = next(e for e in bank["entries"] if e.get("needs_review"))
    assert flagged["week"] == 1 and flagged["needs_review"] == ["quote not found in the source file"]


def test_quotes_match_despite_punctuation_and_markdown(inputs):
    call = plan_calls(inputs)[0]
    lessons = {"L.md": "The **perceptron** learns a *linear* decision-boundary, (roughly) speaking."}
    good = [entry(r["go_id"], "L.md", "the perceptron learns a linear decision boundary roughly speaking")
            for r in call["rows"]]
    assert check_entries(good, call, lessons) == []
