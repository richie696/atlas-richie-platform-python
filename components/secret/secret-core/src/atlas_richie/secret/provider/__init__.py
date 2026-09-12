"""Secret provider SPI 子包:configuration / descriptor / factory / session。

中文
----
对位 Java `cn.richie696.component.secret.api.provider.*` 4 个 class:
`SecretProviderConfiguration` / `SecretProviderDescriptor` /
`SecretProviderFactory` / `SecretProviderSession`。

提供 backend 接入 secret 框架的最小契约。框架层(`DefaultSecretResolver`)
只依赖这里的 Protocol,不 import 任何具体 backend。

English
--------
Secret provider SPI. Re-exports the four provider-related Protocols
and dataclasses; the framework code uses these to talk to backends.
"""

from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import (
    SecretProviderSession,
    ensure_open,
    list_capability,
)

__all__ = [
    "SecretProviderConfiguration",
    "SecretProviderDescriptor",
    "SecretProviderFactory",
    "SecretProviderSession",
    "ensure_open",
    "list_capability",
]
