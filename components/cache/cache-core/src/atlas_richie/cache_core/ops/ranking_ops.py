"""有序集合/排行榜操作接口。

中文
----
有序集合/排行榜操作接口。
对应底层 ZSet 数据结构，支持分数排序、排名查询、范围扫描及弹出操作。

English
--------
Sorted set / leaderboard ops interface.

Mirrors `cn.richie696.component.cache.ops.RankingOps`. Maps to the
underlying ZSet data structure; score-sorted ranking, range scans,
and pop operations.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Protocol, Set, TypeVar

T = TypeVar("T")


class RankingOps(Protocol):
    """中文
    ----
    有序集合/排行榜操作接口。对应底层 ZSet 数据结构，支持分数排序、排名
    查询、范围扫描及弹出操作。

    English
    --------
    Sorted set / leaderboard ops. Maps to the underlying ZSet data
    structure; score-sorted ranking, range scans, and pop operations.
    """

    @abstractmethod
    def set(self, key: str, value: Any, score: float) -> None:
        """中文
        ----
        添加/更新一个 member 及其分数。

        English
        --------
        Add or update a member with the given score.
        """
        ...

    @abstractmethod
    def set_all(self, key: str, ordered_set: set) -> None:
        """中文
        ----
        整体替换有序集合。`ordered_set` 是 `TreeSet` 风格的有序集合
        （Python 可用 `sortedcontainers.SortedSet` 或任意有序 set）。

        English
        --------
        Bulk add. `ordered_set` is a `TreeSet`-style sorted set
        (replaced by Python's `sortedcontainers.SortedSet` or any
        ordered set).
        """
        ...

    @abstractmethod
    def batch_set(self, mapping: dict[str, set]) -> None:
        """中文
        ----
        批量设置多个 key 的有序集合。

        English
        --------
        Bulk set sorted sets for multiple keys.
        """
        ...

    @abstractmethod
    def size(self, key: str) -> int:
        """中文
        ----
        获取有序集合的 member 数量。

        English
        --------
        Number of members in the sorted set.
        """
        ...

    @abstractmethod
    def remove(self, key: str, *values: Any) -> None:
        """中文
        ----
        删除一个或多个 member。

        English
        --------
        Remove one or more members.
        """
        ...

    @abstractmethod
    def remove_by_rank(self, key: str, start: int, end: int) -> None:
        """中文
        ----
        按 rank 区间删除 member（rank 升序，`start`/`end` 含两端）。

        English
        --------
        Remove members in the rank range `[start, end]` (ascending).
        """
        ...

    @abstractmethod
    def remove_by_score(self, key: str, min_score: float, max_score: float) -> None:
        """中文
        ----
        按 score 区间删除 member（`min_score`/`max_score` 含两端）。

        English
        --------
        Remove members whose score is in `[min_score, max_score]`.
        """
        ...

    @abstractmethod
    def increment_score(self, key: str, value: Any, delta: float) -> float:
        """中文
        ----
        原子地给指定 member 的 score 增加 `delta`。

        English
        --------
        Atomic score +delta for a member.
        """
        ...

    @abstractmethod
    def pop_min(self, key: str, reference: type[T]) -> T | None:
        """中文
        ----
        弹出分数最低的 member。

        English
        --------
        Pop the lowest-scored member.
        """
        ...

    @abstractmethod
    def pop_min_many(
        self, key: str, count: int, reference: type[T]
    ) -> Set[T]:
        """中文
        ----
        弹出分数最低的 `count` 个 member。

        English
        --------
        Pop the `count` lowest-scored members.
        """
        ...

    @abstractmethod
    def range(
        self, key: str, start: int, end: int, reference: type[T]
    ) -> Set[T]:
        """中文
        ----
        按 rank 区间（升序）返回 member。

        English
        --------
        Range by rank (ascending).
        """
        ...

    @abstractmethod
    def range_by_score(
        self, key: str, min_score: float, max_score: float, reference: type[T]
    ) -> Set[T]:
        """中文
        ----
        按 score 区间（升序）返回 member。

        English
        --------
        Range by score (ascending).
        """
        ...

    @abstractmethod
    def reverse_rank(self, key: str, value: Any) -> int:
        """中文
        ----
        获取 member 的降序排名（从 0 开始）；不存在则返回 `-1`。

        English
        --------
        Rank in descending order; `-1` if not present.
        """
        ...


__all__ = ["RankingOps"]
