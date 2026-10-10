"""Shared MySQL TLS hostname handling for address-pinned connections."""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import Sequence
from typing import Any


class PinnedHostnameMySQLConnectionMixin:
    """Pin the socket IP while preserving hostname verification during TLS."""

    _target_hostname: str
    _host: str

    async def _request_authentication(self) -> Any:
        pinned_address = self._host
        self._host = self._target_hostname
        try:
            return await super()._request_authentication()
        finally:
            self._host = pinned_address


def verified_mysql_ssl_context(context: ssl.SSLContext | None) -> ssl.SSLContext:
    """Return a hostname-verifying TLS context or reject unsafe configuration."""
    candidate = context or ssl.create_default_context()
    if candidate.verify_mode is not ssl.CERT_REQUIRED or not candidate.check_hostname:
        raise ValueError("MySQL connections require verified TLS")
    return candidate


def create_pinned_mysql_async_creator(
    *,
    hostname: str,
    addresses: Sequence[str],
    port: int,
    username: str,
    password: str,
    database: str,
    ssl_context: ssl.SSLContext,
    connect_timeout_seconds: int,
) -> Any:
    """Create an asyncmy creator that pins sockets but verifies TLS by hostname."""
    import asyncmy

    connection_class = type(
        "_PinnedHostnameAsyncMySQLConnection",
        (PinnedHostnameMySQLConnectionMixin, asyncmy.Connection),
        {},
    )

    async def connect() -> Any:
        last_error: BaseException | None = None
        async with asyncio.timeout(connect_timeout_seconds * len(addresses)):
            for address in addresses:
                connection = connection_class(
                    host=address,
                    port=port,
                    user=username,
                    password=password,
                    database=database,
                    ssl=ssl_context,
                    connect_timeout=connect_timeout_seconds,
                    autocommit=False,
                    local_infile=False,
                )
                connection._target_hostname = hostname
                try:
                    await connection.connect()
                    return connection
                except (asyncmy.errors.Error, OSError, TimeoutError) as error:
                    last_error = error
                    await connection.ensure_closed()
                    if _is_mysql_authentication_error(error):
                        raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("no approved MySQL database address is available")

    return connect


def _is_mysql_authentication_error(error: Exception) -> bool:
    error_code = error.args[0] if error.args else None
    return type(error_code) is int and error_code in {1044, 1045}


__all__ = [
    "PinnedHostnameMySQLConnectionMixin",
    "create_pinned_mysql_async_creator",
    "verified_mysql_ssl_context",
]
