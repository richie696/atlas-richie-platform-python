"""`Pkcs11SecretClient` integration tests — real SoftHSM roundtrip.

中文
----
真 SoftHSM roundtrip,每个 test 启动前清空残留 `test-rsa` key,
用 `pkcs11_rsa_keypair` fixture 生成新的 RSA-2048 keypair。

English
--------
End-to-end integration tests against SoftHSM. RSA-2048 keypair
generated per test via `pkcs11_rsa_keypair` fixture.
"""

from __future__ import annotations

import pytest

from atlas_richie.secret import SecretException
from atlas_richie.secret.crypto import (
    CryptoContext,
    KeyPurpose,
    KeyReference,
)

pytestmark = pytest.mark.integration


# --- KeyWrappingBackend --------------------------------------------------


def test_wrap_unwrap_roundtrip(pkcs11_session_client) -> None:
    kek = KeyReference(provider="pkcs11", key_id="test-rsa")
    dek = b"32-byte-data-encryption-key!!!!"
    wrapped = pkcs11_session_client.wrap_key(dek, kek)
    assert wrapped.algorithm == "pkcs11-rsa-oaep"
    assert wrapped.ciphertext  # non-empty RSA-OAEP ciphertext
    back = pkcs11_session_client.unwrap_key(
        wrapped, CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP),
    )
    assert back == dek


def test_wrap_rejects_empty_dek(pkcs11_session_client) -> None:
    kek = KeyReference(provider="pkcs11", key_id="test-rsa")
    from atlas_richie.secret.errors import SecretCryptoException
    with pytest.raises(SecretCryptoException):
        pkcs11_session_client.wrap_key(b"", kek)


def test_unwrap_rejects_wrong_algorithm(pkcs11_session_client) -> None:
    from atlas_richie.secret.crypto import WrappedKey
    from atlas_richie.secret.errors import SecretCryptoException
    bogus = WrappedKey(
        kek_reference=KeyReference(provider="pkcs11", key_id="test-rsa"),
        ciphertext=b"dummy",
        algorithm="wrong-alg",
    )
    with pytest.raises(SecretCryptoException) as exc:
        pkcs11_session_client.unwrap_key(
            bogus,
            CryptoContext(
                primary_key=KeyReference(provider="pkcs11", key_id="test-rsa"),
                purpose=KeyPurpose.WRAP,
            ),
        )
    assert "wrong-alg" in str(exc.value) or "algorithm" in str(exc.value)


def test_wrap_unknown_key_raises(pkcs11_session_client) -> None:
    from atlas_richie.secret.errors import SecretCryptoException
    kek = KeyReference(provider="pkcs11", key_id="nonexistent-key")
    with pytest.raises(SecretCryptoException) as exc:
        pkcs11_session_client.wrap_key(b"32-bytes-data-key-1234567890", kek)
    assert "SEC-KEY-001" in str(exc.value)


def test_key_bindings_resolves_logical_to_physical(pkcs11_session_client) -> None:
    """The `key_bindings` map translates a logical name to the
    physical HSM key label.
    """
    # pkcs11_session_client fixture sets `key_bindings =
    # {"test-rsa-logical": "test-rsa"}`, so wrap with the
    # logical name should resolve to the physical `test-rsa`
    # key.
    kek = KeyReference(provider="pkcs11", key_id="test-rsa-logical")
    dek = b"32-byte-data-encryption-key!!!!"
    wrapped = pkcs11_session_client.wrap_key(dek, kek)
    back = pkcs11_session_client.unwrap_key(
        wrapped, CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP),
    )
    assert back == dek


# --- SigningBackend ------------------------------------------------------


def test_sign_verify_roundtrip(pkcs11_session_client) -> None:
    key = KeyReference(provider="pkcs11", key_id="test-rsa")
    sig = pkcs11_session_client.sign(b"hello-hsm", key)
    assert sig.algorithm == "SHA256_RSA_PKCS"
    assert sig.signature  # non-empty RSA signature
    assert pkcs11_session_client.verify(b"hello-hsm", sig) is True


def test_verify_rejects_tampered_payload(pkcs11_session_client) -> None:
    key = KeyReference(provider="pkcs11", key_id="test-rsa")
    sig = pkcs11_session_client.sign(b"original", key)
    assert pkcs11_session_client.verify(b"tampered", sig) is False


def test_sign_rejects_empty_payload(pkcs11_session_client) -> None:
    key = KeyReference(provider="pkcs11", key_id="test-rsa")
    from atlas_richie.secret.errors import SecretCryptoException
    with pytest.raises(SecretCryptoException):
        pkcs11_session_client.sign(b"", key)


# --- Session lifecycle ---------------------------------------------------


def test_session_close_is_idempotent(pkcs11_session_client) -> None:
    pkcs11_session_client.close()
    pkcs11_session_client.close()
    assert pkcs11_session_client.is_closed


def test_post_close_raises(pkcs11_session_client) -> None:
    pkcs11_session_client.close()
    kek = KeyReference(provider="pkcs11", key_id="test-rsa")
    with pytest.raises(SecretException) as exc:
        pkcs11_session_client.wrap_key(b"32-byte-data-encryption-key!!!!", kek)
    assert "is closed" in str(exc.value)


def test_descriptor_and_configuration(pkcs11_session_client) -> None:
    from atlas_richie.secret.metadata import SecretBackend
    d = pkcs11_session_client.descriptor
    cfg = pkcs11_session_client.configuration
    assert d.backend is SecretBackend.PKCS11
    assert cfg.namespace == "atlas-test"


def test_operations_writer_deletable_are_none(pkcs11_session_client) -> None:
    """HSM has no secret storage — operations / writer /
    deletable all return None (mirrors Java's
    Pkcs11SecretClient 4-SPI scope)."""
    assert pkcs11_session_client.operations is None
    assert pkcs11_session_client.writer is None
    assert pkcs11_session_client.deletable is None
