"""Volcengine secret properties — pydantic-settings env injection。

中文
----
对位 Java `cn.richie696.component.secret.provider.volcengine.VolcengineSecretProperties`
(SDK 改造后字段精简)。

字段:

- `region: str` — 必填
- `kms_endpoint: str` — 可选(默认 `https://kms.{region}.volcengineapi.com`)
- `namespace: str` — **必填**(Volcengine keyring namespace)
- `kms_key_bindings: dict[str, str]` — logical → 物理 KeyName
- `auth_type: AuthType.ACCESS_KEY` + `access_key_id` +
  `access_key_secret` + 可选 `security_token`

**KMS-only**:Volcengine 不提供 Secret Store 服务,所以
`SecretOperations` 不实现(对位 Java `SEC-CAP-001`)。

English
--------
Pydantic-settings env-injected configuration for the
Volcengine backend. Mirrors Java `VolcengineSecretProperties`
(post-SDK-refactor). Volcengine has no Secret Store —
this wheel is **KMS-only** (wrap / unwrap only).
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthType(str, Enum):
    """Volcengine authentication mechanism (mirrors Java
    `RemoteProviderProperties.AuthenticationType`).
    """

    ACCESS_KEY = "access_key"


class VolcengineSecretProperties(BaseSettings):
    """Env-injected configuration for the Volcengine KMS-only backend."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_VOLCENGINE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    region: str = Field(...)
    kms_endpoint: str | None = Field(default=None)
    namespace: str = Field(...)

    auth_type: AuthType = Field(default=AuthType.ACCESS_KEY)
    access_key_id: str = Field(default="")
    access_key_secret: str = Field(default="")
    security_token: str | None = Field(default=None)

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
                    f"kms_key_bindings: physical KeyName must be non-blank "
                    f"for logical {logical!r}",
                )
        return {k: v.strip() for k, v in value.items()}


__all__ = ["AuthType", "VolcengineSecretProperties"]
