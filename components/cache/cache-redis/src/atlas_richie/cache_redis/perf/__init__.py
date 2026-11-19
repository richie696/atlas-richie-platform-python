"""Redis 性能守卫：复杂度分级策略 + String 载荷形状检查。
----
对位 Java `cn.richie696.component.cache.redis.perf` 包：

| Python | Java |
|---|---|
| `RedisComplexityTier` | `RedisComplexityTier` |
| `RedisCommandMeta` | `RedisCommandMeta` |
| `RedisOperationCatalog` | `RedisOperationCatalog` |
| `RedisStringPayloadInspector` | `RedisStringPayloadInspector` |
| `RedisPerfGuard` | `RedisPerfGuard` |

English
--------
Redis performance guard: complexity-tier policy plus String payload shape
inspection.
"""

from __future__ import annotations

from .command_meta import RedisCommandMeta
from .complexity_tier import BLOCKED_TIERS, RedisComplexityTier
from .guard import RedisPerfGuard
from .operation_catalog import RedisOperationCatalog
from .string_payload_inspector import (
    RedisStringPayloadInspector,
    StringPayloadInspection,
    StringPayloadSeverity,
)

__all__ = [
    "BLOCKED_TIERS",
    "RedisCommandMeta",
    "RedisComplexityTier",
    "RedisOperationCatalog",
    "RedisPerfGuard",
    "RedisStringPayloadInspector",
    "StringPayloadInspection",
    "StringPayloadSeverity",
]
