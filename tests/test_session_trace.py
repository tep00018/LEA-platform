"""scripts/session_trace.py: turns are built from the event log, with a decision-log CSV
fallback, and never call a model."""

import json

import pytest

from scripts.session_trace import _go_mastery, _support_from_scaffolding_strategy, build_trace
from src.services.events import EventRecorder
from src.storage.event_log import EventLog

COURSE = "DEMO101"


@pytest.fixture
def log(tmp_path):
    log = EventLog(tmp_path / "events.db")
    yield log
    log.close()


@pytest.fixture
def recorder(log, lea_redis):
    return EventRecorder(log, "test-salt", lea_redis)


def test_support_from_scaffolding_strategy_handles_string_and_dict():
    assert _support_from_scaffolding_strategy("procedural") == "procedural"
    assert _support_from_scaffolding_strategy({"strategy_type": "procedural", "intensity_level": "high"}) == (
        "procedural/high"
    )
    assert _support_from_scaffolding_strategy({"strategy_type": "procedural"}) == "procedural"
    assert _support_from_scaffolding_strategy(None) is None
    assert _support_from_scaffolding_strategy({}) is None


def test_go_mastery_reads_the_current_stored_level(lea_redis):
    conn = lea_redis.get_redis()
    conn.set(f"mastery:s1:{COURSE}", json.dumps({"go_masteries": {"GO1": {"level": 0.72}, "GO2": 0.4}}))
    levels = _go_mastery(conn, "s1", COURSE)
    assert levels == {"GO1": 0.72, "GO2": 0.4}


def test_go_mastery_is_empty_with_no_stored_mastery(lea_redis):
    assert _go_mastery(lea_redis.get_redis(), "nobody", COURSE) == {}


def test_a_tutor_turn_pairs_the_preceding_learner_state_with_its_answer_event(log, recorder):
    recorder.learner("s1", COURSE, "learner_state", mode="tutor", payload={
        "motivation_state": "motivation_drop",
        "cognitive_state": {"cognitive_load": 6.5, "zpd_score": 0.4},
    })
    recorder.learner("s1", COURSE, "answer", mode="tutor", go_id="GO1", correct=True, score=0.9, payload={
        "graded": True, "response": "AI is machines doing intelligent tasks",
        "recorded_question": "What is AI?", "scaffolding_strategy": "procedural",
        "scaffolding_intensity": "high",
    })

    turns = build_trace(log, recorder, "s1", COURSE, data_dir=None)
    assert len(turns) == 1
    turn = turns[0]
    assert turn["mode"] == "tutor" and turn["go_id"] == "GO1"
    assert turn["question"] == "What is AI?"
    assert turn["reply"] == "AI is machines doing intelligent tasks"
    assert turn["graded"] is True and turn["correct"] is True
    assert turn["cognitive_load"] == 6.5 and turn["zpd"] == 0.4
    assert turn["support"] == "procedural/high"
    assert turn["motivation_state"] == "motivation_drop"


def test_an_ungraded_turn_has_no_correctness_but_still_carries_state(log, recorder):
    recorder.learner("s1", COURSE, "learner_state", mode="tutor", payload={
        "motivation_state": "motivation_plateau",
        "cognitive_state": {"cognitive_load": 3.0, "zpd_score": 0.6},
    })
    recorder.learner("s1", COURSE, "answer", mode="tutor", go_id="GO1", payload={
        "graded": False, "response": "Reading, I guess", "recorded_question": None,
    })

    turns = build_trace(log, recorder, "s1", COURSE, data_dir=None)
    assert turns[0]["graded"] is False and turns[0]["correct"] is None
    assert turns[0]["question"] == ""


def test_a_quiz_turn_reads_the_question_field_and_a_dict_scaffolding_strategy(log, recorder):
    recorder.learner("s1", COURSE, "learner_state", mode="quiz", payload={
        "motivation_state": "motivation_high",
        "cognitive_state": {"cognitive_load": 4.0, "zpd_score": 0.8},
        "scaffolding_strategy": {"strategy_type": "conceptual", "intensity_level": "low"},
    })
    recorder.learner("s1", COURSE, "answer", mode="quiz", go_id="GO2", correct=False, score=0.1, payload={
        "graded": True, "response": "backpropagation", "question": "The ___ algorithm",
    })

    turns = build_trace(log, recorder, "s1", COURSE, data_dir=None)
    turn = turns[0]
    assert turn["question"] == "The ___ algorithm"
    assert turn["correct"] is False
    assert turn["support"] == "conceptual/low"


def test_turns_from_a_different_course_or_learner_are_excluded(log, recorder):
    recorder.learner("s1", COURSE, "answer", mode="tutor", go_id="GO1", correct=True, payload={"graded": True})
    recorder.learner("s1", "OTHER101", "answer", mode="tutor", go_id="GO1", correct=True, payload={"graded": True})
    recorder.learner("s2", COURSE, "answer", mode="tutor", go_id="GO1", correct=True, payload={"graded": True})

    turns = build_trace(log, recorder, "s1", COURSE, data_dir=None)
    assert len(turns) == 1


def test_week_filter_keeps_only_matching_turns(log, recorder):
    recorder.learner("s1", COURSE, "answer", mode="tutor", week=1, go_id="GO1", correct=True, payload={"graded": True})
    recorder.learner("s1", COURSE, "answer", mode="tutor", week=2, go_id="GO5", correct=True, payload={"graded": True})

    turns = build_trace(log, recorder, "s1", COURSE, data_dir=None, week=1)
    assert [t["go_id"] for t in turns] == ["GO1"]
