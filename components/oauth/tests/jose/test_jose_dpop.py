import unittest
from datetime import UTC, datetime

from atlas_richie.oauth import access_token_hash
from atlas_richie.oauth.jose import JoseDpopProofFactory, JoseDpopProofValidator


class JoseDpopProofTests(unittest.TestCase):
    def test_generated_proof_round_trips_with_expected_claims(self) -> None:
        factory = JoseDpopProofFactory.generate()
        proof = factory.create(
            method="get",
            target_uri="https://api.example/items?ignored=yes",
            access_token="access-token",
            nonce="server-nonce",
            now=datetime(2026, 9, 10, tzinfo=UTC),
        )
        claims = JoseDpopProofValidator().validate(proof)

        self.assertEqual("GET", claims.method)
        self.assertEqual("https://api.example/items", claims.target_uri)
        self.assertEqual(factory.key_thumbprint, claims.key_thumbprint)
        self.assertEqual(access_token_hash("access-token"), claims.access_token_hash)
        self.assertEqual("server-nonce", claims.nonce)

    def test_tampered_proof_is_rejected(self) -> None:
        proof = JoseDpopProofFactory.generate().create(method="GET", target_uri="https://api.example/items")
        protected, payload, signature = proof.split(".")
        tampered = f"{protected}.{payload}.{signature[:-1]}x"
        with self.assertRaises(Exception):
            JoseDpopProofValidator().validate(tampered)


if __name__ == "__main__":
    unittest.main()
