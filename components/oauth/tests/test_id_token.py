"""Unit tests for OIDC ID Token validation."""

from __future__ import annotations

import base64
import hashlib
import unittest
from datetime import UTC, datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Mapping

from atlas_richie.oauth import (
    AuthenticatedPrincipal,
    IdTokenValidator,
    OAuthTokenValidationError,
    TokenValidator,
    code_hash,
)


def _hash_left_half(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class _FakeJwtValidator:
    """A `TokenValidator` that returns a configurable principal without real JWS work."""

    def __init__(
        self,
        *,
        issuer: str = "iss",
        audience: str = "aud",
        subject: str = "user-1",
        client_id: str | None = "client-id-1",
        extra_claims: Mapping[str, Any] | None = None,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._subject = subject
        self._client_id = client_id
        self._extra = dict(extra_claims or {})

    def validate(self, access_token: str) -> AuthenticatedPrincipal:
        claims: dict[str, Any] = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": self._subject,
            "client_id": self._client_id,
            "exp": int(datetime.now(UTC).timestamp()) + 600,
        }
        claims.update(self._extra)
        return AuthenticatedPrincipal(
            subject=self._subject,
            client_id=self._client_id,
            issuer=self._issuer,
            audience=frozenset({self._audience}),
            scopes=frozenset(),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            claims=MappingProxyType(claims),
        )


class CodeHashTest(unittest.TestCase):
    def test_matches_at_hash_algorithm(self) -> None:
        # Per OIDC Core 1.0 §3.1.3.7, at_hash and c_hash use the same algorithm.
        sample = "auth-code-xyz"
        self.assertEqual(_hash_left_half(sample), code_hash(sample))

    def test_rejects_empty_code(self) -> None:
        from atlas_richie.oauth import OAuthConfigurationError

        with self.assertRaises(OAuthConfigurationError):
            code_hash("")


class IdTokenValidatorConfigurationTest(unittest.TestCase):
    def test_rejects_invalid_configuration(self) -> None:
        jwt = _FakeJwtValidator()
        with self.assertRaises(ValueError):
            IdTokenValidator(jwt, expected_issuer="", expected_audience="aud")
        with self.assertRaises(ValueError):
            IdTokenValidator(jwt, expected_issuer="iss", expected_audience="")
        with self.assertRaises(ValueError):
            IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud", clock_skew=timedelta(seconds=-1))
        with self.assertRaises(ValueError):
            IdTokenValidator(  # type: ignore[arg-type]
                None,  # type: ignore[arg-type]
                expected_issuer="iss",
                expected_audience="aud",
            )

    def test_rejects_empty_id_token(self) -> None:
        validator = IdTokenValidator(_FakeJwtValidator(), expected_issuer="iss", expected_audience="aud")
        with self.assertRaises(OAuthTokenValidationError):
            validator.validate("")


class IdTokenValidatorPrincipalChecksTest(unittest.TestCase):
    def test_rejects_wrong_issuer(self) -> None:
        jwt = _FakeJwtValidator(issuer="https://other")
        validator = IdTokenValidator(jwt, expected_issuer="https://expected", expected_audience="aud")
        with self.assertRaises(OAuthTokenValidationError):
            validator.validate("token")

    def test_rejects_wrong_audience(self) -> None:
        jwt = _FakeJwtValidator(audience="other-aud")
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        with self.assertRaises(OAuthTokenValidationError):
            validator.validate("token")

    def test_rejects_wrong_client_id_when_expected(self) -> None:
        jwt = _FakeJwtValidator(client_id="client-1")
        validator = IdTokenValidator(
            jwt,
            expected_issuer="iss",
            expected_audience="aud",
            expected_client_id="client-2",
        )
        with self.assertRaises(OAuthTokenValidationError):
            validator.validate("token")

    def test_accepts_matching_client_id(self) -> None:
        jwt = _FakeJwtValidator(client_id="client-1")
        validator = IdTokenValidator(
            jwt,
            expected_issuer="iss",
            expected_audience="aud",
            expected_client_id="client-1",
        )
        principal = validator.validate("token")
        self.assertEqual("user-1", principal.subject)


class IdTokenValidatorNonceTest(unittest.TestCase):
    def test_nonce_matches(self) -> None:
        jwt = _FakeJwtValidator(extra_claims={"nonce": "expected-nonce"})
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        principal = validator.validate("token", expected_nonce="expected-nonce")
        self.assertEqual("user-1", principal.subject)

    def test_nonce_mismatch(self) -> None:
        jwt = _FakeJwtValidator(extra_claims={"nonce": "actual"})
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        with self.assertRaises(OAuthTokenValidationError):
            validator.validate("token", expected_nonce="expected")

    def test_nonce_missing(self) -> None:
        jwt = _FakeJwtValidator()  # no nonce
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        with self.assertRaises(OAuthTokenValidationError):
            validator.validate("token", expected_nonce="expected")

    def test_nonce_check_skipped_when_not_expected(self) -> None:
        jwt = _FakeJwtValidator()  # no nonce claim
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        principal = validator.validate("token")
        self.assertEqual("user-1", principal.subject)


class IdTokenValidatorMaxAgeTest(unittest.TestCase):
    def test_max_age_within_bounds(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        jwt = _FakeJwtValidator(extra_claims={"auth_time": int(now.timestamp()) - 30})
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        principal = validator.validate("token", max_age_seconds=60, now=now)
        self.assertEqual("user-1", principal.subject)

    def test_max_age_exceeded(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        jwt = _FakeJwtValidator(extra_claims={"auth_time": int(now.timestamp()) - 600})
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        with self.assertRaises(OAuthTokenValidationError):
            validator.validate("token", max_age_seconds=60, now=now)

    def test_max_age_skipped_when_not_requested(self) -> None:
        # No auth_time claim; without max_age, no check.
        jwt = _FakeJwtValidator()
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        principal = validator.validate("token")
        self.assertEqual("user-1", principal.subject)

    def test_max_age_without_auth_time_claim_fails(self) -> None:
        jwt = _FakeJwtValidator()  # no auth_time
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        with self.assertRaises(OAuthTokenValidationError):
            validator.validate("token", max_age_seconds=60)


class IdTokenValidatorAtHashTest(unittest.TestCase):
    def test_at_hash_matches(self) -> None:
        access_token = "opaque-access-token"
        jwt = _FakeJwtValidator(extra_claims={"at_hash": _hash_left_half(access_token)})
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        principal = validator.validate("token", access_token=access_token)
        self.assertEqual("user-1", principal.subject)

    def test_at_hash_mismatch(self) -> None:
        jwt = _FakeJwtValidator(extra_claims={"at_hash": _hash_left_half("other")})
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        with self.assertRaises(OAuthTokenValidationError):
            validator.validate("token", access_token="opaque")

    def test_at_hash_present_but_no_access_token_supplied(self) -> None:
        jwt = _FakeJwtValidator(extra_claims={"at_hash": _hash_left_half("x")})
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        with self.assertRaises(OAuthTokenValidationError):
            validator.validate("token")

    def test_at_hash_absent_is_not_enforced(self) -> None:
        jwt = _FakeJwtValidator()  # no at_hash
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        principal = validator.validate("token", access_token="opaque")
        self.assertEqual("user-1", principal.subject)


class IdTokenValidatorCHashTest(unittest.TestCase):
    def test_c_hash_matches(self) -> None:
        code = "auth-code-xyz"
        jwt = _FakeJwtValidator(extra_claims={"c_hash": _hash_left_half(code)})
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        principal = validator.validate("token", code=code)
        self.assertEqual("user-1", principal.subject)

    def test_c_hash_mismatch(self) -> None:
        jwt = _FakeJwtValidator(extra_claims={"c_hash": _hash_left_half("other-code")})
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        with self.assertRaises(OAuthTokenValidationError):
            validator.validate("token", code="auth-code-xyz")

    def test_c_hash_present_but_no_code_supplied(self) -> None:
        jwt = _FakeJwtValidator(extra_claims={"c_hash": _hash_left_half("x")})
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        with self.assertRaises(OAuthTokenValidationError):
            validator.validate("token")

    def test_c_hash_absent_is_not_enforced(self) -> None:
        jwt = _FakeJwtValidator()  # no c_hash
        validator = IdTokenValidator(jwt, expected_issuer="iss", expected_audience="aud")
        principal = validator.validate("token", code="auth-code")
        self.assertEqual("user-1", principal.subject)


class IdTokenValidatorTokenValidatorProtocolTest(unittest.TestCase):
    def test_accepts_any_token_validator(self) -> None:
        # The validator is typed as the `TokenValidator` Protocol, so any
        # implementation that satisfies the protocol shape (e.g. a real
        # `JoseJwtTokenValidator` in production, or a fake in tests) must
        # be accepted without runtime type checks.
        fake = _FakeJwtValidator()
        validator = IdTokenValidator(fake, expected_issuer="iss", expected_audience="aud")
        # Structural check: the injected object has a `.validate` method
        # matching the protocol signature.
        self.assertTrue(callable(getattr(validator.jwt_validator, "validate", None)))
