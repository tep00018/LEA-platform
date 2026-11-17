"""Cognitive load, ZPD and scaffolding metrics (group I) on hand-made sessions."""


from simulation import judges
from simulation import metrics as M
from simulation import support_metrics as SM


def turn(n, p, correct, level, load, zpd, zpd_level="medium", faded=False, learner="sim_a_0"):
    return {"kind": "turn", "learner": learner, "profile": "moderate_reflective", "week": 1, "round": 1, "mode": "tutor",
            "turn": n, "ts": f"2026-01-01T00:00:{n:02d}", "qtype": "tutor_reply", "student_text": "an answer",
            "intent": {"kind": "answer", "correct": correct, "p_correct": p},
            "lea": {"message": "reply", "graded": True, "correct": correct}, "retrieval": [],
            "decisions": [
                {"type": "answer", "payload": {"scaffolding_intensity": level, "scaffolding_strategy": "strategic"}},
                {"type": "cognitive_decision", "payload": {"cognitive_load": load, "zpd_score": zpd, "fatigue": 0.1,
                                                            "intervention_type": "maintain_flow",
                                                            "difficulty_adjustment": "maintain"}},
                {"type": "scaffolding_decision", "payload": {"zpd_level": zpd_level, "was_faded": faded}}]}


def data(events, judgements=()):
    return M.RunData(events, list(judgements))


def easy_then_hard(learner="sim_a_0"):
    ps = [0.95] * 5 + [0.2] * 5
    return [turn(i + 1, p, p > 0.5, "low" if p > 0.5 else "very_high", 3.0 if p > 0.5 else 8.0, 0.2 if p > 0.5 else 0.8,
                 "high" if p > 0.5 else "low", learner=learner) for i, p in enumerate(ps)]


def test_load_and_zpd_that_track_the_true_state_score_well():
    events = easy_then_hard("sim_a_0") + easy_then_hard("sim_b_0")
    out = {m["id"]: m for m in SM.compute(data(events))}
    assert out["CL1"]["value"] > 0.8 and out["CL2"]["value"] > 3
    assert out["SC2"]["value"] < 0.25  # low support when easy, very high when hard: matches the bands


def test_needed_support_bands():
    assert [SM.needed_level(x) for x in (0.95, 0.8, 0.65, 0.5, 0.1)] == [0, 1, 2, 3, 4]


def test_a_zpd_level_that_runs_backwards_fails_zpd1():
    events = []
    for who in ("sim_a_0", "sim_b_0", "sim_c_0"):
        events += [turn(i + 1, 0.9, True, "low", 3.0, 0.1, "low", learner=who) for i in range(4)]
        events += [turn(i + 5, 0.2, False, "high", 7.0, 0.9, "high", learner=who) for i in range(4)]
    out = {m["id"]: m for m in SM.compute(data(events))}
    assert out["ZPD1"]["value"] == 0.0 and out["ZPD1"]["details"]["monotone"] is False


def test_fades_are_judged_against_the_true_state():
    events = [turn(i + 1, 0.9, True, "low", 3, 0.3, faded=(i % 2 == 0)) for i in range(6)]
    events += [turn(i + 7, 0.2, False, "low", 3, 0.3, faded=True) for i in range(2)]
    sc1 = next(m for m in SM.compute(data(events)) if m["id"] == "SC1")
    assert sc1["details"]["faded_turns"] > 0 and 0 < sc1["value"] < 1


def test_lag_counts_shifts_the_support_follows():
    # success collapses after turn 4; support rises one turn later, so it is followed within 3 turns
    ps = [0.95, 0.95, 0.95, 0.95, 0.1, 0.1, 0.1, 0.1]
    levels = ["low", "low", "low", "low", "low", "very_high", "very_high", "very_high"]
    events = [turn(i + 1, p, p > 0.5, lv, 5, 0.5) for i, (p, lv) in enumerate(zip(ps, levels))]
    t1 = next(m for m in SM.compute(data(events)) if m["id"] == "T1")
    assert t1["details"]["shifts"] == 1 and t1["value"] == 1.0
    assert t1["details"]["median_lag_turns_when_followed"] == 1


def test_oscillation_counts_reversals_while_the_true_state_is_flat():
    levels = ["low", "high", "low", "high", "low", "high", "low", "high"]
    events = [turn(i + 1, 0.8, True, lv, 5, 0.5) for i, lv in enumerate(levels)]
    osc = next(m for m in SM.compute(data(events)) if m["id"] == "T2.level")
    assert osc["value"] > 5  # a flip every turn


def test_recovery_after_errors_then_two_right_answers():
    ps = [0.9, 0.2, 0.2, 0.9, 0.9, 0.9, 0.9]
    correct = [True, False, False, True, True, True, True]
    levels = ["low", "high", "very_high", "very_high", "high", "medium", "low"]
    events = [turn(i + 1, p, c, lv, 5, 0.5) for i, (p, c, lv) in enumerate(zip(ps, correct, levels))]
    t3 = next(m for m in SM.compute(data(events)) if m["id"] == "T3")
    assert t3["details"]["recoveries_observed"] == 1 and t3["value"] == 1.0


def test_sessions_too_short_or_missing_signals_do_not_break_the_metrics():
    out = SM.compute(data([turn(1, 0.5, True, "low", None, None)]))
    assert {m["id"] for m in out} >= {"CL1", "T1", "T3", "T4"}


def test_support_units_show_lea_s_support_choice_but_nothing_from_the_simulator():
    events = [{"kind": "tutor_start", "learner": "sim_a_0", "week": 1, "round": 1, "message": "Hi"}, *easy_then_hard()]
    units = judges.build_units(events)["support"]
    assert len(units) == 1 and len(units[0]["exchanges"]) == 10
    prompt = judges.support_prompt(units[0], judges.load_rubrics())
    assert "support chosen" in prompt.lower() and "p_correct" not in prompt and "moderate_reflective" not in prompt
    assert len(units[0]["exchanges"][9]["recent"]) == 5


def test_sc3_reads_judgements():
    j = {"kind": "support", "judge_role": "judge", "repeat": 0, "pass_id": "p", "learner": "sim_a_0", "unit": "u",
         "week": 1, "round": 1,
         "values": {"1": {"support_fit": "about_right", "intervention_fit": "yes"},
                    "2": {"support_fit": "too_much", "intervention_fit": "no"}}}
    sc3 = SM.sc3(data([turn(1, 0.5, True, "low", 5, 0.5)], [j]))
    assert sc3["value"] == 0.5 and sc3["details"]["too_much"] == 0.5


def test_planning_judges_a_share_of_sessions_for_sc3():
    units = {"support": [{"key": f"sim_a_{i}|w1|r1|support", "profile": "p", "learner": f"sim_a_{i}", "week": 1, "round": 1}
                         for i in range(10)]}
    jobs = judges.plan_judging(units, support_share=0.2, repeat_frac=0, second_frac=0)
    assert len([j for j in jobs if j[2] == 0 and j[3] == "judge"]) == 2
