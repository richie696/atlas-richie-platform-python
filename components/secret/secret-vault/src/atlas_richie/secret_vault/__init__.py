"""`atlas-richie-secret-vault` — HashiCorp Vault backend for the secret platform。

中文
----
对位 Java `cn.richie696.component.secret.provider.vault.*`(8 个文件)。
1:1 功能对齐,但 Python 端按 R-232 决定压成单 wheel,内部子包:

- `auth.py` — 3 个 auth Strategy + 工厂(对位 Java
  `VaultClientFactory.authentication(...)` switch)
- `client.py` — `VaultSecretClient`,复合 5 个 SPI 角色
  (`SecretOperations` + `KeyWrappingBackend` + `SigningBackend` +
  `SecretBootstrapClient` + `SecretProviderSession`),1:1 对位
  Java `VaultSecretClient`
- `configuration.py` — `VaultConfigurationResolver`,
  含 path safety 校验 + SHA-256 configuration hash
- `factory.py` — `VaultSecretProviderFactory`(framework 入口)
  + 内部 `VaultClientFactory`(SDK 构造)
- `properties.py` — `VaultSecretProperties` + `AuthType`
  StrEnum(pydantic-settings env 注入,前缀
  `ATLAS_RICHIE_SECRET_VAULT_`)
- `request_id.py` — `VaultRequestIdCapture`,per-thread 关联 ID
- `retry.py` — `VaultRetryExecutor`,bounded retry + 指数退避

顶层 facade 只暴露 framework 集成点 + 调试用的 SPI 内部组件;hvac
SDK 类型不穿透。

English
--------
HashiCorp Vault backend wheel. Mirrors Java
`atlas-richie-secret-provider-vault` 1:1. Strategy / Adapter /
Factory / Composite patterns are used to assemble the 5 SPI
roles into a single `VaultSecretClient`. The top-level facade
re-exports only the framework integration points and the small
set of internal collaborators a test or advanced consumer
might reach for.
"""

from atlas_richie.secret_vault.auth import (
    AppRoleAuthStrategy,
    KubernetesAuthStrategy,
    TokenAuthStrategy,
    VaultAuthStrategy,
    auth_strategy_for,
)
from atlas_richie.secret_vault.client import VaultSecretClient
from atlas_richie.secret_vault.configuration import (
    ResolvedVaultConfiguration,
    VaultConfigurationResolver,
)
from atlas_richie.secret_vault.factory import (
    VaultClientFactory,
    VaultSecretProviderFactory,
)
from atlas_richie.secret_vault.properties import AuthType, VaultSecretProperties
from atlas_richie.secret_vault.request_id import VaultRequestIdCapture
from atlas_richie.secret_vault.retry import VaultRetryExecutor

__all__ = [
    # properties
    "AuthType",
    "VaultSecretProperties",
    # auth strategies
    "VaultAuthStrategy",
    "TokenAuthStrategy",
    "KubernetesAuthStrategy",
    "AppRoleAuthStrategy",
    "auth_strategy_for",
    # configuration
    "ResolvedVaultConfiguration",
    "VaultConfigurationResolver",
    # retry + observability
    "VaultRetryExecutor",
    "VaultRequestIdCapture",
    # SDK construction
    "VaultClientFactory",
    # framework entry
    "VaultSecretProviderFactory",
    # 5-SPI composite
    "VaultSecretClient",
]
