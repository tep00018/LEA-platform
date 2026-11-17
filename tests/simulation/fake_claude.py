"""A stand-in for ``claude -p`` (no network). Reads its script from ``scenario.json`` in
its working directory: a list with one entry per call, used in order. Each entry may set
``api_key_source`` (default "none"), ``init`` (false to omit the init event),
``rate_limits`` (a list of rate_limit_info objects), ``result`` (the reply text),
``structured`` (structured_output), ``is_error``, ``cost`` and ``exit``. Every call is
recorded to ``calls.jsonl`` (argv, environment variable names, stdin)."""

import json
import os
import sys
from pathlib import Path

cwd = Path.cwd()
scenario = json.loads((cwd / "scenario.json").read_text(encoding="utf-8")) if (cwd / "scenario.json").exists() else [{}]
counter = cwd / "call_count"
n = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(n + 1))
step = scenario[min(n, len(scenario) - 1)]

stdin = sys.stdin.read()
with open(cwd / "calls.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "env": sorted(os.environ), "stdin": stdin}) + "\n")

model = "claude-haiku-4-5-20251001"


def emit(event):
    print(json.dumps(event), flush=True)


if step.get("init", True):
    emit({"type": "system", "subtype": "init", "apiKeySource": step.get("api_key_source", "none"),
          "claude_code_version": "9.9.9-fake", "model": model, "tools": [], "mcp_servers": [], "plugins": [],
          "cwd": str(cwd)})
for info in step.get("rate_limits", []):
    emit({"type": "rate_limit_event", "rate_limit_info": info})
emit({"type": "assistant", "message": {"model": model, "content": [{"type": "text", "text": step.get("result", "OK")}]}})
emit({"type": "result", "subtype": "error" if step.get("is_error") else "success", "is_error": bool(step.get("is_error")),
      "result": step.get("result", "OK"), "structured_output": step.get("structured"),
      "total_cost_usd": step.get("cost", 0.001), "duration_ms": 12,
      "usage": {"input_tokens": 10, "output_tokens": 2, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
      "modelUsage": {model: {"inputTokens": 10, "outputTokens": 2}}})
sys.exit(step.get("exit", 0))
