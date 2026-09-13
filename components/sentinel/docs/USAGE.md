# Atlas Richie Sentinel — 1.0 使用手册 (USAGE)

> **状态**: 1.0 publish 准备中 (M6+ 收口阶段)
> **配套 design**: `docs/process/M6.3-CLUSTER-TOKEN-DESIGN.md` / `docs/process/M6.7-WSGI-SYNC-EVAL.md`
> **配套 plan**: `docs/process/PLANNING.md`
> **配套 wire protocol**: `docs/protocol/集群令牌协议-v1.md` (M6.3.1) / `docs/protocol/上报协议-01-envelope-v1.md` (M6.5.7)

---

## 0. 重要部署前提: **ASGI 是 1.x 唯一支持部署**

| 部署 | 1.x 支持 |
| --- | --- |
| **ASGI** (Django 3.0+ 异步视图 / FastAPI / Starlette / Quart / Uvicorn / Hypercorn) | ✅ 支持 |
| **Django / Flask / 传统 WSGI** (gunicorn `--workers N` 默认, `preload_app=True`) | ❌ **不支持** |
| **同步 HTTP 客户端** (`requests` / `httpx.Client()` 同步) | ❌ **不支持** |
| **WSGI bridge 强行包** (asgiref / greenlet / nest_asyncio) | ❌ **不支持** (不引入主包) |

**理由** (详见 `docs/process/M6.7-WSGI-SYNC-EVAL.md`):

- `SentinelEngine` 状态机锁是 `asyncio.Lock` (engine/sentinel_engine.py:203), 同步线程无法 await
- `RuleSourceSupervisor` 后台 task 启动依赖 event loop (supervisor.py:238, 335)
- `EntryLease` 假设 "asyncio.Task 有自己的 contextvars.Context" (entry.py:99-103), WSGI 无 Task
- 取消依赖 `asyncio.CancelledError`, WSGI kill -TERM 不抛
- 同步路径 (`asyncio.run` 反复 / 跨线程 facade) 相对 asyncio 基线 p99 > 20%, 任一不满足 PLANNING §M6.7 决策矩阵 "不支持" 阈值

**用户行动**: 升级到 ASGI (推荐 FastAPI + Uvicorn), 或在 WSGI 视图里**不**使用 Sentinel (用 1.x 限流直接走 FastAPI / Starlette lifespan)。

---

## 1. 安装 (1.0)

主包 0 依赖:

```bash
pip install atlas-richie-sentinel
```

按需装可选 extension:

```bash
# ASGI ingress protection (Django 异步视图 / FastAPI / Starlette)
pip install atlas-richie-sentinel-adapter-asgi

# httpx 客户端限流
pip install atlas-richie-sentinel-adapter-httpx

# 规则源 (按需装, 不影响主包)
pip install atlas-richie-sentinel-source-file      # 文件规则源
pip install atlas-richie-sentinel-source-nacos     # Nacos 规则源 (polling 1.0)
pip install atlas-richie-sentinel-source-redis     # (保留, M6.2 取消, 不在 1.0)

# Cluster (M6.3 实施后, 1.0 publish)
pip install atlas-richie-sentinel-cluster          # 多进程 token quota 协调
```

---

## 2. 快速开始 (FastAPI / ASGI)

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from atlas_richie.sentinel import SentinelEngine
from atlas_richie.sentinel.slots.flow import FlowSlot, FlowRule
from atlas_richie.sentinel.model.resource import Resource

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with SentinelEngine() as engine:
        engine.add_slot(FlowSlot(rules=[
            FlowRule(resource="/api/v1/users", grade=1, count=100),  # 100 QPS
        ]))
        app.state.engine = engine
        yield

app = FastAPI(lifespan=lifespan)

@app.get("/api/v1/users")
async def users():
    async with app.state.engine.entry(Resource("/api/v1/users")) as entry:
        # 业务逻辑
        return {"users": [...]}
```

---

## 3. 集群 (M6.3 实施后, 1.0 publish)

```bash
# 启独立 Server (单进程, 1.0 接受限制: Server 重启 lease 失效)
python -m atlas_richie.sentinel_cluster --bind 0.0.0.0:8765 \
    --config /etc/sentinel/cluster.json
```

`cluster.json` (stdlib json, 1.0 不支持 YAML):

```json
{
  "cluster_token_mode": "standalone",
  "server_addresses": ["0.0.0.0:8765"],
  "auth_token": "shared-secret-here",
  "resources": {
    "/api/v1/users": {
      "max_permits": 100,
      "failure_policy": "fail_closed"
    }
  },
  "request_timeout_ns": 5000000,
  "shutdown_timeout": 5.0
}
```

Client 端 (应用进程):

```python
from atlas_richie.sentinel_cluster import RemoteTokenService, ClusterTokenConfig
from atlas_richie.sentinel.ports.token import ClusterFailurePolicy

config = ClusterTokenConfig(
    cluster_token_mode="client_only",
    server_addresses=["cluster.internal:8765"],
    auth_token="shared-secret-here",
    failure_policy_per_resource={
        "/api/v1/users": ClusterFailurePolicy.FAIL_CLOSED,
    },
)
remote_ts = RemoteTokenService(config, identity=my_client_identity)
```

**强约束** (M6.3 design + 5 owner sign-off):

- ❌ 不用 worker ordinal 选主 / leader election / 服务发现猜测 owner
- ❌ 不用进程内 map 偷渡 remote lease 状态
- ❌ 不用 `asyncio.run()` 反复构造 fake loop (M6.7 评估已论证)
- ❌ 不用跨线程共享 Engine event loop (M6.7 决策)
- 每个集群资源**必须**显式配 `ClusterFailurePolicy` 一项, 启动 fail-fast
- Cluster wheel 0 3rd-party 依赖 (跟主包一致)

---

## 4. 1.x → 1.x 末迁移 (LocalTokenService 不变)

`LocalTokenService` 1.0 行为**完全不变**:

```python
from atlas_richie.sentinel.ports.token import LocalTokenService

svc = LocalTokenService()
resp = svc.acquire(resource="/api/v1/users", permits=1.0)
# resp.decision = LOCAL_GRANTED (永远)
# resp.token.lease_id = None (永远, 1.0 LocalTokenService 不填)
# resp.token.owner_epoch = None (永远)
# resp.retry_after_ns = 0 (永远)
```

`Token` / `TokenResponse` 既有 4 字段构造方式仍 work (新字段默认值):

```python
from atlas_richie.sentinel.ports.token import Token, TokenResponse, TokenDecision

# 旧构造 (M6.3.2 之前): 仍 work
token = Token(
    resource="/api/v1/users",
    permits=1.0,
    issued_at_ns=time.time_ns(),
    ttl_ns=0,
)

# 新构造 (M6.3.2+): 显式填 lease_id / owner_epoch (集群用)
token_cluster = Token(
    resource="/api/v1/users",
    permits=1.0,
    issued_at_ns=time.time_ns(),
    ttl_ns=30_000_000_000,  # 30s
    lease_id="550e8400-...",  # Server 生成的 opaque identity
    owner_epoch=0,            # fencing
)
```

---

## 5. 故障排查

| 错误 / 现象 | 含义 | 处理 |
| --- | --- | --- |
| `STALE_EPOCH` 错误码 | 旧 epoch 迟到 release / renew (正常 race 现象) | **不**抛异常, Client 仅 log warn, 业务继续 |
| `LEASE_EXPIRED` 错误码 | renew 时 lease 已超过 expires_at | log warn, 需重新 acquire |
| `LEASE_NOT_FOUND` 错误码 | release / renew 时 lease_id 不存在 (已被清理) | log warn, 业务继续 |
| `RESOURCE_NOT_CONFIGURED` | Server 端启动期校验发现 resource 未配 | 部署错误, 在 config 里加 resource + 选 1 项 ClusterFailurePolicy |
| `SERVER_OVERLOADED` | Server 资源满, DENIED + deny_reason=SERVER_OVERLOADED | 按 ClusterFailurePolicy 决策 (FAIL_CLOSED 真 deny / FAIL_OPEN 放行 + 指标) |
| `REMOTE_UNAVAILABLE` | Server 不可达 / 协议错 | 同 SERVER_OVERLOADED, 按 ClusterFailurePolicy 决策 |
| `PROTOCOL_VERSION_MISMATCH` | wire protocol version 不一致 | retry 无效, 升级 SDK; 标 ClusterFailurePolicy 决策 |
| p99 突然变慢 | 同进程有 WSGI 视图 (违反 §0) | 升级 ASGI; 1.x 不支持同步, 2.x ADR 起草后再说 |
| fork 后 asyncio.Lock 报错 | gunicorn `preload_app=True` + Sentinel 同进程 | 改 `preload_app=False` + `--workers 1`; Cluster wheel 文档化 |

---

## 6. 已知限制 (1.0)

| 限制 | 原因 | 后续 |
| --- | --- | --- |
| **WSGI / 同步 HTTP 客户端 1.x 不支持** | M6.7 评估 (见 §0) | 2.x ADR (条件触发: ≥3 个独立社区反馈) |
| **Server 进程内 store 不持久化** | 1.0 接受, "Server 重启期间 active lease 失效" | M6.3.x future Redis HA (独立 ADR) |
| **Embedded Server 单 worker 限制** | 多 worker 状态分裂, 启动 assert + fail-fast | client_only + 独立 Server 是推荐 |
| **YAML cluster config 不支持** | 1.0 避免 `pyyaml` 依赖 | 用户用 stdlib `json` 或自带 `pyyaml` 转 dict |
| **Server 跨实例不共享 idempotency cache** | 1.0 进程内 cache, 5 min TTL | 跨实例共享留 M6.3.x future |
| **Reporting 投递 1.0 stub** | M6.5.7 envelope V1 frozen, M6.5.1-6 实施留 worker | M6.5.x 系列 |
| **跨语言 SDK 1.0 未实施** | 1.0 仅 Python 投影 (contracts 仓 `atlas_richie.cluster.v1` + `atlas_richie.reporting.v1`) | 1.0 publish 前 worker 跑 Go / Java mock round-trip |

---

## 7. 进一步阅读

- 快速开始: `components/sentinel/sentinel/README.md`
- 设计阶段: `docs/process/M6.3-CLUSTER-TOKEN-DESIGN.md` / `docs/process/M6.7-WSGI-SYNC-EVAL.md`
- 实施计划: `docs/M6.3-IMPLEMENTATION-PLAN.md`
- 协议: `docs/protocol/集群令牌协议-v1.md` / `docs/protocol/上报协议-01-envelope-v1.md` (envelope) / `docs/protocol/上报协议-02-transport-v1.md` (transport) / `docs/protocol/上报协议-03-freeze-v1.md` (sign-off)
- 总规划: `docs/process/PLANNING.md`

---

**Document version**: 1.0 (M6+ 收口阶段, 1.0 publish 前冻结)
**Last updated**: 2026-09-13
