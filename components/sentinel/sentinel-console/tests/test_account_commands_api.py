"""HTTP security and safe-operation tests for account command adapters."""

from __future__ import annotations

import unittest

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.account_commands import (
    AccountCommandReason,
    AccountCommandUnavailable,
    AccountOperation,
    AccountOperationStatus,
)
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession

_ORIGIN = "https://console.test"
_SESSION = "synthetic-account-command-session-token-0001"
_CSRF = "synthetic-account-command-csrf-token-00001"
_REQUEST_KEY = "account-command-create-1"


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _SetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, _session: str | None) -> bool:
        return False


class _SessionReader:
    def __init__(self, role: str | None) -> None:
        self.role = role

    async def read_active_session(self, _digest: str):
        if self.role == "unavailable":
            raise SessionAuthorityUnavailable("private session authority detail")
        if self.role is None:
            return None
        return ActiveAccountSession("admin-1", "operator", self.role, "epoch-1")


class _AccountCommandService:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self.commands = []
        self.lookups = []

    async def execute(self, *, actor, command, request_id, now):
        if self.unavailable:
            raise AccountCommandUnavailable("private command authority detail")
        self.commands.append((actor, command, request_id))
        return AccountOperation(
            command.request_key,
            AccountOperationStatus.REJECTED,
            reason=AccountCommandReason.USERNAME_TAKEN,
        )

    async def read_operation(self, request_key, actor):
        if self.unavailable:
            raise AccountCommandUnavailable("private operation reader detail")
        self.lookups.append((request_key, actor))


class AccountCommandsApiTest(unittest.IsolatedAsyncioTestCase):
    def _app(self, *, role: str | None = "admin", service=None):
        return build_app(
            bootstrap_initialization_reader=_Initialized(),
            setup_window_reader=_SetupWindow(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=_SessionReader(role),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=object(),
            account_command_service=service or _AccountCommandService(),
            allowed_browser_origins=frozenset({_ORIGIN}),
        )

    async def _client(self, app):
        client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url=_ORIGIN,
            cookies={"sentinel_session": _SESSION, "__Host-sentinel_csrf": _CSRF},
        )
        return client

    @staticmethod
    def _headers(*, key: str = _REQUEST_KEY) -> dict[str, str]:
        return {
            "origin": _ORIGIN,
            "x-request-id": "account-command-http-1",
            "x-sentinel-csrf": _CSRF,
            "idempotency-key": key,
        }

    @staticmethod
    def _create_body() -> dict[str, object]:
        return {
            "kind": "create",
            "requestKey": _REQUEST_KEY,
            "input": {
                "username": " new-operator ",
                "password": "synthetic-new-password-0001",
                "roleId": "view",
            },
        }

    async def test_admin_create_returns_safe_business_rejection_receipt(self) -> None:
        service = _AccountCommandService()
        async with await self._client(self._app(service=service)) as client:
            response = await client.post(
                "/api/v1/accounts/commands",
                json=self._create_body(),
                headers=self._headers(),
            )

        self.assertEqual(response.status_code, 200)
        assert_openapi_response("mutateAccount", response)
        self.assertEqual(
            response.json(),
            {
                "status": "rejected",
                "requestKey": _REQUEST_KEY,
                "reason": "username_taken",
            },
        )
        actor, command, request_id = service.commands[0]
        self.assertEqual(actor.account_id, "admin-1")
        self.assertEqual(command.username.value, "new-operator")
        self.assertEqual(command.password.value, "synthetic-new-password-0001")
        self.assertEqual(request_id, "account-command-http-1")
        self.assertNotIn("synthetic-new-password", repr(command))
        self.assertNotIn("synthetic-new-password", response.text)

    async def test_csrf_role_and_idempotency_fail_before_command_execution(
        self,
    ) -> None:
        service = _AccountCommandService()
        async with await self._client(self._app(service=service)) as client:
            missing_csrf = await client.post(
                "/api/v1/accounts/commands",
                json=self._create_body(),
                headers={
                    key: value
                    for key, value in self._headers().items()
                    if key != "x-sentinel-csrf"
                },
            )
            mismatch = await client.post(
                "/api/v1/accounts/commands",
                json=self._create_body(),
                headers=self._headers(key="different-request-key"),
            )
        async with await self._client(
            self._app(role="view", service=service)
        ) as client:
            viewer = await client.post(
                "/api/v1/accounts/commands",
                json=self._create_body(),
                headers=self._headers(),
            )
            viewer_role_change = await client.post(
                "/api/v1/accounts/commands",
                json={
                    "kind": "role",
                    "requestKey": _REQUEST_KEY,
                    "accountId": "account-target",
                    "revision": "3",
                    "roleId": "view",
                },
                headers=self._headers(),
            )

        self.assertEqual(
            (missing_csrf.status_code, missing_csrf.json()["error"]["code"]),
            (403, "csrf_failed"),
        )
        assert_openapi_response("mutateAccount", missing_csrf)
        self.assertEqual(
            (viewer.status_code, viewer.json()["error"]["code"]),
            (403, "forbidden"),
        )
        assert_openapi_response("mutateAccount", viewer)
        self.assertEqual(
            (viewer_role_change.status_code, viewer_role_change.json()["error"]["code"]),
            (403, "forbidden"),
        )
        assert_openapi_response("mutateAccount", viewer_role_change)
        self.assertEqual(
            (mismatch.status_code, mismatch.json()["error"]["code"]),
            (409, "idempotency_conflict"),
        )
        assert_openapi_response("mutateAccount", mismatch)
        self.assertEqual(service.commands, [])

    async def test_invalid_role_command_is_rejected_before_execution(self) -> None:
        service = _AccountCommandService()
        async with await self._client(self._app(service=service)) as client:
            maximum_revision = "9223372036854775807"
            accepted = await client.post(
                "/api/v1/accounts/commands",
                json={
                    "kind": "role",
                    "requestKey": _REQUEST_KEY,
                    "accountId": "account-target",
                    "revision": maximum_revision,
                    "roleId": "admin",
                },
                headers=self._headers(),
            )
            self.assertEqual(accepted.status_code, 200)
            assert_openapi_response("mutateAccount", accepted)
            self.assertEqual(
                service.commands[0][1].expected_revision, int(maximum_revision)
            )

            for revision in (
                "0",
                "01",
                "account-revision-1",
                "9223372036854775808",
            ):
                with self.subTest(revision=revision):
                    body = {
                        "kind": "role",
                        "requestKey": _REQUEST_KEY,
                        "accountId": "account-target",
                        "revision": revision,
                        "roleId": "admin",
                    }
                    response = await client.post(
                        "/api/v1/accounts/commands",
                        json=body,
                        headers=self._headers(),
                    )
                    self.assertEqual(
                        (response.status_code, response.json()["error"]["code"]),
                        (400, "invalid_request"),
                    )
                    assert_openapi_response("mutateAccount", response)

        self.assertEqual(len(service.commands), 1)
        self.assertEqual(
            service.commands[0][1].expected_revision, 9_223_372_036_854_775_807
        )

    async def test_operation_lookup_returns_safe_not_found_and_requires_admin(
        self,
    ) -> None:
        service = _AccountCommandService()
        async with await self._client(self._app(service=service)) as client:
            missing = await client.get(
                "/api/v1/accounts/operations/original-request-1",
                headers={"x-request-id": "account-operation-1"},
            )
        async with await self._client(
            self._app(role="view", service=service)
        ) as client:
            forbidden = await client.get(
                "/api/v1/accounts/operations/original-request-1",
                headers={"x-request-id": "account-operation-2"},
            )

        self.assertEqual(
            (missing.status_code, missing.json()),
            (200, {"status": "not-found", "requestKey": "original-request-1"}),
        )
        assert_openapi_response("readAccountOperation", missing)
        self.assertEqual(
            (forbidden.status_code, forbidden.json()["error"]["code"]),
            (403, "forbidden"),
        )
        assert_openapi_response("readAccountOperation", forbidden)
        self.assertEqual(len(service.lookups), 1)

    async def test_command_authority_failure_is_sanitized(self) -> None:
        async with await self._client(
            self._app(service=_AccountCommandService(unavailable=True))
        ) as client:
            response = await client.post(
                "/api/v1/accounts/commands",
                json=self._create_body(),
                headers=self._headers(),
            )

        self.assertEqual(
            (response.status_code, response.json()["error"]["code"]),
            (503, "service_unavailable"),
        )
        assert_openapi_response("mutateAccount", response)
        self.assertNotIn("private command authority detail", response.text)
        self.assertNotIn("synthetic-new-password", response.text)
