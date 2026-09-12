"""`atlas-richie-sentinel-adapter-httpx` — httpx PoolGuard (R-SENTINEL-4).

中文
----
Sentinel 家族的**httpx 出站连接池保护**(Layer 3 / R-SENTINEL-4)。
通过 `httpx.AsyncBaseTransport` 子类化,hook 进 httpx 的
请求生命周期,**主动拒绝** 超出池水位的连接请求,避免整
服务因下游慢响应 hang 死。

**防护内容**:
- 活跃连接数(per-host)超过阈值 → 主动 raise `PoolExhausted`
- 等待队列长度超过阈值 → 主动 raise `PoolExhausted`
- 单 host 占比 > 80% → 警告(可配置 block)
- 跟 `sentinel-rules` 配合 — per-host 的 FlowRule 也生效

**对位 Java**:
- Java 端没有对应(HTTP 出站对方自己限流,我们的 Python
  服务只防入口)。但 Python httpx 的连接池是 asyncio 共享
  全局,单 host 慢调用会拖死所有 host 调用,所以 Python
  这边这个 adapter 反而是 Java 端没有的创新。

**使用**:
```python
import httpx
from atlas_richie.sentinel_adapter_httpx import SentinelHTTPTransport

transport = SentinelHTTPTransport(
    pool_max_connections=100,
    pool_max_queue_size=200,
)
async with httpx.AsyncClient(transport=transport) as client:
    resp = await client.get("https://api.example.com/data")
```

English
--------
Sentinel family httpx PoolGuard. Hooks into httpx via
AsyncBaseTransport subclass to actively reject
connection requests that exceed pool thresholds,
preventing one slow downstream from hanging the entire
Python service. Java Sentinel has no direct equivalent
since Java outbound callers self-protect; Python
needs this because httpx's pool is asyncio-shared.
"""

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # Populated in R-SENTINEL-4.
    # "SentinelHTTPTransport",
    # "PoolGuard",
    # "PoolExhausted",
    # "PoolStats",
]
