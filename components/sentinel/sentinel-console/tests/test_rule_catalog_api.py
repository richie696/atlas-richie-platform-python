"""Authenticated, strict and sanitized rule catalog API behavior."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.read_rule_catalog import ReadRuleCatalog
from atlas_richie.sentinel_console.domain.rule_bindings import RuleBinding, RuleKind
from atlas_richie.sentinel_console.domain.rule_catalog import (
    RuleCatalogCoverage,
    RuleCatalogEntry,
    RuleCatalogFreshness,
    RuleCatalogPage,
    RuleCatalogQuery,
    RuleCatalogRefreshResult,
)
from atlas_richie.sentinel_console.domain.rule_snapshots import (
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    FlowStrategy,
    RuleRecord,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession

_HEADERS = {"x-request-id": "rule-catalog-api-1"}
_COOKIE = "synthetic-session-token-for-rule-catalog-0001"
_CSRF = "C" * 48
_NOW = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _OpenSetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _SessionReader:
    def __init__(self, role: str | None) -> None:
        self.role = role

    async def read_active_session(self, session_digest: str):
        if self.role == "unavailable":
            raise SessionAuthorityUnavailable("private session detail")
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _Projection:
    def __init__(self, page: RuleCatalogPage | None = None) -> None:
        self.query: RuleCatalogQuery | None = None
        self.calls = 0
        self.page = page

    async def read_catalog(self, query: RuleCatalogQuery) -> RuleCatalogPage:
        self.calls += 1
        self.query = query
        if self.page is not None:
            return self.page
        return RuleCatalogPage(
            query=query,
            as_of=_NOW,
            coverage=RuleCatalogCoverage.COMPLETE,
            bindings_total=0,
            bindings_current=0,
            bindings_stale=0,
            bindings_not_read=0,
            total=0,
            has_more=False,
            items=(),
            issues=(),
        )


class _Refresher:
    def __init__(self) -> None:
        self.scope: tuple[str, str | None] | None = None

    async def execute(self, environment_id: str, app_id: str | None):
        self.scope = (environment_id, app_id)
        return RuleCatalogRefreshResult(
            environment_id=environment_id,
            app_id=app_id,
            as_of=_NOW,
            coverage=RuleCatalogCoverage.COMPLETE,
            bindings_total=0,
            bindings_attempted=0,
            bindings_current=0,
            bindings_stale=0,
            bindings_not_read=0,
        )


class RuleCatalogApiTests(unittest.IsolatedAsyncioTestCase):
    def _app(
        self, role: str | None, projection=None, refresher=None, session_reader=None
    ):
        return build_app(
            bootstrap_initialization_reader=_Initialized(),
            setup_window_reader=_OpenSetupWindow(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=session_reader or _SessionReader(role),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=object(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            rule_catalog_reader=ReadRuleCatalog(projection)
            if projection is not None
            else None,
            rule_catalog_refresher=refresher,
        )

    async def _client(self, app):
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        client.cookies.set("sentinel_session", _COOKIE)
        return client

    async def test_admin_and_view_can_read_rule_facts_without_metrics_scope(
        self,
    ) -> None:
        for role in ("admin", "view"):
            projection = _Projection()
            async with await self._client(
                self._app(role, projection=projection)
            ) as client:
                response = await client.get(
                    "/api/v2/rules/catalog?environmentId=prod&page=1&pageSize=20",
                    headers=_HEADERS,
                )
            self.assertEqual(response.status_code, 200)
            assert_openapi_response("readRuleCatalog", response)
            self.assertEqual(response.json()["coverage"], "complete")
            self.assertEqual(response.json()["total"], 0)
            self.assertEqual(
                projection.query, RuleCatalogQuery("prod", None, None, "", 1, 20)
            )
            self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_serializes_confirmed_provider_rule_facts_through_the_read_route(
        self,
    ) -> None:
        query = RuleCatalogQuery("prod", "checkout", None, "", 1, 20)
        binding = RuleBinding(
            id="checkout-prod-flow",
            environment_id="prod",
            app_id="checkout",
            kind=RuleKind.FLOW,
            profile="sentinel-python-v1",
            source_id="nacos-prod",
            source_label="Production Nacos",
            location="nacos://prod-namespace/DEFAULT_GROUP/flow-rules.json",
        )
        rule = FlowRuleValue(
            resource="POST /checkout",
            limit_app="default",
            grade=FlowGrade.QPS,
            count=17,
            strategy=FlowStrategy.DIRECT,
            control_behavior=FlowControlBehavior.REJECT,
            cluster_mode=False,
        )
        projection = _Projection(
            RuleCatalogPage(
                query=query,
                as_of=_NOW,
                coverage=RuleCatalogCoverage.COMPLETE,
                bindings_total=1,
                bindings_current=1,
                bindings_stale=0,
                bindings_not_read=0,
                total=1,
                has_more=False,
                items=(
                    RuleCatalogEntry(
                        binding=binding,
                        record=RuleRecord("checkout-submit", rule),
                        checksum="provider-checksum-17",
                        source_revision="nacos-revision-17",
                        version_id=None,
                        snapshot_as_of=_NOW,
                        last_attempt_at=_NOW,
                        freshness=RuleCatalogFreshness.CURRENT,
                    ),
                ),
                issues=(),
            )
        )
        async with await self._client(
            self._app("view", projection=projection)
        ) as client:
            response = await client.get(
                "/api/v2/rules/catalog?environmentId=prod&appId=checkout&page=1&pageSize=20",
                headers=_HEADERS,
            )

        self.assertEqual(response.status_code, 200)
        assert_openapi_response("readRuleCatalog", response)
        entry = response.json()["items"][0]
        self.assertEqual(entry["record"]["rule"]["value"]["resource"], "POST /checkout")
        self.assertEqual(entry["record"]["rule"]["value"]["count"], 17)
        self.assertEqual(entry["snapshot"]["checksum"], "provider-checksum-17")
        self.assertEqual(entry["snapshot"]["sourceRevision"], "nacos-revision-17")
        self.assertEqual(entry["binding"]["sourceLabel"], "Production Nacos")
        self.assertEqual(entry["read"]["freshness"], "current")
        self.assertEqual(projection.query, query)
        self.assertNotIn("credentials", response.text.lower())
        self.assertNotIn("certificate", response.text.lower())

    async def test_refresh_requires_browser_csrf_proof_but_is_available_to_viewer(
        self,
    ) -> None:
        refresher = _Refresher()
        app = self._app("view", refresher=refresher)
        async with await self._client(app) as client:
            csrf_response = await client.post(
                "/api/v2/rules/catalog/refresh",
                json={"environmentId": "prod", "appId": "checkout"},
                headers={**_HEADERS, "origin": "https://console.test"},
            )
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            refreshed = await client.post(
                "/api/v2/rules/catalog/refresh",
                json={"environmentId": "prod", "appId": "checkout"},
                headers={
                    **_HEADERS,
                    "x-request-id": "rule-catalog-api-2",
                    "origin": "https://console.test",
                    "x-sentinel-csrf": _CSRF,
                },
            )
        self.assertEqual(csrf_response.status_code, 403)
        assert_openapi_response("refreshRuleCatalog", csrf_response)
        self.assertEqual(refreshed.status_code, 200)
        assert_openapi_response("refreshRuleCatalog", refreshed)
        self.assertEqual(refresher.scope, ("prod", "checkout"))
        self.assertEqual(refreshed.json()["bindings"]["attempted"], 0)

    async def test_anonymous_and_invalid_query_fail_closed(self) -> None:
        projection = _Projection()
        app = self._app(None, projection=projection)
        async with await self._client(app) as client:
            anonymous = await client.get(
                "/api/v2/rules/catalog?environmentId=prod&page=1&pageSize=20",
                headers=_HEADERS,
            )
        invalid = self._app("admin", projection=projection)
        async with await self._client(invalid) as client:
            malformed = await client.get(
                "/api/v2/rules/catalog?environmentId=prod&unknown=1&page=1&pageSize=20",
                headers={**_HEADERS, "x-request-id": "rule-catalog-api-3"},
            )
        self.assertEqual(anonymous.status_code, 401)
        assert_openapi_response("readRuleCatalog", anonymous)
        self.assertEqual(malformed.status_code, 400)
        assert_openapi_response("readRuleCatalog", malformed)
        self.assertEqual(projection.calls, 0)


if __name__ == "__main__":
    unittest.main()
