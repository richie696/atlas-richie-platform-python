"""Facade for read-only first-run database connectivity checks."""

from __future__ import annotations

import ssl
from pathlib import Path

from ..application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseChecker,
    BootstrapDatabaseCheckResult,
    BootstrapDatabaseFailureReason,
)
from .bootstrap_database_check_adapters import (
    BootstrapDatabaseCheckAdapter,
    BootstrapDatabaseCheckAdapterRegistry,
    unreachable,
)
from .bootstrap_database_targets import BootstrapDatabaseTargetPolicy
from .mysql_bootstrap_database_check_adapter import (
    MySQLBootstrapDatabaseCheckAdapter,
)
from .postgresql_bootstrap_database_check_adapter import (
    PostgreSQLBootstrapDatabaseCheckAdapter,
)
from .sqlite_bootstrap_database_check_adapter import (
    SQLiteBootstrapDatabaseCheckAdapter,
)


class BootstrapDatabaseConnector(BootstrapDatabaseChecker):
    """Dispatch a typed setup check to a provider-specific infrastructure adapter.

    The facade owns no SQL driver or provider branch. Its default registry is
    composed from the built-in SQLite, PostgreSQL, and MySQL adapters; callers
    may append an independently implemented adapter for another database kind.
    """

    def __init__(
        self,
        target_policy: BootstrapDatabaseTargetPolicy,
        *,
        sqlite_database_path: Path | None = None,
        postgresql_root_certificate: str | None = None,
        mysql_ssl_context: ssl.SSLContext | None = None,
        additional_adapters: tuple[BootstrapDatabaseCheckAdapter, ...] = (),
    ) -> None:
        adapters = (
            SQLiteBootstrapDatabaseCheckAdapter(sqlite_database_path),
            PostgreSQLBootstrapDatabaseCheckAdapter(
                target_policy,
                root_certificate=postgresql_root_certificate,
            ),
            MySQLBootstrapDatabaseCheckAdapter(
                target_policy,
                ssl_context=mysql_ssl_context,
            ),
            *additional_adapters,
        )
        self._registry = BootstrapDatabaseCheckAdapterRegistry(adapters)

    async def check(
        self, candidate: BootstrapDatabaseCandidate
    ) -> BootstrapDatabaseCheckResult:
        """Dispatch one candidate without leaking provider-specific behavior."""
        try:
            adapter = self._registry.resolve(candidate.kind)
        except ValueError:
            return unreachable(BootstrapDatabaseFailureReason.UNSUPPORTED)
        return await adapter.check(candidate)


__all__ = ["BootstrapDatabaseConnector"]
