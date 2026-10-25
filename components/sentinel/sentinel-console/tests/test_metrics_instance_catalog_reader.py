"""Real SQL acceptance for the Metrics V2-backed worker instance directory."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

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
    encode_metrics_snapshot,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.applications import Starlette

from atlas_richie.sentinel_console.application.instance_catalog_ports import (
    InstanceIncarnationRetired,
)
from atlas_richie.sentinel_console.application.read_instance_observation import (
    ReadInstanceObservation,
)
from atlas_richie.sentinel_console.api.instance_observation import (
    instance_observation_route,
)
from atlas_richie.sentinel_console.domain.instance_catalog import (
    InstanceCatalogQuery,
    InstanceHealth,
    InstanceLayer,
    MetricQuality,
    ObservationScope,
    ObservationWindow,
    RuleReceiptState,
)
from atlas_richie.sentinel_console.domain.instance_observation import (
    InstanceDetailQuery,
)
from atlas_richie.sentinel_console.domain.session import (
    ActiveAccountSession,
    SessionIdentity,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_history_reader import (
    SQLAlchemyMetricsHistoryReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_instance_catalog_reader import (
    SQLAlchemyMetricsInstanceCatalogReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_instance_observation_reader import (
    SQLAlchemyMetricsInstanceObservationReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    MetricsReporterBindingRecord,
    MetricsReporterEpochRecord,
    MetricsSnapshotRecord,
)


class MetricsInstanceCatalogReaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="sentinel-instance-catalog-", dir="/private/tmp"
        )
        database_url = (
            f"sqlite+aiosqlite:///{Path(self.temporary_directory.name) / 'console.db'}"
        )
        self.engine = create_async_engine(database_url)
        await upgrade_database(self.engine)
        self.as_of = datetime.now(UTC)

        async def resolve_engine():
            return self.engine

        self.reader = SQLAlchemyMetricsInstanceCatalogReader(
            resolve_engine, clock=lambda: self.as_of
        )
        self.metrics_reader = SQLAlchemyMetricsHistoryReader(resolve_engine)
        self.observation_reader = SQLAlchemyMetricsInstanceObservationReader(
            catalog_reader=self.reader,
            metrics_reader=self.metrics_reader,
        )

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temporary_directory.cleanup()

    async def test_projects_worker_metrics_and_excludes_unobserved_or_revoked(self):
        await self._enroll("worker-1", snapshots=2)
        await self._enroll("worker-stale", snapshots=1, age_seconds=4)
        await self._enroll("worker-never-seen", snapshots=0)
        await self._enroll("worker-revoked", snapshots=2, revoked=True)

        snapshot = await self.reader.read_instance_catalog(self._query())

        assert snapshot.total_instances == 2
        assert snapshot.attention_instances == 1
        assert snapshot.coverage.reporting == 1
        assert [item.instance_id for item in snapshot.items] == [
            "worker-1",
            "worker-stale",
        ]
        current = snapshot.items[0]
        assert current.health is InstanceHealth.HEALTHY
        assert current.supported_scopes == (InstanceLayer.PROCESS,)
        assert current.host_id is None
        assert current.container_id is None
        assert current.rule_receipt.state is RuleReceiptState.UNKNOWN
        values = {reading.metric: reading for reading in current.process_metrics}
        assert values["http_qps"].value == 10.0
        assert values["tps"].value == 2.0
        assert values["blocked_ratio"].value == 0.1
        assert values["rt_p95"].value == 1.0
        assert values["cpu_ratio"].value == 0.25
        assert values["memory_ratio"].value == 0.4

        stale = snapshot.items[1]
        assert stale.health is InstanceHealth.ATTENTION
        assert all(
            reading.quality is MetricQuality.STALE and reading.value is None
            for reading in stale.process_metrics
        )

    async def test_attention_filter_and_page_search_use_worker_identity(self):
        await self._enroll("worker-a", snapshots=1, age_seconds=5)
        await self._enroll("worker-b", snapshots=1)
        query = self._query(attention_only=True, search="worker-a")

        snapshot = await self.reader.read_instance_catalog(query)

        assert snapshot.total_instances == 2
        assert snapshot.attention_instances == 1
        assert snapshot.filtered_total == 1
        assert [item.instance_id for item in snapshot.items] == ["worker-a"]

    async def test_uses_latest_snapshots_inside_query_when_newer_report_arrived(self):
        await self._enroll("worker-window", snapshots=4)
        query = self._query(window_ends_at=self.as_of - timedelta(milliseconds=1500))

        snapshot = await self.reader.read_instance_catalog(query)

        values = {item.metric: item for item in snapshot.items[0].process_metrics}
        assert values["http_qps"].quality is MetricQuality.AVAILABLE
        assert values["http_qps"].value == 10.0
        assert values["tps"].quality is MetricQuality.AVAILABLE
        assert values["tps"].value == 2.0
        assert values["rt_p95"].quality is MetricQuality.AVAILABLE
        assert values["rt_p95"].value == 1.0
        assert values["http_qps"].sampled_at == self.as_of - timedelta(seconds=2)

    async def test_worker_directory_paginates_after_stable_identity_sort(self):
        for instance_id in ("worker-c", "worker-a", "worker-b"):
            await self._enroll(instance_id, snapshots=1)

        snapshot = await self.reader.read_instance_catalog(
            self._query(page=2, page_size=1)
        )

        assert snapshot.total_instances == 3
        assert snapshot.filtered_total == 3
        assert [item.instance_id for item in snapshot.items] == ["worker-b"]

    async def test_reporter_instance_identity_is_enforced_by_database(self):
        await self._enroll("worker-duplicate", snapshots=0)
        sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        with self.assertRaises(IntegrityError):
            async with sessions.begin() as session:
                session.add(
                    MetricsReporterBindingRecord(
                        certificate_principal="spiffe://sentinel.test/reporter/duplicate",
                        certificate_sha256=hashlib.sha256(b"duplicate").hexdigest(),
                        reporter_id="reporter-duplicate",
                        environment_id="prod",
                        app_id="orders",
                        instance_id="worker-duplicate",
                        process_id="process-duplicate",
                        last_sequence=0,
                    )
                )

    async def test_reads_only_the_requested_current_process_incarnation(self):
        await self._enroll("worker-detail", snapshots=2)
        query = self._detail_query("worker-detail")

        observation = await self.observation_reader.read_instance_observation(query)

        assert observation.query == query
        assert observation.instance.instance_id == "worker-detail"
        assert observation.instance.process_epoch == str(
            UUID("a3f1a4b2-7b86-4f2a-90d9-000000000001")
        )
        assert observation.metrics is not None
        assert observation.metrics.query.context == query.context
        assert {item.metric for item in observation.metrics.summary} == {
            "http_qps",
            "tps",
            "rt_p95",
            "blocked_ratio",
            "cpu_ratio",
            "memory_ratio",
        }

    async def test_does_not_borrow_process_metrics_for_unsupported_host_scope(self):
        await self._enroll("worker-host-detail", snapshots=2)
        query = self._detail_query("worker-host-detail", scope=InstanceLayer.HOST)

        observation = await self.observation_reader.read_instance_observation(query)

        assert observation.instance.supported_scopes == (InstanceLayer.PROCESS,)
        assert observation.metrics is None

    async def test_rejects_a_retired_process_epoch(self):
        await self._enroll("worker-retired-detail", snapshots=2)
        query = self._detail_query(
            "worker-retired-detail", process_epoch="retired-epoch"
        )

        with self.assertRaises(InstanceIncarnationRetired):
            await self.observation_reader.read_instance_observation(query)

    async def test_rejects_process_restart_during_metrics_read(self):
        await self._enroll("worker-restarted-detail", snapshots=2)

        class RestartDuringRead:
            def __init__(self, catalog_reader):
                self.catalog_reader = catalog_reader
                self.read_count = 0

            async def read_instance_catalog(self, query):
                snapshot = await self.catalog_reader.read_instance_catalog(query)
                self.read_count += 1
                if self.read_count == 2:
                    restarted_receipt = replace(
                        snapshot.items[0].rule_receipt,
                        process_epoch="replacement-epoch",
                    )
                    restarted_instance = replace(
                        snapshot.items[0],
                        process_epoch="replacement-epoch",
                        rule_receipt=restarted_receipt,
                    )
                    return replace(snapshot, items=(restarted_instance,))
                return snapshot

        reader = SQLAlchemyMetricsInstanceObservationReader(
            catalog_reader=RestartDuringRead(self.reader),
            metrics_reader=self.metrics_reader,
        )

        with self.assertRaises(InstanceIncarnationRetired):
            await reader.read_instance_observation(
                self._detail_query("worker-restarted-detail")
            )

    async def test_authenticated_detail_route_uses_sql_reader_and_returns_200(self):
        await self._enroll("worker-http-detail", snapshots=2)
        query = self._detail_query("worker-http-detail")

        class ReadSession:
            async def execute(self, opaque_token):
                if opaque_token != "synthetic-session-token-for-instance-detail":
                    return None
                return SessionIdentity.from_active_session(
                    ActiveAccountSession("account-1", "operator", "view", "epoch-1")
                )

        app = Starlette(
            routes=[
                instance_observation_route(
                    ReadSession(), ReadInstanceObservation(self.observation_reader)
                )
            ]
        )
        params = {
            "environmentId": query.environment_id,
            "appId": query.app_id,
            "scope": query.scope.value,
            "from": query.window.starts_at.isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
            "to": query.window.ends_at.isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
            "processEpoch": query.process_epoch,
            "stepMs": str(query.step_ms),
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            client.cookies.set(
                "sentinel_session", "synthetic-session-token-for-instance-detail"
            )
            response = await client.get(
                "/api/v1/instances/worker-http-detail",
                headers={"x-request-id": "instance-detail-sql-reader"},
                params=params,
            )

        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["instance"]["instanceId"] == "worker-http-detail"
        assert response.json()["metrics"]["query"]["context"]["appId"] == "orders"

    def _detail_query(
        self,
        instance_id: str,
        *,
        scope: InstanceLayer = InstanceLayer.PROCESS,
        process_epoch: str = "a3f1a4b2-7b86-4f2a-90d9-000000000001",
    ) -> InstanceDetailQuery:
        return InstanceDetailQuery(
            environment_id="prod",
            app_id="orders",
            instance_id=instance_id,
            resource=None,
            scope=scope,
            window=ObservationWindow(
                self.as_of - timedelta(minutes=5),
                self.as_of + timedelta(seconds=1),
            ),
            process_epoch=process_epoch,
            step_ms=60_000,
        )

    async def _enroll(
        self,
        instance_id: str,
        *,
        snapshots: int,
        age_seconds: int = 0,
        revoked: bool = False,
    ) -> None:
        principal = f"spiffe://sentinel.test/reporter/{instance_id}"
        reporter_id = f"reporter-{instance_id}"
        epoch = UUID("a3f1a4b2-7b86-4f2a-90d9-000000000001")
        last_received = self.as_of - timedelta(seconds=age_seconds)
        binding = MetricsReporterBindingRecord(
            certificate_principal=principal,
            certificate_sha256=hashlib.sha256(instance_id.encode()).hexdigest(),
            reporter_id=reporter_id,
            environment_id="prod",
            app_id="orders",
            instance_id=instance_id,
            process_id=f"process-{instance_id}",
            revoked_at=self.as_of if revoked else None,
            current_epoch=str(epoch) if snapshots else None,
            last_sequence=snapshots,
            last_elapsed_ns=str(snapshots * 1_000_000_000) if snapshots else None,
            last_received_at=last_received if snapshots else None,
        )
        sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with sessions.begin() as session:
            session.add(binding)
            if snapshots:
                session.add(
                    MetricsReporterEpochRecord(
                        certificate_principal=principal,
                        startup_epoch=str(epoch),
                        first_sequence=1,
                        first_elapsed_ns="1000000000",
                        last_sequence=snapshots,
                        last_elapsed_ns=str(snapshots * 1_000_000_000),
                    )
                )
                for sequence in range(1, snapshots + 1):
                    instant = last_received - timedelta(seconds=snapshots - sequence)
                    snapshot = _metrics_snapshot(
                        reporter_id,
                        epoch,
                        sequence,
                        instant,
                    )
                    body = encode_metrics_snapshot(snapshot)
                    session.add(
                        MetricsSnapshotRecord(
                            certificate_principal=principal,
                            startup_epoch=str(epoch),
                            sequence=sequence,
                            body_sha256=hashlib.sha256(body).hexdigest(),
                            body=body,
                            received_at=instant,
                        )
                    )

    def _query(
        self,
        *,
        attention_only: bool = False,
        search: str = "",
        page: int = 1,
        page_size: int = 20,
        window_ends_at: datetime | None = None,
    ) -> InstanceCatalogQuery:
        return InstanceCatalogQuery(
            environment_id="prod",
            app_id=None,
            instance_id=None,
            resource=None,
            scope=ObservationScope.FLEET,
            window=ObservationWindow(
                self.as_of - timedelta(minutes=5),
                window_ends_at or self.as_of + timedelta(seconds=1),
            ),
            page=page,
            page_size=page_size,
            search=search,
            attention_only=attention_only,
        )


def _metrics_snapshot(
    reporter_id: str,
    epoch: UUID,
    sequence: int,
    captured_at: datetime,
) -> MetricsSnapshot:
    baseline = sequence == 1
    return MetricsSnapshot(
        reporter_id=reporter_id,
        startup_epoch=epoch,
        sequence=sequence,
        captured_at=captured_at,
        capture_elapsed_ns=sequence * 1_000_000_000,
        counters=(
            CounterReading(CounterName.HTTP_REQUESTS_COMPLETED, sequence * 10),
            CounterReading(CounterName.BUSINESS_TRANSACTIONS_COMPLETED, sequence * 2),
            CounterReading(CounterName.SENTINEL_ENTRIES_ADMITTED, sequence * 90),
            CounterReading(CounterName.SENTINEL_ENTRIES_BLOCKED, sequence * 10),
        ),
        histograms=(
            HistogramReading(
                name=HistogramName.HTTP_REQUEST_DURATION,
                boundaries_ns=HTTP_REQUEST_DURATION_BOUNDARIES_NS,
                bucket_counts=(
                    (0,) * (len(HTTP_REQUEST_DURATION_BOUNDARIES_NS) + 1)
                    if baseline
                    else (100,) + (0,) * len(HTTP_REQUEST_DURATION_BOUNDARIES_NS)
                ),
                sample_count=0 if baseline else 100,
                total_ns=0 if baseline else 100_000_000,
                min_ns=None if baseline else 1_000_000,
                max_ns=None if baseline else 1_000_000,
            ),
        ),
        gauges=(
            GaugeReading(GaugeName.PROCESS_CPU_RATIO, 0.25, GaugeQuality.AVAILABLE),
            GaugeReading(GaugeName.PROCESS_RSS_BYTES, 1024, GaugeQuality.AVAILABLE),
            GaugeReading(GaugeName.PROCESS_MEMORY_RATIO, 0.4, GaugeQuality.AVAILABLE),
            GaugeReading(GaugeName.EVENT_LOOP_LAG_NS, None, GaugeQuality.UNAVAILABLE),
        ),
    )
