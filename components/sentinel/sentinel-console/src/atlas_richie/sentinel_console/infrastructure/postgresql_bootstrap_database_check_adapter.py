"""Address-pinned PostgreSQL connectivity checks with verified TLS."""

from __future__ import annotations

import asyncio
from typing import Any

from ..application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseCheckResult,
    BootstrapDatabaseCheckUnavailable,
    BootstrapDatabaseFailureReason,
    BootstrapDatabaseKind,
)
from .bootstrap_database_check_adapters import (
    has_remote_connection_fields,
    resolve_remote_target,
    unreachable,
)
from .bootstrap_database_targets import BootstrapDatabaseTargetPolicy

_CHECK_TIMEOUT_SECONDS = 8.0
_CONNECT_TIMEOUT_SECONDS = 3
_STATEMENT_TIMEOUT_MILLISECONDS = 3000
_READ_ONLY_PROBE = "SELECT 1"
_AUTHENTICATION_STATE_CLASS = "28"
_PASSWORD_REJECTION_MARKER = "password authentication failed"


class BootstrapDatabaseAuthenticationRejected(Exception):
    """Internal, sanitized classification for credential failures."""


class PostgreSQLBootstrapDatabaseCheckAdapter:
    """Check each allowlisted address without exposing driver diagnostics."""

    kind = BootstrapDatabaseKind.POSTGRESQL

    def __init__(
        self,
        target_policy: BootstrapDatabaseTargetPolicy,
        *,
        root_certificate: str | None = None,
    ) -> None:
        self._target_policy = target_policy
        self._root_certificate = root_certificate

    async def check(
        self, candidate: BootstrapDatabaseCandidate
    ) -> BootstrapDatabaseCheckResult:
        if not has_remote_connection_fields(candidate):
            return unreachable(BootstrapDatabaseFailureReason.UNSUPPORTED)
        target = await resolve_remote_target(self._target_policy, candidate)
        if target is None:
            return unreachable(BootstrapDatabaseFailureReason.CONNECTION)

        try:
            import psycopg
        except ImportError as error:
            raise BootstrapDatabaseCheckUnavailable from error

        reason = BootstrapDatabaseFailureReason.CONNECTION
        try:
            async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
                for address in target.addresses:
                    try:
                        await probe_postgresql_address(
                            psycopg,
                            candidate,
                            target.hostname,
                            address.compressed,
                            self._root_certificate,
                        )
                        return BootstrapDatabaseCheckResult(reachable=True)
                    except BootstrapDatabaseAuthenticationRejected:
                        reason = BootstrapDatabaseFailureReason.AUTHENTICATION
                    except (psycopg.Error, OSError, TimeoutError) as error:
                        if is_postgresql_authentication_error(error):
                            reason = BootstrapDatabaseFailureReason.AUTHENTICATION
        except TimeoutError:
            pass
        return unreachable(reason)


async def probe_postgresql_address(
    driver: Any,
    candidate: BootstrapDatabaseCandidate,
    hostname: str,
    address: str,
    root_certificate: str | None,
) -> None:
    """Issue the constant read-only probe using IP pin and hostname TLS."""
    try:
        async with (
            await driver.AsyncConnection.connect(
                host=hostname,
                hostaddr=address,
                port=candidate.port,
                dbname=candidate.database,
                user=candidate.username,
                password=candidate.password,
                sslmode="verify-full",
                **({"sslrootcert": root_certificate} if root_certificate else {}),
                connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                options=f"-c statement_timeout={_STATEMENT_TIMEOUT_MILLISECONDS}",
                autocommit=True,
            ) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(_READ_ONLY_PROBE)
            await cursor.fetchone()
    except driver.Error as error:
        if is_postgresql_authentication_error(error):
            raise BootstrapDatabaseAuthenticationRejected from error
        raise


def is_postgresql_authentication_error(error: BaseException) -> bool:
    """Normalize SQLSTATE and libpq connect-text auth rejection safely."""
    sqlstate = getattr(error, "sqlstate", None)
    if isinstance(sqlstate, str) and sqlstate.startswith(_AUTHENTICATION_STATE_CLASS):
        return True

    pg_connection = getattr(error, "pgconn", None)
    diagnostic = getattr(pg_connection, "error_message", b"")
    if isinstance(diagnostic, bytes):
        diagnostic_text = diagnostic.decode("utf-8", errors="replace")
    else:
        diagnostic_text = str(diagnostic)
    return _PASSWORD_REJECTION_MARKER in f"{diagnostic_text} {error}".casefold()


__all__ = [
    "BootstrapDatabaseAuthenticationRejected",
    "PostgreSQLBootstrapDatabaseCheckAdapter",
    "is_postgresql_authentication_error",
    "probe_postgresql_address",
]
