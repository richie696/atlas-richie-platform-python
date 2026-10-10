"""Create first-run engines only for deployment-approved, pinned targets."""

from __future__ import annotations

import ssl
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncEngine

from ..application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseKind,
)
from ..application.runtime_database_locator import RuntimeDatabaseTarget
from .bootstrap_database_targets import (
    BootstrapDatabaseTargetPolicy,
)
from .pinned_mysql_connection import (
    create_pinned_mysql_async_creator,
    verified_mysql_ssl_context,
)
from .persistence.database_runtime import (
    ConsoleDatabaseConfiguration,
    ConsoleDatabaseConfigurationError,
    ConsoleDatabaseDriverUnavailable,
)

_CONNECT_TIMEOUT_SECONDS = 3


@dataclass(frozen=True, slots=True)
class PreparedBootstrapDatabase:
    """Pinned engine and locator facts from one approved DNS resolution."""

    engine: AsyncEngine = field(repr=False, compare=False)
    locator_database_url: str = field(repr=False, compare=False)
    locator_target: RuntimeDatabaseTarget


class BootstrapDatabaseEngineFactory:
    """Resolve deployment policy once, then build a pinned SQLAlchemy engine.

    The returned engine is lazy and owned by the caller, which must dispose it.
    SQLite remains a test-only database and is intentionally not accepted here.
    """

    def __init__(
        self,
        target_policy: BootstrapDatabaseTargetPolicy,
        *,
        postgresql_root_certificate: str | None = None,
        mysql_ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._target_policy = target_policy
        self._postgresql_root_certificate = postgresql_root_certificate
        self._mysql_ssl_context = verified_mysql_ssl_context(mysql_ssl_context)

    async def create(
        self, candidate: BootstrapDatabaseCandidate
    ) -> PreparedBootstrapDatabase:
        """Validate once and return engine plus durable pin facts."""
        try:
            configuration = ConsoleDatabaseConfiguration.from_bootstrap_candidate(
                candidate
            )
        except ConsoleDatabaseConfigurationError:
            raise
        if candidate.kind not in {
            BootstrapDatabaseKind.POSTGRESQL,
            BootstrapDatabaseKind.MYSQL,
        }:
            raise ConsoleDatabaseConfigurationError(
                "first-run SQL engine requires PostgreSQL or MySQL"
            )

        target = await self._target_policy.resolve(
            candidate.kind,
            candidate.host or "",
            candidate.port or 0,
        )
        if candidate.kind is BootstrapDatabaseKind.POSTGRESQL:
            connect_args: dict[str, Any] = {
                "hostaddr": target.addresses[0].compressed,
                "sslmode": "verify-full",
                "connect_timeout": _CONNECT_TIMEOUT_SECONDS,
            }
            if self._postgresql_root_certificate is not None:
                connect_args["sslrootcert"] = self._postgresql_root_certificate
            engine = configuration.create_engine(connect_args=connect_args)
            pinned_addresses = (target.addresses[0].compressed,)
        else:
            try:
                async_creator = create_pinned_mysql_async_creator(
                    hostname=target.hostname,
                    addresses=tuple(address.compressed for address in target.addresses),
                    port=target.port,
                    username=candidate.username or "",
                    password=candidate.password or "",
                    database=candidate.database or "",
                    ssl_context=self._mysql_ssl_context,
                    connect_timeout_seconds=_CONNECT_TIMEOUT_SECONDS,
                )
            except ImportError:
                raise ConsoleDatabaseDriverUnavailable(
                    "async driver for mysql is not installed"
                ) from None
            engine = configuration.create_engine(async_creator=async_creator)
            pinned_addresses = tuple(
                address.compressed for address in target.addresses
            )

        return PreparedBootstrapDatabase(
            engine=engine,
            locator_database_url=configuration.secret_url_for_storage(),
            locator_target=RuntimeDatabaseTarget(
                target.hostname, pinned_addresses
            ),
        )


__all__ = ["BootstrapDatabaseEngineFactory", "PreparedBootstrapDatabase"]
