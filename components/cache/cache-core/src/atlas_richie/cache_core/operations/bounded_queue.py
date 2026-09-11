"""Bounded FIFO queue — Protocol + abstract base.

Mirrors `cn.richie696.component.cache.redis.operations.BoundedQueue`
(data-structure API only; the Redis-specific Lua scripts and
`MultiRedisTemplate` plumbing live in the `atlas-richie-cache-redis`
backend).

**Active-pull** model: business code calls `poll()` / `drain(int)`.
There is no push consumer group, no ACK. Positioned as peak-shaving
buffer / lightweight async, not a Redis Stream message queue.

Capacity is fixed at construction; can be doubled via `grow()` (single
×2, capped at `BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING`).
On overflow, the oldest entry is dropped (FIFO).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, List, TypeVar

from .bounded_list_capacity_limits import BoundedListCapacityLimits

T = TypeVar("T")


class BoundedQueue(ABC, Generic[T]):
    """有界分布式队列（FIFO）操作对象，参考 JDK `Queue` API 设计。

    主动拉消费：须由业务 `poll()` / `drain(int)` 拉取，无推送、无消费组。
    定位为削峰缓冲与轻量异步，非 Redis Stream 消息队列。

    创建后默认不可变容量；仅可通过 `grow()` 在平台约束下单次翻倍放大。
    入队超限时自动淘汰队首。
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
        return f"BoundedQueue(key='{self._key}', maxLen={self._max_len})"

    def _assert_alive(self) -> None:
        if self._destroyed:
            raise RuntimeError(f"{self} has been destroyed")

    # ─── 状态查询 ───

    @abstractmethod
    def size(self) -> int:
        ...

    @abstractmethod
    def is_empty(self) -> bool:
        ...

    # ─── 写 ───

    @abstractmethod
    def offer(self, item: T) -> bool:
        """入队；满时自动淘汰队首（FIFO）。"""
        ...

    # ─── 读 ───

    @abstractmethod
    def poll(self) -> T | None:
        """出队一个（队首）。"""
        ...

    @abstractmethod
    def peek(self) -> T | None:
        """查看队首（不移除）。"""
        ...

    @abstractmethod
    def peek_tail(self) -> T | None:
        """查看队尾（不移除）。"""
        ...

    @abstractmethod
    def drain(self, count: int) -> List[T]:
        """批量出队。"""
        ...

    # ─── 容量 ───

    @abstractmethod
    def grow(self) -> bool:
        """将容量上限翻倍一次；已达封顶时返回 False。"""
        ...

    # ─── 生命周期 ───

    @abstractmethod
    def expire(self, timeout: int) -> bool:
        ...

    @abstractmethod
    def destroy(self) -> bool:
        ...


__all__ = ["BoundedQueue"]
