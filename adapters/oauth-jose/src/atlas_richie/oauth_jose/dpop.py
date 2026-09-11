"""JOSERFC implementation of DPoP compact-JWS creation and signature validation."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import uuid4

from joserfc import jwk, jwt

from atlas_richie.oauth import DpopProofClaims, OAuthTokenValidationError, access_token_hash, canonical_dpop_uri

_DPOP_JWT_TYPE = "dpop+jwt"
_DPOP_ALGORITHM = "ES256"
_DPOP_CURVE = "P-256"
_DPOP_PROOF_ID = "jti"
_DPOP_METHOD = "htm"
_DPOP_TARGET_URI = "htu"
_DPOP_ISSUED_AT = "iat"
_DPOP_ACCESS_TOKEN_HASH = "ath"
_DPOP_NONCE = "nonce"
_DPOP_PUBLIC_JWK = "jwk"


class JoseDpopProofFactory:
    """Creates DPoP proofs with one ES256 private key owned by this adapter."""

    @classmethod
    def generate(cls) -> "JoseDpopProofFactory":
        return cls(jwk.generate_key("EC", _DPOP_CURVE))

    def __init__(self, private_key: object) -> None:
        self._private_key = private_key if hasattr(private_key, "as_dict") else jwk.import_key(private_key)
        self._public_jwk = self._private_key.as_dict(private=False)
        self._key_thumbprint = self._private_key.thumbprint()

    @property
    def key_thumbprint(self) -> str:
        return self._key_thumbprint

    def create(
        self,
        *,
        method: str,
        target_uri: str,
        access_token: str | None = None,
        nonce: str | None = None,
        now: datetime | None = None,
    ) -> str:
        claims: dict[str, Any] = {
            _DPOP_PROOF_ID: str(uuid4()),
            _DPOP_METHOD: method.upper(),
            _DPOP_TARGET_URI: canonical_dpop_uri(target_uri),
            _DPOP_ISSUED_AT: int((now or datetime.now(UTC)).timestamp()),
        }
        if access_token is not None:
            claims[_DPOP_ACCESS_TOKEN_HASH] = access_token_hash(access_token)
        if nonce is not None:
            claims[_DPOP_NONCE] = nonce
        return jwt.encode(
            {"typ": _DPOP_JWT_TYPE, "alg": _DPOP_ALGORITHM, _DPOP_PUBLIC_JWK: self._public_jwk},
            claims,
            self._private_key,
            algorithms=(_DPOP_ALGORITHM,),
            default_type=None,
        )


class JoseDpopProofValidator:
    """Verifies an embedded-public-JWK DPoP proof and maps it to core claims."""

    def validate(self, proof: str) -> DpopProofClaims:
        try:
            header = _protected_header(proof)
            if header.get("typ") != _DPOP_JWT_TYPE or header.get("alg") != _DPOP_ALGORITHM:
                raise OAuthTokenValidationError("DPoP protected header is not accepted")
            public_jwk = header.get(_DPOP_PUBLIC_JWK)
            if not isinstance(public_jwk, Mapping):
                raise OAuthTokenValidationError("DPoP protected header requires a public JWK")
            key = jwk.import_key(dict(public_jwk))
            token = jwt.decode(proof, key, algorithms=(_DPOP_ALGORITHM,))
            claims = token.claims
            return DpopProofClaims(
                proof_id=_required_text(claims, _DPOP_PROOF_ID),
                issued_at=_issued_at(claims.get(_DPOP_ISSUED_AT)),
                method=_required_text(claims, _DPOP_METHOD),
                target_uri=_required_text(claims, _DPOP_TARGET_URI),
                key_thumbprint=key.thumbprint(),
                access_token_hash=_optional_text(claims, _DPOP_ACCESS_TOKEN_HASH),
                nonce=_optional_text(claims, _DPOP_NONCE),
            )
        except OAuthTokenValidationError:
            raise
        except Exception as error:
            raise OAuthTokenValidationError("DPoP proof signature validation failed") from error


def _protected_header(proof: str) -> Mapping[str, Any]:
    try:
        encoded, _payload, _signature = proof.split(".")
        padding = "=" * (-len(encoded) % 4)
        header = json.loads(base64.urlsafe_b64decode((encoded + padding).encode("ascii")))
        if not isinstance(header, Mapping):
            raise ValueError("protected header must be an object")
        return header
    except Exception as error:
        raise OAuthTokenValidationError("DPoP protected header is invalid") from error


def _required_text(claims: Mapping[str, Any], name: str) -> str:
    value = _optional_text(claims, name)
    if value is None:
        raise OAuthTokenValidationError(f"DPoP proof requires {name}")
    return value


def _optional_text(claims: Mapping[str, Any], name: str) -> str | None:
    value = claims.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise OAuthTokenValidationError(f"DPoP proof {name} must be a non-blank string")
    return value


def _issued_at(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise OAuthTokenValidationError("DPoP proof iat must be numeric")
    return datetime.fromtimestamp(value, UTC)
