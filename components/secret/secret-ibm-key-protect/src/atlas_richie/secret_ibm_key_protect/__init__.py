"""`atlas-richie-secret-ibm-key-protect` — IBM Cloud Key Protect KMS-only backend。

中文
----
对位 Java
`cn.richie696.component.secret.provider.ibm.*`(SDK 改造后
2 个文件),Python 端按 R-232 决定压成单 wheel,内部子包:

- `properties.py` — `IbmKeyProtectProperties` + `AuthType`
  (pydantic-settings env 注入,前缀
  `ATLAS_RICHIE_SECRET_IBM_KP_`)
- `configuration.py` — `IbmKeyProtectConfigurationResolver`,
  含 endpoint / auth / instance_id / kms_key_bindings 校验 +
  SHA-256 configuration hash(含 capability fingerprint,
  R-242 framework 升级新增)
- `client.py` — `IbmKeyProtectSecretClient`,**KMS-only**
  2-SPI 复合(`KeyWrappingBackend` +
  `SecretProviderSession`)。
  **无** `SecretOperations` / `SecretListable` /
  `SecretWriter` / `SecretDeletable`(IBM Key Protect 是
  KMS-only,对位 Java `read()` 抛 `SEC-CAP-001`)
- `factory.py` — `IbmKeyProtectSecretProviderFactory`
  (framework 入口) + 内部
  `IbmKeyProtectClientFactory`(HTTP 适配,import-safe,
  lazy import `ibm-cloud-sdk-core`)

**无官方 Python SDK**:IBM Cloud Key Protect 没有 Python
SDK on PyPI;Python 端用
`ibm-cloud-sdk-core.BearerTokenAuthenticator`(auth)+ 
`httpx.Client`(HTTP)直连 IBM Key Protect REST
`/api/v2/keys/{id}/wrap` 和 `/unwrap`。

`ibm-cloud-sdk-core` 走 `optional-dependency [sdk]`;
无 SDK 时 `IbmKeyProtectClientFactory.create_kms` 抛
`SecretConfigurationException`(`SEC-BOOT-003`)。

English
--------
IBM Cloud Key Protect KMS-only backend wheel. Mirrors
Java `atlas-richie-secret-provider-ibm-key-protect`
(post-SDK-refactor) 1:1. 4 source files. 2-SPI composite
(KeyWrappingBackend + SecretProviderSession). No secret
read / list / write / delete (IBM Key Protect is
KMS-only). **No official Python SDK on PyPI** — uses
`ibm-cloud-sdk-core`'s `BearerTokenAuthenticator` plus
`httpx.Client` against IBM Key Protect REST API.
"""

from atlas_richie.secret_ibm_key_protect.client import (
    IbmKeyProtectSecretClient,
    IbmKeyProtectUnwrapResponse,
    IbmKeyProtectWrapResponse,
    KmsLike,
    WrapOperation,
)
from atlas_richie.secret_ibm_key_protect.configuration import (
    IbmKeyProtectConfigurationResolver,
    ResolvedIbmKeyProtectConfiguration,
)
from atlas_richie.secret_ibm_key_protect.factory import (
    IbmKeyProtectClientFactory,
    IbmKeyProtectSecretProviderFactory,
)
from atlas_richie.secret_ibm_key_protect.properties import (
    AuthType,
    IbmKeyProtectProperties,
)

__all__ = [
    # properties
    "IbmKeyProtectProperties",
    "AuthType",
    # configuration
    "ResolvedIbmKeyProtectConfiguration",
    "IbmKeyProtectConfigurationResolver",
    # SDK construction
    "IbmKeyProtectClientFactory",
    # framework entry
    "IbmKeyProtectSecretProviderFactory",
    # 2-SPI composite
    "IbmKeyProtectSecretClient",
    # Protocol + response dataclasses
    "KmsLike",
    "IbmKeyProtectWrapResponse",
    "IbmKeyProtectUnwrapResponse",
    "WrapOperation",
]
