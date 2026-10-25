"""Fixed-profile Prometheus range queries for Linux HOST metrics."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import aiohttp

from ..application.monitoring_probe import MonitoringProbeCredentials
from ..application.read_host_metrics import HostMetricsQueryPort
from ..domain.host_metrics import (
    MAX_HOST_METRIC_HOSTS,
    HostMetricIdentity,
    HostMetricKind,
    HostMetricPoint,
    HostMetricQuality,
    HostMetricReason,
    HostMetricSeries,
    HostMetricsHost,
    HostMetricsQuery,
    HostMetricsSnapshot,
)
from ..domain.monitoring_sources import MonitoringSource
from .monitoring_target_policy import (
    MonitoringTargetPolicy,
    MonitoringTargetRejected,
    PinnedMonitoringTarget,
)
from .prometheus_http_adapter import (
    MonitoringJsonTransport,
    _authorization_headers,
    _parse_sample,
    _quote_identifier,
    _selectors,
)

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_RANGE_SERIES = 10_000
_QUERY_DEADLINE_SECONDS = 10.0
_CPU_MODES = frozenset({"idle", "iowait", "steal"})


@dataclass(frozen=True, slots=True)
class _RangeSeries:
    identity: tuple[tuple[str, str], ...]
    labels: dict[str, str]
    samples: tuple[HostMetricPoint, ...]


class _RangeQueryFailure(RuntimeError):
    def __init__(self, reason: HostMetricReason):
        self.reason = reason


class PrometheusHostMetricsAdapter(HostMetricsQueryPort):
    """Translate finite node-exporter-v1 ranges into HOST metric facts."""

    def __init__(
        self, policy: MonitoringTargetPolicy, transport: MonitoringJsonTransport
    ) -> None:
        self._policy = policy
        self._transport = transport

    async def read_host_metrics(
        self,
        source: MonitoringSource,
        query: HostMetricsQuery,
        credentials: MonitoringProbeCredentials | None,
    ) -> HostMetricsSnapshot:
        try:
            target = await self._policy.resolve(
                source.endpoint,
                authenticated=source.authentication_mode.value != "none",
            )
        except MonitoringTargetRejected:
            return _empty_snapshot(source, query, HostMetricReason.TARGET_REJECTED)
        headers = _authorization_headers(source, credentials)
        if headers is None:
            return _empty_snapshot(source, query, HostMetricReason.AUTHENTICATION)

        identity_group = ",".join(
            _quote_identifier(label) for label in source.identity_labels
        )
        selectors = _selectors(source)
        cpu_matchers = _merge_matchers(selectors, 'mode=~"idle|iowait|steal"')
        cpu_expr = (
            f"1 - avg by ({identity_group}) ("
            f"sum by ({identity_group},cpu) ("
            f"rate(node_cpu_seconds_total{{{cpu_matchers}}}[5m])))"
        )
        cpu_integrity_expr = (
            f"count by ({identity_group},cpu,mode) "
            f"(node_cpu_seconds_total{{{cpu_matchers}}})"
        )
        idle_matchers = _merge_matchers(selectors, 'mode="idle"')
        cpu_inventory_expr = (
            f"count by ({identity_group},cpu) "
            f"(node_cpu_seconds_total{{{idle_matchers}}})"
        )
        target_health_expr = (
            f"min by ({identity_group}) "
            f"(up{{{selectors}}} and "
            f"(time() - timestamp(up{{{selectors}}}) < {source.stale_after_seconds}))"
        )
        expressions = (
            cpu_expr,
            cpu_integrity_expr,
            cpu_inventory_expr,
            _selector("node_memory_MemTotal_bytes", selectors),
            _selector("node_memory_MemAvailable_bytes", selectors),
            _selector("node_load1", selectors),
            target_health_expr,
        )
        try:
            async with asyncio.timeout(_QUERY_DEADLINE_SECONDS):
                responses = await asyncio.gather(
                    *(
                        self._query_range(
                            target, source.endpoint, expression, query, headers
                        )
                        for expression in expressions
                    )
                )
        except TimeoutError:
            return _empty_snapshot(source, query, HostMetricReason.TIMEOUT)
        except _RangeQueryFailure as error:
            return _empty_snapshot(source, query, error.reason)
        except (aiohttp.ClientError, OSError, ConnectionError, RuntimeError):
            return _empty_snapshot(source, query, HostMetricReason.TRANSPORT)

        try:
            cpu_series = _parse_range_series(
                responses[0], source.identity_labels, query
            )
            cpu_integrity = _parse_integrity_series(
                responses[1], source.identity_labels, query
            )
            cpu_inventory = _parse_inventory_series(
                responses[2], source.identity_labels, query
            )
            memory_total = _parse_range_series(
                responses[3], source.identity_labels, query
            )
            memory_available = _parse_range_series(
                responses[4], source.identity_labels, query
            )
            load = _parse_range_series(responses[5], source.identity_labels, query)
            target_health = _parse_range_series(
                responses[6], source.identity_labels, query
            )
        except _InvalidRangeResponse:
            return _empty_snapshot(source, query, HostMetricReason.INVALID_RESPONSE)

        try:
            identities = _all_identities(
                cpu_series,
                memory_total,
                memory_available,
                load,
                cpu_inventory,
                target_health,
            )
        except _InvalidRangeResponse:
            return _empty_snapshot(source, query, HostMetricReason.CONFLICTING_IDENTITY)
        if len(identities) > MAX_HOST_METRIC_HOSTS:
            return _empty_snapshot(source, query, HostMetricReason.INVALID_RESPONSE)
        if not identities:
            return HostMetricsSnapshot(
                source.source_id,
                source.environment_id,
                query,
                datetime.now(UTC),
                HostMetricQuality.NO_SAMPLES,
                HostMetricReason.MISSING_SAMPLES,
                (),
            )

        integrity_by_host = _integrity_by_identity(cpu_integrity)
        cpu_by_host = _single_by_identity(cpu_series)
        total_by_host = _single_by_identity(memory_total)
        available_by_host = _single_by_identity(memory_available)
        load_by_host = _single_by_identity(load)
        target_health_by_host = _single_by_identity(target_health)
        hosts: list[HostMetricsHost] = []
        for host_key, labels in identities.items():
            expected_cpus = cpu_inventory.get(host_key)
            actual_modes = integrity_by_host.get(host_key, {})
            cpu_conflict = _cpu_inventory_conflict(expected_cpus, actual_modes)
            series = tuple(
                _mark_stale_if_target_unhealthy(
                    metric,
                    target_health_by_host.get(host_key),
                    query,
                    source.stale_after_seconds,
                )
                for metric in (
                    _cpu_metric(
                        cpu_by_host.get(host_key),
                        query,
                        source.stale_after_seconds,
                        cpu_conflict,
                    ),
                    _memory_metric(
                        HostMetricKind.MEMORY_USED_BYTES,
                        total_by_host.get(host_key),
                        available_by_host.get(host_key),
                        query,
                        source.stale_after_seconds,
                    ),
                    _memory_metric(
                        HostMetricKind.MEMORY_USED_RATIO,
                        total_by_host.get(host_key),
                        available_by_host.get(host_key),
                        query,
                        source.stale_after_seconds,
                    ),
                    _simple_metric(
                        HostMetricKind.LOAD_1M,
                        load_by_host.get(host_key),
                        query,
                        source.stale_after_seconds,
                    ),
                )
            )
            identity_labels = tuple(
                (name, labels[name]) for name in source.identity_labels
            )
            host_id = json.dumps(
                identity_labels, ensure_ascii=True, separators=(",", ":")
            )
            hosts.append(
                HostMetricsHost(
                    HostMetricIdentity(host_id=host_id, labels=identity_labels),
                    series,
                )
            )

        metric_qualities = [metric.quality for host in hosts for metric in host.metrics]
        if metric_qualities and all(
            quality is HostMetricQuality.AVAILABLE for quality in metric_qualities
        ):
            quality = HostMetricQuality.AVAILABLE
            reason = None
        elif HostMetricQuality.STALE in metric_qualities:
            quality = HostMetricQuality.STALE
            reason = HostMetricReason.STALE_SAMPLES
        elif HostMetricQuality.PARTIAL in metric_qualities:
            quality = HostMetricQuality.PARTIAL
            reason = HostMetricReason.MISSING_SAMPLES
        elif all(
            quality is HostMetricQuality.NO_SAMPLES for quality in metric_qualities
        ):
            quality = HostMetricQuality.NO_SAMPLES
            reason = HostMetricReason.MISSING_SAMPLES
        else:
            quality = HostMetricQuality.PARTIAL
            reason = HostMetricReason.MISSING_SAMPLES
        return HostMetricsSnapshot(
            source.source_id,
            source.environment_id,
            query,
            datetime.now(UTC),
            quality,
            reason,
            tuple(hosts),
        )

    async def _query_range(
        self,
        target: PinnedMonitoringTarget,
        endpoint: str,
        expression: str,
        query: HostMetricsQuery,
        headers: dict[str, str],
    ) -> dict[str, object]:
        status, body, _response_headers = await self._transport.request_raw(
            target=target,
            endpoint=endpoint,
            method="GET",
            path="/api/v1/query_range",
            params={
                "query": expression,
                "start": _unix_seconds(query.start_at),
                "end": _unix_seconds(query.last_inclusive_at),
                "step": f"{query.step_ms / 1000:g}",
            },
            # The pinned transport keeps decompression disabled so response
            # size limits remain meaningful. Prometheus otherwise negotiates
            # gzip and the JSON parser would see compressed bytes.
            headers={**headers, "Accept-Encoding": "identity"},
        )
        if status in {401, 403}:
            raise _RangeQueryFailure(HostMetricReason.AUTHENTICATION)
        if not 200 <= status < 300 or len(body) > _MAX_RESPONSE_BYTES:
            raise _RangeQueryFailure(HostMetricReason.INVALID_RESPONSE)
        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise _RangeQueryFailure(HostMetricReason.INVALID_RESPONSE) from None
        if not isinstance(decoded, dict) or decoded.get("status") != "success":
            raise _RangeQueryFailure(HostMetricReason.INVALID_RESPONSE)
        data = decoded.get("data")
        if not isinstance(data, dict) or data.get("resultType") != "matrix":
            raise _RangeQueryFailure(HostMetricReason.INVALID_RESPONSE)
        result = data.get("result")
        if (
            not isinstance(result, list)
            or len(result) > _MAX_RANGE_SERIES
            or any(not isinstance(item, dict) for item in result)
        ):
            raise _RangeQueryFailure(HostMetricReason.INVALID_RESPONSE)
        return cast(dict[str, object], {"result": result})


class _InvalidRangeResponse(ValueError):
    pass


def _parse_range_series(
    response: dict[str, object],
    identity_labels: tuple[str, ...],
    query: HostMetricsQuery,
) -> dict[str, list[_RangeSeries]]:
    result = response.get("result")
    if not isinstance(result, list):
        raise _InvalidRangeResponse
    output: dict[str, list[_RangeSeries]] = {}
    for item in result:
        labels = item.get("metric")
        values = item.get("values")
        if not isinstance(labels, dict) or not isinstance(values, list):
            raise _InvalidRangeResponse
        identity = _identity_tuple(labels, identity_labels)
        samples = _parse_values(values, query)
        key = _identity_key(identity)
        output.setdefault(key, []).append(
            _RangeSeries(identity=identity, labels=labels, samples=samples)
        )
    return output


def _parse_integrity_series(
    response: dict[str, object],
    identity_labels: tuple[str, ...],
    query: HostMetricsQuery,
) -> dict[str, dict[str, dict[str, tuple[HostMetricPoint, ...]]]]:
    result = response.get("result")
    if not isinstance(result, list):
        raise _InvalidRangeResponse
    output: dict[str, dict[str, dict[str, tuple[HostMetricPoint, ...]]]] = {}
    seen: set[tuple[str, str, str]] = set()
    for item in result:
        labels = item.get("metric")
        if not isinstance(labels, dict):
            raise _InvalidRangeResponse
        identity = _identity_key(_identity_tuple(labels, identity_labels))
        cpu = labels.get("cpu")
        mode = labels.get("mode")
        if (
            not isinstance(cpu, str)
            or not isinstance(mode, str)
            or mode not in _CPU_MODES
        ):
            raise _InvalidRangeResponse
        key = (identity, cpu, mode)
        if key in seen:
            raise _InvalidRangeResponse
        seen.add(key)
        counts = _parse_values(item.get("values"), query)
        if any(point.value != 1 for point in counts):
            output.setdefault(identity, {}).setdefault(cpu, {})[mode] = ()
        else:
            output.setdefault(identity, {}).setdefault(cpu, {})[mode] = counts
    return output


def _parse_inventory_series(
    response: dict[str, object],
    identity_labels: tuple[str, ...],
    query: HostMetricsQuery,
) -> dict[str, list[_RangeSeries]]:
    result = response.get("result")
    if not isinstance(result, list):
        raise _InvalidRangeResponse
    output: dict[str, list[_RangeSeries]] = {}
    for item in result:
        labels = item.get("metric")
        if not isinstance(labels, dict) or not isinstance(labels.get("cpu"), str):
            raise _InvalidRangeResponse
        identity = _identity_tuple(labels, identity_labels)
        samples = _parse_values(item.get("values"), query)
        if any(point.value != 1 for point in samples):
            samples = ()
        key = _identity_key(identity)
        output.setdefault(key, []).append(
            _RangeSeries(identity=identity, labels=labels, samples=samples)
        )
    return output


def _parse_values(
    values: object, query: HostMetricsQuery
) -> tuple[HostMetricPoint, ...]:
    if not isinstance(values, list) or len(values) > query.point_count:
        raise _InvalidRangeResponse
    output: list[HostMetricPoint] = []
    previous: datetime | None = None
    for pair in values:
        if not isinstance(pair, list) or len(pair) != 2:
            raise _InvalidRangeResponse
        timestamp = _parse_timestamp(pair[0])
        value = _parse_sample(pair[1])
        if timestamp is None or value is None:
            raise _InvalidRangeResponse
        try:
            at = datetime.fromtimestamp(timestamp, UTC)
        except (OverflowError, OSError, ValueError):
            raise _InvalidRangeResponse from None
        if at < query.start_at or at >= query.end_at or (previous and at <= previous):
            raise _InvalidRangeResponse
        output.append(HostMetricPoint(at, value))
        previous = at
    return tuple(output)


def _parse_timestamp(value: object) -> float | None:
    """Prometheus JSON encodes timestamps as numbers and samples as strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        timestamp = float(value)
    except ValueError:
        return None
    return timestamp if timestamp >= 0 and timestamp < 253402300800 else None


def _identity_tuple(
    labels: dict[object, object], identity_labels: tuple[str, ...]
) -> tuple[tuple[str, str], ...]:
    values = tuple((name, labels.get(name)) for name in identity_labels)
    if any(not isinstance(value, str) or not value.strip() for _name, value in values):
        raise _InvalidRangeResponse
    return cast(tuple[tuple[str, str], ...], values)


def _identity_key(identity: tuple[tuple[str, str], ...]) -> str:
    return json.dumps(identity, ensure_ascii=True, separators=(",", ":"))


def _all_identities(
    *collections: dict[str, list[_RangeSeries]],
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for collection in collections:
        for key, rows in collection.items():
            if not rows:
                continue
            labels = dict(rows[0].identity)
            if key in result and result[key] != labels:
                raise _InvalidRangeResponse
            result[key] = labels
    return result


def _single_by_identity(
    values: dict[str, list[_RangeSeries]],
) -> dict[str, tuple[HostMetricPoint, ...] | None]:
    return {
        key: rows[0].samples if len(rows) == 1 else None for key, rows in values.items()
    }


def _integrity_by_identity(
    values: dict[str, dict[str, dict[str, tuple[HostMetricPoint, ...]]]],
) -> dict[str, dict[str, set[str]]]:
    return {
        host: {
            cpu: {mode for mode, samples in modes.items() if samples}
            for cpu, modes in cpus.items()
        }
        for host, cpus in values.items()
    }


def _cpu_inventory_conflict(
    inventory: list[_RangeSeries] | None,
    modes: dict[str, set[str]],
) -> bool:
    if inventory is None or not inventory:
        return True
    cpu_values = [
        row.labels.get("cpu")
        for row in inventory
        if isinstance(row.labels.get("cpu"), str) and row.samples
    ]
    expected = set(cpu_values)
    if len(cpu_values) != len(expected):
        return True
    actual = {cpu for cpu, found in modes.items() if found == _CPU_MODES}
    return not expected or expected != actual


def _cpu_metric(
    samples: tuple[HostMetricPoint, ...] | None,
    query: HostMetricsQuery,
    stale_after_seconds: int,
    conflict: bool,
) -> HostMetricSeries:
    if conflict:
        return _empty_metric(
            HostMetricKind.CPU_BUSY_RATIO,
            HostMetricQuality.PARTIAL,
            HostMetricReason.DUPLICATE_SERIES,
        )
    return _validated_metric(
        HostMetricKind.CPU_BUSY_RATIO,
        samples,
        query,
        stale_after_seconds,
        lambda value: 0 <= value <= 1,
    )


def _memory_metric(
    kind: HostMetricKind,
    total: tuple[HostMetricPoint, ...] | None,
    available: tuple[HostMetricPoint, ...] | None,
    query: HostMetricsQuery,
    stale_after_seconds: int,
) -> HostMetricSeries:
    if total is None or available is None:
        return _empty_metric(
            kind, HostMetricQuality.PARTIAL, HostMetricReason.DUPLICATE_SERIES
        )
    available_by_time = {point.at: point.value for point in available}
    samples: list[HostMetricPoint] = []
    for total_point in total:
        available_value = available_by_time.get(total_point.at)
        if (
            available_value is None
            or total_point.value <= 0
            or available_value < 0
            or available_value > total_point.value
        ):
            continue
        value = (
            total_point.value - available_value
            if kind is HostMetricKind.MEMORY_USED_BYTES
            else 1 - available_value / total_point.value
        )
        samples.append(HostMetricPoint(total_point.at, value))
    if not samples:
        return _empty_metric(
            kind, HostMetricQuality.NO_SAMPLES, HostMetricReason.MISSING_SAMPLES
        )
    quality, reason = _quality_for_samples(samples, query, stale_after_seconds)
    if len(samples) != len(total) or len(samples) != len(available):
        quality, reason = HostMetricQuality.PARTIAL, HostMetricReason.MISSING_SAMPLES
    return HostMetricSeries(kind, quality, reason, tuple(samples))


def _simple_metric(
    kind: HostMetricKind,
    samples: tuple[HostMetricPoint, ...] | None,
    query: HostMetricsQuery,
    stale_after_seconds: int,
) -> HostMetricSeries:
    return _validated_metric(
        kind,
        samples,
        query,
        stale_after_seconds,
        lambda value: value >= 0,
    )


def _validated_metric(
    kind: HostMetricKind,
    samples: tuple[HostMetricPoint, ...] | None,
    query: HostMetricsQuery,
    stale_after_seconds: int,
    is_valid: Callable[[float], bool],
) -> HostMetricSeries:
    if samples is None:
        return _empty_metric(
            kind, HostMetricQuality.PARTIAL, HostMetricReason.DUPLICATE_SERIES
        )
    if not samples:
        return _empty_metric(
            kind, HostMetricQuality.NO_SAMPLES, HostMetricReason.MISSING_SAMPLES
        )
    valid_samples = tuple(sample for sample in samples if is_valid(sample.value))
    if len(valid_samples) != len(samples):
        return _empty_metric(
            kind, HostMetricQuality.PARTIAL, HostMetricReason.INVALID_RESPONSE
        )
    quality, reason = _quality_for_samples(valid_samples, query, stale_after_seconds)
    return HostMetricSeries(kind, quality, reason, valid_samples)


def _quality_for_samples(
    samples: list[HostMetricPoint] | tuple[HostMetricPoint, ...],
    query: HostMetricsQuery,
    stale_after_seconds: int,
) -> tuple[HostMetricQuality, HostMetricReason | None]:
    if samples[-1].at < query.last_inclusive_at - timedelta(
        seconds=stale_after_seconds
    ):
        return HostMetricQuality.STALE, HostMetricReason.STALE_SAMPLES
    if len(samples) < query.point_count:
        return HostMetricQuality.PARTIAL, HostMetricReason.MISSING_SAMPLES
    return HostMetricQuality.AVAILABLE, None


def _mark_stale_if_target_unhealthy(
    metric: HostMetricSeries,
    target_health: tuple[HostMetricPoint, ...] | None,
    query: HostMetricsQuery,
    stale_after_seconds: int,
) -> HostMetricSeries:
    """Do not treat PromQL-derived values as live when their scrape target is not."""
    if not metric.samples:
        return metric
    health_is_current = (
        target_health is not None
        and bool(target_health)
        and target_health[-1].value == 1
        and target_health[-1].at
        >= query.last_inclusive_at - timedelta(seconds=stale_after_seconds)
    )
    if health_is_current:
        return metric
    return HostMetricSeries(
        metric.kind,
        HostMetricQuality.STALE,
        HostMetricReason.STALE_SAMPLES,
        metric.samples,
    )


def _empty_metric(
    kind: HostMetricKind,
    quality: HostMetricQuality,
    reason: HostMetricReason,
) -> HostMetricSeries:
    return HostMetricSeries(kind, quality, reason, ())


def _empty_snapshot(
    source: MonitoringSource, query: HostMetricsQuery, reason: HostMetricReason
) -> HostMetricsSnapshot:
    return HostMetricsSnapshot(
        source.source_id,
        source.environment_id,
        query,
        datetime.now(UTC),
        HostMetricQuality.UNAVAILABLE,
        reason,
        (),
    )


def _selector(metric: str, selectors: str) -> str:
    return f"{metric}{{{selectors}}}" if selectors else metric


def _merge_matchers(base: str, additional: str) -> str:
    return f"{base},{additional}" if base else additional


def _unix_seconds(value: datetime) -> str:
    return f"{value.timestamp():.6f}".rstrip("0").rstrip(".")


__all__ = ["PrometheusHostMetricsAdapter"]
