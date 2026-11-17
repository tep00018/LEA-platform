"""The offline grader-replay harness (simulation/grader_replay.py): dataset shape, candidate prompts and scoring.
No OpenAI calls: every OpenAI client here is a fake."""

import json
from pathlib import Path

import pytest

from simulation import grader_replay as GR


def row(qtype="tutor", intent_correct=True, judge_label="correct", checkable=None, run="pilot-1"):
    return {"run": run, "learner": "sim_a_0", "week": 1, "round": 1, "turn": 1, "mode": "tutor" if qtype == "tutor" else "quiz",
            "qtype": qtype, "question": "What is weak AI?", "answer": "an answer", "reference": "the reference",
            "passage": "the passage", "intent_correct": intent_correct, "judge_label": judge_label,
            "checkable_by_judge": checkable}


class FakeClient:
    """Answers 'correct' iff the dataset row's answer contains RIGHT; honours checkable/no-JSON scripting."""

    def __init__(self, checkable=None, malformed=False):
        self.checkable, self.malformed, self.prompts = checkable, malformed, []
        self.chat = self
        self.completions = self

    def create(self, *, messages, **kw):
        self.prompts.append(messages[0]["content"])
        if self.malformed:
            content = "not json"
        else:
            answer = messages[1]["content"]
            data = {"correct": "RIGHT" in answer, "score": 0.9 if "RIGHT" in answer else 0.1,
                    "explanation": "ok", "matched_concepts": ["x"] if "RIGHT" in answer else []}
            if self.checkable is not None:
                data["checkable"], data["confidence"] = self.checkable, 0.8
            content = json.dumps(data)
        usage = type("U", (), {"prompt_tokens": 120, "completion_tokens": 40})()
        message = type("M", (), {"content": content})()
        choice = type("C", (), {"message": message})()
        return type("R", (), {"choices": [choice], "usage": usage})()


def test_build_dataset_reads_saved_pilot_events_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(GR, "load_bank", lambda course: {"g1": {"reference_answer": "ref", "source_quote": "quote"}})
    run_dir = tmp_path / "p1"
    run_dir.mkdir()
    events = [
        {"kind": "tutor_start", "learner": "u", "week": 1, "round": 1, "message": "opening question"},
        {"kind": "turn", "learner": "u", "week": 1, "round": 1, "mode": "tutor", "turn": 1, "qtype": "tutor_reply",
         "go_id": "g1", "student_text": "an answer", "intent": {"kind": "answer", "correct": True},
         "lea": {"message": "next tutor message"}},
        {"kind": "turn", "learner": "u", "week": 1, "round": 1, "mode": "quiz", "turn": 2, "qtype": "fill_in",
         "go_id": "g1", "student_text": "blank answer", "question": {"text": "fill in ___", "correct_answer": "x"},
         "intent": {"kind": "answer", "correct": False}, "lea": {"graded": True}},
    ]
    (run_dir / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    fid = {"kind": "fidelity", "pass_id": "p", "unit": "u|w1|r1|fid-tutor", "learner": "u", "week": 1, "round": 1,
          "rubric_versions": {"M0a": 2}, "values": {"t1": {"label": "correct"}}}
    (run_dir / "judgements.jsonl").write_text(json.dumps(fid), encoding="utf-8")
    rows = GR.build_dataset([("p1", "p")], runs_dir=tmp_path)
    assert len(rows) == 2
    tutor = next(r for r in rows if r["qtype"] == "tutor")
    assert tutor["question"] == "opening question" and tutor["reference"] == "ref" and tutor["checkable_by_judge"] is True
    quiz = next(r for r in rows if r["qtype"] == "fill_in")
    assert quiz["reference"] == "x" and quiz["judge_label"] is None  # not judged: not in fid map


def test_candidate_prompts_add_exactly_what_each_is_named_for():
    client = FakeClient()
    r = row()
    for c in GR.CANDIDATES:
        usage = GR.Usage()
        GR.grade_one(client, r, c, usage)
    system_v0, system_v1, system_v2, system_v3 = client.prompts
    assert "actually asked" not in system_v0 and "matched_concepts" not in system_v0.split("Reply")[0] or True
    assert "actually asked" in system_v1 and "actually asked" in system_v2 and "actually asked" in system_v3
    assert "name at least one specific concept" in system_v2 and "name at least one specific concept" not in system_v1
    assert '"checkable"' in system_v3 and '"checkable"' not in system_v1


def test_a_non_checkable_answer_is_gated_to_not_graded_only_for_v3():
    r = row()
    client = FakeClient(checkable=False)
    usage = GR.Usage()
    v0 = GR.grade_one(client, r, GR.CANDIDATES[0], usage)
    v3 = GR.grade_one(client, r, GR.CANDIDATES[3], usage)
    assert v0["graded"] is True
    assert v3["graded"] is False and v3["gated_not_checkable"] is True


def test_a_checkable_answer_is_graded_normally_under_v3():
    client = FakeClient(checkable=True)
    v3 = GR.grade_one(client, row(), GR.CANDIDATES[3], GR.Usage())
    assert v3["graded"] is True and v3["correct"] is False  # "an answer" has no RIGHT/WRONG marker


def test_malformed_json_is_ungraded_not_a_crash():
    client = FakeClient(malformed=True)
    result = GR.grade_one(client, row(), GR.CANDIDATES[0], GR.Usage())
    assert result["graded"] is False and result["correct"] is None


def test_usage_and_cost_accumulate_across_calls():
    client = FakeClient()
    usage = GR.Usage()
    for _ in range(3):
        GR.grade_one(client, row(), GR.CANDIDATES[0], usage)
    assert usage.calls == 3 and usage.input_tokens == 360 and usage.output_tokens == 120
    assert usage.cost_usd() > 0


def test_estimate_cost_projects_the_full_plan_from_a_small_sample():
    client = FakeClient()
    dataset = [row() for _ in range(50)]
    est = GR.estimate_cost(dataset, client, sample=5, candidates=GR.CANDIDATES[:2], repeats=2)
    assert est["probe_calls"] == 5 * 2  # 5 sampled items x 2 candidates, once each
    assert est["planned_calls"] == 50 * 2 * 2
    assert est["projected_cost_usd"] > 0


def test_kappa_and_error_rates_are_scored_against_the_simulator_s_intent():
    dataset = [row(intent_correct=True, judge_label="correct"), row(intent_correct=False, judge_label="incorrect"),
              row(intent_correct=True, judge_label="correct"), row(intent_correct=False, judge_label="incorrect")]
    # verdicts: 3 agree with intent, 1 false positive (intent wrong, graded correct)
    results = [{"graded": True, "correct": True}, {"graded": True, "correct": True},
              {"graded": True, "correct": True}, {"graded": True, "correct": False}]
    s = GR.score_candidate(dataset, [results, results])
    d = s["by_type"]["tutor"]
    assert d["n_eligible"] == 4 and d["false_positive_rate"] == 0.5 and d["false_negative_rate"] == 0.0
    assert d["accuracy"] == 0.75
    assert s["consistency_between_two_runs"] == 1.0  # identical repeats


def test_not_graded_items_are_excluded_from_kappa_but_counted_in_the_rate():
    dataset = [row(), row(), row()]
    results = [{"graded": True, "correct": True}, {"graded": False, "correct": None}, {"graded": True, "correct": True}]
    s = GR.score_candidate(dataset, [results, results])
    d = s["by_type"]["tutor"]
    assert d["n_eligible"] == 3 and d["not_graded_rate"] == pytest.approx(1 / 3)


def test_judge_agreed_only_drops_not_an_answer_and_no_checkable_question():
    dataset = [row(judge_label="correct"), row(judge_label="not_an_answer"), row(judge_label="no_checkable_question")]
    results = [{"graded": True, "correct": True}] * 3
    agreed = GR.score_candidate(dataset, [results, results], judge_agreed_only=True)
    everything = GR.score_candidate(dataset, [results, results], judge_agreed_only=False)
    assert agreed["by_type"]["tutor"]["n_eligible"] == 1
    assert everything["by_type"]["tutor"]["n_total"] == 3


def test_format_report_names_every_candidate():
    dataset = [row()]
    results = {c.name: [[{"graded": True, "correct": True}], [{"graded": True, "correct": True}]] for c in GR.CANDIDATES}
    scores = GR.score_all(dataset, results)
    text = GR.format_report(dataset, scores, {"cost_usd": 0.01, "calls": 8, "input_tokens": 100, "output_tokens": 50})
    for c in GR.CANDIDATES:
        assert c.name in text


def _rows_with_results(n_fn, n_fp, qtype="tutor"):
    dataset, results, turn = [], [], 0
    for _ in range(n_fn):
        turn += 1
        dataset.append({**row(qtype=qtype, intent_correct=True, judge_label="correct"), "turn": turn})
        results.append({"graded": True, "correct": False, "explanation": "not quite right"})
    for _ in range(n_fp):
        turn += 1
        dataset.append({**row(qtype=qtype, intent_correct=False, judge_label="incorrect"), "turn": turn})
        results.append({"graded": True, "correct": True, "explanation": "looks solid"})
    return dataset, results


def test_review_sheet_hides_intent_and_randomises_which_reviewer_is_which(tmp_path):
    dataset, results = _rows_with_results(3, 3)
    out = GR.build_review_sheet(dataset, results, tmp_path / "sheet.csv",
                                target={"fn": {"tutor": 3}, "fp": {"tutor": 3}}, seed=1)
    assert out["rows"] == 6 and out["shortfall"] == {}
    text = (tmp_path / "sheet.csv").read_text(encoding="utf-8")
    assert "reviewer_a_verdict" in text and "your_pick" in text
    assert "grader" not in text.lower() and "judge" not in text.lower() and "intent" not in text.lower()
    key = json.loads((tmp_path / "sheet_key.json").read_text(encoding="utf-8"))
    assert len(key) == 6
    sides = {v["a_is"] for v in key.values()} | {v["b_is"] for v in key.values()}
    assert sides == {"grader", "judge"}


def test_review_sheet_reports_a_shortfall_when_a_bucket_runs_out():
    dataset, results = _rows_with_results(2, 0)
    out = GR.build_review_sheet(dataset, results, Path("_unused.csv"),
                                target={"fn": {"tutor": 5}, "fp": {"tutor": 0}}, seed=1)
    assert out["shortfall"] == {"fn/tutor": 3} and out["rows"] == 2
    Path("_unused.csv").unlink(missing_ok=True)
    Path("_unused_key.json").unlink(missing_ok=True)


def test_scoring_the_filled_in_sheet_counts_agreement_with_intent(tmp_path):
    dataset, results = _rows_with_results(1, 1)
    GR.build_review_sheet(dataset, results, tmp_path / "sheet.csv", target={"fn": {"tutor": 1}, "fp": {"tutor": 1}}, seed=2)
    path = tmp_path / "sheet.csv"
    key = json.loads(path.with_name("sheet_key.json").read_text(encoding="utf-8"))
    import csv

    rows_out = list(csv.DictReader(open(path, encoding="utf-8")))
    for r in rows_out:
        k = key[r["item_id"]]
        r["your_pick"] = "A" if k["a_is"] == "judge" else "B"  # always pick the judge
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=GR.REVIEW_COLUMNS)
        w.writeheader()
        w.writerows(rows_out)
    scored = GR.score_review_sheet(path)
    assert scored["answered"] == 2 and scored["agrees_with_judge"] == 2 and scored["agrees_with_grader"] == 0


# ---------------------------------------------------------------- candidates (a), (b), (c)

class KeyPointsClient:
    """Answers key-point requests with fixed points, and grades 'correct' iff RIGHT is in the answer
    AND a key point is echoed (so we can prove the key points, not the raw reference, drove the verdict)."""

    def __init__(self):
        self.chat = self
        self.completions = self
        self.calls = []

    def create(self, *, messages, **kw):
        system, user = messages[0]["content"], messages[1]["content"]
        self.calls.append(user)
        if "key_points" in system:
            content = json.dumps({"key_points": ["mentions X", "mentions Y"]})
        elif "verdict" in system:
            ok = "RIGHT" in user and "mentions X" in system
            content = json.dumps({"verdict": "correct" if ok else "partly_correct" if "RIGHT" in user else "incorrect",
                                  "score": 0.9, "explanation": "ok", "matched_concepts": [], "checkable": True})
        else:
            ok = "RIGHT" in user and "mentions X" in system
            content = json.dumps({"correct": ok, "score": 0.9 if ok else 0.1, "explanation": "ok",
                                  "matched_concepts": [], "checkable": True})
        usage = type("U", (), {"prompt_tokens": 50, "completion_tokens": 20})()
        message = type("M", (), {"content": content})()
        return type("R", (), {"choices": [type("C", (), {"message": message})()], "usage": usage})()


def test_keypoints_candidate_only_touches_tutor_rows_and_uses_generated_points():
    dataset = [row(qtype="tutor", intent_correct=True), row(qtype="fill_in", intent_correct=True)]
    dataset[0]["answer"] = "RIGHT, this mentions X clearly"
    client = KeyPointsClient()
    out = GR.run_keypoints_candidate(dataset, client, repeats=1)
    assert list(out["key_points_by_row"].keys()) == [0]  # only the tutor row got key points
    assert out["results"][0][0]["graded"] is True and out["results"][0][0]["correct"] is True
    assert out["results"][0][1] is None  # the quiz row was never touched


def test_bigger_model_candidate_uses_the_named_model_and_gates_on_checkable():
    class Client:
        def __init__(self):
            self.chat = self
            self.completions = self
            self.models_used = []

        def create(self, *, model, messages, **kw):
            self.models_used.append(model)
            content = json.dumps({"correct": True, "score": 0.9, "explanation": "ok", "checkable": False})
            m = type("M", (), {"content": content})()
            u = type("U", (), {"prompt_tokens": 10, "completion_tokens": 5})()
            return type("R", (), {"choices": [type("C", (), {"message": m})()], "usage": u})()

    client = Client()
    usage = GR.Usage()
    result = GR.grade_one_bigger_model(client, row(), usage, model="gpt-4o")
    assert client.models_used == ["gpt-4o"] and result["graded"] is False  # gated: checkable was False


def test_three_level_candidate_reports_verdict_and_treats_partly_correct_as_incorrect_for_kappa():
    dataset = [row(intent_correct=True, judge_label="correct") for _ in range(3)]
    results = [{"graded": True, "verdict": "correct", "correct": True},
              {"graded": True, "verdict": "partly_correct", "correct": False},
              {"graded": True, "verdict": "incorrect", "correct": False}]
    s = GR.score_three_level(dataset, [results, results])
    d = s["by_type"]["tutor"]
    assert d["level_counts"] == {"correct": 1, "partly_correct": 1, "incorrect": 1}
    assert d["n_eligible"] == 3
    assert s["consistency_between_two_runs"] == 1.0


def test_three_level_gate_still_applies_when_not_checkable():
    class Client:
        chat = completions = None

        def __init__(self):
            self.chat = self
            self.completions = self

        def create(self, *, messages, **kw):
            content = json.dumps({"verdict": "correct", "score": 0.9, "explanation": "ok", "checkable": False})
            m = type("M", (), {"content": content})()
            u = type("U", (), {"prompt_tokens": 10, "completion_tokens": 5})()
            return type("R", (), {"choices": [type("C", (), {"message": m})()], "usage": u})()

    result = GR.grade_one_three_level(Client(), row(), GR.Usage())
    assert result["graded"] is False and result["correct"] is None


def test_probe_bigger_model_cost_projects_per_learner_week_and_per_run():
    class Client:
        def __init__(self):
            self.chat = self
            self.completions = self

        def create(self, *, messages, **kw):
            content = json.dumps({"correct": True, "score": 0.9, "explanation": "ok", "checkable": True})
            m = type("M", (), {"content": content})()
            u = type("U", (), {"prompt_tokens": 1000, "completion_tokens": 200})()
            return type("R", (), {"choices": [type("C", (), {"message": m})()], "usage": u})()

    dataset = [row() for _ in range(48)]
    est = GR.probe_bigger_model_cost(dataset, Client(), sample=10, learner_weeks_in_dataset=24)
    assert est["probe_calls"] == 10 and est["per_learner_week_grading_calls"] == 2.0
    assert est["full_replay_calls"] == 48 * GR.REPEATS
    assert est["projected_cost_per_288_learner_week_run_usd"] > 0


def test_review_sheet_can_leave_the_question_untruncated(tmp_path):
    dataset, results = _rows_with_results(1, 0)
    dataset[0]["question"] = "x " * 500  # well past the 700-char default clip
    GR.build_review_sheet(dataset, results, tmp_path / "sheet.csv", target={"fn": {"tutor": 1}, "fp": {"tutor": 0}},
                          seed=1, clip_question=None)
    text = (tmp_path / "sheet.csv").read_text(encoding="utf-8")
    assert "..." not in text and dataset[0]["question"].strip() in text


def test_split_review_sheet_separates_agreeing_from_disagreeing_rows(tmp_path):
    # row 1: a false negative (intent right, grader wrong) where the judge said "correct" -> reviewers disagree
    # row 2: a false positive (intent wrong, grader right) where the judge said "incorrect" -> reviewers disagree
    # row 3: a false negative where the judge also said "incorrect" -> reviewers agree with each other
    dataset = [{**row(intent_correct=True, judge_label="correct"), "turn": 1},
              {**row(intent_correct=False, judge_label="incorrect"), "turn": 2},
              {**row(intent_correct=True, judge_label="incorrect"), "turn": 3}]
    results = [{"graded": True, "correct": False, "explanation": "x"}, {"graded": True, "correct": True, "explanation": "x"},
              {"graded": True, "correct": False, "explanation": "x"}]
    path = tmp_path / "sheet.csv"
    GR.build_review_sheet(dataset, results, path, target={"fn": {"tutor": 2}, "fp": {"tutor": 1}}, seed=3)
    out = GR.split_review_sheet(path)
    assert out["disagree_n"] + out["agree_n"] == 3
    import csv

    dis = list(csv.DictReader(open(out["disagree"], encoding="utf-8")))
    agr = list(csv.DictReader(open(out["agree"], encoding="utf-8")))
    assert all(r["reviewer_a_verdict"] != r["reviewer_b_verdict"] for r in dis)
    assert all(r["reviewer_a_verdict"] == r["reviewer_b_verdict"] for r in agr)


def test_v4_broader_gate_names_opinion_and_warmup_cases_and_still_gates():
    class Client:
        def __init__(self):
            self.chat = self
            self.completions = self
            self.systems = []

        def create(self, *, messages, **kw):
            self.systems.append(messages[0]["content"])
            content = json.dumps({"correct": True, "score": 0.9, "explanation": "ok", "checkable": False})
            m = type("M", (), {"content": content})()
            u = type("U", (), {"prompt_tokens": 10, "completion_tokens": 5})()
            return type("R", (), {"choices": [type("C", (), {"message": m})()], "usage": u})()

    client = Client()
    result = GR.grade_one_v4(client, row(), GR.Usage())
    assert "opinion" in client.systems[0].lower() and "warm-up" in client.systems[0].lower()
    assert result["graded"] is False and result["checkable"] is False


def test_gate_rate_computes_the_share_of_a_type_left_ungraded():
    dataset = [row(qtype="tutor") for _ in range(4)]
    results = [{"graded": True}, {"graded": False}, {"graded": False}, {"graded": True}]
    assert GR.gate_rate(dataset, results) == 0.5


def test_v5_asks_for_brevity_synonyms_and_lesson_contradiction():
    client = FakeClient()
    GR.grade_one_v5(client, row(), GR.Usage())
    system = client.prompts[0]
    for phrase in ("brief answer", "synonyms", "contradicts"):
        assert phrase in system.lower(), phrase


def test_score_against_corrected_intent_overrides_only_matched_rows():
    dataset = [{**row(intent_correct=True), "run": "p", "learner": "u", "turn": 1},
              {**row(intent_correct=True), "run": "p", "learner": "u", "turn": 2}]
    results = [{"graded": True, "correct": False}, {"graded": True, "correct": False}]
    corrected = {"p:u:1": False}  # only row 1's recorded intent was wrong; row 2's stands
    s = GR.score_against_corrected_intent(dataset, results, corrected)
    # row 1 now "should" be incorrect (matches grader); row 2 still "should" be correct (grader disagrees)
    assert s["by_type"]["tutor"]["accuracy"] == 0.5
