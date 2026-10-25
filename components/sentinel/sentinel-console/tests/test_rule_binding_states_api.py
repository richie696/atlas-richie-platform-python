"""HTTP contract tests for the additive API 0.9 binding-state route."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.read_rule_binding_states import (
    ReadRuleBindingStates,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleBinding, RuleKind
from atlas_richie.sentinel_console.domain.rule_catalog import (
    RuleBindingObservedState,
    RuleBindingObservedStateItem,
    RuleBindingStatesPage,
    RuleBindingStatesQuery,
    RuleCatalogCoverage,
    RuleCatalogFreshness,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession

_NOW = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
_COOKIE = "synthetic-session-token-for-binding-states-0001"


class _SessionReader:
    def __init__(self, role: str | None) -> None:
        self.role = role

    async def read_active_session(self, _digest: str):
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _Reader:
    def __init__(self) -> None:
        self.query: RuleBindingStatesQuery | None = None

    async def read_binding_states(self, query: RuleBindingStatesQuery):
        self.query = query
        binding = RuleBinding(
            id="checkout-flow",
            environment_id="prod",
            app_id="checkout",
            kind=RuleKind.FLOW,
            profile="sentinel-python-v1",
            source_id="source-1",
            source_label="Nacos prod",
            location="nacos://ns/DEFAULT_GROUP/flow-rules",
        )
        return RuleBindingStatesPage(
            query=query,
            as_of=_NOW,
            coverage=RuleCatalogCoverage.COMPLETE,
            total=1,
            has_more=False,
            items=(
                RuleBindingObservedStateItem(
                    binding=binding,
                    state=RuleBindingObservedState.CONFIGURED_EMPTY,
                    rule_count=0,
                    source_revision="opaque-rev",
                    last_attempt_at=_NOW,
                    freshness=RuleCatalogFreshness.CURRENT,
                    has_last_known_good=True,
                ),
            ),
        )


class _UnavailableReader:
    async def read_binding_states(self, _query: RuleBindingStatesQuery):
        raise RuntimeError("private database details must not be returned")


class RuleBindingStatesApiTests(unittest.IsolatedAsyncioTestCase):
    def _app(self, role: str | None, reader: _Reader | None):
        return build_app(
            bootstrap_initialization_reader=object(),
            setup_window_reader=object(),
            bootstrap_operator_verifier=object(),
            current_session_reader=_SessionReader(role),
            current_session_revoker=object(),
            account_directory_reader=object(),
            allowed_browser_origins=frozenset({"https://console.example.test"}),
            rule_binding_state_reader=ReadRuleBindingStates(reader) if reader else None,
        )

    async def _client(self, app):
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        client.cookies.set("sentinel_session", _COOKIE)
        return client

    async def test_admin_and_view_can_read_confirmed_empty_binding_state(self) -> None:
        for role in ("admin", "view"):
            reader = _Reader()
            async with await self._client(self._app(role, reader)) as client:
                response = await client.get(
                    "/api/v2/rules/catalog/binding-states?environmentId=prod&appId=checkout&kind=flow&page=1&pageSize=20",
                    headers={"x-request-id": "binding-state-read-1"},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["x-request-id"], "binding-state-read-1")
            assert_openapi_response("readRuleBindingObservedStates", response)
            self.assertEqual(
                reader.query,
                RuleBindingStatesQuery("prod", "checkout", RuleKind.FLOW, 1, 20),
            )
            item = response.json()["items"][0]
            self.assertEqual(item["state"], "configured_empty")
            self.assertEqual(item["ruleCount"], 0)
            self.assertTrue(item["hasLastKnownGood"])

    async def test_unknown_duplicate_or_blank_query_is_rejected(self) -> None:
        app = self._app("view", _Reader())
        async with await self._client(app) as client:
            cases = (
                "environmentId=prod&unexpected=x",
                "environmentId=prod&environmentId=prod",
                "environmentId=prod&appId=",
                "environmentId=prod&page=01",
                "environmentId=prod&pageSize=101",
            )
            for query in cases:
                response = await client.get(
                    f"/api/v2/rules/catalog/binding-states?{query}",
                    headers={"x-request-id": "binding-state-invalid-1"},
                )
                self.assertEqual(response.status_code, 400, query)
                assert_openapi_response("readRuleBindingObservedStates", response)

    async def test_anonymous_reader_is_rejected_and_unavailable_reader_is_503(
        self,
    ) -> None:
        async with await self._client(self._app(None, _Reader())) as client:
            denied = await client.get(
                "/api/v2/rules/catalog/binding-states?environmentId=prod",
                headers={"x-request-id": "binding-state-anonymous"},
            )
        self.assertEqual(denied.status_code, 401)

        async with await self._client(self._app("admin", None)) as client:
            unavailable = await client.get(
                "/api/v2/rules/catalog/binding-states?environmentId=prod",
                headers={"x-request-id": "binding-state-unavailable"},
            )
        self.assertEqual(unavailable.status_code, 503)

        async with await self._client(
            self._app("view", _UnavailableReader())
        ) as client:
            failed_projection = await client.get(
                "/api/v2/rules/catalog/binding-states?environmentId=prod",
                headers={"x-request-id": "binding-state-sql-failure"},
            )
        self.assertEqual(failed_projection.status_code, 503)
        self.assertNotIn("private database", failed_projection.text)
        assert_openapi_response("readRuleBindingObservedStates", failed_projection)


if __name__ == "__main__":
    unittest.main()
