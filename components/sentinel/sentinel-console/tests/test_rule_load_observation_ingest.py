"""SQLite contract tests for the Rule Load Observation Collector boundary."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from atlas_richie.contracts.rules.load_observation.v1 import (
    RuleKind,
    RuleLoadEventKind,
    RuleLoadMemberFingerprint,
    RuleLoadObservationV1,
    RuleLoadSnapshotV1,
    encode_rule_load_observation,
)
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.applications import Starlette
from openapi_contract_support import assert_openapi_response

from atlas_richie.sentinel_console.api.rule_load_observation_ingest import (
    rule_load_observation_ingest_route,
)
from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.ingest_rule_load_observation import (
    IngestRuleLoadObservation,
)
from atlas_richie.sentinel_console.application.read_rule_load_observations import (
    ReadRuleLoadObservations,
)
from atlas_richie.sentinel_console.application.read_rule_load_observation_history import (
    ReadRuleLoadObservationHistory,
)
from atlas_richie.sentinel_console.application.run_rule_load_observation_projection_worker import (
    RunRuleLoadObservationProjectionWorker,
)
from atlas_richie.sentinel_console.domain.rule_load_observation_query import (
    RuleLoadFreshness,
    RuleLoadObservationQuery,
    RuleLoadObservedState,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    MetricsReporterBindingRecord,
    RegisteredConfigurationSourceRecord,
    RuleBindingRecord,
    RuleLoadObservationCurrentRecord,
    RuleLoadObservationInboxRecord,
    RuleLoadObservationOutboxRecord,
    RuleLoadObservationSequenceRecord,
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
from atlas_richie.sentinel_console.infrastructure.persistence.rule_load_observation_history_reader import (
    SqlAlchemyRuleLoadObservationHistoryReader,
)
from atlas_richie.sentinel_console.domain.rule_load_observation_history import (
    RuleLoadObservationHistoryQuery,
)


class _TlsScope:
    def __init__(self, app: Starlette, certificate_chain: tuple[str, ...]) -> None:
        self._app = app
        self._certificate_chain = certificate_chain

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope)
            scope["scheme"] = "https"
            scope["extensions"] = {
                "tls": {"client_cert_chain": self._certificate_chain}
            }
        await self._app(scope, receive, send)


def _tls_certificate() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "reporter.test")])
    now = datetime.now(UTC).replace(tzinfo=None)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM).decode("ascii"),
        cert.fingerprint(hashes.SHA256()).hex(),
    )


_NOW = datetime(2026, 10, 16, 4, 0, tzinfo=UTC)
_EPOCH = "72000000-0000-4000-8000-000000000001"
_BINDING = "binding-orders-flow"


def _observation(
    *,
    sequence: int = 1,
    observation_id: str | None = None,
    binding_id: str = _BINDING,
    process_epoch: str = _EPOCH,
    active_snapshot: RuleLoadSnapshotV1 | None = None,
):
    return RuleLoadObservationV1(
        observation_id=observation_id or str(uuid4()),
        process_epoch=process_epoch,
        sequence=sequence,
        binding_id=binding_id,
        profile_id="sentinel-python-v1",
        event_kind=RuleLoadEventKind.SNAPSHOT_APPLIED,
        active_snapshot=active_snapshot
        or RuleLoadSnapshotV1(
            source_revision="provider-rev-1",
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
        observed_at=_NOW,
    )


class RuleLoadObservationIngestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sentinel-rule-load-")
        self.addCleanup(temporary.cleanup)
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{temporary.name}/observations.sqlite3"
        )
        self.addAsyncCleanup(self.engine.dispose)
        await upgrade_database(self.engine)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.pem, self.fingerprint = _tls_certificate()
        async with self.sessions.begin() as session:
            session.add(
                AccountRecord(
                    account_id="account-admin",
                    username="admin",
                    username_key="admin",
                    password_hash="not-a-real-password-hash",
                    role_id="admin",
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            session.add(
                RegisteredConfigurationSourceRecord(
                    source_id="source-primary",
                    revision="source-rev-1",
                    name="primary",
                    endpoint="https://nacos.example.test",
                    provider="nacos",
                    location="public/config",
                    authentication_mode="none",
                    credential_configured=False,
                    created_at=_NOW,
                    updated_at=_NOW,
                    updated_by_account_id="account-admin",
                )
            )
            session.add(
                RuleBindingRecord(
                    binding_id=_BINDING,
                    environment_id="test",
                    app_id="orders",
                    kind="flow",
                    profile="sentinel-python-v1",
                    source_id="source-primary",
                    location="flow-rules.json",
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            session.add(
                MetricsReporterBindingRecord(
                    certificate_principal="spiffe://sentinel.test/orders/worker-0",
                    certificate_sha256=self.fingerprint,
                    reporter_id="reporter-orders-worker-0",
                    environment_id="test",
                    app_id="orders",
                    instance_id="orders-worker-0",
                    process_id="pid-1",
                    revoked_at=None,
                    current_epoch=_EPOCH,
                    last_sequence=0,
                    last_elapsed_ns=None,
                    last_received_at=None,
                )
            )
            session.add(
                MetricsReporterBindingRecord(
                    certificate_principal="spiffe://sentinel.test/orders/worker-1",
                    certificate_sha256=hashlib.sha256(b"worker-1").hexdigest(),
                    reporter_id="reporter-orders-worker-1",
                    environment_id="test",
                    app_id="orders",
                    instance_id="orders-worker-1",
                    process_id="pid-2",
                    revoked_at=None,
                    current_epoch="72000000-0000-4000-8000-000000000003",
                    last_sequence=0,
                    last_elapsed_ns=None,
                    last_received_at=None,
                )
            )
            session.add(
                MetricsReporterBindingRecord(
                    certificate_principal="spiffe://sentinel.test/orders/revoked",
                    certificate_sha256=hashlib.sha256(b"revoked").hexdigest(),
                    reporter_id="reporter-orders-revoked",
                    environment_id="test",
                    app_id="orders",
                    instance_id="orders-revoked",
                    process_id="pid-3",
                    revoked_at=_NOW,
                    current_epoch="72000000-0000-4000-8000-000000000004",
                    last_sequence=0,
                    last_elapsed_ns=None,
                    last_received_at=None,
                )
            )
            session.add(
                RuleBindingRecord(
                    binding_id="binding-payments-flow",
                    environment_id="test",
                    app_id="payments",
                    kind="flow",
                    profile="sentinel-python-v1",
                    source_id="source-primary",
                    location="payments-flow-rules.json",
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
        inbox = SQLAlchemyRuleLoadObservationInbox(lambda: _await_engine(self.engine))
        ingest = IngestRuleLoadObservation(inbox, clock=lambda: _NOW)
        app = Starlette(routes=[rule_load_observation_ingest_route(ingest)])
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_TlsScope(app, (self.pem,))),
            base_url="https://collector.test",
        )
        self.addAsyncCleanup(self.client.aclose)

    async def test_durable_ack_and_exact_retry_are_idempotent(self):
        body = encode_rule_load_observation(_observation())
        response = await self.client.post(
            "/api/reporting/v1/rule-load-observations",
            content=body,
            headers={"content-type": "application/json"},
        )
        retry = await self.client.post(
            "/api/reporting/v1/rule-load-observations",
            content=body,
            headers={"content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(retry.status_code, 204)
        async with self.sessions() as session:
            inbox = list(await session.scalars(select(RuleLoadObservationInboxRecord)))
            outbox = list(
                await session.scalars(select(RuleLoadObservationOutboxRecord))
            )
            sequence = await session.get(
                RuleLoadObservationSequenceRecord,
                (
                    "spiffe://sentinel.test/orders/worker-0",
                    _EPOCH,
                    _BINDING,
                ),
            )
        self.assertEqual(len(inbox), 1)
        self.assertEqual(len(outbox), 1)
        self.assertEqual(inbox[0].body, body)
        self.assertEqual(inbox[0].body_sha256, hashlib.sha256(body).hexdigest())
        self.assertEqual(outbox[0].state, "pending")
        self.assertEqual(sequence.last_sequence, 1)

    async def test_same_id_with_changed_bytes_is_rejected(self):
        identity = str(uuid4())
        first = encode_rule_load_observation(
            _observation(sequence=1, observation_id=identity)
        )
        second = encode_rule_load_observation(
            _observation(sequence=1, observation_id=identity)
        )
        self.assertEqual(first, second)
        # Alter only whitespace; the semantic event is equal, but the immutable
        # idempotency key is bound to the exact bytes accepted by Collector.
        response = await self.client.post(
            "/api/reporting/v1/rule-load-observations",
            content=first,
            headers={"content-type": "application/json"},
        )
        retry = await self.client.post(
            "/api/reporting/v1/rule-load-observations",
            content=b" " + first,
            headers={"content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(retry.status_code, 409)

    async def test_epoch_and_binding_scope_are_rejected(self):
        wrong_epoch = await self.client.post(
            "/api/reporting/v1/rule-load-observations",
            content=encode_rule_load_observation(
                _observation(process_epoch="72000000-0000-4000-8000-000000000002")
            ),
            headers={"content-type": "application/json"},
        )
        wrong_scope = await self.client.post(
            "/api/reporting/v1/rule-load-observations",
            content=encode_rule_load_observation(
                _observation(binding_id="binding-payments-flow")
            ),
            headers={"content-type": "application/json"},
        )
        self.assertEqual(wrong_epoch.status_code, 409)
        self.assertEqual(wrong_scope.status_code, 403)

    async def test_sequence_cannot_move_backwards(self):
        later = await self.client.post(
            "/api/reporting/v1/rule-load-observations",
            content=encode_rule_load_observation(_observation(sequence=2)),
            headers={"content-type": "application/json"},
        )
        stale = await self.client.post(
            "/api/reporting/v1/rule-load-observations",
            content=encode_rule_load_observation(_observation(sequence=1)),
            headers={"content-type": "application/json"},
        )
        self.assertEqual(later.status_code, 204)
        self.assertEqual(stale.status_code, 409)

    async def test_same_content_publish_and_rollback_project_latest_sequence_exactly(self):
        baseline = _observation(sequence=1)
        same_content = _observation(
            sequence=2,
            active_snapshot=replace(
                baseline.active_snapshot,
                source_revision="provider-rev-2-same-content",
            ),
        )
        changed_snapshot = replace(
            baseline.active_snapshot,
            source_revision="provider-rev-3-changed-content",
            source_bytes_sha256=hashlib.sha256(b"changed provider bytes").hexdigest(),
            canonical_rules_sha256=hashlib.sha256(b"changed canonical rules").hexdigest(),
            members=(
                RuleLoadMemberFingerprint(
                    RuleKind.FLOW,
                    hashlib.sha256(b"changed flow rule").hexdigest(),
                ),
            ),
        )
        changed = _observation(sequence=3, active_snapshot=changed_snapshot)
        rollback = _observation(
            sequence=4,
            active_snapshot=replace(
                baseline.active_snapshot,
                source_revision="provider-rev-4-rollback",
            ),
        )
        self.assertEqual(
            same_content.active_snapshot.canonical_rules_sha256,
            baseline.active_snapshot.canonical_rules_sha256,
        )
        self.assertEqual(
            same_content.active_snapshot.source_bytes_sha256,
            baseline.active_snapshot.source_bytes_sha256,
        )
        self.assertNotEqual(
            changed.active_snapshot.canonical_rules_sha256,
            baseline.active_snapshot.canonical_rules_sha256,
        )
        self.assertEqual(
            rollback.active_snapshot.canonical_rules_sha256,
            baseline.active_snapshot.canonical_rules_sha256,
        )
        observations = (baseline, same_content, changed, rollback)
        worker = RunRuleLoadObservationProjectionWorker(
            SqlAlchemyRuleLoadObservationProjectionQueue(self.engine)
        )

        for index, observation in enumerate(observations, start=1):
            response = await self.client.post(
                "/api/reporting/v1/rule-load-observations",
                content=encode_rule_load_observation(observation),
                headers={"content-type": "application/json"},
            )
            self.assertEqual(response.status_code, 204)
            result = await worker.run_once(now=_NOW + timedelta(seconds=index))
            self.assertEqual((result.claimed, result.delivered, result.parked), (1, 1, 0))

        query = RuleLoadObservationQuery("test", "orders", _BINDING, None, 1, 20)
        current = await SqlAlchemyRuleLoadObservationReader(
            self.engine, clock=lambda: _NOW + timedelta(seconds=10)
        ).read_rule_load_observations(query)
        async with self.sessions() as session:
            projection = await session.get(
                RuleLoadObservationCurrentRecord,
                ("spiffe://sentinel.test/orders/worker-0", _BINDING),
            )

        self.assertEqual(len(current.items), 2)
        self.assertEqual(projection.sequence, 4)
        self.assertEqual(projection.observation_id, rollback.observation_id)
        worker_zero = next(
            item for item in current.items if item.instance_id == "orders-worker-0"
        )
        worker_one = next(
            item for item in current.items if item.instance_id == "orders-worker-1"
        )
        self.assertEqual(worker_zero.active_snapshot.source_revision, "provider-rev-4-rollback")
        self.assertEqual(
            worker_zero.active_snapshot.canonical_rules_sha256,
            baseline.active_snapshot.canonical_rules_sha256,
        )
        self.assertEqual(
            worker_zero.active_snapshot.members[0].fingerprint_sha256,
            baseline.active_snapshot.members[0].fingerprint_sha256,
        )
        self.assertIsNone(worker_one.active_snapshot)

    async def test_projection_worker_consumes_durable_outbox(self):
        observation = _observation()
        response = await self.client.post(
            "/api/reporting/v1/rule-load-observations",
            content=encode_rule_load_observation(observation),
            headers={"content-type": "application/json"},
        )
        worker = RunRuleLoadObservationProjectionWorker(
            SqlAlchemyRuleLoadObservationProjectionQueue(self.engine)
        )
        result = await worker.run_once(now=_NOW + timedelta(seconds=1))
        repeated = await worker.run_once(now=_NOW + timedelta(seconds=2))
        async with self.sessions() as session:
            current = await session.get(
                RuleLoadObservationCurrentRecord,
                ("spiffe://sentinel.test/orders/worker-0", _BINDING),
            )
            outbox = await session.scalar(select(RuleLoadObservationOutboxRecord))
        self.assertEqual(response.status_code, 204)
        self.assertEqual((result.claimed, result.delivered, result.parked), (1, 1, 0))
        self.assertEqual(repeated.claimed, 0)
        self.assertEqual(outbox.state, "delivered")
        self.assertEqual(current.observation_id, observation.observation_id)

    async def test_current_read_uses_active_enrollment_denominator_and_strict_stale_edge(
        self,
    ):
        response = await self.client.post(
            "/api/reporting/v1/rule-load-observations",
            content=encode_rule_load_observation(_observation()),
            headers={"content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 204)
        worker = RunRuleLoadObservationProjectionWorker(
            SqlAlchemyRuleLoadObservationProjectionQueue(self.engine)
        )
        await worker.run_once(now=_NOW + timedelta(seconds=1))
        query = RuleLoadObservationQuery("test", "orders", _BINDING, None, 1, 20)
        current_reader = SqlAlchemyRuleLoadObservationReader(
            self.engine, clock=lambda: _NOW + timedelta(seconds=90)
        )
        current = await current_reader.read_rule_load_observations(query)
        self.assertEqual(current.targets.expected, 2)
        self.assertEqual(current.targets.observed, 1)
        self.assertEqual(current.targets.not_observed, 1)
        self.assertEqual(current.total, 2)
        self.assertEqual(
            [item.load_state for item in current.items],
            [RuleLoadObservedState.APPLIED, RuleLoadObservedState.NOT_OBSERVED],
        )
        self.assertEqual(current.items[0].freshness, RuleLoadFreshness.CURRENT)

        stale_reader = SqlAlchemyRuleLoadObservationReader(
            self.engine, clock=lambda: _NOW + timedelta(seconds=90, microseconds=1)
        )
        stale = await stale_reader.read_rule_load_observations(query)
        self.assertEqual(stale.targets.stale, 1)
        self.assertEqual(stale.items[0].freshness, RuleLoadFreshness.STALE)

    async def test_current_read_does_not_claim_zero_instances_without_inventory(self):
        query = RuleLoadObservationQuery(
            "test", "payments", "binding-payments-flow", None, 1, 20
        )
        page = await SqlAlchemyRuleLoadObservationReader(
            self.engine, clock=lambda: _NOW
        ).read_rule_load_observations(query)

        self.assertEqual(page.coverage.value, "partial")
        self.assertIsNone(page.total)
        self.assertEqual(page.items, ())
        self.assertEqual(
            (
                page.targets.expected,
                page.targets.observed,
                page.targets.stale,
                page.targets.not_observed,
            ),
            (None, None, None, None),
        )

    async def test_durable_collector_receipt_is_read_back_by_authenticated_console_api(
        self,
    ):
        response = await self.client.post(
            "/api/reporting/v1/rule-load-observations",
            content=encode_rule_load_observation(_observation()),
            headers={"content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 204)

        worker = RunRuleLoadObservationProjectionWorker(
            SqlAlchemyRuleLoadObservationProjectionQueue(self.engine)
        )
        projected = await worker.run_once(now=_NOW + timedelta(seconds=1))
        self.assertEqual(
            (projected.claimed, projected.delivered, projected.parked), (1, 1, 0)
        )

        class SessionReader:
            async def read_active_session(self, _session_digest):
                return ActiveAccountSession(
                    "account-admin", "admin", "admin", "session-1"
                )

        api = build_app(
            bootstrap_initialization_reader=object(),
            setup_window_reader=object(),
            bootstrap_operator_verifier=object(),
            current_session_reader=SessionReader(),
            current_session_revoker=object(),
            account_directory_reader=object(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            rule_load_observation_reader=ReadRuleLoadObservations(
                SqlAlchemyRuleLoadObservationReader(
                    self.engine, clock=lambda: _NOW + timedelta(seconds=2)
                )
            ),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api), base_url="https://console.test"
        ) as console_client:
            console_client.cookies.set(
                "sentinel_session", "authenticated-console-session-0001"
            )
            readback = await console_client.get(
                "/api/v2/rules/load-observations?environmentId=test&appId=orders&bindingId=binding-orders-flow&page=1&pageSize=20",
                headers={"x-request-id": "collector-console-readback-1"},
            )
            no_inventory = await console_client.get(
                "/api/v2/rules/load-observations?environmentId=test&appId=payments&bindingId=binding-payments-flow&page=1&pageSize=20",
                headers={"x-request-id": "collector-console-no-inventory-1"},
            )

        self.assertEqual(readback.status_code, 200, readback.text)
        self.assertEqual(
            readback.headers["x-request-id"], "collector-console-readback-1"
        )
        self.assertEqual(readback.json()["targets"]["expected"], 2)
        self.assertEqual(readback.json()["targets"]["observed"], 1)
        self.assertEqual(readback.json()["items"][0]["loadState"], "applied")
        self.assertEqual(
            readback.json()["items"][0]["activeSnapshot"]["sourceRevision"],
            "provider-rev-1",
        )
        self.assertEqual(no_inventory.status_code, 200, no_inventory.text)
        self.assertEqual(no_inventory.json()["coverage"], "partial")
        self.assertIsNone(no_inventory.json()["total"])
        self.assertEqual(no_inventory.json()["items"], [])
        self.assertEqual(
            no_inventory.json()["targets"],
            {
                "source": "active_reporter_enrollment",
                "expected": None,
                "observed": None,
                "stale": None,
                "notObserved": None,
            },
        )
        self.assertEqual(readback.json()["items"][1]["loadState"], "not_observed")

    async def test_old_process_epoch_is_read_separately_from_current_counts(self):
        receipt = _observation()
        accepted = await self.client.post(
            "/api/reporting/v1/rule-load-observations",
            content=encode_rule_load_observation(receipt),
            headers={"content-type": "application/json"},
        )
        self.assertEqual(accepted.status_code, 204)
        worker = RunRuleLoadObservationProjectionWorker(
            SqlAlchemyRuleLoadObservationProjectionQueue(self.engine)
        )
        await worker.run_once(now=_NOW + timedelta(seconds=1))
        query = RuleLoadObservationHistoryQuery(
            "test", "orders", _BINDING, None, 1, 20
        )
        reader = SqlAlchemyRuleLoadObservationHistoryReader(
            self.engine, clock=lambda: _NOW + timedelta(seconds=2)
        )
        active_history = await reader.read_rule_load_observation_history(query)
        self.assertEqual(active_history.total, 0)

        async with self.sessions.begin() as session:
            reporter = await session.get(
                MetricsReporterBindingRecord,
                "spiffe://sentinel.test/orders/worker-0",
            )
            reporter.current_epoch = "72000000-0000-4000-8000-000000000009"

        history = await reader.read_rule_load_observation_history(query)
        self.assertEqual(history.coverage.value, "complete")
        self.assertEqual(history.total, 1)
        self.assertEqual(history.items[0].epoch_status.value, "superseded")
        self.assertEqual(history.items[0].observation.process_epoch, _EPOCH)

        class SessionReader:
            async def read_active_session(self, _session_digest):
                return ActiveAccountSession(
                    "account-admin", "admin", "admin", "session-1"
                )

        api = build_app(
            bootstrap_initialization_reader=object(),
            setup_window_reader=object(),
            bootstrap_operator_verifier=object(),
            current_session_reader=SessionReader(),
            current_session_revoker=object(),
            account_directory_reader=object(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            rule_load_observation_history_reader=ReadRuleLoadObservationHistory(reader),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api), base_url="https://console.test"
        ) as console_client:
            console_client.cookies.set(
                "sentinel_session", "authenticated-console-session-0001"
            )
            response = await console_client.get(
                "/api/v2/rules/load-observation-history?environmentId=test&appId=orders&bindingId=binding-orders-flow&page=1&pageSize=20",
                headers={"x-request-id": "collector-history-readback-1"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        assert_openapi_response("readRuleLoadObservationHistory", response)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["epochStatus"], "superseded")
        self.assertEqual(body["items"][0]["observation"]["processEpoch"], _EPOCH)
        self.assertNotIn("certificate_principal", response.text)
        self.assertNotIn('"body"', response.text)

        current = await SqlAlchemyRuleLoadObservationReader(
            self.engine, clock=lambda: _NOW + timedelta(seconds=2)
        ).read_rule_load_observations(
            RuleLoadObservationQuery("test", "orders", _BINDING, None, 1, 20)
        )
        self.assertEqual(current.items[0].event_kind, None)

        async with self.sessions.begin() as session:
            reporter = await session.get(
                MetricsReporterBindingRecord,
                "spiffe://sentinel.test/orders/worker-0",
            )
            reporter.revoked_at = _NOW + timedelta(seconds=3)
        revoked = await reader.read_rule_load_observation_history(query)
        self.assertEqual(revoked.items[0].epoch_status.value, "revoked")

        async with self.sessions.begin() as session:
            reporter = await session.get(
                MetricsReporterBindingRecord,
                "spiffe://sentinel.test/orders/worker-0",
            )
            reporter.revoked_at = None
            reporter.current_epoch = None
        no_current_epoch = await reader.read_rule_load_observation_history(query)
        self.assertEqual(no_current_epoch.items[0].epoch_status.value, "no_current_epoch")

    async def test_history_pagination_is_stable_when_received_times_are_equal(self):
        observation_ids = (
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000002",
        )
        for sequence, observation_id in enumerate(observation_ids, start=1):
            response = await self.client.post(
                "/api/reporting/v1/rule-load-observations",
                content=encode_rule_load_observation(
                    _observation(sequence=sequence, observation_id=observation_id)
                ),
                headers={"content-type": "application/json"},
            )
            self.assertEqual(response.status_code, 204)
        worker = RunRuleLoadObservationProjectionWorker(
            SqlAlchemyRuleLoadObservationProjectionQueue(self.engine)
        )
        await worker.run_once(now=_NOW + timedelta(seconds=1))
        async with self.sessions.begin() as session:
            reporter = await session.get(
                MetricsReporterBindingRecord,
                "spiffe://sentinel.test/orders/worker-0",
            )
            reporter.current_epoch = "72000000-0000-4000-8000-000000000009"

        reader = SqlAlchemyRuleLoadObservationHistoryReader(
            self.engine, clock=lambda: _NOW + timedelta(seconds=2)
        )
        first_page = await reader.read_rule_load_observation_history(
            RuleLoadObservationHistoryQuery("test", "orders", _BINDING, None, 1, 1)
        )
        second_page = await reader.read_rule_load_observation_history(
            RuleLoadObservationHistoryQuery("test", "orders", _BINDING, None, 2, 1)
        )
        self.assertEqual(first_page.total, 2)
        self.assertTrue(first_page.has_more)
        self.assertEqual(first_page.items[0].observation_id, observation_ids[1])
        self.assertFalse(second_page.has_more)
        self.assertEqual(second_page.items[0].observation_id, observation_ids[0])


async def _await_engine(engine):
    return engine


if __name__ == "__main__":
    unittest.main()
