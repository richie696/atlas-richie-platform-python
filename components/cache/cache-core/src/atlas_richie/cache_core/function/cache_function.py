"""缓存函数基础接口。
----
缓存函数。提供锁 key 前缀、锁过期时间、DB 加载锁过期时间等公共常量，
以及生成 1~10 分钟随机毫秒数（防止出现缓存雪崩）的工具方法。

``get_random_extra_millis()`` 是**全平台唯一的防雪崩抖动实现**：Redis
驱动（``atlas-richie-cache-redis``）在写 TTL 时一律回调本方法，不允许
在适配器里另写一份分布不同的实现。

English
--------
Cache function base interface.

Provides the public lock key prefix, lock TTL, DB-loader lock TTL, and
a static helper that returns a random millis value in [1, 10] minutes
(used to prevent cache stampede).

`get_random_extra_millis()` is the **single anti-avalanche jitter
implementation in the platform**: the Redis driver
(`atlas-richie-cache-redis`) always calls back into it when writing a
TTL, and adapters must not grow their own copy with a different
distribution.
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

        对位 Java ``CacheFunction.getRandomExtraMillis()``：
        ``ThreadLocalRandom.current().nextInt(1, 11) * 60_000L``。
        两者都是**离散**的整分钟档，取值集合恒为
        ``{60_000, 120_000, ..., 600_000}``（10 档等概率）。

        Returns:
            随机毫秒数（1~10 分钟，整分钟档）。

        English
        --------
        Generate a random millis value in [1, 10] minutes to prevent
        cache stampede.

        Mirrors Java's `CacheFunction.getRandomExtraMillis()`
        (`ThreadLocalRandom.current().nextInt(1, 11) * 60_000L`): both
        are **discrete** whole-minute buckets, always drawn from
        `{60_000, 120_000, ..., 600_000}` (10 equally likely values).

        Returns:
            A random millis value between 1 and 10 minutes, snapped to
            a whole-minute bucket.
        """
        return secrets.randbelow(10) * 60_000 + 60_000


__all__ = ["CacheFunction"]
