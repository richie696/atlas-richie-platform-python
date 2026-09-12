"""Azure Key Vault properties — pydantic-settings env injection.

中文
----
对位 Java `cn.richie696.component.secret.provider.azure.AzureSecretProperties`(Java
端是薄 stub,配置全在 `AbstractRemoteProviderFactory` 公共类里)。

字段:

- **连接**:`vault_url`(`https://*.vault.azure.net/`,必填)
- **认证**:credential 走 `DefaultAzureCredential`,framework
  不暴露具体方式(env / managed identity / Azure CLI / etc.
  全部由 SDK 处理)
- **KMS key bindings**:`key_bindings`(logical → 物理 Key Vault
  key name),跟 vault R-233.3 / aws R-235 模式一致

English
--------
Pydantic-settings env-injected configuration for Azure Key
Vault. Mirrors Java's thin stub. Authentication is delegated
to `azure-identity.DefaultAzureCredential` (env / managed
identity / Azure CLI); the framework does not expose the
choice.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    pass


class AzureKeyWrapAlgorithm(StrEnum):
    """Azure Key Vault local-cryptographic wrap algorithms.

    Mirrors `azure.keyvault.keys.crypto.KeyWrapAlgorithm` for
    the subset that does not require HSM. Default
    `RSA_OAEP_256` (RSA-OAEP with SHA-256) is the most
    broadly supported.
    """

    RSA_OAEP = "rsa-oaep"
    RSA_OAEP_256 = "rsa-oaep-256"
    RSA1_5 = "rsa1_5"


class AzureSecretProperties(BaseSettings):
    """Env-injected configuration for the Azure Key Vault backend."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_AZURE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    vault_url: str = Field(...)
    timeout_seconds: float = Field(default=30.0, gt=0)

    # Key bindings: logical → physical key name.
    key_bindings: dict[str, str] = Field(default_factory=dict)

    # Default key wrap algorithm (per-call override via
    # `wrap_key(..., algorithm=...)` is also supported).
    default_key_wrap_algorithm: AzureKeyWrapAlgorithm = Field(
        default=AzureKeyWrapAlgorithm.RSA_OAEP_256,
    )

    @field_validator("vault_url")
    @classmethod
    def _validate_vault_url(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError(
                "vault_url must start with https:// or http://; "
                f"got {value!r}",
            )
        return value


__all__ = [
    "AzureKeyWrapAlgorithm",
    "AzureSecretProperties",
]
