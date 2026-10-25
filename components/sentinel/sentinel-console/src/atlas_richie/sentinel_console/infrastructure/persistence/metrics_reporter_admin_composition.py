"""Compose the Metrics V2 operator management workflow."""

from __future__ import annotations

import ssl
from functools import partial

from ...application.manage_metrics_reporters import ManageMetricsReporters
from .database_engine_adapters import DatabaseEngineAdapterRegistry
from .database_runtime import create_database_engine_from_locator
from .metrics_reporter_admin_adapter import SqlAlchemyMetricsReporterAdminAdapter
from .runtime_database_engine_provider import RuntimeDatabaseEngineProvider
from .runtime_database_locator_configuration import (
    RuntimeDatabaseLocatorConfiguration,
)


def build_metrics_reporter_admin(
    runtime_locator_configuration: RuntimeDatabaseLocatorConfiguration,
    *,
    postgresql_root_certificate: str | None = None,
    mysql_ssl_context: ssl.SSLContext | None = None,
    adapter_registry: DatabaseEngineAdapterRegistry | None = None,
) -> tuple[ManageMetricsReporters, RuntimeDatabaseEngineProvider]:
    """Build the operator use case against the same selected Console database."""
    runtime_database_engine_factory = partial(
        create_database_engine_from_locator,
        postgresql_root_certificate=postgresql_root_certificate,
        mysql_ssl_context=mysql_ssl_context,
        adapter_registry=adapter_registry,
    )
    runtime_provider = RuntimeDatabaseEngineProvider(
        runtime_locator_configuration.create_store(),
        engine_factory=runtime_database_engine_factory,
    )
    administration = SqlAlchemyMetricsReporterAdminAdapter(
        runtime_provider.require_engine
    )
    return ManageMetricsReporters(administration), runtime_provider


__all__ = ["build_metrics_reporter_admin"]
