"""SQLite integration tests for durable registered-source mutation semantics."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
import unittest

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.application.mutate_registered_source import (
    RegisteredSourceDeletion,
    RegisteredSourceMutation,
    SourceMutationForbidden,
    SourceMutationIdempotencyConflict,
    SourceMutationKind,
    SourceMutationRejection,
    SourceMutationStatus,
    SourceDeletionRejection,
    SourceMutationUnauthenticated,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuditEventRecord,
    AuthenticationSessionRecord,
    RegisteredConfigurationSourceRecord,
    RegisteredSourceOperationRecord,
    RegisteredSourceDeletionOperationRecord,
    RegisteredSourceProbeRecord,
    RuleBindingRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    registered_source_store,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
    EncryptedSecret,
    SecretContext,
    SecretCipherFormat,
    SecretCipherError,
)

_SESSION = "registered-source-session-token-0000000000000001"
_CSRF = "registered-source-csrf-token-00000000000000001"
_NOW = datetime.now(UTC)
_SESSION_DIGEST = hashlib.sha256(_SESSION.encode("ascii")).hexdigest()
_CSRF_DIGEST = hashlib.sha256(_CSRF.encode("ascii")).hexdigest()


class RegisteredSourceStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        self.cipher = AesGcmSecretCipher("key-v1", {"key-v1": b"k" * 32})
        self.store = registered_source_store.SqlAlchemyRegisteredSourceStore(
            self.engine,
            secret_cipher=self.cipher,
            fingerprint_keys={"fingerprint-v1": b"f" * 32},
            active_fingerprint_key_id="fingerprint-v1",
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="account-1",
                    username="Admin",
                    username_key="a" * 64,
                    password_hash="$argon2id$redacted-test-hash",
                    role_id="admin",
                    status="active",
                    built_in=True,
                    revision=1,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=_SESSION_DIGEST,
                    account_id="account-1",
                    session_epoch="epoch-1",
                    csrf_hash=_CSRF_DIGEST,
                    created_at=_NOW,
                    expires_at=_NOW + timedelta(hours=1),
                    revoked_at=None,
                )
            )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    def _command(
        self,
        *,
        request_key="source-request-1",
        name="Production Nacos",
        source_id=None,
        revision=None,
        endpoint="https://nacos.internal:8848",
        authentication_mode=SourceCheckAuthenticationMode.DIRECT,
        username="operator",
        password="source-secret-do-not-store-plain",
    ):
        source = SourceConnectionInput(
            source_id=source_id,
            expected_revision=revision,
            provider=ConfigurationSourceProvider.NACOS,
            endpoint=endpoint,
            location="sentinel",
            authentication_mode=authentication_mode,
            username=username,
            password=password,
        )
        kind = (
            SourceMutationKind.UPDATE
            if source_id is not None
            else SourceMutationKind.REGISTER
        )
        return RegisteredSourceMutation(kind, request_key, name, source)

    async def _mutate(
        self,
        command,
        *,
        actor_id="account-1",
        session_digest=_SESSION_DIGEST,
        csrf_digest=_CSRF_DIGEST,
    ):
        return await self.store.mutate(
            command,
            actor_id=actor_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id="source-store-test-request",
            now=_NOW,
        )

    async def _delete(
        self,
        command,
        *,
        actor_id="account-1",
        session_digest=_SESSION_DIGEST,
        csrf_digest=_CSRF_DIGEST,
    ):
        return await self.store.delete(
            command,
            actor_id=actor_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id="source-delete-test-request",
            now=_NOW,
        )

    async def test_register_encrypts_secret_and_commits_receipt_and_audit(self) -> None:
        command = self._command()
        result = await self._mutate(command)
        self.assertEqual(result.status, SourceMutationStatus.COMPLETED)
        self.assertIsNotNone(result.record)
        self.assertTrue(result.record.credential_configured)

        async with self.engine.connect() as connection:
            source_query = await connection.execute(
                select(RegisteredConfigurationSourceRecord.__table__)
            )
            source = source_query.mappings().one()
            operation_query = await connection.execute(
                select(RegisteredSourceOperationRecord.__table__)
            )
            operation = operation_query.mappings().one()
            audit_result = await connection.execute(select(AuditEventRecord.__table__))
            audit = audit_result.mappings().one()
        self.assertNotIn("source-secret-do-not-store-plain", repr(dict(source)))
        self.assertNotIn("source-secret-do-not-store-plain", repr(dict(operation)))
        encrypted = EncryptedSecret(
            format=SecretCipherFormat.AES_256_GCM_V1,
            key_id=source["credential_key_id"],
            payload=source["credential_payload"],
        )
        plaintext = self.cipher.decrypt(
            encrypted,
            SecretContext("configuration-source", result.record.id, "authentication"),
        )
        self.assertIn("source-secret-do-not-store-plain", plaintext)
        self.assertEqual(audit["actor_account_id"], "account-1")
        self.assertEqual(audit["target_id"], result.record.id)
        snapshot = await self.store.read_registered_sources()
        self.assertEqual(snapshot.items, (result.record,))

    async def test_delete_erases_online_credential_and_is_idempotently_audited(self) -> None:
        registered = await self._mutate(self._command())
        assert registered.record is not None
        command = RegisteredSourceDeletion(
            "source-delete-request-1", registered.record.id, registered.record.revision
        )

        deleted = await self._delete(command)
        replay = await self._delete(command)

        self.assertEqual(deleted.status, SourceMutationStatus.COMPLETED)
        self.assertEqual(deleted.deleted_source_id, registered.record.id)
        self.assertEqual(replay, deleted)
        self.assertIsNone(
            await self.store.resolve_credentials(
                registered.record.id,
                registered.record.revision,
                ConfigurationSourceProvider.NACOS,
            )
        )
        self.assertEqual((await self.store.read_registered_sources()).items, ())
        self.assertEqual(
            await self.store.read_operation(
                command.request_key,
                actor_id="account-1",
                session_digest=_SESSION_DIGEST,
            ),
            deleted,
        )

        async with self.engine.connect() as connection:
            source_rows = (
                await connection.execute(select(RegisteredConfigurationSourceRecord))
            ).all()
            receipt = (
                await connection.execute(
                    select(RegisteredSourceDeletionOperationRecord.__table__)
                )
            ).mappings().one()
            audits = (
                await connection.execute(
                    select(AuditEventRecord.__table__).where(
                        AuditEventRecord.action == "configuration.source.delete"
                    )
                )
            ).mappings().all()
        self.assertEqual(source_rows, [])
        self.assertNotIn("https://nacos.internal:8848", repr(dict(receipt)))
        self.assertNotIn("source-secret-do-not-store-plain", repr(dict(receipt)))
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["target_id"], registered.record.id)

    async def test_delete_rejects_references_and_preserves_source_credentials(self) -> None:
        registered = await self._mutate(self._command())
        assert registered.record is not None
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(RuleBindingRecord).values(
                    binding_id="binding-in-use",
                    environment_id="test",
                    app_id="app",
                    kind="flow",
                    profile="default",
                    source_id=registered.record.id,
                    location="sentinel",
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
        command = RegisteredSourceDeletion(
            "source-delete-in-use", registered.record.id, registered.record.revision
        )

        rejected = await self._delete(command)

        self.assertEqual(rejected.status, SourceMutationStatus.REJECTED)
        self.assertEqual(rejected.reason, SourceDeletionRejection.SOURCE_IN_USE)
        self.assertIsNotNone(
            await self.store.resolve_credentials(
                registered.record.id,
                registered.record.revision,
                ConfigurationSourceProvider.NACOS,
            )
        )
        self.assertEqual(len((await self.store.read_registered_sources()).items), 1)

    async def test_delete_revision_conflict_nonexistent_and_request_key_reuse(self) -> None:
        registered = await self._mutate(self._command())
        assert registered.record is not None
        conflict = await self._delete(
            RegisteredSourceDeletion(
                "source-delete-conflict", registered.record.id, "stale-revision"
            )
        )
        missing = await self._delete(
            RegisteredSourceDeletion(
                "source-delete-missing", "source-absent", "revision-absent"
            )
        )
        self.assertEqual(conflict.reason, SourceDeletionRejection.CONFLICT)
        self.assertEqual(missing.reason, SourceDeletionRejection.NOT_FOUND)
        with self.assertRaises(SourceMutationIdempotencyConflict):
            await self._delete(
                RegisteredSourceDeletion(
                    "source-delete-conflict", registered.record.id, registered.record.revision
                )
            )

    async def test_idempotent_replay_and_changed_payload_conflict(self) -> None:
        first = await self._mutate(self._command())
        replay = await self._mutate(self._command())
        self.assertEqual(first, replay)
        with self.assertRaises(SourceMutationIdempotencyConflict):
            await self._mutate(self._command(name="Different source"))
        async with self.engine.connect() as connection:
            sources = await connection.scalar(
                select(func.count()).select_from(RegisteredConfigurationSourceRecord)
            )
            operations = await connection.scalar(
                select(func.count()).select_from(RegisteredSourceOperationRecord)
            )
            audits = await connection.scalar(
                select(func.count()).select_from(AuditEventRecord)
            )
        self.assertEqual((sources, operations, audits), (1, 1, 1))

    async def test_fingerprint_key_rotation_keeps_replayable_receipts(self) -> None:
        command = self._command()
        first = await self._mutate(command)
        rotated_store = registered_source_store.SqlAlchemyRegisteredSourceStore(
            self.engine,
            secret_cipher=self.cipher,
            fingerprint_keys={
                "fingerprint-v1": b"f" * 32,
                "fingerprint-v2": b"g" * 32,
            },
            active_fingerprint_key_id="fingerprint-v2",
        )
        self.store = rotated_store
        replay = await self._mutate(command)
        self.assertEqual(replay, first)

    async def test_keep_credentials_and_reject_stale_revision(self) -> None:
        created = await self._mutate(self._command())
        assert created.record is not None
        async with self.engine.connect() as connection:
            before = await connection.scalar(
                select(RegisteredConfigurationSourceRecord.credential_payload)
            )
        update_command = self._command(
            request_key="source-update-1",
            source_id=created.record.id,
            revision=created.record.revision,
            endpoint="https://nacos-next.internal:8848",
            authentication_mode=SourceCheckAuthenticationMode.KEEP,
            username=None,
            password=None,
        )
        updated = await self._mutate(update_command)
        assert updated.record is not None
        self.assertNotEqual(updated.record.revision, created.record.revision)
        self.assertEqual(updated.record.endpoint, "https://nacos-next.internal:8848")
        async with self.engine.connect() as connection:
            after = await connection.scalar(
                select(RegisteredConfigurationSourceRecord.credential_payload)
            )
        self.assertEqual(before, after)

        stale = self._command(
            request_key="source-update-stale",
            source_id=created.record.id,
            revision=created.record.revision,
            authentication_mode=SourceCheckAuthenticationMode.KEEP,
            username=None,
            password=None,
        )
        rejected = await self._mutate(stale)
        self.assertEqual(rejected.status, SourceMutationStatus.REJECTED)
        self.assertEqual(rejected.reason, SourceMutationRejection.CONFLICT)

    async def test_probe_read_rejects_revision_no_longer_current_in_registry(self) -> None:
        created = await self._mutate(self._command())
        assert created.record is not None
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(RegisteredSourceProbeRecord).values(
                    source_id=created.record.id,
                    revision=created.record.revision,
                    checked_at=_NOW - timedelta(seconds=1),
                    expires_at=_NOW + timedelta(minutes=1),
                    latency_ms=12.5,
                    capabilities=["read"],
                    reason=None,
                )
            )

        updated = await self._mutate(
            self._command(
                request_key="source-update-revision-race",
                source_id=created.record.id,
                revision=created.record.revision,
                endpoint="https://nacos-updated.internal:8848",
                authentication_mode=SourceCheckAuthenticationMode.KEEP,
                username=None,
                password=None,
            )
        )
        assert updated.record is not None
        self.assertNotEqual(updated.record.revision, created.record.revision)

        stale_probe = await self.store.read_registered_source_probes(
            ((created.record.id, created.record.revision),)
        )

        self.assertEqual(stale_probe, ())

    async def test_missing_source_is_a_durable_not_found_receipt(self) -> None:
        missing = self._command(
            request_key="source-update-missing",
            source_id="missing-source",
            revision="old-revision",
            authentication_mode=SourceCheckAuthenticationMode.KEEP,
            username=None,
            password=None,
        )
        result = await self._mutate(missing)
        self.assertEqual(result.status, SourceMutationStatus.REJECTED)
        self.assertEqual(result.reason, SourceMutationRejection.NOT_FOUND)
        self.assertEqual(
            await self.store.read_operation(
                "source-update-missing",
                actor_id="account-1",
                session_digest=_SESSION_DIGEST,
            ),
            result,
        )

    async def test_transaction_rechecks_session_admin_and_csrf(self) -> None:
        with self.assertRaises(SourceMutationUnauthenticated):
            await self._mutate(self._command(), csrf_digest="0" * 64)
        with self.assertRaises(SourceMutationUnauthenticated):
            await self._mutate(self._command(), session_digest="1" * 64)
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="account-view",
                    username="Viewer",
                    username_key="v" * 64,
                    password_hash="$argon2id$redacted-test-hash",
                    role_id="view",
                    status="active",
                    built_in=False,
                    revision=1,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash="2" * 64,
                    account_id="account-view",
                    session_epoch="epoch-view",
                    csrf_hash="3" * 64,
                    created_at=_NOW,
                    expires_at=_NOW + timedelta(hours=1),
                    revoked_at=None,
                )
            )
        with self.assertRaises(SourceMutationForbidden):
            await self._mutate(
                self._command(),
                actor_id="account-view",
                session_digest="2" * 64,
                csrf_digest="3" * 64,
            )
        async with self.engine.connect() as connection:
            count = await connection.scalar(
                select(func.count()).select_from(RegisteredConfigurationSourceRecord)
            )
        self.assertEqual(count, 0)

    async def test_operation_is_not_visible_to_another_valid_session(self) -> None:
        await self._mutate(self._command())
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="account-other",
                    username="Other",
                    username_key="o" * 64,
                    password_hash="$argon2id$redacted-test-hash",
                    role_id="admin",
                    status="active",
                    built_in=False,
                    revision=1,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash="4" * 64,
                    account_id="account-other",
                    session_epoch="epoch-other",
                    csrf_hash="5" * 64,
                    created_at=_NOW,
                    expires_at=_NOW + timedelta(hours=1),
                    revoked_at=None,
                )
            )
        result = await self.store.read_operation(
            "source-request-1", actor_id="account-other", session_digest="4" * 64
        )
        self.assertIsNone(result)

    async def test_operation_is_visible_after_same_actor_reauthenticates(self) -> None:
        original = await self._mutate(self._command())
        new_session_digest = "6" * 64
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=new_session_digest,
                    account_id="account-1",
                    session_epoch="epoch-reauthenticated",
                    csrf_hash="7" * 64,
                    created_at=_NOW,
                    expires_at=_NOW + timedelta(hours=1),
                    revoked_at=None,
                )
            )

        visible = await self.store.read_operation(
            "source-request-1",
            actor_id="account-1",
            session_digest=new_session_digest,
        )

        self.assertEqual(visible, original)

    async def test_reauthenticated_viewer_cannot_read_admin_operation(self) -> None:
        await self._mutate(self._command())
        viewer_session_digest = "8" * 64
        async with self.engine.begin() as connection:
            await connection.execute(
                update(AccountRecord)
                .where(AccountRecord.account_id == "account-1")
                .values(role_id="view", built_in=False)
            )
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=viewer_session_digest,
                    account_id="account-1",
                    session_epoch="epoch-downgraded",
                    csrf_hash="9" * 64,
                    created_at=_NOW,
                    expires_at=_NOW + timedelta(hours=1),
                    revoked_at=None,
                )
            )

        with self.assertRaises(SourceMutationForbidden):
            await self.store.read_operation(
                "source-request-1",
                actor_id="account-1",
                session_digest=viewer_session_digest,
            )

    async def test_secret_context_mismatch_cannot_decrypt_credential(self) -> None:
        result = await self._mutate(self._command())
        async with self.engine.connect() as connection:
            result_rows = await connection.execute(
                select(RegisteredConfigurationSourceRecord.__table__)
            )
            row = result_rows.mappings().one()
        envelope = EncryptedSecret(
            format=SecretCipherFormat.AES_256_GCM_V1,
            key_id=row["credential_key_id"],
            payload=row["credential_payload"],
        )
        with self.assertRaises(SecretCipherError):
            self.cipher.decrypt(
                envelope,
                SecretContext(
                    "configuration-source",
                    f"not-{result.record.id}",
                    "authentication",
                ),
            )


if __name__ == "__main__":
    unittest.main()
