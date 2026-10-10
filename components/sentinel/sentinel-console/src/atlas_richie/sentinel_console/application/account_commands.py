"""Account mutation use case and its persistence-facing contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from ..domain.account_password import AccountPassword
from ..domain.account_username import AccountUsername
from ..domain.session import AccountRole
from .account_directory_ports import AccountDirectoryItem

_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_FINGERPRINT_DOMAIN = b"atlas-richie-sentinel:account-command:v1\x00"


class AccountCommandKind(StrEnum):
    """Finite account mutation variants supported by the Console contract."""

    CREATE = "create"
    STATUS = "status"
    ROLE = "role"


class AccountOperationStatus(StrEnum):
    """Durable final outcomes for synchronous account commands."""

    COMPLETED = "completed"
    REJECTED = "rejected"


class AccountCommandReason(StrEnum):
    """Business rejection reasons exposed by account-operation receipts."""

    USERNAME_TAKEN = "username_taken"
    LAST_ADMIN = "last_admin"
    BUILT_IN = "built_in"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class AccountCommandActor:
    """Hashed browser proof passed from the HTTP boundary to the writer."""

    account_id: str
    session_digest: str
    csrf_digest: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AccountOperationActor:
    """Session identity used to authorize safe command-receipt reads."""

    account_id: str
    session_digest: str


@dataclass(frozen=True, slots=True)
class AccountMutation:
    """Validated, immutable account command; password is hidden from repr."""

    request_key: str
    kind: AccountCommandKind
    username: AccountUsername | None = None
    password: AccountPassword | None = field(default=None, repr=False)
    role_id: AccountRole | None = None
    account_id: str | None = None
    expected_revision: int | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        if self.kind is AccountCommandKind.CREATE:
            valid = (
                self.username is not None
                and self.password is not None
                and self.role_id is not None
                and self.account_id is None
                and self.expected_revision is None
                and self.status is None
            )
        elif self.kind is AccountCommandKind.STATUS:
            valid = (
                self.account_id is not None
                and self.expected_revision is not None
                and self.status in {"active", "disabled"}
                and self.username is None
                and self.password is None
                and self.role_id is None
            )
        else:
            valid = (
                self.account_id is not None
                and self.expected_revision is not None
                and self.role_id is not None
                and self.username is None
                and self.password is None
                and self.status is None
            )
        if not valid:
            raise ValueError("account command fields do not match its kind")

    def fingerprint_payload(self) -> bytes:
        """Return canonical bytes for HMAC only; callers must never persist them."""
        payload: dict[str, str] = {
            "kind": self.kind.value,
            "requestKey": self.request_key,
        }
        if self.kind is AccountCommandKind.CREATE:
            assert self.username is not None and self.password is not None
            assert self.role_id is not None
            payload["username"] = self.username.value
            payload["password"] = self.password.value
            payload["roleId"] = self.role_id.value
        elif self.kind is AccountCommandKind.STATUS:
            assert self.account_id is not None and self.expected_revision is not None
            assert self.status is not None
            payload["accountId"] = self.account_id
            payload["revision"] = str(self.expected_revision)
            payload["status"] = self.status
        else:
            assert self.account_id is not None and self.expected_revision is not None
            assert self.role_id is not None
            payload["accountId"] = self.account_id
            payload["revision"] = str(self.expected_revision)
            payload["roleId"] = self.role_id.value
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class KeyedFingerprint:
    """One versioned, domain-separated HMAC of a command payload."""

    key_id: str
    digest: str


@dataclass(frozen=True, slots=True)
class AccountOperation:
    """Safe immutable command result retained independently of current account state."""

    request_key: str
    status: AccountOperationStatus
    account: AccountDirectoryItem | None = None
    reason: AccountCommandReason | None = None

    def __post_init__(self) -> None:
        if self.status is AccountOperationStatus.COMPLETED:
            valid = self.account is not None and self.reason is None
        else:
            valid = self.account is None and self.reason is not None
        if not valid:
            raise ValueError("account operation result is inconsistent")


class AccountCommandUnauthenticated(RuntimeError):
    """The browser session is no longer active at the write boundary."""


class AccountCommandForbidden(RuntimeError):
    """The current account no longer has administrative authority."""


class AccountCommandCsrfFailed(RuntimeError):
    """The persisted session's CSRF nonce no longer matches the submitted proof."""


class AccountCommandIdempotencyConflict(RuntimeError):
    """An idempotency key was reused with another actor or semantic request."""


class AccountCommandUnavailable(RuntimeError):
    """Account command storage cannot safely complete the operation."""


class AccountOperationUnavailable(RuntimeError):
    """Durable account-operation history cannot be safely read."""


class AccountOperationReader(Protocol):
    """Read a durable operation result owned by the authenticated actor."""

    async def read_operation(
        self, request_key: str, actor: AccountOperationActor
    ) -> AccountOperation | None:
        """Return an operation only for its original actor."""


class AccountCommandStore(AccountOperationReader, Protocol):
    """Commit account mutation, safe receipt, and audit fact atomically."""

    async def execute_command(
        self,
        *,
        actor: AccountCommandActor,
        command: AccountMutation,
        fingerprints: tuple[KeyedFingerprint, ...],
        password_hash: str | None,
        account_id: str,
        operation_id: str,
        audit_event_id: str,
        request_id: str,
        now: datetime,
    ) -> AccountOperation:
        """Revalidate authority and perform or recover exactly one operation."""


class AccountPasswordHasher(Protocol):
    """Hash a validated password without exposing the hashing dependency."""

    def hash_password(self, password: str) -> str:
        """Return a one-way encoded password hash."""


class MutateAccount:
    """Validate/hash/fingerprint account commands before transactional persistence."""

    def __init__(
        self,
        *,
        store: AccountCommandStore,
        password_hasher: AccountPasswordHasher,
        fingerprint_keys: Mapping[str, bytes],
        active_fingerprint_key_id: str,
    ) -> None:
        if not fingerprint_keys or active_fingerprint_key_id not in fingerprint_keys:
            raise ValueError("an active account-command fingerprint key is required")
        for key_id, key in fingerprint_keys.items():
            if _KEY_ID_PATTERN.fullmatch(key_id) is None:
                raise ValueError("account-command fingerprint key ID is invalid")
            if not isinstance(key, bytes) or len(key) < 32:
                raise ValueError(
                    "account-command fingerprint keys must be at least 32 bytes"
                )
        self._store = store
        self._password_hasher = password_hasher
        self._fingerprint_keys = dict(fingerprint_keys)
        self._active_fingerprint_key_id = active_fingerprint_key_id

    async def execute(
        self,
        *,
        actor: AccountCommandActor,
        command: AccountMutation,
        request_id: str,
        now: datetime,
    ) -> AccountOperation:
        """Produce versioned fingerprints and delegate one atomic side effect."""
        canonical_payload = _FINGERPRINT_DOMAIN + command.fingerprint_payload()
        ordered_key_ids = [self._active_fingerprint_key_id]
        ordered_key_ids.extend(
            key_id
            for key_id in self._fingerprint_keys
            if key_id != self._active_fingerprint_key_id
        )
        fingerprints = tuple(
            KeyedFingerprint(
                key_id,
                hmac.new(
                    self._fingerprint_keys[key_id], canonical_payload, hashlib.sha256
                ).hexdigest(),
            )
            for key_id in ordered_key_ids
        )
        password_hash = (
            self._password_hasher.hash_password(command.password.value)
            if command.password is not None
            else None
        )
        return await self._store.execute_command(
            actor=actor,
            command=command,
            fingerprints=fingerprints,
            password_hash=password_hash,
            account_id=str(uuid4()),
            operation_id=str(uuid4()),
            audit_event_id=str(uuid4()),
            request_id=request_id,
            now=now,
        )

    async def read_operation(
        self, request_key: str, actor: AccountOperationActor
    ) -> AccountOperation | None:
        """Read an original result without exposing another actor's operation."""
        return await self._store.read_operation(request_key, actor)


def digest_browser_value(value: str) -> str:
    """Hash an opaque session/CSRF value before passing it to persistence."""
    return hashlib.sha256(value.encode("ascii")).hexdigest()
