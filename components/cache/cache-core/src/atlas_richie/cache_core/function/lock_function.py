"""分布式锁缓存操作函数。
----
分布式锁 API：仅暴露乐观锁、悲观锁及带续期获取。
业务侧统一使用 `DistributedLock` 包装，通过
`optimistic_lock(key, time)` / `pessimistic_lock(key, time)` 获取，
可选 `lock_with_renewal(key, seconds, optimistic)` 带续期。

English
--------
Distributed lock cache function (high-level, built on `LockOps`).

Mirrors `cn.richie696.component.cache.function.LockFunction`. All three
methods return the framework-level `DistributedLock` handle — Java's
`cn.richie696.component.cache.redis.manage.CacheLock` is replaced by
the abstract `DistributedLock` Protocol so the function is backend-
agnostic.

For `lock_with_renewal`, the renewal watchdog is **always on** when
`seconds >= 3` (matches Java's behavior); callers do not need to
distinguish whether renewal is active — the handle releases the lock
exactly once and cancels the watchdog in the same step.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from ..contracts.distributed_lock import DistributedLock


class LockFunction(Protocol):
    """分布式锁 API。

    仅暴露乐观锁、悲观锁及带续期获取。业务侧统一使用 `DistributedLock`
    包装，通过 `optimistic_lock(key, time)` / `pessimistic_lock(key, time)`
    获取，可选 `lock_with_renewal(key, seconds, optimistic)` 带续期。

    English
    --------
    Distributed lock API exposing only optimistic, pessimistic, and
    renewal-capable acquisition. Business code uniformly consumes a
    `DistributedLock` handle.
    """

    @abstractmethod
    def optimistic_lock(self, key: str, time_seconds: int) -> DistributedLock:
        """乐观锁（试一次，失败即返回）。

        Args:
            key: 资源键
            time_seconds: 占锁时间（秒）

        Returns:
            加锁结果（未拿到锁时 `try_acquire()` 返回 `False`）。

        English
        --------
        Optimistic lock — try once, return on failure.

        Args:
            key: 资源键
            time_seconds: 占锁时间（秒）

        Returns:
            The lock handle. If the lock was not acquired,
            `try_acquire()` returns `False`.
        """
        ...

    @abstractmethod
    def pessimistic_lock(self, key: str, time_seconds: int) -> DistributedLock:
        """悲观锁（阻塞直到获取或中断）。

        Args:
            key: 资源键
            time_seconds: 占锁时间（秒），`-1` 表示不设过期（若底层支持）

        English
        --------
        Pessimistic lock — block until acquired or interrupted.

        Args:
            key: 资源键
            time_seconds: 占锁时间（秒），`-1` 表示不设过期（若底层支持）
        """
        ...

    @abstractmethod
    def lock_with_renewal(
        self, key: str, seconds: int, optimistic: bool
    ) -> DistributedLock:
        """带续期能力的加锁（先按乐观/悲观获取，成功则启动续期任务）。

        Args:
            key: 资源键
            seconds: 锁过期时间（秒），不能小于 3
            optimistic: `True` 乐观锁获取，`False` 悲观锁获取

        English
        --------
        Lock with renewal — acquire optimistically or pessimistically,
        then start a renewal task on success.
        """
        ...


__all__ = ["LockFunction"]
