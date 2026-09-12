"""Secret 启动期注入子包:catalog / spi / policy / state / discovery / processor / default_client。

中文
----
对位 Java `cn.richie696.component.secret.bootstrap` 全部 23 个文件
(processor + SPI + catalog + state + discovery + policy / properties
+ default client)。

- `catalog` — 9 个 class:`SecretKind` / `SecretExposure` / `RequiredWhen` /
  `SecretRefreshStrategy` / `SecretPropertyPattern` / `SecretBinding` /
  `SecretBindingCatalog` / `SecretBindingCatalogSet` /
  `SecretBindingCatalogLoader`
- `spi` — 6 个 class:`SecretProviderType` / `SecretBootstrapRequest` /
  `SecretBootstrapResult` / `SecretBootstrapContext` /
  `SecretBootstrapClient` / `SecretBootstrapProviderFactory` +
  `DefaultBootstrapContext`
- `policy` — 2 个 dataclass:`SecretPropertyPolicy` /
  `BootstrapSecretProperties`
- `state` — 3 个:`SecretBootstrapState` / `SecretProviderTopology` /
  `SecretBootstrapSnapshot`
- `discovery` — `SecretProviderDiscovery` / `DiscoveryResult`
- `processor` — `AtlasSecretEnvironmentPostProcessor`(应用入口)
- `default_client` — `ResolverBackedBootstrapClient`(`SecretResolver`
  委托的默认 client)

English
--------
Secret bootstrap sub-package. Re-exports the full Java bootstrap
surface (processor / SPI / catalog / state / discovery / policy).
"""

from atlas_richie.secret.bootstrap.catalog import (
    RequiredWhen,
    SecretBinding,
    SecretBindingCatalog,
    SecretBindingCatalogLoader,
    SecretBindingCatalogSet,
    SecretExposure,
    SecretKind,
    SecretPropertyPattern,
    SecretRefreshStrategy,
)
from atlas_richie.secret.bootstrap.default_client import ResolverBackedBootstrapClient
from atlas_richie.secret.bootstrap.discovery import DiscoveryResult, SecretProviderDiscovery
from atlas_richie.secret.bootstrap.policy import (
    BootstrapSecretProperties,
    SecretPropertyPolicy,
)
from atlas_richie.secret.bootstrap.processor import AtlasSecretEnvironmentPostProcessor
from atlas_richie.secret.bootstrap.spi import (
    DefaultBootstrapContext,
    SecretBootstrapClient,
    SecretBootstrapContext,
    SecretBootstrapProviderFactory,
    SecretBootstrapRequest,
    SecretBootstrapResult,
    SecretProviderType,
)
from atlas_richie.secret.bootstrap.state import (
    SecretBootstrapSnapshot,
    SecretBootstrapState,
    SecretProviderTopology,
)

__all__ = [
    "SecretKind",
    "SecretExposure",
    "RequiredWhen",
    "SecretRefreshStrategy",
    "SecretPropertyPattern",
    "SecretBinding",
    "SecretBindingCatalog",
    "SecretBindingCatalogSet",
    "SecretBindingCatalogLoader",
    "SecretProviderType",
    "SecretBootstrapRequest",
    "SecretBootstrapResult",
    "SecretBootstrapContext",
    "DefaultBootstrapContext",
    "SecretBootstrapClient",
    "SecretBootstrapProviderFactory",
    "SecretPropertyPolicy",
    "BootstrapSecretProperties",
    "SecretBootstrapState",
    "SecretProviderTopology",
    "SecretBootstrapSnapshot",
    "SecretProviderDiscovery",
    "DiscoveryResult",
    "AtlasSecretEnvironmentPostProcessor",
    "ResolverBackedBootstrapClient",
]
