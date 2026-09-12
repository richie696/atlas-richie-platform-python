"""`atlas-richie-secret-volcengine-kms` — 火山引擎 KMS-only backend。

中文
----
对位 Java `cn.richie696.component.secret.provider.volcengine.*`(SDK
改造后 3 个文件),Python 端按 R-232 决定压成单 wheel,内部子包:

- `properties.py` — `VolcengineSecretProperties` + `AuthType`
  (pydantic-settings env 注入,前缀
  `ATLAS_RICHIE_SECRET_VOLCENGINE_`)
- `configuration.py` — `VolcengineConfigurationResolver`,含
  endpoint / auth / namespace / kms_key_bindings 校验 +
  SHA-256 configuration hash(含 capability fingerprint,
  R-242 framework 升级新增)
- `client.py` — `VolcengineSecretClient`,**KMS-only** 2-SPI
  复合(`KeyWrappingBackend` + `SecretProviderSession`)。
  **无** `SecretOperations` / `SecretListable` /
  `SecretWriter` / `SecretDeletable`(Volcengine 是 KMS-only,
  对位 Java `read()` 直接抛 `SEC-CAP-001`)
- `factory.py` — `VolcengineSecretProviderFactory`(framework
  入口) + 内部 `VolcengineClientFactory`(SDK 适配,import-safe)

SDK 通过 `optional-dependency [sdk]` 提供;无 SDK 时
`VolcengineClientFactory.create_kms` 抛
`SecretConfigurationException`(`SEC-BOOT-003`)。

English
--------
Volcengine KMS-only backend wheel. Mirrors Java
`atlas-richie-secret-provider-volcengine` (post-SDK-refactor)
1:1. 4 source files. 2-SPI composite (KeyWrappingBackend +
SecretProviderSession). No secret read / list / write /
delete (Volcengine is KMS-only). SDK is opt-in via the
`[sdk]` extra so the wheel is import-safe without it.
"""

from atlas_richie.secret_volcengine_kms.client import (
    KmsLike,
    VolcengineKmsDecryptResponse,
    VolcengineKmsEncryptResponse,
    VolcengineSecretClient,
)
from atlas_richie.secret_volcengine_kms.configuration import (
    ResolvedVolcengineConfiguration,
    VolcengineConfigurationResolver,
)
from atlas_richie.secret_volcengine_kms.factory import (
    VolcengineClientFactory,
    VolcengineSecretProviderFactory,
)
from atlas_richie.secret_volcengine_kms.properties import (
    AuthType,
    VolcengineSecretProperties,
)

__all__ = [
    # properties
    "VolcengineSecretProperties",
    "AuthType",
    # configuration
    "ResolvedVolcengineConfiguration",
    "VolcengineConfigurationResolver",
    # SDK construction
    "VolcengineClientFactory",
    # framework entry
    "VolcengineSecretProviderFactory",
    # 2-SPI composite
    "VolcengineSecretClient",
    # Protocol + response dataclasses
    "KmsLike",
    "VolcengineKmsEncryptResponse",
    "VolcengineKmsDecryptResponse",
]
