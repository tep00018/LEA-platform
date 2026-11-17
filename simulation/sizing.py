"""Calibration and sizing (docs/simulation/PLAN.md, section 6, layer 4).

Anthropic doesn't publish plan allowances as numbers, so they are measured:

- ``calibrate``: the pilot's API-equivalent Claude spend divided by the share of each
  window it used (the researcher's /usage percentages before and after, with no other Claude
  work in between) estimates the 5-hour and weekly allowances in API-equivalent dollars.
  Saved to ``simulation/config/allowance.yaml`` with the date and plan.
- ``plan``: from the pilot's per-learner-week figures, a proposed run's Claude calls,
  tokens and cost by role, LEA's OpenAI cost, wall time, and how many days and 5-hour
  windows it needs within ``share_of_allowance``. If it needs more than
  ``max_days_per_run``, it proposes scale-downs in the plan's order and the run won't start.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from simulation.llm.usage_guard import UsageLedger

JUDGE_ROLES = ("judge", "second_judge")


def pilot_rates(run_dir: Path, ledger: UsageLedger) -> Dict[str, Any]:
    """Per learner-week averages from a finished pilot (its manifest, events and ledger rows)."""
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    run_id = manifest["run_id"]
    weeks = max(1, int(manifest.get("learner_weeks_done") or 0))
    rows = [r for r in ledger.records() if r.get("run_id") == run_id]
    by_role: Dict[str, Dict[str, float]] = defaultdict(lambda: {"calls": 0, "usd": 0.0, "tokens": 0})
    for r in rows:
        role = r.get("role") or "unknown"
        by_role[role]["calls"] += 1
        by_role[role]["usd"] += float(r.get("cost_usd") or 0)
        by_role[role]["tokens"] += sum(int(r.get(k) or 0) for k in ("input_tokens", "output_tokens",
                                                                     "cache_read_input_tokens",
                                                                     "cache_creation_input_tokens"))
    seconds = 0.0
    events = run_dir / "events.jsonl"
    if events.exists():
        for line in events.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            if e.get("kind") == "learner_week":
                seconds += float(e.get("seconds") or 0)
    return {"run_id": run_id, "learner_weeks": weeks,
            "per_learner_week": {role: {k: v / weeks for k, v in d.items()} for role, d in by_role.items()},
            "openai_usd_per_learner_week": float((manifest.get("openai") or {}).get("usd") or 0) / weeks,
            "seconds_per_learner_week": seconds / weeks,
            "judged_share_in_pilot": 1.0}


def calibrate(pilot_usd: float, before: Dict[str, float], after: Dict[str, float], plan: str,
              path: Path, note: str = "") -> Dict[str, Any]:
    """``before``/``after``: {"five_hour": %, "seven_day": %} from /usage (0-100)."""
    out: Dict[str, Any] = {"calibrated_on": date.today().isoformat(), "plan": plan, "pilot_api_equivalent_usd": pilot_usd,
                           "before_percent": before, "after_percent": after, "note": note}
    for window, key in (("five_hour", "five_hour_usd"), ("seven_day", "weekly_usd")):
        used = float(after[window]) - float(before[window])
        out[f"{window}_used_percent"] = used
        out[key] = round(pilot_usd / (used / 100), 2) if used > 0 else None
    if out["weekly_usd"] is None:
        raise ValueError("The weekly percentage didn't move, so the allowance can't be estimated; the pilot was "
                         "too small or the numbers were read at the wrong times.")
    Path(path).write_text(yaml.safe_dump(out, sort_keys=False), encoding="utf-8")
    return out


def estimate(config: Dict[str, Any], rates: Dict[str, Any], *, tutor_share: Optional[float] = None,
             weeks: Optional[List[int]] = None, learners_per_profile: Optional[int] = None,
             second_judge_frac: float = 0.10) -> Dict[str, Any]:
    scale = config["scale"]
    n_learners = (learners_per_profile or int(scale["learners_per_profile"])) * len(config["profiles"])
    n_weeks = len(weeks if weeks is not None else scale["weeks"])
    lw = n_learners * n_weeks
    share = 1.0 if tutor_share is None else tutor_share
    per = rates["per_learner_week"]
    roles = {}
    for role, d in per.items():
        factor = share if role == "judge" else (share * second_judge_frac / 0.10 if role == "second_judge" else 1.0)
        roles[role] = {"calls": round(d["calls"] * lw * factor), "usd": round(d["usd"] * lw * factor, 2),
                       "tokens": round(d["tokens"] * lw * factor)}
    claude_usd = sum(r["usd"] for r in roles.values())
    return {"learners": n_learners, "weeks": n_weeks, "learner_weeks": lw, "tutor_share_judged": share,
            "claude": {"by_role": roles, "api_equivalent_usd": round(claude_usd, 2),
                       "calls": sum(r["calls"] for r in roles.values())},
            "openai_usd": round(rates["openai_usd_per_learner_week"] * lw, 2),
            "wall_hours_sequential": round(rates["seconds_per_learner_week"] * lw / 3600, 1)}


def fit(est: Dict[str, Any], config: Dict[str, Any], allowance: Dict[str, Any]) -> Dict[str, Any]:
    c = config["claude"]
    weekly = float(allowance["weekly_usd"]) * float(c["share_of_allowance"])
    five = float(allowance.get("five_hour_usd") or 0) * float(c["share_of_allowance"])
    usd = est["claude"]["api_equivalent_usd"]
    days = math.ceil(7 * usd / weekly) if weekly > 0 else None
    windows = math.ceil(usd / five) if five > 0 else None
    share_of_week = usd / float(allowance["weekly_usd"]) if allowance.get("weekly_usd") else None
    return {"days": days, "five_hour_windows": windows, "share_of_weekly_allowance": share_of_week,
            "budget_per_week_usd": round(weekly, 2), "budget_per_5h_usd": round(five, 2),
            "fits": days is not None and days <= int(c["max_days_per_run"])}


def plan(config: Dict[str, Any], rates: Dict[str, Any], allowance: Dict[str, Any]) -> Dict[str, Any]:
    """The run as configured, and, if it doesn't fit, scale-downs in the plan's order."""
    base = estimate(config, rates)
    result = {"proposed": {**base, **fit(base, config, allowance)}, "alternatives": []}
    if result["proposed"]["fits"]:
        return result
    weeks = list(config["scale"]["weeks"])
    lpp = int(config["scale"]["learners_per_profile"])
    steps = [("judge a 50% stratified sample of tutor sessions", dict(tutor_share=0.5))]
    for k in range(len(weeks) - 1, 0, -1):
        steps.append((f"fewer weeks: {weeks[:k]}", dict(tutor_share=0.5, weeks=weeks[:k])))
    for n in range(lpp - 1, 4, -1):
        steps.append((f"{n} learners per profile", dict(tutor_share=0.5, weeks=weeks[:1], learners_per_profile=n)))
    steps.append(("Opus second judge on a 5% sample", dict(tutor_share=0.5, weeks=weeks[:1], learners_per_profile=5,
                                                          second_judge_frac=0.05)))
    for label, kw in steps:
        est = estimate(config, rates, **kw)
        f = fit(est, config, allowance)
        result["alternatives"].append({"change": label, **est, **f})
        if f["fits"]:
            break
    return result
