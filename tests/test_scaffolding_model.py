"""The switchable ZPD and scaffolding rules (src/core/scaffolding_model.py)."""

import json

import pytest

from src.core import grading
from src.core import scaffolding_model as sm
from src.core.learner_evidence import LearnerEvidence
from src.core.scaffolding_engine import ScaffoldingEngine


def entries(*flags, weights=None):
    out = []
    for i, c in enumerate(flags):
        e = {"correct": c, "score": 1.0 if c else 0.0, "lo_id": "LO1"}
        if weights and weights[i] is not None:
            e["weight"] = weights[i]
        out.append(e)
    return out


def test_the_default_model_is_current_and_unknown_values_fall_back(monkeypatch):
    monkeypatch.delenv(sm.MODEL_ENV, raising=False)
    assert sm.selected_model() == "current"
    monkeypatch.setenv(sm.MODEL_ENV, "load_led")
    assert sm.selected_model() == "load_led"
    monkeypatch.setenv(sm.MODEL_ENV, "bogus")
    assert sm.selected_model() == "current"


def test_shrunk_zpd_is_pulled_toward_the_prior_and_recent_answers_count_more():
    none, d0 = sm.shrunk_zpd([], 0.7, False)
    assert none == pytest.approx(0.7) and d0["used"] == 0
    one_wrong, _ = sm.shrunk_zpd(entries(False), 0.7, False)
    assert 0.4 < one_wrong < 0.7                                   # one wrong answer doesn't collapse it
    four_wrong, _ = sm.shrunk_zpd(entries(False, False, False, False), 0.7, False)
    assert four_wrong < one_wrong
    recent_right, _ = sm.shrunk_zpd(entries(False, False, True, True), 0.5, False)
    recent_wrong, _ = sm.shrunk_zpd(entries(True, True, False, False), 0.5, False)
    assert recent_right > recent_wrong
    many = entries(*([True] * 30))
    assert sm.shrunk_zpd(many, 0.2, False)[1]["used"] == sm.ZPD_WINDOW


def test_grader_weights_only_count_when_asked_for():
    ev = entries(False, False, False, True, weights=[0.0, 0.0, 0.0, 1.0])
    plain, _ = sm.shrunk_zpd(ev, 0.6, False)
    weighted, det = sm.shrunk_zpd(ev, 0.6, True)
    assert weighted > plain                                         # three unchecked misses no longer drag it down
    assert det["effective_n"] == pytest.approx(1.0, abs=1e-6) or det["effective_n"] < plain


def test_evidence_weight_from_the_grader():
    assert sm.evidence_weight(None, None) is None
    assert sm.evidence_weight(False, 0.9) == 0.0
    assert sm.evidence_weight(True, 0.9) == 0.9
    assert sm.evidence_weight(True, 0.0) == sm.MIN_CONFIDENCE_WEIGHT
    assert sm.evidence_weight(True, None) == 1.0


def test_unchecked_replies_do_not_break_or_extend_a_fading_streak():
    counted = sm.counted_correctness(entries(True, True, False, True, weights=[1.0, 1.0, 0.0, 1.0]))
    assert counted == [True, True, True]                            # the unchecked miss is ignored


@pytest.mark.parametrize("cl,zpd,expected", [
    ("high", "low", "very_high"), ("high", "medium", "high"), ("high", "high", "high"),
    ("medium", "low", "high"), ("medium", "medium", "medium"), ("medium", "high", "medium"),
    ("low", "low", "low"), ("low", "medium", "low"), ("low", "high", "low")])
def test_support_comes_from_load_and_is_raised_only_when_zpd_is_low(cl, zpd, expected):
    assert sm.support_from_load(cl, zpd) == expected


def test_zpd_steers_difficulty_not_support():
    assert [sm.difficulty_from_zpd(z) for z in (0.95, 0.85, 0.7, 0.45, 0.2)] == \
        ["increase", "increase", "maintain", "decrease", "decrease"]


@pytest.fixture
def engine(lea_redis):
    return ScaffoldingEngine(lea_redis)


def decide(engine, user, level, history, difficulty="maintain"):
    return engine.get_scaffolding_decision("medium", "medium", user, "LO1", history,
                                           intensity_override=(level, 3), difficulty=difficulty)


def test_the_engine_without_an_override_is_unchanged(engine):
    d = engine.get_scaffolding_decision("high", "low", "u_plain", "LO1", [])
    assert d.intensity_level == "very_high" and d.difficulty is None


def test_a_load_led_level_fades_after_three_and_is_held_for_two_decisions(engine):
    user = "u_dwell"
    first = decide(engine, user, "high", [])
    assert first.intensity_level == "high"
    held = decide(engine, user, "low", [])            # wants to drop at once, but the level was just set
    assert held.intensity_level == "high"
    moved = decide(engine, user, "low", [])            # held for two decisions in all, then it may change
    assert moved.intensity_level == "low"
    faded = decide(engine, "u_fade", "medium", [True, True, True])
    assert faded.intensity_level == "low" and faded.faded_steps == 1
    assert decide(engine, "u_diff", "medium", [], difficulty="increase").difficulty == "increase"


class GradingClient:
    def __init__(self, checkable=False):
        self.systems, self.checkable = [], checkable
        self.chat = self
        self.completions = self

    def create(self, *, messages, **kw):
        self.systems.append(messages[0]["content"])
        content = json.dumps({"correct": True, "score": 0.9, "explanation": "ok", "matched_concepts": [],
                              "missing_concepts": [], "checkable": self.checkable, "confidence": 0.4})
        return type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": content})()})()]})()


def test_the_checkable_gate_is_on_by_default_since_v3_was_approved():
    # V3 (simulation/grader_replay.py): checkable is asked by default, and a non-checkable reply is
    # left ungraded instead of scored right or wrong, whatever "correct" says.
    not_checkable = GradingClient(checkable=False)
    gated = grading.grade_with_llm(not_checkable, kind="tutor", reference={"objective": "x"},
                                   student_answer="an answer", conversation="q")
    assert '"checkable"' in not_checkable.systems[0] and "actually asked" in not_checkable.systems[0]
    assert gated["graded"] is False and gated["correct"] is None and gated["checkable"] is False

    checkable = GradingClient(checkable=True)
    scored = grading.grade_with_llm(checkable, kind="tutor", reference={"objective": "x"}, student_answer="an answer",
                                    conversation="q")
    assert scored["graded"] is True and scored["correct"] is True and scored["confidence"] == 0.4


def test_with_confidence_false_restores_the_plain_ungated_grader():
    client = GradingClient(checkable=False)  # would gate if asked, but with_confidence=False never asks
    plain = grading.grade_with_llm(client, kind="tutor", reference={"objective": "x"}, student_answer="an answer",
                                   conversation="q", with_confidence=False)
    assert "checkable" not in client.systems[0]
    assert plain["graded"] is True and plain["correct"] is True and "checkable" not in plain


def test_evidence_stores_a_weight_only_when_given(lea_redis):
    evidence = LearnerEvidence(lea_redis)
    a = evidence.record("u_w", "AIML101", mode="tutor", go_id="g", correct=True, score=1.0)
    b = evidence.record("u_w", "AIML101", mode="tutor", go_id="g", correct=False, score=0.0, weight=0.3)
    assert "weight" not in a and b["weight"] == 0.3


# ---------------------------------------------------------------- the motivation switches

from src.core.agent_orchestrator_mcp import (CognitiveState, MotivationHistory, MotivationMetrics, MotivationState,
                                              PersistenceLevel)


def metrics(performance, affect=0.0, persistence=PersistenceLevel.MAINTAINS_PERSISTENCE):
    return MotivationMetrics(persistence_level=persistence, affective_score=affect, performance_score=performance,
                             interaction_count=9, session_completion_rate=0.5, consecutive_correct=0,
                             consecutive_incorrect=0, time_on_task=1.0, help_seeking_frequency=0.0)


def history():
    return MotivationHistory(baseline_established=True, baseline_interactions=[], recent_metrics=[],
                             state_transitions=[], session_count=1)


def test_the_motivation_switches_default_to_support_off_and_the_current_classifier(monkeypatch):
    # LEA_MOTIVATION_SUPPORT defaults to off since 2026-09-27 (Amendment A3: it swamped every scaffolding
    # comparison). LEA_MOTIVATION_CLASSIFIER is unchanged, defaulting to "current".
    monkeypatch.delenv("LEA_MOTIVATION_SUPPORT", raising=False)
    monkeypatch.delenv("LEA_MOTIVATION_CLASSIFIER", raising=False)
    assert not sm.motivation_shifts_support() and sm.motivation_uses_performance()
    monkeypatch.setenv("LEA_MOTIVATION_SUPPORT", "on")
    monkeypatch.setenv("LEA_MOTIVATION_CLASSIFIER", "no_performance")
    assert sm.motivation_shifts_support() and not sm.motivation_uses_performance()


def test_low_accuracy_is_a_motivation_drop_only_under_the_current_classifier(orchestrator, monkeypatch):
    monkeypatch.delenv("LEA_MOTIVATION_CLASSIFIER", raising=False)
    assert orchestrator._classify_motivation_state(metrics(0.3), history()) == MotivationState.MOTIVATION_DROP
    assert orchestrator._classify_motivation_state(metrics(0.9), history()) == MotivationState.MAINTAINED_HIGH
    monkeypatch.setenv("LEA_MOTIVATION_CLASSIFIER", "no_performance")
    assert orchestrator._classify_motivation_state(metrics(0.3), history()) == MotivationState.MOTIVATION_PLATEAU
    assert orchestrator._classify_motivation_state(metrics(0.9), history()) == MotivationState.MOTIVATION_PLATEAU
    # behavioural signals still count
    assert orchestrator._classify_motivation_state(metrics(0.3, affect=-0.5), history()) == MotivationState.MOTIVATION_DROP
    assert orchestrator._classify_motivation_state(
        metrics(0.3, persistence=PersistenceLevel.DECREASED_PERSISTENCE), history()) == MotivationState.MOTIVATION_DROP


@pytest.mark.parametrize("switch,expected", [("on", "high"), ("off", "medium")])
def test_the_motivation_state_moves_the_load_level_only_when_the_switch_is_on(orchestrator, monkeypatch, switch, expected):
    monkeypatch.setenv("LEA_MOTIVATION_SUPPORT", switch)
    seen = {}

    def spy(**kw):
        seen.update(kw)
        raise RuntimeError("stop here")

    orchestrator.scaffolding_engine.get_scaffolding_decision = spy
    state = CognitiveState(cognitive_load=5.0, zpd_score=0.6, motivation_score=0.5,
                           motivation_state=MotivationState.MOTIVATION_DROP, motivation_metrics=metrics(0.4),
                           fatigue_level=0.1, scaffolding_level="medium", session_quality="good", mastery_data={})
    orchestrator._get_motivation_informed_scaffolding(state, "u", "AIML101", {}, MotivationState.MOTIVATION_DROP, [])
    assert seen["cl_level"] == expected


def test_tutor_temperature_defaults_to_0_7_and_can_be_overridden(monkeypatch):
    monkeypatch.delenv("LEA_TUTOR_TEMPERATURE", raising=False)
    assert sm.tutor_temperature() == 0.7
    monkeypatch.setenv("LEA_TUTOR_TEMPERATURE", "0.4")
    assert sm.tutor_temperature() == 0.4
    monkeypatch.setenv("LEA_TUTOR_TEMPERATURE", "not-a-number")
    assert sm.tutor_temperature() == 0.7


def test_tutor_question_scope_defaults_to_broad_and_falls_back_on_bad_values(monkeypatch):
    monkeypatch.delenv("LEA_TUTOR_QUESTION_SCOPE", raising=False)
    assert sm.tutor_question_scope() == "broad"
    monkeypatch.setenv("LEA_TUTOR_QUESTION_SCOPE", "strict")
    assert sm.tutor_question_scope() == "strict"
    monkeypatch.setenv("LEA_TUTOR_QUESTION_SCOPE", "bogus")
    assert sm.tutor_question_scope() == "broad"


def test_tutor_records_one_question_defaults_to_on(monkeypatch):
    monkeypatch.delenv("LEA_TUTOR_RECORDED_QUESTION", raising=False)
    assert sm.tutor_records_one_question() is True
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "off")
    assert sm.tutor_records_one_question() is False
