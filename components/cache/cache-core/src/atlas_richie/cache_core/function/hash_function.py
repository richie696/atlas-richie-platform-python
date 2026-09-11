"""Hash 字段级缓存操作函数。
----
Hash 类型缓存管理器接口，定义了所有对 Redis Hash 类型的通用操作能力。
适用于对象缓存、属性映射、分布式数据结构等场景。

English
--------
Hash / field-level cache function (high-level, built on `FieldOps`).

Mirrors `cn.richie696.component.cache.function.HashFunction`.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Callable, Collection, Dict, List, Protocol, Set, TypeVar

from .cache_function import CacheFunction

T = TypeVar("T")


class HashFunction(CacheFunction, Protocol):
    """Hash 类型缓存管理器接口。

    定义了所有对 Hash 类型的通用操作能力。适用于对象缓存、属性映射、
    分布式数据结构等场景。

    English
    --------
    Defines the full set of generic Hash operations. Suitable for object
    caching, attribute maps, and distributed data structures.
    """

    @abstractmethod
    def get_object_from_hash_with_lock(
        self, key: str, clazz: type[T], db_loader: Callable[[], T | None], timeout_millis: int
    ) -> T | None:
        """防缓存击穿：Hash 对象。

        Args:
            key: 缓存 key
            clazz: 缓存对象类型
            db_loader: 回源加载器
            timeout_millis: 超时时间

        Returns:
            返回缓存对象；不存在或加载失败时为 `None`。

        English
        --------
        Stampede-proof Hash-object load.

        Returns:
            The cached object, or `None` when missing / load failed.
        """
        ...

    @abstractmethod
    def get_from_hash_with_lock(
        self,
        key: str,
        hash_key: str,
        clazz: type[T],
        db_loader: Callable[[], T | None],
        timeout_millis: int,
    ) -> T | None:
        """防缓存击穿：Hash 单项。

        Args:
            key: 资源键
            hash_key: HASH 资源键
            clazz: 目标缓存类型
            db_loader: 回源加载器
            timeout_millis: 超时时间

        Returns:
            返回资源值；不存在或加载失败时为 `None`。

        English
        --------
        Stampede-proof single-field load.

        Returns:
            The field value, or `None` when missing / load failed.
        """
        ...

    @abstractmethod
    def get_from_hash_with_lock_typed(
        self,
        key: str,
        hash_key: str,
        reference: type[T],
        db_loader: Callable[[], T | None],
        timeout_millis: int,
    ) -> T | None:
        """防缓存击穿：Hash 单项（支持复杂类型）。

        Args:
            key: 资源键
            hash_key: HASH 资源键
            reference: 目标缓存类型引用
            db_loader: 回源加载器
            timeout_millis: 超时时间

        Returns:
            返回资源值。

        English
        --------
        Stampede-proof single-field load with complex (generic) type.
        """
        ...

    @abstractmethod
    def set(self, key: str, field: str, value: Any, timeout_millis: int) -> None:
        ...

    @abstractmethod
    def get(self, key: str, field: str, clazz: type[T]) -> T | None:
        ...

    @abstractmethod
    def get_typed(self, key: str, field: str, reference: type[T]) -> T | None:
        ...

    @abstractmethod
    def increment(self, key: str, field: str, delta: int) -> int:
        """原子地为 Hash field 增加整数值。

        English
        --------
        Atomically increment a Hash field by an integer delta.
        """
        ...

    @abstractmethod
    def increment_double(self, key: str, field: str, delta: float) -> float:
        """原子地为 Hash field 增加浮点值。

        English
        --------
        Atomically increment a Hash field by a floating-point delta.
        """
        ...

    @abstractmethod
    def decrement(self, key: str, field: str, delta: int) -> int:
        ...

    @abstractmethod
    def set_all(self, key: str, mapping: Dict[str, Any], timeout_millis: int) -> None:
        ...

    @abstractmethod
    def get_all(self, key: str, clazz: type[T]) -> Dict[str, T]:
        ...

    @abstractmethod
    def get_many_typed(
        self, key: str, fields: Collection[str], reference: type[T]
    ) -> List[T]:
        ...

    @abstractmethod
    def get_many(
        self, key: str, fields: Collection[str], clazz: type[T]
    ) -> Dict[str, T]:
        """根据指定字段批量读取 Hash 值，并保留 field 到 value 的映射。

        English
        --------
        Batch read multiple fields, preserving the field→value mapping.
        """
        ...

    @abstractmethod
    def get_fields(self, key: str) -> Set[str]:
        """根据 HASH 资源键获取资源 HASH_KEY 集合。

        Returns:
            返回资源值集合。

        English
        --------
        Return the set of field names under the given Hash key.
        """
        ...

    @abstractmethod
    def size(self, key: str) -> int:
        """获取 Hash 表中元素数量。

        Returns:
            返回执行结果。

        English
        --------
        Return the number of fields in the Hash.
        """
        ...

    @abstractmethod
    def remove(self, key: str, *fields: str) -> None:
        ...

    @abstractmethod
    def batch_set(self, mapping: Dict[str, Dict[str, Any]]) -> None:
        """批量添加缓存到 Redis Hash。

        **注意**：此方法**非原子性**操作，有可能出现并发安全问题。

        English
        --------
        Batch-add entries to Redis Hashes.

        **Warning**: this method is **non-atomic** and may exhibit
        concurrency anomalies.
        """
        ...

    @abstractmethod
    def get_many_with_lock(
        self,
        key: str,
        fields: Collection[str],
        clazz: type[T],
        timeout_millis: int,
        db_loader: Callable[[], Dict[str, T] | None],
    ) -> Dict[str, T]:
        """批量字段读取的防缓存击穿版本。

        缓存未命中时以 Hash 为粒度加锁并回源，避免业务层逐字段调用
        产生 N 次锁竞争。

        English
        --------
        Stampede-proof batch field read; one Redis read plus one
        Hash-granular lock.
        """
        ...


__all__ = ["HashFunction"]
