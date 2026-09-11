"""Hash 字段级存取操作接口。

中文
----
Hash 字段级存取操作接口。
对应底层 Hash 数据结构，以 field 为粒度进行读写、批量操作及元信息查询。

English
--------
Hash field-level access ops interface.

Mirrors `cn.richie696.component.cache.ops.FieldOps`. Maps to the
underlying Hash data structure; reads/writes at field granularity,
plus batch ops and meta queries.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Callable, Collection, List, Dict, Protocol, Set, TypeVar

T = TypeVar("T")


class FieldOps(Protocol):
    """中文
    ----
    Hash 字段级存取操作接口。对应底层 Hash 数据结构，以 field 为粒度进行
    读写、批量操作及元信息查询。

    English
    --------
    Hash field-level access ops. Maps to the underlying Hash data
    structure; reads/writes at field granularity, plus batch ops and
    meta queries.
    """

    # ─────────── 单 field ───────────

    @abstractmethod
    def set(self, key: str, field: str, value: Any) -> None:
        """中文
        ----
        设置 `key` 的 `field` 为 `value`。

        English
        --------
        Set the `field` of `key` to `value`.
        """
        ...

    @abstractmethod
    def get(self, key: str, field: str, clazz: type[T]) -> T | None:
        """中文
        ----
        读取 `key` 的 `field`，反序列化为 `clazz` 类型。

        English
        --------
        Read one field, deserialised into `clazz`.
        """
        ...

    @abstractmethod
    def get_typed(self, key: str, field: str, reference: type[T]) -> T | None:
        """中文
        ----
        读取 `key` 的 `field`，使用运行时类型（替代 Java `TypeReference<T>` —
        Python 保留泛型信息，裸 `type[T]` 即可）。

        English
        --------
        Read one field with a runtime-resolved type (replaces Java
        `TypeReference<T>` — Python preserves generic type info, so a
        bare `type[T]` is sufficient).
        """
        ...

    @abstractmethod
    def exists(self, key: str, field: str) -> bool:
        """中文
        ----
        判断 field 是否存在。

        English
        --------
        Whether the field exists.
        """
        ...

    # ─────────── 原子计数器 ───────────

    @abstractmethod
    def increment(self, key: str, field: str) -> int:
        """中文
        ----
        原子地将 Hash field 加一。

        English
        --------
        Atomic +1 on a Hash field.
        """
        ...

    @abstractmethod
    def increment_by(self, key: str, field: str, delta: int) -> int:
        """中文
        ----
        原子地为 Hash field 增加整数值。

        English
        --------
        Atomic integer +delta on a Hash field.
        """
        ...

    @abstractmethod
    def increment_double(self, key: str, field: str, delta: float) -> float:
        """中文
        ----
        原子地为 Hash field 增加浮点值。

        English
        --------
        Atomic float +delta on a Hash field.
        """
        ...

    @abstractmethod
    def decrement(self, key: str, field: str) -> int:
        """中文
        ----
        原子地将 Hash field 减一。

        English
        --------
        Atomic -1 on a Hash field.
        """
        ...

    @abstractmethod
    def decrement_by(self, key: str, field: str, delta: int) -> int:
        """中文
        ----
        原子地为 Hash field 减少整数值。

        English
        --------
        Atomic integer -delta on a Hash field.
        """
        ...

    # ─────────── 多 field ───────────

    @abstractmethod
    def set_all(self, key: str, mapping: Dict[str, Any], timeout_millis: int) -> None:
        """中文
        ----
        批量设置多个 field，并设置 TTL（毫秒）。

        English
        --------
        Bulk-set multiple fields and apply TTL in milliseconds.
        """
        ...

    @abstractmethod
    def get_all(self, key: str, clazz: type[T]) -> Dict[str, T]:
        """中文
        ----
        读取 Hash 的全部 field。

        English
        --------
        Read all fields of the Hash.
        """
        ...

    @abstractmethod
    def get_many_typed(
        self, key: str, fields: Collection[str], reference: type[T]
    ) -> List[T]:
        """中文
        ----
        批量读取多个 field。

        English
        --------
        Read multiple fields.
        """
        ...

    @abstractmethod
    def get_many(
        self, key: str, fields: Collection[str], clazz: type[T]
    ) -> Dict[str, T]:
        """中文
        ----
        批量读取多个字段，并保留 field 到 value 的映射。

        English
        --------
        Batch-read multiple fields, preserving the field→value mapping.
        """
        ...

    # ─────────── 元信息 ───────────

    @abstractmethod
    def get_fields(self, key: str) -> Set[str]:
        """中文
        ----
        获取 Hash 全部 field 名。

        English
        --------
        Get all field names of the Hash.
        """
        ...

    @abstractmethod
    def size(self, key: str) -> int:
        """中文
        ----
        获取 Hash 的 field 数量。

        English
        --------
        Number of fields in the Hash.
        """
        ...

    @abstractmethod
    def remove(self, key: str, *fields: str) -> None:
        """中文
        ----
        删除一个或多个 field。

        English
        --------
        Remove one or more fields.
        """
        ...

    # ─────────── 批量 ───────────

    @abstractmethod
    def batch_set(self, mapping: Dict[str, Dict[str, Any]]) -> None:
        """中文
        ----
        批量设置多个 key 的多个 field。

        English
        --------
        Bulk-set multiple fields across multiple keys.
        """
        ...

    # ─────────── 防击穿 ───────────

    @abstractmethod
    def get_with_lock(
        self,
        key: str,
        field: str,
        clazz: type[T],
        timeout_millis: int,
        db_loader: Callable[[], T | None],
    ) -> T | None:
        """中文
        ----
        单 field 的防缓存击穿版本：缓存命中直接返回；未命中则获取 Hash
        粒度锁，调用 `db_loader` 回源，回写缓存。

        English
        --------
        Stampede-prevention variant for a single field: cache-hit →
        return; cache-miss → acquire Hash-level lock → call
        `db_loader` → writeback.
        """
        ...

    @abstractmethod
    def get_with_lock_typed(
        self,
        key: str,
        field: str,
        reference: type[T],
        timeout_millis: int,
        db_loader: Callable[[], T | None],
    ) -> T | None:
        """中文
        ----
        单 field 的防缓存击穿版本（运行时类型版本）。

        English
        --------
        Stampede-prevention variant for a single field with a
        runtime-resolved type.
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
        """中文
        ----
        批量字段读取的防缓存击穿版本；一次 Redis 读取、一次 Hash 粒度锁。

        English
        --------
        Stampede-prevention variant for batch field reads: one Redis read
        plus one Hash-granularity lock.
        """
        ...


__all__ = ["FieldOps"]
