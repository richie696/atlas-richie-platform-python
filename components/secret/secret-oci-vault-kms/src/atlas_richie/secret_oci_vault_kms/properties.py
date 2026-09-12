"""OCI secret properties — pydantic-settings env injection。

中文
----
对位 Java `cn.richie696.component.secret.provider.oci.OciSecretProperties`
(SDK 改造后字段精简)。

字段:

- `region: str` — 必填
- `secret_endpoint: str` — 可选,OCI Vault 入口
- `kms_endpoint: str` — 可选,OCI KMS 入口
- `secrets: dict[str, str]` — logical → 物理 secret OCID
- `kms_key_bindings: dict[str, str]` — logical → 物理 Key OCID

**认证**(`AuthType`):
- `NONE` → **Instance Principal**(Java 端 `NONE` 走
  `InstancePrincipalsAuthenticationDetailsProvider`)
- `WORKLOAD_IDENTITY_TOKEN_FILE` → **Resource Principal**
  (Java 端 `WORKLOAD_IDENTITY_TOKEN_FILE` 走
  `ResourcePrincipalAuthenticationDetailsProvider`;实际凭据
  由 OCI 运行环境提供,token file 路径不被读取)
- ACCESS_KEY / 其它类型**拒收**(`SEC-BOOT-003`)

English
--------
Pydantic-settings env-injected configuration for the
OCI backend. Mirrors Java `OciSecretProperties`
(post-SDK-refactor). Auth is **forced to** `NONE` (Instance
Principal) **or** `WORKLOAD_IDENTITY_TOKEN_FILE` (Resource
Principal); API-key auth is rejected (the SDK does not
support it).
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthType(str, Enum):
    """OCI authentication mechanism (mirrors Java
    `RemoteProviderProperties.AuthenticationType`).
    """

    NONE = "none"
    WORKLOAD_IDENTITY_TOKEN_FILE = "workload_identity_token_file"


class OciSecretProperties(BaseSettings):
    """Env-injected configuration for the OCI Vault + KMS backend."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_OCI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    region: str = Field(...)
    secret_endpoint: str | None = Field(default=None)
    kms_endpoint: str | None = Field(default=None)

    auth_type: AuthType = Field(default=AuthType.NONE)
    workload_identity_token_file: str | None = Field(default=None)

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
                    f"secrets[{logical!r}]: physical OCID must be non-blank",
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
                    f"kms_key_bindings: physical Key OCID must be non-blank "
                    f"for logical {logical!r}",
                )
        return {k: v.strip() for k, v in value.items()}


__all__ = ["AuthType", "OciSecretProperties"]
