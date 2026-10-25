"""SQL Adapter for bounded Metrics V2 history queries."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from atlas_richie.contracts.reporting.v2 import HTTP_REQUEST_DURATION_BOUNDARIES_NS
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ...application.instance_catalog_ports import InstanceCatalogAuthorityUnavailable
from ...application.metrics_ports import MetricsReader
from ...domain.instance_catalog import (
    METRIC_DENOMINATORS,
    METRIC_UNITS,
    MetricQuality,
    MetricReading,
    ObservationCoverage,
    ObservationScope,
)
from ...domain.instance_observation import (
    MetricBundle,
    MetricQuery,
    MetricSample,
    MetricSeries,
)
from ...domain.metrics_rollups import MetricContributionQuality
from ...domain.observation_limits import MAX_OBSERVATION_POINTS
from .models import MetricsMinuteRollupRecord, MetricsReporterBindingRecord

_SOURCE_ID = "metrics-v2-collector"
_MINUTE = timedelta(minutes=1)
_MAX_STEP_MS = 7 * 24 * 60 * 60 * 1_000
_STALE_AFTER = timedelta(seconds=3)
_RATE_METRICS = frozenset({"http_qps", "resource_entry_rate", "tps"})
_RATIO_METRICS = frozenset({"blocked_ratio"})
_HISTOGRAM_METRICS = frozenset({"rt_p95"})
_GAUGE_METRICS = frozenset({"cpu_ratio", "memory_bytes", "memory_ratio"})


class SQLAlchemyMetricsHistoryReader(MetricsReader):
    """Read stored per-reporter rollups and aggregate without SQL dialect logic."""

    def __init__(self, engine_resolver: Callable[[], Awaitable[AsyncEngine]]) -> None:
        self._engine_resolver = engine_resolver

    async def read_metrics(self, query: MetricQuery) -> MetricBundle:
        """Return bounded historical series for one exact Console query."""
        if not isinstance(query, MetricQuery):
            raise TypeError("metrics query is required")
        as_of = datetime.now(UTC)
        context = query.context
        try:
            sessions = async_sessionmaker(
                await self._engine_resolver(), expire_on_commit=False
            )
            async with sessions() as session:
                reporters, has_enrolled_reporters = await self._read_reporters(
                    session, query, as_of
                )
                rows = await self._read_rollups(session, query)
        except SQLAlchemyError:
            raise InstanceCatalogAuthorityUnavailable(
                "metrics history is unavailable"
            ) from None

        samples_by_metric = self._project_series(query, rows)
        stale = (
            context.window.ends_at >= as_of - _STALE_AFTER
            and has_enrolled_reporters
            and not reporters
        )
        series: list[MetricSeries] = []
        summary: list[MetricReading] = []
        for metric in query.metrics:
            metric_samples = samples_by_metric[metric]
            metric_rows = [row for row in rows if row.metric_name == metric]
            metric_reporting = _metric_reporting(metric, metric_rows)
            metric_coverage = ObservationCoverage(
                expected=None,
                inventory_source=None,
                reporting=metric_reporting,
            )
            quality = _metric_quality(
                metric,
                rows,
                metric_samples,
                metric_reporting,
                stale,
                context.scope in (ObservationScope.HOST, ObservationScope.CONTAINER),
            )
            latest = next(
                (
                    sample
                    for sample in reversed(metric_samples)
                    if sample.value is not None
                ),
                None,
            )
            summary.append(
                MetricReading(
                    source=_SOURCE_ID,
                    denominator=METRIC_DENOMINATORS[metric],
                    coverage=metric_coverage,
                    quality=quality,
                    metric=metric,
                    unit=METRIC_UNITS[metric],
                    value=latest.value if latest is not None else None,
                    sampled_at=latest.at if latest is not None else None,
                )
            )
            series.append(
                MetricSeries(
                    source=_SOURCE_ID,
                    denominator=METRIC_DENOMINATORS[metric],
                    coverage=metric_coverage,
                    quality=quality,
                    metric=metric,
                    unit=METRIC_UNITS[metric],
                    samples=tuple(metric_samples),
                )
            )
        return MetricBundle(
            query=query,
            as_of=as_of,
            summary=tuple(summary),
            series=tuple(series),
            annotations=(),
        )

    async def _read_reporters(
        self,
        session: AsyncSession,
        query: MetricQuery,
        as_of: datetime,
    ) -> tuple[tuple[str, ...], bool]:
        context = query.context
        statement = select(MetricsReporterBindingRecord).where(
            MetricsReporterBindingRecord.environment_id == context.environment_id,
            MetricsReporterBindingRecord.revoked_at.is_(None),
            MetricsReporterBindingRecord.last_received_at.is_not(None),
        )
        if context.app_id is not None:
            statement = statement.where(
                MetricsReporterBindingRecord.app_id == context.app_id
            )
        if context.instance_id is not None:
            statement = statement.where(
                MetricsReporterBindingRecord.instance_id == context.instance_id
            )
        records = (await session.scalars(statement)).all()
        fresh: list[str] = []
        for record in records:
            received_at = _normalize_utc(record.last_received_at)
            if timedelta(0) <= as_of - received_at <= _STALE_AFTER:
                fresh.append(record.reporter_id)
        return tuple(fresh), bool(records)

    async def _read_rollups(
        self, session: AsyncSession, query: MetricQuery
    ) -> tuple[MetricsMinuteRollupRecord, ...]:
        context = query.context
        if context.scope in (ObservationScope.HOST, ObservationScope.CONTAINER):
            return ()
        window_start = _ceil_minute(context.window.starts_at)
        window_end = _floor_minute(context.window.ends_at)
        if window_start >= window_end:
            return ()
        statement = select(MetricsMinuteRollupRecord).where(
            MetricsMinuteRollupRecord.environment_id == context.environment_id,
            MetricsMinuteRollupRecord.bucket_started_at >= window_start,
            MetricsMinuteRollupRecord.bucket_started_at < window_end,
            MetricsMinuteRollupRecord.metric_name.in_(query.metrics),
            MetricsMinuteRollupRecord.reporter_id.is_not(None),
            MetricsMinuteRollupRecord.startup_epoch.is_not(None),
        )
        if context.app_id is not None:
            statement = statement.where(
                MetricsMinuteRollupRecord.app_id == context.app_id
            )
        if context.instance_id is not None:
            statement = statement.where(
                MetricsMinuteRollupRecord.instance_id == context.instance_id
            )
        if context.resource is not None:
            statement = statement.where(
                MetricsMinuteRollupRecord.resource_id == context.resource
            )
        statement = statement.order_by(
            MetricsMinuteRollupRecord.bucket_started_at,
            MetricsMinuteRollupRecord.metric_name,
            MetricsMinuteRollupRecord.reporter_id,
        )
        return tuple((await session.scalars(statement)).all())

    def _project_series(
        self,
        query: MetricQuery,
        rows: tuple[MetricsMinuteRollupRecord, ...],
    ) -> dict[str, list[MetricSample]]:
        context = query.context
        start = _ceil_minute(context.window.starts_at)
        end = _floor_minute(context.window.ends_at)
        if start >= end:
            return {metric: [] for metric in query.metrics}
        step = timedelta(milliseconds=_effective_step_ms(query, start, end))
        slots = _slots(start, end, step)
        grouped_rows: dict[tuple[str, datetime], list[MetricsMinuteRollupRecord]] = (
            defaultdict(list)
        )
        for row in rows:
            bucket = _normalize_utc(row.bucket_started_at)
            slot_start = start + ((bucket - start) // step) * step
            if slot_start < end:
                grouped_rows[(row.metric_name, slot_start)].append(row)

        result: dict[str, list[MetricSample]] = {}
        for metric in query.metrics:
            metric_samples: list[MetricSample] = []
            for slot_start, slot_end in slots:
                contribution_rows = grouped_rows.get((metric, slot_start), [])
                value = _aggregate_value(metric, contribution_rows)
                sample_at = slot_start + (slot_end - slot_start) / 2
                metric_samples.append(MetricSample(sample_at, value))
            result[metric] = metric_samples
        return result


def _aggregate_value(
    metric: str, rows: list[MetricsMinuteRollupRecord]
) -> float | int | None:
    if not rows:
        return None
    payloads = [_payload(row, metric) for row in rows]
    if metric in _RATE_METRICS:
        delta = sum(int(payload["delta"]) for payload in payloads)
        elapsed_ns = sum(int(payload["elapsed_ns"]) for payload in payloads)
        return delta * 1_000_000_000 / elapsed_ns if elapsed_ns else None
    if metric in _RATIO_METRICS:
        numerator = sum(int(payload["numerator"]) for payload in payloads)
        denominator = sum(int(payload["denominator"]) for payload in payloads)
        return numerator / denominator if denominator else None
    if metric in _HISTOGRAM_METRICS:
        counts = [0] * (len(HTTP_REQUEST_DURATION_BOUNDARIES_NS) + 1)
        for payload in payloads:
            current = payload["histogram_buckets"]
            for index, count in enumerate(current):
                counts[index] += int(count)
        sample_count = sum(counts)
        if sample_count == 0:
            return None
        rank = (sample_count * 95 + 99) // 100
        cumulative = 0
        for boundary, count in zip(
            HTTP_REQUEST_DURATION_BOUNDARIES_NS, counts[:-1], strict=True
        ):
            cumulative += count
            if cumulative >= rank:
                return boundary / 1_000_000
        return None
    if metric in _GAUGE_METRICS:
        valid = [
            payload
            for payload in payloads
            if payload["quality"] == MetricContributionQuality.AVAILABLE.value
            and payload.get("gauge_value") is not None
        ]
        if not valid:
            return None
        if len({payload["reporter_id"] for payload in valid}) > 1 and metric in {
            "cpu_ratio",
            "memory_ratio",
        }:
            return None
        values = [payload["gauge_value"] for payload in valid]
        if metric == "memory_bytes":
            return sum(values)
        return values[0]
    return None


def _payload(row: MetricsMinuteRollupRecord, metric: str) -> dict[str, object]:
    payload = row.payload
    if not isinstance(payload, dict) or not _is_valid_payload(payload, metric):
        raise InstanceCatalogAuthorityUnavailable(
            "metrics history contains an invalid rollup"
        )
    return {**payload, "reporter_id": row.reporter_id}


def _is_valid_payload(payload: dict[str, object], metric: str) -> bool:
    try:
        if metric in _RATE_METRICS:
            return int(payload["delta"]) >= 0 and int(payload["elapsed_ns"]) > 0
        if metric in _RATIO_METRICS:
            return int(payload["numerator"]) >= 0 and int(payload["denominator"]) >= 0
        if metric in _HISTOGRAM_METRICS:
            values = payload["histogram_buckets"]
            return (
                isinstance(values, list)
                and len(values) == len(HTTP_REQUEST_DURATION_BOUNDARIES_NS) + 1
                and all(type(value) is int and value >= 0 for value in values)
                and int(payload["histogram_sample_count"]) == sum(values)
            )
        if metric in _GAUGE_METRICS:
            return payload.get("quality") in {
                MetricContributionQuality.AVAILABLE.value,
                MetricContributionQuality.UNAVAILABLE.value,
            }
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return False


def _metric_quality(
    metric: str,
    rows: tuple[MetricsMinuteRollupRecord, ...],
    samples: list[MetricSample],
    reporting: int,
    stale: bool,
    scope_unavailable: bool,
) -> MetricQuality:
    matching = [row for row in rows if row.metric_name == metric]
    if scope_unavailable:
        return MetricQuality.NOT_INTEGRATED
    if (
        metric in _GAUGE_METRICS
        and matching
        and all(
            row.payload.get("quality") == MetricContributionQuality.UNAVAILABLE.value
            for row in matching
        )
    ):
        return MetricQuality.NOT_INTEGRATED
    if metric in _RATIO_METRICS and any(
        row.payload.get("quality") == MetricContributionQuality.UNAVAILABLE.value
        for row in matching
    ):
        return MetricQuality.PARTIAL
    if stale:
        return MetricQuality.STALE
    if reporting == 0:
        return MetricQuality.NO_SAMPLES
    if any(sample.value is None for sample in samples):
        return MetricQuality.PARTIAL
    # Expected reporter inventory is not authoritative; available is therefore
    # intentionally never claimed for fleet/application queries.
    return MetricQuality.PARTIAL


def _metric_reporting(metric: str, rows: list[MetricsMinuteRollupRecord]) -> int:
    reporter_ids: set[str] = set()
    for row in rows:
        if row.reporter_id is None:
            continue
        payload = _payload(row, metric)
        if metric in _GAUGE_METRICS and (
            payload.get("quality") != MetricContributionQuality.AVAILABLE.value
            or payload.get("gauge_value") is None
        ):
            continue
        if metric in _RATIO_METRICS and int(payload.get("denominator", 0)) == 0:
            continue
        if (
            metric in _HISTOGRAM_METRICS
            and int(payload.get("histogram_sample_count", 0)) == 0
        ):
            continue
        reporter_ids.add(row.reporter_id)
    return len(reporter_ids)


def _effective_step_ms(query: MetricQuery, start: datetime, end: datetime) -> int:
    requested = max(query.step_ms, 60_000)
    duration_ms = (end - start).total_seconds() * 1_000
    required = int((duration_ms + MAX_OBSERVATION_POINTS - 1) // MAX_OBSERVATION_POINTS)
    rounded = ((max(requested, required) + 59_999) // 60_000) * 60_000
    return min(rounded, _MAX_STEP_MS)


def _slots(
    start: datetime, end: datetime, step: timedelta
) -> tuple[tuple[datetime, datetime], ...]:
    slots: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end and len(slots) < MAX_OBSERVATION_POINTS:
        slot_end = min(cursor + step, end)
        slots.append((cursor, slot_end))
        cursor = slot_end
    return tuple(slots)


def _ceil_minute(value: datetime) -> datetime:
    normalized = _normalize_utc(value)
    floored = _floor_minute(normalized)
    return floored if normalized == floored else floored + _MINUTE


def _floor_minute(value: datetime) -> datetime:
    return _normalize_utc(value).replace(second=0, microsecond=0)


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["SQLAlchemyMetricsHistoryReader"]
