"""`atlas-richie-secret-aliyun-kms` — Alibaba Cloud Secrets Manager + KMS backend。

中文
----
对位 Java `cn.richie696.component.secret.provider.aliyun.*`(7 个
文件,纯 Aliyun SDK 抽象)。Python 端按 R-232 决定压成单 wheel,内部
子包:

- `client.py` — `AliyunSecretClient`,复合 4 个 SPI 角色
  (`SecretOperations` via Secrets Manager + `KeyWrappingBackend`
  via KMS 对称 Encrypt/Decrypt + `SecretBootstrapClient` +
  `SecretProviderSession`),跑在 `AliyunKmsGateway` Protocol 之上
- `configuration.py` — `AliyunConfigurationResolver`,
  含 endpoint/CA/path-safety 校验 + SHA-256 configuration hash
- `factory.py` — `AliyunSecretProviderFactory`(framework 入口)
  + 内部 `AliyunClientFactory`(懒加载 Aliyun SDK + gateway 适配)
- `properties.py` — `AliyunSecretProperties` +
  `AliyunSecretMapping`(pydantic-settings env 注入,前缀
  `ATLAS_RICHIE_SECRET_ALIYUN_`)

没有 `auth.py` / `request_id.py` / `retry.py` — Aliyun SDK 自带
credential chain / response `RequestId` / autoretry,不需要 framework
层再包一层。

**不**实现:

- `SigningBackend`(Aliyun 对称 KMS 不暴露 sign/verify;Java 同)
- `SecretWriter` / `SecretDeletable` / `SecretListable`

顶层 facade 只暴露 framework 集成点;Aliyun SDK 类型不穿透。

English
--------
Alibaba Cloud backend wheel. Mirrors Java
`atlas-richie-secret-provider-aliyun` 1:1. 4 source files
(client / configuration / factory / properties). No
auth / request_id / retry modules because Alibaba SDK's
default credential chain, response `RequestId`, and
autoretry cover those concerns natively. **Import-safe**:
importing this package does not require the Alibaba SDK to
be installed; the SDK is only loaded inside
`AliyunClientFactory.create_gateway(...)`.
"""

from atlas_richie.secret_aliyun_kms.client import (
    AliyunBootstrapLoadResult,
    AliyunDecryptResponse,
    AliyunEncryptResponse,
    AliyunGetSecretValueResponse,
    AliyunKmsGateway,
    AliyunSecretClient,
    MissingPolicy,
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
    "AliyunSecretMapping",
    "AliyunSecretProperties",
    # configuration
    "ResolvedAliyunConfiguration",
    "AliyunConfigurationResolver",
    # gateway Protocol + responses
    "AliyunKmsGateway",
    "AliyunGetSecretValueResponse",
    "AliyunEncryptResponse",
    "AliyunDecryptResponse",
    # spec types
    "MissingPolicy",
    "AliyunBootstrapLoadResult",
    # SDK construction
    "AliyunClientFactory",
    # framework entry
    "AliyunSecretProviderFactory",
    # 4-SPI composite
    "AliyunSecretClient",
]
