"""Framework-neutral resource-server authentication orchestration."""

from __future__ import annotations

from typing import Protocol

from .client import IntrospectionClient
from .dpop import DpopProofVerifier
from .errors import OAuthTokenValidationError
from .models import AuthenticatedPrincipal, OAuthClientCredentials


class TokenValidator(Protocol):
    """Validate a bearer token and return only framework-neutral principal data."""

    def validate(self, access_token: str) -> AuthenticatedPrincipal:
        """Raise OAuthTokenValidationError for an invalid or unacceptable token."""


class ResourceServerAuthenticator:
    """JWT-first, optional introspection-fallback façade mirroring the Java component flow."""

    def __init__(
        self,
        jwt_validator: TokenValidator | None,
        *,
        introspection_client: IntrospectionClient | None = None,
        introspection_endpoint: str | None = None,
        introspection_credentials: OAuthClientCredentials | None = None,
        expected_issuer: str | None = None,
        expected_audience: str | None = None,
        introspection_fallback: bool = True,
    ) -> None:
        self._jwt_validator = jwt_validator
        self._introspection_client = introspection_client
        self._introspection_endpoint = introspection_endpoint
        self._introspection_credentials = introspection_credentials
        self._expected_issuer = expected_issuer
        self._expected_audience = expected_audience
        self._introspection_fallback = introspection_fallback

    def authenticate(self, access_token: str) -> AuthenticatedPrincipal:
        if not access_token:
            raise OAuthTokenValidationError("access token is required")
        if self._jwt_validator is not None:
            try:
                return self._jwt_validator.validate(access_token)
            except OAuthTokenValidationError:
                if not self._introspection_fallback:
                    raise
        if self._introspection_client is None or self._introspection_endpoint is None or self._introspection_credentials is None:
            raise OAuthTokenValidationError("no accepted resource-server validation path is configured")
        result = self._introspection_client.introspect(
            self._introspection_endpoint,
            self._introspection_credentials,
            access_token,
        )
        if not result.active or not result.subject or not result.issuer:
            raise OAuthTokenValidationError("access token is inactive")
        if self._expected_issuer is not None and result.issuer != self._expected_issuer:
            raise OAuthTokenValidationError("access token issuer is not accepted")
        if self._expected_audience is not None and self._expected_audience not in result.audience:
            raise OAuthTokenValidationError("access token audience is not accepted")
        return AuthenticatedPrincipal(
            subject=result.subject,
            client_id=result.client_id,
            issuer=result.issuer,
            audience=result.audience,
            scopes=result.scopes,
            expires_at=result.expires_at,
            token_id=result.token_id,
            claims=result.claims,
        )

    def authenticate_dpop(
        self,
        access_token: str,
        proof: str,
        *,
        method: str,
        target_uri: str,
        verifier: DpopProofVerifier,
        nonce: str | None = None,
    ) -> AuthenticatedPrincipal:
        """Authenticate a DPoP-bound token and reject missing `cnf.jkt` binding."""

        principal = self.authenticate(access_token)
        confirmation = principal.claims.get("cnf")
        key_thumbprint = confirmation.get("jkt") if isinstance(confirmation, dict) else None
        if not isinstance(key_thumbprint, str) or not key_thumbprint:
            raise OAuthTokenValidationError("DPoP-bound access token confirmation is required")
        verifier.verify(
            proof,
            method=method,
            target_uri=target_uri,
            access_token=access_token,
            expected_key_thumbprint=key_thumbprint,
            nonce=nonce,
        )
        return principal
