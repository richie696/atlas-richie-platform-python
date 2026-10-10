"""HTTP contract tests for authenticated, idempotent source commands."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.mutate_registered_source import (
    RegisteredSourceOperation,
    SourceMutationKind,
    SourceMutationStatus,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.registered_sources import (
    RegisteredConfigurationSource,
    SourceAuthenticationMode,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from session_test_doubles import UnusedSessionRevoker

_SESSION = "registered-source-session-token-0000000000000001"
_CSRF = "registered-source-csrf-token-00000000000000001"
_DEFAULT_OPERATION = object()


class _InitializationReader:
    async def is_initialized(self) -> bool:
        return True


class _SetupWindowReader:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _SessionReader:
    def __init__(self, role: str | None) -> None:
        self.role = role
        self.calls = 0

    async def read_active_session(self, _session_digest: str):
        self.calls += 1
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _AccountDirectoryReader:
    async def list_accounts(self, query):
        return ()

    async def read_account(self, account_id: str):
        return None


class _MutationAuthority:
    def __init__(self, operation=_DEFAULT_OPERATION) -> None:
        self.operation = (
            RegisteredSourceOperation("source-request-1", SourceMutationStatus.PENDING)
            if operation is _DEFAULT_OPERATION
            else operation
        )
        self.commands = []
        self.lookups = []

    async def mutate(self, command, **context):
        self.commands.append((command, context))
        return self.operation

    async def read_operation(self, request_key, **context):
        self.lookups.append((request_key, context))
        return self.operation


class RegisteredSourceCommandsApiTest(unittest.IsolatedAsyncioTestCase):
    def _build_app(self, *, role="admin", authority=None):
        self.sessions = _SessionReader(role)
        return build_app(
            bootstrap_initialization_reader=_InitializationReader(),
            setup_window_reader=_SetupWindowReader(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=self.sessions,
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=_AccountDirectoryReader(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            registered_source_mutation_authority=authority,
        )

    async def _client(self, app):
        return AsyncClient(
            transport=ASGITransport(app=app), base_url="https://console.test"
        )

    @staticmethod
    def _headers(*, csrf=_CSRF, origin="https://console.test"):
        return {
            "origin": origin,
            "x-request-id": "source-command-http-1",
            "x-sentinel-csrf": csrf,
            "idempotency-key": "source-request-1",
        }

    @staticmethod
    def _cookies(*, authenticated=True, csrf=_CSRF):
        cookies = {"__Host-sentinel_csrf": csrf}
        if authenticated:
            cookies["sentinel_session"] = _SESSION
        return cookies

    @staticmethod
    def _body(*, authentication=None):
        return {
            "kind": "register",
            "requestKey": "source-request-1",
            "name": "Production Nacos",
            "source": {
                "provider": "nacos",
                "endpoint": "https://nacos.internal:8848",
                "namespace": "sentinel",
                "authentication": authentication or {"mode": "none"},
            },
        }

    async def test_admin_register_returns_typed_202_receipt(self) -> None:
        authority = _MutationAuthority()
        app = self._build_app(authority=authority)
        async with await self._client(app) as client:
            response = await client.post(
                "/api/v1/system/sources/commands",
                json=self._body(),
                headers=self._headers(),
                cookies=self._cookies(),
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.json(), {"status": "pending", "requestKey": "source-request-1"}
        )
        command, context = authority.commands[0]
        self.assertEqual(command.kind, SourceMutationKind.REGISTER)
        self.assertEqual(command.source.provider, ConfigurationSourceProvider.NACOS)
        self.assertEqual(context["actor_id"], "account-1")
        self.assertEqual(context["now"].tzinfo, UTC)

    async def test_role_csrf_and_idempotency_are_checked_before_authority(self) -> None:
        authority = _MutationAuthority()
        app = self._build_app(role="view", authority=authority)
        async with await self._client(app) as client:
            denied = await client.post(
                "/api/v1/system/sources/commands",
                json=self._body(),
                headers=self._headers(),
                cookies=self._cookies(),
            )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(authority.commands, [])

        app = self._build_app(authority=authority)
        async with await self._client(app) as client:
            csrf = await client.post(
                "/api/v1/system/sources/commands",
                json=self._body(),
                headers=self._headers(csrf="wrong-csrf-token-000000000000000000"),
                cookies=self._cookies(),
            )
            mismatch = await client.post(
                "/api/v1/system/sources/commands",
                json={**self._body(), "requestKey": "source-request-2"},
                headers=self._headers(),
                cookies=self._cookies(),
            )
        self.assertEqual(csrf.status_code, 403)
        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(authority.commands, [])

    async def test_invalid_command_body_uses_contract_validation_error(self) -> None:
        authority = _MutationAuthority()
        invalid_bodies = [
            {**self._body(), "unexpected": True},
            *({**self._body(), "name": blank} for blank in ("\x1c", "\x85", "\ufeff", "\u3000")),
        ]
        async with await self._client(self._build_app(authority=authority)) as client:
            responses = [
                await client.post(
                    "/api/v1/system/sources/commands",
                    json=body,
                    headers=self._headers(),
                    cookies=self._cookies(),
                )
                for body in invalid_bodies
            ]
        self.assertTrue(all(response.status_code == 422 for response in responses))
        self.assertTrue(
            all(response.json()["error"]["code"] == "validation_failed" for response in responses)
        )
        self.assertEqual(authority.commands, [])

    async def test_direct_credentials_are_ephemeral_and_never_echoed(self) -> None:
        authority = _MutationAuthority()
        body = self._body(
            authentication={"mode": "direct", "username": "operator", "password": "do-not-echo"}
        )
        async with await self._client(self._build_app(authority=authority)) as client:
            response = await client.post(
                "/api/v1/system/sources/commands",
                json=body,
                headers=self._headers(),
                cookies=self._cookies(),
            )
        self.assertEqual(response.status_code, 202)
        self.assertNotIn("do-not-echo", response.text)
        self.assertNotIn("do-not-echo", repr(authority.commands[0][0]))

    async def test_conditional_update_requires_and_preserves_source_revision(self) -> None:
        authority = _MutationAuthority()
        body = {
            "kind": "update",
            "requestKey": "source-request-1",
            "sourceId": "source-1",
            "expectedRevision": "revision-8",
            "name": "Production Nacos",
            "source": {
                "provider": "nacos",
                "endpoint": "https://nacos.internal:8848",
                "namespace": "sentinel",
                "authentication": {"mode": "keep"},
            },
        }
        async with await self._client(self._build_app(authority=authority)) as client:
            response = await client.post(
                "/api/v1/system/sources/commands",
                json=body,
                headers=self._headers(),
                cookies=self._cookies(),
            )
        self.assertEqual(response.status_code, 202)
        command = authority.commands[0][0]
        self.assertEqual(command.kind, SourceMutationKind.UPDATE)
        self.assertEqual(command.source.source_id, "source-1")
        self.assertEqual(command.source.expected_revision, "revision-8")
        self.assertEqual(command.source.authentication_mode.value, "keep")

    async def test_completed_operation_contains_only_safe_registered_facts(self) -> None:
        record = RegisteredConfigurationSource(
            id="source-1",
            revision="revision-2",
            name="Production Nacos",
            endpoint="https://nacos.internal:8848",
            provider=ConfigurationSourceProvider.NACOS,
            location="sentinel",
            authentication_mode=SourceAuthenticationMode.DIRECT,
            credential_configured=True,
        )
        authority = _MutationAuthority(
            RegisteredSourceOperation(
                "source-request-1", SourceMutationStatus.COMPLETED, record=record
            )
        )
        async with await self._client(self._build_app(authority=authority)) as client:
            response = await client.post(
                "/api/v1/system/sources/commands",
                json=self._body(),
                headers=self._headers(),
                cookies=self._cookies(),
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["record"]["namespace"], "sentinel")
        self.assertNotIn("password", response.text)
        self.assertTrue(response.json()["record"]["credentialConfigured"])

    async def test_original_operation_lookup_requires_admin_and_returns_not_found(self) -> None:
        authority = _MutationAuthority(None)
        async with await self._client(self._build_app(authority=authority)) as client:
            response = await client.get(
                "/api/v1/system/sources/operations/source-request-1",
                headers={"x-request-id": "source-operation-read-1"},
                cookies=self._cookies(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"status": "not_found", "requestKey": "source-request-1"}
        )
        self.assertEqual(authority.lookups[0][0], "source-request-1")

        authority = _MutationAuthority()
        async with await self._client(
            self._build_app(role="view", authority=authority)
        ) as client:
            denied = await client.get(
                "/api/v1/system/sources/operations/source-request-1",
                headers={"x-request-id": "source-operation-read-2"},
                cookies=self._cookies(),
            )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(authority.lookups, [])

    async def test_operation_lookup_rejects_invalid_request_id_as_bad_request(self) -> None:
        authority = _MutationAuthority()
        async with await self._client(self._build_app(authority=authority)) as client:
            response = await client.get(
                "/api/v1/system/sources/operations/source-request-1",
                headers={"x-request-id": "invalid\nrequest"},
                cookies=self._cookies(),
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        self.assertEqual(authority.lookups, [])


if __name__ == "__main__":
    unittest.main()
