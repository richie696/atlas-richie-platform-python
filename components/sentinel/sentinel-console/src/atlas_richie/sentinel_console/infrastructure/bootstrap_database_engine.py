"""Create first-run engines only for deployment-approved, pinned targets."""

from __future__ import annotations

import ssl
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine

from ..application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
)
from ..application.runtime_database_locator import RuntimeDatabaseTarget
from .bootstrap_database_targets import BootstrapDatabaseTargetPolicy
from .persistence.database_engine_adapters import DatabaseEngineAdapterRegistry
from .persistence.database_runtime import ConsoleDatabaseConfiguration
from .pinned_mysql_connection import verified_mysql_ssl_context


@dataclass(frozen=True, slots=True)
class PreparedBootstrapDatabase:
    """Pinned engine and locator facts from one approved DNS resolution."""

    engine: AsyncEngine = field(repr=False, compare=False)
    locator_database_url: str = field(repr=False, compare=False)
    locator_target: RuntimeDatabaseTarget | None


class BootstrapDatabaseEngineFactory:
    """Resolve deployment policy once, then build a pinned SQLAlchemy engine.

    The returned engine is lazy and owned by the caller, which must dispose it.
    Local databases use their deployment-owned location and never enter DNS policy.
    """

    def __init__(
        self,
        target_policy: BootstrapDatabaseTargetPolicy,
        *,
        sqlite_database_path: Path | None = None,
        postgresql_root_certificate: str | None = None,
        mysql_ssl_context: ssl.SSLContext | None = None,
        adapter_registry: DatabaseEngineAdapterRegistry | None = None,
    ) -> None:
        self._target_policy = target_policy
        self._sqlite_database_path = sqlite_database_path
        self._postgresql_root_certificate = postgresql_root_certificate
        self._mysql_ssl_context = verified_mysql_ssl_context(mysql_ssl_context)
        self._adapter_registry = adapter_registry

    def configuration_for(
        self, candidate: BootstrapDatabaseCandidate
    ) -> ConsoleDatabaseConfiguration:
        """Resolve provider-neutral setup input through its database Adapter."""
        return ConsoleDatabaseConfiguration.from_bootstrap_candidate(
            candidate,
            sqlite_database_path=self._sqlite_database_path,
            adapter_registry=self._adapter_registry,
        )

    def requires_remote_target(self, candidate: BootstrapDatabaseCandidate) -> bool:
        """Return whether this Adapter requires DNS policy and address pinning."""
        return self.configuration_for(candidate).requires_remote_target

    async def create(
        self, candidate: BootstrapDatabaseCandidate
    ) -> PreparedBootstrapDatabase:
        """Validate once and return engine plus durable pin facts."""
        configuration = self.configuration_for(candidate)
        target = None
        if configuration.requires_remote_target:
            target = await self._target_policy.resolve(
                candidate.kind,
                candidate.host or "",
                candidate.port or 0,
            )
        engine, locator_target = configuration.create_pinned_bootstrap_engine(
            candidate,
            target,
            postgresql_root_certificate=self._postgresql_root_certificate,
            mysql_ssl_context=self._mysql_ssl_context,
        )

        return PreparedBootstrapDatabase(
            engine=engine,
            locator_database_url=configuration.secret_url_for_storage(),
            locator_target=locator_target,
        )


__all__ = ["BootstrapDatabaseEngineFactory", "PreparedBootstrapDatabase"]
