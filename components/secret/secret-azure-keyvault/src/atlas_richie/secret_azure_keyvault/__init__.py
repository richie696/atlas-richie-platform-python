"""`atlas-richie-secret-azure-keyvault` — Azure Key Vault backend。

中文
----
对位 Java `cn.richie696.component.secret.provider.azure.*`(Java 端
薄 stub,核心实现在 `AbstractRemoteProviderFactory` 公共类)。Python
端按 Azure SDK 实际能力拆开:

- `properties.py` — `AzureSecretProperties` + `AzureKeyWrapAlgorithm`
- `configuration.py` — `AzureConfigurationResolver` + path safety + hash
- `client.py` — `AzureSecretClient`(4-SPI composite,无 sign)
- `factory.py` — `AzureSecretProviderFactory` + 内部 `AzureClientFactory`

Azure SDK client 类型不穿透 facade。

English
--------
Azure Key Vault backend wheel. Mirrors Java
`atlas-richie-secret-provider-azure` 1:1 (narrow 4-SPI scope).
No `auth.py` / `request_id.py` / `retry.py` because Azure SDK
handles credential chain / `RequestId` / retries natively.
"""

from atlas_richie.secret_azure_keyvault.client import AzureSecretClient
from atlas_richie.secret_azure_keyvault.configuration import (
    AzureConfigurationResolver,
    ResolvedAzureConfiguration,
)
from atlas_richie.secret_azure_keyvault.factory import (
    AzureClientFactory,
    AzureSecretProviderFactory,
)
from atlas_richie.secret_azure_keyvault.properties import (
    AzureKeyWrapAlgorithm,
    AzureSecretProperties,
)

__all__ = [
    # properties
    "AzureKeyWrapAlgorithm",
    "AzureSecretProperties",
    # configuration
    "ResolvedAzureConfiguration",
    "AzureConfigurationResolver",
    # SDK construction
    "AzureClientFactory",
    # framework entry
    "AzureSecretProviderFactory",
    # 4-SPI composite
    "AzureSecretClient",
]
