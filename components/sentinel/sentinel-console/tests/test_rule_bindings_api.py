"""Rule binding directory API contract against isolated authorities."""

from __future__ import annotations

from datetime import datetime
import unittest

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.rule_binding_ports import (
    RuleBindingAuthorityUnavailable,
    RuleBindingRateLimited,
    RegisterRuleBinding,
    RuleBindingTargetNotFound,
)
from atlas_richie.sentinel_console.domain.rule_bindings import (
    RuleBinding,
    RuleBindingPage,
    RuleBindingQuery,
    RuleKind,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
)
from session_test_doubles import UnusedSessionRevoker

_HEADERS = {"x-request-id": "rule-bindings-read-1"}
_COOKIE = "synthetic-session-token-for-rule-directory-0001"
_CSRF = "synthetic-csrf-token-for-rule-registration-00001"
_PATH = "/api/v1/rulesets?environmentId=prod&page=1&pageSize=10"


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
        raise AssertionError("rule binding reads must not access accounts")

    async def read_account(self, account_id: str):
        raise AssertionError("rule binding reads must not access accounts")


def _binding(
    *,
    binding_id: str = "binding-1",
    environment_id: str = "prod",
    app_id: str = "checkout",
    kind: RuleKind = RuleKind.FLOW,
    source_label: str = "Primary Nacos",
    location: str = "sentinel/prod/flow-rules",
) -> RuleBinding:
    return RuleBinding(
        id=binding_id,
        environment_id=environment_id,
        app_id=app_id,
        kind=kind,
        profile="sentinel-flow-v1",
        source_id="nacos-main",
        source_label=source_label,
        location=location,
    )


def _page(query: RuleBindingQuery | None = None) -> RuleBindingPage:
    resolved = query or RuleBindingQuery("prod", None, None, "", 1, 10)
    total = (resolved.page - 1) * resolved.page_size + 1
    return RuleBindingPage(resolved, total, (_binding(),))


class _BindingReader:
    def __init__(self, *, error=None, page: RuleBindingPage | None = None) -> None:
        self.error = error
        self.page = page
        self.query: RuleBindingQuery | None = None
        self.calls = 0

    async def read_rule_bindings(self, query: RuleBindingQuery) -> RuleBindingPage:
        self.query = query
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.page or _page(query)


class _BindingRegistrationAuthority:
    def __init__(self) -> None:
        self.commands = []

    async def register_rule_binding(self, command, **context):
        self.commands.append((command, context))
        return _binding(
            binding_id=command.binding_id,
            environment_id=command.environment_id,
            app_id=command.app_id,
            kind=command.kind,
            source_label="Primary Nacos",
            location="nacos://prod-namespace/DEFAULT_GROUP/flow.json",
        )


class _UnusedAccountCommandService:
    async def execute(self, command):
        raise AssertionError("rule binding reads must not mutate accounts")


def _app(
    role: str | None,
    *,
    reader=None,
    registration_authority=None,
    session_reader=None,
):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_OpenSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=session_reader or _SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_AccountDirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.test"}),
        rule_binding_reader=reader,
        rule_binding_registration_authority=registration_authority,
    )


class RuleBindingsApiTests(unittest.IsolatedAsyncioTestCase):
    async def _get(self, role, path=_PATH, *, reader=None, session_reader=None):
        app = _app(role, reader=reader, session_reader=session_reader)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE},
        ) as client:
            return await client.get(path, headers=_HEADERS)

    @staticmethod
    def _registration_body():
        return {
            "requestKey": "binding-create-1",
            "bindingId": "binding-new",
            "environmentId": "prod",
            "appId": "checkout",
            "kind": "flow",
            "profile": "sentinel-flow-v1",
            "sourceId": "nacos-main",
            "sourceRevision": "source-revision-1",
            "target": {
                "provider": "nacos",
                "namespace": "prod-namespace",
                "group": "DEFAULT_GROUP",
                "dataId": "flow.json",
            },
        }

    async def _post_registration(
        self,
        *,
        role="admin",
        authority=None,
        body=None,
        csrf=_CSRF,
        origin="https://console.test",
        session_reader=None,
    ):
        app = _app(
            role,
            registration_authority=authority,
            session_reader=session_reader,
        )
        headers = {
            "origin": origin,
            "x-request-id": "binding-registration-1",
            "x-sentinel-csrf": csrf,
            "idempotency-key": "binding-create-1",
        }
        cookies = {"sentinel_session": _COOKIE, "__Host-sentinel_csrf": _CSRF}
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies=cookies,
        ) as client:
            return await client.post(
                "/api/v1/rulesets",
                json=body or self._registration_body(),
                headers=headers,
            )

    async def test_admin_registration_passes_exact_source_and_target_command(self):
        authority = _BindingRegistrationAuthority()
        response = await self._post_registration(authority=authority)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.json()["id"], "binding-new")
        self.assertEqual(response.json()["sourceLabel"], "Primary Nacos")
        command, context = authority.commands[0]
        self.assertIsInstance(command, RegisterRuleBinding)
        self.assertEqual(command.target, NacosRulePublicationTarget(
            "binding-new", "nacos-main", "prod-namespace", "DEFAULT_GROUP", "flow.json"
        ))
        self.assertEqual(command.source_revision, "source-revision-1")
        self.assertEqual(context["request_id"], "binding-registration-1")
        self.assertEqual(context["actor_id"], "account-1")
        self.assertIsInstance(context["now"], datetime)

    async def test_viewer_csrf_and_invalid_provider_are_rejected_before_authority(self):
        for options, expected_status, expected_code in (
            ({"role": "view"}, 403, "forbidden"),
            ({"origin": "https://attacker.test"}, 403, "csrf_failed"),
            ({"csrf": "mismatched-csrf-token-for-rule-registration-000"}, 403, "csrf_failed"),
        ):
            with self.subTest(expected_code=expected_code):
                authority = _BindingRegistrationAuthority()
                response = await self._post_registration(
                    authority=authority, **options
                )
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.json()["error"]["code"], expected_code)
                self.assertEqual(authority.commands, [])

        authority = _BindingRegistrationAuthority()
        invalid_body = self._registration_body()
        invalid_body["target"]["token"] = "must-not-be-accepted"
        invalid = await self._post_registration(
            authority=authority, body=invalid_body
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(authority.commands, [])

    async def test_admin_and_view_read_query_bound_page_with_no_store(self):
        for role in ("admin", "view"):
            with self.subTest(role=role):
                reader = _BindingReader()
                response = await self._get(role, reader=reader)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(
                    response.headers["x-request-id"], _HEADERS["x-request-id"]
                )
                self.assertEqual(
                    response.json()["query"],
                    {
                        "environmentId": "prod",
                        "appId": None,
                        "kind": None,
                        "search": "",
                        "page": 1,
                        "pageSize": 10,
                    },
                )
                self.assertEqual(
                    response.json()["items"][0]["location"],
                    "sentinel/prod/flow-rules",
                )
                self.assertEqual(reader.calls, 1)

    async def test_exact_filters_search_and_pagination_are_passed_to_authority(self):
        reader = _BindingReader()
        path = (
            "/api/v1/rulesets?environmentId=prod&appId=checkout&kind=flow"
            "&search=flow&page=2&pageSize=25"
        )
        response = await self._get(
            "view", path, reader=reader
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            reader.query,
            RuleBindingQuery("prod", "checkout", RuleKind.FLOW, "flow", 2, 25),
        )
        self.assertEqual(response.json()["query"]["page"], 2)

    async def test_invalid_or_ambiguous_query_is_rejected_before_authority(self):
        invalid_paths = (
            "/api/v1/rulesets?page=1&pageSize=10",
            _PATH + "&page=2",
            _PATH + "&ignored=true",
            "/api/v1/rulesets?environmentId=prod&page=0&pageSize=10",
            "/api/v1/rulesets?environmentId=prod&page=1&pageSize=101",
            "/api/v1/rulesets?environmentId=prod&kind=unknown&page=1&pageSize=10",
            "/api/v1/rulesets?environmentId=prod&search="
            + ("x" * 201)
            + "&page=1&pageSize=10",
            "/api/v1/rulesets?environmentId=%EF%BB%BF&page=1&pageSize=10",
        )
        for path in invalid_paths:
            with self.subTest(path=path[:100]):
                reader = _BindingReader()
                response = await self._get("admin", path, reader=reader)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "invalid_request")
                self.assertEqual(reader.calls, 0)

    async def test_anonymous_and_session_failure_do_not_call_directory_authority(self):
        anonymous_reader = _BindingReader()
        anonymous = await self._get(None, reader=anonymous_reader)
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(anonymous_reader.calls, 0)
        unavailable_reader = _BindingReader()
        unavailable = await self._get(
            "admin",
            reader=unavailable_reader,
            session_reader=_SessionReader("unavailable"),
        )
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable_reader.calls, 0)

    async def test_missing_reader_and_authority_failures_have_stable_codes(self):
        no_reader = await self._get("view")
        self.assertEqual(no_reader.status_code, 503)
        cases = (
            (RuleBindingTargetNotFound(), 404, "not_found"),
            (RuleBindingRateLimited(25), 429, "rate_limited"),
            (RuleBindingAuthorityUnavailable("private"), 503, "service_unavailable"),
        )
        for error, status, code in cases:
            with self.subTest(code=code):
                response = await self._get("view", reader=_BindingReader(error=error))
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertNotIn("private", response.text)

    async def test_query_mismatch_and_unsafe_location_fail_closed(self):
        mismatched_reader = _BindingReader(
            page=RuleBindingPage(
                RuleBindingQuery("stage", None, None, "", 1, 10), 0, ()
            )
        )
        mismatch = await self._get("admin", reader=mismatched_reader)
        self.assertEqual(mismatch.status_code, 503)
        unsafe = await self._get(
            "admin", reader=_BindingReader(error=ValueError("unsafe location"))
        )
        self.assertEqual(unsafe.status_code, 503)

    def test_domain_rejects_duplicate_bindings_and_misfiltered_items(self):
        query = RuleBindingQuery("prod", "checkout", RuleKind.FLOW, "", 1, 10)
        with self.assertRaises(ValueError):
            RuleBindingPage(query, 2, (_binding(), _binding()))
        with self.assertRaises(ValueError):
            RuleBindingPage(query, 1, (_binding(app_id="billing"),))
        with self.assertRaises(ValueError):
            _binding(location="sentinel/prod?token=credential-value")

    def test_domain_rejects_cross_runtime_blank_binding_text(self):
        for blank in (" ", "\u0085", "\u001c", "\ufeff"):
            with self.subTest(blank=repr(blank)):
                for field in ("binding_id", "environment_id", "app_id"):
                    with self.assertRaises(ValueError):
                        _binding(**{field: blank})
                with self.assertRaises(ValueError):
                    _binding(source_label=blank)
                with self.assertRaises(ValueError):
                    _binding(location=blank)


if __name__ == "__main__":
    unittest.main()
