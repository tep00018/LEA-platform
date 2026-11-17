"""Keep a free Redis Cloud database from being deleted for inactivity.

Free Redis Cloud databases can be removed after a period without activity. Running this
once a week writes and reads a single key, which counts as activity.

    python scripts/redis_keepalive.py

Schedule it on Windows (runs every Monday at 09:00 while you are logged in):

    schtasks /Create /SC WEEKLY /D MON /ST 09:00 /TN "LEA Redis keepalive" ^
      /TR "\"C:\\path\\to\\LEA\\.venv\\Scripts\\python.exe\" \"C:\\path\\to\\LEA\\scripts\\redis_keepalive.py\""

Exit status is 0 on success and 1 on failure, so Task Scheduler's history shows problems.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402


def main() -> int:
    load_dotenv(ROOT / ".env")
    from src.config_check import check_configuration

    problems = [p for p in check_configuration(openai_key="skip") if "Redis" in p or "REDIS" in p]
    if problems:
        print("\n".join(problems))
        return 1

    import os

    import redis

    conn = redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=10)
    stamp = datetime.now(timezone.utc).isoformat()
    conn.set("lea:keepalive", stamp)
    print(f"Redis keepalive OK at {conn.get('lea:keepalive').decode()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
