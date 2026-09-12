"""`atlas-richie-secret-baidu-kms` — 百度智能云 KMS-only backend。

中文
----
对位 Java
`cn.richie696.component.secret.provider.baidu.*`(SDK 改造
后 3 个文件),Python 端按 R-232 决定压成单 wheel,内部子包:

- `properties.py` — `BaiduSecretProperties` + `AuthType`
  (pydantic-settings env 注入,前缀
  `ATLAS_RICHIE_SECRET_BAIDU_`)
- `configuration.py` — `BaiduConfigurationResolver`,含
  endpoint / auth / kms_key_bindings 校验 + SHA-256
  configuration hash(含 capability fingerprint,R-242
  framework 升级新增)
- `client.py` — `BaiduSecretClient`,**KMS-only** 2-SPI
  复合(`KeyWrappingBackend` + `SecretProviderSession`)。
  **无** `SecretOperations` / `SecretListable` /
  `SecretWriter` / `SecretDeletable`(Baidu KMS 是
  KMS-only,对位 Java `read()` 抛 `SEC-CAP-001`)
- `factory.py` — `BaiduSecretProviderFactory`(framework
  入口) + 内部 `BaiduClientFactory`(SDK 适配,import-safe)

SDK 通过 `optional-dependency [sdk]` 提供;无 SDK 时
`BaiduClientFactory.create_kms` 抛
`SecretConfigurationException`(`SEC-BOOT-003`)。

English
--------
Baidu Cloud KMS-only backend wheel. Mirrors Java
`atlas-richie-secret-provider-baidu` (post-SDK-refactor)
1:1. 4 source files. 2-SPI composite
(KeyWrappingBackend + SecretProviderSession). No secret
read / list / write / delete (Baidu KMS is KMS-only).
SDK is opt-in via the `[sdk]` extra so the wheel is
import-safe without it.
"""

from atlas_richie.secret_baidu_kms.client import (
    BaiduKmsDecryptResponse,
    BaiduKmsEncryptResponse,
    BaiduSecretClient,
    KmsLike,
)
from atlas_richie.secret_baidu_kms.configuration import (
    BaiduConfigurationResolver,
    ResolvedBaiduConfiguration,
)
from atlas_richie.secret_baidu_kms.factory import (
    BaiduClientFactory,
    BaiduSecretProviderFactory,
)
from atlas_richie.secret_baidu_kms.properties import (
    AuthType,
    BaiduSecretProperties,
)

__all__ = [
    # properties
    "BaiduSecretProperties",
    "AuthType",
    # configuration
    "ResolvedBaiduConfiguration",
    "BaiduConfigurationResolver",
    # SDK construction
    "BaiduClientFactory",
    # framework entry
    "BaiduSecretProviderFactory",
    # 2-SPI composite
    "BaiduSecretClient",
    # Protocol + response dataclasses
    "KmsLike",
    "BaiduKmsEncryptResponse",
    "BaiduKmsDecryptResponse",
]
