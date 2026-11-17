"""Mastery changes in the event log: the learner record that profiles and refreshers are built from."""

import json

from src.services.mastery_log import mastery_events

KC = {"week_navigation": {"week_01": {"learning_objectives": [
    {"lo_id": "LO_01_01", "granular_objectives": [
        {"go_id": "GO_01_01_001", "mastery_threshold": 0.7},
        {"go_id": "GO_01_01_002", "mastery_threshold": 0.8},
        {"go_id": "GO_01_01_003"},
    ]},
]}}}


def kinds(events):
    return [(t, p.get("scope"), p.get("event")) for t, p in events]


def test_a_change_inside_the_threshold_logs_only_the_level():
    events = mastery_events("GO_01_01_001", {"GO_01_01_001": 0.3}, {"GO_01_01_001": 0.5}, KC)
    assert kinds(events) == [("mastery_change", None, None)]
    go = events[0][1]["go"]
    assert go == {"level_before": 0.3, "level_after": 0.5, "threshold": 0.7,
                  "mastered_before": False, "mastered_after": False}
    assert events[0][1]["lo"] == {"id": "LO_01_01", "mastered_before": False, "mastered_after": False,
                                  "objectives_mastered": 0, "objectives_total": 3}


def test_crossing_the_threshold_logs_a_milestone_and_completing_the_lo_logs_another():
    done = {"GO_01_01_001": 0.9, "GO_01_01_002": 0.85}
    events = mastery_events("GO_01_01_003", {**done, "GO_01_01_003": 0.75}, {**done, "GO_01_01_003": 0.82}, KC)
    assert kinds(events) == [("mastery_change", None, None), ("mastery_milestone", "go", "mastered"),
                             ("mastery_milestone", "lo", "mastered")]  # GO_01_01_003 has no threshold: 0.8
    assert events[2][1] == {"scope": "lo", "id": "LO_01_01", "event": "mastered",
                            "objectives_mastered": 3, "objectives_total": 3}


def test_falling_below_the_threshold_is_logged_as_lost():
    both = {"GO_01_01_001": 0.9, "GO_01_01_002": 0.85, "GO_01_01_003": 0.9}
    events = mastery_events("GO_01_01_002", both, {**both, "GO_01_01_002": 0.7}, KC)
    assert kinds(events) == [("mastery_change", None, None), ("mastery_milestone", "go", "lost"),
                             ("mastery_milestone", "lo", "lost")]


def test_without_a_model_the_default_threshold_applies_and_no_lo_milestone_is_invented():
    events = mastery_events("GO_01_01_001", {}, {"GO_01_01_001": 0.81}, None)
    assert kinds(events) == [("mastery_change", None, None), ("mastery_milestone", "go", "mastered"),
                             ("mastery_milestone", "lo", "mastered")]  # a one-objective LO when the model is unknown
    assert events[0][1]["go"]["level_before"] is None and events[0][1]["go"]["threshold"] == 0.8


def mastery_rows(svc, username, type_):
    pseudonym = svc.events.pseudonym(username)
    return [r for r in svc.events.log.query("type = ?", (type_,)) if r["username_hash"] == pseudonym]


def test_graded_answers_write_mastery_events_and_ungraded_ones_do_not(services, username):
    graded = {"graded": True, "correct": True, "score": 1.0}
    services.learning.record(username, "DEMO101", 1, mode="quiz", go_id="GO_01_01_001", result=graded)
    services.learning.record(username, "DEMO101", 1, mode="tutor", go_id="GO_01_01_002",
                             result={"graded": False, "correct": None, "score": None})
    rows = mastery_rows(services, username, "mastery_change")
    assert len(rows) == 1 and rows[0]["go_id"] == "GO_01_01_001" and rows[0]["lo_id"] == "LO_01_01"
    payload = json.loads(rows[0]["payload_json"])
    assert payload["go"]["level_before"] is None and payload["go"]["level_after"] > 0.9
    assert payload["go"]["mastered_after"] is True


def test_mastering_every_objective_of_a_learning_objective_logs_the_milestones_once(services, username):
    graded = {"graded": True, "correct": True, "score": 1.0}
    lo_gos = [g for g in ("GO_01_01_001", "GO_01_01_002", "GO_01_01_003", "GO_01_01_004")]
    for go in lo_gos:
        for _ in range(3):
            services.learning.record(username, "DEMO101", 1, mode="quiz", go_id=go, result=graded)
    milestones = [json.loads(r["payload_json"]) for r in mastery_rows(services, username, "mastery_milestone")]
    assert [m["id"] for m in milestones if m["scope"] == "go"] == lo_gos  # each reached once, in order
    los = [m for m in milestones if m["scope"] == "lo"]
    assert len(los) == 1 and los[0]["id"] == "LO_01_01" and los[0]["event"] == "mastered"
    assert services.learning.go_masteries(username, "DEMO101").keys() >= set(lo_gos)
