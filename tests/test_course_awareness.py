"""Course profiles decide course-specific behaviour; nothing falls back to another course."""

import json

import pytest

from src.core.course_registry import CourseRegistry
from src.core.kc_model_loader import KCModelLoader
from src.quiz.simple_quiz_system import SimpleQuizSystem
from tests.fakes import StubRAGTool

MC_REPLY = json.dumps({
    "question": "Which option is right?",
    "options": ["A) one", "B) two", "C) three", "D) four"],
    "correct_answer": "B",
    "explanation": "Because.",
})

# A plan the old code always turned into a Python question: 'Apply' level at position 6.
APPLY_PLAN = {
    "go_id": "GO_02_01_001", "lo_id": "LO_02_01", "skill_name": "Apply the bystander model",
    "description": "Apply the model to a real scenario", "keywords": ["bystander effect"],
    "type": "multiple_choice", "question_number": 6, "lo_question_count": 0,
    "quiz_id": "q1", "skill_category": "application", "cognitive_level": "Apply", "complexity": "advanced",
}


@pytest.fixture
def registry(tmp_path):
    profiles = tmp_path / "course_profiles"
    profiles.mkdir()
    (profiles / "PSY999.json").write_text(json.dumps({
        "code": "PSY999", "name": "Test Psychology", "discipline": "social_science", "allows_code": False,
    }))
    (profiles / "CMP999.json").write_text(json.dumps({
        "code": "CMP999", "name": "Test Programming", "discipline": "computing",
        "allows_code": True, "code_language": "python",
    }))
    return CourseRegistry(tmp_path)


@pytest.fixture
def quiz(monkeypatch, registry, fake_llm):
    monkeypatch.setattr("src.quiz.simple_quiz_system.default_registry", lambda: registry)
    fake_llm._responder = lambda messages: MC_REPLY
    system = SimpleQuizSystem("sk-test", rag_tool=StubRAGTool())
    return system


def test_non_programming_course_never_gets_code_questions(quiz, fake_llm):
    question = quiz._generate_question("PSY999", dict(APPLY_PLAN))
    prompt = fake_llm.last_prompt
    assert question["has_code"] is False
    assert "CODING QUESTION" not in prompt
    assert "does not involve programming" in prompt
    assert "sklearn" not in prompt


def test_programming_course_can_still_get_code_questions(quiz, fake_llm):
    question = quiz._generate_question("CMP999", dict(APPLY_PLAN))
    assert question["has_code"] is True
    assert "CODING QUESTION" in fake_llm.last_prompt


def test_course_without_profile_defaults_to_no_code(registry):
    profile = registry.profile("ABC123")
    assert profile.allows_code is False and profile.from_file is False


def test_demo_course_profile_is_committed():
    from src.core.course_registry import default_registry

    profile = default_registry().profile("DEMO101")
    assert profile.from_file and profile.allows_code and profile.code_language == "python"
    assert "DEMO101" in default_registry().available_courses()


def test_unknown_course_is_an_error_not_another_courses_model(lea_redis):
    loader = KCModelLoader(lea_redis, module="ZZZ999")
    with pytest.raises(FileNotFoundError):
        loader.load_course_model("ZZZ999")


@pytest.mark.parametrize("bad", ["../../etc", "DEMO101/../x", "", "demo 101"])
def test_course_codes_that_could_escape_the_data_folder_are_rejected(lea_redis, bad):
    with pytest.raises(ValueError):
        KCModelLoader(lea_redis, module=bad)
