"""进程级缓存 provider 注册表（强制互斥）。
----
`CacheRegistry` 是框架的"一进程一 provider"门禁：后端在启动期注册自己，
静态外观 `GlobalCache` 从这里读取。已激活 provider 时再注册第二个会抛
`StateError`，调用方必须先 `unregister()` 才能切换后端。这是有意为之：
静默覆盖活跃 provider 会让一个组件在另一个组件不知情的情况下释放其
Redis 客户端。

线程安全：一个类级别 `Lock` 同时保护 `_registrar` 的读和写。读
（`active()` / `is_registered()`）也拿锁，因此切换中途不会被观察到。
锁仅覆盖赋值/查找过程，不覆盖用户级操作；最大延迟是 Lock acquire +
属性写。

为什么用 classmethod（而不是 instance + Holder 模式）：注册表本身就是
进程级状态，实例化它没有意义。静态类是这种语义最诚实的表达。

诊断：`active_provider()` 返回活跃 provider 的枚举（未初始化时为
`None`），供日志和健康检查使用。

English
--------
Process-wide cache provider registry (mutual-exclusion enforced).

`CacheRegistry` is the framework's "one process, one provider" gate.
Backends register themselves here at startup; the static facade
`GlobalCache` reads from here. Registering a second provider while
one is already active raises `StateError` — the caller must call
`unregister()` first to swap backends. This is deliberate: silently
overwriting the active provider would let one component tear down
another component's Redis client out from under it.

Thread-safety: a single class-level `Lock` guards both reads and
writes of `_registrar`. Reads (`active()`, `is_registered()`) acquire
the lock too, so a swap cannot be observed mid-flight. The lock is
held only for the duration of the assignment / lookup, not for any
user-level operation; cap latency is bounded by Lock acquire +
attribute write.

Why classmethods (not instance + Holder pattern)? Because the
registry is itself process-wide state; there's no value in
instantiating it. A static class is the most honest expression of
that.

Diagnostics: `active_provider()` returns the enum of the active
provider (or `None` if uninitialized) for logs / health checks.
"""

from __future__ import annotations

import threading
from typing import ClassVar, Optional

from ..enums.cache_provider import CacheProvider
from .provider_registrar import ProviderRegistrar


class StateError(RuntimeError):
    """Raised when the registry is in a state that prevents the
    requested operation (already-registered, not-registered, ...)."""


class CacheRegistry:
    """Mutex-guarded singleton for the active `ProviderRegistrar`."""

    _registrar: ClassVar[Optional[ProviderRegistrar]] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def register(cls, registrar: ProviderRegistrar) -> None:
        """Install `registrar` as the active provider.

        Raises:
            StateError: another provider is already registered. Call
                :meth:`unregister` first to swap backends.
        """
        with cls._lock:
            if cls._registrar is not None:
                active_kind = cls._registrar.provider()
                new_kind = registrar.provider()
                raise StateError(
                    f"Cache provider already registered ({active_kind!r}). "
                    f"Call CacheRegistry.unregister() first to switch "
                    f"to {new_kind!r}."
                )
            cls._registrar = registrar

    @classmethod
    def unregister(cls) -> None:
        """Drop the active provider. No-op if none was registered.

        The caller is responsible for closing the previous provider's
        resources (e.g. Redis connection); the registry only drops
        its reference.
        """
        with cls._lock:
            cls._registrar = None

    @classmethod
    def active(cls) -> ProviderRegistrar:
        """Return the active `ProviderRegistrar`.

        Raises:
            StateError: no provider is currently registered. Call
                :meth:`register` (or `GlobalCache.install(...)`) first.
        """
        with cls._lock:
            if cls._registrar is None:
                raise StateError(
                    "No cache provider registered. "
                    "Call GlobalCache.install(registrar) first."
                )
            return cls._registrar

    @classmethod
    def is_registered(cls) -> bool:
        """True if a provider is currently registered."""
        with cls._lock:
            return cls._registrar is not None

    @classmethod
    def active_provider(cls) -> Optional[CacheProvider]:
        """Return the active provider's enum (or `None`)."""
        with cls._lock:
            return cls._registrar.provider() if cls._registrar else None


__all__ = ["CacheRegistry", "StateError"]
