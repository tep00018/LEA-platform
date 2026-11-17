"""The simulated students' hidden load and timing, and the comparison of the two load equations."""

import json

import numpy as np

from simulation import arms
from simulation.metrics import RunData
from simulation.signals import HumanSignals


def obs(sig, go="g1", demand=0.5, task=0.0, prompt=200, chars=40, kind="answer", engagement="steady"):
    return sig.observe(go, demand=demand, task=task, prompt_chars=prompt, chars=chars, kind=kind, engagement=engagement,
                       answer_attempt=kind == "answer")


def test_the_same_seed_gives_the_same_student_and_a_checkpoint_continues_exactly():
    a, b = HumanSignals(7), HumanSignals(7)
    first = [obs(a, demand=0.3 + 0.05 * i) for i in range(6)]
    assert first == [obs(b, demand=0.3 + 0.05 * i) for i in range(6)]
    saved = json.loads(json.dumps(a.state()))
    c = HumanSignals(7)
    c.load_state(saved)
    assert obs(a) == obs(c)


def test_students_differ_and_harder_demand_means_more_load_and_longer_thinking():
    easy = np.mean([obs(HumanSignals(i), demand=0.1)["true_load"] for i in range(40)])
    hard = np.mean([obs(HumanSignals(i), demand=0.95)["true_load"] for i in range(40)])
    assert hard > easy + 1.5
    assert len({round(HumanSignals(s).p["think0"], 2) for s in range(40)}) > 20
    slow = np.mean([obs(HumanSignals(i), demand=0.95)["timing"]["response_ms"] for i in range(60)])
    quick = np.mean([obs(HumanSignals(i), demand=0.05)["timing"]["response_ms"] for i in range(60)])
    assert slow > quick


def test_fatigue_builds_over_a_session_and_resets_with_a_new_one():
    s = HumanSignals(3)
    early = np.mean([obs(s, demand=0.5)["true_load"] for _ in range(3)])
    for _ in range(60):
        obs(s, demand=0.5)
    late = np.mean([obs(s, demand=0.5)["true_load"] for _ in range(3)])
    assert late > early
    s.start_session()
    assert s.elapsed_ms == 0.0


def test_disengaged_students_make_rapid_guesses():
    s = HumanSignals(11)
    rapid = [obs(s, engagement="disengaging")["rapid_guess"] for _ in range(60)]
    assert 8 < sum(rapid) < 45
    assert not any(obs(HumanSignals(2), engagement="engaged")["rapid_guess"] for _ in range(20))


def test_a_harder_objective_produces_a_positive_relative_rating():
    ratings = []
    for seed in range(20):
        r = HumanSignals(seed)
        for _ in range(6):
            obs(r, go="g1", demand=0.1)
        for _ in range(6):
            obs(r, go="g2", demand=0.9)
        ratings.append(obs(r, go="g3", demand=0.9)["timing"].get("effort_rating"))
    given = [x for x in ratings if x is not None]
    assert given and np.mean(given) > 0


def ev(learner, i, true, fixed, personal, level, selected=None):
    return {"kind": "turn", "learner": learner, "profile": "p", "week": 1, "round": 1, "mode": "tutor", "turn": i,
            "true_load": true, "intent": {"kind": "answer", "correct": True, "p_correct": 0.5}, "student_text": "x",
            "decisions": [
                {"type": "learner_state", "payload": {"cognitive_state": {
                    "cognitive_load": personal if selected is None else selected,
                    "load_details": {"fixed": fixed, "load": personal, "rapid_guess": False, "gain": 1.0}}}},
                {"type": "answer", "payload": {"scaffolding_intensity": level}}]}


def run_events(learners, tracker):
    rng = np.random.default_rng(0)
    events = []
    for name in learners:
        for i in range(20):
            true = float(rng.uniform(1, 9))
            noisy = float(np.clip(true + rng.normal(0, 3), 0, 10))
            good = float(np.clip(true + rng.normal(0, 0.3), 0, 10))
            driving = noisy if tracker == "fixed" else good
            level = ("very_high" if driving >= 8 else "high" if driving >= 6 else "medium" if driving >= 4
                     else "low" if driving >= 2 else "minimal")
            events.append(ev(name, i + 1, true, noisy, good, level, selected=driving))
    return events


def test_within_a_run_the_better_tracker_is_measured_better_and_paired():
    data = RunData(run_events([f"l{i}" for i in range(8)], "personal"), [])
    out = {m["id"]: m for m in arms.run_metrics(data)}
    assert out["CLT.personal"]["value"] > out["CLT.fixed"]["value"]
    assert out["CLT.diff_r"]["value"] > 0.3 and out["CLT.diff_mae"]["value"] < 0
    assert out["CLT.diff_r"]["details"]["p_wilcoxon"] < 0.05


def test_two_arms_are_compared_learner_by_learner_with_holm_over_the_primary_outcomes():
    names = [f"l{i}" for i in range(10)]
    result = arms.compare(RunData(run_events(names, "fixed"), []), RunData(run_events(names, "personal"), []))
    assert len(result["matched"]) == 10
    p1, p2 = result["primary"]["P1"], result["primary"]["P2"]
    assert p1["mean_diff"] > 0 and p1["favours_b"] and p1["significant"]
    assert p2["mean_diff"] < 0 and p2["favours_b"] and p2["p_holm"] >= 0
    text = arms.format_comparison(result, "A", "B")
    assert "P1" in text and "Holm" in text and "cannot show learning gains" in text


def test_unmatched_learners_are_left_out_not_imputed():
    a = run_events(["l0", "l1", "l2"], "fixed")
    b = run_events(["l1", "l2", "l3"], "personal")
    assert arms.compare(RunData(a, []), RunData(b, []))["matched"] == ["l1", "l2"]


def test_load_needed_level_bands():
    assert [arms.load_needed_level(x) for x in (9, 7, 5, 3, 1)] == [4, 3, 2, 1, 0]
