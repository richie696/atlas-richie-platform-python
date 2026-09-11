"""有界队列（Bounded FIFO Queue）管理接口。

中文
----
有界队列（Bounded FIFO Queue）管理接口。
通过 `GlobalCache.queue()` 获取实例。创建后容量默认不可变；扩容仅能
通过 `BoundedQueue.grow()`（单次 ×2，封顶
`BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING`）。

English
--------
Bounded FIFO queue management interface.

Mirrors `cn.richie696.component.cache.ops.BoundedQueueOps`. Acquired
via `GlobalCache.queue()`. Capacity is fixed at creation; can be
doubled via `grow()` up to `BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING`.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol, TypeVar

from ..operations.bounded_list_capacity_limits import BoundedListCapacityLimits
from ..operations.bounded_queue import BoundedQueue

T = TypeVar("T")


class BoundedQueueOps(Protocol):
    """中文
    ----
    有界队列（Bounded FIFO Queue）管理接口。通过 `GlobalCache.queue()`
    获取实例。创建后容量默认不可变；扩容仅能通过 `BoundedQueue.grow()`
    （单次 ×2，封顶 `BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING`）。

    English
    --------
    Bounded FIFO queue management ops. Acquired via
    `GlobalCache.queue()`. Capacity is fixed at creation; can be doubled
    via `BoundedQueue.grow()` up to
    `BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING`.
    """

    @abstractmethod
    def create(self, key: str, max_len: int, clazz: type[T]) -> BoundedQueue[T]:
        """中文
        ----
        创建有界队列。同一 key 已存在时抛异常。

        Args:
            key: 队列 key
            max_len: 队列最大长度，须在
                [`BoundedListCapacityLimits.MIN_MAX_LEN`,
                `BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING`] 内

        English
        --------
        Create a bounded queue. Throws if the same key already exists.

        Args:
            key: Queue key.
            max_len: Maximum length; must be within
                [`BoundedListCapacityLimits.MIN_MAX_LEN`,
                `BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING`].
        """
        ...

    @abstractmethod
    def get(self, key: str, clazz: type[T]) -> BoundedQueue[T]:
        """中文
        ----
        获取已存在的有界队列。

        English
        --------
        Get an existing bounded queue.
        """
        ...

    @abstractmethod
    def get_or_create(self, key: str, max_len: int, clazz: type[T]) -> BoundedQueue[T]:
        """中文
        ----
        获取或创建。已存在时校验 `max_len` 与 meta 一致，否则抛异常。

        English
        --------
        Get or create. When the key exists, validates that `max_len`
        matches the stored meta, otherwise throws.
        """
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        """中文
        ----
        判断指定 key 的有界队列是否存在。

        English
        --------
        Whether a bounded queue with the given key exists.
        """
        ...

    @abstractmethod
    def destroy(self, key: str) -> bool:
        """中文
        ----
        销毁指定 key 的有界队列。

        English
        --------
        Destroy the bounded queue for the given key.
        """
        ...

    @abstractmethod
    def expire(self, key: str, timeout: int) -> bool:
        """中文
        ----
        设置指定 key 的过期时间。

        English
        --------
        Set the expiry for the given key.
        """
        ...

    @abstractmethod
    def grow(self, key: str) -> bool:
        """中文
        ----
        将指定队列容量翻倍（平台托管，不可缩小）。

        Returns:
            扩容成功 `True`，已达封顶 `False`

        Raises:
            KeyError: 队列不存在

        English
        --------
        Double the capacity of the given queue (platform-managed; never
        shrinks).

        Returns:
            `True` if grown, `False` if at the ceiling.

        Raises:
            KeyError: If the queue does not exist.
        """
        ...


__all__ = ["BoundedQueueOps"]
