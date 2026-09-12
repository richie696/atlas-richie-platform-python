"""`AliyunSecretProperties` — pydantic-settings 注入的阿里云配置。

中文
----
对位 Java `cn.richie696.component.secret.provider.aliyun.AliyunSecretProperties`。
env_prefix `ATLAS_RICHIE_SECRET_ALIYUN_`,所有可调字段都从环境变量注入;
不暴露 3rd-party SDK 类型(SDK 仅在 `AliyunClientFactory.create_gateway(...)`
中懒加载,见 `factory.py`)。

字段语义对位 Java:

- `region` — 必填(对位 Java `@NotBlank`);KMS / Secrets Manager endpoint
  都依赖它(endpoint 未指定时拼 `kms.{region}.aliyuncs.com`)。
- `endpoint` — 可选,完整 URI;若 host 包含 `cryptoservice.kms.aliyuncs.com`
  表明是专属 KMS,必须配 `ca_file`(对位 Java `AliyunClientFactory`)。
- `ca_file` — 可选,PEM 证书 bundle 路径,用于专属 KMS endpoint 的
  TLS 验证。
- `secrets_manager_path_prefix` — 可选,Secrets Manager 逻辑名 →
  物理名前缀;前置 `/`,无 `..` / `://` / 末尾 `/`。
- `kms_key_bindings` — `dict[logical, physical]`,逻辑名 → 阿里云
  KMS CMK id(对位 Java `Map<String, String>`)。
- `secrets` — `dict[logical, AliyunSecretMapping]`,逻辑名 → 物理
  secret name + 可选 JSON 字段名(对位 Java `Map<String, SecretMapping>`)。
- `connect_timeout_seconds` / `read_timeout_seconds` / `max_attempts`
  — SDK 超时 + 重试(对位 Java `Client.setConnectTimeout` /
  `setReadTimeout` / `RuntimeOptions` 的 `maxAttempts`)。

设计:

- 公开 API 用 `MappingProxyType` / `dict[str, ...]` 避免在外部代码
  里直接 mutate(冻结语义在 pydantic 校验完成时建立)。
- `AliyunSecretMapping` 是 frozen dataclass,只承载 `secret_name` +
  可选 `field`;对齐 Java 端 2 字段 record。
- 字段名遵循 snake_case + 类型注解;不为 Java Lombok / record
  getter 保留 setter 入口。

English
--------
Pydantic-settings-injected Alibaba Cloud properties. Mirrors Java
`AliyunSecretProperties`. Env prefix `ATLAS_RICHIE_SECRET_ALIYUN_`;
no 3rd-party SDK type is referenced here (the SDK is loaded lazily
inside `AliyunClientFactory.create_gateway(...)`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True, slots=True)
class AliyunSecretMapping:
    """Mapping from a logical secret name to a physical Secrets Manager entry.

    Attributes:
        secret_name: Backend-side name of the secret (e.g. ``"prod/db"``).
        field: Optional JSON field name to pluck out of the stored
            document. ``None`` means the stored value is the secret
            itself (a scalar string).
    """

    secret_name: str
    field: str | None = None


class AliyunSecretProperties(BaseSettings):
    """Configuration for the Alibaba Cloud Secrets Manager + KMS backend.

    All fields are overridable via environment variables prefixed with
    `ATLAS_RICHIE_SECRET_ALIYUN_`. Pydantic-settings resolves nested
    keys with `__`, e.g. `ATLAS_RICHIE_SECRET_ALIYUN_REGION` →
    `region`.

    Attributes:
        region: Alibaba Cloud region id (e.g. ``"cn-hangzhou"``).
            Required; the configuration resolver rejects empty values.
        endpoint: Optional full URI for the KMS endpoint. Defaults
            to ``"kms.{region}.aliyuncs.com"`` when not set. Required
            when the host contains ``".cryptoservice.kms.aliyuncs.com"``
            (dedicated KMS), and must be HTTPS (loopback HTTP is
            allowed for local development).
        ca_file: Optional path to a PEM certificate bundle used to
            verify the TLS connection to a dedicated KMS endpoint.
        secrets_manager_path_prefix: Optional prefix prepended (with
            a leading ``/``) to every logical secret name when no
            explicit `secrets` mapping is provided. Must not contain
            ``..`` / ``://`` / leading or trailing ``/``.
        kms_key_bindings: Mapping from logical key name (the value
            passed as `KeyReference.key_id`) to the physical Alibaba
            Cloud KMS CMK id. Logical names must be non-blank
            "safe logical" strings; physical ids must be non-blank.
        secrets: Mapping from logical secret name (the value passed
            as `SecretReference.path`) to a physical Secrets Manager
            name + optional JSON field. Each mapping is validated to
            have a non-blank `secret_name` and a safe optional `field`.
        connect_timeout_seconds: Connect timeout for the SDK client
            (mirrors Java `Client.setConnectTimeout`).
        read_timeout_seconds: Per-request read timeout (mirrors Java
            `Client.setReadTimeout`).
        max_attempts: Retry count for transient SDK failures (mirrors
            Java `RuntimeOptions.maxAttempts`).
    """

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_ALIYUN_",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    region: str = Field(..., min_length=1, description="Alibaba Cloud region id, e.g. 'cn-hangzhou'.")
    endpoint: str | None = Field(
        default=None,
        description="Optional full KMS endpoint URI; defaults to 'kms.{region}.aliyuncs.com'.",
    )
    ca_file: str | None = Field(
        default=None,
        description="Optional PEM bundle path for dedicated KMS endpoint TLS verification.",
    )
    secrets_manager_path_prefix: str | None = Field(
        default=None,
        description="Optional Secrets Manager path prefix prepended with '/' to logical names.",
    )
    kms_key_bindings: dict[str, str] = Field(
        default_factory=dict,
        description="Logical key name → physical Alibaba KMS CMK id.",
    )
    secrets: dict[str, AliyunSecretMapping] = Field(
        default_factory=dict,
        description="Logical secret name → physical Secrets Manager entry + optional field.",
    )
    connect_timeout_seconds: float = Field(
        default=10.0,
        ge=0.0,
        description="SDK connect timeout in seconds.",
    )
    read_timeout_seconds: float = Field(
        default=30.0,
        ge=0.0,
        description="SDK per-request read timeout in seconds.",
    )
    max_attempts: int = Field(
        default=3,
        ge=1,
        description="Retry count for transient SDK failures.",
    )

    @classmethod
    def model_validate_mapping(cls, source: Mapping[str, Any]) -> "AliyunSecretProperties":
        """Build an `AliyunSecretProperties` from an arbitrary mapping.

        Pydantic's standard `model_validate` accepts the same input
        shape, but the dedicated method is here so that callers can
        chain custom pre-validators without losing the readability
        affordance of an explicit name.
        """
        return cls.model_validate(dict(source))


__all__ = [
    "AliyunSecretMapping",
    "AliyunSecretProperties",
]
