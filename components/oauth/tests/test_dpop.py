import unittest
from datetime import UTC, datetime

from atlas_richie.oauth import DpopProofClaims, DpopProofVerifier, InMemoryDpopReplayStore, OAuthTokenValidationError, access_token_hash


class _Validator:
    def __init__(self, claims: DpopProofClaims) -> None:
        self._claims = claims

    def validate(self, _proof: str) -> DpopProofClaims:
        return self._claims


class DpopProofVerifierTests(unittest.TestCase):
    def test_request_token_key_and_replay_are_bound(self) -> None:
        now = datetime.now(UTC)
        token = "access-token"
        claims = DpopProofClaims("proof-1", now, "GET", "https://api.example/items?ignored=yes", "key-thumbprint", access_token_hash(token))
        verifier = DpopProofVerifier(_Validator(claims), InMemoryDpopReplayStore())
        verifier.verify("proof", method="GET", target_uri="https://api.example/items?other=no", access_token=token, expected_key_thumbprint="key-thumbprint", now=now)
        with self.assertRaises(OAuthTokenValidationError):
            verifier.verify("proof", method="GET", target_uri="https://api.example/items", access_token=token, expected_key_thumbprint="key-thumbprint", now=now)

    def test_wrong_binding_fails_closed(self) -> None:
        now = datetime.now(UTC)
        claims = DpopProofClaims("proof-2", now, "POST", "https://api.example/items", "key-thumbprint", access_token_hash("token"))
        verifier = DpopProofVerifier(_Validator(claims), InMemoryDpopReplayStore())
        with self.assertRaises(OAuthTokenValidationError):
            verifier.verify("proof", method="GET", target_uri="https://api.example/items", access_token="token", expected_key_thumbprint="key-thumbprint", now=now)


if __name__ == "__main__":
    unittest.main()
