import unittest

from atlas_richie.mcp import AuthenticationError
from atlas_richie.mcp_oauth import McpM2mAuthorization, McpM2mTarget, OAuthBearerContextResolver, OAuthDpopContextResolver
from atlas_richie.oauth import AuthenticatedPrincipal, OAuthAccessToken, OAuthTokenValidationError, ResourceIndicator


class OAuthBridgeTests(unittest.TestCase):
    def test_valid_bearer_becomes_token_free_tool_context(self) -> None:
        resolver = OAuthBearerContextResolver(_Authenticator(), resource_metadata_uri="https://api.example/.well-known/oauth-protected-resource/mcp")
        context = resolver({"Authorization": "Bearer secret-not-retained"})
        self.assertEqual("service-a", context.principal_id)
        self.assertEqual(frozenset({"inventory:read"}), context.granted_scopes)
        self.assertEqual("tenant-a", context.tenant_id)

    def test_missing_or_invalid_bearer_returns_a_safe_resource_metadata_challenge(self) -> None:
        resolver = OAuthBearerContextResolver(_Authenticator(invalid=True), resource_metadata_uri="https://api.example/prm")
        with self.assertRaises(AuthenticationError) as captured:
            resolver({"Authorization": "Bearer invalid"})
        self.assertNotIn("invalid", str(captured.exception))
        self.assertEqual('Bearer resource_metadata="https://api.example/prm"', captured.exception.challenge)

    def test_dpop_requires_scheme_and_proof_and_binds_the_mcp_post_resource(self) -> None:
        authenticator = _DpopAuthenticator()
        resolver = OAuthDpopContextResolver(
            authenticator,
            object(),
            resource_metadata_uri="https://api.example/prm",
            target_uri="https://api.example/mcp",
        )
        context = resolver({"Authorization": "DPoP dpop-token", "DPoP": "proof-value"})
        self.assertEqual("service-a", context.principal_id)
        self.assertEqual(("dpop-token", "proof-value", "POST", "https://api.example/mcp"), authenticator.call)
        with self.assertRaises(AuthenticationError):
            resolver({"Authorization": "Bearer token"})

    def test_m2m_profile_obtains_an_exact_resource_dpop_token(self) -> None:
        target = McpM2mTarget(ResourceIndicator("https://peer.example/mcp"), frozenset({"inventory.read"}))
        manager = _TokenManager()
        authorization = McpM2mAuthorization(manager, target)

        self.assertEqual("DPoP peer-token", authorization.authorization_for())
        self.assertEqual((target.resource, target.required_scopes), manager.call)
        with self.assertRaises(ValueError):
            McpM2mAuthorization(_TokenManager(token_type="Bearer"), target).authorization_for()


class _Authenticator:
    def __init__(self, invalid=False):
        self.invalid = invalid
    def authenticate(self, _token):
        if self.invalid:
            raise OAuthTokenValidationError("invalid")
        return AuthenticatedPrincipal("service-a", "client-a", "https://issuer.example", frozenset({"https://api.example/mcp"}), frozenset({"inventory:read"}), None, claims={"tenant_id": "tenant-a"})


class _DpopAuthenticator(_Authenticator):
    def __init__(self):
        super().__init__()
        self.call = None

    def authenticate_dpop(self, access_token, proof, *, method, target_uri, verifier, nonce):  # type: ignore[no-untyped-def]
        self.call = (access_token, proof, method, target_uri)
        return self.authenticate(access_token)


class _TokenManager:
    def __init__(self, token_type="DPoP"):
        self.token_type = token_type
        self.call = None

    def token_for(self, resource, scopes):
        self.call = (resource, scopes)
        return OAuthAccessToken("peer-token", token_type=self.token_type, resource=resource, scopes=scopes)


if __name__ == "__main__":
    unittest.main()
