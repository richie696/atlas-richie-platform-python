"""Redis 命令复杂度分级。
----
Redis 操作在 ToC 场景下的复杂度分级，用于文档与 `RedisPerfGuard` 的策略判定。

总序：`O1` > `LOG_N` > `LINEAR_N` > `WORSE` > `SCRIPT_OR_UNKNOWN`

对位 Java `cn.richie696.component.cache.redis.perf.RedisComplexityTier`。
Python 侧此前**没有任何分级概念**——`RedisPerfGuard.check_complexity` 存在但
零调用点，manager 也不声明自己操作的复杂度。本枚举把那层缺失补回来。

English
--------
Complexity tiers for Redis operations under the ToC (traffic-of-the-City)
profile, used by the guard's policy checks.

Total order: O1 > LOG_N > LINEAR_N > WORSE > SCRIPT_OR_UNKNOWN.
"""

from __future__ import annotations

from enum import StrEnum


class RedisComplexityTier(StrEnum):
    """Redis 操作的复杂度分级。

    English
    --------
    Complexity tier of a Redis operation.
    """

    #: 常数级：核心链路推荐。
    O1 = "O1"

    #: 对数级：有序结构（如 ZSet）相关，可控范围内可用。
    LOG_N = "LOG_N"

    #: 线性级：与元素数、扫描范围相关；ToC 高并发下默认禁用或仅离线/管理端。
    LINEAR_N = "LINEAR_N"

    #: 更差（O(n log n)、O(n²)、指数级等）：严禁在 ToC 核心路径使用。
    WORSE = "WORSE"

    #: 由脚本/自定义逻辑决定（如 Lua），无法在封装层统一归类。
    SCRIPT_OR_UNKNOWN = "SCRIPT_OR_UNKNOWN"


#: ToC 核心路径上会被直接拦截的分级（与 Java `shouldBlock` 一致）。
#: `LOG_N` 与 `SCRIPT_OR_UNKNOWN` 不在列——前者可控，后者无法静态判定。
BLOCKED_TIERS: frozenset[RedisComplexityTier] = frozenset(
    {RedisComplexityTier.LINEAR_N, RedisComplexityTier.WORSE}
)


__all__ = ["BLOCKED_TIERS", "RedisComplexityTier"]
