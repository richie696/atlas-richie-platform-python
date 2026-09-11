"""KV 缓存 + 计数器操作接口。

中文
----
KV 缓存 + 计数器操作接口。
对应底层 String 数据结构，提供基本类型/对象的存取、原子计数、
批量操作及防缓存击穿能力。

@author richie696
@version 1.0.0
@since 2025-06-05

English
--------
KV cache + counter ops interface.

Mirrors `cn.richie696.component.cache.ops.ValueOps`. Maps to the
underlying String data structure; provides basic-type/object access,
atomic counters, batch operations, and stampede prevention.

Translated 1:1 from Java. The 24 Java `set*` overloads are collapsed
to 4 Python methods (Python duck-typing covers str / int / float / bool
naturally); semantics are preserved.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Callable, Collection, Generic, List, Dict, Protocol, TypeVar

T = TypeVar("T")


class ValueOps(Protocol, Generic[T]):
    """中文
    ----
    KV 缓存 + 计数器操作接口。对应底层 String 数据结构。

    English
    --------
    KV cache + counter ops. Mirrors `ops/ValueOps.java`.
    """

    # ─────────────────────── 读 ───────────────────────

    @abstractmethod
    def get(self, key: str, clazz: type[T]) -> T | None:
        """中文
        ----
        读取 key，反序列化为 `clazz` 类型。

        English
        --------
        Read a key, deserialised into `clazz`.
        """
        ...

    @abstractmethod
    def get_typed(self, key: str, reference: type[T]) -> T | None:
        """中文
        ----
        读取 key，使用运行时类型（替代 Java `TypeReference<T>` —
        Python 保留泛型信息，裸 `type[T]` 即可）。

        English
        --------
        Read a key with a runtime-resolved type (replaces Java
        `TypeReference<T>` — Python preserves generic type info, so a
        bare `type[T]` is sufficient).
        """
        ...

    @abstractmethod
    def get_map(self, keys: Collection[str], reference: type[T]) -> Dict[str, T]:
        """中文
        ----
        批量读取多个 key，以原 key 为键的 dict 返回。

        English
        --------
        Batch-read multiple keys into a map keyed by the original key.
        """
        ...

    @abstractmethod
    def get_list(self, keys: Collection[str], reference: type[T]) -> List[T]:
        """中文
        ----
        批量读取多个 key，返回 list（顺序不保证）。

        English
        --------
        Batch-read multiple keys into a list (order not preserved).
        """
        ...

    # ─────────────────────── 写 ───────────────────────

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """中文
        ----
        设置 `key` 为 `value`。接受 str / int / float / bool（Python 动态类型）。

        English
        --------
        Set `key` to `value`. Accepts str / int / float / bool.
        """
        ...

    @abstractmethod
    def set_if_absent(self, key: str, value: Any) -> bool:
        """中文
        ----
        仅当 key 不存在时设置。写入成功返回 `True`，key 已存在返回 `False`。

        English
        --------
        Set `key` to `value` only if it does not exist. Returns
        `True` on write, `False` if the key already existed.
        """
        ...

    @abstractmethod
    def set_with_ttl(self, key: str, value: Any, timeout_millis: int) -> None:
        """中文
        ----
        设置 `key` 为 `value`，TTL 单位毫秒。

        English
        --------
        Set `key` to `value` with TTL in milliseconds.
        """
        ...

    @abstractmethod
    def set_if_absent_with_ttl(
        self, key: str, value: Any, timeout_millis: int
    ) -> bool:
        """中文
        ----
        组合 `setIfAbsent` + TTL。写入成功返回 `True`。

        English
        --------
        Combine `setIfAbsent` + TTL. Returns `True` on write.
        """
        ...

    # ─────────────────────── 原子计数器 ───────────────────────

    @abstractmethod
    def increment(self, key: str) -> int:
        """中文
        ----
        原子 +1。

        English
        --------
        Atomic +1.
        """
        ...

    @abstractmethod
    def increment_by(self, key: str, delta: int) -> int:
        """中文
        ----
        原子 +delta（long）。

        English
        --------
        Atomic +delta (long).
        """
        ...

    @abstractmethod
    def increment_by_with_ttl(
        self, key: str, delta: int, timeout_millis: int
    ) -> int:
        """中文
        ----
        原子 +delta（long），同时刷新 TTL。

        English
        --------
        Atomic +delta (long) with TTL refresh.
        """
        ...

    @abstractmethod
    def increment_double(self, key: str, delta: float, timeout_millis: int) -> float:
        """中文
        ----
        原子 +delta（double），同时刷新 TTL。

        English
        --------
        Atomic +delta (double) with TTL refresh.
        """
        ...

    @abstractmethod
    def decrement(self, key: str) -> int:
        """中文
        ----
        原子 -1。

        English
        --------
        Atomic -1.
        """
        ...

    @abstractmethod
    def decrement_by(self, key: str, delta: int) -> int:
        """中文
        ----
        原子 -delta（long）。

        English
        --------
        Atomic -delta (long).
        """
        ...

    @abstractmethod
    def decrement_by_with_ttl(
        self, key: str, delta: int, timeout_millis: int
    ) -> int:
        """中文
        ----
        原子 -delta（long），同时刷新 TTL。

        English
        --------
        Atomic -delta (long) with TTL refresh.
        """
        ...

    # ─────────────────────── 批量 ───────────────────────

    @abstractmethod
    def batch_set(self, mapping: Dict[str, Any]) -> None:
        """中文
        ----
        批量设置。**非原子** — 参见 Java 文档的警告。

        English
        --------
        Bulk set. Not atomic — see Java doc for the warning.
        """
        ...

    @abstractmethod
    def batch_set_with_ttl(self, mapping: Dict[str, Any], timeout_millis: int) -> None:
        """中文
        ----
        批量设置带 TTL。**非原子**。

        English
        --------
        Bulk set with TTL. Not atomic.
        """
        ...

    @abstractmethod
    def batch_set_if_absent(self, mapping: Dict[str, Any]) -> None:
        """中文
        ----
        批量 `setIfAbsent`。**非原子**。

        English
        --------
        Bulk `setIfAbsent`. Not atomic.
        """
        ...

    @abstractmethod
    def batch_set_if_absent_with_ttl(
        self, mapping: Dict[str, Any], timeout_millis: int
    ) -> None:
        """中文
        ----
        批量 `setIfAbsent` 带 TTL。**非原子**。

        English
        --------
        Bulk `setIfAbsent` with TTL. Not atomic.
        """
        ...

    # ─────────────────────── 防缓存击穿 ───────────────────────

    @abstractmethod
    def get_with_lock(
        self, key: str, timeout_millis: int, db_loader: Callable[[], str | None]
    ) -> str | None:
        """中文
        ----
        防缓存击穿：缓存命中直接返回；缓存未命中则获取分布式锁，
        调用 `db_loader` 回源，回写缓存。其他并发 caller 阻塞等待锁。

        English
        --------
        Stampede-prevention: cache-hit → return; cache-miss →
        acquire lock → call `db_loader` → writeback. Other concurrent
        callers wait via the lock.
        """
        ...


__all__ = ["ValueOps"]
