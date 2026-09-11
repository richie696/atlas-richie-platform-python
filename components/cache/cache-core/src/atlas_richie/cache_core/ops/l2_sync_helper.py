"""二级缓存（L2）同步辅助类。

中文
----
二级缓存（L2）同步辅助类。
集中处理 `LocalCache` 的读写、删除和过期逻辑，避免在各 Ops 实现中重复
`if (enableL2Caching() && enableKeyTypeCache(...))` 判断。

English
--------
L2 (second-tier cache) sync helper.

Mirrors `cn.richie696.component.cache.ops.L2SyncHelper` (a `@Component`
class in Java). Centralises the L2 read/write/delete/expiry logic so
individual `XxxOpsImpl` classes don't need to repeat
`if (enableL2Caching() && enableKeyTypeCache(...))` checks.
"""

from __future__ import annotations

from typing import Callable, TypeVar

from ..enums.key_type_enum import KeyTypeEnum
from ..enums.l2_caching_region import L2CachingRegion
from ..local.manage.local_cache import LocalCache
from .cache_infrastructure import CacheInfrastructure

T = TypeVar("T")


class L2SyncHelper:
    """中文
    ----
    二级缓存（L2）同步辅助类。集中处理 `LocalCache` 的读写、删除和过期
    逻辑，避免在各 Ops 实现中重复
    `if (enableL2Caching() && enableKeyTypeCache(...))` 判断。

    English
    --------
    L2 (second-tier cache) sync helper. Centralises the L2 read /
    write / delete / expiry logic so individual `XxxOpsImpl` classes
    don't need to repeat `if (enableL2Caching() &&
    enableKeyTypeCache(...))` checks.
    """

    REGION = L2CachingRegion.GLOBAL_CACHE

    def __init__(self, infra: CacheInfrastructure) -> None:
        """中文
        ----
        初始化 L2SyncHelper，注入 `CacheInfrastructure`。

        English
        --------
        Initialise the L2SyncHelper with a `CacheInfrastructure`.
        """
        self._infra = infra

    def is_enabled(self, key_type: KeyTypeEnum) -> bool:
        """中文
        ----
        是否应对指定数据类型启用 L2 同步。

        English
        --------
        Whether L2 sync should be enabled for the given key type.
        """
        return self._infra.enable_l2_caching() and self._infra.enable_key_type_cache(key_type)

    def put(self, key_type: KeyTypeEnum, key: str, value: T) -> None:
        """中文
        ----
        写入本地缓存（不带过期时间）。

        English
        --------
        Write to the local cache (no expiry).
        """
        if self.is_enabled(key_type):
            LocalCache.put(self.REGION, key, value)

    def put_with_ttl(
        self, key_type: KeyTypeEnum, key: str, value: T, timeout_millis: int
    ) -> None:
        """中文
        ----
        写入本地缓存（带过期时间）。

        English
        --------
        Write to the local cache (with expiry).
        """
        if self.is_enabled(key_type):
            LocalCache.put(self.REGION, key, value)
            LocalCache.expiry(self.REGION, key, timeout_millis)

    def get(self, key_type: KeyTypeEnum, key: str, redis_loader: Callable[[], T | None]) -> T | None:
        """中文
        ----
        从本地缓存读取；若未命中则调用 `redis_loader` 并从 Redis 加载后
        回写。等价于当前 GlobalCache 中 `getWithLocalCache` 的逻辑。

        English
        --------
        Read from the local cache; on miss call `redis_loader` and
        write the result back. Equivalent to `getWithLocalCache` in
        `GlobalCache`.
        """
        if self.is_enabled(key_type):
            cached = LocalCache.get(self.REGION, key)
            if cached is not None:
                return cached
        result = redis_loader()
        if result is not None and self.is_enabled(key_type):
            LocalCache.put(self.REGION, key, result)
        return result

    def get_with_lock(
        self, key_type: KeyTypeEnum, key: str, redis_loader: Callable[[], T | None]
    ) -> T | None:
        """中文
        ----
        从本地缓存读取（带锁场景）；逻辑与 `get` 一致。

        English
        --------
        Read from the local cache (lock scenario); same logic as `get`.
        """
        if self.is_enabled(key_type):
            cached = LocalCache.get(self.REGION, key)
            if cached is not None:
                return cached
        result = redis_loader()
        if result is not None and self.is_enabled(key_type):
            LocalCache.put(self.REGION, key, result)
        return result

    def remove(self, key: str) -> None:
        """中文
        ----
        删除本地缓存。

        English
        --------
        Remove an entry from the local cache.
        """
        if self._infra.enable_l2_caching():
            LocalCache.remove(self.REGION, key)

    def remove_all(self, keys) -> None:
        """中文
        ----
        批量删除本地缓存。

        English
        --------
        Bulk-remove entries from the local cache.
        """
        if self._infra.enable_l2_caching():
            for key in keys:
                LocalCache.remove(self.REGION, key)

    def register_type(self, key: str, clazz: type) -> None:
        """中文
        ----
        注册 key 类型。

        English
        --------
        Register the value type for a key.
        """
        self._infra.register_type(key, clazz)


__all__ = ["L2SyncHelper"]
