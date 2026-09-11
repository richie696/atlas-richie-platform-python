"""分布式锁操作接口。

中文
----
分布式锁操作接口。
提供乐观锁、悲观锁、自动续期锁及批量锁能力。

English
--------
Distributed lock ops interface.

Mirrors `cn.richie696.component.cache.ops.LockOps`. Provides
optimistic, pessimistic, and auto-renewal locks plus batch locks.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Collection, Protocol

from ..contracts.distributed_lock import DistributedBatchLock, DistributedLock


class LockOps(Protocol):
    """中文
    ----
    分布式锁操作接口。提供乐观锁、悲观锁、自动续期锁及批量锁能力。

    English
    --------
    Distributed lock ops. Provides optimistic, pessimistic,
    auto-renewal, and batch locks.
    """

    @abstractmethod
    def optimistic(self, key: str) -> DistributedLock:
        """中文
        ----
        获取乐观锁，使用默认 TTL。

        English
        --------
        Optimistic lock; default TTL.
        """
        ...

    @abstractmethod
    def optimistic_with_ttl(self, key: str, seconds: int) -> DistributedLock:
        """中文
        ----
        获取乐观锁，`seconds` 秒后过期。

        English
        --------
        Optimistic lock; expire in `seconds`.
        """
        ...

    @abstractmethod
    def optimistic_with_renewal(self, key: str, seconds: int) -> DistributedLock:
        """中文
        ----
        获取乐观锁并自动续期（`seconds` 必须 ≥ 3）。

        English
        --------
        Optimistic lock + watchdog renewal (must be ≥ 3 seconds).
        """
        ...

    @abstractmethod
    def pessimistic(self, key: str) -> DistributedLock:
        """中文
        ----
        获取悲观锁，使用默认 TTL；阻塞直到获取成功或被中断。

        English
        --------
        Pessimistic lock; default TTL; blocks until acquired or
        interrupted.
        """
        ...

    @abstractmethod
    def pessimistic_with_ttl(self, key: str, seconds: int) -> DistributedLock:
        """中文
        ----
        获取悲观锁，`seconds` 秒后过期（后端支持时 `-1` 表示不过期）。

        English
        --------
        Pessimistic lock with `seconds` TTL (`-1` means no expiry if
        backend supports).
        """
        ...

    @abstractmethod
    def pessimistic_with_renewal(self, key: str, seconds: int) -> DistributedLock:
        """中文
        ----
        获取悲观锁并自动续期（`seconds` 必须 ≥ 3）。

        English
        --------
        Pessimistic lock + watchdog renewal (must be ≥ 3 seconds).
        """
        ...

    @abstractmethod
    def batch(self, keys: Collection[str], timeout: int, unit) -> DistributedBatchLock:
        """中文
        ----
        批量获取多个 key 的锁；`unit` 为时间单位枚举。

        English
        --------
        Acquire all keys as a batch; `unit` is a time-unit enum.
        """
        ...


__all__ = ["LockOps"]
