"""IBM Key Protect secret client — KMS-only 2-SPI tests via fake Kms."""

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
from atlas_richie.secret_ibm_key_protect.client import (
    IbmKeyProtectSecretClient,
    IbmKeyProtectUnwrapResponse,
    IbmKeyProtectWrapResponse,
    KmsLike,
)
from atlas_richie.secret_ibm_key_protect.configuration import (
    IbmKeyProtectConfigurationResolver,
)
from atlas_richie.secret_ibm_key_protect.properties import (
    AuthType,
    IbmKeyProtectProperties,
)


class FakeKms(KmsLike):
    """In-process `KmsLike` for tests; round-trips via a simple in-memory map."""

    def __init__(self) -> None:
        self._last_call: dict | None = None
        # Map wrapped_ciphertext -> original plaintext_b64
        self._vault: dict[str, str] = {}

    def wrap(
        self,
        key_id: str,
        plaintext_b64: str,
    ) -> IbmKeyProtectWrapResponse:
        self._last_call = {"op": "wrap", "key_id": key_id, "plaintext_b64": plaintext_b64}
        # The fake ciphertext IS the plaintext (pass-through); the IBM
        # KMS API is symmetric, so unwrap with the same ciphertext
        # returns the same plaintext. Real IBM calls would return
        # something different; this is just a smoke test.
        self._vault[plaintext_b64] = plaintext_b64
        return IbmKeyProtectWrapResponse(ciphertext=plaintext_b64)

    def unwrap(
        self,
        key_id: str,
        ciphertext: str,
    ) -> IbmKeyProtectUnwrapResponse:
        self._last_call = {"op": "unwrap", "key_id": key_id, "ciphertext": ciphertext}
        if not ciphertext:
            raise ValueError("FakeKms: empty ciphertext")
        # Pass-through: the fake treats ciphertext as plaintext
        if ciphertext not in self._vault:
            raise ValueError(f"FakeKms: unknown ciphertext (not wrapped by this fake)")
        return IbmKeyProtectUnwrapResponse(plaintext=self._vault[ciphertext])


@pytest.fixture
def base_properties() -> IbmKeyProtectProperties:
    return IbmKeyProtectProperties(
        region="us-south",
        instance_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        key_ring="default",
        auth_type=AuthType.BEARER_TOKEN,
        bearer_token="iam-token-abc",
        kms_endpoint="https://us-south.kms.cloud.ibm.com",
        kms_key_bindings={"envelope": "crn:v1:bluemix:public:kms:us-south:a/...:key:abcd-1234"},
    )


@pytest.fixture
def resolved(base_properties):
    return IbmKeyProtectConfigurationResolver().resolve(
        base_properties,
        provider_id="ibm-key-protect-us-south",
    )


@pytest.fixture
def kms() -> FakeKms:
    return FakeKms()


@pytest.fixture
def client(resolved, kms: FakeKms) -> IbmKeyProtectSecretClient:
    return IbmKeyProtectSecretClient(resolved=resolved, kms=kms)


def _kek() -> KeyReference:
    return KeyReference(provider="ibm-key-protect-us-south", key_id="envelope")


def _ref() -> SecretReference:
    return SecretReference(provider="ibm-key-protect-us-south", path="db")


# ---------------------------------------------------------------------------
# Descriptor / capability
# ---------------------------------------------------------------------------


class TestIbmDescriptor:
    def test_descriptor(self, client: IbmKeyProtectSecretClient) -> None:
        d = client.descriptor
        assert d.name == "ibm-key-protect-us-south"
        assert d.backend is SecretBackend.IBM_KEY_PROTECT
        assert d.version == "0.2.0"
        assert d.capability.can_read is False
        assert d.capability.can_write is False
        assert d.capability.encrypts_at_rest is True

    def test_operations_is_none(self, client: IbmKeyProtectSecretClient) -> None:
        assert client.operations is None

    def test_writer_is_none(self, client: IbmKeyProtectSecretClient) -> None:
        assert client.writer is None

    def test_deletable_is_none(self, client: IbmKeyProtectSecretClient) -> None:
        assert client.deletable is None

    def test_configuration_hash_present(self, client: IbmKeyProtectSecretClient) -> None:
        assert len(client.configuration_hash) == 64
        assert all(c in "0123456789abcdef" for c in client.configuration_hash)


# ---------------------------------------------------------------------------
# read() / metadata() — KMS-only
# ---------------------------------------------------------------------------


class TestIbmReadCapability:
    def test_read_raises_sec_cap_001(self, client: IbmKeyProtectSecretClient) -> None:
        with pytest.raises(SecretCapabilityException) as exc_info:
            client.read(_ref())
        assert "SEC-CAP-001" in str(exc_info.value)
        assert "cannot read secrets" in str(exc_info.value).lower()

    def test_metadata_raises_sec_cap_001(self, client: IbmKeyProtectSecretClient) -> None:
        with pytest.raises(SecretCapabilityException) as exc_info:
            client.metadata(_ref())
        assert "SEC-CAP-001" in str(exc_info.value)


# ---------------------------------------------------------------------------
# wrap_key() / unwrap_key()
# ---------------------------------------------------------------------------


class TestIbmWrap:
    def test_wrap_then_unwrap(self, client: IbmKeyProtectSecretClient, kms: FakeKms) -> None:
        wrapped = client.wrap_key(b"data-key-32-bytes-1234567890ab", _kek())
        assert wrapped.algorithm == "ibm-key-protect-default"
        ctx = CryptoContext(primary_key=_kek(), purpose=KeyPurpose.WRAP)
        unwrapped = client.unwrap_key(wrapped, ctx)
        assert unwrapped == b"data-key-32-bytes-1234567890ab"
        assert kms._last_call == {  # type: ignore[attr-defined]
            "op": "unwrap",
            "key_id": "crn:v1:bluemix:public:kms:us-south:a/...:key:abcd-1234",
            "ciphertext": bytes(wrapped.ciphertext).decode("utf-8"),
        }

    def test_wrap_empty_dek_raises_crypto(self, client: IbmKeyProtectSecretClient) -> None:
        with pytest.raises(SecretCryptoException) as exc_info:
            client.wrap_key(b"", _kek())
        assert "SEC-CRYPTO-001" in str(exc_info.value)

    def test_unwrap_wrong_algorithm_raises_crypto(self, client: IbmKeyProtectSecretClient) -> None:
        bad = WrappedKey(
            kek_reference=_kek(),
            ciphertext=b"abc",
            algorithm="not-ibm",
        )
        with pytest.raises(SecretCryptoException) as exc_info:
            client.unwrap_key(bad, CryptoContext(primary_key=_kek(), purpose=KeyPurpose.WRAP))
        assert "SEC-CRYPTO-002" in str(exc_info.value)

    def test_unwrap_empty_ciphertext_raises_crypto(self, client: IbmKeyProtectSecretClient) -> None:
        bad = WrappedKey(
            kek_reference=_kek(),
            ciphertext=b"",
            algorithm="ibm-key-protect-default",
        )
        with pytest.raises(SecretCryptoException) as exc_info:
            client.unwrap_key(bad, CryptoContext(primary_key=_kek(), purpose=KeyPurpose.WRAP))
        assert "SEC-CRYPTO-002" in str(exc_info.value)

    def test_wrap_missing_key_binding_raises_config(
        self,
        resolved,
        kms: FakeKms,
    ) -> None:
        client = IbmKeyProtectSecretClient(resolved=resolved, kms=kms)
        bad_kek = KeyReference(provider="ibm-key-protect-us-south", key_id="missing")
        with pytest.raises(SecretConfigurationException) as exc_info:
            client.wrap_key(b"data", bad_kek)
        assert "SEC-KEY-001" in str(exc_info.value)

    def test_unwrap_with_aad_raises_sec_cap_001(
        self,
        client: IbmKeyProtectSecretClient,
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


class TestIbmLifecycle:
    def test_close_idempotent(self, client: IbmKeyProtectSecretClient) -> None:
        client.close()
        client.close()
        assert client.is_closed is True

    def test_read_after_close_raises(self, client: IbmKeyProtectSecretClient) -> None:
        client.close()
        with pytest.raises(SecretException):
            client.read(_ref())

    def test_configuration_property(
        self,
        client: IbmKeyProtectSecretClient,
        base_properties: IbmKeyProtectProperties,
    ) -> None:
        cfg = client.configuration
        assert cfg.name == "ibm-key-protect-us-south"
        assert cfg.namespace == base_properties.region
        assert cfg.timeout_seconds == base_properties.read_timeout_seconds


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestIbmFactory:
    def test_factory_descriptor(self, base_properties: IbmKeyProtectProperties) -> None:
        from atlas_richie.secret_ibm_key_protect.factory import (
            IbmKeyProtectSecretProviderFactory,
        )

        factory = IbmKeyProtectSecretProviderFactory(base_properties)
        d = factory.descriptor()
        assert d.name == "ibm-key-protect-us-south"
        assert d.backend is SecretBackend.IBM_KEY_PROTECT

    def test_factory_create_with_fake(
        self,
        base_properties: IbmKeyProtectProperties,
    ) -> None:
        from atlas_richie.secret_ibm_key_protect.factory import (
            IbmKeyProtectSecretProviderFactory,
        )

        factory = IbmKeyProtectSecretProviderFactory(
            base_properties,
            client_factory=lambda _props: FakeKms(),
        )
        session = factory.create(factory.default_configuration())
        assert session.descriptor.name == "ibm-key-protect-us-south"
        assert session.operations is None  # KMS-only
        # Smoke wrap/unwrap
        wrapped = session.wrap_key(b"data", _kek())
        unwrapped = session.unwrap_key(
            wrapped,
            CryptoContext(primary_key=_kek(), purpose=KeyPurpose.WRAP),
        )
        assert unwrapped == b"data"
        session.close()
