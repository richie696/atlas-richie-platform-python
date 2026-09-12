"""Secret registry — 一进程一 provider 互斥 + 全局 catalog 容器。

中文
----
对位 Java `cn.richie696.component.cache.registry.CacheRegistry` 的角色,
但对 secret 子系统重新实现(不放进 cache 的 registry,以免组件耦合)。

`SecretRegistry` 提供:

- `register(name, session, factory=None)` — 注册一个 provider session。
  同一 provider `name` 已存在抛 `SecretException`(避免静默覆盖)。
- `unregister(name)` — 注销并 `session.close()`。
- `session(name)` — 取 session,缺则抛 `SecretException`。
- `active()` — 当前活跃的 provider 名(单 provider 模式),或
  `None`(多 provider 模式)。
- `install_catalog(catalog)` / `catalogs()` — 启动期 binding 容器。
- `shared_snapshot_manager()` — 跨 session 共享的 listener 注册表;
  rotation 事件统一发到这一个 manager,避免多个 snapshot_manager 失配。

设计要点(沿用 R-214 / R-218 决定):

- **不缓存 manager**:每次 `active()` 重新解析,避免长生命周期切换
  时的悬空引用。
- **互斥**:`register` 时若已有同名 provider 抛错;不静默覆盖。
- **进程级**:class-level state,框架不引入 DI 容器。

English
--------
Secret registry: process-wide mutex over active provider sessions,
plus the global `SecretBindingCatalog` container. Mirrors the role
of Java's `CacheRegistry` but lives inside the secret component
(no cross-component coupling).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Mapping

from atlas_richie.secret.bootstrap.catalog import SecretBindingCatalog
from atlas_richie.secret.errors import SecretException
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.snapshot import SecretSnapshotManager


class SecretRegistry:
    """Process-wide registry of active secret providers and catalogs."""

    _instance: "SecretRegistry | None" = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._sessions: dict[str, SecretProviderSession] = {}
        self._factories: dict[str, SecretProviderFactory] = {}
        self._catalogs: list[SecretBindingCatalog] = []
        self._shared_snapshot = SecretSnapshotManager()
        self._lock = threading.Lock()
        self._logger = logging.getLogger("atlas_richie.secret.registry")

    @classmethod
    def instance(cls) -> "SecretRegistry":
        """Return the process-wide singleton. Created on first call.

        The pattern follows R-214: double-checked locking + class-level
        field. Tests should call `reset()` to clear state.
        """
        if cls._instance is not None:
            return cls._instance
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the singleton. Used by tests."""
        with cls._instance_lock:
            if cls._instance is not None:
                for session in cls._instance._sessions.values():
                    try:
                        session.close()
                    except Exception:  # noqa: BLE001
                        pass
            cls._instance = None

    def register(
        self,
        name: str,
        session: SecretProviderSession,
        *,
        factory: SecretProviderFactory | None = None,
    ) -> None:
        """Register a session. Duplicate name raises `SecretException`."""
        with self._lock:
            if name in self._sessions:
                raise SecretException(
                    f"secret provider {name!r} already registered; "
                    "call unregister() first to switch backends",
                )
            self._sessions[name] = session
            if factory is not None:
                self._factories[name] = factory
            self._logger.info("registered secret provider %r", name)

    def unregister(self, name: str) -> None:
        """Close and remove the named session. ``None`` is a no-op."""
        with self._lock:
            session = self._sessions.pop(name, None)
            self._factories.pop(name, None)
        if session is not None:
            try:
                session.close()
            except Exception:  # noqa: BLE001
                self._logger.exception(
                    "error closing secret provider %r during unregister",
                    name,
                )
            self._logger.info("unregistered secret provider %r", name)

    def session(self, name: str) -> SecretProviderSession:
        try:
            return self._sessions[name]
        except KeyError as error:
            raise SecretException(
                f"no secret provider registered as {name!r}",
            ) from error

    def sessions(self) -> Mapping[str, SecretProviderSession]:
        with self._lock:
            return dict(self._sessions)

    def factory(self, name: str) -> SecretProviderFactory | None:
        return self._factories.get(name)

    def shared_snapshot_manager(self) -> SecretSnapshotManager:
        """Return the process-wide snapshot manager used by
        `DefaultSecretResolver` to fan out rotation events.
        """
        return self._shared_snapshot

    # --- Catalogs ---------------------------------------------------------

    def install_catalog(self, catalog: SecretBindingCatalog) -> None:
        """Add a binding catalog. Idempotent on name."""
        with self._lock:
            for index, existing in enumerate(self._catalogs):
                if existing.name == catalog.name:
                    self._catalogs[index] = catalog
                    return
            self._catalogs.append(catalog)

    def uninstall_catalog(self, name: str) -> None:
        with self._lock:
            self._catalogs = [c for c in self._catalogs if c.name != name]

    def catalogs(self) -> Iterable[SecretBindingCatalog]:
        with self._lock:
            return tuple(self._catalogs)

    def active(self) -> str | None:
        """Return the single active provider name, or ``None`` if
        the registry holds zero / multiple providers.
        """
        with self._lock:
            count = len(self._sessions)
            if count != 1:
                return None
            return next(iter(self._sessions))


__all__ = ["SecretRegistry"]
