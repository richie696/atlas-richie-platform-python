"""`atlas-richie-sentinel-source-redis` — Redis pub/sub rule source (M6+).

中文
----
Sentinel 家族的**规则源 — Redis pub/sub**(M6+)。把 rule
JSON publish 到 Redis channel,所有订阅者热重载。轻量级
替代 Nacos,适合 Python / Go 混合部署或不想引入 Nacos 的
小团队。

**为什么 M6+ 才做**:
- 用 Redis 的人多,但用 Redis pub/sub 做 rule distribution
  的少(一般用 config key 轮询)
- 跟 Nacos 一起做(M6+ 一并讨论)

English
--------
Sentinel family rule source — Redis pub/sub. Push rule
JSON to a Redis channel, all subscribers hot-reload.
Lightweight alternative to Nacos for mixed-stack or
small-team deployments. Scheduled for M6+.
"""

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # Populated in M6+.
    # "RedisPubSubRuleSource",
]
