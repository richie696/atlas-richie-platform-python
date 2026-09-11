import base64
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx

from atlas_richie.http import HttpClient
from atlas_richie.oauth import (
    AllowHttpEndpointPolicy,
    AuthenticatedPrincipal,
    HttpJwkSetSource,
    OAuthAccessToken,
    OAuthAuthorizationServerMetadata,
    OAuthClientCredentials,
    OAuthIntrospectionResult,
    OAuthMetadataClient,
    OAuthResourceMismatch,
    OAuthEndpointError,
    OAuthTokenClient,
    OAuthTokenManager,
    OAuthTokenResponse,
    OAuthTokenValidationError,
    PkcePair,
    PkceS256,
    ResourceIndicator,
    ResourceServerAuthenticator,
)


def _controlled_client(transport: httpx.BaseTransport):
    return patch(
        "atlas_richie.http.client._HttpxClientFactory.create_sync",
        return_value=httpx.Client(transport=transport),
    )


class _Requester:
    def __init__(self) -> None:
        self.calls: list[tuple[str, frozenset[str]]] = []

    def client_credentials(self, _endpoint, _credentials, resource, scopes):  # type: ignore[no-untyped-def]
        self.calls.append((resource.value, scopes))
        return OAuthTokenResponse(
            OAuthAccessToken("new-access", datetime.now(UTC) + timedelta(hours=1), scopes=scopes, resource=resource),
            granted_scopes=scopes,
        )

    def refresh_token(self, _endpoint, _credentials, _refresh, resource, scopes):  # type: ignore[no-untyped-def]
        return self.client_credentials(_endpoint, _credentials, resource, scopes)


class _InactiveIntrospection:
    def introspect(self, _endpoint, _credentials, _token):  # type: ignore[no-untyped-def]
        return OAuthIntrospectionResult(active=False)


class _ActiveIntrospection:
    def introspect(self, _endpoint, _credentials, _token):  # type: ignore[no-untyped-def]
        return OAuthIntrospectionResult(
            active=True,
            subject="service-a",
            issuer="https://issuer.test",
            audience=frozenset({"https://resource.test"}),
            scopes=frozenset({"mcp.read"}),
        )


class _RejectingValidator:
    def validate(self, _access_token: str) -> AuthenticatedPrincipal:
        raise OAuthTokenValidationError("not a JWT")


class _DpopFactory:
    def __init__(self) -> None:
        self.call = None

    def create(self, *, method, target_uri, access_token=None, nonce=None):  # type: ignore[no-untyped-def]
        self.call = (method, target_uri)
        return "proof-value"


class OAuthComponentTests(unittest.TestCase):
    def test_pkce_is_s256_only_and_constant_contract_rejects_tampering(self) -> None:
        pair = PkcePair.generate()
        self.assertEqual("S256", pair.method)
        self.assertGreaterEqual(len(pair.verifier), 43)
        self.assertTrue(PkceS256.verify(verifier=pair.verifier, expected_challenge=pair.challenge))
        self.assertFalse(PkceS256.verify(verifier=pair.verifier + "x", expected_challenge=pair.challenge))
        self.assertFalse(PkceS256.verify(verifier=pair.verifier, expected_challenge=pair.challenge, method="plain"))

    def test_client_credentials_form_is_resource_bound_and_has_no_transport_type(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200,
                json={"access_token": "opaque-secret", "expires_in": 3600, "scope": "mcp.read reports.read"},
                request=request,
            )

        with _controlled_client(httpx.MockTransport(handler)):
            with HttpClient() as http_client:
                client = OAuthTokenClient(http_client)
                token = client.client_credentials(
                    "https://issuer.test/oauth/token",
                    OAuthClientCredentials("client-a", "top-secret"),
                    ResourceIndicator("https://resource.test/mcp"),
                    frozenset({"reports.read", "mcp.read"}),
                )

        form = parse_qs(captured[0].content.decode("utf-8"))
        self.assertEqual(["client_credentials"], form["grant_type"])
        self.assertEqual(["client-a"], form["client_id"])
        self.assertEqual(["https://resource.test/mcp"], form["resource"])
        self.assertEqual(["mcp.read reports.read"], form["scope"])
        expected_basic = base64.b64encode(b"client-a:top-secret").decode("ascii")
        self.assertEqual(f"Basic {expected_basic}", captured[0].headers["Authorization"])
        self.assertEqual(frozenset({"mcp.read", "reports.read"}), token.access_token.scopes)
        self.assertNotIn("httpx", __import__("atlas_richie.oauth", fromlist=["x"]).__all__)

    def test_token_request_includes_a_dpop_proof_from_an_explicit_factory(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json={"access_token": "access", "expires_in": 60}, request=request)

        factory = _DpopFactory()
        with _controlled_client(httpx.MockTransport(handler)):
            with HttpClient() as http_client:
                OAuthTokenClient(http_client, dpop_proof_factory=factory).client_credentials(
                    "https://issuer.test/token", OAuthClientCredentials("client", "secret"),
                    ResourceIndicator("https://resource.test/mcp"), frozenset()
                )
        self.assertEqual("proof-value", captured[0].headers["DPoP"])
        self.assertEqual(("POST", "https://issuer.test/token"), factory.call)

    def test_manager_isolates_resource_and_merges_scopes_before_one_refresh(self) -> None:
        requester = _Requester()
        resource = ResourceIndicator("https://resource.test/mcp")
        manager = OAuthTokenManager(
            requester,
            token_endpoint="https://issuer.test/token",
            credentials=OAuthClientCredentials("client", "secret"),
            resource=resource,
            configured_scopes=frozenset({"mcp.read"}),
        )
        token = manager.token_for(resource, frozenset({"reports.read"}))
        self.assertEqual(frozenset({"mcp.read", "reports.read"}), token.scopes)
        self.assertEqual(1, len(requester.calls))
        self.assertIs(token, manager.token_for(resource, frozenset({"mcp.read"})))
        with self.assertRaises(OAuthResourceMismatch):
            manager.token_for(ResourceIndicator("https://other-resource.test/mcp"))

    def test_oauth_error_never_reflects_untrusted_endpoint_value(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "opaque-access-token"}, request=request)

        with _controlled_client(httpx.MockTransport(handler)):
            with HttpClient() as http_client:
                client = OAuthTokenClient(http_client)
                with self.assertRaises(OAuthEndpointError) as raised:
                    client.client_credentials(
                        "https://issuer.test/oauth/token",
                        OAuthClientCredentials("client-a", "top-secret"),
                        ResourceIndicator("https://resource.test/mcp"),
                        frozenset({"mcp.read"}),
                    )

        self.assertEqual("oauth_endpoint_error", raised.exception.error)
        self.assertNotIn("opaque-access-token", str(raised.exception))

    def test_public_authorization_code_client_uses_pkce_and_omits_basic_auth(self) -> None:
        captured: list[httpx.Request] = []
        pair = PkcePair.generate()

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json={"access_token": "access", "expires_in": 120}, request=request)

        with _controlled_client(httpx.MockTransport(handler)):
            with HttpClient() as http_client:
                OAuthTokenClient(http_client).authorization_code(
                    "https://issuer.test/token",
                    OAuthClientCredentials("public-client"),
                    code="authorization-code",
                    redirect_uri="https://client.test/callback",
                    code_verifier=pair.verifier,
                    resource=ResourceIndicator("https://resource.test/mcp"),
                )

        self.assertNotIn("Authorization", captured[0].headers)
        self.assertEqual(["public-client"], parse_qs(captured[0].content.decode())["client_id"])

    def test_device_revocation_registration_and_userinfo_are_remote_client_capabilities(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if request.url.path == "/device":
                return httpx.Response(
                    200,
                    json={
                        "device_code": "device-secret",
                        "user_code": "ABCD-EFGH",
                        "verification_uri": "https://issuer.test/verify",
                        "expires_in": 600,
                        "interval": 7,
                    },
                    request=request,
                )
            if request.url.path == "/register":
                return httpx.Response(
                    201,
                    json={"client_id": "registered-client", "client_secret": "registered-secret"},
                    request=request,
                )
            if request.url.path == "/userinfo":
                return httpx.Response(200, json={"sub": "service-a", "tenant": "alpha"}, request=request)
            return httpx.Response(200, request=request)

        credentials = OAuthClientCredentials("client-a", "top-secret")
        resource = ResourceIndicator("https://resource.test/mcp")
        access_token = OAuthAccessToken("access-secret", resource=resource)
        with _controlled_client(httpx.MockTransport(handler)):
            with HttpClient() as http_client:
                client = OAuthTokenClient(http_client)
                device = client.device_authorization(
                    "https://issuer.test/device", credentials, resource=resource, scopes=frozenset({"mcp.read"})
                )
                client.revoke("https://issuer.test/revoke", credentials, token="access-secret", token_type_hint="access_token")
                registration = client.register_client(
                    "https://issuer.test/register", {"redirect_uris": ["https://client.test/callback"]}
                )
                userinfo = client.user_info("https://issuer.test/userinfo", access_token)

        self.assertEqual("ABCD-EFGH", device.user_code)
        self.assertEqual(7, device.interval_seconds)
        self.assertEqual("registered-client", registration.client_id)
        self.assertEqual("service-a", userinfo.subject)
        self.assertEqual(["access_token"], parse_qs(captured[1].content.decode())["token_type_hint"])
        self.assertEqual("Bearer access-secret", captured[3].headers["Authorization"])

    def test_metadata_jwks_and_hybrid_resource_authenticator(self) -> None:
        hits: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            hits.append(str(request.url))
            if request.url.path == "/metadata":
                return httpx.Response(
                    200,
                    json={
                        "issuer": "https://issuer.test",
                        "token_endpoint": "https://issuer.test/token",
                        "jwks_uri": "https://issuer.test/jwks",
                        "code_challenge_methods_supported": ["S256"],
                    },
                    request=request,
                )
            return httpx.Response(200, json={"keys": [{"kid": "one", "kty": "RSA"}]}, request=request)

        with _controlled_client(httpx.MockTransport(handler)):
            with HttpClient() as http_client:
                metadata = OAuthMetadataClient(http_client).authorization_server("https://issuer.test/metadata")
                jwks = HttpJwkSetSource(http_client, metadata.jwks_uri or "").get()

        self.assertIsInstance(metadata, OAuthAuthorizationServerMetadata)
        self.assertEqual("https://issuer.test", metadata.issuer)
        self.assertEqual("one", jwks["keys"][0]["kid"])
        self.assertEqual(["https://issuer.test/metadata", "https://issuer.test/jwks"], hits)

        auth = ResourceServerAuthenticator(
            _RejectingValidator(),
            introspection_client=_ActiveIntrospection(),
            introspection_endpoint="https://issuer.test/introspect",
            introspection_credentials=OAuthClientCredentials("resource", "secret"),
            expected_issuer="https://issuer.test",
            expected_audience="https://resource.test",
        )
        self.assertEqual("service-a", auth.authenticate("opaque-token").subject)
        inactive = ResourceServerAuthenticator(
            None,
            introspection_client=_InactiveIntrospection(),
            introspection_endpoint="https://issuer.test/introspect",
            introspection_credentials=OAuthClientCredentials("resource", "secret"),
        )
        with self.assertRaises(OAuthTokenValidationError):
            inactive.authenticate("opaque-token")


if __name__ == "__main__":
    unittest.main()
