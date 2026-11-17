"""A reviewed reference-question-bank entry is used in place of an LLM-generated question
for its exact GO and type; everything else still goes to the model. No model call is ever
made for a bank hit. See src/quiz/simple_quiz_system.py's _bank_question."""

import json

import pytest

from src.core.course_registry import CourseRegistry
from src.quiz.simple_quiz_system import SimpleQuizSystem
from tests.fakes import StubRAGTool

MC_REPLY = json.dumps({
    "question": "An LLM-generated question", "options": ["A) one", "B) two"],
    "correct_answer": "A", "explanation": "Because.",
})

MC_PLAN = {
    "go_id": "GO_01_01_001", "lo_id": "LO_01_01", "skill_name": "Define weak AI",
    "description": "Define weak AI", "keywords": ["weak ai"], "type": "multiple_choice",
    "question_number": 1, "lo_question_count": 0, "quiz_id": "q1",
    "skill_category": "conceptual", "cognitive_level": "Understand", "complexity": "basic",
}
TF_PLAN = {**MC_PLAN, "go_id": "GO_01_01_002", "type": "true_false"}


def bank_entry(go_id, qtype, **over):
    base = {
        "id": "B-1", "week": 1, "type": qtype, "go_id": go_id, "lo_id": "LO_01_01",
        "source": {"curriculum": "Test Bank"}, "tagging": {"method": "manual", "score": 1.0, "reviewed": True},
    }
    if qtype == "multiple_choice":
        base.update({"text": "A bank multiple-choice question", "options": ["Weak AI", "Strong AI", "Neither"],
                     "correct_index": 0})
    else:
        base.update({"text": "A bank true/false question", "options": ["True", "False"], "correct_index": 1})
    base.update(over)
    return base


@pytest.fixture
def registry(tmp_path):
    profiles = tmp_path / "course_profiles"
    profiles.mkdir()
    (profiles / "TST101.json").write_text(json.dumps({
        "code": "TST101", "name": "Test Course", "discipline": "computing", "allows_code": False,
    }))
    return CourseRegistry(tmp_path)


def write_bank(registry, questions):
    d = registry.data_dir / "course_sources" / "TST101"
    d.mkdir(parents=True)
    (d / "question_bank.json").write_text(json.dumps({
        "course": "TST101", "format": "lea-reference-question-bank/1", "note": "test", "questions": questions,
    }))


@pytest.fixture
def quiz(monkeypatch, registry, fake_llm):
    monkeypatch.setattr("src.quiz.simple_quiz_system.default_registry", lambda: registry)
    fake_llm._responder = lambda messages: MC_REPLY
    return SimpleQuizSystem("sk-test", rag_tool=StubRAGTool())


def test_a_reviewed_bank_question_is_used_with_no_model_call(quiz, fake_llm, registry):
    write_bank(registry, [bank_entry("GO_01_01_001", "multiple_choice")])
    question = quiz._generate_question("TST101", dict(MC_PLAN))
    assert fake_llm.calls == []
    assert question["text"] == "A bank multiple-choice question"
    assert question["bank_question_id"] == "B-1"
    assert question["go_id"] == "GO_01_01_001" and question["has_code"] is False


def test_bank_multiple_choice_options_and_answer_grade_correctly(quiz, registry):
    write_bank(registry, [bank_entry("GO_01_01_001", "multiple_choice")])
    question = quiz._generate_question("TST101", dict(MC_PLAN))
    assert question["options"] == ["A) Weak AI", "B) Strong AI", "C) Neither"]
    assert question["correct_answer"] == "A"
    from src.core import grading
    assert grading.grade_multiple_choice("A", question["correct_answer"], question["options"])["correct"]
    assert not grading.grade_multiple_choice("B", question["correct_answer"], question["options"])["correct"]


def test_bank_true_false_grades_correctly(quiz, registry):
    write_bank(registry, [bank_entry("GO_01_01_002", "true_false")])
    question = quiz._generate_question("TST101", dict(TF_PLAN))
    assert question["correct_answer"] == "False"
    from src.core import grading
    assert grading.grade_true_false("False", question["correct_answer"])["correct"]
    assert not grading.grade_true_false("True", question["correct_answer"])["correct"]


def test_an_unreviewed_bank_entry_is_never_used(quiz, fake_llm, registry):
    entry = bank_entry("GO_01_01_001", "multiple_choice")
    entry["tagging"]["reviewed"] = False
    write_bank(registry, [entry])
    question = quiz._generate_question("TST101", dict(MC_PLAN))
    assert fake_llm.calls != []  # fell through to the model
    assert question["text"] == "An LLM-generated question"


def test_a_go_with_no_bank_entry_falls_through_to_the_model(quiz, fake_llm, registry):
    write_bank(registry, [bank_entry("GO_99_99_999", "multiple_choice")])  # a different GO
    question = quiz._generate_question("TST101", dict(MC_PLAN))
    assert fake_llm.calls != []
    assert question["text"] == "An LLM-generated question"


def test_a_bank_entry_of_a_different_type_is_not_used(quiz, fake_llm, registry):
    write_bank(registry, [bank_entry("GO_01_01_001", "true_false")])  # plan wants multiple_choice
    question = quiz._generate_question("TST101", dict(MC_PLAN))
    assert fake_llm.calls != []
    assert question["text"] == "An LLM-generated question"


def test_no_bank_file_falls_through_to_the_model(quiz, fake_llm):
    question = quiz._generate_question("TST101", dict(MC_PLAN))
    assert fake_llm.calls != []
    assert question["text"] == "An LLM-generated question"


def test_a_bank_question_is_recorded_for_variety_tracking(quiz, registry):
    write_bank(registry, [bank_entry("GO_01_01_001", "multiple_choice")])
    trackers = quiz._new_trackers()
    quiz._generate_question("TST101", dict(MC_PLAN), trackers=trackers)
    assert trackers["question_history"][-1]["skill"] == "Define weak AI"
