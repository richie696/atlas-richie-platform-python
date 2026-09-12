"""`atlas-richie-secret-aws-kms` — AWS Secrets Manager + KMS backend。

中文
----
对位 Java `cn.richie696.component.secret.provider.aws.*`(6 个文件)。
1:1 功能对齐,但 Python 端按 R-232 决定压成单 wheel,内部子包:

- `client.py` — `AwsSecretClient`,复合 5 个 SPI 角色
  (`SecretOperations` via SM + `KeyWrappingBackend` + `SigningBackend`
  via KMS + `SecretBootstrapClient` + `SecretProviderSession`),
  跑在两个 boto3 client 上(`kms` + `secretsmanager`)
- `configuration.py` — `AwsConfigurationResolver`,
  含 path safety 校验 + SHA-256 configuration hash
- `factory.py` — `AwsSecretProviderFactory`(framework 入口)
  + 内部 `AwsClientFactory`(boto3 client 构造)
- `properties.py` — `AwsSecretProperties` + `AwsAuthType`
  StrEnum(pydantic-settings env 注入,前缀
  `ATLAS_RICHIE_SECRET_AWS_`)

没有 `auth.py` / `request_id.py` / `retry.py` — boto3 自带
default credential chain / response `RequestId` / standard
retry,不需要 framework 层再包一层。

顶层 facade 只暴露 framework 集成点;boto3 client 类型不穿透。

English
--------
AWS backend wheel. Mirrors Java
`atlas-richie-secret-provider-aws` 1:1. 4 source files
(client / configuration / factory / properties). No
auth / request_id / retry modules because boto3's default
credential chain, response `RequestId`, and standard retry
mode cover those concerns natively.
"""

from atlas_richie.secret_aws_kms.client import AwsSecretClient
from atlas_richie.secret_aws_kms.configuration import (
    AwsConfigurationResolver,
    ResolvedAwsConfiguration,
)
from atlas_richie.secret_aws_kms.factory import (
    AwsClientFactory,
    AwsSecretProviderFactory,
)
from atlas_richie.secret_aws_kms.properties import AwsAuthType, AwsSecretProperties

__all__ = [
    # properties
    "AwsAuthType",
    "AwsSecretProperties",
    # configuration
    "ResolvedAwsConfiguration",
    "AwsConfigurationResolver",
    # SDK construction
    "AwsClientFactory",
    # framework entry
    "AwsSecretProviderFactory",
    # 5-SPI composite
    "AwsSecretClient",
]
