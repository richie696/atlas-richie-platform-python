"""Restart acceptance for bootstrap source credentials encrypted under old keys."""

from __future__ import annotations

import unittest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseKind,
)
from atlas_richie.sentinel_console.application.bootstrap_initialization import (
    BootstrapInitializationInput,
    BootstrapInitializationStatus,
)
from atlas_richie.sentinel_console.application.bootstrap_source_check import (
    BootstrapSourceCandidate,
    BootstrapSourceProvider,
    NacosDirectCredentials,
)
from atlas_richie.sentinel_console.application.check_registered_source import (
    RegisteredSourceCredentialsUnavailable,
    SourceCheckAuthenticationMode,
)
from atlas_richie.sentinel_console.domain.account_password import AccountPassword
from atlas_richie.sentinel_console.domain.account_username import AccountUsername
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    RegisteredConfigurationSourceRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    bootstrap_initialization_transaction,
    registered_source_store,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)

_OPERATOR = "synthetic-bootstrap-grant-for-key-rotation"
_OLD_KEY = b"o" * 32
_ACTIVE_KEY = b"n" * 32
_FINGERPRINT_KEY = b"f" * 32
_SOURCE_PASSWORD = "synthetic-nacos-password-never-log"
_ADMIN_PASSWORD = "synthetic-admin-password-never-log"
_bootstrap_tx = bootstrap_initialization_transaction
_source_store = registered_source_store


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return opaque_session == _OPERATOR


class _PasswordHasher:
    def hash_password(self, password: str) -> str:
        return f"test-hash:{len(password)}"


class BootstrapSecretRotationAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_restarted_runtime_resolves_only_owned_bootstrap_secret(self) -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            await upgrade_database(engine)
            initial_cipher = AesGcmSecretCipher("source-v1", {"source-v1": _OLD_KEY})
            transaction = _bootstrap_tx.SqlAlchemyBootstrapInitializationTransaction(
                engine,
                operator_verifier=_OperatorVerifier(),
                password_hasher=_PasswordHasher(),
                source_secret_cipher=initial_cipher,
                idempotency_key=b"i" * 32,
            )
            receipt = await transaction.initialize(
                operator_session=_OPERATOR,
                request_key="bootstrap-key-rotation-acceptance-1",
                input=BootstrapInitializationInput(
                    database=BootstrapDatabaseCandidate(BootstrapDatabaseKind.SQLITE),
                    admin_username=AccountUsername("admin"),
                    admin_password=AccountPassword(_ADMIN_PASSWORD),
                    source=BootstrapSourceCandidate(
                        provider=BootstrapSourceProvider.NACOS,
                        endpoint="https://nacos.synthetic.invalid:8848",
                        location="sentinel",
                        authentication=NacosDirectCredentials(
                            "synthetic-operator", _SOURCE_PASSWORD
                        ),
                    ),
                ),
            )
            self.assertIs(receipt.status, BootstrapInitializationStatus.COMPLETED)

            async with engine.connect() as connection:
                row = (
                    await connection.execute(
                        select(RegisteredConfigurationSourceRecord.__table__)
                    )
                ).mappings().one()

            self.assertEqual(row["credential_key_id"], "source-v1")
            self.assertNotIn(_SOURCE_PASSWORD, repr(dict(row)))
            self.assertNotIn(_ADMIN_PASSWORD, repr(receipt))

            # A fresh cipher/store models service restart after deployment key
            # rotation: key v2 is active while retained key v1 can decrypt the
            # previously persisted credential envelope.
            restarted_store = _source_store.SqlAlchemyRegisteredSourceStore(
                engine,
                secret_cipher=AesGcmSecretCipher(
                    "source-v2", {"source-v2": _ACTIVE_KEY, "source-v1": _OLD_KEY}
                ),
                fingerprint_keys={"source-fingerprint-v1": _FINGERPRINT_KEY},
                active_fingerprint_key_id="source-fingerprint-v1",
            )
            resolved = await restarted_store.resolve_credentials(
                row["source_id"],
                row["revision"],
                ConfigurationSourceProvider.NACOS,
            )

            self.assertIsNotNone(resolved)
            self.assertIs(
                resolved.authentication_mode, SourceCheckAuthenticationMode.DIRECT
            )
            self.assertEqual(resolved.endpoint, "https://nacos.synthetic.invalid:8848")
            self.assertEqual(resolved.location, "sentinel")
            self.assertEqual(resolved.username, "synthetic-operator")
            self.assertEqual(resolved.password, _SOURCE_PASSWORD)
            self.assertIsNone(
                await restarted_store.resolve_credentials(
                    "another-source-id",
                    row["revision"],
                    ConfigurationSourceProvider.NACOS,
                )
            )
            self.assertIsNone(
                await restarted_store.resolve_credentials(
                    row["source_id"],
                    "another-revision",
                    ConfigurationSourceProvider.NACOS,
                )
            )
            self.assertIsNone(
                await restarted_store.resolve_credentials(
                    row["source_id"],
                    row["revision"],
                    ConfigurationSourceProvider.CONSUL,
                )
            )

            without_previous_key = _source_store.SqlAlchemyRegisteredSourceStore(
                engine,
                secret_cipher=AesGcmSecretCipher(
                    "source-v2", {"source-v2": _ACTIVE_KEY}
                ),
                fingerprint_keys={"source-fingerprint-v1": _FINGERPRINT_KEY},
                active_fingerprint_key_id="source-fingerprint-v1",
            )
            with self.assertRaises(RegisteredSourceCredentialsUnavailable):
                await without_previous_key.resolve_credentials(
                    row["source_id"],
                    row["revision"],
                    ConfigurationSourceProvider.NACOS,
                )
        finally:
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
