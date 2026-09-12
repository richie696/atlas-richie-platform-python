"""`GlobalSecretManager` — 每实例 manager,持有多个 provider session。

中文
----
对位 cache 端 `GlobalCacheManager`(持有 `ProviderRegistrar`),secret
端重新实现为 `GlobalSecretManager` — 持有 `SecretProviderSession`
列表 + callback 链 + 共享 snapshot manager。

生命周期:

- `GlobalSecretManager(sessions, factory_for=...)`:构造时显式
  注入 session 列表,每个 session 视为一个独立 provider(支持多
  provider 同时激活,按 `reference.provider` 路由)。
- `from_sessions(sessions)`:便捷构造。
- `add_callback(callback)`:追加 `SecretCallback`,每次 resolve
  都会触发(best-effort,失败 log 不抛)。
- `resolver`:返回绑定的 `DefaultSecretResolver`(线程安全)。
- `factory_for(name)`:返回该 provider 的 `SecretProviderFactory`
  (用于 framework 在 close 时反向 uninstall)。

设计:

- **不持有写锁**:session 的 close 由 `SecretRegistry.unregister` 触发
  ,manager 自身不主动关。
- **多 provider**:`sessions` 列表支持任意长度,路由由
  `DefaultSecretResolver` 按 `reference.provider` 字段做。

English
--------
Per-instance manager for `GlobalSecret`. Mirrors the role of Java's
`GlobalCacheManager`. Holds a list of `SecretProviderSession`s and
the callback chain.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from atlas_richie.secret.callback import SecretCallback
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.resolver import DefaultSecretResolver
from atlas_richie.secret.snapshot import SecretSnapshotManager


@runtime_checkable
class _FactoryLookup(Protocol):
    def factory_for(self, name: str) -> SecretProviderFactory | None: ...


@dataclass(slots=True)
class GlobalSecretManager:
    """Wraps a set of `SecretProviderSession`s and exposes a
    multi-provider `DefaultSecretResolver`.
    """

    sessions: tuple[SecretProviderSession, ...]
    callbacks: tuple[SecretCallback, ...] = field(default_factory=tuple)
    snapshot_manager: SecretSnapshotManager = field(
        default_factory=SecretSnapshotManager,
    )
    _factories: Mapping[str, SecretProviderFactory] = field(default_factory=dict)
    _resolver: DefaultSecretResolver | None = field(default=None, init=False)

    @classmethod
    def from_sessions(
        cls,
        sessions: Iterable[SecretProviderSession],
        *,
        factories: Mapping[str, SecretProviderFactory] | None = None,
        callbacks: Iterable[SecretCallback] = (),
        snapshot_manager: SecretSnapshotManager | None = None,
    ) -> "GlobalSecretManager":
        sessions_tuple = tuple(sessions)
        manager = cls(
            sessions=sessions_tuple,
            callbacks=tuple(callbacks),
            snapshot_manager=snapshot_manager or SecretSnapshotManager(),
            _factories=dict(factories or {}),
        )
        manager._resolver = DefaultSecretResolver(
            providers={session.descriptor.name: session for session in sessions_tuple},
            callbacks=tuple(callbacks),
            snapshot_manager=manager.snapshot_manager,
        )
        return manager

    def factory_for(self, name: str) -> SecretProviderFactory | None:
        return self._factories.get(name)

    def add_callback(self, callback: SecretCallback) -> "GlobalSecretManager":
        """Return a new manager with `callback` appended to the chain."""
        new_callbacks = self.callbacks + (callback,)
        new_resolver = DefaultSecretResolver(
            providers={session.descriptor.name: session for session in self.sessions},
            callbacks=new_callbacks,
            snapshot_manager=self.snapshot_manager,
        )
        new_manager = GlobalSecretManager(
            sessions=self.sessions,
            callbacks=new_callbacks,
            snapshot_manager=self.snapshot_manager,
            _factories=self._factories,
        )
        new_manager._resolver = new_resolver
        return new_manager

    @property
    def resolver(self) -> DefaultSecretResolver:
        if self._resolver is None:
            self._resolver = DefaultSecretResolver(
                providers={
                    session.descriptor.name: session for session in self.sessions
                },
                callbacks=self.callbacks,
                snapshot_manager=self.snapshot_manager,
            )
        return self._resolver


__all__ = ["GlobalSecretManager"]


_ = (_FactoryLookup,)
