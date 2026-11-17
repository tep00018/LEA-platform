"""A run must never get the real YouTube key or Redis URL back from .env, however the modules are imported.

LEA's ``src.storage.redis_client`` copies every line of ``.env`` into ``os.environ`` (overriding) the first
time it is imported. In a fresh process that import happens while services are built, i.e. inside the run,
so this is tested in a fresh process with a ``.env`` in the working directory.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SCRIPT = r"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from simulation.isolation import RunContext
with RunContext("dotenv-probe", "AIML101", runs_dir=Path(tempfile.mkdtemp())) as ctx:
    import src.storage.redis_client  # what building the services does
    from src.mcp.tool_registry import MCPToolRegistry  # noqa: F401
    print("KEY=" + repr(os.environ.get("YOUTUBE_API_KEY")))
    print("REDIS=" + os.environ.get("REDIS_URL", ""))
    print("SALT_IS_RUNS=" + str(os.environ.get("LEA_EVENT_SALT") == ctx.salt()))
"""


def test_dotenv_inside_a_run_cannot_restore_the_youtube_key_or_the_redis_url(tmp_path):
    (tmp_path / ".env").write_text("YOUTUBE_API_KEY=not-a-real-key-123\nREDIS_URL=redis://real.example:6379/0\n"
                                   "LEA_EVENT_SALT=from-dotenv\nOPENAI_API_KEY=sk-not-real\n")
    out = subprocess.run([sys.executable, "-c", SCRIPT, str(REPO)], cwd=tmp_path, capture_output=True, text=True,
                         timeout=300, env={**__import__("os").environ, "PYTHONPATH": str(REPO)})
    assert out.returncode == 0, out.stderr[-2000:]
    lines = dict(l.split("=", 1) for l in out.stdout.splitlines() if "=" in l and l.split("=", 1)[0] in ("KEY", "REDIS", "SALT_IS_RUNS"))
    assert lines["KEY"] == "''"
    assert "real.example" not in lines["REDIS"]
    assert lines["SALT_IS_RUNS"] == "True"
