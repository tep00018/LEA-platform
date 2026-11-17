"""S1: the learner model and profiles (docs/simulation/PLAN.md, section 1).

BKT behaves as its formulas say (M0c), and every profile parameter changes behaviour.
"""

import copy
import statistics

import pytest

from simulation.learner import (ENGAGEMENT, Intent, Learner, build_profiles, go_difficulties, learner_seed,
                                make_learner, sigmoid)
from simulation.settings import load
from simulation.validity import m0c

CONFIG = load()
N = 4000
GOS = {f"G{i:05d}": 0.0 for i in range(N)}


def learner(profile="inconsistent_adaptive", config=CONFIG, gos=GOS, seed=1, **params):
    config = copy.deepcopy(config)
    config["profiles"][profile].update(params)
    p = build_profiles(config)[profile]
    return Learner(f"sim_{profile}_0", p, gos, config["learner"], seed)


def with_learner_cfg(**over):
    config = copy.deepcopy(CONFIG)
    config["learner"].update(over)
    return config


def accuracy(lr, qtype="tutor_reply", known=True, n=N):
    for g in list(lr.known)[:n]:
        lr.known[g] = known
    return sum(lr.turn(g, qtype, may_digress=False).correct for g in list(lr.known)[:n]) / n


def intents(lr, turns=6000):
    counts = dict.fromkeys(("answer", "question", "minimal", "quit"), 0)
    for _ in range(turns):
        counts[lr.turn("G00000").kind] += 1
    return {k: v / turns for k, v in counts.items()}


def start_known(lr):
    return sum(lr.known.values()) / len(lr.known)


def learned_after(lr, exchanges):
    answer = Intent("answer", None, "tutor_reply", None, None, None, "steady", None)
    for g in lr.known:
        for _ in range(exchanges):
            lr.after_tutor_exchange(g, answer)
    return sum(lr.known.values()) / len(lr.known)


# ---------------------------------------------------------------------------- M0c


def test_m0c_the_simulated_learners_match_the_bkt_formulas():
    result = m0c(CONFIG, draws=10_000)
    assert result["passed"], [r for r in result["rows"] if r["deviation"] > 0.01]
    assert {r["profile"] for r in result["rows"]} == set(CONFIG["profiles"])


def test_start_state_follows_ability_and_difficulty():
    lr = learner(theta=0.8)
    assert abs(start_known(lr) - sigmoid(0.8)) < 0.02
    hard = learner(theta=0.8, gos={g: 1.0 for g in GOS})
    assert start_known(hard) < start_known(lr) - 0.1


# ---------------------------------------------------------------------------- each parameter matters


def test_theta_changes_starting_knowledge():
    assert start_known(learner(theta=1.5)) > start_known(learner(theta=-1.5)) + 0.5


def test_p_learn_changes_learning_speed():
    assert learned_after(learner(theta=-3, p_learn=0.3), 2) > learned_after(learner(theta=-3, p_learn=0.1), 2) + 0.2


def test_quiz_feedback_teaches_less_than_a_tutor_exchange():
    tutor, quiz = learner(theta=-3, p_learn=0.3), learner(theta=-3, p_learn=0.3)
    learned_after(tutor, 1)
    for g in quiz.known:
        quiz.after_quiz_feedback(g)
    assert abs(start_known(quiz) - (1 - (1 - sigmoid(-3)) * (1 - 0.15))) < 0.02
    assert start_known(tutor) > start_known(quiz) + 0.1
    faster = learner(config=with_learner_cfg(quiz_learning_factor=1.0), theta=-3, p_learn=0.3)
    for g in faster.known:
        faster.after_quiz_feedback(g)
    assert start_known(faster) > start_known(quiz) + 0.1


def test_minimal_replies_and_quitting_are_not_learning_opportunities():
    lr = learner(theta=-5, p_learn=1.0)
    lr.after_tutor_exchange("G00001", Intent("minimal", "G00001", "tutor_reply", None, None, None, "steady", None))
    lr.after_tutor_exchange("G00002", Intent("quit", "G00002", "tutor_reply", None, None, None, "steady", None))
    lr.after_tutor_exchange("G00003", Intent("question", "G00003", "tutor_reply", None, None, None, "steady", None))
    assert (lr.known["G00001"], lr.known["G00002"], lr.known["G00003"]) == (False, False, True)
    assert lr.p_know("G00001") < 0.01 and lr.p_know("G00003") == pytest.approx(1.0)


def test_slip_changes_accuracy_when_known():
    assert accuracy(learner(slip=0.02)) > accuracy(learner(slip=0.25)) + 0.15


def test_question_type_difficulty_and_guessing_are_inputs():
    lr = learner(slip=0.05)
    assert accuracy(lr, "multiple_choice") > accuracy(lr, "open_ended") + 0.05  # d_type
    assert accuracy(lr, "true_false", known=False) > accuracy(lr, "multiple_choice", known=False) + 0.15
    assert accuracy(lr, "multiple_choice", known=False) > accuracy(lr, "fill_in", known=False) + 0.15
    harder = learner(config=with_learner_cfg(d_type={**CONFIG["learner"]["d_type"], "open_ended": 0.3}), slip=0.05)
    assert accuracy(harder, "open_ended") < accuracy(lr, "open_ended") - 0.1


def test_sigma_makes_sessions_inconsistent():
    def session_accuracies(sigma):
        lr = learner(sigma=sigma, slip=0.2)
        out = []
        for _ in range(60):
            lr.start_session()
            out.append(accuracy(lr, n=300))
        return statistics.pstdev(out)

    assert session_accuracies(0.8) > 2 * session_accuracies(0.05)


@pytest.mark.parametrize("rate,kind", [("ask", "question"), ("minimal", "minimal"), ("quit", "quit")])
def test_turn_rates_change_what_the_learner_does(rate, kind):
    low = intents(learner(**{"ask": 0.1, "minimal": 0.05, "quit": 0.01, rate: 0.02}))
    high = intents(learner(**{"ask": 0.1, "minimal": 0.05, "quit": 0.01, rate: 0.30}))
    assert high[kind] > low[kind] + 0.2


def test_each_profile_average_rates_match_the_configured_values():
    """Engagement tilts the rates turn by turn, but the average is what the profile says (M0b's basis)."""
    for key, p in CONFIG["profiles"].items():
        lr = learner(key)
        seen = intents(lr, turns=20_000)
        assert seen["question"] == pytest.approx(p["ask"], abs=0.02), key
        assert seen["minimal"] == pytest.approx(p["minimal"], abs=0.02), key
        assert seen["quit"] == pytest.approx(p["quit"], abs=0.01), key


def test_the_engagement_mix_follows_the_profile():
    def share(profile):
        lr = learner(profile)
        states = []
        for _ in range(20_000):
            lr.turn("G00000")
            states.append(lr.engagement_state)
        return {s: states.count(s) / len(states) for s in ENGAGEMENT}

    assert share("advanced_eager")["engaged"] > 0.6
    assert share("capable_disengaged")["disengaging"] > 0.5
    changed = learner(engagement={"engaged": 0.05, "steady": 0.05, "disengaging": 0.9})
    changed_states = []
    for _ in range(5000):
        changed.turn("G00000")
        changed_states.append(changed.engagement_state)
    assert changed_states.count("disengaging") / 5000 > 0.8


def test_engagement_rates_differ_by_state():
    rates = build_profiles(CONFIG)["capable_disengaged"].state_rates
    assert rates["disengaging"]["minimal"] > rates["engaged"]["minimal"] * 3
    assert rates["engaged"]["ask"] > rates["disengaging"]["ask"]


def test_persistence_makes_engagement_sticky():
    def switches(persistence):
        lr = learner(config=with_learner_cfg(engagement_persistence=persistence))
        prev, n = None, 0
        for _ in range(5000):
            lr.turn("G00000")
            n += prev is not None and lr.engagement_state != prev
            prev = lr.engagement_state
        return n

    assert switches(0.1) > 3 * switches(0.9)


def test_reply_length_sets_target_words():
    words = CONFIG["learner"]["reply_words"]
    assert learner(reply_length="very_short").target_words() == words["very_short"]
    assert learner(reply_length="long").target_words() == words["long"]
    varied = {learner(reply_length="varies", seed=s).target_words() for s in range(40)}
    assert len(varied) >= 3


def test_bloom_levels_and_jitter_set_go_difficulty():
    gos = [{"go_id": f"GO_{i}", "cognitive_level": level} for i, level in
           enumerate(["Remember"] * 200 + ["Apply"] * 200 + ["Analyze"] * 200 + [None] * 200)]
    b = go_difficulties(gos, CONFIG["learner"], seed=7)
    mean = {lvl: statistics.mean(b[f"GO_{i}"] for i in range(k * 200, k * 200 + 200))
            for k, lvl in enumerate(["remember", "apply", "analyze", "none"])}
    assert mean["remember"] == pytest.approx(-0.5, abs=0.06) and mean["apply"] == pytest.approx(0, abs=0.06)
    assert mean["analyze"] == pytest.approx(0.5, abs=0.06) and mean["none"] == pytest.approx(0, abs=0.06)
    assert statistics.pstdev(b[f"GO_{i}"] for i in range(200)) == pytest.approx(0.3, abs=0.05)
    assert go_difficulties(list(reversed(gos)), CONFIG["learner"], seed=7) == b  # order-independent
    assert go_difficulties(gos, CONFIG["learner"], seed=8) != b
    flat = go_difficulties(gos, {**CONFIG["learner"], "difficulty_jitter_sd": 0.0}, seed=7)
    assert set(flat.values()) == {-0.5, 0.0, 0.5}


# ---------------------------------------------------------------------------- seeds and options


def test_learners_are_reproducible_and_distinct():
    b = {f"GO_{i}": 0.0 for i in range(50)}
    one, again = make_learner(CONFIG, "novice_variable", 0, b), make_learner(CONFIG, "novice_variable", 0, b)
    other = make_learner(CONFIG, "novice_variable", 1, b)
    assert one.username == "sim_novice_variable_0" and one.known == again.known
    assert [one.turn("GO_1").kind for _ in range(50)] == [again.turn("GO_1").kind for _ in range(50)]
    assert learner_seed(1, "novice_variable", 0) != learner_seed(1, "novice_variable", 1)
    assert one.known != other.known or [one.turn("GO_2").kind for _ in range(30)] != \
        [other.turn("GO_2").kind for _ in range(30)]


def test_the_starting_state_does_not_depend_on_the_conversation():
    b = {f"GO_{i}": 0.0 for i in range(50)}
    quiet, chatty = make_learner(CONFIG, "struggling_eager", 3, b), make_learner(CONFIG, "struggling_eager", 3, b)
    for _ in range(100):
        chatty.turn("GO_1")
    assert quiet.known == chatty.known


def test_wrong_options_are_never_the_right_one():
    lr = learner()
    options = ["A", "B", "C", "D"]
    picks = {lr.pick_option(options, 2, correct=False) for _ in range(200)}
    assert picks == {0, 1, 3} and lr.pick_option(options, 2, correct=True) == 2


def test_bad_profiles_are_rejected():
    config = copy.deepcopy(CONFIG)
    config["profiles"]["novice_variable"]["engagement"] = {"engaged": 0.5, "steady": 0.5, "disengaging": 0.5}
    with pytest.raises(ValueError, match="add up"):
        build_profiles(config)
    config = copy.deepcopy(CONFIG)
    config["profiles"]["novice_variable"].update(ask=0.7, minimal=0.4)
    with pytest.raises(ValueError, match="exceed"):
        build_profiles(config)
