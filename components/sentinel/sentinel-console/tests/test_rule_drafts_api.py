"""Rule draft collection API contract against isolated authorities."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import unittest

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.rule_draft_detail_ports import (
    RuleDraftDetailAuthorityUnavailable,
    RuleDraftDetailNotFound,
    RuleDraftDetailRateLimited,
)
from atlas_richie.sentinel_console.application.rule_draft_ports import (
    RuleDraftAuthorityUnavailable,
    RuleDraftNotFound,
    RuleDraftRateLimited,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleKind
from atlas_richie.sentinel_console.domain.rule_drafts import (
    RuleDraftCollection,
    StoredRuleDraft,
)
from atlas_richie.sentinel_console.domain.rule_snapshots import (
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    FlowStrategy,
    RuleRecord,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from session_test_doubles import UnusedSessionRevoker

_HEADERS = {"x-request-id": "rule-drafts-read-1"}
_COOKIE = "synthetic-session-token-for-rule-drafts-0001"
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
        raise AssertionError("rule draft reads must not access accounts")

    async def read_account(self, account_id: str):
        raise AssertionError("rule draft reads must not access accounts")


def _rule_draft(draft_id: str = "draft-1") -> StoredRuleDraft:
    rule = FlowRuleValue(
        resource="POST /api/orders",
        limit_app="default",
        grade=FlowGrade.QPS,
        count=50,
        strategy=FlowStrategy.DIRECT,
        control_behavior=FlowControlBehavior.REJECT,
        cluster_mode=False,
    )
    return StoredRuleDraft(
        id=draft_id,
        binding_id="binding-1",
        revision="draft-revision-2",
        kind=RuleKind.FLOW,
        profile="sentinel-flow-v1",
        base_version_id="version-1",
        base_checksum="sha256-base",
        source_revision="source-revision-1",
        updated_at=_AS_OF,
        records=(RuleRecord("rule-1", rule),),
    )


def _collection(
    *, binding_id: str = "binding-1", items: tuple[StoredRuleDraft, ...] | None = None
) -> RuleDraftCollection:
    return RuleDraftCollection(
        binding_id, _AS_OF, (_rule_draft(),) if items is None else items
    )


class _RuleDraftReader:
    def __init__(self, *, error=None, collection: RuleDraftCollection | None = None):
        self.error = error
        self.collection = collection
        self.binding_id: str | None = None
        self.calls = 0

    async def read_rule_drafts(self, binding_id: str) -> RuleDraftCollection:
        self.binding_id = binding_id
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.collection or _collection(binding_id=binding_id)


class _RuleDraftDetailReader:
    def __init__(self, *, error=None, draft: StoredRuleDraft | None = None):
        self.error = error
        self.draft = draft
        self.binding_id: str | None = None
        self.draft_id: str | None = None
        self.calls = 0

    async def read_rule_draft(self, binding_id: str, draft_id: str):
        self.binding_id = binding_id
        self.draft_id = draft_id
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.draft or _rule_draft(draft_id)


def _app(
    role: str | None, *, reader=None, detail_reader=None, session_reader=None
):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_OpenSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=session_reader or _SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_AccountDirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.test"}),
        rule_draft_reader=reader,
        rule_draft_detail_reader=detail_reader,
    )


class RuleDraftApiTests(unittest.IsolatedAsyncioTestCase):
    async def _get(
        self,
        role,
        *,
        reader=None,
        session_reader=None,
        binding_id="binding-1",
    ):
        app = _app(role, reader=reader, session_reader=session_reader)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE},
        ) as client:
            return await client.get(
                f"/api/v1/rulesets/{binding_id}/drafts", headers=_HEADERS
            )

    async def _get_detail(
        self,
        role,
        *,
        reader=None,
        session_reader=None,
        binding_id="binding-1",
        draft_id="draft-1",
    ):
        app = _app(role, detail_reader=reader, session_reader=session_reader)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE},
        ) as client:
            return await client.get(
                f"/api/v1/rulesets/{binding_id}/drafts/{draft_id}",
                headers=_HEADERS,
            )

    async def test_admin_reads_complete_binding_scoped_drafts(self):
        reader = _RuleDraftReader()
        response = await self._get("admin", reader=reader)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(reader.binding_id, "binding-1")
        body = response.json()
        self.assertEqual(body["bindingId"], "binding-1")
        self.assertEqual(body["asOf"], "2026-10-09T01:00:01.123Z")
        self.assertEqual(body["items"][0]["revision"], "draft-revision-2")
        self.assertEqual(body["items"][0]["records"][0]["rule"]["kind"], "flow")
        self.assertNotIn("credential", response.text)

    async def test_view_and_anonymous_are_rejected_before_authority_read(self):
        for role, status in (("view", 403), (None, 401)):
            with self.subTest(role=role):
                reader = _RuleDraftReader()
                response = await self._get(role, reader=reader)
                self.assertEqual(response.status_code, status)
                self.assertEqual(reader.calls, 0)

    async def test_invalid_binding_and_session_failure_do_not_read_drafts(self):
        reader = _RuleDraftReader()
        invalid = await self._get("admin", reader=reader, binding_id=" ")
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(reader.calls, 0)
        unavailable_reader = _RuleDraftReader()
        unavailable = await self._get(
            "admin",
            reader=unavailable_reader,
            session_reader=_SessionReader("unavailable"),
        )
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable_reader.calls, 0)

    async def test_missing_and_failed_authorities_map_to_stable_responses(self):
        missing = await self._get("admin")
        self.assertEqual(missing.status_code, 503)
        cases = (
            (RuleDraftNotFound("private binding"), 404, "not_found"),
            (RuleDraftRateLimited(25), 429, "rate_limited"),
            (
                RuleDraftAuthorityUnavailable("private persistence detail"),
                503,
                "service_unavailable",
            ),
        )
        for error, status, code in cases:
            with self.subTest(code=code):
                response = await self._get(
                    "admin", reader=_RuleDraftReader(error=error)
                )
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertNotIn("private", response.text)

    async def test_mismatched_collection_fails_closed(self):
        response = await self._get(
            "admin",
            reader=_RuleDraftReader(
                collection=_collection(binding_id="other", items=())
            ),
        )
        self.assertEqual(response.status_code, 503)

    async def test_admin_reads_one_exact_draft(self):
        reader = _RuleDraftDetailReader()
        response = await self._get_detail("admin", reader=reader)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(reader.binding_id, "binding-1")
        self.assertEqual(reader.draft_id, "draft-1")
        self.assertEqual(response.json()["id"], "draft-1")
        self.assertEqual(response.json()["bindingId"], "binding-1")
        self.assertEqual(response.json()["records"][0]["rule"]["kind"], "flow")

    async def test_draft_detail_permissions_and_invalid_paths_skip_reader(self):
        missing = await self._get_detail("admin")
        self.assertEqual(missing.status_code, 503)
        for role, status in (("view", 403), (None, 401)):
            with self.subTest(role=role):
                reader = _RuleDraftDetailReader()
                response = await self._get_detail(role, reader=reader)
                self.assertEqual(response.status_code, status)
                self.assertEqual(reader.calls, 0)
        invalid_reader = _RuleDraftDetailReader()
        invalid = await self._get_detail(
            "admin", reader=invalid_reader, draft_id=" "
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid_reader.calls, 0)

    async def test_draft_detail_mismatch_and_authority_errors_fail_closed(self):
        wrong = _rule_draft("other-draft")
        wrong_id = await self._get_detail(
            "admin", reader=_RuleDraftDetailReader(draft=wrong)
        )
        self.assertEqual(wrong_id.status_code, 503)
        wrong_binding = StoredRuleDraft(
            id="draft-1",
            binding_id="other-binding",
            revision="revision-1",
            kind=RuleKind.FLOW,
            profile="profile-1",
            base_version_id=None,
            base_checksum="checksum-1",
            source_revision=None,
            updated_at=_AS_OF,
            records=(),
        )
        foreign = await self._get_detail(
            "admin", reader=_RuleDraftDetailReader(draft=wrong_binding)
        )
        self.assertEqual(foreign.status_code, 503)
        cases = (
            (RuleDraftDetailNotFound("private"), 404, "not_found"),
            (RuleDraftDetailRateLimited(25), 429, "rate_limited"),
            (
                RuleDraftDetailAuthorityUnavailable("private store detail"),
                503,
                "service_unavailable",
            ),
        )
        for error, status, code in cases:
            with self.subTest(code=code):
                response = await self._get_detail(
                    "admin", reader=_RuleDraftDetailReader(error=error)
                )
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertNotIn("private", response.text)


class RuleDraftDomainTests(unittest.TestCase):
    def test_collection_rejects_duplicate_drafts_and_other_binding(self):
        with self.assertRaises(ValueError):
            _collection(items=(_rule_draft(), _rule_draft()))
        with self.assertRaises(ValueError):
            RuleDraftCollection("binding-1", _AS_OF, (_rule_draft(),) * 1_001)
        foreign = _rule_draft()
        foreign = StoredRuleDraft(
            id=foreign.id,
            binding_id="other",
            revision=foreign.revision,
            kind=foreign.kind,
            profile=foreign.profile,
            base_version_id=foreign.base_version_id,
            base_checksum=foreign.base_checksum,
            source_revision=foreign.source_revision,
            updated_at=foreign.updated_at,
            records=foreign.records,
        )
        with self.assertRaises(ValueError):
            _collection(items=(foreign,))

    def test_draft_rejects_non_millisecond_time_and_mismatched_rule_kind(self):
        valid = _rule_draft()
        with self.assertRaises(ValueError):
            replace(valid, kind=RuleKind.DEGRADE)
        with self.assertRaises(ValueError):
            StoredRuleDraft(
                id=valid.id,
                binding_id=valid.binding_id,
                revision=valid.revision,
                kind=valid.kind,
                profile=valid.profile,
                base_version_id=valid.base_version_id,
                base_checksum=valid.base_checksum,
                source_revision=valid.source_revision,
                updated_at=datetime(2026, 10, 9, 1, 0, 1, 123456, tzinfo=UTC),
                records=valid.records,
            )


if __name__ == "__main__":
    unittest.main()
