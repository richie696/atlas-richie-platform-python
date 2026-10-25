"""T05.3 authenticated API + SQL persistence slice on isolated SQLite."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.monitoring_source_registry import (
    MonitoringSourceSecret,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import AccountRecord
from atlas_richie.sentinel_console.infrastructure.persistence.monitoring_source_store import (
    SQLAlchemyMonitoringSourceStore,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)

_COOKIE = "synthetic-monitoring-source-sql-session-0001"
_CSRF = "synthetic-monitoring-source-sql-csrf-token-0001"
_ORIGIN = "https://console.example.test"
_FINGERPRINT_KEY = b"f" * 32
_CIPHER_KEY = b"c" * 32


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _ClosedSetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _SessionReader:
    def __init__(self, role: str = "admin") -> None:
        self.role = role

    async def read_active_session(self, session_digest: str):
        if session_digest != hashlib.sha256(_COOKIE.encode()).hexdigest():
            return None
        return ActiveAccountSession("account-t053", "operator", self.role, "epoch-1")


class _UnusedAccountDirectory:
    async def list_accounts(self, query):
        raise AssertionError("monitoring-source route must not read accounts")

    async def read_account(self, account_id: str):
        raise AssertionError("monitoring-source route must not read accounts")


def _source() -> dict[str, object]:
    return {
        "sourceId": "t053-prometheus-source",
        "revision": "candidate-revision-1",
        "displayName": "Acceptance Prometheus",
        "environmentId": "acceptance",
        "endpoint": "https://prometheus.example.test/api/v1/path-must-not-leak",
        "provider": "prometheus-compatible",
        "profile": "node-exporter-v1",
        "authenticationMode": "direct-bearer",
        "credentialConfigured": True,
        "enabled": True,
        "identityLabels": ["host"],
        "selectorLabels": [{"name": "job", "value": "node-exporter"}],
        "scrapeIntervalSeconds": 15,
        "staleAfterSeconds": 90,
    }


def _app(registry, role: str):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_ClosedSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=_SessionReader(role),
        current_session_revoker=_UnusedAccountDirectory(),
        account_directory_reader=_UnusedAccountDirectory(),
        allowed_browser_origins=frozenset({_ORIGIN}),
        monitoring_source_registry=registry,
        monitoring_fingerprint_key=_FINGERPRINT_KEY,
    )


def _store(engine: AsyncEngine) -> SQLAlchemyMonitoringSourceStore:
    async def resolve_engine() -> AsyncEngine:
        return engine

    return SQLAlchemyMonitoringSourceStore(
        resolve_engine,
        AesGcmSecretCipher("monitoring-v1", {"monitoring-v1": _CIPHER_KEY}),
        fingerprint_key=_FINGERPRINT_KEY,
    )


async def _seed_account(engine: AsyncEngine) -> None:
    now = datetime.now(UTC)
    async with engine.begin() as connection:
        await connection.execute(
            insert(AccountRecord).values(
                account_id="account-t053",
                username="t053-acceptance-admin",
                username_key="a" * 64,
                password_hash="argon2id$synthetic-acceptance-only",
                role_id="admin",
                status="active",
                built_in=False,
                last_login_at=None,
                revision=1,
                created_at=now,
                updated_at=now,
            )
        )


class MonitoringSourcesSqlApiAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_api_persists_and_recovers_redacted_source_across_restart(self):
        temporary = tempfile.TemporaryDirectory(prefix="sentinel-t053-sql-api-")
        self.addCleanup(temporary.cleanup)
        database = Path(temporary.name) / "console.sqlite3"
        database_url = f"sqlite+aiosqlite:///{database}"
        engine = create_async_engine(database_url)
        await upgrade_database(engine)
        await _seed_account(engine)
        store = _store(engine)
        secret = "acceptance-only-bearer-secret-do-not-log"
        request_key = f"t053-create-{uuid4().hex}"
        source = _source()
        create_body = {
            "kind": "create",
            "requestKey": request_key,
            "source": source,
            "credentials": {"bearerToken": secret},
            "credentialUpdate": "replace",
            "checkId": None,
            "skipCheck": True,
        }
        headers = {
            "origin": _ORIGIN,
            "x-sentinel-csrf": _CSRF,
            "idempotency-key": request_key,
        }
        cookies = {
            "sentinel_session": _COOKIE,
            "__Host-sentinel_csrf": _CSRF,
        }

        async with AsyncClient(
            transport=ASGITransport(app=_app(store, "admin")),
            base_url=_ORIGIN,
            cookies=cookies,
        ) as client:
            created = await client.post(
                "/api/v2/monitoring/sources/commands",
                json=create_body,
                headers={**headers, "x-request-id": "t053-sql-create"},
            )
            self.assertEqual(created.status_code, 202, created.text)
            self.assertEqual(created.json()["status"], "completed")
            self.assertFalse(created.json()["verified"])
            source_revision = created.json()["sourceRevision"]

            directory = await client.get(
                "/api/v2/monitoring/sources", headers={"x-request-id": "t053-sql-list"}
            )
            detail = await client.get(
                "/api/v2/monitoring/sources/t053-prometheus-source",
                headers={"x-request-id": "t053-sql-detail"},
            )
            operation = await client.get(
                f"/api/v2/monitoring/sources/operations/{request_key}",
                headers={"x-request-id": "t053-sql-operation"},
            )

        self.assertEqual(directory.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(operation.status_code, 200)
        safe_payloads = " ".join(
            response.text for response in (created, directory, detail, operation)
        )
        self.assertNotIn(secret, safe_payloads)
        self.assertNotIn("path-must-not-leak", safe_payloads)
        self.assertEqual(detail.json()["endpointOrigin"], "https://prometheus.example.test")
        self.assertTrue(directory.json()["items"][0]["credentialConfigured"])

        await engine.dispose()
        restarted_engine = create_async_engine(database_url)
        self.addAsyncCleanup(restarted_engine.dispose)
        restarted_store = _store(restarted_engine)
        async with AsyncClient(
            transport=ASGITransport(app=_app(restarted_store, "admin")),
            base_url=_ORIGIN,
            cookies=cookies,
        ) as restarted_client:
            recovered = await restarted_client.get(
                "/api/v2/monitoring/sources",
                headers={"x-request-id": "t053-sql-restarted-list"},
            )
            replay = await restarted_client.post(
                "/api/v2/monitoring/sources/commands",
                json=create_body,
                headers={**headers, "x-request-id": "t053-sql-create-replay"},
            )
            view_write = AsyncClient(
                transport=ASGITransport(app=_app(restarted_store, "view")),
                base_url=_ORIGIN,
                cookies=cookies,
            )
            try:
                denied = await view_write.post(
                    "/api/v2/monitoring/sources/commands",
                    json={
                        "kind": "set-enabled",
                        "requestKey": f"t053-view-write-{uuid4().hex}",
                        "sourceId": "t053-prometheus-source",
                        "expectedRevision": source_revision,
                        "enabled": False,
                    },
                    headers={
                        **headers,
                        "idempotency-key": "t053-view-write-denied",
                        "x-request-id": "t053-view-write-denied",
                    },
                )
            finally:
                await view_write.aclose()

        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json()["items"][0]["revision"], source_revision)
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay.json()["sourceRevision"], source_revision)
        self.assertEqual(denied.status_code, 403)
        resolved = await restarted_store.resolve_monitoring_source_secret(
            "t053-prometheus-source", expected_revision=source_revision
        )
        self.assertEqual(resolved, MonitoringSourceSecret(bearer_token=secret))


if __name__ == "__main__":
    unittest.main()
