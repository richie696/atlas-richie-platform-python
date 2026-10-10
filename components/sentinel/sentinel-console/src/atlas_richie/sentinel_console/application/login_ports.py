"""Consumer-owned boundaries for credential lookup and login session writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LoginCredential:
    """Minimal credential record; its hash is never part of an HTTP response."""

    account_id: str
    username: str
    role_id: str
    status: str
    password_hash: str = field(repr=False)


class LoginCredentialReader(Protocol):
    """Read one account's credential facts by canonical username digest."""

    async def read_login_credential(self, username_key: str) -> LoginCredential | None:
        """Return a credential row or ``None`` without accepting a raw password."""


class LoginSessionWriter(Protocol):
    """Atomically issue a hashed browser session and record last-login time."""

    async def issue_login_session(
        self,
        *,
        account_id: str,
        session_digest: str,
        csrf_digest: str,
        session_epoch: str,
        created_at: datetime,
        expires_at: datetime,
        previous_session_digest: str | None,
    ) -> bool:
        """Return false if the account is no longer eligible to authenticate."""


class LoginAttemptLimiter(Protocol):
    """Deployment-owned attempt policy; implementations must be multi-worker safe."""

    async def retry_after_ms(self, client_identity_digest: str) -> int | None:
        """Return a bounded retry delay when this client is currently limited."""

    async def record_failure(self, client_identity_digest: str) -> None:
        """Record one failed attempt using the limiter's configured policy."""

    async def record_success(self, client_identity_digest: str) -> None:
        """Clear or reduce the client's failure state after successful login."""


class PasswordVerifier(Protocol):
    """Verify a one-way encoded password hash without exposing its library type."""

    def verify_password(self, encoded_hash: str, candidate: str) -> bool:
        """Return whether the candidate matches the encoded hash."""

    def verify_account_password(
        self, encoded_hash: str | None, candidate: str
    ) -> bool:
        """Verify an account or execute the dummy path for malformed/absent hashes."""

    def verify_unknown_account(self, candidate: str) -> None:
        """Perform the same password-hash work when no eligible hash is available."""


class LoginAuthorityUnavailable(RuntimeError):
    """Credential, session, or rate-limit authority cannot safely serve login."""
