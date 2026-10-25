"""SQLite contract for durable per-worker Runtime protocol negotiations."""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atlas_richie.sentinel_console.application.metrics_ingest_ports import (
    VerifiedMetricsPeer,
)
from atlas_richie.sentinel_console.application.negotiate_agent_reporting import (
    NegotiateAgentReporting,
)
from atlas_richie.sentinel_console.application.negotiate_incident_events import (
    NegotiateIncidentEvents,
)
from atlas_richie.sentinel_console.application.negotiate_rule_load_observation import (
    NegotiateRuleLoadObservation,
)
from atlas_richie.sentinel_console.domain.protocol_negotiations import (
    INCIDENT_EVENTS_V1,
    RULE_LOAD_OBSERVATION_V1,
    NegotiatedCompatibility,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    MetricsReporterBindingRecord,
    RuleLoadObservationNegotiationRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.protocol_negotiation_store import (
    SQLAlchemyProtocolNegotiationStore,
)

_NOW = datetime(2026, 10, 15, 4, 0, tzinfo=UTC)


class _EngineProvider:
    def __init__(self, engine) -> None:
        self.engine = engine

    async def require_engine(self):
        return self.engine


class ProtocolNegotiationStoreTest(unittest.IsolatedAsyncioTestCase):
    async def test_worker_versions_unknown_and_revocation_are_lossless(self):
        with tempfile.TemporaryDirectory(
            prefix="sentinel-protocol-facts-"
        ) as directory:
            engine = create_async_engine(
                f"sqlite+aiosqlite:///{directory}/console.sqlite3"
            )
            try:
                await upgrade_database(engine)
                provider = _EngineProvider(engine)
                store = SQLAlchemyProtocolNegotiationStore(provider.require_engine)
                fingerprints = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
                async with async_sessionmaker(engine).begin() as session:
                    for index, fingerprint in enumerate(fingerprints):
                        session.add(
                            MetricsReporterBindingRecord(
                                certificate_principal=f"spiffe://worker/{index}",
                                certificate_sha256=fingerprint,
                                reporter_id=f"reporter-{index}",
                                environment_id="prod",
                                app_id="orders",
                                instance_id=f"orders-worker-{index}",
                                process_id=f"pid-{index}",
                                last_sequence=0,
                                revoked_at=_NOW if index == 3 else None,
                            )
                        )

                negotiate = NegotiateAgentReporting(store, clock=lambda: _NOW)
                incident_negotiate = NegotiateIncidentEvents(store, clock=lambda: _NOW)
                rule_load_negotiate = NegotiateRuleLoadObservation(
                    store, clock=lambda: _NOW
                )
                incident_unobserved = await store.read_incident_event_negotiations(
                    page=1, page_size=10, as_of=_NOW
                )
                assert incident_unobserved.total == 3
                assert all(
                    item.compatibility is NegotiatedCompatibility.UNKNOWN
                    and item.runtime_version is None
                    and item.observed_at is None
                    and item.collector_supported == (INCIDENT_EVENTS_V1,)
                    for item in incident_unobserved.items
                )

                compatible = await negotiate.execute(
                    VerifiedMetricsPeer(fingerprints[0]),
                    "atlas-richie.reporting/v1",
                )
                incompatible = await negotiate.execute(
                    VerifiedMetricsPeer(fingerprints[1]),
                    "atlas-richie.reporting/v2",
                )
                assert compatible.compatibility is NegotiatedCompatibility.COMPATIBLE
                assert (
                    incompatible.compatibility is NegotiatedCompatibility.INCOMPATIBLE
                )

                first = await store.read_agent_reporting_negotiations(
                    page=1, page_size=1, as_of=_NOW + timedelta(seconds=1)
                )
                second = await store.read_agent_reporting_negotiations(
                    page=2, page_size=1, as_of=_NOW + timedelta(seconds=1)
                )
                third = await store.read_agent_reporting_negotiations(
                    page=3, page_size=1, as_of=_NOW + timedelta(seconds=1)
                )

                assert first.total == second.total == third.total == 3
                assert first.items[0].runtime_version == "atlas-richie.reporting/v1"
                assert (
                    first.items[0].compatibility is NegotiatedCompatibility.COMPATIBLE
                )
                assert second.items[0].runtime_version == "atlas-richie.reporting/v2"
                assert (
                    second.items[0].compatibility
                    is NegotiatedCompatibility.INCOMPATIBLE
                )
                assert third.items[0].runtime_version is None
                assert third.items[0].compatibility is NegotiatedCompatibility.UNKNOWN
                assert third.items[0].collector_supported == (
                    "atlas-richie.reporting/v1",
                )

                await negotiate.execute(
                    VerifiedMetricsPeer(fingerprints[0]),
                    "atlas-richie.reporting/v2",
                )
                updated = await store.read_agent_reporting_negotiations(
                    page=1, page_size=1, as_of=_NOW + timedelta(seconds=2)
                )
                assert updated.items[0].runtime_version == "atlas-richie.reporting/v2"
                assert (
                    updated.items[0].compatibility
                    is NegotiatedCompatibility.INCOMPATIBLE
                )

                incident = await incident_negotiate.execute(
                    VerifiedMetricsPeer(fingerprints[0]), INCIDENT_EVENTS_V1
                )
                incident_page = await store.read_incident_event_negotiations(
                    page=1, page_size=10, as_of=_NOW + timedelta(seconds=2)
                )
                reporting_after_incident = (
                    await store.read_agent_reporting_negotiations(
                        page=1, page_size=10, as_of=_NOW + timedelta(seconds=2)
                    )
                )
                assert incident.compatibility is NegotiatedCompatibility.COMPATIBLE
                assert incident_page.items[0].runtime_version == INCIDENT_EVENTS_V1
                assert (
                    incident_page.items[0].compatibility
                    is NegotiatedCompatibility.COMPATIBLE
                )
                assert (
                    reporting_after_incident.items[0].runtime_version
                    == "atlas-richie.reporting/v2"
                )

                rule_load = await rule_load_negotiate.execute(
                    VerifiedMetricsPeer(fingerprints[2]), RULE_LOAD_OBSERVATION_V1
                )
                async with async_sessionmaker(engine)() as session:
                    rule_load_fact = await session.get(
                        RuleLoadObservationNegotiationRecord,
                        "spiffe://worker/2",
                    )
                assert rule_load.runtime_version == RULE_LOAD_OBSERVATION_V1
                assert rule_load.compatibility is NegotiatedCompatibility.COMPATIBLE
                assert rule_load_fact is not None
                assert rule_load_fact.compatibility == "compatible"

                async with async_sessionmaker(engine).begin() as session:
                    await session.execute(
                        update(MetricsReporterBindingRecord)
                        .where(
                            MetricsReporterBindingRecord.certificate_sha256
                            == fingerprints[0]
                        )
                        .values(revoked_at=_NOW)
                    )
                revoked = await store.read_agent_reporting_negotiations(
                    page=1, page_size=10, as_of=_NOW + timedelta(seconds=3)
                )
                assert revoked.total == 2
                assert all(
                    item.instance_id != "orders-worker-0" for item in revoked.items
                )
                incident_revoked = await store.read_incident_event_negotiations(
                    page=1, page_size=10, as_of=_NOW + timedelta(seconds=3)
                )
                assert incident_revoked.total == 2
                assert all(
                    item.instance_id != "orders-worker-0"
                    for item in incident_revoked.items
                )
            finally:
                await engine.dispose()
