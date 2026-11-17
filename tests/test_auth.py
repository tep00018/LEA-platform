"""Registration, login and session validation against Redis."""

import uuid

from src.auth.auth_service import AuthService


def test_register_login_and_validate_session(redis_url):
    auth = AuthService(redis_url)
    username = f"student_{uuid.uuid4().hex[:8]}"

    ok, _ = auth.register_user(username, "secret123", "Test Student", ["DEMO101"])
    assert ok

    ok, session_id, _ = auth.login_user(username, "secret123")
    assert ok and session_id
    assert auth.validate_session(session_id) == username


def test_login_rejects_wrong_password(redis_url):
    auth = AuthService(redis_url)
    username = f"student_{uuid.uuid4().hex[:8]}"
    auth.register_user(username, "secret123", "Test Student", ["DEMO101"])

    ok, session_id, _ = auth.login_user(username, "wrong-password")
    assert not ok
    assert not session_id


def test_duplicate_registration_is_rejected(redis_url):
    auth = AuthService(redis_url)
    username = f"student_{uuid.uuid4().hex[:8]}"
    assert auth.register_user(username, "secret123", "A", ["DEMO101"])[0]
    assert not auth.register_user(username, "secret123", "B", ["DEMO101"])[0]


def test_usernames_that_could_break_redis_keys_are_rejected(redis_url):
    auth = AuthService(redis_url)
    for bad in ["alice:ZZZ999", "a b", "x", "../etc", "a" * 40]:
        ok, message = auth.register_user(bad, "secret123", "Name", ["DEMO101"])
        assert not ok and "Usernames" in message


def test_passwords_are_stored_with_argon2id(redis_url):
    auth = AuthService(redis_url)
    username = f"student_{uuid.uuid4().hex[:8]}"
    auth.register_user(username, "secret123", "A", ["DEMO101"])
    stored = auth.redis_client.get_redis().hget(f"user:{username}", "password_hash")
    assert stored.startswith("$argon2id$") and "secret123" not in stored


def test_old_pbkdf2_accounts_log_in_and_are_upgraded(redis_url):
    from src.auth.passwords import _legacy_hash

    auth = AuthService(redis_url)
    username = f"student_{uuid.uuid4().hex[:8]}"
    auth.register_user(username, "placeholder", "A", ["DEMO101"])
    conn = auth.redis_client.get_redis()
    conn.hset(f"user:{username}", mapping={"password_hash": _legacy_hash("secret123", "s" * 64), "salt": "s" * 64})

    assert not auth.login_user(username, "wrong")[0]
    assert conn.hget(f"user:{username}", "password_hash").startswith("$argon2") is False  # untouched on failure
    assert auth.login_user(username, "secret123")[0]
    assert conn.hget(f"user:{username}", "password_hash").startswith("$argon2id$")
    assert auth.login_user(username, "secret123")[0]  # and still works afterwards


def test_tokens_expire_and_can_be_revoked(redis_url):
    from src.auth import tokens as tk

    now = [1_000_000.0]
    auth = AuthService(redis_url)
    auth.tokens = tk.TokenStore(auth.redis_client, clock=lambda: now[0])
    username = f"student_{uuid.uuid4().hex[:8]}"
    auth.register_user(username, "secret123", "A", ["DEMO101"])

    _, token, _ = auth.login_user(username, "secret123")
    assert auth.validate_session(token) == username
    stored = auth.redis_client.get_redis().keys("auth:token:*")
    assert all(token not in k for k in stored)  # only a hash is stored

    now[0] += tk.MAX_AGE_SECONDS + 1  # past the absolute limit, even if used recently
    assert auth.validate_session(token) is None

    _, token, _ = auth.login_user(username, "secret123")
    auth.logout(token)
    assert auth.validate_session(token) is None

    _, token, _ = auth.login_user(username, "secret123")
    auth.redis_client.get_redis().hset(f"user:{username}", "is_active", "false")
    assert auth.validate_session(token) is None  # a deactivated account's tokens stop working
