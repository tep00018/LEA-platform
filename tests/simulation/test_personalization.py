"""The personalisation study: reproducible, and it measures what it claims to."""

import numpy as np
import pytest

from simulation import personalization as P

SMALL = dict(learners_per_profile=6, train_learners=36)


def test_the_study_is_reproducible_from_its_seed():
    a = P.study(P.Config(**SMALL))
    b = P.study(P.Config(**SMALL))
    assert a["load"]["E1"]["r_pooled"]["value"] == b["load"]["E1"]["r_pooled"]["value"]
    assert P.study(P.Config(**SMALL, seed=1))["load"]["E1"]["r_pooled"]["value"] != a["load"]["E1"]["r_pooled"]["value"]


def test_lea_s_formula_is_reproduced_exactly():
    x = np.array([1.0, 0.5, 0.4, 2.0, 1.0, 0.0, 0.0])  # difficulty .5, inaccuracy .4, 20 interactions, open-ended
    assert P.lea_load(x) == pytest.approx(0.5 + 0.5 + 4.5 * 0.4 + 0.1 * 20 + 1.0)
    assert P.lea_load(np.array([1.0, 1.0, 1.0, 9.0, 1.0, 0, 0])) == pytest.approx(10)  # bounded at 10


def test_truth_is_hidden_from_every_estimator_input():
    L = P.simulate_learner(np.random.default_rng(0), "moderate_reflective", P.Config())
    norms = P.Norms([L])
    x = P.load_features(L, 5, norms)
    assert x.shape == (len(P.FEATURES),) and not np.isclose(x, L["load_true"][5]).any()


def test_a_population_model_beats_the_fixed_formula_and_personal_ratings_help_when_learners_differ():
    r = P.study(P.Config(**SMALL))
    assert r["load"]["E1"]["r_pooled"]["value"] > r["load"]["E0"]["r_pooled"]["value"]
    assert r["load"]["E2"]["mae"]["value"] < r["load"]["E1"]["mae"]["value"]
    assert r["zpd"]["Z1"]["brier"]["value"] < r["zpd"]["Z0"]["brier"]["value"]


def test_without_ratings_behaviour_alone_still_beats_the_fixed_formula():
    r = P.study(P.Config(**SMALL))
    assert r["load"]["E3"]["r_pooled"]["value"] > r["load"]["E0"]["r_pooled"]["value"]


def test_the_report_lists_every_estimator():
    text = P.format_report(P.study(P.Config(**SMALL)))
    for name in ("E0", "E1", "E2", "E3", "Z0", "Z1", "Z2"):
        assert name in text
