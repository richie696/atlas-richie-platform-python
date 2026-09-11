"""有界栈（Bounded LIFO Stack）管理接口。

中文
----
有界栈（Bounded LIFO Stack）管理接口。
通过 `GlobalCache.stack()` 获取实例。容量治理规则同 `BoundedQueueOps`。

English
--------
Bounded LIFO stack management interface.

Mirrors `cn.richie696.component.cache.ops.BoundedStackOps`. Acquired
via `GlobalCache.stack()`. Capacity rules mirror `BoundedQueueOps`.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol, TypeVar

from ..operations.bounded_stack import BoundedStack

T = TypeVar("T")


class BoundedStackOps(Protocol):
    """中文
    ----
    有界栈（Bounded LIFO Stack）管理接口。通过 `GlobalCache.stack()` 获取
    实例。容量治理规则同 `BoundedQueueOps`。

    English
    --------
    Bounded LIFO stack management ops. Acquired via
    `GlobalCache.stack()`. Capacity rules mirror `BoundedQueueOps`.
    """

    @abstractmethod
    def create(self, key: str, max_len: int, clazz: type[T]) -> BoundedStack[T]:
        """中文
        ----
        创建有界栈。同一 key 已存在时抛异常。

        English
        --------
        Create a bounded stack. Throws if the same key already exists.
        """
        ...

    @abstractmethod
    def get(self, key: str, clazz: type[T]) -> BoundedStack[T]:
        """中文
        ----
        获取已存在的有界栈。

        English
        --------
        Get an existing bounded stack.
        """
        ...

    @abstractmethod
    def get_or_create(self, key: str, max_len: int, clazz: type[T]) -> BoundedStack[T]:
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
        判断指定 key 的有界栈是否存在。

        English
        --------
        Whether a bounded stack with the given key exists.
        """
        ...

    @abstractmethod
    def destroy(self, key: str) -> bool:
        """中文
        ----
        销毁指定 key 的有界栈。

        English
        --------
        Destroy the bounded stack for the given key.
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
        将指定栈容量翻倍（平台托管，不可缩小）。

        Returns:
            扩容成功 `True`，已达封顶 `False`

        Raises:
            KeyError: 栈不存在

        English
        --------
        Double the capacity of the given stack (platform-managed; never
        shrinks).

        Returns:
            `True` if grown, `False` if at the ceiling.

        Raises:
            KeyError: If the stack does not exist.
        """
        ...


__all__ = ["BoundedStackOps"]
