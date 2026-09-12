"""`atlas-richie-secret-tencent-ssm-kms` — Tencent Cloud SSM + KMS backend。

中文
----
对位 Java `cn.richie696.component.secret.provider.tencent.*`(SDK
改造后只剩 3 个文件,Python 端按 R-232 决定压成单 wheel,内部子包):

- `properties.py` — `TencentSecretProperties` + `AuthType`
  (pydantic-settings env 注入,前缀 `ATLAS_RICHIE_SECRET_TENCENT_`)
- `configuration.py` — `TencentConfigurationResolver`,含 endpoint /
  auth / secrets / kms_key_bindings 校验 + SHA-256 configuration
  hash(含 capability fingerprint,R-242 framework 升级新增)
- `client.py` — `TencentSecretClient`,复合 3 个 SPI 角色
  (`SecretOperations` via SSM `GetSecretValue` +
  `KeyWrappingBackend` via KMS `Encrypt` / `Decrypt` +
  `SecretBootstrapClient` + `SecretProviderSession`)。
  **无** `SecretWriter` / `SecretDeletable`(read-only)。
- `factory.py` — `TencentSecretProviderFactory`(framework
  入口) + 内部 `TencentClientFactory`(SDK 适配,import-safe)

SDK 通过 `optional-dependency [sdk]` 提供;无 SDK 时
`TencentClientFactory.create_clients` 抛 `SecretConfigurationException`
(`SEC-BOOT-003`)。framework 端**不**看到 SDK 类型,通过
`SsmLike` / `KmsLike` Protocol 抽象。

English
--------
Tencent Cloud SSM + KMS backend wheel. Mirrors Java
`atlas-richie-secret-provider-tencent` (post-SDK-refactor)
1:1. 4 source files. 3-SPI composite (SecretOperations +
KeyWrappingBackend + SecretBootstrapClient +
SecretProviderSession). SDK is opt-in via the `[sdk]`
extra so the wheel is import-safe without it. AAD on
`unwrap_key` is gated by the framework's
`require_aad_support` → `SEC-CAP-001` (Tencent KMS
EncryptionContext does not accept AAD bytes).
"""

from atlas_richie.secret_tencent_ssm_kms.client import (
    KmsLike,
    SsmLike,
    TencentKmsDecryptResponse,
    TencentKmsEncryptResponse,
    TencentSecretClient,
    TencentSsmGetResponse,
)
from atlas_richie.secret_tencent_ssm_kms.configuration import (
    ResolvedTencentConfiguration,
    TencentConfigurationResolver,
)
from atlas_richie.secret_tencent_ssm_kms.factory import (
    TencentClientFactory,
    TencentSecretProviderFactory,
)
from atlas_richie.secret_tencent_ssm_kms.properties import (
    AuthType,
    TencentSecretProperties,
)

__all__ = [
    # properties
    "TencentSecretProperties",
    "AuthType",
    # configuration
    "ResolvedTencentConfiguration",
    "TencentConfigurationResolver",
    # SDK construction
    "TencentClientFactory",
    # framework entry
    "TencentSecretProviderFactory",
    # 3-SPI composite
    "TencentSecretClient",
    # Protocol + response dataclasses
    "SsmLike",
    "KmsLike",
    "TencentSsmGetResponse",
    "TencentKmsEncryptResponse",
    "TencentKmsDecryptResponse",
]
