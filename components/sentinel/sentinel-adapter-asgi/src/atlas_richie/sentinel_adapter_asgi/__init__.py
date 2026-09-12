"""`atlas-richie-sentinel-adapter-asgi` — ASGI ingress adapter (R-SENTINEL-2).

中文
----
Sentinel 家族的**ASGI 入口适配器**(Layer 3 / R-SENTINEL-2)。
把任意 ASGI app(FastAPI / Starlette / Quart)包一层,实现
**服务级防护**:

- `SystemSlot` — 监控进程 CPU / Load / 入口 QPS / 平均 RT /
  并发线程数,触发了自动 503 整服务降级
- `WorkerSlot` — 守护 asyncio 任务队列,worker 排队太长
  主动 503
- 跟 `sentinel-rules` 配合 — 每个 route 都可以加
  `@sentinel_resource("order:create", flow=[...])`
- 跟 `sentinel-source-file` 配合 — 启动时加载 YAML 规则

**对位 Java**:
- `sentinel-spring-cloud-gateway-adapter`(Spring Cloud Gateway
  入口的 Sentinel 适配)
- Java 守护 Netty event loop 线程池;Python 守护
  uvicorn worker 的 asyncio loop

**使用**:
```python
from fastapi import FastAPI
from atlas_richie.sentinel_adapter_asgi import SentinelASGIMiddleware

app = FastAPI()
app.add_middleware(SentinelASGIMiddleware)
```

English
--------
Sentinel family ASGI ingress adapter. Wraps any ASGI
app to provide service-level protection: SystemSlot
monitors CPU/Load/QPS/RT, WorkerSlot guards asyncio
queue depth. Mirrors Java
sentinel-spring-cloud-gateway-adapter.
"""

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # Populated in R-SENTINEL-2.
    # "SentinelASGIMiddleware",
    # "SentinelASGIConfig",
    # "WorkerSlot",
]
