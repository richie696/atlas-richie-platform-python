"""Set 集合缓存操作函数。
----
Set 类型缓存 API 管理器接口，封装了 Redis 中 Set 集合的常用操作。
主要用于集合去重、批量操作、分布式缓存等场景，支持布隆过滤器防击穿、
批量添加、差集、弹出等能力。
推荐用于用户标签、去重统计、批量缓存等高并发场景。

English
--------
Unordered Set cache function (high-level, built on `CollectionOps`).

Mirrors `cn.richie696.component.cache.function.SetFunction`. Wraps
`CollectionOps` with stampede-prevention, pop, difference, and batch
add helpers.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Callable, Collection, Protocol, Set, TypeVar

from .cache_function import CacheFunction

T = TypeVar("T")


class SetFunction(CacheFunction, Protocol):
    """Set 类型缓存操作接口。

    封装了 Redis 中 Set 集合的常用操作。主要用于集合去重、批量操作、
    分布式缓存等场景，支持布隆过滤器防击穿、批量添加、差集、弹出等能力。
    推荐用于用户标签、去重统计、批量缓存等高并发场景。

    English
    --------
    Set-type cache operation interface. Suited for de-duplication,
    batch operations, and distributed caching. Supports stampede-
    prevention (with lock), batch add, difference, pop, etc.
    """

    @abstractmethod
    def get_from_set_with_lock(
        self,
        key: str,
        reference: type[T],
        db_loader: Callable[[], Set[T] | None],
        timeout_millis: int,
    ) -> Set[T]:
        """防缓存击穿：Set。

        Args:
            key: 缓存键
            reference: 集合元素类型
            db_loader: 回源加载器（零参 callable）
            timeout_millis: 超时时间（毫秒）

        Returns:
            集合值；不存在或加载失败时为空集。

        English
        --------
        Stampede-proof Set load.

        Args:
            key: 缓存键
            reference: 集合元素类型
            db_loader: 回源加载器
            timeout_millis: 超时时间（毫秒）

        Returns:
            集合值，不存在或加载失败时为 null。
        """
        ...

    @abstractmethod
    def get_from_set(self, key: str, reference: type[T]) -> Set[T]:
        """根据资源键获取资源值集合。

        Args:
            key: 资源键
            reference: 目标缓存类型

        Returns:
            返回资源值集合。

        English
        --------
        Return the full Set for the given key.
        """
        ...

    @abstractmethod
    def pop_data_from_set(self, key: str, reference: type[T]) -> T | None:
        """从 Set 中弹出一个元素。

        Args:
            key: 资源键
            reference: 目标缓存类型

        Returns:
            弹出的元素；集合为空时为 `None`。

        English
        --------
        Pop a single element from the Set.
        """
        ...

    @abstractmethod
    def pop_members_from_set(
        self, key: str, count: int, reference: type[T]
    ) -> Set[T]:
        """从 Set 中弹出指定数量元素。

        Args:
            key: 资源键
            count: 弹出元素的数量
            reference: 目标缓存类型

        Returns:
            返回弹出的元素集合。

        English
        --------
        Pop up to `count` elements from the Set.
        """
        ...

    @abstractmethod
    def difference_from_set(
        self, keys: Collection[str], reference: type[T]
    ) -> Set[T]:
        """查询给定的 Set 集合的差集并返回差集。

        Args:
            keys: 待比较的资源键列表
            reference: 返回值元素类型

        Returns:
            返回差集元素集合。

        English
        --------
        Return the difference of the given Sets.
        """
        ...

    @abstractmethod
    def difference_from_set_with_key(
        self, key: str, other_keys: Collection[str], reference: type[T]
    ) -> Set[T]:
        """查询 `key` 与 `other_keys` 的差集。

        Args:
            key: 用于比较的主键
            other_keys: 待比较的资源键列表
            reference: 返回值元素类型

        Returns:
            返回差集元素集合。

        English
        --------
        Return the difference between `key` and `other_keys`.
        """
        ...

    @abstractmethod
    def difference_and_store_from_set(
        self, compare_keys: Collection[str], dest_key: str
    ) -> int:
        """查询差集并保存到目标键。

        Returns:
            目标键元素数量。

        English
        --------
        Compute the difference of `compare_keys` and store it at
        `dest_key`.

        Returns:
            The number of elements in the destination key.
        """
        ...

    @abstractmethod
    def exists_in_set(self, key: str, value: Any) -> bool:
        """检查指定的 value 是否存在于 Set 内。

        Args:
            key: 资源键
            value: 资源值

        Returns:
            `True` 表示存在，`False` 表示不存在。

        English
        --------
        Check whether the value exists in the Set.
        """
        ...

    @abstractmethod
    def batch_add_to_set(self, mapping: dict[str, set]) -> None:
        """批量添加缓存到 Set。

        **注意**：此方法**非原子性**操作，有可能出现并发安全问题。

        Args:
            mapping: 批量添加的缓存数据

        English
        --------
        Batch add entries to Sets. **Non-atomic** — may exhibit
        concurrency anomalies.
        """
        ...

    @abstractmethod
    def add_set(self, key: str, values: set) -> None:
        """批量添加元素到指定 Set（本方法不会添加重复值）。

        Args:
            key: Set 名称
            values: Set 值

        English
        --------
        Batch add elements to the given Set (no duplicates).
        """
        ...

    @abstractmethod
    def add_set_item(self, key: str, *value: Any) -> None:
        """添加单个元素到 Set。

        Args:
            key: Set 名称
            value: Set 值

        English
        --------
        Add a single element to the Set.
        """
        ...

    @abstractmethod
    def remove_set_item(self, key: str, *values: Any) -> None:
        """批量删除 Set 集合元素。

        Args:
            key: Set 名称
            values: 要移除的值

        English
        --------
        Batch remove elements from the Set.
        """
        ...

    @abstractmethod
    def get_set_size(self, key: str) -> int:
        """获取 Set 集合元素数量。

        Args:
            key: 元素 KEY

        Returns:
            返回执行结果。

        English
        --------
        Return the number of elements in the Set.
        """
        ...


__all__ = ["SetFunction"]
