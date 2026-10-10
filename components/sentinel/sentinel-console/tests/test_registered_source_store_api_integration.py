"""Focused ASGI-to-SQLite integration for the registered-source user path."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
import unittest

from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.check_registered_source import (
    RegisteredSourceCheckResult,
    SourceCheckCapability,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuthenticationSessionRecord,
    RegisteredConfigurationSourceRecord,
    RegisteredSourceProbeRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    current_session_reader,
    registered_source_store,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_connections_reader import (
    RegisteredSourceSystemConnectionsReader,
)
from session_test_doubles import UnusedSessionRevoker

_SESSION = "registered-source-session-token-0000000000000001"
_CSRF = "registered-source-csrf-token-00000000000000001"
_ORIGIN = "https://console.test"


class _InitializationReader:
    async def is_initialized(self) -> bool:
        return True


class _SetupWindowReader:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, _opaque_session: str | None) -> bool:
        return False


class _AccountDirectoryReader:
    async def list_accounts(self, _query):
        return ()

    async def read_account(self, _account_id: str):
        return None


class _Checker:
    def __init__(self) -> None:
        self.calls = []

    async def check(self, command, actor_id: str):
        self.calls.append((command, actor_id))
        now = datetime.now(UTC)
        return RegisteredSourceCheckResult(
            checked_at=now,
            expires_at=now + timedelta(seconds=30),
            capabilities=(SourceCheckCapability.READ,),
        )


class RegisteredSourceStoreApiIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        now = datetime.now(UTC)
        self.session_digest = hashlib.sha256(_SESSION.encode("ascii")).hexdigest()
        self.csrf_digest = hashlib.sha256(_CSRF.encode("ascii")).hexdigest()
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
                    created_at=now,
                    updated_at=now,
                )
            )
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=self.session_digest,
                    account_id="account-1",
                    session_epoch="epoch-1",
                    csrf_hash=self.csrf_digest,
                    created_at=now,
                    expires_at=now + timedelta(hours=1),
                    revoked_at=None,
                )
            )
        self.source_store = registered_source_store.SqlAlchemyRegisteredSourceStore(
            self.engine,
            secret_cipher=AesGcmSecretCipher("source-v1", {"source-v1": b"k" * 32}),
            fingerprint_keys={"source-fingerprint-v1": b"f" * 32},
            active_fingerprint_key_id="source-fingerprint-v1",
        )
        self.checker = _Checker()
        self.app = build_app(
            bootstrap_initialization_reader=_InitializationReader(),
            setup_window_reader=_SetupWindowReader(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=(
                current_session_reader.SqlAlchemyCurrentSessionReader(self.engine)
            ),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=_AccountDirectoryReader(),
            allowed_browser_origins=frozenset({_ORIGIN}),
            registered_sources_reader=self.source_store,
            system_connections_reader=RegisteredSourceSystemConnectionsReader(
                self.source_store, self.source_store
            ),
            registered_source_checker=self.checker,
            registered_source_credential_resolver=self.source_store,
            registered_source_probe_recorder=self.source_store,
            registered_source_mutation_authority=self.source_store,
        )
        self.client = AsyncClient(
            transport=ASGITransport(app=self.app), base_url=_ORIGIN
        )
        self.cookies = {
            "sentinel_session": _SESSION,
            "__Host-sentinel_csrf": _CSRF,
        }
        self.client.cookies.update(self.cookies)

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        await self.engine.dispose()

    async def test_register_then_read_safe_registry_and_original_receipt(self) -> None:
        registered = await self.client.post(
            "/api/v1/system/sources/commands",
            json={
                "kind": "register",
                "requestKey": "source-full-path-1",
                "name": "Nacos production",
                "source": {
                    "provider": "nacos",
                    "endpoint": "https://nacos.internal:8848",
                    "namespace": "sentinel",
                    "authentication": {
                        "mode": "direct",
                        "username": "operator",
                        "password": "integration-secret-value",
                    },
                },
            },
            headers={
                "origin": _ORIGIN,
                "x-request-id": "source-full-path-command",
                "x-sentinel-csrf": _CSRF,
                "idempotency-key": "source-full-path-1",
            },
        )
        self.assertEqual(registered.status_code, 202)
        self.assertEqual(registered.json()["status"], "completed")
        self.assertNotIn("integration-secret-value", registered.text)
        source_id = registered.json()["record"]["id"]

        registry = await self.client.get(
            "/api/v1/system/sources",
            headers={"x-request-id": "source-full-path-list"},
        )
        self.assertEqual(registry.status_code, 200)
        self.assertEqual([item["id"] for item in registry.json()["items"]], [source_id])
        self.assertTrue(registry.json()["items"][0]["credentialConfigured"])
        self.assertNotIn("integration-secret-value", registry.text)

        checked = await self.client.post(
            "/api/v1/system/sources/check",
            json={
                "sourceId": source_id,
                "expectedRevision": registered.json()["record"]["revision"],
                "source": {
                    "provider": "nacos",
                    "endpoint": "https://nacos-edited.internal:8848",
                    "namespace": "sentinel-next",
                    "authentication": {"mode": "keep"},
                },
            },
            headers={
                "origin": _ORIGIN,
                "x-request-id": "source-full-path-check",
                "x-sentinel-csrf": _CSRF,
            },
        )
        self.assertEqual(checked.status_code, 200)
        checked_command, checked_actor = self.checker.calls[0]
        self.assertEqual(checked_actor, "account-1")
        self.assertEqual(checked_command.endpoint, "https://nacos-edited.internal:8848")
        self.assertEqual(checked_command.location, "sentinel-next")
        self.assertEqual(checked_command.password, "integration-secret-value")
        self.assertNotIn("integration-secret-value", checked.text)

        uncommitted_candidate = await self.client.get(
            "/api/v1/system/connections", headers={"x-request-id": "candidate-probe"}
        )
        self.assertEqual(uncommitted_candidate.status_code, 200)
        self.assertEqual(uncommitted_candidate.json()["items"][0]["state"], "unknown")

        checked_current = await self.client.post(
            "/api/v1/system/sources/check",
            json={
                "sourceId": source_id,
                "expectedRevision": registered.json()["record"]["revision"],
                "source": {
                    "provider": "nacos",
                    "endpoint": "https://nacos.internal:8848",
                    "namespace": "sentinel",
                    "authentication": {"mode": "keep"},
                },
            },
            headers={"origin": _ORIGIN, "x-request-id": "current-probe", "x-sentinel-csrf": _CSRF},
        )
        self.assertEqual(checked_current.status_code, 200)
        async with self.engine.connect() as connection:
            probe_rows = (
                await connection.execute(select(RegisteredSourceProbeRecord.__table__))
            ).mappings().all()
        self.assertEqual(len(probe_rows), 1, repr(probe_rows))
        observed = await self.client.get(
            "/api/v1/system/connections", headers={"x-request-id": "observed-probe"}
        )
        self.assertEqual(observed.status_code, 200, observed.text)
        observation = observed.json()["items"][0]
        self.assertEqual(observation["state"], "available")
        self.assertEqual(observation["capabilities"], ["read"])
        self.assertIsInstance(observation["latencyMs"], float)
        self.assertNotIn("integration-secret-value", observed.text)

        async with self.engine.begin() as connection:
            await connection.execute(
                update(RegisteredConfigurationSourceRecord)
                .where(RegisteredConfigurationSourceRecord.source_id == source_id)
                .values(revision="new-source-revision")
            )
        stale_probe = await self.client.get(
            "/api/v1/system/connections", headers={"x-request-id": "stale-probe"}
        )
        self.assertEqual(stale_probe.json()["items"][0]["state"], "unknown")

        operation = await self.client.get(
            "/api/v1/system/sources/operations/source-full-path-1",
            headers={"x-request-id": "source-full-path-operation"},
        )
        self.assertEqual(operation.status_code, 200)
        self.assertEqual(operation.json(), registered.json())


if __name__ == "__main__":
    unittest.main()
