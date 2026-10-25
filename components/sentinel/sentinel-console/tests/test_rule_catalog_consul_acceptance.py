"""Opt-in real Consul -> registered SQL authority -> rule catalog acceptance."""

from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from ipaddress import ip_address
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.refresh_rule_catalog import (
    RefreshRuleCatalog,
)
from atlas_richie.sentinel_console.application.resolve_registered_source_connection import (
    ResolveRegisteredSourceConnection,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_catalog import RuleCatalogQuery
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    RegisteredConfigurationSourceRecord,
    RuleBindingRecord,
    RulePublicationTargetRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.registered_source_store import (
    SqlAlchemyRegisteredSourceStore,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_binding_directory_reader import (
    SqlAlchemyRuleBindingDirectoryReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_catalog_projection import (
    SqlAlchemyRuleCatalogProjection,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_target_mapping import (
    target_body,
    target_location,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_target_reader import (
    SqlAlchemyRulePublicationTargetReader,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)
from atlas_richie.sentinel_console.infrastructure.rule_set_snapshot_reader import (
    create_registered_source_rule_set_snapshot_reader,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)

_CONSUL_URL = os.environ.get("SENTINEL_E2E_CONSUL_URL", "")
_RUN_ACCEPTANCE = os.environ.get("SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE") == "1"
_NOW = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
_INITIAL_RULE = (
    b'[{"resource":"POST /api/orders","limitApp":"default",'
    b'"grade":1,"count":25,"strategy":0,"controlBehavior":0,'
    b'"clusterMode":false}]'
)
_UPDATED_RULE = (
    b'[{"resource":"POST /api/orders","limitApp":"default",'
    b'"grade":1,"count":17,"strategy":0,"controlBehavior":0,'
    b'"clusterMode":false}]'
)


@unittest.skipUnless(
    _RUN_ACCEPTANCE,
    "run through tools/with_disposable_e2e_dependencies.sh for isolated Consul",
)
class ConsulRuleCatalogAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        parsed = urlsplit(_CONSUL_URL)
        if (
            parsed.scheme != "http"
            or parsed.hostname is None
            or not ip_address(parsed.hostname).is_loopback
            or parsed.port is None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            self.fail("acceptance requires the wrapper-owned loopback Consul URL")
        self.endpoint = _CONSUL_URL.rstrip("/")
        self.port = parsed.port
        self.key = f"sentinel/t034/{uuid4().hex}/flow-rules"
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        await self._seed_authority()
        policy = RegisteredSourceTargetPolicy(
            (
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.CONSUL,
                    parsed.hostname,
                    [f"{parsed.hostname}/32"],
                    frozenset({self.port}),
                ),
            )
        )
        self.snapshot_reader = create_registered_source_rule_set_snapshot_reader(
            binding_reader=SqlAlchemyRuleBindingDirectoryReader(self.engine),
            target_reader=SqlAlchemyRulePublicationTargetReader(self.engine),
            connection_resolver=ResolveRegisteredSourceConnection(
                SqlAlchemyRegisteredSourceStore(
                    self.engine,
                    secret_cipher=AesGcmSecretCipher("test-v1", {"test-v1": b"k" * 32}),
                    fingerprint_keys={"test-v1": b"f" * 32},
                    active_fingerprint_key_id="test-v1",
                )
            ),
            target_policies={ConfigurationSourceProvider.CONSUL: policy},
        )
        self.projection = SqlAlchemyRuleCatalogProjection(
            self.engine, clock=lambda: _NOW
        )
        self.refresher = RefreshRuleCatalog(
            self.projection, self.snapshot_reader, clock=lambda: _NOW
        )

    async def asyncTearDown(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                await client.delete(
                    f"{self.endpoint}/v1/kv/{quote(self.key, safe='/')}"
                )
        finally:
            await self.engine.dispose()

    async def test_real_consul_rule_catalog_reads_external_updates_and_keeps_lkg(self):
        async with httpx.AsyncClient(timeout=3) as client:
            initial_write = await client.put(
                f"{self.endpoint}/v1/kv/{quote(self.key, safe='/')}",
                content=_INITIAL_RULE,
            )
            self.assertEqual(initial_write.status_code, 200)
            self.assertEqual(initial_write.json(), True)

            first_refresh = await self.refresher.execute("e2e-live", "t034-app")
            first_page = await self.projection.read_catalog(
                RuleCatalogQuery("e2e-live", "t034-app", None, "", 1, 20)
            )
            self.assertEqual(first_refresh.bindings_current, 1)
            self.assertEqual(first_page.coverage.value, "complete")
            self.assertEqual(first_page.total, 1)
            self.assertEqual(
                first_page.items[0].record.rule.resource, "POST /api/orders"
            )
            self.assertEqual(first_page.items[0].record.rule.count, 25)
            original_checksum = first_page.items[0].checksum
            self.assertTrue(first_page.items[0].source_revision)

            external_write = await client.put(
                f"{self.endpoint}/v1/kv/{quote(self.key, safe='/')}",
                content=_UPDATED_RULE,
            )
            self.assertEqual(external_write.status_code, 200)
            second_refresh = await self.refresher.execute("e2e-live", "t034-app")
            updated_page = await self.projection.read_catalog(
                RuleCatalogQuery("e2e-live", "t034-app", None, "", 1, 20)
            )
            self.assertEqual(second_refresh.bindings_current, 1)
            self.assertEqual(updated_page.items[0].record.rule.count, 17)
            self.assertNotEqual(updated_page.items[0].checksum, original_checksum)

            from support.rule_catalog_page_runner import (
                verify_mounted_rule_catalog_page,
            )

            from httpx import ASGITransport, AsyncClient
            from atlas_richie.sentinel_console.app import build_app
            from atlas_richie.sentinel_console.application.read_rule_binding_states import (
                ReadRuleBindingStates,
            )
            from atlas_richie.sentinel_console.application.read_rule_catalog import (
                ReadRuleCatalog,
            )
            from atlas_richie.sentinel_console.domain.session import (
                ActiveAccountSession,
            )
            from atlas_richie.sentinel_console.infrastructure.persistence.rule_binding_state_reader import (
                SqlAlchemyRuleBindingStateReader,
            )

            class InitializedReader:
                async def is_initialized(self):
                    return True

            class SetupWindowReader:
                async def is_setup_window_open(self):
                    return False

            class OperatorVerifier:
                async def is_current_operator(self, opaque_session):
                    return False

            class AdminSessionReader:
                async def read_active_session(self, session_digest):
                    return ActiveAccountSession(
                        "t034-owner", "t034-owner", "admin", "t034-session-epoch"
                    )

            binding_directory = SqlAlchemyRuleBindingDirectoryReader(self.engine)
            api = build_app(
                bootstrap_initialization_reader=InitializedReader(),
                setup_window_reader=SetupWindowReader(),
                bootstrap_operator_verifier=OperatorVerifier(),
                current_session_reader=AdminSessionReader(),
                current_session_revoker=object(),
                account_directory_reader=object(),
                allowed_browser_origins=frozenset({"http://localhost:5173"}),
                rule_binding_reader=binding_directory,
                rule_binding_scope_reader=binding_directory,
                rule_catalog_reader=ReadRuleCatalog(self.projection),
                rule_catalog_refresher=self.refresher,
                rule_binding_state_reader=ReadRuleBindingStates(
                    SqlAlchemyRuleBindingStateReader(self.engine, clock=lambda: _NOW)
                ),
            )
            await verify_mounted_rule_catalog_page(
                api,
                environment_id="e2e-live",
                app_id="t034-app",
                resource="POST /api/orders",
                source_label="t034-consul",
            )

            invalid_write = await client.put(
                f"{self.endpoint}/v1/kv/{quote(self.key, safe='/')}",
                content=b'{"not":"a rule array"}',
            )
            self.assertEqual(invalid_write.status_code, 200)
            third_refresh = await self.refresher.execute("e2e-live", "t034-app")
            retained_page = await self.projection.read_catalog(
                RuleCatalogQuery("e2e-live", "t034-app", None, "", 1, 20)
            )
            self.assertEqual(third_refresh.bindings_stale, 1)
            self.assertEqual(retained_page.coverage.value, "partial")
            self.assertEqual(retained_page.items[0].record.rule.count, 17)
            self.assertEqual(retained_page.items[0].freshness.value, "stale")
            self.assertEqual(retained_page.issues[0].reason.value, "content_invalid")

            async def read_binding_state() -> dict[str, object]:
                async with AsyncClient(
                    transport=ASGITransport(app=api), base_url="http://console.test"
                ) as console_client:
                    console_client.cookies.set(
                        "sentinel_session", "t034-session-token-0000000000001"
                    )
                    response = await console_client.get(
                        "/api/v2/rules/catalog/binding-states?environmentId=e2e-live&appId=t034-app&kind=flow&page=1&pageSize=20",
                        headers={"x-request-id": "t034-consul-state-read"},
                    )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["total"], 1)
                return response.json()["items"][0]

            invalid_state = await read_binding_state()
            self.assertEqual(invalid_state["state"], "content_invalid")
            self.assertEqual(invalid_state["freshness"], "stale")
            self.assertTrue(invalid_state["hasLastKnownGood"])

            empty_write = await client.put(
                f"{self.endpoint}/v1/kv/{quote(self.key, safe='/')}", content=b"[]"
            )
            self.assertEqual(empty_write.status_code, 200)
            empty_refresh = await self.refresher.execute("e2e-live", "t034-app")
            empty_state = await read_binding_state()
            empty_page = await self.projection.read_catalog(
                RuleCatalogQuery("e2e-live", "t034-app", None, "", 1, 20)
            )
            self.assertEqual(empty_refresh.bindings_current, 1)
            self.assertEqual(empty_page.total, 0)
            self.assertEqual(empty_state["state"], "configured_empty")
            self.assertEqual(empty_state["ruleCount"], 0)
            self.assertEqual(empty_state["freshness"], "current")

            missing_write = await client.delete(
                f"{self.endpoint}/v1/kv/{quote(self.key, safe='/')}"
            )
            self.assertEqual(missing_write.status_code, 200)
            missing_refresh = await self.refresher.execute("e2e-live", "t034-app")
            missing_state = await read_binding_state()
            missing_page = await self.projection.read_catalog(
                RuleCatalogQuery("e2e-live", "t034-app", None, "", 1, 20)
            )
            self.assertEqual(missing_refresh.bindings_stale, 1)
            self.assertEqual(missing_state["state"], "target_missing")
            self.assertEqual(missing_state["freshness"], "stale")
            self.assertTrue(missing_state["hasLastKnownGood"])
            # The frozen 0.8 catalog issue enum cannot grow target_missing;
            # API 0.9 binding-states is the authoritative precise classification.
            self.assertEqual(missing_page.issues[0].reason.value, "not_read")
            self.assertTrue(missing_page.issues[0].stale)

    async def _seed_authority(self) -> None:
        target = ConsulRulePublicationTarget(
            "t034-binding", "t034-source", self.key, "dc1"
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="t034-owner",
                    username="t034-owner",
                    username_key="t" * 64,
                    password_hash="$argon2id$synthetic-hash",
                    role_id="admin",
                    status="active",
                    built_in=True,
                    revision=1,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await connection.execute(
                insert(RegisteredConfigurationSourceRecord).values(
                    source_id=target.source_id,
                    revision="t034-source-r1",
                    name="t034-consul",
                    endpoint=self.endpoint,
                    provider=ConfigurationSourceProvider.CONSUL.value,
                    location="dc1",
                    authentication_mode="none",
                    credential_configured=False,
                    credential_cipher_format=None,
                    credential_key_id=None,
                    credential_payload=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                    updated_by_account_id="t034-owner",
                )
            )
            await connection.execute(
                insert(RuleBindingRecord).values(
                    binding_id=target.binding_id,
                    environment_id="e2e-live",
                    app_id="t034-app",
                    kind="flow",
                    profile="sentinel-python-v1",
                    source_id=target.source_id,
                    location=target_location(target),
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await connection.execute(
                insert(RulePublicationTargetRecord).values(
                    binding_id=target.binding_id,
                    source_id=target.source_id,
                    target_revision="t034-target-r1",
                    source_revision="t034-source-r1",
                    target_body=target_body(target),
                    updated_at=_NOW,
                )
            )


if __name__ == "__main__":
    unittest.main()
