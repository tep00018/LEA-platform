"""Background onboarding jobs, run in-process like the memory-consolidation worker.

A job is created with a cost estimate and waits for the teacher to confirm it; only then is
it queued (Redis list ``jobs:queue``) for the worker thread the API starts
(``Services.start_background_work(jobs=True)``; Streamlit never runs jobs). One job per course at a time (``course:{code}:job``),
counting a job that awaits confirmation. A job can be cancelled at any point: a waiting or
queued job at once, a running one at the next file or step.

State: the hash ``job:{id}`` (status, step, percent, estimate, result, error) and the list
``job:{id}:log`` (the last 500 lines). A job left running when LEA stopped is marked
failed at the next start.
"""

from __future__ import annotations

import io
import json
import logging
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.onboarding.pipeline import STEP_LABELS, STEPS, Cancelled, JobContext, Pipeline, estimate
from src.services.errors import Busy, InvalidInput, NotFound, WrongState
from src.services.events import EventRecorder, disabled

logger = logging.getLogger(__name__)

QUEUE = "jobs:queue"
LOG_LINES = 500
POLL_SECONDS = 2
STATUSES = ("awaiting_confirmation", "queued", "running", "succeeded", "failed", "cancelled")
FINISHED = ("succeeded", "failed", "cancelled")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _ThreadStdout(io.TextIOBase):
    """Routes print() from a job's thread into its log (data_foundation code prints its
    progress); every other thread keeps the real stdout."""

    def __init__(self, original):
        self.original = original
        self.sinks: Dict[int, Any] = {}

    def write(self, text: str) -> int:
        sink = self.sinks.get(threading.get_ident())
        if sink is None:
            return self.original.write(text)
        sink(text)
        return len(text)

    def flush(self) -> None:
        self.original.flush()


class JobService:
    def __init__(self, redis_client, setup, pipeline: Optional[Pipeline] = None,
                 events: Optional[EventRecorder] = None):
        self.redis_client = redis_client
        self.setup = setup
        self.pipeline = pipeline or Pipeline()
        self.events = events or disabled()
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        setup.busy_check = self.busy

    @property
    def conn(self):
        return self.redis_client.get_redis()

    # ------------------------------------------------------------------ reads

    def get(self, job_id: str, log_lines: int = 200) -> Dict[str, Any]:
        raw = self.conn.hgetall(f"job:{job_id}")
        if not raw:
            raise NotFound("No such job.")
        job = {k: raw.get(k) for k in ("id", "course", "status", "step", "created_by", "created_at",
                                        "started_at", "finished_at", "error")}
        job["percent"] = float(raw.get("percent", 0))
        job["steps"] = json.loads(raw.get("steps", "[]"))
        job["estimate"] = json.loads(raw.get("estimate", "{}"))
        job["result"] = json.loads(raw.get("result", "{}"))
        job["step_label"] = STEP_LABELS.get(job["step"] or "", "")
        job["log"] = self.conn.lrange(f"job:{job_id}:log", -log_lines, -1) if log_lines else []
        return job

    def for_course(self, code: str, limit: int = 20) -> List[Dict[str, Any]]:
        ids = self.conn.lrange(f"course:{code}:jobs", 0, limit - 1)
        return [self.get(i, log_lines=0) for i in ids if self.conn.exists(f"job:{i}")]

    def active(self, code: str) -> Optional[str]:
        return self.conn.get(f"course:{code}:job")

    def busy(self, code: str) -> bool:
        """A queued or running job is using the course's files (a job awaiting confirmation isn't)."""
        job_id = self.active(code)
        return bool(job_id) and self.conn.hget(f"job:{job_id}", "status") in ("queued", "running")

    # ------------------------------------------------------------------ teacher actions

    def create(self, actor: str, code: str, steps: Optional[List[str]] = None) -> Dict[str, Any]:
        meta = self.setup.require_managed(code)
        unknown = set(steps or []) - set(STEPS)
        steps = [s for s in STEPS if s in (steps or STEPS)]
        if not steps or unknown:
            raise InvalidInput(f"Steps are: {', '.join(STEPS)}.")
        self.setup.sync_materials_source(actor, code)  # no-op without a linked source
        uploads = self.setup.uploads(code)
        if not uploads and any(s in steps for s in ("convert", "transcribe", "embed")):
            raise InvalidInput("Upload some course materials first.")
        plan = self.setup.plan(code)
        if "kc_draft" in steps and not plan:
            raise InvalidInput("Add the weekly learning objectives first: the KC model is drafted from them.")
        job_id = uuid.uuid4().hex[:12]
        if not self.conn.set(f"course:{code}:job", job_id, nx=True):
            raise Busy("This course already has a job. Wait for it to finish, or cancel it.")
        ctx = self._context(job_id, code, meta)
        cost = estimate(ctx, steps)
        self.conn.hset(f"job:{job_id}", mapping={
            "id": job_id, "course": code, "status": "awaiting_confirmation", "step": "", "percent": 0,
            "steps": json.dumps(steps), "estimate": json.dumps(cost), "result": "{}",
            "created_by": actor, "created_at": _now(), "started_at": "", "finished_at": "", "error": "",
        })
        self.conn.lpush(f"course:{code}:jobs", job_id)
        self.conn.ltrim(f"course:{code}:jobs", 0, 49)
        self._log(job_id, f"Estimated OpenAI cost: ${cost['usd']:.2f}. Waiting for confirmation.")
        self.events.staff(actor, "job_create", course=code, payload={"job": job_id, "steps": steps, "usd": cost["usd"]})
        return self.get(job_id)

    def confirm(self, actor: str, job_id: str) -> Dict[str, Any]:
        job = self.get(job_id, log_lines=0)
        if job["status"] != "awaiting_confirmation":
            raise WrongState("This job isn't waiting for confirmation.")
        self.conn.hset(f"job:{job_id}", "status", "queued")
        self.conn.lpush(QUEUE, job_id)
        self._log(job_id, f"Confirmed by {actor}; queued.")
        self.events.staff(actor, "job_confirm", course=job["course"], payload={"job": job_id})
        return self.get(job_id)

    def cancel(self, actor: str, job_id: str) -> Dict[str, Any]:
        job = self.get(job_id, log_lines=0)
        if job["status"] in FINISHED:
            raise WrongState("This job has already finished.")
        if job["status"] == "running":
            self.conn.hset(f"job:{job_id}", "cancel_requested", "1")
            self._log(job_id, f"Cancel requested by {actor}; stopping after the current file.")
        else:
            self._finish(job_id, job["course"], "cancelled")
            self._log(job_id, f"Cancelled by {actor}.")
        self.events.staff(actor, "job_cancel", course=job["course"], payload={"job": job_id})
        return self.get(job_id)

    # ------------------------------------------------------------------ worker

    def run_next(self) -> bool:
        """Run one queued job; False if there was none. The worker thread polls this (a
        blocking pop would outlast the Redis client's 5-second socket timeout)."""
        job_id = self.conn.rpop(QUEUE)
        if not job_id:
            return False
        if self.conn.hget(f"job:{job_id}", "status") != "queued":
            return True  # cancelled while queued
        self._run(job_id)
        return True

    def _run(self, job_id: str) -> None:
        job = self.get(job_id, log_lines=0)
        code = job["course"]
        self.conn.hset(f"job:{job_id}", mapping={"status": "running", "started_at": _now()})
        meta = self.setup.meta(code) or {}
        ctx = self._context(job_id, code, meta)
        steps = job["steps"]

        def progress(step: str, fraction: float) -> None:
            done = steps.index(step) if step in steps else 0
            percent = round(100 * (done + max(0.0, min(1.0, fraction))) / len(steps), 1)
            self.conn.hset(f"job:{job_id}", mapping={"step": step, "percent": percent})

        ctx.progress = progress
        ctx.log = lambda line: self._log(job_id, line)
        ctx.is_cancelled = lambda: self.conn.hget(f"job:{job_id}", "cancel_requested") == "1"
        stdout = self._capture_stdout(job_id)
        try:
            result = self.pipeline.run(ctx, steps)
            self.conn.hset(f"job:{job_id}", mapping={"result": json.dumps(result), "percent": 100})
            self._finish(job_id, code, "succeeded")
            self._log(job_id, "Done.")
        except Cancelled:
            self.conn.hset(f"job:{job_id}", "result", json.dumps(ctx.result))
            self._finish(job_id, code, "cancelled")
            self._log(job_id, "Cancelled. Files already processed stay processed.")
        except Exception as e:
            logger.exception(f"Onboarding job {job_id} for {code} failed")
            self.conn.hset(f"job:{job_id}", mapping={"result": json.dumps(ctx.result), "error": str(e)[:500]})
            self._finish(job_id, code, "failed")
            self._log(job_id, f"Failed: {e}")
        finally:
            stdout.sinks.pop(threading.get_ident(), None)
            self.setup.registry.forget(code)
        self.events.staff("system", "job_finished", course=code,
                          payload={"job": job_id, "status": self.conn.hget(f"job:{job_id}", "status")})

    def recover(self) -> None:
        """Jobs left running by a stopped LEA are marked failed (their course is freed)."""
        for key in self.conn.scan_iter(match="job:*", count=500):
            if key.endswith(":log"):
                continue
            if self.conn.hget(key, "status") == "running":
                job_id = key.split(":", 1)[1]
                self.conn.hset(key, "error", "LEA stopped while the job was running. Start it again.")
                self._finish(job_id, self.conn.hget(key, "course"), "failed")

    def start_worker(self) -> None:
        if self._worker is not None:
            return
        self.recover()

        def loop():
            while not self._stop.is_set():
                try:
                    if not self.run_next():
                        self._stop.wait(POLL_SECONDS)
                except Exception as e:  # never let the worker die
                    logger.error(f"Job worker error: {e}")
                    time.sleep(5)

        self._worker = threading.Thread(target=loop, name="lea-onboarding-jobs", daemon=True)
        self._worker.start()

    # ------------------------------------------------------------------ helpers

    def _context(self, job_id: str, code: str, meta: Dict[str, Any]) -> JobContext:
        return JobContext(job_id=job_id, course=code, data_dir=self.setup.registry.data_dir, meta=meta,
                          uploads=self.setup.uploads(code), plan=self.setup.plan(code))

    def _finish(self, job_id: str, code: str, status: str) -> None:
        self.conn.hset(f"job:{job_id}", mapping={"status": status, "finished_at": _now()})
        if code and self.conn.get(f"course:{code}:job") == job_id:
            self.conn.delete(f"course:{code}:job")

    def _log(self, job_id: str, text: str) -> None:
        lines = [ln.rstrip() for ln in str(text).splitlines() if ln.strip()]
        if lines:
            stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            self.conn.rpush(f"job:{job_id}:log", *[f"{stamp} {ln[:1000]}" for ln in lines])
            self.conn.ltrim(f"job:{job_id}:log", -LOG_LINES, -1)

    def _capture_stdout(self, job_id: str) -> _ThreadStdout:
        if not isinstance(sys.stdout, _ThreadStdout):
            sys.stdout = _ThreadStdout(sys.stdout)
        sys.stdout.sinks[threading.get_ident()] = lambda text: self._log(job_id, text)
        return sys.stdout
