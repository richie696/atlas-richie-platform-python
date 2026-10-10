"""Out-of-band PostgreSQL/MySQL URL parsing and async engine creation."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
import ssl
from typing import Any

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ...application.runtime_database_locator import (
    RuntimeDatabaseLocator,
    RuntimeDatabaseLocatorStore,
)
from ...application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseKind,
)
from ...application.runtime_database_locator import (
    RuntimeDatabaseLocator,
    RuntimeDatabaseTarget,
)
from ..pinned_mysql_connection import (
    create_pinned_mysql_async_creator,
    verified_mysql_ssl_context,
)

_DATABASE_URL_ENV = "SENTINEL_CONSOLE_DATABASE_URL"
_SUPPORTED_DRIVERS = frozenset({"postgresql+psycopg", "mysql+asyncmy"})


class ConsoleDatabaseConfigurationError(ValueError):
    """Deployment database settings are missing or unsupported."""


class ConsoleDatabaseDriverUnavailable(RuntimeError):
    """The configured optional async database driver is not installed."""


@dataclass(frozen=True, slots=True)
class ConsoleDatabaseConfiguration:
    """Validated runtime database URL; credentials are suppressed from repr."""

    _url: URL = field(repr=False)
    _pinned_target: RuntimeDatabaseTarget | None = field(
        default=None, repr=False, compare=False
    )

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> ConsoleDatabaseConfiguration:
        """Parse a deployment environment URL without connecting."""
        values = os.environ if environment is None else environment
        raw_url = values.get(_DATABASE_URL_ENV)
        if not isinstance(raw_url, str) or not raw_url:
            raise ConsoleDatabaseConfigurationError(
                "Console runtime database URL is required"
            )
        return cls.from_url(raw_url)

    @classmethod
    def from_locator(
        cls, locator: RuntimeDatabaseLocator
    ) -> ConsoleDatabaseConfiguration:
        """Validate a decrypted first-run locator as a supported runtime URL."""
        if not isinstance(locator, RuntimeDatabaseLocator):
            raise ConsoleDatabaseConfigurationError(
                "Console runtime database locator is unavailable"
            )
        configuration = cls.from_url(locator.database_url)
        if locator.target is None:
            return configuration
        if (
            configuration._url.host is None
            or configuration._url.host.casefold().rstrip(".")
            != locator.target.hostname.casefold().rstrip(".")
        ):
            raise ConsoleDatabaseConfigurationError(
                "runtime database locator target does not match its URL"
            )
        return cls(configuration._url, locator.target)

    @classmethod
    def from_bootstrap_candidate(
        cls, candidate: BootstrapDatabaseCandidate
    ) -> ConsoleDatabaseConfiguration:
        """Map validated PostgreSQL/MySQL setup fields to an async URL.

        This method does not resolve DNS or connect. A deployment connector must
        apply its approved address pinning and TLS policy before opening sockets.
        """
        if not isinstance(candidate, BootstrapDatabaseCandidate):
            raise ConsoleDatabaseConfigurationError(
                "Console bootstrap database candidate is invalid"
            )
        if (
            candidate.kind not in {
                BootstrapDatabaseKind.POSTGRESQL,
                BootstrapDatabaseKind.MYSQL,
            }
            or not isinstance(candidate.host, str)
            or not candidate.host
            or not isinstance(candidate.port, int)
            or isinstance(candidate.port, bool)
            or not 1 <= candidate.port <= 65535
            or not isinstance(candidate.database, str)
            or not candidate.database
            or not isinstance(candidate.username, str)
            or not candidate.username
            or not isinstance(candidate.password, str)
            or not candidate.password
        ):
            raise ConsoleDatabaseConfigurationError(
                "Console bootstrap database credentials are incomplete"
            )
        drivername = (
            "postgresql+psycopg"
            if candidate.kind is BootstrapDatabaseKind.POSTGRESQL
            else "mysql+asyncmy"
        )
        return cls(
            URL.create(
                drivername=drivername,
                username=candidate.username,
                password=candidate.password,
                host=candidate.host,
                port=candidate.port,
                database=candidate.database,
            )
        )

    def secret_url_for_storage(self) -> str:
        """Render the complete URL for immediate encrypted locator persistence."""
        return self._url.render_as_string(hide_password=False)

    @classmethod
    def from_url(cls, raw_url: str) -> ConsoleDatabaseConfiguration:
        """Validate a supported production URL without connecting."""
        try:
            url = make_url(raw_url)
        except (ArgumentError, TypeError, ValueError):
            raise ConsoleDatabaseConfigurationError(
                "Console runtime database URL is invalid"
            ) from None
        if (
            url.drivername not in _SUPPORTED_DRIVERS
            or not url.username
            or not url.password
            or not url.host
            or not url.database
        ):
            raise ConsoleDatabaseConfigurationError(
                "Console runtime database URL must use configured "
                "PostgreSQL or MySQL credentials"
            )
        return cls(url)

    @property
    def dialect(self) -> str:
        """Return the supported SQL dialect name without connection details."""
        return (
            "postgresql"
            if self._url.drivername.startswith("postgresql+")
            else "mysql"
        )

    def create_engine(
        self,
        *,
        connect_args: Mapping[str, Any] | None = None,
        async_creator: Any | None = None,
    ) -> AsyncEngine:
        """Create a pooled async engine without opening a network connection."""
        options: dict[str, Any] = {
            "pool_pre_ping": True,
            "hide_parameters": True,
        }
        if connect_args is not None:
            options["connect_args"] = dict(connect_args)
        if async_creator is not None:
            options["async_creator"] = async_creator
        if self._pinned_target is not None:
            target = self._pinned_target
            if self.dialect == "postgresql":
                pinned_args = options.setdefault("connect_args", {})
                pinned_args["hostaddr"] = target.addresses[0]
                pinned_args["sslmode"] = "verify-full"
            else:
                try:
                    async_creator = create_pinned_mysql_async_creator(
                        hostname=target.hostname,
                        addresses=target.addresses,
                        port=self._url.port or 3306,
                        username=self._url.username or "",
                        password=self._url.password or "",
                        database=self._url.database or "",
                        ssl_context=verified_mysql_ssl_context(
                            ssl.create_default_context()
                        ),
                        connect_timeout_seconds=3,
                    )
                except ImportError:
                    raise ConsoleDatabaseDriverUnavailable(
                        "async driver for mysql is not installed"
                    ) from None
                options["async_creator"] = async_creator
        try:
            return create_async_engine(self._url, **options)
        except ImportError:
            raise ConsoleDatabaseDriverUnavailable(
                f"async driver for {self.dialect} is not installed"
            ) from None


async def create_runtime_database_engine(
    locator_store: RuntimeDatabaseLocatorStore,
) -> AsyncEngine | None:
    """Resolve the durable locator into a lazy engine; absent means setup mode.

    Locator corruption/unavailability propagates as a fail-closed error. This
    helper never substitutes an environment URL or local SQLite database.
    """
    locator = await locator_store.read()
    if locator is None:
        return None
    return create_database_engine_from_locator(locator)


def create_database_engine_from_locator(
    locator: RuntimeDatabaseLocator,
) -> AsyncEngine:
    """Build an engine from one already-read, validated durable locator."""
    configuration = ConsoleDatabaseConfiguration.from_locator(locator)
    return configuration.create_engine()
