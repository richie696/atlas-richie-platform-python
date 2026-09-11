"""分布式限流 API。

中文
----
分布式限流 API，封装基于 Redis 的固定窗口计数器。
适用于接口防刷、限流、突发流量控制等场景。

English
--------
Rate-limiter ops interface.

Mirrors `cn.richie696.component.cache.ops.LimiterOps`. Encapsulates
Redis-based fixed-window counter rate limiting. Suitable for
anti-brush / rate-limit / burst control scenarios.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol


class LimiterOps(Protocol):
    """中文
    ----
    分布式限流 API，封装基于 Redis 的固定窗口计数器。适用于接口防刷、
    限流、突发流量控制等场景。

    English
    --------
    Distributed rate-limiter ops, encapsulating Redis-based
    fixed-window counter rate limiting. Suitable for anti-brush,
    rate-limit, and burst-control scenarios.
    """

    @abstractmethod
    def try_acquire(self, key: str, max_count: int, window_seconds: int) -> bool:
        """中文
        ----
        固定窗口限流，判断是否允许通过。

        Args:
            key: 限流标识键
            max_count: 窗口内最大请求数
            window_seconds: 窗口时间（秒）

        Returns:
            `True` 表示允许通过，`False` 表示被限流

        English
        --------
        Fixed-window rate-limit check.

        Args:
            key: Rate-limit identifier key.
            max_count: Maximum request count per window.
            window_seconds: Window length in seconds.

        Returns:
            `True` if allowed, `False` if rate-limited.
        """
        ...


__all__ = ["LimiterOps"]
