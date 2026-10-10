"""Application contracts for idempotent source registration and updates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from ..domain.registered_sources import RegisteredConfigurationSource
from .check_registered_source import SourceConnectionInput


class SourceMutationKind(StrEnum):
    """Supported source-registry mutation types."""

    REGISTER = "register"
    UPDATE = "update"


class SourceMutationStatus(StrEnum):
    """Safe operation facts returned by source mutation authorities."""

    PENDING = "pending"
    COMPLETED = "completed"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"


class SourceMutationRejection(StrEnum):
    """Finite reasons for a rejected source operation."""

    VALIDATION = "validation"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class RegisteredSourceMutation:
    """Idempotent registration/update input with ephemeral connection secrets."""

    kind: SourceMutationKind
    request_key: str
    name: str
    source: SourceConnectionInput

    def __post_init__(self) -> None:
        if self.kind is SourceMutationKind.REGISTER:
            if self.source.source_id is not None:
                raise ValueError("register cannot target an existing source")
        elif self.kind is SourceMutationKind.UPDATE:
            if self.source.source_id is None:
                raise ValueError("update must target an existing source revision")
        else:
            raise ValueError("source mutation kind is invalid")
        if not self.request_key or len(self.request_key) > 128:
            raise ValueError("source mutation request key is invalid")
        if not self.name.strip() or len(self.name) > 200:
            raise ValueError("source mutation name is invalid")


@dataclass(frozen=True, slots=True)
class RegisteredSourceOperation:
    """Safe command/query observation; it never contains submitted credentials."""

    request_key: str
    status: SourceMutationStatus
    record: RegisteredConfigurationSource | None = None
    reason: SourceMutationRejection | None = None

    def __post_init__(self) -> None:
        if not self.request_key or len(self.request_key) > 128:
            raise ValueError("source operation request key is invalid")
        if (self.status is SourceMutationStatus.COMPLETED) != (
            self.record is not None
        ):
            raise ValueError("completed source operation requires exactly one record")
        if (self.status is SourceMutationStatus.REJECTED) != (
            self.reason is not None
        ):
            raise ValueError("rejected source operation requires exactly one reason")
        if self.status is SourceMutationStatus.NOT_FOUND and (
            self.record is not None or self.reason is not None
        ):
            raise ValueError("not-found source operation cannot carry a result")


class SourceMutationAuthorityUnavailable(RuntimeError):
    """The durable source-registry mutation authority is unavailable."""


class SourceMutationIdempotencyConflict(RuntimeError):
    """An idempotency key was reused for a different source mutation."""


class SourceMutationUnauthenticated(RuntimeError):
    """The browser session became inactive before the transaction committed."""


class SourceMutationForbidden(RuntimeError):
    """The actor does not own an operation or cannot mutate sources."""


class SourceMutationRateLimited(RuntimeError):
    """The authority temporarily rate-limited source mutation operations."""

    def __init__(self, retry_after_ms: int) -> None:
        if type(retry_after_ms) is not int or not 0 <= retry_after_ms <= 300_000:
            raise ValueError("retry delay must be bounded")
        self.retry_after_ms = retry_after_ms
        super().__init__("source mutation rate limited")


class RegisteredSourceMutationAuthority(Protocol):
    """Durable transaction boundary for registry, credentials and operation facts."""

    async def mutate(
        self,
        command: RegisteredSourceMutation,
        *,
        actor_id: str,
        session_digest: str,
        csrf_digest: str,
        request_id: str,
        now: datetime,
    ) -> RegisteredSourceOperation:
        """Persist safe receipt/audit and protected credentials atomically."""

    async def read_operation(
        self, request_key: str, *, actor_id: str, session_digest: str
    ) -> RegisteredSourceOperation | None:
        """Read only the original actor-owned operation result."""
