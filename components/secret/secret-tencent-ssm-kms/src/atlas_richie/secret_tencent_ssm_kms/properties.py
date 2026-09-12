"""Tencent secret properties — pydantic-settings env injection。

中文
----
对位 Java `cn.richie696.component.secret.provider.tencent.TencentSecretProperties`
(经 SDK 改造后的字段,不再有旧 REST 的 `wire.*`)。

字段:

- `region: str` — 必填(例如 `ap-guangzhou`)
- `secret_endpoint: str` — 可选,SSM 入口,默认走 SDK 内部 region
  路由
- `kms_endpoint: str` — 可选,KMS 入口,默认走 SDK 内部 region 路由
- `secrets: dict[str, str]` — logical → 物理 Tencent SecretName
- `kms_key_bindings: dict[str, str]` — logical → 物理 KeyId
- `connect_timeout_seconds: float = 10`
- `read_timeout_seconds: float = 30`
- `max_attempts: int = 3`

**认证**(`AuthType`):
- `ACCESS_KEY` + `access_key_id` + `access_key_secret` + 可选
  `security_token`(STS 临时凭据,需 refresh 时也走这个)
- 其它模式(SCS / CAM 角色)由腾讯云 SDK 的 `Credential` 解析,
  本 wheel 强制 ACCESS_KEY 一条路径(对位 Java 端 ACCESS_KEY
  模式约束)

English
--------
Pydantic-settings env-injected configuration for the
Tencent backend. Mirrors Java `TencentSecretProperties`
(post-SDK-refactor; no legacy `wire.*` fields). Auth is
forced to `ACCESS_KEY` (the SDK's `Credential` class
takes id + secret + optional security token for STS).
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthType(str, Enum):
    """Tencent Cloud authentication mechanism (mirrors Java
    `RemoteProviderProperties.AuthenticationType`).
    """

    ACCESS_KEY = "access_key"


class TencentSecretProperties(BaseSettings):
    """Env-injected configuration for the Tencent SSM + KMS backend."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_TENCENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Connection
    region: str = Field(...)
    secret_endpoint: str | None = Field(default=None)
    kms_endpoint: str | None = Field(default=None)

    # Auth (flat fields; ACCESS_KEY only)
    auth_type: AuthType = Field(default=AuthType.ACCESS_KEY)
    access_key_id: str = Field(default="")
    access_key_secret: str = Field(default="")
    security_token: str | None = Field(default=None)

    # Logical → physical
    secrets: dict[str, str] = Field(default_factory=dict)
    kms_key_bindings: dict[str, str] = Field(default_factory=dict)

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

    @field_validator("secrets")
    @classmethod
    def _validate_secrets(cls, value: dict[str, str]) -> dict[str, str]:
        for logical, physical in value.items():
            if not logical or not logical.strip():
                raise ValueError(
                    f"secrets: logical name must be non-blank: {logical!r}",
                )
            if not physical or not physical.strip():
                raise ValueError(
                    f"secrets[{logical!r}]: physical SecretName must be non-blank",
                )
        return {k: v.strip() for k, v in value.items()}

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
                    f"kms_key_bindings: physical KeyId must be non-blank "
                    f"for logical {logical!r}",
                )
        return {k: v.strip() for k, v in value.items()}


__all__ = ["AuthType", "TencentSecretProperties"]
