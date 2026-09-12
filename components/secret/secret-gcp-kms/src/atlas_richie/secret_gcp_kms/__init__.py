"""`atlas-richie-secret-gcp-kms` — Google Cloud Secret Manager + KMS backend.

中文
----
对位 Java `cn.richie696.component.secret.provider.gcp.*`(Java 端薄 stub,
核心实现在 `AbstractRemoteProviderFactory` 公共类)。Python 端按 GCP
SDK 实际能力拆开,4 个源文件,4-SPI 窄范围(对位 Java capability
声明:SECRET_READ / SECRET_VERSIONING / KEY_WRAP / KEY_UNWRAP)。

English
--------
GCP Secret Manager + KMS backend wheel. Mirrors Java
`atlas-richie-secret-provider-gcp` 1:1 (narrow 4-SPI scope).
No `auth.py` / `request_id.py` / `retry.py` because Google
Cloud SDK handles auth chain / metadata headers / retries
natively.
"""

from atlas_richie.secret_gcp_kms.client import GcpSecretClient
from atlas_richie.secret_gcp_kms.configuration import (
    GcpConfigurationResolver,
    ResolvedGcpConfiguration,
)
from atlas_richie.secret_gcp_kms.factory import (
    GcpClientFactory,
    GcpSecretProviderFactory,
)
from atlas_richie.secret_gcp_kms.properties import (
    GcpKmsAlgorithm,
    GcpSecretProperties,
)

__all__ = [
    # properties
    "GcpKmsAlgorithm",
    "GcpSecretProperties",
    # configuration
    "ResolvedGcpConfiguration",
    "GcpConfigurationResolver",
    # SDK construction
    "GcpClientFactory",
    # framework entry
    "GcpSecretProviderFactory",
    # 4-SPI composite
    "GcpSecretClient",
]
