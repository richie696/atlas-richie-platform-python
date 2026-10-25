from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.monitoring_source_registry import (
    MonitoringCredentialUpdateMode,
    MonitoringSourceCommandForbidden,
    MonitoringSourceIdempotencyConflict,
    MonitoringSourceMutation,
    MonitoringSourceOperationReason,
    MonitoringSourceOperationStatus,
    MonitoringSourceNotFound,
    MonitoringSourceRegistryUnavailable,
    MonitoringSourceRevisionConflict,
    MonitoringSourceSecret,
)
from atlas_richie.sentinel_console.domain.monitoring_sources import (
    MonitoringAuthenticationMode,
    MonitoringLabel,
    MonitoringProfile,
    MonitoringProvider,
    MonitoringSource,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    MonitoringProbeReceiptRecord,
    MonitoringSourceRecord,
    MonitoringSourceOperationRecord,
    HostInstanceAssociationRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.monitoring_source_store import (
    SQLAlchemyMonitoringSourceStore,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)

_NOW = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
_KEY = b"m" * 32


class MonitoringSourceStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="account-admin",
                    username="admin",
                    username_key="a" * 64,
                    password_hash="argon2id$test-hash",
                    role_id="admin",
                    status="active",
                    built_in=True,
                    last_login_at=None,
                    revision=1,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )

        async def engine_resolver():
            return self.engine

        self.store = SQLAlchemyMonitoringSourceStore(
            engine_resolver,
            AesGcmSecretCipher("monitoring-v1", {"monitoring-v1": _KEY}),
            fingerprint_key=b"f" * 32,
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_create_list_and_read_expose_safe_source_without_credentials(self):
        source = _source(
            authentication_mode=MonitoringAuthenticationMode.DIRECT_BASIC,
            credential_configured=True,
        )
        secret = MonitoringSourceSecret(username="prom-user", password="strong-secret")

        created = await self.store.create_monitoring_source(
            source, secret=secret, now=_NOW
        )
        snapshot = await self.store.read_monitoring_sources()
        detail = await self.store.read_monitoring_source(source.source_id)
        resolved = await self.store.resolve_monitoring_source_secret(
            source.source_id, expected_revision=created.revision
        )
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(
                        MonitoringSourceRecord.credential_payload,
                        MonitoringSourceRecord.endpoint,
                    ).where(MonitoringSourceRecord.source_id == source.source_id)
                )
            ).one()

        assert created.revision and created.revision != source.revision
        assert snapshot.items == (created,)
        assert detail == created
        assert resolved == secret
        assert b"strong-secret" not in row.credential_payload
        assert b"prom-user" not in row.credential_payload
        assert "strong-secret" not in repr(secret)
        assert "prom-user" not in repr(secret)

    async def test_reference_handle_is_encrypted_and_resolved_only_for_current_revision(self):
        source = _source(
            authentication_mode=MonitoringAuthenticationMode.CREDENTIAL_REFERENCE,
            credential_configured=True,
        )
        secret = MonitoringSourceSecret(credential_reference="vault://ops/prometheus")
        created = await self.store.create_monitoring_source(
            source, secret=secret, now=_NOW
        )

        resolved = await self.store.resolve_monitoring_source_secret(
            source.source_id, expected_revision=created.revision
        )
        with self.assertRaises(MonitoringSourceRevisionConflict):
            await self.store.resolve_monitoring_source_secret(
                source.source_id, expected_revision="stale-revision"
            )
        async with self.engine.connect() as connection:
            payload = await connection.scalar(
                select(MonitoringSourceRecord.credential_payload).where(
                    MonitoringSourceRecord.source_id == source.source_id
                )
            )

        assert resolved == secret
        assert b"vault://ops/prometheus" not in payload

    async def test_source_command_commits_operation_and_replays_only_for_same_session(self):
        from atlas_richie.sentinel_console.application.monitoring_source_registry import (
            ManageMonitoringSource,
        )

        source = _source()
        command = MonitoringSourceMutation(
            request_key="monitor-create-1",
            kind="create",
            actor_id="account-admin",
            session_digest="s" * 64,
            request_id="req-monitor-create-1",
            source=source,
            credential_update=MonitoringCredentialUpdateMode.CLEAR,
            skip_check=True,
            now=_NOW,
        )
        manager = ManageMonitoringSource(self.store, b"f" * 32)

        first = await manager.execute(command)
        replay = await manager.execute(command)
        readback = await self.store.read_monitoring_source_operation(
            command.request_key,
            actor_id="account-admin",
            session_digest="s" * 64,
        )

        assert first.status is MonitoringSourceOperationStatus.COMPLETED
        assert first.source_revision is not None and first.source_revision != source.revision
        assert first.verified is False
        assert replay == first == readback
        with self.assertRaises(MonitoringSourceIdempotencyConflict):
            await manager.execute(
                replace(command, source=replace(source, display_name="changed"))
            )
        with self.assertRaises(MonitoringSourceCommandForbidden):
            await self.store.read_monitoring_source_operation(
                command.request_key,
                actor_id="account-admin",
                session_digest="x" * 64,
            )
        async with self.engine.connect() as connection:
            source_count = await connection.scalar(
                select(func.count()).select_from(MonitoringSourceRecord)
            )
            operation_count = await connection.scalar(
                select(func.count()).select_from(MonitoringSourceOperationRecord)
            )
        assert source_count == operation_count == 1

    async def test_source_command_check_receipt_must_match_exact_candidate(self):
        from atlas_richie.sentinel_console.application.check_monitoring_source import (
            monitoring_candidate_fingerprint,
        )
        from atlas_richie.sentinel_console.application.monitoring_source_registry import (
            ManageMonitoringSource,
        )

        source = _source()
        candidate_fingerprint = monitoring_candidate_fingerprint(
            source,
            fingerprint_key=b"f" * 32,
            credentials=None,
            credential_reference=None,
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(MonitoringProbeReceiptRecord).values(
                    check_id="check-monitor-source-1",
                    source_id=source.source_id,
                    source_revision=source.revision,
                    actor_account_id="account-admin",
                    session_hash="s" * 64,
                    candidate_fingerprint=candidate_fingerprint,
                    checked_at=_NOW,
                    expires_at=datetime(2026, 10, 17, 10, 10, tzinfo=UTC),
                    connection="reachable",
                    query_api="available",
                    profile="supported",
                    failure=None,
                    observed_count=1,
                    unique_count=1,
                    missing_count=0,
                    conflicting_count=0,
                )
            )
        command = MonitoringSourceMutation(
            request_key="monitor-create-verified-1",
            kind="create",
            actor_id="account-admin",
            session_digest="s" * 64,
            request_id="req-monitor-create-verified-1",
            source=source,
            credential_update=MonitoringCredentialUpdateMode.CLEAR,
            check_id="check-monitor-source-1",
            skip_check=False,
            now=_NOW,
        )

        operation = await ManageMonitoringSource(self.store, b"f" * 32).execute(
            command
        )

        assert operation.status is MonitoringSourceOperationStatus.COMPLETED
        assert operation.verified is True
        async with self.engine.connect() as connection:
            receipt = await connection.scalar(
                select(MonitoringProbeReceiptRecord.check_id).where(
                    MonitoringProbeReceiptRecord.check_id == "check-monitor-source-1"
                )
            )
        assert receipt is None

    async def test_update_keep_rotates_revision_invalidates_probe_and_rejects_stale_writer(
        self,
    ):
        original = _source(
            authentication_mode=MonitoringAuthenticationMode.DIRECT_BEARER,
            credential_configured=True,
        )
        created = await self.store.create_monitoring_source(
            original,
            secret=MonitoringSourceSecret(bearer_token="initial-token"),
            now=_NOW,
        )
        await self._insert_receipt("check-current")
        updated = await self.store.update_monitoring_source(
            replace(created, display_name="Prometheus primary"),
            expected_revision=created.revision,
            credential_update=MonitoringCredentialUpdateMode.KEEP,
            secret=None,
            now=_NOW,
        )
        resolved = await self.store.resolve_monitoring_source_secret(
            created.source_id, expected_revision=updated.revision
        )
        async with self.engine.connect() as connection:
            receipt_count = await connection.scalar(
                select(MonitoringProbeReceiptRecord.check_id).where(
                    MonitoringProbeReceiptRecord.check_id == "check-current"
                )
            )

        assert updated.display_name == "Prometheus primary"
        assert updated.revision != created.revision
        assert resolved == MonitoringSourceSecret(bearer_token="initial-token")
        assert receipt_count is None
        with self.assertRaises(MonitoringSourceRevisionConflict):
            await self.store.update_monitoring_source(
                replace(created, display_name="stale write"),
                expected_revision=created.revision,
                credential_update=MonitoringCredentialUpdateMode.KEEP,
                secret=None,
                now=_NOW,
            )

    async def test_replace_and_clear_credentials_are_explicit(self):
        original = _source(
            authentication_mode=MonitoringAuthenticationMode.DIRECT_BASIC,
            credential_configured=True,
        )
        created = await self.store.create_monitoring_source(
            original,
            secret=MonitoringSourceSecret(username="first", password="first-password"),
            now=_NOW,
        )
        replaced = await self.store.update_monitoring_source(
            created,
            expected_revision=created.revision,
            credential_update=MonitoringCredentialUpdateMode.REPLACE,
            secret=MonitoringSourceSecret(username="second", password="second-password"),
            now=_NOW,
        )
        assert await self.store.resolve_monitoring_source_secret(
            created.source_id, expected_revision=replaced.revision
        ) == MonitoringSourceSecret(username="second", password="second-password")

        cleared_source = replace(
            replaced,
            authentication_mode=MonitoringAuthenticationMode.NONE,
            credential_configured=False,
        )
        cleared = await self.store.update_monitoring_source(
            cleared_source,
            expected_revision=replaced.revision,
            credential_update=MonitoringCredentialUpdateMode.CLEAR,
            secret=None,
            now=_NOW,
        )
        assert await self.store.resolve_monitoring_source_secret(
            created.source_id, expected_revision=cleared.revision
        ) is None

    async def test_delete_requires_revision_and_removes_source_and_receipts(self):
        source = await self.store.create_monitoring_source(
            _source(), secret=None, now=_NOW
        )
        await self._insert_receipt("check-to-delete")

        with self.assertRaises(MonitoringSourceRevisionConflict):
            await self.store.delete_monitoring_source(
                source.source_id, expected_revision="stale", now=_NOW
            )
        await self.store.delete_monitoring_source(
            source.source_id, expected_revision=source.revision, now=_NOW
        )
        with self.assertRaises(MonitoringSourceNotFound):
            await self.store.read_monitoring_source(source.source_id)
        async with self.engine.connect() as connection:
            receipt = await connection.scalar(
                select(MonitoringProbeReceiptRecord.check_id).where(
                    MonitoringProbeReceiptRecord.check_id == "check-to-delete"
                )
            )
        assert receipt is None

    async def test_delete_rejects_source_referenced_by_host_association(self):
        source = await self.store.create_monitoring_source(
            _source(), secret=None, now=_NOW
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(HostInstanceAssociationRecord).values(
                    environment_id=source.environment_id,
                    app_id="orders",
                    instance_id="orders-1",
                    source_id=source.source_id,
                    host_id="host-1",
                    revision="association-revision-1",
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )

        command = MonitoringSourceMutation(
            request_key="monitor-delete-in-use-1",
            kind="delete",
            actor_id="account-admin",
            session_digest="a" * 64,
            request_id="monitor-delete-in-use-request",
            source_id=source.source_id,
            expected_revision=source.revision,
            now=_NOW,
        )
        operation = await self.store.execute_monitoring_source_mutation(command)
        replay = await self.store.read_monitoring_source_operation(
            command.request_key,
            actor_id=command.actor_id,
            session_digest=command.session_digest,
        )

        assert operation.status is MonitoringSourceOperationStatus.REJECTED
        assert operation.reason is MonitoringSourceOperationReason.SOURCE_IN_USE
        assert replay == operation
        assert await self.store.read_monitoring_source(source.source_id) == source
        async with self.engine.connect() as connection:
            association_count = await connection.scalar(
                select(func.count())
                .select_from(HostInstanceAssociationRecord)
                .where(HostInstanceAssociationRecord.source_id == source.source_id)
            )
        assert association_count == 1

    async def test_set_enabled_rotates_revision_without_touching_credentials(self):
        source = _source(
            authentication_mode=MonitoringAuthenticationMode.DIRECT_BEARER,
            credential_configured=True,
        )
        created = await self.store.create_monitoring_source(
            source,
            secret=MonitoringSourceSecret(bearer_token="private-monitor-token"),
            now=_NOW,
        )
        async with self.engine.connect() as connection:
            encrypted_before = await connection.scalar(
                select(MonitoringSourceRecord.credential_payload).where(
                    MonitoringSourceRecord.source_id == source.source_id
                )
            )
        command = MonitoringSourceMutation(
            request_key="monitoring-enable-1",
            kind="set-enabled",
            actor_id="account-admin",
            session_digest="a" * 64,
            request_id="monitoring-enable-request",
            source_id=source.source_id,
            expected_revision=created.revision,
            enabled=False,
            now=_NOW,
        )

        result = await self.store.execute_monitoring_source_mutation(command)
        updated = await self.store.read_monitoring_source(source.source_id)
        async with self.engine.connect() as connection:
            encrypted_after = await connection.scalar(
                select(MonitoringSourceRecord.credential_payload).where(
                    MonitoringSourceRecord.source_id == source.source_id
                )
            )

        assert result.status is MonitoringSourceOperationStatus.COMPLETED
        assert result.enabled is False
        assert updated.enabled is False
        assert updated.revision != created.revision
        assert encrypted_after == encrypted_before
        assert await self.store.resolve_monitoring_source_secret(
            source.source_id, expected_revision=updated.revision
        ) == MonitoringSourceSecret(bearer_token="private-monitor-token")

    async def test_wrong_key_or_corrupt_envelope_is_sanitized(self):
        source = _source(
            authentication_mode=MonitoringAuthenticationMode.DIRECT_BEARER,
            credential_configured=True,
        )
        created = await self.store.create_monitoring_source(
            source,
            secret=MonitoringSourceSecret(bearer_token="do-not-leak"),
            now=_NOW,
        )
        async def engine_resolver():
            return self.engine

        wrong_key_store = SQLAlchemyMonitoringSourceStore(
            engine_resolver, AesGcmSecretCipher("other", {"other": b"z" * 32})
        )

        with self.assertRaises(MonitoringSourceRegistryUnavailable) as caught:
            await wrong_key_store.resolve_monitoring_source_secret(
                source.source_id, expected_revision=created.revision
            )
        assert "do-not-leak" not in str(caught.exception)
        assert "do-not-leak" not in repr(caught.exception)

    async def test_registry_rejects_secret_that_does_not_match_authentication_mode(self):
        with self.assertRaises(ValueError):
            await self.store.create_monitoring_source(
                _source(), secret=MonitoringSourceSecret(bearer_token="wrong-mode"), now=_NOW
            )

    async def _insert_receipt(self, check_id: str) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(MonitoringProbeReceiptRecord).values(
                    check_id=check_id,
                    source_id="monitoring-local",
                    source_revision="source-rev",
                    actor_account_id="account-admin",
                    session_hash="s" * 64,
                    candidate_fingerprint="f" * 64,
                    checked_at=_NOW,
                    expires_at=datetime(2026, 10, 17, 10, 10, tzinfo=UTC),
                    connection="reachable",
                    query_api="available",
                    profile="supported",
                    failure=None,
                    observed_count=1,
                    unique_count=1,
                    missing_count=0,
                    conflicting_count=0,
                )
            )


def _source(**changes: object) -> MonitoringSource:
    values: dict[str, object] = {
        "source_id": "monitoring-local",
        "revision": "draft-revision",
        "display_name": "Local Prometheus",
        "environment_id": "development",
        "endpoint": "http://127.0.0.1:9090",
        "provider": MonitoringProvider.PROMETHEUS_COMPATIBLE,
        "profile": MonitoringProfile.NODE_EXPORTER_V1,
        "authentication_mode": MonitoringAuthenticationMode.NONE,
        "credential_configured": False,
        "enabled": True,
        "identity_labels": ("host",),
        "selector_labels": (MonitoringLabel("job", "node-exporter"),),
        "scrape_interval_seconds": 15,
        "stale_after_seconds": 90,
    }
    values.update(changes)
    return MonitoringSource(**values)  # type: ignore[arg-type]
