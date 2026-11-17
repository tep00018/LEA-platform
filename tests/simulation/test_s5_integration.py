"""S5 on real-shaped events: a fake-LLM run, judged, then every metric and the report."""

from simulation.harness import load_bank, run
from simulation.judges import judge_run, read_events
from simulation.metrics import compute_all
from simulation.report import write
from simulation.settings import load
from simulation.validity import m0c
from tests.simulation.test_s3_drivers import FakeStudent, factory, pilot  # noqa: F401 (fixtures)
from tests.simulation.test_s4_judges import ScriptedJudge


def test_metrics_and_report_from_a_real_shaped_run(pilot, factory, tmp_path):  # noqa: F811
    result = run(pilot, "metrics", services_factory=factory, claude_client=FakeStudent(), runs_dir=tmp_path / "runs",
                 log=lambda m: None)
    config = load(pilot)
    judge_run(result["dir"], config, ScriptedJudge(), load_bank("AIML101"), pass_id="p1")
    events = read_events(f"{result['dir']}/events.jsonl")
    judgements = read_events(f"{result['dir']}/judgements.jsonl")
    results = compute_all(events, judgements, config, m0c_result=m0c(config, draws=2000, tolerance=0.03))
    by = {m["id"]: m for m in results["metrics"]}

    # Fields LEA really writes are found (not silently empty)
    assert by["M1"]["n"] and by["M4"]["details"] and by["M15"]["details"]["confusion"]
    assert by["M6"]["details"]["learner_weeks"] == 6
    assert by["M12"]["details"]["by_level"], "scaffolding intensity not found in LEA's answer events"
    assert by["M9"]["details"]["points"] > 0, "ZPD not found in LEA's learner_state events"
    assert sum(sum(row.values()) for row in by["M15"]["details"]["confusion"].values()) > 0
    assert by["M3"]["value"] is not None and by["M17"]["value"] is not None
    assert results["reliability"]["M16"]["M20_items"] > 0 and results["reliability"]["M16"]["M21_items"] > 0
    paths = write(tmp_path, results, manifest={"course": "AIML101"})
    assert "## D. Adaptation" in paths["report"].read_text(encoding="utf-8")

    from simulation.transcripts import pilot_report, write_transcripts

    files = write_transcripts(result["dir"], 10)
    assert 3 <= len(files) <= 10 and {f.name.rsplit("_", 1)[1] for f in files} >= {"tutor.md", "quiz.md", "chat.md"}
    text = files[0].read_text(encoding="utf-8")
    assert "hidden:" in text and "**Student:**" in text and "**LEA" in text
    report = pilot_report(result["dir"], [], results)
    assert "| Learner-week |" in report and "M0c" in report and report.count("sim_") >= 6
