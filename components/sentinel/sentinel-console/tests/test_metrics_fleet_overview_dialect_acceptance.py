"""Fleet overview SQL read-model acceptance on disposable PostgreSQL/MySQL."""

from __future__ import annotations

import hashlib
import os
import unittest
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote
from uuid import uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atlas_richie.sentinel_console.domain.fleet_overview import FleetQuery
from atlas_richie.sentinel_console.domain.instance_catalog import (
    MetricQuality,
    ObservationScope,
    ObservationWindow,
)
from atlas_richie.sentinel_console.domain.instance_observation import (
    ObservationContext,
)
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


def _disposable_database_url() -> str:
    choices = (
        ("SENTINEL_CONSOLE_TEST_POSTGRES_URL", "POSTGRES", "postgresql+psycopg"),
        ("SENTINEL_CONSOLE_TEST_MYSQL_URL", "MYSQL", "mysql+asyncmy"),
    )
    configured = [
        (key, provider, scheme, os.environ[key])
        for key, provider, scheme in choices
        if os.environ.get(key)
    ]
    if len(configured) != 1:
        raise unittest.SkipTest(
            "run with exactly one disposable SQL acceptance wrapper"
        )

    key, provider, scheme, value = configured[0]
    parsed = make_url(value)
    database = unquote(parsed.database or "")
    port = str(parsed.port or "")
    if (
        parsed.drivername != scheme
        or parsed.host != "127.0.0.1"
        or parsed.port is None
        or parsed.username != "sentinel_e2e"
        or not database.startswith("sentinel_console_test_")
        or os.environ.get(f"SENTINEL_E2E_{provider}_HOST") != "127.0.0.1"
        or os.environ.get(f"SENTINEL_E2E_{provider}_PORT") != port
        or os.environ.get(f"SENTINEL_E2E_{provider}_DATABASE") != database
        or os.environ.get(f"SENTINEL_E2E_{provider}_USER") != parsed.username
        or not os.environ.get(f"SENTINEL_E2E_{provider}_PASSWORD")
    ):
        raise unittest.SkipTest(
            f"refusing {key} not issued by a disposable SQL wrapper"
        )
    return value


class MetricsFleetOverviewDialectAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(_disposable_database_url(), pool_size=2)
        self.addAsyncCleanup(self.engine.dispose)
        await upgrade_database(self.engine)
        self.as_of = datetime.now(UTC)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.environment_id = f"fleet-dialect-{uuid4()}"
        self.app_id = f"app-{uuid4()}"
        self.instance_id = f"worker-{uuid4()}"
        self.reporter_id = f"reporter-{uuid4()}"
        self.process_id = f"process-{uuid4()}"
        self.epoch = str(uuid4())
        self.certificate_principal = f"spiffe://sentinel.test/{self.reporter_id}"
        async with self.sessions.begin() as session:
            session.add(
                MetricsReporterBindingRecord(
                    certificate_principal=self.certificate_principal,
                    certificate_sha256=hashlib.sha256(
                        self.certificate_principal.encode()
                    ).hexdigest(),
                    reporter_id=self.reporter_id,
                    environment_id=self.environment_id,
                    app_id=self.app_id,
                    instance_id=self.instance_id,
                    process_id=self.process_id,
                    current_epoch=self.epoch,
                    last_sequence=1,
                    last_elapsed_ns="1000000000",
                    last_received_at=self.as_of,
                )
            )

        async def resolve_engine():
            return self.engine

        self.reader = SQLAlchemyMetricsFleetOverviewReader(
            resolve_engine,
            SQLAlchemyMetricsHistoryReader(resolve_engine),
            clock=lambda: self.as_of,
        )

    async def test_observed_reporter_scope_round_trips_through_fleet_reader(
        self,
    ) -> None:
        query = FleetQuery(
            context=ObservationContext(
                environment_id=self.environment_id,
                app_id=None,
                instance_id=None,
                resource=None,
                scope=ObservationScope.FLEET,
                window=ObservationWindow(self.as_of - timedelta(hours=1), self.as_of),
            ),
            page=1,
            page_size=20,
            search="",
            step_ms=60_000,
        )

        snapshot = await self.reader.read_fleet_overview(query)

        self.assertEqual(snapshot.query, query)
        self.assertEqual(snapshot.total_applications, 1)
        self.assertEqual(snapshot.applications.total, 1)
        self.assertEqual(
            [item.app_id for item in snapshot.applications.items], [self.app_id]
        )
        self.assertEqual(snapshot.coverage.reporting, 1)
        self.assertIsNone(snapshot.coverage.expected)
        self.assertEqual(snapshot.connections, ())
        self.assertTrue(
            all(
                metric.quality is MetricQuality.NO_SAMPLES
                for metric in snapshot.applications.items[0].metrics
            )
        )

        absent_scope = FleetQuery(
            context=ObservationContext(
                environment_id=f"absent-{uuid4()}",
                app_id=None,
                instance_id=None,
                resource=None,
                scope=ObservationScope.FLEET,
                window=query.context.window,
            ),
            page=1,
            page_size=20,
            search="",
            step_ms=60_000,
        )
        empty = await self.reader.read_fleet_overview(absent_scope)
        self.assertEqual(empty.total_applications, 0)
        self.assertEqual(empty.applications.items, ())
        self.assertEqual(empty.coverage.reporting, 0)


if __name__ == "__main__":
    unittest.main()
