"""Typed, authenticated and exact-baseline rule-candidate diff tests."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.api.rule_candidate_parsing import (
    InvalidCandidateShape,
    parse_rule_candidate,
)
from atlas_richie.sentinel_console.domain.rule_candidates import candidate_checksum
from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.rule_snapshot_ports import (
    RuleSetSnapshotAuthorityUnavailable,
    RuleSetSnapshotNotFound,
    RuleSetSnapshotRateLimited,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleBinding, RuleKind
from atlas_richie.sentinel_console.domain.rule_snapshots import (
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    FlowStrategy,
    RuleRecord,
    RuleSetSnapshot,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from session_test_doubles import UnusedSessionRevoker

_REQUEST_ID = "rule-candidate-diff-1"
_SESSION = "synthetic-session-token-for-candidate-diff-0001"
_CSRF = "synthetic-csrf-token-for-candidate-diff-0001"
_AS_OF = datetime(2026, 10, 9, 1, 0, 1, 123000, tzinfo=UTC)
_ORIGIN = "https://console.test"


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _SetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _SessionReader:
    def __init__(self, role: str | None, error=None) -> None:
        self.role = role
        self.error = error

    async def read_active_session(self, _session_digest: str):
        if self.error is not None:
            raise self.error
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _AccountDirectoryReader:
    async def list_accounts(self, _query):
        raise AssertionError("candidate diff must not access account data")

    async def read_account(self, _account_id: str):
        raise AssertionError("candidate diff must not access account data")


class _SnapshotReader:
    def __init__(self, error=None) -> None:
        self.error = error
        self.calls: list[str] = []

    async def read_rule_set_snapshot(self, binding_id: str) -> RuleSetSnapshot:
        self.calls.append(binding_id)
        if self.error is not None:
            raise self.error
        return _snapshot()


def _binding() -> RuleBinding:
    return RuleBinding(
        "binding-1",
        "prod",
        "checkout",
        RuleKind.FLOW,
        "sentinel-rule-profile-v1",
        "nacos-main",
        "Primary Nacos",
        "sentinel/prod/rules",
    )


def _flow_rule(count: int = 50) -> FlowRuleValue:
    return FlowRuleValue(
        "POST /api/orders",
        "default",
        FlowGrade.QPS,
        count,
        FlowStrategy.DIRECT,
        FlowControlBehavior.REJECT,
        False,
    )


def _snapshot() -> RuleSetSnapshot:
    return RuleSetSnapshot(
        _binding(),
        "version-1",
        "sha256:baseline",
        "revision-1",
        _AS_OF,
        (RuleRecord("rule-1", _flow_rule()), RuleRecord("rule-2", _flow_rule(70))),
    )


def _candidate(*, base_checksum: str = "sha256:baseline") -> dict[str, object]:
    return {
        "bindingId": "binding-1",
        "profile": "sentinel-rule-profile-v1",
        "kind": "flow",
        "baseVersionId": "version-1",
        "baseChecksum": base_checksum,
        "sourceRevision": "revision-1",
        "rules": [
            {
                "recordId": "rule-1",
                "rule": {
                    "kind": "flow",
                    "value": {
                        "resource": "POST /api/orders",
                        "limitApp": "default",
                        "grade": 1,
                        "count": 60,
                        "strategy": 0,
                        "controlBehavior": 0,
                        "clusterMode": False,
                    },
                },
            },
            {
                "recordId": None,
                "rule": {
                    "kind": "flow",
                    "value": {
                        "resource": "GET /api/orders",
                        "limitApp": "default",
                        "grade": 1,
                        "count": 25,
                        "strategy": 0,
                        "controlBehavior": 0,
                        "clusterMode": False,
                    },
                },
            },
        ],
    }


def _app(role: str | None, *, reader=None, session_error=None):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_SetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=_SessionReader(role, session_error),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_AccountDirectoryReader(),
        allowed_browser_origins=frozenset({_ORIGIN}),
        rule_set_snapshot_reader=reader,
    )


class RuleCandidateDiffApiTests(unittest.IsolatedAsyncioTestCase):
    async def _post(self, role, body, *, reader=None, headers=None, cookies=None):
        app = _app(role, reader=reader)
        request_headers = {
            "x-request-id": _REQUEST_ID,
            "origin": _ORIGIN,
            "x-sentinel-csrf": _CSRF,
        }
        request_headers.update(headers or {})
        request_cookies = {"sentinel_session": _SESSION, "__Host-sentinel_csrf": _CSRF}
        request_cookies.update(cookies or {})
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=_ORIGIN, cookies=request_cookies
        ) as client:
            return await client.post(
                "/api/v1/rulesets/binding-1/diff",
                json=body,
                headers=request_headers,
            )

    async def test_returns_exact_add_remove_replace_diff_without_mutating(self):
        reader = _SnapshotReader()
        response = await self._post("admin", _candidate(), reader=reader)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["bindingId"], "binding-1")
        self.assertEqual(body["baseChecksum"], "sha256:baseline")
        self.assertRegex(body["candidateChecksum"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            [item["operation"] for item in body["changes"]],
            ["replace", "add", "remove"],
        )
        self.assertEqual(body["changes"][0]["recordId"], "rule-1")
        self.assertEqual(body["changes"][0]["before"]["value"]["count"], 50)
        self.assertEqual(body["changes"][0]["after"]["value"]["count"], 60)
        self.assertEqual(
            body["changes"][1]["after"]["value"]["resource"],
            "GET /api/orders",
        )
        self.assertEqual(body["changes"][2]["recordId"], "rule-2")
        self.assertEqual(reader.calls, ["binding-1"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("cookie", response.headers["vary"].lower())

    async def test_stale_base_and_unknown_record_fail_as_conflict(self):
        for field, value in (
            ("baseVersionId", "version-old"),
            ("baseChecksum", "sha256:old"),
            ("sourceRevision", "revision-old"),
        ):
            with self.subTest(field=field):
                stale_candidate = _candidate()
                stale_candidate[field] = value
                stale = await self._post(
                    "admin", stale_candidate, reader=_SnapshotReader()
                )
                self.assertEqual(stale.status_code, 409)
        candidate = _candidate()
        candidate["rules"][0]["recordId"] = "foreign-record"
        unknown = await self._post("admin", candidate, reader=_SnapshotReader())
        self.assertEqual(unknown.status_code, 409)

    async def test_path_binding_mismatch_is_conflict_without_rebinding(self):
        app = _app("admin", reader=_SnapshotReader())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=_ORIGIN,
            cookies={"sentinel_session": _SESSION,
                     "__Host-sentinel_csrf": _CSRF},
        ) as client:
            response = await client.post(
                "/api/v1/rulesets/another-binding/diff",
                json=_candidate(),
                headers={
                    "x-request-id": _REQUEST_ID,
                    "origin": _ORIGIN,
                    "x-sentinel-csrf": _CSRF,
                },
            )
        self.assertEqual(response.status_code, 409)

    async def test_view_and_anonymous_sessions_cannot_compare_candidates(self):
        reader = _SnapshotReader()
        viewer = await self._post("view", _candidate(), reader=reader)
        anonymous = await self._post(None, _candidate(), reader=reader)
        self.assertEqual(viewer.status_code, 403)
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(reader.calls, [])

    async def test_invalid_browser_proof_is_rejected_before_authority_read(self):
        reader = _SnapshotReader()
        missing = await self._post(
            "admin", _candidate(), reader=reader, headers={"x-sentinel-csrf": ""}
        )
        wrong_origin = await self._post(
            "admin",
            _candidate(),
            reader=reader,
            headers={"origin": "https://evil.test"},
        )
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(wrong_origin.status_code, 403)
        self.assertEqual(reader.calls, [])

    async def test_invalid_shape_and_semantics_have_distinct_status(self):
        malformed = _candidate()
        malformed["unexpected"] = True
        shape = await self._post("admin", malformed, reader=_SnapshotReader())
        invalid = _candidate()
        invalid["rules"][0]["rule"]["value"]["count"] = 0
        semantic = await self._post("admin", invalid, reader=_SnapshotReader())
        self.assertEqual(shape.status_code, 400)
        self.assertEqual(semantic.status_code, 422)

    async def test_authority_failures_never_become_empty_success(self):
        for error, expected in (
            (RuleSetSnapshotNotFound(), 404),
            (RuleSetSnapshotRateLimited(500), 429),
            (RuleSetSnapshotAuthorityUnavailable(), 503),
        ):
            with self.subTest(error=type(error).__name__):
                response = await self._post(
                    "admin", _candidate(), reader=_SnapshotReader(error)
                )
                self.assertEqual(response.status_code, expected)

    def test_all_supported_rule_families_parse_as_typed_values(self):
        values = (
            (
                "flow",
                {
                    "resource": "r",
                    "limitApp": "default",
                    "grade": 1,
                    "count": 2,
                    "strategy": 0,
                    "controlBehavior": 0,
                    "clusterMode": False,
                },
            ),
            (
                "degrade",
                {
                    "resource": "r",
                    "grade": 2,
                    "count": 2,
                    "timeWindow": 10,
                    "minRequestAmount": 5,
                    "statIntervalMs": 1000,
                },
            ),
            (
                "system",
                {
                    "highestSystemLoad": 1,
                    "avgRt": -1,
                    "maxThread": -1,
                    "qps": -1,
                    "highestCpuUsage": -1,
                },
            ),
            ("authority", {"resource": "r", "limitApp": "default", "strategy": 0}),
            (
                "param",
                {
                    "resource": "r",
                    "grade": 1,
                    "count": 2,
                    "durationInSec": 1,
                    "paramIdx": 0,
                    "paramFlowItemList": [],
                },
            ),
        )
        for kind, value in values:
            with self.subTest(kind=kind):
                candidate = {
                    "bindingId": "binding-1",
                    "profile": "profile-1",
                    "kind": kind,
                    "baseVersionId": None,
                    "baseChecksum": "sha256:base",
                    "sourceRevision": None,
                    "rules": [
                        {"recordId": None, "rule": {"kind": kind, "value": value}}
                    ],
                }
                parsed = parse_rule_candidate(candidate)
                self.assertEqual(parsed.rules[0].rule.kind.value, kind)

    def test_candidate_parser_rejects_unknown_nested_fields_and_duplicate_ids(self):
        candidate = _candidate()
        candidate["rules"][0]["rule"]["value"]["vendorMagic"] = 1
        with self.assertRaises(InvalidCandidateShape):
            parse_rule_candidate(candidate)
        candidate = _candidate()
        candidate["rules"][1]["recordId"] = "rule-1"
        with self.assertRaises(ValueError):
            parse_rule_candidate(candidate)

    def test_candidate_checksum_is_stable_and_preserves_record_order(self):
        parsed = parse_rule_candidate(_candidate())
        self.assertEqual(candidate_checksum(parsed), candidate_checksum(parsed))
        reversed_candidate = _candidate()
        reversed_candidate["rules"] = list(reversed(reversed_candidate["rules"]))
        self.assertNotEqual(
            candidate_checksum(parsed),
            candidate_checksum(parse_rule_candidate(reversed_candidate)),
        )


if __name__ == "__main__":
    unittest.main()
