"""`atlas-richie-secret-barbican` — OpenStack Barbican secret backend。

中文
----
对位 Java `cn.richie696.component.secret.provider.barbican.*`(5 个文件)。
1:1 功能对齐,Python 端按 R-232 决定压成单 wheel,内部子包:

- `properties.py` — `BarbicanSecretProperties` +
  `BarbicanAuth` / `AuthType` / `BarbicanSecretMapping`
  (pydantic-settings env 注入,前缀
  `ATLAS_RICHIE_SECRET_BARBICAN_`)
- `configuration.py` — `BarbicanConfigurationResolver`,含
  endpoint / auth / secrets 校验 + SHA-256 configuration hash
- `client.py` — `BarbicanSecretClient`,复合 3 个 SPI 角色
  (`SecretOperations` via HTTP GET + `SecretBootstrapClient`
  + `SecretProviderSession`),**无** `KeyWrappingBackend` /
  `SecretWriter` / `SecretDeletable`(Barbican 是 secret
  store,无 KMS,read-only)
- `factory.py` — `BarbicanSecretProviderFactory`(framework
  入口) + 内部 `BarbicanClientFactory`(`httpx.Client` 构造)

依赖 `httpx` 做 HTTP 客户端(对位 Java JDK `HttpClient` +
`RemoteHttpClientFactory`)。SDK 类型(httpx.Response /
httpx.Client)不穿透到 framework 边界。

English
--------
OpenStack Barbican backend wheel. Mirrors Java
`atlas-richie-secret-provider-barbican` 1:1. 4 source
files (properties / configuration / client / factory).
3-SPI composite: `SecretOperations` + `SecretBootstrapClient`
+ `SecretProviderSession`. No `KeyWrappingBackend`
(Barbican has no KMS wrap API) and no `SecretWriter` /
`SecretDeletable` (read-only). Uses `httpx.Client` for
HTTP.
"""

from atlas_richie.secret_barbican.client import (
    BarbicanSecretClient,
    BarbicanSecretMetadata,
)
from atlas_richie.secret_barbican.configuration import (
    BarbicanConfigurationResolver,
    ResolvedBarbicanConfiguration,
)
from atlas_richie.secret_barbican.factory import (
    BarbicanClientFactory,
    BarbicanSecretProviderFactory,
)
from atlas_richie.secret_barbican.properties import (
    AuthType,
    BarbicanAuth,
    BarbicanSecretMapping,
    BarbicanSecretProperties,
)

__all__ = [
    # properties
    "BarbicanSecretProperties",
    "BarbicanSecretMapping",
    "BarbicanAuth",
    "AuthType",
    # configuration
    "ResolvedBarbicanConfiguration",
    "BarbicanConfigurationResolver",
    # HTTP construction
    "BarbicanClientFactory",
    # framework entry
    "BarbicanSecretProviderFactory",
    # 3-SPI composite
    "BarbicanSecretClient",
    "BarbicanSecretMetadata",
]
