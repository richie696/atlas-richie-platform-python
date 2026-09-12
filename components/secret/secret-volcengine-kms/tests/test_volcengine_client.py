"""Volcengine secret client — KMS-only 2-SPI tests via fake Kms."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from atlas_richie.secret.crypto import (
    CryptoContext,
    KeyPurpose,
    KeyReference,
    WrappedKey,
)
from atlas_richie.secret.errors import (
    SecretConfigurationException,
    SecretCryptoException,
    SecretException,
)
from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret_volcengine_kms.client import (
    KmsLike,
    VolcengineKmsDecryptResponse,
    VolcengineKmsEncryptResponse,
    VolcengineSecretClient,
)
from atlas_richie.secret_volcengine_kms.configuration import (
    VolcengineConfigurationResolver,
)
from atlas_richie.secret_volcengine_kms.properties import (
    AuthType,
    VolcengineSecretProperties,
)


class FakeKms(KmsLike):
    """In-process `KmsLike` for tests."""

    def encrypt(
        self,
        keyring_name: str,
        key_name: str,
        plaintext_b64: str,
        encryption_context,
    ) -> VolcengineKmsEncryptResponse:
        return VolcengineKmsEncryptResponse(
            ciphertext_blob=f"cipher:{plaintext_b64}",
        )

    def decrypt(
        self,
        ciphertext_blob: str,
        encryption_context,
    ) -> VolcengineKmsDecryptResponse:
        if not ciphertext_blob.startswith("cipher:"):
            raise ValueError("FakeKms: cannot decrypt non-fake ciphertext")
        plaintext_b64 = ciphertext_blob[len("cipher:"):]
        return VolcengineKmsDecryptResponse(plaintext=plaintext_b64)


@pytest.fixture
def fake_kms() -> FakeKms:
    return FakeKms()


@pytest.fixture
def default_properties() -> VolcengineSecretProperties:
    return VolcengineSecretProperties(
        region="cn-beijing",
        namespace="atlas-orders",
        access_key_id="AKID-test",
        access_key_secret="secret-test",
        kms_key_bindings={"default-envelope": "key-abc-123"},
    )


@pytest.fixture
def client(
    default_properties: VolcengineSecretProperties,
    fake_kms: FakeKms,
) -> Iterator[VolcengineSecretClient]:
    resolved = VolcengineConfigurationResolver().resolve(default_properties)
    yield VolcengineSecretClient(resolved=resolved, kms=fake_kms)


def _kek(key_id: str = "default-envelope") -> KeyReference:
    return KeyReference(
        provider="volcengine-test",
        key_id=key_id,
        version=None,
        algorithm="AES-256",
    )


class TestVolcengineRead:
    def test_descriptor_declares_volcengine_backend(self, client) -> None:
        descriptor = client.descriptor
        assert descriptor.backend is SecretBackend.VOLCENGINE
        assert descriptor.capability.can_read is False
        assert descriptor.capability.can_write is False
        assert descriptor.capability.can_rotate is False
        assert descriptor.capability.encrypts_at_rest is True

    def test_operations_writer_deletable_are_none(self, client) -> None:
        assert client.operations is None
        assert client.writer is None
        assert client.deletable is None


class TestVolcengineWrapUnwrap:
    def test_wrap_empty_plaintext_raises(self, client) -> None:
        with pytest.raises(SecretCryptoException):
            client.wrap_key(b"", _kek())

    def test_wrap_then_unwrap_round_trip(self, client) -> None:
        kek = _kek()
        plaintext = b"this is a 32-byte plaintext key!!"
        wrapped = client.wrap_key(plaintext, kek)
        assert wrapped.algorithm == "volcengine-kms-default"
        assert wrapped.ciphertext.startswith(b"cipher:")

        context = CryptoContext(
            primary_key=kek,
            purpose=KeyPurpose.WRAP,
            aad={"path": "secret/orders"},
        )
        recovered = client.unwrap_key(wrapped, context)
        assert recovered == plaintext

    def test_unwrap_wrong_algorithm_raises(self, client) -> None:
        kek = _kek()
        bad = WrappedKey(
            kek_reference=kek,
            ciphertext=b"junk",
            algorithm="aws-kms",
        )
        context = CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP)
        with pytest.raises(SecretCryptoException) as info:
            client.unwrap_key(bad, context)
        assert "volcengine-kms-default" in str(info.value)

    def test_wrap_missing_key_binding_raises_configuration(
        self,
        default_properties,
        fake_kms,
    ) -> None:
        properties = default_properties.model_copy(
            update={"kms_key_bindings": {}},
        )
        resolved = VolcengineConfigurationResolver().resolve(properties)
        client = VolcengineSecretClient(resolved=resolved, kms=fake_kms)
        with pytest.raises(SecretConfigurationException) as info:
            client.wrap_key(b"x" * 32, _kek())
        assert "SEC-KEY-001" in str(info.value)


class TestVolcengineSession:
    def test_close_is_idempotent(self, client) -> None:
        client.close()
        client.close()
        assert client.is_closed is True

    def test_wrap_after_close_raises(self, client) -> None:
        client.close()
        with pytest.raises(SecretException):
            client.wrap_key(b"x" * 32, _kek())


__all__ = []
