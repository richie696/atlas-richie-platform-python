"""Provider-neutral registry and shared facts for bootstrap DB check adapters."""

from __future__ import annotations

from typing import Protocol

from ..application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseCheckResult,
    BootstrapDatabaseFailureReason,
    BootstrapDatabaseKind,
)
from .bootstrap_database_targets import (
    BootstrapDatabaseTargetPolicy,
    BootstrapDatabaseTargetRejected,
    ResolvedBootstrapDatabaseTarget,
)


class BootstrapDatabaseCheckAdapter(Protocol):
    """Perform one database product's bounded, read-only connectivity probe."""

    kind: BootstrapDatabaseKind

    async def check(
        self, candidate: BootstrapDatabaseCandidate
    ) -> BootstrapDatabaseCheckResult:
        """Return a finite result without leaking provider diagnostics."""


class BootstrapDatabaseCheckAdapterRegistry:
    """Dispatch typed candidates to exactly one registered check adapter."""

    def __init__(self, adapters: tuple[BootstrapDatabaseCheckAdapter, ...]) -> None:
        by_kind = {adapter.kind: adapter for adapter in adapters}
        if not adapters or len(by_kind) != len(adapters):
            raise ValueError("bootstrap database check adapters must be unique")
        self._adapters = by_kind

    def resolve(self, kind: BootstrapDatabaseKind) -> BootstrapDatabaseCheckAdapter:
        """Return the one adapter registered for this database kind."""
        try:
            return self._adapters[kind]
        except (KeyError, TypeError):
            raise ValueError("bootstrap database kind is unsupported") from None


def has_remote_connection_fields(candidate: BootstrapDatabaseCandidate) -> bool:
    """Report whether all required remote credentials are present."""
    return bool(
        candidate.host
        and candidate.port
        and candidate.database
        and candidate.username
        and candidate.password
    )


async def resolve_remote_target(
    target_policy: BootstrapDatabaseTargetPolicy,
    candidate: BootstrapDatabaseCandidate,
) -> ResolvedBootstrapDatabaseTarget | None:
    """Resolve and pin a candidate target, mapping denied input to no target."""
    try:
        return await target_policy.resolve(
            candidate.kind, candidate.host or "", candidate.port or 0
        )
    except BootstrapDatabaseTargetRejected:
        return None


def unreachable(
    reason: BootstrapDatabaseFailureReason,
) -> BootstrapDatabaseCheckResult:
    """Build the stable non-secret result used by all provider adapters."""
    return BootstrapDatabaseCheckResult(reachable=False, reason=reason)


__all__ = [
    "BootstrapDatabaseCheckAdapter",
    "BootstrapDatabaseCheckAdapterRegistry",
    "has_remote_connection_fields",
    "resolve_remote_target",
    "unreachable",
]
