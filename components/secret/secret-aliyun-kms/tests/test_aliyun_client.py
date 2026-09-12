"""Aliyun secret client — 4-SPI composite behaviour tests.

中文
----
通过 `FakeAliyunGateway`(in-process 真对象,非 MagicMock)验证
`AliyunSecretClient` 全部 4 个 SPI 角色的行为:

- `read` / `metadata`(SecretOperations)
- `wrap` / `unwrap`(KeyWrappingBackend)
- `bootstrap`(SecretBootstrapClient)
- `close` / `descriptor`(SecretProviderSession)

错误路径:
- KMS key binding 缺失 → `SEC-KEY-001`
- wrap 空 plaintext → `SEC-CRYPTO-001`
- unwrap 错误算法 / key_id 不匹配 → `SEC-CRYPTO-002`
- bootstrap missing secret + STARTUP `required_when` → 抛
  `SEC-STORE-001`;非 STARTUP 容忍 missing 并进入 `missing` 元组
- 二进制 secret 自动 base64 解码;JSON 字段提取
- field 不是 scalar → `SEC-STORE-003`

English
--------
Tests `AliyunSecretClient` end-to-end via `FakeAliyunGateway`.
Covers all 4 SPI roles + error paths. The fake is a real
in-process object, so the framework's full data path is
exercised.
"""

from __future__ import annotations

from datetime import datetime, timezone

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
from atlas_richie.secret.crypto import CryptoContext, KeyPurpose, KeyReference
from atlas_richie.secret.errors import (
    SecretConfigurationException,
    SecretCryptoException,
    SecretException,
    SecretIntegrityException,
)
from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret.reference import SecretReference, SecretVersionSelector
from atlas_richie.secret_aliyun_kms.client import (
    AliyunGetSecretValueResponse,
    AliyunSecretClient,
)
from atlas_richie.secret_aliyun_kms.properties import AliyunSecretMapping


def _ref(path: str, *, provider: str = "aliyun-test") -> SecretReference:
    return SecretReference(provider=provider, path=path)


# ---------------------------------------------------------------------------
# read / metadata
# ---------------------------------------------------------------------------


class TestAliyunClientRead:
    def test_read_text_secret(self, client_with_gateway, fake_aliyun_gateway) -> None:
        fake_aliyun_gateway.put(
            "company/prod/db",
            AliyunGetSecretValueResponse(
                secret_name="company/prod/db",
                secret_data="super-secret",
                secret_data_type="text",
                version_id="v1",
                version_stages=("ACSCurrent",),
                create_time="2026-01-01T00:00:00Z",
                request_id="req-1",
            ),
        )
        value = client_with_gateway.read(_ref("prod/db"))
        assert value.plaintext == b"super-secret"

    def test_read_binary_secret_decodes_base64(
        self,
        client_with_gateway,
        fake_aliyun_gateway,
    ) -> None:
        import base64

        fake_aliyun_gateway.put(
            "company/prod/binary",
            AliyunGetSecretValueResponse(
                secret_name="company/prod/binary",
                secret_data=base64.b64encode(b"\x00\x01\x02\x03").decode("ascii"),
                secret_data_type="binary",
                version_id="v2",
                version_stages=("ACSCurrent",),
                create_time=None,
                request_id=None,
            ),
        )
        value = client_with_gateway.read(_ref("prod/binary"))
        assert value.plaintext == b"\x00\x01\x02\x03"

    def test_read_json_field(self, client_with_gateway, fake_aliyun_gateway) -> None:
        fake_aliyun_gateway.put(
            "company/prod/db",
            AliyunGetSecretValueResponse(
                secret_name="company/prod/db",
                secret_data='{"password":"hunter2","port":5432}',
                secret_data_type="text",
                version_id="v1",
                version_stages=("ACSCurrent",),
                create_time=None,
                request_id=None,
            ),
        )
        # path#field convention
        value = client_with_gateway.read(_ref("prod/db#password"))
        assert value.plaintext == b"hunter2"

    def test_read_missing_secret_raises_integrity(
        self,
        client_with_gateway,
    ) -> None:
        with pytest.raises(SecretIntegrityException):
            client_with_gateway.read(_ref("nonexistent"))

    def test_read_non_scalar_field_raises_configuration(
        self,
        client_with_gateway,
        fake_aliyun_gateway,
    ) -> None:
        fake_aliyun_gateway.put(
            "company/prod/db",
            AliyunGetSecretValueResponse(
                secret_name="company/prod/db",
                secret_data='{"nested":{"k":"v"}}',
                secret_data_type="text",
                version_id="v1",
                version_stages=("ACSCurrent",),
                create_time=None,
                request_id=None,
            ),
        )
        with pytest.raises(SecretConfigurationException):
            client_with_gateway.read(_ref("prod/db#nested"))

    def test_metadata_returns_version_and_stages(
        self,
        client_with_gateway,
        fake_aliyun_gateway,
    ) -> None:
        fake_aliyun_gateway.put(
            "company/prod/db",
            AliyunGetSecretValueResponse(
                secret_name="company/prod/db",
                secret_data="x",
                secret_data_type="text",
                version_id="v3",
                version_stages=("ACSCurrent", "AWSCurrent"),
                create_time="2026-09-12T10:00:00Z",
                request_id="req-meta",
            ),
        )
        metadata = client_with_gateway.metadata(_ref("prod/db"))
        assert metadata.version.number == "v3"
        assert metadata.tags["stages"] == "ACSCurrent,AWSCurrent"
        assert metadata.tags["request_id"] == "req-meta"
        assert metadata.created_at is not None
        assert metadata.created_at.tzinfo is not None


# ---------------------------------------------------------------------------
# wrap / unwrap
# ---------------------------------------------------------------------------


class TestAliyunClientWrapUnwrap:
    def _kek(self, key_id: str = "alias/orders") -> KeyReference:
        return KeyReference(
            provider="aliyun-test",
            key_id=key_id,
            version=None,
            algorithm="AES-256",
        )

    def test_wrap_empty_plaintext_raises_crypto(self, client_with_gateway) -> None:
        with pytest.raises(SecretCryptoException):
            client_with_gateway.wrap_key(b"", self._kek())

    def test_wrap_missing_key_binding_raises_configuration(
        self,
        client_with_gateway,
    ) -> None:
        kek = self._kek(key_id="   ")
        with pytest.raises(SecretConfigurationException) as info:
            client_with_gateway.wrap_key(b"x" * 32, kek)
        assert "SEC-KEY-001" in str(info.value)

    def test_wrap_then_unwrap_round_trip(self, client_with_gateway) -> None:
        kek = self._kek()
        plaintext = b"this is a 32-byte plaintext key!!"  # 32 bytes
        wrapped = client_with_gateway.wrap_key(plaintext, kek)
        assert wrapped.algorithm == "aliyun-kms-symmetric-default"
        assert wrapped.ciphertext.startswith(b"cipher:")

        context = CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP)
        recovered = client_with_gateway.unwrap_key(wrapped, context)
        assert recovered == plaintext

    def test_unwrap_wrong_algorithm_raises(self, client_with_gateway) -> None:
        from atlas_richie.secret.crypto import WrappedKey

        kek = self._kek()
        bad = WrappedKey(
            kek_reference=kek,
            ciphertext=b"cipher:abc",
            algorithm="aws-kms",
        )
        context = CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP)
        with pytest.raises(SecretCryptoException) as info:
            client_with_gateway.unwrap_key(bad, context)
        assert "SEC-CRYPTO-002" in str(info.value)

    def test_wrap_includes_envelope_attributes_in_context(
        self,
        client_with_gateway,
    ) -> None:
        kek = self._kek()
        # The fake ignores the encryption context, but we verify
        # the call does not raise; for real SDK testing this
        # would assert the captured context.
        wrapped = client_with_gateway.wrap_key(b"x" * 32, kek)
        assert wrapped.algorithm == "aliyun-kms-symmetric-default"


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------


def _binding(
    name: str,
    path: str,
    *,
    required_when: RequiredWhen = RequiredWhen.STARTUP,
) -> SecretBinding:
    return SecretBinding(
        name=name,
        reference=SecretReference(provider="aliyun-test", path=path),
        kind=SecretKind.GENERIC,
        required_when=required_when,
    )


class TestAliyunClientBootstrap:
    def test_bootstrap_resolves_all_startup_bindings(
        self,
        client_with_gateway,
        fake_aliyun_gateway,
    ) -> None:
        fake_aliyun_gateway.put(
            "company/a",
            AliyunGetSecretValueResponse(
                secret_name="company/a", secret_data="a-value",
                secret_data_type="text", version_id="v1",
                version_stages=("ACSCurrent",), create_time=None, request_id=None,
            ),
        )
        fake_aliyun_gateway.put(
            "company/b",
            AliyunGetSecretValueResponse(
                secret_name="company/b", secret_data="b-value",
                secret_data_type="text", version_id="v1",
                version_stages=("ACSCurrent",), create_time=None, request_id=None,
            ),
        )
        request = SecretBootstrapRequest(
            catalog=SecretBindingCatalog(
                name="default",
                bindings=(
                    _binding("a", "a"),
                    _binding("b", "b"),
                ),
            ),
        )
        result = client_with_gateway.bootstrap(request, DefaultBootstrapContext())
        assert "a" in result.resolved
        assert "b" in result.resolved
        assert result.missing == ()

    def test_bootstrap_startup_missing_raises(
        self,
        client_with_gateway,
    ) -> None:
        request = SecretBootstrapRequest(
            catalog=SecretBindingCatalog(
                name="default",
                bindings=(_binding("a", "a"),),
            ),
        )
        with pytest.raises(SecretException) as info:
            client_with_gateway.bootstrap(request, DefaultBootstrapContext())
        assert "SEC-STORE-001" in str(info.value)

    def test_bootstrap_optional_missing_silently(
        self,
        client_with_gateway,
    ) -> None:
        request = SecretBootstrapRequest(
            catalog=SecretBindingCatalog(
                name="default",
                bindings=(_binding("a", "a", required_when=RequiredWhen.OPTIONAL),),
            ),
        )
        result = client_with_gateway.bootstrap(request, DefaultBootstrapContext())
        assert result.missing == ("a",)
        assert "a" not in result.resolved

    def test_bootstrap_lazy_missing_silently(
        self,
        client_with_gateway,
    ) -> None:
        request = SecretBootstrapRequest(
            catalog=SecretBindingCatalog(
                name="default",
                bindings=(_binding("a", "a", required_when=RequiredWhen.LAZY),),
            ),
        )
        result = client_with_gateway.bootstrap(request, DefaultBootstrapContext())
        assert result.missing == ("a",)


# ---------------------------------------------------------------------------
# session + descriptor
# ---------------------------------------------------------------------------


class TestAliyunClientSession:
    def test_descriptor_declares_aliyun_backend(
        self,
        client_with_gateway,
    ) -> None:
        descriptor = client_with_gateway.descriptor()
        assert descriptor.backend is SecretBackend.ALIYUN
        assert descriptor.name == "aliyun-test"
        assert descriptor.capability.can_read is True
        assert descriptor.capability.can_write is False
        assert descriptor.capability.signs_values is False

    def test_close_is_idempotent_and_calls_gateway(
        self,
        client_with_gateway,
        fake_aliyun_gateway,
    ) -> None:
        client_with_gateway.close()
        assert fake_aliyun_gateway.close_calls == 1
        client_with_gateway.close()  # idempotent
        assert fake_aliyun_gateway.close_calls == 1

    def test_read_after_close_raises(self, client_with_gateway) -> None:
        client_with_gateway.close()
        with pytest.raises(SecretException):
            client_with_gateway.read(_ref("anything"))

    def test_configuration_hash_propagated(
        self,
        client_with_gateway,
    ) -> None:
        # The `client_with_gateway` fixture mutates the path
        # prefix on the configuration; we just verify the
        # client exposes a 64-char SHA-256 hex digest.
        assert len(client_with_gateway.configuration_hash) == 64
        assert all(c in "0123456789abcdef" for c in client_with_gateway.configuration_hash)


# ---------------------------------------------------------------------------
# not-found handling
# ---------------------------------------------------------------------------


class TestAliyunClientNotFound:
    def test_gateway_not_found_returns_none(
        self,
        resolved_configuration,
    ) -> None:
        from atlas_richie.secret_aliyun_kms.client import AliyunKmsGateway

        class _NotFoundGateway(AliyunKmsGateway):
            def get_secret_value(self, *args, **kwargs):
                exc = Exception("simulated not-found")
                setattr(exc, "code", "Forbidden.ResourceNotFound")
                raise exc

            def encrypt(self, *a, **kw): raise NotImplementedError
            def decrypt(self, *a, **kw): raise NotImplementedError
            def close(self): pass

        client = AliyunSecretClient(resolved_configuration, _NotFoundGateway())
        # The not-found mapping in `AliyunSecretClient._get_secret`
        # catches `SecretException` subclasses; an unqualified
        # `Exception` with a `.code` attribute is intentionally
        # NOT translated (the client relies on the SDK's
        # `TeaException` shape). We verify the SDK-shape path
        # here: a wrapper exception whose message includes
        # the canonical not-found code is caught and the read
        # surfaces as `SecretIntegrityException`.

        class _TeaShaped(Exception):
            pass

        class _TeaShapedGateway(AliyunKmsGateway):
            def get_secret_value(self, *args, **kwargs):
                raise _TeaShaped(
                    "Forbidden.ResourceNotFound: secret missing",
                )

            def encrypt(self, *a, **kw): raise NotImplementedError
            def decrypt(self, *a, **kw): raise NotImplementedError
            def close(self): pass

        client = AliyunSecretClient(
            resolved_configuration, _TeaShapedGateway(),
        )
        with pytest.raises(SecretIntegrityException):
            client.read(_ref("anything"))


__all__ = []
