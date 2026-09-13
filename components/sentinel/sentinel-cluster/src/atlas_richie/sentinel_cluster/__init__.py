"""``atlas-richie-sentinel-cluster`` — distributed cluster mode (M6.3).

中文
----
Sentinel 家族的**集群模式** (M6.3)。把多个 Python 进程的 Flow/Degrade
统计聚合成全局视角, 实现共享配额 (lease) 协调。1.0 进程内 Server + HTTP/1.1
+ JSON wire protocol, **不**依赖 Redis / gRPC / aiohttp (Cluster wheel 0
3rd-party)。

**架构分层** (跟 M6.3-CLUSTER-TOKEN-DESIGN.md §2 一致):

- **主包 sentinel**: ``TokenService`` Port + ``LocalTokenService`` 默认实现
  (永远 LOCAL_GRANTED), 零 Cluster / Redis 依赖
- **集群 wheel (本仓)**: ``TokenServer`` (资源分配状态机) + ``HttpTransport``
  (HTTP/1.1 + JSON) + ``StandaloneTokenServer`` / ``EmbeddedTokenServer`` 启动形态
- **wire protocol 投影**: ``atlas_richie.contracts.cluster.v1`` (Foundation wheel,
  跨语言 wire schema frozen)

**1.0 公开 API** (本任务实现 M6.3.3 + M6.3.5; M6.3.4 Client 留 Worker 2):

- ``ClusterTokenConfig`` — frozen dataclass (启动配置)
- ``ClusterTokenMode`` — StrEnum (standalone / embedded / client_only)
- ``ResourceConfig`` — 单 resource 配额 (max_permits / initial_permits)
- ``TokenServer`` — 资源分配状态机
- ``TokenServerState`` — 状态枚举
- ``TokenServerStats`` — 运行时统计 snapshot
- ``StandaloneTokenServer`` — 独立进程 wrapper (CLI 路径)
- ``EmbeddedTokenServer`` — 进程内 wrapper (单 worker 强约束)
- ``HttpTransport`` — HTTP/1.1 + JSON 传输
- ``LeaseStore`` — 进程内 lease + 配额 store
- ``Lease`` — Server 生成的 opaque lease 句柄
- ``IdempotencyCache`` — request_id 短期 cache (5 min TTL)
- 错误类: ``ClusterServerError`` / ``ClusterConfigError`` /
  ``ClusterLeaseNotFound`` / ``ClusterLeaseExpired`` / ``ClusterStaleEpoch`` /
  ``ClusterResourceNotConfigured`` / ``ClusterServerOverloaded``

**关键不变量** (PLANNING §M6.3 验收):

- **FAIL_CLOSED** 实际 grant 总量不得超出 Server 认定的配额
- **FAIL_OPEN** 不承诺不超发, 但每次放行都必须有可查询决策 + 指标
- **LOCAL_FALLBACK** 显式配置本地策略, **不**伪装共享配额
- **禁止默认静默放行** (每个 cluster resource 必须显式配 ClusterFailurePolicy)
- **Server 决定 lease 有效性** (Client 不能按本机时钟续约/回收)
- **opaque lease identity** (Server 生成, Client 不能伪造)
- **owner epoch fencing** (旧 epoch 迟到 release / renew 不影响新 epoch)
- **idempotency key** (重复请求用同 request_id 不双扣)
- **wire schema 跨语言** (Python 字段不能直接序列化, 用 stable 值)
- **主包零 Cluster / Redis 依赖**

**不在 1.0 范围** (留 M6.3.x future):

- ❌ ``RemoteTokenService`` (Client, M6.3.4 Worker 2 实施)
- ❌ 任何 ``ClusterTokenClient`` / ``ClusterClient`` (M6.3.4 命名)
- ❌ Server 进程内 store 持久化 (Server 重启 lease 失效, 设计 §8 接受)
- ❌ mTLS / OAuth 鉴权 (1.0 仅 shared secret)
- ❌ Embedded Server 多 worker 模式 (强制单 worker 启动 fail-fast)
- ❌ 服务发现 / leader election / 按 worker ordinal 选主

English
--------
Sentinel family **cluster mode** (M6.3). Aggregates Flow/Degrade stats
across multiple Python processes into a global view, implementing
shared quota (lease) coordination. 1.0 ships an in-process Server over
HTTP/1.1 + JSON wire protocol, with **zero** Redis / gRPC / aiohttp
dependencies (Cluster wheel is 0 3rd-party).

Architecture (per M6.3-CLUSTER-TOKEN-DESIGN.md §2):

- **main sentinel**: ``TokenService`` Port + ``LocalTokenService`` default
  (always LOCAL_GRANTED), zero Cluster / Redis deps
- **cluster wheel (this package)**: ``TokenServer`` (state machine) +
  ``HttpTransport`` (HTTP/1.1 + JSON) + ``StandaloneTokenServer`` /
  ``EmbeddedTokenServer`` startup modes
- **wire protocol projection**: ``atlas_richie.contracts.cluster.v1``
  (Foundation wheel, cross-language schema frozen)

1.0 public API (M6.3.3 + M6.3.5; M6.3.4 Client deferred to Worker 2):

- ``ClusterTokenConfig`` — frozen dataclass (startup config)
- ``ClusterTokenMode`` — StrEnum (standalone / embedded / client_only)
- ``ResourceConfig`` — per-resource quota
- ``TokenServer`` — resource allocation state machine
- ``TokenServerState`` — state enum
- ``TokenServerStats`` — runtime stats snapshot
- ``StandaloneTokenServer`` — standalone process wrapper (CLI path)
- ``EmbeddedTokenServer`` — in-process wrapper (single-worker strict)
- ``HttpTransport`` — HTTP/1.1 + JSON transport
- ``LeaseStore`` — in-process lease + quota store
- ``Lease`` — Server-generated opaque lease handle
- ``IdempotencyCache`` — request_id short-term cache (5 min TTL)
- Errors: ``ClusterServerError`` / ``ClusterConfigError`` /
  ``ClusterLeaseNotFound`` / ``ClusterLeaseExpired`` / ``ClusterStaleEpoch`` /
  ``ClusterResourceNotConfigured`` / ``ClusterServerOverloaded``

Key invariants (PLANNING §M6.3 acceptance):

- **FAIL_CLOSED**: actual grant total never exceeds Server-admitted quota
- **FAIL_OPEN**: no over-grant promise; every pass produces queryable decision + metric
- **LOCAL_FALLBACK**: explicit local policy; **not** disguised as shared quota
- **forbidden** default silent pass: every cluster resource must explicitly
  choose a ClusterFailurePolicy
- **Server is the lease authority**: Client cannot renew / return by local clock
- **opaque lease identity**: Server-generated, Client cannot forge
- **owner epoch fencing**: stale-epoch release / renew cannot affect new epoch
- **idempotency key**: same request_id never double-charges
- **wire schema cross-language**: Python fields don't serialize directly,
  use stable values
- **main wheel zero Cluster / Redis deps**

Out of 1.0 scope (deferred to M6.3.x future):

- ❌ ``RemoteTokenService`` (Client, M6.3.4 Worker 2)
- ❌ any ``ClusterTokenClient`` / ``ClusterClient`` (M6.3.4 naming)
- ❌ Server in-process store persistence (restart invalidates leases, design §8)
- ❌ mTLS / OAuth auth (1.0 shared secret only)
- ❌ Embedded Server multi-worker (strict single-worker, fail-fast on multi)
- ❌ service discovery / leader election / worker-ordinal master selection
"""

from __future__ import annotations

from .config import ClusterTokenConfig, ClusterTokenMode, ResourceConfig
from .errors import (
    ClusterConfigError,
    ClusterLeaseExpired,
    ClusterLeaseNotFound,
    ClusterResourceNotConfigured,
    ClusterServerError,
    ClusterServerOverloaded,
    ClusterStaleEpoch,
)
from .server import (
    EmbeddedTokenServer,
    HttpTransport,
    IdempotencyCache,
    CacheEntry,
    Lease,
    LeaseStore,
    StandaloneTokenServer,
    TokenServer,
    TokenServerState,
    TokenServerStats,
    epoch_key,
    main,
)

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # 配置 (M6.3.5)
    "ClusterTokenConfig",
    "ClusterTokenMode",
    "ResourceConfig",
    # 错误 (M6.3.3)
    "ClusterServerError",
    "ClusterConfigError",
    "ClusterLeaseNotFound",
    "ClusterLeaseExpired",
    "ClusterStaleEpoch",
    "ClusterResourceNotConfigured",
    "ClusterServerOverloaded",
    # Server 端 (M6.3.3 + M6.3.5)
    "TokenServer",
    "TokenServerState",
    "TokenServerStats",
    "StandaloneTokenServer",
    "EmbeddedTokenServer",
    "HttpTransport",
    "LeaseStore",
    "Lease",
    "IdempotencyCache",
    "CacheEntry",
    "epoch_key",
    # CLI 入口 (standalone)
    "main",
]
