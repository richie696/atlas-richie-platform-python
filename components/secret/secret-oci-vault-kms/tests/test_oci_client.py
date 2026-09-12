"""OCI secret client — 3-SPI tests via fake Vault + KMS."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import datetime, timezone

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
    SecretIntegrityException,
)
from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret.reference import (
    SecretReference,
    SecretVersion,
    SecretVersionSelector,
)
from atlas_richie.secret_oci_vault_kms.client import (
    KmsLike,
    OciKmsDecryptResponse,
    OciKmsEncryptResponse,
    OciSecretClient,
    OciVaultSecret,
    VaultLike,
)
from atlas_richie.secret_oci_vault_kms.configuration import (
    OciConfigurationResolver,
)
from atlas_richie.secret_oci_vault_kms.properties import (
    AuthType,
    OciSecretProperties,
)


class FakeVault(VaultLike):
    """In-process `VaultLike` for tests."""

    def __init__(self, *, not_found: bool = False) -> None:
        self._calls: list[dict] = []
        self._not_found = not_found

    def get_secret_bundle(
        self,
        secret_id: str,
        version_number: int | None,
        stage: str | None,
        secret_version_name: str | None,
    ) -> OciVaultSecret | None:
        self._calls.append(
            {
                "secret_id": secret_id,
                "version_number": version_number,
                "stage": stage,
                "secret_version_name": secret_version_name,
            },
        )
        if self._not_found:
            return None
        return OciVaultSecret(
            secret_id=secret_id,
            version_name="v7",
            content=b"secret-value",
            create_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


class FakeOciException(Exception):
    """Simulates `oci.exceptions.BmcException` with a `.status` attr."""

    def __init__(self, status: int, message: str = "fake") -> None:
        super().__init__(message)
        self.status = status


class FakeKms(KmsLike):
    """In-process `KmsLike` for tests; tracks AAD round-trip."""

    def __init__(self) -> None:
        self._last_aad: dict[str, str] | None = None

    def encrypt(
        self,
        key_id: str,
        plaintext_b64: str,
        associated_data: dict[str, str] | None,
    ) -> OciKmsEncryptResponse:
        self._last_aad = associated_data
        return OciKmsEncryptResponse(
            ciphertext=base64.b64encode(
                f"wrap:{key_id}:{plaintext_b64}".encode("utf-8"),
            ).decode("ascii"),
        )

    def decrypt(
        self,
        key_id: str,
        ciphertext: str,
        associated_data: dict[str, str] | None,
    ) -> OciKmsDecryptResponse:
        self._last_aad = associated_data
        if not ciphertext:
            raise ValueError("FakeKms: empty ciphertext")
        decoded = base64.b64decode(ciphertext).decode("utf-8")
        # Format: "wrap:<key_id>:<plaintext_b64>"
        parts = decoded.split(":", 2)
        return OciKmsDecryptResponse(plaintext=parts[2])


@pytest.fixture
def base_properties() -> OciSecretProperties:
    return OciSecretProperties(
        region="us-ashburn-1",
        auth_type=AuthType.NONE,
        secrets={"db-password": "ocid1.vaultsecret.oc1..abcd"},
        kms_key_bindings={"default-envelope": "ocid1.key.oc1..deadbeef"},
    )


@pytest.fixture
def resolved(base_properties) -> "object":  # ResolvedOciConfiguration
    return OciConfigurationResolver().resolve(
        base_properties,
        provider_id="oci-us-ashburn-1",
    )


@pytest.fixture
def vault() -> FakeVault:
    return FakeVault()


@pytest.fixture
def kms() -> FakeKms:
    return FakeKms()


@pytest.fixture
def client(
    resolved,
    vault: FakeVault,
    kms: FakeKms,
) -> OciSecretClient:
    return OciSecretClient(
        resolved=resolved,
        vault=vault,
        kms=kms,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ref(logical: str = "db-password") -> SecretReference:
    return SecretReference(
        provider="oci-us-ashburn-1",
        path=logical,
    )


# ---------------------------------------------------------------------------
# Descriptor / capability
# ---------------------------------------------------------------------------


class TestOciDescriptor:
    def test_descriptor(self, client: OciSecretClient) -> None:
        descriptor = client.descriptor
        assert descriptor.name == "oci-us-ashburn-1"
        assert descriptor.backend is SecretBackend.OCI
        assert descriptor.version == "0.2.0"
        assert descriptor.capability.can_read is True
        assert descriptor.capability.can_write is False
        assert descriptor.capability.can_rotate is True
        assert descriptor.capability.encrypts_at_rest is True

    def test_operations_returns_self(self, client: OciSecretClient) -> None:
        assert client.operations is client

    def test_writer_is_none(self, client: OciSecretClient) -> None:
        assert client.writer is None

    def test_deletable_is_none(self, client: OciSecretClient) -> None:
        assert client.deletable is None

    def test_configuration_hash_present(self, client: OciSecretClient) -> None:
        assert len(client.configuration_hash) == 64
        assert all(c in "0123456789abcdef" for c in client.configuration_hash)


# ---------------------------------------------------------------------------
# read() / metadata()
# ---------------------------------------------------------------------------


class TestOciRead:
    def test_read_returns_value(self, client: OciSecretClient) -> None:
        value = client.read(_ref())
        assert bytes(value.plaintext) == b"secret-value"
        assert value.metadata.version.number == "v7"
        assert value.metadata.backend is SecretBackend.OCI
        assert value.metadata.tags == {"provider": "oci"}

    def test_read_with_logical_mapping(
        self,
        client: OciSecretClient,
        vault: FakeVault,
    ) -> None:
        client.read(_ref("db-password"))
        # The Vault was called with the physical OCID, not the logical.
        assert vault._calls[0]["secret_id"] == "ocid1.vaultsecret.oc1..abcd"  # type: ignore[attr-defined]

    def test_read_with_unmapped_logical(
        self,
        client: OciSecretClient,
        vault: FakeVault,
    ) -> None:
        client.read(_ref("unmapped-logical"))
        # Falls back to using path as physical id
        assert vault._calls[0]["secret_id"] == "unmapped-logical"  # type: ignore[attr-defined]

    def test_read_not_found_vault_returns_none_raises_integrity(
        self,
        resolved,
        kms: FakeKms,
    ) -> None:
        vault = FakeVault(not_found=True)
        client = OciSecretClient(resolved=resolved, vault=vault, kms=kms)
        with pytest.raises(SecretIntegrityException):
            client.read(_ref())

    def test_read_http_404_raises_integrity(
        self,
        resolved,
        kms: FakeKms,
    ) -> None:
        class BoomVault(VaultLike):
            def get_secret_bundle(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                raise FakeOciException(404, "NotFound")

        client = OciSecretClient(resolved=resolved, vault=BoomVault(), kms=kms)
        with pytest.raises(SecretIntegrityException):
            client.read(_ref())

    def test_read_other_exception_raises_sec_provider_001(
        self,
        resolved,
        kms: FakeKms,
    ) -> None:
        class BoomVault(VaultLike):
            def get_secret_bundle(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                raise FakeOciException(500, "InternalError")

        client = OciSecretClient(resolved=resolved, vault=BoomVault(), kms=kms)
        with pytest.raises(SecretException) as exc_info:
            client.read(_ref())
        assert "SEC-PROVIDER-001" in str(exc_info.value)

    def test_metadata(self, client: OciSecretClient) -> None:
        meta = client.metadata(_ref())
        assert meta.version.number == "v7"
        assert meta.backend is SecretBackend.OCI

    def test_version_selector_static_version(
        self,
        client: OciSecretClient,
        vault: FakeVault,
    ) -> None:
        ref = SecretReference(
            provider="oci-us-ashburn-1",
            path="db-password",
            version_selector=SecretVersionSelector.of_static(
                SecretVersion(number="3", created_at=None),
            ),
        )
        client.read(ref)
        assert vault._calls[0]["version_number"] == 3  # type: ignore[attr-defined]
        assert vault._calls[0]["stage"] is None  # type: ignore[attr-defined]

    def test_version_selector_pinned_at_time(
        self,
        client: OciSecretClient,
        vault: FakeVault,
    ) -> None:
        from atlas_richie.secret.reference import SecretVersionSelectorKind

        ref = SecretReference(
            provider="oci-us-ashburn-1",
            path="db-password",
            version_selector=SecretVersionSelector(
                kind=SecretVersionSelectorKind.PINNED_AT_TIME,
                pinned_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        )
        client.read(ref)
        # PINNED_AT_TIME → LATEST in vault (no version, no stage)
        assert vault._calls[0]["version_number"] is None  # type: ignore[attr-defined]
        assert vault._calls[0]["stage"] is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# wrap_key() / unwrap_key()
# ---------------------------------------------------------------------------


def _kek() -> KeyReference:
    return KeyReference(provider="oci-us-ashburn-1", key_id="default-envelope")


class TestOciWrap:
    def test_wrap_then_unwrap(self, client: OciSecretClient, kms: FakeKms) -> None:
        wrapped = client.wrap_key(b"data-key-32-bytes-1234567890ab", _kek())
        assert wrapped.algorithm == "oci-kms-default"
        assert wrapped.kek_reference == _kek()
        ctx = CryptoContext(
            primary_key=_kek(),
            purpose=KeyPurpose.WRAP,
            aad={"tenant": "t1", "env": "prod"},
        )
        unwrapped = client.unwrap_key(wrapped, ctx)
        assert unwrapped == b"data-key-32-bytes-1234567890ab"
        # AAD round-trip is preserved
        assert kms._last_aad == {"tenant": "t1", "env": "prod"}  # type: ignore[attr-defined]

    def test_unwrap_with_no_aad(self, client: OciSecretClient) -> None:
        wrapped = client.wrap_key(b"data-key", _kek())
        ctx = CryptoContext(primary_key=_kek(), purpose=KeyPurpose.WRAP, aad={})
        unwrapped = client.unwrap_key(wrapped, ctx)
        assert unwrapped == b"data-key"

    def test_wrap_empty_dek_raises_crypto(self, client: OciSecretClient) -> None:
        with pytest.raises(SecretCryptoException) as exc_info:
            client.wrap_key(b"", _kek())
        assert "SEC-CRYPTO-001" in str(exc_info.value)

    def test_unwrap_wrong_algorithm_raises_crypto(self, client: OciSecretClient) -> None:
        bad = WrappedKey(
            kek_reference=_kek(),
            ciphertext=b"abc",
            algorithm="not-oci",
        )
        with pytest.raises(SecretCryptoException) as exc_info:
            client.unwrap_key(bad, CryptoContext(primary_key=_kek(), purpose=KeyPurpose.WRAP))
        assert "SEC-CRYPTO-002" in str(exc_info.value)

    def test_unwrap_empty_ciphertext_raises_crypto(self, client: OciSecretClient) -> None:
        bad = WrappedKey(
            kek_reference=_kek(),
            ciphertext=b"",
            algorithm="oci-kms-default",
        )
        with pytest.raises(SecretCryptoException) as exc_info:
            client.unwrap_key(bad, CryptoContext(primary_key=_kek(), purpose=KeyPurpose.WRAP))
        assert "SEC-CRYPTO-002" in str(exc_info.value)

    def test_wrap_missing_key_binding_raises_config(
        self,
        resolved,
        vault: FakeVault,
        kms: FakeKms,
    ) -> None:
        # properties has only "default-envelope" → ask for a different one
        client = OciSecretClient(resolved=resolved, vault=vault, kms=kms)
        bad_kek = KeyReference(provider="oci-us-ashburn-1", key_id="missing-key")
        with pytest.raises(SecretConfigurationException) as exc_info:
            client.wrap_key(b"data", bad_kek)
        assert "SEC-KEY-001" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestOciLifecycle:
    def test_close_idempotent(self, client: OciSecretClient) -> None:
        client.close()
        client.close()
        assert client.is_closed is True

    def test_read_after_close_raises(self, client: OciSecretClient) -> None:
        client.close()
        with pytest.raises(SecretException):
            client.read(_ref())

    def test_configuration_property(
        self,
        client: OciSecretClient,
        base_properties: OciSecretProperties,
    ) -> None:
        cfg = client.configuration
        assert cfg.name == "oci-us-ashburn-1"
        assert cfg.namespace == base_properties.region
        assert cfg.timeout_seconds == base_properties.read_timeout_seconds
        assert cfg.retries == base_properties.max_attempts


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestOciFactory:
    def test_factory_descriptor(self, base_properties: OciSecretProperties) -> None:
        from atlas_richie.secret_oci_vault_kms.factory import OciSecretProviderFactory

        factory = OciSecretProviderFactory(base_properties)
        descriptor = factory.descriptor()
        assert descriptor.name == "oci-us-ashburn-1"
        assert descriptor.backend is SecretBackend.OCI

    def test_factory_default_configuration(
        self,
        base_properties: OciSecretProperties,
    ) -> None:
        from atlas_richie.secret_oci_vault_kms.factory import OciSecretProviderFactory

        factory = OciSecretProviderFactory(base_properties)
        cfg = factory.default_configuration()
        assert cfg.name == "oci-us-ashburn-1"
        assert cfg.namespace == "us-ashburn-1"

    def test_factory_create_with_fakes(
        self,
        base_properties: OciSecretProperties,
    ) -> None:
        from atlas_richie.secret_oci_vault_kms.factory import OciSecretProviderFactory

        factory = OciSecretProviderFactory(
            base_properties,
            client_factory=lambda _props: (FakeVault(), FakeKms()),
        )
        session = factory.create(factory.default_configuration())
        assert session.descriptor.name == "oci-us-ashburn-1"
        assert session.operations is not None  # SECRET_READ capable
        # Smoke: read works
        value = session.read(_ref())
        assert bytes(value.plaintext) == b"secret-value"
        session.close()
