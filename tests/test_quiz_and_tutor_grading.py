"""Quiz and Tutor grading end to end with a scripted model."""

import json

import pytest

from src.quiz.simple_quiz_system import SimpleQuizSystem
from src.tutor.simple_tutor_system import SimpleTutorSystem, TutorSession
from tests.fakes import FakeLLM, StubRAGTool


def _quiz_data(question):
    return {
        "quiz_id": "q1", "username": "s1", "course": "DEMO101", "current_question_index": 0,
        "question_plan": [{"go_id": "GO_01_01_001"}], "current_question": question, "answers": [],
    }


@pytest.fixture
def quiz(fake_llm):
    return SimpleQuizSystem("sk-test", rag_tool=StubRAGTool())


def test_multiple_choice_is_graded_without_the_model(quiz, fake_llm):
    question = {"type": "multiple_choice", "text": "Q", "options": ["A) x", "B) y"], "correct_answer": "B"}
    result = quiz.submit_answer(_quiz_data(question), "A) x")
    assert result["graded"] and result["correct"] is False
    assert fake_llm.calls == []


def test_open_ended_grading_failure_is_ungraded_not_correct(quiz, fake_llm):
    fake_llm._responder = lambda messages: "Sorry, I can't do that."
    question = {"type": "open_ended", "text": "Explain overfitting", "sample_answer": "Model memorises noise",
                "key_points": ["noise", "generalisation"]}
    result = quiz.submit_answer(_quiz_data(question), "A long answer that goes on and on about models")
    assert result["graded"] is False and result["correct"] is None and result["score"] is None


def test_motivation_changes_wording_but_not_score(quiz, fake_llm):
    fake_llm._responder = lambda messages: json.dumps({"correct": False, "score": 0.3, "explanation": "Close."})
    question = {"type": "fill_in_blank", "text": "The ___ algorithm", "correct_answer": "gradient descent"}
    data = _quiz_data(question)
    data["orchestrator_context"] = {"motivation_state": "motivation_drop"}
    result = quiz.submit_answer(data, "backpropagation")
    assert result["score"] == 0.3 and result["correct"] is False
    assert result["explanation"].startswith("Good attempt!")


def test_generated_question_with_answer_outside_options_is_rejected(quiz):
    bad = json.dumps({"question": "Q?", "options": ["A) x", "B) y"], "correct_answer": "D"})
    assert quiz._parse_generated_question(bad, "multiple_choice") is None


def test_generated_true_false_answer_is_normalised(quiz):
    ok = json.dumps({"question": "Q?", "correct_answer": "false", "explanation": "e"})
    assert quiz._parse_generated_question(ok, "true_false")["correct_answer"] == "False"


# --------------------------------------------------------------------------- tutor

GO = {"go_id": "GO_01_01_001", "skill_name": "Definition Of Ai", "description": "Recall what AI is",
      "content_keywords": ["ai_basics"], "mastery_threshold": 0.6}


def _session():
    session = TutorSession(session_id="t1", username="s1", course="DEMO101", week=1,
                           go_list=[GO, {**GO, "go_id": "GO_01_01_002"}])
    session.conversation_history.append({"role": "tutor", "content": "What is AI?"})
    session.awaiting_diagnostic = False  # past the opening "what do you know?" reply
    return session


def test_tutor_uses_the_graders_verdict_not_answer_length(monkeypatch):
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "off")  # not testing that feature here
    llm = FakeLLM(lambda m: json.dumps({"correct": False, "score": 0.2, "explanation": "Off topic."})
                  if "<answer>" in m[-1]["content"] else "Tutor reply")
    tutor = SimpleTutorSystem(llm)
    # 60+ words, an example phrase, no concept terms: the old keyword grader scored this 0.6 = correct.
    long_answer = " ".join(["I think this is likely about stuff people discuss, for example"] * 6)
    result = tutor.process_student_response(_session(), long_answer)
    assert result["graded"] is True and result["is_correct"] is False
    assert result["session_complete"] is False


def test_tutor_advances_on_a_graded_correct_answer(monkeypatch):
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "off")  # not testing that feature here
    llm = FakeLLM(lambda m: json.dumps({"correct": True, "score": 0.9, "explanation": "Yes."})
                  if "<answer>" in m[-1]["content"] else "Tutor reply")
    session = _session()
    result = SimpleTutorSystem(llm).process_student_response(session, "AI is machines doing tasks that need intelligence")
    assert result["is_correct"] and result["current_go"] == "GO_01_01_001"
    assert session.current_go_index == 1 and session.go_interaction_count == 0


def test_tutor_grading_failure_never_advances():
    llm = FakeLLM(lambda m: "no json" if "<answer>" in m[-1]["content"] else "Tutor reply")
    session = _session()
    result = SimpleTutorSystem(llm).process_student_response(session, "ai basics are about intelligent machines")
    assert result["graded"] is False
    assert session.current_go_index == 0


def test_tutor_after_last_objective_reports_completion_instead_of_crashing():
    session = _session()
    session.current_go_index = len(session.go_list)
    result = SimpleTutorSystem(FakeLLM()).process_student_response(session, "anything")
    assert result["session_complete"] is True and result["graded"] is False


def test_tutor_starts_at_first_unmastered_objective(lea_redis, username):
    lea_redis.get_redis().set(f"mastery:{username}:DEMO101", json.dumps({
        "go_masteries": {"GO_01_01_001": {"level": 0.9}, "GO_01_01_003": {"level": 0.95}},
    }))
    gos = [dict(GO, go_id=f"GO_01_01_00{i}", mastery_threshold=0.8) for i in (1, 2, 3)]
    session = TutorSession(session_id="t", username=username, course="DEMO101", week=1, go_list=gos)
    session = SimpleTutorSystem(FakeLLM(), redis_client=lea_redis)._check_prior_mastery(session)
    assert session.current_go_index == 1  # GO 2 is the first not yet mastered


def test_opening_reply_is_diagnostic_not_evidence(monkeypatch):
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "off")  # not testing that feature here
    llm = FakeLLM(lambda m: json.dumps({"correct": False, "score": 0.2, "explanation": "Not yet."})
                  if "<answer>" in m[-1]["content"] else "Tutor reply")
    session = _session()
    session.awaiting_diagnostic = True
    first = SimpleTutorSystem(llm).process_student_response(session, "I'm not sure yet, maybe robots?")
    assert first["diagnostic"] is True and first["graded"] is False
    second = SimpleTutorSystem(llm).process_student_response(session, "Robots that think")
    assert second["diagnostic"] is False and second["graded"] is True


def test_hedged_answer_is_sent_to_the_grader(monkeypatch):
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "off")  # not testing that feature here
    llm = FakeLLM(lambda m: json.dumps({"correct": True, "score": 0.9, "explanation": "Yes."})
                  if "<answer>" in m[-1]["content"] else "Tutor reply")
    result = SimpleTutorSystem(llm).process_student_response(
        _session(), "I'm not sure, but I think AI means machines doing tasks that need intelligence")
    assert result["graded"] and result["is_correct"]


def test_opening_message_introduces_the_objective_the_session_starts_on(lea_redis, username):
    lea_redis.get_redis().set(f"mastery:{username}:DEMO101", json.dumps({
        "go_masteries": {"GO_01_01_001": {"level": 0.95}},
    }))
    gos = [dict(GO, go_id="GO_01_01_001", skill_name="Definition Of Ai", mastery_threshold=0.8),
           dict(GO, go_id="GO_01_01_002", skill_name="Types Of Ai", mastery_threshold=0.8)]
    session = SimpleTutorSystem(FakeLLM(), redis_client=lea_redis).start_tutoring_session(
        "DEMO101", 1, username, None, gos)
    assert session.current_go_index == 1
    opening = session.conversation_history[-1]
    assert "Types Of Ai" in opening["content"] and opening["go_id"] == "GO_01_01_002"


# --------------------------------------------------------------------------- LEA_TUTOR_RECORDED_QUESTION (research)

def _responder_for(extraction_reply):
    def respond(messages):
        system = messages[0]["content"]
        if "ONE required checkable question" in system:
            return json.dumps(extraction_reply)
        if "<answer>" in messages[-1]["content"]:
            return json.dumps({"correct": True, "score": 0.9, "explanation": "Yes."})
        return "Some tutor reply. What do you think about AI?"
    return respond


def test_recorded_question_is_on_by_default_since_2026_09_27(monkeypatch):
    monkeypatch.delenv("LEA_TUTOR_RECORDED_QUESTION", raising=False)
    llm = FakeLLM(_responder_for({"question": "What distinguishes weak AI from strong AI?", "about_this_objective": True}))
    session = _session()
    SimpleTutorSystem(llm).process_student_response(session, "AI is machines doing intelligent tasks")
    assert any("ONE required checkable question" in c["messages"][0]["content"] for c in llm.calls)


def test_recorded_question_can_still_be_switched_off(monkeypatch):
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "off")
    llm = FakeLLM(_responder_for({"question": "What is AI?", "about_this_objective": True}))
    session = _session()
    SimpleTutorSystem(llm).process_student_response(session, "AI is machines doing intelligent tasks")
    assert not any("ONE required checkable question" in c["messages"][0]["content"] for c in llm.calls)


def test_recorded_question_is_extracted_at_grading_time_and_used_instead_of_the_raw_message(monkeypatch):
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "on")
    monkeypatch.setenv("LEA_TUTOR_QUESTION_SCOPE", "strict")  # testing extraction mechanics, not scope
    # the session's existing tutor message is "What is AI?"; extraction returns a different, cleaned-up
    # question, which must be what reaches the grader -- not the raw message.
    llm = FakeLLM(_responder_for({"question": "What distinguishes weak AI from strong AI?", "about_this_objective": True}))
    session = _session()
    result = SimpleTutorSystem(llm).process_student_response(session, "Weak AI does one task, strong AI is general")
    extraction_calls = [c for c in llm.calls if "ONE required checkable question" in c["messages"][0]["content"]]
    grading_calls = [c for c in llm.calls if "<answer>" in c["messages"][-1]["content"]]
    assert len(extraction_calls) == 1  # exactly one extraction call, at grading time
    assert "distinguishes weak AI from strong AI" in grading_calls[-1]["messages"][-1]["content"]
    assert "What is AI?" not in grading_calls[-1]["messages"][-1]["content"]
    assert result["graded"] is True and result["one_question_about_objective"] is True


def test_a_question_not_about_the_objective_is_never_sent_to_the_grader(monkeypatch):
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "on")
    monkeypatch.setenv("LEA_TUTOR_QUESTION_SCOPE", "strict")  # testing extraction mechanics, not scope
    llm = FakeLLM(_responder_for({"question": "What's your favourite hobby?", "about_this_objective": False}))
    result = SimpleTutorSystem(llm).process_student_response(_session(), "Reading, I guess")
    assert result["graded"] is False and result["one_question_about_objective"] is False
    assert not any("<answer>" in c["messages"][-1]["content"] for c in llm.calls)  # never even sent to the grader


def test_extraction_failure_leaves_the_turn_ungraded_not_guessed(monkeypatch):
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "on")
    llm = FakeLLM(_responder_for({"question": "", "about_this_objective": True}))  # empty question: invalid
    result = SimpleTutorSystem(llm).process_student_response(_session(), "Anything at all")
    assert result["graded"] is False and result["one_question_extracted"] is False


def test_no_extraction_call_at_all_if_the_student_never_replies():
    # the point of extracting at grading time: nothing is spent unless a reply actually arrives.
    llm = FakeLLM(_responder_for({"question": "What is AI?", "about_this_objective": True}))
    SimpleTutorSystem(llm)  # constructed, never asked to process a reply
    assert llm.calls == []


# --------------------------------------------------------------------------- LEA_TUTOR_QUESTION_SCOPE=broad (research)

def _two_go_session():
    other = {**GO, "go_id": "GO_01_01_002", "skill_name": "Machine Learning Basics"}
    session = TutorSession(session_id="t2", username="s1", course="DEMO101", week=1, go_list=[GO, other])
    session.conversation_history.append({"role": "tutor", "content": "What is AI?"})
    session.awaiting_diagnostic = False
    return session


def _broad_responder(category, question="A recorded question"):
    def respond(messages):
        system = messages[0]["content"]
        if "ONE required checkable question" in system:
            assert "Machine Learning Basics" in system  # the other GO must be offered to the extractor
            return json.dumps({"question": question, "category": category})
        if "<answer>" in messages[-1]["content"]:
            return json.dumps({"correct": True, "score": 0.9, "explanation": "Yes."})
        return "Some tutor reply. What do you think about AI?"
    return respond


def test_broad_scope_is_on_by_default_since_2026_09_27(monkeypatch):
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "on")
    monkeypatch.delenv("LEA_TUTOR_QUESTION_SCOPE", raising=False)  # broad by default
    llm = FakeLLM(_broad_responder("related_comparison"))
    result = SimpleTutorSystem(llm).process_student_response(_two_go_session(), "an answer")
    assert any("category" in c["messages"][0]["content"] and "one of" in c["messages"][0]["content"]
              for c in llm.calls)  # the 4-category extraction prompt was used, not the plain two-field one
    assert result["graded"] is True  # a related comparison counts by default


def test_strict_scope_can_still_be_selected(monkeypatch):
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "on")
    monkeypatch.setenv("LEA_TUTOR_QUESTION_SCOPE", "strict")
    llm = FakeLLM(_responder_for({"question": "What is AI?", "about_this_objective": True}))
    SimpleTutorSystem(llm).process_student_response(_two_go_session(), "an answer")
    assert not any("category" in c["messages"][0]["content"] and "one of" in c["messages"][0]["content"]
                  for c in llm.calls)  # the plain, two-field extraction prompt was used, not the 4-category one


def test_broad_scope_counts_a_related_comparison_as_about_the_objective(monkeypatch):
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "on")
    monkeypatch.setenv("LEA_TUTOR_QUESTION_SCOPE", "broad")
    llm = FakeLLM(_broad_responder("related_comparison"))
    result = SimpleTutorSystem(llm).process_student_response(_two_go_session(), "an answer")
    assert result["graded"] is True and result["one_question_about_objective"] is True
    assert result["one_question_category"] == "related_comparison"


def test_broad_scope_still_leaves_a_same_week_other_go_question_ungraded(monkeypatch):
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "on")
    monkeypatch.setenv("LEA_TUTOR_QUESTION_SCOPE", "broad")
    llm = FakeLLM(_broad_responder("same_week_other_go"))
    result = SimpleTutorSystem(llm).process_student_response(_two_go_session(), "an answer")
    assert result["graded"] is False and result["one_question_category"] == "same_week_other_go"
    assert not any("<answer>" in c["messages"][-1]["content"] for c in llm.calls)  # never sent to the grader


def test_broad_scope_leaves_outside_week_ungraded(monkeypatch):
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "on")
    monkeypatch.setenv("LEA_TUTOR_QUESTION_SCOPE", "broad")
    llm = FakeLLM(_broad_responder("outside_week"))
    result = SimpleTutorSystem(llm).process_student_response(_two_go_session(), "an answer")
    assert result["graded"] is False and result["one_question_category"] == "outside_week"


def test_broad_scope_still_counts_current_as_before(monkeypatch):
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "on")
    monkeypatch.setenv("LEA_TUTOR_QUESTION_SCOPE", "broad")
    llm = FakeLLM(_broad_responder("current"))
    result = SimpleTutorSystem(llm).process_student_response(_two_go_session(), "an answer")
    assert result["graded"] is True and result["one_question_category"] == "current"


def test_an_invalid_category_from_the_model_is_treated_as_extraction_failure(monkeypatch):
    monkeypatch.setenv("LEA_TUTOR_RECORDED_QUESTION", "on")
    monkeypatch.setenv("LEA_TUTOR_QUESTION_SCOPE", "broad")
    llm = FakeLLM(_broad_responder("not_a_real_category"))
    result = SimpleTutorSystem(llm).process_student_response(_two_go_session(), "an answer")
    assert result["graded"] is False and result["one_question_extracted"] is False
