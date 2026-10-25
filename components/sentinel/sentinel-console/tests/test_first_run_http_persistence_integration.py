"""First-run ASGI command integration through durable setup and SQLite storage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.bootstrap_database_check import (
    BootstrapDatabaseKind,
)
from atlas_richie.sentinel_console.application.runtime_database_locator import (
    RuntimeDatabaseTarget,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_engine import (
    PreparedBootstrapDatabase,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_targets import (
    BootstrapDatabaseTargetPolicy,
    BootstrapDatabaseTargetRule,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    first_run_composition,
)
from atlas_richie.sentinel_console.infrastructure.persistence.bootstrap_authorization_file_authority import (
    BootstrapAuthorizationConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.persistence.database_runtime import (
    ConsoleDatabaseConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.persistence.first_run_composition import (
    FirstRunSqlIdentityConfiguration,
    build_first_run_sql_identity_app,
)
from atlas_richie.sentinel_console.infrastructure.persistence.login_attempt_configuration import (
    LoginAttemptLimitConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    ConsoleGuardRecord,
    InitializationOperationRecord,
    RegisteredConfigurationSourceRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_locator_configuration import (
    RuntimeDatabaseLocatorConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.persistence.setup_window_configuration import (
    SetupWindowConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.security.account_command_keys import (
    AccountCommandKeyConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.security.client_identity_key import (
    ClientIdentityKeyConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.security.registered_source_keys import (
    RegisteredSourceKeyConfiguration,
)

_OPERATOR_CODE = "synthetic-first-run-operator-code-00000001"
_ADMIN_PASSWORD = "Synthetic-Admin-Password-42!"
_DATABASE_PASSWORD = "Synthetic-Database-Password-42!"
_SOURCE_TOKEN = "Synthetic-Consul-ACL-Token-42!"


def _configuration(
    directory: Path, *, sqlite_database_path: Path | None = None
) -> FirstRunSqlIdentityConfiguration:
    return FirstRunSqlIdentityConfiguration(
        setup_window=SetupWindowConfiguration(directory / "setup.json"),
        runtime_locator=RuntimeDatabaseLocatorConfiguration(
            directory / "runtime.json",
            "runtime-active",
            {"runtime-active": b"r" * 32},
        ),
        bootstrap_authorization=BootstrapAuthorizationConfiguration(
            directory / "operator.json", _OPERATOR_CODE, b"o" * 32
        ),
        initialization_lock_path=directory / "initialize.lock",
        database_target_policy=BootstrapDatabaseTargetPolicy(
            [
                BootstrapDatabaseTargetRule.create(
                    BootstrapDatabaseKind.POSTGRESQL,
                    "10.0.0.0/8",
                    frozenset({5432}),
                )
            ]
        ),
        bootstrap_idempotency_key=b"i" * 32,
        login_attempt_limit=LoginAttemptLimitConfiguration(5, 300, 300),
        account_command_keys=AccountCommandKeyConfiguration(
            "account-active", {"account-active": b"a" * 32}
        ),
        client_identity_key=ClientIdentityKeyConfiguration(b"c" * 32),
        registered_source_keys=RegisteredSourceKeyConfiguration(
            "source-active",
            {"source-active": b"s" * 32},
            "fingerprint-active",
            {"fingerprint-active": b"f" * 32},
        ),
        allowed_browser_origins=frozenset({"https://console.test"}),
        sqlite_database_path=sqlite_database_path,
    )


class FirstRunHttpPersistenceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_authorized_initialization_persists_and_closes_setup(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            directory = Path(temporary)
            database_path = directory / "isolated-target.sqlite"
            sqlite_url = f"sqlite+aiosqlite:///{database_path}"
            configuration = _configuration(directory)
            setup_window = configuration.setup_window.create_store()
            await setup_window.set_setup_window_open(True, expected_revision=None)

            async def create_disposable_target(_factory, candidate):
                url = ConsoleDatabaseConfiguration.from_bootstrap_candidate(
                    candidate
                ).secret_url_for_storage()
                return PreparedBootstrapDatabase(
                    engine=create_async_engine(sqlite_url),
                    locator_database_url=url,
                    locator_target=RuntimeDatabaseTarget(
                        candidate.host or "db.internal", ("10.0.0.42",)
                    ),
                )

            def open_disposable_target(_locator, **_tls_options):
                return create_async_engine(sqlite_url)

            with (
                patch.object(
                    first_run_composition.BootstrapDatabaseEngineFactory,
                    "create",
                    create_disposable_target,
                ),
                patch.object(
                    first_run_composition,
                    "create_database_engine_from_locator",
                    open_disposable_target,
                ),
            ):
                app = build_first_run_sql_identity_app(configuration)
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="https://console.test",
                ) as client:
                    before = await client.get(
                        "/api/v1/system/bootstrap",
                        headers={"x-request-id": "first-run-before"},
                    )
                    csrf = before.headers["x-sentinel-csrf"]
                    authorized = await client.post(
                        "/api/v1/system/bootstrap/authorize",
                        json={"operatorCode": _OPERATOR_CODE},
                        headers={
                            "origin": "https://console.test",
                            "x-request-id": "first-run-authorize",
                            "x-sentinel-csrf": csrf,
                        },
                    )
                    self.assertEqual(authorized.status_code, 200, authorized.text)
                    self.assertEqual(authorized.json(), {"authorized": True})
                    assert_openapi_response("authorizeBootstrap", authorized)
                    self.assertNotIn(_OPERATOR_CODE, authorized.text)

                    request_key = "first-run-integration-0001"
                    initialized = await client.post(
                        "/api/v1/system/bootstrap/initialize",
                        json={
                            "requestKey": request_key,
                            "input": {
                                "database": {
                                    "kind": "postgresql",
                                    "host": "db.internal",
                                    "port": 5432,
                                    "database": "sentinel_console",
                                    "username": "console_user",
                                    "password": _DATABASE_PASSWORD,
                                },
                                "admin": {
                                    "username": "synthetic-admin",
                                    "password": _ADMIN_PASSWORD,
                                },
                                "source": {
                                    "provider": "consul",
                                    "endpoint": "https://consul.internal:8501",
                                    "datacenter": "dc1",
                                    "authentication": {
                                        "mode": "direct",
                                        "aclToken": _SOURCE_TOKEN,
                                    },
                                },
                            },
                        },
                        headers={
                            "origin": "https://console.test",
                            "x-request-id": "first-run-initialize",
                            "x-sentinel-csrf": authorized.headers["x-sentinel-csrf"],
                            "idempotency-key": request_key,
                        },
                    )
                    self.assertEqual(initialized.status_code, 200)
                    self.assertEqual(initialized.json()["status"], "completed")
                    self.assertEqual(initialized.json()["requestKey"], request_key)
                    assert_openapi_response("initializeConsole", initialized)
                    for secret in (
                        _OPERATOR_CODE,
                        _ADMIN_PASSWORD,
                        _DATABASE_PASSWORD,
                        _SOURCE_TOKEN,
                    ):
                        self.assertNotIn(secret, initialized.text)

                    gate = await client.get(
                        "/api/v1/system/bootstrap",
                        headers={"x-request-id": "first-run-after"},
                    )
                    session_after_initialization = await client.get(
                        "/api/v1/auth/me",
                        headers={"x-request-id": "first-run-session-after"},
                    )
                    operation = await client.get(
                        f"/api/v1/system/bootstrap/operations/{request_key}",
                        headers={"x-request-id": "first-run-operation"},
                    )
                    repeated_authorize = await client.post(
                        "/api/v1/system/bootstrap/authorize",
                        json={"operatorCode": _OPERATOR_CODE},
                        headers={
                            "origin": "https://console.test",
                            "x-request-id": "first-run-reauthorize",
                            "x-sentinel-csrf": authorized.headers["x-sentinel-csrf"],
                        },
                    )
                    repeated_initialize = await client.post(
                        "/api/v1/system/bootstrap/initialize",
                        json={
                            "requestKey": request_key,
                            "input": {
                                "database": {
                                    "kind": "postgresql",
                                    "host": "db.internal",
                                    "port": 5432,
                                    "database": "sentinel_console",
                                    "username": "console_user",
                                    "password": _DATABASE_PASSWORD,
                                },
                                "admin": {
                                    "username": "synthetic-admin",
                                    "password": _ADMIN_PASSWORD,
                                },
                                "source": {
                                    "provider": "consul",
                                    "endpoint": "https://consul.internal:8501",
                                    "datacenter": "dc1",
                                    "authentication": {
                                        "mode": "direct",
                                        "aclToken": _SOURCE_TOKEN,
                                    },
                                },
                            },
                        },
                        headers={
                            "origin": "https://console.test",
                            "x-request-id": "first-run-repeat-initialize",
                            "x-sentinel-csrf": authorized.headers["x-sentinel-csrf"],
                            "idempotency-key": request_key,
                        },
                    )

                self.assertEqual(before.status_code, 200)
                self.assertEqual(before.json()["initialized"], False)
                assert_openapi_response("readBootstrap", before)
                self.assertEqual(gate.status_code, 200)
                self.assertEqual(gate.json(), {"initialized": True})
                assert_openapi_response("readBootstrap", gate)
                self.assertEqual(session_after_initialization.status_code, 200)
                self.assertIsNone(session_after_initialization.json())
                assert_openapi_response("readSession", session_after_initialization)
                self.assertEqual(operation.status_code, 200)
                self.assertEqual(operation.json(), initialized.json())
                assert_openapi_response("readInitialization", operation)
                self.assertEqual(repeated_authorize.status_code, 409)
                assert_openapi_response("authorizeBootstrap", repeated_authorize)
                self.assertEqual(repeated_initialize.status_code, 403)
                assert_openapi_response("initializeConsole", repeated_initialize)

                locator_bytes = (directory / "runtime.json").read_bytes()
                authority_bytes = (directory / "operator.json").read_bytes()
                self.assertNotIn(_DATABASE_PASSWORD.encode(), locator_bytes)
                self.assertNotIn(_OPERATOR_CODE.encode(), authority_bytes)
                persisted_engine = create_async_engine(sqlite_url)
                try:
                    async with persisted_engine.connect() as connection:
                        initialized_flag = await connection.scalar(
                            select(ConsoleGuardRecord.initialized).where(
                                ConsoleGuardRecord.singleton_id == 1
                            )
                        )
                        account_count = await connection.scalar(
                            select(func.count()).select_from(AccountRecord)
                        )
                        operation_count = await connection.scalar(
                            select(func.count())
                            .select_from(InitializationOperationRecord)
                            .where(
                                InitializationOperationRecord.request_key == request_key
                            )
                        )
                        source_count = await connection.scalar(
                            select(func.count()).select_from(
                                RegisteredConfigurationSourceRecord
                            )
                        )
                        password_hash = await connection.scalar(
                            select(AccountRecord.password_hash).where(
                                AccountRecord.username == "synthetic-admin"
                            )
                        )
                        source_payload = await connection.scalar(
                            select(
                                RegisteredConfigurationSourceRecord.credential_payload
                            )
                        )
                    self.assertIs(initialized_flag, True)
                    self.assertEqual(account_count, 1)
                    self.assertEqual(operation_count, 1)
                    self.assertEqual(source_count, 1)
                    self.assertNotEqual(password_hash, _ADMIN_PASSWORD)
                    self.assertIsNotNone(source_payload)
                    self.assertNotIn(_SOURCE_TOKEN.encode(), source_payload)
                finally:
                    await persisted_engine.dispose()

    async def test_sqlite_first_run_creates_database_and_reopens_from_locator(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            directory = Path(temporary)
            database_path = directory / "deployment-owned-console.sqlite3"
            configuration = _configuration(
                directory, sqlite_database_path=database_path
            )
            setup_window = configuration.setup_window.create_store()
            await setup_window.set_setup_window_open(True, expected_revision=None)
            self.assertFalse(database_path.exists())

            app = build_first_run_sql_identity_app(configuration)
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="https://console.test",
            ) as client:
                bootstrap = await client.get(
                    "/api/v1/system/bootstrap",
                    headers={"x-request-id": "sqlite-setup-bootstrap"},
                )
                csrf = bootstrap.headers["x-sentinel-csrf"]
                authorized = await client.post(
                    "/api/v1/system/bootstrap/authorize",
                    json={"operatorCode": _OPERATOR_CODE},
                    headers={
                        "origin": "https://console.test",
                        "x-request-id": "sqlite-setup-authorize",
                        "x-sentinel-csrf": csrf,
                    },
                )
                self.assertEqual(authorized.status_code, 200, authorized.text)

                request_key = "sqlite-first-run-create-0001"
                initialized = await client.post(
                    "/api/v1/system/bootstrap/initialize",
                    json={
                        "requestKey": request_key,
                        "input": {
                            "database": {"kind": "sqlite"},
                            "admin": {
                                "username": "sqlite-admin",
                                "password": _ADMIN_PASSWORD,
                            },
                            "source": {
                                "provider": "consul",
                                "endpoint": "https://consul.internal:8501",
                                "datacenter": "dc1",
                                "authentication": {
                                    "mode": "direct",
                                    "aclToken": _SOURCE_TOKEN,
                                },
                            },
                        },
                    },
                    headers={
                        "origin": "https://console.test",
                        "x-request-id": "sqlite-setup-initialize",
                        "x-sentinel-csrf": authorized.headers["x-sentinel-csrf"],
                        "idempotency-key": request_key,
                    },
                )

            self.assertEqual(initialized.status_code, 200, initialized.text)
            self.assertEqual(initialized.json()["status"], "completed")
            assert_openapi_response("initializeConsole", initialized)
            self.assertTrue(database_path.is_file())
            self.assertTrue((directory / "runtime.json").is_file())
            locator_bytes = (directory / "runtime.json").read_bytes()
            self.assertNotIn(database_path.as_posix().encode(), locator_bytes)
            self.assertNotIn(_ADMIN_PASSWORD.encode(), locator_bytes)
            self.assertNotIn(_SOURCE_TOKEN.encode(), locator_bytes)

            restarted_app = build_first_run_sql_identity_app(configuration)
            async with AsyncClient(
                transport=ASGITransport(app=restarted_app),
                base_url="https://console.test",
            ) as restarted_client:
                restarted_bootstrap = await restarted_client.get(
                    "/api/v1/system/bootstrap",
                    headers={"x-request-id": "sqlite-setup-restarted"},
                )

            self.assertEqual(restarted_bootstrap.status_code, 200)
            self.assertEqual(restarted_bootstrap.json(), {"initialized": True})
            assert_openapi_response("readBootstrap", restarted_bootstrap)


if __name__ == "__main__":
    unittest.main()
