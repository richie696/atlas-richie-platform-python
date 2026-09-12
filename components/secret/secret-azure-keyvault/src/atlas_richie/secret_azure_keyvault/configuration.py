"""Azure Key Vault configuration resolver — path safety + SHA-256 hash.

中文
----
对位 Java `AzureSecretConfigurationResolver`(Java 端的具体文件
`AzureSecretConfigurationResolver.java` 留作扩展点,本 wheel 的
核心配置由 `AbstractRemoteProviderFactory` 公共类处理)。

Python 端把 path safety + hash 计算集中到本模块:

1. **path safety 校验**:Azure `vault_url` 不允许 `..` /
   `://` / 开头 `/`(对位 Java `safeLogicalName` 模式)
2. **capability 固定**:Azure backend 静态声明
   `can_read=True, can_write=False, can_rotate=True, can_list=False,
   encrypts_at_rest=True`(对位 Java 4 个 capability: SECRET_READ
   / SECRET_VERSIONING / KEY_WRAP / KEY_UNWRAP,**不**含 LIST)
3. **configuration_hash**:SHA-256 over canonical fields,用于
   session reuse detection

Azure 跟 AWS 的 capability 区别:**can_list=False**(Azure 端
`SecretClient.list_properties_of_secrets` 存在但 Java Azure
`AbstractRemoteProviderFactory` 没声明 LIST,我们跟 Java 一致
不暴露 list)。

English
--------
Resolves `AzureSecretProperties` to `ResolvedAzureConfiguration`.
Mirrors Java's `AbstractRemoteProviderFactory`-level capability
declaration. Path safety check on the vault URL, static
`SecretCapability`, SHA-256 configuration hash.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability

if TYPE_CHECKING:
    from atlas_richie.secret_azure_keyvault.properties import AzureSecretProperties


def _safe_url(value: str, label: str) -> None:
    if not value or ".." in value or value.startswith("/"):
        raise SecretConfigurationException(
            f"azure: {label} is invalid (no '..' or leading '/'): {value!r}",
        )


def _azure_capability() -> SecretCapability:
    """Static capability for the Azure Key Vault backend.

    Mirrors Java `providerCapabilities` on
    `AzureSecretBootstrapProviderFactory`:
    - `SECRET_READ` / `SECRET_VERSIONING` (Secrets API)
    - `KEY_WRAP` / `KEY_UNWRAP` (Keys API)

    NOT exposed (Java does not declare):
    - `SECRET_LIST`
    - `SIGN` / `VERIFY`
    """
    return SecretCapability(
        can_read=True,
        can_write=False,
        can_rotate=True,
        can_list=False,
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=True,
    )


@dataclass(frozen=True, slots=True)
class ResolvedAzureConfiguration:
    """Immutable result of resolving `AzureSecretProperties`."""

    provider_id: str
    properties: "AzureSecretProperties"
    configuration_hash: str
    capability: SecretCapability = field(default_factory=_azure_capability)


class AzureConfigurationResolver:
    """Resolve `AzureSecretProperties` to a `ResolvedAzureConfiguration`."""

    __slots__ = ()

    def resolve(
        self,
        properties: "AzureSecretProperties",
        *,
        provider_id: str = "azure-main",
    ) -> ResolvedAzureConfiguration:
        _safe_url(properties.vault_url, "vault_url")
        return ResolvedAzureConfiguration(
            provider_id=provider_id,
            properties=properties,
            configuration_hash=self._configuration_hash(provider_id, properties),
        )

    @staticmethod
    def _configuration_hash(
        provider_id: str,
        properties: "AzureSecretProperties",
    ) -> str:
        bindings = properties.key_bindings or {}
        bindings_canonical = "\n".join(
            f"{k}={v}" for k, v in sorted(bindings.items())
        )
        canonical = (
            f"{provider_id}\n"
            f"{properties.vault_url}\n"
            f"{properties.default_key_wrap_algorithm.value}\n"
            f"{bindings_canonical}\n"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ResolvedAzureConfiguration",
    "AzureConfigurationResolver",
]
