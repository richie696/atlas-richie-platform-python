"""多实例前缀路由（cache-redis 侧）。
----
把 core 侧的路由契约（``atlas_richie.cache_core.routing``）接到真实
的 Redis 连接上：

- ``RedisCommandKeySpec`` / ``RedisCommandKeySpecTable`` —— 命令的
  key 位置表；
- ``RedisRoutingClient`` —— 按 key 前缀路由 + 改写 key 的客户端代理；
- ``RedisRoutingPipeline`` —— 按实例分组执行的 pipeline；
- ``MultiRedisDistributedCache`` —— 主实例 + 从实例的统一入口。

English
--------
Wires the core routing contract (``atlas_richie.cache_core.routing``)
to real Redis connections.
"""

from __future__ import annotations

from .command_specs import (
    DEFAULT_COMMAND_KEY_SPECS,
    DEFAULT_COMMAND_KEY_SPEC_TABLE,
    KEYLESS_COMMANDS,
    RedisCommandKeySpec,
    RedisCommandKeySpecTable,
)
from .multi_distributed_cache import MultiRedisDistributedCache
from .route_client import RedisRoutingClient
from .route_pipeline import RedisRoutingPipeline

__all__ = [
    "DEFAULT_COMMAND_KEY_SPECS",
    "DEFAULT_COMMAND_KEY_SPEC_TABLE",
    "KEYLESS_COMMANDS",
    "MultiRedisDistributedCache",
    "RedisCommandKeySpec",
    "RedisCommandKeySpecTable",
    "RedisRoutingClient",
    "RedisRoutingPipeline",
]
