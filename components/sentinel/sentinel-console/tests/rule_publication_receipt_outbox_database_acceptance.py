"""Real PostgreSQL/MySQL acceptance for the durable receipt projection path."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from atlas_richie.contracts.rules.publication_receipt import (
    PublicationReceiptState,
    RulePublicationReceiptV1,
    encode_rule_publication_receipt,
)
from atlas_richie.sentinel_console.application.ingest_rule_publication_receipt import (
    IngestRulePublicationReceipt,
)
from atlas_richie.sentinel_console.application.metrics_ingest_ports import (
    VerifiedMetricsPeer,
)
from atlas_richie.sentinel_console.application.run_rule_publication_receipt_projection_worker import (
    RunRulePublicationReceiptProjectionWorker,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    identity_composition,
)
from atlas_richie.sentinel_console.infrastructure.persistence.login_attempt_configuration import (
    LoginAttemptLimitConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuthenticationSessionRecord,
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
from atlas_richie.sentinel_console.infrastructure.security.account_command_keys import (
    AccountCommandKeyConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.security.client_identity_key import (
    ClientIdentityKeyConfiguration,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

_CONSOLE_ORIGIN = "https://receipt-outbox.acceptance.invalid"
_SESSION_COOKIE_NAME = "sentinel_session"


class _ClosedSetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


async def assert_rule_publication_receipt_outbox_round_trip(
    case, engine: AsyncEngine, dialect: str
) -> None:
    """Prove durable authenticated acceptance, replay, worker ACK and projection."""
    if dialect not in {"sqlite", "postgresql", "mysql"}:
        raise ValueError("acceptance requires a supported SQL dialect")
    token = uuid4().hex
    now = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)
    account_id = str(uuid4())
    source_id = f"receipt-outbox-source-{token}"
    binding_id = f"receipt-outbox-binding-{token}"
    version_id = f"receipt-outbox-version-{token}"
    publication_id = f"receipt-outbox-publication-{token}"
    principal = f"spiffe://sentinel.acceptance/{token}"
    certificate_sha256 = hashlib.sha256(token.encode("ascii")).hexdigest()
    reporter_id = f"receipt-outbox-reporter-{token}"
    environment_id = f"receipt-outbox-env-{token}"
    app_id = f"receipt-outbox-app-{token}"
    instance_id = f"receipt-outbox-instance-{token}"
    process_id = f"receipt-outbox-process-{token}"
    process_epoch = str(uuid4())
    receipt_id = str(uuid4())
    session_token = f"receipt-outbox-session-{token}"
    session_hash = hashlib.sha256(session_token.encode("ascii")).hexdigest()
    target_payload_sha256 = hashlib.sha256(b"[]").hexdigest()
    receipt = RulePublicationReceiptV1(
        receipt_id=receipt_id,
        process_epoch=process_epoch,
        sequence=1,
        binding_id=binding_id,
        publication_id=publication_id,
        target_version_id=version_id,
        target_payload_sha256=target_payload_sha256,
        state=PublicationReceiptState.APPLIED,
        reason=None,
        source_revision="acceptance-source-revision",
        observed_at=now,
    )
    body = encode_rule_publication_receipt(receipt)
    peer = VerifiedMetricsPeer(certificate_sha256)
    inbox = SQLAlchemyRulePublicationReceiptInbox(lambda: _resolved(engine))

    try:
        async with engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id=account_id,
                    username=f"receipt-{token[:16]}",
                    username_key=f"receipt-{token[:16]}",
                    password_hash="$argon2id$acceptance-only",
                    role_id="admin",
                    status="active",
                    built_in=False,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            await connection.execute(
                insert(RegisteredConfigurationSourceRecord).values(
                    source_id=source_id,
                    revision="acceptance-revision",
                    name="receipt acceptance source",
                    endpoint="https://source.acceptance.invalid",
                    provider="nacos",
                    location="acceptance/rules",
                    authentication_mode="none",
                    credential_configured=False,
                    credential_cipher_format=None,
                    credential_key_id=None,
                    credential_payload=None,
                    created_at=now,
                    updated_at=now,
                    updated_by_account_id=account_id,
                )
            )
            await connection.execute(
                insert(RuleBindingRecord).values(
                    binding_id=binding_id,
                    environment_id=environment_id,
                    app_id=app_id,
                    kind="flow",
                    profile="atlas-richie-sentinel-managed-v1",
                    source_id=source_id,
                    location="acceptance/flow",
                    created_at=now,
                    updated_at=now,
                )
            )
            await connection.execute(
                insert(RuleValidationReceiptRecord).values(
                    validation_id=f"receipt-outbox-validation-{token}",
                    binding_id=binding_id,
                    profile="atlas-richie-sentinel-managed-v1",
                    base_checksum="acceptance-base",
                    candidate_checksum="acceptance-checksum",
                    is_publishable=True,
                    issues=[],
                    actor_account_id=account_id,
                    request_id=f"receipt-outbox-request-{token}",
                    created_at=now,
                )
            )
            await connection.execute(
                insert(RuleSetVersionRecord).values(
                    version_id=version_id,
                    binding_id=binding_id,
                    kind="flow",
                    profile="atlas-richie-sentinel-managed-v1",
                    base_version_id=None,
                    checksum="acceptance-checksum",
                    name="receipt acceptance",
                    note="",
                    validation_id=f"receipt-outbox-validation-{token}",
                    records=[],
                    created_at=now,
                    created_by_account_id=account_id,
                )
            )
            await connection.execute(
                insert(RulePublicationRecord).values(
                    publication_id=publication_id,
                    binding_id=binding_id,
                    target_version_id=version_id,
                    target_checksum="acceptance-checksum",
                    target_payload_checksum=target_payload_sha256,
                    publication_sequence=1,
                    base_version_id=None,
                    created_at=now,
                    validation_state="succeeded",
                    validation_observed_at=now,
                    validation_reason=None,
                    write_state="succeeded",
                    write_observed_at=now,
                    write_reason=None,
                    read_back_state="succeeded",
                    read_back_observed_at=now,
                    read_back_reason=None,
                )
            )
            await connection.execute(
                insert(MetricsReporterBindingRecord).values(
                    certificate_principal=principal,
                    certificate_sha256=certificate_sha256,
                    reporter_id=reporter_id,
                    environment_id=environment_id,
                    app_id=app_id,
                    instance_id=instance_id,
                    process_id=process_id,
                    revoked_at=None,
                    current_epoch=process_epoch,
                    last_sequence=0,
                    last_elapsed_ns=None,
                    last_received_at=None,
                )
            )

        received_at = now + timedelta(milliseconds=1)
        use_case = IngestRulePublicationReceipt(inbox, clock=lambda: received_at)
        await use_case.execute(peer, body)
        await use_case.execute(peer, body)
        async with engine.connect() as connection:
            inbox_count = await connection.scalar(
                select(RulePublicationReceiptInboxRecord.receipt_id).where(
                    RulePublicationReceiptInboxRecord.receipt_id == receipt_id
                )
            )
            outbox_count = await connection.scalar(
                select(RulePublicationReceiptOutboxRecord.receipt_id).where(
                    RulePublicationReceiptOutboxRecord.receipt_id == receipt_id
                )
            )
        case.assertEqual(inbox_count, receipt_id)
        case.assertEqual(outbox_count, receipt_id)

        reopened_engine = create_async_engine(engine.url)
        try:
            async with reopened_engine.connect() as connection:
                durable_outbox_state = await connection.scalar(
                    select(RulePublicationReceiptOutboxRecord.state).where(
                        RulePublicationReceiptOutboxRecord.receipt_id == receipt_id
                    )
                )
            case.assertEqual(durable_outbox_state, "pending")
        finally:
            await reopened_engine.dispose()

        worker = RunRulePublicationReceiptProjectionWorker(
            SqlAlchemyRulePublicationReceiptProjectionQueue(engine)
        )
        result = await worker.run_once(
            now=received_at + timedelta(milliseconds=1), batch_size=10
        )
        case.assertEqual((result.claimed, result.delivered, result.parked), (1, 1, 0))
        async with engine.connect() as connection:
            projection = (
                (
                    await connection.execute(
                        select(RulePublicationReceiptRecord.__table__).where(
                            RulePublicationReceiptRecord.publication_id
                            == publication_id,
                            RulePublicationReceiptRecord.instance_id == instance_id,
                        )
                    )
                )
                .mappings()
                .one()
            )
            outbox_state = await connection.scalar(
                select(RulePublicationReceiptOutboxRecord.state).where(
                    RulePublicationReceiptOutboxRecord.receipt_id == receipt_id
                )
            )
        case.assertEqual(outbox_state, "delivered")
        case.assertEqual(projection["receipt_id"], receipt_id)
        case.assertEqual(projection["receipt_sequence"], 1)
        case.assertEqual(projection["state"], "applied")
        case.assertEqual(projection["loaded_version_id"], version_id)
        case.assertEqual(projection["loaded_checksum"], "acceptance-checksum")

        async with engine.begin() as connection:
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=session_hash,
                    account_id=account_id,
                    session_epoch=str(uuid4()),
                    csrf_hash=hashlib.sha256(
                        f"receipt-outbox-csrf-{token}".encode("ascii")
                    ).hexdigest(),
                    created_at=now,
                    expires_at=now + timedelta(hours=1),
                    revoked_at=None,
                )
            )
        app = identity_composition.build_sql_identity_app(
            engine,
            attempt_limit=LoginAttemptLimitConfiguration(5, 300, 300),
            account_command_keys=AccountCommandKeyConfiguration(
                "receipt-outbox-acceptance-v1",
                {"receipt-outbox-acceptance-v1": b"a" * 32},
            ),
            client_identity_key=ClientIdentityKeyConfiguration(b"c" * 32),
            session_ttl=timedelta(hours=1),
            setup_window_reader=_ClosedSetupWindow(),
            allowed_browser_origins=frozenset({_CONSOLE_ORIGIN}),
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url=_CONSOLE_ORIGIN,
            cookies={_SESSION_COOKIE_NAME: session_token},
        ) as client:
            response = await client.get(
                f"/api/v1/rulesets/{binding_id}/publications/{publication_id}/receipts"
                "?page=1&pageSize=10",
                headers={"x-request-id": f"receipt-outbox-read-{token}"},
            )
            client.cookies.clear()
            anonymous_response = await client.get(
                f"/api/v1/rulesets/{binding_id}/publications/{publication_id}/receipts"
                "?page=1&pageSize=10",
                headers={"x-request-id": f"receipt-outbox-anon-{token}"},
            )
        case.assertEqual(response.status_code, 200)
        case.assertEqual(response.headers["cache-control"], "no-store")
        case.assertEqual(response.json()["total"], 1)
        case.assertEqual(response.json()["applied"], 1)
        case.assertEqual(response.json()["items"][0]["instanceId"], instance_id)
        case.assertEqual(response.json()["items"][0]["loadedVersionId"], version_id)
        case.assertEqual(anonymous_response.status_code, 401)

        retry = await worker.run_once(
            now=received_at + timedelta(seconds=35), batch_size=10
        )
        case.assertEqual((retry.claimed, retry.delivered, retry.parked), (0, 0, 0))
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(AuthenticationSessionRecord).where(
                    AuthenticationSessionRecord.session_hash == session_hash
                )
            )
            await connection.execute(
                delete(RulePublicationReceiptOutboxRecord).where(
                    RulePublicationReceiptOutboxRecord.receipt_id == receipt_id
                )
            )
            await connection.execute(
                delete(RulePublicationReceiptInboxRecord).where(
                    RulePublicationReceiptInboxRecord.receipt_id == receipt_id
                )
            )
            await connection.execute(
                delete(RulePublicationReceiptSequenceRecord).where(
                    RulePublicationReceiptSequenceRecord.certificate_principal
                    == principal
                )
            )
            await connection.execute(
                delete(RulePublicationReceiptRecord).where(
                    RulePublicationReceiptRecord.publication_id == publication_id
                )
            )
            await connection.execute(
                delete(RulePublicationRecord).where(
                    RulePublicationRecord.publication_id == publication_id
                )
            )
            await connection.execute(
                delete(RuleSetVersionRecord).where(
                    RuleSetVersionRecord.version_id == version_id
                )
            )
            await connection.execute(
                delete(RuleValidationReceiptRecord).where(
                    RuleValidationReceiptRecord.binding_id == binding_id
                )
            )
            await connection.execute(
                delete(RuleBindingRecord).where(
                    RuleBindingRecord.binding_id == binding_id
                )
            )
            await connection.execute(
                delete(MetricsReporterBindingRecord).where(
                    MetricsReporterBindingRecord.certificate_principal == principal
                )
            )
            await connection.execute(
                delete(RegisteredConfigurationSourceRecord).where(
                    RegisteredConfigurationSourceRecord.source_id == source_id
                )
            )
            await connection.execute(
                delete(AccountRecord).where(AccountRecord.account_id == account_id)
            )


async def _resolved(engine: AsyncEngine) -> AsyncEngine:
    return engine
