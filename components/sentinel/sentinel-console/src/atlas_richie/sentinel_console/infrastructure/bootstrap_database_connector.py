"""Read-only PostgreSQL/MySQL adapters for first-run connectivity checks."""

from __future__ import annotations

import asyncio
import ssl
from enum import IntEnum
from pathlib import Path
from typing import Any

from ..application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseChecker,
    BootstrapDatabaseCheckResult,
    BootstrapDatabaseCheckUnavailable,
    BootstrapDatabaseFailureReason,
    BootstrapDatabaseKind,
)
from .bootstrap_database_targets import (
    BootstrapDatabaseTargetPolicy,
    BootstrapDatabaseTargetRejected,
    ResolvedBootstrapDatabaseTarget,
)
from .pinned_mysql_connection import (
    PinnedHostnameMySQLConnectionMixin,
    verified_mysql_ssl_context,
)

_CHECK_TIMEOUT_SECONDS = 8.0
_SQLITE_CHECK_TIMEOUT_SECONDS = 3.0
_CONNECT_TIMEOUT_SECONDS = 3
_READ_TIMEOUT_SECONDS = 3
_POSTGRESQL_STATEMENT_TIMEOUT_MILLISECONDS = 3000
_READ_ONLY_PROBE = "SELECT 1"
_POSTGRESQL_AUTHENTICATION_STATE_CLASS = "28"


class _MySQLServerErrorCode(IntEnum):
    """Protocol error codes whose stable meaning is credential rejection."""

    DATABASE_ACCESS_DENIED = 1044
    ACCESS_DENIED = 1045


class _BootstrapDatabaseAuthenticationRejected(Exception):
    """Internal, sanitized classification for database credential failures."""


_PinnedHostnameMySQLMixin = PinnedHostnameMySQLConnectionMixin


class BootstrapDatabaseConnector(BootstrapDatabaseChecker):
    """Check remote database reachability without changing database state.

    The deployment supplies a strict destination policy. DNS is resolved once;
    PostgreSQL receives the approved address as ``hostaddr`` and MySQL connects
    to that address directly, while both drivers verify TLS against the
    original hostname. This adapter never persists or logs candidate values.
    """

    def __init__(
        self,
        target_policy: BootstrapDatabaseTargetPolicy,
        *,
        sqlite_database_path: Path | None = None,
        postgresql_root_certificate: str | None = None,
        mysql_ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if (
            sqlite_database_path is not None
            and not sqlite_database_path.is_absolute()
        ):
            raise ValueError("SQLite path must be absolute and deployment-owned")
        self._target_policy = target_policy
        self._sqlite_database_path = sqlite_database_path
        self._postgresql_root_certificate = postgresql_root_certificate
        self._mysql_ssl_context = verified_mysql_ssl_context(mysql_ssl_context)

    async def check(
        self, candidate: BootstrapDatabaseCandidate
    ) -> BootstrapDatabaseCheckResult:
        """Return a finite connectivity result; leave cancellation untouched."""
        if candidate.kind is BootstrapDatabaseKind.SQLITE:
            return await self._check_sqlite()

        if not _has_remote_connection_fields(candidate):
            return _unreachable(BootstrapDatabaseFailureReason.UNSUPPORTED)

        try:
            target = await self._target_policy.resolve(
                candidate.kind, candidate.host or "", candidate.port or 0
            )
        except BootstrapDatabaseTargetRejected:
            return _unreachable(BootstrapDatabaseFailureReason.CONNECTION)

        if candidate.kind is BootstrapDatabaseKind.POSTGRESQL:
            return await self._check_postgresql(candidate, target)
        if candidate.kind is BootstrapDatabaseKind.MYSQL:
            return await self._check_mysql(candidate, target)
        return _unreachable(BootstrapDatabaseFailureReason.UNSUPPORTED)

    async def _check_sqlite(self) -> BootstrapDatabaseCheckResult:
        """Probe only the configured local database, never a client-supplied path."""
        if self._sqlite_database_path is None:
            return _unreachable(BootstrapDatabaseFailureReason.UNSUPPORTED)

        try:
            import aiosqlite
        except ImportError as error:
            raise BootstrapDatabaseCheckUnavailable from error

        database_uri = f"{self._sqlite_database_path.as_uri()}?mode=ro"
        try:
            async with asyncio.timeout(_SQLITE_CHECK_TIMEOUT_SECONDS):
                async with aiosqlite.connect(
                    database_uri,
                    uri=True,
                    timeout=_SQLITE_CHECK_TIMEOUT_SECONDS,
                ) as connection:
                    await connection.execute("PRAGMA query_only = ON")
                    async with connection.execute(_READ_ONLY_PROBE) as cursor:
                        await cursor.fetchone()
            return BootstrapDatabaseCheckResult(reachable=True)
        except (aiosqlite.Error, OSError, TimeoutError):
            return _unreachable(BootstrapDatabaseFailureReason.CONNECTION)

    async def _check_postgresql(
        self,
        candidate: BootstrapDatabaseCandidate,
        target: ResolvedBootstrapDatabaseTarget,
    ) -> BootstrapDatabaseCheckResult:
        try:
            import psycopg
        except ImportError as error:
            raise BootstrapDatabaseCheckUnavailable from error

        failure_reason = BootstrapDatabaseFailureReason.CONNECTION
        try:
            async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
                for address in target.addresses:
                    try:
                        await _probe_postgresql_address(
                            psycopg,
                            candidate,
                            target.hostname,
                            address.compressed,
                            self._postgresql_root_certificate,
                        )
                        return BootstrapDatabaseCheckResult(reachable=True)
                    except _BootstrapDatabaseAuthenticationRejected:
                        failure_reason = BootstrapDatabaseFailureReason.AUTHENTICATION
                    except (psycopg.Error, OSError, TimeoutError):
                        continue
        except TimeoutError:
            pass
        return _unreachable(failure_reason)

    async def _check_mysql(
        self,
        candidate: BootstrapDatabaseCandidate,
        target: ResolvedBootstrapDatabaseTarget,
    ) -> BootstrapDatabaseCheckResult:
        try:
            import asyncmy
        except ImportError as error:
            raise BootstrapDatabaseCheckUnavailable from error

        failure_reason = BootstrapDatabaseFailureReason.CONNECTION
        connection_class = type(
            "_PinnedHostnameAsyncMySQLConnection",
            (_PinnedHostnameMySQLMixin, asyncmy.Connection),
            {},
        )
        try:
            async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
                for address in target.addresses:
                    connection = connection_class(
                        host=address.compressed,
                        port=candidate.port,
                        user=candidate.username,
                        password=candidate.password,
                        database=candidate.database,
                        ssl=self._mysql_ssl_context,
                        connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                        read_timeout=_READ_TIMEOUT_SECONDS,
                        autocommit=True,
                        local_infile=False,
                    )
                    connection._target_hostname = target.hostname
                    probe_completed = False
                    close_failed = False
                    try:
                        await connection.connect()
                        async with connection.cursor() as cursor:
                            await cursor.execute(_READ_ONLY_PROBE)
                            await cursor.fetchone()
                        probe_completed = True
                    except (asyncmy.errors.Error, OSError, TimeoutError) as error:
                        if _is_mysql_authentication_error(error):
                            failure_reason = (
                                BootstrapDatabaseFailureReason.AUTHENTICATION
                            )
                    finally:
                        try:
                            await connection.ensure_closed()
                        except (asyncmy.errors.Error, OSError, TimeoutError):
                            close_failed = True
                    if probe_completed:
                        if close_failed:
                            return _unreachable(
                                BootstrapDatabaseFailureReason.CONNECTION
                            )
                        return BootstrapDatabaseCheckResult(reachable=True)
        except TimeoutError:
            pass
        return _unreachable(failure_reason)


def _has_remote_connection_fields(candidate: BootstrapDatabaseCandidate) -> bool:
    return bool(
        candidate.host
        and candidate.port
        and candidate.database
        and candidate.username
        and candidate.password
    )


async def _probe_postgresql_address(
    driver: Any,
    candidate: BootstrapDatabaseCandidate,
    hostname: str,
    address: str,
    root_certificate: str | None,
) -> None:
    try:
        async with await driver.AsyncConnection.connect(
            host=hostname,
            hostaddr=address,
            port=candidate.port,
            dbname=candidate.database,
            user=candidate.username,
            password=candidate.password,
            sslmode="verify-full",
            **({"sslrootcert": root_certificate} if root_certificate else {}),
            connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            options=(
                "-c statement_timeout="
                f"{_POSTGRESQL_STATEMENT_TIMEOUT_MILLISECONDS}"
            ),
            autocommit=True,
        ) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(_READ_ONLY_PROBE)
                await cursor.fetchone()
    except driver.Error as error:
        if (error.sqlstate or "").startswith(
            _POSTGRESQL_AUTHENTICATION_STATE_CLASS
        ):
            raise _BootstrapDatabaseAuthenticationRejected from error
        raise


def _is_mysql_authentication_error(error: Exception) -> bool:
    error_code = error.args[0] if error.args else None
    return type(error_code) is int and error_code in {
        _MySQLServerErrorCode.DATABASE_ACCESS_DENIED,
        _MySQLServerErrorCode.ACCESS_DENIED,
    }


def _unreachable(
    reason: BootstrapDatabaseFailureReason,
) -> BootstrapDatabaseCheckResult:
    return BootstrapDatabaseCheckResult(reachable=False, reason=reason)


def _verified_mysql_context(
    context: ssl.SSLContext | None,
) -> ssl.SSLContext:
    return verified_mysql_ssl_context(context)
