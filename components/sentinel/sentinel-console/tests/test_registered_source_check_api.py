"""Authenticated HTTP tests for non-mutating registered-source probes."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.check_registered_source import (
    RegisteredSourceCheckRateLimited,
    RegisteredSourceCheckResult,
    RegisteredSourceCheckUnavailable,
    SourceCheckAuthenticationMode,
    SourceCheckCapability,
    SourceCheckFailureReason,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.application.source_credential_references import (
    ResolvedSourceCredentials,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession

_SESSION = "registered-source-session-token-0000000000000001"
_CSRF = "registered-source-csrf-token-00000000000000001"
_NOW = datetime(2026, 10, 9, 2, 0, tzinfo=UTC)


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
    def __init__(self, role: str | None, *, fail: bool = False) -> None:
        self.role = role
        self.fail = fail
        self.calls = 0

    async def read_active_session(self, _session_digest: str):
        self.calls += 1
        if self.fail:
            from atlas_richie.sentinel_console.application.errors import (
                SessionAuthorityUnavailable,
            )

            raise SessionAuthorityUnavailable("private session error")
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _AccountDirectoryReader:
    async def list_accounts(self, query):
        return ()

    async def read_account(self, account_id: str):
        return None


class _Checker:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result or RegisteredSourceCheckResult(
            checked_at=_NOW,
            expires_at=_NOW + timedelta(seconds=60),
            capabilities=(SourceCheckCapability.READ, SourceCheckCapability.WATCH),
        )
        self.error = error
        self.commands: list[tuple[SourceConnectionInput, str]] = []

    async def check(self, command, actor_id: str):
        self.commands.append((command, actor_id))
        if self.error is not None:
            raise self.error
        return self.result


class _CredentialResolver:
    async def resolve_credentials(self, source_id, expected_revision, provider):
        return SourceConnectionInput(
            source_id=source_id,
            expected_revision=expected_revision,
            provider=provider,
            endpoint="https://stored.internal:8848",
            location="stored-namespace",
            authentication_mode=SourceCheckAuthenticationMode.DIRECT,
            username="operator",
            password="private-password",
        )


class _ReferenceResolver:
    async def resolve(self, provider, reference):
        if (
            provider is not ConfigurationSourceProvider.NACOS
            or reference != "secret://nacos/prod"
        ):
            return None
        return ResolvedSourceCredentials(
            provider,
            username="operator",
            password="resolved-private-password",
        )


class RegisteredSourceCheckApiTest(unittest.IsolatedAsyncioTestCase):
    def _build_app(
        self,
        role: str | None = "admin",
        checker=None,
        *,
        fail=False,
        credential_resolver=None,
        credential_reference_resolver=None,
    ):
        return build_app(
            bootstrap_initialization_reader=_InitializationReader(),
            setup_window_reader=_SetupWindowReader(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=_SessionReader(role, fail=fail),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=_AccountDirectoryReader(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            registered_source_checker=checker,
            registered_source_credential_resolver=credential_resolver,
            source_credential_reference_resolver=credential_reference_resolver,
        )

    async def _client(self, app, *, authenticated: bool = True):
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies=self._cookies(authenticated=authenticated),
        )

    @staticmethod
    def _headers(*, origin: str = "https://console.test"):
        return {
            "origin": origin,
            "x-request-id": "registered-source-check-1",
            "x-sentinel-csrf": _CSRF,
        }

    @staticmethod
    def _cookies(*, authenticated: bool = True):
        cookies = {"__Host-sentinel_csrf": _CSRF}
        if authenticated:
            cookies["sentinel_session"] = _SESSION
        return cookies

    @staticmethod
    def _body():
        return {
            "sourceId": "source-1",
            "expectedRevision": "revision-8",
            "source": {
                "provider": "nacos",
                "endpoint": "https://nacos.internal:8848",
                "namespace": "sentinel",
                "authentication": {"mode": "keep"},
            },
        }

    async def test_admin_check_returns_short_lived_capabilities(self) -> None:
        checker = _Checker()
        async with await self._client(
            self._build_app(checker=checker, credential_resolver=_CredentialResolver())
        ) as client:
            response = await client.post(
                "/api/v1/system/sources/check",
                json=self._body(),
                headers=self._headers(),
            )
        self.assertEqual(response.status_code, 200)
        assert_openapi_response("checkRegisteredSource", response)
        self.assertEqual(
            response.json(),
            {
                "status": "reachable",
                "checkedAt": "2026-10-09T02:00:00.000Z",
                "expiresAt": "2026-10-09T02:01:00.000Z",
                "capabilities": ["read", "watch"],
            },
        )
        command, actor_id = checker.commands[0]
        self.assertEqual(
            (command.source_id, command.expected_revision),
            ("source-1", "revision-8"),
        )
        self.assertEqual(actor_id, "account-1")
        self.assertEqual(
            command.authentication_mode, SourceCheckAuthenticationMode.DIRECT
        )
        self.assertEqual(command.endpoint, "https://nacos.internal:8848")
        self.assertEqual(command.location, "sentinel")
        self.assertEqual(command.password, "private-password")

    async def test_view_and_anonymous_sessions_never_reach_checker(self) -> None:
        checker = _Checker()
        cases = (("view", True, 403), (None, True, 401))
        for role, authenticated, expected_status in cases:
            async with await self._client(
                self._build_app(role=role, checker=checker),
                authenticated=authenticated,
            ) as client:
                response = await client.post(
                    "/api/v1/system/sources/check",
                    json=self._body(),
                    headers=self._headers(),
                )
            self.assertEqual(response.status_code, expected_status)
            assert_openapi_response("checkRegisteredSource", response)
        self.assertEqual(checker.commands, [])

    async def test_bad_csrf_origin_and_schema_do_not_call_checker(self) -> None:
        checker = _Checker()
        async with await self._client(self._build_app(checker=checker)) as client:
            bad_origin = await client.post(
                "/api/v1/system/sources/check",
                json=self._body(),
                headers=self._headers(origin="https://attacker.test"),
            )
            bad_schema = await client.post(
                "/api/v1/system/sources/check",
                json={**self._body(), "unexpected": True},
                headers=self._headers(),
            )
        self.assertEqual(bad_origin.status_code, 403)
        assert_openapi_response("checkRegisteredSource", bad_origin)
        self.assertEqual(bad_schema.status_code, 400)
        assert_openapi_response("checkRegisteredSource", bad_schema)
        self.assertEqual(checker.commands, [])

    async def test_source_identity_and_expected_revision_must_be_paired(self) -> None:
        checker = _Checker()
        bodies = (self._body(), self._body())
        bodies[0]["expectedRevision"] = None
        bodies[1]["sourceId"] = None
        async with await self._client(self._build_app(checker=checker)) as client:
            responses = [
                await client.post(
                    "/api/v1/system/sources/check",
                    json=body,
                    headers=self._headers(),
                )
                for body in bodies
            ]

        for response in responses:
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"]["code"], "invalid_request")
            assert_openapi_response("checkRegisteredSource", response)
        self.assertEqual(checker.commands, [])

        candidate = self._body()
        candidate.update(sourceId=None, expectedRevision=None)
        candidate["source"] = {
            "provider": "nacos",
            "endpoint": "https://nacos.internal:8848",
            "namespace": "sentinel",
            "authentication": {"mode": "none"},
        }
        async with await self._client(self._build_app(checker=checker)) as client:
            accepted = await client.post(
                "/api/v1/system/sources/check",
                json=candidate,
                headers=self._headers(),
            )
        self.assertEqual(accepted.status_code, 200)
        assert_openapi_response("checkRegisteredSource", accepted)
        self.assertEqual(len(checker.commands), 1)

    async def test_source_check_rejects_utf16_overflow_and_blank_references_before_checker(
        self,
    ) -> None:
        checker = _Checker()
        cases = []
        for field, value in (
            ("endpoint", f"https://nacos.internal/{'😀' * 1020}"),
            ("endpoint", "http://256.256.256.256"),
            ("endpoint", "https://nacos.internal:99999"),
            ("endpoint", "https://%41.nacos.internal"),
            ("namespace", "😀" * 101),
        ):
            body = self._body()
            body["source"][field] = value
            cases.append(body)

        reference = self._body()
        reference["source"]["authentication"] = {
            "mode": "credential-reference",
            "reference": "😀" * 257,
        }
        cases.append(reference)
        blank_reference = self._body()
        blank_reference["source"]["authentication"] = {
            "mode": "credential-reference",
            "reference": "\ufeff",
        }
        cases.append(blank_reference)
        username = self._body()
        username["source"]["authentication"] = {
            "mode": "direct",
            "username": "😀" * 101,
            "password": "synthetic-password",
        }
        cases.append(username)
        blank_username = self._body()
        blank_username["source"]["authentication"] = {
            "mode": "direct",
            "username": "\x1c",
            "password": "synthetic-password",
        }
        cases.append(blank_username)
        password = self._body()
        password["source"]["authentication"] = {
            "mode": "direct",
            "username": "operator",
            "password": "😀" * 513,
        }
        cases.append(password)
        consul_token = self._body()
        consul_token["source"] = {
            "provider": "consul",
            "endpoint": "https://consul.internal",
            "datacenter": "dc1",
            "authentication": {"mode": "direct", "aclToken": "😀" * 513},
        }
        cases.append(consul_token)

        async with await self._client(self._build_app(checker=checker)) as client:
            responses = [
                await client.post(
                    "/api/v1/system/sources/check",
                    json=body,
                    headers=self._headers(),
                )
                for body in cases
            ]
        self.assertTrue(all(response.status_code == 400 for response in responses))
        self.assertTrue(
            all(
                response.json()["error"]["code"] == "invalid_request"
                for response in responses
            )
        )
        self.assertEqual(checker.commands, [])

    async def test_direct_secret_is_write_only_and_revision_is_required(self) -> None:
        checker = _Checker()
        body = {
            "sourceId": None,
            "expectedRevision": None,
            "source": {
                "provider": "consul",
                "endpoint": "https://consul.internal:8501",
                "datacenter": "dc-a",
                "authentication": {"mode": "direct", "aclToken": "private-token"},
            },
        }
        async with await self._client(self._build_app(checker=checker)) as client:
            response = await client.post(
                "/api/v1/system/sources/check",
                json=body,
                headers=self._headers(),
            )
            mismatch = await client.post(
                "/api/v1/system/sources/check",
                json={**body, "expectedRevision": "revision-1"},
                headers=self._headers(),
            )
        self.assertEqual(response.status_code, 200)
        assert_openapi_response("checkRegisteredSource", response)
        self.assertNotIn("private-token", repr(checker.commands[0][0]))
        self.assertNotIn("private-token", response.text)
        self.assertEqual(mismatch.status_code, 400)
        assert_openapi_response("checkRegisteredSource", mismatch)
        self.assertEqual(len(checker.commands), 1)

    async def test_credential_reference_is_resolved_before_checker_and_not_returned(
        self,
    ):
        checker = _Checker()
        body = {
            "sourceId": None,
            "expectedRevision": None,
            "source": {
                "provider": "nacos",
                "endpoint": "https://nacos.internal:8848",
                "namespace": "sentinel",
                "authentication": {
                    "mode": "credential-reference",
                    "reference": "secret://nacos/prod",
                },
            },
        }
        async with await self._client(
            self._build_app(
                checker=checker,
                credential_reference_resolver=_ReferenceResolver(),
            )
        ) as client:
            response = await client.post(
                "/api/v1/system/sources/check",
                json=body,
                headers=self._headers(),
            )

        self.assertEqual(response.status_code, 200)
        assert_openapi_response("checkRegisteredSource", response)
        self.assertNotIn("resolved-private-password", response.text)
        command, _actor_id = checker.commands[0]
        self.assertIs(command.authentication_mode, SourceCheckAuthenticationMode.DIRECT)
        self.assertEqual(command.password, "resolved-private-password")
        self.assertNotIn("resolved-private-password", repr(command))

    async def test_failure_rate_limit_missing_and_unavailable_checker(self) -> None:
        result = RegisteredSourceCheckResult(
            checked_at=_NOW,
            expires_at=_NOW + timedelta(seconds=30),
            reason=SourceCheckFailureReason.AUTHENTICATION,
        )
        unsupported_result = RegisteredSourceCheckResult(
            checked_at=_NOW,
            expires_at=_NOW + timedelta(seconds=30),
            reason=SourceCheckFailureReason.UNSUPPORTED,
        )
        cases = (
            (_Checker(result), 200, "authentication"),
            (_Checker(unsupported_result), 200, "unsupported"),
            (
                _Checker(error=RegisteredSourceCheckRateLimited(250)),
                429,
                "rate_limited",
            ),
            (
                _Checker(error=RegisteredSourceCheckUnavailable("private failure")),
                503,
                "service_unavailable",
            ),
            (None, 503, "service_unavailable"),
        )
        for checker, expected_status, expected_code in cases:
            async with await self._client(
                self._build_app(
                    checker=checker, credential_resolver=_CredentialResolver()
                )
            ) as client:
                response = await client.post(
                    "/api/v1/system/sources/check",
                    json=self._body(),
                    headers=self._headers(),
                )
            self.assertEqual(response.status_code, expected_status)
            assert_openapi_response("checkRegisteredSource", response)
            if expected_status == 200:
                self.assertEqual(response.json()["status"], "unreachable")
                self.assertEqual(response.json()["reason"], expected_code)
            else:
                self.assertEqual(response.json()["error"]["code"], expected_code)
                if expected_code == "rate_limited":
                    self.assertEqual(response.json()["error"]["retryAfterMs"], 250)
        self.assertNotIn("private failure", response.text)
