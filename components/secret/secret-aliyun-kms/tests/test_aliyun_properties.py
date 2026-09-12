"""Aliyun secret properties — pydantic-settings env injection tests.

中文
----
验证:
- 必填 `region` 校验
- 可选 `endpoint` / `ca_file` / `secrets_manager_path_prefix` / `kms_key_bindings`
  / `secrets` 字段注入
- `key_bindings` 的 logical / physical 非空校验
- `secrets` 映射的 `secret_name` 非空校验
- env_prefix 是 `ATLAS_RICHIE_SECRET_ALIYUN_`

English
--------
Tests for pydantic-settings env injection on
`AliyunSecretProperties`. Region is required; key bindings
+ secret mappings validate non-blank logical / physical
names. Env prefix is `ATLAS_RICHIE_SECRET_ALIYUN_`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret_aliyun_kms.properties import (
    AliyunSecretMapping,
    AliyunSecretProperties,
)


class TestAliyunSecretPropertiesRequired:
    def test_region_is_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", raising=False)
        with pytest.raises(ValidationError) as info:
            AliyunSecretProperties()
        assert "region" in str(info.value)

    def test_region_must_be_non_blank(self) -> None:
        with pytest.raises(ValidationError) as info:
            AliyunSecretProperties(region="   ")
        assert "region" in str(info.value)

    def test_region_default_optional_fields(self) -> None:
        properties = AliyunSecretProperties(region="cn-hangzhou")
        assert properties.region == "cn-hangzhou"
        assert properties.endpoint is None
        assert properties.ca_file is None
        assert properties.secrets_manager_path_prefix == ""
        assert properties.kms_key_bindings == {}
        assert properties.secrets == {}
        assert properties.connect_timeout_seconds == 10.0
        assert properties.read_timeout_seconds == 30.0
        assert properties.max_attempts == 3


class TestAliyunSecretPropertiesEnvPrefix:
    def test_env_prefix_uses_atlas_aliyun_namespace(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", "us-west-1")
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_ENDPOINT", "https://kms.us-west-1.aliyuncs.com")
        monkeypatch.setenv(
            "ATLAS_RICHIE_SECRET_ALIYUN_SECRETS_MANAGER_PATH_PREFIX", "company",
        )
        properties = AliyunSecretProperties()
        assert properties.region == "us-west-1"
        assert properties.endpoint == "https://kms.us-west-1.aliyuncs.com"
        assert properties.secrets_manager_path_prefix == "company"


class TestAliyunSecretPropertiesKeyBindings:
    def test_logical_key_must_be_non_blank(self) -> None:
        with pytest.raises(ValidationError) as info:
            AliyunSecretProperties(
                region="cn-hangzhou",
                kms_key_bindings={"": "alias/orders"},
            )
        assert "kms_key_bindings" in str(info.value)

    def test_physical_key_must_be_non_blank(self) -> None:
        with pytest.raises(ValidationError) as info:
            AliyunSecretProperties(
                region="cn-hangzhou",
                kms_key_bindings={"default-envelope": "  "},
            )
        assert "kms_key_bindings" in str(info.value)

    def test_key_bindings_strip_physical_whitespace(self) -> None:
        # Only the physical value is whitespace-stripped; the
        # logical key is preserved verbatim (Python dicts do
        # not allow mutating keys after validation).
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            kms_key_bindings={"default-envelope": "  alias/orders  "},
        )
        assert properties.kms_key_bindings == {
            "default-envelope": "alias/orders",
        }


class TestAliyunSecretPropertiesMappings:
    def test_mapping_secret_name_must_be_non_blank(self) -> None:
        with pytest.raises(ValidationError) as info:
            AliyunSecretProperties(
                region="cn-hangzhou",
                secrets={
                    "db-password": AliyunSecretMapping(secret_name="   "),
                },
            )
        assert "secrets" in str(info.value)

    def test_mapping_logical_name_must_be_non_blank(self) -> None:
        with pytest.raises(ValidationError) as info:
            AliyunSecretProperties(
                region="cn-hangzhou",
                secrets={
                    "  ": AliyunSecretMapping(secret_name="prod/db"),
                },
            )
        assert "secrets" in str(info.value)

    def test_field_optional(self) -> None:
        properties = AliyunSecretProperties(
            region="cn-hangzhou",
            secrets={
                "db-password": AliyunSecretMapping(secret_name="prod/db"),
            },
        )
        assert properties.secrets["db-password"].field is None


class TestAliyunSecretPropertiesTimezones:
    def test_timeouts_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            AliyunSecretProperties(
                region="cn-hangzhou",
                connect_timeout_seconds=0,
            )
        with pytest.raises(ValidationError):
            AliyunSecretProperties(
                region="cn-hangzhou",
                read_timeout_seconds=-1,
            )

    def test_max_attempts_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            AliyunSecretProperties(region="cn-hangzhou", max_attempts=0)


__all__ = []
