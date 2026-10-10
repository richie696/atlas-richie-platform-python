"""HTTP contract tests for the guarded bootstrap configuration-source check."""

from __future__ import annotations

import unittest

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.bootstrap_source_check import (
    BootstrapSourceCandidate,
    BootstrapSourceCheckResult,
    BootstrapSourceCheckUnavailable,
    BootstrapSourceFailureReason,
    ConsulDirectCredentials,
    NacosDirectCredentials,
)
from atlas_richie.sentinel_console.application.source_credential_references import (
    ResolvedSourceCredentials,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.application.issue_csrf_nonce import IssueCsrfNonce
from atlas_richie.sentinel_console.api.bootstrap_source_check import (
    parse_source_candidate,
)
from session_test_doubles import UnusedSessionRevoker


class _InitializationReader:
    async def is_initialized(self) -> bool:
        return False


class _SetupWindowReader:
    async def is_setup_window_open(self) -> bool:
        return True


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return opaque_session == "operator-session"


class _SessionReader:
    async def read_active_session(self, session_digest: str):
        return None


class _AccountDirectoryReader:
    async def list_accounts(self, query):
        return ()

    async def read_account(self, account_id: str):
        return None


class _Checker:
    def __init__(self, result: BootstrapSourceCheckResult) -> None:
        self.result = result
        self.candidates: list[BootstrapSourceCandidate] = []

    async def check(self, candidate: BootstrapSourceCandidate):
        self.candidates.append(candidate)
        return self.result


class _UnavailableChecker:
    async def check(self, candidate: BootstrapSourceCandidate):
        raise BootstrapSourceCheckUnavailable("private connector detail")


class _ReferenceResolver:
    async def resolve(self, provider, reference):
        if reference != "secret://configuration-source/prod":
            return None
        if provider is ConfigurationSourceProvider.NACOS:
            return ResolvedSourceCredentials(
                provider, username="operator", password="resolved-secret"
            )
        return ResolvedSourceCredentials(provider, acl_token="resolved-secret")


class _FailingReferenceResolver:
    async def resolve(self, provider, reference):
        raise RuntimeError("vault backend detail must not leak")


class BootstrapSourceCheckApiTest(unittest.IsolatedAsyncioTestCase):
    def _build_app(
        self, *, authorized: bool = True, checker=None, credential_resolver=None
    ):
        return build_app(
            bootstrap_initialization_reader=_InitializationReader(),
            setup_window_reader=_SetupWindowReader(),
            bootstrap_operator_verifier=_OperatorVerifier()
            if authorized
            else _NeverOperatorVerifier(),
            current_session_reader=_SessionReader(),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=_AccountDirectoryReader(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            bootstrap_source_checker=checker,
            source_credential_reference_resolver=credential_resolver,
        )

    async def _client(self, app):
        return AsyncClient(
            transport=ASGITransport(app=app), base_url="https://console.test"
        )

    @staticmethod
    def _headers(nonce: str):
        return {
            "origin": "https://console.test",
            "x-request-id": "source-check-1",
            "x-sentinel-csrf": nonce,
        }

    @staticmethod
    def _cookies(nonce: str, *, authorized: bool = True):
        cookies = {"__Host-sentinel_csrf": nonce}
        if authorized:
            cookies["sentinel_bootstrap"] = "operator-session"
        return cookies

    async def test_nacos_direct_credentials_are_ephemeral(self) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        checker = _Checker(BootstrapSourceCheckResult(reachable=True))
        body = {
            "provider": "nacos",
            "endpoint": "https://nacos.internal:8848",
            "namespace": "sentinel",
            "authentication": {
                "mode": "direct",
                "username": "operator",
                "password": "secret-that-must-not-leak",
            },
        }
        async with await self._client(self._build_app(checker=checker)) as client:
            response = await client.post(
                "/api/v1/system/bootstrap/source-check",
                json=body,
                headers=self._headers(nonce),
                cookies=self._cookies(nonce),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "reachable"})
        candidate = checker.candidates[0]
        self.assertEqual(candidate.location, "sentinel")
        self.assertIsInstance(candidate.authentication, NacosDirectCredentials)
        self.assertNotIn("secret-that-must-not-leak", repr(candidate))
        self.assertNotIn("secret-that-must-not-leak", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_consul_direct_acl_token_maps_to_datacenter(self) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        checker = _Checker(
            BootstrapSourceCheckResult(
                reachable=False,
                reason=BootstrapSourceFailureReason.AUTHENTICATION,
            )
        )
        async with await self._client(self._build_app(checker=checker)) as client:
            response = await client.post(
                "/api/v1/system/bootstrap/source-check",
                json={
                    "provider": "consul",
                    "endpoint": "https://consul.internal:8501",
                    "datacenter": "dc-a",
                    "authentication": {"mode": "direct", "aclToken": "private-token"},
                },
                headers=self._headers(nonce),
                cookies=self._cookies(nonce),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"status": "unreachable", "reason": "authentication"}
        )
        self.assertEqual(checker.candidates[0].location, "dc-a")
        self.assertIsInstance(
            checker.candidates[0].authentication, ConsulDirectCredentials
        )
        self.assertNotIn("private-token", repr(checker.candidates[0]))

    async def test_external_reference_is_resolved_before_bootstrap_probe(self) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        checker = _Checker(BootstrapSourceCheckResult(reachable=True))
        bodies = (
            {
                "provider": "nacos",
                "endpoint": "https://nacos.internal:8848",
                "namespace": "sentinel",
                "authentication": {
                    "mode": "credential-reference",
                    "reference": "secret://configuration-source/prod",
                },
            },
            {
                "provider": "consul",
                "endpoint": "https://consul.internal:8501",
                "datacenter": "dc-a",
                "authentication": {
                    "mode": "credential-reference",
                    "reference": "secret://configuration-source/prod",
                },
            },
        )
        async with await self._client(
            self._build_app(
                checker=checker, credential_resolver=_ReferenceResolver()
            )
        ) as client:
            responses = [
                await client.post(
                    "/api/v1/system/bootstrap/source-check",
                    json=body,
                    headers=self._headers(nonce),
                    cookies=self._cookies(nonce),
                )
                for body in bodies
            ]

        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertIsInstance(checker.candidates[0].authentication, NacosDirectCredentials)
        self.assertEqual(checker.candidates[0].authentication.password, "resolved-secret")
        self.assertIsInstance(checker.candidates[1].authentication, ConsulDirectCredentials)
        self.assertEqual(checker.candidates[1].authentication.acl_token, "resolved-secret")
        self.assertNotIn("resolved-secret", "".join(response.text for response in responses))
        self.assertNotIn("resolved-secret", repr(checker.candidates))

    async def test_external_reference_without_resolver_fails_before_probe(self) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        checker = _Checker(BootstrapSourceCheckResult(reachable=True))
        body = {
            "provider": "nacos",
            "endpoint": "https://nacos.internal:8848",
            "namespace": "sentinel",
            "authentication": {
                "mode": "credential-reference",
                "reference": "secret://configuration-source/prod",
            },
        }
        async with await self._client(self._build_app(checker=checker)) as client:
            response = await client.post(
                "/api/v1/system/bootstrap/source-check",
                json=body,
                headers=self._headers(nonce),
                cookies=self._cookies(nonce),
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(checker.candidates, [])

    async def test_external_resolver_failure_is_redacted_and_fails_closed(self) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        checker = _Checker(BootstrapSourceCheckResult(reachable=True))
        body = {
            "provider": "nacos",
            "endpoint": "https://nacos.internal:8848",
            "namespace": "sentinel",
            "authentication": {
                "mode": "credential-reference",
                "reference": "secret://configuration-source/prod",
            },
        }
        async with await self._client(
            self._build_app(
                checker=checker,
                credential_resolver=_FailingReferenceResolver(),
            )
        ) as client:
            response = await client.post(
                "/api/v1/system/bootstrap/source-check",
                json=body,
                headers=self._headers(nonce),
                cookies=self._cookies(nonce),
            )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("vault backend detail", response.text)
        self.assertEqual(checker.candidates, [])

    async def test_unauthorized_operator_does_not_call_checker(self) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        checker = _Checker(BootstrapSourceCheckResult(reachable=True))
        async with await self._client(
            self._build_app(authorized=False, checker=checker)
        ) as client:
            response = await client.post(
                "/api/v1/system/bootstrap/source-check",
                json=_valid_nacos_body(),
                headers=self._headers(nonce),
                cookies=self._cookies(nonce, authorized=False),
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(checker.candidates, [])

    async def test_invalid_provider_payloads_never_reach_checker(self) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        checker = _Checker(BootstrapSourceCheckResult(reachable=True))
        invalid_bodies = [
            {**_valid_nacos_body(), "unexpected": "property"},
            {
                **_valid_nacos_body(),
                "endpoint": "https://user:password@nacos.internal",
            },
            {**_valid_nacos_body(), "endpoint": "http://:80"},
            {**_valid_nacos_body(), "endpoint": "https://nacos.internal:99999"},
            {**_valid_nacos_body(), "endpoint": "https://nacos.internal:abc"},
            {**_valid_nacos_body(), "endpoint": "http://256.256.256.256"},
            {**_valid_nacos_body(), "endpoint": "https://exa%mple.internal"},
            {
                **_valid_nacos_body(),
                "authentication": {
                    "mode": "direct",
                    "username": "operator",
                    "password": "secret",
                    "extra": "not-allowed",
                },
            },
            {
                **_valid_nacos_body(),
                "datacenter": "must-not-alias-namespace",
            },
        ]
        async with await self._client(self._build_app(checker=checker)) as client:
            for body in invalid_bodies:
                response = await client.post(
                    "/api/v1/system/bootstrap/source-check",
                    json=body,
                    headers=self._headers(nonce),
                    cookies=self._cookies(nonce),
                )
                self.assertEqual(response.status_code, 400)
        self.assertEqual(checker.candidates, [])

    async def test_source_check_uses_utf16_bounds_and_nonblank_identifiers(self) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        checker = _Checker(BootstrapSourceCheckResult(reachable=True))
        nacos = {
            "provider": "nacos",
            "endpoint": "https://nacos.internal:8848",
            "namespace": "sentinel",
            "authentication": {"mode": "none"},
        }
        consul = {
            "provider": "consul",
            "endpoint": "https://consul.internal:8501",
            "datacenter": "dc-a",
            "authentication": {"mode": "none"},
        }
        invalid_bodies = [
            {**nacos, "endpoint": "https://nacos.internal/" + "a" * 2025 + "🌋"},
            {**nacos, "namespace": "🌋" * 101},
            {
                **nacos,
                "authentication": {
                    "mode": "credential-reference",
                    "reference": "secret://" + "🌋" * 252,
                },
            },
            {
                **nacos,
                "authentication": {
                    "mode": "credential-reference",
                    "reference": "\u001c",
                },
            },
            {
                **nacos,
                "authentication": {
                    "mode": "direct",
                    "username": "\u0085",
                    "password": "secret",
                },
            },
            {
                **nacos,
                "authentication": {
                    "mode": "direct",
                    "username": "🌋" * 101,
                    "password": "secret",
                },
            },
            {
                **nacos,
                "authentication": {
                    "mode": "direct",
                    "username": "operator",
                    "password": "🌋" * 513,
                },
            },
            {**consul, "datacenter": "🌋" * 101},
            {
                **consul,
                "authentication": {"mode": "direct", "aclToken": "🌋" * 513},
            },
        ]
        async with await self._client(self._build_app(checker=checker)) as client:
            responses = [
                await client.post(
                    "/api/v1/system/bootstrap/source-check",
                    json=body,
                    headers=self._headers(nonce),
                    cookies=self._cookies(nonce),
                )
                for body in invalid_bodies
            ]

        self.assertEqual([response.status_code for response in responses], [400] * len(invalid_bodies))
        self.assertEqual(checker.candidates, [])

    def test_source_candidate_rejects_lone_surrogates(self) -> None:
        body = _valid_nacos_body()
        body["namespace"] = "invalid-\ud800"
        self.assertIsNone(parse_source_candidate(body))

    async def test_missing_or_unavailable_connector_fails_closed(self) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        async with await self._client(self._build_app()) as client:
            missing = await client.post(
                "/api/v1/system/bootstrap/source-check",
                json=_valid_nacos_body(),
                headers=self._headers(nonce),
                cookies=self._cookies(nonce),
            )
        checker_app = self._build_app(checker=_UnavailableChecker())
        async with await self._client(checker_app) as client:
            unavailable = await client.post(
                "/api/v1/system/bootstrap/source-check",
                json=_valid_nacos_body(),
                headers=self._headers(nonce),
                cookies=self._cookies(nonce),
            )
        self.assertEqual(missing.status_code, 503)
        self.assertEqual(unavailable.status_code, 503)
        self.assertNotIn("private connector detail", unavailable.text)


class _NeverOperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


def _valid_nacos_body():
    return {
        "provider": "nacos",
        "endpoint": "https://nacos.internal:8848",
        "namespace": "sentinel",
        "authentication": {"mode": "none"},
    }
