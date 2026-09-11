"""L2 分布式缓存（R-223）— 两层 cache-aside。
----
对位 Java 端 `cn.richie696.component.cache.l2.L2DistributedCache`。

**架构**：

    caller → L1（进程内 cachetools）→ L2（Redis）→ loader（调用方）

  - L1 命中：直接返回，无网络。
  - L1 未命中 / L2 命中：拷贝 L2 → L1（read-through），返回。
  - 都没命中：调用方负责从下游源（DB / API）加载并通过 `set(...)` 回写。

**L1 与 L2 共享同一 TTL**，避免 L2 已过期的条目在 L1 继续存活。
TTL 在构造时确定，每个实例独立。

**按 region 的 L1 容量**：每个 `L2DistributedCache` 实例持有自己的
`LocalCacheManager`，按 region 配置 `CacheDefinition`，把 `max_size`
固定到调用方请求值。这样 LRU 的 `max_size` 预算是 per-instance 的，
而不是默认的 10_000。

English
--------
L2 DistributedCache (R-223) — two-tier cache-aside.

Mirrors `cn.richie696.component.cache.l2.L2DistributedCache` (Java).

**Architecture**:
    caller → L1 (process-local cachetools) → L2 (Redis) → loader (caller)

  - L1 hit: return immediately, no network.
  - L1 miss, L2 hit: copy to L1 (read-through), return.
  - Both miss: caller is responsible for loading from a downstream
    source (DB / API) and writing back via `set(...)`.

**L1 and L2 share the same TTL** so an expired L2 entry won't
silently live on in L1. The TTL is per-instance (set at construction).

**Per-region L1 sizing**: each `L2DistributedCache` instance owns a
`LocalCacheManager` configured with a per-region `CacheDefinition`
that pins `max_size` to the caller's request. This way the LRU
`max_size` budget is honored per-instance rather than the default
10_000.
"""

from __future__ import annotations

import threading
import weakref
from typing import Any, Callable, Dict, Optional

from atlas_richie.cache_core.local.config.local_cache_properties import (
    CacheDefinition,
    LocalCacheProperties,
)
from atlas_richie.cache_core.local.enums.expiry_policy import ExpiryPolicy
from atlas_richie.cache_core.local.manage.local_cache_manager import (
    LocalCacheManager,
)

from ..managers.redis_string_manager import (
    RedisStringManager,
    _call_db_loader_with_timeout,
)


class _KeyLock:
    """Per-key `threading.Lock` wrapper that supports `weakref`.

    M5.2: `L2DistributedCache` maintains a `WeakValueDictionary`
    of these instances, keyed by user-key. When the last caller
    of a key releases its lock, the instance becomes unreferenced
    (the caller's frame releases it) and the weak entry is
    automatically dropped by the `WeakValueDictionary`. This
    bounds the lock table's memory in long-running processes
    without an explicit LRU + manual cleanup.

    `threading.Lock` itself does not support `weakref` (built-in
    mutex objects are excluded), so we wrap it in a class with
    `__weakref__` in `__slots__` to enable weak-reference support.

    The `__enter__` / `__exit__` methods delegate to the
    underlying lock, so callers can use it as a context manager:
    `with lock: ...`.
    """

    __slots__ = ("_lock", "__weakref__")

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def __enter__(self) -> None:
        self._lock.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self._lock.release()


class L2DistributedCache:
    """Two-tier cache facade (L1 in-process + L2 Redis).

    Construction is intentionally cheap: the L1 bucket is a lazy
    `cachetools.LRUCache` and the L2 is just a reference to a
    `RedisStringManager`. Use ``L2CacheFactory`` (or
    ``RedisProviderRegistrar.l1(...)``) to obtain cached instances.
    """

    def __init__(
        self,
        value_ops: RedisStringManager,
        region: str,
        max_size: int = 10_000,
        ttl_seconds: int = 300,
    ) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be > 0")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        self._value_ops = value_ops
        self._region = region
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        # Per-instance LocalCacheManager with a per-region
        # `CacheDefinition` so the L1 budget matches the L2 cache's
        # `max_size` request.
        properties = LocalCacheProperties(
            cache_definitions={
                region: CacheDefinition(
                    expiry_policy=ExpiryPolicy.ACCESSED,
                    ttl_millis=ttl_seconds * 1000,
                    max_size=max_size,
                )
            }
        )
        self._local = LocalCacheManager(properties)
        # M5.2: in-process stampede-prevention lock table. The
        # `WeakValueDictionary` automatically drops entries when
        # the `_KeyLock` instance loses all strong references
        # (i.e. when the last caller exits the `with lock:` block
        # and the lock is no longer held by any thread).
        self._key_locks: "weakref.WeakValueDictionary[str, _KeyLock]" = (
            weakref.WeakValueDictionary()
        )
        self._key_locks_guard = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._stats_lock = threading.Lock()

    # ── Public API ───────────────────────────────────────────────

    def get(self, key: str) -> Optional[bytes]:
        """Look up a key. Returns the raw bytes, or `None` on miss."""
        # L1 first.
        l1_value = self._local.get(self._region, key)
        if l1_value is not None:
            with self._stats_lock:
                self._hits += 1
            return l1_value
        # L1 miss — try L2.
        with self._stats_lock:
            self._misses += 1
        l2_value = self._value_ops.get(key, bytes)
        if l2_value is None:
            return None
        # Read-through: copy L2 → L1.
        try:
            self._local.put(self._region, key, l2_value)
            self._local.expiry(self._region, key, self._ttl_seconds * 1000)
        except Exception:
            pass
        return l2_value

    def set(self, key: str, value: bytes, ttl_seconds: int = 0) -> None:
        """Set a key. `ttl_seconds=0` uses the instance default.

        Writes go to BOTH L1 and L2 synchronously. A L2 failure does
        not roll back L1 (callers that need strict consistency should
        invalidate L1 after a successful L2 write).
        """
        effective_ttl = ttl_seconds if ttl_seconds > 0 else self._ttl_seconds
        # L1 first (cheap, no network).
        try:
            self._local.put(self._region, key, value)
            self._local.expiry(self._region, key, effective_ttl * 1000)
        except Exception:
            pass
        # L2 (network).
        self._value_ops.set_with_ttl(key, value, effective_ttl * 1000)

    def delete(self, key: str) -> None:
        """Delete from BOTH L1 and L2."""
        try:
            self._local.remove(self._region, key)
        except Exception:
            pass
        # L2 delete: `value_ops` is the ValueOps Protocol and doesn't
        # expose `delete`; the Redis-side key manager owns the key-level
        # operations. We grab a fresh `key_ops` from the same backend.
        self._value_ops._backend.raw_client().delete(  # type: ignore[attr-defined]
            self._value_ops._k(key)  # type: ignore[attr-defined]
        )

    def invalidate_l1(self, key: str) -> None:
        """Delete from L1 only (force a fresh L2 read on the next get)."""
        try:
            self._local.remove(self._region, key)
        except Exception:
            pass

    # ── M5.2: in-process stampede prevention + loader-driven read ──

    def get_or_load(
        self,
        key: str,
        loader: Callable[[], Optional[bytes]],
        *,
        ttl_seconds: int | None = None,
        loader_timeout_millis: int | None = None,
    ) -> Optional[bytes]:
        """按 key 防进程内击穿：L1 命中直接返回；L1 未命中走 L2；都没中则
        在 per-key `threading.Lock` 保护下调用 `loader` 回源，回写 L1 +
        L2。

        Args:
            key: 缓存键
            loader: 回源加载器；返回 `None` 表示无值（不写缓存）
            ttl_seconds: 缓存 TTL（秒）。`None` = 用实例默认 TTL
            loader_timeout_millis: 可选 — M5.1：`loader` 的
                毫秒级超时。`None`（默认）= 无限时；`> 0` =
                超时返 None（不写缓存）。复用 `_call_db_loader_with_timeout`。

        Returns:
            缓存值；未命中且加载失败或超时时为 `None`。

        Raises:
            ValueError: `loader_timeout_millis <= 0`。
            `loader` 自身抛出的异常会原样传播。

        English
        --------
        In-process stampede-proof loader-driven read. On L1 hit,
        returns immediately (no lock acquired, no loader called).
        On L1 miss, acquires a per-key in-process `threading.Lock`
        so concurrent in-process misses funnel to ONE loader call,
        tries L2 (Redis), and only invokes `loader` on the
        L1+L2-miss path. The loader's return value is written to
        both L1 and L2. The in-process lock is the L2 layer's
        stampede defense; the cross-process stampede defense lives
        in `RedisStringManager.get_with_lock` (R-M4). These two
        layers are complementary, not redundant — `get_or_load`
        protects in-process fan-out; `*_with_lock` protects
        cross-process fan-out.
        """
        if loader is None:
            raise ValueError("loader is required")
        if loader_timeout_millis is not None and loader_timeout_millis <= 0:
            raise ValueError("loader_timeout_millis must be > 0 (or None)")
        effective_ttl = ttl_seconds if (ttl_seconds is not None and ttl_seconds > 0) else self._ttl_seconds

        # 1. L1 fast path (no lock acquired, no network).
        l1_value = self._local.get(self._region, key)
        if l1_value is not None:
            with self._stats_lock:
                self._hits += 1
            return l1_value

        # 2. L1 miss. Acquire the per-key in-process stampede lock
        #    so concurrent in-process misses funnel to ONE loader call.
        with self._get_key_lock(key):
            # 3. Double-check L1 (another thread may have just
            #    populated it under the lock).
            l1_value = self._local.get(self._region, key)
            if l1_value is not None:
                with self._stats_lock:
                    self._hits += 1
                return l1_value

            with self._stats_lock:
                self._misses += 1

            # 4. Try L2 (read-through). If L2 hits, populate L1 and
            #    return; no loader call.
            l2_value = self._value_ops.get(key, bytes)
            if l2_value is not None:
                try:
                    self._local.put(self._region, key, l2_value)
                    self._local.expiry(self._region, key, effective_ttl * 1000)
                except Exception:
                    pass
                return l2_value

            # 5. L1 + L2 both miss → call the loader, optionally
            #    with a timeout (M5.1 helper).
            value = _call_db_loader_with_timeout(loader, loader_timeout_millis)
            if value is None:
                return None

            # 6. Write to BOTH L1 and L2 with the effective TTL.
            #    L1 first (cheap, no network), then L2 (network).
            try:
                self._local.put(self._region, key, value)
                self._local.expiry(self._region, key, effective_ttl * 1000)
            except Exception:
                pass
            self._value_ops.set_with_ttl(key, value, effective_ttl * 1000)
            return value

    def _get_key_lock(self, key: str) -> _KeyLock:
        """Get-or-create the per-key `_KeyLock`.

        The `_key_locks` is a `WeakValueDictionary`; the lock
        is created lazily on first contention for a given key.
        When the last caller exits the `with` block, the strong
        reference is dropped and the weak entry is collected
        automatically.
        """
        with self._key_locks_guard:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = _KeyLock()
                self._key_locks[key] = lock
            return lock

    def stats(self) -> Dict[str, int]:
        """Return a snapshot of L1 hit / miss counters and current
        L1 size. Useful for tuning and observability."""
        with self._stats_lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "l1_size": self._l1_size(),
                "max_size": self._max_size,
            }

    # ── Internal ─────────────────────────────────────────────────

    def _l1_size(self) -> int:
        """Best-effort L1 size — the local cache doesn't expose a
        `__len__` directly, so we walk the bucket's entries."""
        try:
            bucket = self._local._buckets[self._region]  # type: ignore[attr-defined]
            with bucket._lock:  # type: ignore[attr-defined]
                return len(bucket._entries)  # type: ignore[attr-defined]
        except (KeyError, AttributeError):
            return 0

    # ── Properties ───────────────────────────────────────────────

    @property
    def region(self) -> str:
        return self._region

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds


__all__ = ["L2DistributedCache"]
