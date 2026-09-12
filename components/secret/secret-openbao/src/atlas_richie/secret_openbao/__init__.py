"""`atlas-richie-secret-openbao` — OpenBao backend for the secret platform。

中文
----
对位 Java `cn.richie696.component.secret.provider.openbao.*`。
OpenBao API 100% 兼容 Vault,所以 Python 端走 **thin wrapper**
模式:

- `OpenBaoSecretProperties` — `VaultSecretProperties` 子类,
  零新增字段(等 OpenBao 偏离时再补)
- `OpenBaoSecretProviderFactory` — `VaultSecretProviderFactory`
  子类,只 override `name` 前缀(`openbao-`)/ `backend` 枚举
  (`SecretBackend.OPENBAO`)/ `version` 后缀,SDK 构造 / auth /
  retry / request-id / 5-SPI composite **全部**继承自
  `VaultSecretProviderFactory`
- `VaultSecretClient` — 直接 re-export,运行时产出的对象就是
  `VaultSecretClient` 实例,只是 `descriptor.backend` 不同

`hvac` 客户端类型 / `VaultSecretClient` 类型**不**穿透到 OpenBao
facade 之外(只有 `OpenBaoSecretProperties` + `OpenBaoSecretProviderFactory`
+ `VaultSecretClient` 三个 public symbol)。

English
--------
Thin wrapper over `atlas-richie-secret-vault`. OpenBao is API-
compatible with Vault (KV v2 + Transit), so this wheel exists
only for brand attribution and future OpenBao-specific
divergence. 3 public symbols.
"""

from atlas_richie.secret_openbao.factory import OpenBaoSecretProviderFactory
from atlas_richie.secret_openbao.properties import OpenBaoSecretProperties
from atlas_richie.secret_vault.client import VaultSecretClient

__all__ = [
    "OpenBaoSecretProperties",
    "OpenBaoSecretProviderFactory",
    "VaultSecretClient",
]
