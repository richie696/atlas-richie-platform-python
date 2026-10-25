"""Durable Rule Load Observation V1 acceptance for disposable SQL dialects."""

from __future__ import annotations

import hashlib
import os
import unittest
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from atlas_richie.contracts.rules.load_observation.v1 import (
    RuleKind,
    RuleLoadEventKind,
    RuleLoadMemberFingerprint,
    RuleLoadObservationV1,
    RuleLoadSnapshotV1,
    encode_rule_load_observation,
)
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atlas_richie.sentinel_console.application.ingest_rule_load_observation import (
    IngestRuleLoadObservation,
)
from atlas_richie.sentinel_console.application.metrics_ingest_ports import (
    VerifiedMetricsPeer,
)
from atlas_richie.sentinel_console.application.run_rule_load_observation_projection_worker import (
    RunRuleLoadObservationProjectionWorker,
)
from atlas_richie.sentinel_console.domain.rule_bindings import (
    RuleKind as BindingRuleKind,
)
from atlas_richie.sentinel_console.domain.rule_catalog import (
    RuleBindingObservedState,
    RuleBindingStatesQuery,
)
from atlas_richie.sentinel_console.domain.rule_load_observation_query import (
    RuleLoadFreshness,
    RuleLoadObservationQuery,
    RuleLoadObservedState,
)
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    MetricsReporterBindingRecord,
    RegisteredConfigurationSourceRecord,
    RuleBindingRecord,
    RuleCatalogSnapshotRecord,
    RuleLoadObservationCurrentRecord,
    RuleLoadObservationInboxRecord,
    RuleLoadObservationOutboxRecord,
    RulePublicationTargetRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_binding_state_reader import (
    SqlAlchemyRuleBindingStateReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_load_observation_inbox import (
    SQLAlchemyRuleLoadObservationInbox,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_load_observation_projection_queue import (
    SqlAlchemyRuleLoadObservationProjectionQueue,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_load_observation_reader import (
    SqlAlchemyRuleLoadObservationReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_target_mapping import (
    target_body,
)

_DATABASE_URLS = (
    ("SENTINEL_CONSOLE_TEST_POSTGRES_URL", "POSTGRES", "postgresql+psycopg"),
    ("SENTINEL_CONSOLE_TEST_MYSQL_URL", "MYSQL", "mysql+asyncmy"),
)


def _disposable_database_url() -> str:
    configured = [
        (name, provider, scheme, os.environ[name])
        for name, provider, scheme in _DATABASE_URLS
        if os.environ.get(name)
    ]
    if len(configured) != 1:
        raise unittest.SkipTest(
            "run through exactly one disposable PostgreSQL or MySQL wrapper"
        )
    name, provider, scheme, value = configured[0]
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
            f"refusing {name} URL not issued by a disposable loopback wrapper"
        )
    return value


class RuleLoadObservationDialectAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database_url = _disposable_database_url()
        self.engine = create_async_engine(self.database_url, pool_size=4)
        self.addAsyncCleanup(self._dispose_engine)
        await upgrade_database(self.engine)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.now = datetime(2026, 10, 16, 4, 0, tzinfo=UTC)
        self.principal = f"spiffe://sentinel.test/rules/{uuid4()}"
        self.certificate = hashlib.sha256(self.principal.encode()).hexdigest()
        self.process_epoch = str(uuid4())
        self.binding_id = f"binding-{uuid4()}"
        self.app_id = f"dialect-{uuid4()}"
        self.source_id = f"source-{uuid4()}"
        self.observation = RuleLoadObservationV1(
            observation_id=str(uuid4()),
            process_epoch=self.process_epoch,
            sequence=1,
            binding_id=self.binding_id,
            profile_id="sentinel-python-v1",
            event_kind=RuleLoadEventKind.SNAPSHOT_APPLIED,
            active_snapshot=RuleLoadSnapshotV1(
                source_revision="provider-revision-1",
                source_bytes_sha256=hashlib.sha256(b"provider bytes").hexdigest(),
                canonical_rules_sha256=hashlib.sha256(b"canonical rules").hexdigest(),
                membership_complete=True,
                members=(
                    RuleLoadMemberFingerprint(
                        RuleKind.FLOW,
                        hashlib.sha256(b"one flow rule").hexdigest(),
                    ),
                ),
            ),
            attempt=None,
            observed_at=self.now,
        )
        publication_target = NacosRulePublicationTarget(
            self.binding_id,
            self.source_id,
            "public",
            "DEFAULT_GROUP",
            "flow-rules.json",
        )
        async with self.sessions.begin() as session:
            account_id = str(uuid4())
            username = f"admin-{uuid4()}"
            session.add(
                AccountRecord(
                    account_id=account_id,
                    username=username,
                    username_key=username.casefold(),
                    password_hash="test-only-not-a-password-hash",
                    role_id="admin",
                    created_at=self.now,
                    updated_at=self.now,
                )
            )
            session.add(
                RegisteredConfigurationSourceRecord(
                    source_id=self.source_id,
                    revision="source-rev-1",
                    name="acceptance-source",
                    endpoint="https://provider.example.test",
                    provider="nacos",
                    location="public/config",
                    authentication_mode="none",
                    credential_configured=False,
                    created_at=self.now,
                    updated_at=self.now,
                    updated_by_account_id=account_id,
                )
            )
            session.add(
                RuleBindingRecord(
                    binding_id=self.binding_id,
                    environment_id="acceptance",
                    app_id=self.app_id,
                    kind="flow",
                    profile="sentinel-python-v1",
                    source_id=self.source_id,
                    location="nacos://public/DEFAULT_GROUP/flow-rules.json",
                    created_at=self.now,
                    updated_at=self.now,
                )
            )
            session.add(
                RulePublicationTargetRecord(
                    binding_id=self.binding_id,
                    source_id=self.source_id,
                    target_revision="target-rev-1",
                    source_revision="source-rev-1",
                    target_body=target_body(publication_target),
                    updated_at=self.now,
                )
            )
            session.add(
                MetricsReporterBindingRecord(
                    certificate_principal=self.principal,
                    certificate_sha256=self.certificate,
                    reporter_id=f"reporter-{uuid4()}",
                    environment_id="acceptance",
                    app_id=self.app_id,
                    instance_id="worker-0",
                    process_id="process-1",
                    revoked_at=None,
                    current_epoch=self.process_epoch,
                    last_sequence=0,
                )
            )

        self.inbox = SQLAlchemyRuleLoadObservationInbox(self._resolve_engine)
        self.ingest = IngestRuleLoadObservation(self.inbox, clock=lambda: self.now)
        self.peer = VerifiedMetricsPeer(self.certificate)

    async def _resolve_engine(self):
        return self.engine

    async def _dispose_engine(self) -> None:
        await self.engine.dispose()

    async def test_durable_ack_idempotency_and_projection_survive_reopen(self) -> None:
        binding_query = RuleBindingStatesQuery(
            "acceptance", self.app_id, BindingRuleKind.FLOW, 1, 20
        )
        binding_reader = SqlAlchemyRuleBindingStateReader(
            self.engine, clock=lambda: self.now
        )
        unread = await binding_reader.read_binding_states(binding_query)
        self.assertEqual(unread.total, 1)
        self.assertEqual(unread.items[0].state, RuleBindingObservedState.NOT_READ)
        self.assertIsNone(unread.items[0].rule_count)

        async with self.engine.begin() as connection:
            await connection.execute(
                insert(RuleCatalogSnapshotRecord).values(
                    binding_id=self.binding_id,
                    environment_id="acceptance",
                    app_id=self.app_id,
                    kind="flow",
                    read_state="current",
                    error_code=None,
                    last_attempt_at=self.now,
                    snapshot_as_of=self.now,
                    checksum="sha256:confirmed-empty",
                    source_revision="provider-revision-1",
                    version_id=None,
                    rule_count=0,
                )
            )
        empty = await binding_reader.read_binding_states(binding_query)
        self.assertEqual(
            empty.items[0].state, RuleBindingObservedState.CONFIGURED_EMPTY
        )
        self.assertEqual(empty.items[0].rule_count, 0)

        async with self.engine.begin() as connection:
            await connection.execute(
                update(RuleCatalogSnapshotRecord)
                .where(RuleCatalogSnapshotRecord.binding_id == self.binding_id)
                .values(
                    read_state="stale",
                    error_code="target_missing",
                    last_attempt_at=self.now + timedelta(seconds=1),
                )
            )
        missing_target = await binding_reader.read_binding_states(binding_query)
        self.assertEqual(
            missing_target.items[0].state, RuleBindingObservedState.TARGET_MISSING
        )
        self.assertTrue(missing_target.items[0].has_last_known_good)
        self.assertEqual(missing_target.items[0].freshness.value, "stale")

        body = encode_rule_load_observation(self.observation)
        accepted = await self.ingest.execute(self.peer, body)
        replay = await self.ingest.execute(self.peer, body)
        self.assertEqual(accepted, replay)

        async with self.sessions() as session:
            inbox_rows = await session.scalar(
                select(func.count()).select_from(RuleLoadObservationInboxRecord)
            )
            outbox_rows = await session.scalar(
                select(func.count()).select_from(RuleLoadObservationOutboxRecord)
            )
        self.assertEqual(inbox_rows, 1)
        self.assertEqual(outbox_rows, 1)

        await self.engine.dispose()
        self.engine = create_async_engine(self.database_url, pool_size=4)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        reopened_inbox = SQLAlchemyRuleLoadObservationInbox(self._resolve_engine)
        reopened_ingest = IngestRuleLoadObservation(
            reopened_inbox, clock=lambda: self.now + timedelta(seconds=1)
        )
        self.assertEqual(await reopened_ingest.execute(self.peer, body), accepted)
        worker = RunRuleLoadObservationProjectionWorker(
            SqlAlchemyRuleLoadObservationProjectionQueue(self.engine)
        )
        result = await worker.run_once(now=self.now + timedelta(seconds=2))
        repeated = await worker.run_once(now=self.now + timedelta(seconds=3))

        async with self.sessions() as session:
            current_rows = await session.scalars(
                select(RuleLoadObservationCurrentRecord)
            )
            current = list(current_rows)
            outbox = await session.get(
                RuleLoadObservationOutboxRecord, self.observation.observation_id
            )
        self.assertEqual((result.claimed, result.delivered, result.parked), (1, 1, 0))
        self.assertEqual(repeated.claimed, 0)
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].observation_id, self.observation.observation_id)
        self.assertEqual(
            current[0].active_snapshot["source_revision"], "provider-revision-1"
        )
        self.assertEqual(outbox.state, "delivered")

        query = RuleLoadObservationQuery(
            "acceptance", self.app_id, self.binding_id, None, 1, 20
        )
        current_reader = SqlAlchemyRuleLoadObservationReader(
            self.engine, clock=lambda: self.now + timedelta(seconds=90)
        )
        current_page = await current_reader.read_rule_load_observations(query)
        self.assertEqual(current_page.targets.expected, 1)
        self.assertEqual(current_page.targets.observed, 1)
        self.assertEqual(current_page.targets.stale, 0)
        self.assertEqual(
            current_page.items[0].load_state, RuleLoadObservedState.APPLIED
        )
        self.assertEqual(current_page.items[0].freshness, RuleLoadFreshness.CURRENT)
        self.assertEqual(len(current_page.items[0].active_snapshot.members), 1)

        stale_reader = SqlAlchemyRuleLoadObservationReader(
            self.engine, clock=lambda: self.now + timedelta(seconds=90, microseconds=1)
        )
        stale_page = await stale_reader.read_rule_load_observations(query)
        self.assertEqual(stale_page.targets.stale, 1)
        self.assertEqual(stale_page.items[0].freshness, RuleLoadFreshness.STALE)


if __name__ == "__main__":
    unittest.main()
