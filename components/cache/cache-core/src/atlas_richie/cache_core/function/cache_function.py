"""缓存函数基础接口。
----
缓存函数。提供锁 key 前缀、锁过期时间、DB 加载锁过期时间等公共常量，
以及生成 1~10 分钟随机毫秒数（防止出现缓存雪崩）的工具方法。

English
--------
Cache function base interface.

Provides the public lock key prefix, lock TTL, DB-loader lock TTL, and
a static helper that returns a random millis value in [1, 10] minutes
(used to prevent cache stampede).
"""

from __future__ import annotations

import secrets
from typing import Protocol


class CacheFunction(Protocol):
    """缓存函数。

    提供以下公共成员：
    - `LOCK_KEY`：锁的 key 前缀
    - `TIME_OUT`：锁的过期时间（秒）
    - `DB_LOADER_TIME_OUT`：数据库加载锁的过期时间（秒）
    - `get_random_extra_millis()`：生成 1~10 分钟的随机毫秒数（防止出现缓存雪崩）
    """

    #: 锁的 key 前缀
    LOCK_KEY = "LOCK_KEY_"
    #: 锁的过期时间
    TIME_OUT = 3
    #: 数据库加载锁的过期时间
    DB_LOADER_TIME_OUT = 10

    @staticmethod
    def get_random_extra_millis() -> int:
        """生成 1~10 分钟的随机毫秒数（防止出现缓存雪崩）。

        Returns:
            随机毫秒数（1~10 分钟）。

        English
        --------
        Generate a random millis value in [1, 10] minutes to prevent
        cache stampede.

        Returns:
            A random millis value between 1 and 10 minutes.
        """
        return secrets.randbelow(10) * 60_000 + 60_000


__all__ = ["CacheFunction"]
