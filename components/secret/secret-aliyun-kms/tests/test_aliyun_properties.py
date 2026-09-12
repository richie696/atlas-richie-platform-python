"""Unit tests for `AliyunSecretProperties` pydantic-settings injection。

中文
----
覆盖:
- env_prefix `ATLAS_RICHIE_SECRET_ALIYUN_` 生效
- 必填字段 `region` 缺失时 pydantic 抛 `ValidationError`
- 可选字段 `endpoint` / `ca_file` / `secrets_manager_path_prefix`
  默认为 `None`
- `kms_key_bindings` / `secrets` 字典注入
- `connect_timeout_seconds` / `read_timeout_seconds` / `max_attempts`
  默认值
- 数值字段的边界值(`max_attempts >= 1`,`connect_timeout_seconds >= 0`)

English
--------
Tests that pydantic-settings injects environment variables with the
expected prefix, that defaults line up with Java
`AliyunSecretProperties`, and that boundary values are validated
upfront. No SDK is required.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret_aliyun_kms.properties import (
    AliyunSecretMapping,
    AliyunSecretProperties,
)


class TestAliyunSecretPropertiesEnvInjection:
    """Verify pydantic-settings env_prefix and field injection."""

    def test_env_prefix_is_aliyun(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", "cn-beijing")
        monkeypatch.delenv("ATLAS_RICHIE_SECRET_AWS_REGION", raising=False)
        monkeypatch.delenv("ATLAS_RICHIE_SECRET_REDIS_HOST", raising=False)
        properties = AliyunSecretProperties()
        assert properties.region == "cn-beijing"

    def test_region_is_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", raising=False)
        with pytest.raises(ValidationError):
            AliyunSecretProperties()

    def test_region_blank_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", "")
        with pytest.raises(ValidationError):
            AliyunSecretProperties()

    def test_endpoint_optional_default_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", "cn-hangzhou")
        properties = AliyunSecretProperties()
        assert properties.endpoint is None

    def test_endpoint_injected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", "cn-hangzhou")
        monkeypatch.setenv(
            "ATLAS_RICHIE_SECRET_ALIYUN_ENDPOINT",
            "https://kms.cn-hangzhou.aliyuncs.com",
        )
        properties = AliyunSecretProperties()
        assert properties.endpoint == "https://kms.cn-hangzhou.aliyuncs.com"

    def test_ca_file_optional_default_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", "cn-hangzhou")
        properties = AliyunSecretProperties()
        assert properties.ca_file is None

    def test_secrets_manager_path_prefix_optional(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", "cn-hangzhou")
        monkeypatch.setenv(
            "ATLAS_RICHIE_SECRET_ALIYUN_SECRETS_MANAGER_PATH_PREFIX",
            "my-team",
        )
        properties = AliyunSecretProperties()
        assert properties.secrets_manager_path_prefix == "my-team"

    def test_kms_key_bindings_dict_default_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", "cn-hangzhou")
        properties = AliyunSecretProperties()
        assert properties.kms_key_bindings == {}

    def test_kms_key_bindings_injected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", "cn-hangzhou")
        monkeypatch.setenv(
            "ATLAS_RICHIE_SECRET_ALIYUN_KMS_KEY_BINDINGS",
            '{"cmk-a": "alias/my-team/cmk-a", "cmk-b": "alias/my-team/cmk-b"}',
        )
        properties = AliyunSecretProperties()
        assert properties.kms_key_bindings == {
            "cmk-a": "alias/my-team/cmk-a",
            "cmk-b": "alias/my-team/cmk-b",
        }

    def test_secrets_mapping_default_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", "cn-hangzhou")
        properties = AliyunSecretProperties()
        assert properties.secrets == {}

    def test_timeouts_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", "cn-hangzhou")
        properties = AliyunSecretProperties()
        assert properties.connect_timeout_seconds == 10.0
        assert properties.read_timeout_seconds == 30.0
        assert properties.max_attempts == 3

    def test_timeouts_overridable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", "cn-hangzhou")
        monkeypatch.setenv(
            "ATLAS_RICHIE_SECRET_ALIYUN_CONNECT_TIMEOUT_SECONDS", "5.5"
        )
        monkeypatch.setenv(
            "ATLAS_RICHIE_SECRET_ALIYUN_READ_TIMEOUT_SECONDS", "15"
        )
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_MAX_ATTEMPTS", "5")
        properties = AliyunSecretProperties()
        assert properties.connect_timeout_seconds == 5.5
        assert properties.read_timeout_seconds == 15.0
        assert properties.max_attempts == 5

    def test_max_attempts_must_be_positive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", "cn-hangzhou")
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_MAX_ATTEMPTS", "0")
        with pytest.raises(ValidationError):
            AliyunSecretProperties()

    def test_connect_timeout_must_be_non_negative(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", "cn-hangzhou")
        monkeypatch.setenv(
            "ATLAS_RICHIE_SECRET_ALIYUN_CONNECT_TIMEOUT_SECONDS", "-1"
        )
        with pytest.raises(ValidationError):
            AliyunSecretProperties()

    def test_env_prefix_does_not_collide_with_sibling_wheels(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sanity check: a different wheel's env var must not leak in."""
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_ALIYUN_REGION", "cn-hangzhou")
        monkeypatch.setenv("ATLAS_RICHIE_SECRET_AWS_REGION", "us-east-1")
        properties = AliyunSecretProperties()
        assert properties.region == "cn-hangzhou"


class TestAliyunSecretMapping:
    """Direct construction + frozen semantics of `AliyunSecretMapping`."""

    def test_minimal_construction(self) -> None:
        mapping = AliyunSecretMapping(secret_name="prod/db")
        assert mapping.secret_name == "prod/db"
        assert mapping.field is None

    def test_field_optional(self) -> None:
        mapping = AliyunSecretMapping(secret_name="prod/db", field="password")
        assert mapping.field == "password"

    def test_frozen(self) -> None:
        mapping = AliyunSecretMapping(secret_name="prod/db", field="password")
        with pytest.raises((AttributeError, Exception)):
            mapping.secret_name = "other"  # type: ignore[misc]


class TestModelValidateMapping:
    """The `model_validate_mapping` helper accepts a dict."""

    def test_validate_from_mapping(self) -> None:
        properties = AliyunSecretProperties.model_validate_mapping(
            {
                "region": "cn-shanghai",
                "kms_key_bindings": {"a": "id-a"},
            }
        )
        assert properties.region == "cn-shanghai"
        assert properties.kms_key_bindings == {"a": "id-a"}

    def test_validate_from_mapping_rejects_blank_region(self) -> None:
        with pytest.raises(ValidationError):
            AliyunSecretProperties.model_validate_mapping({"region": ""})
