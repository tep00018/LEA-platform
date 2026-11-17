"""Simulation v2: LEA on AIML101 with ground-truth learners (docs/simulation/PLAN.md).

LEA itself runs unchanged on OpenAI. Everything the simulation adds (students, judges,
question bank) calls Claude through the researcher's subscription with ``claude -p``
(``simulation.llm.claude_cli``), never an Anthropic API key.
"""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
RUNS_DIR = PACKAGE_DIR / "runs"
CONFIG_DIR = PACKAGE_DIR / "config"
