"""Aliyun secret backend properties — pydantic-settings env injection。

中文
----
对位 Java `cn.richie696.component.secret.provider.aliyun.AliyunSecretProperties`。

字段分类:

- **连接**:`region`(必填,例如 `cn-hangzhou`)、`endpoint`(可选,完整
  URI;为空时自动构造 `kms.{region}.aliyuncs.com`)、`ca_file`(专有
  KMS endpoint `.cryptoservice.kms.aliyuncs.com` 强制要求)
- **Secrets Manager**:`secrets_manager_path_prefix`(逻辑名 → 物理
  secret name 的前缀,例如 `company`)
- **KMS**:`kms_key_bindings`(logical → 物理 CMK id / alias,跟 Vault
  R-233.3 / AWS R-235 / Azure R-236 模式一致)
- **secret 映射**:`secrets: dict[str, AliyunSecretMapping]`(逻辑名
  → `secret_name` + 可选 `field`,对位 Java `SecretMapping`)
- **超时 / 重试**:`connect_timeout_seconds` / `read_timeout_seconds`
  / `max_attempts`(默认 10/30/3,跟 Java `BootstrapSecretProperties`
  默认一致)

**认证**:Aliyun SDK 用 `alibabacloud_credentials.Client` 自动从
env / instance metadata / RAM role 解析凭证。Framework 不暴露具体
auth 方式(对位 Java 端 `Client credentials = new Client()` 同样
不暴露)。

English
--------
Pydantic-settings env-injected configuration for the Aliyun
backend. Mirrors Java `AliyunSecretProperties`: region /
endpoint / ca_file / Secrets Manager path prefix / KMS key
bindings / secret mapping table. Auth is delegated to the
Alibaba SDK's credential client (env / instance metadata /
RAM role); the framework does not expose the choice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    pass


@dataclass(frozen=True, slots=True)
class AliyunSecretMapping:
    """Logical → physical secret mapping (mirrors Java `SecretMapping`).

    Attributes:
        secret_name: Physical Alibaba Cloud Secrets Manager
            secret name (resolved after the path prefix is
            applied by the client).
        field: Optional JSON field name to extract from the
            secret value. If set, the secret must be a JSON
            object and the named field must be a scalar.
    """

    secret_name: str
    field: str | None = None


class AliyunSecretProperties(BaseSettings):
    """Env-injected configuration for the Aliyun secret backend."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_ALIYUN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Connection — region is required, endpoint optional.
    region: str = Field(...)
    endpoint: str | None = Field(default=None)
    ca_file: str | None = Field(default=None)

    # Secrets Manager
    secrets_manager_path_prefix: str = Field(default="")

    # KMS
    kms_key_bindings: dict[str, str] = Field(default_factory=dict)

    # Secret mapping table
    secrets: dict[str, AliyunSecretMapping] = Field(default_factory=dict)

    # Timeouts and retries
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    read_timeout_seconds: float = Field(default=30.0, gt=0)
    max_attempts: int = Field(default=3, ge=1)

    @field_validator("region")
    @classmethod
    def _validate_region(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("region is required and must be non-blank")
        return value.strip()

    @field_validator("kms_key_bindings")
    @classmethod
    def _validate_key_bindings(cls, value: dict[str, str]) -> dict[str, str]:
        for logical, physical in value.items():
            if not logical or not logical.strip():
                raise ValueError(
                    f"kms_key_bindings: logical key must be non-blank: {logical!r}",
                )
            if not physical or not physical.strip():
                raise ValueError(
                    f"kms_key_bindings: physical key id must be non-blank "
                    f"for logical {logical!r}",
                )
        # Strip whitespace from physical values (logical keys
        # are preserved verbatim — Python dicts do not allow
        # mutating keys post-validation).
        return {k: v.strip() for k, v in value.items()}

    @field_validator("secrets")
    @classmethod
    def _validate_secrets(cls, value: dict[str, AliyunSecretMapping]) -> dict[str, AliyunSecretMapping]:
        for logical, mapping in value.items():
            if not logical or not logical.strip():
                raise ValueError(
                    f"secrets: logical name must be non-blank: {logical!r}",
                )
            if mapping is None:
                raise ValueError(
                    f"secrets[{logical!r}]: mapping must not be null",
                )
            if not mapping.secret_name or not mapping.secret_name.strip():
                raise ValueError(
                    f"secrets[{logical!r}]: secret_name must be non-blank",
                )
        return value


__all__ = [
    "AliyunSecretMapping",
    "AliyunSecretProperties",
]
