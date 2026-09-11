"""布隆过滤器接口。
----
布隆过滤器（Bloom Filter）契约。支持两种实现策略：
- 内存版本（单进程内）
- 共享版本（基于 Redis，**必须通过 Lua 脚本保证原子性**）

English
--------
Bloom filter contract. Implementations: in-memory or shared (Redis).

Two strategies:
- in-memory (single process)
- shared (Redis-backed, **must be atomic via Lua**)
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol


class BloomFilter(Protocol):
    """布隆过滤器（Bloom Filter）契约。

    English
    --------
    Bloom filter contract. Implementations: in-memory or shared (Redis).
    """

    @abstractmethod
    def add(self, item: bytes | str) -> None:
        """将元素加入布隆过滤器。

        English
        --------
        Add the element to the filter.
        """
        ...

    @abstractmethod
    def might_contain(self, item: bytes | str) -> bool:
        """判断元素是否可能存在于布隆过滤器中。

        Returns:
            `True` 表示可能存在（可能为误判），`False` 表示绝对不存在。

        English
        --------
        Whether the element may be present in the filter.

        Returns:
            `True` means probably present (false positive possible);
            `False` means definitely absent.
        """
        ...


__all__ = ["BloomFilter"]
