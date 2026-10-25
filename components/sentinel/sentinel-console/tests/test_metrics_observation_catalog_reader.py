"""Real SQL acceptance for the Metrics V2-backed observation catalog."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atlas_richie.sentinel_console.infrastructure.persistence import (
    metrics_observation_catalog_reader as observation_catalog_reader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    MetricsReporterBindingRecord,
    MetricsReporterEpochRecord,
    MetricsSnapshotRecord,
    MonitoringSourceRecord,
)


class MetricsObservationCatalogReaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="sentinel-observation-catalog-", dir="/private/tmp"
        )
        database_url = (
            f"sqlite+aiosqlite:///{Path(self.temporary_directory.name) / 'console.db'}"
        )
        self.engine = create_async_engine(database_url)
        await upgrade_database(self.engine)
        self.as_of = datetime.now(UTC)

        async def resolve_engine():
            return self.engine

        self.reader = (
            observation_catalog_reader.SQLAlchemyMetricsObservationCatalogReader(
                resolve_engine, clock=lambda: self.as_of
            )
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temporary_directory.cleanup()

    async def test_returns_only_active_scopes_with_a_durable_snapshot(self) -> None:
        await self._enroll("worker-1", "prod", "orders", observed=True)
        await self._enroll("worker-2", "prod", "orders", observed=True)
        await self._enroll("worker-3", "stage", "orders", observed=True)
        await self._enroll("worker-unseen", "dev", "catalog", observed=False)
        await self._enroll(
            "worker-revoked", "retired", "old-app", observed=True, revoked=True
        )

        snapshot = await self.reader.read_observation_catalog()

        assert snapshot.as_of == self.as_of
        assert [(item.id, item.name) for item in snapshot.environments] == [
            ("prod", "prod"),
            ("stage", "stage"),
        ]
        assert [
            (item.environment_id, item.id, item.name)
            for item in snapshot.applications
        ] == [("prod", "orders", "orders"), ("stage", "orders", "orders")]

    async def test_empty_authoritative_database_returns_an_empty_catalog(self) -> None:
        snapshot = await self.reader.read_observation_catalog()

        assert snapshot.environments == ()
        assert snapshot.applications == ()

    async def test_monitoring_only_environment_is_available_without_app_reporters(self) -> None:
        await self._register_monitoring_source("host-only", "infra-prod")

        snapshot = await self.reader.read_observation_catalog()

        assert [(item.id, item.name) for item in snapshot.environments] == [
            ("infra-prod", "infra-prod")
        ]
        assert snapshot.applications == ()

    async def test_monitoring_environment_merges_with_reporter_environment(self) -> None:
        await self._enroll("worker-1", "prod", "orders", observed=True)
        await self._register_monitoring_source("host-prod", "prod")
        await self._register_monitoring_source("host-stage", "stage")

        snapshot = await self.reader.read_observation_catalog()

        assert [item.id for item in snapshot.environments] == [
            "prod",
            "stage",
        ]
        assert [(item.environment_id, item.id) for item in snapshot.applications] == [
            ("prod", "orders")
        ]

    async def test_catalog_clock_must_be_timezone_aware(self) -> None:
        async def resolve_engine():
            return self.engine

        reader = (
            observation_catalog_reader.SQLAlchemyMetricsObservationCatalogReader(
                resolve_engine, clock=lambda: datetime(2026, 10, 15)
            )
        )

        with self.assertRaises(ValueError):
            await reader.read_observation_catalog()

    async def _enroll(
        self,
        instance_id: str,
        environment_id: str,
        app_id: str,
        *,
        observed: bool,
        revoked: bool = False,
    ) -> None:
        principal = f"spiffe://sentinel.test/reporter/{instance_id}"
        session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with session_factory.begin() as session:
            session.add(
                MetricsReporterBindingRecord(
                    certificate_principal=principal,
                    certificate_sha256=hashlib.sha256(instance_id.encode()).hexdigest(),
                    reporter_id=f"reporter-{instance_id}",
                    environment_id=environment_id,
                    app_id=app_id,
                    instance_id=instance_id,
                    process_id=f"process-{instance_id}",
                    revoked_at=self.as_of if revoked else None,
                    current_epoch="a3f1a4b2-7b86-4f2a-90d9-000000000001"
                    if observed
                    else None,
                    last_sequence=1 if observed else 0,
                    last_elapsed_ns="1000000000" if observed else None,
                    last_received_at=self.as_of if observed else None,
                )
            )
            if not observed:
                return
            session.add(
                MetricsReporterEpochRecord(
                    certificate_principal=principal,
                    startup_epoch="a3f1a4b2-7b86-4f2a-90d9-000000000001",
                    first_sequence=1,
                    first_elapsed_ns="1000000000",
                    last_sequence=1,
                    last_elapsed_ns="1000000000",
                )
            )
            body = b"accepted-metrics-v2-snapshot"
            session.add(
                MetricsSnapshotRecord(
                    certificate_principal=principal,
                    startup_epoch="a3f1a4b2-7b86-4f2a-90d9-000000000001",
                    sequence=1,
                    body_sha256=hashlib.sha256(body).hexdigest(),
                    body=body,
                    received_at=self.as_of,
                )
            )

    async def _register_monitoring_source(
        self, source_id: str, environment_id: str
    ) -> None:
        session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with session_factory.begin() as session:
            session.add(
                MonitoringSourceRecord(
                    source_id=source_id,
                    revision="revision-1",
                    display_name=source_id,
                    environment_id=environment_id,
                    endpoint="http://127.0.0.1:9090",
                    provider="prometheus-compatible",
                    profile="node-exporter-v1",
                    authentication_mode="none",
                    credential_configured=False,
                    credential_cipher_format=None,
                    credential_key_id=None,
                    credential_payload=None,
                    enabled=True,
                    identity_labels=["host"],
                    selector_labels=[{"name": "job", "value": "node"}],
                    scrape_interval_seconds=15,
                    stale_after_seconds=90,
                    created_at=self.as_of,
                    updated_at=self.as_of,
                )
            )
