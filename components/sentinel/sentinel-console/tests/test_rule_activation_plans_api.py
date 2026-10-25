"""Activation-plan read contract against isolated session and schedule authorities."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.rule_activation_plan_ports import (
    RuleActivationPlanAuthorityUnavailable,
    RuleActivationPlanNotFound,
    RuleActivationPlanRateLimited,
)
from atlas_richie.sentinel_console.domain.rule_activation_plans import (
    RuleActivationPlan,
    RuleActivationPlanCollection,
    RuleActivationPlanState,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession

_HEADERS = {"x-request-id": "rule-activation-plans-read-1"}
_COOKIE = "synthetic-session-token-for-rule-plans-0001"
_AS_OF = datetime(2026, 10, 9, 1, 0, 1, 123000, tzinfo=UTC)


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
    def __init__(self, role: str | None) -> None:
        self.role = role

    async def read_active_session(self, session_digest: str):
        if self.role == "unavailable":
            raise SessionAuthorityUnavailable("private session detail")
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _AccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("plan reads must not query accounts")

    async def read_account(self, account_id: str):
        raise AssertionError("plan reads must not query accounts")


def _plan(
    *,
    plan_id: str = "plan-1",
    binding_id: str = "binding-1",
    state: RuleActivationPlanState = RuleActivationPlanState.PENDING,
    version_id: str = "version-2",
    restore_version_id: str = "version-1",
) -> RuleActivationPlan:
    return RuleActivationPlan(
        id=plan_id,
        revision="revision-1",
        binding_id=binding_id,
        version_id=version_id,
        restore_version_id=restore_version_id,
        activate_at=_AS_OF + timedelta(minutes=5),
        deactivate_at=_AS_OF + timedelta(minutes=10),
        time_zone="Asia/Shanghai",
        state=state,
        activation_publication_id="publication-1",
        restore_publication_id=None,
    )


def _collection(
    *,
    binding_id: str = "binding-1",
    items: tuple[RuleActivationPlan, ...] | None = None,
) -> RuleActivationPlanCollection:
    plans = (_plan(binding_id=binding_id),) if items is None else items
    return RuleActivationPlanCollection(binding_id, _AS_OF, plans)


class _PlanReader:
    def __init__(
        self,
        *,
        error=None,
        collection: RuleActivationPlanCollection | None = None,
    ):
        self.error = error
        self.collection = collection
        self.binding_id: str | None = None
        self.calls = 0

    async def read_rule_activation_plans(
        self, binding_id: str
    ) -> RuleActivationPlanCollection:
        self.binding_id = binding_id
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.collection or _collection(binding_id=binding_id)


def _app(role, *, reader=None, session_reader=None):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_ClosedSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=session_reader or _SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_AccountDirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.test"}),
        rule_activation_plan_reader=reader,
    )


class RuleActivationPlansApiTests(unittest.IsolatedAsyncioTestCase):
    async def _get(
        self, role, *, reader=None, session_reader=None, binding_id="binding-1"
    ):
        app = _app(role, reader=reader, session_reader=session_reader)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE},
        ) as client:
            return await client.get(
                f"/api/v1/rulesets/{binding_id}/plans", headers=_HEADERS
            )

    async def test_admin_and_view_read_exact_persisted_schedule_facts(self):
        for role in ("admin", "view"):
            with self.subTest(role=role):
                reader = _PlanReader(
                    collection=_collection(
                        items=(
                            _plan(state=RuleActivationPlanState.ACTIVE),
                            _plan(
                                plan_id="plan-2",
                                state=RuleActivationPlanState.COMPLETED,
                            ),
                        )
                    )
                )
                response = await self._get(role, reader=reader)
                self.assertEqual(response.status_code, 200)
                assert_openapi_response("readRuleActivationPlans", response)
                self.assertEqual(reader.binding_id, "binding-1")
                body = response.json()
                self.assertEqual(body["asOf"], "2026-10-09T01:00:01.123Z")
                self.assertEqual(
                    body["items"][0]["activateAt"], "2026-10-09T01:05:01.123Z"
                )
                self.assertEqual(body["items"][0]["timeZone"], "Asia/Shanghai")
                self.assertEqual(body["items"][0]["state"], "active")
                self.assertEqual(
                    body["items"][0]["activationPublicationId"], "publication-1"
                )

    async def test_anonymous_invalid_and_unavailable_session_skip_reader(self):
        anonymous_reader = _PlanReader()
        anonymous = await self._get(None, reader=anonymous_reader)
        self.assertEqual(anonymous.status_code, 401)
        assert_openapi_response("readRuleActivationPlans", anonymous)
        self.assertEqual(anonymous_reader.calls, 0)
        invalid_reader = _PlanReader()
        invalid = await self._get("admin", reader=invalid_reader, binding_id=" ")
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid_reader.calls, 0)
        unavailable_reader = _PlanReader()
        unavailable = await self._get(
            "admin",
            reader=unavailable_reader,
            session_reader=_SessionReader("unavailable"),
        )
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable_reader.calls, 0)

    async def test_missing_mismatched_and_authority_errors_fail_closed(self):
        missing = await self._get("admin")
        self.assertEqual(missing.status_code, 503)
        mismatch = await self._get(
            "admin",
            reader=_PlanReader(collection=_collection(binding_id="another-binding")),
        )
        self.assertEqual(mismatch.status_code, 503)
        cases = (
            (RuleActivationPlanNotFound("private binding"), 404, "not_found"),
            (RuleActivationPlanRateLimited(30), 429, "rate_limited"),
            (
                RuleActivationPlanAuthorityUnavailable("private scheduler detail"),
                503,
                "service_unavailable",
            ),
        )
        for error, status, code in cases:
            with self.subTest(code=code):
                response = await self._get("view", reader=_PlanReader(error=error))
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertNotIn("private", response.text)


class RuleActivationPlanDomainTests(unittest.TestCase):
    def test_rejects_bad_window_state_zone_and_publication_identity(self):
        plan = _plan()
        with self.assertRaises(ValueError):
            replace(plan, version_id=plan.restore_version_id)
        with self.assertRaises(ValueError):
            replace(plan, deactivate_at=plan.activate_at)
        with self.assertRaises(ValueError):
            replace(plan, time_zone="not/a-zone")
        with self.assertRaises(ValueError):
            replace(plan, state="invented")
        with self.assertRaises(ValueError):
            replace(plan, activation_publication_id=" ")

    def test_time_zone_uses_the_cross_runtime_nonblank_and_scalar_contract(self):
        plan = _plan()
        for blank in (" ", "\u0085", "\u001c", "\ufeff", "Asia/Shanghai\ud800"):
            with (
                self.subTest(time_zone=repr(blank)),
                self.assertRaises(ValueError),
            ):
                replace(plan, time_zone=blank)

    def test_collection_is_complete_bounded_unique_and_binding_scoped(self):
        plan = _plan()
        with self.assertRaises(ValueError):
            _collection(items=(plan, plan))
        with self.assertRaises(ValueError):
            _collection(items=(_plan(binding_id="another-binding"),))
        with self.assertRaises(ValueError):
            _collection(items=(plan,) * 1_001)
        with self.assertRaises(ValueError):
            replace(
                _collection(),
                as_of=datetime(2026, 10, 9, 1, 0, 1, 123456, tzinfo=UTC),
            )


if __name__ == "__main__":
    unittest.main()
