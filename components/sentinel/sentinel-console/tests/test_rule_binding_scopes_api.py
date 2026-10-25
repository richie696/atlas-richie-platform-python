"""Authenticated Rules scope reads are independent from Metrics V2 observations."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.rule_binding_ports import (
    RuleBindingScopeAuthorityUnavailable,
)
from atlas_richie.sentinel_console.domain.rule_bindings import (
    RuleBindingScopeApplication,
    RuleBindingScopeCatalog,
    RuleBindingScopeEnvironment,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession

_REQUEST_HEADERS = {"x-request-id": "rule-scope-catalog-1"}
_OPAQUE_COOKIE = "synthetic-session-token-for-console-read-0002"


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
            raise SessionAuthorityUnavailable("private session store detail")
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _ScopeReader:
    async def read_rule_binding_scopes(self) -> RuleBindingScopeCatalog:
        return RuleBindingScopeCatalog(
            as_of=datetime(2026, 10, 15, 1, 2, 3, 456789, tzinfo=UTC),
            environments=(RuleBindingScopeEnvironment("prod", "prod"),),
            applications=(RuleBindingScopeApplication("checkout", "prod", "checkout"),),
        )


class _EmptyScopeReader:
    async def read_rule_binding_scopes(self) -> RuleBindingScopeCatalog:
        return RuleBindingScopeCatalog(datetime(2026, 10, 15, tzinfo=UTC), (), ())


class _UnavailableScopeReader:
    async def read_rule_binding_scopes(self) -> RuleBindingScopeCatalog:
        raise RuleBindingScopeAuthorityUnavailable("private SQL failure")


class _UnexpectedScopeReader:
    async def read_rule_binding_scopes(self):
        return {"credentials": "private"}


class RuleBindingScopesApiTest(unittest.IsolatedAsyncioTestCase):
    def _app(self, role: str | None, *, reader=None, session_reader=None):
        return build_app(
            bootstrap_initialization_reader=_Initialized(),
            setup_window_reader=_OpenSetupWindow(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=session_reader or _SessionReader(role),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=object(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            rule_binding_scope_reader=reader,
        )

    async def _get(self, role: str | None, reader=None, *, session_reader=None):
        async with AsyncClient(
            transport=ASGITransport(
                app=self._app(role, reader=reader, session_reader=session_reader)
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            return await client.get(
                "/api/v2/rules/binding-scopes", headers=_REQUEST_HEADERS
            )

    async def test_admin_and_viewer_receive_rule_owned_scopes(self) -> None:
        expected = {
            "asOf": "2026-10-15T01:02:03.456Z",
            "environments": [{"id": "prod", "name": "prod"}],
            "applications": [
                {"id": "checkout", "environmentId": "prod", "name": "checkout"}
            ],
        }
        for role in ("admin", "view"):
            response = await self._get(role, _ScopeReader())
            self.assertEqual(response.status_code, 200)
            assert_openapi_response("readRuleBindingScopes", response)
            self.assertEqual(response.json(), expected)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["vary"], "Cookie")
            self.assertNotIn("credentials", response.text)

    async def test_empty_rule_authority_is_not_an_observation_failure(self) -> None:
        response = await self._get("admin", _EmptyScopeReader())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["environments"], [])
        self.assertEqual(response.json()["applications"], [])

    async def test_anonymous_session_and_missing_authority_fail_closed(self) -> None:
        anonymous = await self._get(None, _ScopeReader())
        missing_authority = await self._get("admin")

        self.assertEqual(anonymous.status_code, 401)
        assert_openapi_response("readRuleBindingScopes", anonymous)
        self.assertEqual(missing_authority.status_code, 503)
        assert_openapi_response("readRuleBindingScopes", missing_authority)
        self.assertEqual(
            missing_authority.json()["error"]["code"], "service_unavailable"
        )

    async def test_authority_and_session_failures_are_sanitized(self) -> None:
        authority_failure = await self._get("admin", _UnavailableScopeReader())
        session_failure = await self._get(
            "admin", _ScopeReader(), session_reader=_SessionReader("unavailable")
        )
        invalid_snapshot = await self._get("admin", _UnexpectedScopeReader())

        for response in (authority_failure, session_failure, invalid_snapshot):
            self.assertEqual(response.status_code, 503)
            assert_openapi_response("readRuleBindingScopes", response)
            self.assertNotIn("private", response.text)


if __name__ == "__main__":
    unittest.main()
