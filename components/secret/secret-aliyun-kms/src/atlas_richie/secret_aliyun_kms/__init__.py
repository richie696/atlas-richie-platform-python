"""`atlas-richie-secret-aliyun-kms` — Alibaba Cloud KMS + Secrets Manager backend。

中文
----
对位 Java `cn.richie696.component.secret.provider.aliyun.*`(7 个文件)。
1:1 功能对齐,但 Python 端按 R-232 决定压成单 wheel,内部子包:

- `client.py` — `AliyunSecretClient`,复合 4 个 SPI 角色
  (`SecretOperations` via SM + `KeyWrappingBackend` via KMS +
  `SecretBootstrapClient` + `SecretProviderSession`),无
  `SigningBackend`(Aliyun KMS 对称加密只支持 wrap)
- `configuration.py` — `AliyunConfigurationResolver`,含 endpoint
  / path / binding / mapping 校验 + SHA-256 configuration hash
- `factory.py` — `AliyunSecretProviderFactory`(framework 入口)
  + 内部 `AliyunClientFactory`(`alibabacloud_kms20160120` 构造)
- `properties.py` — `AliyunSecretProperties` + `AliyunSecretMapping`
  (pydantic-settings env 注入,前缀 `ATLAS_RICHIE_SECRET_ALIYUN_`)

SDK 通过 `optional-dependency [kms]` 提供;无 SDK 时
`AliyunClientFactory.create_gateway` 抛 `SecretConfigurationException`。
framework 端**不**看到 SDK 类型。

English
--------
Aliyun backend wheel. Mirrors Java
`atlas-richie-secret-provider-aliyun` 1:1. 4 source files
(client / configuration / factory / properties). The Alibaba
SDK is opt-in via the `[kms]` extra so the wheel is
import-safe without it.
"""

from atlas_richie.secret_aliyun_kms.client import (
    AliyunDecryptResponse,
    AliyunEncryptResponse,
    AliyunGetSecretValueResponse,
    AliyunKmsGateway,
    AliyunSecretClient,
)
from atlas_richie.secret_aliyun_kms.configuration import (
    AliyunConfigurationResolver,
    ResolvedAliyunConfiguration,
)
from atlas_richie.secret_aliyun_kms.factory import (
    AliyunClientFactory,
    AliyunSecretProviderFactory,
)
from atlas_richie.secret_aliyun_kms.properties import (
    AliyunSecretMapping,
    AliyunSecretProperties,
)

__all__ = [
    # properties
    "AliyunSecretProperties",
    "AliyunSecretMapping",
    # configuration
    "ResolvedAliyunConfiguration",
    "AliyunConfigurationResolver",
    # SDK construction
    "AliyunClientFactory",
    # framework entry
    "AliyunSecretProviderFactory",
    # 4-SPI composite
    "AliyunSecretClient",
    # Gateway Protocol + response dataclasses
    "AliyunKmsGateway",
    "AliyunGetSecretValueResponse",
    "AliyunEncryptResponse",
    "AliyunDecryptResponse",
]
