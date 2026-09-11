"""无序集合操作接口。

中文
----
无序集合操作接口。
对应底层 Set 数据结构，提供集合元素的增删查以及防缓存击穿能力。

English
--------
Unordered Set ops interface.

Mirrors `cn.richie696.component.cache.ops.CollectionOps`. Maps to the
underlying Set data structure; add/remove/query/pop + stampede prevention.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Callable, Protocol, Set, TypeVar

T = TypeVar("T")


class CollectionOps(Protocol):
    """中文
    ----
    无序集合操作接口。对应底层 Set 数据结构，提供集合元素的增删查以及
    防缓存击穿能力。

    English
    --------
    Unordered Set ops. Maps to the underlying Set data structure;
    add/remove/query/pop + stampede prevention.
    """

    @abstractmethod
    def get(self, key: str, clazz: type[T]) -> Set[T]:
        """中文
        ----
        读取 key 对应的集合，反序列化为 `clazz` 元素类型。

        English
        --------
        Read the set for `key`, deserialised into `clazz`.
        """
        ...

    @abstractmethod
    def set(self, key: str, values: Set[Any], timeout_millis: int) -> None:
        """中文
        ----
        整体替换 key 的集合，并设置 TTL（毫秒）。

        English
        --------
        Replace the set for `key` and set TTL in milliseconds.
        """
        ...

    @abstractmethod
    def add(self, key: str, value: Any) -> None:
        """中文
        ----
        向集合添加一个元素。

        English
        --------
        Add one element to the set.
        """
        ...

    @abstractmethod
    def size(self, key: str) -> int:
        """中文
        ----
        获取集合的元素数量。

        English
        --------
        Number of elements in the set.
        """
        ...

    @abstractmethod
    def exists(self, key: str, value: Any) -> bool:
        """中文
        ----
        判断 value 是否在集合中。

        English
        --------
        Whether `value` is in the set.
        """
        ...

    @abstractmethod
    def remove(self, key: str, *values: Any) -> None:
        """中文
        ----
        从集合中删除一个或多个元素。

        English
        --------
        Remove one or more elements from the set.
        """
        ...

    @abstractmethod
    def batch_set(self, mapping: dict[str, Set[Any]]) -> None:
        """中文
        ----
        批量替换多个 key 的集合。

        English
        --------
        Bulk-replace sets for multiple keys.
        """
        ...

    @abstractmethod
    def pop(self, key: str, clazz: type[T]) -> T | None:
        """中文
        ----
        随机弹出一个元素。

        English
        --------
        Pop one element at random.
        """
        ...

    @abstractmethod
    def pop_many(self, key: str, count: int, clazz: type[T]) -> Set[T]:
        """中文
        ----
        随机弹出 `count` 个元素。

        English
        --------
        Pop `count` elements at random.
        """
        ...

    @abstractmethod
    def get_with_lock(
        self,
        key: str,
        clazz: type[T],
        timeout_millis: int,
        db_loader: Callable[[], Set[T] | None],
    ) -> Set[T]:
        """中文
        ----
        防缓存击穿：缓存命中直接返回；缓存未命中则获取分布式锁，调用
        `db_loader` 回源，回写缓存。其他并发 caller 阻塞等待锁。

        English
        --------
        Stampede-prevention: cache-hit → return; cache-miss → acquire
        lock → call `db_loader` → writeback. Other concurrent callers
        wait via the lock.
        """
        ...


__all__ = ["CollectionOps"]
