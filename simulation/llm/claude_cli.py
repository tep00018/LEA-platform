"""Claude through the researcher's subscription: ``claude -p`` in a subprocess.

The only supported way to use a Claude subscription from code (docs/simulation/PLAN.md,
section 6). Rules this client enforces:

- **Never an API key.** The subprocess environment is built from an allowlist of OS
  essentials; every ``ANTHROPIC_*`` and ``CLAUDE*`` variable is dropped (API keys, auth
  tokens, OAuth tokens, base URLs, and a host app's session variables), so ``claude``
  uses its own stored subscription login. The ``system/init`` event of every call must
  report ``apiKeySource: "none"``; anything else stops the run. There is no fallback.
- **A clean, cheap call.** ``--safe-mode`` (no CLAUDE.md, skills, plugins, hooks, MCP
  servers, custom agents), ``--strict-mcp-config``, ``--tools ""`` (no tools),
  ``--system-prompt-file`` (the role prompt replaces Claude Code's own), no session
  persistence, stream-json output, run from an empty working directory. Never ``--bare``,
  which ignores the subscription login.
- **Metered and guarded.** Every call is checked by ``UsageGuard`` before it starts, its
  ``rate_limit_event`` lines are handled as they arrive, and its model ID, tokens and
  ``total_cost_usd`` (an API-equivalent estimate, not a bill) go to the shared ledger.
- Prompts go through stdin and a temp file, never the command line.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from simulation.llm.usage_guard import ClaudeStop, UsageGuard, UsageLedger

# OS essentials a subprocess needs on Windows and elsewhere; nothing Anthropic-specific.
SAFE_ENV = {
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "HOME", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)",
    "COMPUTERNAME", "USERNAME", "USERDOMAIN", "LOGONSERVER", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    "OS", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "USER", "LOGNAME", "SHELL", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
    "XDG_CACHE_HOME", "XDG_RUNTIME_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy",
    "no_proxy", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
}
BLOCKED_PREFIXES = ("ANTHROPIC", "CLAUDE")
SUBSCRIPTION_KEY_SOURCES = {"none"}  # the init event's apiKeySource under a subscription login


def subprocess_env(environ: Optional[Mapping[str, str]] = None,
                   max_thinking_tokens: Optional[int] = None) -> Dict[str, str]:
    """The environment for ``claude``: OS essentials only, never Anthropic credentials.

    ``max_thinking_tokens`` (0 turns extended thinking off) is passed as the one extra
    variable Claude Code reads for it. In the pilot, ``--effort low`` alone left Haiku
    reasoning for about 2,250 output tokens to write a 30-token reply: 10x the cost and time.
    """
    environ = os.environ if environ is None else environ
    env = {k: v for k, v in environ.items()
           if k.upper() in {s.upper() for s in SAFE_ENV} and not k.upper().startswith(BLOCKED_PREFIXES)}
    if max_thinking_tokens is not None:
        env["MAX_THINKING_TOKENS"] = str(int(max_thinking_tokens))
    return env


def find_executable(configured: Optional[str | Sequence[str]] = None) -> List[str]:
    if configured:
        return [configured] if isinstance(configured, str) else list(configured)
    found = shutil.which("claude")  # claude.exe, or claude.cmd from npm on Windows
    if not found:
        raise ClaudeStop("Can't find the claude command. Install Claude Code and sign in with your subscription.")
    return [found]


class ClaudeCallError(RuntimeError):
    """A call that returned no usable result (the caller records it as missing)."""


@dataclass
class CallResult:
    text: str
    structured: Any
    model: Optional[str]
    models: Dict[str, Any]
    usage: Dict[str, Any]
    cost_usd: float
    duration_ms: Optional[int]
    init: Dict[str, Any]
    rate_limit_events: List[Dict[str, Any]] = field(default_factory=list)


class ClaudeCLI:
    """One subscription-billed ``claude -p`` call per ``call()``; thread-safe."""

    def __init__(self, guard: UsageGuard, ledger: UsageLedger, cwd: Path, *, executable=None,
                 concurrency: int = 2, timeout_seconds: int = 300, extra_args: Sequence[str] = ()):
        self.guard = guard
        self.ledger = ledger
        self.cwd = Path(cwd)
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.command = find_executable(executable)
        self.timeout = timeout_seconds
        self.extra_args = list(extra_args)
        self._slots = threading.BoundedSemaphore(concurrency)

    def args(self, *, model: str, system_file: Path, effort: Optional[str], json_schema: Optional[Dict]) -> List[str]:
        args = [*self.command, "-p", "--model", model, "--system-prompt-file", str(system_file),
                "--safe-mode", "--strict-mcp-config", "--tools", "", "--no-session-persistence",
                "--output-format", "stream-json", "--verbose", *self.extra_args]
        if effort:
            args += ["--effort", effort]
        if json_schema is not None:
            args += ["--json-schema", json.dumps(json_schema)]
        return args

    def call(self, prompt: str, *, system_prompt: str, model: str, role: str,
             json_schema: Optional[Dict] = None, effort: Optional[str] = None,
             max_thinking_tokens: Optional[int] = None) -> CallResult:
        self.guard.before_call()
        with self._slots:
            self.guard.before_call()  # budgets may have moved while waiting for a slot
            started = time.monotonic()
            with tempfile.NamedTemporaryFile("w", suffix=".md", dir=self.cwd, delete=False, encoding="utf-8") as f:
                f.write(system_prompt)
                system_file = Path(f.name)
            try:
                proc = subprocess.run(self.args(model=model, system_file=system_file, effort=effort,
                                                json_schema=json_schema),
                                      input=prompt, capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", cwd=self.cwd,
                                      env=subprocess_env(max_thinking_tokens=max_thinking_tokens),
                                      timeout=self.timeout)
            except subprocess.TimeoutExpired as e:
                raise ClaudeCallError(f"claude -p timed out after {self.timeout}s") from e
            finally:
                system_file.unlink(missing_ok=True)
        return self._finish(proc, role=role, model_requested=model, seconds=time.monotonic() - started,
                            max_thinking_tokens=max_thinking_tokens)

    # ------------------------------------------------------------ parsing
    def _finish(self, proc: subprocess.CompletedProcess, *, role: str, model_requested: str,
                seconds: float, max_thinking_tokens: Optional[int] = None) -> CallResult:
        init: Dict[str, Any] = {}
        result: Optional[Dict[str, Any]] = None
        rate_events: List[Dict[str, Any]] = []
        assistant_models: List[str] = []
        pending: Optional[BaseException] = None
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "system" and event.get("subtype") == "init":
                init = event
            elif kind == "rate_limit_event":
                info = event.get("rate_limit_info", event)
                rate_events.append(info)
                try:
                    self.guard.on_rate_limit(info)
                except ClaudeStop:
                    raise
                except Exception as e:  # a pause: finish reading and recording this call first
                    pending = pending or e
            elif kind == "assistant":
                m = (event.get("message") or {}).get("model")
                if m:
                    assistant_models.append(m)
            elif kind == "result":
                result = event
        cost = float((result or {}).get("total_cost_usd") or 0.0)
        usage = (result or {}).get("usage") or {}
        models = (result or {}).get("modelUsage") or {}
        model = assistant_models[-1] if assistant_models else (next(iter(models)) if models else None)
        self.ledger.append({"ts": self.guard.clock().isoformat(), "run_id": self.guard.run_id, "role": role,
                            "model_requested": model_requested, "model": model, "cost_usd": cost,
                            "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                            "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
                            "thinking_tokens": (usage.get("output_tokens_details") or {}).get("thinking_tokens"),
                            "max_thinking_tokens": max_thinking_tokens,
                            "seconds": round(seconds, 2), "ok": bool(result and not result.get("is_error")),
                            "claude_code_version": init.get("claude_code_version")})
        if not init:
            self.guard._stop("claude didn't report how it authenticated (no system/init event); stopping "
                             "rather than risk an API key.")
        if init.get("apiKeySource") not in SUBSCRIPTION_KEY_SOURCES:
            self.guard._stop(f"claude reported apiKeySource={init.get('apiKeySource')!r}, not the subscription "
                             "login. The run stopped; no API key may be used.")
        error_text = " ".join(str(x) for x in ((result or {}).get("result"), proc.stderr) if x)
        if result is None or result.get("is_error") or proc.returncode != 0:
            self.guard.on_error_text(error_text)
            if pending:
                raise pending
            raise ClaudeCallError(f"claude -p failed (exit {proc.returncode}): {error_text[:300]}")
        if pending:
            raise pending
        return CallResult(text=result.get("result") or "", structured=result.get("structured_output"),
                          model=model, models=models, usage=usage, cost_usd=cost,
                          duration_ms=result.get("duration_ms"), init=init, rate_limit_events=rate_events)


def init_summary(init: Dict[str, Any]) -> Dict[str, Any]:
    """What the init event says was loaded, for the owner (no secrets are in it)."""
    keys = ("claude_code_version", "model", "apiKeySource", "cwd", "permissionMode", "output_style", "tools",
            "mcp_servers", "slash_commands", "agents", "skills", "plugins", "memory_paths")
    return {k: init.get(k) for k in keys if k in init} | {"other_fields": sorted(set(init) - set(keys))}
