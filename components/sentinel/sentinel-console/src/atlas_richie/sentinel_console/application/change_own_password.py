"""Change the authenticated account's password and invalidate its sessions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import hashlib
import hmac
from typing import Protocol, TypeVar

from ..domain.account_password import AccountPassword

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class OwnPasswordActor:
    """Hashed browser proofs and account identity from the current session."""

    account_id: str
    session_digest: str
    csrf_digest: str = field(repr=False)


class OwnPasswordReader(Protocol):
    """Read only the active account's encoded password hash."""

    async def read_password_hash(
        self, actor: OwnPasswordActor, now: datetime
    ) -> str | None:
        """Return a hash only for the actor's active session/CSRF proof."""


class OwnPasswordWriter(Protocol):
    """Persist a password change and revocation as one transaction."""

    async def change_password(
        self,
        *,
        actor: OwnPasswordActor,
        expected_password_hash: str,
        replacement_password_hash: str,
        request_id: str,
        now: datetime,
    ) -> bool:
        """Return true on commit; raise a safe error if authority changed."""


class OwnPasswordHasher(Protocol):
    """Hash and verify account passwords without exposing a library type."""

    def verify_password(self, encoded_hash: str, candidate: str) -> bool:
        """Check the current password against its stored one-way hash."""

    def hash_password(self, password: str) -> str:
        """Create a one-way password hash for a validated replacement."""


class OwnPasswordAttemptLimiter(Protocol):
    """Persist bounded retry state by an opaque account-scoped digest."""

    async def retry_after_ms(self, attempt_subject_digest: str) -> int | None:
        """Return a retry delay while this account's change is blocked."""

    async def record_failure(self, attempt_subject_digest: str) -> None:
        """Record an invalid current-password attempt."""

    async def record_success(self, attempt_subject_digest: str) -> None:
        """Clear the account's failure window after current-password proof."""


class OwnPasswordUnauthenticated(RuntimeError):
    """The account or browser session is not currently authenticated."""


class OwnPasswordCurrentPasswordInvalid(RuntimeError):
    """The authenticated user supplied an incorrect current password."""


class OwnPasswordRateLimited(RuntimeError):
    """Current-password attempts are temporarily blocked."""

    def __init__(self, retry_after_ms: int) -> None:
        if (
            isinstance(retry_after_ms, bool)
            or not isinstance(retry_after_ms, int)
            or not 1 <= retry_after_ms <= 300_000
        ):
            raise ValueError("retry delay is outside the supported range")
        self.retry_after_ms = retry_after_ms
        super().__init__("own-password attempt is rate limited")


class OwnPasswordCsrfFailed(RuntimeError):
    """The persisted browser session rejects the submitted CSRF proof."""


class OwnPasswordUnavailable(RuntimeError):
    """The password authority cannot safely complete the operation."""


class OwnPasswordDisposition(StrEnum):
    """The required browser action after a confirmed password change."""

    REAUTHENTICATE = "reauthenticate"


@dataclass(frozen=True, slots=True)
class OwnPasswordResult:
    """Safe result returned after the password and session transaction commits."""

    disposition: OwnPasswordDisposition


class ChangeOwnPassword:
    """Verify the current password then atomically replace it and revoke sessions."""

    def __init__(
        self,
        *,
        reader: OwnPasswordReader,
        writer: OwnPasswordWriter,
        password_hasher: OwnPasswordHasher,
        attempt_limiter: OwnPasswordAttemptLimiter,
        attempt_hmac_key: bytes,
    ) -> None:
        if not isinstance(attempt_hmac_key, bytes) or len(attempt_hmac_key) < 32:
            raise ValueError("own-password attempt HMAC key must be at least 32 bytes")
        self._reader = reader
        self._writer = writer
        self._password_hasher = password_hasher
        self._attempt_limiter = attempt_limiter
        self._attempt_hmac_key = attempt_hmac_key

    async def execute(
        self,
        *,
        actor: OwnPasswordActor,
        current_password: str,
        new_password: AccountPassword,
        request_id: str,
        now: datetime,
    ) -> OwnPasswordResult:
        """Do not return until the new hash and global session revocation commit."""
        encoded_hash = await self._reader.read_password_hash(actor, now)
        if encoded_hash is None:
            raise OwnPasswordUnauthenticated("current password is not valid")
        attempt_subject_digest = self._attempt_subject_digest(actor.account_id)
        retry_after_ms = await self._limiter_call(
            self._attempt_limiter.retry_after_ms(attempt_subject_digest)
        )
        if retry_after_ms is not None:
            if (
                isinstance(retry_after_ms, bool)
                or not isinstance(retry_after_ms, int)
                or retry_after_ms < 1
            ):
                raise OwnPasswordUnavailable(
                    "attempt limiter returned an invalid delay"
                )
            raise OwnPasswordRateLimited(min(retry_after_ms, 300_000))
        if not await asyncio.to_thread(
            self._password_hasher.verify_password, encoded_hash, current_password
        ):
            await self._limiter_call(
                self._attempt_limiter.record_failure(attempt_subject_digest)
            )
            raise OwnPasswordCurrentPasswordInvalid("current password is not valid")

        # The correct current password proves control; clear prior failures before
        # the write transaction, so an already committed change cannot be followed
        # by a limiter-store error that masks its successful receipt.
        await self._limiter_call(
            self._attempt_limiter.record_success(attempt_subject_digest)
        )

        replacement_hash = await asyncio.to_thread(
            self._password_hasher.hash_password, new_password.value
        )
        changed = await self._writer.change_password(
            actor=actor,
            expected_password_hash=encoded_hash,
            replacement_password_hash=replacement_hash,
            request_id=request_id,
            now=now,
        )
        if not changed:
            raise OwnPasswordUnauthenticated("current session is no longer valid")
        return OwnPasswordResult(OwnPasswordDisposition.REAUTHENTICATE)

    async def _limiter_call(self, operation: Awaitable[_T]) -> _T:
        """Fail closed when the shared attempt-limit authority is unavailable."""
        try:
            return await operation
        except Exception:
            raise OwnPasswordUnavailable(
                "own-password attempt authority is unavailable"
            ) from None

    def _attempt_subject_digest(self, account_id: str) -> str:
        if not isinstance(account_id, str) or not account_id:
            raise OwnPasswordUnavailable("session account identity is invalid")
        scoped_identity = b"sentinel-console:own-password:v1\x00" + account_id.encode(
            "utf-8"
        )
        return hmac.new(
            self._attempt_hmac_key, scoped_identity, hashlib.sha256
        ).hexdigest()
