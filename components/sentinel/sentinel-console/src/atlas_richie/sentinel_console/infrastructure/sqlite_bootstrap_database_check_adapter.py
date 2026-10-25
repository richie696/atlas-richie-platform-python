"""Read-only connectivity check for a deployment-owned SQLite file."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseCheckResult,
    BootstrapDatabaseCheckUnavailable,
    BootstrapDatabaseFailureReason,
    BootstrapDatabaseKind,
)
from .bootstrap_database_check_adapters import unreachable

_CHECK_TIMEOUT_SECONDS = 3.0
_READ_ONLY_PROBE = "SELECT 1"


class SQLiteBootstrapDatabaseCheckAdapter:
    """Probe only a configured path; request data never chooses the file."""

    kind = BootstrapDatabaseKind.SQLITE

    def __init__(self, database_path: Path | None = None) -> None:
        if database_path is not None and not database_path.is_absolute():
            raise ValueError("SQLite path must be absolute and deployment-owned")
        self._database_path = database_path

    async def check(
        self, candidate: BootstrapDatabaseCandidate
    ) -> BootstrapDatabaseCheckResult:
        del candidate
        if self._database_path is None:
            return unreachable(BootstrapDatabaseFailureReason.UNSUPPORTED)

        try:
            import aiosqlite
        except ImportError as error:
            raise BootstrapDatabaseCheckUnavailable from error

        database_uri = f"{self._database_path.as_uri()}?mode=ro"
        try:
            async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
                async with aiosqlite.connect(
                    database_uri,
                    uri=True,
                    timeout=_CHECK_TIMEOUT_SECONDS,
                ) as connection:
                    await connection.execute("PRAGMA query_only = ON")
                    async with connection.execute(_READ_ONLY_PROBE) as cursor:
                        await cursor.fetchone()
            return BootstrapDatabaseCheckResult(reachable=True)
        except (aiosqlite.Error, OSError, TimeoutError):
            return unreachable(BootstrapDatabaseFailureReason.CONNECTION)


__all__ = ["SQLiteBootstrapDatabaseCheckAdapter"]
