"""Baidu Cloud KMS secret properties — pydantic-settings env injection。

中文
----
对位 Java
`cn.richie696.component.secret.provider.baidu.BaiduSecretProperties`
(SDK 改造后字段精简)。

字段:

- `region: str` — 必填(冗余,KMS endpoint 不一定需要 region
  但 BCE SDK 用 region 做 signing;Java 端对应)
- `kms_endpoint: str` — 必填,BCE KMS 入口
  (默认 `http://bkm.bj.baidubce.com`)
- `kms_key_bindings: dict[str, str]` — logical → 物理 key
  ID

**认证**(`AuthType`):
- `ACCESS_KEY` — BCE AK + SK(Java 端 `ACCESS_KEY` 走
  `DefaultBceCredentials`)
- 其它类型**拒收**(`SEC-BOOT-003`)

English
--------
Pydantic-settings env-injected configuration for the
Baidu Cloud KMS backend. Mirrors Java
`BaiduSecretProperties` (post-SDK-refactor). Auth is
**forced to** `ACCESS_KEY` (BCE AK + SK); other types
are rejected.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthType(str, Enum):
    """Baidu Cloud KMS authentication mechanism (mirrors Java
    `RemoteProviderProperties.AuthenticationType`).
    """

    ACCESS_KEY = "access_key"


class BaiduSecretProperties(BaseSettings):
    """Env-injected configuration for the Baidu Cloud KMS-only backend."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_BAIDU_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    region: str = Field(default="bj")
    kms_endpoint: str = Field(default="http://bkm.bj.baidubce.com")
    auth_type: AuthType = Field(default=AuthType.ACCESS_KEY)
    access_key_id: str = Field(...)
    access_key_secret: str = Field(...)
    kms_key_bindings: dict[str, str] = Field(default_factory=dict)

    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    read_timeout_seconds: float = Field(default=30.0, gt=0)
    max_attempts: int = Field(default=3, ge=1)

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
                    f"kms_key_bindings[{logical!r}]: physical key id must be "
                    f"non-blank",
                )
        return {k: v.strip() for k, v in value.items()}


__all__ = ["AuthType", "BaiduSecretProperties"]
