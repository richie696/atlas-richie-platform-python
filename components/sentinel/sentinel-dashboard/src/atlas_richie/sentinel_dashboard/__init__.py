"""`atlas-richie-sentinel-dashboard` — control panel (M5).

中文
----
Sentinel 家族的**控制台**(M5)。一个轻量级 FastAPI 应用,
暴露:

- 实时 metrics:`/api/metrics?resource=order:create` →
  QPS / pass / block / RT histogram
- 规则查询:`GET /api/rules?type=flow`
- 规则推送:`POST /api/rules?type=flow`(立即生效,无需
  重启被保护的服务)
- 节点列表:`GET /api/resources`(当前被监控的所有 resource)
- 健康检查:`GET /healthz`

**部署方式**:
- 单独一个进程,跟被保护的服务共享一个 Redis
  (`sentinel-cluster` 模式)或 in-process bus(file watcher)
- 单 binary:`uvicorn atlas_richie.sentinel_dashboard:app`

**对位 Java**:
- `sentinel-dashboard` Java 应用
- 提供 web UI + REST API(我们 MVP 阶段只做 REST API,
  web UI 留作 v1.1)

**为什么 M5 才做**:
- MVP 阶段 file 源已经够用
- dashboard 价值在集群模式(多个 Python 实例统一管控)
- 跟 `sentinel-cluster` 一起做

English
--------
Sentinel family control panel (M5). Lightweight FastAPI
app exposing real-time metrics + dynamic rule push
via REST. Mirrors Java sentinel-dashboard. Scheduled
for M5 since MVP can rely on file source.
"""

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # Populated in M5.
    # "create_app",
    # "MetricsView",
    # "RuleView",
    # "ResourceView",
]
