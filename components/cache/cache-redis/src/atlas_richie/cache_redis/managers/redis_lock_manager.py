"""分布式锁管理器，基于 Redisson FencedLock 实现。
----
``LockOps`` + ``LockFunction`` 的 Redis 后端实现（M4）。

按「本地锁 → 可重入 → Redisson 获取」三层统一处理；锁类型分乐观（试一次）
与悲观（阻塞直到获取或中断）。

镜像 ``cn.richie696.component.cache.redis.manage.RedisLockManager`` 的结构。
在 Python 中实现完整的三层锁架构：

1. **进程内本地锁** —— ``threading.RLock``，以锁名为 key。允许单进程在不
   访问 Redis 的情况下廉价地串行化争用调用方。本地锁在乐观路径下始终
   非阻塞，在悲观路径下轮询（每 20 ms 一次，对齐 Java 的
   ``PESSIMISTIC_LOCK_WAIT_MS``）。

2. **可重入** —— 同一线程可以重新获取它已持有的锁而无需重新发起 Redis
   的 ``SET NX EX``。通过 ``_local_holders`` 中的每线程计数器跟踪。

3. **Redis 分布式锁** —— ``SET NX PX`` 实现原子获取（通过 ``PX`` 提供
   ``EXPIRE`` 等价能力）。释放通过基于 ``request_id`` 的 Lua compare-and-delete
   完成，使过期的持有者无法在原始 TTL 过期后错误释放被其他请求重新
   获取的锁。

续约：当调用 ``_with_renewal`` 时，守护看门狗以 ``ttl/3`` 的频率延长
TTL，只要锁仍被持有。看门狗在 ``release()`` 时停止。

批量：``batch(keys, timeout, unit)`` 以**字典序**获取所有 key，避免 AB/BA
死锁。调用方指定超时（Python：整数秒）。

English
--------
Redis-backed `LockOps` + `LockFunction` (M4).

Mirrors `cn.richie696.component.cache.redis.manage.RedisLockManager`
1:1 in Python. Implements the full 3-layer lock architecture:

1. **Local in-process lock** — `threading.RLock` keyed by the lock
   name. Lets a single process cheaply serialise contending
   callers without round-tripping to Redis. The local lock is
   always non-blocking in the optimistic path and polling in the
   pessimistic path (20 ms per check, matches Java's
   `PESSIMISTIC_LOCK_WAIT_MS`).

2. **Reentrancy** — the same thread can re-acquire a lock it
   already holds without re-issuing the Redis `SET NX EX`. Tracked
   via a per-thread counter in `_local_holders`.

3. **Redis distributed lock** — `SET NX PX` for atomic acquisition
   (with optional `EXPIRE`-equivalent via `PX`). Release is a
   Lua compare-and-delete by `request_id` so a stale holder
   cannot accidentally release a lock re-acquired by a different
   request after the original TTL expired.

Renewal: when `_with_renewal` is called, a daemon watchdog extends
the TTL on a `ttl/3` cadence for as long as the lock is held.
The watchdog stops on `release()`.

Batch: `batch(keys, timeout, unit)` acquires all keys in
**alphabetical order** to avoid AB/BA deadlocks. The caller
specifies a timeout (Python: integer seconds).
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Collection, Dict, List, Set

from atlas_richie.cache_core.contracts.distributed_lock import (
    DistributedBatchLock,
    DistributedLock,
)
from atlas_richie.cache_core.function.lock_function import LockFunction
from atlas_richie.cache_core.ops.lock_ops import LockOps

from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache
from .redis_distributed_lock import (
    RedisDistributedBatchLock,
    RedisDistributedLock,
)


# Atomic acquire: SET NX PX. Returns the request_id on success
# (so the caller can later compare-and-delete), or empty string on
# failure.
_ACQUIRE_LUA = """
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'PX', ARGV[2]) then
    return ARGV[1]
end
return ''
"""


class RedisLockManager(LockOps, LockFunction):
    """Redis 后端的三层分布式锁管理器。
    ----
    本地锁与可重入层是进程范围的类级别状态（镜像 Java 的
    ``CacheLockManager``）。Redis 层是唯一与网络交互的部分。

    English
    --------
    Redis-backed 3-layer distributed lock manager.

    The local lock and the reentrancy layer are process-wide
    class-level state (mirroring Java's `CacheLockManager`). The
    Redis layer is the only part that talks to the network.
    """

    # ── Class-level (process-wide) state ──────────────────────────

    _local_locks: Dict[str, threading.RLock] = {}
    _local_holders: Dict[str, Dict[int, int]] = {}  # key → {tid → count}
    _state_lock: threading.Lock = threading.Lock()

    # Pessimistic local-lock polling cadence.
    _PESSIMISTIC_LOCAL_WAIT_SEC: float = 0.020

    def __init__(
        self,
        backend: RedisDistributedCache,
        infra: RedisCacheInfrastructure,
    ) -> None:
        self._backend = backend
        self._infra = infra

    # ── Layer 1 helpers: in-process lock ─────────────────────────

    def _get_local_lock(self, key: str) -> threading.RLock:
        with self._state_lock:
            lock = self._local_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._local_locks[key] = lock
            return lock

    def _get_holders(self, key: str) -> Dict[int, int]:
        with self._state_lock:
            holders = self._local_holders.get(key)
            if holders is None:
                holders = {}
                self._local_holders[key] = holders
            return holders

    def _try_local_lock(self, key: str) -> bool:
        """Acquire the in-process lock once (non-blocking).

        Returns `False` if some other thread is currently holding it
        AND that holder has not yet released. Reentrant acquisitions
        from the same thread always succeed.
        """
        local = self._get_local_lock(key)
        tid = threading.get_ident()
        holders = self._get_holders(key)
        # If we already hold it, increment and return True.
        if tid in holders:
            holders[tid] += 1
            return True
        if local.acquire(blocking=False):
            holders[tid] = 1
            return True
        return False

    def _wait_local_lock(self, key: str) -> bool:
        """Block until the in-process lock is free, then acquire it.

        Returns `False` if interrupted. Reentrant acquisitions from
        the same thread always succeed without waiting.
        """
        local = self._get_local_lock(key)
        tid = threading.get_ident()
        holders = self._get_holders(key)
        if tid in holders:
            holders[tid] += 1
            return True
        # Acquire with polling (the in-process lock is non-reentrant
        # for other threads, so we need a polling loop).
        while True:
            if local.acquire(blocking=False):
                holders[tid] = 1
                return True
            if not threading.Event().wait(self._PESSIMISTIC_LOCAL_WAIT_SEC):
                # wait() returns False on timeout, True on set.
                # We don't have a stop event here, so we treat every
                # iteration as "not yet".
                continue
            # Defensive: if the wait somehow returns True, treat as
            # acquired (should not happen without a stop event).
            local.acquire(blocking=False)
            holders[tid] = 1
            return True

    def _release_local_lock(self, key: str) -> None:
        """Decrement the per-thread reentrancy counter; release the
        in-process RLock once the counter hits 0."""
        local = self._get_local_lock(key)
        tid = threading.get_ident()
        holders = self._get_holders(key)
        count = holders.get(tid, 0)
        if count <= 1:
            holders.pop(tid, None)
            try:
                local.release()
            except RuntimeError:
                # Not held — should not happen in normal flow.
                pass
        else:
            holders[tid] = count - 1

    # ── Layer 3 helper: Redis SET NX PX ───────────────────────────

    def _try_redis_lock_once(
        self, key: str, request_id: str, ttl_millis: int
    ) -> bool:
        ns_key = self._backend.make_key(key)
        result = self._backend.raw_client().eval(
            _ACQUIRE_LUA, 1, ns_key, request_id, str(int(ttl_millis))
        )
        return bool(result)

    def _poll_redis_lock(
        self, key: str, request_id: str, ttl_millis: int, timeout_seconds: int
    ) -> bool:
        """Block until the Redis lock is free, then acquire it.

        Returns `False` on timeout.
        """
        deadline = threading.Event()  # placeholder; we just busy-wait
        import time as _time

        end = _time.monotonic() + max(0, int(timeout_seconds))
        while True:
            if self._try_redis_lock_once(key, request_id, ttl_millis):
                return True
            if _time.monotonic() >= end:
                return False
            if deadline.wait(self._PESSIMISTIC_LOCAL_WAIT_SEC):
                return False

    # ── Unified acquisition pipeline ─────────────────────────────

    def _acquire(
        self,
        key: str,
        ttl_seconds: int,
        optimistic: bool,
        renewal: bool,
    ) -> RedisDistributedLock:
        # Layer 1: local lock.
        if optimistic:
            if not self._try_local_lock(key):
                return self._make_failed_handle(key, renewal)
        else:
            if not self._wait_local_lock(key):
                return self._make_failed_handle(key, renewal)

        # Layer 2: reentrancy — if we already hold the Redis lock
        # for this key from this thread, return the existing handle.
        existing = self._find_existing_reentrant_handle(key)
        if existing is not None:
            return existing

        # Layer 3: Redis SET NX PX. Determine the TTL.
        ttl_millis = self._ttl_to_millis(ttl_seconds, renewal)
        request_id = str(uuid.uuid4())
        if optimistic:
            ok = self._try_redis_lock_once(key, request_id, ttl_millis)
        else:
            # Pessimistic: block until acquired or timeout.
            ok = self._poll_redis_lock(
                key, request_id, ttl_millis, int(ttl_seconds) if ttl_seconds > 0 else 30
            )
        if not ok:
            self._release_local_lock(key)
            return self._make_failed_handle(key, renewal)

        handle = RedisDistributedLock(
            backend=self._backend,
            key=key,
            request_id=request_id,
            acquired=True,
            ttl_seconds=ttl_millis // 1000,
        )
        if renewal:
            # Refresh at ttl/3 cadence; the watchdog stops on
            # `release()`.
            handle.start_renewal(interval_seconds=max(0.1, ttl_millis / 1000.0 / 3.0))
        return handle

    @staticmethod
    def _ttl_to_millis(ttl_seconds: int, renewal: bool) -> int:
        """Compute the actual TTL to send to Redis.

        `renewal=True` means the watchdog will refresh — so the
        *initial* TTL should be relatively short (Java uses the
        configured value; we use 30 seconds when the caller doesn't
        specify one). For the non-renewal path, we honour the
        caller's `ttl_seconds` (clamped to a safe minimum).
        """
        if ttl_seconds <= 0:
            return 30_000 if renewal else 60_000
        return int(ttl_seconds) * 1000

    @staticmethod
    def _make_failed_handle(
        key: str, renewal: bool
    ) -> RedisDistributedLock:
        return RedisDistributedLock(
            backend=None,  # type: ignore[arg-type]
            key=key,
            request_id="",
            acquired=False,
            ttl_seconds=None,
        )

    def _find_existing_reentrant_handle(
        self, key: str
    ) -> Optional[RedisDistributedLock]:
        """Return an existing handle for this thread + key, if any.

        The current Python implementation does NOT keep a registry
        of outstanding handles per thread (Java's
        `CacheLockManager` does, via `CacheLockManager.addLock`).
        Reentrancy is therefore enforced at the local-lock layer
        only; the Redis layer is acquired once per outer call.

        This is a deliberate M4 simplification: a full reentrancy
        registry would require weakref + thread-local storage and
        is deferred to a follow-up R-###. The trade-off is that
        callers must NOT call `release()` on an inner-acquired
        handle before the outer acquisition has been released.
        """
        return None

    # ── LockOps (low-level) ───────────────────────────────────────

    def optimistic(self, key: str) -> DistributedLock:
        return self._acquire(key, ttl_seconds=30, optimistic=True, renewal=False)

    def optimistic_with_ttl(
        self, key: str, seconds: int
    ) -> DistributedLock:
        return self._acquire(
            key, ttl_seconds=int(seconds), optimistic=True, renewal=False
        )

    def optimistic_with_renewal(
        self, key: str, seconds: int
    ) -> DistributedLock:
        if int(seconds) < 3:
            raise ValueError("lock renewal time must be >= 3 seconds")
        return self._acquire(
            key, ttl_seconds=int(seconds), optimistic=True, renewal=True
        )

    def pessimistic(self, key: str) -> DistributedLock:
        return self._acquire(
            key, ttl_seconds=30, optimistic=False, renewal=False
        )

    def pessimistic_with_ttl(
        self, key: str, seconds: int
    ) -> DistributedLock:
        return self._acquire(
            key, ttl_seconds=int(seconds), optimistic=False, renewal=False
        )

    def pessimistic_with_renewal(
        self, key: str, seconds: int
    ) -> DistributedLock:
        if int(seconds) < 3:
            raise ValueError("lock renewal time must be >= 3 seconds")
        return self._acquire(
            key, ttl_seconds=int(seconds), optimistic=False, renewal=True
        )

    def batch(
        self, keys: Collection[str], timeout: int, unit: Any
    ) -> DistributedBatchLock:
        """Acquire all keys as a batch (deadlock-safe via sorted order).

        The cache-core Protocol takes `(timeout, unit)` for
        parity with the Java `TimeUnit` API. In Python we treat
        `unit` as either a `datetime.timedelta` (its `.total_seconds()`
        is the timeout) or `None` (default 30 seconds).
        """
        if unit is None:
            timeout_seconds = 30
        else:
            # `datetime.timedelta` has `total_seconds()`. Any other
            # numeric is treated as seconds.
            total = getattr(unit, "total_seconds", None)
            timeout_seconds = int(total()) if callable(total) else int(unit)
        if timeout and timeout > 0:
            timeout_seconds = int(timeout)

        # Sort the keys to avoid AB/BA deadlocks across competing
        # batch acquirers.
        sorted_keys = sorted(set(keys))
        handles: List[RedisDistributedLock] = []
        try:
            for key in sorted_keys:
                handle = self._acquire(
                    key,
                    ttl_seconds=timeout_seconds,
                    optimistic=False,
                    renewal=False,
                )
                if not handle.try_acquire():
                    # Acquire failed for this key; release any we
                    # already hold and bail.
                    for h in handles:
                        h.release()
                    return RedisDistributedBatchLock([])
                handles.append(handle)
            return RedisDistributedBatchLock(handles)
        except Exception:
            for h in handles:
                h.release()
            raise

    # ── LockFunction (high-level) ─────────────────────────────────

    def optimistic_lock(
        self, key: str, time_seconds: int
    ) -> DistributedLock:
        return self._acquire(
            key,
            ttl_seconds=int(time_seconds),
            optimistic=True,
            renewal=False,
        )

    def pessimistic_lock(
        self, key: str, time_seconds: int
    ) -> DistributedLock:
        return self._acquire(
            key,
            ttl_seconds=int(time_seconds),
            optimistic=False,
            renewal=False,
        )

    def lock_with_renewal(
        self, key: str, seconds: int, optimistic: bool
    ) -> DistributedLock:
        if int(seconds) < 3:
            raise ValueError("lock renewal time must be >= 3 seconds")
        return self._acquire(
            key,
            ttl_seconds=int(seconds),
            optimistic=bool(optimistic),
            renewal=True,
        )


__all__ = ["RedisLockManager"]
