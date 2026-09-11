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
import time
import weakref
from typing import Any, Callable, Dict, Iterable, List, Optional

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
    _call_db_loader_with_timeout_ex,
    _is_negative,
    _NEGATIVE_SENTINEL,
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
        # M5.3 observability counters (cumulative since construction;
        # `stats()` is a snapshot of these).
        self._in_process_loader_fan_in = 0
        self._in_process_loader_wait_seconds_total = 0.0
        self._loader_timeouts = 0
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
        negative_cache_ttl_millis: int | None = None,
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
            negative_cache_ttl_millis: 可选 — M5.7：仅当
                `loader` 因 `loader_timeout_millis` **超时**而未
                返回时，写一个短 TTL 的"负缓存"标记到 L1 + L2，
                让后续 caller 在 TTL 窗口内直接返回 `None` 而
                不再调用 loader。自然返回 `None` 不写负缓存。
                负缓存标记是固定的字节 sentinel（与
                `RedisStringManager.get_with_lock` 共享同一个
                常量），由 `_is_negative(...)` 识别。

        Returns:
            缓存值；未命中且加载失败或超时时为 `None`；命中负缓存
            标记时同样为 `None`。

        Raises:
            ValueError: `loader_timeout_millis <= 0` 或
                `negative_cache_ttl_millis <= 0`。
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

        M5.7: `negative_cache_ttl_millis` writes a bytes sentinel
        to BOTH L1 and L2 on TIMEOUT so subsequent callers within
        the window return `None` without re-invoking the loader.
        Only fires on TIMEOUT, never on a natural `None` from
        the loader.
        """
        if loader is None:
            raise ValueError("loader is required")
        if loader_timeout_millis is not None and loader_timeout_millis <= 0:
            raise ValueError("loader_timeout_millis must be > 0 (or None)")
        if negative_cache_ttl_millis is not None and negative_cache_ttl_millis <= 0:
            raise ValueError(
                "negative_cache_ttl_millis must be > 0 (or None)"
            )
        effective_ttl = ttl_seconds if (ttl_seconds is not None and ttl_seconds > 0) else self._ttl_seconds

        # 1. L1 fast path (no lock acquired, no network). M5.7: a
        #    negative-cache marker is also a hit (returns `None`).
        l1_value = self._local.get(self._region, key)
        if l1_value is not None:
            if _is_negative(l1_value):
                with self._stats_lock:
                    self._hits += 1
                return None
            with self._stats_lock:
                self._hits += 1
            return l1_value

        # 2. L1 miss. Acquire the per-key in-process stampede lock
        #    so concurrent in-process misses funnel to ONE loader call.
        #    M5.3: track wait time + fan-in counters for `stats()`.
        _lock_acquired_at = time.monotonic()
        with self._get_key_lock(key):
            wait_seconds = time.monotonic() - _lock_acquired_at
            with self._stats_lock:
                self._in_process_loader_fan_in += 1
                self._in_process_loader_wait_seconds_total += wait_seconds
            # 3. Double-check L1 (another thread may have just
            #    populated it under the lock). M5.7: a negative
            #    marker is also a hit.
            l1_value = self._local.get(self._region, key)
            if l1_value is not None:
                if _is_negative(l1_value):
                    with self._stats_lock:
                        self._hits += 1
                    return None
                with self._stats_lock:
                    self._hits += 1
                return l1_value

            with self._stats_lock:
                self._misses += 1

            # 4. Try L2 (read-through). If L2 hits, populate L1 and
            #    return; no loader call. M5.7: a negative marker in
            #    L2 also counts as a hit (returns `None`).
            l2_value = self._value_ops.get(key, bytes)
            if l2_value is not None:
                if _is_negative(l2_value):
                    # L2 negative-cache hit — populate L1 with the
                    # sentinel (so the next L1 fast path is a hit
                    # too) and return `None`.
                    try:
                        self._local.put(self._region, key, l2_value)
                        self._local.expiry(
                            self._region, key,
                            int(negative_cache_ttl_millis or effective_ttl * 1000),
                        )
                    except Exception:
                        pass
                    return None
                try:
                    self._local.put(self._region, key, l2_value)
                    self._local.expiry(self._region, key, effective_ttl * 1000)
                except Exception:
                    pass
                return l2_value

            # 5. L1 + L2 both miss → call the loader, optionally
            #    with a timeout (M5.1 helper, `_call_db_loader_with_timeout_ex`
            #    also returns the `timed_out` flag for M5.7).
            value, was_timed_out = _call_db_loader_with_timeout_ex(
                loader, loader_timeout_millis
            )
            if value is None:
                # M5.3: record the timeout event for `stats()`.
                with self._stats_lock:
                    self._loader_timeouts += 1
                # M5.7: on TIMEOUT, optionally write the negative
                # sentinel to BOTH L1 and L2 so subsequent callers
                # within the window return `None` immediately.
                if (
                    was_timed_out
                    and negative_cache_ttl_millis is not None
                    and negative_cache_ttl_millis > 0
                ):
                    try:
                        self._local.put(self._region, key, _NEGATIVE_SENTINEL)
                        self._local.expiry(
                            self._region, key, int(negative_cache_ttl_millis),
                        )
                    except Exception:
                        pass
                    try:
                        self._value_ops.set_with_ttl(
                            key, _NEGATIVE_SENTINEL,
                            int(negative_cache_ttl_millis),
                        )
                    except Exception:
                        pass
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

    # ── M5.3: batch loader ─────────────────────────────────────────

    def get_or_load_many(
        self,
        keys: Iterable[str],
        loader: Callable[[List[str]], Dict[str, bytes]],
        *,
        ttl_seconds: int | None = None,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> Dict[str, Optional[bytes]]:
        """按 batch 防进程内击穿：L1 命中的直接返回；L1 未命中的走 L2；都没中则在
        单次锁保护下调用一次 `loader(missing_keys)` 拿 dict，回写 L1 + L2。

        Args:
            keys: 缓存键列表（任意 iterable）
            loader: 批量回源加载器；输入 missing keys 列表，返回
                `{key: value}` dict；missing 键不返回 / 返回 `None`
                都表示"无值"（不写缓存）
            ttl_seconds: 缓存 TTL（秒），`None` = 实例默认
            loader_timeout_millis: 可选 — `loader` 的毫秒级超时
                （M5.1 helper 复用），`None` = 无限时
            negative_cache_ttl_millis: 可选 — M5.7：仅当 `loader`
                因 `loader_timeout_millis` **超时**而未返回时，对
                **所有**仍处于 missing 状态的 key 写一个短 TTL
                的"负缓存"标记到 L1 + L2，让后续 caller 在 TTL
                窗口内直接返回 `None` 而不再调用 loader。自然
                返回空 dict 不写负缓存。负缓存标记是固定的字节
                sentinel，由 `_is_negative(...)` 识别。

        Returns:
            `Dict[str, Optional[bytes]]` — 每个请求 key 的值；
            命中/loader 返回/超时/未找到都映射到 `bytes | None`。
            返回 dict 的 keys 严格 = 入参 keys（顺序不保证）。

        Raises:
            ValueError: `loader is None` / `loader_timeout_millis <= 0`
                / `negative_cache_ttl_millis <= 0`。
            `loader` 自身抛出的异常会原样传播

        English
        --------
        Batch in-process stampede-proof load. The `loader` is called
        ONCE per stampede (not once per missing key), with the list
        of missing keys as input and a `{key: value}` dict as output.
        Each result is then written to both L1 and L2.

        The implementation acquires a per-BATCH lock (key = sorted
        tuple of missing keys, hashed) so concurrent batch callers
        funnel to one loader call. Per-key L1/L2 lookups happen
        sequentially (not in parallel) for simplicity; the dominant
        cost is usually the loader, not the cache reads.

        M5.7: `negative_cache_ttl_millis` writes a per-key bytes
        sentinel to BOTH L1 and L2 on TIMEOUT for every key that
        was still missing when the timeout fired. Subsequent
        callers within the window return `None` for those keys
        without re-invoking the loader. Only fires on TIMEOUT,
        never on a natural empty dict from the loader.
        """
        if loader is None:
            raise ValueError("loader is required")
        if loader_timeout_millis is not None and loader_timeout_millis <= 0:
            raise ValueError("loader_timeout_millis must be > 0 (or None)")
        if negative_cache_ttl_millis is not None and negative_cache_ttl_millis <= 0:
            raise ValueError(
                "negative_cache_ttl_millis must be > 0 (or None)"
            )
        effective_ttl = ttl_seconds if (ttl_seconds is not None and ttl_seconds > 0) else self._ttl_seconds

        # Deduplicate + preserve insertion order
        keys_list = list(dict.fromkeys(keys))
        if not keys_list:
            return {}

        results: Dict[str, Optional[bytes]] = {}
        # Phase 1: try L1 for each key (no lock, no network).
        #    M5.7: a negative-cache marker is also a hit (returns `None`).
        for k in keys_list:
            v = self._local.get(self._region, k)
            if v is not None:
                if _is_negative(v):
                    results[k] = None
                else:
                    results[k] = v
                with self._stats_lock:
                    self._hits += 1
        # Phase 2: collect keys still missing after L1.
        missing = [k for k in keys_list if k not in results]
        if not missing:
            return results

        # Phase 3: acquire the per-batch stampede lock.
        #    M5.3: track wait time + fan-in counters for `stats()`.
        batch_lock_key = self._make_batch_lock_key(missing)
        _lock_acquired_at = time.monotonic()
        with self._get_key_lock(batch_lock_key):
            wait_seconds = time.monotonic() - _lock_acquired_at
            with self._stats_lock:
                self._in_process_loader_fan_in += 1
                self._in_process_loader_wait_seconds_total += wait_seconds
            # Phase 4: double-check L1 (another batch holder may have
            # populated it under the lock). M5.7: a negative marker
            # is also a hit.
            for k in list(missing):
                v = self._local.get(self._region, k)
                if v is not None:
                    if _is_negative(v):
                        results[k] = None
                    else:
                        results[k] = v
                    with self._stats_lock:
                        self._hits += 1
            missing = [k for k in missing if k not in results]
            if not missing:
                return results

            with self._stats_lock:
                self._misses += len(missing)

            # Phase 5: try L2 for each missing key (sequential for
            # simplicity; L2 reads are cheap when keys are missing).
            #    M5.7: a negative marker in L2 is also a hit
            #    (returns `None`).
            l2_hits: Dict[str, bytes] = {}
            for k in missing:
                v = self._value_ops.get(k, bytes)
                if v is not None:
                    l2_hits[k] = v
            for k, v in l2_hits.items():
                if _is_negative(v):
                    results[k] = None
                else:
                    results[k] = v
                try:
                    self._local.put(self._region, k, v)
                    # Use the caller-supplied TTL (or default);
                    # the negative TTL is only relevant for
                    # writes triggered by a TIMEOUT, not for
                    # a published L2 negative marker (which
                    # already has its own L2-side TTL).
                    self._local.expiry(self._region, k, effective_ttl * 1000)
                except Exception:
                    pass
            missing = [k for k in missing if k not in l2_hits]
            if not missing:
                return results

            # Phase 6: L1 + L2 all miss → call the loader ONCE for
            # the whole batch (funnel).
            value, was_timed_out = _call_db_loader_with_timeout_ex(
                lambda: loader(missing), loader_timeout_millis
            )
            if value is None:
                with self._stats_lock:
                    self._loader_timeouts += 1
                # M5.7: on TIMEOUT, write a per-key negative
                # sentinel to BOTH L1 and L2 for each still-missing
                # key so subsequent callers within the window
                # return `None` immediately.
                if (
                    was_timed_out
                    and negative_cache_ttl_millis is not None
                    and negative_cache_ttl_millis > 0
                ):
                    for k in missing:
                        try:
                            self._local.put(self._region, k, _NEGATIVE_SENTINEL)
                            self._local.expiry(
                                self._region, k, int(negative_cache_ttl_millis),
                            )
                        except Exception:
                            pass
                        try:
                            self._value_ops.set_with_ttl(
                                k, _NEGATIVE_SENTINEL,
                                int(negative_cache_ttl_millis),
                            )
                        except Exception:
                            pass
                # Loader returned None / timed out → all `missing` keys
                # are reported as `None` in the result.
                for k in missing:
                    results[k] = None
                return results

            # Phase 7: write each loaded value to L1 + L2.
            for k, v in list(value.items()):
                if v is None:
                    results[k] = None
                    continue
                results[k] = v
                try:
                    self._local.put(self._region, k, v)
                    self._local.expiry(self._region, k, effective_ttl * 1000)
                except Exception:
                    pass
                self._value_ops.set_with_ttl(k, v, effective_ttl * 1000)
            # Any `missing` keys that the loader didn't return are
            # treated as "no value" (returns `None`).
            for k in missing:
                if k not in results:
                    results[k] = None
            return results

    @staticmethod
    def _make_batch_lock_key(keys: List[str]) -> str:
        """Stable per-batch lock key.

        Sort the keys to make `(["a", "b", "c"])` and `(["c", "b", "a"])`
        collide on the same lock — otherwise concurrent batch callers
        with different orderings of the same keys would each
        independently call their own loader, defeating the funnel.
        """
        return "__batch_lock__::" + "::".join(sorted(keys))

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

    def stats(self) -> Dict[str, Any]:
        """Return a snapshot of L1 hit / miss counters and current
        L1 size, plus M5.3 / R-M5.1 cumulative observability counters.

        Useful for tuning and observability:

        - `hits` / `misses` — L1+L2 cache hit / miss counts since
          construction
        - `l1_size` — current L1 entry count (best-effort, walks the
          internal bucket)
        - `max_size` — configured LRU `max_size` for this region
        - `in_process_loader_fan_in` — total number of times the
          in-process stampede lock was acquired (i.e. the number of
          loader invocations across all `get_or_load` /
          `get_or_load_many` calls; > 1 means concurrent misses
          funneled to one loader call)
        - `in_process_loader_wait_seconds` — total seconds the
          cache thread spent waiting for the in-process stampede
          lock (high = lots of contention)
        - `key_lock_table_size` — current number of live per-key
          `_KeyLock` entries (after GC of unused locks); gives a
          sense of working-set size
        - `loader_timeouts` — total number of times the loader
          exceeded `loader_timeout_millis` (R-M5.1)
        """
        with self._stats_lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "l1_size": self._l1_size(),
                "max_size": self._max_size,
                "in_process_loader_fan_in": self._in_process_loader_fan_in,
                "in_process_loader_wait_seconds": self._in_process_loader_wait_seconds_total,
                "key_lock_table_size": self._live_key_lock_count(),
                "loader_timeouts": self._loader_timeouts,
            }

    def _live_key_lock_count(self) -> int:
        """Number of currently-live `_KeyLock` entries.

        `WeakValueDictionary` doesn't expose `__len__` cleanly when
        many entries have been GC'd but the dict still holds weak
        refs. We force a `gc.collect()` per call (this is a stats
        endpoint, called infrequently, not in the hot path) and
        then read `len()`.
        """
        try:
            import gc as _gc
            _gc.collect()
            return len(self._key_locks)
        except Exception:
            return -1

    # ── Internal ─────────────────────────────────────────────────

    def _l1_size(self) -> int:
        """Best-effort L1 size for `stats()["l1_size"]`.

        Delegates to the public `LocalCacheManager.size(region)` API
        so we don't poke the manager's private attributes (R-M5.x
        polish: prefer the public surface; `LocalCacheManager.size`
        walks the bucket under the bucket's RLock on our behalf).
        """
        return self._local.size(self._region)

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
