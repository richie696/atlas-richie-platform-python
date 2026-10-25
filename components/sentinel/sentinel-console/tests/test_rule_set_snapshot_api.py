"""Complete rule snapshot API contract and typed value validation tests."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.api.rule_snapshot_serializers import (
    rule_set_snapshot_body,
)
from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.rule_snapshot_ports import (
    RuleSetSnapshotAuthorityUnavailable,
    RuleSetSnapshotNotFound,
    RuleSetSnapshotRateLimited,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleBinding, RuleKind
from atlas_richie.sentinel_console.domain.rule_snapshots import (
    AuthorityRuleValue,
    AuthorityStrategy,
    ClusterRuleConfig,
    ClusterThresholdType,
    DegradeGrade,
    DegradeRuleValue,
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    FlowStrategy,
    ParamFlowItemValue,
    ParamFlowRuleValue,
    RuleRecord,
    RuleSetSnapshot,
    SystemRuleValue,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from atlas_richie.sentinel_console.domain.wire_numbers import MAX_SAFE_JSON_INTEGER

_HEADERS = {"x-request-id": "rule-snapshot-read-1"}
_COOKIE = "synthetic-session-token-for-rule-snapshot-0001"
_AS_OF = datetime(2026, 10, 9, 1, 0, 1, 123000, tzinfo=UTC)


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
            raise SessionAuthorityUnavailable("private session authority detail")
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _AccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("rule snapshot reads must not access accounts")

    async def read_account(self, account_id: str):
        raise AssertionError("rule snapshot reads must not access accounts")


def _binding(kind: RuleKind = RuleKind.FLOW, binding_id: str = "binding-1"):
    return RuleBinding(
        id=binding_id,
        environment_id="prod",
        app_id="checkout",
        kind=kind,
        profile="sentinel-rule-profile-v1",
        source_id="nacos-main",
        source_label="Primary Nacos",
        location="sentinel/prod/rules",
    )


def _rule_for(kind: RuleKind):
    if kind is RuleKind.FLOW:
        return FlowRuleValue(
            resource="POST /api/orders",
            limit_app="default",
            grade=FlowGrade.QPS,
            count=50,
            strategy=FlowStrategy.DIRECT,
            control_behavior=FlowControlBehavior.REJECT,
            cluster_mode=True,
            cluster_config=ClusterRuleConfig(
                ClusterThresholdType.GLOBAL, True, 10, 1_000
            ),
        )
    if kind is RuleKind.DEGRADE:
        return DegradeRuleValue(
            "POST /api/orders",
            DegradeGrade.SLOW_REQUEST_RATIO,
            0.5,
            10,
            5,
            1_000,
            0.8,
        )
    if kind is RuleKind.SYSTEM:
        return SystemRuleValue(1.0, -1, -1, -1, -1)
    if kind is RuleKind.AUTHORITY:
        return AuthorityRuleValue(
            "POST /api/orders", "trusted-service,worker", AuthorityStrategy.WHITE_LIST
        )
    if kind is RuleKind.PARAM:
        return ParamFlowRuleValue(
            "POST /api/orders",
            FlowGrade.QPS,
            10,
            1,
            0,
            (ParamFlowItemValue("java.lang.String", "vip", 20),),
        )
    raise AssertionError("unknown test rule kind")


def _snapshot(
    kind: RuleKind = RuleKind.FLOW, binding_id: str = "binding-1"
) -> RuleSetSnapshot:
    return RuleSetSnapshot(
        binding=_binding(kind, binding_id),
        version_id="version-1",
        checksum="sha256-abc",
        source_revision="revision-1",
        as_of=_AS_OF,
        records=(RuleRecord("rule-1", _rule_for(kind)),),
    )


class _RuleSnapshotReader:
    def __init__(self, *, error=None, snapshot: RuleSetSnapshot | None = None) -> None:
        self.error = error
        self.snapshot = snapshot
        self.binding_id: str | None = None
        self.calls = 0

    async def read_rule_set_snapshot(self, binding_id: str) -> RuleSetSnapshot:
        self.binding_id = binding_id
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.snapshot or _snapshot(binding_id=binding_id)


def _app(role: str | None, *, reader=None, session_reader=None):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_OpenSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=session_reader or _SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_AccountDirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.test"}),
        rule_set_snapshot_reader=reader,
    )


class RuleSetSnapshotApiTests(unittest.IsolatedAsyncioTestCase):
    async def _get(
        self, role, binding_id="binding-1", *, reader=None, session_reader=None
    ):
        app = _app(role, reader=reader, session_reader=session_reader)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE},
        ) as client:
            return await client.get(
                f"/api/v1/rulesets/{binding_id}/snapshot", headers=_HEADERS
            )

    async def test_admin_and_view_read_complete_exact_binding_snapshot(self):
        for role in ("admin", "view"):
            with self.subTest(role=role):
                reader = _RuleSnapshotReader()
                response = await self._get(role, reader=reader)
                self.assertEqual(response.status_code, 200)
                assert_openapi_response("readRuleSetSnapshot", response)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(reader.binding_id, "binding-1")
                body = response.json()
                self.assertEqual(body["binding"]["id"], "binding-1")
                self.assertEqual(body["asOf"], "2026-10-09T01:00:01.123Z")
                self.assertEqual(body["records"][0]["rule"]["kind"], "flow")
                self.assertEqual(
                    body["records"][0]["rule"]["value"]["clusterConfig"],
                    {
                        "thresholdType": 1,
                        "fallbackToLocalWhenFail": True,
                        "sampleCount": 10,
                        "windowIntervalMs": 1_000,
                    },
                )
                self.assertNotIn("password", response.text)

    async def test_all_five_rule_families_serialize_with_native_codes(self):
        for kind in RuleKind:
            with self.subTest(kind=kind.value):
                body = rule_set_snapshot_body(_snapshot(kind))
                self.assertEqual(body["binding"]["kind"], kind.value)
                self.assertEqual(body["records"][0]["rule"]["kind"], kind.value)

    async def test_anonymous_session_failure_and_missing_authority_fail_closed(self):
        anonymous_reader = _RuleSnapshotReader()
        anonymous = await self._get(None, reader=anonymous_reader)
        self.assertEqual(anonymous.status_code, 401)
        assert_openapi_response("readRuleSetSnapshot", anonymous)
        self.assertEqual(anonymous_reader.calls, 0)
        unavailable_reader = _RuleSnapshotReader()
        unavailable = await self._get(
            "admin",
            reader=unavailable_reader,
            session_reader=_SessionReader("unavailable"),
        )
        self.assertEqual(unavailable.status_code, 503)
        assert_openapi_response("readRuleSetSnapshot", unavailable)
        self.assertEqual(unavailable_reader.calls, 0)
        missing = await self._get("view")
        self.assertEqual(missing.status_code, 503)
        assert_openapi_response("readRuleSetSnapshot", missing)

    async def test_authority_error_mapping_does_not_leak_private_detail(self):
        cases = (
            (RuleSetSnapshotNotFound("private binding"), 404, "not_found"),
            (RuleSetSnapshotRateLimited(25), 429, "rate_limited"),
            (
                RuleSetSnapshotAuthorityUnavailable("private provider detail"),
                503,
                "service_unavailable",
            ),
        )
        for error, status, code in cases:
            with self.subTest(code=code):
                response = await self._get(
                    "view", reader=_RuleSnapshotReader(error=error)
                )
                self.assertEqual(response.status_code, status)
                assert_openapi_response("readRuleSetSnapshot", response)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertNotIn("private", response.text)

    async def test_wrong_binding_is_not_returned_and_bad_path_id_is_rejected(self):
        wrong = await self._get(
            "admin", reader=_RuleSnapshotReader(snapshot=_snapshot(binding_id="other"))
        )
        self.assertEqual(wrong.status_code, 503)
        assert_openapi_response("readRuleSetSnapshot", wrong)
        invalid_reader = _RuleSnapshotReader()
        invalid = await self._get("admin", " ", reader=invalid_reader)
        self.assertEqual(invalid.status_code, 400)
        assert_openapi_response("readRuleSetSnapshot", invalid)
        self.assertEqual(invalid_reader.calls, 0)


class RuleSnapshotDomainTests(unittest.TestCase):
    def test_snapshot_rejects_wrong_rule_kind_duplicate_ids_and_too_many_records(self):
        with self.assertRaises(ValueError):
            RuleSetSnapshot(
                _binding(RuleKind.FLOW),
                None,
                "checksum",
                None,
                _AS_OF,
                (RuleRecord("rule-1", _rule_for(RuleKind.DEGRADE)),),
            )
        with self.assertRaises(ValueError):
            RuleSetSnapshot(
                _binding(),
                None,
                "checksum",
                None,
                _AS_OF,
                (RuleRecord("rule-1", _rule_for(RuleKind.FLOW)),) * 2,
            )
        with self.assertRaises(ValueError):
            RuleSetSnapshot(
                _binding(),
                None,
                "checksum",
                None,
                _AS_OF,
                tuple(
                    RuleRecord(f"rule-{index}", _rule_for(RuleKind.FLOW))
                    for index in range(1_001)
                ),
            )

    def test_invalid_native_rule_invariants_are_rejected(self):
        with self.assertRaises(ValueError):
            FlowRuleValue(
                "resource",
                "default",
                FlowGrade.THREAD,
                1.5,
                FlowStrategy.DIRECT,
                FlowControlBehavior.REJECT,
                False,
            )
        with self.assertRaises(ValueError):
            ClusterRuleConfig(ClusterThresholdType.GLOBAL, True, 0, 1_000)
        with self.assertRaises(ValueError):
            FlowRuleValue(
                "resource",
                "default",
                FlowGrade.QPS,
                MAX_SAFE_JSON_INTEGER + 1,
                FlowStrategy.DIRECT,
                FlowControlBehavior.REJECT,
                False,
            )
        with self.assertRaises(ValueError):
            SystemRuleValue(0, -1, MAX_SAFE_JSON_INTEGER + 1, -1, -1)
        with self.assertRaises(ValueError):
            AuthorityRuleValue(
                "resource", "caller,caller", AuthorityStrategy.BLACK_LIST
            )

    def test_snapshot_time_must_match_millisecond_wire_precision(self):
        with self.assertRaises(ValueError):
            RuleSetSnapshot(
                _binding(),
                None,
                "checksum",
                None,
                datetime(2026, 10, 9, 1, 0, 1, 123456, tzinfo=UTC),
                (),
            )


if __name__ == "__main__":
    unittest.main()
