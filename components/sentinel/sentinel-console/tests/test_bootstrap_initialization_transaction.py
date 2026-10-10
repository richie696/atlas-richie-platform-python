"""Isolated SQLite evidence for the target-database initialization transaction."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseKind,
)
from atlas_richie.sentinel_console.application.bootstrap_initialization import (
    BootstrapInitializationIdempotencyConflict,
    BootstrapInitializationInput,
    BootstrapInitializationStatus,
)
from atlas_richie.sentinel_console.application.errors import (
    BootstrapAuthorityUnavailable,
)
from atlas_richie.sentinel_console.application.bootstrap_source_check import (
    BootstrapSourceCandidate,
    BootstrapSourceProvider,
    NacosDirectCredentials,
    SourceCredentialReference,
)
from atlas_richie.sentinel_console.domain.account_password import AccountPassword
from atlas_richie.sentinel_console.domain.account_username import AccountUsername
from atlas_richie.sentinel_console.infrastructure.persistence import (
    bootstrap_initialization_transaction as bootstrap_transaction,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuditEventRecord,
    ConsoleGuardRecord,
    InitializationOperationRecord,
    RegisteredConfigurationSourceRecord,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
    EncryptedSecret,
    SecretCipherFormat,
    SecretContext,
)

_OPERATOR = "synthetic-bootstrap-operator-session"
_NOW = datetime(2026, 10, 9, 2, 0, tzinfo=UTC)


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return opaque_session == _OPERATOR


class _PasswordHasher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def hash_password(self, password: str) -> str:
        if self.fail:
            raise ValueError("synthetic hashing failure")
        return f"test-hash:{len(password)}"


class BootstrapInitializationTransactionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        self.cipher = AesGcmSecretCipher("source-v1", {"source-v1": b"s" * 32})
        self.transaction = self._transaction()

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    def _transaction(self, *, hasher: _PasswordHasher | None = None):
        return (
            bootstrap_transaction.SqlAlchemyBootstrapInitializationTransaction(
                self.engine,
                operator_verifier=_OperatorVerifier(),
                password_hasher=hasher or _PasswordHasher(),
                source_secret_cipher=self.cipher,
                idempotency_key=b"i" * 32,
            )
        )

    @staticmethod
    def _input(
        *,
        password: str = "admin-password-123",
        source_secret: str = "nacos-secret",
        source: BootstrapSourceCandidate | None = None,
    ):
        selected_source = source or BootstrapSourceCandidate(
            provider=BootstrapSourceProvider.NACOS,
            endpoint="https://nacos.internal:8848",
            location="sentinel",
            authentication=NacosDirectCredentials("operator", source_secret),
        )
        return BootstrapInitializationInput(
            database=BootstrapDatabaseCandidate(BootstrapDatabaseKind.SQLITE),
            admin_username=AccountUsername("admin"),
            admin_password=AccountPassword(password),
            source=selected_source,
        )

    async def _counts(self) -> tuple[int, int, int, int]:
        async with self.engine.connect() as connection:
            return (
                await connection.scalar(
                    select(func.count()).select_from(AccountRecord)
                ),
                await connection.scalar(
                    select(func.count()).select_from(
                        RegisteredConfigurationSourceRecord
                    )
                ),
                await connection.scalar(
                    select(func.count()).select_from(InitializationOperationRecord)
                ),
                await connection.scalar(
                    select(func.count()).select_from(AuditEventRecord)
                ),
            )

    async def test_success_commits_admin_encrypted_source_receipt_audit_and_guard(self):
        receipt = await self.transaction.initialize(
            operator_session=_OPERATOR,
            request_key="bootstrap-first-run-1",
            input=self._input(),
        )

        self.assertEqual(receipt.status, BootstrapInitializationStatus.COMPLETED)
        self.assertEqual(await self._counts(), (1, 1, 1, 1))
        async with self.engine.connect() as connection:
            account = (
                await connection.execute(select(AccountRecord.__table__))
            ).mappings().one()
            source = (
                await connection.execute(
                    select(RegisteredConfigurationSourceRecord.__table__)
                )
            ).mappings().one()
            audit = (
                await connection.execute(select(AuditEventRecord.__table__))
            ).mappings().one()
            initialized = await connection.scalar(
                select(ConsoleGuardRecord.initialized).where(
                    ConsoleGuardRecord.singleton_id == 1
                )
            )

        self.assertEqual(account["role_id"], "admin")
        self.assertTrue(account["built_in"])
        self.assertEqual(account["password_hash"], "test-hash:18")
        self.assertNotIn("admin-password-123", repr(dict(account)))
        self.assertNotIn("nacos-secret", repr(dict(source)))
        envelope = EncryptedSecret(
            SecretCipherFormat(source["credential_cipher_format"]),
            source["credential_key_id"],
            source["credential_payload"],
        )
        decoded = self.cipher.decrypt(
            envelope,
            SecretContext(
                "configuration-source", source["source_id"], "authentication"
            ),
        )
        self.assertIn("nacos-secret", decoded)
        self.assertIsNone(audit["actor_account_id"])
        self.assertEqual(audit["action"], "system.bootstrap.initialize")
        self.assertEqual(audit["outcome"], "completed")
        self.assertTrue(initialized)

    async def test_same_operator_and_input_recover_the_same_receipt(self):
        first = await self.transaction.initialize(
            operator_session=_OPERATOR,
            request_key="bootstrap-replay-1",
            input=self._input(),
        )
        recovered = await self.transaction.initialize(
            operator_session=_OPERATOR,
            request_key="bootstrap-replay-1",
            input=self._input(),
        )
        self.assertEqual(first, recovered)
        self.assertEqual(await self._counts(), (1, 1, 1, 1))

    async def test_same_request_key_with_changed_input_conflicts(self):
        await self.transaction.initialize(
            operator_session=_OPERATOR,
            request_key="bootstrap-conflict-1",
            input=self._input(),
        )
        with self.assertRaises(BootstrapInitializationIdempotencyConflict):
            await self.transaction.initialize(
                operator_session=_OPERATOR,
                request_key="bootstrap-conflict-1",
                input=self._input(source_secret="different-secret"),
            )
        self.assertEqual(await self._counts(), (1, 1, 1, 1))

    async def test_hash_failure_rolls_back_all_target_database_changes(self):
        failing = self._transaction(hasher=_PasswordHasher(fail=True))
        with self.assertRaises(BootstrapAuthorityUnavailable):
            await failing.initialize(
                operator_session=_OPERATOR,
                request_key="bootstrap-rollback-1",
                input=self._input(),
            )
        self.assertEqual(await self._counts(), (0, 0, 0, 0))
        async with self.engine.connect() as connection:
            initialized = await connection.scalar(
                select(ConsoleGuardRecord.initialized).where(
                    ConsoleGuardRecord.singleton_id == 1
                )
            )
        self.assertFalse(initialized)

    async def test_initialized_database_rejects_and_records_a_safe_receipt(self):
        async with self.engine.begin() as connection:
            await connection.execute(
                update(ConsoleGuardRecord)
                .where(ConsoleGuardRecord.singleton_id == 1)
                .values(initialized=True)
            )
        receipt = await self.transaction.initialize(
            operator_session=_OPERATOR,
            request_key="bootstrap-closed-1",
            input=self._input(),
        )
        self.assertEqual(receipt.status, BootstrapInitializationStatus.REJECTED)
        self.assertEqual(await self._counts(), (0, 0, 1, 1))

    async def test_credential_reference_is_encrypted_using_registry_envelope(self):
        source = BootstrapSourceCandidate(
            provider=BootstrapSourceProvider.CONSUL,
            endpoint="https://consul.internal:8501",
            location="dc1",
            authentication=SourceCredentialReference("secret://consul/token"),
        )
        receipt = await self.transaction.initialize(
            operator_session=_OPERATOR,
            request_key="bootstrap-reference-1",
            input=self._input(source=source),
        )
        self.assertEqual(receipt.status, BootstrapInitializationStatus.COMPLETED)
        async with self.engine.connect() as connection:
            stored = (
                await connection.execute(
                    select(RegisteredConfigurationSourceRecord.__table__)
                )
            ).mappings().one()
        self.assertEqual(stored["authentication_mode"], "credential-reference")
        envelope = EncryptedSecret(
            SecretCipherFormat(stored["credential_cipher_format"]),
            stored["credential_key_id"],
            stored["credential_payload"],
        )
        plaintext = self.cipher.decrypt(
            envelope,
            SecretContext(
                "configuration-source", stored["source_id"], "authentication"
            ),
        )
        self.assertIn("secret://consul/token", plaintext)
        self.assertNotIn("secret://consul/token", repr(dict(stored)))

if __name__ == "__main__":
    unittest.main()
