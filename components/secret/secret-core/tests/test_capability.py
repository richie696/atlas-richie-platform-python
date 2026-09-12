"""Capability gate tests — AAD / read / write guards + capability fingerprint.

中文
----
对位 Java 端 `RemoteSecretProviderClient` 的 capability 门禁。
覆盖:
- `require_aad_support` 对非空 AAD + 显式"不支持"门 抛
  `SEC-CAP-001`
- `has_aad` 对 None / 空 Mapping / 非空 Mapping 三种情况
- `assert_can_read` / `assert_can_write` 对 capability flag
  翻转抛 / 不抛
- `assert_capability` 通用门
- `capability_fingerprint` 稳定 + capability 改变会变

English
--------
Tests for `crypto.capability` gates (R-242 SDK refactor).
Mirrors Java's `RemoteSecretProviderClient` capability
gates.
"""

from __future__ import annotations

import pytest

from atlas_richie.secret.crypto import (
    CryptoContext,
    KeyPurpose,
    KeyReference,
    assert_can_read,
    assert_can_write,
    assert_capability,
    capability_fingerprint,
    has_aad,
    require_aad_support,
)
from atlas_richie.secret.errors import SecretCapabilityException
from atlas_richie.secret.metadata import SecretCapability


def _kek() -> KeyReference:
    return KeyReference(
        provider="test",
        key_id="alias/test",
        version=None,
        algorithm="AES-256",
    )


class TestRequireAadSupport:
    def test_none_context_ok(self) -> None:
        # Even when the backend does not support AAD, a None
        # context (no AAD attached) is accepted.
        require_aad_support(
            SecretCapability(can_read=True, can_write=False, can_rotate=False,
                             can_list=False, encrypts_at_rest=True,
                             signs_values=False, cacheable=False),
            context=None,
            backend_label="azure",
        )

    def test_empty_aad_ok(self) -> None:
        context = CryptoContext(primary_key=_kek(), purpose=KeyPurpose.WRAP, aad={})
        require_aad_support(
            SecretCapability(can_read=True, can_write=False, can_rotate=False,
                             can_list=False, encrypts_at_rest=True,
                             signs_values=False, cacheable=False),
            context=context,
            backend_label="azure",
        )

    def test_non_empty_aad_raises_capability(self) -> None:
        context = CryptoContext(
            primary_key=_kek(),
            purpose=KeyPurpose.WRAP,
            aad={"path": "secret/orders"},
        )
        with pytest.raises(SecretCapabilityException) as info:
            require_aad_support(
                SecretCapability(can_read=False, can_write=False,
                                 can_rotate=False, can_list=False,
                                 encrypts_at_rest=True, signs_values=False,
                                 cacheable=False),
                context=context,
                backend_label="azure",
            )
        assert "SEC-CAP-001" in str(info.value)
        assert "azure" in str(info.value)


class TestHasAad:
    def test_none_is_false(self) -> None:
        assert has_aad(None) is False

    def test_empty_is_false(self) -> None:
        context = CryptoContext(primary_key=_kek(), purpose=KeyPurpose.WRAP, aad={})
        assert has_aad(context) is False

    def test_non_empty_is_true(self) -> None:
        context = CryptoContext(
            primary_key=_kek(),
            purpose=KeyPurpose.WRAP,
            aad={"x": "y"},
        )
        assert has_aad(context) is True


class TestAssertCanRead:
    def test_read_capability_ok(self) -> None:
        cap = SecretCapability(can_read=True, can_write=False, can_rotate=False,
                               can_list=False, encrypts_at_rest=True,
                               signs_values=False, cacheable=False)
        assert_can_read(cap, backend_label="vault")  # does not raise

    def test_no_read_capability_raises(self) -> None:
        cap = SecretCapability(can_read=False, can_write=False, can_rotate=False,
                               can_list=False, encrypts_at_rest=True,
                               signs_values=False, cacheable=False)
        with pytest.raises(SecretCapabilityException) as info:
            assert_can_read(cap, backend_label="pkcs11")
        assert "SEC-CAP-001" in str(info.value)
        assert "pkcs11" in str(info.value)


class TestAssertCanWrite:
    def test_write_capability_ok(self) -> None:
        cap = SecretCapability(can_read=True, can_write=True, can_rotate=False,
                               can_list=False, encrypts_at_rest=True,
                               signs_values=False, cacheable=False)
        assert_can_write(cap, backend_label="vault")

    def test_no_write_capability_raises(self) -> None:
        cap = SecretCapability(can_read=True, can_write=False, can_rotate=False,
                               can_list=False, encrypts_at_rest=True,
                               signs_values=False, cacheable=False)
        with pytest.raises(SecretCapabilityException) as info:
            assert_can_write(cap, backend_label="aws")
        assert "SEC-CAP-001" in str(info.value)


class TestAssertCapability:
    def test_can_read_required_and_available(self) -> None:
        cap = SecretCapability(can_read=True, can_write=False, can_rotate=False,
                               can_list=False, encrypts_at_rest=True,
                               signs_values=False, cacheable=False)
        assert_capability(cap, required=True, backend_label="vault",
                          operation="read")
        assert_capability(cap, required=False, backend_label="vault",
                          operation="metadata")

    def test_can_read_required_and_unavailable(self) -> None:
        cap = SecretCapability(can_read=False, can_write=False, can_rotate=False,
                               can_list=False, encrypts_at_rest=True,
                               signs_values=False, cacheable=False)
        with pytest.raises(SecretCapabilityException) as info:
            assert_capability(cap, required=True, backend_label="kmip",
                              operation="read")
        assert "kmip" in str(info.value)


class TestCapabilityFingerprint:
    def test_fingerprint_stable(self) -> None:
        cap = SecretCapability(can_read=True, can_write=False, can_rotate=False,
                               can_list=False, encrypts_at_rest=True,
                               signs_values=False, cacheable=False)
        a = capability_fingerprint(cap)
        b = capability_fingerprint(cap)
        assert a == b
        assert "can_read=True" in a
        assert "encrypts_at_rest=True" in a

    def test_fingerprint_changes_with_capability(self) -> None:
        a = SecretCapability(can_read=True, can_write=False, can_rotate=False,
                             can_list=False, encrypts_at_rest=True,
                             signs_values=False, cacheable=False)
        b = SecretCapability(can_read=True, can_write=True, can_rotate=False,
                             can_list=False, encrypts_at_rest=True,
                             signs_values=False, cacheable=False)
        assert capability_fingerprint(a) != capability_fingerprint(b)


__all__ = []
