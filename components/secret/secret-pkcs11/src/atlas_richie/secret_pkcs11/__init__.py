"""`atlas-richie-secret-pkcs11` — PKCS#11 / HSM backend.

中文
----
对位 Java `cn.richie696.component.secret.provider.pkcs11.*`(5 个文件,
纯 HSM 抽象)。Python 端按 `python-pkcs11` 实际能力拆开 4 个源文件,
实现 4 个 SPI 角色(无 `SecretOperations`,HSM 不存 secret):

- `client.py` — `Pkcs11SecretClient`(`KeyWrappingBackend` +
  `SigningBackend` + `SecretBootstrapClient` +
  `SecretProviderSession`)
- `configuration.py` — `Pkcs11ConfigurationResolver` + SHA-256 hash
- `factory.py` — `Pkcs11SecretProviderFactory` +
  内部 `Pkcs11ClientFactory`
- `properties.py` — `Pkcs11SecretProperties` +
  `Pkcs11SignMechanism`

English
--------
PKCS#11 / HSM backend wheel. Mirrors Java
`atlas-richie-secret-provider-pkcs11` 1:1 (4-SPI narrow scope).
"""

from atlas_richie.secret_pkcs11.client import Pkcs11SecretClient
from atlas_richie.secret_pkcs11.configuration import (
    Pkcs11ConfigurationResolver,
    ResolvedPkcs11Configuration,
)
from atlas_richie.secret_pkcs11.factory import (
    Pkcs11ClientFactory,
    Pkcs11SecretProviderFactory,
)
from atlas_richie.secret_pkcs11.properties import (
    Pkcs11SecretProperties,
    Pkcs11SignMechanism,
)

__all__ = [
    # properties
    "Pkcs11SignMechanism",
    "Pkcs11SecretProperties",
    # configuration
    "ResolvedPkcs11Configuration",
    "Pkcs11ConfigurationResolver",
    # SDK construction
    "Pkcs11ClientFactory",
    # framework entry
    "Pkcs11SecretProviderFactory",
    # 4-SPI composite
    "Pkcs11SecretClient",
]
