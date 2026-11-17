"""Staying inside the Claude subscription (docs/simulation/PLAN.md, section 6).

Every Claude call the simulation makes goes through ``ClaudeCLI``, which asks this guard
before and after each call:

1. **Account setting.** A run doesn't start unless the owner has confirmed usage credits
   are off (``usage_credits_confirmed_off: true``), and, until calibration exists, only a
   pilot may start.
2. **Anthropic's signals.** ``rate_limit_event`` lines are logged; ``isUsingOverage: true``
   stops the run at once; ``status: rejected`` pauses until ``resetsAt`` + 2 minutes;
   ``allowed_warning`` at or above the pause threshold pauses until ``resetsAt``, and so
   does any window in ``unifiedWindows`` (per-window utilization, reported on every event)
   that reaches its threshold.
   Missing fields are unknown, never safe. An error mentioning a spend limit, credits or
   billing stops the run.
3. **Our own budgets.** Rolling 5-hour and 7-day API-equivalent spend (from each call's
   ``total_cost_usd``, kept in a ledger shared by all runs), a per-run call cap, and
   optional run hours.

``ClaudeStop`` ends the run (checkpoint and tell the owner); ``ClaudePause`` means wait
until ``until`` and resume.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

FIVE_HOURS = timedelta(hours=5)
SEVEN_DAYS = timedelta(days=7)
REJECT_MARGIN = timedelta(minutes=2)
UNKNOWN_RESET = timedelta(hours=1)  # when a pause signal comes without resetsAt
BILLING_WORDS = re.compile(r"spend(ing)? limit|usage credit|credit balance|credits|billing|overage|extra usage",
                           re.IGNORECASE)


class ClaudeStop(RuntimeError):
    """Stop the whole run now (checkpoint and tell the owner)."""


class ClaudePause(RuntimeError):
    """Wait until ``until`` (UTC), then resume."""

    def __init__(self, until: datetime, reason: str):
        super().__init__(f"{reason}; paused until {until.isoformat(timespec='seconds')}")
        self.until = until
        self.reason = reason


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_hours(spec: str) -> tuple[time, time]:
    start, end = spec.split("-")
    return time.fromisoformat(start), time.fromisoformat(end)


class UsageLedger:
    """Append-only JSONL of every Claude call (all runs), for rolling budgets."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, record: Dict[str, Any]) -> None:
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def records(self):
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn last line after a crash
        return out

    def spent_since(self, since: datetime) -> float:
        return sum(float(r.get("cost_usd") or 0) for r in self.records()
                   if datetime.fromisoformat(r["ts"]) >= since)

    def calls(self, run_id: str) -> int:
        return sum(1 for r in self.records() if r.get("run_id") == run_id)


@dataclass
class GuardSettings:
    per_5h_budget: Optional[float]
    per_week_budget: Optional[float]
    pause_at_5h: float
    pause_at_week: float
    run_hours: Optional[str]
    max_calls_per_run: int

    @classmethod
    def from_config(cls, claude: Dict[str, Any]) -> "GuardSettings":
        return cls(per_5h_budget=claude.get("per_5h_budget"), per_week_budget=claude.get("per_week_budget"),
                   pause_at_5h=float(claude["pause_at_5h"]), pause_at_week=float(claude["pause_at_week"]),
                   run_hours=claude.get("run_hours"), max_calls_per_run=int(claude["max_calls_per_run"]))


def preflight(config: Dict[str, Any], allowance_path: Path) -> None:
    """Refuse to start a run the owner hasn't cleared (layer 1 and the calibration rule)."""
    if config.get("usage_credits_confirmed_off") is not True:
        raise ClaudeStop("Usage credits haven't been confirmed off. Check Claude's usage settings (or "
                         "/usage-credits in Claude Code), then set usage_credits_confirmed_off: true.")
    if not config.get("pilot") and not Path(allowance_path).exists():
        raise ClaudeStop("There is no allowance calibration yet (simulation/config/allowance.yaml): only a "
                         "pilot may run until the pilot has calibrated it.")
    claude = config["claude"]
    if not config.get("pilot") and (claude.get("per_5h_budget") is None or claude.get("per_week_budget") is None):
        raise ClaudeStop("claude.per_5h_budget and claude.per_week_budget must be set (from calibration) "
                         "for any run other than the pilot.")


class UsageGuard:
    def __init__(self, settings: GuardSettings, ledger: UsageLedger, run_id: str,
                 events_path: Optional[Path] = None, clock: Callable[[], datetime] = utcnow):
        self.settings = settings
        self.ledger = ledger
        self.run_id = run_id
        self.events_path = Path(events_path) if events_path else None
        self.clock = clock
        self.paused_until: Optional[datetime] = None
        self.stopped: Optional[str] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ before a call
    def before_call(self) -> None:
        now = self.clock()
        with self._lock:
            if self.stopped:
                raise ClaudeStop(self.stopped)
            if self.paused_until and now < self.paused_until:
                raise ClaudePause(self.paused_until, "Paused by an earlier usage signal")
        s = self.settings
        if self.ledger.calls(self.run_id) >= s.max_calls_per_run:
            self._stop(f"Reached claude.max_calls_per_run ({s.max_calls_per_run}) for this run")
        if s.run_hours:
            opens = self._next_opening(now)
            if opens is not None:
                raise ClaudePause(opens, f"Outside claude.run_hours ({s.run_hours})")
        for budget, window, name in ((s.per_5h_budget, FIVE_HOURS, "per_5h_budget"),
                                     (s.per_week_budget, SEVEN_DAYS, "per_week_budget")):
            if budget is None:
                continue
            spent = self.ledger.spent_since(now - window)
            if spent >= float(budget):
                raise self._pause(self._budget_frees(now, window, float(budget)),
                                  f"claude.{name} reached (${spent:.2f} of ${float(budget):.2f} API-equivalent)")

    def _next_opening(self, now: datetime) -> Optional[datetime]:
        """None if now is inside run_hours, else when the window next opens (UTC)."""
        start, end = _parse_hours(self.settings.run_hours)
        local = now.astimezone()
        t = local.time()
        inside = (start <= t < end) if start < end else (t >= start or t < end)
        if inside:
            return None
        opening = local.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        if opening <= local:
            opening += timedelta(days=1)
        return opening.astimezone(timezone.utc)

    def _budget_frees(self, now: datetime, window: timedelta, budget: float) -> datetime:
        """When enough of the window's spend ages out to go below the budget."""
        rows = sorted((datetime.fromisoformat(r["ts"]), float(r.get("cost_usd") or 0))
                      for r in self.ledger.records() if datetime.fromisoformat(r["ts"]) >= now - window)
        spent = sum(c for _, c in rows)
        for ts, cost in rows:
            spent -= cost
            if spent < budget:
                return ts + window + timedelta(seconds=1)
        return now + window

    # ------------------------------------------------------------ during and after a call
    def on_rate_limit(self, info: Dict[str, Any]) -> None:
        """Handle one ``rate_limit_info`` object. Raises to stop or pause."""
        self._log({"kind": "rate_limit_event", "info": info})
        if not isinstance(info, dict):
            return
        if info.get("isUsingOverage") is True:
            self._stop("Claude reports usage credits (overage) in use (isUsingOverage: true). "
                       "The run stopped; nothing more will be sent until you restart it.")
        status = info.get("status")
        resets = self._resets_at(info)
        if status == "rejected":
            raise self._pause((resets or self.clock() + UNKNOWN_RESET) + REJECT_MARGIN,
                              f"Claude usage limit reached ({info.get('rateLimitType', 'unknown window')})")
        # Claude Code 2.1.x also reports every window's utilization on each event
        # ("unifiedWindows"); pause as soon as any window reaches its threshold.
        windows = info.get("unifiedWindows")
        if isinstance(windows, dict):
            for window, data in windows.items():
                if not isinstance(data, dict):
                    continue
                utilization = data.get("utilization")
                threshold = self._threshold(window)
                if isinstance(utilization, (int, float)) and float(utilization) >= threshold:
                    until = self._resets_at(data) or self.clock() + UNKNOWN_RESET
                    raise self._pause(until, f"Claude {window} usage at {float(utilization):.2f} "
                                             f"(pause threshold {threshold:.2f})")
        if status == "allowed_warning":
            threshold = self._threshold(info.get("rateLimitType"))
            utilization = info.get("utilization")
            # Missing utilization is unknown, not safe: treat the warning as reaching the threshold.
            if not isinstance(utilization, (int, float)) or float(utilization) >= threshold:
                raise self._pause(resets or self.clock() + UNKNOWN_RESET,
                                  f"Claude usage at {utilization if utilization is not None else 'an unknown level'} "
                                  f"of the {info.get('rateLimitType', 'unknown')} limit "
                                  f"(pause threshold {threshold:.2f})")

    def on_error_text(self, text: str) -> None:
        if text and BILLING_WORDS.search(text):
            self._stop("Claude returned an error about spend limits, credits or billing; the run stopped.")

    def _threshold(self, window: Optional[str]) -> float:
        if window == "five_hour":
            return self.settings.pause_at_5h
        if window and window.startswith("seven_day"):
            return self.settings.pause_at_week
        return min(self.settings.pause_at_5h, self.settings.pause_at_week)  # unknown: the stricter

    def _resets_at(self, info: Dict[str, Any]) -> Optional[datetime]:
        value = info.get("resetsAt")
        if isinstance(value, (int, float)) and value > 0:
            return datetime.fromtimestamp(float(value), timezone.utc)
        return None

    def _pause(self, until: datetime, reason: str) -> ClaudePause:
        with self._lock:
            self.paused_until = max(until, self.paused_until or until)
        self._log({"kind": "pause", "until": until.isoformat(), "reason": reason})
        return ClaudePause(until, reason)

    def _stop(self, reason: str) -> None:
        with self._lock:
            self.stopped = reason
        self._log({"kind": "stop", "reason": reason})
        raise ClaudeStop(reason)

    def _log(self, record: Dict[str, Any]) -> None:
        if self.events_path is None:
            return
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": self.clock().isoformat(), "run_id": self.run_id, **record}) + "\n")


def run_with_pauses(fn: Callable[[], Any], sleep: Callable[[float], None], clock: Callable[[], datetime] = utcnow,
                    max_pauses: int = 1000):
    """Call ``fn``; on ``ClaudePause`` wait until the pause ends and call it again.
    ``ClaudeStop`` propagates. The harness wraps each learner-week in this after a checkpoint."""
    for _ in range(max_pauses):
        try:
            return fn()
        except ClaudePause as pause:
            wait = (pause.until - clock()).total_seconds()
            if wait > 0:
                sleep(wait)
    raise ClaudeStop("Too many pauses in a row; stopping so the owner can look.")
