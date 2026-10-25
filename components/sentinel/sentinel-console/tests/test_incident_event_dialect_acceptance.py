"""Durable Incident Event V1 acceptance for disposable PostgreSQL/MySQL."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from atlas_richie.contracts.incidents.v1 import (
    IncidentEventV1,
    ResourcePressureFact,
    ResourcePressureMetric,
    encode_incident_event,
)
from atlas_richie.contracts.incidents.v1 import (
    IncidentSeverity as WireSeverity,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atlas_richie.sentinel_console.application.ingest_incident_event import (
    IngestIncidentEvent,
)
from atlas_richie.sentinel_console.application.metrics_ingest_ports import (
    VerifiedMetricsPeer,
)
from atlas_richie.sentinel_console.cli import main
from atlas_richie.sentinel_console.domain.incidents import (
    IncidentCategory,
    IncidentDetailQuery,
    IncidentEvidenceCompleteness,
    IncidentQuery,
    IncidentSeverity,
)
from atlas_richie.sentinel_console.domain.instance_catalog import (
    ObservationScope,
    ObservationWindow,
)
from atlas_richie.sentinel_console.domain.instance_observation import (
    ObservationContext,
)
from atlas_richie.sentinel_console.infrastructure.persistence.incident_event_adapter import (
    SQLAlchemyIncidentEventAdapter,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    IncidentEventRecord,
    MetricsReporterBindingRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_locator_configuration import (
    RuntimeDatabaseLocatorConfiguration,
)

_RECEIVED_AT = datetime(2026, 10, 15, 4, 0, tzinfo=UTC)


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
            "run using exactly one disposable SQL acceptance wrapper"
        )
    _key, provider, scheme, value = configured[0]
    parsed = urlsplit(value)
    database = unquote(parsed.path.removeprefix("/"))
    if (
        parsed.scheme != scheme
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.username != "sentinel_e2e"
        or not database.startswith("sentinel_console_test_")
        or os.environ.get(f"SENTINEL_E2E_{provider}_HOST") != "127.0.0.1"
        or os.environ.get(f"SENTINEL_E2E_{provider}_PORT") != str(parsed.port)
        or os.environ.get(f"SENTINEL_E2E_{provider}_DATABASE") != database
        or os.environ.get(f"SENTINEL_E2E_{provider}_USER") != parsed.username
    ):
        raise unittest.SkipTest(
            "refusing a database URL not issued by the disposable wrapper"
        )
    return value


class IncidentEventDialectAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database_url = _disposable_database_url()
        self.engine = create_async_engine(self.database_url, pool_size=4)
        self.addAsyncCleanup(self.engine.dispose)
        await upgrade_database(self.engine)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.principal = f"spiffe://sentinel.test/reporter/{uuid4()}"
        self.certificate = hashlib.sha256(self.principal.encode()).hexdigest()
        self.epoch = uuid4()
        self.reporter_id = f"reporter-{uuid4()}"
        self.instance_id = f"worker-{uuid4()}"
        self.process_id = f"process-{uuid4()}"
        async with self.sessions.begin() as session:
            session.add(
                MetricsReporterBindingRecord(
                    certificate_principal=self.principal,
                    certificate_sha256=self.certificate,
                    reporter_id=self.reporter_id,
                    environment_id="acceptance",
                    app_id="incident-dialect",
                    instance_id=self.instance_id,
                    process_id=self.process_id,
                    current_epoch=str(self.epoch),
                    last_sequence=0,
                )
            )
        self.store = SQLAlchemyIncidentEventAdapter(self._resolve_engine)
        self.ingest = IngestIncidentEvent(
            self.store, self.store, clock=lambda: _RECEIVED_AT
        )

    async def _resolve_engine(self):
        return self.engine

    async def test_durable_idempotent_timeline_and_expiration(self) -> None:
        event = IncidentEventV1(
            event_id=uuid4(),
            process_epoch=self.epoch,
            occurred_at=_RECEIVED_AT - timedelta(seconds=2),
            severity=WireSeverity.WARNING,
            fact=ResourcePressureFact(
                metric=ResourcePressureMetric.CPU_RATIO,
                value=0.96,
                threshold=0.9,
            ),
        )
        body = encode_incident_event(event)
        peer = VerifiedMetricsPeer(self.certificate)
        receipts = await asyncio.gather(
            self.ingest.execute(peer, body), self.ingest.execute(peer, body)
        )
        self.assertEqual(receipts[0], receipts[1])

        query = IncidentQuery(
            context=ObservationContext(
                environment_id="acceptance",
                app_id="incident-dialect",
                instance_id=self.instance_id,
                resource=None,
                scope=ObservationScope.PROCESS,
                window=ObservationWindow(
                    _RECEIVED_AT - timedelta(hours=1),
                    _RECEIVED_AT + timedelta(hours=1),
                ),
            ),
            severity=None,
            category=None,
            cursor=None,
            page_size=20,
        )
        page = await self.store.read_incident_timeline(query)
        self.assertEqual(len(page.items), 1)
        self.assertEqual(page.items[0].source_event_id, str(event.event_id))
        detail_query = IncidentDetailQuery(
            context=query.context,
            event_id=page.items[0].id,
            severity=IncidentSeverity.WARNING,
            category=IncidentCategory.RESOURCE,
        )
        evidence = await self.store.read_incident_evidence(detail_query)
        self.assertEqual(evidence.query, detail_query)
        self.assertEqual(evidence.event, page.items[0])
        self.assertEqual(
            evidence.completeness, IncidentEvidenceCompleteness.PARTIAL
        )
        self.assertEqual(len(evidence.facts), 1)
        self.assertEqual(evidence.facts[0].fact, page.items[0].caption)
        self.assertIsNone(evidence.related_rule)
        async with self.sessions() as session:
            count = await session.scalar(
                select(func.count()).select_from(IncidentEventRecord)
            )
        self.assertEqual(count, 1)

        expiry = _RECEIVED_AT + timedelta(days=31)
        self.assertEqual(await self.store.expire_incident_history(expiry), 1)
        self.assertEqual(await self.store.expire_incident_history(expiry), 0)
        self.assertEqual((await self.store.read_incident_timeline(query)).items, ())

    async def test_retention_cli_uses_encrypted_disposable_runtime_locator(
        self,
    ) -> None:
        peer = VerifiedMetricsPeer(self.certificate)
        events = tuple(
            IncidentEventV1(
                event_id=uuid4(),
                process_epoch=self.epoch,
                occurred_at=_RECEIVED_AT - timedelta(seconds=1),
                severity=WireSeverity.WARNING,
                fact=ResourcePressureFact(
                    metric=ResourcePressureMetric.CPU_RATIO,
                    value=0.96,
                    threshold=0.9,
                ),
            )
            for _ in range(2)
        )
        for event in events:
            await self.ingest.execute(peer, encode_incident_event(event))

        maintenance_time = datetime.now(UTC)
        async with self.sessions.begin() as session:
            await session.execute(
                IncidentEventRecord.__table__.update()
                .where(IncidentEventRecord.event_id == str(events[0].event_id))
                .values(expires_at=maintenance_time - timedelta(seconds=1))
            )
            await session.execute(
                IncidentEventRecord.__table__.update()
                .where(IncidentEventRecord.event_id == str(events[1].event_id))
                .values(expires_at=maintenance_time + timedelta(days=1))
            )

        with tempfile.TemporaryDirectory(
            prefix="sentinel-incident-retention-dialect-"
        ) as directory:
            key = bytes(range(32))
            locator = RuntimeDatabaseLocatorConfiguration(
                path=Path(directory).resolve() / "runtime-locator.json",
                active_key_id="test-key",
                keys={"test-key": key},
            )
            await locator.create_store().write(
                self.database_url, expected_revision=None
            )
            environment = {
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH": str(locator.path),
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_ACTIVE_KEY_ID": "test-key",
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_KEY_RING": (
                    "test-key=" + base64.b64encode(key).decode("ascii")
                ),
            }

            def invoke_cli() -> tuple[int, str]:
                output = StringIO()
                with (
                    patch.dict(os.environ, environment, clear=True),
                    redirect_stdout(output),
                ):
                    status = main(["incident-events", "expire"])
                return status, output.getvalue().strip()

            status, output = await asyncio.to_thread(invoke_cli)
            self.assertEqual(status, 0)
            self.assertEqual(output, "expired-incidents=1")

            async with self.sessions() as session:
                remaining = list(
                    (
                        await session.scalars(
                            select(IncidentEventRecord).order_by(
                                IncidentEventRecord.event_id
                            )
                        )
                    ).all()
                )
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0].event_id, str(events[1].event_id))

            second_status, second_output = await asyncio.to_thread(invoke_cli)
            self.assertEqual(second_status, 0)
            self.assertEqual(second_output, "expired-incidents=0")
