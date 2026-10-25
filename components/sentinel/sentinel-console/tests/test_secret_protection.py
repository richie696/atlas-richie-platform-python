"""Password hashing and authenticated-encryption boundary tests."""

from __future__ import annotations

import unittest

from atlas_richie.sentinel_console.infrastructure.security.password_hash import (
    PasswordHashService,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
    EncryptedSecret,
    SecretCipherError,
    SecretContext,
)


class PasswordHashTest(unittest.TestCase):
    def test_password_is_one_way_hashed_and_verified(self) -> None:
        service = PasswordHashService()
        password = "Sufficiently-long-test-password"
        encoded = service.hash_password(password)

        self.assertTrue(encoded.startswith("$argon2id$"))
        self.assertNotIn(password, encoded)
        self.assertTrue(service.verify_password(encoded, password))
        self.assertFalse(service.verify_password(encoded, "incorrect-password"))
        self.assertFalse(service.verify_password("malformed", password))
        self.assertFalse(service.verify_account_password("malformed", password))
        self.assertFalse(service.verify_account_password(None, password))


class SecretCipherTest(unittest.TestCase):
    def test_ciphertext_round_trips_and_binds_to_owner_and_field(self) -> None:
        cipher = AesGcmSecretCipher("key-2026-01", {"key-2026-01": b"k" * 32})
        context = SecretContext("configuration-source", "source-17", "password")
        plaintext = "private-database-password"
        encrypted = cipher.encrypt(plaintext, context)

        self.assertIsInstance(encrypted, EncryptedSecret)
        self.assertNotEqual(encrypted.payload, plaintext.encode())
        self.assertNotIn(plaintext, repr(encrypted))
        self.assertEqual(cipher.decrypt(encrypted, context), plaintext)
        with self.assertRaises(SecretCipherError):
            cipher.decrypt(
                encrypted,
                SecretContext("configuration-source", "source-18", "password"),
            )

    def test_ciphertext_tampering_is_rejected(self) -> None:
        cipher = AesGcmSecretCipher("active", {"active": b"a" * 32})
        context = SecretContext("database-config", "primary", "password")
        encrypted = cipher.encrypt("private-database-password", context)
        tampered = EncryptedSecret(
            format=encrypted.format,
            key_id=encrypted.key_id,
            payload=encrypted.payload[:-1] + bytes([encrypted.payload[-1] ^ 1]),
        )

        with self.assertRaises(SecretCipherError):
            cipher.decrypt(tampered, context)

    def test_key_rotation_keeps_old_decryption_and_uses_new_key_for_encryption(
        self,
    ) -> None:
        old_cipher = AesGcmSecretCipher("old", {"old": b"o" * 32})
        context = SecretContext("database-config", "primary", "password")
        old_envelope = old_cipher.encrypt("old-password", context)
        rotated_cipher = AesGcmSecretCipher(
            "new", {"old": b"o" * 32, "new": b"n" * 32}
        )

        self.assertEqual(rotated_cipher.decrypt(old_envelope, context), "old-password")
        new_envelope = rotated_cipher.encrypt("new-password", context)
        self.assertEqual(new_envelope.key_id, "new")
        self.assertEqual(rotated_cipher.decrypt(new_envelope, context), "new-password")
        with self.assertRaises(SecretCipherError):
            AesGcmSecretCipher("other", {"other": b"x" * 32}).decrypt(
                old_envelope, context
            )
