"""Command line for the simulation.

    python -m simulation check-claude [--model haiku]    # one live call through the subscription
    python -m simulation build-bank [--dry-run]           # the AIML101 question bank (S2)
    python -m simulation run --config simulation/config/pilot.yaml [--run-id ID] [--resume]
    python -m simulation judge --run-id ID [--tutor-share 0.5] [--no-reliability]   # from saved events
    python -m simulation reanalyse --run-id ID [--pass-id P] [--labels sheet.csv]   # metrics and report
    python -m simulation calibrate --run-id PILOT --plan "Max 20x" --before 43,24 --after 55,27
    python -m simulation plan --config simulation/config/main.yaml --from PILOT
    python -m simulation transcripts --run-id ID [--n 10]
    python -m simulation pilot-report --run-id PILOT
    python -m simulation compare-models [--arms openai,sonnet,sonnet_nocoach] [--max-calls 250]

Further commands (run, plan, rejudge, reanalyse) arrive with later milestones.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional

from simulation import REPO_ROOT, RUNS_DIR
from simulation.llm.claude_cli import ClaudeCallError, ClaudeCLI, init_summary
from simulation.llm.usage_guard import ClaudePause, ClaudeStop, GuardSettings, UsageGuard, UsageLedger
from simulation.settings import ConfigError, load

LEDGER = RUNS_DIR / "usage_ledger.jsonl"


def check_claude(model: str, config_path: Optional[str] = None) -> int:
    """One tiny call, to confirm ``claude -p`` works through the subscription login and to
    show what the init event reports as loaded. Capped at one call; needs no run approval."""
    config = load(config_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"check-{stamp}"
    folder = RUNS_DIR / "_checks" / run_id
    settings = GuardSettings.from_config(config["claude"])
    settings.max_calls_per_run = 1
    guard = UsageGuard(settings, UsageLedger(LEDGER), run_id, events_path=folder / "usage_events.jsonl")
    client = ClaudeCLI(guard, guard.ledger, folder / "claude_cwd", executable=config["claude"]["executable"],
                       concurrency=1, timeout_seconds=int(config["claude"]["timeout_seconds"]))
    try:
        result = client.call("Reply with exactly: OK", system_prompt="You reply with exactly what is asked.",
                             model=model, role="check")
    except ClaudeStop as e:
        print(f"Stopped: {e}")
        return 2
    except ClaudePause as e:
        print(f"Paused: {e}")
        return 3
    except ClaudeCallError as e:
        print(f"The call failed: {e}")
        return 1
    report = {"reply": result.text.strip(), "model": result.model, "cost_usd_api_equivalent": result.cost_usd,
              "usage": {k: result.usage.get(k) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                          "cache_creation_input_tokens")},
              "rate_limit_events": result.rate_limit_events, "init": init_summary(result.init)}
    (folder / "check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nSaved to {folder / 'check.json'}")
    return 0


def build_bank(dry_run: bool, config_path: Optional[str] = None) -> int:
    """Build ``simulation/assets/<course>/question_bank.json`` and its spot-check sheet."""
    from simulation import PACKAGE_DIR, REPO_ROOT
    from simulation.bank import build, load_inputs, plan_calls, prompt_for, spot_check_sheet

    config = load(config_path)
    course = config["course"]
    data_dir = REPO_ROOT / "data"
    inputs = load_inputs(data_dir, course)
    calls = plan_calls(inputs)
    tokens = [len(prompt_for(c, inputs, course)) // 4 for c in calls]
    for c, t in zip(calls, tokens):
        print(f"week {c['week']}: {len(c['rows'])} GOs, ~{t:,} input tokens")
    print(f"{len(calls)} calls, ~{sum(tokens):,} input tokens (at most {2 * len(calls)} calls with retries)")
    if dry_run:
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"bank-{course}-{stamp}"
    folder = RUNS_DIR / run_id
    checkpoints = RUNS_DIR / f"bank-{course}-checkpoints"  # finished weeks, reused by the next build
    settings = GuardSettings.from_config(config["claude"])
    settings.max_calls_per_run = 2 * len(calls)
    guard = UsageGuard(settings, UsageLedger(LEDGER), run_id, events_path=folder / "usage_events.jsonl")
    client = ClaudeCLI(guard, guard.ledger, folder / "claude_cwd", executable=config["claude"]["executable"],
                       concurrency=int(config["claude"]["concurrency"]), timeout_seconds=900)
    try:
        bank = build(client, data_dir, course, config["claude"]["bank_model"],
                     concurrency=int(config["claude"]["concurrency"]), checkpoint_dir=checkpoints)
    except (ClaudeStop, ClaudePause) as e:
        print(f"Stopped: {e}")
        return 2
    except RuntimeError as e:
        print(f"Not finished: {e}")
        return 1
    out = PACKAGE_DIR / "assets" / course
    out.mkdir(parents=True, exist_ok=True)
    (out / "question_bank.json").write_text(json.dumps(bank, indent=2, ensure_ascii=False) + "\n",
                                            encoding="utf-8")
    (out / "spot_check.md").write_text(spot_check_sheet(bank), encoding="utf-8")
    print(f"{len(bank['entries'])} entries; {sum(len(r['attempts']) for r in bank['calls'])} calls; "
          f"${bank['api_equivalent_usd']:.2f} API-equivalent; models {bank['generator']['models']}")
    if bank["needs_review"]:
        print(f"Flagged for review (quote not found word for word): {', '.join(bank['needs_review'])}")
    print(f"Wrote {out / 'question_bank.json'} and spot_check.md")
    return 0


def compare_models(args) -> int:
    """LEA unchanged, its client swapped: OpenAI as deployed, then Sonnet (subscription)."""
    from dotenv import load_dotenv

    from simulation.capture import OpenAIMeter
    from simulation.compare import COURSE, bank_for, openai_costs, run_arm, write_comparison
    from simulation.harness import ALLOWANCE, PausingClient
    from simulation.isolation import RunContext
    from simulation.llm.openai_compat import ClaudeChatClient
    from simulation.llm.usage_guard import preflight

    load_dotenv(REPO_ROOT / ".env")  # OPENAI_API_KEY (LEA on OpenAI, and retrieval embeddings)
    config = load(args.config)
    try:
        preflight(config, ALLOWANCE)
    except ClaudeStop as e:
        print(f"Not started: {e}")
        return 2
    base = "compare-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bank = bank_for(COURSE)
    arms, costs = [], {}
    for arm in [a.strip() for a in args.arms.split(",") if a.strip()]:
        ctx = RunContext(f"{base}-{arm}", COURSE)
        with ctx:
            from src.services.container import build_services

            if arm == "openai":
                label = "LEA on OpenAI (gpt-4o-mini)"
                with OpenAIMeter(float(config["openai"]["budget_usd"])) as meter:
                    result = run_arm(label, build_services(ctx.redis_url), bank)
                costs[label] = openai_costs(meter)
            elif arm in ("sonnet", "sonnet_nocoach"):
                import contextlib

                import src.core.mastery_tracker as mastery_tracker
                import src.storage.consolidation_worker as consolidation
                from simulation.variants import quiz_questions_without_coaching

                variant = arm == "sonnet_nocoach"
                label = "LEA on Claude Sonnet" + (" (no coaching in questions)" if variant else "")
                settings = GuardSettings.from_config(config["claude"])
                settings.max_calls_per_run = args.max_calls
                guard = UsageGuard(settings, UsageLedger(LEDGER), ctx.run_id, events_path=ctx.dir / "usage_events.jsonl")
                cli = ClaudeCLI(guard, guard.ledger, ctx.claude_cwd, executable=config["claude"]["executable"],
                                concurrency=1, timeout_seconds=int(config["claude"]["timeout_seconds"]))
                chat = ClaudeChatClient(PausingClient(cli, on_pause=lambda p: print(f"Paused: {p}")),
                                        model=config["claude"]["judge_model"], role="lea_sonnet")
                saved = (mastery_tracker.OpenAI, consolidation.OpenAI)
                mastery_tracker.OpenAI = consolidation.OpenAI = lambda *a, **k: chat  # as the tests do
                try:
                    with OpenAIMeter(float(config["openai"]["budget_usd"])) as meter, (
                            quiz_questions_without_coaching() if variant else contextlib.nullcontext()):
                        result = run_arm(label, build_services(ctx.redis_url, openai_client=chat), bank,
                                         should_stop=lambda: guard.stopped or chat.stop_reason,
                                         parts=("quiz",) if variant else ("chat", "tutor", "quiz"))
                finally:
                    mastery_tracker.OpenAI, consolidation.OpenAI = saved
                costs[label] = {**openai_costs(meter), "Claude calls": len(chat.calls),
                                "Claude API-equivalent $": round(sum(c["cost_usd"] or 0 for c in chat.calls), 3),
                                "Claude models": sorted({c["model"] for c in chat.calls if c["model"]})}
            else:
                print(f"Unknown arm {arm!r}")
                return 1
        arms.append(result)
        print(f"{label}: {len(result['chat'])} chat, {len(result['tutor'].get('turns', []))} tutor, "
              f"{len(result['quiz'])} quiz turns in {result['seconds']}s"
              + (f"; stopped: {result['error']}" if result.get("error") else ""))
    out = RUNS_DIR / base
    out.mkdir(parents=True, exist_ok=True)
    notes = None
    if any(a["label"].endswith("(no coaching in questions)") for a in arms):
        from simulation.variants import describe

        notes = describe()
    write_comparison(out / "comparison.md", arms, costs, notes)
    print(f"Wrote {out / 'comparison.md'}")
    return 0 if not any(a.get("error") for a in arms) else 2


def judge(args) -> int:
    """Judge a finished run (``--rejudge`` in the plan): the same ledger and call cap as the run."""
    from simulation.harness import ALLOWANCE, PausingClient, load_bank
    from simulation.judges import judge_run
    from simulation.llm.usage_guard import preflight

    run_dir = RUNS_DIR / args.run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    config = manifest["config"]
    try:
        preflight(config, ALLOWANCE)
    except ClaudeStop as e:
        print(f"Not started: {e}")
        return 2
    guard = UsageGuard(GuardSettings.from_config(config["claude"]), UsageLedger(LEDGER), args.run_id,
                       events_path=run_dir / "usage_events.jsonl")
    client = PausingClient(ClaudeCLI(guard, guard.ledger, run_dir / "claude_cwd", executable=config["claude"]["executable"],
                                     concurrency=int(config["claude"]["concurrency"]),
                                     timeout_seconds=int(config["claude"]["timeout_seconds"])),
                           on_pause=lambda p: print(f"Paused: {p}"))
    pass_id = args.pass_id or datetime.now(timezone.utc).strftime("judge-%Y%m%dT%H%M%SZ")
    try:
        summary = judge_run(run_dir, config, client, load_bank(config["course"]), pass_id=pass_id,
                            tutor_share=args.tutor_share, support_share=args.support_share,
                            kinds=args.kinds.split(",") if args.kinds else None,
                            reliability=not args.no_reliability)
    except ClaudeStop as e:
        print(f"Stopped: {e}")
        return 2
    print(json.dumps({"pass_id": pass_id, **summary}, indent=2))
    return 0


def reanalyse(args) -> int:
    """Recompute every metric and the report from a run's saved events and judgements."""
    from simulation.judges import read_events, read_labels
    from simulation.metrics import compute_all
    from simulation.report import write
    from simulation.validity import m0c

    run_dir = RUNS_DIR / args.run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    config = manifest["config"]
    events = read_events(run_dir / "events.jsonl")
    judged = run_dir / "judgements.jsonl"
    judgements = read_events(judged) if judged.exists() else []
    labels = read_labels(args.labels) if args.labels else None
    ragas_file = run_dir / "ragas.json"
    ragas = json.loads(ragas_file.read_text(encoding="utf-8")) if ragas_file.exists() else None
    results = compute_all(events, judgements, config, m0c_result=m0c(config), labels=labels, pass_id=args.pass_id,
                          ragas=ragas)
    rows = [r for r in UsageLedger(LEDGER).records() if r.get("run_id") == args.run_id]
    costs = {"openai": manifest.get("openai"), "claude_api_equivalent_usd_by_role": {}}
    for r in rows:
        role = r.get("role")
        costs["claude_api_equivalent_usd_by_role"][role] = round(
            costs["claude_api_equivalent_usd_by_role"].get(role, 0) + float(r.get("cost_usd") or 0), 4)
    paths = write(run_dir, results, manifest=manifest, costs=costs)
    print(f"Wrote {paths['report']}")
    return 0


def calibrate_cmd(args) -> int:
    from simulation.harness import ALLOWANCE
    from simulation.sizing import calibrate

    rows = [r for r in UsageLedger(LEDGER).records() if r.get("run_id") == args.run_id]
    usd = round(sum(float(r.get("cost_usd") or 0) for r in rows), 4)
    before = dict(zip(("five_hour", "seven_day"), map(float, args.before.split(","))))
    after = dict(zip(("five_hour", "seven_day"), map(float, args.after.split(","))))
    result = calibrate(usd, before, after, args.plan, ALLOWANCE, args.note)
    print(json.dumps(result, indent=2))
    return 0


def plan_cmd_run(args) -> int:
    import yaml

    from simulation.harness import ALLOWANCE
    from simulation.sizing import pilot_rates, plan

    if not ALLOWANCE.exists():
        print("No calibration yet: run the pilot, then python -m simulation calibrate.")
        return 1
    config = load(args.config)
    rates = pilot_rates(RUNS_DIR / args.pilot, UsageLedger(LEDGER))
    result = plan(config, rates, yaml.safe_load(ALLOWANCE.read_text(encoding="utf-8")))
    print(json.dumps({"pilot_rates": rates, **result}, indent=2))
    return 0 if result["proposed"]["fits"] else 3


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m simulation", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check-claude", help="One live call through the subscription login")
    check.add_argument("--model", default="haiku")
    check.add_argument("--config")
    bank = sub.add_parser("build-bank", help="Build the question bank (Claude, subscription)")
    bank.add_argument("--dry-run", action="store_true", help="Show the planned calls; send nothing")
    bank.add_argument("--config")
    run_cmd = sub.add_parser("run", help="Run a simulation (LEA on OpenAI; students on Claude)")
    run_cmd.add_argument("--config", required=True)
    run_cmd.add_argument("--run-id")
    run_cmd.add_argument("--verbose", action="store_true",
                         help="Print one debug line per turn (intent, what was said, LEA's grade, mastery, decisions, cost)")
    run_cmd.add_argument("--resume", action="store_true", help="Continue a stopped run from its checkpoint")
    judge_cmd = sub.add_parser("judge", help="Judge a run from its saved events (Claude; no LEA or OpenAI)")
    judge_cmd.add_argument("--run-id", required=True)
    judge_cmd.add_argument("--tutor-share", type=float, default=1.0, help="Judge this stratified share of tutor sessions")
    judge_cmd.add_argument("--support-share", type=float, default=0.20,
                           help="Judge this stratified share of sessions for SC3 (support appropriateness)")
    judge_cmd.add_argument("--kinds", help="Comma-separated kinds to judge (tutor, quiz, chat, fidelity, support); default all")
    judge_cmd.add_argument("--no-reliability", action="store_true", help="Skip the repeat and second-judge samples")
    judge_cmd.add_argument("--pass-id", help="Label for this judging pass (default: a timestamp)")
    re_cmd = sub.add_parser("reanalyse", help="Metrics and report from saved events and judgements (no model calls)")
    re_cmd.add_argument("--run-id", required=True)
    re_cmd.add_argument("--pass-id", help="Judging pass to use (default: the latest)")
    re_cmd.add_argument("--labels", help="The owner's filled-in labelling sheet (M22)")
    cal = sub.add_parser("calibrate", help="Estimate the allowance from the pilot and /usage percentages")
    cal.add_argument("--run-id", required=True, help="The pilot run")
    cal.add_argument("--plan", required=True, help='Your Claude plan, e.g. "Max 20x"')
    cal.add_argument("--before", required=True, help="5-hour and weekly percent before the pilot, e.g. 43,24")
    cal.add_argument("--after", required=True, help="the same after the pilot, e.g. 55,27")
    cal.add_argument("--note", default="")
    plan_cmd = sub.add_parser("plan", help="Size a run from the pilot's figures and the calibration")
    plan_cmd.add_argument("--config", required=True)
    plan_cmd.add_argument("--from", dest="pilot", required=True, help="The pilot run id")
    pz = sub.add_parser("personalize", help="Simulation study: can cognitive load and ZPD be personalised from "
                                            "behaviour? (numerical, no Claude or OpenAI calls)")
    pz.add_argument("--learners-per-profile", type=int, default=20)
    pz.add_argument("--sensitivity", action="store_true", help="Also vary one setting at a time")
    pz.add_argument("--out", default=str(REPO_ROOT / "simulation" / "runs" / "personalization"))
    ca = sub.add_parser("compare-arms", help="Compare two runs of the same learners with different cognitive-load "
                                             "equations driving scaffolding (A = fixed, B = personal)")
    ca.add_argument("--a", required=True, help="Run id using the fixed equation")
    ca.add_argument("--b", required=True, help="Run id using the personal equation")
    ca.add_argument("--scaffolding", action="store_true",
                    help="Amendment A2: the runs differ in the scaffolding model (primary outcomes P2 and P3)")
    gd = sub.add_parser("build-grader-dataset", help="Offline: build the fixed grader-replay dataset from saved "
                                                    "pilot events (no calls)")
    gd.add_argument("--pilots", help="Comma-separated run_id:pass_id pairs; default pilot-1..4's saved pass ids")
    ge = sub.add_parser("estimate-grader-replay", help="Grade a small sample with every candidate once to get a "
                                                       "real $/call, then project the full replay's cost (gpt-4o-mini)")
    ge.add_argument("--sample", type=int, default=20)
    rs = sub.add_parser("grader-review-sheet", help="Offline: 40 grader/judge disagreements for the owner to "
                                                   "adjudicate blind (no calls)")
    rs.add_argument("--replay-dir", default=str(RUNS_DIR / "grader_replay"))
    rs.add_argument("--out", default=str(RUNS_DIR / "grader_replay" / "review_sheet.csv"))
    gr = sub.add_parser("replay-graders", help="Run the full grader replay (gpt-4o-mini; run estimate-grader-replay "
                                               "first)")
    gr.add_argument("--out", default=str(RUNS_DIR / "grader_replay"))
    ar = sub.add_parser("arm-report", help="One table of every metric with a column per run (needs metrics.json in each)")
    ar.add_argument("--run", action="append", required=True, help="name=run_id, once per arm")
    ar.add_argument("--out", help="Write the table here as well")
    ka = sub.add_parser("replay-keypoints", help="Candidate (a): V3 grading tutor replies against generated "
                                                 "key points instead of the raw reference (gpt-4o-mini)")
    ka.add_argument("--out", default=str(RUNS_DIR / "grader_replay" / "keypoints"))
    kb1 = sub.add_parser("probe-bigger-model", help="Candidate (b), step 1: a small real sample on the next-larger "
                                                    "model, to project the full replay's cost before running it")
    kb1.add_argument("--sample", type=int, default=20)
    kb2 = sub.add_parser("replay-bigger-model", help="Candidate (b), step 2: the full V3 replay on the next-larger "
                                                     "model (run probe-bigger-model first)")
    kb2.add_argument("--out", default=str(RUNS_DIR / "grader_replay" / "bigger_model"))
    kc = sub.add_parser("replay-three-level", help="Candidate (c): V3 with a correct/partly_correct/incorrect "
                                                   "verdict (gpt-4o-mini)")
    kc.add_argument("--out", default=str(RUNS_DIR / "grader_replay" / "three_level"))
    fc = sub.add_parser("fit-cognitive-load", help="Fit the personal cognitive-load equation's population "
                                                   "coefficients on simulated students (no model calls)")
    fc.add_argument("--learners-per-profile", type=int, default=30)
    fc.add_argument("--turns", type=int, default=60)
    fc.add_argument("--seed", type=int, default=20260927)
    tr = sub.add_parser("transcripts", help="Readable sample transcripts with the hidden state (for the owner)")
    tr.add_argument("--run-id", required=True)
    tr.add_argument("--n", type=int, default=10)
    pr = sub.add_parser("pilot-report", help="Per learner-week costs, time, pauses and M0a-M0c")
    pr.add_argument("--run-id", required=True)
    cm = sub.add_parser("compare-models", help="Same scripted learner against LEA on OpenAI and on Claude Sonnet")
    cm.add_argument("--arms", default="openai,sonnet")
    cm.add_argument("--config", default=str(REPO_ROOT / "simulation" / "config" / "pilot.yaml"))
    cm.add_argument("--max-calls", type=int, default=250, help="Hard cap on Claude calls for the Sonnet arm")
    args = parser.parse_args(argv)
    if args.command == "check-claude":
        return check_claude(args.model, args.config)
    if args.command == "build-bank":
        return build_bank(args.dry_run, args.config)
    if args.command == "compare-models":
        return compare_models(args)
    if args.command == "judge":
        return judge(args)
    if args.command == "reanalyse":
        return reanalyse(args)
    if args.command == "calibrate":
        return calibrate_cmd(args)
    if args.command == "plan":
        return plan_cmd_run(args)
    if args.command == "compare-arms":
        from simulation import arms
        from simulation.judges import read_events
        from simulation.metrics import RunData

        def load_run(run_id):
            return RunData(read_events(RUNS_DIR / run_id / "events.jsonl"), [])

        result = arms.compare(load_run(args.a), load_run(args.b), scaffolding=args.scaffolding)
        text = arms.format_comparison(result, args.a, args.b, "scaffolding models" if args.scaffolding else "the load equation")
        out = RUNS_DIR / f"compare_{args.a}_vs_{args.b}"
        out.mkdir(parents=True, exist_ok=True)
        (out / "comparison.md").write_text(text, encoding="utf-8")
        (out / "comparison.json").write_text(json.dumps(result, indent=1, default=float), encoding="utf-8")
        print(text)
        print(f"Wrote {out / 'comparison.md'}")
        return 0
    if args.command == "build-grader-dataset":
        from simulation import grader_replay as GR

        pilots = GR.PILOTS
        if args.pilots:
            pilots = [tuple(p.split(":", 1)) for p in args.pilots.split(",")]
        rows = GR.build_dataset(pilots)
        path = GR.save_dataset(rows)
        from collections import Counter

        print(f"{len(rows)} items -> {path}")
        print(Counter((r["run"], r["qtype"]) for r in rows))
        return 0
    if args.command in ("estimate-grader-replay", "replay-graders"):
        from dotenv import load_dotenv
        from openai import OpenAI

        from simulation import grader_replay as GR

        load_dotenv(REPO_ROOT / ".env")
        client = OpenAI()
        dataset = GR.load_dataset()
        if args.command == "estimate-grader-replay":
            est = GR.estimate_cost(dataset, client, sample=args.sample)
            print(json.dumps(est, indent=2))
            return 0
        result = GR.run_replay(dataset, client, on_progress=lambda done, total: print(f"{done}/{total}", flush=True))
        scores = GR.score_all(dataset, result["results"])
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "raw_results.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
        (out / "scores.json").write_text(json.dumps({**scores, "usage": result["usage"]}, indent=1), encoding="utf-8")
        report = GR.format_report(dataset, scores, result["usage"])
        (out / "report.md").write_text(report, encoding="utf-8")
        print(report)
        print(f"Wrote {out / 'report.md'}")
        return 0
    if args.command == "grader-review-sheet":
        from simulation import grader_replay as GR

        dataset = GR.load_dataset()
        raw = json.loads((Path(args.replay_dir) / "raw_results.json").read_text(encoding="utf-8"))
        v3 = raw["results"]["V3_checkable_gate"][0]
        summary = GR.build_review_sheet(dataset, v3, Path(args.out))
        print(json.dumps(summary, indent=2))
        return 0
    if args.command == "arm-report":
        from simulation import arm_report

        runs = {kv.split("=", 1)[0]: RUNS_DIR / kv.split("=", 1)[1] for kv in args.run}
        table = arm_report.build_table(runs)
        if args.out:
            Path(args.out).write_text(table, encoding="utf-8")
        print(table)
        return 0
    if args.command in ("replay-keypoints", "probe-bigger-model", "replay-bigger-model", "replay-three-level"):
        from dotenv import load_dotenv
        from openai import OpenAI

        from simulation import grader_replay as GR

        load_dotenv(REPO_ROOT / ".env")
        client = OpenAI()
        dataset = GR.load_dataset()
        if args.command == "replay-keypoints":
            result = GR.run_keypoints_candidate(dataset, client)
            tutor_rows = [r for r in dataset if r["qtype"] == "tutor"]
            tutor_results = [[r for r, d in zip(rep, dataset) if d["qtype"] == "tutor"] for rep in result["results"]]
            scores = GR.score_candidate(tutor_rows, tutor_results)
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            (out / "raw_results.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
            (out / "scores.json").write_text(json.dumps({"scores": scores, "usage": result["usage"]}, indent=1),
                                             encoding="utf-8")
            print(json.dumps({"usage": result["usage"], "scores": scores}, indent=2, default=str))
            print(f"Wrote {out}")
            return 0
        if args.command == "probe-bigger-model":
            est = GR.probe_bigger_model_cost(dataset, client, sample=args.sample)
            print(json.dumps(est, indent=2))
            return 0
        if args.command == "replay-bigger-model":
            result = GR.run_bigger_model_candidate(dataset, client)
            scores = GR.score_candidate(dataset, result["results"])
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            (out / "raw_results.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
            (out / "scores.json").write_text(json.dumps({"scores": scores, "usage": result["usage"]}, indent=1),
                                             encoding="utf-8")
            print(json.dumps({"usage": result["usage"], "scores": scores}, indent=2, default=str))
            print(f"Wrote {out}")
            return 0
        if args.command == "replay-three-level":
            result = GR.run_three_level_candidate(dataset, client)
            scores = GR.score_three_level(dataset, result["results"])
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            (out / "raw_results.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
            (out / "scores.json").write_text(json.dumps({"scores": scores, "usage": result["usage"]}, indent=1),
                                             encoding="utf-8")
            print(json.dumps({"usage": result["usage"], "scores": scores}, indent=2, default=str))
            print(f"Wrote {out}")
            return 0
    if args.command == "fit-cognitive-load":
        from simulation import cl_calibration as CC

        pop = CC.fit(args.seed, args.learners_per_profile, args.turns)
        path = CC.write(pop)
        print(json.dumps({k: pop[k] for k in ("version", "coef", "norms", "rating_scale", "fit")}, indent=2))
        print(f"Wrote {path}")
        return 0
    if args.command == "personalize":
        from simulation import personalization as P

        cfg = P.Config(learners_per_profile=args.learners_per_profile)
        main, sens = P.study(cfg), (P.sensitivity(cfg) if args.sensitivity else None)
        out = __import__("pathlib").Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(json.dumps({"main": main, "sensitivity": sens}, indent=1, default=float),
                                          encoding="utf-8")
        (out / "report.md").write_text(P.format_report(main, sens), encoding="utf-8")
        print(P.format_report(main, sens))
        print(f"Wrote {out / 'report.md'}")
        return 0
    if args.command == "transcripts":
        from simulation.transcripts import write_transcripts

        for path in write_transcripts(RUNS_DIR / args.run_id, args.n):
            print(path)
        return 0
    if args.command == "pilot-report":
        from simulation.transcripts import pilot_report

        run_dir = RUNS_DIR / args.run_id
        metrics_file = run_dir / "metrics.json"
        if not metrics_file.exists():
            print("Run reanalyse first.")
            return 1
        rows = [r for r in UsageLedger(LEDGER).records() if r.get("run_id") == args.run_id]
        text = pilot_report(run_dir, rows, json.loads(metrics_file.read_text(encoding="utf-8")))
        (run_dir / "pilot_report.md").write_text(text, encoding="utf-8")
        print(f"Wrote {run_dir / 'pilot_report.md'}")
        return 0
    if args.command == "run":
        from dotenv import load_dotenv

        from simulation.harness import new_run_id, run

        load_dotenv(REPO_ROOT / ".env")  # OPENAI_API_KEY for LEA; REDIS_URL is replaced inside the run
        if args.resume and not args.run_id:
            parser.error("--resume needs --run-id")
        try:
            result = run(args.config, args.run_id or new_run_id("run"), resume=args.resume,
                         trace=(lambda m: print(m, flush=True)) if args.verbose else None)
        except (ClaudeStop, ConfigError) as e:
            print(f"Not started: {e}")
            return 2
        print(f"{result['status']}: {len(result['done'])} learner-weeks; {result['dir']}")
        return 0 if result["status"] == "completed" else 2
    return 1
