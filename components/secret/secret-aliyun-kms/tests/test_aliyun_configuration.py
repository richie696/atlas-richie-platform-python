"""Aliyun configuration resolver tests.

中文
----
验证 `AliyunConfigurationResolver._validate` 的全部校验规则:
- region 必填(由 pydantic 强制)
- endpoint 非空时必须是 https(或 loopback http)
- dedicated KMS endpoint (`.cryptoservice.kms.aliyuncs.com`) 必须配 ca_file
- path prefix 不允许 `..` / `://` / 开头结尾 `/`
- key bindings 的 logical / physical 非空且 logical 合法
- secret mappings 的 secret_name 非空
- configuration_hash 是 64 字符 hex

English
--------
Tests for `AliyunConfigurationResolver`. Validates region /
endpoint / ca_file / path prefix / key bindings / secret
mappings / configuration_hash. 1:1 with Java
`AliyunSecretConfigurationResolver.validate`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret_aliyun_kms.configuration import (
    AliyunConfigurationResolver,
    ResolvedAliyunConfiguration,
)
from atlas_richie.secret_aliyun_kms.properties import (
    AliyunSecretMapping,
    AliyunSecretProperties,
)


def _expect_rejection(value: object) -> None:
    """Pydantic-level validators raise `ValidationError`;
    resolver-level checks raise `SecretConfigurationException`.
    Both are valid "configuration rejected" signals for the
    tests below.
    """
    with pytest.raises((SecretConfigurationException, ValidationError)):
        raise value  # type: ignore[misc]


class TestAliyunEndpoint:
    def test_missing_endpoint_ok(self) -> None:
        properties = AliyunSecretProperties(region="cn-hangzhou")
        resolved = AliyunConfigurationResolver().resolve(properties)
        assert isinstance(resolved, ResolvedAliyunConfiguration)

    def test_https_endpoint_ok(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            endpoint="https://kms.cn-hangzhou.aliyuncs.com",
        )
        AliyunConfigurationResolver().resolve(properties)  # does not raise

    def test_http_loopback_ok(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            endpoint="http://127.0.0.1:8080",
        )
        AliyunConfigurationResolver().resolve(properties)

    def test_http_non_loopback_rejected(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            endpoint="http://kms.aliyuncs.com",
        )
        with pytest.raises(SecretConfigurationException) as info:
            AliyunConfigurationResolver().resolve(properties)
        assert "https" in str(info.value).lower()

    def test_endpoint_with_query_rejected(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            endpoint="https://kms.aliyuncs.com?foo=bar",
        )
        with pytest.raises(SecretConfigurationException):
            AliyunConfigurationResolver().resolve(properties)

    def test_endpoint_with_userinfo_rejected(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            endpoint="https://user:pass@kms.aliyuncs.com",
        )
        with pytest.raises(SecretConfigurationException):
            AliyunConfigurationResolver().resolve(properties)


class TestAliyunCryptoserviceEndpoint:
    def test_dedicated_endpoint_requires_ca_file(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            endpoint="https://mykey.cryptoservice.kms.aliyuncs.com",
        )
        with pytest.raises(SecretConfigurationException) as info:
            AliyunConfigurationResolver().resolve(properties)
        assert "ca_file" in str(info.value)

    def test_dedicated_endpoint_with_ca_file_ok(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            endpoint="https://mykey.cryptoservice.kms.aliyuncs.com",
            ca_file="/etc/ssl/certs/aliyun-kms.pem",
        )
        AliyunConfigurationResolver().resolve(properties)  # does not raise


class TestAliyunPathPrefix:
    def test_path_prefix_double_dot_rejected(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            secrets_manager_path_prefix="../etc",
        )
        with pytest.raises(SecretConfigurationException):
            AliyunConfigurationResolver().resolve(properties)

    def test_path_prefix_with_scheme_rejected(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            secrets_manager_path_prefix="https://example",
        )
        with pytest.raises(SecretConfigurationException):
            AliyunConfigurationResolver().resolve(properties)

    def test_path_prefix_leading_slash_rejected(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            secrets_manager_path_prefix="/etc",
        )
        with pytest.raises(SecretConfigurationException):
            AliyunConfigurationResolver().resolve(properties)

    def test_path_prefix_trailing_slash_rejected(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            secrets_manager_path_prefix="company/",
        )
        with pytest.raises(SecretConfigurationException):
            AliyunConfigurationResolver().resolve(properties)

    def test_empty_path_prefix_ok(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            secrets_manager_path_prefix="",
        )
        AliyunConfigurationResolver().resolve(properties)


class TestAliyunKeyBindings:
    def test_blank_logical_rejected(self) -> None:
        # Pydantic catches the blank key first (its validator
        # fires before the resolver). Both signals are
        # semantically equivalent "configuration rejected".
        with pytest.raises((SecretConfigurationException, ValidationError)):
            AliyunSecretProperties(
                region="cn-hangzhou",
                kms_key_bindings={"": "alias/orders"},
            )

    def test_invalid_logical_with_double_dot_rejected(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            kms_key_bindings={"db..orders": "alias/orders"},
        )
        with pytest.raises(SecretConfigurationException):
            AliyunConfigurationResolver().resolve(properties)

    def test_blank_physical_rejected(self) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            AliyunSecretProperties(
                region="cn-hangzhou",
                kms_key_bindings={"db-orders": "  "},
            )


class TestAliyunSecretMappings:
    def test_blank_secret_name_rejected(self) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            AliyunSecretProperties(
                region="cn-hangzhou",
                secrets={"db": AliyunSecretMapping(secret_name="")},
            )

    def test_invalid_field_rejected(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            secrets={"db": AliyunSecretMapping(secret_name="prod/db", field="../foo")},
        )
        with pytest.raises(SecretConfigurationException):
            AliyunConfigurationResolver().resolve(properties)

    def test_valid_mapping_ok(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            secrets={"db": AliyunSecretMapping(secret_name="prod/db", field="password")},
        )
        resolved = AliyunConfigurationResolver().resolve(properties)
        assert resolved.properties.secrets["db"].field == "password"


class TestAliyunConfigurationHash:
    def test_hash_is_64_hex_chars(self) -> None:
        properties = AliyunSecretProperties(region="cn-hangzhou")
        resolved = AliyunConfigurationResolver().resolve(properties)
        assert len(resolved.configuration_hash) == 64
        assert all(c in "0123456789abcdef" for c in resolved.configuration_hash)

    def test_hash_changes_with_region(self) -> None:
        a = AliyunConfigurationResolver().resolve(
            AliyunSecretProperties(region="cn-hangzhou"),
        )
        b = AliyunConfigurationResolver().resolve(
            AliyunSecretProperties(region="us-west-1"),
        )
        assert a.configuration_hash != b.configuration_hash

    def test_hash_changes_with_provider_id(self) -> None:
        properties = AliyunSecretProperties(region="cn-hangzhou")
        a = AliyunConfigurationResolver().resolve(properties, provider_id="aliyun-a")
        b = AliyunConfigurationResolver().resolve(properties, provider_id="aliyun-b")
        assert a.configuration_hash != b.configuration_hash

    def test_hash_stable_for_identical_config(self) -> None:
        properties = AliyunSecretProperties(region="cn-hangzhou")
        a = AliyunConfigurationResolver().resolve(properties)
        b = AliyunConfigurationResolver().resolve(properties)
        assert a.configuration_hash == b.configuration_hash


class TestAliyunCapability:
    def test_capability_matches_java(self) -> None:
        properties = AliyunSecretProperties(region="cn-hangzhou")
        resolved = AliyunConfigurationResolver().resolve(properties)
        cap = resolved.capability
        assert cap.can_read is True
        assert cap.can_write is False
        assert cap.can_rotate is True
        assert cap.can_list is False
        assert cap.encrypts_at_rest is True
        assert cap.signs_values is False
        assert cap.cacheable is True


__all__ = []
