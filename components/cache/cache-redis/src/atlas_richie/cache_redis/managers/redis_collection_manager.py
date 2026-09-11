"""Set 类型缓存管理器。
----
``CollectionOps`` + ``SetFunction`` 的 Redis 后端实现（M2）。

镜像 ``cn.richie696.component.cache.redis.manage.RedisSetManager`` 的结构。
同时实现 cache-core 中的底层 ``CollectionOps`` Protocol（Set 数据结构访问）
与高层 ``SetFunction`` Protocol（pop 辅助 + 批量差集）。``ProviderRegistrar``
的 ``collection_ops()`` 与 ``set_function()`` 返回同一个实例。

``CollectionOps`` 与 ``SetFunction`` 之间方法名冲突：**无**。Java 端故意为
高层与底层 Set 操作使用不同方法名（例如 ``CollectionOps.pop`` 对应
``SetFunction.pop_data_from_set``，``CollectionOps.size`` 对应
``SetFunction.get_set_size``，``CollectionOps.add`` 对应
``SetFunction.add_set_item``）。这意味着 Python 翻译可以逐字实现每个
Protocol 的方法而无需合并签名 —— Java 的设计选择与 Python 缺少方法重载
恰好契合的少数情形之一。

防雪崩策略（对齐 Java）：仅在高层 ``add_set`` / ``add_set_item`` 辅助
方法的调用方显式传入 TTL 时生效（在 ``SetFunction`` 中很少见；Set 通常
没有 TTL）。``CollectionOps.set(key, values, timeout_millis)`` 辅助方法会
对传入的 TTL 应用防雪崩。

English
--------
Redis-backed `CollectionOps` + `SetFunction` (M2).

Mirrors `cn.richie696.component.cache.redis.manage.RedisSetManager`
1:1 in Python. Implements **both** the low-level `CollectionOps`
Protocol (Set data structure access) and the high-level `SetFunction`
Protocol (pop helpers + bulk difference) from `cache-core`. The
`ProviderRegistrar.collection_ops()` and `.set_function()` return
the same instance.

Method-name collisions between `CollectionOps` and `SetFunction`:
**none**. The Java side deliberately uses different method names for
the high-level and low-level Set operations (e.g.
`CollectionOps.pop` vs `SetFunction.pop_data_from_set`,
`CollectionOps.size` vs `SetFunction.get_set_size`,
`CollectionOps.add` vs `SetFunction.add_set_item`). This means the
Python translation can implement each Protocol's methods verbatim
without merging signatures — a rare case where the Java design
choice and Python's lack of overloading line up perfectly.

Anti-avalanche policy (matches Java): applied on the high-level
`add_set` / `add_set_item` helpers when the calling context
explicitly passes a TTL (rare; Set is usually TTL-less in
`SetFunction`). The `CollectionOps.set(key, values, timeout_millis)`
helper applies anti-avalanche to the supplied TTL.
"""

from __future__ import annotations

import secrets as _secrets
import time
import uuid
from typing import Any, Callable, Collection, Set as _PySet, TypeVar

from atlas_richie.cache_core.function.set_function import SetFunction
from atlas_richie.cache_core.ops.collection_ops import CollectionOps

from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache
from ..serialization import decode_value, encode_value
from .redis_string_manager import (
    _call_db_loader_with_timeout,
    _call_db_loader_with_timeout_ex,
    _make_stampede_lock_key,
    _stampede_acquire,
    _stampede_release,
)

T = TypeVar("T")

# Anti-avalanche TTL offset range (matches Java's
# `CacheFunction.getRandomExtraMillis()`).
_MIN_ANTI_AVALANCHE_MS = 60_000
_MAX_ANTI_AVALANCHE_MS = 600_000


def _anti_avalanche_ms() -> int:
    return (
        _secrets.randbelow(_MAX_ANTI_AVALANCHE_MS - _MIN_ANTI_AVALANCHE_MS)
        + _MIN_ANTI_AVALANCHE_MS
    )


class RedisCollectionManager(CollectionOps, SetFunction):
    """Set 类型缓存管理器。
    ----
    Redis 后端的 Set 缓存管理器。

    同时实现 ``CollectionOps``（底层 Set 访问）与 ``SetFunction``
    （高层业务辅助）。

    English
    --------
    Redis-backed Set cache manager.

    Implements both `CollectionOps` (low-level Set access) and
    `SetFunction` (high-level business helpers).

    Args:
        backend: The Redis transport wrapper.
        infra: The `CacheInfrastructure` (currently unused; reserved
            for the M4 typed-read plumbing).
    """

    def __init__(
        self,
        backend: RedisDistributedCache,
        infra: RedisCacheInfrastructure,
    ) -> None:
        self._backend = backend
        self._infra = infra

    # ── Internal helpers ───────────────────────────────────────────

    def _k(self, key: str) -> str:
        return self._backend.make_key(key)

    @staticmethod
    def _encode_set(values: _PySet[Any]) -> list[str]:
        return [encode_value(v) for v in values]

    @staticmethod
    def _decode_set(raws: list[Any], clazz: type) -> _PySet[Any]:
        return {v for v in (decode_value(r, clazz) for r in raws) if v is not None}

    # ══════════════════════════════════════════════════════════════
    # CollectionOps (low-level)
    # ══════════════════════════════════════════════════════════════

    def get(self, key: str, clazz: type) -> _PySet[T]:
        raws = self._backend.raw_client().smembers(self._k(key))
        return self._decode_set(raws, clazz)

    def set(
        self, key: str, values: _PySet[Any], timeout_millis: int
    ) -> None:
        """Replace the entire Set with `values`; apply TTL with
        anti-avalanche offset if `timeout_millis > 0`.

        Uses DEL + SADD in a pipeline so the operation is one
        round-trip; the pipeline is NOT transactional.
        """
        client = self._backend.raw_client()
        encoded = self._encode_set(values)
        pipe = client.pipeline(transaction=False)
        pipe.delete(self._k(key))
        if encoded:
            pipe.sadd(self._k(key), *encoded)
        if timeout_millis and timeout_millis > 0:
            pipe.pexpire(
                self._k(key),
                int(timeout_millis) + _anti_avalanche_ms(),
            )
        pipe.execute()

    def add(self, key: str, value: Any) -> None:
        self._backend.raw_client().sadd(self._k(key), encode_value(value))

    def size(self, key: str) -> int:
        return int(self._backend.raw_client().scard(self._k(key)))

    def exists(self, key: str, value: Any) -> bool:
        return bool(
            self._backend.raw_client().sismember(
                self._k(key), encode_value(value)
            )
        )

    def remove(self, key: str, *values: Any) -> None:
        if not values:
            return
        self._backend.raw_client().srem(
            self._k(key), *[encode_value(v) for v in values]
        )

    def batch_set(self, mapping: dict[str, _PySet]) -> None:
        """Bulk replace Sets across many keys.

        NOT atomic (per the Java doc). Uses a pipeline so the batch
        is one round-trip.
        """
        if not mapping:
            return
        client = self._backend.raw_client()
        pipe = client.pipeline(transaction=False)
        for key, values in mapping.items():
            pipe.delete(self._k(key))
            encoded = self._encode_set(values)
            if encoded:
                pipe.sadd(self._k(key), *encoded)
        pipe.execute()

    def pop(self, key: str, clazz: type) -> Any:
        raw = self._backend.raw_client().spop(self._k(key))
        if raw is None:
            return None
        if isinstance(raw, (list, _PySet)):
            raw = raw[0] if raw else None
        if raw is None:
            return None
        return decode_value(raw, clazz)

    def pop_many(self, key: str, count: int, clazz: type) -> _PySet[T]:
        if count <= 0:
            return set()
        raws = self._backend.raw_client().spop(self._k(key), count)
        if raws is None:
            return set()
        if isinstance(raws, (bytes, str)):
            raws = [raws]
        return self._decode_set(list(raws), clazz)

    def get_with_lock(
        self,
        key: str,
        clazz: type,
        timeout_millis: int,
        db_loader: Callable[[], _PySet[T] | None],
        *,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> _PySet[T]:
        """防缓存击穿：Set 类型（底层 ``CollectionOps`` 入口）。

        命中直接返回；未命中则获取本方法的 stampede 锁（与
        ``LockFunction`` 业务锁**独立**），调用 ``db_loader`` 回源，
        回写缓存。其他并发 caller 在锁被持有时进入短暂的轮询重试，
        超出等待预算则返回空集，由调用方决定是否再次重试。

        Args:
            key: 缓存键
            clazz: 集合元素类型（反序列化目标）
            timeout_millis: 缓存 TTL（毫秒），同时也是 stampede 锁
                的持有超时
            db_loader: 回源加载器；返回 ``None`` 或空集表示无值
                （不写缓存）
            loader_timeout_millis: 可选 — M5.1：`db_loader` 的
                毫秒级超时。`None`（默认）= 沿用旧行为（不限时）；
                `> 0` = `db_loader` 在此时间内未完成则当作
                ``None`` 处理（不写缓存），让 caller 决定是否重试。
                超时的 loader 可能在后台继续运行（best-effort
                终止，详见 `_call_db_loader_with_timeout`）。
            negative_cache_ttl_millis: 可选 — M5.7：仅当
                `db_loader` 因 `loader_timeout_millis` **超时**而
                未返回时，写一个短 TTL 的"负缓存"标记，让后续
                caller 在 TTL 窗口内直接返回空集而不再调用 loader。
                标记是一个独立的 Redis 键
                （``__negative_set__:<key>``），而不是写入 Set 本身
                — Sets 的元素值不能用作 marker。自然返回
                ``None`` / 空集的 loader 不写负缓存。

        Returns:
            集合值；未命中且加载失败或超时时为空集；命中负缓存
            标记时同样为空集。

        Raises:
            ValueError: ``timeout_millis <= 0``、``db_loader`` 为
                ``None``、``loader_timeout_millis <= 0``，或
                ``negative_cache_ttl_millis <= 0``。
            ``db_loader`` 自身抛出的异常会原样传播。

        English
        --------
        Stampede-proof Set load (low-level ``CollectionOps`` entry).
        On cache hit, returns the cached value directly. On cache
        miss, acquires a per-key stampede lock (independent of any
        application-level ``LockFunction`` lock the caller may also
        be holding), invokes ``db_loader`` on the lock-holder, writes
        the result back to the cache, and returns. Concurrent waiters
        that lose the lock race enter a short polling loop and
        re-read the cache; if the winner hasn't published within the
        wait budget, returns ``set()`` and lets the caller decide
        whether to retry.

        M5.1: `loader_timeout_millis` adds a millisecond-level
        backstop on `db_loader`. `None` preserves legacy
        (unbounded) behavior. A timed-out loader is treated as
        ``None`` (no cache write). Exceptions from `db_loader`
        are re-raised unchanged.

        M5.7: `negative_cache_ttl_millis` writes a separate Redis
        marker key (``__negative_set__:<key>``) on TIMEOUT — Sets
        can't store a sentinel bytes value via SADD, so we use a
        sibling key with a PEXPIRE. Subsequent callers within the
        window return ``set()`` without re-invoking the loader.
        Only fires on TIMEOUT.
        """
        return self._stampede_load_set(
            key, clazz, timeout_millis, db_loader,
            wait_budget_millis=int(timeout_millis),
            loader_timeout_millis=loader_timeout_millis,
            negative_cache_ttl_millis=negative_cache_ttl_millis,
        )

    # ══════════════════════════════════════════════════════════════
    # SetFunction (high-level) — pop / difference / batch
    # ══════════════════════════════════════════════════════════════

    def get_from_set_with_lock(
        self,
        key: str,
        reference: type,
        db_loader: Callable[[], _PySet[T] | None],
        timeout_millis: int,
        *,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> _PySet[T]:
        """防缓存击穿：Set 类型（业务级便捷方法）。

        与 ``CollectionOps.get_with_lock`` 行为一致，仅参数顺序不同
        （``key, reference, db_loader, timeout_millis``），便于业务代码
        按 (资源键, 元素类型, 加载器, 超时) 的自然顺序书写。镜像
        ``cn.richie696.component.cache.function.SetFunction.getFromSetWithLock``。

        Args:
            key: 缓存键
            reference: 集合元素类型
            db_loader: 回源加载器
            timeout_millis: 缓存 TTL（毫秒）
            loader_timeout_millis: 可选 — M5.1：`db_loader` 的
                毫秒级超时。详见 `get_with_lock` 文档。
            negative_cache_ttl_millis: 可选 — M5.7：超时负缓存
                TTL；详见 `get_with_lock` 文档。

        Returns:
            集合值；未命中且加载失败或超时时为空集；命中负缓存
            标记时同样为空集。

        English
        --------
        Stampede-proof Set load (business-facing convenience). Same
        semantics as ``get_with_lock`` with the more natural
        argument order ``(key, reference, db_loader, timeout_millis)``.
        Honours both `loader_timeout_millis` (M5.1) and
        `negative_cache_ttl_millis` (M5.7).
        """
        return self._stampede_load_set(
            key, reference, timeout_millis, db_loader,
            wait_budget_millis=int(timeout_millis),
            loader_timeout_millis=loader_timeout_millis,
            negative_cache_ttl_millis=negative_cache_ttl_millis,
        )

    # ── Stampede-prevention shared helpers (M4) ────────────────────

    def _is_cached(self, key: str) -> bool:
        """EXISTS check for the Set at ``key``.

        Used as the cache-hit detector on the stampede path because
        an empty Set is a valid cached value and cannot be told apart
        from a missing key via SMEMBERS / SCARD alone.
        """
        return self._backend.raw_client().exists(self._k(key)) > 0

    # M5.7 negative marker: Sets cannot store a bytes sentinel via
    # SADD (every member is itself an element of the set), so we
    # use a separate Redis key whose existence encodes the
    # "loader timed out within the TTL window" state. The marker
    # is namespaced under `__negative_set__:` and uses
    # `make_key` so it picks up the same prefix as the user key.
    def _negative_set_marker_key(self, key: str) -> str:
        return self._backend.make_key(f"__negative_set__:{key}")

    def _is_negative_set_cached(self, key: str) -> bool:
        """True if the M5.7 negative-cache marker exists for `key`."""
        return (
            self._backend.raw_client().exists(
                self._negative_set_marker_key(key)
            )
            > 0
        )

    def _write_negative_set_marker(
        self, key: str, ttl_millis: int
    ) -> None:
        """Write the M5.7 negative-cache marker for `key` with `ttl_millis`."""
        self._backend.raw_client().set(
            self._negative_set_marker_key(key),
            b"1",
            px=int(ttl_millis),
        )

    def _stampede_load_set(
        self,
        key: str,
        clazz: type,
        timeout_millis: int,
        db_loader: Callable[[], _PySet[T] | None],
        *,
        wait_budget_millis: int,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> _PySet[T]:
        """Shared implementation for `get_with_lock` + `get_from_set_with_lock`.

        Returns the cached set (on hit, even when empty) or the loaded
        set (after a successful db_loader round-trip). Returns an
        empty set if the db_loader returned ``None`` / empty, timed
        out (M5.1), or if a competing stampede lock holder didn't
        publish within the wait budget.

        M5.7: on a TIMEOUT, optionally writes a separate
        ``__negative_set__:<key>`` marker with
        `negative_cache_ttl_millis`; subsequent callers within the
        window return ``set()`` without re-invoking the loader. Only
        fires on TIMEOUT, never on a natural ``None`` / empty set
        from the loader.
        """
        if timeout_millis <= 0:
            raise ValueError("timeout_millis must be > 0")
        if db_loader is None:
            raise ValueError("db_loader is required")
        if loader_timeout_millis is not None and loader_timeout_millis <= 0:
            raise ValueError("loader_timeout_millis must be > 0 (or None)")
        if negative_cache_ttl_millis is not None and negative_cache_ttl_millis <= 0:
            raise ValueError(
                "negative_cache_ttl_millis must be > 0 (or None)"
            )

        # 1. Fast path: cache hit (EXISTS, not SCARD, so a cached
        #    empty Set is honoured as a valid value). M5.7: a
        #    negative-cache marker is also a hit (returns `set()`).
        if self._is_cached(key):
            return self.get(key, clazz)
        if (
            negative_cache_ttl_millis is not None
            and negative_cache_ttl_millis > 0
            and self._is_negative_set_cached(key)
        ):
            return set()

        # 2. Cache miss: try to acquire the per-key stampede lock.
        request_id = uuid.uuid4().hex
        lock_key = _make_stampede_lock_key(self._backend, key)
        client = self._backend.raw_client()
        if not _stampede_acquire(client, lock_key, request_id, timeout_millis):
            return self._wait_for_set_publication(
                key, clazz, wait_budget_millis=wait_budget_millis
            )

        try:
            # 3. We hold the stampede lock — re-check the cache.
            if self._is_cached(key):
                return self.get(key, clazz)
            # 4. Still missing → invoke the db_loader, optionally
            #    with a timeout. `_call_db_loader_with_timeout_ex`
            #    returns `(value, timed_out)`; we use the flag to
            #    decide whether to write a negative-cache marker
            #    (M5.7).
            value, was_timed_out = _call_db_loader_with_timeout_ex(
                db_loader, loader_timeout_millis
            )
            if not value:
                # Loader returned None / empty. M5.7: on TIMEOUT,
                # write a separate negative marker so subsequent
                # callers see this key as already-cached `set()`.
                if (
                    was_timed_out
                    and negative_cache_ttl_millis is not None
                    and negative_cache_ttl_millis > 0
                ):
                    try:
                        self._write_negative_set_marker(
                            key, int(negative_cache_ttl_millis),
                        )
                    except Exception:
                        pass
                return set()
            # 5. Publish: DEL + SADD + PEXPIRE, no anti-avalanche
            #    offset (the `*_with_lock` path is the canonical
            #    write path and the caller is responsible for any
            #    TTL jitter policy). A successful publish
            #    transparently clears any stale negative-cache
            #    marker — the user can call again with a fresh
            #    loader, no leftover "negative" state to confuse
            #    the next caller.
            try:
                client.delete(self._negative_set_marker_key(key))
            except Exception:
                pass
            encoded = self._encode_set(value)
            pipe = client.pipeline(transaction=False)
            pipe.delete(self._k(key))
            if encoded:
                pipe.sadd(self._k(key), *encoded)
            if timeout_millis and timeout_millis > 0:
                pipe.pexpire(self._k(key), int(timeout_millis))
            pipe.execute()
            return value
        finally:
            try:
                _stampede_release(client, lock_key, request_id)
            except Exception:
                # Release failures are non-fatal: the lock will
                # expire on its own via the PX TTL.
                pass

    def _wait_for_set_publication(
        self, key: str, clazz: type, *, wait_budget_millis: int
    ) -> _PySet[T]:
        """Poll the cache for up to `wait_budget_millis` (50ms cadence).

        Returns the published set, or an empty set if no one
        published within the budget. A published negative-cache
        marker is also surfaced as ``set()`` (the winner hit a
        `loader_timeout_millis` timeout and opted into M5.7).
        """
        deadline = time.monotonic() + (wait_budget_millis / 1000.0)
        poll_interval_seconds = 0.05
        while time.monotonic() < deadline:
            time.sleep(poll_interval_seconds)
            if self._is_cached(key):
                return self.get(key, clazz)
            if self._is_negative_set_cached(key):
                return set()
        return set()

    def get_from_set(self, key: str, reference: type) -> _PySet[T]:
        return self.get(key, reference)

    def pop_data_from_set(self, key: str, reference: type) -> Any:
        return self.pop(key, reference)

    def pop_members_from_set(
        self, key: str, count: int, reference: type
    ) -> _PySet[T]:
        return self.pop_many(key, count, reference)

    def difference_from_set(
        self, keys: Collection[str], reference: type
    ) -> _PySet[T]:
        """SDIFF across multiple keys (left-to-right precedence)."""
        if not keys:
            return set()
        namespaced = [self._k(k) for k in keys]
        raws = self._backend.raw_client().sdiff(*namespaced)
        if not raws:
            return set()
        return self._decode_set(list(raws), reference)

    def difference_from_set_with_key(
        self, key: str, other_keys: Collection[str], reference: type
    ) -> _PySet[T]:
        """SDIFF `key` minus the union of `other_keys`."""
        if not other_keys:
            return self.get_from_set(key, reference)
        namespaced = [self._k(k) for k in other_keys]
        raws = self._backend.raw_client().sdiff(self._k(key), *namespaced)
        if not raws:
            return set()
        return self._decode_set(list(raws), reference)

    def difference_and_store_from_set(
        self, compare_keys: Collection[str], dest_key: str
    ) -> int:
        """SDIFFSTORE; returns the cardinality of the stored set."""
        if not compare_keys:
            return 0
        namespaced = [self._k(k) for k in compare_keys]
        return int(
            self._backend.raw_client().sdiffstore(
                self._k(dest_key), *namespaced
            )
        )

    def exists_in_set(self, key: str, value: Any) -> bool:
        return self.exists(key, value)

    def batch_add_to_set(self, mapping: dict[str, _PySet]) -> None:
        """Bulk SADD across many Sets; NOT atomic (per the Java doc)."""
        if not mapping:
            return
        client = self._backend.raw_client()
        pipe = client.pipeline(transaction=False)
        for key, values in mapping.items():
            encoded = self._encode_set(values)
            if encoded:
                pipe.sadd(self._k(key), *encoded)
        pipe.execute()

    def add_set(self, key: str, values: _PySet) -> None:
        if not values:
            return
        self._backend.raw_client().sadd(
            self._k(key), *self._encode_set(values)
        )

    def add_set_item(self, key: str, *value: Any) -> None:
        if not value:
            return
        self._backend.raw_client().sadd(
            self._k(key), *[encode_value(v) for v in value]
        )

    def remove_set_item(self, key: str, *values: Any) -> None:
        self.remove(key, *values)

    def get_set_size(self, key: str) -> int:
        return self.size(key)


__all__ = ["RedisCollectionManager"]
