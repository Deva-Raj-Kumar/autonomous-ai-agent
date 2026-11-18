"""Cryptographic building blocks. No database, no FastAPI: easy to test and reason about.

Passwords      bcrypt (salt rounds 12: adaptive, robust password hashing).
Access tokens  JWT signed with HMAC-SHA256: stateless, short-lived (15 min default).
Refresh tokens 384 random bits, stored as SHA-256. A fast hash is fine here because
               the token is random (nothing to brute-force), and it must be
               deterministic so the database can look it up by hash.
"""

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

logger = logging.getLogger(__name__)

# Bcrypt with salt rounds, supporting legacy Argon2id for backward compatibility
password_hasher = PasswordHash((BcryptHasher(), Argon2Hasher()))
# Verified against when the email doesn't exist, so "unknown email" takes as long as
# "wrong password": response timing can't reveal which emails have accounts.
_DUMMY_HASH = password_hasher.hash("dummy password used only for timing")

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128  # long enough for passphrases; caps hashing cost per request
COMMON_PASSWORDS = frozenset({
    "password123", "password1234", "1234567890", "qwertyuiop", "iloveyou12", "letmein123",
    "welcome123", "admin12345", "passw0rd123", "abcdefghij", "0987654321", "qwerty1234",
})


class InvalidTokenError(Exception):
    """Missing, malformed, expired, or wrongly signed token."""


@dataclass(frozen=True)
class TokenConfig:
    secret: str
    algorithm: str = "HS256"
    access_minutes: int = 15
    refresh_days: int = 7
    issuer: str = "autonomous-ai-agent"


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> tuple[bool, str | None]:
    """(matches, new_hash). new_hash is set when the stored hash uses outdated
    parameters: the caller saves it, so hashes upgrade silently as users log in."""
    if not password_hash:
        password_hasher.verify(password, _DUMMY_HASH)
        return False, None
    try:
        return password_hasher.verify_and_update(password, password_hash)
    except UnknownHashError:  # e.g. "!" = an account with no usable password
        password_hasher.verify(password, _DUMMY_HASH)
        return False, None


def burn_time_like_a_login(password: str) -> None:
    """Do the same work as a real password check (for unknown emails)."""
    password_hasher.verify(password, _DUMMY_HASH)


def password_problem(password: str, email: str = "", username: str = "") -> str | None:
    """Why this password is unacceptable, or None. Length beats complexity rules
    (NIST SP 800-63B): no "must contain a symbol", but no obvious choices either."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS or len(set(lowered)) < 4:
        return "Password is too easy to guess."
    for personal in (email.split("@")[0].lower(), username.lower()):
        if len(personal) >= 4 and personal in lowered:
            return "Password must not contain your email name or username."
    return None


# --------------------------------------------------------------- access JWT
def create_access_token(user_id: int, config: TokenConfig, *, now: datetime | None = None) -> str:
    issued = now or datetime.now(UTC)
    claims = {
        "sub": str(user_id),        # subject: who this token is for (JWT wants a string)
        "type": "access",           # a refresh token can never be used as an access token
        "iss": config.issuer,       # who issued it
        "iat": issued,              # issued at
        "exp": issued + timedelta(minutes=config.access_minutes),  # expiry (checked by PyJWT)
        "jti": secrets.token_hex(8),  # unique id (useful for logging / future deny-lists)
    }
    return jwt.encode(claims, config.secret, algorithm=config.algorithm)


def decode_access_token(token: str, config: TokenConfig) -> int:
    """The user id inside a valid access token, else InvalidTokenError.

    algorithms=[...] is a LIST of what we accept: never let the token's own header
    choose (the classic "alg: none" attack)."""
    try:
        claims = jwt.decode(
            token, config.secret, algorithms=[config.algorithm], issuer=config.issuer,
            options={"require": ["sub", "exp", "iat", "type"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(type(exc).__name__) from None
    if claims.get("type") != "access" or not str(claims["sub"]).isdigit():
        raise InvalidTokenError("not an access token")
    return int(claims["sub"])


# ------------------------------------------------------------ refresh token
def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def resolve_jwt_secret(configured: str | None) -> str:
    """The configured secret, or (development only) a random one for this process."""
    if configured:
        return configured
    logger.warning(
        "JWT_SECRET_KEY is not set: using a random key for this run. Everyone is logged out "
        "when the server restarts. Set JWT_SECRET_KEY in .env to keep sessions."
    )
    return secrets.token_urlsafe(64)
