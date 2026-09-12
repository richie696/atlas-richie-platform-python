"""Huawei secret properties — pydantic-settings env injection。

中文
----
对位 Java `cn.richie696.component.secret.provider.huawei.HuaweiSecretProperties`
(SDK 改造后字段精简,不含旧 `wire.*`)。

字段:

- `region: str` — 必填
- `secret_endpoint: str` — 可选,CSMS 入口
- `kms_endpoint: str` — 可选,DEW KMS 入口
- `project_id: str` — **必填**(Huawei DEW BasicCredentials 需要)
- `secrets: dict[str, str]` — logical → 物理 SecretName
- `kms_key_bindings: dict[str, str]` — logical → 物理 KeyId
- `auth_type: AuthType.ACCESS_KEY` + `access_key_id` + `access_key_secret` +
  可选 `security_token`(STS 临时凭据)

English
--------
Pydantic-settings env-injected configuration for the
Huawei backend. Mirrors Java `HuaweiSecretProperties`
(post-SDK-refactor). Auth is forced to `ACCESS_KEY`
because Huawei's `BasicCredentials` requires
`ak + sk [+ security_token] + project_id`.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthType(str, Enum):
    """Huawei Cloud authentication mechanism (mirrors Java
    `RemoteProviderProperties.AuthenticationType`).
    """

    ACCESS_KEY = "access_key"


class HuaweiSecretProperties(BaseSettings):
    """Env-injected configuration for the Huawei CSMS + KMS backend."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_HUAWEI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    region: str = Field(...)
    secret_endpoint: str | None = Field(default=None)
    kms_endpoint: str | None = Field(default=None)
    project_id: str = Field(...)

    auth_type: AuthType = Field(default=AuthType.ACCESS_KEY)
    access_key_id: str = Field(default="")
    access_key_secret: str = Field(default="")
    security_token: str | None = Field(default=None)

    secrets: dict[str, str] = Field(default_factory=dict)
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


__all__ = ["AuthType", "HuaweiSecretProperties"]
