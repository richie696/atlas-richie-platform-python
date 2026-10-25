"""SQL Adapter projecting enrolled Metrics V2 workers into the instance directory."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from atlas_richie.contracts.reporting.v2 import (
    HTTP_REQUEST_DURATION_BOUNDARIES_NS,
    MetricsSnapshot,
    MetricsV2ProtocolError,
    decode_metrics_snapshot,
)
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ...application.instance_catalog_ports import (
    InstanceCatalogAuthorityUnavailable,
    InstanceCatalogReader,
)
from ...domain.instance_catalog import (
    METRIC_DENOMINATORS,
    METRIC_UNITS,
    OPERATIONAL_METRIC_NAMES,
    InstanceCatalogQuery,
    InstanceCatalogSnapshot,
    InstanceHealth,
    InstanceLayer,
    InstanceRuleReceipt,
    MetricQuality,
    MetricReading,
    ObservationCoverage,
    ObservedInstance,
    RuleReceiptState,
)
from ...domain.metrics_rollups import (
    MetricContributionQuality,
    MetricIntervalContribution,
    build_metric_interval_contributions,
)
from .models import MetricsReporterBindingRecord, MetricsSnapshotRecord

_REPORTER_SOURCE = "metrics-v2-reporter"
_STALE_AFTER = timedelta(seconds=3)
_METRIC_SOURCE = "metrics-v2"
_NANOSECONDS_PER_SECOND = 1_000_000_000


class SQLAlchemyMetricsInstanceCatalogReader(InstanceCatalogReader):
    """Read process-per-worker identity, freshness, and Metrics V2 values."""

    def __init__(
        self,
        engine_resolver: Callable[[], Awaitable[AsyncEngine]],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine_resolver = engine_resolver
        self._clock = clock or (lambda: datetime.now(UTC))

    async def read_instance_catalog(
        self, query: InstanceCatalogQuery
    ) -> InstanceCatalogSnapshot:
        """Return the bounded worker directory from enrollment and accepted snapshots."""
        if not isinstance(query, InstanceCatalogQuery):
            raise TypeError("instance catalog query is required")
        as_of = self._clock()
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("catalog clock must return an aware instant")
        as_of = as_of.astimezone(UTC)
        try:
            engine = await self._engine_resolver()
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                records, total, attention, fresh, filtered = await self._read_bindings(
                    session, query, as_of
                )
                items = await self._read_page_instances(session, query, records, as_of)
        except (SQLAlchemyError, MetricsV2ProtocolError):
            raise InstanceCatalogAuthorityUnavailable(
                "instance catalog authority is unavailable"
            ) from None
        return InstanceCatalogSnapshot(
            query=query,
            as_of=as_of,
            coverage=ObservationCoverage(None, None, fresh),
            total_instances=total,
            attention_instances=attention,
            filtered_total=filtered,
            items=items,
        )

    async def _read_bindings(
        self, session: AsyncSession, query: InstanceCatalogQuery, as_of: datetime
    ) -> tuple[tuple[MetricsReporterBindingRecord, ...], int, int, int, int]:
        base = (
            MetricsReporterBindingRecord.environment_id == query.environment_id,
            MetricsReporterBindingRecord.revoked_at.is_(None),
            MetricsReporterBindingRecord.last_received_at.is_not(None),
            MetricsReporterBindingRecord.current_epoch.is_not(None),
        )
        if query.app_id is not None:
            base += (MetricsReporterBindingRecord.app_id == query.app_id,)
        base_statement = select(MetricsReporterBindingRecord).where(*base)
        total = int(
            await session.scalar(
                select(func.count()).select_from(
                    select(MetricsReporterBindingRecord.certificate_principal)
                    .where(*base)
                    .subquery()
                )
            )
            or 0
        )
        stale_expression = or_(
            MetricsReporterBindingRecord.last_received_at < as_of - _STALE_AFTER,
            MetricsReporterBindingRecord.last_received_at > as_of,
        )
        attention = int(
            await session.scalar(
                select(func.count()).select_from(
                    select(MetricsReporterBindingRecord.certificate_principal)
                    .where(*base, stale_expression)
                    .subquery()
                )
            )
            or 0
        )
        fresh = total - attention
        filtered_statement = base_statement
        search = query.search.strip()
        if search:
            search_expression = or_(
                MetricsReporterBindingRecord.app_id.icontains(search, autoescape=True),
                MetricsReporterBindingRecord.instance_id.icontains(
                    search, autoescape=True
                ),
                MetricsReporterBindingRecord.process_id.icontains(
                    search, autoescape=True
                ),
            )
            filtered_statement = filtered_statement.where(search_expression)
        if query.attention_only:
            filtered_statement = filtered_statement.where(stale_expression)
        filtered = int(
            await session.scalar(
                select(func.count()).select_from(
                    filtered_statement.with_only_columns(
                        MetricsReporterBindingRecord.certificate_principal
                    ).subquery()
                )
            )
            or 0
        )
        page_statement = (
            filtered_statement.order_by(
                MetricsReporterBindingRecord.app_id,
                MetricsReporterBindingRecord.instance_id,
            )
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
        page_records = tuple((await session.scalars(page_statement)).all())
        return page_records, total, attention, fresh, filtered

    async def _read_page_instances(
        self,
        session: AsyncSession,
        query: InstanceCatalogQuery,
        records: tuple[MetricsReporterBindingRecord, ...],
        as_of: datetime,
    ) -> tuple[ObservedInstance, ...]:
        selected = records
        pairs = tuple(
            (row.certificate_principal, row.current_epoch)
            for row in selected
            if row.current_epoch is not None
        )
        snapshots = await self._read_latest_snapshots(
            session, pairs, query.window.ends_at
        )
        grouped: dict[tuple[str, str], list[MetricsSnapshotRecord]] = defaultdict(list)
        for snapshot in snapshots:
            grouped[(snapshot.certificate_principal, snapshot.startup_epoch)].append(
                snapshot
            )
        instances = tuple(
            _observed_instance(
                row,
                grouped.get((row.certificate_principal, row.current_epoch or ""), []),
                as_of,
                query,
            )
            for row in selected
        )
        return instances

    async def _read_latest_snapshots(
        self,
        session: AsyncSession,
        pairs: tuple[tuple[str, str], ...],
        ends_at: datetime,
    ) -> tuple[MetricsSnapshotRecord, ...]:
        if not pairs:
            return ()
        rank = (
            func.row_number()
            .over(
                partition_by=(
                    MetricsSnapshotRecord.certificate_principal,
                    MetricsSnapshotRecord.startup_epoch,
                ),
                order_by=MetricsSnapshotRecord.sequence.desc(),
            )
            .label("snapshot_rank")
        )
        identity_filter = or_(
            *(
                and_(
                    MetricsSnapshotRecord.certificate_principal == principal,
                    MetricsSnapshotRecord.startup_epoch == epoch,
                )
                for principal, epoch in pairs
            )
        )
        ranked = (
            select(
                MetricsSnapshotRecord.certificate_principal.label("principal"),
                MetricsSnapshotRecord.startup_epoch.label("epoch"),
                MetricsSnapshotRecord.sequence.label("sequence"),
                rank,
            )
            .where(
                identity_filter,
                MetricsSnapshotRecord.received_at < ends_at,
            )
            .subquery()
        )
        statement = (
            select(MetricsSnapshotRecord)
            .join(
                ranked,
                and_(
                    MetricsSnapshotRecord.certificate_principal == ranked.c.principal,
                    MetricsSnapshotRecord.startup_epoch == ranked.c.epoch,
                    MetricsSnapshotRecord.sequence == ranked.c.sequence,
                ),
            )
            .where(ranked.c.snapshot_rank <= 2)
            .order_by(
                MetricsSnapshotRecord.certificate_principal,
                MetricsSnapshotRecord.sequence.desc(),
            )
        )
        return tuple((await session.scalars(statement)).all())


def _observed_instance(
    record: MetricsReporterBindingRecord,
    snapshot_rows: list[MetricsSnapshotRecord],
    as_of: datetime,
    query: InstanceCatalogQuery,
) -> ObservedInstance:
    received_at = _normalize_utc(record.last_received_at)
    stale = _is_stale(received_at, as_of)
    ordered_rows = sorted(snapshot_rows, key=lambda item: item.sequence)
    decoded = tuple(decode_metrics_snapshot(row.body) for row in ordered_rows)
    if any(
        snapshot.reporter_id != record.reporter_id
        or str(snapshot.startup_epoch) != row.startup_epoch
        or snapshot.sequence != row.sequence
        or hashlib.sha256(row.body).hexdigest() != row.body_sha256
        for snapshot, row in zip(decoded, ordered_rows, strict=True)
    ):
        raise InstanceCatalogAuthorityUnavailable(
            "stored reporter snapshot identity is inconsistent"
        )
    latest_report_is_inside_query = received_at < query.window.ends_at
    if latest_report_is_inside_query and (
        not ordered_rows or ordered_rows[-1].sequence != record.last_sequence
    ):
        raise InstanceCatalogAuthorityUnavailable(
            "stored reporter baseline does not match its accepted snapshot"
        )
    metrics = (
        _empty_metrics(stale=True)
        if stale
        else _process_metrics(record, ordered_rows, decoded, received_at, query)
    )
    current_epoch = record.current_epoch
    if current_epoch is None:
        raise InstanceCatalogAuthorityUnavailable(
            "worker process incarnation is unavailable"
        )
    return ObservedInstance(
        instance_id=record.instance_id,
        app_id=record.app_id,
        environment_id=record.environment_id,
        host_id=None,
        container_id=None,
        process_id=record.process_id,
        process_epoch=current_epoch,
        health=InstanceHealth.ATTENTION if stale else InstanceHealth.HEALTHY,
        last_report_at=received_at,
        supported_scopes=(InstanceLayer.PROCESS,),
        rule_receipt=InstanceRuleReceipt(
            state=RuleReceiptState.UNKNOWN,
            desired_version_id=None,
            applied_version_id=None,
            process_epoch=current_epoch,
            received_at=None,
        ),
        process_metrics=metrics,
    )


def _process_metrics(
    record: MetricsReporterBindingRecord,
    snapshot_rows: list[MetricsSnapshotRecord],
    snapshots: tuple[MetricsSnapshot, ...],
    received_at: datetime,
    query: InstanceCatalogQuery,
) -> tuple[MetricReading, ...]:
    contributions: tuple[MetricIntervalContribution, ...] = ()
    metric_received_at = (
        _normalize_utc(snapshot_rows[-1].received_at)
        if snapshot_rows
        else received_at
    )
    if snapshots:
        latest = snapshots[-1]
        previous = snapshots[-2] if len(snapshots) > 1 else None
        previous_row = (
            _normalize_utc(snapshot_rows[-2].received_at)
            if previous is not None and len(snapshot_rows) >= 2
            else None
        )
        contributions = build_metric_interval_contributions(
            environment_id=record.environment_id,
            app_id=record.app_id,
            instance_id=record.instance_id,
            previous=previous,
            previous_received_at=previous_row,
            current=latest,
            received_at=metric_received_at,
        )
    values = _project_contributions(contributions)
    within_window = query.window.contains(metric_received_at)
    readings: list[MetricReading] = []
    for metric in OPERATIONAL_METRIC_NAMES:
        value = values.get(metric) if within_window else None
        available = value is not None
        coverage = ObservationCoverage(
            expected=1 if available else None,
            inventory_source=_REPORTER_SOURCE if available else None,
            reporting=1 if available else 0,
        )
        readings.append(
            MetricReading(
                source=_METRIC_SOURCE,
                denominator=METRIC_DENOMINATORS[metric],
                coverage=coverage,
                quality=(
                    MetricQuality.AVAILABLE if available else MetricQuality.NO_SAMPLES
                ),
                metric=metric,
                unit=METRIC_UNITS[metric],
                value=value,
                sampled_at=metric_received_at if available else None,
            )
        )
    return tuple(readings)


def _project_contributions(
    contributions: tuple[MetricIntervalContribution, ...],
) -> dict[str, float]:
    grouped: dict[str, list[MetricIntervalContribution]] = defaultdict(list)
    for contribution in contributions:
        grouped[contribution.metric].append(contribution)
    result: dict[str, float] = {}
    for metric in ("http_qps", "tps"):
        selected = grouped.get(metric, [])
        if selected and all(item.elapsed_ns for item in selected):
            elapsed_ns = sum(item.elapsed_ns or 0 for item in selected)
            delta = sum(item.delta or 0 for item in selected)
            if elapsed_ns:
                result[metric] = delta * _NANOSECONDS_PER_SECOND / elapsed_ns

    ratio_contributions = grouped.get("blocked_ratio", [])
    global_ratios = [item for item in ratio_contributions if item.resource is None]
    selected_ratios = global_ratios or ratio_contributions
    denominator = sum(item.denominator or 0 for item in selected_ratios)
    if denominator:
        result["blocked_ratio"] = (
            sum(item.numerator or 0 for item in selected_ratios) / denominator
        )

    histogram_contributions = grouped.get("rt_p95", [])
    global_histograms = [
        item for item in histogram_contributions if item.resource is None
    ]
    selected_histograms = global_histograms or histogram_contributions
    if selected_histograms:
        counts = [0] * (len(HTTP_REQUEST_DURATION_BOUNDARIES_NS) + 1)
        for item in selected_histograms:
            for index, count in enumerate(item.histogram_buckets or ()):
                counts[index] += count
        sample_count = sum(counts)
        if sample_count:
            rank = (sample_count * 95 + 99) // 100
            cumulative = 0
            for boundary, count in zip(
                HTTP_REQUEST_DURATION_BOUNDARIES_NS, counts[:-1], strict=True
            ):
                cumulative += count
                if cumulative >= rank:
                    result["rt_p95"] = boundary / 1_000_000
                    break

    for metric in ("cpu_ratio", "memory_ratio"):
        selected = grouped.get(metric, [])
        if selected and selected[-1].quality is MetricContributionQuality.AVAILABLE:
            value = selected[-1].gauge_value
            if value is not None:
                result[metric] = float(value)
    return result


def _empty_metrics(*, stale: bool) -> tuple[MetricReading, ...]:
    quality = MetricQuality.STALE if stale else MetricQuality.NO_SAMPLES
    return tuple(
        MetricReading(
            source=_METRIC_SOURCE,
            denominator=METRIC_DENOMINATORS[metric],
            coverage=ObservationCoverage(None, None, 0),
            quality=quality,
            metric=metric,
            unit=METRIC_UNITS[metric],
            value=None,
            sampled_at=None,
        )
        for metric in OPERATIONAL_METRIC_NAMES
    )


def _is_stale(received_at: datetime | None, as_of: datetime) -> bool:
    if received_at is None:
        return True
    age = as_of - _normalize_utc(received_at)
    return age < timedelta(0) or age > _STALE_AFTER


def _normalize_utc(value: datetime | None) -> datetime:
    if value is None:
        raise InstanceCatalogAuthorityUnavailable(
            "worker last receipt time is unavailable"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["SQLAlchemyMetricsInstanceCatalogReader"]
