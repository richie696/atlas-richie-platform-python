"""Rule-version HTTP and domain contracts against isolated authorities."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.rule_version_ports import (
    RuleSetVersionAuthorityUnavailable,
    RuleSetVersionNotFound,
    RuleSetVersionRateLimited,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleKind
from atlas_richie.sentinel_console.domain.rule_snapshots import (
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    FlowStrategy,
    RuleRecord,
)
from atlas_richie.sentinel_console.domain.rule_versions import (
    RuleSetVersion,
    RuleSetVersionCollection,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession

_HEADERS = {"x-request-id": "rule-versions-read-1"}
_COOKIE = "synthetic-session-token-for-rule-versions-0001"
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
        raise AssertionError("version reads must not query accounts")

    async def read_account(self, account_id: str):
        raise AssertionError("version reads must not query accounts")


def _version(
    *,
    version_id: str = "version-1",
    binding_id: str = "binding-1",
    kind: RuleKind = RuleKind.FLOW,
    records: tuple[RuleRecord, ...] | None = None,
) -> RuleSetVersion:
    flow = FlowRuleValue(
        resource="POST /api/orders",
        limit_app="default",
        grade=FlowGrade.QPS,
        count=50,
        strategy=FlowStrategy.DIRECT,
        control_behavior=FlowControlBehavior.REJECT,
        cluster_mode=False,
    )
    return RuleSetVersion(
        id=version_id,
        binding_id=binding_id,
        kind=kind,
        profile="sentinel-flow-v1",
        base_version_id="version-0",
        checksum="sha256-version-1",
        name="Baseline",
        note="Reviewed initial release",
        created_at=_AS_OF,
        created_by_id="account-1",
        records=(RuleRecord("rule-1", flow),) if records is None else records,
    )


def _collection(
    *, binding_id: str = "binding-1", items: tuple[RuleSetVersion, ...] | None = None
) -> RuleSetVersionCollection:
    versions = (_version(binding_id=binding_id),) if items is None else items
    return RuleSetVersionCollection(binding_id, _AS_OF, versions)


class _VersionReader:
    def __init__(
        self, *, error=None, collection: RuleSetVersionCollection | None = None
    ):
        self.error = error
        self.collection = collection
        self.binding_id: str | None = None
        self.calls = 0

    async def read_rule_versions(self, binding_id: str) -> RuleSetVersionCollection:
        self.binding_id = binding_id
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.collection or _collection(binding_id=binding_id)


class _VersionDetailReader:
    def __init__(self, *, error=None, version: RuleSetVersion | None = None):
        self.error = error
        self.version = version
        self.binding_id: str | None = None
        self.version_id: str | None = None
        self.calls = 0

    async def read_rule_version(
        self, binding_id: str, version_id: str
    ) -> RuleSetVersion:
        self.binding_id = binding_id
        self.version_id = version_id
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.version or _version(version_id=version_id, binding_id=binding_id)


def _app(
    role: str | None,
    *,
    reader=None,
    detail_reader=None,
    session_reader=None,
):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_ClosedSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=session_reader or _SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_AccountDirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.test"}),
        rule_set_version_reader=reader,
        rule_set_version_detail_reader=detail_reader,
    )


class RuleVersionApiTests(unittest.IsolatedAsyncioTestCase):
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
                f"/api/v1/rulesets/{binding_id}/versions", headers=_HEADERS
            )

    async def _get_detail(
        self,
        role,
        *,
        reader=None,
        session_reader=None,
        binding_id="binding-1",
        version_id="version-1",
    ):
        app = _app(role, detail_reader=reader, session_reader=session_reader)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE},
        ) as client:
            return await client.get(
                f"/api/v1/rulesets/{binding_id}/versions/{version_id}",
                headers=_HEADERS,
            )

    async def test_session_reads_complete_immutable_version_collection(self):
        reader = _VersionReader()
        response = await self._get("view", reader=reader)
        self.assertEqual(response.status_code, 200)
        assert_openapi_response("readRuleVersions", response)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(reader.binding_id, "binding-1")
        body = response.json()
        self.assertEqual(body["bindingId"], "binding-1")
        self.assertEqual(body["asOf"], "2026-10-09T01:00:01.123Z")
        self.assertEqual(body["items"][0]["checksum"], "sha256-version-1")
        self.assertEqual(body["items"][0]["records"][0]["rule"]["kind"], "flow")
        self.assertEqual(body["items"][0]["createdAt"], "2026-10-09T01:00:01.123Z")

    async def test_anonymous_and_invalid_binding_do_not_read_authority(self):
        for role, status in ((None, 401),):
            with self.subTest(role=role):
                reader = _VersionReader()
                response = await self._get(role, reader=reader)
                self.assertEqual(response.status_code, status)
                assert_openapi_response("readRuleVersions", response)
                self.assertEqual(reader.calls, 0)
        reader = _VersionReader()
        invalid = await self._get("admin", reader=reader, binding_id=" ")
        self.assertEqual(invalid.status_code, 400)
        assert_openapi_response("readRuleVersions", invalid)
        self.assertEqual(reader.calls, 0)

    async def test_list_maps_missing_and_authority_failures_without_details(self):
        missing = await self._get("admin")
        self.assertEqual(missing.status_code, 503)
        assert_openapi_response("readRuleVersions", missing)
        cases = (
            (RuleSetVersionNotFound("private binding"), 404, "not_found"),
            (RuleSetVersionRateLimited(30), 429, "rate_limited"),
            (
                RuleSetVersionAuthorityUnavailable("private store detail"),
                503,
                "service_unavailable",
            ),
        )
        for error, status, code in cases:
            with self.subTest(code=code):
                response = await self._get("admin", reader=_VersionReader(error=error))
                self.assertEqual(response.status_code, status)
                assert_openapi_response("readRuleVersions", response)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertNotIn("private", response.text)

    async def test_mismatched_collection_or_unavailable_session_fail_closed(self):
        wrong_binding = await self._get(
            "admin", reader=_VersionReader(collection=_collection(binding_id="other"))
        )
        self.assertEqual(wrong_binding.status_code, 503)
        assert_openapi_response("readRuleVersions", wrong_binding)
        reader = _VersionReader()
        unavailable_session = await self._get(
            "admin", reader=reader, session_reader=_SessionReader("unavailable")
        )
        self.assertEqual(unavailable_session.status_code, 503)
        assert_openapi_response("readRuleVersions", unavailable_session)
        self.assertEqual(reader.calls, 0)

    async def test_session_reads_one_exact_version(self):
        reader = _VersionDetailReader()
        response = await self._get_detail("admin", reader=reader)
        self.assertEqual(response.status_code, 200)
        assert_openapi_response("readRuleVersion", response)
        self.assertEqual(reader.binding_id, "binding-1")
        self.assertEqual(reader.version_id, "version-1")
        self.assertEqual(response.json()["id"], "version-1")
        self.assertEqual(response.json()["bindingId"], "binding-1")
        self.assertEqual(response.json()["name"], "Baseline")

    async def test_detail_rejects_anonymous_invalid_paths_and_mismatched_identity(self):
        anonymous_reader = _VersionDetailReader()
        anonymous = await self._get_detail(None, reader=anonymous_reader)
        self.assertEqual(anonymous.status_code, 401)
        assert_openapi_response("readRuleVersion", anonymous)
        self.assertEqual(anonymous_reader.calls, 0)
        invalid_reader = _VersionDetailReader()
        invalid = await self._get_detail("view", reader=invalid_reader, version_id=" ")
        self.assertEqual(invalid.status_code, 400)
        assert_openapi_response("readRuleVersion", invalid)
        self.assertEqual(invalid_reader.calls, 0)
        wrong_id = await self._get_detail(
            "view", reader=_VersionDetailReader(version=_version(version_id="other"))
        )
        self.assertEqual(wrong_id.status_code, 503)
        assert_openapi_response("readRuleVersion", wrong_id)
        wrong_binding = await self._get_detail(
            "view",
            reader=_VersionDetailReader(
                version=_version(binding_id="other", version_id="version-1")
            ),
        )
        self.assertEqual(wrong_binding.status_code, 503)
        assert_openapi_response("readRuleVersion", wrong_binding)

    async def test_detail_maps_not_found_and_authority_failures(self):
        missing = await self._get_detail("view")
        self.assertEqual(missing.status_code, 503)
        assert_openapi_response("readRuleVersion", missing)
        cases = (
            (RuleSetVersionNotFound("private"), 404, "not_found"),
            (RuleSetVersionRateLimited(30), 429, "rate_limited"),
            (
                RuleSetVersionAuthorityUnavailable("private persistence detail"),
                503,
                "service_unavailable",
            ),
        )
        for error, status, code in cases:
            with self.subTest(code=code):
                response = await self._get_detail(
                    "view", reader=_VersionDetailReader(error=error)
                )
                self.assertEqual(response.status_code, status)
                assert_openapi_response("readRuleVersion", response)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertNotIn("private", response.text)


class RuleVersionDomainTests(unittest.TestCase):
    def test_collection_rejects_duplicate_or_foreign_versions_and_overflow(self):
        version = _version()
        with self.assertRaises(ValueError):
            _collection(items=(version, version))
        with self.assertRaises(ValueError):
            RuleSetVersionCollection("binding-1", _AS_OF, (_version(),) * 1_001)
        with self.assertRaises(ValueError):
            _collection(items=(_version(binding_id="other"),))

    def test_version_rejects_wrong_kind_duplicate_records_and_bad_time(self):
        version = _version()
        with self.assertRaises(ValueError):
            replace(version, kind=RuleKind.DEGRADE)
        with self.assertRaises(ValueError):
            replace(version, records=version.records * 2)
        with self.assertRaises(ValueError):
            instant = datetime(2026, 10, 9, 1, 0, 1, 123456, tzinfo=UTC)
            replace(version, created_at=instant)

    def test_version_name_uses_the_cross_runtime_nonblank_contract(self):
        version = _version()
        for blank in (" ", "\u0085", "\u001c", "\ufeff"):
            with self.subTest(blank=repr(blank)), self.assertRaises(ValueError):
                replace(version, name=blank)


if __name__ == "__main__":
    unittest.main()
