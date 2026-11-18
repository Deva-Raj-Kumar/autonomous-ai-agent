"""Accounts and sessions: register, log in, refresh (with rotation), log out.

Refresh-token rotation, step by step:
  login     -> access token A1 + refresh token R1 (family F)
  refresh   -> R1 is revoked, A2 + R2 issued (same family F)
  refresh   -> R2 revoked, A3 + R3 ...
  If R1 is EVER presented again, someone kept a copy (stolen token): every token in
  family F is revoked, so both the thief and the real user must log in again.
"""

import asyncio
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.auth.schemas import AuthUser, TokenPair
from app.auth.security import (
    InvalidTokenError,
    TokenConfig,
    burn_time_like_a_login,
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.database.connection import LOCAL_USER_EMAIL, Database
from app.database.models import AgentRun, Conversation, Memory, RefreshToken, SavedRecord, User
from app.timeutils import as_utc


class EmailAlreadyRegistered(Exception):
    pass


class UserDeactivated(Exception):
    pass


class RefreshTokenReused(InvalidTokenError):
    """An already-rotated refresh token came back: treated as theft."""


def normalise_email(email: str) -> str:
    return email.strip().lower()


class AuthService:
    def __init__(self, database: Database, config: TokenConfig) -> None:
        self._db = database
        self.config = config

    # ------------------------------------------------------------ public API
    async def register(self, email: str, username: str, password: str, *, is_admin: bool = False) -> AuthUser:
        # Hashing takes ~50-100 ms of CPU: do it in a thread, not on the event loop.
        password_hash = await asyncio.to_thread(hash_password, password)
        return await asyncio.to_thread(self._register, normalise_email(email), username.strip(), password_hash, is_admin)

    async def authenticate(self, email: str, password: str) -> AuthUser | None:
        """The user if email + password are right AND the account is active, else None.
        The same answer for every failure: callers can't tell WHICH part was wrong."""
        return await asyncio.to_thread(self._authenticate, normalise_email(email), password)

    async def issue_tokens(self, user_id: int) -> TokenPair:
        return await asyncio.to_thread(self._issue_tokens, user_id, secrets.token_hex(16))

    async def refresh(self, refresh_token: str) -> TokenPair:
        return await asyncio.to_thread(self._refresh, refresh_token)

    async def logout(self, refresh_token: str) -> None:
        await asyncio.to_thread(self._logout, refresh_token)

    async def get_active_user(self, user_id: int) -> AuthUser | None:
        return await asyncio.to_thread(self._get_active_user, user_id)

    async def reset_password(self, email: str, new_password: str) -> bool:
        pw_hash = await asyncio.to_thread(hash_password, new_password)
        return await asyncio.to_thread(self._reset_password, normalise_email(email), pw_hash)

    def _reset_password(self, email: str, password_hash: str) -> bool:
        with self._db.session() as s:
            user = s.scalars(select(User).where(User.email == email)).first()
            if user is None:
                return False
            user.password_hash = password_hash
            self._revoke_where(s, RefreshToken.user_id == user.id)
            return True

    async def get_or_create_google_user(self, email: str, username: str | None = None) -> AuthUser:
        return await asyncio.to_thread(self._get_or_create_google_user, normalise_email(email), username)

    def _get_or_create_google_user(self, email: str, username: str | None = None) -> AuthUser:
        with self._db.session() as s:
            user = s.scalars(select(User).where(User.email == email)).first()
            if user is not None:
                if not user.is_active:
                    raise UserDeactivated(email)
                user.last_login_at = datetime.now(UTC)
                return AuthUser.model_validate(user)
            uname = username.strip() if username and username.strip() else email.split("@")[0]
            pw_hash = hash_password(secrets.token_urlsafe(32))
            user = User(
                email=email,
                username=uname,
                password_hash=pw_hash,
                is_active=True,
                is_admin=False,
                last_login_at=datetime.now(UTC),
            )
            s.add(user)
            s.flush()
            return AuthUser.model_validate(user)

    # Admin operations (used by the CLI)
    def list_users(self) -> list[AuthUser]:
        with self._db.session() as s:
            return [AuthUser.model_validate(u) for u in s.scalars(select(User).order_by(User.id))]

    def set_flags(self, email: str, *, is_admin: bool | None = None, is_active: bool | None = None) -> AuthUser | None:
        with self._db.session() as s:
            user = s.scalars(select(User).where(User.email == normalise_email(email))).first()
            if user is None:
                return None
            if is_admin is not None:
                user.is_admin = is_admin
            if is_active is not None:
                user.is_active = is_active
                if not is_active:  # deactivating also ends every session
                    self._revoke_where(s, RefreshToken.user_id == user.id)
            return AuthUser.model_validate(user)

    def adopt_local_data(self, user_id: int) -> dict[str, int]:
        """Move everything the CLI's local user owns (runs, memories, chats, records)
        to a real account, in ONE transaction."""
        moved: dict[str, int] = {}
        local_id = self._db.default_user_id()
        with self._db.session() as s:
            for model in (AgentRun, Memory, Conversation, SavedRecord):
                result = s.execute(update(model).where(model.user_id == local_id).values(user_id=user_id))
                moved[model.__tablename__] = result.rowcount
        return moved

    # ------------------------------------------------------- implementation
    def _register(self, email: str, username: str, password_hash: str, is_admin: bool) -> AuthUser:
        if email == LOCAL_USER_EMAIL:
            raise EmailAlreadyRegistered(email)
        try:
            with self._db.session() as s:
                if s.scalar(select(func.count()).select_from(User).where(User.email == email)):
                    raise EmailAlreadyRegistered(email)
                user = User(email=email, username=username, password_hash=password_hash, is_active=True, is_admin=is_admin)
                s.add(user)
                s.flush()
                return AuthUser.model_validate(user)
        except IntegrityError:
            # Two registrations raced past the check above; the UNIQUE index on email
            # stopped the second one. The database, not the check, is the guarantee.
            raise EmailAlreadyRegistered(email) from None

    def _authenticate(self, email: str, password: str) -> AuthUser | None:
        with self._db.session() as s:
            user = s.scalars(select(User).where(User.email == email)).first()
            if user is None:
                burn_time_like_a_login(password)
                return None
            ok, new_hash = verify_password(password, user.password_hash)
            if not ok or not user.is_active:
                return None
            if new_hash:  # stored with outdated Argon2 settings: upgrade it now
                user.password_hash = new_hash
            user.last_login_at = datetime.now(UTC)
            return AuthUser.model_validate(user)

    def _issue_tokens(self, user_id: int, family_id: str) -> TokenPair:
        with self._db.session() as s:
            return self._new_pair(s, user_id, family_id)

    def _new_pair(self, s, user_id: int, family_id: str) -> TokenPair:
        refresh = new_refresh_token()
        s.add(RefreshToken(
            user_id=user_id, token_hash=hash_refresh_token(refresh), family_id=family_id,
            expires_at=datetime.now(UTC) + timedelta(days=self.config.refresh_days),
        ))
        return TokenPair(
            access_token=create_access_token(user_id, self.config),
            refresh_token=refresh,
            expires_in=self.config.access_minutes * 60,
        )

    def _refresh(self, refresh_token: str) -> TokenPair:
        now = datetime.now(UTC)
        with self._db.session() as s:
            row = s.scalars(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(refresh_token))).first()
            if row is None:
                raise InvalidTokenError("unknown refresh token")
            if row.revoked_at is not None:
                family = row.family_id
            elif as_utc(row.expires_at) <= now:
                raise InvalidTokenError("refresh token expired")
            else:
                # Claim the token with a CONDITIONAL update: if two requests race with the
                # same token, exactly one sees rowcount == 1; the other is treated as reuse.
                claimed = s.execute(
                    update(RefreshToken)
                    .where(RefreshToken.id == row.id, RefreshToken.revoked_at.is_(None))
                    .values(revoked_at=now)
                ).rowcount
                user = s.get(User, row.user_id)
                if claimed == 1 and user is not None and user.is_active:
                    return self._new_pair(s, row.user_id, row.family_id)
                if claimed == 1:
                    raise InvalidTokenError("account disabled")
                family = row.family_id
        # Reuse detected: revoke the whole family in its OWN transaction (committed even
        # though we then raise).
        with self._db.session() as s:
            self._revoke_where(s, RefreshToken.family_id == family)
        raise RefreshTokenReused("refresh token was already used")

    def _logout(self, refresh_token: str) -> None:
        with self._db.session() as s:
            row = s.scalars(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(refresh_token))).first()
            if row is not None:  # unknown token: nothing to do (logout is idempotent)
                self._revoke_where(s, RefreshToken.family_id == row.family_id)

    @staticmethod
    def _revoke_where(s, condition) -> None:
        s.execute(update(RefreshToken).where(condition, RefreshToken.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))

    def _get_active_user(self, user_id: int) -> AuthUser | None:
        with self._db.session() as s:
            user = s.get(User, user_id)
            if user is None or not user.is_active:
                return None
            return AuthUser.model_validate(user)
