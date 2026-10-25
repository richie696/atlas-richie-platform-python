"""Out-of-band PostgreSQL/MySQL URL parsing and async engine creation."""

from __future__ import annotations

import os
import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
)
from ...application.runtime_database_locator import (
    RuntimeDatabaseLocator,
    RuntimeDatabaseLocatorStore,
    RuntimeDatabaseTarget,
)
from ..bootstrap_database_targets import ResolvedBootstrapDatabaseTarget
from .database_engine_adapters import (
    DatabaseEngineAdapter,
    DatabaseEngineAdapterRegistry,
    DatabaseEngineOptions,
    default_database_engine_adapters,
)

_DATABASE_URL_ENV = "SENTINEL_CONSOLE_DATABASE_URL"
_DATABASE_ENGINE_ADAPTERS = default_database_engine_adapters()
SUPPORTED_RUNTIME_DATABASE_DIALECTS = _DATABASE_ENGINE_ADAPTERS.supported_dialects


class ConsoleDatabaseConfigurationError(ValueError):
    """Deployment database settings are missing or unsupported."""


class ConsoleDatabaseDriverUnavailable(RuntimeError):
    """The configured optional async database driver is not installed."""


def _has_remote_bootstrap_fields(candidate: BootstrapDatabaseCandidate) -> bool:
    return bool(
        isinstance(candidate.host, str)
        and candidate.host
        and isinstance(candidate.port, int)
        and not isinstance(candidate.port, bool)
        and 1 <= candidate.port <= 65535
        and isinstance(candidate.database, str)
        and candidate.database
        and isinstance(candidate.username, str)
        and candidate.username
        and isinstance(candidate.password, str)
        and candidate.password
    )


@dataclass(frozen=True, slots=True)
class ConsoleDatabaseConfiguration:
    """Validated runtime database URL; credentials are suppressed from repr."""

    _url: URL = field(repr=False)
    _adapter: DatabaseEngineAdapter = field(repr=False, compare=False)
    _pinned_target: RuntimeDatabaseTarget | None = field(
        default=None, repr=False, compare=False
    )

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        adapter_registry: DatabaseEngineAdapterRegistry | None = None,
    ) -> ConsoleDatabaseConfiguration:
        """Parse a deployment environment URL without connecting."""
        values = os.environ if environment is None else environment
        raw_url = values.get(_DATABASE_URL_ENV)
        if not isinstance(raw_url, str) or not raw_url:
            raise ConsoleDatabaseConfigurationError(
                "Console runtime database URL is required"
            )
        return cls.from_url(raw_url, adapter_registry=adapter_registry)

    @classmethod
    def from_locator(
        cls,
        locator: RuntimeDatabaseLocator,
        *,
        adapter_registry: DatabaseEngineAdapterRegistry | None = None,
    ) -> ConsoleDatabaseConfiguration:
        """Validate a decrypted first-run locator as a supported runtime URL."""
        if not isinstance(locator, RuntimeDatabaseLocator):
            raise ConsoleDatabaseConfigurationError(
                "Console runtime database locator is unavailable"
            )
        configuration = cls.from_url(
            locator.database_url, adapter_registry=adapter_registry
        )
        if locator.target is None:
            return configuration
        if configuration._url.host is None or configuration._url.host.casefold().rstrip(
            "."
        ) != locator.target.hostname.casefold().rstrip("."):
            raise ConsoleDatabaseConfigurationError(
                "runtime database locator target does not match its URL"
            )
        return cls(
            configuration._url,
            configuration._adapter,
            _pinned_target=locator.target,
        )

    @classmethod
    def from_bootstrap_candidate(
        cls,
        candidate: BootstrapDatabaseCandidate,
        *,
        sqlite_database_path: Path | None = None,
        adapter_registry: DatabaseEngineAdapterRegistry | None = None,
    ) -> ConsoleDatabaseConfiguration:
        """Map validated remote setup fields through the selected Adapter.

        This method does not resolve DNS or connect. A deployment connector must
        apply its approved address pinning and TLS policy before opening sockets.
        """
        if not isinstance(candidate, BootstrapDatabaseCandidate):
            raise ConsoleDatabaseConfigurationError(
                "Console bootstrap database candidate is invalid"
            )
        try:
            adapters = adapter_registry or _DATABASE_ENGINE_ADAPTERS
            adapter = adapters.resolve_kind(candidate.kind)
        except (TypeError, ValueError):
            raise ConsoleDatabaseConfigurationError(
                "Console bootstrap database credentials are incomplete"
            ) from None
        if not adapter.supports_bootstrap:
            raise ConsoleDatabaseConfigurationError(
                "Console bootstrap database credentials are incomplete"
            )
        if adapter.requires_remote_target and not _has_remote_bootstrap_fields(candidate):
            raise ConsoleDatabaseConfigurationError(
                "Console bootstrap database credentials are incomplete"
            )
        if not adapter.requires_remote_target and any(
            value is not None
            for value in (
                candidate.host,
                candidate.port,
                candidate.database,
                candidate.username,
                candidate.password,
            )
        ):
            raise ConsoleDatabaseConfigurationError(
                "local database bootstrap does not accept network credentials"
            )
        try:
            url = adapter.create_bootstrap_url(
                candidate, sqlite_database_path=sqlite_database_path
            )
        except (OSError, TypeError, ValueError):
            raise ConsoleDatabaseConfigurationError(
                "Console bootstrap database configuration is invalid"
            ) from None
        return cls(
            url,
            adapter,
        )

    def create_pinned_bootstrap_engine(
        self,
        candidate: BootstrapDatabaseCandidate,
        target: ResolvedBootstrapDatabaseTarget | None,
        *,
        postgresql_root_certificate: str | None,
        mysql_ssl_context: ssl.SSLContext | None,
    ) -> tuple[AsyncEngine, RuntimeDatabaseTarget]:
        """Delegate vendor-specific bootstrap TLS and address pinning."""
        if (
            not self._adapter.supports_bootstrap
            or self._adapter.bootstrap_kind is not candidate.kind
        ):
            raise ConsoleDatabaseConfigurationError(
                "database adapter does not match the bootstrap candidate"
            )
        try:
            return self._adapter.create_pinned_bootstrap_engine(
                candidate,
                self._url,
                target,
                postgresql_root_certificate=postgresql_root_certificate,
                mysql_ssl_context=mysql_ssl_context,
            )
        except ImportError:
            raise ConsoleDatabaseDriverUnavailable(
                f"async driver for {self.dialect} is not installed"
            ) from None

    def secret_url_for_storage(self) -> str:
        """Render the complete URL for immediate encrypted locator persistence."""
        return self._url.render_as_string(hide_password=False)

    @classmethod
    def from_url(
        cls,
        raw_url: str,
        *,
        adapter_registry: DatabaseEngineAdapterRegistry | None = None,
    ) -> ConsoleDatabaseConfiguration:
        """Validate a supported production URL without connecting."""
        try:
            url = make_url(raw_url)
        except (ArgumentError, TypeError, ValueError):
            raise ConsoleDatabaseConfigurationError(
                "Console runtime database URL is invalid"
            ) from None
        try:
            adapters = adapter_registry or _DATABASE_ENGINE_ADAPTERS
            adapter = adapters.resolve(url.drivername)
        except ValueError:
            raise ConsoleDatabaseConfigurationError(
                "Console runtime database driver is unsupported"
            ) from None
        if not adapter.requires_remote_target:
            if (
                url.username is not None
                or url.password is not None
                or url.host is not None
                or not url.database
                or not url.database.startswith("/")
                or url.database == ":memory:"
            ):
                raise ConsoleDatabaseConfigurationError(
                    "SQLite runtime database URL must use an absolute file path"
                )
        elif not url.username or not url.password or not url.host or not url.database:
            raise ConsoleDatabaseConfigurationError(
                "Console runtime database URL must use configured "
                "PostgreSQL or MySQL credentials"
            )
        return cls(url, adapter)

    @property
    def dialect(self) -> str:
        """Return the supported SQL dialect name without connection details."""
        return self._adapter.dialect

    @property
    def requires_remote_target(self) -> bool:
        """Report whether deployment DNS policy must pin this database."""
        return self._adapter.requires_remote_target

    def create_engine(
        self,
        *,
        connect_args: Mapping[str, Any] | None = None,
        async_creator: Any | None = None,
        mysql_ssl_context: ssl.SSLContext | None = None,
        postgresql_root_certificate: str | None = None,
    ) -> AsyncEngine:
        """Create a pooled async engine without opening a network connection."""
        try:
            return self._adapter.create_engine(
                self._url,
                DatabaseEngineOptions(
                    pinned_target=self._pinned_target,
                    connect_args=(
                        dict(connect_args) if connect_args is not None else None
                    ),
                    async_creator=async_creator,
                    mysql_ssl_context=mysql_ssl_context,
                    postgresql_root_certificate=postgresql_root_certificate,
                ),
            )
        except ImportError:
            raise ConsoleDatabaseDriverUnavailable(
                f"async driver for {self.dialect} is not installed"
            ) from None


async def create_runtime_database_engine(
    locator_store: RuntimeDatabaseLocatorStore,
    *,
    postgresql_root_certificate: str | None = None,
    mysql_ssl_context: ssl.SSLContext | None = None,
    adapter_registry: DatabaseEngineAdapterRegistry | None = None,
) -> AsyncEngine | None:
    """Resolve the durable locator into a lazy engine; absent means setup mode.

    Locator corruption/unavailability propagates as a fail-closed error. This
    helper never substitutes an environment URL or local SQLite database.
    """
    locator = await locator_store.read()
    if locator is None:
        return None
    return create_database_engine_from_locator(
        locator,
        postgresql_root_certificate=postgresql_root_certificate,
        mysql_ssl_context=mysql_ssl_context,
        adapter_registry=adapter_registry,
    )


def create_database_engine_from_locator(
    locator: RuntimeDatabaseLocator,
    *,
    postgresql_root_certificate: str | None = None,
    mysql_ssl_context: ssl.SSLContext | None = None,
    adapter_registry: DatabaseEngineAdapterRegistry | None = None,
) -> AsyncEngine:
    """Build an engine from one already-read, validated durable locator."""
    configuration = ConsoleDatabaseConfiguration.from_locator(
        locator, adapter_registry=adapter_registry
    )
    return configuration.create_engine(
        postgresql_root_certificate=postgresql_root_certificate,
        mysql_ssl_context=mysql_ssl_context,
    )
