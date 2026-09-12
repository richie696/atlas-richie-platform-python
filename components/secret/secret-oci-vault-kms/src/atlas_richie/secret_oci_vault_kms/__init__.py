"""`atlas-richie-secret-oci-vault-kms` — Oracle Cloud Infrastructure (OCI) Vault + KMS backend。

中文
----
对位 Java `cn.richie696.component.secret.provider.oci.*`(SDK 改造
后 2 个文件),Python 端按 R-232 决定压成单 wheel,内部子包:

- `properties.py` — `OciSecretProperties` + `AuthType`
  (pydantic-settings env 注入,前缀
  `ATLAS_RICHIE_SECRET_OCI_`)
- `configuration.py` — `OciConfigurationResolver`,含
  endpoint / auth / secrets / kms_key_bindings 校验 +
  SHA-256 configuration hash(含 capability fingerprint,
  R-242 framework 升级新增)
- `client.py` — `OciSecretClient`,**3-SPI 复合**
  (`SecretOperations` via Vault `getSecretBundle` +
  `KeyWrappingBackend` via KMS `encrypt` / `decrypt` +
  `SecretBootstrapClient` + `SecretProviderSession`)
- `factory.py` — `OciSecretProviderFactory`(framework
  入口) + 内部 `OciClientFactory`(SDK 适配,import-safe)

SDK 通过 `optional-dependency [sdk]` 提供;无 SDK 时
`OciClientFactory.create` 抛 `SecretConfigurationException`
(`SEC-BOOT-003`)。

English
--------
OCI Vault + KMS backend wheel. Mirrors Java
`atlas-richie-secret-provider-oci` (post-SDK-refactor)
1:1. 4 source files. 3-SPI composite (SecretOperations via
Vault + KeyWrappingBackend via KMS + SecretBootstrapClient
+ SecretProviderSession). SDK is opt-in via the `[sdk]`
extra so the wheel is import-safe without it.
"""

from atlas_richie.secret_oci_vault_kms.client import (
    KmsLike,
    OciKmsDecryptResponse,
    OciKmsEncryptResponse,
    OciSecretClient,
    OciVaultSecret,
    VaultLike,
)
from atlas_richie.secret_oci_vault_kms.configuration import (
    OciConfigurationResolver,
    ResolvedOciConfiguration,
)
from atlas_richie.secret_oci_vault_kms.factory import (
    OciClientFactory,
    OciSecretProviderFactory,
)
from atlas_richie.secret_oci_vault_kms.properties import (
    AuthType,
    OciSecretProperties,
)

__all__ = [
    # properties
    "OciSecretProperties",
    "AuthType",
    # configuration
    "ResolvedOciConfiguration",
    "OciConfigurationResolver",
    # SDK construction
    "OciClientFactory",
    # framework entry
    "OciSecretProviderFactory",
    # 3-SPI composite
    "OciSecretClient",
    # Protocol + response dataclasses
    "VaultLike",
    "KmsLike",
    "OciVaultSecret",
    "OciKmsEncryptResponse",
    "OciKmsDecryptResponse",
]
