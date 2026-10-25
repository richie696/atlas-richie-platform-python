"""Authenticated HTTP contract tests for API 0.9 rule-load observations."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response

from atlas_richie.contracts.rules.load_observation.v1 import RuleLoadEventKind
from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.read_rule_load_observations import (
    ReadRuleLoadObservations,
)
from atlas_richie.sentinel_console.application.read_rule_load_observation_history import (
    ReadRuleLoadObservationHistory,
)
from atlas_richie.sentinel_console.domain.rule_load_observation_history import (
    RuleLoadObservationHistoryPage,
    RuleLoadObservationHistoryQuery,
)
from atlas_richie.sentinel_console.domain.rule_catalog import RuleCatalogCoverage
from atlas_richie.sentinel_console.domain.rule_load_observation_query import (
    RuleLoadFreshness,
    RuleLoadObservationItem,
    RuleLoadObservationPage,
    RuleLoadObservationQuery,
    RuleLoadObservationTargets,
    RuleLoadObservedState,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession

_NOW = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
_COOKIE = "synthetic-session-token-for-load-observations-0001"


class _SessionReader:
    def __init__(self, role: str | None) -> None:
        self.role = role

    async def read_active_session(self, _digest: str):
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _Reader:
    def __init__(self) -> None:
        self.query: RuleLoadObservationQuery | None = None

    async def read_rule_load_observations(self, query: RuleLoadObservationQuery):
        self.query = query
        return RuleLoadObservationPage(
            query=query,
            as_of=_NOW,
            coverage=RuleCatalogCoverage.COMPLETE,
            targets=RuleLoadObservationTargets(
                expected=1, observed=1, stale=0, not_observed=0
            ),
            total=1,
            has_more=False,
            items=(
                RuleLoadObservationItem(
                    binding_id="checkout-flow",
                    instance_id="checkout-0",
                    process_id="worker-0",
                    process_epoch="epoch-1",
                    profile_id="unknown-profile",
                    load_state=RuleLoadObservedState.APPLIED,
                    event_kind=RuleLoadEventKind.SNAPSHOT_APPLIED,
                    active_snapshot=None,
                    attempt=None,
                    observed_at=_NOW,
                    received_at=_NOW,
                    freshness=RuleLoadFreshness.CURRENT,
                ),
            ),
        )


class _UnavailableReader:
    async def read_rule_load_observations(self, _query: RuleLoadObservationQuery):
        raise RuntimeError("private database details must not be returned")


class _HistoryReader:
    def __init__(self) -> None:
        self.query: RuleLoadObservationHistoryQuery | None = None

    async def read_rule_load_observation_history(self, query):
        self.query = query
        return RuleLoadObservationHistoryPage(
            query=query,
            as_of=_NOW,
            coverage=RuleCatalogCoverage.COMPLETE,
            total=0,
            has_more=False,
            items=(),
        )


class RuleLoadObservationsApiTests(unittest.IsolatedAsyncioTestCase):
    def _app(self, role: str | None, reader: _Reader | None):
        return build_app(
            bootstrap_initialization_reader=object(),
            setup_window_reader=object(),
            bootstrap_operator_verifier=object(),
            current_session_reader=_SessionReader(role),
            current_session_revoker=object(),
            account_directory_reader=object(),
            allowed_browser_origins=frozenset({"https://console.example.test"}),
            rule_load_observation_reader=(ReadRuleLoadObservations(reader) if reader else None),
        )

    def _history_app(self, role: str | None, reader: _HistoryReader | None):
        return build_app(
            bootstrap_initialization_reader=object(),
            setup_window_reader=object(),
            bootstrap_operator_verifier=object(),
            current_session_reader=_SessionReader(role),
            current_session_revoker=object(),
            account_directory_reader=object(),
            allowed_browser_origins=frozenset({"https://console.example.test"}),
            rule_load_observation_history_reader=(
                ReadRuleLoadObservationHistory(reader) if reader else None
            ),
        )

    async def _client(self, app):
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        client.cookies.set("sentinel_session", _COOKIE)
        return client

    async def test_admin_and_view_read_current_observation_without_claiming_membership(self) -> None:
        for role in ("admin", "view"):
            reader = _Reader()
            async with await self._client(self._app(role, reader)) as client:
                response = await client.get(
                    "/api/v2/rules/load-observations?environmentId=prod&appId=checkout&bindingId=checkout-flow&instanceId=checkout-0&page=1&pageSize=20",
                    headers={"x-request-id": "load-observation-read-1"},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["x-request-id"], "load-observation-read-1")
            assert_openapi_response("readRuleLoadObservations", response)
            self.assertEqual(
                reader.query,
                RuleLoadObservationQuery("prod", "checkout", "checkout-flow", "checkout-0", 1, 20),
            )
            item = response.json()["items"][0]
            self.assertEqual(item["loadState"], "applied")
            self.assertIsNone(item["activeSnapshot"])
            self.assertEqual(response.json()["targets"]["expected"], 1)

    async def test_invalid_duplicate_and_blank_optional_query_is_rejected(self) -> None:
        async with await self._client(self._app("view", _Reader())) as client:
            for query in (
                "environmentId=prod&appId=checkout&unknown=x",
                "environmentId=prod&appId=checkout&appId=checkout",
                "environmentId=prod&appId=checkout&bindingId=",
                "environmentId=prod&appId=checkout&page=01",
                "environmentId=prod&appId=checkout&pageSize=101",
            ):
                response = await client.get(
                    f"/api/v2/rules/load-observations?{query}",
                    headers={"x-request-id": "load-observation-invalid-1"},
                )
                self.assertEqual(response.status_code, 400, query)
                assert_openapi_response("readRuleLoadObservations", response)

    async def test_anonymous_and_unavailable_reads_fail_closed(self) -> None:
        async with await self._client(self._app(None, _Reader())) as client:
            response = await client.get(
                "/api/v2/rules/load-observations?environmentId=prod&appId=checkout",
                headers={"x-request-id": "load-observation-anonymous"},
            )
        self.assertEqual(response.status_code, 401)
        async with await self._client(self._app("admin", None)) as client:
            response = await client.get(
                "/api/v2/rules/load-observations?environmentId=prod&appId=checkout",
                headers={"x-request-id": "load-observation-unavailable"},
            )
        self.assertEqual(response.status_code, 503)
        async with await self._client(self._app("view", _UnavailableReader())) as client:
            failed_projection = await client.get(
                "/api/v2/rules/load-observations?environmentId=prod&appId=checkout",
                headers={"x-request-id": "load-observation-sql-failure"},
            )
        self.assertEqual(failed_projection.status_code, 503)
        self.assertNotIn("private database", failed_projection.text)
        assert_openapi_response("readRuleLoadObservations", failed_projection)

    async def test_history_is_separate_exact_binding_read_for_both_roles(self) -> None:
        for role in ("admin", "view"):
            reader = _HistoryReader()
            async with await self._client(self._history_app(role, reader)) as client:
                response = await client.get(
                    "/api/v2/rules/load-observation-history?environmentId=prod&appId=checkout&bindingId=checkout-flow&page=1&pageSize=20",
                    headers={"x-request-id": "load-history-read-1"},
                )
            self.assertEqual(response.status_code, 200)
            assert_openapi_response("readRuleLoadObservationHistory", response)
            self.assertEqual(
                reader.query,
                RuleLoadObservationHistoryQuery(
                    "prod", "checkout", "checkout-flow", None, 1, 20
                ),
            )
            self.assertEqual(response.json()["total"], 0)
            self.assertEqual(response.json()["items"], [])

    async def test_history_rejects_missing_or_noncanonical_scope_and_anonymous_access(self) -> None:
        async with await self._client(self._history_app("admin", _HistoryReader())) as client:
            for query in (
                "environmentId=prod&appId=checkout",
                "environmentId=prod&appId=checkout&bindingId=checkout-flow&bindingId=checkout-flow",
                "environmentId=prod&appId=checkout&bindingId=checkout-flow&unknown=x",
                "environmentId=prod&appId=checkout&bindingId=checkout-flow&pageSize=101",
            ):
                response = await client.get(
                    f"/api/v2/rules/load-observation-history?{query}",
                    headers={"x-request-id": "load-history-invalid-1"},
                )
                self.assertEqual(response.status_code, 400, query)
                assert_openapi_response("readRuleLoadObservationHistory", response)
        async with await self._client(self._history_app(None, _HistoryReader())) as client:
            anonymous = await client.get(
                "/api/v2/rules/load-observation-history?environmentId=prod&appId=checkout&bindingId=checkout-flow",
                headers={"x-request-id": "load-history-anonymous-1"},
            )
        self.assertEqual(anonymous.status_code, 401)
        assert_openapi_response("readRuleLoadObservationHistory", anonymous)


if __name__ == "__main__":
    unittest.main()
