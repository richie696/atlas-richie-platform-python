"""`atlas-richie-secret-huawei-csms-kms` — 华为云 CSMS + DEW KMS backend。

中文
----
对位 Java `cn.richie696.component.secret.provider.huawei.*`(SDK
改造后 3 个文件,Python 端按 R-232 决定压成单 wheel,内部子包):

- `properties.py` — `HuaweiSecretProperties` + `AuthType`
  (pydantic-settings env 注入,前缀
  `ATLAS_RICHIE_SECRET_HUAWEI_`);Huawei DEW BasicCredentials
  强制 ACCESS_KEY + `project_id` 必填
- `configuration.py` — `HuaweiConfigurationResolver`,含
  endpoint / auth / project_id / secrets / kms_key_bindings
  校验 + SHA-256 configuration hash(含 capability fingerprint,
  R-242 framework 升级新增)
- `client.py` — `HuaweiSecretClient`,复合 3 个 SPI 角色
  (`SecretOperations` via CSMS `ShowSecretVersion` +
  `KeyWrappingBackend` via DEW `EncryptData` / `DecryptData` +
  `SecretBootstrapClient` + `SecretProviderSession`)。
  **无** `SecretWriter` / `SecretDeletable`(read-only)
- `factory.py` — `HuaweiSecretProviderFactory`(framework
  入口) + 内部 `HuaweiClientFactory`(SDK 适配,import-safe)

SDK 通过 `optional-dependency [sdk]` 提供(`huaweicloud-sdk-python`);
无 SDK 时 `HuaweiClientFactory.create_clients` 抛
`SecretConfigurationException`(`SEC-BOOT-003`)。framework
端**不**看到 SDK 类型,通过 `CsmsLike` / `KmsLike` Protocol
抽象。

English
--------
Huawei Cloud CSMS + DEW KMS backend wheel. Mirrors
Java `atlas-richie-secret-provider-huawei` (post-SDK-refactor)
1:1. 4 source files. 3-SPI composite (SecretOperations +
KeyWrappingBackend + SecretBootstrapClient +
SecretProviderSession). SDK is opt-in via the `[sdk]`
extra so the wheel is import-safe without it. AAD on
`unwrap_key` is encoded into Huawei DEW
`additionalAuthenticatedData` (Base64-encoded).
"""

from atlas_richie.secret_huawei_csms_kms.client import (
    CsmsLike,
    HuaweiCsmsGetResponse,
    HuaweiKmsDecryptResponse,
    HuaweiKmsEncryptResponse,
    HuaweiSecretClient,
    KmsLike,
)
from atlas_richie.secret_huawei_csms_kms.configuration import (
    HuaweiConfigurationResolver,
    ResolvedHuaweiConfiguration,
)
from atlas_richie.secret_huawei_csms_kms.factory import (
    HuaweiClientFactory,
    HuaweiSecretProviderFactory,
)
from atlas_richie.secret_huawei_csms_kms.properties import (
    AuthType,
    HuaweiSecretProperties,
)

__all__ = [
    # properties
    "HuaweiSecretProperties",
    "AuthType",
    # configuration
    "ResolvedHuaweiConfiguration",
    "HuaweiConfigurationResolver",
    # SDK construction
    "HuaweiClientFactory",
    # framework entry
    "HuaweiSecretProviderFactory",
    # 3-SPI composite
    "HuaweiSecretClient",
    # Protocol + response dataclasses
    "CsmsLike",
    "KmsLike",
    "HuaweiCsmsGetResponse",
    "HuaweiKmsEncryptResponse",
    "HuaweiKmsDecryptResponse",
]
