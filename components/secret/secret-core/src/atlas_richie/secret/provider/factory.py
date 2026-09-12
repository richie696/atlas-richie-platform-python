"""Secret provider factory SPI — backend 的入口。

中文
----
对位 Java `cn.richie696.component.secret.api.provider.SecretProviderFactory` /
`cn.richie696.component.secret.api.provider.SecretProviderSession`。

`SecretProviderFactory` Protocol 是 backend 包(redis / vault / openbao /
pkcs11 / aws / azure / ...)接入 secret 框架的唯一入口。框架从不
import 任何后端实现;后端实现方提供 factory,facade 在 `install()` 时
构造 session。

每个 backend 实现一个 `SecretProviderFactory` 子类,提供:

- `name`: backend 自己的名字(用于 `SecretProviderDescriptor.name`)。
- `backend`: 物理后端类型(`SecretBackend.VAULT` / `REDIS` / ...)。
- `capability`: 该 backend 静态能力声明。
- `create(configuration) -> SecretProviderSession`: 构造并 connect。
- `close_session(session)`: 释放 session(可在 framework 自动调
  `session.close()` 时省略)。

framework 端用 `SecretProviderFactory` Protocol 与 backend 解耦:
facade 只看到 Protocol,不 import 任何具体 backend。

English
--------
Secret provider factory SPI. Mirrors the Java
`SecretProviderFactory`. The Protocol is the single integration point
between the secret framework and a backend implementation; the
framework never imports a concrete backend.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.session import SecretProviderSession


@runtime_checkable
class SecretProviderFactory(Protocol):
    """Backend-implemented factory that produces `SecretProviderSession`s.

    The framework calls `create(configuration)` once per `install(...)`
    and stores the returned session in `SecretRegistry`. The factory
    MAY close the session itself, but the framework also calls
    `session.close()` on `uninstall` to be safe.
    """

    @property
    def name(self) -> str:
        """Stable identifier for this backend (e.g. ``"redis-1"``,
        ``"vault-main"``).
        """
        ...

    @property
    def backend(self) -> SecretBackend:
        """Physical backend family."""
        ...

    @property
    def capability(self) -> SecretCapability:
        """Static capability of this backend. Must NOT change between
        sessions; runtime changes belong in the session state, not
        the descriptor.
        """
        ...

    @property
    def version(self) -> str:
        """Backend-specific version string for diagnostics."""
        ...

    def descriptor(self) -> SecretProviderDescriptor:
        """Convenience accessor returning a fresh descriptor instance."""
        ...

    def create(
        self,
        configuration: SecretProviderConfiguration,
    ) -> SecretProviderSession:
        """Open a new session. Must validate the configuration and
        raise `SecretConfigurationException` on bad input.
        """
        ...


__all__ = [
    "SecretProviderFactory",
]
