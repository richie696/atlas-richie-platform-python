"""Convert bearer authentication into an MCP context without retaining token material."""

from __future__ import annotations

from collections.abc import Mapping

from atlas_richie.mcp import AuthenticationError, ToolContext
from atlas_richie.oauth import DpopProofVerifier, OAuthTokenValidationError, ResourceServerAuthenticator

_BEARER_SCHEME = "Bearer"
_DPOP_SCHEME = "DPoP"
_AUTHORIZATION_HEADER = "authorization"
_DPOP_HEADER = "dpop"
_POST_METHOD = "POST"


class OAuthMcpAuthenticationError(AuthenticationError):
    """Authentication failure that carries only a standards-safe HTTP challenge."""

    def __init__(self, challenge: str) -> None:
        super().__init__(-32001, "Unauthorized", {"challenge": challenge})

    @property
    def challenge(self) -> str:
        return str((self.data or {}).get("challenge", "Bearer"))


class OAuthBearerContextResolver:
    """ASGI/WSGI-neutral header resolver backed by the owned OAuth component."""

    def __init__(self, authenticator: ResourceServerAuthenticator, *, resource_metadata_uri: str) -> None:
        if not resource_metadata_uri.strip():
            raise ValueError("resource_metadata_uri is required")
        self._authenticator = authenticator
        self._challenge = f'Bearer resource_metadata="{resource_metadata_uri}"'

    def __call__(self, headers: Mapping[str, str]) -> ToolContext:
        access_token = _scheme_token(_header(headers, _AUTHORIZATION_HEADER), _BEARER_SCHEME)
        if access_token is None:
            raise OAuthMcpAuthenticationError(self._challenge)
        try:
            principal = self._authenticator.authenticate(access_token)
        except OAuthTokenValidationError as error:
            raise OAuthMcpAuthenticationError(self._challenge) from error
        return _context(principal)


class OAuthDpopContextResolver:
    """Resolve a DPoP-bound token for one explicitly mounted MCP resource URI."""

    def __init__(
        self,
        authenticator: ResourceServerAuthenticator,
        verifier: DpopProofVerifier,
        *,
        resource_metadata_uri: str,
        target_uri: str,
        nonce: str | None = None,
    ) -> None:
        if not resource_metadata_uri.strip() or not target_uri.strip():
            raise ValueError("resource_metadata_uri and target_uri are required")
        self._authenticator = authenticator
        self._verifier = verifier
        self._target_uri = target_uri
        self._nonce = nonce
        self._challenge = f'DPoP resource_metadata="{resource_metadata_uri}"'

    def __call__(self, headers: Mapping[str, str]) -> ToolContext:
        access_token = _scheme_token(_header(headers, _AUTHORIZATION_HEADER), _DPOP_SCHEME)
        proof = _header(headers, _DPOP_HEADER)
        if access_token is None or proof is None or not proof.strip():
            raise OAuthMcpAuthenticationError(self._challenge)
        try:
            principal = self._authenticator.authenticate_dpop(
                access_token,
                proof,
                method=_POST_METHOD,
                target_uri=self._target_uri,
                verifier=self._verifier,
                nonce=self._nonce,
            )
        except OAuthTokenValidationError as error:
            raise OAuthMcpAuthenticationError(self._challenge) from error
        return _context(principal)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    return next((value for key, value in headers.items() if key.casefold() == name), None)


def _scheme_token(value: str | None, scheme: str) -> str | None:
    if value is None:
        return None
    actual_scheme, separator, token = value.partition(" ")
    return token.strip() if separator and actual_scheme.casefold() == scheme.casefold() and token.strip() else None


def _context(principal) -> ToolContext:  # type: ignore[no-untyped-def]
    return ToolContext(
        principal_id=principal.subject,
        principal_kind="service" if principal.client_id else "user",
        tenant_id=_tenant(principal.claims),
        granted_scopes=principal.scopes,
    )


def _tenant(claims: Mapping[str, object]) -> str | None:
    value = claims.get("tenant_id") or claims.get("tenantId")
    return value if isinstance(value, str) and value else None
