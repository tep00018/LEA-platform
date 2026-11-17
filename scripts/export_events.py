"""Export the event log for research, as CSV.

    python scripts/export_events.py research.csv                     # real sessions, consented learners
    python scripts/export_events.py sim.csv --kinds simulated
    python scripts/export_events.py aiml.csv --course AIML101
    python scripts/export_events.py teaching.csv --teachers      # teacher and admin actions


Only learners whose account has research consent (``manage_account.py consent <name> yes``)
are included; simulated accounts need no consent. Test sessions (teacher previews, test
accounts) and staff audit events are never exported. Learners appear only as pseudonyms.
With --teachers, only teacher and admin actions are written instead (KC review, audit
decisions, analytics views...), with each teacher as a pseudonym. Teachers taking part in a
study need their own consent: that is not tracked by LEA.
Uses REDIS_URL, LEA_EVENT_SALT and LEA_EVENTS_DB (optional) from .env.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.services.events import EventRecorder, research_learners  # noqa: E402
from src.storage.event_log import EventLog  # noqa: E402
from src.storage.redis_client import LEARedisClient  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", help="CSV file to write")
    parser.add_argument("--kinds", default="real", help="real, simulated, or real,simulated (never test)")
    parser.add_argument("--course", help="Only this course")
    parser.add_argument("--teachers", action="store_true", help="Teacher and admin actions instead")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    salt = os.getenv("LEA_EVENT_SALT")
    if not salt:
        print("LEA_EVENT_SALT is not set in .env, so learners can't be matched to their consent.")
        return 1
    client = LEARedisClient()
    if client.get_redis() is None:
        print("Can't reach Redis: check REDIS_URL in .env")
        return 1
    path = os.getenv("LEA_EVENTS_DB") or str(ROOT / "data" / "lea_events.db")
    if not Path(path).exists():
        print(f"No event log at {path}")
        return 1
    log = EventLog(path)
    recorder = EventRecorder(log, salt, client)
    if args.teachers:
        rows = log.export_staff_csv(args.out, recorder.pseudonym, course=args.course)
        print(f"Wrote {rows} teacher and admin actions to {args.out}")
        return 0
    try:
        rows = log.export_csv(args.out, kinds=[k.strip() for k in args.kinds.split(",")],
                              learners=research_learners(recorder), course=args.course)
    except ValueError as e:
        print(e)
        return 1
    print(f"Wrote {rows} events to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
