"""HyperLogLog 基数统计缓存操作函数。
----
HyperLogLog 相关 API 管理器，封装了 Redis 中 HyperLogLog 数据结构的常用操作。
主要用于大规模基数统计（如 UV、去重计数）等场景，具有极低内存消耗
和可接受误差。

English
--------
HyperLogLog cardinality estimation cache function.

Mirrors `cn.richie696.component.cache.function.HyperLogFunction`.
HyperLogLog is for huge-stream de-dup with ~0.81% standard error and
constant memory.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Protocol


class HyperLogFunction(Protocol):
    """基数统计操作接口。

    封装了 Redis 中 HyperLogLog 数据结构的常用操作。主要用于大规模基数
    统计（如 UV、去重计数）等场景，具有极低内存消耗和可接受误差。

    English
    --------
    Approximate de-dup counting (error ~0.81%).
    """

    @abstractmethod
    def pf_add(self, key: str, *values: Any) -> None:
        """向 HyperLogLog 添加元素。

        Args:
            key: HyperLogLog 的键
            values: 要添加的元素，可变参数

        English
        --------
        Add elements to the HyperLogLog.

        Args:
            key: The HyperLogLog key.
            values: One or more elements to add.
        """
        ...

    @abstractmethod
    def pf_count(self, key: str) -> int:
        """获取 HyperLogLog 的基数估算值。

        Args:
            key: HyperLogLog 的键

        Returns:
            基数估算值（`int`）。

        English
        --------
        Get the estimated cardinality of the HyperLogLog.

        Returns:
            The estimated cardinality as an integer.
        """
        ...


__all__ = ["HyperLogFunction"]
