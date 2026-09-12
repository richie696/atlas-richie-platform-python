# Atlas Richie Sentinel — Extension Guide

> 1.0 主包(`atlas-richie-sentinel`)已**冻结**核心 API。**新功能
> / 后端 / 数据源 / 控制面一律走独立 wheel**,按 feature 剪裁。本
> 指南是"如何扩"的契约,不是"如何改主包"。
>
> The 1.0 main package (`atlas-richie-sentinel`) has **frozen** the
> core API. New features / backends / data sources / control planes
> live in independent wheels, installable by feature. This guide is
> the contract for "how to extend", not "how to modify the core".

---

## 1. 三个扩展维度(中文)

Atlas Richie Sentinel 的可扩展点分 3 类,**每一类都有独立 wheel**,
互不污染:

| 维度 | 协议 | 1.0 内置 | 1.x 计划 |
| ---- | ---- | -------- | -------- |
| **Adapter**(集成面) | `SentinelEngine` / `FlowSlot` 暴露给 web / 客户端 | `adapter-asgi` / `adapter-httpx` | `adapter-grpc` / `adapter-faststream` |
| **Source**(数据源) | `RuleSource` Protocol(主包) | `source-file`(JSON / YAML) | `source-nacos` / `source-redis` / `source-consul` |
| **Dashboard**(控制面) | REST + admin token | `sentinel-dashboard`(loopback) | `dashboard-cluster` / `dashboard-prometheus` |

每一类扩展**只引入一个独立 wheel**,主包不受影响。

## 1. The three extension axes (English)

Atlas Richie Sentinel's extension surface is divided into 3 axes;
each axis ships in its own wheel, free of cross-contamination:

| Axis | Protocol | 1.0 built-in | 1.x planned |
| ---- | -------- | ------------ | ----------- |
| **Adapter** (integration) | `SentinelEngine` / `FlowSlot` exposed to web / clients | `adapter-asgi` / `adapter-httpx` | `adapter-grpc` / `adapter-faststream` |
| **Source** (data source) | `RuleSource` Protocol (in main package) | `source-file` (JSON / YAML) | `source-nacos` / `source-redis` / `source-consul` |
| **Dashboard** (control plane) | REST + admin token | `sentinel-dashboard` (loopback) | `dashboard-cluster` / `dashboard-prometheus` |

Each axis extension ships as a single new wheel; the main package is
unaffected.

---

## 2. Adapter 扩展(中文)

**目标**:把 Sentinel 接到 **任意 web 框架 / 客户端**。

### 2.1 ASGI(已实现,见 `adapter-asgi`)

```python
from atlas_richie.sentinel_adapter_asgi import SentinelASGIMiddleware

app = FastAPI()
app.add_middleware(SentinelASGIMiddleware, engine=engine, flow_slot=flow_slot)
```

### 2.2 HTTPX(已实现,见 `adapter-httpx`)

```python
from atlas_richie.sentinel_adapter_httpx import SentinelAsyncTransport

transport = SentinelAsyncTransport(
    engine=engine, flow_slot=flow_slot,
    inner_transport=httpx.AsyncHTTPTransport(),
)
client = httpx.AsyncClient(transport=transport)
```

### 2.3 写一个新 Adapter(以 WSGI 为例)

```python
# atlas_richie_sentinel_adapter_wsgi.py
from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.model.resource import Resource
from atlas_richie.sentinel.model.outcome import OutcomeKind
from atlas_richie.sentinel.slots.flow import FlowSlot

class SentinelWsgiMiddleware:
    def __init__(self, app, engine, flow_slot):
        self.app = app
        self.engine = engine
        self.flow_slot = flow_slot

    def __call__(self, environ, start_response):
        # Build Resource from WSGI environ
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")
        resource = Resource(f"{method} {path}")

        # Engine.entry is async — bridge to sync via asyncio.run
        import asyncio
        try:
            asyncio.run(self._process(resource, environ, start_response))
        except SentinelBlockedError:
            start_response("503 Service Unavailable", [("Content-Type", "text/plain")])
            return [b"sentinel: blocked"]

    async def _process(self, resource, environ, start_response):
        async with self.engine.entry(resource):
            # delegate to downstream sync app — run in executor
            ...
```

**契约**:
- Engine 必须是 `async context manager`,不允许同步误用
- BLOCKED 路径返回 503 + `sentinel: blocked` body
- 透传下游应用,不读 `httpcore` 私有字段
- 不在 handle 内部 retry(用户责任)

### 2.4 Adapter 边界规则(硬约束)

- **不**改主包 Engine / Slot API
- **不**读 web 框架的私有字段
- **不** retry(用户显式 `RetryExecutor` 才重试)
- **不**做指标上报(交给 Dashboard 扩展)

## 2. Adapter Extension (English)

**Goal**: wire Sentinel into **any web framework / client**.

### 2.3 Write a new Adapter (WSGI example)

(See code block above.)

**Contract**:
- Engine must be `async context manager`; sync misuse forbidden.
- BLOCKED path returns 503 + `sentinel: blocked` body.
- Pass through to downstream; do not read `httpcore` private fields.
- Do not retry inside `handle_*` (caller's responsibility via
  `RetryExecutor`).

### 2.4 Adapter boundary rules (hard constraints)

- Do **not** modify the main package Engine / Slot API.
- Do **not** read web framework private fields.
- Do **not** retry.
- Do **not** emit metrics (delegate to Dashboard extension).

---

## 3. Source 扩展(中文)

**目标**:把规则从 **任意数据源**(Nacos / Redis / Consul / K8s ConfigMap)
推到 `RuleRepository`。

### 3.1 `RuleSource` Protocol(主包定义)

```python
# atlas_richie/sentinel/source/rule_source.py
class RuleSource(Protocol):
    def latest(self) -> RuleSnapshot | None: ...
    def start(self, repository: RuleRepository) -> None: ...
    def stop(self) -> None: ...
```

### 3.2 `FileRuleSource` 已有,见 `source-file` wheel

```python
from atlas_richie.sentinel_source_file import FileRuleSource

source = FileRuleSource(
    path="/etc/sentinel/rules.json",
    poll_interval_sec=5.0,
)
source.start(repository)  # 立即推一次 + 后台轮询
```

### 3.3 写一个新的 Source(以 Redis pub/sub 为例)

```python
# atlas_richie_sentinel_source_redis.py
import json
import redis.asyncio as redis
from atlas_richie.sentinel.rules.snapshot import RuleSnapshot, RuleVersion
from atlas_richie.sentinel.rules.repository import RuleRepository
from atlas_richie.sentinel.source.rule_source import RuleSource

class RedisRuleSource:
    def __init__(self, url: str, channel: str = "sentinel:rules"):
        self.url = url
        self.channel = channel
        self._client = None
        self._task = None
        self._latest = None

    def latest(self) -> RuleSnapshot | None:
        return self._latest

    async def start(self, repository: RuleRepository) -> None:
        self._client = redis.from_url(self.url)
        pubsub = self._client.pubsub()
        await pubsub.subscribe(self.channel)
        self._task = asyncio.create_task(self._consume(pubsub, repository))

    async def _consume(self, pubsub, repository: RuleRepository) -> None:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data = json.loads(message["data"])
            # deserialize into RuleSnapshot, push to repository
            snap = _decode_snapshot(data)
            repository.apply_snapshot(snap)

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
```

### 3.4 Source 边界规则(硬约束)

- **不**阻塞调用方(`start` 后立即返回;订阅循环跑在后台 task)
- **不**做 schema 转换(M2 schema registry 在主包,见 PLANNING §M2.5)
- **不**缓存过期规则(每条消息立即推 Repository)
- **不**重试网络错误(Dashboard / 上游负责)

### 3.5 Source contract test

每个 Source 都要跑 `tests/test_sen_rule_source.py` 的 5 个契约:

- `isinstance(source, RuleSource)` (Protocol runtime_checkable)
- `start` / `stop` 幂等
- `latest` 返回 `None` 或 `RuleSnapshot`
- 推 Repository 后 `last_version` 更新
- 文件不存在 / 解析失败 不抛(返回 `None`)

## 3. Source Extension (English)

(See code above.)

**Source boundary rules**:
- Do not block the caller (`start` returns immediately; the subscription
  loop runs as a background task).
- Do not do schema conversion (M2 schema registry lives in the main
  package).
- Do not cache stale rules.
- Do not retry on network errors (upstream / Dashboard's job).

### 3.5 Source contract test

Each Source must pass `tests/test_sen_rule_source.py` (5 contracts).

---

## 4. Dashboard 扩展(中文)

**目标**:暴露指标 / 控制 endpoint。

### 4.1 `sentinel-dashboard` 已有

```python
from atlas_richie.sentinel_dashboard import SentinelDashboard

dashboard = SentinelDashboard(engine=engine, repository=repository)
dashboard.run(host="127.0.0.1", port=8719)
```

### 4.2 写一个新的 Dashboard(以 Prometheus exporter 为例)

```python
# atlas_richie_sentinel_dashboard_prometheus.py
from prometheus_client import generate_latest, REGISTRY

class PrometheusExporter:
    def __init__(self, engine, repository):
        self.engine = engine
        self.repository = repository
        self._setup_metrics()

    def _setup_metrics(self) -> None:
        from prometheus_client import Counter, Gauge
        self.requests = Counter("sentinel_requests_total", ["resource", "outcome"])
        self.in_flight = Gauge("sentinel_in_flight", "current in-flight entries")

    def render(self) -> bytes:
        # Pull metrics from engine.last_outcome etc.
        ...
        return generate_latest(REGISTRY)
```

### 4.3 Dashboard 边界规则

- **只**读 Engine / Repository(不修改)
- **只**绑 loopback / admin token(避免未授权访问)
- **不**做规则修改(Dashboard 是控制面,规则修改由管理员 API 走)
- **不**持久化状态(读 Engine 实时)

## 4. Dashboard Extension (English)

(See code above.)

**Dashboard boundary rules**:
- Read-only on Engine / Repository.
- Bind to loopback / require admin token.
- No rule modification (admin API for that).
- No state persistence (read Engine live).

---

## 5. 决策矩阵:什么时候该写新 wheel(中文)

| 你想做的 | 是否新 wheel? |
| -------- | ------------- |
| 给 Engine 加一条新规则类型 | ❌ 不允许(主包冻结) |
| 给 ASGI middleware 加新特性 | ✅ `adapter-asgi` 升级 |
| 把 Sentinel 接到 gRPC | ✅ 新 wheel `adapter-grpc` |
| 用 Nacos 推规则 | ✅ 新 wheel `source-nacos` |
| 把指标写到 Prometheus | ✅ 新 wheel `dashboard-prometheus` |
| 改 FlowSlot 内部算法 | ❌ 不允许(主包冻结) |
| 改 Engine 6 状态机 | ❌ 不允许 |
| 加新 Slot 协议 | ❌ Slot 协议冻结 |
| 改 `RuleVersion` 协议 | ❌ 协议冻结 |

**主包 = 1.0 之后 6 月不 breaking**。任何 1.0 写的主包 API,1.x
阶段不破坏。新功能一律新 wheel。

## 5. Decision matrix: when to write a new wheel (English)

| You want to | New wheel? |
| ----------- | ---------- |
| Add a new rule type to Engine | ❌ forbidden (main is frozen) |
| Add a feature to ASGI middleware | ✅ upgrade `adapter-asgi` |
| Wire Sentinel to gRPC | ✅ new `adapter-grpc` |
| Push rules from Nacos | ✅ new `source-nacos` |
| Export metrics to Prometheus | ✅ new `dashboard-prometheus` |
| Change FlowSlot internal algorithm | ❌ forbidden |
| Change Engine 6-state machine | ❌ forbidden |
| Add a new Slot protocol | ❌ Slot protocol is frozen |
| Change `RuleVersion` protocol | ❌ protocol is frozen |

**Main package = 6-month no-breaking after 1.0**. Any 1.0 main
package API is not broken in 1.x. New features ship as new wheels.

---

## 6. 主包 0 依赖原则(中文)

主包 `dependencies = []`;`stamina` / `aiolimiter` / `httpx` /
`prometheus-client` 全部**禁止**作为主包依赖。

每个扩展 wheel 按需声明自己的依赖:

```toml
# atlas-richie-sentinel-adapter-httpx/pyproject.toml
dependencies = [
    "atlas-richie-sentinel>=0.2.0,<0.3.0",
    "httpx>=0.27,<1.0",  # 适配目标
]
```

`uv pip install atlas-richie-sentinel` 主包体积 0 依赖;
`uv pip install atlas-richie-sentinel-adapter-httpx` 装 httpx;
`uv pip install atlas-richie-sentinel-dashboard` 装 dashboard 自身
依赖(如果有)。

## 6. Main package zero-dep principle (English)

Main package `dependencies = []`; `stamina` / `aiolimiter` / `httpx`
/ `prometheus-client` are all **forbidden** as main package deps.

Each extension wheel declares its own deps:

```toml
# atlas-richie-sentinel-adapter-httpx/pyproject.toml
dependencies = [
    "atlas-richie-sentinel>=0.2.0,<0.3.0",
    "httpx>=0.27,<1.0",  # adapter target
]
```

`uv pip install atlas-richie-sentinel` is zero-dep; `uv pip install
atlas-richie-sentinel-adapter-httpx` pulls in httpx; etc.

---

## 7. 检查清单(中文)

写新 wheel 之前确认:

- [ ] 主包没有这个能力(否则改主包,不要新 wheel)
- [ ] 已经查 `tests/test_sen_rule_source.py` / `tests/test_sen_core.py`
      看看契约
- [ ] `pyproject.toml` 只声明 1 个 dep: `atlas-richie-sentinel` (按需 + 适配目标)
- [ ] README 写明:依赖 / 安装命令 / 1.0 兼容范围
- [ ] 测试独立 wheel 安装:`uv venv && uv pip install -e .`
- [ ] 测试 wheel 的 Python 3.12 + 3.13 兼容(2 个 venv)
- [ ] 不读主包私有字段(任何 `_` 开头)
- [ ] 不发兼容 shim,直接新 API

## 7. Checklist (English)

Before writing a new wheel:

- [ ] Main package doesn't have this (otherwise modify the main, don't new-wheel)
- [ ] Reviewed `tests/test_sen_rule_source.py` / `tests/test_sen_core.py` for contracts
- [ ] `pyproject.toml` declares only 1 dep: `atlas-richie-sentinel` (plus adapter target if needed)
- [ ] README documents deps / install / 1.0 compat range
- [ ] Test isolated wheel install: `uv venv && uv pip install -e .`
- [ ] Test wheel on Python 3.12 + 3.13 (2 venvs)
- [ ] Do not read main package private fields (any `_`-prefixed)
- [ ] No compat shim; ship new API directly
