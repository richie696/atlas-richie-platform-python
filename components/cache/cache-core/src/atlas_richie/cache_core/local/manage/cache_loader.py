"""L1 read-through 加载器契约。
----
read-through：本地缓存未命中时，由加载器回源取数并把结果写回缓存。

对位 JSR-107 ``javax.cache.integration.CacheLoader``。Java 侧通过
``CacheDefinition.cacheLoaderClassName``（类名字符串）+ 反射工厂装配；
Python 没有"按类路径字符串反射"这种惯用法，因此改为**注册可调用对象**：
``LocalCacheManager.register_loader(region, loader)``。

English
--------
L1 read-through loader contract.

Mirrors JSR-107 `javax.cache.integration.CacheLoader`. The Java side
wires it through `CacheDefinition.cacheLoaderClassName` (a class-path
string) plus a reflection factory; Python has no classpath-string
reflection idiom, so the loader is **registered as a callable** instead:
`LocalCacheManager.register_loader(region, loader)`.
"""

from __future__ import annotations

from typing import Any, Callable, Collection, Mapping, Protocol, runtime_checkable


@runtime_checkable
class CacheLoader(Protocol):
    """回源加载器。

    English
    --------
    Source-of-truth loader.
    """

    def load(self, key: str) -> Any | None:
        """按 key 回源；返回 ``None`` 表示"无值"，不写入缓存。

        English
        --------
        Load one key; `None` means "no value" and is not cached.
        """
        ...

    def load_all(self, keys: Collection[str]) -> Mapping[str, Any]:
        """批量回源；返回的映射中缺失的 key 视为"无值"。

        English
        --------
        Load several keys; keys absent from the mapping mean "no value".
        """
        ...


class CallableCacheLoader:
    """把普通可调用对象适配成 :class:`CacheLoader`。

    ``loader`` 是 ``key -> value | None`` 的函数。``batch_loader`` 可选：
    提供时用于批量回源；不提供时批量回源退化为逐 key 调用。

    English
    --------
    Adapts a plain callable into a :class:`CacheLoader`.

    `loader` is a `key -> value | None` function. `batch_loader` is
    optional: when given it serves batch loads, otherwise a batch load
    degrades to per-key calls.
    """

    def __init__(
        self,
        loader: Callable[[str], Any],
        batch_loader: Callable[[Collection[str]], Mapping[str, Any]] | None = None,
    ) -> None:
        self._loader = loader
        self._batch_loader = batch_loader

    def load(self, key: str) -> Any | None:
        return self._loader(key)

    def load_all(self, keys: Collection[str]) -> Mapping[str, Any]:
        if self._batch_loader is not None:
            return self._batch_loader(keys)
        loaded: dict[str, Any] = {}
        for key in keys:
            value = self._loader(key)
            if value is not None:
                loaded[key] = value
        return loaded


def as_cache_loader(loader: Any) -> CacheLoader:
    """把入参规范化成 :class:`CacheLoader`。

    接受：实现了 ``load`` / ``load_all`` 的对象，或单个
    ``key -> value | None`` 可调用对象。

    English
    --------
    Normalise `loader` into a :class:`CacheLoader`. Accepts an object
    implementing `load` / `load_all`, or a single
    `key -> value | None` callable.
    """
    if hasattr(loader, "load") and hasattr(loader, "load_all"):
        return loader
    if callable(loader):
        return CallableCacheLoader(loader)
    raise TypeError(
        "loader must implement load/load_all or be a callable, got "
        f"{type(loader).__name__}"
    )


__all__ = ["CacheLoader", "CallableCacheLoader", "as_cache_loader"]
