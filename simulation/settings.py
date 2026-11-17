"""Run configuration: YAML layered over ``config/default.yaml``, checked, and hashed.

A run config may name a ``base`` (another YAML file, relative to itself) and overrides
only what it changes. Unknown keys are errors, so a typo can't silently fall back to a
default.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from simulation import CONFIG_DIR

DEFAULT = CONFIG_DIR / "default.yaml"
RUN_HOURS = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")


class ConfigError(ValueError):
    pass


def _merge(base: Dict[str, Any], over: Dict[str, Any], path: str = "") -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in over.items():
        where = f"{path}{key}"
        if key not in base:
            raise ConfigError(f"Unknown setting: {where}")
        if isinstance(base[key], dict) and not isinstance(value, dict):
            raise ConfigError(f"{where} must be a mapping")
        out[key] = _merge(base[key], value, f"{where}.") if isinstance(base[key], dict) else value
    return out


def _read(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must be a mapping")
    return data


def load(path: Optional[Path | str] = None, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The default config, overlaid by ``path`` (and its ``base`` chain) and ``overrides``."""
    config = _read(DEFAULT)
    chain = []
    current = Path(path) if path else None
    while current is not None:
        data = _read(current)
        chain.append(data)
        base = data.pop("base", None)
        current = (current.parent / base) if base else None
        if len(chain) > 10:
            raise ConfigError("Config base chain is too long")
    for layer in reversed(chain):
        config = _merge(config, layer)
    if overrides:
        config = _merge(config, overrides)
    validate(config)
    return config


def validate(config: Dict[str, Any]) -> None:
    c = config["claude"]
    for key in ("pause_at_5h", "pause_at_week", "share_of_allowance"):
        if not 0 < float(c[key]) <= 1:
            raise ConfigError(f"claude.{key} must be between 0 and 1")
    for key in ("per_5h_budget", "per_week_budget"):
        if c[key] is not None and float(c[key]) <= 0:
            raise ConfigError(f"claude.{key} must be positive or null")
    if int(c["max_calls_per_run"]) < 1 or int(c["concurrency"]) < 1:
        raise ConfigError("claude.max_calls_per_run and claude.concurrency must be at least 1")
    if c["run_hours"] is not None and not RUN_HOURS.match(str(c["run_hours"])):
        raise ConfigError('claude.run_hours must look like "23:00-07:00"')
    if not isinstance(config["usage_credits_confirmed_off"], bool):
        raise ConfigError("usage_credits_confirmed_off must be true or false")


def config_hash(config: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()
