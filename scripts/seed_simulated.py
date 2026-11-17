"""Seed simulated students into the event log, to try the analytics.

    python scripts/seed_simulated.py AIML101                # 30 students, every week
    python scripts/seed_simulated.py AIML101 --students 12 --weeks 3

The events are tagged ``simulated``: never real, never in research exports; the analytics
screens show them only when "Simulated students" is chosen. The event log is append-only,
so seeding twice adds a second cohort (the script asks you to pass --again).
Uses LEA_EVENT_SALT and LEA_EVENTS_DB (optional) from .env.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.core.course_registry import default_registry  # noqa: E402
from src.onboarding.simulate import existing, seed  # noqa: E402
from src.services.events import EventRecorder  # noqa: E402
from src.storage.event_log import EventLog  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("course")
    parser.add_argument("--students", type=int, default=30)
    parser.add_argument("--weeks", type=int, help="Only the first N weeks")
    parser.add_argument("--again", action="store_true", help="Add another cohort even if one exists")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")
    salt = os.getenv("LEA_EVENT_SALT")
    if not salt:
        print("LEA_EVENT_SALT is not set in .env.")
        return 1
    registry = default_registry()
    model = registry.kc_model(args.course.upper())
    if model is None:
        print(f"{args.course} has no published objectives.")
        return 1
    path = os.getenv("LEA_EVENTS_DB") or str(registry.data_dir / "lea_events.db")
    recorder = EventRecorder(EventLog(path), salt)
    if existing(recorder, args.course.upper()) and not args.again:
        print(f"{args.course} already has simulated students. Pass --again to add another cohort.")
        return 1
    counts = seed(recorder, model, args.course.upper(), students=args.students, weeks=args.weeks)
    print(f"Seeded {counts['students']} simulated students: {counts['answers']} answers, {counts['chat']} chat "
          f"questions, {counts['sessions']} sessions; {counts['hard_objectives']} objectives made hard on purpose.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
