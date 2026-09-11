"""缓存框架内部基础设施接口。

中文
----
缓存框架内部基础设施接口，提供 L2 缓存开关、类型注册等框架级能力。
仅供 `ops` 层与 `redis.manage` 层内部使用，不暴露给业务侧。

English
--------
Cache framework internal-infrastructure interface.

Mirrors `cn.richie696.component.cache.ops.CacheInfrastructure`. Only
for `ops` layer and `redis.manage` layer internal use, NOT exposed to
business code.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from ..enums.key_type_enum import KeyTypeEnum


class CacheInfrastructure(Protocol):
    """中文
    ----
    缓存框架内部基础设施接口，提供 L2 缓存开关、类型注册等框架级能力。
    仅供 `ops` 层与 `redis.manage` 层内部使用，不暴露给业务侧。

    English
    --------
    Cache framework internal-infrastructure ops. Provides framework-level
    capabilities such as the L2 cache switch and type registration. Only
    for the `ops` and `redis.manage` layers; not exposed to business
    code.
    """

    @abstractmethod
    def get_connection_string(self) -> str:
        """中文
        ----
        获取 Redis 连接信息（调试/日志用）。

        English
        --------
        Get the Redis connection string (debug/log use).
        """
        ...

    @abstractmethod
    def enable_l2_caching(self) -> bool:
        """中文
        ----
        检查是否启用二级缓存。

        English
        --------
        Whether L2 caching is enabled.
        """
        ...

    @abstractmethod
    def enable_key_type_cache(self, key_type: KeyTypeEnum) -> bool:
        """中文
        ----
        检查指定数据类型是否开启二级缓存。

        English
        --------
        Whether L2 caching is enabled for the given key type.
        """
        ...

    @abstractmethod
    def get_value_type(self, key: str) -> type | None:
        """中文
        ----
        获取指定 Key 的已注册值类型。

        English
        --------
        Get the registered value type for the given key.
        """
        ...

    @abstractmethod
    def register_type(self, key: str, clazz: type) -> None:
        """中文
        ----
        注册 Key 的值类型（用于反序列化）。

        English
        --------
        Register the value type for a key (used for deserialisation).
        """
        ...


__all__ = ["CacheInfrastructure"]
