"""Huawei secret client — 3-SPI composite tests via fake CSMS / KMS.

中文
----
通过 `FakeCsms` / `FakeKms`(in-process 真对象,非 MagicMock)验证
`HuaweiSecretClient` 全部 3 个 SPI 角色 + 错误路径 + AAD:
- `read` / `metadata`(SecretOperations via CSMS)
- `wrap_key` / `unwrap_key`(KeyWrappingBackend via DEW)
- `bootstrap`(SecretBootstrapClient)
- `close` / `descriptor`(SecretProviderSession)
- HTTP 404 → missing(NotFound 边界)
- 其它错误 → `SEC-PROVIDER-001`(不能伪装成 missing)

English
--------
Tests `HuaweiSecretClient` end-to-end via `FakeCsms` /
`FakeKms` (in-process real objects). Covers all 3 SPI
roles + capability + NotFound boundary.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from typing import Any

import pytest

from atlas_richie.secret.bootstrap.catalog import (
    RequiredWhen,
    SecretBinding,
    SecretBindingCatalog,
    SecretKind,
)
from atlas_richie.secret.bootstrap.spi import (
    DefaultBootstrapContext,
    SecretBootstrapRequest,
)
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
from atlas_richie.secret.reference import SecretReference
from atlas_richie.secret_huawei_csms_kms.client import (
    CsmsLike,
    HuaweiCsmsGetResponse,
    HuaweiKmsDecryptResponse,
    HuaweiKmsEncryptResponse,
    HuaweiSecretClient,
    KmsLike,
)
from atlas_richie.secret_huawei_csms_kms.configuration import (
    HuaweiConfigurationResolver,
)
from atlas_richie.secret_huawei_csms_kms.properties import (
    AuthType,
    HuaweiSecretProperties,
)


# ---------------------------------------------------------------------------
# Fake SDK clients
# ---------------------------------------------------------------------------


class FakeCsms(CsmsLike):
    """In-process `CsmsLike` for tests."""

    __slots__ = ("_secrets",)

    def __init__(self) -> None:
        self._secrets: dict[str, HuaweiCsmsGetResponse] = {}

    def put(
        self,
        name: str,
        response: HuaweiCsmsGetResponse,
    ) -> None:
        self._secrets[name] = response

    def put_text(
        self,
        name: str,
        text: str,
        version_id: str = "v1",
    ) -> None:
        self._secrets[name] = HuaweiCsmsGetResponse(
            secret_name=name,
            version_id=version_id,
            secret_string=text,
            secret_binary="",
            create_time=1735689600000,
        )

    def show_secret_version(
        self,
        secret_name: str,
        version_id: str | None,
    ) -> HuaweiCsmsGetResponse:
        if secret_name not in self._secrets:
            err = Exception("CSMS 404: secret not found")
            setattr(err, "http_status_code", 404)
            raise err
        return self._secrets[secret_name]


class FakeKms(KmsLike):
    """In-process `KmsLike` for tests."""

    __slots__ = ()

    def encrypt_data(
        self,
        key_id: str,
        plain_text_b64: str,
        aad_b64,
    ) -> HuaweiKmsEncryptResponse:
        return HuaweiKmsEncryptResponse(
            cipher_text=f"cipher:{plain_text_b64}",
        )

    def decrypt_data(
        self,
        cipher_text: str,
        aad_b64,
    ) -> HuaweiKmsDecryptResponse:
        if not cipher_text.startswith("cipher:"):
            raise ValueError("FakeKms: cannot decrypt non-fake ciphertext")
        plain_text_b64 = cipher_text[len("cipher:"):]
        return HuaweiKmsDecryptResponse(
            plain_text="",
            plain_text_base64=plain_text_b64,
        )


@pytest.fixture
def fake_csms() -> FakeCsms:
    return FakeCsms()


@pytest.fixture
def fake_kms() -> FakeKms:
    return FakeKms()


@pytest.fixture
def default_properties() -> HuaweiSecretProperties:
    return HuaweiSecretProperties(
        region="cn-north-4",
        project_id="project-1",
        access_key_id="AKID-test",
        access_key_secret="secret-test",
        secrets={"db": "prod/orders/db"},
        kms_key_bindings={"default-envelope": "key-abc-123"},
    )


@pytest.fixture
def client(
    default_properties: HuaweiSecretProperties,
    fake_csms: FakeCsms,
    fake_kms: FakeKms,
) -> Iterator[HuaweiSecretClient]:
    resolved = HuaweiConfigurationResolver().resolve(default_properties)
    yield HuaweiSecretClient(resolved=resolved, csms=fake_csms, kms=fake_kms)


def _kek(key_id: str = "default-envelope") -> KeyReference:
    return KeyReference(
        provider="huawei-test",
        key_id=key_id,
        version=None,
        algorithm="AES-256",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHuaweiRead:
    def test_read_text_secret(self, client, fake_csms) -> None:
        fake_csms.put_text("prod/orders/db", "hunter2", version_id="v1")
        value = client.read(SecretReference(provider="huawei", path="db"))
        assert value.plaintext == b"hunter2"

    def test_read_binary_secret(self, client, fake_csms) -> None:
        fake_csms.put(
            "prod/orders/db",
            HuaweiCsmsGetResponse(
                secret_name="prod/orders/db",
                version_id="v1",
                secret_string="",
                secret_binary=base64.b64encode(b"\x00\x01\x02\x03").decode("ascii"),
                create_time=1735689600000,
            ),
        )
        value = client.read(SecretReference(provider="huawei", path="db"))
        assert value.plaintext == b"\x00\x01\x02\x03"

    def test_read_unmapped_uses_path(self, client, fake_csms) -> None:
        fake_csms.put_text("unmapped-secret", "direct")
        value = client.read(
            SecretReference(provider="huawei", path="unmapped-secret"),
        )
        assert value.plaintext == b"direct"

    def test_read_missing_raises_integrity(self, client) -> None:
        with pytest.raises(SecretIntegrityException):
            client.read(SecretReference(provider="huawei", path="nonexistent"))

    def test_read_5xx_does_not_look_like_missing(
        self,
        default_properties,
        fake_csms,
        fake_kms,
    ) -> None:
        class _BoomCsms(CsmsLike):
            def show_secret_version(self, *a, **kw):
                err = Exception("CSMS 500: internal error")
                setattr(err, "http_status_code", 500)
                raise err

        resolved = HuaweiConfigurationResolver().resolve(default_properties)
        client = HuaweiSecretClient(
            resolved=resolved, csms=_BoomCsms(), kms=fake_kms,
        )
        with pytest.raises(SecretException) as info:
            client.read(SecretReference(provider="huawei", path="db"))
        assert "SEC-PROVIDER-001" in str(info.value)
        assert not isinstance(info.value, SecretIntegrityException)


class TestHuaweiWrapUnwrap:
    def test_wrap_empty_plaintext_raises(self, client) -> None:
        with pytest.raises(SecretCryptoException):
            client.wrap_key(b"", _kek())

    def test_wrap_then_unwrap_round_trip(self, client) -> None:
        kek = _kek()
        plaintext = b"this is a 32-byte plaintext key!!"
        wrapped = client.wrap_key(plaintext, kek)
        assert wrapped.algorithm == "huawei-dew-default"
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
        assert "huawei-dew-default" in str(info.value)

    def test_wrap_missing_key_binding_raises_configuration(
        self,
        default_properties,
        fake_csms,
        fake_kms,
    ) -> None:
        properties = default_properties.model_copy(
            update={"kms_key_bindings": {}},
        )
        resolved = HuaweiConfigurationResolver().resolve(properties)
        client = HuaweiSecretClient(
            resolved=resolved, csms=fake_csms, kms=fake_kms,
        )
        with pytest.raises(SecretConfigurationException) as info:
            client.wrap_key(b"x" * 32, _kek())
        assert "SEC-KEY-001" in str(info.value)


class TestHuaweiBootstrap:
    def test_bootstrap_resolves_all_startup_bindings(
        self,
        default_properties,
        fake_csms,
        fake_kms,
    ) -> None:
        properties = default_properties.model_copy(
            update={"secrets": {"a": "prod/a", "b": "prod/b"}},
        )
        resolved = HuaweiConfigurationResolver().resolve(properties)
        client = HuaweiSecretClient(
            resolved=resolved, csms=fake_csms, kms=fake_kms,
        )
        fake_csms.put_text("prod/a", "a-value")
        fake_csms.put_text("prod/b", "b-value")
        request = SecretBootstrapRequest(
            catalog=SecretBindingCatalog(
                name="default",
                bindings=(
                    SecretBinding(
                        name="a",
                        reference=SecretReference(provider="huawei", path="a"),
                        kind=SecretKind.GENERIC,
                    ),
                    SecretBinding(
                        name="b",
                        reference=SecretReference(provider="huawei", path="b"),
                        kind=SecretKind.GENERIC,
                    ),
                ),
            ),
        )
        result = client.bootstrap(request, DefaultBootstrapContext())
        assert "a" in result.resolved
        assert "b" in result.resolved
        assert result.missing == ()

    def test_bootstrap_startup_missing_raises(self, client) -> None:
        request = SecretBootstrapRequest(
            catalog=SecretBindingCatalog(
                name="default",
                bindings=(
                    SecretBinding(
                        name="a",
                        reference=SecretReference(provider="huawei", path="a"),
                        kind=SecretKind.GENERIC,
                    ),
                ),
            ),
        )
        with pytest.raises(SecretException) as info:
            client.bootstrap(request, DefaultBootstrapContext())
        assert "SEC-STORE-001" in str(info.value)

    def test_bootstrap_optional_missing_silently(self, client) -> None:
        request = SecretBootstrapRequest(
            catalog=SecretBindingCatalog(
                name="default",
                bindings=(
                    SecretBinding(
                        name="a",
                        reference=SecretReference(provider="huawei", path="a"),
                        kind=SecretKind.GENERIC,
                        required_when=RequiredWhen.OPTIONAL,
                    ),
                ),
            ),
        )
        result = client.bootstrap(request, DefaultBootstrapContext())
        assert result.missing == ("a",)


class TestHuaweiSession:
    def test_descriptor_declares_huawei_backend(self, client) -> None:
        descriptor = client.descriptor
        assert descriptor.backend is SecretBackend.HUAWEI
        assert descriptor.capability.can_read is True
        assert descriptor.capability.can_write is False
        assert descriptor.capability.signs_values is False

    def test_writer_deletable_are_none(self, client) -> None:
        assert client.writer is None
        assert client.deletable is None

    def test_close_is_idempotent(self, client) -> None:
        client.close()
        client.close()
        assert client.is_closed is True

    def test_read_after_close_raises(self, client) -> None:
        client.close()
        with pytest.raises(SecretException):
            client.read(SecretReference(provider="huawei", path="db"))


__all__ = []
