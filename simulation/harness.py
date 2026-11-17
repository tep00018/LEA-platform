"""Running a simulation: a queue of learner-weeks, checkpointed (docs/simulation/PLAN.md).

``run()``:

1. checks the researcher's approvals (``preflight``: usage credits confirmed off; before
   calibration, only a pilot);
2. enters the ``RunContext`` (a copy of AIML101, fakeredis only, no writes under data/);
3. builds LEA's services exactly as the API does (LEA keeps its own OpenAI client);
4. drives each learner week by week (``LearnerRunner``), checkpointing after every
   learner-week: LEA's Redis state, every learner's hidden state and random streams, and
   the lengths of the run's logs, so ``--resume`` continues exactly where the last
   finished learner-week left off (a half-done week is discarded and redone);
5. waits in place when Claude reports a usage limit (the conversation with LEA stays
   open), and stops cleanly on ``ClaudeStop`` (for example overage) or when LEA's OpenAI
   spend reaches the run budget.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from simulation import CONFIG_DIR, PACKAGE_DIR, RUNS_DIR
from simulation.capture import BudgetExceeded, spies
from simulation.drivers import EventWriter, LearnerRunner
from simulation.isolation import RunContext
from simulation.learner import build_profiles, go_difficulties, make_learner
from simulation.llm.claude_cli import ClaudeCLI
from simulation.llm.usage_guard import (ClaudePause, ClaudeStop, GuardSettings, UsageGuard, UsageLedger, preflight,
                                        utcnow)
from simulation.manifest import Manifest
from simulation.settings import load
from simulation.student import StudentLLM

ALLOWANCE = CONFIG_DIR / "allowance.yaml"
LEDGER = RUNS_DIR / "usage_ledger.jsonl"


class PausingClient:
    """Wraps the Claude client: on a usage pause, wait until it ends and try again."""

    def __init__(self, client, sleep: Callable[[float], None] = time.sleep, clock=utcnow, on_pause=None):
        self.client, self.sleep, self.clock, self.on_pause = client, sleep, clock, on_pause

    def call(self, *args, **kwargs):
        while True:
            try:
                return self.client.call(*args, **kwargs)
            except ClaudePause as pause:
                if self.on_pause:
                    self.on_pause(pause)
                wait = (pause.until - self.clock()).total_seconds()
                if wait > 0:
                    self.sleep(wait)


def load_bank(course: str, path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    path = path or PACKAGE_DIR / "assets" / course / "question_bank.json"
    if not Path(path).exists():
        raise FileNotFoundError(f"No question bank at {path}; build it first (python -m simulation build-bank).")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {e["go_id"]: e for e in data["entries"]}


def openai_budget(config: Dict[str, Any]) -> float:
    return float(os.getenv("LEA_SIM_OPENAI_BUDGET_USD") or config["openai"]["budget_usd"])


class Checkpoint:
    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self.path = ctx.dir / "checkpoint.json"

    def exists(self) -> bool:
        return self.path.exists()

    def logs(self) -> Dict[str, int]:
        """Current sizes of everything the run appends to."""
        sizes = {}
        for path in [self.ctx.dir / "events.jsonl", *self.ctx.data_dir.rglob("*.csv")]:
            if path.exists():
                sizes[str(path.relative_to(self.ctx.dir))] = path.stat().st_size
        return sizes

    def save(self, done: List[str], learners, event_log) -> None:
        max_id = event_log.query("id = (SELECT MAX(id) FROM events)") if event_log is not None else []
        data = {"saved_at": utcnow().isoformat(), "done": done,
                "learners": {lr.username: lr.state() for lr in learners},
                "redis": self.ctx.dump_redis(), "logs": self.logs(),
                "event_log_max_id": int(max_id[0]["id"]) if max_id else 0}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(self.path)

    def restore(self, learners, event_log) -> List[str]:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.ctx.restore_redis(data["redis"])
        for lr in learners:
            if lr.username in data["learners"]:
                lr.load_state(data["learners"][lr.username])
        # Drop anything a half-finished learner-week appended after the checkpoint.
        for rel, size in data["logs"].items():
            path = self.ctx.dir / rel
            if path.exists() and path.stat().st_size > size:
                with open(path, "r+b") as f:
                    f.truncate(size)
        for path in [self.ctx.dir / "events.jsonl", *self.ctx.data_dir.rglob("*.csv")]:
            if str(path.relative_to(self.ctx.dir)) not in data["logs"] and path.exists():
                path.unlink()
        if event_log is not None:
            with event_log._lock:
                event_log._conn.execute("DELETE FROM events WHERE id > ?", (data["event_log_max_id"],))
                event_log._conn.commit()
        return list(data["done"])


def check_fits(config: Dict[str, Any]) -> Dict[str, Any]:
    """Refuse a non-pilot run that doesn't fit the researcher's limits (claude.max_days_per_run)."""
    import yaml

    from simulation.sizing import pilot_rates, plan

    if not config.get("sizing_from"):
        raise ClaudeStop("Set sizing_from to the pilot run that sizes this run (see python -m simulation plan).")
    allowance = yaml.safe_load(ALLOWANCE.read_text(encoding="utf-8"))
    rates = pilot_rates(RUNS_DIR / config["sizing_from"], UsageLedger(LEDGER))
    result = plan(config, rates, allowance)
    if not result["proposed"]["fits"]:
        raise ClaudeStop(f"This run needs {result['proposed']['days']} days of the allowed share; "
                         f"claude.max_days_per_run is {config['claude']['max_days_per_run']}. "
                         "Change the config (python -m simulation plan lists options).")
    return result


def run(config_path: Optional[str], run_id: str, *, resume: bool = False, services_factory=None,
        claude_client=None, sleep: Callable[[float], None] = time.sleep, runs_dir: Path = RUNS_DIR,
        bank_path: Optional[Path] = None, log: Callable[[str], None] = print,
        skip_preflight: bool = False, trace: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """``skip_preflight`` is only for runs whose student is an injected stand-in (no Claude
    at all): it is refused with the real Claude client."""
    config = load(config_path)
    if skip_preflight and (claude_client is None or isinstance(claude_client, ClaudeCLI)):
        raise ClaudeStop("skip_preflight is only allowed without Claude (an injected stand-in student).")
    if not skip_preflight:
        preflight(config, ALLOWANCE)
        if not config.get("pilot"):
            check_fits(config)
    course = config["course"]
    ctx = RunContext(run_id, course, runs_dir=runs_dir,
                     extra_env={"LEA_COGNITIVE_LOAD_MODEL": str((config.get("lea") or {}).get("cognitive_load_model", "fixed")),
                         "LEA_SCAFFOLDING_MODEL": str((config.get("lea") or {}).get("scaffolding_model", "current")),
                         "LEA_MOTIVATION_SUPPORT": str((config.get("lea") or {}).get("motivation_support", "off")),
                         "LEA_MOTIVATION_CLASSIFIER": str((config.get("lea") or {}).get("motivation_classifier", "current")),
                         "LEA_TUTOR_RECORDED_QUESTION": str((config.get("lea") or {}).get("tutor_recorded_question", "off")),
                         "LEA_TUTOR_TEMPERATURE": str((config.get("lea") or {}).get("tutor_temperature", 0.7))})
    if ctx.dir.exists() and (ctx.dir / "manifest.json").exists() and not resume:
        raise FileExistsError(f"Run {run_id} exists; use --resume to continue it or pick a new id.")
    bank = load_bank(course, bank_path)
    status = "completed"
    with ctx:
        manifest = Manifest.start(ctx.dir, run_id, config, ctx.data_dir, course)
        manifest.data["external_services"] = {
            "youtube_api": "disabled: no external calls; LEA falls back to search links (as in its tests)"}
        manifest.save()
        if services_factory is None:
            from src.services.container import build_services

            services = build_services(ctx.redis_url)
        else:
            services = services_factory(ctx)
        from src.core.course_registry import default_registry
        from src.onboarding import kc_model as K

        model = default_registry().kc_model(course)  # the run's copy (LEA_DATA_DIR)

        gos = K.gos_of(model)
        thresholds = {g: float(v.get("mastery_threshold") or 0.7) for g, v in gos.items()}
        difficulties = go_difficulties(list(gos.values()), config["learner"], int(config["seed"]))
        manifest.data["go_difficulty"] = difficulties
        manifest.data["profiles"] = {k: {**vars(p), "state_rates": p.state_rates}
                                     for k, p in build_profiles(config).items()}
        manifest.save()

        scale = config["scale"]
        keys = scale.get("profiles") or list(config["profiles"])
        learners = [make_learner(config, key, i, difficulties)
                    for key in keys for i in range(int(scale["learners_per_profile"]))]
        weeks = [int(w) for w in scale["weeks"]]

        if claude_client is None:
            settings = GuardSettings.from_config(config["claude"])
            guard = UsageGuard(settings, UsageLedger(LEDGER), run_id, events_path=ctx.dir / "usage_events.jsonl")
            claude_client = ClaudeCLI(guard, guard.ledger, ctx.claude_cwd, executable=config["claude"]["executable"],
                                      concurrency=int(config["claude"]["concurrency"]),
                                      timeout_seconds=int(config["claude"]["timeout_seconds"]))
        pauses: List[Dict[str, Any]] = []
        client = PausingClient(claude_client, sleep=sleep,
                               on_pause=lambda p: (pauses.append({"until": p.until.isoformat(), "reason": p.reason}),
                                                   log(f"Paused: {p}")))
        student = StudentLLM(client, model=config["claude"]["student_model"], effort=config["claude"]["student_effort"],
                             max_thinking_tokens=config["claude"]["student_max_thinking_tokens"])
        writer = EventWriter(ctx.dir / "events.jsonl")
        checkpoint = Checkpoint(ctx)
        done: List[str] = checkpoint.restore(learners, services.events.log) if resume and checkpoint.exists() else []
        started = time.monotonic()
        prior_openai = dict(manifest.data.get("openai") or {})
        meters: List[Any] = []
        try:
            with spies(services, openai_budget(config)) as (meter, spy):
                meters.append(meter)
                for learner in learners:
                    runner = LearnerRunner(services=services, learner=learner, bank=bank, student=student,
                                           meter=meter, spy=spy, writer=writer, config=config, course=course,
                                           run_id=run_id, thresholds=thresholds, trace=trace)
                    if not services.redis_client.get_redis().exists(f"user:{learner.username}"):
                        runner.create_account()
                    for week in weeks:
                        key = f"{learner.username}:{week}"
                        if key in done:
                            continue
                        meter.check_budget()
                        t0 = time.monotonic()
                        summary = runner.run_week(week)
                        done.append(key)
                        writer.write({"kind": "learner_week", "run_id": run_id, "learner": learner.username,
                                      "week": week, "seconds": round(time.monotonic() - t0, 1),
                                      "stuck": summary["stuck"]})
                        checkpoint.save(done, learners, services.events.log)  # after the line, so a resume keeps it
                        log(f"{key} done ({len(done)}/{len(learners) * len(weeks)}); OpenAI ${meter.usd:.3f}")
        except (ClaudeStop, BudgetExceeded) as e:
            status = f"stopped: {e}"
            log(f"Stopped: {e}")
        finally:
            # Recorded however the run ended (a stop used to leave the OpenAI cost out of the
            # manifest); a resumed run adds to what earlier sessions used.
            if meters:
                m = meters[0]
                models = dict(prior_openai.get("models") or {})
                for name, n in m.models().items():
                    models[name] = models.get(name, 0) + n
                manifest.data["openai"] = {
                    "models": models, "usd": round(float(prior_openai.get("usd") or 0) + m.usd, 6),
                    "tokens": int(prior_openai.get("tokens") or 0) + sum(c["input_tokens"] + c["output_tokens"]
                                                                          for c in m.calls),
                    "unpriced_models": sorted(set(prior_openai.get("unpriced_models") or []) |
                                              {c["model"] for c in m.calls if not c["priced"]})}
        claude_rows = [r for r in UsageLedger(LEDGER).records() if r.get("run_id") == run_id]
        manifest.data["claude"].update({
            "calls": len(claude_rows), "api_equivalent_usd": round(sum(r.get("cost_usd") or 0 for r in claude_rows), 6),
            "models": sorted({r["model"] for r in claude_rows if r.get("model")}),
            "code_version": next((r.get("claude_code_version") for r in claude_rows if r.get("claude_code_version")),
                                 None)})
        manifest.data.update({"status": status, "learner_weeks_done": len(done), "pauses": pauses,
                              "wall_seconds_this_session": round(time.monotonic() - started, 1)})
        manifest.finish()
    return {"status": status, "done": done, "dir": str(ctx.dir)}


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
