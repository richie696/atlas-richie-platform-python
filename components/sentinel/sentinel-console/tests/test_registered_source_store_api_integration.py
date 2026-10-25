"""ASGI-to-SQL integration for the registered-source user path."""

from __future__ import annotations

import hashlib
import os
import unittest
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.check_registered_source import (
    RegisteredSourceCheckResult,
    SourceCheckCapability,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    identity_composition,
    login_attempt_configuration,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuthenticationSessionRecord,
    RegisteredConfigurationSourceRecord,
    RegisteredSourceProbeRecord,
    RegisteredSourceDeletionOperationRecord,
    RuleBindingRecord,
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
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    RegisteredSourceTargetRule,
)
from consul_acl_test_support import DisposableConsulAclServer

_SESSION = "registered-source-session-token-0000000000000001"
_CSRF = "registered-source-csrf-token-00000000000000001"
_ORIGIN = "https://console.test"
_DATABASE_URL_ENV = "SENTINEL_CONSOLE_REGISTERED_SOURCE_TEST_URL"
_CONSUL_URL_ENV = "SENTINEL_E2E_CONSUL_URL"
_RUN_CONSUL_ACL_ACCEPTANCE = (
    os.environ.get("SENTINEL_CONSOLE_RUN_CONSUL_ACL_ACCEPTANCE") == "1"
)


def _registered_source_test_database_url() -> str:
    """Allow only an isolated, disposable loopback database for this acceptance."""
    value = os.environ.get(_DATABASE_URL_ENV)
    if value is None:
        return "sqlite+aiosqlite:///:memory:"
    url = make_url(value)
    if (
        url.drivername not in {"mysql+asyncmy", "postgresql+psycopg"}
        or not url.database
        or not url.database.startswith("sentinel_console_test_")
        or url.host not in {"127.0.0.1", "localhost"}
    ):
        raise ValueError(
            f"{_DATABASE_URL_ENV} must target an isolated loopback "
            "sentinel_console_test_* database"
        )
    return value


class _SetupWindowReader:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, _opaque_session: str | None) -> bool:
        return False


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
        self.engine = create_async_engine(_registered_source_test_database_url())
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
        consul_url = os.environ.get(_CONSUL_URL_ENV)
        self.checker = _Checker() if consul_url is None else None
        target_rules: tuple[RegisteredSourceTargetRule, ...] | None = None
        if consul_url is not None:
            parsed_consul_url = urlsplit(consul_url)
            if (
                parsed_consul_url.scheme != "http"
                or parsed_consul_url.hostname != "127.0.0.1"
                or parsed_consul_url.port is None
            ):
                raise ValueError(
                    f"{_CONSUL_URL_ENV} must target a loopback disposable Consul"
                )
            target_rules = (
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.CONSUL,
                    "127.0.0.1",
                    ["127.0.0.1/32"],
                    frozenset({parsed_consul_url.port}),
                ),
            )
        self.app = identity_composition.build_sql_identity_app(
            self.engine,
            attempt_limit=login_attempt_configuration.LoginAttemptLimitConfiguration(
                5, 60, 300
            ),
            account_command_keys=AccountCommandKeyConfiguration(
                "account-v1", {"account-v1": b"a" * 32}
            ),
            client_identity_key=ClientIdentityKeyConfiguration(b"c" * 32),
            session_ttl=timedelta(hours=1),
            setup_window_reader=_SetupWindowReader(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            allowed_browser_origins=frozenset({_ORIGIN}),
            registered_source_keys=RegisteredSourceKeyConfiguration(
                "source-v1",
                {"source-v1": b"k" * 32},
                "source-fingerprint-v1",
                {"source-fingerprint-v1": b"f" * 32},
            ),
            registered_source_checker=self.checker,
            registered_source_target_rules=target_rules,
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
        consul_url = os.environ.get(_CONSUL_URL_ENV)
        if consul_url is None:
            source_payload = {
                "provider": "nacos",
                "endpoint": "https://nacos.internal:8848",
                "namespace": "sentinel",
                "authentication": {
                    "mode": "direct",
                    "username": "operator",
                    "password": "integration-secret-value",
                },
            }
            candidate_payload = {
                "provider": "nacos",
                "endpoint": "https://nacos-edited.internal:8848",
                "namespace": "sentinel-next",
                "authentication": {"mode": "keep"},
            }
            expected_capabilities = ["read"]
        else:
            source_payload = {
                "provider": "consul",
                "endpoint": consul_url,
                "datacenter": "dc1",
                "authentication": {"mode": "none"},
            }
            candidate_payload = source_payload
            expected_capabilities = ["read", "watch"]
        registered = await self.client.post(
            "/api/v1/system/sources/commands",
            json={
                "kind": "register",
                "requestKey": "source-full-path-1",
                "name": "Registered source integration",
                "source": source_payload,
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
        self.assertEqual(
            registry.json()["items"][0]["credentialConfigured"],
            consul_url is None,
        )
        self.assertNotIn("integration-secret-value", registry.text)

        checked = await self.client.post(
            "/api/v1/system/sources/check",
            json={
                "sourceId": source_id,
                "expectedRevision": registered.json()["record"]["revision"],
                "source": {
                    **candidate_payload,
                    "authentication": (
                        {"mode": "keep"}
                        if consul_url is None
                        else {"mode": "none"}
                    ),
                },
            },
            headers={
                "origin": _ORIGIN,
                "x-request-id": "source-full-path-check",
                "x-sentinel-csrf": _CSRF,
            },
        )
        self.assertEqual(checked.status_code, 200)
        if self.checker is not None:
            checked_command, checked_actor = self.checker.calls[0]
            self.assertEqual(checked_actor, "account-1")
            self.assertEqual(
                checked_command.endpoint, "https://nacos-edited.internal:8848"
            )
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
                    **source_payload,
                    "authentication": {"mode": "keep"},
                },
            },
            headers={
                "origin": _ORIGIN,
                "x-request-id": "current-probe",
                "x-sentinel-csrf": _CSRF,
            },
        )
        self.assertEqual(checked_current.status_code, 200)
        async with self.engine.connect() as connection:
            probe_rows = (
                (
                    await connection.execute(
                        select(RegisteredSourceProbeRecord.__table__)
                    )
                )
                .mappings()
                .all()
            )
        self.assertEqual(len(probe_rows), 1, repr(probe_rows))
        observed = await self.client.get(
            "/api/v1/system/connections", headers={"x-request-id": "observed-probe"}
        )
        self.assertEqual(observed.status_code, 200, observed.text)
        observation = observed.json()["items"][0]
        self.assertEqual(observation["state"], "available")
        self.assertEqual(observation["capabilities"], expected_capabilities)
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

    async def test_delete_removes_online_secret_and_returns_safe_durable_receipt(
        self,
    ) -> None:
        secret = "delete-online-secret-must-disappear"
        request_key = "source-delete-http-1"
        registered = await self.client.post(
            "/api/v1/system/sources/commands",
            json={
                "kind": "register",
                "requestKey": "source-delete-register-1",
                "name": "Delete lifecycle source",
                "source": {
                    "provider": "nacos",
                    "endpoint": "https://nacos.internal:8848",
                    "namespace": "sentinel",
                    "authentication": {
                        "mode": "direct",
                        "username": "operator",
                        "password": secret,
                    },
                },
            },
            headers={
                "origin": _ORIGIN,
                "x-request-id": "source-delete-register-request",
                "x-sentinel-csrf": _CSRF,
                "idempotency-key": "source-delete-register-1",
            },
        )
        self.assertEqual(registered.status_code, 202, registered.text)
        record = registered.json()["record"]
        binding_id = "source-delete-protection-binding"
        now = datetime.now(UTC)
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(RegisteredSourceProbeRecord).values(
                    source_id=record["id"],
                    revision=record["revision"],
                    checked_at=now,
                    expires_at=now + timedelta(seconds=30),
                    latency_ms=1.0,
                    capabilities=["read"],
                    reason=None,
                )
            )
            await connection.execute(
                insert(RuleBindingRecord).values(
                    binding_id=binding_id,
                    environment_id="source-delete-protection-environment",
                    app_id="source-delete-protection-app",
                    kind="flow",
                    profile="sentinel-flow-v1",
                    source_id=record["id"],
                    location="namespace",
                    created_at=now,
                    updated_at=now,
                )
            )

        blocked_key = "source-delete-blocked-http-1"
        blocked_headers = {
            "origin": _ORIGIN,
            "x-request-id": "source-delete-blocked-request",
            "x-sentinel-csrf": _CSRF,
            "idempotency-key": blocked_key,
        }
        blocked = await self.client.post(
            "/api/v1/system/sources/commands",
            json={
                "kind": "delete",
                "requestKey": blocked_key,
                "sourceId": record["id"],
                "expectedRevision": record["revision"],
            },
            headers=blocked_headers,
        )
        self.assertEqual(
            blocked.json(),
            {
                "status": "rejected",
                "requestKey": blocked_key,
                "reason": "source_in_use",
            },
        )
        retained = await self.client.get(
            "/api/v1/system/sources", headers={"x-request-id": "source-delete-retained"}
        )
        self.assertEqual([item["id"] for item in retained.json()["items"]], [record["id"]])
        async with self.engine.begin() as connection:
            await connection.execute(
                delete(RuleBindingRecord).where(RuleBindingRecord.binding_id == binding_id)
            )

        delete_body = {
            "kind": "delete",
            "requestKey": request_key,
            "sourceId": record["id"],
            "expectedRevision": record["revision"],
        }
        delete_headers = {
            "origin": _ORIGIN,
            "x-request-id": "source-delete-request",
            "x-sentinel-csrf": _CSRF,
            "idempotency-key": request_key,
        }
        deleted = await self.client.post(
            "/api/v1/system/sources/commands",
            json=delete_body,
            headers=delete_headers,
        )
        replay = await self.client.post(
            "/api/v1/system/sources/commands",
            json=delete_body,
            headers={**delete_headers, "x-request-id": "source-delete-replay"},
        )

        expected = {
            "status": "completed",
            "requestKey": request_key,
            "deletedSourceId": record["id"],
        }
        self.assertEqual(deleted.status_code, 202, deleted.text)
        self.assertEqual(deleted.json(), expected)
        self.assertEqual(replay.json(), expected)
        self.assertNotIn(secret, registered.text + blocked.text + deleted.text + replay.text)
        registry = await self.client.get(
            "/api/v1/system/sources", headers={"x-request-id": "deleted-source-list"}
        )
        self.assertEqual(registry.status_code, 200, registry.text)
        self.assertEqual(registry.json()["items"], [])
        receipt = await self.client.get(
            f"/api/v1/system/sources/operations/{request_key}",
            headers={"x-request-id": "deleted-source-operation"},
        )
        self.assertEqual(receipt.status_code, 200, receipt.text)
        self.assertEqual(receipt.json(), expected)
        self.assertNotIn(secret, receipt.text)

        async with self.engine.connect() as connection:
            sources = (
                await connection.execute(
                    select(RegisteredConfigurationSourceRecord.__table__)
                )
            ).mappings().all()
            deletion_receipts = (
                await connection.execute(
                    select(RegisteredSourceDeletionOperationRecord.__table__)
                )
            ).mappings().all()
            source_probes = (
                await connection.execute(select(RegisteredSourceProbeRecord.__table__))
            ).mappings().all()
        self.assertEqual(sources, [])
        self.assertEqual(source_probes, [])
        self.assertEqual(len(deletion_receipts), 2)
        self.assertTrue(
            any(row["reason"] == "source_in_use" for row in deletion_receipts)
        )
        self.assertTrue(
            any(row["deleted_source_id"] == record["id"] for row in deletion_receipts)
        )
        self.assertNotIn(secret, repr(dict(deletion_receipts[0])))
        self.assertNotIn("nacos.internal", repr(dict(deletion_receipts[0])))

    @unittest.skipUnless(
        _RUN_CONSUL_ACL_ACCEPTANCE,
        "set SENTINEL_CONSOLE_RUN_CONSUL_ACL_ACCEPTANCE=1 for disposable ACL Consul",
    )
    async def test_direct_acl_token_is_encrypted_and_used_by_real_source_check(
        self,
    ) -> None:
        consul = DisposableConsulAclServer("sentinel/acceptance/source-check.json")
        await consul.start()
        try:
            acl_token = consul.create_source_probe_token()
            parsed_endpoint = urlsplit(consul.endpoint)
            self.assertIsNotNone(parsed_endpoint.port)
            self.assertIsNotNone(consul.client_ssl_context)
            target_rule = RegisteredSourceTargetRule.create(
                ConfigurationSourceProvider.CONSUL,
                "127.0.0.1",
                ("127.0.0.1/32",),
                frozenset({parsed_endpoint.port}),
            )
            app = identity_composition.build_sql_identity_app(
                self.engine,
                attempt_limit=(
                    login_attempt_configuration.LoginAttemptLimitConfiguration(
                        5, 60, 300
                    )
                ),
                account_command_keys=AccountCommandKeyConfiguration(
                    "account-v1", {"account-v1": b"a" * 32}
                ),
                client_identity_key=ClientIdentityKeyConfiguration(b"c" * 32),
                session_ttl=timedelta(hours=1),
                setup_window_reader=_SetupWindowReader(),
                bootstrap_operator_verifier=_OperatorVerifier(),
                allowed_browser_origins=frozenset({_ORIGIN}),
                registered_source_keys=RegisteredSourceKeyConfiguration(
                    "source-v1",
                    {"source-v1": b"k" * 32},
                    "source-fingerprint-v1",
                    {"source-fingerprint-v1": b"f" * 32},
                ),
                registered_source_target_rules=(target_rule,),
                registered_source_ssl_context=consul.client_ssl_context,
            )
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url=_ORIGIN,
                cookies=self.cookies,
            ) as client:
                request_key = "consul-acl-source-register-1"
                registered = await client.post(
                    "/api/v1/system/sources/commands",
                    json={
                        "kind": "register",
                        "requestKey": request_key,
                        "name": "Disposable ACL Consul source",
                        "source": {
                            "provider": "consul",
                            "endpoint": consul.endpoint,
                            "datacenter": "dc1",
                            "authentication": {
                                "mode": "direct",
                                "aclToken": acl_token,
                            },
                        },
                    },
                    headers={
                        "origin": _ORIGIN,
                        "x-request-id": "consul-acl-source-register",
                        "x-sentinel-csrf": _CSRF,
                        "idempotency-key": request_key,
                    },
                )
                self.assertEqual(registered.status_code, 202, registered.text)
                self.assertEqual(registered.json().get("status"), "completed")
                self.assertNotIn(acl_token, registered.text)
                source_record = registered.json()["record"]
                source_id = source_record["id"]
                revision = source_record["revision"]

                registry = await client.get(
                    "/api/v1/system/sources",
                    headers={"x-request-id": "consul-acl-source-list"},
                )
                self.assertEqual(registry.status_code, 200, registry.text)
                self.assertNotIn(acl_token, registry.text)
                self.assertEqual(
                    registry.json()["items"][0]["authenticationMode"], "direct"
                )

                before_probe = await client.get(
                    "/api/v1/system/connections",
                    headers={"x-request-id": "consul-acl-source-before-probe"},
                )
                self.assertEqual(before_probe.status_code, 200, before_probe.text)
                matching_before = [
                    item
                    for item in before_probe.json()["items"]
                    if item.get("sourceId") == source_id
                ]
                self.assertEqual(len(matching_before), 1, before_probe.json())
                self.assertEqual(matching_before[0].get("state"), "unknown")

                denied_check = await client.post(
                    "/api/v1/system/sources/check",
                    json={
                        "sourceId": source_id,
                        "expectedRevision": revision,
                        "source": {
                            "provider": "consul",
                            "endpoint": consul.endpoint,
                            "datacenter": "dc1",
                            "authentication": {
                                "mode": "direct",
                                "aclToken": "synthetic-invalid-consul-token",
                            },
                        },
                    },
                    headers={
                        "origin": _ORIGIN,
                        "x-request-id": "consul-acl-source-check-denied",
                        "x-sentinel-csrf": _CSRF,
                    },
                )
                self.assertEqual(denied_check.status_code, 200, denied_check.text)
                self.assertEqual(denied_check.json().get("status"), "unreachable")
                self.assertEqual(denied_check.json().get("reason"), "authentication")
                self.assertNotIn("synthetic-invalid-consul-token", denied_check.text)

                checked = await client.post(
                    "/api/v1/system/sources/check",
                    json={
                        "sourceId": source_id,
                        "expectedRevision": revision,
                        "source": {
                            "provider": "consul",
                            "endpoint": consul.endpoint,
                            "datacenter": "dc1",
                            "authentication": {"mode": "keep"},
                        },
                    },
                    headers={
                        "origin": _ORIGIN,
                        "x-request-id": "consul-acl-source-check",
                        "x-sentinel-csrf": _CSRF,
                    },
                )
                self.assertEqual(checked.status_code, 200, checked.text)
                self.assertEqual(checked.json().get("status"), "reachable")
                self.assertEqual(checked.json().get("capabilities"), ["read", "watch"])
                self.assertNotIn(acl_token, checked.text)
                self.assertTrue(
                    any(token == acl_token for _path, token in consul.observed_requests)
                )
                self.assertTrue(
                    all(
                        acl_token not in path
                        for path, _token in consul.observed_requests
                    )
                )

                after_probe = await client.get(
                    "/api/v1/system/connections",
                    headers={"x-request-id": "consul-acl-source-after-probe"},
                )
                self.assertEqual(after_probe.status_code, 200, after_probe.text)
                matching_after = [
                    item
                    for item in after_probe.json()["items"]
                    if item.get("sourceId") == source_id
                ]
                self.assertEqual(len(matching_after), 1, after_probe.json())
                self.assertEqual(matching_after[0].get("state"), "available")
                self.assertEqual(
                    matching_after[0].get("capabilities"), ["read", "watch"]
                )
                self.assertNotIn(acl_token, after_probe.text)

            async with self.engine.connect() as connection:
                encrypted_payload = await connection.scalar(
                    select(RegisteredConfigurationSourceRecord.credential_payload)
                    .where(
                        RegisteredConfigurationSourceRecord.source_id == source_id
                    )
                )
            self.assertIsInstance(encrypted_payload, bytes)
            self.assertNotIn(acl_token.encode("utf-8"), encrypted_payload)
        finally:
            await consul.close()


if __name__ == "__main__":
    unittest.main()
