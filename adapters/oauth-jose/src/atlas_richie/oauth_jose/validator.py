"""JOSERFC-backed JWT access-token validation behind the platform contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from joserfc import jwt
from joserfc.jwk import KeySet

from atlas_richie.oauth import AuthenticatedPrincipal, JwkSetSource, OAuthTokenValidationError


class JoseJwtTokenValidator:
    """Validate an RS256 OAuth JWT using a refreshable JWKS source.

    This adapter owns every JOSERFC type.  Its public output is the core
    `AuthenticatedPrincipal`, so applications can replace this adapter without
    changing resource-server code.
    """

    def __init__(
        self,
        jwk_source: JwkSetSource,
        *,
        issuer: str,
        audience: str,
        allowed_algorithms: Sequence[str] = ("RS256",),
        clock_skew: timedelta = timedelta(seconds=30),
    ) -> None:
        if not issuer or not audience or not allowed_algorithms or clock_skew < timedelta():
            raise ValueError("issuer, audience, algorithms, and non-negative clock_skew are required")
        self._jwk_source = jwk_source
        self._issuer = issuer
        self._audience = audience
        self._allowed_algorithms = tuple(allowed_algorithms)
        self._clock_skew = clock_skew

    def validate(self, access_token: str) -> AuthenticatedPrincipal:
        if not access_token:
            raise OAuthTokenValidationError("access token is required")
        try:
            header = _unverified_header(access_token)
            if header.get("alg") not in self._allowed_algorithms:
                raise OAuthTokenValidationError("JWT algorithm is not accepted")
            kid = header.get("kid")
            if not isinstance(kid, str) or not kid:
                raise OAuthTokenValidationError("JWT kid is required")
            document = self._jwk_source.get()
            if not _contains_kid(document, kid):
                document = self._jwk_source.refresh()
            if not _contains_kid(document, kid):
                raise OAuthTokenValidationError("JWT signing key is unknown")
            token = jwt.decode(access_token, KeySet.import_key_set(dict(document)), algorithms=self._allowed_algorithms)
            claims = token.claims
            registry = jwt.JWTClaimsRegistry(
                leeway=int(self._clock_skew.total_seconds()),
                iss={"essential": True, "value": self._issuer},
                aud={"essential": True, "value": self._audience},
                exp={"essential": True},
                sub={"essential": True},
            )
            registry.validate(claims)
            return AuthenticatedPrincipal(
                subject=_claim_string(claims, "sub"),
                client_id=_claim_optional_string(claims, "client_id"),
                issuer=_claim_string(claims, "iss"),
                audience=_audience(claims.get("aud")),
                scopes=_scopes(claims.get("scope")),
                expires_at=_expires_at(claims.get("exp")),
                token_id=_claim_optional_string(claims, "jti"),
                claims=claims,
            )
        except OAuthTokenValidationError:
            raise
        except Exception as error:
            raise OAuthTokenValidationError("JWT access token validation failed") from error


def _unverified_header(access_token: str) -> Mapping[str, Any]:
    """Parse only the compact protected header for key selection; verification follows immediately."""

    try:
        parts = access_token.split(".")
        if len(parts) != 3:
            raise ValueError("not a compact JWT")
        from base64 import urlsafe_b64decode
        import json

        encoded = parts[0] + "=" * (-len(parts[0]) % 4)
        header = json.loads(urlsafe_b64decode(encoded.encode("ascii")))
        if not isinstance(header, Mapping):
            raise ValueError("JWT header is not an object")
        return header
    except Exception as error:
        raise OAuthTokenValidationError("JWT protected header is invalid") from error


def _contains_kid(document: Mapping[str, Any], kid: str) -> bool:
    keys = document.get("keys")
    return isinstance(keys, list) and any(isinstance(key, Mapping) and key.get("kid") == kid for key in keys)


def _claim_string(claims: Mapping[str, Any], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value:
        raise OAuthTokenValidationError(f"JWT {name} is required")
    return value


def _claim_optional_string(claims: Mapping[str, Any], name: str) -> str | None:
    value = claims.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise OAuthTokenValidationError(f"JWT {name} must be a non-blank string")
    return value


def _audience(value: object) -> frozenset[str]:
    if isinstance(value, str) and value:
        return frozenset({value})
    if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
        return frozenset(value)
    raise OAuthTokenValidationError("JWT aud must be a string or string array")


def _scopes(value: object) -> frozenset[str]:
    if value is None:
        return frozenset()
    if not isinstance(value, str):
        raise OAuthTokenValidationError("JWT scope must be a space-delimited string")
    return frozenset(scope for scope in value.split() if scope)


def _expires_at(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise OAuthTokenValidationError("JWT exp must be a numeric epoch value")
    return datetime.fromtimestamp(value, UTC)
