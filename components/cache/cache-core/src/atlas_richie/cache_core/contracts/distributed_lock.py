"""分布式锁与批量锁接口。
----
分布式锁句柄与批量锁句柄契约。锁的接口属于核心契约，
具体实现位于 Redis 包中。

English
--------
Distributed lock + batch lock contracts.

Mirrors `cn.richie696.component.cache.redis.manage.CacheLock` and
`CacheBatchLock`. Moved to core because the lock interface is a
core contract — concrete implementations live in the Redis package.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Collection, Protocol


class DistributedLock(Protocol):
    """分布式锁句柄。

    English
    --------
    Distributed lock handle. Mirrors `redis.manage.CacheLock`.
    """

    @abstractmethod
    def try_acquire(self) -> bool:
        """尝试获取锁（非阻塞）。

        English
        --------
        Try to acquire; non-blocking.
        """
        ...

    @abstractmethod
    def release(self) -> bool:
        """释放锁。

        Returns:
            释放是否成功（即锁是否仍由该句柄持有）。

        English
        --------
        Release the lock.

        Returns:
            Whether the release was successful (i.e., the lock was
            still held by this handle).
        """
        ...


class DistributedBatchLock(Protocol):
    """批量分布式锁。

    English
    --------
    Batch distributed lock. Mirrors `redis.manage.CacheBatchLock`.
    """

    @abstractmethod
    def release_all(self) -> int:
        """释放所有锁。

        Returns:
            已释放的锁数量。

        English
        --------
        Release all locks.

        Returns:
            The number of locks released.
        """
        ...


__all__ = ["DistributedLock", "DistributedBatchLock"]
