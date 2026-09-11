"""结构化对象缓存操作接口。

中文
----
结构化对象缓存操作接口。
对应底层 Hash 数据结构，将 JavaBean 作为整体存取，适用于对象的全体读写、
刷新及防缓存击穿。

English
--------
Structured object cache ops interface.

Mirrors `cn.richie696.component.cache.ops.StructOps`. Maps to the
underlying Hash data structure; treats a JavaBean/Pydantic model as a
unit (whole-object read/write/refresh + stampede prevention).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Callable, Protocol, TypeVar

T = TypeVar("T")


class StructOps(Protocol):
    """中文
    ----
    结构化对象缓存操作接口。对应底层 Hash 数据结构，将 JavaBean 作为整体
    存取，适用于对象的全体读写、刷新及防缓存击穿。

    English
    --------
    Structured object cache ops. Maps to the underlying Hash data
    structure; treats a JavaBean/Pydantic model as a unit (whole-object
    read/write/refresh + stampede prevention).
    """

    @abstractmethod
    def get(self, key: str, clazz: type[T]) -> T | None:
        """中文
        ----
        读取 key 对应的结构化对象，反序列化为 `clazz` 类型。

        English
        --------
        Read the structured object for `key`, deserialised into
        `clazz`.
        """
        ...

    @abstractmethod
    def get_typed(self, key: str, reference: type[T]) -> T | None:
        """中文
        ----
        读取 key 对应的结构化对象，使用运行时类型（替代 Java
        `TypeReference<T>` — Python 保留泛型信息，裸 `type[T]` 即可）。

        English
        --------
        Read the structured object for `key` with a runtime-resolved
        type (replaces Java `TypeReference<T>` — Python preserves
        generic type info, so a bare `type[T]` is sufficient).
        """
        ...

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """中文
        ----
        整体写入一个结构化对象。

        English
        --------
        Write a structured object as a whole.
        """
        ...

    @abstractmethod
    def set_with_ttl(self, key: str, value: Any, timeout_millis: int) -> None:
        """中文
        ----
        整体写入一个结构化对象，并设置 TTL（毫秒）。

        English
        --------
        Write a structured object as a whole with TTL in milliseconds.
        """
        ...

    @abstractmethod
    def refresh(self, key: str, func: Callable[[T | None], T]) -> T:
        """中文
        ----
        读改写（read-modify-write）原子操作：func 接收当前值（不存在则为
        `None`），返回新值。

        English
        --------
        Read-modify-write in a single operation. The function receives
        the current value (or `None` if absent) and returns the new
        value.
        """
        ...

    @abstractmethod
    def get_with_lock(
        self,
        key: str,
        clazz: type[T],
        timeout_millis: int,
        db_loader: Callable[[], T | None],
    ) -> T | None:
        """中文
        ----
        防缓存击穿：缓存命中直接返回；未命中则获取分布式锁，调用
        `db_loader` 回源，回写缓存。

        English
        --------
        Stampede-prevention: cache-hit → return; cache-miss → acquire
        lock → call `db_loader` → writeback.
        """
        ...

    @abstractmethod
    def get_with_lock_typed(
        self,
        key: str,
        reference: type[T],
        timeout_millis: int,
        db_loader: Callable[[], T | None],
    ) -> T | None:
        """中文
        ----
        防缓存击穿（运行时类型版本）。

        English
        --------
        Stampede-prevention variant with a runtime-resolved type.
        """
        ...


__all__ = ["StructOps"]
