"""基数统计操作接口。

中文
----
基数统计操作接口。
对应底层 HyperLogLog 数据结构，提供近似去重计数能力（误差约 0.81%）。

English
--------
HyperLogLog cardinality estimation ops interface.

Mirrors `cn.richie696.component.cache.ops.HyperLogOps`. Approximate
distinct-count with ~0.81% error.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Protocol


class HyperLogOps(Protocol):
    """中文
    ----
    基数统计操作接口。对应底层 HyperLogLog 数据结构，提供近似去重计数
    能力（误差约 0.81%）。

    English
    --------
    HyperLogLog cardinality estimation ops. Maps to the underlying
    HyperLogLog data structure; approximate de-dup counting
    (error ~0.81%).
    """

    @abstractmethod
    def add(self, key: str, *values: Any) -> None:
        """中文
        ----
        添加一个或多个待统计元素。

        English
        --------
        Add one or more elements to the HLL sketch.
        """
        ...

    @abstractmethod
    def count(self, key: str) -> int:
        """中文
        ----
        获取近似去重基数。

        English
        --------
        Get the approximate distinct count.
        """
        ...


__all__ = ["HyperLogOps"]
