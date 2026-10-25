"""Read HOST metrics through the configured monitoring source."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ..domain.host_metrics import (
    HostMetricQuality,
    HostMetricReason,
    HostMetricsQuery,
    HostMetricsSnapshot,
)
from ..domain.monitoring_sources import MonitoringAuthenticationMode, MonitoringSource
from .monitoring_probe import MonitoringCredentialReferenceResolver, MonitoringProbeCredentials
from .monitoring_source_registry import (
    MonitoringSourceNotFound,
    MonitoringSourceRegistryPort,
    MonitoringSourceRegistryUnavailable,
    MonitoringSourceSecret,
)


class HostMetricsQueryUnavailable(RuntimeError):
    """Required source metadata or credential authority could not be read."""


class HostMetricsQueryPort(Protocol):
    """Provider-neutral HOST query capability consumed by the use case."""

    async def read_host_metrics(
        self,
        source: MonitoringSource,
        query: HostMetricsQuery,
        credentials: MonitoringProbeCredentials | None,
    ) -> HostMetricsSnapshot: ...


@dataclass(frozen=True, slots=True)
class ReadHostMetrics:
    """Resolve one stored source, resolve write-only credentials, then query it."""

    registry: MonitoringSourceRegistryPort
    query_port: HostMetricsQueryPort
    credential_reference_resolver: MonitoringCredentialReferenceResolver | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def execute(
        self, source_id: str, query: HostMetricsQuery
    ) -> HostMetricsSnapshot:
        try:
            source = await self.registry.read_monitoring_source(source_id)
            if not source.enabled:
                return _empty_snapshot(
                    source,
                    query,
                    self.clock(),
                    HostMetricQuality.NOT_INTEGRATED,
                    HostMetricReason.SOURCE_DISABLED,
                )
            credentials = await self._credentials(source)
            return await self.query_port.read_host_metrics(source, query, credentials)
        except MonitoringSourceNotFound:
            raise
        except (MonitoringSourceRegistryUnavailable, HostMetricsQueryUnavailable):
            raise
        except (RuntimeError, OSError, ValueError, TypeError):
            raise HostMetricsQueryUnavailable from None

    async def _credentials(
        self, source: MonitoringSource
    ) -> MonitoringProbeCredentials | None:
        if source.authentication_mode is MonitoringAuthenticationMode.NONE:
            return None
        secret = await self.registry.resolve_monitoring_source_secret(
            source.source_id, expected_revision=source.revision
        )
        if secret is None:
            raise HostMetricsQueryUnavailable
        if secret.credential_reference is not None:
            if self.credential_reference_resolver is None:
                raise HostMetricsQueryUnavailable
            try:
                resolved = await self.credential_reference_resolver.resolve(
                    secret.credential_reference
                )
            except (RuntimeError, OSError, ValueError, TypeError):
                raise HostMetricsQueryUnavailable from None
            if resolved is None:
                raise HostMetricsQueryUnavailable
            return resolved
        return _probe_credentials(secret)


def _probe_credentials(secret: MonitoringSourceSecret) -> MonitoringProbeCredentials:
    if secret.username is not None and secret.password is not None:
        return MonitoringProbeCredentials(secret.username, secret.password)
    if secret.bearer_token is not None:
        return MonitoringProbeCredentials(bearer_token=secret.bearer_token)
    raise HostMetricsQueryUnavailable


def _empty_snapshot(
    source: MonitoringSource,
    query: HostMetricsQuery,
    as_of: datetime,
    quality: HostMetricQuality,
    reason: HostMetricReason,
) -> HostMetricsSnapshot:
    return HostMetricsSnapshot(
        source_id=source.source_id,
        environment_id=source.environment_id,
        query=query,
        as_of=as_of,
        quality=quality,
        reason=reason,
        hosts=(),
    )


__all__ = [
    "HostMetricsQueryPort",
    "HostMetricsQueryUnavailable",
    "ReadHostMetrics",
]
