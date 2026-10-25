"""Address-pinned MySQL connectivity checks with hostname-verified TLS."""

from __future__ import annotations

import asyncio
import ssl
from enum import IntEnum

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
from .pinned_mysql_connection import (
    PinnedHostnameMySQLConnectionMixin,
    verified_mysql_ssl_context,
)

_CHECK_TIMEOUT_SECONDS = 8.0
_CONNECT_TIMEOUT_SECONDS = 3
_READ_TIMEOUT_SECONDS = 3
_READ_ONLY_PROBE = "SELECT 1"


class _MySQLServerErrorCode(IntEnum):
    """Protocol error codes whose stable meaning is credential rejection."""

    DATABASE_ACCESS_DENIED = 1044
    ACCESS_DENIED = 1045


class MySQLBootstrapDatabaseCheckAdapter:
    """Check MySQL through approved IPs and preserve TLS hostname identity."""

    kind = BootstrapDatabaseKind.MYSQL

    def __init__(
        self,
        target_policy: BootstrapDatabaseTargetPolicy,
        *,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._target_policy = target_policy
        self._ssl_context = verified_mysql_ssl_context(ssl_context)

    async def check(
        self, candidate: BootstrapDatabaseCandidate
    ) -> BootstrapDatabaseCheckResult:
        if not has_remote_connection_fields(candidate):
            return unreachable(BootstrapDatabaseFailureReason.UNSUPPORTED)
        target = await resolve_remote_target(self._target_policy, candidate)
        if target is None:
            return unreachable(BootstrapDatabaseFailureReason.CONNECTION)

        try:
            import asyncmy
        except ImportError as error:
            raise BootstrapDatabaseCheckUnavailable from error

        connection_class = type(
            "_PinnedHostnameAsyncMySQLConnection",
            (PinnedHostnameMySQLConnectionMixin, asyncmy.Connection),
            {},
        )
        reason = BootstrapDatabaseFailureReason.CONNECTION
        try:
            async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
                for address in target.addresses:
                    connection = connection_class(
                        host=address.compressed,
                        port=candidate.port,
                        user=candidate.username,
                        password=candidate.password,
                        database=candidate.database,
                        ssl=self._ssl_context,
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
                        if is_mysql_authentication_error(error):
                            reason = BootstrapDatabaseFailureReason.AUTHENTICATION
                    finally:
                        try:
                            await connection.ensure_closed()
                        except (asyncmy.errors.Error, OSError, TimeoutError):
                            close_failed = True
                    if probe_completed:
                        if close_failed:
                            return unreachable(
                                BootstrapDatabaseFailureReason.CONNECTION
                            )
                        return BootstrapDatabaseCheckResult(reachable=True)
        except TimeoutError:
            pass
        return unreachable(reason)


def is_mysql_authentication_error(error: Exception) -> bool:
    """Map only stable server error codes to the public auth failure reason."""
    error_code = error.args[0] if error.args else None
    return type(error_code) is int and error_code in {
        _MySQLServerErrorCode.DATABASE_ACCESS_DENIED,
        _MySQLServerErrorCode.ACCESS_DENIED,
    }


__all__ = [
    "MySQLBootstrapDatabaseCheckAdapter",
    "is_mysql_authentication_error",
]
