"""S3: driving LEA end to end with the scripted fake LLM (no network).

LEA runs for real (services, orchestrator, grading, mastery) on fakeredis, with the
scripted OpenAI stand-in and stub retrieval; a fake student client stands in for Claude.
"""

import json
import os
import re
from unittest import mock
from datetime import timedelta
from types import SimpleNamespace

import pytest
import yaml

from simulation.capture import OpenAIMeter, price
from simulation.harness import run
from simulation.llm.usage_guard import ClaudePause, ClaudeStop, utcnow
from tests.test_acceptance_phase1 import question_writer


class FakeStudent:
    """Stands in for claude -p: answers meant to be right contain RIGHT (the fake LEA grades on it)."""

    def __init__(self, stop_after=None, pause_at=None, no_question=False):
        self.prompts, self.stop_after, self.pause_at, self.paused = [], stop_after, pause_at, False
        self.no_question = no_question

    def call(self, prompt, *, system_prompt, model, role, json_schema=None, effort=None, max_thinking_tokens=None):
        self.prompts.append(prompt)
        self.thinking = getattr(self, "thinking", []) + [max_thinking_tokens]
        n = len(self.prompts)
        if self.stop_after and n > self.stop_after:
            raise ClaudeStop("isUsingOverage: true (scripted)")
        if self.pause_at == n and not self.paused:
            self.paused = True
            raise ClaudePause(utcnow() + timedelta(minutes=5), "scripted limit")
        structured, text = None, ""
        if json_schema is not None and "reply" in json_schema["properties"]:
            reply = ("RIGHT answer, I think it works like the lesson says" if "CORRECT" in prompt
                     else "WRONG answer, it just memorises")
            structured = {"asks_answerable_question": not self.no_question, "reply": reply}
        elif json_schema is not None:
            count = len(re.findall(r"^\d+\. ", prompt, re.M))
            structured = {"messages": [f"so, question {i + 1}: what about that?" for i in range(count)]}
        elif "CORRECT" in prompt:
            text = "RIGHT answer, I think it works like the lesson says"
        elif "WRONG" in prompt or "wrong" in prompt:
            text = "WRONG answer, it just memorises"
        else:
            text = "what does that mean in practice?"
        return SimpleNamespace(text=text, structured=structured, model="claude-haiku-fake", cost_usd=0.0001,
                               usage={}, init={"claude_code_version": "fake"})


def lea_reply(messages):
    return question_writer(messages) if ("Return JSON" in messages[-1]["content"] or "<answer>" in
                                         messages[-1]["content"] or "JSON" in messages[0]["content"]) \
        else "Tutor says: tell me what you know about this."


@pytest.fixture
def pilot(tmp_path):
    path = tmp_path / "pilot.yaml"
    path.write_text(yaml.safe_dump({"pilot": True, "usage_credits_confirmed_off": True,
                                    "scale": {"learners_per_profile": 1, "weeks": [1], "tutor_turn_cap": 12,
                                              "extra_rounds_when_stuck": 1}}))
    return str(path)


@pytest.fixture
def factory(fake_llm, monkeypatch):
    from tests.fakes import StubRAGTool

    monkeypatch.setattr("src.mcp.tool_registry.RAGRetrievalTool", StubRAGTool)
    fake_llm._responder = lea_reply

    def make(ctx):
        from src.services.container import build_services

        return build_services(ctx.redis_url, openai_client=fake_llm)
    return make


def records(result, kind=None):
    rows = [json.loads(line) for line in open(f"{result['dir']}/events.jsonl", encoding="utf-8")]
    return [r for r in rows if kind is None or r["kind"] == kind]


def test_a_pilot_drives_chat_tutor_and_quiz_and_captures_everything(pilot, factory, tmp_path):
    student = FakeStudent()
    result = run(pilot, "e2e", services_factory=factory, claude_client=student, runs_dir=tmp_path / "runs",
                 log=lambda m: None)
    assert result["status"] == "completed" and len(result["done"]) == 6
    turns = records(result, "turn")
    modes = {t["mode"] for t in turns}
    assert modes == {"chat", "tutor", "quiz"}
    assert {t["profile"] for t in turns} == {"advanced_eager", "moderate_reflective", "struggling_eager",
                                             "capable_disengaged", "novice_variable", "inconsistent_adaptive"}

    chat = [t for t in turns if t["mode"] == "chat"]
    assert all(t["retrieval"] and t["retrieval"][0]["sources"] for t in chat)  # what LEA retrieved
    assert any(t["follow_up"] for t in chat) and all(t["source_file"].startswith("Week01") for t in chat)
    assert 3 * 6 <= len(chat) <= 5 * 6

    tutor = [t for t in turns if t["mode"] == "tutor" and t["student_text"]]
    assert tutor and all(t["hidden_before"]["p_know"] is not None and t["intent"]["kind"] for t in tutor)
    graded = [t for t in tutor if t["lea"]["graded"]]
    assert graded and all(t["lea"]["correct"] == ("RIGHT" in t["student_text"]) for t in graded)
    assert any(t["decisions"] for t in tutor)  # the orchestrator's own logged decisions
    assert any(d["type"] == "learner_state" for t in tutor for d in t["decisions"])
    assert any(t["mastery"]["after"] is not None for t in graded)

    quiz = [t for t in turns if t["mode"] == "quiz"]
    assert quiz and all(t["lea"]["graded"] is not None and t["question"]["text"] for t in quiz)
    mc = [t for t in quiz if t["qtype"] == "multiple_choice"]
    assert all(t["lea"]["correct"] == t["intent"]["correct"] for t in mc)  # options picked, no LLM
    assert all(t["claude_student"]["calls"] == 0 for t in mc)

    ends = records(result, "week_end")
    assert len(ends) == 6 and all(len(e["gos"]) == 10 for e in ends)
    assert all({"known", "p_know", "lea_mastery", "lea_mastered"} <= set(e["gos"][0]) for e in ends)
    manifest = json.load(open(f"{result['dir']}/manifest.json"))
    assert manifest["status"] == "completed" and len(manifest["go_difficulty"]) == 63
    assert manifest["learner_weeks_done"] == 6 and manifest["profiles"]["capable_disengaged"]["minimal"] == 0.35

    from src.storage.event_log import EventLog
    kinds = {r["session_kind"] for r in EventLog(f"{result['dir']}/lea_events.db").query("actor IS NULL")}
    assert kinds == {"simulated"}  # LEA tagged every learner event simulated
    assert not any("sim_" in p for p in student.prompts)  # the student never sees usernames or LEA state
    assert not any(w in p.lower() for p in student.prompts for w in ("mastery", "zpd", "scaffolding"))
    assert set(student.thinking) == {0}  # the student never reasons at length for a 30-token reply


def test_a_stopped_run_resumes_from_the_last_finished_learner_week(pilot, factory, tmp_path):
    stopping = FakeStudent(stop_after=25)
    first = run(pilot, "resume", services_factory=factory, claude_client=stopping, runs_dir=tmp_path / "runs",
                log=lambda m: None)
    assert first["status"].startswith("stopped") and 0 < len(first["done"]) < 6
    with pytest.raises(FileExistsError):
        run(pilot, "resume", services_factory=factory, claude_client=FakeStudent(), runs_dir=tmp_path / "runs")
    path = f"{first['dir']}/manifest.json"
    stopped_manifest = json.load(open(path))
    assert stopped_manifest["openai"]["usd"] == 0 and stopped_manifest["openai"]["models"] == {}  # written on a stop
    stopped_manifest["openai"] = {"models": {"gpt-4o-mini": 3}, "usd": 1.5, "tokens": 10, "unpriced_models": []}
    json.dump(stopped_manifest, open(path, "w"))  # as if the first session had really used OpenAI
    second = run(pilot, "resume", resume=True, services_factory=factory, claude_client=FakeStudent(),
                 runs_dir=tmp_path / "runs", log=lambda m: None)
    resumed = json.load(open(path))
    assert resumed["openai"]["usd"] == 1.5 and resumed["openai"]["models"] == {"gpt-4o-mini": 3}  # kept, not reset
    assert second["status"] == "completed" and len(second["done"]) == 6
    ends = records(second, "week_end")
    assert sorted(e["learner"] for e in ends) == sorted(set(e["learner"] for e in ends))  # no week twice
    assert len(ends) == 6
    weeks = records(second, "learner_week")  # written before the checkpoint, so a resume never loses one
    assert sorted((w["learner"], w["week"]) for w in weeks) == sorted(set((w["learner"], w["week"]) for w in weeks))
    assert len(weeks) == 6
    learners_in_turns = [t["learner"] for t in records(second, "turn")]
    first_done = {k.split(":")[0] for k in first["done"]}
    for name in first_done:  # finished weeks were not redone
        assert sum(1 for e in ends if e["learner"] == name) == 1
    assert set(learners_in_turns) == {e["learner"] for e in ends}
    chat_per_learner = {}
    for t in records(second, "turn"):
        if t["mode"] == "chat":
            chat_per_learner[t["learner"]] = chat_per_learner.get(t["learner"], 0) + 1
    assert max(chat_per_learner.values()) <= 5  # the half-done week's turns were dropped, not kept twice
    turn_numbers = [t["turn"] for t in records(second, "turn") if t["learner"] == records(second, "turn")[0]["learner"]]
    assert turn_numbers == sorted(set(turn_numbers))


def test_a_usage_pause_waits_in_place_and_the_conversation_carries_on(pilot, factory, tmp_path):
    waits = []
    result = run(pilot, "pause", services_factory=factory, claude_client=FakeStudent(pause_at=3),
                 runs_dir=tmp_path / "runs", sleep=waits.append, log=lambda m: None)
    assert result["status"] == "completed" and len(waits) == 1 and 250 < waits[0] <= 300
    manifest = json.load(open(f"{result['dir']}/manifest.json"))
    assert manifest["pauses"][0]["reason"] == "scripted limit"


def test_no_run_without_the_usage_credits_confirmation(factory, tmp_path):
    path = tmp_path / "unconfirmed.yaml"
    path.write_text(yaml.safe_dump({"pilot": True}))
    with pytest.raises(ClaudeStop, match="Usage credits"):
        run(str(path), "x", services_factory=factory, claude_client=FakeStudent(), runs_dir=tmp_path / "runs")
    with pytest.raises(ClaudeStop, match="only allowed without Claude"):
        run(str(path), "y", services_factory=factory, runs_dir=tmp_path / "runs", skip_preflight=True)


def test_the_openai_meter_records_models_tokens_and_cost(monkeypatch):
    import openai.resources.chat.completions as chat_mod

    def fake_create(self, **kwargs):
        return SimpleNamespace(model="gpt-4o-mini-2024-07-18",
                               usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=500))

    monkeypatch.setattr(chat_mod.Completions, "create", fake_create)
    with OpenAIMeter(budget_usd=0.001) as meter:
        chat_mod.Completions.create(None, model="gpt-4o-mini", messages=[])
        assert meter.since_mark() == {"calls": 1, "usd": 0.00045, "tokens": 1500, "models": ["gpt-4o-mini-2024-07-18"]}
        chat_mod.Completions.create(None, model="gpt-4o-mini", messages=[])
        chat_mod.Completions.create(None, model="gpt-4o-mini", messages=[])
        with pytest.raises(Exception, match="budget"):
            meter.check_budget()
    assert chat_mod.Completions.create is fake_create  # restored
    assert price("gpt-4o-mini-2024-07-18")[0] == (0.15, 0.60) and price("mystery-model")[1] is False


def test_verbose_trace_prints_one_line_per_turn(pilot, factory, tmp_path):
    lines = []
    result = run(pilot, "trace", services_factory=factory, claude_client=FakeStudent(), runs_dir=tmp_path / "runs",
                 log=lambda m: None, trace=lines.append)
    turns = records(result, "turn")
    assert len(lines) == len(turns) > 0
    assert all(l.startswith("[sim_") and "true_p_know=" in l or "chat:" in l for l in lines)


@pytest.mark.parametrize("model", ["fixed", "personal"])
def test_timing_reaches_lea_and_the_selected_equation_drives_load(pilot, factory, tmp_path, model):
    cfg = yaml.safe_load(open(pilot))
    cfg["lea"] = {"cognitive_load_model": model}
    cfg["scale"]["profiles"] = ["advanced_eager", "struggling_eager"]
    json.dump(cfg, open(pilot, "w"))
    result = run(pilot, f"cl-{model}", services_factory=factory, claude_client=FakeStudent(), runs_dir=tmp_path / "runs",
                 log=lambda m: None)
    turns = [t for t in records(result, "turn") if t.get("timing")]
    assert turns and all(t["true_load"] is not None and t["timing"]["response_ms"] > 0 for t in turns)
    states = [next((d["payload"]["cognitive_state"] for d in t["decisions"] if d["type"] == "learner_state"), {})
              for t in turns]
    with_details = [s for s in states if s.get("load_details")]
    assert len(with_details) > 0.8 * len(states)                      # both equations are logged in either arm
    for s in with_details:
        d = s["load_details"]
        assert d["selected"] == model and 0 <= d["load"] <= 10
        assert abs(s["cognitive_load"] - (d["load"] if model == "personal" else d["fixed"])) < 0.01


def test_a_long_student_reply_is_held_to_its_target_length_by_whole_sentences():
    from simulation.student import trim_to_words

    text = "First point is short. Second point adds a bit more detail here. Third point rambles on and on and on and on."
    assert trim_to_words(text, 10) == "First point is short. Second point adds a bit more detail here."
    assert trim_to_words(text, None) == text and trim_to_words("Short one.", 10) == "Short one."
    assert trim_to_words("One very long sentence with many many words in it and no stop", 3).startswith("One very long")


@pytest.mark.parametrize("model", ["current", "zpd_shrunk", "load_led"])
def test_each_scaffolding_model_runs_and_records_how_zpd_was_estimated(pilot, factory, tmp_path, model):
    cfg = yaml.safe_load(open(pilot))
    cfg["lea"] = {"cognitive_load_model": "personal", "scaffolding_model": model}
    cfg["scale"]["profiles"] = ["struggling_eager"]
    json.dump(cfg, open(pilot, "w"))
    result = run(pilot, f"sc-{model}", services_factory=factory, claude_client=FakeStudent(), runs_dir=tmp_path / "runs",
                 log=lambda m: None)
    assert result["status"] == "completed"
    states = [next((d["payload"]["cognitive_state"] for d in t["decisions"] if d["type"] == "learner_state"), {})
              for t in records(result, "turn") if t["mode"] == "tutor"]
    states = [s for s in states if s]
    assert states
    assert (any(s.get("zpd_details") for s in states)) == (model != "current")
    levels = {d["payload"].get("scaffolding_intensity") for t in records(result, "turn") for d in t["decisions"]
              if d["type"] == "answer"} - {None}
    assert levels


def test_a_reply_to_a_tutor_message_that_asked_nothing_is_recorded_as_an_acknowledgement(pilot, factory, tmp_path):
    result = run(pilot, "ack", services_factory=factory, claude_client=FakeStudent(no_question=True),
                 runs_dir=tmp_path / "runs", log=lambda m: None)
    tutor = [t for t in records(result, "turn") if t["mode"] == "tutor" and t.get("student_text")]
    acks = [t for t in tutor if t["intent"]["kind"] == "acknowledge"]
    assert acks and all(t["intent"]["correct"] is None and t["misconception"] is None for t in acks)
    assert not [t for t in tutor if t["intent"]["kind"] == "answer"]      # none left to be judged for M0a or M4


def test_the_one_question_flag_is_wired_through_the_harness_env(pilot, factory, tmp_path):
    cfg = yaml.safe_load(open(pilot))
    cfg["lea"] = {"tutor_recorded_question": "on"}
    json.dump(cfg, open(pilot, "w"))
    seen = {}
    real_getenv = os.getenv

    def spy_getenv(key, default=None):
        if key == "LEA_TUTOR_RECORDED_QUESTION":
            seen["value"] = real_getenv(key, default)
        return real_getenv(key, default)

    with mock.patch("os.getenv", side_effect=spy_getenv):
        run(pilot, "one-question-env", services_factory=factory, claude_client=FakeStudent(),
            runs_dir=tmp_path / "runs", log=lambda m: None)
    assert seen.get("value") == "on"
