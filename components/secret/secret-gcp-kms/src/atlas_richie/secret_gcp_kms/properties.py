"""GCP Secret Manager + KMS properties — pydantic-settings env injection.

中文
----
对位 Java `cn.richie696.component.secret.provider.gcp.GcpSecretProperties`
(Java 端是薄 stub,核心配置在 `AbstractRemoteProviderFactory` 公共类)。

字段:
- **连接**:`project_id`(GCP 项目 ID,必填)
- **认证**:走 `google.auth.default()` 处理 ADC 链(env / metadata
  server / `gcloud auth` / workload identity),framework 不暴露
  具体方式
- **KMS**:`kms_key_ring` / `kms_key_name` / `kms_location` /
  `kms_key_bindings`(logical → 物理 KMS key resource name)

English
--------
Pydantic-settings env-injected configuration for GCP Secret
Manager + KMS. Authentication is delegated to
`google.auth.default()` (Application Default Credentials).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    pass


class GcpKmsAlgorithm(StrEnum):
    """GCP KMS protection level hint (subset that does not
    require HSM). Default `EXTERNAL` means the key was imported
    (the `kms.encrypt` / `kms.decrypt` envelope format)."""

    EXTERNAL = "EXTERNAL"
    SOFTWARE = "SOFTWARE"


class GcpSecretProperties(BaseSettings):
    """Env-injected configuration for the GCP Secret Manager +
    KMS backend."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_GCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_id: str = Field(...)
    timeout_seconds: float = Field(default=30.0, gt=0)

    # KMS
    kms_location: str = Field(default="global")
    kms_key_ring: str = Field(default="atlas-richie")
    kms_key_bindings: dict[str, str] = Field(default_factory=dict)

    @field_validator("project_id")
    @classmethod
    def _validate_project_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("project_id is required")
        return value.strip()


__all__ = ["GcpKmsAlgorithm", "GcpSecretProperties"]
