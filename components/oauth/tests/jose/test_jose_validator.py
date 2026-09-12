import time
import unittest
from typing import Any, Mapping

from joserfc import jwt
from joserfc.jwk import RSAKey

from atlas_richie.oauth import OAuthTokenValidationError
from atlas_richie.oauth.jose import JoseJwtTokenValidator


class _JwkSource:
    def __init__(self, current: Mapping[str, Any], refreshed: Mapping[str, Any] | None = None) -> None:
        self.current = current
        self.refreshed = refreshed or current
        self.refreshes = 0

    def get(self) -> Mapping[str, Any]:
        return self.current

    def refresh(self) -> Mapping[str, Any]:
        self.refreshes += 1
        return self.refreshed


def _document(key: RSAKey) -> Mapping[str, Any]:
    return {"keys": [key.as_dict(is_private=False)]}


def _signed(key: RSAKey, *, issuer: str = "https://issuer.test", audience: str = "https://resource.test") -> str:
    return jwt.encode(
        {"alg": "RS256", "kid": key.kid},
        {
            "iss": issuer,
            "sub": "service-a",
            "aud": audience,
            "exp": int(time.time()) + 120,
            "scope": "mcp.read reports.read",
            "client_id": "client-a",
            "jti": "jti-1",
        },
        key,
    )


class JoseJwtTokenValidatorTests(unittest.TestCase):
    def test_validates_signature_and_registered_oauth_claims(self) -> None:
        key = RSAKey.generate_key(auto_kid=True)
        validator = JoseJwtTokenValidator(_JwkSource(_document(key)), issuer="https://issuer.test", audience="https://resource.test")
        principal = validator.validate(_signed(key))
        self.assertEqual("service-a", principal.subject)
        self.assertEqual(frozenset({"mcp.read", "reports.read"}), principal.scopes)
        self.assertEqual("client-a", principal.client_id)

    def test_unknown_kid_refreshes_once_and_wrong_issuer_fails_closed(self) -> None:
        old_key = RSAKey.generate_key(auto_kid=True)
        new_key = RSAKey.generate_key(auto_kid=True)
        source = _JwkSource(_document(old_key), _document(new_key))
        validator = JoseJwtTokenValidator(source, issuer="https://issuer.test", audience="https://resource.test")
        validator.validate(_signed(new_key))
        self.assertEqual(1, source.refreshes)
        with self.assertRaises(OAuthTokenValidationError):
            validator.validate(_signed(new_key, issuer="https://other-issuer.test"))


if __name__ == "__main__":
    unittest.main()
