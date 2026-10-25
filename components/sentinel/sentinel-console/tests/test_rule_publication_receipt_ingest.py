"""SQLite acceptance for authenticated receipt inbox/outbox ingestion."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from atlas_richie.contracts.rules.publication_receipt import (
    PublicationReceiptState,
    RulePublicationReceiptV1,
    encode_rule_publication_receipt,
)
from atlas_richie.sentinel_console.api.rule_publication_receipt_ingest import (
    rule_publication_receipt_ingest_route,
)
from atlas_richie.sentinel_console.application.ingest_rule_publication_receipt import (
    IngestRulePublicationReceipt,
)
from atlas_richie.sentinel_console.application.metrics_ingest_ports import (
    VerifiedMetricsPeer,
)
from atlas_richie.sentinel_console.application.publication_receipt_ingest_ports import (
    PublicationReceiptIngestError,
)
from atlas_richie.sentinel_console.application.publication_receipt_ingest_ports import (
    PublicationReceiptIngestErrorCode as ErrorCode,
)
from atlas_richie.sentinel_console.application.run_rule_publication_receipt_projection_worker import (
    RunRulePublicationReceiptProjectionWorker,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    MetricsReporterBindingRecord,
    RegisteredConfigurationSourceRecord,
    RuleBindingRecord,
    RulePublicationReceiptInboxRecord,
    RulePublicationReceiptOutboxRecord,
    RulePublicationReceiptRecord,
    RulePublicationReceiptSequenceRecord,
    RulePublicationRecord,
    RuleSetVersionRecord,
    RuleValidationReceiptRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_receipt_inbox import (
    SQLAlchemyRulePublicationReceiptInbox,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_receipt_projection_queue import (
    SqlAlchemyRulePublicationReceiptProjectionQueue,
)
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from rule_publication_receipt_outbox_database_acceptance import (
    assert_rule_publication_receipt_outbox_round_trip,
)
from sqlalchemy import event, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.applications import Starlette


class _TlsScope:
    def __init__(self, app, certificate_chain: tuple[str, ...]) -> None:
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
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "reporter.test")])
    now = datetime.now(UTC).replace(tzinfo=None)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(private_key, hashes.SHA256())
    )
    return (
        certificate.public_bytes(serialization.Encoding.PEM).decode("ascii"),
        certificate.fingerprint(hashes.SHA256()).hex(),
    )


_PRINCIPAL = "spiffe://sentinel.test/reporter/orders-worker-0"
_CERTIFICATE = "a" * 64
_ENVIRONMENT = "test"
_APP = "orders"
_INSTANCE = "orders-worker-0"
_PROCESS = "orders-pid-1"
_EPOCH = "72000000-0000-4000-8000-000000000001"
_INSTANT = datetime(2026, 10, 15, 4, 0, tzinfo=UTC)
_PAYLOAD_SHA256 = hashlib.sha256(b"[]").hexdigest()


def _receipt(
    *,
    sequence: int = 1,
    receipt_id: str | None = None,
    binding_id: str = "binding-orders-flow",
    target_version_id: str = "version-orders-1",
    digest: str = _PAYLOAD_SHA256,
) -> RulePublicationReceiptV1:
    return RulePublicationReceiptV1(
        receipt_id=receipt_id or str(uuid4()),
        process_epoch=_EPOCH,
        sequence=sequence,
        binding_id=binding_id,
        publication_id="publication-orders-1",
        target_version_id=target_version_id,
        target_payload_sha256=digest,
        state=PublicationReceiptState.APPLIED,
        reason=None,
        source_revision="source-rev-1",
        observed_at=_INSTANT,
    )


class RulePublicationReceiptIngestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sentinel-receipt-ingest-")
        self.addCleanup(temporary.cleanup)
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{temporary.name}/receipts.sqlite3"
        )
        self.addAsyncCleanup(self.engine.dispose)
        await upgrade_database(self.engine)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions.begin() as session:
            session.add(
                AccountRecord(
                    account_id="account-admin",
                    username="admin",
                    username_key="admin",
                    password_hash="not-a-real-password-hash",
                    role_id="admin",
                    created_at=_INSTANT,
                    updated_at=_INSTANT,
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
                    created_at=_INSTANT,
                    updated_at=_INSTANT,
                    updated_by_account_id="account-admin",
                )
            )
            session.add(
                RuleBindingRecord(
                    binding_id="binding-orders-flow",
                    environment_id=_ENVIRONMENT,
                    app_id=_APP,
                    kind="flow",
                    profile="atlas-richie-sentinel-managed-v1",
                    source_id="source-primary",
                    location="rules/orders",
                    created_at=_INSTANT,
                    updated_at=_INSTANT,
                )
            )
            session.add(
                RuleValidationReceiptRecord(
                    validation_id="validation-orders-1",
                    binding_id="binding-orders-flow",
                    profile="atlas-richie-sentinel-managed-v1",
                    base_checksum="base-checksum",
                    candidate_checksum="candidate-checksum",
                    is_publishable=True,
                    issues=[],
                    actor_account_id="account-admin",
                    request_id="request-validation-1",
                    created_at=_INSTANT,
                )
            )
            session.add(
                RuleSetVersionRecord(
                    version_id="version-orders-1",
                    binding_id="binding-orders-flow",
                    kind="flow",
                    profile="atlas-richie-sentinel-managed-v1",
                    base_version_id=None,
                    checksum="target-checksum",
                    name="Initial",
                    note="receipt test",
                    validation_id="validation-orders-1",
                    records=[],
                    created_at=_INSTANT,
                    created_by_account_id="account-admin",
                )
            )
            session.add(
                RulePublicationRecord(
                    publication_id="publication-orders-1",
                    binding_id="binding-orders-flow",
                    target_version_id="version-orders-1",
                    target_checksum="target-checksum",
                    target_payload_checksum=_PAYLOAD_SHA256,
                    publication_sequence=1,
                    base_version_id=None,
                    created_at=_INSTANT,
                    validation_state="succeeded",
                    validation_observed_at=_INSTANT,
                    validation_reason=None,
                    write_state="succeeded",
                    write_observed_at=_INSTANT,
                    write_reason=None,
                    read_back_state="succeeded",
                    read_back_observed_at=_INSTANT,
                    read_back_reason=None,
                )
            )
            session.add(
                MetricsReporterBindingRecord(
                    certificate_principal=_PRINCIPAL,
                    certificate_sha256=_CERTIFICATE,
                    reporter_id="reporter-orders-worker-0",
                    environment_id=_ENVIRONMENT,
                    app_id=_APP,
                    instance_id=_INSTANCE,
                    process_id=_PROCESS,
                    revoked_at=None,
                    current_epoch=_EPOCH,
                    last_sequence=0,
                    last_elapsed_ns=None,
                    last_received_at=None,
                )
            )
        inbox = SQLAlchemyRulePublicationReceiptInbox(self._engine)
        self.ingest = IngestRulePublicationReceipt(inbox, clock=lambda: _INSTANT)
        self.peer = VerifiedMetricsPeer(_CERTIFICATE)

    async def _engine(self):
        return self.engine

    async def test_commit_before_ack_and_exact_replay_enqueues_once(self):
        body = encode_rule_publication_receipt(_receipt())

        accepted = await self.ingest.execute(self.peer, body)
        retried = await self.ingest.execute(self.peer, body)

        self.assertEqual(retried, accepted)
        async with self.sessions() as session:
            inbox = (
                await session.scalars(select(RulePublicationReceiptInboxRecord))
            ).all()
            outbox = (
                await session.scalars(select(RulePublicationReceiptOutboxRecord))
            ).all()
            sequence = await session.get(
                RulePublicationReceiptSequenceRecord, (_PRINCIPAL, _EPOCH)
            )
        self.assertEqual(len(inbox), 1)
        self.assertEqual(len(outbox), 1)
        self.assertEqual(inbox[0].body, body)
        self.assertEqual(inbox[0].body_sha256, hashlib.sha256(body).hexdigest())
        self.assertEqual(inbox[0].instance_id, _INSTANCE)
        self.assertEqual(outbox[0].state, "pending")
        self.assertEqual(sequence.last_sequence, 1)

    async def test_scope_digest_sequence_and_revocation_rejections_are_durable_noops(
        self,
    ):

        cases = (
            (_receipt(digest="b" * 64), ErrorCode.DIGEST_MISMATCH),
            (
                _receipt(target_version_id="version-foreign"),
                ErrorCode.TARGET_MISMATCH,
            ),
            (_receipt(binding_id="binding-foreign"), ErrorCode.PUBLICATION_NOT_FOUND),
        )
        for receipt, expected in cases:
            with self.assertRaises(PublicationReceiptIngestError) as raised:
                await self.ingest.execute(
                    self.peer, encode_rule_publication_receipt(receipt)
                )
            self.assertIs(raised.exception.code, expected)

        body = encode_rule_publication_receipt(_receipt())
        await self.ingest.execute(self.peer, body)
        with self.assertRaises(PublicationReceiptIngestError) as stale:
            await self.ingest.execute(
                self.peer, encode_rule_publication_receipt(_receipt(sequence=1))
            )
        self.assertIs(stale.exception.code, ErrorCode.STALE_SEQUENCE)

        async with self.sessions.begin() as session:
            await session.execute(
                update(MetricsReporterBindingRecord)
                .where(MetricsReporterBindingRecord.certificate_principal == _PRINCIPAL)
                .values(app_id="different-app")
            )
        with self.assertRaises(PublicationReceiptIngestError) as scope:
            await self.ingest.execute(
                self.peer, encode_rule_publication_receipt(_receipt(sequence=2))
            )
        self.assertIs(scope.exception.code, ErrorCode.SCOPE_MISMATCH)

        async with self.sessions.begin() as session:
            await session.execute(
                update(MetricsReporterBindingRecord)
                .where(MetricsReporterBindingRecord.certificate_principal == _PRINCIPAL)
                .values(revoked_at=_INSTANT, app_id=_APP)
            )
        with self.assertRaises(PublicationReceiptIngestError) as revoked:
            await self.ingest.execute(
                self.peer, encode_rule_publication_receipt(_receipt(sequence=2))
            )
        self.assertIs(revoked.exception.code, ErrorCode.IDENTITY_REVOKED)

        async with self.sessions() as session:
            inbox = (
                await session.scalars(select(RulePublicationReceiptInboxRecord))
            ).all()
            outbox = (
                await session.scalars(select(RulePublicationReceiptOutboxRecord))
            ).all()
        self.assertEqual(len(inbox), 1)
        self.assertEqual(len(outbox), 1)

    async def test_stale_epoch_is_rejected_before_durable_enqueue(self):
        async with self.sessions.begin() as session:
            await session.execute(
                update(MetricsReporterBindingRecord)
                .where(MetricsReporterBindingRecord.certificate_principal == _PRINCIPAL)
                .values(current_epoch=str(uuid4()))
            )
        with self.assertRaises(PublicationReceiptIngestError) as raised:
            await self.ingest.execute(
                self.peer,
                encode_rule_publication_receipt(_receipt()),
            )
        self.assertIs(raised.exception.code, ErrorCode.INVALID_EPOCH)
        async with self.sessions() as session:
            inbox = (
                await session.scalars(select(RulePublicationReceiptInboxRecord))
            ).all()
            outbox = (
                await session.scalars(select(RulePublicationReceiptOutboxRecord))
            ).all()
            sequences = (
                await session.scalars(select(RulePublicationReceiptSequenceRecord))
            ).all()
        self.assertEqual(inbox, [])
        self.assertEqual(outbox, [])
        self.assertEqual(sequences, [])

    async def test_same_receipt_id_with_different_bytes_is_rejected(self):
        receipt_id = str(uuid4())
        await self.ingest.execute(
            self.peer,
            encode_rule_publication_receipt(_receipt(receipt_id=receipt_id)),
        )
        conflict = _receipt(
            sequence=2,
            receipt_id=receipt_id,
            digest="b" * 64,
        )
        with self.assertRaises(PublicationReceiptIngestError) as raised:
            await self.ingest.execute(
                self.peer, encode_rule_publication_receipt(conflict)
            )
        self.assertIs(raised.exception.code, ErrorCode.IDEMPOTENCY_CONFLICT)

    async def test_mtls_route_acks_only_after_durable_acceptance(self):
        certificate_pem, fingerprint = _tls_certificate()
        async with self.sessions.begin() as session:
            await session.execute(
                update(MetricsReporterBindingRecord)
                .where(MetricsReporterBindingRecord.certificate_principal == _PRINCIPAL)
                .values(certificate_sha256=fingerprint)
            )
        app = Starlette(routes=[rule_publication_receipt_ingest_route(self.ingest)])
        wrapped = _TlsScope(app, (certificate_pem,))
        body = encode_rule_publication_receipt(_receipt())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://collector.test",
        ) as client:
            unauthenticated = await client.post(
                "/api/reporting/v1/rule-publication-receipts",
                content=body,
                headers={"content-type": "application/json"},
            )
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(
            unauthenticated.json()["error"]["code"], "identity_not_enrolled"
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=wrapped),
            base_url="https://collector.test",
        ) as client:
            response = await client.post(
                "/api/reporting/v1/rule-publication-receipts",
                content=body,
                headers={"content-type": "application/json"},
            )
            # Simulate the response being lost after the transaction committed.
            replay = await client.post(
                "/api/reporting/v1/rule-publication-receipts",
                content=body,
                headers={"content-type": "application/json"},
            )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(replay.status_code, 204)
        async with self.sessions() as session:
            inbox = (
                await session.scalars(select(RulePublicationReceiptInboxRecord))
            ).all()
            outbox = (
                await session.scalars(select(RulePublicationReceiptOutboxRecord))
            ).all()
        self.assertEqual(len(inbox), 1)
        self.assertEqual(len(outbox), 1)

    async def test_mtls_route_never_acks_when_outbox_commit_fails(self):
        certificate_pem, fingerprint = _tls_certificate()
        async with self.sessions.begin() as session:
            await session.execute(
                update(MetricsReporterBindingRecord)
                .where(MetricsReporterBindingRecord.certificate_principal == _PRINCIPAL)
                .values(certificate_sha256=fingerprint)
            )
        app = Starlette(routes=[rule_publication_receipt_ingest_route(self.ingest)])
        wrapped = _TlsScope(app, (certificate_pem,))
        body = encode_rule_publication_receipt(_receipt())

        def fail_outbox_insert(_conn, _cursor, statement, parameters, _context, _many):
            if (
                "insert into console_rule_publication_receipt_outbox"
                in statement.lower()
            ):
                raise OperationalError(
                    statement, parameters, RuntimeError("injected storage failure")
                )

        event.listen(
            self.engine.sync_engine, "before_cursor_execute", fail_outbox_insert
        )
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=wrapped),
                base_url="https://collector.test",
            ) as client:
                response = await client.post(
                    "/api/reporting/v1/rule-publication-receipts",
                    content=body,
                    headers={"content-type": "application/json"},
                )
        finally:
            event.remove(
                self.engine.sync_engine, "before_cursor_execute", fail_outbox_insert
            )

        self.assertEqual(response.status_code, 503)
        async with self.sessions() as session:
            inbox = (
                await session.scalars(select(RulePublicationReceiptInboxRecord))
            ).all()
            outbox = (
                await session.scalars(select(RulePublicationReceiptOutboxRecord))
            ).all()
            sequences = (
                await session.scalars(select(RulePublicationReceiptSequenceRecord))
            ).all()
        self.assertEqual(inbox, [])
        self.assertEqual(outbox, [])
        self.assertEqual(sequences, [])

    async def test_projection_redelivery_is_idempotent_after_projection_commit(self):
        await self.ingest.execute(
            self.peer, encode_rule_publication_receipt(_receipt(sequence=8))
        )
        queue = SqlAlchemyRulePublicationReceiptProjectionQueue(self.engine)
        claim_now = _INSTANT + timedelta(seconds=1)
        claims = await queue.claim_ready(
            now=claim_now,
            lease_expires_at=claim_now + timedelta(seconds=30),
            limit=10,
        )
        self.assertEqual(len(claims), 1)

        await queue.project(claims[0], now=claim_now)
        async with self.sessions() as session:
            projection = await session.get(
                RulePublicationReceiptRecord,
                ("publication-orders-1", _INSTANCE),
            )
            outbox = await session.get(
                RulePublicationReceiptOutboxRecord, claims[0].receipt.receipt_id
            )
        self.assertEqual(projection.receipt_id, claims[0].receipt.receipt_id)
        self.assertEqual(projection.receipt_sequence, 8)
        self.assertEqual(projection.loaded_checksum, "target-checksum")
        self.assertEqual(projection.last_report_at.replace(tzinfo=UTC), _INSTANT)
        self.assertEqual(outbox.state, "claimed")

        retry_now = claim_now + timedelta(seconds=31)
        worker = RunRulePublicationReceiptProjectionWorker(queue)
        result = await worker.run_once(now=retry_now, batch_size=10)
        self.assertEqual((result.claimed, result.delivered, result.parked), (1, 1, 0))
        async with self.sessions() as session:
            projections = (
                await session.scalars(select(RulePublicationReceiptRecord))
            ).all()
            outbox = await session.get(
                RulePublicationReceiptOutboxRecord, claims[0].receipt.receipt_id
            )
        self.assertEqual(len(projections), 1)
        self.assertEqual(outbox.state, "delivered")

    async def test_expired_claim_is_recovered_after_worker_termination(self):
        await self.ingest.execute(
            self.peer, encode_rule_publication_receipt(_receipt())
        )
        queue = SqlAlchemyRulePublicationReceiptProjectionQueue(self.engine)
        claimed_at = _INSTANT + timedelta(seconds=1)
        abandoned_claim = await queue.claim_ready(
            now=claimed_at,
            lease_expires_at=claimed_at + timedelta(seconds=5),
            limit=1,
        )
        self.assertEqual(len(abandoned_claim), 1)

        result = await RunRulePublicationReceiptProjectionWorker(queue).run_once(
            now=claimed_at + timedelta(seconds=6), batch_size=1
        )

        self.assertEqual((result.claimed, result.delivered, result.parked), (1, 1, 0))
        async with self.sessions() as session:
            outbox = await session.scalar(select(RulePublicationReceiptOutboxRecord))
            projection = await session.scalar(select(RulePublicationReceiptRecord))
        self.assertEqual(outbox.state, "delivered")
        self.assertIsNotNone(projection)

    async def test_pending_outbox_survives_reopening_the_database(self):
        receipt = _receipt()
        await self.ingest.execute(self.peer, encode_rule_publication_receipt(receipt))
        reopened_engine = create_async_engine(str(self.engine.url))
        self.addAsyncCleanup(reopened_engine.dispose)
        async with async_sessionmaker(reopened_engine)() as session:
            outbox = await session.get(
                RulePublicationReceiptOutboxRecord, receipt.receipt_id
            )
        self.assertEqual(outbox.state, "pending")

    async def test_projection_parks_receipt_from_a_superseded_process_epoch(self):
        await self.ingest.execute(
            self.peer, encode_rule_publication_receipt(_receipt())
        )
        async with self.sessions.begin() as session:
            await session.execute(
                update(MetricsReporterBindingRecord)
                .where(MetricsReporterBindingRecord.certificate_principal == _PRINCIPAL)
                .values(current_epoch=str(uuid4()))
            )
        queue = SqlAlchemyRulePublicationReceiptProjectionQueue(self.engine)
        worker = RunRulePublicationReceiptProjectionWorker(queue)
        result = await worker.run_once(
            now=_INSTANT + timedelta(seconds=1), batch_size=10
        )
        self.assertEqual((result.claimed, result.delivered, result.parked), (1, 0, 1))
        async with self.sessions() as session:
            projection = await session.scalar(select(RulePublicationReceiptRecord))
            outbox = await session.scalar(select(RulePublicationReceiptOutboxRecord))
        self.assertIsNone(projection)
        self.assertEqual(outbox.state, "parked")
        self.assertEqual(outbox.rejection_code, "stale_epoch")

    async def test_projection_parks_when_inbox_index_fields_diverge_from_wire_fact(
        self,
    ):
        receipt = _receipt()
        await self.ingest.execute(self.peer, encode_rule_publication_receipt(receipt))
        async with self.sessions.begin() as session:
            await session.execute(
                update(RulePublicationReceiptInboxRecord)
                .where(
                    RulePublicationReceiptInboxRecord.receipt_id == receipt.receipt_id
                )
                .values(sequence=99)
            )

        result = await RunRulePublicationReceiptProjectionWorker(
            SqlAlchemyRulePublicationReceiptProjectionQueue(self.engine)
        ).run_once(now=_INSTANT + timedelta(seconds=1), batch_size=10)

        self.assertEqual((result.delivered, result.parked, result.retried), (0, 1, 0))
        async with self.sessions() as session:
            projection = await session.scalar(select(RulePublicationReceiptRecord))
            outbox = await session.scalar(select(RulePublicationReceiptOutboxRecord))
        self.assertIsNone(projection)
        self.assertEqual(outbox.state, "parked")
        self.assertEqual(outbox.rejection_code, "invalid_inbox")

    async def test_projection_rechecks_reporter_scope_before_read_model_write(self):
        await self.ingest.execute(
            self.peer, encode_rule_publication_receipt(_receipt())
        )
        async with self.sessions.begin() as session:
            await session.execute(
                update(MetricsReporterBindingRecord)
                .where(MetricsReporterBindingRecord.certificate_principal == _PRINCIPAL)
                .values(app_id="different-app")
            )

        result = await RunRulePublicationReceiptProjectionWorker(
            SqlAlchemyRulePublicationReceiptProjectionQueue(self.engine)
        ).run_once(now=_INSTANT + timedelta(seconds=1), batch_size=10)

        self.assertEqual((result.delivered, result.parked, result.retried), (0, 1, 0))
        async with self.sessions() as session:
            projection = await session.scalar(select(RulePublicationReceiptRecord))
            outbox = await session.scalar(select(RulePublicationReceiptOutboxRecord))
        self.assertIsNone(projection)
        self.assertEqual(outbox.state, "parked")
        self.assertEqual(outbox.rejection_code, "scope_mismatch")

    async def test_projection_parks_corrupt_inbox_bytes_instead_of_retrying_forever(
        self,
    ):
        receipt = _receipt()
        await self.ingest.execute(self.peer, encode_rule_publication_receipt(receipt))
        async with self.sessions.begin() as session:
            await session.execute(
                update(RulePublicationReceiptInboxRecord)
                .where(
                    RulePublicationReceiptInboxRecord.receipt_id == receipt.receipt_id
                )
                .values(body=b"not a receipt")
            )

        result = await RunRulePublicationReceiptProjectionWorker(
            SqlAlchemyRulePublicationReceiptProjectionQueue(self.engine)
        ).run_once(now=_INSTANT + timedelta(seconds=1), batch_size=10)

        self.assertEqual((result.claimed, result.delivered, result.parked), (0, 0, 0))
        async with self.sessions() as session:
            projection = await session.scalar(select(RulePublicationReceiptRecord))
            outbox = await session.scalar(select(RulePublicationReceiptOutboxRecord))
        self.assertIsNone(projection)
        self.assertEqual(outbox.state, "parked")
        self.assertEqual(outbox.rejection_code, "invalid_inbox")

    async def test_durable_outbox_round_trip_against_sqlite_schema(self) -> None:
        await assert_rule_publication_receipt_outbox_round_trip(
            self, self.engine, "sqlite"
        )
