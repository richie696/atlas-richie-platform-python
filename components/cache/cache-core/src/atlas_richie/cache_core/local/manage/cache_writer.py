"""L1 write-through 写入器契约。
----
write-through：本地缓存发生变更时，同步把变更回写到数据源。

对位 JSR-107 ``javax.cache.integration.CacheWriter``。Java 侧通过
``CacheDefinition.cacheWriterClassName`` + 反射工厂装配；Python 改为
**注册可调用对象**：``LocalCacheManager.register_writer(region, writer)``。

调用顺序与 JSR-107 一致：**先改缓存，再调写入器**。写入器抛出的异常会
向上抛给调用方，但缓存侧的变更已经生效——JSR-107 同样是这个语义。

写入器拿到的是**调用方传入的那个对象**，而不是缓存内部存储的副本
（`store_by_value=True` 时缓存会另外存一份防御性拷贝）。这与 JSR-107
参考实现一致：写回是同步完成的，调用方在 `put` 返回后才可能改动该对象，
不会影响已经完成的写入。

English
--------
L1 write-through writer contract.

Mirrors JSR-107 `javax.cache.integration.CacheWriter`. The Java side
wires it through `CacheDefinition.cacheWriterClassName` plus a
reflection factory; Python registers a **callable** instead:
`LocalCacheManager.register_writer(region, writer)`.

Ordering matches JSR-107: the cache is mutated **first**, then the
writer is called. A writer exception propagates to the caller, but the
cache-side change has already taken effect — JSR-107 behaves the same.

The writer is handed the object the caller passed in, not the copy the
cache keeps internally (`store_by_value=True`). That matches the JCache
reference implementation, and the write is synchronous, so the caller
cannot mutate the value before it reaches the source of truth.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class CacheWriter(Protocol):
    """回写数据源的写入器。

    English
    --------
    Writer that pushes cache mutations back to the source of truth.
    """

    def write(self, key: str, value: Any) -> None:
        """把 key 的新值回写到数据源。

        English
        --------
        Write the new value for `key` back to the source of truth.
        """
        ...

    def delete(self, key: str) -> None:
        """从数据源删除 key。

        English
        --------
        Delete `key` from the source of truth.
        """
        ...


class CallableCacheWriter:
    """把两个普通可调用对象适配成 :class:`CacheWriter`。

    ``delete`` 是**必填**的：缓存删条目却不同步删数据源，会留下永远不会
    消失的脏数据。这种配置错误必须在注册时就暴露，而不是运行时静默跳过。

    English
    --------
    Adapts two plain callables into a :class:`CacheWriter`.

    `delete` is **required**: deleting from the cache without deleting
    from the source leaves data that can never disappear. That
    misconfiguration must surface at registration time rather than be
    silently skipped at runtime.
    """

    def __init__(
        self,
        write: Callable[[str, Any], None],
        delete: Callable[[str], None],
    ) -> None:
        self._write = write
        self._delete = delete

    def write(self, key: str, value: Any) -> None:
        self._write(key, value)

    def delete(self, key: str) -> None:
        self._delete(key)


def as_cache_writer(writer: Any) -> CacheWriter:
    """把入参规范化成 :class:`CacheWriter`。

    接受：同时实现 ``write`` 与 ``delete`` 的对象；或 ``(write, delete)``
    二元组。

    English
    --------
    Normalise `writer` into a :class:`CacheWriter`. Accepts an object
    implementing both `write` and `delete`, or a `(write, delete)` pair.
    """
    if hasattr(writer, "write") and hasattr(writer, "delete"):
        return writer
    if isinstance(writer, tuple) and len(writer) == 2:
        return CallableCacheWriter(writer[0], writer[1])
    raise TypeError(
        "writer must implement write/delete or be a (write, delete) pair, got "
        f"{type(writer).__name__}"
    )


__all__ = ["CacheWriter", "CallableCacheWriter", "as_cache_writer"]
