"""IBM Key Protect secret properties — pydantic-settings env injection。

中文
----
对位 Java `cn.richie696.component.secret.provider.ibm.IbmKeyProtectProperties`
(SDK 改造后字段精简)。

字段:

- `region: str` — 必填(IBM Cloud region,例如 `us-south`)
- `kms_endpoint: str` — 必填,Key Protect service URL
  (默认 `https://{region}.kms.ibm.cloud.ibm.com`)
- `instance_id: str` — 必填,Key Protect instance GUID
  (Java 端 `tenant-id` 字段,IBM 叫 instance-id)
- `key_ring: str` — 可选,默认 `"default"`
- `kms_key_bindings: dict[str, str]` — logical → 物理 key
  CRN(IBM 资源名)

**认证**(`AuthType`):
- `BEARER_TOKEN` — IBM IAM access token(Java 端
  `BEARER_TOKEN` 走 `BearerTokenAuthenticator`)
- 其它类型**拒收**(`SEC-BOOT-003`)

English
--------
Pydantic-settings env-injected configuration for the IBM
Key Protect backend. Mirrors Java
`IbmKeyProtectProperties` (post-SDK-refactor). Auth is
**forced to** `BEARER_TOKEN` (IBM IAM token); other types
are rejected.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthType(str, Enum):
    """IBM Key Protect authentication mechanism (mirrors Java
    `RemoteProviderProperties.AuthenticationType`).
    """

    BEARER_TOKEN = "bearer_token"


class IbmKeyProtectProperties(BaseSettings):
    """Env-injected configuration for the IBM Key Protect KMS-only backend."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_IBM_KP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    region: str = Field(...)
    kms_endpoint: str | None = Field(default=None)
    instance_id: str = Field(...)
    key_ring: str = Field(default="default")
    auth_type: AuthType = Field(default=AuthType.BEARER_TOKEN)
    bearer_token: str | None = Field(default=None)

    kms_key_bindings: dict[str, str] = Field(default_factory=dict)

    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    read_timeout_seconds: float = Field(default=30.0, gt=0)
    max_attempts: int = Field(default=3, ge=1)

    @field_validator("region")
    @classmethod
    def _validate_region(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("region is required and must be non-blank")
        return value.strip()

    @field_validator("instance_id")
    @classmethod
    def _validate_instance_id(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("instance_id is required and must be non-blank")
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
                    f"kms_key_bindings[{logical!r}]: physical key CRN must be "
                    f"non-blank",
                )
        return {k: v.strip() for k, v in value.items()}


__all__ = ["AuthType", "IbmKeyProtectProperties"]
