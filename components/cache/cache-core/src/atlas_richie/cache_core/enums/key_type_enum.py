"""缓存键类型枚举。
----
缓存键类型枚举。列出缓存中键的可用 Redis 数据结构类型。

English
--------
Key type enum (Redis data structure classification).

Mirrors `cn.richie696.component.cache.enums.KeyTypeEnum`.
"""

from __future__ import annotations

from enum import StrEnum


class KeyTypeEnum(StrEnum):
    """缓存键类型枚举。

    English
    --------
    Cache key type enum.
    """

    #: Redis String 类型，适用于存储简单的字符串值
    STRING = "string"

    #: Redis Hash 类型，适用于存储键值对集合的场景
    HASH = "hash"

    #: Redis List 类型，适用于需要有序列表的场景
    LIST = "list"

    #: Redis Set 类型，适用于需要唯一性和集合操作的场景
    SET = "set"


__all__ = ["KeyTypeEnum"]
