"""Crypto 单元测试 — AES-GCM cipher + ECDSA signing + envelope codec。

中文
----
覆盖简单 envelope 加密的 round-trip + tamper detection + AAD 校验。
依赖 `atlas-richie-secret-core[crypto]` extra。

English
--------
Crypto unit tests for AES-GCM cipher, ECDSA signing, and the
envelope codec. Requires the `cryptography` package.
"""

from __future__ import annotations

import unittest

import pytest

from atlas_richie.secret import (
    ArseEnvelopeCodec,
    CipherEnvelope,
    CryptoContext,
    DefaultEnvelopeCrypto,
    DefaultSecretCipher,
    DefaultSigningService,
    KeyPurpose,
    KeyReference,
    SignatureValue,
    generate_ecdsa_keypair,
)


def _try_import_crypto():
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        return ec
    except ImportError:
        return None


_ec_module = _try_import_crypto()
requires_crypto = pytest.mark.skipif(
    _ec_module is None,
    reason="requires the 'cryptography' package; install with "
    "atlas-richie-secret-core[crypto]",
)


@requires_crypto
class SecretCipherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.key = bytes(32)  # all-zero AES-256 key for tests
        self.cipher = DefaultSecretCipher(local_key=self.key)
        self.context = CryptoContext(
            primary_key=KeyReference(provider="test", key_id="k1"),
            purpose=KeyPurpose.ENCRYPT,
            aad={"path": "db.password"},
        )

    def test_roundtrip(self) -> None:
        envelope = self.cipher.encrypt(b"plain text", self.context)
        decrypted = self.cipher.decrypt(envelope, self.context)
        self.assertEqual(decrypted, b"plain text")

    def test_tampered_ciphertext_fails(self) -> None:
        envelope = self.cipher.encrypt(b"plain", self.context)
        tampered = CipherEnvelope(
            algorithm=envelope.algorithm,
            ciphertext=envelope.ciphertext[:-1] + b"\x00",
            nonce=envelope.nonce,
            aad=envelope.aad,
            wrapped_key=envelope.wrapped_key,
            signature=envelope.signature,
            metadata=envelope.metadata,
        )
        from atlas_richie.secret import SecretCryptoException
        with self.assertRaises(SecretCryptoException):
            self.cipher.decrypt(tampered, self.context)

    def test_tampered_aad_fails(self) -> None:
        envelope = self.cipher.encrypt(b"plain", self.context)
        tampered = CipherEnvelope(
            algorithm=envelope.algorithm,
            ciphertext=envelope.ciphertext,
            nonce=envelope.nonce,
            aad={"path": "wrong"},
            wrapped_key=envelope.wrapped_key,
            signature=envelope.signature,
            metadata=envelope.metadata,
        )
        from atlas_richie.secret import SecretCryptoException
        with self.assertRaises(SecretCryptoException):
            self.cipher.decrypt(tampered, self.context)

    def test_nonce_uniqueness(self) -> None:
        seen = set()
        for _ in range(50):
            envelope = self.cipher.encrypt(b"x", self.context)
            self.assertNotIn(envelope.nonce, seen)
            seen.add(envelope.nonce)


@requires_crypto
class SigningServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.private_key, self.public_key = generate_ecdsa_keypair()
        self.key_ref = KeyReference(
            provider="test",
            key_id="signing-key-1",
            algorithm="ECDSA-P256",
        )
        self.signing = DefaultSigningService(
            local_private_key=self.private_key,
            local_public_key=self.public_key,
            key_reference=self.key_ref,
        )
        self.context = CryptoContext(
            primary_key=self.key_ref,
            purpose=KeyPurpose.SIGN,
        )

    def test_sign_and_verify(self) -> None:
        sig = self.signing.sign(b"hello", self.context)
        self.assertEqual(sig.algorithm, "ECDSA-P256-SHA256")
        self.assertTrue(self.signing.verify(b"hello", sig))

    def test_verify_rejects_tampered_payload(self) -> None:
        sig = self.signing.sign(b"hello", self.context)
        self.assertFalse(self.signing.verify(b"hellO", sig))


@requires_crypto
class EnvelopeCodecTest(unittest.TestCase):
    def test_roundtrip(self) -> None:
        codec = ArseEnvelopeCodec()
        original = CipherEnvelope(
            algorithm="AES-256-GCM",
            ciphertext=b"\x00\x01\x02",
            nonce=b"\x03\x04\x05",
            aad={"path": "x"},
            metadata={"key_id": "k1"},
        )
        encoded = codec.encode(original)
        decoded = codec.decode(encoded)
        self.assertEqual(decoded.algorithm, original.algorithm)
        self.assertEqual(decoded.ciphertext, original.ciphertext)
        self.assertEqual(decoded.nonce, original.nonce)
        self.assertEqual(decoded.aad, original.aad)
        self.assertEqual(decoded.metadata, original.metadata)


@requires_crypto
class EnvelopeCryptoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.key = bytes(32)
        self.cipher = DefaultSecretCipher(local_key=self.key)
        self.private_key, self.public_key = generate_ecdsa_keypair()
        self.signing = DefaultSigningService(
            local_private_key=self.private_key,
            local_public_key=self.public_key,
            key_reference=KeyReference(
                provider="test", key_id="sk1", algorithm="ECDSA-P256",
            ),
        )
        self.envelope = DefaultEnvelopeCrypto(
            cipher=self.cipher, signing=self.signing,
        )
        self.context = CryptoContext(
            primary_key=KeyReference(provider="test", key_id="k1"),
            purpose=KeyPurpose.ENCRYPT,
            aad={"path": "db.password"},
        )

    def test_seal_and_open(self) -> None:
        sealed = self.envelope.seal(b"plain", self.context)
        self.assertIsNotNone(sealed.signature)
        opened = self.envelope.open(sealed, self.context)
        self.assertEqual(opened, b"plain")

    def test_open_rejects_tampered_envelope(self) -> None:
        from atlas_richie.secret import SecretCryptoException
        sealed = self.envelope.seal(b"plain", self.context)
        tampered = CipherEnvelope(
            algorithm=sealed.algorithm,
            ciphertext=sealed.ciphertext[:-1] + b"\x00",
            nonce=sealed.nonce,
            aad=sealed.aad,
            wrapped_key=sealed.wrapped_key,
            signature=sealed.signature,
            metadata=sealed.metadata,
        )
        with self.assertRaises(SecretCryptoException):
            self.envelope.open(tampered, self.context)

    def test_aad_mismatch_raises(self) -> None:
        from atlas_richie.secret import SecretCryptoException
        sealed = self.envelope.seal(b"plain", self.context)
        wrong_context = CryptoContext(
            primary_key=self.context.primary_key,
            purpose=self.context.purpose,
            aad={"path": "different"},
        )
        with self.assertRaises(SecretCryptoException):
            self.envelope.open(sealed, wrong_context)


if __name__ == "__main__":
    unittest.main()
