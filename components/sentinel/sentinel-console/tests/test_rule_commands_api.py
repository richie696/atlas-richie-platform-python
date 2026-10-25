"""HTTP authorization and strict-command boundary tests for rule mutations."""

from __future__ import annotations

import hashlib
import unittest

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.api.rule_mutation_parsing import (
    InvalidRuleMutation,
    parse_rule_mutation,
)
from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.mutate_rule_set import (
    ConfigureRulePublicationTarget,
    RuleMutationOperation,
    RuleOperationStatus,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession

_SESSION = "rule-command-session-token-0000000000000000001"
_CSRF = "rule-command-csrf-token-000000000000000000001"
_BINDING_ID = "binding-1"
_REQUEST_KEY = "rule-command-request-1"


class _InitializationReader:
    async def is_initialized(self) -> bool:
        return True


class _SetupWindowReader:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, _opaque_session: str | None) -> bool:
        return False


class _SessionReader:
    def __init__(self, role: str | None) -> None:
        self.role = role

    async def read_active_session(self, _session_digest: str):
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _AccountDirectoryReader:
    async def list_accounts(self, _query):
        return ()

    async def read_account(self, _account_id: str):
        return None


class _MutationAuthority:
    def __init__(self) -> None:
        self.commands = []
        self.lookups = []

    async def mutate(self, command, **context):
        self.commands.append((command, context))
        return RuleMutationOperation(
            command.binding_id,
            command.request_key,
            RuleOperationStatus.PENDING,
        )

    async def read_operation(self, binding_id, request_key, **context):
        self.lookups.append((binding_id, request_key, context))
        return RuleMutationOperation(
            binding_id,
            request_key,
            RuleOperationStatus.PENDING,
        )


class RuleCommandsApiTest(unittest.IsolatedAsyncioTestCase):
    def _build_app(self, *, role="admin", authority=None):
        return build_app(
            bootstrap_initialization_reader=_InitializationReader(),
            setup_window_reader=_SetupWindowReader(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=_SessionReader(role),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=_AccountDirectoryReader(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            rule_mutation_authority=authority,
        )

    async def _client(self, app):
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies=self._cookies(),
        )

    @staticmethod
    def _headers(*, request_key=_REQUEST_KEY):
        return {
            "origin": "https://console.test",
            "x-request-id": "rule-command-http-1",
            "x-sentinel-csrf": _CSRF,
            "idempotency-key": request_key,
        }

    @staticmethod
    def _cookies():
        return {"sentinel_session": _SESSION, "__Host-sentinel_csrf": _CSRF}

    @staticmethod
    def _body():
        return {
            "requestKey": _REQUEST_KEY,
            "mutation": {
                "kind": "save_draft",
                "draftId": None,
                "expectedRevision": None,
                "candidate": {
                    "bindingId": _BINDING_ID,
                    "profile": "sentinel-rule-profile-v1",
                    "kind": "flow",
                    "baseVersionId": None,
                    "baseChecksum": "sha256:baseline",
                    "sourceRevision": None,
                    "rules": [],
                },
            },
        }

    def test_publication_target_command_uses_exact_provider_shape(self) -> None:
        command = parse_rule_mutation(
            _BINDING_ID,
            {
                "requestKey": _REQUEST_KEY,
                "mutation": {
                    "kind": "configure_target",
                    "expectedSourceRevision": "source-rev-4",
                    "expectedTargetRevision": None,
                    "target": {
                        "provider": "consul",
                        "sourceId": "source-1",
                        "key": "sentinel/apps/orders/flow",
                    },
                },
            },
        )
        self.assertIsInstance(command.mutation, ConfigureRulePublicationTarget)
        self.assertEqual(command.mutation.target.binding_id, _BINDING_ID)
        self.assertEqual(command.mutation.target.source_id, "source-1")

    def test_publication_target_command_rejects_provider_field_drift(self) -> None:
        body = {
            "requestKey": _REQUEST_KEY,
            "mutation": {
                "kind": "configure_target",
                "expectedSourceRevision": "source-rev-4",
                "expectedTargetRevision": None,
                "target": {
                    "provider": "consul",
                    "sourceId": "source-1",
                    "key": "sentinel/apps/orders/flow",
                    "token": "must-never-be-accepted",
                },
            },
        }
        with self.assertRaises(InvalidRuleMutation):
            parse_rule_mutation(_BINDING_ID, body)

    async def test_admin_command_is_parsed_and_returns_pending_receipt(self) -> None:
        authority = _MutationAuthority()
        app = self._build_app(authority=authority)
        async with await self._client(app) as client:
            response = await client.post(
                f"/api/v1/rulesets/{_BINDING_ID}/commands",
                json=self._body(),
                headers=self._headers(),
            )
        self.assertEqual(response.status_code, 202)
        assert_openapi_response("mutateRuleSet", response)
        self.assertEqual(
            response.json(),
            {
                "bindingId": _BINDING_ID,
                "requestKey": _REQUEST_KEY,
                "status": "pending",
            },
        )
        command, context = authority.commands[0]
        self.assertEqual(command.binding_id, _BINDING_ID)
        self.assertEqual(command.request_key, _REQUEST_KEY)
        self.assertEqual(command.mutation.candidate.binding_id, _BINDING_ID)
        self.assertEqual(context["actor_id"], "account-1")
        self.assertNotIn("password", repr(command))

    async def test_mismatched_idempotency_key_is_rejected_before_authority(
        self,
    ) -> None:
        authority = _MutationAuthority()
        app = self._build_app(authority=authority)
        async with await self._client(app) as client:
            response = await client.post(
                f"/api/v1/rulesets/{_BINDING_ID}/commands",
                json=self._body(),
                headers=self._headers(request_key="different-request"),
            )
        self.assertEqual(response.status_code, 409)
        assert_openapi_response("mutateRuleSet", response)
        self.assertEqual(response.json()["error"]["code"], "idempotency_conflict")
        self.assertEqual(authority.commands, [])

    async def test_non_admin_cannot_submit_rule_command(self) -> None:
        authority = _MutationAuthority()
        app = self._build_app(role="view", authority=authority)
        async with await self._client(app) as client:
            response = await client.post(
                f"/api/v1/rulesets/{_BINDING_ID}/commands",
                json=self._body(),
                headers=self._headers(),
            )
        self.assertEqual(response.status_code, 403)
        assert_openapi_response("mutateRuleSet", response)
        self.assertEqual(authority.commands, [])

    async def test_operation_read_is_admin_and_scoped_to_binding_and_session(
        self,
    ) -> None:
        authority = _MutationAuthority()
        app = self._build_app(authority=authority)
        async with await self._client(app) as client:
            response = await client.get(
                f"/api/v1/rulesets/{_BINDING_ID}/operations/{_REQUEST_KEY}",
                headers={"x-request-id": "rule-operation-read-1"},
            )
        self.assertEqual(response.status_code, 200)
        assert_openapi_response("readRuleOperation", response)
        self.assertEqual(response.json()["status"], "pending")
        binding_id, request_key, context = authority.lookups[0]
        self.assertEqual((binding_id, request_key), (_BINDING_ID, _REQUEST_KEY))
        self.assertEqual(context["actor_id"], "account-1")
        self.assertEqual(
            context["session_digest"],
            hashlib.sha256(_SESSION.encode("ascii")).hexdigest(),
        )

    async def test_unavailable_mutation_authority_fails_closed(self) -> None:
        app = self._build_app(authority=None)
        async with await self._client(app) as client:
            response = await client.post(
                f"/api/v1/rulesets/{_BINDING_ID}/commands",
                json=self._body(),
                headers=self._headers(),
            )
        self.assertEqual(response.status_code, 503)
        assert_openapi_response("mutateRuleSet", response)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")

    async def test_non_admin_cannot_read_rule_operation(self) -> None:
        authority = _MutationAuthority()
        app = self._build_app(role="view", authority=authority)
        async with await self._client(app) as client:
            response = await client.get(
                f"/api/v1/rulesets/{_BINDING_ID}/operations/{_REQUEST_KEY}",
                headers={"x-request-id": "rule-operation-viewer-1"},
            )
        self.assertEqual(response.status_code, 403)
        assert_openapi_response("readRuleOperation", response)
        self.assertEqual(authority.lookups, [])
