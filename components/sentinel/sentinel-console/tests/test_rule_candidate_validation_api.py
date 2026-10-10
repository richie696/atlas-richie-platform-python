"""Authenticated and exact-candidate validation receipt route tests."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.rule_validation_ports import (
    RuleValidationAuthorityUnavailable,
)
from atlas_richie.sentinel_console.api.rule_candidate_parsing import (
    parse_rule_candidate,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleBinding, RuleKind
from atlas_richie.sentinel_console.domain.rule_candidates import candidate_checksum
from atlas_richie.sentinel_console.domain.rule_snapshots import (
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    FlowStrategy,
    RuleRecord,
    RuleSetSnapshot,
)
from atlas_richie.sentinel_console.domain.rule_validation import (
    RuleCandidateValidationReceipt,
    RuleValidationIssue,
    RuleValidationIssueCode,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from session_test_doubles import UnusedSessionRevoker

_REQUEST_ID = "rule-candidate-validation-1"
_SESSION = "synthetic-session-token-for-candidate-validation-0001"
_CSRF = "synthetic-csrf-token-for-candidate-validation-0001"
_ORIGIN = "https://console.test"
_AS_OF = datetime(2026, 10, 9, 1, 0, 1, 123000, tzinfo=UTC)


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
    def __init__(self, role: str | None, error: Exception | None = None) -> None:
        self.role = role
        self.error = error
        self.calls = 0

    async def read_active_session(self, _session_digest: str):
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _AccountDirectoryReader:
    async def list_accounts(self, _query):
        raise AssertionError("validation must not access the account directory")

    async def read_account(self, _account_id: str):
        raise AssertionError("validation must not access the account directory")


class _SnapshotReader:
    def __init__(self, *, error: Exception | None = None, stale: bool = False) -> None:
        self.error = error
        self.stale = stale
        self.calls: list[str] = []

    async def read_rule_set_snapshot(self, binding_id: str) -> RuleSetSnapshot:
        self.calls.append(binding_id)
        if self.error is not None:
            raise self.error
        return _snapshot(stale=self.stale)


class _ProfileValidator:
    def __init__(self, *, issue: bool = False, error: Exception | None = None) -> None:
        self.issue = issue
        self.error = error
        self.calls: list[tuple[RuleBinding, object]] = []

    def validate_candidate(self, binding: RuleBinding, candidate):
        self.calls.append((binding, candidate))
        if self.error is not None:
            raise self.error
        return (
            (
                RuleValidationIssue(
                    RuleValidationIssueCode.UNSUPPORTED_CAPABILITY,
                    0,
                    "rules[0].clusterConfig",
                ),
            )
            if self.issue
            else ()
        )


class _ReceiptWriter:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = []

    async def record_validation(self, receipt, **metadata) -> None:
        self.calls.append((receipt, metadata))
        if self.error is not None:
            raise self.error


def _snapshot(*, stale: bool = False) -> RuleSetSnapshot:
    binding = RuleBinding(
        "binding-1", "prod", "checkout", RuleKind.FLOW,
        "sentinel-rule-profile-v1", "nacos-main", "Primary Nacos",
        "sentinel/prod/rules",
    )
    rule = FlowRuleValue(
        "POST /api/orders", "default", FlowGrade.QPS, 50,
        FlowStrategy.DIRECT, FlowControlBehavior.REJECT, False,
    )
    return RuleSetSnapshot(
        binding,
        "version-stale" if stale else "version-1",
        "sha256:baseline",
        "revision-1",
        _AS_OF,
        (RuleRecord("rule-1", rule),),
    )


def _candidate() -> dict[str, object]:
    return {
        "bindingId": "binding-1",
        "profile": "sentinel-rule-profile-v1",
        "kind": "flow",
        "baseVersionId": "version-1",
        "baseChecksum": "sha256:baseline",
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
                        "count": 50,
                        "strategy": 0,
                        "controlBehavior": 0,
                        "clusterMode": False,
                    },
                },
            }
        ],
    }


def _app(
    role: str | None,
    validator: _ProfileValidator | None,
    writer: _ReceiptWriter | None = None,
    *,
    session_error: Exception | None = None,
    snapshot_reader: _SnapshotReader | None = None,
):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_SetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=_SessionReader(role, session_error),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_AccountDirectoryReader(),
        allowed_browser_origins=frozenset({_ORIGIN}),
        rule_set_snapshot_reader=snapshot_reader or _SnapshotReader(),
        rule_candidate_profile_validator=validator,
        rule_validation_receipt_writer=writer or _ReceiptWriter(),
    )


class RuleCandidateValidationApiTests(unittest.IsolatedAsyncioTestCase):
    def test_validation_receipt_invariants_and_issue_paths_are_enforced(self):
        issue = RuleValidationIssue(
            RuleValidationIssueCode.VALIDATION,
            0,
            "rules[0].count",
        )
        with self.assertRaises(ValueError):
            RuleCandidateValidationReceipt(
                "binding-1",
                "sentinel-rule-profile-v1",
                "sha256:baseline",
                "sha256:candidate",
                "validation-01",
                True,
                (issue,),
            )
        with self.assertRaises(ValueError):
            RuleValidationIssue(
                RuleValidationIssueCode.VALIDATION,
                0,
                "provider error: password=secret",
            )
        with self.assertRaises(ValueError):
            RuleValidationIssue(
                RuleValidationIssueCode.VALIDATION,
                1_000,
                "rules[1000].count",
            )

    async def _post(
        self,
        role: str | None,
        body: dict[str, object],
        validator: _ProfileValidator | None,
        *,
        headers: dict[str, str] | None = None,
        session_error: Exception | None = None,
        writer: _ReceiptWriter | None = None,
        snapshot_reader: _SnapshotReader | None = None,
    ):
        app = _app(
            role,
            validator,
            writer,
            session_error=session_error,
            snapshot_reader=snapshot_reader,
        )
        request_headers = {
            "x-request-id": _REQUEST_ID,
            "origin": _ORIGIN,
            "x-sentinel-csrf": _CSRF,
        }
        request_headers.update(headers or {})
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url=_ORIGIN,
            cookies={
                "sentinel_session": _SESSION,
                "__Host-sentinel_csrf": _CSRF,
            },
        ) as client:
            return await client.post(
                "/api/v1/rulesets/binding-1/validate",
                json=body,
                headers=request_headers,
            )

    async def test_returns_profile_receipt_bound_to_exact_candidate(self):
        validator = _ProfileValidator()
        writer = _ReceiptWriter()
        response = await self._post("admin", _candidate(), validator, writer=writer)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["bindingId"], "binding-1")
        self.assertEqual(body["profile"], "sentinel-rule-profile-v1")
        self.assertEqual(body["baseChecksum"], "sha256:baseline")
        self.assertEqual(
            body["candidateChecksum"],
            candidate_checksum(parse_rule_candidate(_candidate())),
        )
        self.assertTrue(body["validationId"])
        self.assertTrue(body["isPublishable"])
        self.assertEqual(body["issues"], [])
        self.assertEqual(len(validator.calls), 1)
        self.assertEqual(len(writer.calls), 1)
        self.assertEqual(writer.calls[0][1]["actor_id"], "account-1")
        self.assertEqual(writer.calls[0][1]["request_id"], _REQUEST_ID)
        self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_blank_rule_text_is_rejected_before_profile_validation(self):
        for blank in (" ", "\u0085", "\u001c", "\ufeff"):
            with self.subTest(blank=repr(blank)):
                body = _candidate()
                body["rules"][0]["rule"]["value"]["resource"] = blank
                validator = _ProfileValidator()
                response = await self._post("admin", body, validator)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], "validation_failed")
                self.assertEqual(validator.calls, [])

    async def test_validation_issue_is_a_safe_non_publishable_receipt(self):
        response = await self._post(
            "admin", _candidate(), _ProfileValidator(issue=True)
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["isPublishable"])
        self.assertEqual(
            body["issues"],
            [
                {
                    "code": "unsupported_capability",
                    "recordIndex": 0,
                    "path": "rules[0].clusterConfig",
                }
            ],
        )
        self.assertNotIn("secret", response.text.lower())

    async def test_authentication_permission_and_csrf_gate_precede_authority(self):
        validator = _ProfileValidator()
        for role, headers, status in (
            (None, {}, 401),
            ("view", {}, 403),
            ("admin", {"x-sentinel-csrf": "wrong"}, 403),
        ):
            with self.subTest(role=role, status=status):
                response = await self._post(
                    role, _candidate(), validator, headers=headers
                )
                self.assertEqual(response.status_code, status)
        self.assertEqual(validator.calls, [])

    async def test_unconfigured_and_unavailable_authority_fail_closed(self):
        missing = await self._post("admin", _candidate(), None)
        unavailable = await self._post(
            "admin",
            _candidate(),
            _ProfileValidator(error=RuleValidationAuthorityUnavailable()),
        )
        writer_unavailable = await self._post(
            "admin",
            _candidate(),
            _ProfileValidator(),
            writer=_ReceiptWriter(RuleValidationAuthorityUnavailable()),
        )

        self.assertEqual(missing.status_code, 503)
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(writer_unavailable.status_code, 503)
        self.assertEqual(missing.json()["error"]["code"], "service_unavailable")

    async def test_stale_candidate_conflict_is_not_reported_as_validation_success(self):
        response = await self._post(
            "admin",
            {**_candidate(), "baseVersionId": "version-stale"},
            _ProfileValidator(),
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "conflict")

    async def test_stale_snapshot_conflict_precedes_profile_validation(self):
        validator = _ProfileValidator()
        response = await self._post(
            "admin",
            _candidate(),
            validator,
            snapshot_reader=_SnapshotReader(stale=True),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(validator.calls, [])

    async def test_session_authority_error_fails_before_validation(self):
        validator = _ProfileValidator()
        response = await self._post(
            "admin",
            _candidate(),
            validator,
            session_error=SessionAuthorityUnavailable(),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(validator.calls, [])


if __name__ == "__main__":
    unittest.main()
