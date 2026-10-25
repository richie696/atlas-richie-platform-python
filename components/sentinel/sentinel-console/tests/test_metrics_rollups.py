"""Pure Metrics V2 interval-to-UTC-rollup contribution contracts."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from atlas_richie.contracts.reporting.v2 import (
    HTTP_REQUEST_DURATION_BOUNDARIES_NS,
    CounterName,
    CounterReading,
    GaugeName,
    GaugeQuality,
    GaugeReading,
    HistogramName,
    HistogramReading,
    MetricsSnapshot,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atlas_richie.sentinel_console.application.metrics_ingest_ports import (
    MetricsReporterBinding,
)
from atlas_richie.sentinel_console.domain.instance_catalog import (
    ObservationScope,
    ObservationWindow,
)
from atlas_richie.sentinel_console.domain.instance_observation import (
    MetricQuery,
    ObservationContext,
)
from atlas_richie.sentinel_console.domain.metrics_rollups import (
    MetricContributionQuality,
    build_metric_interval_contributions,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_history_reader import (
    SQLAlchemyMetricsHistoryReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_history_store import (
    SQLAlchemyMetricsHistoryAdapter,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    MetricsMinuteRollupRecord,
    MetricsReporterBindingRecord,
)

_REPORTER_ID = "reporter-orders"
_EPOCH = uuid4()
_START = datetime(2026, 10, 14, 1, 2, tzinfo=UTC)


class MetricsRollupContributionTests(unittest.TestCase):
    def test_counter_rates_use_monotonic_interval_and_collector_minute_bucket(self):
        previous = _snapshot(sequence=1, elapsed_ns=1_000_000_000, http=100)
        current = _snapshot(sequence=2, elapsed_ns=3_000_000_000, http=140)

        contributions = build_metric_interval_contributions(
            environment_id="test",
            app_id="orders",
            instance_id="orders-1",
            previous=previous,
            previous_received_at=_START + timedelta(seconds=59),
            current=current,
            received_at=_START + timedelta(seconds=61, microseconds=900),
        )

        http = _find(contributions, "http_qps")
        assert http.delta == 40
        assert http.elapsed_ns == 2_000_000_000
        assert http.received_at == _START + timedelta(seconds=61, microseconds=900)
        assert http.bucket_started_at == _START + timedelta(minutes=1)

    def test_resource_rates_and_blocked_ratio_keep_resource_population(self):
        previous = _snapshot(
            sequence=1, elapsed_ns=1_000_000_000, admitted=10, blocked=2
        )
        current = _snapshot(
            sequence=2, elapsed_ns=2_000_000_000, admitted=15, blocked=5
        )

        contributions = build_metric_interval_contributions(
            environment_id="test",
            app_id="orders",
            instance_id="orders-1",
            previous=previous,
            previous_received_at=_START,
            current=current,
            received_at=_START + timedelta(seconds=1),
        )

        entries = _find(contributions, "resource_entry_rate")
        blocked = _find(contributions, "blocked_ratio")
        assert entries.resource == "POST /orders"
        assert (entries.delta, entries.elapsed_ns) == (8, 1_000_000_000)
        assert blocked.resource == entries.resource
        assert (blocked.numerator, blocked.denominator) == (3, 8)
        assert blocked.quality is MetricContributionQuality.AVAILABLE

    def test_zero_attempt_denominator_is_unavailable_not_zero_ratio(self):
        previous = _snapshot(
            sequence=1, elapsed_ns=1_000_000_000, admitted=4, blocked=1
        )
        current = _snapshot(sequence=2, elapsed_ns=2_000_000_000, admitted=4, blocked=1)

        contributions = build_metric_interval_contributions(
            environment_id="test",
            app_id="orders",
            instance_id="orders-1",
            previous=previous,
            previous_received_at=_START,
            current=current,
            received_at=_START + timedelta(seconds=1),
        )

        blocked = _find(contributions, "blocked_ratio")
        assert blocked.denominator == 0
        assert blocked.quality is MetricContributionQuality.UNAVAILABLE

    def test_histogram_overflow_is_preserved_as_a_distinct_quality(self):
        previous = _snapshot(
            sequence=1,
            elapsed_ns=1_000_000_000,
            histogram_count=1,
            include_histogram=True,
        )
        current = _snapshot(
            sequence=2,
            elapsed_ns=2_000_000_000,
            histogram_count=2,
            histogram_overflow=1,
            include_histogram=True,
        )

        contributions = build_metric_interval_contributions(
            environment_id="test",
            app_id="orders",
            instance_id="orders-1",
            previous=previous,
            previous_received_at=_START,
            current=current,
            received_at=_START + timedelta(seconds=1),
        )

        p95 = _find(contributions, "rt_p95")
        assert p95.histogram_sample_count == 1
        assert p95.histogram_buckets[-1] == 1
        assert p95.quality is MetricContributionQuality.OVERFLOW

    def test_new_epoch_or_stale_receipt_gap_rebaselines_rates_but_keeps_gauges(self):
        previous = _snapshot(sequence=1, elapsed_ns=1_000_000_000, http=100)
        current = _snapshot(sequence=2, elapsed_ns=2_000_000_000, http=110)
        gauges = (
            GaugeReading(GaugeName.PROCESS_CPU_RATIO, 0.25, GaugeQuality.AVAILABLE),
            GaugeReading(GaugeName.PROCESS_RSS_BYTES, None, GaugeQuality.UNAVAILABLE),
        )
        current = _snapshot(
            sequence=2,
            elapsed_ns=2_000_000_000,
            http=110,
            gauges=gauges,
        )

        stale_gap = build_metric_interval_contributions(
            environment_id="test",
            app_id="orders",
            instance_id="orders-1",
            previous=previous,
            previous_received_at=_START,
            current=current,
            received_at=_START + timedelta(seconds=4),
        )
        epoch_change = build_metric_interval_contributions(
            environment_id="test",
            app_id="orders",
            instance_id="orders-1",
            previous=previous,
            previous_received_at=_START,
            current=_snapshot(
                sequence=1,
                elapsed_ns=1_000_000_000,
                http=110,
                epoch=uuid4(),
                gauges=gauges,
            ),
            received_at=_START + timedelta(seconds=1),
        )

        assert {item.metric for item in stale_gap} == {"cpu_ratio", "memory_bytes"}
        assert {item.metric for item in epoch_change} == {"cpu_ratio", "memory_bytes"}
        assert (
            _find(stale_gap, "memory_bytes").quality
            is MetricContributionQuality.UNAVAILABLE
        )


class MetricsRollupPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_durable_rollup_is_atomic_and_exact_replay_does_not_double_count(
        self,
    ):
        with tempfile.TemporaryDirectory(prefix="sentinel-rollup-") as directory:
            engine = create_async_engine(f"sqlite+aiosqlite:///{directory}/db.sqlite3")
            try:
                await upgrade_database(engine)
                sessions = async_sessionmaker(engine, expire_on_commit=False)
                binding = MetricsReporterBinding(
                    certificate_principal="spiffe://sentinel.test/reporter/orders-1",
                    certificate_sha256="a" * 64,
                    reporter_id=_REPORTER_ID,
                    environment_id="test",
                    app_id="orders",
                    instance_id="orders-1",
                    process_id="orders-1-worker-0",
                )
                async with sessions.begin() as session:
                    session.add(
                        MetricsReporterBindingRecord(
                            certificate_principal=binding.certificate_principal,
                            certificate_sha256=binding.certificate_sha256,
                            reporter_id=binding.reporter_id,
                            environment_id=binding.environment_id,
                            app_id=binding.app_id,
                            instance_id=binding.instance_id,
                            process_id=binding.process_id,
                            last_sequence=0,
                        )
                    )

                async def resolve_engine():
                    return engine

                history = SQLAlchemyMetricsHistoryAdapter(resolve_engine)
                epoch = uuid4()
                first = _snapshot(
                    sequence=1,
                    elapsed_ns=1_000_000_000,
                    epoch=epoch,
                    http=100,
                    admitted=10,
                    blocked=2,
                    include_histogram=True,
                )
                second = _snapshot(
                    sequence=2,
                    elapsed_ns=2_000_000_000,
                    epoch=epoch,
                    http=140,
                    admitted=15,
                    blocked=5,
                    histogram_count=1,
                    include_histogram=True,
                )
                await _accept_rollup_snapshot(history, binding, first, _START)
                body = _encode_snapshot(second)
                receipt = await history.accept_snapshot(
                    binding=binding,
                    snapshot=second,
                    body=body,
                    body_sha256=hashlib.sha256(body).hexdigest(),
                    received_at=_START + timedelta(seconds=1),
                )
                replay = await history.accept_snapshot(
                    binding=binding,
                    snapshot=second,
                    body=body,
                    body_sha256=hashlib.sha256(body).hexdigest(),
                    received_at=_START + timedelta(seconds=20),
                )

                assert replay == receipt
                async with sessions() as session:
                    rows = (
                        await session.scalars(select(MetricsMinuteRollupRecord))
                    ).all()
                http = next(row for row in rows if row.metric_name == "http_qps")
                assert http.reporter_id == _REPORTER_ID
                assert http.startup_epoch == str(epoch)
                assert http.bucket_started_at.replace(tzinfo=UTC) == _START.replace(
                    second=0
                )
                assert http.payload == {
                    "delta": "40",
                    "elapsed_ns": "1000000000",
                    "quality": "available",
                }

                reader = SQLAlchemyMetricsHistoryReader(resolve_engine)
                query = MetricQuery(
                    context=ObservationContext(
                        environment_id="test",
                        app_id="orders",
                        instance_id="orders-1",
                        resource=None,
                        scope=ObservationScope.PROCESS,
                        window=ObservationWindow(
                            _START.replace(second=0),
                            _START.replace(second=0) + timedelta(minutes=1),
                        ),
                    ),
                    metrics=("http_qps", "rt_p95"),
                    step_ms=60_000,
                )
                bundle = await reader.read_metrics(query)
                assert bundle.query == query
                assert bundle.summary[0].value == 40
                assert bundle.series[0].samples[0].value == 40
                assert bundle.summary[0].quality.value == "partial"
                assert bundle.summary[1].value == 1.0

                second_binding = MetricsReporterBinding(
                    certificate_principal="spiffe://sentinel.test/reporter/orders-2",
                    certificate_sha256="b" * 64,
                    reporter_id="reporter-orders-2",
                    environment_id="test",
                    app_id="orders",
                    instance_id="orders-2",
                    process_id="orders-2-worker-0",
                )
                async with sessions.begin() as session:
                    session.add(
                        MetricsReporterBindingRecord(
                            certificate_principal=second_binding.certificate_principal,
                            certificate_sha256=second_binding.certificate_sha256,
                            reporter_id=second_binding.reporter_id,
                            environment_id=second_binding.environment_id,
                            app_id=second_binding.app_id,
                            instance_id=second_binding.instance_id,
                            process_id=second_binding.process_id,
                            last_sequence=0,
                        )
                    )
                second_epoch = uuid4()
                second_previous = _snapshot(
                    sequence=1,
                    elapsed_ns=1_000_000_000,
                    epoch=second_epoch,
                    http=100,
                    reporter_id=second_binding.reporter_id,
                    include_histogram=True,
                )
                second_current = _snapshot(
                    sequence=2,
                    elapsed_ns=3_000_000_000,
                    epoch=second_epoch,
                    http=160,
                    reporter_id=second_binding.reporter_id,
                    histogram_count=1,
                    histogram_overflow=1,
                    include_histogram=True,
                )
                await _accept_rollup_snapshot(
                    history,
                    second_binding,
                    second_previous,
                    _START + timedelta(seconds=5),
                )
                await _accept_rollup_snapshot(
                    history,
                    second_binding,
                    second_current,
                    _START + timedelta(seconds=6),
                )
                application_query = MetricQuery(
                    context=ObservationContext(
                        environment_id="test",
                        app_id="orders",
                        instance_id=None,
                        resource=None,
                        scope=ObservationScope.APPLICATION,
                        window=query.context.window,
                    ),
                    metrics=("http_qps", "rt_p95"),
                    step_ms=60_000,
                )
                application_bundle = await reader.read_metrics(application_query)
                assert application_bundle.summary[0].value == 100 / 3
                assert application_bundle.summary[0].coverage.reporting == 2
                assert application_bundle.summary[1].value is None
                assert application_bundle.summary[1].quality.value == "partial"

                resource_query = MetricQuery(
                    context=ObservationContext(
                        environment_id="test",
                        app_id="orders",
                        instance_id="orders-1",
                        resource="POST /orders",
                        scope=ObservationScope.PROCESS,
                        window=query.context.window,
                    ),
                    metrics=("resource_entry_rate", "blocked_ratio"),
                    step_ms=60_000,
                )
                resource_bundle = await reader.read_metrics(resource_query)
                assert resource_bundle.summary[0].value == 8
                assert resource_bundle.summary[1].value == 3 / 8

                partial_minute_query = MetricQuery(
                    context=ObservationContext(
                        environment_id="test",
                        app_id="orders",
                        instance_id="orders-1",
                        resource="POST /orders",
                        scope=ObservationScope.PROCESS,
                        window=ObservationWindow(
                            _START + timedelta(seconds=1),
                            _START + timedelta(minutes=1, seconds=-1),
                        ),
                    ),
                    metrics=("resource_entry_rate",),
                    step_ms=60_000,
                )
                partial_minute_bundle = await reader.read_metrics(partial_minute_query)
                assert partial_minute_bundle.summary[0].value is None
                assert partial_minute_bundle.summary[0].quality.value == "no_samples"

                host_query = MetricQuery(
                    context=ObservationContext(
                        environment_id="test",
                        app_id="orders",
                        instance_id="orders-1",
                        resource=None,
                        scope=ObservationScope.HOST,
                        window=query.context.window,
                    ),
                    metrics=("cpu_ratio",),
                    step_ms=60_000,
                )
                host_bundle = await reader.read_metrics(host_query)
                assert host_bundle.summary[0].value is None
                assert host_bundle.summary[0].quality.value == "not_integrated"
            finally:
                await engine.dispose()

    async def test_reader_preserves_stale_quality_without_inventing_a_value(self):
        with tempfile.TemporaryDirectory(prefix="sentinel-rollup-stale-") as directory:
            engine = create_async_engine(f"sqlite+aiosqlite:///{directory}/db.sqlite3")
            try:
                await upgrade_database(engine)
                sessions = async_sessionmaker(engine, expire_on_commit=False)
                now = datetime.now(UTC)
                stale_binding = MetricsReporterBindingRecord(
                    certificate_principal="spiffe://sentinel.test/reporter/stale",
                    certificate_sha256="c" * 64,
                    reporter_id="reporter-stale",
                    environment_id="test",
                    app_id="orders",
                    instance_id="orders-1",
                    process_id="orders-1-worker-0",
                    last_sequence=3,
                    last_received_at=now - timedelta(seconds=30),
                )
                async with sessions.begin() as session:
                    session.add(stale_binding)

                async def resolve_engine():
                    return engine

                minute = now.replace(second=0, microsecond=0)
                query = MetricQuery(
                    context=ObservationContext(
                        environment_id="test",
                        app_id="orders",
                        instance_id="orders-1",
                        resource=None,
                        scope=ObservationScope.PROCESS,
                        window=ObservationWindow(
                            minute,
                            minute + timedelta(minutes=1),
                        ),
                    ),
                    metrics=("http_qps",),
                    step_ms=60_000,
                )
                bundle = await SQLAlchemyMetricsHistoryReader(
                    resolve_engine
                ).read_metrics(query)

                assert bundle.summary[0].value is None
                assert bundle.summary[0].quality.value == "stale"
                assert bundle.series[0].samples[0].value is None
            finally:
                await engine.dispose()


def _snapshot(
    *,
    sequence: int,
    elapsed_ns: int,
    http: int = 0,
    admitted: int = 0,
    blocked: int = 0,
    histogram_count: int = 0,
    histogram_overflow: int = 0,
    include_histogram: bool = False,
    epoch=None,
    gauges: tuple[GaugeReading, ...] = (),
    reporter_id: str = _REPORTER_ID,
) -> MetricsSnapshot:
    finite_counts = [0] * len(HTTP_REQUEST_DURATION_BOUNDARIES_NS)
    if histogram_count > histogram_overflow:
        finite_counts[0] = histogram_count - histogram_overflow
    histogram_counts = (*finite_counts, histogram_overflow)
    histograms = (
        (
            HistogramReading(
                HistogramName.HTTP_REQUEST_DURATION,
                HTTP_REQUEST_DURATION_BOUNDARIES_NS,
                histogram_counts,
                histogram_count,
                (histogram_count - histogram_overflow) * 1_000_000
                + histogram_overflow * 20_000_000_000,
                1_000_000 if histogram_count else None,
                20_000_000_000
                if histogram_overflow
                else 1_000_000
                if histogram_count
                else None,
            ),
        )
        if include_histogram
        else ()
    )
    return MetricsSnapshot(
        reporter_id=reporter_id,
        startup_epoch=epoch or _EPOCH,
        sequence=sequence,
        captured_at=_START + timedelta(seconds=sequence),
        capture_elapsed_ns=elapsed_ns,
        counters=(
            CounterReading(CounterName.HTTP_REQUESTS_COMPLETED, http),
            CounterReading(
                CounterName.SENTINEL_ENTRIES_ADMITTED, admitted, "POST /orders"
            ),
            CounterReading(
                CounterName.SENTINEL_ENTRIES_BLOCKED, blocked, "POST /orders"
            ),
        ),
        histograms=histograms,
        gauges=gauges,
    )


def _find(contributions, metric):
    return next(item for item in contributions if item.metric == metric)


async def _accept_rollup_snapshot(history, binding, snapshot, received_at):
    body = _encode_snapshot(snapshot)
    return await history.accept_snapshot(
        binding=binding,
        snapshot=snapshot,
        body=body,
        body_sha256=hashlib.sha256(body).hexdigest(),
        received_at=received_at,
    )


def _encode_snapshot(snapshot):
    from atlas_richie.contracts.reporting.v2 import encode_metrics_snapshot

    return encode_metrics_snapshot(snapshot)
