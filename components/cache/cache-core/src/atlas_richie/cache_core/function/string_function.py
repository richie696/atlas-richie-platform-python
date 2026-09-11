"""字符串 / KV 缓存操作函数。
----
字符串缓存操作接口，提供对 Redis String 类型缓存的操作方法。

English
--------
String / KV cache function (high-level, built on `ValueOps`).

Mirrors `cn.richie696.component.cache.function.StringFunction`. Provides
typed access, batch operations, counter helpers, and stampede prevention.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Collection, List, Dict, Protocol, TypeVar

from .cache_function import CacheFunction

T = TypeVar("T")


class StringFunction(CacheFunction, Protocol):
    """字符串缓存操作接口。

    提供对 KV 类型缓存的操作方法。适用于字符串缓存、对象缓存、防缓存击穿、
    批量操作等场景。

    English
    --------
    String cache operation interface providing KV-type accessors. Suited
    for string caching, object caching, stampede prevention, and batch
    operations.
    """

    @abstractmethod
    def get_from_string_with_lock(
        self, key: str, db_loader, timeout_millis: int
    ) -> str | None:
        """防缓存击穿：String 类型。

        Args:
            key: 缓存键
            db_loader: 回源加载器
            timeout_millis: 超时时间（毫秒）

        Returns:
            缓存值，不存在或加载失败时为 `None`。

        English
        --------
        Stampede-proof String load.

        Returns:
            The cached value, or `None` when missing / load failed.
        """
        ...

    @abstractmethod
    def batch_add_to_string(self, mapping: Dict[str, Any]) -> None:
        """批量添加缓存到 KV。

        **注意**：此方法**非原子性**操作，有可能出现并发安全问题。

        English
        --------
        Batch add entries to Redis String. **Non-atomic** — may exhibit
        concurrency anomalies.
        """
        ...

    @abstractmethod
    def batch_add_to_string_with_ttl(
        self, mapping: Dict[str, Any], timeout_millis: int
    ) -> None:
        """批量添加缓存到 KV（带过期时间）。

        **注意**：此方法**非原子性**操作，有可能出现并发安全问题。

        Args:
            mapping: 批量添加的缓存数据
            timeout_millis: 超时时间（单位：毫秒）

        English
        --------
        Batch add entries to Redis String with TTL. **Non-atomic**.
        """
        ...

    @abstractmethod
    def add_value(self, key: str, value: Any, timeout_millis: int) -> None:
        """添加缓存到 KV 中的方法。

        Args:
            key: 缓存键
            value: 缓存值
            timeout_millis: 超时时间（单位：毫秒）

        English
        --------
        Add a value with TTL.
        """
        ...

    @abstractmethod
    def add_value_simple(self, key: str, value: Any) -> None:
        """添加缓存到 KV 中的方法（不带过期时间）。

        Args:
            key: 缓存键
            value: 缓存值

        English
        --------
        Add a value without TTL.
        """
        ...

    @abstractmethod
    def add_value_if_absent(self, key: str, value: Any, timeout_millis: int) -> bool:
        """添加缓存到 KV 中的方法（如果不存在）。

        Args:
            key: 缓存键
            value: 缓存值
            timeout_millis: 超时时间（单位：毫秒）

        Returns:
            是否成功添加。

        English
        --------
        Add a value only if absent, with TTL.
        """
        ...

    @abstractmethod
    def add_value_if_absent_simple(self, key: str, value: Any) -> bool:
        """添加缓存到 KV 中的方法（如果不存在，不带过期时间）。

        Args:
            key: 缓存键
            value: 缓存值

        Returns:
            是否成功添加。

        English
        --------
        Add a value only if absent, no TTL.
        """
        ...

    @abstractmethod
    def increment(self, key: str, timeout_millis: int) -> int:
        """计数器 +1 的方法。

        Args:
            key: 缓存键
            timeout_millis: 超时时间

        Returns:
            返回最新的计数值。

        English
        --------
        Increment the counter at `key` by 1, with TTL.
        """
        ...

    @abstractmethod
    def batch_update_if_absent(self, batch_update: Dict[str, Any], timeout_millis: int) -> None:
        """批量更新缓存对象的方法。

        Args:
            batch_update: 批量更新的数据
            timeout_millis: 超时时间

        English
        --------
        Batch update cache entries (only if absent).
        """
        ...

    @abstractmethod
    def increment_by(self, key: str, delta: int, timeout_millis: int) -> int:
        """计数器 +delta 的方法。

        Args:
            key: 缓存键
            delta: 增量
            timeout_millis: 超时时间

        Returns:
            返回最新的计数值。

        English
        --------
        Increment the counter at `key` by `delta`, with TTL.
        """
        ...

    @abstractmethod
    def increment_double(self, key: str, delta: float, timeout_millis: int) -> float:
        """计数器 +delta 的方法（浮点）。

        Args:
            key: 缓存键
            delta: 增量
            timeout_millis: 超时时间

        Returns:
            返回最新的计数值。

        English
        --------
        Increment the counter at `key` by `delta` (float), with TTL.
        """
        ...

    @abstractmethod
    def decrement(self, key: str, timeout_millis: int) -> int:
        """计数器 -1 的方法。

        Args:
            key: 缓存键
            timeout_millis: 超时时间

        Returns:
            返回最新的计数值。

        English
        --------
        Decrement the counter at `key` by 1, with TTL.
        """
        ...

    @abstractmethod
    def decrement_by(self, key: str, delta: int, timeout_millis: int) -> int:
        """计数器 -delta 的方法。

        Args:
            key: 缓存键
            delta: 增量
            timeout_millis: 超时时间

        Returns:
            返回最新的计数值。

        English
        --------
        Decrement the counter at `key` by `delta`, with TTL.
        """
        ...

    @abstractmethod
    def get_value_map(self, keys: Collection[str], reference: type[T]) -> Dict[str, T]:
        """获取匹配的 KEY 对应值的方法。

        **注意**：此方法可能会破坏分布式锁对值的锁定，**慎用**！

        Args:
            keys: 匹配的 KEY 集合
            reference: 内省对象

        Returns:
            返回 KEY 对应的值，如果某个值不存在则返回 `None`。

        English
        --------
        Return values for the given keys. **May break distributed-lock
        invariants — use with care.**
        """
        ...

    @abstractmethod
    def get_objects(self, keys: Collection[str], reference: type[T]) -> List[T]:
        """获取匹配的 KEY 对应值的方法。

        **注意**：此方法可能会破坏分布式锁对值的锁定，**慎用**！

        Args:
            keys: 匹配的 KEY 集合
            reference: 内省对象

        Returns:
            返回 KEY 对应的值列表。

        English
        --------
        Return values for the given keys. **May break distributed-lock
        invariants — use with care.**
        """
        ...

    @abstractmethod
    def get_from_string(self, key: str, clazz: type[T]) -> T | None:
        """根据资源键获取资源值。

        Args:
            key: 资源键
            clazz: 目标缓存类型

        Returns:
            返回资源值。

        English
        --------
        Return the value at `key` deserialized to `clazz`.
        """
        ...

    @abstractmethod
    def get_from_string_typed(self, key: str, reference: type[T]) -> T | None:
        """根据资源键获取资源值（支持复杂类型）。

        Args:
            key: 资源键
            reference: 目标缓存类型

        Returns:
            返回资源值。

        English
        --------
        Return the value at `key` deserialized via a generic `reference`.
        """
        ...

    @abstractmethod
    def scan(self, match: str, count: int, clazz: type[T]) -> Dict[str, T]:
        """模糊匹配获取所有值的方法。

        Args:
            match: 模糊匹配的 key
            count: 每次扫描的数量
            clazz: 目标缓存类型

        Returns:
            返回资源值。

        English
        --------
        Fuzzy-match scan over keys and return their values.
        """
        ...


__all__ = ["StringFunction"]
