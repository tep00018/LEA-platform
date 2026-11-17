"""Password hashing: argon2id, with transparent upgrade of the old PBKDF2 hashes.

Accounts created before Phase 3 store a PBKDF2-SHA256 hash (100k iterations) and a salt.
They keep working: the first successful login re-hashes the password with argon2id.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# OWASP's argon2id baseline (19 MiB, 2 passes): about 20-50 ms per check on a laptop,
# so a class logging in at once doesn't exhaust the memory of the PC hosting LEA.
_hasher = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1)

LEGACY_ITERATIONS = 100_000

# Verified against when the username doesn't exist, so a login takes the same time
# whether or not the account exists.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def is_argon2(stored_hash: Optional[str]) -> bool:
    return bool(stored_hash) and stored_hash.startswith("$argon2")


def _legacy_hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), LEGACY_ITERATIONS).hex()


def verify_password(password: str, stored_hash: Optional[str], salt: Optional[str] = None) -> bool:
    """True if ``password`` matches. Accepts argon2id hashes and the old PBKDF2 ones."""
    if not stored_hash:
        burn_time(password)
        return False
    if is_argon2(stored_hash):
        try:
            return _hasher.verify(stored_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
    if not salt:
        return False
    return hmac.compare_digest(_legacy_hash(password, salt), stored_hash)


def needs_rehash(stored_hash: Optional[str]) -> bool:
    return not is_argon2(stored_hash) or _hasher.check_needs_rehash(stored_hash)


def burn_time(password: str) -> None:
    """Spend the time a real check would (for unknown usernames)."""
    try:
        _hasher.verify(_DUMMY_HASH, password)
    except VerificationError:
        pass
