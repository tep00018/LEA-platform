"""The personalised cognitive-load equation (src/core/cognitive_load.py)."""


from src.core import cognitive_load as cl
from src.core.cognitive_load import MemoryStore, PersonalLoad, error_rate, parse_timing


def turn(model, user="u", think_ms=8000, typing_ms=6000, chars=60, hint=False, difficulty=0.5, mastery=0.5,
         history=(), task=0.0, n=3, elapsed=None, rating=None, update=True):
    timing = {"response_ms": think_ms + typing_ms, "typing_ms": typing_ms, "chars": chars, "prompt_chars": 200,
              "hint_requested": hint}
    if elapsed is not None:
        timing["elapsed_ms"] = elapsed
    if rating is not None:
        timing["effort_rating"] = rating
    return model.estimate(user, difficulty=difficulty, mastery=mastery, correct_history=list(history), task_type=task,
                          interaction_count=n, timing=parse_timing(timing), update=update)


def settled(model, user, think_ms, turns=80):
    for k in range(turns):  # a student's times vary about 20% turn to turn
        turn(model, user, think_ms=think_ms * (0.8 if k % 2 else 1.2))


def test_the_default_model_is_the_fixed_equation(monkeypatch):
    monkeypatch.delenv(cl.MODEL_ENV, raising=False)
    assert cl.selected_model() == "fixed"
    monkeypatch.setenv(cl.MODEL_ENV, "personal")
    assert cl.selected_model() == "personal"
    monkeypatch.setenv(cl.MODEL_ENV, "nonsense")
    assert cl.selected_model() == "fixed"


def test_timing_is_validated_and_absurd_values_are_dropped():
    assert parse_timing(None) is None and parse_timing("x") is None
    t = parse_timing({"response_ms": -5, "typing_ms": "abc", "chars": 40, "effort_rating": 7, "hint_requested": 1})
    assert t == {"chars": 40.0, "hint_requested": True}
    assert parse_timing({"effort_rating": -2}) == {"hint_requested": False, "effort_rating": -2}


def test_slow_for_this_student_raises_load_but_slow_for_everyone_else_does_not():
    m = PersonalLoad(MemoryStore())
    settled(m, "slow_student", think_ms=30000)   # always takes 30 s
    settled(m, "fast_student", think_ms=6000)    # always takes 6 s
    same_day = turn(m, "slow_student", think_ms=30000, update=False)
    deviating = turn(m, "slow_student", think_ms=90000, update=False)
    fast_normal = turn(m, "fast_student", think_ms=6000, update=False)
    assert deviating["load"] > same_day["load"] + 0.2
    assert abs(same_day["slow"]) < 0.35                     # 30 s is this student's normal
    assert abs(fast_normal["slow"]) < 0.35
    assert deviating["slow"] > 0.4


def test_a_rapid_guess_adds_nothing_and_does_not_move_the_baseline():
    m = PersonalLoad(MemoryStore())
    settled(m, "u", think_ms=12000)
    n_before = m.store.load("u")["think"]["n"]
    quick = turn(m, "u", think_ms=800, typing_ms=0, chars=3)
    assert quick["rapid_guess"] is True and quick["slow"] == 0.0
    assert m.store.load("u")["think"]["n"] == n_before


def test_away_times_are_capped_and_ignored_by_the_baseline():
    m = PersonalLoad(MemoryStore())
    settled(m, "u", think_ms=10000)
    n_before = m.store.load("u")["think"]["n"]
    gone = turn(m, "u", think_ms=20 * 60 * 1000)
    assert gone["away"] is True and gone["slow"] <= 1.0
    assert m.store.load("u")["think"]["n"] == n_before


def test_help_requests_errors_and_fatigue_each_raise_load():
    m = PersonalLoad(MemoryStore())
    base = turn(m, "a", update=False)["load"]
    assert turn(m, "b", hint=True, update=False)["load"] > base
    assert turn(m, "c", history=[False, False, False], update=False)["load"] > base
    assert turn(m, "d", elapsed=40 * 60000, update=False)["load"] > base


def test_demand_is_difficulty_relative_to_mastery():
    m = PersonalLoad(MemoryStore())
    hard_for_them = turn(m, "a", difficulty=0.8, mastery=0.1, update=False)
    easy_for_them = turn(m, "b", difficulty=0.8, mastery=0.95, update=False)
    assert hard_for_them["demand"] > easy_for_them["demand"] and hard_for_them["load"] > easy_for_them["load"]


def test_error_rate_weights_recent_answers_most():
    assert error_rate([]) == 0.5
    assert error_rate([True, True, False]) > error_rate([False, True, True])


def test_ratings_make_the_behavioural_terms_count_more_for_a_sensitive_student():
    m = PersonalLoad(MemoryStore())
    # Objectives where behaviour swings and the student reports matching swings: the gain rises above 1.
    for k, (think, rating) in enumerate([(6000, None), (40000, 2), (6000, -2), (40000, 2), (6000, -2), (40000, 2)]):
        for _ in range(4):
            turn(m, "u", think_ms=think, hint=think > 20000)
        turn(m, "u", think_ms=think, hint=think > 20000, rating=rating)
    assert m.store.load("u").get("ratings")
    assert turn(m, "u", update=False)["gain"] != 1.0


def test_no_timing_means_no_behavioural_terms_and_a_finite_load():
    m = PersonalLoad(MemoryStore())
    out = m.estimate("u", difficulty=0.5, mastery=None, correct_history=[], task_type=0.0, interaction_count=1, timing=None)
    assert 0 <= out["load"] <= 10 and out["slow"] == out["typing"] == 0.0


def test_orchestrator_leaves_the_default_path_alone(orchestrator, monkeypatch):
    monkeypatch.delenv(cl.MODEL_ENV, raising=False)
    assert orchestrator._personal_load("u", {}, {}, [], 0.5, 3, 0.0, 5.0) is None            # no timing, default model
    got = orchestrator._personal_load("u", {"timing": {"response_ms": 9000, "typing_ms": 3000, "chars": 40}}, {}, [],
                                      0.5, 3, 0.0, 5.0)
    assert got and got["fixed"] == 5.0 and got["selected"] == "fixed"                        # recorded, not used
