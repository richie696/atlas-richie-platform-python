"""`AzureSecretClient` tests — 4-SPI composite via mocked SDK clients.

中文
----
Azure 没本地 emulator,所以 SDK client 用 `MagicMock` 模拟,测试
覆盖 4 个 SPI 角色(对位 Java `AzureSecretBootstrapProviderFactory`
+ `AbstractRemoteProviderFactory` 的 capability 声明):

- `SecretOperations` — get / get_version / get_metadata / exists
- `KeyWrappingBackend` — wrap_key (RSA-OAEP-256) / unwrap_key
- `SecretBootstrapClient` — STARTUP 必填 + optional 容忍
- `SecretProviderSession` — close idempotent + post-close + signing=None

`writer` / `deletable` / `signing` 都返回 None(对位 Java 4-SPI 窄范围)。

English
--------
Tests for the 4-SPI composite. SDK clients are MagicMock because
Azure has no local emulator. Per-test MagicMock.return_value is
used to provide specific responses (e.g. `KeyVaultSecret` with
properties).

The same tests are runnable against real Azure by swapping
`azure_secret_client_mock` / `azure_key_client_mock` for real
`SecretClient` / `KeyClient` instances (see
`tests/conftest.py::real_azure_session`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from atlas_richie.secret import (
    SecretException,
    SecretIntegrityException,
    SecretReference,
    SecretVersion,
    SecretVersionSelector,
)
from atlas_richie.secret.bootstrap.catalog import (
    RequiredWhen,
    SecretBinding,
    SecretBindingCatalog,
)
from atlas_richie.secret.bootstrap.spi import (
    DefaultBootstrapContext,
    SecretBootstrapRequest,
)
from atlas_richie.secret.crypto import (
    CryptoContext,
    KeyPurpose,
    KeyReference,
)
from atlas_richie.secret.metadata import SecretBackend
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
)

pytestmark = pytest.mark.integration


# --- Helpers --------------------------------------------------------------


def _make_secret(value: str, version: str = "v1", created_at: datetime | None = None):
    """Build a `MagicMock` that imitates `KeyVaultSecret`."""
    secret = MagicMock()
    secret.value = value
    secret.properties = MagicMock()
    secret.properties.version = version
    secret.properties.created_on = created_at or datetime.now(tz=timezone.utc)
    secret.properties.expires_on = None
    return secret


# --- SecretOperations -----------------------------------------------------


def test_sm_get_roundtrip(azure_session, azure_secret_client_mock) -> None:
    azure_secret_client_mock.get_secret.return_value = _make_secret("s3cret")
    ref = SecretReference(provider=azure_session.descriptor.name, path="db")
    value = azure_session.get(ref)
    assert value.plaintext == b"s3cret"
    assert value.metadata.backend is SecretBackend.AZURE


def test_sm_get_passes_version(azure_session, azure_secret_client_mock) -> None:
    azure_secret_client_mock.get_secret.return_value = _make_secret("pinned")
    ref = SecretReference(
        provider=azure_session.descriptor.name,
        path="db",
    ).with_version(SecretVersionSelector.of_static(SecretVersion(number="v3")))
    azure_session.get(ref)
    azure_secret_client_mock.get_secret.assert_called_once_with("db", version="v3")


def test_sm_get_metadata(azure_session, azure_secret_client_mock) -> None:
    azure_secret_client_mock.get_secret.return_value = _make_secret("x", version="v7")
    ref = SecretReference(provider=azure_session.descriptor.name, path="db")
    md = azure_session.get_metadata(ref)
    assert md.backend is SecretBackend.AZURE
    assert md.version.number == "v7"


def test_sm_exists_true_and_false(azure_session, azure_secret_client_mock) -> None:
    azure_secret_client_mock.get_secret.return_value = _make_secret("x")
    ref_present = SecretReference(provider=azure_session.descriptor.name, path="db")
    assert azure_session.exists(ref_present) is True

    azure_secret_client_mock.get_secret.side_effect = ResourceNotFoundError("missing")
    ref_absent = SecretReference(provider=azure_session.descriptor.name, path="missing")
    assert azure_session.exists(ref_absent) is False


def test_sm_missing_raises_integrity(azure_session, azure_secret_client_mock) -> None:
    azure_secret_client_mock.get_secret.side_effect = ResourceNotFoundError("missing")
    ref = SecretReference(provider=azure_session.descriptor.name, path="nope")
    with pytest.raises(SecretIntegrityException):
        azure_session.get(ref)


def test_sm_auth_error_maps_to_secret_exception(
    azure_session, azure_secret_client_mock,
) -> None:
    err = HttpResponseError("auth")
    err.status_code = 401
    azure_secret_client_mock.get_secret.side_effect = err
    ref = SecretReference(provider=azure_session.descriptor.name, path="db")
    with pytest.raises(SecretException) as exc:
        azure_session.get(ref)
    assert "SEC-AUTH-001" in str(exc.value)


# --- KeyWrappingBackend ----------------------------------------------------


def test_kms_wrap_unwrap_roundtrip(azure_session, azure_key_client_mock) -> None:
    # wrap_key returns a mock with `.encrypted_key`; unwrap_key
    # returns a mock with `.key`.
    wrap_result = MagicMock()
    wrap_result.encrypted_key = b"wrapped-bytes"
    unwrap_result = MagicMock()
    unwrap_result.key = b"the-original-32-byte-data-key!"
    azure_key_client_mock.wrap_key.return_value = wrap_result
    azure_key_client_mock.unwrap_key.return_value = unwrap_result

    kek = KeyReference(provider="azure", key_id="prod-rsa-2048")
    dek = b"the-original-32-byte-data-key!"
    wrapped = azure_session.wrap_key(dek, kek)
    assert wrapped.algorithm == "azure-keyvault-local-wrap"
    back = azure_session.unwrap_key(
        wrapped, CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP),
    )
    assert back == dek


def test_kms_wrap_rejects_empty_dek(azure_session) -> None:
    kek = KeyReference(provider="azure", key_id="prod-rsa-2048")
    with pytest.raises(Exception):
        azure_session.wrap_key(b"", kek)


def test_kms_unwrap_rejects_wrong_algorithm(azure_session) -> None:
    from atlas_richie.secret.crypto import WrappedKey
    bogus = WrappedKey(
        kek_reference=KeyReference(provider="azure", key_id="prod-rsa-2048"),
        ciphertext=b"dummy",
        algorithm="wrong-alg",
    )
    with pytest.raises(Exception) as exc:
        azure_session.unwrap_key(
            bogus,
            CryptoContext(
                primary_key=KeyReference(provider="azure", key_id="prod-rsa-2048"),
                purpose=KeyPurpose.WRAP,
            ),
        )
    assert "wrong-alg" in str(exc.value) or "algorithm" in str(exc.value)


def test_kms_unwrap_404_maps_to_crypto_exception(
    azure_session, azure_key_client_mock,
) -> None:
    err = HttpResponseError("key not found")
    err.status_code = 404
    azure_key_client_mock.unwrap_key.side_effect = err
    from atlas_richie.secret.crypto import WrappedKey
    wrapped = WrappedKey(
        kek_reference=KeyReference(provider="azure", key_id="missing"),
        ciphertext=b"somebytes",
        algorithm="azure-keyvault-local-wrap",
    )
    with pytest.raises(Exception) as exc:
        azure_session.unwrap_key(
            wrapped,
            CryptoContext(
                primary_key=KeyReference(provider="azure", key_id="missing"),
                purpose=KeyPurpose.WRAP,
            ),
        )
    assert "SEC-KEY-001" in str(exc.value)


# --- Key bindings (logical -> physical) -----------------------------------


def test_kms_key_bindings_resolves_logical_to_physical(
    azure_session, azure_key_client_mock,
) -> None:
    wrap_result = MagicMock()
    wrap_result.encrypted_key = b"wrapped-bytes"
    unwrap_result = MagicMock()
    unwrap_result.key = b"original-32-bytes-dek-padding!"
    azure_key_client_mock.wrap_key.return_value = wrap_result
    azure_key_client_mock.unwrap_key.return_value = unwrap_result

    from atlas_richie.secret_azure_keyvault import (
        AzureSecretProperties,
        AzureSecretProviderFactory,
    )
    properties = AzureSecretProperties(
        vault_url="https://x.vault.azure.net/",
        key_bindings={"logical-master": "prod-rsa-2048"},
    )
    factory = AzureSecretProviderFactory(
        properties=properties,
        name="azure-key-bindings",
        client_factory=lambda _p: (MagicMock(), azure_key_client_mock),
    )
    session = factory.create(factory.default_configuration())
    try:
        kek = KeyReference(provider="azure", key_id="logical-master")
        dek = b"original-32-bytes-dek-padding!"
        wrapped = session.wrap_key(dek, kek)
        back = session.unwrap_key(
            wrapped, CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP),
        )
        assert back == dek
    finally:
        session.close()


# --- Bootstrap ------------------------------------------------------------


def test_bootstrap_resolves_all(azure_session, azure_secret_client_mock) -> None:
    def _by_path(name, **kwargs):
        return _make_secret(f"value-of-{name}")
    azure_secret_client_mock.get_secret.side_effect = _by_path
    catalog = SecretBindingCatalog(
        name="boot",
        bindings=(
            SecretBinding(
                name="DB",
                reference=SecretReference(
                    provider=azure_session.descriptor.name, path="db",
                ),
                required_when=RequiredWhen.STARTUP,
            ),
            SecretBinding(
                name="API",
                reference=SecretReference(
                    provider=azure_session.descriptor.name, path="api",
                ),
                required_when=RequiredWhen.STARTUP,
            ),
        ),
    )
    result = azure_session.bootstrap(
        SecretBootstrapRequest(catalog=catalog),
        DefaultBootstrapContext(),
    )
    assert set(result.resolved.keys()) == {"DB", "API"}
    assert result.missing == ()


def test_bootstrap_raises_on_missing_startup(azure_session, azure_secret_client_mock) -> None:
    azure_secret_client_mock.get_secret.side_effect = ResourceNotFoundError("missing")
    catalog = SecretBindingCatalog(
        name="boot-missing",
        bindings=(
            SecretBinding(
                name="NEVER",
                reference=SecretReference(
                    provider=azure_session.descriptor.name, path="nope",
                ),
                required_when=RequiredWhen.STARTUP,
            ),
        ),
    )
    with pytest.raises(SecretException) as exc:
        azure_session.bootstrap(
            SecretBootstrapRequest(catalog=catalog),
            DefaultBootstrapContext(),
        )
    assert "NEVER" in str(exc.value)


def test_bootstrap_tolerates_missing_optional(azure_session, azure_secret_client_mock) -> None:
    azure_secret_client_mock.get_secret.side_effect = ResourceNotFoundError("missing")
    catalog = SecretBindingCatalog(
        name="boot-optional",
        bindings=(
            SecretBinding(
                name="MAYBE",
                reference=SecretReference(
                    provider=azure_session.descriptor.name, path="nope",
                ),
                required_when=RequiredWhen.OPTIONAL,
            ),
        ),
    )
    result = azure_session.bootstrap(
        SecretBootstrapRequest(catalog=catalog),
        DefaultBootstrapContext(),
    )
    assert result.resolved == {}
    assert result.missing == ("MAYBE",)


# --- Session lifecycle ---------------------------------------------------


def test_session_close_is_idempotent(azure_session) -> None:
    azure_session.close()
    azure_session.close()
    assert azure_session.is_closed


def test_post_close_raises(azure_session) -> None:
    azure_session.close()
    ref = SecretReference(
        provider=azure_session.descriptor.name, path="any",
    )
    with pytest.raises(SecretException) as exc:
        azure_session.get(ref)
    assert "is closed" in str(exc.value)


def test_descriptor_and_configuration(azure_session) -> None:
    d = azure_session.descriptor
    cfg = azure_session.configuration
    assert d.backend is SecretBackend.AZURE
    assert d.version == "0.2.0"
    assert cfg.namespace == "https://test-vault.vault.azure.net/"


def test_writer_deletable_signing_are_none(azure_session) -> None:
    """`AzureSecretClient` is the narrower 4-SPI composite:
    no `SecretWriter`, no `SecretDeletable`, no `SigningBackend`
    (Java's `AbstractRemoteProviderFactory` declares only
    SECRET_READ / SECRET_VERSIONING / KEY_WRAP / KEY_UNWRAP)."""
    assert azure_session.writer is None
    assert azure_session.deletable is None
    assert azure_session.signing is None
