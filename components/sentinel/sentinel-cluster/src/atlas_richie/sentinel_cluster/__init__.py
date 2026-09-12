"""`atlas-richie-sentinel-cluster` — distributed cluster mode (M6+).

中文
----
Sentinel 家族的**集群模式**(M6+)。把多个 Python 进程的
Flow/Degrade 统计聚合成全局视角,实现:

- **Token server 模式**:1 个 token server 进程,其他 client
  进程通过 gRPC / HTTP 拉全局统计
- **Embedded 模式**:所有进程通过 Redis 共享 token bucket
  状态,无中心化

**对位 Java**:
- `sentinel-cluster` 包的 `TokenClient` / `TokenServer`
- 1:1 翻译 token 分配协议

**为什么 M6+ 才做**:
- MVP 阶段单进程 FlowRule 已经够用
- 集群模式需要 cluster server 部署,对用户友好度要求高
- 跟 `sentinel-dashboard` 一起做更合理

English
--------
Sentinel family distributed cluster mode. Aggregates
Flow/Degrade statistics across multiple Python
processes via gRPC token-server or Redis embedded
mode. Mirrors Java sentinel-cluster. Scheduled for
M6+ since MVP can rely on single-process FlowRule.
"""

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # Populated in M6+.
    # "ClusterClient",
    # "ClusterServer",
    # "ClusterMode",
    # "TokenRequest",
    # "TokenResponse",
]
