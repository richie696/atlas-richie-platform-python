"""ZSet（有序集合）缓存操作函数。
----
ZSet 类型缓存 API 管理器接口，封装了 Redis 中 ZSet 有序集合的常用操作。
主要用于排行榜、分数排序、批量操作、集合运算等场景，支持批量添加、
弹出、分数增减、交并差集等能力。推荐用于积分榜、活跃度排行、
分数统计、复杂集合运算等高并发场景。

English
--------
Sorted set (ZSet) cache function (high-level, built on `RankingOps`).

Mirrors `cn.richie696.component.cache.function.ZSetFunction`. Wraps
`RankingOps` with batch add, pop, score-increment, range queries, and
intersect/union/difference helpers.

Java's `TypeReference<T>` collapses to a bare `type[T]` in Python —
Python preserves generic type info, so a `type[T]` argument is
sufficient for typed deserialisation.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Collection, Protocol, Set, TypeVar

from .cache_function import CacheFunction

T = TypeVar("T")


class ZSetFunction(CacheFunction, Protocol):
    """ZSet（有序集合）类型缓存操作接口。

    适用于排行榜、分数排序、批量操作、集合运算等场景。

    English
    --------
    ZSet-type cache operation interface. Suited for leaderboards,
    score sorting, batch operations, and set algebra.
    """

    @abstractmethod
    def batch_add_to_zset(self, mapping: dict[str, set]) -> None:
        """批量添加缓存到 ZSet。

        **注意**：此方法**非原子性**操作，有可能出现并发安全问题。

        Args:
            mapping: 批量添加的缓存数据

        English
        --------
        Batch-add entries to ZSets. **Non-atomic** — may exhibit
        concurrency anomalies.
        """
        ...

    @abstractmethod
    def pop_min_from_zset(self, key: str, reference: type[T]) -> T | None:
        """弹出 ZSet 队首元素（Score 最小）。

        Args:
            key: 列表名称
            reference: 内省对象

        Returns:
            队首元素，无元素时为 `None`。

        English
        --------
        Pop the lowest-score element from the ZSet.
        """
        ...

    @abstractmethod
    def pop_min_from_zset_many(
        self, key: str, count: int, reference: type[T]
    ) -> Set[T]:
        """弹出 ZSet 队首 `count` 个元素。

        Args:
            key: 列表名称
            count: 弹出元素的数量
            reference: 内省对象

        Returns:
            弹出的元素集合。

        English
        --------
        Pop up to `count` lowest-score elements from the ZSet.
        """
        ...

    @abstractmethod
    def add_zset(self, key: str, ordered_set: set) -> None:
        """批量添加元素到 ZSet（不会添加重复值）。

        `ordered_set` 期望传入可按 score 排序的有序集合实现
        （如 `sortedcontainers.SortedSet`）。任意可迭代的 `(value, score)`
        序列也可。

        Args:
            key: 列表名称
            ordered_set: 列表值

        English
        --------
        Batch-add elements to the ZSet (no duplicates). `ordered_set`
        should be an iterable sorted by score (e.g.
        `sortedcontainers.SortedSet`).
        """
        ...

    @abstractmethod
    def add_zset_item(self, key: str, value: Any, score: float) -> None:
        """添加单个元素到 ZSet。

        Args:
            key: 列表名称
            value: 列表值
            score: 列表排序号

        English
        --------
        Add a single element to the ZSet with the given score.
        """
        ...

    @abstractmethod
    def remove_zset_item(self, key: str, *values: Any) -> None:
        """批量删除 ZSet 元素。

        Args:
            key: 列表名称
            values: 要移除的值

        English
        --------
        Batch-remove elements from the ZSet.
        """
        ...

    @abstractmethod
    def remove_zset_item_by_rank(
        self, key: str, start: int, end: int
    ) -> None:
        """按 rank 区间删除 ZSet 元素。

        Args:
            key: 列表名称
            start: 要移除的元素起始位置
            end: 要移除的元素结束位置

        English
        --------
        Remove ZSet elements in the given rank range.
        """
        ...

    @abstractmethod
    def remove_zset_item_by_score(
        self, key: str, min_score: float, max_score: float
    ) -> None:
        """按 score 区间删除 ZSet 元素。

        Args:
            key: 缓存 KEY
            min_score: 最小分数
            max_score: 最大分数

        English
        --------
        Remove ZSet elements whose score falls in `[min_score, max_score]`.
        """
        ...

    @abstractmethod
    def reverse_range_with_scores(
        self, key: str, start: int, end: int, reference: type[T]
    ) -> Set[T]:
        """以 Score 值降序排列获取指定 Rank 范围元素。

        Args:
            key: 资源 KEY
            start: 起始索引位置
            end: 结束索引位置
            reference: 目标元素类型

        Returns:
            返回指定范围内的元素列表。

        English
        --------
        Return elements in the given rank range, ordered by score
        descending.
        """
        ...

    @abstractmethod
    def reverse_range_by_score(
        self, key: str, min_score: float, max_score: float, reference: type[T]
    ) -> Set[T]:
        """以 Score 值降序排列获取指定 Score 范围元素。

        Args:
            key: 资源 KEY
            min_score: 最小排序值
            max_score: 最大排序值
            reference: 目标类型引用

        Returns:
            返回指定范围内的元素列表。

        English
        --------
        Return elements whose score is in `[min_score, max_score]`,
        ordered by score descending.
        """
        ...

    @abstractmethod
    def get_zset_size(self, key: str) -> int:
        """获取 ZSet 集合元素数量。

        Args:
            key: 元素 KEY

        Returns:
            返回执行结果。

        English
        --------
        Return the number of elements in the ZSet.
        """
        ...

    @abstractmethod
    def increment_score(
        self, key: str, value: Any, delta: float
    ) -> float:
        """为 ZSet 元素增加分数。

        Args:
            key: 元素 KEY
            value: 元素值
            delta: 增量

        Returns:
            返回增加后的分数。

        English
        --------
        Atomically increment the score of `value` by `delta`.
        """
        ...

    @abstractmethod
    def get_zset_rank(self, key: str, value: Any) -> int:
        """获取 ZSet 元素的排名（升序，0-based；不存在返回 -1）。

        Args:
            key: 元素 KEY
            value: 元素值

        Returns:
            返回元素的排名。

        English
        --------
        Return the rank of `value` in ascending order (0-based;
        `-1` if absent).
        """
        ...

    @abstractmethod
    def get_zset_reverse_rank(self, key: str, value: Any) -> int:
        """获取 ZSet 元素的 reverse rank（降序，0-based；不存在返回 -1）。

        Args:
            key: 元素 KEY
            value: 元素值

        Returns:
            返回元素的排名。

        English
        --------
        Return the rank of `value` in descending order (0-based;
        `-1` if absent).
        """
        ...

    @abstractmethod
    def get_zset_data(
        self, key: str, start: int, end: int, reference: type[T]
    ) -> dict[float, T]:
        """获取 ZSet 区间元素（score → value 映射）。

        Args:
            key: 元素 KEY
            start: 元素起始位置
            end: 元素结束位置
            reference: 内省对象

        Returns:
            返回全部的元素。

        English
        --------
        Return ZSet elements in `[start, end]` as a `score → value` map.
        """
        ...

    @abstractmethod
    def intersect_from_zset(
        self, key: str, other_keys: Collection[str], reference: type[T]
    ) -> list[T]:
        """计算交集。返回有序列表。

        Args:
            key: 元素 KEY
            other_keys: 其他元素 KEY 列表
            reference: 目标缓存类型

        Returns:
            交集元素数量。

        English
        --------
        Compute the intersection of `key` and `other_keys` and return
        an ordered list.
        """
        ...

    @abstractmethod
    def union_from_zset(
        self, key: str, other_keys: Collection[str], reference: type[T]
    ) -> list[T]:
        """计算并集。返回有序列表。

        Args:
            key: 元素 KEY
            other_keys: 其他元素 KEY 列表
            reference: 目标缓存类型

        Returns:
            并集元素数量。

        English
        --------
        Compute the union of `key` and `other_keys` and return an
        ordered list.
        """
        ...

    @abstractmethod
    def union_and_store_from_zset(
        self, key: str, other_keys: Collection[str], dest_key: str
    ) -> int:
        """并集并存储到目标键。

        Args:
            key: 元素 KEY
            other_keys: 其他元素 KEY 列表
            dest_key: 目标元素 KEY

        Returns:
            并集元素数量。

        English
        --------
        Compute the union of `key` and `other_keys` and store it at
        `dest_key`.
        """
        ...

    @abstractmethod
    def intersect_and_store_from_zset(
        self, key: str, other_keys: Collection[str], dest_key: str
    ) -> int:
        """交集并存储到目标键。

        Args:
            key: 元素 KEY
            other_keys: 其他元素 KEY 列表
            dest_key: 目标元素 KEY

        Returns:
            交集元素数量。

        English
        --------
        Compute the intersection of `key` and `other_keys` and store it
        at `dest_key`.
        """
        ...

    @abstractmethod
    def difference_and_store_from_zset(
        self, key: str, other_keys: Collection[str], dest_key: str
    ) -> int:
        """差集并存储到目标键。

        Args:
            key: 元素 KEY
            other_keys: 其他元素 KEY 列表
            dest_key: 目标元素 KEY

        Returns:
            差集元素数量。

        English
        --------
        Compute the difference of `key` and `other_keys` and store it
        at `dest_key`.
        """
        ...

    @abstractmethod
    def difference_from_zset(
        self, key: str, other_keys: Collection[str], reference: type[T]
    ) -> list[T]:
        """计算差集。返回有序列表。

        Args:
            key: 元素 KEY
            other_keys: 其他元素 KEY 列表
            reference: 目标缓存类型

        Returns:
            差集元素数量。

        English
        --------
        Compute the difference of `key` and `other_keys` and return an
        ordered list.
        """
        ...


__all__ = ["ZSetFunction"]
