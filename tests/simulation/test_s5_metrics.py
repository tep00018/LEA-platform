"""S5: every metric on synthetic logs with known answers, the statistics, and the report."""

import json
import math

import pytest

from simulation import metrics as M
from simulation import stats as S
from simulation.report import write
from simulation.settings import load

CONFIG = load()
_ts = iter(range(1, 10_000_000))


def turn(learner="sim_a_0", profile="advanced_eager", mode="tutor", *, week=1, round=1, n=None, go="GO_1",
         qtype="tutor_reply", kind="answer", correct=True, p=0.8, known=True, engagement="engaged", text="an answer",
         graded=True, lea_correct=None, level=None, zpd=None, motivation=None, diagnostic=False, mastery_after=None,
         threshold=0.7, message="Tutor reply.", **extra):
    decisions = []
    if level or diagnostic:
        decisions.append({"type": "answer", "payload": {"scaffolding_intensity": level, "diagnostic": diagnostic}})
    if zpd is not None or motivation:
        decisions.append({"type": "learner_state", "payload": {"motivation_state": motivation,
                                                                "cognitive_state": {"zpd_score": zpd}}})
    t = next(_ts)
    return {"kind": "turn", "ts": f"2026-09-26T00:00:{t:08d}", "learner": learner, "profile": profile, "week": week,
            "round": round, "mode": mode, "turn": n if n is not None else t, "go_id": go, "qtype": qtype,
            "intent": {"kind": kind, "correct": correct if kind == "answer" else None, "p_correct": p, "known": known,
                       "engagement": engagement, "target_words": None},
            "student_text": text, "hidden_before": {"known": known, "p_know": p},
            "lea": {"graded": graded, "correct": correct if lea_correct is None else lea_correct, "message": message},
            "mastery": {"after": mastery_after, "threshold": threshold}, "decisions": decisions, **extra}


def week_end(learner, profile, gos, advanced=2, week=1):
    return {"kind": "week_end", "learner": learner, "profile": profile, "week": week, "advanced_to_week": advanced,
            "gos": [{"go_id": f"G{i}", "lea_mastery": lea, "threshold": 0.7, "lea_mastered": lea is not None and lea >= 0.7,
                     "known": known, "p_know": pk} for i, (lea, known, pk) in enumerate(gos)]}


def judgement(kind, learner, values, *, unit=None, repeat=0, role="judge", week=1, round=1, pass_id="p"):
    return {"kind": kind, "unit": unit or f"{learner}|w{week}|r{round}|{kind}", "learner": learner, "week": week,
            "round": round, "repeat": repeat, "judge_role": role, "values": values, "pass_id": pass_id}


def data(events, judgements=()):
    return M.RunData(list(events), list(judgements))


# ---------------------------------------------------------------------------- statistics


def test_agreement_statistics_on_known_cases():
    assert S.cohen_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0
    assert S.cohen_kappa([1, 0, 1, 0], [0, 1, 0, 1]) == -1.0
    assert S.cohen_kappa(["y", "y", "y", "n"], ["y", "y", "n", "n"]) == pytest.approx(0.5)
    assert S.fleiss_kappa([["y", "y", "y"], ["n", "n", "n"], ["y", "y", "y"]]) == pytest.approx(1.0)
    assert S.fleiss_kappa([["y", "n", "y"], ["n", "y", "n"]]) < 0
    assert S.icc_2_1([[1, 1], [3, 3], [5, 5]]) == pytest.approx(1.0)
    assert S.icc_2_1([[1, 5], [5, 1], [3, 3]]) < 0
    assert S.macro_f1(["a", "b", "a"], ["a", "b", "a"], ["a", "b"]) == 1.0
    assert S.holm({"x": 0.01, "y": 0.04, "z": 0.03}) == {"x": 0.03, "z": 0.06, "y": 0.06}
    assert S.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_the_cluster_bootstrap_resamples_learners_and_is_seeded():
    clusters = {f"l{i}": [i % 2 == 0] * 5 for i in range(10)}
    a = S.cluster_bootstrap(clusters, S.share, seed=1)
    assert a["value"] == 0.5 and a["lo"] < 0.5 < a["hi"] and a["n_clusters"] == 10 and a["n"] == 50
    assert a == S.cluster_bootstrap(clusters, S.share, seed=1)
    one = S.cluster_bootstrap({"only": [True, False]}, S.share)
    assert one["value"] == 0.5 and one["lo"] is None  # no CI from a single learner


# ---------------------------------------------------------------------------- 0 and A


def test_m0a_fidelity():
    events = [turn(n=i, correct=c, qtype="tutor_reply") for i, c in enumerate([True, True, False, False], 1)]
    fid = judgement("fidelity", "sim_a_0", {"t1": {"label": "correct"}, "t2": {"label": "correct"},
                                             "t3": {"label": "incorrect"}, "t4": {"label": "correct"}},
                    unit="sim_a_0|w1|r1|fid-tutor")
    assert M.m0a(data(events, [fid]))["value"] == 0.75


def test_m0b_persona_fidelity():
    p = CONFIG["profiles"]["capable_disengaged"]  # ask 0.05, minimal 0.35, very short (4 words)
    kinds = ["minimal"] * 35 + ["question"] * 5 + ["answer"] * 60
    events = [turn(profile="capable_disengaged", kind=k, text="one two three four") for k in kinds]
    result = M.m0b(data(events), CONFIG)
    assert result["value"] == 1.0 and result["details"]["capable_disengaged"]["within"] == {
        "question_rate": True, "minimal_rate": True, "reply_words": True}
    wordy = [turn(profile="capable_disengaged", kind=k, text="word " * 30) for k in kinds]
    assert M.m0b(data(wordy), CONFIG)["value"] == 0.0
    assert p["minimal"] == 0.35


def test_m1_retrieval_hits_compare_file_names_without_extensions():
    def chat(src, retrieved):
        return turn(mode="chat", kind="question", source_file=src,
                    retrieval=[{"sources": [{"source": r} for r in retrieved]}])

    events = [chat("Week02-LabA-X.ipynb", ["Week02-LabA-X.ipynb"]), chat("Week01-LectureA-Y.md", ["Week01-LectureA-Y.md"]),
              chat("Week01-LectureA-Y.md", ["data/org_docs/Week01-LectureA-Y.md"]), chat("Week01-LectureB-Z.md", ["Other.md"])]
    assert M.m1(data(events))["value"] == 0.75


def test_m3_follow_ups():
    js = [judgement("chat", "a", {"1": {"resolves_reference": "yes"}, "2": {"resolves_reference": "no"}}),
          judgement("chat", "b", {"1": {"resolves_reference": "yes"}})]
    assert M.m3(data([], js))["value"] == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------- B. grading


def test_m4_grading_agreement_kappa_and_false_positives():
    mc = [turn(mode="quiz", qtype="multiple_choice", correct=t, lea_correct=g)
          for t, g in [(True, True)] * 6 + [(False, False)] * 3 + [(False, True)]]
    free = [turn(mode="quiz", qtype="open_ended", n=i, correct=t, lea_correct=g) for i, (t, g) in
            enumerate([(True, True), (False, False), (False, True), (True, True)], 1)]
    fid = judgement("fidelity", "sim_a_0", {"q1": {"label": "correct"}, "q2": {"label": "incorrect"},
                                             "q3": {"label": "correct"},  # disagrees with the intent: left out
                                             "q4": {"label": "correct"}}, unit="sim_a_0|w1|r1|fid-quiz")
    result = M.m4(data(mc + free, [fid]))
    d = result["details"]["quiz/multiple_choice"]
    assert d["n"] == 10 and d["accuracy"] == 0.9 and d["fp_rate"] == 0.25 and d["fn_rate"] == 0.0
    assert d["kappa"] == pytest.approx(S.cohen_kappa([True] * 6 + [False] * 4, [True] * 6 + [False] * 3 + [True]))
    o = result["details"]["quiz/open_ended"]
    assert o["n"] == 3 and o["kappa"] == 1.0 and o["all_answers (sensitivity)"]["n"] == 4
    assert result["value"] == 0.0  # MC misses kappa 0.95 and FP 0.10


def test_m5_not_graded_rate_excludes_warm_ups():
    events = [turn(graded=False, diagnostic=True), turn(graded=False), turn(), turn(), turn()]
    assert M.m5(data(events))["details"]["tutor/tutor_reply"] == {"n": 4, "not_graded": 0.25}


# ---------------------------------------------------------------------------- C. tracking


def test_m6_m7_m8_on_known_week_ends():
    ends = [week_end("a1", "advanced_eager", [(0.9, True, 0.9), (0.8, True, 0.7), (0.2, False, 0.2)]),
            week_end("n1", "novice_variable", [(0.75, False, 0.3), (0.1, False, 0.1), (None, False, 0.05)]),
            week_end("m1", "moderate_reflective", [(0.6, True, 0.6), (0.4, False, 0.4), (0.3, False, 0.35)])]
    d = data(ends)
    assert M.m6(d)["value"] == pytest.approx(1.0)  # each week's mastery is ordered like p_know
    m7 = M.m7(d)
    assert m7["value"] == pytest.approx(2 / 3) and m7["details"]["premature_mastery"] == pytest.approx(1 / 3)
    assert m7["details"]["recall"]["value"] == pytest.approx(2 / 3)
    m8 = M.m8(d)
    assert m8["value"] == pytest.approx(1.0) and m8["details"]["true_order"][0] == "novice_variable"


def test_m9_zpd_tracks_true_success():
    events = []
    ps = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.85, 0.3]
    history = []
    for p in ps:
        truth = sum(history[-4:]) / 4 if len(history) >= 4 else None
        events.append(turn(p=p, zpd=truth if truth is not None else 0.5))
        history.append(p)
    assert M.m9(data(events))["value"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------- D. adaptation


def test_m10_responsiveness_and_fading():
    wrong_then_up = [turn(n=1, correct=False, level="medium"), turn(n=2, correct=False, level="medium"),
                     turn(n=3, correct=True, level="high")]
    wrong_no_up = [turn(learner="b", n=1, correct=False, level="medium"), turn(learner="b", n=2, correct=False, level="medium"),
                   turn(learner="b", n=3, correct=False, level="medium"), turn(learner="b", n=4, correct=False, level="low")]
    right_then_down = [turn(learner="c", n=i, correct=True, level=lv) for i, lv in
                       enumerate(["high", "high", "high", "medium"], 1)]
    up, down = M.m10(data(wrong_then_up + wrong_no_up + right_then_down))
    assert up["value"] == pytest.approx(1 / 3) and down["value"] == 1.0


def test_m11_stability_counts_changes_while_the_truth_stands_still():
    events = [turn(n=i, level=lv, known=False) for i, lv in enumerate(["low", "low", "medium", "medium", "medium"], 1)]
    assert M.m11(data(events))["value"] == pytest.approx(10 * 1 / 4)


def test_m12_level_need_alignment():
    events = []
    for level, p in [("very_high", 0.1), ("high", 0.35), ("medium", 0.6), ("low", 0.9)]:
        for i in range(4):
            events.append(turn(learner=f"l{i}", level=level, p=p + 0.01 * i))
    assert M.m12(data(events))["value"] == 1.0
    events.append(turn(learner="l0", level="low", p=0.0))
    events += [turn(learner="l1", level="low", p=0.0) for _ in range(20)]
    assert M.m12(data(events))["value"] == 0.0


def test_m13_efficiency_and_over_teaching():
    events = [turn(n=1, go="G1", known=False, mastery_after=0.5), turn(n=2, go="G1", known=False, mastery_after=0.8),
              turn(n=3, go="G2", known=True, mastery_after=0.9)]
    d = M.m13(data(events))["details"]["advanced_eager"]
    assert d["turns_per_go_to_mastery"] == 1.5 and d["over_teaching_share"] == pytest.approx(1 / 3)


def test_m14_stuck_and_early():
    ends = [week_end("a", "advanced_eager", [(0.9, True, 0.9)] * 4, advanced=None),               # stuck
            week_end("b", "novice_variable", [(0.9, False, 0.2)] * 4, advanced=2),                 # early
            week_end("c", "moderate_reflective", [(0.9, True, 0.9)] * 3 + [(0.1, False, 0.1)], advanced=2)]  # fine
    stuck, early = M.m14(data(ends))
    assert stuck["value"] == pytest.approx(1 / 3) and early["value"] == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------- E, F, G


def test_m15_motivation_agreement_excludes_cold_start():
    events = [turn(engagement="engaged", motivation="maintained_high"), turn(engagement="steady", motivation="motivation_plateau"),
              turn(engagement="disengaging", motivation="motivation_drop"), turn(engagement="engaged", motivation="cold_start")]
    result = M.m15(data(events))
    assert result["value"] == 1.0 and result["details"]["cold_start_excluded"] == 1
    assert result["details"]["confusion"]["engaged"]["engaged"] == 1


def test_judged_checklists_coherence_and_length():
    yes = {k: "yes" for k in M.M16_ITEMS}
    js = [judgement("tutor", "a", {"1": {**yes, "coherence": 5}, "2": {**yes, "explains_why": "no", "coherence": 3}})]
    d = data([turn(message="short reply"), turn(message="word " * 400)], js)
    items = {m["id"]: m["value"] for m in M._judged_items(d, "tutor", M.M16_ITEMS, "M16", "x", 0.85, "F")}
    assert items["M16.explains_why"] == 0.5 and items["M16.responds_to_student"] == 1.0
    assert M.m17(d)["value"] == 4.0
    assert M.m16b(d, 375)["value"] == 0.5
    quiz = [judgement("quiz", "a", {"1": {k: "yes" for k in M.M18_ITEMS}, "2": {**{k: "yes" for k in M.M18_ITEMS},
                                                                               "plausible_distractors": "no"}})]
    q = {m["id"]: m["value"] for m in M._judged_items(data([], quiz), "quiz", M.M18_ITEMS, "M18", "x", 0.9, "G")}
    assert q["M18.plausible_distractors"] == 0.5 and q["M18.tests_its_objective"] == 1.0


# ---------------------------------------------------------------------------- H. reliability


def test_reliability_test_retest_inter_judge_and_human():
    yes = {k: "yes" for k in M.M16_ITEMS}
    no = {k: "no" for k in M.M16_ITEMS}
    vals = {"1": {**yes, "coherence": 5}, "2": {**no, "coherence": 2}}
    js = [judgement("tutor", "a", vals, repeat=r) for r in range(3)]
    js.append(judgement("tutor", "a", {"1": {**yes, "coherence": 5}, "2": {**yes, "coherence": 2}}, role="second_judge"))
    labels = {"a|w1|r1|tutor#1": {f"label_{i}": "yes" for i in range(1, 6)} | {"label_coherence": "5"},
              "a|w1|r1|tutor#2": {f"label_{i}": "no" for i in range(1, 6)} | {"label_coherence": "2"}}
    rel = M.reliability(data([], js), labels)
    assert rel["M16"]["M20_test_retest"] == pytest.approx(1.0) and rel["M17"]["M20_test_retest"] == pytest.approx(1.0)
    assert rel["M16"]["M21_inter_judge"] == pytest.approx(0.0)  # the second judge said yes to everything
    assert rel["M16"]["M22_judge_human"] == pytest.approx(1.0) and rel["M16"]["M22_items"] == 10
    assert rel["M16"]["reliable"] is False and rel["M3"]["reliable"] is None  # no data for M3


def test_missing_judgements_are_counted_not_scored():
    js = [judgement("tutor", "a", None), judgement("tutor", "b", {"1": {**{k: "yes" for k in M.M16_ITEMS},
                                                                      "coherence": 4}})]
    d = data([], js)
    assert M.missing_counts(d)["tutor/judge"] == {"judged": 1, "missing": 1}
    assert M.m17(d)["value"] == 4.0  # the missing unit contributes nothing, not a default


# ---------------------------------------------------------------------------- everything and the report


def test_compute_all_and_the_report(tmp_path):
    events = [turn(level="medium", zpd=0.5, motivation="maintained_high"),
              turn(mode="chat", kind="question", source_file="W.md", retrieval=[{"sources": [{"source": "W.md"}]}]),
              week_end("sim_a_0", "advanced_eager", [(0.8, True, 0.8), (0.2, False, 0.3), (0.5, False, 0.5)])]
    js = [judgement("tutor", "sim_a_0", {"1": {**{k: "yes" for k in M.M16_ITEMS}, "coherence": 4}})]
    results = M.compute_all(events, js, CONFIG, m0c_result={"max_deviation": 0.004, "tolerance": 0.01, "rows": [1],
                                                            "passed": True})
    ids = [m["id"] for m in results["metrics"]]
    for mid in ("M0a", "M0b", "M0c", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10a", "M10b", "M11",
                "M12", "M13", "M14a", "M14b", "M15", "M16b", "M17"):
        assert mid in ids, mid
    assert sum(1 for i in ids if i.startswith("M16.")) == 5 and sum(1 for i in ids if i.startswith("M18.")) == 5
    paths = write(tmp_path, results, manifest={"course": "AIML101", "status": "completed"}, costs={"openai_usd": 0.1})
    report = paths["report"].read_text(encoding="utf-8")
    assert "## B. Grading" in report and "## H. Judge reliability" in report and "M22" in report
    assert json.loads(paths["json"].read_text())["counts"]["turns"] == 2
    rows = paths["csv"].read_text().splitlines()
    assert rows[0].startswith("id,group,name") and len(rows) == len(results["metrics"]) + 1
    assert not any(isinstance(m.get("value"), float) and math.isnan(m["value"]) for m in results["metrics"])
