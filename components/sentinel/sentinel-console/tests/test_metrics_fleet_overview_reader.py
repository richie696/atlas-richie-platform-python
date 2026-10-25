"""SQLite integration coverage for the production Fleet overview adapter."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atlas_richie.sentinel_console.application.fleet_overview_ports import (
    FleetOverviewTargetNotFound,
)
from atlas_richie.sentinel_console.domain.fleet_overview import FleetQuery
from atlas_richie.sentinel_console.domain.instance_catalog import (
    MetricQuality,
    ObservationScope,
    ObservationWindow,
)
from atlas_richie.sentinel_console.domain.instance_observation import ObservationContext
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_fleet_overview_reader import (
    SQLAlchemyMetricsFleetOverviewReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_history_reader import (
    SQLAlchemyMetricsHistoryReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    MetricsReporterBindingRecord,
)


class SQLAlchemyMetricsFleetOverviewReaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="sentinel-fleet-overview-", dir="/private/tmp"
        )
        database_url = (
            f"sqlite+aiosqlite:///{Path(self.temporary_directory.name) / 'console.db'}"
        )
        self.engine = create_async_engine(database_url)
        await upgrade_database(self.engine)
        self.as_of = datetime.now(UTC)

        async def resolve_engine():
            return self.engine

        metrics_reader = SQLAlchemyMetricsHistoryReader(resolve_engine)
        self.reader = SQLAlchemyMetricsFleetOverviewReader(
            resolve_engine, metrics_reader, clock=lambda: self.as_of
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temporary_directory.cleanup()

    async def test_empty_authority_returns_a_valid_unknown_snapshot(self) -> None:
        snapshot = await self.reader.read_fleet_overview(self._query())

        self.assertEqual(snapshot.total_applications, 0)
        self.assertEqual(snapshot.applications.items, ())
        self.assertEqual(snapshot.applications.total, 0)
        self.assertEqual(snapshot.coverage.expected, None)
        self.assertEqual(snapshot.coverage.reporting, 0)
        self.assertEqual(snapshot.connections, ())
        self.assertEqual(snapshot.metrics.as_of, self.as_of)
        self.assertTrue(
            all(
                item.quality is MetricQuality.NO_SAMPLES
                for item in snapshot.metrics.summary
            )
        )

    async def test_projects_only_observed_non_revoked_reporter_applications(
        self,
    ) -> None:
        await self._enroll("worker-orders", "prod", "orders")
        await self._enroll("worker-revoked", "prod", "retired", revoked=True)
        await self._enroll("worker-unobserved", "prod", "unobserved", observed=False)
        await self._enroll("worker-other-env", "stage", "catalog")

        snapshot = await self.reader.read_fleet_overview(self._query())

        self.assertEqual(snapshot.total_applications, 1)
        self.assertEqual(snapshot.coverage.reporting, 1)
        self.assertEqual(
            [item.app_id for item in snapshot.applications.items], ["orders"]
        )
        application = snapshot.applications.items[0]
        self.assertEqual(application.health.value, "unknown")
        self.assertEqual(application.instance_coverage.reporting, 1)
        self.assertEqual(application.rule_coverage.reporting, 0)
        self.assertTrue(
            all(
                item.quality is MetricQuality.NO_SAMPLES for item in application.metrics
            )
        )

    async def test_missing_application_is_not_returned_as_a_fabricated_row(
        self,
    ) -> None:
        await self._enroll("worker-orders", "prod", "orders")

        with self.assertRaises(FleetOverviewTargetNotFound):
            await self.reader.read_fleet_overview(self._query(app_id="missing"))

    async def test_search_filters_page_without_changing_scope_population_total(
        self,
    ) -> None:
        await self._enroll("worker-orders", "prod", "orders")
        await self._enroll("worker-payments", "prod", "payments")

        snapshot = await self.reader.read_fleet_overview(self._query(search="order"))

        self.assertEqual(snapshot.total_applications, 2)
        self.assertEqual(snapshot.applications.total, 1)
        self.assertEqual(
            [item.app_id for item in snapshot.applications.items], ["orders"]
        )

    async def test_stale_reporter_remains_visible_without_claiming_fresh_coverage(
        self,
    ) -> None:
        await self._enroll(
            "worker-orders",
            "prod",
            "orders",
            last_received_at=self.as_of - timedelta(seconds=10),
        )

        snapshot = await self.reader.read_fleet_overview(self._query())

        self.assertEqual(snapshot.total_applications, 1)
        self.assertEqual(snapshot.coverage.reporting, 0)
        self.assertEqual(snapshot.applications.items[0].instance_coverage.reporting, 0)
        self.assertTrue(
            all(
                item.quality is MetricQuality.STALE
                for item in snapshot.applications.items[0].metrics
            )
        )

    def _query(self, *, app_id: str | None = None, search: str = "") -> FleetQuery:
        return FleetQuery(
            context=ObservationContext(
                environment_id="prod",
                app_id=app_id,
                instance_id=None,
                resource=None,
                scope=(
                    ObservationScope.APPLICATION
                    if app_id is not None
                    else ObservationScope.FLEET
                ),
                window=ObservationWindow(self.as_of - timedelta(hours=1), self.as_of),
            ),
            page=1,
            page_size=20,
            search=search,
            step_ms=60_000,
        )

    async def _enroll(
        self,
        instance_id: str,
        environment_id: str,
        app_id: str,
        *,
        revoked: bool = False,
        observed: bool = True,
        last_received_at: datetime | None = None,
    ) -> None:
        factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with factory.begin() as session:
            session.add(
                MetricsReporterBindingRecord(
                    certificate_principal=f"spiffe://sentinel.test/{instance_id}",
                    certificate_sha256=hashlib.sha256(instance_id.encode()).hexdigest(),
                    reporter_id=f"reporter-{instance_id}",
                    environment_id=environment_id,
                    app_id=app_id,
                    instance_id=instance_id,
                    process_id=f"process-{instance_id}",
                    revoked_at=self.as_of if revoked else None,
                    current_epoch=(
                        "a3f1a4b2-7b86-4f2a-90d9-000000000001" if observed else None
                    ),
                    last_sequence=1 if observed else 0,
                    last_elapsed_ns="1000000000" if observed else None,
                    last_received_at=(
                        last_received_at or self.as_of if observed else None
                    ),
                )
            )


if __name__ == "__main__":
    unittest.main()
