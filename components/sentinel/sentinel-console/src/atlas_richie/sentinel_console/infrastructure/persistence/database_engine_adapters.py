"""SQLAlchemy engine adapters selected by the persistence composition root."""

from __future__ import annotations

import os
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ...application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseKind,
)
from ...application.runtime_database_locator import RuntimeDatabaseTarget
from ..bootstrap_database_targets import ResolvedBootstrapDatabaseTarget
from ..pinned_mysql_connection import (
    create_pinned_mysql_async_creator,
    verified_mysql_ssl_context,
)

_MYSQL_ROOT_CERTIFICATE_ENV = "SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE"
_DATABASE_CONNECT_TIMEOUT_ENV = "SENTINEL_CONSOLE_DATABASE_CONNECT_TIMEOUT_SECONDS"
_DEFAULT_DATABASE_CONNECT_TIMEOUT_SECONDS = 10
_MAX_DATABASE_CONNECT_TIMEOUT_SECONDS = 60


def _database_connect_timeout_seconds() -> int:
    """Resolve a bounded DB connection timeout from process configuration."""
    configured = os.environ.get(
        _DATABASE_CONNECT_TIMEOUT_ENV,
        str(_DEFAULT_DATABASE_CONNECT_TIMEOUT_SECONDS),
    )
    try:
        timeout_seconds = int(configured)
    except ValueError:
        raise ValueError(
            f"{_DATABASE_CONNECT_TIMEOUT_ENV} must be an integer between 1 and "
            f"{_MAX_DATABASE_CONNECT_TIMEOUT_SECONDS}"
        ) from None
    if not 1 <= timeout_seconds <= _MAX_DATABASE_CONNECT_TIMEOUT_SECONDS:
        raise ValueError(
            f"{_DATABASE_CONNECT_TIMEOUT_ENV} must be an integer between 1 and "
            f"{_MAX_DATABASE_CONNECT_TIMEOUT_SECONDS}"
        )
    return timeout_seconds


@dataclass(frozen=True, slots=True)
class DatabaseEngineOptions:
    """Security and connection inputs shared by selected dialect adapters."""

    pinned_target: RuntimeDatabaseTarget | None = None
    connect_args: dict[str, object] | None = None
    async_creator: object | None = None
    mysql_ssl_context: ssl.SSLContext | None = None
    postgresql_root_certificate: str | None = None


class DatabaseEngineAdapter(Protocol):
    """Translate one database product into runtime and bootstrap engines."""

    drivername: str
    dialect: str
    bootstrap_kind: BootstrapDatabaseKind
    supports_bootstrap: bool
    requires_remote_target: bool

    def create_bootstrap_url(
        self,
        candidate: BootstrapDatabaseCandidate,
        *,
        sqlite_database_path: Path | None = None,
    ) -> URL:
        """Map provider-neutral setup fields to this driver's SQLAlchemy URL."""

    def create_engine(self, url: URL, options: DatabaseEngineOptions) -> AsyncEngine:
        """Create a lazy engine while preserving the adapter's security policy."""

    def create_pinned_bootstrap_engine(
        self,
        candidate: BootstrapDatabaseCandidate,
        url: URL,
        target: ResolvedBootstrapDatabaseTarget | None,
        *,
        postgresql_root_certificate: str | None,
        mysql_ssl_context: ssl.SSLContext | None,
    ) -> tuple[AsyncEngine, RuntimeDatabaseTarget | None]:
        """Build an engine and durable pin after deployment policy approval."""


class DatabaseEngineAdapterRegistry:
    """Resolve drivers without leaking provider selection into use cases."""

    def __init__(self, adapters: tuple[DatabaseEngineAdapter, ...]) -> None:
        by_driver = {adapter.drivername: adapter for adapter in adapters}
        by_kind = {adapter.bootstrap_kind: adapter for adapter in adapters}
        if (
            len(by_driver) != len(adapters)
            or len(by_kind) != len(adapters)
            or not by_driver
        ):
            raise ValueError("database engine adapters must be unique and non-empty")
        self._adapters = by_driver
        self._adapters_by_kind = by_kind

    def resolve(self, drivername: str) -> DatabaseEngineAdapter:
        """Return the single registered adapter or fail with a stable error."""
        try:
            return self._adapters[drivername]
        except KeyError:
            raise ValueError("database driver is unsupported") from None

    def resolve_kind(self, kind: BootstrapDatabaseKind) -> DatabaseEngineAdapter:
        """Select the adapter for one typed first-run database choice."""
        try:
            return self._adapters_by_kind[kind]
        except KeyError:
            raise ValueError("database kind is unsupported") from None

    @property
    def supported_dialects(self) -> frozenset[str]:
        """Expose registered dialects for runtime composition diagnostics."""
        return frozenset(adapter.dialect for adapter in self._adapters.values())


class PostgreSQLAsyncEngineAdapter:
    """Apply the PostgreSQL address pin and hostname-verifying TLS options."""

    drivername = "postgresql+psycopg"
    dialect = "postgresql"
    bootstrap_kind = BootstrapDatabaseKind.POSTGRESQL
    supports_bootstrap = True
    requires_remote_target = True

    def create_bootstrap_url(
        self,
        candidate: BootstrapDatabaseCandidate,
        *,
        sqlite_database_path: Path | None = None,
    ) -> URL:
        del sqlite_database_path
        return _remote_bootstrap_url(self.drivername, candidate)

    def create_engine(self, url: URL, options: DatabaseEngineOptions) -> AsyncEngine:
        engine_options: dict[str, object] = {
            "pool_pre_ping": True,
            "hide_parameters": True,
        }
        if options.connect_args is not None:
            engine_options["connect_args"] = dict(options.connect_args)
        if options.async_creator is not None:
            engine_options["async_creator"] = options.async_creator
        if options.pinned_target is not None:
            pinned_args = engine_options.setdefault("connect_args", {})
            assert isinstance(pinned_args, dict)
            pinned_args["hostaddr"] = options.pinned_target.addresses[0]
            pinned_args["sslmode"] = "verify-full"
            if options.postgresql_root_certificate is not None:
                pinned_args["sslrootcert"] = options.postgresql_root_certificate
        return create_async_engine(url, **engine_options)

    def create_pinned_bootstrap_engine(
        self,
        candidate: BootstrapDatabaseCandidate,
        url: URL,
        target: ResolvedBootstrapDatabaseTarget | None,
        *,
        postgresql_root_certificate: str | None,
        mysql_ssl_context: ssl.SSLContext | None,
    ) -> tuple[AsyncEngine, RuntimeDatabaseTarget | None]:
        del mysql_ssl_context
        if target is None:
            raise ValueError("PostgreSQL bootstrap requires a resolved network target")
        connect_args: dict[str, object] = {
            "hostaddr": target.addresses[0].compressed,
            "sslmode": "verify-full",
            "connect_timeout": _database_connect_timeout_seconds(),
        }
        if postgresql_root_certificate is not None:
            connect_args["sslrootcert"] = postgresql_root_certificate
        engine = self.create_engine(
            url,
            DatabaseEngineOptions(connect_args=connect_args),
        )
        return engine, RuntimeDatabaseTarget(
            target.hostname, (target.addresses[0].compressed,)
        )


class MySQLAsyncEngineAdapter:
    """Apply pinned-address dialing while verifying TLS for the DB hostname."""

    drivername = "mysql+asyncmy"
    dialect = "mysql"
    bootstrap_kind = BootstrapDatabaseKind.MYSQL
    supports_bootstrap = True
    requires_remote_target = True

    def create_bootstrap_url(
        self,
        candidate: BootstrapDatabaseCandidate,
        *,
        sqlite_database_path: Path | None = None,
    ) -> URL:
        del sqlite_database_path
        return _remote_bootstrap_url(self.drivername, candidate)

    def create_engine(self, url: URL, options: DatabaseEngineOptions) -> AsyncEngine:
        engine_options: dict[str, object] = {
            "pool_pre_ping": True,
            "hide_parameters": True,
        }
        if options.connect_args is not None:
            engine_options["connect_args"] = dict(options.connect_args)
        if options.async_creator is not None:
            engine_options["async_creator"] = options.async_creator
        if options.pinned_target is not None:
            try:
                creator = create_pinned_mysql_async_creator(
                    hostname=options.pinned_target.hostname,
                    addresses=options.pinned_target.addresses,
                    port=url.port or 3306,
                    username=url.username or "",
                    password=url.password or "",
                    database=url.database or "",
                    ssl_context=_mysql_ssl_context(options.mysql_ssl_context),
                    connect_timeout_seconds=_database_connect_timeout_seconds(),
                )
            except ImportError:
                raise ImportError("async driver for mysql is not installed") from None
            engine_options["async_creator"] = creator
        return create_async_engine(url, **engine_options)

    def create_pinned_bootstrap_engine(
        self,
        candidate: BootstrapDatabaseCandidate,
        url: URL,
        target: ResolvedBootstrapDatabaseTarget | None,
        *,
        postgresql_root_certificate: str | None,
        mysql_ssl_context: ssl.SSLContext | None,
    ) -> tuple[AsyncEngine, RuntimeDatabaseTarget | None]:
        del postgresql_root_certificate
        if target is None:
            raise ValueError("MySQL bootstrap requires a resolved network target")
        creator = create_pinned_mysql_async_creator(
            hostname=target.hostname,
            addresses=tuple(address.compressed for address in target.addresses),
            port=target.port,
            username=candidate.username or "",
            password=candidate.password or "",
            database=candidate.database or "",
            ssl_context=verified_mysql_ssl_context(mysql_ssl_context),
            connect_timeout_seconds=_database_connect_timeout_seconds(),
        )
        engine = self.create_engine(
            url,
            DatabaseEngineOptions(async_creator=creator),
        )
        return engine, RuntimeDatabaseTarget(
            target.hostname,
            tuple(address.compressed for address in target.addresses),
        )


class SQLiteAsyncEngineAdapter:
    """Create local SQLite engines; network pinning is never applicable."""

    drivername = "sqlite+aiosqlite"
    dialect = "sqlite"
    bootstrap_kind = BootstrapDatabaseKind.SQLITE
    supports_bootstrap = True
    requires_remote_target = False

    def create_bootstrap_url(
        self,
        candidate: BootstrapDatabaseCandidate,
        *,
        sqlite_database_path: Path | None = None,
    ) -> URL:
        del candidate
        path = _validated_sqlite_path(sqlite_database_path)
        return URL.create(drivername=self.drivername, database=str(path))

    def create_engine(self, url: URL, options: DatabaseEngineOptions) -> AsyncEngine:
        if options.pinned_target is not None:
            raise ValueError("SQLite cannot use a remote database target")
        engine_options: dict[str, object] = {
            "pool_pre_ping": True,
            "hide_parameters": True,
        }
        if options.connect_args is not None:
            engine_options["connect_args"] = dict(options.connect_args)
        return create_async_engine(url, **engine_options)

    def create_pinned_bootstrap_engine(
        self,
        candidate: BootstrapDatabaseCandidate,
        url: URL,
        target: ResolvedBootstrapDatabaseTarget | None,
        *,
        postgresql_root_certificate: str | None,
        mysql_ssl_context: ssl.SSLContext | None,
    ) -> tuple[AsyncEngine, RuntimeDatabaseTarget | None]:
        del candidate, postgresql_root_certificate, mysql_ssl_context
        if target is not None:
            raise ValueError("SQLite cannot use a remote bootstrap target")
        return self.create_engine(url, DatabaseEngineOptions()), None


def _validated_sqlite_path(path: Path | None) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("SQLite bootstrap requires an absolute deployment-owned path")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("SQLite bootstrap path must be a regular file path")
    if not path.parent.is_dir():
        raise ValueError("SQLite bootstrap parent directory must already exist")
    return path


def default_database_engine_adapters(
    *, additional_adapters: tuple[DatabaseEngineAdapter, ...] = ()
) -> DatabaseEngineAdapterRegistry:
    """Build the built-in adapter set plus composition-owned additions.

    Additional adapters are explicit application wiring, not runtime plugin
    discovery. Duplicate driver names or bootstrap kinds fail during startup.
    """
    return DatabaseEngineAdapterRegistry(
        (
            SQLiteAsyncEngineAdapter(),
            PostgreSQLAsyncEngineAdapter(),
            MySQLAsyncEngineAdapter(),
            *additional_adapters,
        )
    )


def _mysql_ssl_context(configured_context: ssl.SSLContext | None) -> ssl.SSLContext:
    if configured_context is not None:
        return verified_mysql_ssl_context(configured_context)
    root_certificate = os.environ.get(_MYSQL_ROOT_CERTIFICATE_ENV)
    try:
        context = ssl.create_default_context(
            cafile=root_certificate if root_certificate else None
        )
    except (OSError, ssl.SSLError):
        raise ValueError("configured MySQL root certificate is unavailable") from None
    return verified_mysql_ssl_context(context)


def _remote_bootstrap_url(
    drivername: str, candidate: BootstrapDatabaseCandidate
) -> URL:
    return URL.create(
        drivername=drivername,
        username=candidate.username,
        password=candidate.password,
        host=candidate.host,
        port=candidate.port,
        database=candidate.database,
    )


__all__ = [
    "DatabaseEngineAdapter",
    "DatabaseEngineAdapterRegistry",
    "DatabaseEngineOptions",
    "MySQLAsyncEngineAdapter",
    "PostgreSQLAsyncEngineAdapter",
    "SQLiteAsyncEngineAdapter",
    "default_database_engine_adapters",
]
