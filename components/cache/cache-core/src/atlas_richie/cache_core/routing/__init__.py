"""多实例前缀路由契约（cache-core 侧）。
----
只包含纯逻辑：key 解析、路由表、异常类型。**不**包含任何连接相关
逻辑 —— 那部分在 ``atlas_richie.cache_redis.routing``。

English
--------
Pure routing contract: key parsing, route table, error type. No
connection handling - that lives in ``atlas_richie.cache_redis.routing``.
"""

from __future__ import annotations

from .route_error import CacheRouteError
from .route_key import ROUTE_SEPARATOR, CacheRouteKey
from .route_registry import CacheRouteRegistry

__all__ = [
    "ROUTE_SEPARATOR",
    "CacheRouteError",
    "CacheRouteKey",
    "CacheRouteRegistry",
]
