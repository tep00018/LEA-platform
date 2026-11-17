"""KC models as editable rows: conversion both ways, ID assignment, validation and diffs.

A row is one granular objective (GO) with its learning objective (LO) and week:

    {go_id, week, week_title, lo_id, lo_title, lo_short_title, skill_name, description,
     cognitive_level, mastery_threshold, keywords, prerequisites, prerequisite_notes,
     split_from, merged_from, provenance}

ID rules (docs/teacher/BUILD_PLAN.md, B4): only LEA assigns IDs. A blank ``go_id`` is a new
objective; a blank ``lo_id`` a new learning objective (rows with the same week and LO title
share it). IDs are never changed or reused: an ID removed from the model is *retired*, and
a split (``split_from``) or merge (``merged_from``) is recorded in the model's lineage. New
IDs follow ``GO_<week>_<lo>_<n>`` from the LO they join, with the next number never used
for that LO; after a move, an ID no longer says where its objective is (``quick_lookup``
does).

``prerequisites`` are GO IDs. The model's ``prerequisite_concepts`` (names, which LEA's
prompts read) are rebuilt from them plus any ``prerequisite_notes`` that name no objective.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

BLOOM = ("Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create")
_BLOOM_ALIASES = {"knowledge": "Remember", "comprehension": "Understand", "application": "Apply",
                  "analysis": "Analyze", "analyse": "Analyze", "synthesis": "Create", "evaluation": "Evaluate"}
THRESHOLD_RANGE = (0.5, 0.95)
EDITABLE = ("week", "week_title", "lo_id", "lo_title", "lo_short_title", "skill_name", "description",
            "cognitive_level", "mastery_threshold", "keywords", "prerequisites", "prerequisite_notes")
GO_RE = re.compile(r"^GO_(\d{2})_(\d{2})_(\d{3})$")
LO_RE = re.compile(r"^LO_(\d{2})_(\d{2})$")


def bloom(value: Any) -> str:
    text = str(value or "").strip()
    return _BLOOM_ALIASES.get(text.lower(), text[:1].upper() + text[1:].lower() if text else "")


# ---------------------------------------------------------------------- model <-> rows


def weeks_of(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sorted(model.get("week_navigation", {}).values(), key=lambda w: w.get("week_number", 0))


def gos_of(model: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if not model:
        return {}
    return {go["go_id"]: go for w in weeks_of(model) for lo in w.get("learning_objectives", [])
            for go in lo.get("granular_objectives", [])}


def los_of(model: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if not model:
        return {}
    return {lo["lo_id"]: lo for w in weeks_of(model) for lo in w.get("learning_objectives", [])}


def rows_from_model(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    gos = gos_of(model)
    by_name = {go.get("skill_name", "").strip().lower(): gid for gid, go in gos.items()}
    rows = []
    for week in weeks_of(model):
        for lo in week.get("learning_objectives", []):
            for go in lo.get("granular_objectives", []):
                if "prerequisites" in go:
                    prereqs, notes = list(go["prerequisites"]), list(go.get("prerequisite_notes", []))
                else:  # older models name their prerequisites
                    names = go.get("prerequisite_concepts", [])
                    prereqs = [by_name[n.strip().lower()] for n in names if n.strip().lower() in by_name]
                    notes = [n for n in names if n.strip().lower() not in by_name]
                rows.append({
                    "go_id": go["go_id"], "week": week["week_number"],
                    "week_title": week.get("week_name", f"Week {week['week_number']}"),
                    "lo_id": lo["lo_id"], "lo_title": lo.get("title", ""), "lo_short_title": lo.get("short_title", ""),
                    "skill_name": go.get("skill_name", ""), "description": go.get("description", ""),
                    "cognitive_level": bloom(go.get("cognitive_level")),
                    "mastery_threshold": float(go.get("mastery_threshold", 0.75)),
                    "keywords": list(go.get("conceptual_tags", [])),
                    "prerequisites": [p for p in prereqs if p != go["go_id"]], "prerequisite_notes": notes,
                    "split_from": None, "merged_from": [], "provenance": go.get("provenance"),
                })
    return rows


def model_from_rows(rows: List[Dict[str, Any]], base: Optional[Dict[str, Any]], course_info: Dict[str, Any],
                    lineage: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a full KC model (week_navigation + quick_lookup) from rows that already have
    IDs, keeping any extra fields the base model had for each GO and LO."""
    base_gos, base_los = gos_of(base), los_of(base)
    skill = {r["go_id"]: r["skill_name"] for r in rows}
    weeks: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        week = weeks.setdefault(int(r["week"]), {"title": r.get("week_title") or f"Week {r['week']}", "los": {}})
        lo = week["los"].setdefault(r["lo_id"], {"row": r, "gos": []})
        go = copy.deepcopy(base_gos.get(r["go_id"], {"estimated_time_minutes": 15, "skill_category": "conceptual",
                                                      "complexity": "basic"}))
        go.update({
            "go_id": r["go_id"], "skill_name": r["skill_name"].strip(), "description": r["description"].strip(),
            "cognitive_level": bloom(r["cognitive_level"]), "mastery_threshold": round(float(r["mastery_threshold"]), 2),
            "conceptual_tags": [k.strip() for k in r.get("keywords", []) if str(k).strip()],
            "prerequisites": list(r.get("prerequisites", [])),
            "prerequisite_notes": list(r.get("prerequisite_notes", [])),
            "prerequisite_concepts": [skill[p] for p in r.get("prerequisites", []) if p in skill]
                                     + list(r.get("prerequisite_notes", [])),
        })
        if r.get("provenance"):
            go["provenance"] = r["provenance"]
        lo["gos"].append(go)

    navigation, lo_by_id, go_by_id, week_by_lo = {}, {}, {}, {}
    for number in sorted(weeks):
        week = weeks[number]
        learning_objectives = []
        for lo_id, entry in week["los"].items():
            r = entry["row"]
            lo = copy.deepcopy(base_los.get(lo_id, {"difficulty": 2, "complexity": "basic"}))
            lo.pop("granular_objectives", None)
            lo.update({"lo_id": lo_id, "title": r["lo_title"].strip(), "short_title": (r.get("lo_short_title") or "").strip(),
                       "granular_count": len(entry["gos"]),
                       "estimated_time": sum(int(g.get("estimated_time_minutes", 15)) for g in entry["gos"]),
                       "granular_objectives": entry["gos"]})
            lo.setdefault("description", "Learning objective covering: " + ", ".join(g["skill_name"] for g in entry["gos"]))
            learning_objectives.append(lo)
            lo_by_id[lo_id] = {k: v for k, v in lo.items()}
            week_by_lo[lo_id] = {"week_number": number, "week_name": week["title"]}
            for g in entry["gos"]:
                go_by_id[g["go_id"]] = {**g, "parent_lo_id": lo_id}
        navigation[f"week_{number:02d}"] = {
            "week_number": number, "week_name": week["title"], "week_display": f"Week {number}: {week['title']}",
            "learning_objectives": learning_objectives,
            "total_time_minutes": sum(lo["estimated_time"] for lo in learning_objectives),
            "total_granular_objectives": sum(lo["granular_count"] for lo in learning_objectives),
        }
    model = {"course_info": {**course_info, "total_weeks": len(navigation)}, "week_navigation": navigation,
             "quick_lookup": {"lo_by_id": lo_by_id, "go_by_id": go_by_id, "week_by_lo_id": week_by_lo}}
    if lineage is not None:
        model["lineage"] = lineage
    return model


# ---------------------------------------------------------------------- IDs


def assign_ids(rows: List[Dict[str, Any]], used: Iterable[str]) -> List[Dict[str, Any]]:
    """Give new rows IDs that were never used (``used``: every GO and LO ID ever issued)."""
    used = set(used)
    lo_numbers = [int(m.group(2)) for i in used if (m := LO_RE.match(i))]
    lo_numbers += [int(m.group(2)) for i in used if (m := GO_RE.match(i))]
    next_lo = max(lo_numbers, default=0) + 1
    new_los: Dict[Tuple[int, str], str] = {}
    rows = [dict(r) for r in rows]
    for r in rows:
        if not r.get("lo_id"):
            key = (int(r["week"]), r["lo_title"].strip().lower())
            if key not in new_los:
                new_los[key] = f"LO_{int(r['week']):02d}_{next_lo:02d}"
                next_lo += 1
            r["lo_id"] = new_los[key]
    for r in rows:
        if r.get("go_id"):
            continue
        m = LO_RE.match(r["lo_id"])
        prefix = f"GO_{m.group(1)}_{m.group(2)}_"
        taken = [int(i[-3:]) for i in used if i.startswith(prefix)]
        r["go_id"] = f"{prefix}{max(taken, default=0) + 1:03d}"
        used.add(r["go_id"])
    return rows


def ids_in(model: Optional[Dict[str, Any]]) -> Set[str]:
    return set(gos_of(model)) | set(los_of(model))


# ---------------------------------------------------------------------- validation


def validate(rows: List[Dict[str, Any]], known: Set[str], retired: Set[str], base_gos: Set[str],
             weeks: int) -> List[Dict[str, Any]]:
    """Problems with a set of rows: ``level`` is ``error`` (can't be saved) or ``warning``.
    ``known``: GO/LO IDs the rows may use; ``retired``: IDs that may never come back;
    ``base_gos``: the published GO IDs (split and merge sources); ``weeks``: the course's
    week count (every week needs objectives)."""
    issues: List[Dict[str, Any]] = []

    def add(i, field, message, level="error"):
        issues.append({"row": i + 1 if i is not None else None, "field": field, "message": message, "level": level})

    seen: Dict[str, int] = {}
    lo_home: Dict[str, Tuple[int, str]] = {}
    ids = {r.get("go_id") for r in rows if r.get("go_id")}
    for i, r in enumerate(rows):
        go_id, lo_id = r.get("go_id") or "", r.get("lo_id") or ""
        if go_id:
            if go_id in retired:
                add(i, "go_id", f"{go_id} was retired and can't come back. Leave the ID blank for a new objective.")
            elif go_id not in known:
                add(i, "go_id", f"Unknown ID {go_id}. IDs can't be typed in: leave it blank for a new objective.")
            if go_id in seen:
                add(i, "go_id", f"{go_id} appears twice (rows {seen[go_id]} and {i + 1}).")
            seen[go_id] = i + 1
        if lo_id and lo_id not in known:
            add(i, "lo_id", f"Unknown learning objective ID {lo_id}. Leave it blank for a new one.")
        try:
            week = int(r.get("week"))
        except (TypeError, ValueError):
            add(i, "week", "Week must be a number.")
            continue
        if not 1 <= week <= weeks:
            add(i, "week", f"Week must be 1 to {weeks}.")
        if lo_id:
            home = (week, (r.get("lo_title") or "").strip())
            if lo_id in lo_home and lo_home[lo_id][0] != week:
                add(i, "week", f"All objectives of {lo_id} must be in the same week.")
            elif lo_id in lo_home and lo_home[lo_id][1] != home[1]:
                add(i, "lo_title", f"{lo_id} has two different titles; give its rows the same one.")
            lo_home.setdefault(lo_id, home)
        if len((r.get("lo_title") or "").strip()) < 5:
            add(i, "lo_title", "Give the learning objective as a sentence.")
        if not (r.get("skill_name") or "").strip():
            add(i, "skill_name", "Give the objective a name.")
        if not (r.get("description") or "").strip():
            add(i, "description", "A description helps the tutor and the quiz stay on target.", "warning")
        if bloom(r.get("cognitive_level")) not in BLOOM:
            add(i, "cognitive_level", f"Bloom level must be one of: {', '.join(BLOOM)}.")
        try:
            t = float(r.get("mastery_threshold"))
            if not THRESHOLD_RANGE[0] <= t <= THRESHOLD_RANGE[1]:
                add(i, "mastery_threshold", f"Mastery threshold must be {THRESHOLD_RANGE[0]} to {THRESHOLD_RANGE[1]}.")
        except (TypeError, ValueError):
            add(i, "mastery_threshold", "Mastery threshold must be a number like 0.75.")
        for p in r.get("prerequisites", []):
            if p == go_id:
                add(i, "prerequisites", "An objective can't be its own prerequisite.")
            elif p not in ids:
                add(i, "prerequisites", f"Prerequisite {p} isn't an objective in this model.")
        split, merged = r.get("split_from"), r.get("merged_from") or []
        if split and merged:
            add(i, "split_from", "A row is either split from one objective or merged from several, not both.")
        if split and (split not in base_gos or split in ids):
            add(i, "split_from", f"{split} must be a published objective that this version removes.")
        if merged and (len(merged) < 2 or any(m not in base_gos or m in ids for m in merged)):
            add(i, "merged_from", "Merge two or more published objectives that this version removes.")
        if (split or merged) and go_id in base_gos:  # IDs LEA gave it in the draft are fine
            add(i, "go_id", "A split or merged objective is new: leave its ID blank.")

    # A split has several rows with the same split_from; anything else may be used once.
    split_sources = {r["split_from"] for r in rows if r.get("split_from")}
    merge_sources = [m for r in rows for m in (r.get("merged_from") or [])]
    for m in sorted({m for m in merge_sources if merge_sources.count(m) > 1 or m in split_sources}):
        add(None, "merged_from", f"{m} is used in more than one split or merge.")

    weeks_used = {int(r["week"]) for r in rows if str(r.get("week", "")).isdigit()}
    for w in range(1, weeks + 1):
        if w not in weeks_used:
            add(None, "week", f"Week {w} has no objectives.")
    issues += _cycle_issues(rows)
    week_of = {r["go_id"]: int(r["week"]) for r in rows if r.get("go_id") and str(r.get("week", "")).isdigit()}
    for i, r in enumerate(rows):
        for p in r.get("prerequisites", []):
            if p in week_of and r.get("go_id") in week_of and week_of[p] > week_of[r["go_id"]]:
                add(i, "prerequisites", f"{p} is taught in week {week_of[p]}, after this objective.", "warning")
    return issues


def _cycle_issues(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    graph = {r["go_id"]: [p for p in r.get("prerequisites", [])] for r in rows if r.get("go_id")}
    state: Dict[str, int] = {}
    cycles = []

    def visit(node, path):
        state[node] = 1
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                cycles.append(path[path.index(nxt):] + [nxt] if nxt in path else [node, nxt])
            elif state.get(nxt) is None and nxt in graph:
                visit(nxt, path + [nxt])
        state[node] = 2

    for node in graph:
        if state.get(node) is None:
            visit(node, [node])
    return [{"row": None, "field": "prerequisites", "level": "error",
             "message": "Prerequisites go round in a circle: " + " -> ".join(c)} for c in cycles]


# ---------------------------------------------------------------------- diff


def diff(before: Optional[Dict[str, Any]], after_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """What a draft changes against the published model."""
    old = {r["go_id"]: r for r in rows_from_model(before)} if before else {}
    new = {r["go_id"]: r for r in after_rows if r.get("go_id")}
    splits = {r["split_from"]: [] for r in after_rows if r.get("split_from")}
    for r in after_rows:
        if r.get("split_from"):
            splits[r["split_from"]].append(r["go_id"])
    merges = [{"from": list(r["merged_from"]), "to": r["go_id"]} for r in after_rows if r.get("merged_from")]
    merged_away = {m for mg in merges for m in mg["from"]}
    changed = []
    for gid in sorted(set(old) & set(new)):
        fields = [{"field": f, "before": old[gid].get(f), "after": new[gid].get(f)} for f in EDITABLE
                  if f not in ("prerequisite_notes",) and _norm(old[gid].get(f)) != _norm(new[gid].get(f))]
        if fields:
            changed.append({"go_id": gid, "changes": fields})
    added = [gid for gid in new if gid not in old]
    removed = [gid for gid in old if gid not in new]
    return {
        "added": [{"go_id": g, "skill_name": new[g]["skill_name"], "week": new[g]["week"]} for g in added],
        "changed": changed,
        "retired": [{"go_id": g, "skill_name": old[g]["skill_name"]} for g in removed
                    if g not in splits and g not in merged_away],
        "splits": [{"from": k, "to": v} for k, v in splits.items()],
        "merges": merges,
        "counts": {"added": len(added), "changed": len(changed), "removed": len(removed),
                   "splits": len(splits), "merges": len(merges), "total": len(new)},
    }


def _norm(value):
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, str):
        return value.strip()
    return value
