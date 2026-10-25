"""Application contract for a read-only first-run database connectivity check."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class BootstrapDatabaseKind(StrEnum):
    """Database products accepted by the first-run setup contract."""

    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"


class BootstrapDatabaseFailureReason(StrEnum):
    """Finite reasons that are safe to show to a setup operator."""

    AUTHENTICATION = "authentication"
    CONNECTION = "connection"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class BootstrapDatabaseCandidate:
    """Ephemeral connection input; credentials never appear in repr/equality."""

    kind: BootstrapDatabaseKind
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class BootstrapDatabaseCheckResult:
    """Read-only reachability fact with a protocol-bounded failure reason."""

    reachable: bool
    reason: BootstrapDatabaseFailureReason | None = None

    def __post_init__(self) -> None:
        if self.reachable == (self.reason is not None):
            raise ValueError("reachability and failure reason are inconsistent")


class BootstrapDatabaseCheckUnavailable(RuntimeError):
    """The configured checker cannot produce a reliable result."""


class BootstrapDatabaseChecker(Protocol):
    """Check a candidate without migration, persistence, or credential logging."""

    async def check(
        self, candidate: BootstrapDatabaseCandidate
    ) -> BootstrapDatabaseCheckResult:
        """Return a bounded connectivity fact or raise on checker unavailability."""
