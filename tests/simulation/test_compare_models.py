"""Trying LEA on Claude Sonnet: the OpenAI-shaped client and the side-by-side harness (no network)."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from simulation.compare import bank_for, mc_answer, quiz_answer, run_arm, summarise, tf_answer, write_comparison
from simulation.isolation import RunContext
from simulation.llm.claude_cli import ClaudeCallError, ClaudeCLI
from simulation.llm.openai_compat import ClaudeChatClient, flatten, unfence
from simulation.llm.usage_guard import GuardSettings, UsageGuard, UsageLedger

FAKE = [sys.executable, str(Path(__file__).with_name("fake_claude.py"))]


@pytest.fixture
def cli(tmp_path):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    ledger = UsageLedger(tmp_path / "ledger.jsonl")
    guard = UsageGuard(GuardSettings(None, None, 0.8, 0.6, None, 100), ledger, "cmp")
    return ClaudeCLI(guard, ledger, cwd, executable=FAKE), cwd


def script(cwd, **step):
    (cwd / "scenario.json").write_text(json.dumps([step]))


def calls(cwd):
    return [json.loads(x) for x in (cwd / "calls.jsonl").read_text().splitlines()]


# ---------------------------------------------------------------------------- the client


def test_openai_shaped_calls_are_answered_by_claude(cli):
    client, cwd = cli
    script(cwd, result="Hello there.", cost=0.02)
    chat = ClaudeChatClient(client, model="sonnet", role="lea_sonnet", effort=None, max_thinking_tokens=0)
    response = chat.chat.completions.create(
        model="gpt-4o-mini", temperature=0.7, max_tokens=500,
        messages=[{"role": "system", "content": "You are a tutor."}, {"role": "user", "content": "Hi"}])
    assert response.choices[0].message.content == "Hello there." and response.model.startswith("claude-")
    seen = calls(cwd)[0]
    argv = seen["argv"]
    assert argv[argv.index("--model") + 1] == "sonnet"  # LEA's hard-coded gpt-4o-mini is ignored
    assert seen["stdin"] == "Hi" and "MAX_THINKING_TOKENS" in seen["env"]
    assert chat.calls[0]["cost_usd"] == 0.02 and not chat.calls[0]["json"]


def test_json_mode_becomes_an_instruction_and_fences_are_removed(cli):
    client, cwd = cli
    script(cwd, result='```json\n{"question": "Q?", "correct_answer": "A"}\n```')
    chat = ClaudeChatClient(client)
    out = chat.chat.completions.create(model="x", messages=[{"role": "user", "content": "make one"}],
                                       response_format={"type": "json_object"})
    assert json.loads(out.choices[0].message.content) == {"question": "Q?", "correct_answer": "A"}
    assert chat.calls[0]["json"] and "JSON object only" in chat.calls[0]["system_head"]
    assert unfence('Sure! {"a": 1} hope that helps') == '{"a": 1}' and unfence("plain") == "plain"


def test_streaming_yields_the_reply_as_a_chunk_and_lea_helper_reads_it(cli):
    client, cwd = cli
    script(cwd, result="A streamed reply.")
    chat = ClaudeChatClient(client)
    from src.core.llm import complete

    pieces = []
    assert complete(chat, on_token=pieces.append, model="x", messages=[{"role": "user", "content": "hi"}]) == \
        "A streamed reply." and pieces == ["A streamed reply."]


def test_multi_turn_messages_are_flattened_and_errors_propagate(cli):
    system, prompt = flatten([{"role": "system", "content": "S"}, {"role": "user", "content": "one"},
                              {"role": "assistant", "content": "two"}, {"role": "user", "content": "three"}])
    assert system == "S" and prompt.startswith("USER: one\n\nASSISTANT: two") and prompt.endswith("ASSISTANT message.")
    client, cwd = cli
    script(cwd, is_error=True, result="overloaded", exit=1)
    with pytest.raises(ClaudeCallError):
        ClaudeChatClient(client).chat.completions.create(model="x", messages=[{"role": "user", "content": "hi"}])
    with pytest.raises(NotImplementedError):
        ClaudeChatClient(client).embeddings.create(input="x", model="y")


# ---------------------------------------------------------------------------- answers


def test_scripted_answers_use_what_lea_holds_or_the_bank():
    mc = {"type": "multiple_choice", "options": ["A) x", "B) y", "C) z", "D) w"], "correct_answer": "C"}
    assert mc_answer(mc, True) == "C) z" and mc_answer(mc, False) == "A) x"
    assert tf_answer({"correct_answer": "True"}, True) == "True" and tf_answer({"correct_answer": "True"}, False) == "False"
    bank = {"G1": {"reference_answer": "The true idea.", "misconceptions": [{"text": "A wrong belief."}]}}
    assert quiz_answer({"type": "open_ended", "go_id": "G1"}, True, bank) == "The true idea."
    assert quiz_answer({"type": "fill_in_blank", "go_id": "G1"}, False, bank) == "A wrong belief."
    assert quiz_answer({"type": "fill_in_blank", "go_id": "G1", "correct_answer": "model"}, True, bank) == "model"
    assert quiz_answer({"type": "open_ended", "go_id": "NOPE", "sample_answer": "S"}, True, bank) == "S"


# ---------------------------------------------------------------------------- both arms end to end


class FakeClaude:
    """Stands in for the subscription client: LEA's prompts get the scripted fake replies."""

    def __init__(self):
        self.prompts = []

    def call(self, prompt, *, system_prompt, model, role, effort=None, max_thinking_tokens=None, **kw):
        self.prompts.append(prompt)
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
        from tests.simulation.test_s3_drivers import lea_reply

        return SimpleNamespace(text=lea_reply(messages), model="claude-sonnet-fake", cost_usd=0.01,
                               usage={"input_tokens": 10, "output_tokens": 5}, init={})


def test_the_same_script_runs_against_both_models_and_writes_the_comparison(fake_llm, monkeypatch, tmp_path):
    from src.services.container import build_services
    from tests.fakes import StubRAGTool
    from tests.simulation.test_s3_drivers import lea_reply

    monkeypatch.setattr("src.mcp.tool_registry.RAGRetrievalTool", StubRAGTool)
    fake_llm._responder = lea_reply
    bank = bank_for("AIML101")
    arms = []
    with RunContext("cmp-openai", runs_dir=tmp_path / "runs") as ctx:
        arms.append(run_arm("LEA on OpenAI", build_services(ctx.redis_url, openai_client=fake_llm), bank,
                            progress=lambda m: None))
    claude = ClaudeChatClient(FakeClaude(), model="sonnet", role="lea_sonnet")
    with RunContext("cmp-sonnet", runs_dir=tmp_path / "runs") as ctx:
        arms.append(run_arm("LEA on Claude Sonnet", build_services(ctx.redis_url, openai_client=claude), bank,
                            progress=lambda m: None))
    for arm in arms:
        assert not arm.get("error"), arm.get("error")
        assert len(arm["chat"]) == 5 and arm["chat"][1]["kind"] == "follow_up" and arm["chat"][0]["ok"]
        assert 3 <= len(arm["tutor"]["turns"]) <= 6 and arm["tutor"]["opening"]
        assert {t["intended"] for t in arm["tutor"]["turns"]} >= {"right", "wrong", "minimal"}
        assert len(arm["quiz"]) >= 5 and {q["intended"] for q in arm["quiz"]} == {"right", "wrong"}
        s = summarise(arm)
        assert s["questions"] == len(arm["quiz"]) and s["graded"] > 0
    assert claude.calls and all(c["model"] == "claude-sonnet-fake" for c in claude.calls)
    # the scripted grading works the same on both: right answers marked right, wrong ones wrong
    assert summarise(arms[0])["grade_agrees_with_intent"] == summarise(arms[1])["grade_agrees_with_intent"]

    path = tmp_path / "comparison.md"
    write_comparison(path, arms, {"LEA on OpenAI": {"OpenAI $": 0.01}, "LEA on Claude Sonnet": {"Claude calls": 9}})
    text = path.read_text(encoding="utf-8")
    assert "LEA on OpenAI" in text and "LEA on Claude Sonnet" in text and "### Question 1" in text
    assert "## Tutor" in text and "## Chat" in text and path.with_suffix(".json").exists()


def test_a_stop_keeps_what_happened_so_far(fake_llm, monkeypatch, tmp_path):
    from simulation.llm.usage_guard import ClaudeStop
    from src.services.container import build_services
    from tests.fakes import StubRAGTool

    monkeypatch.setattr("src.mcp.tool_registry.RAGRetrievalTool", StubRAGTool)

    class Stops(FakeClaude):
        def call(self, *a, **kw):
            if len(self.prompts) >= 6:
                raise ClaudeStop("scripted stop")
            return super().call(*a, **kw)

    claude = ClaudeChatClient(Stops(), model="sonnet")
    with RunContext("cmp-stop", runs_dir=tmp_path / "runs") as ctx:
        arm = run_arm("LEA on Claude Sonnet", build_services(ctx.redis_url, openai_client=claude),
                      bank_for("AIML101"), progress=lambda m: None, should_stop=lambda: claude.stop_reason)
    assert "scripted stop" in arm["error"] and arm["chat"] and claude.stop_reason
    write_comparison(tmp_path / "c.md", [arm], {})
    assert "stopped early" in (tmp_path / "c.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------- the prompt variant


def quiz_prompts(monkeypatch):
    """The live question-generation prompt, for each motivation state and scaffolding strategy."""
    from src.quiz.simple_quiz_system import SimpleQuizSystem
    from tests.fakes import StubRAGTool

    system = SimpleQuizSystem("sk-test", rag_tool=StubRAGTool())
    plan = {"go_id": "GO_01_01_001", "skill_name": "Weak AI", "type": "multiple_choice", "week": 1,
            "description": "Define weak AI", "cognitive_level": "Understand"}
    out = {}
    for state in ("motivation_drop", "maintained_high", "cold_start", "motivation_plateau"):
        for strategy in ("conceptual", "procedural", "strategic", "metacognitive"):
            out[(state, strategy)] = system._create_orchestrator_guided_prompt(
                plan, "course content", {"motivation_state": state, "scaffolding_strategy": {"strategy_type": strategy}},
                [])
    return out


def test_the_default_variant_keeps_the_tone_guidance_and_scopes_it_to_the_feedback(fake_llm, monkeypatch):
    from simulation.variants import AFFECT_LINES, SCOPE_RULE, describe, quiz_questions_without_coaching

    before = quiz_prompts(monkeypatch)
    with quiz_questions_without_coaching():
        during = quiz_prompts(monkeypatch)
    assert quiz_prompts(monkeypatch) == before  # restored on exit
    for key, prompt in during.items():
        assert prompt == before[key] + SCOPE_RULE  # nothing removed, one rule added at the end
        assert 'ONLY to the "explanation" field' in prompt and "WHERE TONE GOES" in prompt
    assert all(line in "\n".join(during.values()) for line in AFFECT_LINES)
    assert "feedback only" in describe() and "removed" in describe(strip_lines=True)


def test_every_tone_line_is_in_the_live_prompt_and_the_strip_variant_removes_only_those(fake_llm, monkeypatch):
    from simulation.variants import AFFECT_LINES, NEUTRAL_RULE, quiz_questions_without_coaching, strip_affect

    before = quiz_prompts(monkeypatch)
    text = "\n".join(before.values())
    for line in AFFECT_LINES:  # a stale variant (LEA's prompt changed) fails here
        assert line in text, f"LEA's prompt no longer contains: {line}"
    with quiz_questions_without_coaching(strip_lines=True):
        during = quiz_prompts(monkeypatch)
    after = quiz_prompts(monkeypatch)
    assert after == before  # restored on exit
    for key, prompt in during.items():
        assert not any(line in prompt for line in AFFECT_LINES), key
        assert "QUESTION TEXT RULE" in prompt
        original = before[key]
        removed = [ln for ln in original.split("\n") if ln not in prompt.split("\n")]
        assert removed and all(any(a in ln for a in AFFECT_LINES) for ln in removed), key
        # difficulty, scaffolding and hint adaptations are untouched
        for keep in ("SCAFFOLDING STRATEGY", "Current Student Motivation State"):
            assert keep in prompt, (key, keep)
    assert strip_affect("a\n        - Use collaborative language\nb") == "a\nb"
    assert "no worries" in NEUTRAL_RULE and "feedback shown after" in " ".join(NEUTRAL_RULE.split())
