"""SQLite persistence and query contract for Incident Event V1."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from atlas_richie.contracts.incidents.v1 import (
    IncidentEventV1,
    ResourcePressureFact,
    ResourcePressureMetric,
    encode_incident_event,
)
from atlas_richie.contracts.incidents.v1 import (
    IncidentSeverity as WireIncidentSeverity,
)
from atlas_richie.sentinel_console.application.incident_ingest_ports import (
    IncidentIngestError,
    IncidentIngestErrorCode,
)
from atlas_richie.sentinel_console.application.ingest_incident_event import (
    IngestIncidentEvent,
)
from atlas_richie.sentinel_console.application.incident_evidence_ports import (
    IncidentEvidenceNotFound,
)
from atlas_richie.sentinel_console.application.metrics_ingest_ports import (
    VerifiedMetricsPeer,
)
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
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_PRINCIPAL = "spiffe://sentinel.test/reporter/orders-worker-0"
_CERTIFICATE = "a" * 64
_REPORTER_ID = "reporter-orders-worker-0"
_EPOCH = uuid4()
_BINDING = {
    "certificate_principal": _PRINCIPAL,
    "certificate_sha256": _CERTIFICATE,
    "reporter_id": _REPORTER_ID,
    "environment_id": "test",
    "app_id": "orders",
    "instance_id": "orders-worker-0",
    "process_id": "orders-pid-1",
    "current_epoch": str(_EPOCH),
    "last_sequence": 0,
}
_RECEIVED = datetime(2026, 10, 15, 4, 0, tzinfo=UTC)


class IncidentEventStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sentinel-incident-store-")
        self.addCleanup(temporary.cleanup)
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{temporary.name}/incidents.sqlite3"
        )
        self.addAsyncCleanup(self.engine.dispose)
        await upgrade_database(self.engine)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions.begin() as session:
            session.add(MetricsReporterBindingRecord(**_BINDING))
        self.store = SQLAlchemyIncidentEventAdapter(
            self._engine, clock=lambda: _RECEIVED + timedelta(seconds=1)
        )
        self.ingest = IngestIncidentEvent(
            self.store, self.store, clock=lambda: _RECEIVED
        )
        self.peer = VerifiedMetricsPeer(_CERTIFICATE)

    async def _engine(self):
        return self.engine

    async def test_commit_ack_exact_retry_and_conflicting_retry(self):
        event = _event(1)
        body = encode_incident_event(event)
        receipt = await self.ingest.execute(self.peer, body)
        replay = await self.ingest.execute(self.peer, body)

        assert replay == receipt
        assert receipt.body_sha256 == hashlib.sha256(body).hexdigest()
        assert receipt.received_at == _RECEIVED
        async with self.sessions() as session:
            rows = (await session.scalars(select(IncidentEventRecord))).all()
        assert len(rows) == 1
        assert rows[0].body == body
        assert rows[0].expires_at.replace(tzinfo=UTC) == _RECEIVED + timedelta(days=30)

        with pytest.raises(IncidentIngestError) as conflict:
            await self.ingest.execute(self.peer, body + b" ")
        assert conflict.value.code is IncidentIngestErrorCode.IDEMPOTENCY_CONFLICT

    async def test_old_epoch_and_revoked_reporter_are_rejected(self):
        old_epoch_body = encode_incident_event(_event(2, epoch=uuid4()))
        with pytest.raises(IncidentIngestError) as old_epoch:
            await self.ingest.execute(self.peer, old_epoch_body)
        assert old_epoch.value.code is IncidentIngestErrorCode.IDENTITY_MISMATCH

        async with self.sessions.begin() as session:
            await session.execute(
                update(MetricsReporterBindingRecord)
                .where(MetricsReporterBindingRecord.certificate_principal == _PRINCIPAL)
                .values(revoked_at=_RECEIVED)
            )
        with pytest.raises(IncidentIngestError) as revoked:
            await self.ingest.execute(self.peer, encode_incident_event(_event(3)))
        assert revoked.value.code is IncidentIngestErrorCode.IDENTITY_NOT_ENROLLED

    async def test_timeline_paginates_in_stable_order_and_applies_filters(self):
        events = (_event(11, minute=1), _event(12, minute=2), _event(13, minute=3))
        for event in events:
            await self.ingest.execute(self.peer, encode_incident_event(event))

        first_query = _query(page_size=2)
        first = await self.store.read_incident_timeline(first_query)
        assert first.statistics.total == 3
        assert first.statistics.critical == 3
        assert first.filtered_total == 3
        assert len(first.items) == 2
        assert first.next_cursor is not None

        second = await self.store.read_incident_timeline(
            _query(page_size=2, cursor=first.next_cursor)
        )
        assert len(second.items) == 1
        assert second.next_cursor is None
        assert first.items[0].occurred_at > first.items[1].occurred_at
        assert first.items[-1].occurred_at > second.items[0].occurred_at
        assert len({item.id for item in first.items + second.items}) == 3

        filtered = await self.store.read_incident_timeline(
            _query(severity=IncidentSeverity.WARNING)
        )
        assert filtered.items == ()
        assert filtered.filtered_total == 0
        assert filtered.statistics.total == 3

    async def test_expired_events_are_not_visible_or_returned_in_statistics(self):
        await self.ingest.execute(self.peer, encode_incident_event(_event(21)))
        as_of = _RECEIVED + timedelta(days=31)
        store = SQLAlchemyIncidentEventAdapter(self._engine, clock=lambda: as_of)

        page = await store.read_incident_timeline(_query())

        assert page.items == ()
        assert page.statistics.total == 0
        assert await store.expire_incident_history(as_of) == 1
        assert await store.expire_incident_history(as_of) == 0
        async with self.sessions() as session:
            rows = (await session.scalars(select(IncidentEventRecord))).all()
        assert rows == []

    async def test_evidence_read_returns_only_exact_persisted_event_fact(self):
        await self.ingest.execute(self.peer, encode_incident_event(_event(31)))
        page = await self.store.read_incident_timeline(_query())
        event = page.items[0]
        query = IncidentDetailQuery(
            context=_query().context,
            event_id=event.id,
            severity=event.severity,
            category=event.category,
        )

        evidence = await self.store.read_incident_evidence(query)

        assert evidence.query == query
        assert evidence.event == event
        assert evidence.completeness is IncidentEvidenceCompleteness.PARTIAL
        assert len(evidence.facts) == 1
        assert evidence.facts[0].fact == event.caption
        assert evidence.facts[0].source == "runtime-event"
        assert evidence.related_rule is None
        assert evidence.suggested_views

    async def test_evidence_read_hides_events_outside_active_filters(self):
        await self.ingest.execute(self.peer, encode_incident_event(_event(32)))
        event = (await self.store.read_incident_timeline(_query())).items[0]
        query = IncidentDetailQuery(
            context=_query().context,
            event_id=event.id,
            severity=event.severity,
            category=event.category,
        )
        context = query.context
        shifted_window = ObservationWindow(
            context.window.starts_at + timedelta(days=1),
            context.window.ends_at + timedelta(days=1),
        )
        mismatched_queries = (
            replace(query, context=replace(context, environment_id="other")),
            replace(query, context=replace(context, app_id="billing")),
            replace(query, context=replace(context, instance_id="worker-1")),
            replace(query, context=replace(context, window=shifted_window)),
            replace(query, severity=IncidentSeverity.WARNING),
            replace(query, category=IncidentCategory.RESPONSE_TIME),
            replace(query, event_id="missing-event"),
        )

        for mismatched_query in mismatched_queries:
            with self.subTest(query=mismatched_query):
                with pytest.raises(IncidentEvidenceNotFound):
                    await self.store.read_incident_evidence(mismatched_query)


def _event(
    number: int,
    *,
    epoch: UUID = _EPOCH,
    minute: int = 0,
) -> IncidentEventV1:
    return IncidentEventV1(
        event_id=UUID(int=number),
        process_epoch=epoch,
        occurred_at=datetime(2026, 10, 15, 3, minute, tzinfo=UTC),
        severity=WireIncidentSeverity.CRITICAL,
        fact=ResourcePressureFact(
            metric=ResourcePressureMetric.CPU_RATIO,
            value=0.95,
            threshold=0.9,
        ),
    )


def _query(
    *,
    page_size: int = 100,
    cursor: str | None = None,
    severity: IncidentSeverity | None = None,
) -> IncidentQuery:
    return IncidentQuery(
        context=ObservationContext(
            environment_id="test",
            app_id="orders",
            instance_id="orders-worker-0",
            resource=None,
            scope=ObservationScope.PROCESS,
            window=ObservationWindow(
                datetime(2026, 10, 15, 0, 0, tzinfo=UTC),
                datetime(2026, 10, 16, 0, 0, tzinfo=UTC),
            ),
        ),
        severity=severity,
        category=(
            IncidentCategory.RESOURCE
            if severity is not IncidentSeverity.WARNING
            else None
        ),
        cursor=cursor,
        page_size=page_size,
    )
