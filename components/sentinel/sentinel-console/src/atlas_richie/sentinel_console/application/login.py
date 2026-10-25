"""Login use case: verify credentials and issue opaque browser credentials."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import hashlib
import re
from secrets import token_urlsafe
from typing import Callable, TypeVar
from uuid import uuid4

from ..domain.account_username import AccountUsername
from ..domain.session import ActiveAccountSession, SessionIdentity
from .login_ports import (
    LoginAttemptLimiter,
    LoginAuthorityUnavailable,
    LoginCredentialReader,
    LoginSessionWriter,
    PasswordVerifier,
)

_OPAQUE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
_T = TypeVar("_T")


class LoginOutcome(StrEnum):
    """Finite protocol-level login outcomes without account enumeration."""

    AUTHENTICATED = "authenticated"
    REJECTED = "rejected"
    RATE_LIMITED = "rate_limited"


@dataclass(frozen=True, slots=True)
class LoginSession:
    """Successful login result; raw credentials are deliberately repr-hidden."""

    identity: SessionIdentity
    session_token: str = field(repr=False)
    csrf_nonce: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class LoginResult:
    """A login outcome with only the response facts required by the adapter."""

    outcome: LoginOutcome
    session: LoginSession | None = None
    retry_after_ms: int | None = None

    def __post_init__(self) -> None:
        if (self.outcome is LoginOutcome.AUTHENTICATED) != (self.session is not None):
            raise ValueError("authenticated outcomes require exactly one session")
        if (self.outcome is LoginOutcome.RATE_LIMITED) != (
            self.retry_after_ms is not None
        ):
            raise ValueError("rate-limited outcomes require a retry delay")


class Login:
    """Coordinate username identity, password verification and session issuance."""

    def __init__(
        self,
        *,
        credential_reader: LoginCredentialReader,
        session_writer: LoginSessionWriter,
        attempt_limiter: LoginAttemptLimiter,
        password_hasher: PasswordVerifier,
        session_ttl: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        token_factory: Callable[[int], str] = token_urlsafe,
    ) -> None:
        if session_ttl <= timedelta(0):
            raise ValueError("session_ttl must be positive")
        self._credential_reader = credential_reader
        self._session_writer = session_writer
        self._attempt_limiter = attempt_limiter
        self._password_hasher = password_hasher
        self._session_ttl = session_ttl
        self._clock = clock
        self._token_factory = token_factory

    async def execute(
        self,
        *,
        username: str,
        password: str,
        client_identity_digest: str,
        previous_session_token: str | None,
    ) -> LoginResult:
        """Authenticate without returning distinct unknown/wrong/disabled results."""
        retry_after_ms = await self._limiter_call(
            self._attempt_limiter.retry_after_ms(client_identity_digest)
        )
        if retry_after_ms is not None:
            if isinstance(retry_after_ms, bool) or not isinstance(retry_after_ms, int):
                raise LoginAuthorityUnavailable(
                    "login limiter returned an invalid delay"
                )
            return LoginResult(
                LoginOutcome.RATE_LIMITED,
                retry_after_ms=max(0, min(retry_after_ms, 300_000)),
            )

        try:
            account_username = AccountUsername(username)
        except (TypeError, ValueError):
            await asyncio.to_thread(
                self._password_hasher.verify_unknown_account, password
            )
            await self._limiter_call(
                self._attempt_limiter.record_failure(client_identity_digest)
            )
            return LoginResult(LoginOutcome.REJECTED)

        credential = await self._credential_reader.read_login_credential(
            account_username.lookup_key
        )
        if credential is None or credential.status != "active":
            await asyncio.to_thread(
                self._password_hasher.verify_unknown_account, password
            )
            await self._limiter_call(
                self._attempt_limiter.record_failure(client_identity_digest)
            )
            return LoginResult(LoginOutcome.REJECTED)

        if not await asyncio.to_thread(
            self._password_hasher.verify_account_password,
            credential.password_hash,
            password,
        ):
            await self._limiter_call(
                self._attempt_limiter.record_failure(client_identity_digest)
            )
            return LoginResult(LoginOutcome.REJECTED)

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return an aware datetime")
        session_token = self._token_factory(32)
        csrf_nonce = self._token_factory(32)
        if (
            not isinstance(session_token, str)
            or not isinstance(csrf_nonce, str)
            or _OPAQUE_TOKEN_PATTERN.fullmatch(session_token) is None
            or _OPAQUE_TOKEN_PATTERN.fullmatch(csrf_nonce) is None
            or session_token == csrf_nonce
        ):
            raise ValueError("token factory returned invalid or reused credentials")

        session_epoch = str(uuid4())
        try:
            identity = SessionIdentity.from_active_session(
                ActiveAccountSession(
                    account_id=credential.account_id,
                    username=credential.username,
                    role_id=credential.role_id,
                    session_epoch=session_epoch,
                )
            )
        except ValueError:
            raise LoginAuthorityUnavailable(
                "credential authority returned an unsupported role"
            ) from None

        previous_digest = _previous_session_digest(previous_session_token)
        await self._limiter_call(
            self._attempt_limiter.record_success(client_identity_digest)
        )
        issued = await self._session_writer.issue_login_session(
            account_id=credential.account_id,
            expected_password_hash=credential.password_hash,
            session_digest=_token_digest(session_token),
            csrf_digest=_token_digest(csrf_nonce),
            session_epoch=session_epoch,
            created_at=now,
            expires_at=now + self._session_ttl,
            previous_session_digest=previous_digest,
        )
        if not issued:
            await self._limiter_call(
                self._attempt_limiter.record_failure(client_identity_digest)
            )
            return LoginResult(LoginOutcome.REJECTED)

        return LoginResult(
            LoginOutcome.AUTHENTICATED,
            LoginSession(identity, session_token, csrf_nonce),
        )

    @staticmethod
    async def _limiter_call(operation: Awaitable[_T]) -> _T:
        """Translate deployment limiter failures into a safe authority failure."""
        try:
            return await operation
        except LoginAuthorityUnavailable:
            raise
        except Exception:
            raise LoginAuthorityUnavailable(
                "login attempt authority is unavailable"
            ) from None


def _token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _previous_session_digest(value: str | None) -> str | None:
    if value is None or _OPAQUE_TOKEN_PATTERN.fullmatch(value) is None:
        return None
    return _token_digest(value)
