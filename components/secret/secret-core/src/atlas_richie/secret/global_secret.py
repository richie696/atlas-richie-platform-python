"""`GlobalSecret` 进程级静态外观。

中文
----
对位 Java `cn.richie696.component.cache.GlobalCache` 的角色
(`GlobalCache.install` / `GlobalCache.value` / `uninstall` /
`is_initialized` / `active`),在 secret 子系统内重新实现。

`GlobalSecret` 用 classmethod 暴露最小 façade:

- `install(manager)` — 注册一个 `GlobalSecretManager` 作为当前
  provider(委托给 `SecretRegistry.register`)。
- `uninstall()` — 注销当前 manager(全部)。
- `is_initialized()` — 是否已注册至少一个 provider。
- `active()` — 单 provider 模式下返回其 name,否则 `None`。
- `resolve(reference)` — 一行读 secret。
- `write(reference, plaintext)` — 一行写 secret。
- `rotate(reference, plaintext)` — 一行旋转。
- `register_callback(callback)` — 注入 `SecretCallback`(每 provider)。

设计要点(沿用 R-214 决定):

- **不缓存 manager**:每次调用重新解析,避免长生命周期切换悬空。
- **不暴露 SecretRegistry**:注册表是实现细节;外部只通过 facade
  访问;保持公共接口面积小。
- **class-level state**:与 `SecretRegistry` 共享同一进程单例;
  `install` / `uninstall` 影响 `SecretRegistry.instance()`。

English
--------
Process-wide static facade for the secret subsystem. Mirrors the role
of Java's `GlobalCache`. The class exposes the minimal set of
classmethods needed by business code without leaking the registry or
the resolver.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from atlas_richie.secret.callback import SecretCallback
from atlas_richie.secret.errors import SecretException
from atlas_richie.secret.metadata import SecretMetadata
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.reference import SecretReference, SecretVersion
from atlas_richie.secret.registry.secret_registry import SecretRegistry
from atlas_richie.secret.value import DestroyableSecretValue, SecretValue

if TYPE_CHECKING:
    from atlas_richie.secret.global_secret_manager import GlobalSecretManager


class GlobalSecret:
    """Process-wide static facade for secret read / write / rotate."""

    _installed: "GlobalSecretManager | None" = None

    @classmethod
    def install(cls, manager: "GlobalSecretManager") -> None:
        """Register a manager as the active provider.

        The manager owns the resolver + callbacks; the registry
        stores the underlying provider session for `GlobalSecret` to
        look up by name.
        """
        cls._installed = manager
        registry = SecretRegistry.instance()
        for session in manager.sessions:
            registry.register(
                name=session.descriptor.name,
                session=session,
                factory=manager.factory_for(session.descriptor.name),
            )

    @classmethod
    def uninstall(cls) -> None:
        """Unregister every provider. Idempotent."""
        cls._installed = None
        registry = SecretRegistry.instance()
        for name in list(registry.sessions()):
            registry.unregister(name)

    @classmethod
    def is_initialized(cls) -> bool:
        return len(SecretRegistry.instance().sessions()) > 0

    @classmethod
    def active(cls) -> str | None:
        return SecretRegistry.instance().active()

    @classmethod
    def resolve(cls, reference: SecretReference) -> SecretValue:
        return cls._manager().resolver.resolve(reference)

    @classmethod
    def resolve_destroyable(
        cls,
        reference: SecretReference,
    ) -> DestroyableSecretValue:
        return cls._manager().resolver.resolve_destroyable(reference)

    @classmethod
    def resolve_version(
        cls,
        reference: SecretReference,
        version: SecretVersion,
    ) -> SecretValue:
        return cls._manager().resolver.resolve_version(reference, version)

    @classmethod
    def metadata(cls, reference: SecretReference) -> SecretMetadata:
        return cls._manager().resolver.metadata(reference)

    @classmethod
    def write(
        cls,
        reference: SecretReference,
        plaintext: bytes,
    ) -> SecretValue:
        return cls._manager().resolver.write(reference, plaintext)

    @classmethod
    def rotate(
        cls,
        reference: SecretReference,
        new_plaintext: bytes,
    ) -> SecretValue:
        return cls._manager().resolver.rotate(reference, new_plaintext)

    @classmethod
    def register_callback(cls, callback: SecretCallback) -> None:
        """Append a callback to the active manager's resolver.

        Replaces `_installed` with a copy that has the callback
        appended. The `SecretRegistry` is left untouched; the
        installed manager is the source of truth for the callback
        chain.
        """
        manager = cls._manager()
        cls._installed = manager.add_callback(callback)

    # --- Internal helpers ------------------------------------------------

    @classmethod
    def _manager(cls) -> "GlobalSecretManager":
        # Lazy import to avoid a cycle at module load.
        from atlas_richie.secret.global_secret_manager import (
            GlobalSecretManager,
        )

        if cls._installed is not None:
            return cls._installed
        registry = SecretRegistry.instance()
        sessions: list[SecretProviderSession] = list(registry.sessions().values())
        if not sessions:
            raise SecretException(
                "GlobalSecret is not initialized; call install() first",
            )
        # Fall back to a manager built from the registry sessions; this
        # supports the "registered via SecretRegistry but never installed
        # via GlobalSecret" workflow.
        manager = GlobalSecretManager.from_sessions(sessions)
        cls._installed = manager
        return manager


__all__ = ["GlobalSecret"]


_ = (Iterable,)
