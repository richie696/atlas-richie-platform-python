"""Authenticated read route for bounded HOST-scope Prometheus metrics."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.monitoring_probe import MonitoringCredentialReferenceResolver
from ..application.monitoring_source_registry import (
    MonitoringSourceNotFound,
    MonitoringSourceRegistryPort,
    MonitoringSourceRegistryUnavailable,
)
from ..application.read_host_metrics import (
    HostMetricsQueryPort,
    HostMetricsQueryUnavailable,
    ReadHostMetrics,
)
from ..application.read_session import ReadSession
from ..domain.host_metrics import (
    HostMetricKind,
    HostMetricSeries,
    HostMetricsQuery,
    HostMetricsSnapshot,
)
from .http_support import error_response
from .query_parsing import (
    MAX_QUERY_STEP_MS,
    MIN_QUERY_INTEGER,
    parse_integer,
    parse_query_values,
    parse_utc_timestamp,
)
from .system_observation_access import authorize_system_read, system_read_headers, utc_timestamp

_REQUIRED_QUERY_FIELDS = frozenset({"from", "to", "stepMs"})
_NO_OPTIONAL_QUERY_FIELDS: frozenset[str] = frozenset()
_METRIC_UNITS = {
    HostMetricKind.CPU_BUSY_RATIO: "ratio",
    HostMetricKind.MEMORY_USED_BYTES: "bytes",
    HostMetricKind.MEMORY_USED_RATIO: "ratio",
    HostMetricKind.LOAD_1M: "tasks",
}


def host_metrics_route(
    read_session: ReadSession,
    registry: MonitoringSourceRegistryPort | None,
    query_port: HostMetricsQueryPort | None,
    credential_reference_resolver: MonitoringCredentialReferenceResolver | None,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Route:
    """Create a bounded source-scoped HOST metrics query route."""

    async def read_host_metrics(request: Request) -> Response:
        request_id_value, identity, rejection = await authorize_system_read(
            request, read_session, invalid_request_code="invalid_request"
        )
        if rejection is not None:
            return rejection
        if identity is None:
            return error_response(request_id_value, "unauthenticated", 401)
        try:
            supplied = parse_query_values(
                request, _REQUIRED_QUERY_FIELDS, _NO_OPTIONAL_QUERY_FIELDS
            )
            query = HostMetricsQuery(
                start_at=parse_utc_timestamp(supplied["from"]),
                end_at=parse_utc_timestamp(supplied["to"]),
                step_ms=parse_integer(
                    supplied["stepMs"], MIN_QUERY_INTEGER, MAX_QUERY_STEP_MS
                ),
            )
        except (KeyError, TypeError, ValueError):
            return error_response(request_id_value, "invalid_request", 400)
        if registry is None or query_port is None:
            return error_response(request_id_value, "service_unavailable", 503)
        source_id = request.path_params.get("sourceId", "")
        try:
            snapshot = await ReadHostMetrics(
                registry,
                query_port,
                credential_reference_resolver,
                clock=clock,
            ).execute(source_id, query)
        except MonitoringSourceNotFound:
            return error_response(request_id_value, "not_found", 404)
        except (MonitoringSourceRegistryUnavailable, HostMetricsQueryUnavailable):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            host_metrics_snapshot_body(snapshot),
            headers=system_read_headers(request_id_value),
        )

    return Route(
        "/api/v2/monitoring/sources/{sourceId:str}/host-metrics",
        read_host_metrics,
        methods=["GET"],
    )


def host_metrics_snapshot_body(snapshot: HostMetricsSnapshot) -> dict[str, object]:
    """Project domain facts to the stable, provider-free API shape."""
    query = snapshot.query
    return {
        "sourceId": snapshot.source_id,
        "environmentId": snapshot.environment_id,
        "query": {
            "from": utc_timestamp(query.start_at),
            "to": utc_timestamp(query.end_at),
            "stepMs": query.step_ms,
        },
        "asOf": utc_timestamp(snapshot.as_of),
        "quality": snapshot.quality.value,
        "reason": snapshot.reason.value if snapshot.reason is not None else None,
        "hosts": [
            {
                "hostId": host.identity.host_id,
                "identity": [
                    {"name": name, "value": value}
                    for name, value in host.identity.labels
                ],
                "metrics": [
                    _series_body(series) for series in host.metrics
                ],
            }
            for host in snapshot.hosts
        ],
    }


def _series_body(series: HostMetricSeries) -> dict[str, object]:
    return {
        "metric": series.kind.value,
        "unit": _METRIC_UNITS[series.kind],
        "quality": series.quality.value,
        "reason": series.reason.value if series.reason is not None else None,
        "samples": [
            {"at": utc_timestamp(sample.at), "value": sample.value}
            for sample in series.samples
        ],
    }


__all__ = ["host_metrics_route", "host_metrics_snapshot_body"]
