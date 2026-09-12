"""Baidu Cloud KMS secret client — KMS-only 2-SPI tests via fake Kms."""

from __future__ import annotations

import base64

import pytest

from atlas_richie.secret.crypto import (
    CryptoContext,
    KeyPurpose,
    KeyReference,
    WrappedKey,
)
from atlas_richie.secret.errors import (
    SecretCapabilityException,
    SecretConfigurationException,
    SecretCryptoException,
    SecretException,
)
from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret.reference import SecretReference
from atlas_richie.secret_baidu_kms.client import (
    BaiduKmsDecryptResponse,
    BaiduKmsEncryptResponse,
    BaiduSecretClient,
    KmsLike,
)
from atlas_richie.secret_baidu_kms.configuration import BaiduConfigurationResolver
from atlas_richie.secret_baidu_kms.properties import (
    AuthType,
    BaiduSecretProperties,
)


class FakeKms(KmsLike):
    """In-process `KmsLike` for tests; pass-through round-trip."""

    def __init__(self) -> None:
        self._last_call: dict | None = None
        self._vault: dict[str, str] = {}

    def encrypt(
        self,
        key_id: str,
        plaintext_b64: str,
    ) -> BaiduKmsEncryptResponse:
        self._last_call = {"op": "encrypt", "key_id": key_id, "plaintext_b64": plaintext_b64}
        # Pass-through: store plaintext as ciphertext (fake symmetric KMS)
        self._vault[plaintext_b64] = plaintext_b64
        return BaiduKmsEncryptResponse(ciphertext=plaintext_b64)

    def decrypt(
        self,
        key_id: str,
        ciphertext: str,
    ) -> BaiduKmsDecryptResponse:
        self._last_call = {"op": "decrypt", "key_id": key_id, "ciphertext": ciphertext}
        if not ciphertext:
            raise ValueError("FakeKms: empty ciphertext")
        if ciphertext not in self._vault:
            raise ValueError("FakeKms: unknown ciphertext")
        return BaiduKmsDecryptResponse(plaintext=self._vault[ciphertext])


@pytest.fixture
def base_properties() -> BaiduSecretProperties:
    return BaiduSecretProperties(
        region="bj",
        kms_endpoint="http://bkm.bj.baidubce.com",
        auth_type=AuthType.ACCESS_KEY,
        access_key_id="ak-test-123",
        access_key_secret="sk-test-456",
        kms_key_bindings={"envelope": "kms-key-id-abc"},
    )


@pytest.fixture
def resolved(base_properties):
    return BaiduConfigurationResolver().resolve(
        base_properties,
        provider_id="baidu-kms-bj",
    )


@pytest.fixture
def kms() -> FakeKms:
    return FakeKms()


@pytest.fixture
def client(resolved, kms: FakeKms) -> BaiduSecretClient:
    return BaiduSecretClient(resolved=resolved, kms=kms)


def _kek() -> KeyReference:
    return KeyReference(provider="baidu-kms-bj", key_id="envelope")


def _ref() -> SecretReference:
    return SecretReference(provider="baidu-kms-bj", path="db")


# ---------------------------------------------------------------------------
# Descriptor / capability
# ---------------------------------------------------------------------------


class TestBaiduDescriptor:
    def test_descriptor(self, client: BaiduSecretClient) -> None:
        d = client.descriptor
        assert d.name == "baidu-kms-bj"
        assert d.backend is SecretBackend.BAIDU
        assert d.version == "0.2.0"
        assert d.capability.can_read is False
        assert d.capability.can_write is False
        assert d.capability.encrypts_at_rest is True

    def test_operations_is_none(self, client: BaiduSecretClient) -> None:
        assert client.operations is None

    def test_writer_is_none(self, client: BaiduSecretClient) -> None:
        assert client.writer is None

    def test_deletable_is_none(self, client: BaiduSecretClient) -> None:
        assert client.deletable is None

    def test_configuration_hash_present(self, client: BaiduSecretClient) -> None:
        assert len(client.configuration_hash) == 64
        assert all(c in "0123456789abcdef" for c in client.configuration_hash)


# ---------------------------------------------------------------------------
# read() / metadata() — KMS-only
# ---------------------------------------------------------------------------


class TestBaiduReadCapability:
    def test_read_raises_sec_cap_001(self, client: BaiduSecretClient) -> None:
        with pytest.raises(SecretCapabilityException) as exc_info:
            client.read(_ref())
        assert "SEC-CAP-001" in str(exc_info.value)
        assert "cannot read secrets" in str(exc_info.value).lower()

    def test_metadata_raises_sec_cap_001(self, client: BaiduSecretClient) -> None:
        with pytest.raises(SecretCapabilityException) as exc_info:
            client.metadata(_ref())
        assert "SEC-CAP-001" in str(exc_info.value)


# ---------------------------------------------------------------------------
# wrap_key() / unwrap_key()
# ---------------------------------------------------------------------------


class TestBaiduWrap:
    def test_wrap_then_unwrap(self, client: BaiduSecretClient, kms: FakeKms) -> None:
        wrapped = client.wrap_key(b"data-key-32-bytes-1234567890ab", _kek())
        assert wrapped.algorithm == "baidu-kms-default"
        ctx = CryptoContext(primary_key=_kek(), purpose=KeyPurpose.WRAP)
        unwrapped = client.unwrap_key(wrapped, ctx)
        assert unwrapped == b"data-key-32-bytes-1234567890ab"
        assert kms._last_call == {  # type: ignore[attr-defined]
            "op": "decrypt",
            "key_id": "kms-key-id-abc",
            "ciphertext": bytes(wrapped.ciphertext).decode("utf-8"),
        }

    def test_wrap_empty_dek_raises_crypto(self, client: BaiduSecretClient) -> None:
        with pytest.raises(SecretCryptoException) as exc_info:
            client.wrap_key(b"", _kek())
        assert "SEC-CRYPTO-001" in str(exc_info.value)

    def test_unwrap_wrong_algorithm_raises_crypto(self, client: BaiduSecretClient) -> None:
        bad = WrappedKey(
            kek_reference=_kek(),
            ciphertext=b"abc",
            algorithm="not-baidu",
        )
        with pytest.raises(SecretCryptoException) as exc_info:
            client.unwrap_key(bad, CryptoContext(primary_key=_kek(), purpose=KeyPurpose.WRAP))
        assert "SEC-CRYPTO-002" in str(exc_info.value)

    def test_unwrap_empty_ciphertext_raises_crypto(self, client: BaiduSecretClient) -> None:
        bad = WrappedKey(
            kek_reference=_kek(),
            ciphertext=b"",
            algorithm="baidu-kms-default",
        )
        with pytest.raises(SecretCryptoException) as exc_info:
            client.unwrap_key(bad, CryptoContext(primary_key=_kek(), purpose=KeyPurpose.WRAP))
        assert "SEC-CRYPTO-002" in str(exc_info.value)

    def test_wrap_missing_key_binding_raises_config(
        self,
        resolved,
        kms: FakeKms,
    ) -> None:
        client = BaiduSecretClient(resolved=resolved, kms=kms)
        bad_kek = KeyReference(provider="baidu-kms-bj", key_id="missing")
        with pytest.raises(SecretConfigurationException) as exc_info:
            client.wrap_key(b"data", bad_kek)
        assert "SEC-KEY-001" in str(exc_info.value)

    def test_unwrap_with_aad_raises_sec_cap_001(
        self,
        client: BaiduSecretClient,
    ) -> None:
        wrapped = client.wrap_key(b"data", _kek())
        ctx = CryptoContext(
            primary_key=_kek(),
            purpose=KeyPurpose.WRAP,
            aad={"tenant": "t1"},
        )
        with pytest.raises(SecretCapabilityException) as exc_info:
            client.unwrap_key(wrapped, ctx)
        assert "SEC-CAP-001" in str(exc_info.value)
        assert "AAD" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestBaiduLifecycle:
    def test_close_idempotent(self, client: BaiduSecretClient) -> None:
        client.close()
        client.close()
        assert client.is_closed is True

    def test_read_after_close_raises(self, client: BaiduSecretClient) -> None:
        client.close()
        with pytest.raises(SecretException):
            client.read(_ref())

    def test_configuration_property(
        self,
        client: BaiduSecretClient,
        base_properties: BaiduSecretProperties,
    ) -> None:
        cfg = client.configuration
        assert cfg.name == "baidu-kms-bj"
        assert cfg.namespace == base_properties.region
        assert cfg.timeout_seconds == base_properties.read_timeout_seconds


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestBaiduFactory:
    def test_factory_descriptor(self, base_properties: BaiduSecretProperties) -> None:
        from atlas_richie.secret_baidu_kms.factory import BaiduSecretProviderFactory

        factory = BaiduSecretProviderFactory(base_properties)
        d = factory.descriptor()
        assert d.name == "baidu-kms-bj"
        assert d.backend is SecretBackend.BAIDU

    def test_factory_create_with_fake(
        self,
        base_properties: BaiduSecretProperties,
    ) -> None:
        from atlas_richie.secret_baidu_kms.factory import BaiduSecretProviderFactory

        factory = BaiduSecretProviderFactory(
            base_properties,
            client_factory=lambda _props: FakeKms(),
        )
        session = factory.create(factory.default_configuration())
        assert session.descriptor.name == "baidu-kms-bj"
        assert session.operations is None  # KMS-only
        wrapped = session.wrap_key(b"data", _kek())
        unwrapped = session.unwrap_key(
            wrapped,
            CryptoContext(primary_key=_kek(), purpose=KeyPurpose.WRAP),
        )
        assert unwrapped == b"data"
        session.close()
