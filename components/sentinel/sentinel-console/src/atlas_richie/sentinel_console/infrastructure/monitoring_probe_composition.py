"""Explicit composition for the private Prometheus query adapter."""

from __future__ import annotations

import ssl
from collections.abc import Sequence

from ..application.read_host_metrics import HostMetricsQueryPort
from ..application.monitoring_probe import MonitoringProbePort
from .monitoring_target_policy import (
    AddressResolver,
    MonitoringTargetPolicy,
    MonitoringTargetRule,
)
from .prometheus_http_adapter import PrometheusHttpAdapter
from .prometheus_host_metrics_adapter import PrometheusHostMetricsAdapter
from .registered_source_checker import PinnedAioHttpJsonClient

_MAX_MONITORING_RESPONSE_BYTES = 2 * 1024 * 1024


def compose_prometheus_http_adapter(
    rules: Sequence[MonitoringTargetRule],
    *,
    ssl_context: ssl.SSLContext | None = None,
    resolver: AddressResolver | None = None,
) -> MonitoringProbePort:
    """Build an adapter with deployment-owned target rules and pinned transport."""
    policy = MonitoringTargetPolicy(rules, resolver)
    transport = PinnedAioHttpJsonClient(
        max_response_bytes=_MAX_MONITORING_RESPONSE_BYTES,
        ssl_context=ssl_context,
        request_timeout_seconds=8.0,
    )
    return PrometheusHttpAdapter(policy, transport)


def compose_prometheus_host_metrics_adapter(
    rules: Sequence[MonitoringTargetRule],
    *,
    ssl_context: ssl.SSLContext | None = None,
    resolver: AddressResolver | None = None,
) -> HostMetricsQueryPort:
    """Build the fixed HOST-metrics profile over the pinned JSON transport."""
    policy = MonitoringTargetPolicy(rules, resolver)
    transport = PinnedAioHttpJsonClient(
        max_response_bytes=_MAX_MONITORING_RESPONSE_BYTES,
        ssl_context=ssl_context,
        request_timeout_seconds=8.0,
    )
    return PrometheusHostMetricsAdapter(policy, transport)


__all__ = [
    "compose_prometheus_host_metrics_adapter",
    "compose_prometheus_http_adapter",
]
