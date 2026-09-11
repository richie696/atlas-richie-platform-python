"""Snowflake ID 生成器接口。
----
Snowflake ID 生成器契约，`workerId` 由 Redis 持久化。
64 位布局为 `(41 bits timestamp) | (10 bits worker) | (12 bits sequence)`，
起始时间戳（epoch）为 `2020-05-03 UTC`。

English
--------
Snowflake ID builder contract.

Mirrors `cn.richie696.component.cache.redis.snowflake.IdBuilder`.
The 64-bit layout is `(41 bits timestamp) | (10 bits worker) | (12 bits sequence)`
with epoch `2020-05-03 UTC` (matches Java).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol


class SnowflakeIdBuilder(Protocol):
    """Snowflake ID 生成器，`workerId` 由 Redis 持久化。

    English
    --------
    Snowflake ID generator with Redis-persisted `workerId`.
    """

    @abstractmethod
    def next_id(self) -> int:
        """生成全局唯一的 64 位 ID。

        Returns:
            内嵌时间戳、worker 与序列号的 64 位 ID。

        English
        --------
        Generate a globally unique 64-bit ID.

        Returns:
            A 64-bit ID with embedded timestamp, worker, and sequence.
        """
        ...


__all__ = ["SnowflakeIdBuilder"]
