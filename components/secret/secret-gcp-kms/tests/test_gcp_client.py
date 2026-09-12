"""`GcpSecretClient` tests — 4-SPI composite via mocked GCP SDK clients."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from google.api_core import exceptions as gapi_exceptions

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

pytestmark = pytest.mark.integration


def _make_sm_response(value: str, version: str = "1"):
    response = MagicMock()
    response.payload.data = value.encode("utf-8")
    response.name = f"projects/p/secrets/db/versions/{version}"
    return response


# --- SecretOperations ----------------------------------------------------


def test_sm_get_roundtrip(gcp_session, gcp_sm_client_mock) -> None:
    gcp_sm_client_mock.access_secret_version.return_value = _make_sm_response("s3cret")
    ref = SecretReference(provider=gcp_session.descriptor.name, path="db")
    value = gcp_session.get(ref)
    assert value.plaintext == b"s3cret"
    assert value.metadata.backend is SecretBackend.GCP


def test_sm_get_passes_version(gcp_session, gcp_sm_client_mock) -> None:
    gcp_sm_client_mock.access_secret_version.return_value = _make_sm_response("x", "3")
    ref = SecretReference(
        provider=gcp_session.descriptor.name, path="db",
    ).with_version(SecretVersionSelector.of_static(SecretVersion(number="3")))
    gcp_session.get(ref)
    call = gcp_sm_client_mock.access_secret_version.call_args
    assert "versions/3" in call.kwargs["request"].name


def test_sm_get_metadata(gcp_session, gcp_sm_client_mock) -> None:
    gcp_sm_client_mock.access_secret_version.return_value = _make_sm_response("x", "5")
    ref = SecretReference(provider=gcp_session.descriptor.name, path="db")
    md = gcp_session.get_metadata(ref)
    assert md.backend is SecretBackend.GCP
    assert md.version.number == "5"


def test_sm_exists_true_and_false(gcp_session, gcp_sm_client_mock) -> None:
    gcp_sm_client_mock.access_secret_version.return_value = _make_sm_response("x")
    ref_present = SecretReference(provider=gcp_session.descriptor.name, path="db")
    assert gcp_session.exists(ref_present) is True

    gcp_sm_client_mock.access_secret_version.side_effect = gapi_exceptions.NotFound("missing")
    ref_absent = SecretReference(provider=gcp_session.descriptor.name, path="nope")
    assert gcp_session.exists(ref_absent) is False


def test_sm_missing_raises_integrity(gcp_session, gcp_sm_client_mock) -> None:
    gcp_sm_client_mock.access_secret_version.side_effect = gapi_exceptions.NotFound("missing")
    ref = SecretReference(provider=gcp_session.descriptor.name, path="nope")
    with pytest.raises(SecretIntegrityException):
        gcp_session.get(ref)


# --- KeyWrappingBackend --------------------------------------------------


def test_kms_wrap_unwrap_roundtrip(gcp_session, gcp_kms_client_mock) -> None:
    encrypt_result = MagicMock()
    encrypt_result.ciphertext = b"wrapped-bytes"
    decrypt_result = MagicMock()
    decrypt_result.plaintext = b"original-32-bytes-dek-padding"
    gcp_kms_client_mock.encrypt.return_value = encrypt_result
    gcp_kms_client_mock.decrypt.return_value = decrypt_result

    kek = KeyReference(
        provider="gcp",
        key_id="projects/p/locations/global/keyRings/r/cryptoKeys/k",
    )
    dek = b"original-32-bytes-dek-padding"
    wrapped = gcp_session.wrap_key(dek, kek)
    assert wrapped.algorithm == "gcp-kms-symmetric"
    back = gcp_session.unwrap_key(
        wrapped, CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP),
    )
    assert back == dek


def test_kms_wrap_rejects_empty_dek(gcp_session) -> None:
    kek = KeyReference(provider="gcp", key_id="any")
    with pytest.raises(Exception):
        gcp_session.wrap_key(b"", kek)


def test_kms_unwrap_rejects_wrong_algorithm(gcp_session) -> None:
    from atlas_richie.secret.crypto import WrappedKey
    bogus = WrappedKey(
        kek_reference=KeyReference(provider="gcp", key_id="any"),
        ciphertext=b"dummy",
        algorithm="wrong-alg",
    )
    with pytest.raises(Exception) as exc:
        gcp_session.unwrap_key(
            bogus,
            CryptoContext(
                primary_key=KeyReference(provider="gcp", key_id="any"),
                purpose=KeyPurpose.WRAP,
            ),
        )
    assert "wrong-alg" in str(exc.value) or "algorithm" in str(exc.value)


def test_kms_unwrap_404_maps_to_crypto_exception(gcp_session, gcp_kms_client_mock) -> None:
    gcp_kms_client_mock.decrypt.side_effect = gapi_exceptions.NotFound("key not found")
    from atlas_richie.secret.crypto import WrappedKey
    wrapped = WrappedKey(
        kek_reference=KeyReference(provider="gcp", key_id="missing"),
        ciphertext=b"somebytes",
        algorithm="gcp-kms-symmetric",
    )
    with pytest.raises(Exception) as exc:
        gcp_session.unwrap_key(
            wrapped,
            CryptoContext(
                primary_key=KeyReference(provider="gcp", key_id="missing"),
                purpose=KeyPurpose.WRAP,
            ),
        )
    assert "SEC-KEY-001" in str(exc.value)


# --- Key bindings --------------------------------------------------------


def test_kms_key_bindings_resolves_logical_to_physical(
    gcp_session, gcp_kms_client_mock,
) -> None:
    encrypt_result = MagicMock()
    encrypt_result.ciphertext = b"wrapped"
    decrypt_result = MagicMock()
    decrypt_result.plaintext = b"original-32-bytes-dek-padding"
    gcp_kms_client_mock.encrypt.return_value = encrypt_result
    gcp_kms_client_mock.decrypt.return_value = decrypt_result

    from atlas_richie.secret_gcp_kms import (
        GcpSecretProperties,
        GcpSecretProviderFactory,
    )
    properties = GcpSecretProperties(
        project_id="p",
        kms_key_bindings={"logical-master": "projects/p/locations/global/keyRings/r/cryptoKeys/k"},
    )
    factory = GcpSecretProviderFactory(
        properties=properties,
        name="gcp-key-bindings",
        client_factory=lambda _p: (MagicMock(), gcp_kms_client_mock),
    )
    session = factory.create(factory.default_configuration())
    try:
        kek = KeyReference(provider="gcp", key_id="logical-master")
        dek = b"original-32-bytes-dek-padding"
        wrapped = session.wrap_key(dek, kek)
        back = session.unwrap_key(
            wrapped, CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP),
        )
        assert back == dek
    finally:
        session.close()


# --- Bootstrap -----------------------------------------------------------


def test_bootstrap_resolves_all(gcp_session, gcp_sm_client_mock) -> None:
    gcp_sm_client_mock.access_secret_version.side_effect = lambda request: _make_sm_response(
        f"value-of-{request.name.split('/')[3]}"
    )
    catalog = SecretBindingCatalog(
        name="boot",
        bindings=(
            SecretBinding(
                name="DB",
                reference=SecretReference(
                    provider=gcp_session.descriptor.name, path="db",
                ),
                required_when=RequiredWhen.STARTUP,
            ),
            SecretBinding(
                name="API",
                reference=SecretReference(
                    provider=gcp_session.descriptor.name, path="api",
                ),
                required_when=RequiredWhen.STARTUP,
            ),
        ),
    )
    result = gcp_session.bootstrap(
        SecretBootstrapRequest(catalog=catalog),
        DefaultBootstrapContext(),
    )
    assert set(result.resolved.keys()) == {"DB", "API"}


def test_bootstrap_raises_on_missing_startup(gcp_session, gcp_sm_client_mock) -> None:
    gcp_sm_client_mock.access_secret_version.side_effect = gapi_exceptions.NotFound("missing")
    catalog = SecretBindingCatalog(
        name="boot-missing",
        bindings=(
            SecretBinding(
                name="NEVER",
                reference=SecretReference(
                    provider=gcp_session.descriptor.name, path="nope",
                ),
                required_when=RequiredWhen.STARTUP,
            ),
        ),
    )
    with pytest.raises(SecretException) as exc:
        gcp_session.bootstrap(
            SecretBootstrapRequest(catalog=catalog),
            DefaultBootstrapContext(),
        )
    assert "NEVER" in str(exc.value)


def test_bootstrap_tolerates_missing_optional(gcp_session, gcp_sm_client_mock) -> None:
    gcp_sm_client_mock.access_secret_version.side_effect = gapi_exceptions.NotFound("missing")
    catalog = SecretBindingCatalog(
        name="boot-optional",
        bindings=(
            SecretBinding(
                name="MAYBE",
                reference=SecretReference(
                    provider=gcp_session.descriptor.name, path="nope",
                ),
                required_when=RequiredWhen.OPTIONAL,
            ),
        ),
    )
    result = gcp_session.bootstrap(
        SecretBootstrapRequest(catalog=catalog),
        DefaultBootstrapContext(),
    )
    assert result.resolved == {}
    assert result.missing == ("MAYBE",)


# --- Session lifecycle ---------------------------------------------------


def test_session_close_is_idempotent(gcp_session) -> None:
    gcp_session.close()
    gcp_session.close()
    assert gcp_session.is_closed


def test_post_close_raises(gcp_session) -> None:
    gcp_session.close()
    ref = SecretReference(provider=gcp_session.descriptor.name, path="any")
    with pytest.raises(SecretException) as exc:
        gcp_session.get(ref)
    assert "is closed" in str(exc.value)


def test_descriptor_and_configuration(gcp_session) -> None:
    d = gcp_session.descriptor
    cfg = gcp_session.configuration
    assert d.backend is SecretBackend.GCP
    assert cfg.namespace == "test-project"


def test_writer_deletable_signing_are_none(gcp_session) -> None:
    assert gcp_session.writer is None
    assert gcp_session.deletable is None
    assert gcp_session.signing is None
