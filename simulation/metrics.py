"""Every metric in docs/simulation/PLAN.md, section 3, from a run's saved events.

GT metrics come from the hidden state and LEA's own logs; J metrics from judgements
(repeat 0 of the main judge in the chosen pass). Every value has a 95% CI from a cluster
bootstrap over learners where it makes sense, a target, and whether it was met. Judged
metrics also carry their reliability (M20-M22) and are marked unreliable if it fails.
Nothing here calls LEA, OpenAI or Claude (``--reanalyse``).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from simulation import stats as S

LEVELS = {"minimal": 0, "low": 1, "medium": 2, "high": 3, "very_high": 4, "intensive": 4}
LEVEL_NAMES = ["very_high", "high", "medium", "low"]  # most support first
MOTIVATION = {"maintained_high": "engaged", "motivation_plateau": "steady", "motivation_drop": "disengaging"}
ENGAGEMENT = ["engaged", "steady", "disengaging"]
PROFILE_ORDER = ["novice_variable", "struggling_eager", "inconsistent_adaptive", "moderate_reflective",
                 "capable_disengaged", "advanced_eager"]
M16_ITEMS = ["consistent_with_content", "responds_to_student", "explains_why", "no_giveaway", "clear_next_step"]
M18_ITEMS = ["answerable_from_content", "one_correct_option", "plausible_distractors", "tests_its_objective",
             "stem_does_not_reveal"]
GRADE_GROUPS = [("tutor", "tutor_reply"), ("quiz", "multiple_choice"), ("quiz", "true_false"), ("quiz", "fill_in"),
                ("quiz", "open_ended")]


def _metric(mid, group, name, source, result, target, op, *, details=None, unit="learner") -> Dict[str, Any]:
    value = result.get("value") if isinstance(result, dict) else result
    met = None
    if value is not None and target is not None:
        met = value >= target if op == ">=" else value <= target
    out = {"id": mid, "group": group, "name": name, "source": source, "value": value, "target": target, "op": op,
           "met": met, "unit": unit}
    if isinstance(result, dict):
        out.update({k: result.get(k) for k in ("lo", "hi", "n", "n_clusters")})
    if details:
        out["details"] = details
    return out


class RunData:
    def __init__(self, events: List[Dict[str, Any]], judgements: List[Dict[str, Any]], pass_id: Optional[str] = None):
        self.turns = [e for e in events if e.get("kind") == "turn"]
        self.week_ends = [e for e in events if e.get("kind") == "week_end"]
        passes = [j.get("pass_id") for j in judgements]
        self.pass_id = pass_id or (passes[-1] if passes else None)
        self.judgements = [j for j in judgements if j.get("pass_id") == self.pass_id]
        self.profile = {e["learner"]: e.get("profile") for e in self.turns + self.week_ends}

    def main_judgements(self, kind: str) -> List[Dict[str, Any]]:
        return [j for j in self.judgements if j["kind"] == kind and j["repeat"] == 0 and j["judge_role"] == "judge"]

    def fidelity(self) -> Dict[Tuple, str]:
        """(learner, week, round, mode, turn) -> the judge's label for a free-text answer."""
        out = {}
        for j in self.main_judgements("fidelity"):
            if not j["values"]:
                continue
            mode = "tutor" if j["unit"].endswith("fid-tutor") else "quiz"
            for item, v in j["values"].items():
                out[(j["learner"], j["week"], j["round"], mode, int(item[1:]))] = v["label"]
        return out


def _clusters(rows: List[Dict[str, Any]], value=lambda r: r) -> Dict[str, List[Any]]:
    out: Dict[str, List[Any]] = defaultdict(list)
    for r in rows:
        out[r["learner"]].append(value(r))
    return out


def _decision(turn: Dict[str, Any], type_: str) -> Optional[Dict[str, Any]]:
    return next((d["payload"] for d in turn.get("decisions") or [] if d.get("type") == type_), None)


def _level(turn: Dict[str, Any]) -> Optional[int]:
    answer = _decision(turn, "answer") or {}
    return LEVELS.get(str(answer.get("scaffolding_intensity") or "").lower())


def _answers(data: RunData, mode=None, qtype=None) -> List[Dict[str, Any]]:
    return [t for t in data.turns if (t.get("intent") or {}).get("kind") == "answer"
            and (mode is None or t["mode"] == mode) and (qtype is None or t["qtype"] == qtype)]


# ---------------------------------------------------------------------------- 0. simulator validity

NO_QUESTION = "no_checkable_question"


def m0a(data: RunData) -> Dict[str, Any]:
    fid = data.fidelity()
    rows = []
    for t in _answers(data):
        key = (t["learner"], t["week"], t.get("round", 1), t["mode"], t["turn"])
        if key in fid and fid[key] != NO_QUESTION:
            rows.append({"learner": t["learner"], "ok": (fid[key] == "correct") == bool(t["intent"]["correct"])})
    res = S.cluster_bootstrap(_clusters(rows, lambda r: r["ok"]), S.share)
    out = _metric("M0a", "0", "Student fidelity: judged correctness matches the intent", "J", res, 0.90, ">=")
    out["details"] = {"answers_with_no_checkable_question (excluded)": sum(1 for v in fid.values() if v == NO_QUESTION)}
    return out


def wilson(successes: int, n: int, z: float = 1.96):
    if n <= 0:
        return 0.0, 1.0
    p = successes / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return centre - half, centre + half


def m0b(data: RunData, config: Dict[str, Any]) -> Dict[str, Any]:
    words = config["learner"]["reply_words"]
    details, all_ok = {}, True
    for key, p in config["profiles"].items():
        turns = [t for t in data.turns if t["profile"] == key and t["mode"] == "tutor" and t.get("intent")
                 and t["intent"]["kind"] != "quit"]
        if not turns:
            continue
        kinds = [t["intent"]["kind"] for t in turns]
        texts = [t["student_text"] for t in turns if t["intent"]["kind"] in ("answer", "question") and t.get("student_text")]
        asked = [t["intent"]["target_words"] for t in turns if t["intent"]["kind"] in ("answer", "question")
                 and t["intent"].get("target_words")]  # what the student was actually asked for, turn by turn
        target_words = S.mean(asked) if asked else (words[p["reply_length"]] if p["reply_length"] in words
                                                    else sum(words.values()) / len(words))
        observed = {"question_rate": kinds.count("question") / len(kinds), "minimal_rate": kinds.count("minimal") / len(kinds),
                    "reply_words": S.mean(len(x.split()) for x in texts)}
        targets = {"question_rate": p["ask"], "minimal_rate": p["minimal"], "reply_words": target_words}
        checks = {}
        for k in targets:
            if k == "reply_words":
                checks[k] = observed[k] is not None and abs(observed[k] - targets[k]) <= max(0.20 * targets[k], 1.5)
            else:  # a rate: the target must sit inside the 95% Wilson interval for what was seen, or within tolerance
                lo, hi = wilson(round(observed[k] * len(kinds)), len(kinds))
                checks[k] = lo <= targets[k] <= hi or abs(observed[k] - targets[k]) <= max(0.20 * targets[k], 0.02)
        details[key] = {"observed": observed, "target": targets, "within": checks, "turns": len(turns)}
        all_ok = all_ok and all(checks.values())
    out = _metric("M0b", "0", "Persona fidelity: length, question and minimal-reply rates per profile", "GT",
                  {"value": 1.0 if all_ok else 0.0}, 1.0, ">=", details=details, unit="profile")
    out["value_note"] = ("1 = every profile within tolerance: reply words within 20% of the words asked for; a rate "
                         "passes when its target is inside the 95% Wilson interval of the observed rate (or within 20%)")
    return out


def m0c_metric(result: Dict[str, Any]) -> Dict[str, Any]:
    return _metric("M0c", "0", "Learner model matches the BKT formulas (10,000 draws)", "GT",
                   {"value": result["max_deviation"]}, result["tolerance"], "<=",
                   details={"checks": len(result["rows"]), "passed": result["passed"]}, unit="draws")


# ---------------------------------------------------------------------------- A. retrieval and chat

def _norm_source(s: Optional[str]) -> str:
    import os

    return os.path.splitext(os.path.basename(str(s or "")))[0].lower()


def m1(data: RunData) -> Dict[str, Any]:
    rows = []
    for t in data.turns:
        if t["mode"] != "chat" or not t.get("source_file"):
            continue
        sources = {_norm_source(s.get("source")) for r in t.get("retrieval") or [] for s in r.get("sources") or []}
        rows.append({"learner": t["learner"], "hit": _norm_source(t["source_file"]) in sources})
    res = S.cluster_bootstrap(_clusters(rows, lambda r: r["hit"]), S.share)
    return _metric("M1", "A", "Retrieval hit@k against the question's source lesson", "GT", res, 0.90, ">=")


def m3(data: RunData) -> Dict[str, Any]:
    rows = [{"learner": j["learner"], "yes": v["resolves_reference"] == "yes"}
            for j in data.main_judgements("chat") if j["values"] for v in j["values"].values()]
    res = S.cluster_bootstrap(_clusters(rows, lambda r: r["yes"]), S.share)
    return _metric("M3", "A", "Follow-up resolution in Chat", "J", res, 0.85, ">=")


# ---------------------------------------------------------------------------- B. grading

def _grading(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    truth = [r["truth"] for r in rows]
    lea = [r["lea"] for r in rows]
    neg = [r for r in rows if not r["truth"]]
    pos = [r for r in rows if r["truth"]]
    return {"n": len(rows), "accuracy": S.share(t == g for t, g in zip(truth, lea)), "kappa": S.cohen_kappa(truth, lea),
            "fp_rate": S.share(r["lea"] for r in neg) if neg else None,
            "fn_rate": S.share(not r["lea"] for r in pos) if pos else None}


def m4(data: RunData) -> Dict[str, Any]:
    fid = data.fidelity()
    details, met_all = {}, True
    for mode, qtype in GRADE_GROUPS:
        all_rows, agreed = [], []
        for t in _answers(data, mode, qtype):
            lea = t.get("lea") or {}
            if not lea.get("graded") or lea.get("correct") is None:
                continue
            row = {"learner": t["learner"], "truth": bool(t["intent"]["correct"]), "lea": bool(lea["correct"])}
            all_rows.append(row)
            if qtype in ("multiple_choice", "true_false"):
                agreed.append(row)
            else:
                label = fid.get((t["learner"], t["week"], t.get("round", 1), mode, t["turn"]))
                if label not in (None, NO_QUESTION) and (label == "correct") == row["truth"]:
                    agreed.append(row)
        if not all_rows:
            continue
        clusters = _clusters(agreed)
        kappa = S.cluster_bootstrap(clusters, lambda rs: S.cohen_kappa([r["truth"] for r in rs], [r["lea"] for r in rs]))
        fp = S.cluster_bootstrap(_clusters([r for r in agreed if not r["truth"]]), lambda rs: S.share(r["lea"] for r in rs))
        target = 0.95 if qtype in ("multiple_choice", "true_false") else 0.70
        met = (kappa["value"] is not None and kappa["value"] >= target and (fp["value"] is None or fp["value"] <= 0.10))
        met_all = met_all and met
        details[f"{mode}/{qtype}"] = {**_grading(agreed), "kappa_ci": [kappa["lo"], kappa["hi"]],
                                      "fp_ci": [fp["lo"], fp["hi"]], "kappa_target": target, "met": met,
                                      "all_answers (sensitivity)": _grading(all_rows),
                                      "used_fidelity_filter": qtype not in ("multiple_choice", "true_false")}
    out = _metric("M4", "B", "Grading agreement with the truth (kappa and false positives by type)", "GT",
                  {"value": 1.0 if (details and met_all) else 0.0}, 1.0, ">=", details=details)
    out["value_note"] = "1 = every type meets its kappa target and FP <= 0.10"
    return out


def m5(data: RunData) -> Dict[str, Any]:
    details = {}
    for mode, qtype in GRADE_GROUPS:
        rows = [t for t in _answers(data, mode, qtype) if not (_decision(t, "answer") or {}).get("diagnostic")]
        if rows:
            details[f"{mode}/{qtype}"] = {"n": len(rows), "not_graded": S.share(not (t.get("lea") or {}).get("graded")
                                                                               for t in rows)}
    return _metric("M5", "B", "Not-graded rate by type (warm-ups excluded)", "GT", {"value": None}, None, None,
                   details=details)


# ---------------------------------------------------------------------------- C. learner model tracking

def _week_rows(data: RunData) -> List[Dict[str, Any]]:
    rows = []
    for w in data.week_ends:
        for g in w["gos"]:
            rows.append({"learner": w["learner"], "profile": w["profile"], "week": w["week"], "go": g["go_id"],
                         "lea": g["lea_mastery"] if g["lea_mastery"] is not None else 0.0,
                         "lea_mastered": bool(g["lea_mastered"]), "known": bool(g["known"]), "p_know": g["p_know"]})
    return rows


def m6(data: RunData) -> Dict[str, Any]:
    per = []
    for w in data.week_ends:
        rho = S.spearman([g["lea_mastery"] if g["lea_mastery"] is not None else 0.0 for g in w["gos"]],
                         [g["p_know"] for g in w["gos"]])
        if rho is not None:
            per.append({"learner": w["learner"], "rho": rho})

    def median(xs):
        xs = sorted(xs)
        return None if not xs else (xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2)

    res = S.cluster_bootstrap(_clusters(per, lambda r: r["rho"]), median)
    return _metric("M6", "C", "Mastery tracking: median Spearman rho (LEA mastery vs true p_know), per learner-week",
                   "GT", res, 0.5, ">=", details={"learner_weeks_with_rho": len(per), "learner_weeks": len(data.week_ends)})


def m7(data: RunData) -> Dict[str, Any]:
    rows = _week_rows(data)
    precision = S.cluster_bootstrap(_clusters([r for r in rows if r["lea_mastered"]], lambda r: r["known"]), S.share)
    recall = S.cluster_bootstrap(_clusters([r for r in rows if r["known"]], lambda r: r["lea_mastered"]), S.share)
    out = _metric("M7", "C", "Mastery decisions: precision (premature mastery = 1 - precision)", "GT", precision,
                  0.85, ">=", details={"recall": recall, "premature_mastery": None if precision["value"] is None
                                       else 1 - precision["value"]})
    return out


def m8(data: RunData) -> Dict[str, Any]:
    rows = _week_rows(data)

    def tau(rs):
        by = S.group_by(rs, "profile")
        if len(by) < 3:
            return None
        names = sorted(by)
        return S.kendall_tau([S.mean(r["p_know"] for r in by[p]) for p in names], [S.mean(r["lea"] for r in by[p]) for p in names])

    res = S.cluster_bootstrap(_clusters(rows), tau)
    by = S.group_by(rows, "profile")
    order = sorted(by, key=lambda p: S.mean(r["p_know"] for r in by[p]))
    gaps = {}
    for a, b in zip(order, order[1:]):
        subset = [r for r in rows if r["profile"] in (a, b)]
        gaps[f"{b} - {a}"] = S.cluster_bootstrap(
            _clusters(subset), lambda rs: (S.mean(r["lea"] for r in rs if r["profile"] == b) or 0)
            - (S.mean(r["lea"] for r in rs if r["profile"] == a) or 0)
            if any(r["profile"] == a for r in rs) and any(r["profile"] == b for r in rs) else None)
    details = {"true_order": order, "profile_means": {p: {"true_p_know": S.mean(r["p_know"] for r in by[p]),
                                                          "lea_mastery": S.mean(r["lea"] for r in by[p])} for p in order},
               "adjacent_gaps_in_lea_mastery": gaps,
               "mixed_model": S.profile_contrasts(rows, "lea", order)}
    return _metric("M8", "C", "Profile separation: Kendall tau (true knowledge order vs LEA mastery order)", "GT", res,
                   0.73, ">=", details=details)


def m9(data: RunData) -> Dict[str, Any]:
    by_learner = S.group_by(sorted(data.turns, key=lambda t: (t["learner"], t["ts"])), "learner")
    points = []
    for learner, turns in by_learner.items():
        graded: List[float] = []
        for t in turns:
            state = _decision(t, "learner_state") or {}
            cog = state.get("cognitive_state") or {}
            zpd = cog.get("zpd_score", cog.get("zpd")) if isinstance(cog, dict) else None
            if zpd is not None and len(graded) >= 4:
                points.append({"learner": learner, "zpd": float(zpd), "truth": S.mean(graded[-4:])})
            if (t.get("intent") or {}).get("kind") == "answer" and (t.get("lea") or {}).get("graded"):
                graded.append(t["intent"]["p_correct"])
    res = S.cluster_bootstrap(_clusters(points), lambda rs: S.pearson([r["zpd"] for r in rs], [r["truth"] for r in rs]))
    return _metric("M9", "C", "ZPD tracking: r(LEA ZPD, true success probability over the last 4 graded items)", "GT",
                   res, 0.6, ">=", details={"points": len(points)})


# ---------------------------------------------------------------------------- D. adaptation

def _sessions(data: RunData) -> Dict[Tuple, List[Dict[str, Any]]]:
    out: Dict[Tuple, List[Dict[str, Any]]] = defaultdict(list)
    for t in data.turns:
        if t["mode"] == "tutor" and t.get("student_text"):
            out[(t["learner"], t["week"], t.get("round", 1))].append(t)
    for v in out.values():
        v.sort(key=lambda t: t["turn"])
    return out


def m10(data: RunData) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    up, down = [], []
    for (learner, _, _), turns in _sessions(data).items():
        answers = [t for t in turns if t["intent"]["kind"] == "answer"]
        levels = [_level(t) for t in answers]
        for i in range(len(answers)):
            base = levels[i]
            if base is None:
                continue
            if i >= 1 and not answers[i]["intent"]["correct"] and not answers[i - 1]["intent"]["correct"]:
                after = [x for x in levels[i + 1:i + 3] if x is not None]
                if after:
                    up.append({"learner": learner, "ok": max(after) > base})
            if i >= 2 and all(a["intent"]["correct"] for a in answers[i - 2:i + 1]):
                after = [x for x in levels[i + 1:i + 4] if x is not None]
                if after:
                    down.append({"learner": learner, "ok": min(after) < base})
    inc = S.cluster_bootstrap(_clusters(up, lambda r: r["ok"]), S.share)
    fade = S.cluster_bootstrap(_clusters(down, lambda r: r["ok"]), S.share)
    return (_metric("M10a", "D", "Scaffolding responsiveness: support rises within 2 turns after 2 wrong answers", "GT",
                    inc, 0.70, ">="),
            _metric("M10b", "D", "Scaffolding fading: support falls within 3 turns after 3 right answers", "GT",
                    fade, 0.70, ">="))


def m11(data: RunData) -> Dict[str, Any]:
    rows = []
    for (learner, _, _), turns in _sessions(data).items():
        for a, b in zip(turns, turns[1:]):
            la, lb = _level(a), _level(b)
            if la is None or lb is None or a["go_id"] != b["go_id"]:
                continue
            if (a.get("hidden_before") or {}).get("known") != (b.get("hidden_before") or {}).get("known"):
                continue
            rows.append({"learner": learner, "changed": la != lb})
    res = S.cluster_bootstrap(_clusters(rows, lambda r: r["changed"]),
                              lambda xs: None if not xs else 10 * sum(xs) / len(xs))
    return _metric("M11", "D", "Scaffolding stability: level changes per 10 turns while the true state is unchanged",
                   "GT", res, 1.0, "<=", details={"pairs": len(rows)})


def m12(data: RunData) -> Dict[str, Any]:
    rows = []
    for t in _answers(data, "tutor"):
        level = _level(t)
        if level is not None:
            rows.append({"learner": t["learner"], "level": level, "p": t["intent"]["p_correct"]})
    by_level = {}
    for name in LEVEL_NAMES:
        subset = [r for r in rows if r["level"] == LEVELS[name]]
        if subset:
            by_level[name] = S.cluster_bootstrap(_clusters(subset, lambda r: r["p"]), S.mean)
    present = [n for n in LEVEL_NAMES if n in by_level]
    means = [by_level[n]["value"] for n in present]
    monotone = all(x < y for x, y in zip(means, means[1:])) if len(means) >= 2 else None
    separated = all(by_level[a]["hi"] is not None and by_level[b]["lo"] is not None and by_level[a]["hi"] < by_level[b]["lo"]
                    for a, b in zip(present, present[1:])) if len(present) >= 2 else None
    ok = None if monotone is None else float(bool(monotone and separated))
    out = _metric("M12", "D", "Level-need alignment: true success probability rises from very_high to low support",
                  "GT", {"value": ok}, 1.0, ">=", details={"by_level": by_level, "monotone": monotone,
                                                           "adjacent_cis_separated": separated})
    out["value_note"] = "1 = monotone with non-overlapping adjacent CIs"
    return out


def m13(data: RunData) -> Dict[str, Any]:
    per_profile: Dict[str, Dict[str, Any]] = {}
    for profile in PROFILE_ORDER:
        sessions = {k: v for k, v in _sessions(data).items() if data.profile.get(k[0]) == profile}
        if not sessions:
            continue
        counts, over, total = [], 0, 0
        for turns in sessions.values():
            seen: Dict[str, int] = defaultdict(int)
            reached = set()
            for t in turns:
                if t["intent"]["kind"] not in ("answer", "question"):
                    continue
                total += 1
                over += bool((t.get("hidden_before") or {}).get("known"))
                go = t["go_id"]
                seen[go] += 1
                m = t.get("mastery") or {}
                if go not in reached and m.get("after") is not None and m.get("threshold") is not None \
                        and m["after"] >= m["threshold"]:
                    reached.add(go)
                    counts.append(seen[go])
        per_profile[profile] = {"turns_per_go_to_mastery": S.mean(counts), "gos_mastered_in_session": len(counts),
                                "over_teaching_share": over / total if total else None}
    return _metric("M13", "D", "Efficiency: turns per GO to LEA mastery; share of turns on already-known GOs", "GT",
                   {"value": None}, None, None, details=per_profile)


def m14(data: RunData) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    rows = []
    for w in data.week_ends:
        truly = S.share(g["known"] for g in w["gos"])
        rows.append({"learner": w["learner"], "stuck": bool(truly is not None and truly >= 0.75 and not w["advanced_to_week"]),
                     "early": bool(w["advanced_to_week"] and truly is not None and truly < 0.75)})
    stuck = S.cluster_bootstrap(_clusters(rows, lambda r: r["stuck"]), S.share)
    early = S.cluster_bootstrap(_clusters(rows, lambda r: r["early"]), S.share)
    return (_metric("M14a", "D", "Week advance: 'stuck' rate (truly >= 75% known, not advanced)", "GT", stuck, 0.10, "<=",
                    unit="learner-week"),
            _metric("M14b", "D", "Week advance: 'early' rate (advanced while truly < 75% known)", "GT", early, 0.10, "<=",
                    unit="learner-week"))


# ---------------------------------------------------------------------------- E. motivation

def m15(data: RunData) -> Dict[str, Any]:
    rows = []
    for t in data.turns:
        state = (_decision(t, "learner_state") or {}).get("motivation_state")
        eng = (t.get("intent") or {}).get("engagement")
        if state in MOTIVATION and eng:
            rows.append({"learner": t["learner"], "profile": t["profile"], "truth": eng, "lea": MOTIVATION[state]})
    res = S.cluster_bootstrap(_clusters(rows), lambda rs: S.macro_f1([r["truth"] for r in rs], [r["lea"] for r in rs],
                                                                       ENGAGEMENT))
    details = {"confusion": S.confusion([r["truth"] for r in rows], [r["lea"] for r in rows], ENGAGEMENT, ENGAGEMENT),
               "by_profile": {p: S.confusion([r["truth"] for r in rs], [r["lea"] for r in rs], ENGAGEMENT, ENGAGEMENT)
                              for p, rs in S.group_by(rows, "profile").items()},
               "cold_start_excluded": sum(1 for t in data.turns
                                          if (_decision(t, "learner_state") or {}).get("motivation_state") == "cold_start")}
    return _metric("M15", "E", "Motivation state vs hidden engagement: macro-F1", "GT", res, 0.6, ">=", details=details)


# ---------------------------------------------------------------------------- F, G. judged quality

def _judged_items(data: RunData, kind: str, items: List[str], mid: str, name: str, target: float, group: str):
    out = []
    for item in items:
        rows = [{"learner": j["learner"], "yes": v[item] == "yes"}
                for j in data.main_judgements(kind) if j["values"] for v in j["values"].values()]
        res = S.cluster_bootstrap(_clusters(rows, lambda r: r["yes"]), S.share)
        out.append(_metric(f"{mid}.{item}", group, f"{name}: {item.replace('_', ' ')}", "J", res, target, ">="))
    return out


def m16b(data: RunData, limit_words: int) -> Dict[str, Any]:
    rows = [{"learner": t["learner"], "ok": len(str((t.get("lea") or {}).get("message") or "").split()) <= limit_words}
            for t in data.turns if t["mode"] == "tutor" and (t.get("lea") or {}).get("message")]
    res = S.cluster_bootstrap(_clusters(rows, lambda r: r["ok"]), S.share)
    return _metric("M16b", "F", f"Tutor reply within {limit_words} words", "GT", res, 0.95, ">=")


def m17(data: RunData) -> Dict[str, Any]:
    rows = [{"learner": j["learner"], "score": v["coherence"]}
            for j in data.main_judgements("tutor") if j["values"] for v in j["values"].values()]
    res = S.cluster_bootstrap(_clusters(rows, lambda r: r["score"]), S.mean)
    return _metric("M17", "F", "Coherence over the last five turns (1-5)", "J", res, 4.0, ">=")


# ---------------------------------------------------------------------------- H. judge reliability

def _pairs(judgements, kind: str, fields: List[str]):
    """{(unit, id, field): {(role, repeat): value}}"""
    out: Dict[Tuple, Dict[Tuple, Any]] = defaultdict(dict)
    for j in judgements:
        if j["kind"] != kind or not j["values"]:
            continue
        for item, v in j["values"].items():
            for f in fields:
                out[(j["unit"], item, f)][(j["judge_role"], j["repeat"])] = v.get(f)
    return out


RELIABILITY_SPECS = {"M16": ("tutor", M16_ITEMS), "M17": ("tutor", ["coherence"]), "M18": ("quiz", M18_ITEMS),
                     "M3": ("chat", ["resolves_reference"]), "M0a": ("fidelity", ["label"]),
                     "SC3": ("support", ["support_fit"])}


def reliability(data: RunData, labels: Optional[Dict[str, Dict[str, str]]] = None) -> Dict[str, Dict[str, Any]]:
    out = {}
    for metric, (kind, fields) in RELIABILITY_SPECS.items():
        cells = _pairs(data.judgements, kind, fields)
        scale = fields == ["coherence"]
        repeats = [[v[("judge", r)] for r in range(3)] for v in cells.values() if all(("judge", r) in v for r in range(3))]
        m20 = S.icc_2_1(repeats) if scale else S.fleiss_kappa(repeats)
        two = [(v[("judge", 0)], v[("second_judge", 0)]) for v in cells.values()
               if ("judge", 0) in v and ("second_judge", 0) in v]
        m21 = (S.icc_2_1([list(p) for p in two]) if scale else S.cohen_kappa([a for a, _ in two], [b for _, b in two]))
        m22, n22 = None, 0
        if labels:
            human, judge = [], []
            for item_key, lab in labels.items():
                unit, item = item_key.rsplit("#", 1)
                for n, f in enumerate(fields):
                    column = "label_coherence" if f == "coherence" else f"label_{n + 1}"
                    cell = cells.get((unit, item, f), {})
                    if column in lab and ("judge", 0) in cell:
                        h = int(lab[column]) if scale and lab[column].isdigit() else lab[column]
                        human.append(h)
                        judge.append(cell[("judge", 0)])
            n22 = len(human)
            if human:
                m22 = S.icc_2_1([[a, b] for a, b in zip(human, judge)]) if scale else S.cohen_kappa(human, judge)
        reliable = (m20 is not None and m20 >= 0.70) and (m21 is not None and m21 >= 0.60) and \
            (m22 is None or m22 >= 0.60)
        out[metric] = {"M20_test_retest": m20, "M20_items": len(repeats), "M21_inter_judge": m21, "M21_items": len(two),
                       "M22_judge_human": m22, "M22_items": n22, "M22_status": "done" if labels else "pending",
                       "reliable": reliable if (m20 is not None and m21 is not None) else None}
    return out


def missing_counts(data: RunData) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = defaultdict(lambda: {"judged": 0, "missing": 0})
    for j in data.judgements:
        key = f"{j['kind']}/{j['judge_role']}"
        out[key]["judged" if j["values"] else "missing"] += 1
    return dict(out)


# ---------------------------------------------------------------------------- all together

def compute_all(events, judgements, config, *, m0c_result=None, labels=None, pass_id=None,
                ragas: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = RunData(events, judgements, pass_id)
    limit = int((config.get("metrics") or {}).get("tutor_reply_word_limit", 375))
    ms: List[Dict[str, Any]] = [m0a(data), m0b(data, config)]
    if m0c_result:
        ms.append(m0c_metric(m0c_result))
    ms += [m1(data)]
    ms.append(_metric("M2", "A", "RAGAS (faithfulness, answer relevancy, context precision, context recall)", "RAGAS",
                      {"value": None}, None, None, details=ragas or {"status": "not run"}))
    ms += [m3(data), m4(data), m5(data), m6(data), m7(data), m8(data), m9(data), *m10(data), m11(data), m12(data),
           m13(data), *m14(data), m15(data)]
    ms += _judged_items(data, "tutor", M16_ITEMS, "M16", "Tutor checklist", 0.85, "F")
    ms += [m16b(data, limit), m17(data)]
    from simulation import support_metrics

    ms += support_metrics.compute(data)
    ms.append(support_metrics.sc3(data))
    ms += _judged_items(data, "quiz", M18_ITEMS, "M18", "Quiz item checklist", 0.90, "G")
    rel = reliability(data, labels)
    for m in ms:
        base = m["id"].split(".")[0]
        if m["source"] == "J" and base in rel:
            m["reliability"] = rel[base]
            if rel[base]["reliable"] is False:
                m["reliability_note"] = "unreliable: failed M20/M21/M22 thresholds; reported, not a finding"
    return {"pass_id": data.pass_id, "metrics": ms, "reliability": rel, "judgements": missing_counts(data),
            "counts": {"turns": len(data.turns), "learner_weeks": len(data.week_ends),
                       "learners": len({t['learner'] for t in data.turns})}}
