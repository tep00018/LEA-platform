"""The run manifest (``runs/<run_id>/manifest.json``): enough to reproduce and audit a run.

Git commit and dirty flag, config and its hash, seeds, Claude Code version, package
versions, SHA-256 of the course's KC model and vector store copy, times, and the model IDs
and costs actually seen (OpenAI and Claude, the latter as API-equivalent estimates).
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Dict

from simulation import REPO_ROOT
from simulation.settings import ConfigError, config_hash

PACKAGES = ("openai", "chromadb", "redis", "fakeredis", "numpy", "scipy", "pandas", "pyyaml", "statsmodels",
            "ragas", "sentence-transformers")


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


# What a resume may change: limits and guards, never what the learners do. Anything else that
# differs from the saved config (a seed, a profile, the scale) would make the learners
# already run and those still to run incomparable, so the resume refuses.
RESUME_MAY_CHANGE = {
    "claude.max_calls_per_run", "claude.per_5h_budget", "claude.per_week_budget", "claude.share_of_allowance",
    "claude.pause_at_5h", "claude.pause_at_week", "claude.run_hours", "claude.max_days_per_run",
    "claude.concurrency", "claude.timeout_seconds", "openai.budget_usd", "usage_credits_confirmed_off",
}


def _flatten(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in d.items():
        name = f"{prefix}{key}"
        out.update(_flatten(value, name + ".") if isinstance(value, dict) and value else {name: value})
    return out


def resume_changes(saved: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The settings that differ between a run's saved config and the one it is resumed with.
    New settings (added to LEA's simulation since the run began) are allowed and recorded;
    a changed existing setting must be in ``RESUME_MAY_CHANGE`` or the resume is refused."""
    old, now = _flatten(saved), _flatten(new)
    changed = {k: {"from": old.get(k), "to": v} for k, v in now.items() if k in old and old[k] != v}
    added = {k: {"from": None, "to": v} for k, v in now.items() if k not in old}
    refused = sorted(k for k in changed if k not in RESUME_MAY_CHANGE)
    if refused:
        raise ConfigError("This run can't be resumed with those settings changed (the learners already run "
                          "would no longer be comparable): " + ", ".join(refused))
    return {**changed, **added}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_tree(root: Path) -> str:
    """One hash over every file's relative path and contents, in sorted order."""
    h = hashlib.sha256()
    for path in sorted(p for p in Path(root).rglob("*") if p.is_file()):
        h.update(path.relative_to(root).as_posix().encode())
        h.update(sha256_file(path).encode())
    return h.hexdigest()


def package_versions() -> Dict[str, str]:
    out = {}
    for name in PACKAGES:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    return out


class Manifest:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: Dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    @classmethod
    def start(cls, run_dir: Path, run_id: str, config: Dict[str, Any], data_dir: Path, course: str) -> "Manifest":
        m = cls(Path(run_dir) / "manifest.json")
        if m.data:  # a resumed run keeps its original record, plus what changed at the resume
            changed = resume_changes(m.data.get("config") or {}, config)
            m.data.setdefault("resumes", []).append({"at": _now(), "changed": changed})
            m.data["config"], m.data["config_hash"] = config, config_hash(config)
            m.data["usage_credits_confirmed_off"] = config.get("usage_credits_confirmed_off")
            m.save()
            return m
        kc = Path(data_dir) / "kc_models" / course / f"kc_model_{course}.json"
        chroma = Path(data_dir) / "chroma_data" / course
        m.data = {
            "run_id": run_id,
            "started_at": _now(),
            "ended_at": None,
            "git_commit": _git("rev-parse", "HEAD"),
            "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
            "config": config,
            "config_hash": config_hash(config),
            "seed": config.get("seed"),
            "course": course,
            "kc_model_sha256": sha256_file(kc) if kc.exists() else None,
            "vector_store_sha256": sha256_tree(chroma) if chroma.exists() else None,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "packages": package_versions(),
            "claude": {"code_version": None, "models": {}, "calls": 0, "api_equivalent_usd": 0.0,
                       "temperature": "not settable in claude -p", "seed": "not settable in claude -p"},
            "openai": {"models": {}, "tokens": 0, "usd": 0.0},
            "usage_credits_confirmed_off": config.get("usage_credits_confirmed_off"),
        }
        m.save()
        return m

    def record_claude(self, result) -> None:
        c = self.data.setdefault("claude", {})
        c["code_version"] = result.init.get("claude_code_version") or c.get("code_version")
        if result.model:
            c.setdefault("models", {})[result.model] = c.get("models", {}).get(result.model, 0) + 1
        c["calls"] = c.get("calls", 0) + 1
        c["api_equivalent_usd"] = round(c.get("api_equivalent_usd", 0.0) + result.cost_usd, 6)

    def finish(self) -> None:
        self.data["ended_at"] = _now()
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
