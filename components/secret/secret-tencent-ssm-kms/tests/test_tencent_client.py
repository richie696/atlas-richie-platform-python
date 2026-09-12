"""Tencent secret client — 3-SPI composite tests via fake Ssm / Kms.

中文
----
通过 `FakeSsm` / `FakeKms`(in-process 真对象,非 MagicMock)验证
`TencentSecretClient` 全部 3 个 SPI 角色 + 错误路径:
- `read` / `metadata`(SecretOperations via SSM)
- `wrap_key` / `unwrap_key`(KeyWrappingBackend via KMS)
- `bootstrap`(SecretBootstrapClient)
- `close` / `descriptor`(SecretProviderSession)
- `SEC-CAP-001` AAD gate on `unwrap_key`
- `SEC-PROVIDER-001` non-NotFound SSM errors 不伪装成 missing

English
--------
Tests `TencentSecretClient` end-to-end via in-process
`FakeSsm` / `FakeKms` (real objects, not MagicMock).
Covers all 3 SPI roles + capability gate + NotFound
boundary.
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
    SecretCapabilityException,
    SecretConfigurationException,
    SecretCryptoException,
    SecretException,
    SecretIntegrityException,
)
from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret.reference import SecretReference
from atlas_richie.secret_tencent_ssm_kms.client import (
    KmsLike,
    SsmLike,
    TencentKmsDecryptResponse,
    TencentKmsEncryptResponse,
    TencentSecretClient,
    TencentSsmGetResponse,
)
from atlas_richie.secret_tencent_ssm_kms.configuration import (
    TencentConfigurationResolver,
)
from atlas_richie.secret_tencent_ssm_kms.properties import (
    AuthType,
    TencentSecretProperties,
)


# ---------------------------------------------------------------------------
# Fake SDK clients
# ---------------------------------------------------------------------------


class FakeSsm(SsmLike):
    """In-process `SsmLike` for tests.

    Stores secret values in an internal dict. By default
    `ResourceNotFound` is raised on missing entries;
    callers can put canned `TencentSsmGetResponse` values
    via `.put(name, response)` or `.put_text(name, text)`
    / `.put_binary(name, b64_text)`.
    """

    __slots__ = ("_secrets",)

    def __init__(self) -> None:
        self._secrets: dict[str, TencentSsmGetResponse] = {}

    def put(
        self,
        name: str,
        response: TencentSsmGetResponse,
    ) -> None:
        self._secrets[name] = response

    def put_text(self, name: str, text: str, version_id: str = "v1") -> None:
        self._secrets[name] = TencentSsmGetResponse(
            secret_name=name,
            version_id=version_id,
            secret_string=text,
            secret_binary="",
            request_id=f"req-{name}",
        )

    def put_binary(
        self,
        name: str,
        binary: bytes,
        version_id: str = "v1",
    ) -> None:
        self._secrets[name] = TencentSsmGetResponse(
            secret_name=name,
            version_id=version_id,
            secret_string="",
            secret_binary=base64.b64encode(binary).decode("ascii"),
            request_id=f"req-{name}",
        )

    def get_secret_value(
        self,
        secret_name: str,
        version_id: str | None,
    ) -> TencentSsmGetResponse:
        if secret_name not in self._secrets:
            err = Exception("ResourceNotFound: secret missing")
            setattr(err, "code", "ResourceNotFound")
            raise err
        response = self._secrets[secret_name]
        if version_id is not None and response.version_id != version_id:
            err = Exception("ResourceNotFound: version missing")
            setattr(err, "code", "ResourceNotFound")
            raise err
        return response


class FakeKms(KmsLike):
    """In-process `KmsLike` for tests. Round-trip via base64 inversion."""

    __slots__ = ()

    def encrypt(
        self,
        key_id: str,
        plaintext_b64: str,
        encryption_context,
    ) -> TencentKmsEncryptResponse:
        return TencentKmsEncryptResponse(
            ciphertext_blob=f"cipher:{plaintext_b64}",
            request_id="fake-encrypt",
        )

    def decrypt(
        self,
        ciphertext_blob: str,
        encryption_context,
    ) -> TencentKmsDecryptResponse:
        if not ciphertext_blob.startswith("cipher:"):
            raise ValueError("FakeKms: cannot decrypt non-fake ciphertext")
        plaintext_b64 = ciphertext_blob[len("cipher:"):]
        return TencentKmsDecryptResponse(
            plaintext=plaintext_b64,
            request_id="fake-decrypt",
        )


@pytest.fixture
def fake_ssm() -> FakeSsm:
    return FakeSsm()


@pytest.fixture
def fake_kms() -> FakeKms:
    return FakeKms()


@pytest.fixture
def default_properties() -> TencentSecretProperties:
    return TencentSecretProperties(
        region="ap-guangzhou",
        access_key_id="AKID-test",
        access_key_secret="secret-test",
        secrets={"db": "prod/orders/db"},
        kms_key_bindings={"default-envelope": "alias/orders"},
    )


@pytest.fixture
def client(
    default_properties: TencentSecretProperties,
    fake_ssm: FakeSsm,
    fake_kms: FakeKms,
) -> Iterator[TencentSecretClient]:
    resolved = TencentConfigurationResolver().resolve(default_properties)
    yield TencentSecretClient(resolved=resolved, ssm=fake_ssm, kms=fake_kms)


def _kek(key_id: str = "default-envelope") -> KeyReference:
    return KeyReference(
        provider="tencent-test",
        key_id=key_id,
        version=None,
        algorithm="AES-256",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTencentRead:
    def test_read_text_secret(self, client, fake_ssm) -> None:
        fake_ssm.put_text("prod/orders/db", "hunter2", version_id="v1")
        value = client.read(SecretReference(provider="tencent", path="db"))
        assert value.plaintext == b"hunter2"
        assert value.metadata.tags["request_id"] == "req-prod/orders/db"

    def test_read_binary_secret(self, client, fake_ssm) -> None:
        fake_ssm.put_binary("prod/orders/db", b"\x00\x01\x02\x03", version_id="v1")
        value = client.read(SecretReference(provider="tencent", path="db"))
        assert value.plaintext == b"\x00\x01\x02\x03"

    def test_read_unmapped_uses_path_as_name(
        self,
        client,
        fake_ssm,
    ) -> None:
        fake_ssm.put_text("unmapped-secret", "direct")
        value = client.read(SecretReference(provider="tencent", path="unmapped-secret"))
        assert value.plaintext == b"direct"

    def test_read_missing_raises_integrity(self, client) -> None:
        with pytest.raises(SecretIntegrityException):
            client.read(SecretReference(provider="tencent", path="nonexistent"))

    def test_read_5xx_does_not_look_like_missing(
        self,
        default_properties,
        fake_ssm,
        fake_kms,
    ) -> None:
        class _BoomSsm(SsmLike):
            def get_secret_value(self, *a, **kw):
                raise Exception("InternalError: backend down")

        resolved = TencentConfigurationResolver().resolve(default_properties)
        client = TencentSecretClient(resolved=resolved, ssm=_BoomSsm(), kms=fake_kms)
        with pytest.raises(SecretException) as info:
            client.read(SecretReference(provider="tencent", path="db"))
        assert "SEC-PROVIDER-001" in str(info.value)
        # Crucially: NOT a SecretIntegrityException (would imply missing).
        assert not isinstance(info.value, SecretIntegrityException)


class TestTencentMetadata:
    def test_metadata_returns_version_and_request_id(
        self,
        client,
        fake_ssm,
    ) -> None:
        fake_ssm.put_text("prod/orders/db", "x", version_id="v5")
        metadata = client.metadata(SecretReference(provider="tencent", path="db"))
        assert metadata.version.number == "v5"
        assert metadata.tags["request_id"] == "req-prod/orders/db"


class TestTencentWrapUnwrap:
    def test_wrap_empty_plaintext_raises(self, client) -> None:
        with pytest.raises(SecretCryptoException):
            client.wrap_key(b"", _kek())

    def test_wrap_then_unwrap_round_trip(self, client) -> None:
        kek = _kek()
        plaintext = b"this is a 32-byte plaintext key!!"
        wrapped = client.wrap_key(plaintext, kek)
        assert wrapped.algorithm == "tencent-kms-default"
        assert wrapped.ciphertext.startswith(b"cipher:")

        context = CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP)
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
        assert "tencent-kms-default" in str(info.value)

    def test_wrap_missing_key_binding_raises_configuration(
        self,
        default_properties,
        fake_ssm,
        fake_kms,
    ) -> None:
        properties = default_properties.model_copy(
            update={"kms_key_bindings": {}},
        )
        resolved = TencentConfigurationResolver().resolve(properties)
        client = TencentSecretClient(resolved=resolved, ssm=fake_ssm, kms=fake_kms)
        with pytest.raises(SecretConfigurationException) as info:
            client.wrap_key(b"x" * 32, _kek())
        assert "SEC-KEY-001" in str(info.value)

    def test_unwrap_with_aad_ok(self, client) -> None:
        # Tencent KMS `EncryptionContext` accepts arbitrary
        # key/value attributes; the framework's AAD
        # `Mapping[str, str]` serializes directly into the
        # context. No `SEC-CAP-001` is raised.
        kek = _kek()
        plaintext = b"this is a 32-byte plaintext key!!"
        wrapped = client.wrap_key(plaintext, kek)
        context = CryptoContext(
            primary_key=kek,
            purpose=KeyPurpose.WRAP,
            aad={"path": "secret/orders", "env": "prod"},
        )
        recovered = client.unwrap_key(wrapped, context)
        assert recovered == plaintext

    def test_unwrap_with_empty_aad_ok(self, client) -> None:
        kek = _kek()
        plaintext = b"this is a 32-byte plaintext key!!"
        wrapped = client.wrap_key(plaintext, kek)
        context = CryptoContext(
            primary_key=kek,
            purpose=KeyPurpose.WRAP,
            aad={},
        )
        recovered = client.unwrap_key(wrapped, context)
        assert recovered == plaintext


class TestTencentBootstrap:
    def test_bootstrap_resolves_all_startup_bindings(
        self,
        default_properties,
        fake_ssm,
        fake_kms,
    ) -> None:
        # Override the secrets mapping so binding paths
        # directly resolve to fake_ssm entries.
        properties = default_properties.model_copy(
            update={
                "secrets": {
                    "a": "prod/a",
                    "b": "prod/b",
                },
            },
        )
        resolved = TencentConfigurationResolver().resolve(properties)
        client = TencentSecretClient(resolved=resolved, ssm=fake_ssm, kms=fake_kms)
        fake_ssm.put_text("prod/a", "a-value")
        fake_ssm.put_text("prod/b", "b-value")
        request = SecretBootstrapRequest(
            catalog=SecretBindingCatalog(
                name="default",
                bindings=(
                    SecretBinding(
                        name="a",
                        reference=SecretReference(provider="tencent", path="a"),
                        kind=SecretKind.GENERIC,
                    ),
                    SecretBinding(
                        name="b",
                        reference=SecretReference(provider="tencent", path="b"),
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
                        reference=SecretReference(provider="tencent", path="a"),
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
                        reference=SecretReference(provider="tencent", path="a"),
                        kind=SecretKind.GENERIC,
                        required_when=RequiredWhen.OPTIONAL,
                    ),
                ),
            ),
        )
        result = client.bootstrap(request, DefaultBootstrapContext())
        assert result.missing == ("a",)


class TestTencentSession:
    def test_descriptor_declares_tencent_backend(self, client) -> None:
        descriptor = client.descriptor
        assert descriptor.backend is SecretBackend.TENCENT
        assert descriptor.capability.can_read is True
        assert descriptor.capability.can_write is False
        assert descriptor.capability.can_list is False
        assert descriptor.capability.signs_values is False

    def test_writer_deletable_are_none(self, client) -> None:
        assert client.writer is None
        assert client.deletable is None

    def test_close_is_idempotent(self, client) -> None:
        client.close()
        client.close()  # idempotent
        assert client.is_closed is True

    def test_read_after_close_raises(self, client) -> None:
        client.close()
        with pytest.raises(SecretException):
            client.read(SecretReference(provider="tencent", path="db"))


__all__ = []
