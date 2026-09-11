"""Bounded LIFO stack — Protocol + abstract base.

Mirrors `cn.richie696.component.cache.redis.operations.BoundedStack`.
Active-pull (`pop()` / `latest(int)`). Push is rejected when full.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, List, TypeVar

from .bounded_list_capacity_limits import BoundedListCapacityLimits

T = TypeVar("T")


class BoundedStack(ABC, Generic[T]):
    """有界分布式栈（LIFO）操作对象，参考 JDK `Deque` API 设计。

    主动拉（`pop()` / `latest(int)`），满时拒绝压入；有界 List 工具，非消息队列。
    """

    def __init__(self, key: str, max_len: int) -> None:
        BoundedListCapacityLimits.validate_max_len(max_len)
        self._key = key
        self._meta_key = BoundedListCapacityLimits.meta_key(key)
        self._max_len = max_len
        self._destroyed = False

    @property
    def key(self) -> str:
        return self._key

    @property
    def max_len(self) -> int:
        return self._max_len

    def __repr__(self) -> str:
        return f"BoundedStack(key='{self._key}', maxLen={self._max_len})"

    def _assert_alive(self) -> None:
        if self._destroyed:
            raise RuntimeError(f"{self} has been destroyed")

    @abstractmethod
    def size(self) -> int:
        ...

    @abstractmethod
    def is_empty(self) -> bool:
        ...

    @abstractmethod
    def push(self, item: T) -> bool:
        """压栈；满时返回 False（拒绝）。"""
        ...

    @abstractmethod
    def pop(self) -> T | None:
        """弹栈（栈顶）。"""
        ...

    @abstractmethod
    def peek(self) -> T | None:
        """查看栈顶（不移除）。"""
        ...

    @abstractmethod
    def latest(self, count: int) -> List[T]:
        """最近 `count` 个元素（newest first）。"""
        ...

    @abstractmethod
    def grow(self) -> bool:
        ...

    @abstractmethod
    def expire(self, timeout: int) -> bool:
        ...

    @abstractmethod
    def destroy(self) -> bool:
        ...


__all__ = ["BoundedStack"]
