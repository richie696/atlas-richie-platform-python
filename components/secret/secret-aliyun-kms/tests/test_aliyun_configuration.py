"""Unit tests for `AliyunConfigurationResolver`。

中文
----
覆盖 `AliyunConfigurationResolver._validate(...)` 全部失败路径 +
happy path。验证:

- 缺 region ⇒ `SEC-BOOT-003`
- endpoint 非 HTTPS(且非 loopback HTTP)⇒ `SEC-BOOT-003`
- endpoint 含 `.cryptoservice.kms.aliyuncs.com` 但无 `ca_file` ⇒
  `SEC-BOOT-003`
- `secrets_manager_path_prefix` 含 `..` / 头尾 `/` / `://` ⇒
  `SEC-BOOT-003`
- `kms_key_bindings` values 空白 ⇒ `SEC-BOOT-003`
- `secrets` mapping 空 / `secret_name` 空白 ⇒ `SEC-BOOT-003`
- 合法 config ⇒ `ResolvedAliyunConfiguration.configuration_hash` 是
  64-char hex
- 相同输入产生相同 hash(稳定性)
- 变更任一字段,hash 改变

English
--------
Validation and SHA-256 hash behavior. Each negative case asserts
the exact `SEC-BOOT-003` prefix; the positive case asserts hash
shape and stability.
"""

from __future__ import annotations

import re

import pytest

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret_aliyun_kms.configuration import (
    AliyunConfigurationResolver,
    ResolvedAliyunConfiguration,
)
from atlas_richie.secret_aliyun_kms.properties import (
    AliyunSecretMapping,
    AliyunSecretProperties,
)


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class TestValidationRegion:
    def test_blank_region_rejected(self) -> None:
        # Pydantic enforces min_length=1, so the resolver sees a
        # blank region only via direct construction. We bypass
        # pydantic by using a stub property.
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="",
        )
        with pytest.raises(SecretConfigurationException) as exc:
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test
        assert "SEC-BOOT-003" in str(exc.value)
        assert "region" in str(exc.value)

    def test_whitespace_region_rejected(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="   ",
        )
        with pytest.raises(SecretConfigurationException) as exc:
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test
        assert "SEC-BOOT-003" in str(exc.value)


class TestValidationEndpoint:
    def test_endpoint_must_be_https(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            endpoint="http://kms.cn-hangzhou.aliyuncs.com",
        )
        with pytest.raises(SecretConfigurationException) as exc:
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test
        assert "SEC-BOOT-003" in str(exc.value)
        assert "https" in str(exc.value).lower()

    def test_loopback_http_allowed(self) -> None:
        for loopback in (
            "http://localhost",
            "http://127.0.0.1",
            "http://[::1]",
        ):
            properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
                region="cn-hangzhou",
                endpoint=loopback,
            )
            # Should not raise.
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test

    def test_dedicated_kms_requires_ca_file(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            endpoint="https://my-pcpc-01.cryptoservice.kms.aliyuncs.com",
        )
        with pytest.raises(SecretConfigurationException) as exc:
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test
        assert "SEC-BOOT-003" in str(exc.value)
        assert "ca_file" in str(exc.value)

    def test_dedicated_kms_with_ca_file_ok(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            endpoint="https://my-pcpc-01.cryptoservice.kms.aliyuncs.com",
            ca_file="/etc/ssl/alibabacloud-dedicated.pem",
        )
        # Should not raise.
        AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test

    def test_invalid_url_rejected(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            endpoint="::::",
        )
        with pytest.raises(SecretConfigurationException) as exc:
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test
        assert "SEC-BOOT-003" in str(exc.value)


class TestValidationPathPrefix:
    def test_double_dot_rejected(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            secrets_manager_path_prefix="../escape",
        )
        with pytest.raises(SecretConfigurationException) as exc:
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test
        assert "SEC-BOOT-003" in str(exc.value)

    def test_leading_slash_rejected(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            secrets_manager_path_prefix="/leading",
        )
        with pytest.raises(SecretConfigurationException) as exc:
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test
        assert "SEC-BOOT-003" in str(exc.value)

    def test_trailing_slash_rejected(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            secrets_manager_path_prefix="trailing/",
        )
        with pytest.raises(SecretConfigurationException) as exc:
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test
        assert "SEC-BOOT-003" in str(exc.value)

    def test_scheme_marker_rejected(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            secrets_manager_path_prefix="evil://prefix",
        )
        with pytest.raises(SecretConfigurationException) as exc:
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test
        assert "SEC-BOOT-003" in str(exc.value)

    def test_none_prefix_ok(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            secrets_manager_path_prefix=None,
        )
        AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test

    def test_valid_prefix_ok(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            secrets_manager_path_prefix="my-team",
        )
        AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test


class TestValidationKeyBindings:
    def test_empty_physical_key_rejected(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            kms_key_bindings={"cmk-a": ""},
        )
        with pytest.raises(SecretConfigurationException) as exc:
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test
        assert "SEC-BOOT-003" in str(exc.value)

    def test_whitespace_physical_key_rejected(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            kms_key_bindings={"cmk-a": "   "},
        )
        with pytest.raises(SecretConfigurationException) as exc:
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test
        assert "SEC-BOOT-003" in str(exc.value)

    def test_unsafe_logical_key_rejected(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            kms_key_bindings={"cmk/with/slash": "id"},
        )
        with pytest.raises(SecretConfigurationException) as exc:
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test
        assert "SEC-BOOT-003" in str(exc.value)

    def test_valid_bindings_ok(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            kms_key_bindings={"cmk-a": "alias/my-team/cmk-a"},
        )
        AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test


class TestValidationSecretMappings:
    def test_empty_secret_name_rejected(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            secrets={"db.password": AliyunSecretMapping(secret_name="")},
        )
        with pytest.raises(SecretConfigurationException) as exc:
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test
        assert "SEC-BOOT-003" in str(exc.value)

    def test_unsafe_field_rejected(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            secrets={
                "db.password": AliyunSecretMapping(
                    secret_name="prod/db", field="with/slash"
                )
            },
        )
        with pytest.raises(SecretConfigurationException) as exc:
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test
        assert "SEC-BOOT-003" in str(exc.value)

    def test_unsafe_logical_secret_name_rejected(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            secrets={
                "db/with/slash": AliyunSecretMapping(secret_name="prod/db")
            },
        )
        with pytest.raises(SecretConfigurationException) as exc:
            AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test
        assert "SEC-BOOT-003" in str(exc.value)

    def test_valid_secret_mapping_ok(self) -> None:
        properties = AliyunSecretProperties.model_construct(  # type: ignore[call-arg]
            region="cn-hangzhou",
            secrets={
                "db.password": AliyunSecretMapping(
                    secret_name="prod/db", field="password"
                )
            },
        )
        AliyunConfigurationResolver._validate(properties)  # noqa: SLF001 - test


class TestResolveHappyPath:
    def test_valid_config_returns_resolved_with_hash(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            endpoint="https://kms.cn-hangzhou.aliyuncs.com",
            secrets_manager_path_prefix="my-team",
            kms_key_bindings={"cmk-a": "alias/my-team/cmk-a"},
            secrets={
                "db.password": AliyunSecretMapping(
                    secret_name="prod/db", field="password"
                )
            },
        )
        resolved = AliyunConfigurationResolver().resolve(
            properties, provider_id="aliyun-prod"
        )
        assert isinstance(resolved, ResolvedAliyunConfiguration)
        assert resolved.provider_id == "aliyun-prod"
        assert resolved.properties == properties
        assert _HEX64.fullmatch(resolved.configuration_hash)

    def test_hash_is_stable_for_same_input(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            kms_key_bindings={"a": "id-a", "b": "id-b"},
            secrets={"k": AliyunSecretMapping(secret_name="prod/k")},
        )
        resolver = AliyunConfigurationResolver()
        a = resolver.resolve(properties, provider_id="aliyun-x")
        b = resolver.resolve(properties, provider_id="aliyun-x")
        assert a.configuration_hash == b.configuration_hash

    def test_hash_changes_with_provider_id(self) -> None:
        properties = AliyunSecretProperties(region="cn-hangzhou")
        resolver = AliyunConfigurationResolver()
        a = resolver.resolve(properties, provider_id="aliyun-a")
        b = resolver.resolve(properties, provider_id="aliyun-b")
        assert a.configuration_hash != b.configuration_hash

    def test_hash_changes_with_region(self) -> None:
        properties_a = AliyunSecretProperties(region="cn-hangzhou")
        properties_b = AliyunSecretProperties(region="cn-beijing")
        resolver = AliyunConfigurationResolver()
        a = resolver.resolve(properties_a)
        b = resolver.resolve(properties_b)
        assert a.configuration_hash != b.configuration_hash

    def test_hash_changes_with_endpoint(self) -> None:
        a = AliyunSecretProperties(region="cn-hangzhou")
        b = AliyunSecretProperties(
            region="cn-hangzhou",
            endpoint="https://kms.cn-hangzhou.aliyuncs.com",
        )
        resolver = AliyunConfigurationResolver()
        ha = resolver.resolve(a).configuration_hash
        hb = resolver.resolve(b).configuration_hash
        assert ha != hb

    def test_hash_changes_with_bindings(self) -> None:
        a = AliyunSecretProperties(
            region="cn-hangzhou", kms_key_bindings={"k": "id-1"}
        )
        b = AliyunSecretProperties(
            region="cn-hangzhou", kms_key_bindings={"k": "id-2"}
        )
        resolver = AliyunConfigurationResolver()
        assert resolver.resolve(a).configuration_hash != resolver.resolve(b).configuration_hash

    def test_hash_changes_with_secret_mappings(self) -> None:
        a = AliyunSecretProperties(
            region="cn-hangzhou",
            secrets={"x": AliyunSecretMapping(secret_name="prod/x")},
        )
        b = AliyunSecretProperties(
            region="cn-hangzhou",
            secrets={"y": AliyunSecretMapping(secret_name="prod/y")},
        )
        resolver = AliyunConfigurationResolver()
        assert resolver.resolve(a).configuration_hash != resolver.resolve(b).configuration_hash

    def test_default_provider_id(self) -> None:
        properties = AliyunSecretProperties(region="cn-hangzhou")
        resolved = AliyunConfigurationResolver().resolve(properties)
        assert resolved.provider_id == "aliyun-default"

    def test_resolved_carries_static_capability(self) -> None:
        properties = AliyunSecretProperties(region="cn-hangzhou")
        resolved = AliyunConfigurationResolver().resolve(properties)
        assert resolved.capability.can_read is True
        assert resolved.capability.can_write is False
        assert resolved.capability.can_list is False
        assert resolved.capability.signs_values is False
        assert resolved.capability.encrypts_at_rest is True
