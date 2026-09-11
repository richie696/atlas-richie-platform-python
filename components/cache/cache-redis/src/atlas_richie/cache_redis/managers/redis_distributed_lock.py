"""Redis 后端的分布式锁句柄。
----
``RedisLockManager`` 负责实际的锁获取；这里的句柄类是持有获取结果的状态
记录，并为业务代码提供简洁的 ``try_acquire()`` / ``release()`` API。
在 Python 中镜像 ``cn.richie696.component.cache.redis.manage.CacheLock`` +
``CacheBatchLock`` 的结构。

锁释放通过 Lua 脚本（基于 ``request_id`` 的 compare-and-delete）保证
**原子性**：只有原始获取者才能释放锁。这避免了一个过期的持有者错误释放
已被另一个请求在原始 TTL 过期后重新获取的锁。

English
--------
Redis-backed distributed lock handles.

The `RedisLockManager` does the actual acquisition; the handle
classes here are stateful records that hold the acquisition result
and provide a clean `try_acquire()` / `release()` API to business
code. Mirrors `cn.richie696.component.cache.redis.manage.CacheLock`
+ `CacheBatchLock` 1:1 in Python.

Lock release is **atomic** via a Lua script (compare-and-delete by
`request_id`): only the original acquirer can release the lock.
This prevents a stale holder from accidentally releasing a lock
that has been re-acquired by a different request after the original
TTL expired.
"""

from __future__ import annotations

import threading
import uuid
from typing import List, Optional

from atlas_richie.cache_core.contracts.distributed_lock import (
    DistributedBatchLock,
    DistributedLock,
)

from ..redis_distributed_cache import RedisDistributedCache


# Atomic release: only the holder of the matching `request_id` can
# delete the lock. Returns 1 on success, 0 if the lock was either
# absent or held by a different request.
_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisDistributedLock(DistributedLock):
    """单个分布式锁句柄。
    ----
    由 ``RedisLockManager`` 创建并返回给业务代码。管理器已经尝试过
    获取；``try_acquire()`` 仅是对缓存结果的查询。

    English
    --------
    A single distributed lock handle.

    Created by `RedisLockManager` and returned to business code. The
    manager has already attempted acquisition; `try_acquire()` is
    just a lookup against the cached result.
    """

    __slots__ = (
        "_backend",
        "_key",
        "_request_id",
        "_acquired",
        "_ttl_seconds",
        "_renewal_handle",
        "_released",
    )

    def __init__(
        self,
        backend: RedisDistributedCache,
        key: str,
        request_id: str,
        acquired: bool,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        self._backend = backend
        self._key = key
        self._request_id = request_id
        self._acquired = acquired
        self._ttl_seconds = ttl_seconds
        self._renewal_handle: Optional["_LockRenewal"] = None
        self._released = False

    @property
    def key(self) -> str:
        return self._key

    @property
    def request_id(self) -> str:
        return self._request_id

    @property
    def ttl_seconds(self) -> Optional[int]:
        return self._ttl_seconds

    def try_acquire(self) -> bool:
        """Return the cached acquisition result.

        Per the cache-core `DistributedLock` Protocol, this is
        non-blocking. The manager has already attempted acquisition
        before returning this handle; `try_acquire()` simply reports
        the outcome.
        """
        return self._acquired

    def release(self) -> bool:
        """Atomic compare-and-delete release.

        Returns `True` if the lock was still held by this handle
        (i.e., the `request_id` matched and we successfully
        `DEL`'d the Redis key). Returns `False` if the lock was
        already gone or held by someone else.
        """
        if self._released:
            return False
        self._released = True
        if not self._acquired:
            return False
        # Stop the renewal watchdog first so it does not race with
        # the release.
        if self._renewal_handle is not None:
            self._renewal_handle.stop()
        ns_key = self._backend.make_key(self._key)
        try:
            result = self._backend.raw_client().eval(
                _RELEASE_LUA, 1, ns_key, self._request_id
            )
        except Exception:
            return False
        return int(result) == 1

    def start_renewal(self, interval_seconds: float) -> None:
        """Start a daemon watchdog that periodically extends the TTL.

        Called by the manager when the lock was acquired with
        `_with_renewal`. The watchdog stops itself when the lock is
        released.
        """
        if self._renewal_handle is not None or not self._acquired:
            return
        if self._ttl_seconds is None:
            return
        self._renewal_handle = _LockRenewal(
            backend=self._backend,
            key=self._key,
            request_id=self._request_id,
            ttl_seconds=self._ttl_seconds,
            interval_seconds=interval_seconds,
        )
        self._renewal_handle.start()

    def __enter__(self) -> "RedisDistributedLock":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class RedisDistributedBatchLock(DistributedBatchLock):
    """A batch of lock handles acquired together.

    `release_all()` releases each lock; the return value is the
    number of locks successfully released.
    """

    __slots__ = ("_locks",)

    def __init__(self, locks: List[RedisDistributedLock]) -> None:
        self._locks = list(locks)

    def release_all(self) -> int:
        n = 0
        for lock in self._locks:
            if lock.release():
                n += 1
        return n

    @property
    def locks(self) -> List[RedisDistributedLock]:
        return list(self._locks)


# ── Renewal watchdog ──────────────────────────────────────────────────


class _LockRenewal:
    """Background thread that periodically extends the lock's TTL.

    Mirrors the Java `RFencedLock` watchdog. The renewal loop:

    1. Sleep for `interval_seconds` (default: `ttl_seconds / 3`).
    2. Compare-and-extend the TTL on the Redis key (only if the
       `request_id` still matches — this prevents a stale watchdog
       from extending someone else's lock after expiry + re-acquire).
    3. On stop, exit the loop.

    Threading: the watchdog is a daemon thread; it dies with the
    process. It holds no Python-side state beyond the lock key +
    request_id, so it is safe to GC.
    """

    # Compare-and-extend: only extend if the lock is still held by
    # this `request_id`.
    _EXTEND_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

    def __init__(
        self,
        backend: RedisDistributedCache,
        key: str,
        request_id: str,
        ttl_seconds: int,
        interval_seconds: float,
    ) -> None:
        self._backend = backend
        self._key = key
        self._request_id = request_id
        self._ttl_seconds = int(ttl_seconds)
        self._interval = float(interval_seconds)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._pump,
            name=f"lock-renewal:{self._key}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _pump(self) -> None:
        try:
            while not self._stop_event.is_set():
                # Wait for the next renewal window. `wait` returns
                # True if the event is set (i.e. we should exit).
                if self._stop_event.wait(self._interval):
                    return
                ns_key = self._backend.make_key(self._key)
                try:
                    self._backend.raw_client().eval(
                        self._EXTEND_LUA,
                        1,
                        ns_key,
                        self._request_id,
                        str(self._ttl_seconds * 1000),
                    )
                except Exception:
                    # Connection lost or key evicted; exit silently.
                    return
        except Exception:
            return


__all__ = [
    "RedisDistributedLock",
    "RedisDistributedBatchLock",
]
