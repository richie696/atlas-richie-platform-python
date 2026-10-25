"""Local operator recovery for the built-in administrator password."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..domain.account_password import AccountPassword


@dataclass(frozen=True, slots=True)
class AdminPasswordRecoveryResult:
    """Safe outcome of recovering the built-in administrator account."""

    username: str
    revoked_sessions: int


class BuiltInAdminPasswordRecoveryStore(Protocol):
    """Persistence boundary for one audited local administrator recovery."""

    async def recover_built_in_admin_password(
        self, *, password_hash: str, now: datetime, event_id: str, request_id: str
    ) -> AdminPasswordRecoveryResult:
        """Replace the built-in admin hash and revoke its sessions atomically."""


class PasswordHasher(Protocol):
    """One-way password hashing port used by account workflows."""

    def hash_password(self, password: str) -> str:
        """Return a password hash without retaining the submitted value."""


class RecoverBuiltInAdminPassword:
    """Validate a local operator's password and persist its recovery safely."""

    def __init__(
        self, *, store: BuiltInAdminPasswordRecoveryStore, password_hasher: PasswordHasher
    ) -> None:
        self._store = store
        self._password_hasher = password_hasher

    async def execute(
        self, *, password: str, now: datetime, event_id: str, request_id: str
    ) -> AdminPasswordRecoveryResult:
        """Validate the shared password policy, hash, then delegate atomically."""
        validated = AccountPassword(password)
        password_hash = self._password_hasher.hash_password(validated.value)
        return await self._store.recover_built_in_admin_password(
            password_hash=password_hash,
            now=now,
            event_id=event_id,
            request_id=request_id,
        )
