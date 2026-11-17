"""Account admin for whoever runs LEA (there is no self-service password reset yet).

    python scripts/manage_account.py reset-password alice   # asks for the new password
    python scripts/manage_account.py deactivate alice
    python scripts/manage_account.py activate alice
    python scripts/manage_account.py sign-out alice          # end every session
    python scripts/manage_account.py set-kind alice test     # real (default), test or simulated
    python scripts/manage_account.py consent alice yes       # research consent: yes, no or unset
    python scripts/manage_account.py delete alice            # the account and all its data (asks first)
    python scripts/manage_account.py make-admin alice        # also make-teacher, make-student

Resetting a password or deactivating an account also ends the account's sessions.
A test account's activity is tagged ``test`` in the event log and left out of the research
logs and exports. Every change is recorded in the event log's audit trail.
Uses REDIS_URL (and LEA_EVENTS_DB, if set) from .env.
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.auth import passwords  # noqa: E402
from src.auth.tokens import TokenStore  # noqa: E402
from src.storage.event_log import SESSION_KINDS, EventLog  # noqa: E402
from src.storage.redis_client import LEARedisClient  # noqa: E402

CONSENT = {"yes": "true", "no": "false", "unset": None}


def audit(action: str, username: str, value=None) -> None:
    """Record the change in the event log's staff audit trail (never fails the command)."""
    try:
        path = os.getenv("LEA_EVENTS_DB") or str(ROOT / "data" / "lea_events.db")
        log = EventLog(path)
        log.append(type=f"account_{action.replace('-', '_')}", session_kind="real", mode="admin",
                   actor=f"host:{getpass.getuser()}", payload={"username": username, "value": value})
        log.close()
    except Exception as e:
        print(f"(Couldn't write the audit trail: {e})")


def account_keys(conn, username: str) -> list:
    """Every Redis key holding this account's data: keys with the username as one
    ``:``-separated part (user:, mastery:, evidence:, sessions, memory, progress...)."""
    return sorted(k for k in conn.scan_iter(match=f"*{username}*", count=1000)
                  if username in k.split(":"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["reset-password", "deactivate", "activate", "sign-out",
                                           "set-kind", "consent", "delete", "make-admin", "make-teacher",
                                           "make-student"])
    parser.add_argument("username")
    parser.add_argument("value", nargs="?", help="set-kind: real, test or simulated; consent: yes, no or unset")
    parser.add_argument("--yes", action="store_true", help="delete: don't ask for confirmation")
    args = parser.parse_args(argv)
    if args.action == "set-kind" and args.value not in SESSION_KINDS:
        parser.error("set-kind needs one of: " + ", ".join(SESSION_KINDS))
    if args.action == "consent" and args.value not in CONSENT:
        parser.error("consent needs one of: yes, no, unset")

    load_dotenv(ROOT / ".env")
    client = LEARedisClient()
    conn = client.get_redis()
    if conn is None:
        print("Can't reach Redis: check REDIS_URL in .env")
        return 1
    key = f"user:{args.username}"
    if not conn.exists(key):
        print(f"No account called {args.username}")
        return 1
    tokens = TokenStore(client)

    if args.action == "delete":
        keys = account_keys(conn, args.username)
        print(f"This permanently deletes {args.username} and {len(keys)} Redis keys:")
        for k in keys:
            print(f"  {k}")
        print("The event log keeps its pseudonymous history.")
        if not args.yes:
            try:
                answer = input(f"Type {args.username} to confirm: ").strip()
            except EOFError:
                answer = ""
            if answer != args.username:
                print("Nothing deleted.")
                return 1
        tokens.revoke_all(args.username)
        for k in keys:
            conn.delete(k)
        audit(args.action, args.username, len(keys))
        print(f"Done: deleted {args.username}")
        return 0

    if args.action == "reset-password":
        new = getpass.getpass("New password: ")
        if len(new) < 6 or new != getpass.getpass("Again: "):
            print("Passwords must match and be at least 6 characters.")
            return 1
        conn.hset(key, mapping={"password_hash": passwords.hash_password(new), "salt": ""})
    elif args.action in ("deactivate", "activate"):
        conn.hset(key, "is_active", "true" if args.action == "activate" else "false")
    elif args.action.startswith("make-"):
        conn.hset(key, "role", args.action.removeprefix("make-"))
    elif args.action == "set-kind":
        conn.hset(key, "session_kind", args.value)
    elif args.action == "consent":
        if CONSENT[args.value] is None:
            conn.hdel(key, "research_consent")
        else:
            conn.hset(key, "research_consent", CONSENT[args.value])
    if args.action in ("reset-password", "deactivate", "sign-out"):
        tokens.revoke_all(args.username)
    audit(args.action, args.username, args.value)
    print(f"Done: {args.action} {args.username}" + (f" {args.value}" if args.value else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
