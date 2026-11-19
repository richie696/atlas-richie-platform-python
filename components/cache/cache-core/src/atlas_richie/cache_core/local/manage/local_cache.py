"""本地缓存静态工具类。
----
本地缓存静态工具类。提供进程内本地缓存的静态访问入口，底层通过
`AtomicReference<LocalCacheManager>` 持有管理器实例。

English
--------
Process-local in-memory static facade.

Mirrors Java's `cn.richie696.component.cache.LocalCache` **without**
the JSR-107 contract. The Java side is a static class delegating to an
`AtomicReference<LocalCacheManager>`; in Python we use a class-level
singleton (double-checked locking) plus `set_manager()` for test
injection and `reset()` for teardown.

The API surface is Pythonic and minimal: ~20 classmethods covering
the basic KV, CAS, atomic get-and-modify, batch, and TTL-update
operations. No JSR-107 `EntryProcessor` / `CompletionListener` /
`CacheManager` boilerplate — those exist solely to satisfy the JSR-107
spec and are not idiomatic Python.

Example::

    from atlas_richie.cache_core.local import LocalCache

    LocalCache.put("session:42", "user_42", {"name": "richie"})
    user = LocalCache.get("session:42", "user_42")
    LocalCache.put_with_ttl("session:42", "user_43", payload, ttl_millis=60_000)

For tests::

    from atlas_richie.cache_core.local import LocalCache, LocalCacheManager
    LocalCache.set_manager(LocalCacheManager())
    try:
        LocalCache.put("region", "k", "v")
    finally:
        LocalCache.reset()
"""

from __future__ import annotations

import threading
from typing import Any, ClassVar, Dict, List

from ..config.local_cache_properties import LocalCacheProperties
from .cache_statistics import CacheStatistics
from .local_cache_manager import LocalCacheManager


class LocalCache:
    """进程级本地缓存静态外观。

    首次调用时懒构造单例。通过 double-checked locking 保证线程安全。
    若需多租户隔离或测试注入，可通过 :meth:`set_manager` 注入特定 Holder。

    English
    --------
    Process-wide static facade for the in-memory cache.

    Lazy singleton built on first call. Thread-safe via double-checked
    locking. For multi-tenant / per-test isolation, use
    :meth:`set_manager` to inject a specific Holder.
    """

    _instance: ClassVar[LocalCacheManager | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────

    @classmethod
    def get_manager(cls) -> LocalCacheManager:
        """Return the process-wide ``LocalCacheManager``; build it on
        first call.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = LocalCacheManager()
        return cls._instance

    @classmethod
    def set_manager(cls, manager: LocalCacheManager) -> None:
        """Inject a specific Holder (test override / framework bootstrap).

        The previous instance, if any, is closed best-effort outside
        the lock to avoid holding it during a slow ``close()``.
        """
        with cls._lock:
            previous, cls._instance = cls._instance, manager
        if previous is not None and previous is not manager:
            try:
                previous.close()
            except Exception:
                pass

    @classmethod
    def reset(cls) -> None:
        """Drop the singleton; close its resources best-effort."""
        with cls._lock:
            previous, cls._instance = cls._instance, None
        if previous is not None:
            try:
                previous.close()
            except Exception:
                pass

    @classmethod
    def close(cls) -> None:
        """Application shutdown hook. Alias for :meth:`reset`."""
        cls.reset()

    @classmethod
    def configure(cls, properties: LocalCacheProperties) -> None:
        """Replace the singleton with a manager using the given properties.

        Convenience for environments where env-driven configuration is
        not appropriate (tests, custom bootstrap).
        """
        cls.set_manager(LocalCacheManager(properties=properties))

    # ── KV / TTL ─────────────────────────────────────────────────────

    @classmethod
    def put(cls, region: str | Any, key: str, value: Any) -> None:
        cls.get_manager().put(region, key, value)

    @classmethod
    def put_with_ttl(
        cls,
        region: str | Any,
        key: str,
        value: Any,
        ttl_millis: int,
    ) -> None:
        cls.get_manager().put_with_ttl(region, key, value, ttl_millis)

    @classmethod
    def put_if_absent(
        cls, region: str | Any, key: str, value: Any
    ) -> bool:
        return cls.get_manager().put_if_absent(region, key, value)

    @classmethod
    def put_if_absent_with_ttl(
        cls,
        region: str | Any,
        key: str,
        value: Any,
        ttl_millis: int,
    ) -> bool:
        return cls.get_manager().put_if_absent_with_ttl(
            region, key, value, ttl_millis
        )

    @classmethod
    def get(cls, region: str | Any, key: str) -> Any:
        return cls.get_manager().get(region, key)

    @classmethod
    def get_all(
        cls, region: str | Any, keys: List[str]
    ) -> Dict[str, Any]:
        return cls.get_manager().get_all(region, keys)

    @classmethod
    def contains_key(cls, region: str | Any, key: str) -> bool:
        return cls.get_manager().contains_key(region, key)

    @classmethod
    def remove(cls, region: str | Any, key: str) -> bool:
        return cls.get_manager().remove(region, key)

    @classmethod
    def remove_keys(
        cls, region: str | Any, keys: List[str]
    ) -> int:
        return cls.get_manager().remove_keys(region, keys)

    @classmethod
    def clear_region(cls, region: str | Any) -> int:
        return cls.get_manager().clear_region(region)

    # ── CAS / atomic get-and-modify ────────────────────────────────

    @classmethod
    def replace(
        cls,
        region: str | Any,
        key: str,
        old_value: Any,
        new_value: Any,
    ) -> bool:
        return cls.get_manager().replace(region, key, old_value, new_value)

    @classmethod
    def get_and_remove(cls, region: str | Any, key: str) -> Any:
        return cls.get_manager().get_and_remove(region, key)

    @classmethod
    def get_and_put(
        cls, region: str | Any, key: str, value: Any
    ) -> Any:
        return cls.get_manager().get_and_put(region, key, value)

    @classmethod
    def get_and_replace(
        cls, region: str | Any, key: str, value: Any
    ) -> Any:
        return cls.get_manager().get_and_replace(region, key, value)

    # ── Batch / TTL update ─────────────────────────────────────────

    @classmethod
    def put_all(
        cls,
        region: str | Any,
        mapping: Dict[str, Any],
        ttl_millis: int | None = None,
    ) -> None:
        cls.get_manager().put_all(region, mapping, ttl_millis)

    @classmethod
    def pop_by_count(
        cls, region: str | Any, count: int
    ) -> Dict[str, Any]:
        return cls.get_manager().pop_by_count(region, count)

    @classmethod
    def expiry(
        cls, region: str | Any, key: str, ttl_millis: int
    ) -> None:
        cls.get_manager().expiry(region, key, ttl_millis)

    @classmethod
    def region_size(cls, region: str | Any) -> int:
        return cls.get_manager().region_size(region)

    @classmethod
    def size(cls, region: str | Any) -> int:
        """返回 region 中存活（未过期）的条目数。

        English
        --------
        Number of live (non-expired) entries in `region`.
        """
        return cls.get_manager().size(region)

    # ── Read-through / write-through ───────────────────────────────

    @classmethod
    def register_loader(cls, region: str | Any, loader: Any) -> None:
        """注册某 region 的 read-through 加载器。

        接受实现了 `load` / `load_all` 的对象，或单个
        `key -> value | None` 可调用对象。未命中时由它回源并把结果
        写回缓存。

        English
        --------
        Register the read-through loader for `region`.

        Accepts an object implementing `load` / `load_all`, or a
        single `key -> value | None` callable. On a miss the loader is
        asked for the value and the result is cached.
        """
        cls.get_manager().register_loader(region, loader)

    @classmethod
    def register_writer(cls, region: str | Any, writer: Any) -> None:
        """注册某 region 的 write-through 写入器。

        接受同时实现 `write` 与 `delete` 的对象，或 `(write, delete)`
        二元组。缓存发生变更时同步回写数据源（先改缓存、再调写入器）。

        English
        --------
        Register the write-through writer for `region`.

        Accepts an object implementing both `write` and `delete`, or
        a `(write, delete)` pair. Cache mutations are pushed back to
        the source of truth (cache first, then the writer).
        """
        cls.get_manager().register_writer(region, writer)

    # ── Statistics ─────────────────────────────────────────────────

    @classmethod
    def stats(cls, region: str | Any) -> CacheStatistics:
        """返回某 region 的累计统计快照。

        计数只在 region 的 `statistics_enabled` 为真时维护。

        English
        --------
        Cumulative statistics snapshot for `region`. Counters are only
        maintained when the region has `statistics_enabled` set.
        """
        return cls.get_manager().stats(region)

    @classmethod
    def all_stats(cls) -> Dict[str, CacheStatistics]:
        """返回所有已创建 region 的统计快照。

        English
        --------
        Statistics snapshots for every region that has been created.
        """
        return cls.get_manager().all_stats()


__all__ = ["LocalCache"]
