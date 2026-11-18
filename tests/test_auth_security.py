"""Unit tests for the auth building blocks: hashing, JWTs, password policy, throttle,
and the per-request user context. No HTTP, no database."""

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.auth import context
from app.auth.security import (
    InvalidTokenError,
    TokenConfig,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    password_problem,
    verify_password,
)
from app.auth.throttle import LoginThrottle

CONFIG = TokenConfig(secret="test-secret-" + "x" * 40)


# ---------------------------------------------------------------- passwords
def test_passwords_are_hashed_with_argon2id_and_salted() -> None:
    first, second = hash_password("a long passphrase"), hash_password("a long passphrase")

    assert first.startswith("$2b$") or first.startswith("$argon2id$")
    assert first != second  # random salt: equal passwords give different hashes
    assert verify_password("a long passphrase", first) == (True, None)
    assert verify_password("a long passphrasE", first) == (False, None)


def test_unusable_hashes_never_match() -> None:
    assert verify_password("anything", "!") == (False, None)  # the local CLI user
    assert verify_password("anything", "") == (False, None)


def test_outdated_hashes_are_upgraded_on_login() -> None:
    weak = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8 * 1024),)).hash("a long passphrase")

    ok, new_hash = verify_password("a long passphrase", weak)

    assert ok and new_hash is not None and new_hash != weak  # caller stores new_hash


@pytest.mark.parametrize(("password", "problem"), [
    ("short", "at least 10"),
    ("x" * 129, "at most 128"),
    ("password123", "too easy"),
    ("aaaaaaaaaaaa", "too easy"),
    ("ravikumar-2026!", "email name or username"),
])
def test_weak_passwords_are_rejected(password: str, problem: str) -> None:
    assert problem in password_problem(password, "ravikumar@example.com", "ravi")


def test_a_long_passphrase_is_accepted() -> None:
    assert password_problem("correct horse battery staple", "ravi@example.com", "ravi") is None


# --------------------------------------------------------------------- JWTs
def test_access_token_round_trip() -> None:
    assert decode_access_token(create_access_token(42, CONFIG), CONFIG) == 42


def test_expired_token_is_rejected() -> None:
    long_ago = datetime.now(UTC) - timedelta(hours=1)

    with pytest.raises(InvalidTokenError, match="Expired"):
        decode_access_token(create_access_token(42, CONFIG, now=long_ago), CONFIG)


def test_token_signed_with_another_key_is_rejected() -> None:
    forged = create_access_token(42, TokenConfig(secret="attacker-" + "y" * 40))

    with pytest.raises(InvalidTokenError):
        decode_access_token(forged, CONFIG)


def test_tampered_payload_is_rejected() -> None:
    header, payload, signature = create_access_token(42, CONFIG).split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["sub"] = "1"  # try to become user 1
    evil = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")

    with pytest.raises(InvalidTokenError):
        decode_access_token(f"{header}.{evil}.{signature}", CONFIG)


def test_unsigned_alg_none_token_is_rejected() -> None:
    claims = {"sub": "1", "type": "access", "iss": CONFIG.issuer,
              "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(minutes=5)}
    unsigned = jwt.encode(claims, key=None, algorithm="none")

    with pytest.raises(InvalidTokenError):
        decode_access_token(unsigned, CONFIG)


def test_non_access_tokens_are_rejected() -> None:
    claims = {"sub": "1", "type": "refresh", "iss": CONFIG.issuer,
              "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(minutes=5)}

    with pytest.raises(InvalidTokenError, match="not an access token"):
        decode_access_token(jwt.encode(claims, CONFIG.secret, algorithm="HS256"), CONFIG)


def test_refresh_tokens_are_random_and_stored_as_sha256() -> None:
    first, second = new_refresh_token(), new_refresh_token()

    assert first != second and len(first) >= 60
    assert len(hash_refresh_token(first)) == 64 and hash_refresh_token(first) == hash_refresh_token(first)
    assert first not in hash_refresh_token(first)


# ----------------------------------------------------------------- throttle
class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_throttle_blocks_after_max_failures_then_recovers() -> None:
    clock = FakeClock()
    throttle = LoginThrottle(max_failures=3, window_seconds=60, clock=clock)
    for _ in range(3):
        assert throttle.retry_after("ravi|1.2.3.4") == 0
        throttle.record_failure("ravi|1.2.3.4")

    assert 1 <= throttle.retry_after("ravi|1.2.3.4") <= 61
    assert throttle.retry_after("ravi|5.6.7.8") == 0  # other IPs are not locked out

    clock.now += 61
    assert throttle.retry_after("ravi|1.2.3.4") == 0
    assert throttle.tracked_keys() == 0  # expired entries are forgotten (no memory leak)


def test_successful_login_resets_the_counter() -> None:
    throttle = LoginThrottle(max_failures=2, window_seconds=60, clock=FakeClock())
    throttle.record_failure("k")
    throttle.reset("k")
    throttle.record_failure("k")

    assert throttle.retry_after("k") == 0


# ------------------------------------------------------------------ context

@pytest.mark.anyio
async def test_user_context_follows_background_tasks_and_threads() -> None:
    async def background() -> tuple[int | None, int | None]:
        in_thread = await asyncio.to_thread(context.current_user_id)
        return context.current_user_id(), in_thread

    async def request_for(user_id: int) -> tuple[int | None, int | None]:
        context.bind_user(user_id)  # what require_user does
        return await asyncio.create_task(background())

    a, b = await asyncio.gather(request_for(1), request_for(2))  # two concurrent "requests"

    assert a == (1, 1) and b == (2, 2)  # never mixed up
    assert context.current_user_id() is None  # and nothing leaked into the caller


def test_acting_as_restores_the_previous_user() -> None:
    with context.acting_as(7):
        assert context.current_user_id() == 7
    assert context.current_user_id() is None
