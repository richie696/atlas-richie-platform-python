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
| **Source**(数据源) | `RuleSource` Protocol(主包) | `source-file`(JSON / YAML) | `source-nacos` / 经 ADR 批准的持久化 Source |
| **Dashboard**(控制面) | REST + admin token | `sentinel-dashboard`(loopback) | `dashboard-cluster` / `dashboard-prometheus` |

每一类扩展**只引入一个独立 wheel**,主包不受影响。

## 1. The three extension axes (English)

Atlas Richie Sentinel's extension surface is divided into 3 axes;
each axis ships in its own wheel, free of cross-contamination:

| Axis | Protocol | 1.0 built-in | 1.x planned |
| ---- | -------- | ------------ | ----------- |
| **Adapter** (integration) | `SentinelEngine` / `FlowSlot` exposed to web / clients | `adapter-asgi` / `adapter-httpx` | `adapter-grpc` / `adapter-faststream` |
| **Source** (data source) | `RuleSource` Protocol (in main package) | `source-file` (JSON / YAML) | `source-nacos` / ADR-approved durable Sources |
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

**目标**:把规则从具备持久化、恢复和审计边界的数据源（例如 Nacos）推到
`RuleRepository`。缓存、纯 pub/sub 和仅内存数据不是 RuleSource 的事实来源。

### 3.1 双 Port: `LegacyRuleSource` + `SnapshotRuleSource` (M6.1.0b)

1.0 阶段 `RuleSource` 是单契约 Protocol;M6.1 阶段拆为**双 Port** (API delta v3
决策 3, 见 `R-SENTINEL-M6.1.0b-api-delta.md`):

```python
# atlas_richie/sentinel/source/rule_source.py
class LegacyRuleSource(Protocol):
    """1.0 旧契约; 1.x 全程保留 (alias: RuleSource = LegacyRuleSource)。"""
    def latest(self) -> RuleSnapshot | None: ...
    def start(self, repository: RuleRepository) -> None: ...
    def stop(self) -> None: ...

class SnapshotRuleSource(Protocol):
    """新契约; SentinelEngine.assemble_sources() 仅接受本类型。"""
    source_id: str  # 稳定字符串, 配置时声明 (rule_source_activation.md §7)
    def snapshots(self) -> AsyncIterator[RuleSnapshot]: ...
    async def aclose(self) -> None: ...

class RuleSourceAssembly:
    """公开 immutable assembly DTO; __post_init__ 校验 priority≥0 / failover_after≥0。"""
    source: SnapshotRuleSource
    priority: int
    failover_after: timedelta
```

**`RuleSource` 是 `LegacyRuleSource` 的 type alias** — 1.0 用户零代码改动。
1.x 全程不发出 deprecation warning; 弃用时钟 ≥ 2 minor 或 6 个月 (以较晚者
为准), 不得早于 2.0 删除。

### 3.2 `FileRuleSource` 已有,见 `source-file` wheel

```python
from atlas_richie.sentinel_source_file import FileRuleSource

# 1.0 路径 (LegacyRuleSource 实现, 1.x 仍可用)
source = FileRuleSource(
    path="/etc/sentinel/rules.json",
    poll_interval_sec=5.0,
)
source.start(repository)  # 立即推一次 + 后台轮询
```

**1.0 路径 (1.x 仍可用, 零代码改动)**: 调 `engine.install_legacy_source(source, repository=repo)`。
**新路径 (M6.1+)**: 调 `engine.assemble_sources([RuleSourceAssembly(source, priority, failover_after), ...], repository=repo)`。

两入口**互斥**: 调用任一入口后再调另一入口抛 `SentinelConfigurationError("multimode_conflict")`。
详见 `MIGRATION-M6.md`。

### 3.3 写一个新的 Source (SnapshotRuleSource, M6.1+ 推荐)

先证明候选系统是规则的持久化事实来源：新实例必须能在通知丢失、客户端离线、服务
重启和故障切换后恢复到同一个已审计快照。通过该前提后，扩展才可实现 `SnapshotRuleSource`
Protocol (M6.1+ 推荐) 或 `LegacyRuleSource` (1.0 兼容, 不推荐新写)。

**已有生产级实现**: `sentinel-source-nacos` wheel 已是完整
`SnapshotRuleSource` 实现, 含 5 类 rule data-id 解码 + 5 类错误分类
+ 状态机 + 退避 + 脱敏 + 幂等 aclose。新 Source 应该**优先参考此
实现**, 而不是从零开始 (PLANNING M6.1.1-1.6 落地 1:1 Java
`sentinel-datasource-nacos` 行为)。详见 §3.6。

下面给出一个**最小骨架** (仅作 template, 真实 Nacos 行为已在
`sentinel-source-nacos` wheel 完整实现):

```python
# 路径: 你的 extension/src/atlas_richie/sentinel_source_<name>/
# 主包**不**导入你的 SDK, 全部走 Port
from typing import AsyncIterator
from atlas_richie.sentinel.source.rule_source import SnapshotRuleSource
from atlas_richie.sentinel.rules.snapshot import RuleSnapshot

class MyRuleSource(SnapshotRuleSource):
    source_id: str  # 配置时声明, e.g. "my-prod"

    async def snapshots(self) -> AsyncIterator[RuleSnapshot]:
        """Yield complete validated RuleSnapshot; 失败不 yield, 保留 last-known-good."""
        async for snap in self._listener():
            yield snap  # 已校验; 失败 → 不 yield (Supervisor 标 stale)

    async def aclose(self) -> None:
        """幂等关闭: 取消 listener, 停止重连, 关闭 SDK。"""
        ...
```

使用:
```python
await engine.assemble_sources(
    [RuleSourceAssembly(
        source=NacosRuleSource(source_id="nacos-prod", ...),
        priority=100,
        failover_after=timedelta(seconds=5),
    )],
    repository=repo,
)
```

**禁止 shim**: 不要把 1.0 旧 `RuleSource` 实现包装成 `SnapshotRuleSource` (旧
`start(repository)` 没有 Engine / Supervisor 引用, 没法挂载"经 Supervisor
仲裁"路径; shim 包装必然改变 1.0 行为)。

### 3.4 Source 边界规则(硬约束)

- **不**阻塞调用方(`start` 后立即返回;订阅循环跑在后台 task)
- **不**做 schema 转换(M2 schema registry 在主包,见 PLANNING §M2.5)
- **不**缓存过期规则(每条消息立即推 Repository)
- **不**重试网络错误(Dashboard / 上游负责)
- **不**直接调 `RuleRepository.apply_snapshot` (新路径下, 由 Supervisor 仲裁;
  老路径下, `start(repository)` 内调, 等同 1.0 行为)
- **不**在 `RuleSource` 自己声明 priority / failover_after (新契约下, 由
  `RuleSourceAssembly` 显式声明, 防止 Source 决定自己的优先级)
- **不**跨进程订阅 / 写 `event_name` 字符串 (跨语言 wire 推迟到 M6.5.7 envelope)

### 3.5 Source contract test

每个 Source 都要跑 `tests/test_sen_rule_source.py` 的契约 (M6.1.0d-1 扩展为
26 LegacyRuleSource + 21 SnapshotRuleSource):

- `isinstance(source, RuleSource)` (Protocol runtime_checkable, 1.0 兼容)
- `start` / `stop` 幂等 (1.0)
- `latest` 返回 `None` 或 `RuleSnapshot` (1.0)
- 推 Repository 后 `last_version` 更新 (1.0)
- 文件不存在 / 解析失败 不抛(返回 `None`) (1.0)
- `isinstance(source, SnapshotRuleSource)` + `source_id` 字段非空 (新契约)
- `snapshots()` 异步迭代 yield 完整 `RuleSnapshot`, 不持有 Repository 引用 (新)
- `aclose()` 幂等 (新)
- 优先级全局唯一, `duplicate_priority` 抛 `SentinelConfigurationError` (新)
- Repository 不可 None, 拒绝 `Optional[RuleRepository]` (default-deny)

## 3. Source Extension (English)

**Goal**: push rules from a source of truth (durable, recoverable,
auditable) such as Nacos into `RuleRepository`. Caches, pure pub/sub, and
in-memory-only data are not sources of truth for `RuleSource`.

### 3.1 Two Ports: `LegacyRuleSource` + `SnapshotRuleSource` (M6.1.0b)

The 1.0 single `RuleSource` Protocol is split into **two Ports** in M6.1
(API delta v3 decision 3, see `R-SENTINEL-M6.1.0b-api-delta.md`):

```python
# atlas_richie/sentinel/source/rule_source.py
class LegacyRuleSource(Protocol):
    """1.0 old contract; preserved for the entire 1.x phase
    (alias: RuleSource = LegacyRuleSource)."""
    def latest(self) -> RuleSnapshot | None: ...
    def start(self, repository: RuleRepository) -> None: ...
    def stop(self) -> None: ...

class SnapshotRuleSource(Protocol):
    """New contract; SentinelEngine.assemble_sources() accepts only this type."""
    source_id: str  # stable string, declared at config time
    def snapshots(self) -> AsyncIterator[RuleSnapshot]: ...
    async def aclose(self) -> None: ...

class RuleSourceAssembly:
    """Public immutable assembly DTO; __post_init__ validates priority≥0 /
    failover_after≥0."""
    source: SnapshotRuleSource
    priority: int
    failover_after: timedelta
```

**`RuleSource` is a type alias of `LegacyRuleSource`** — 1.0 users see zero
code changes. 1.x never emits a deprecation warning; deprecation clock is
≥ 2 minor or 6 months (whichever is later), cannot be removed before 2.0.

### 3.2 `FileRuleSource` (existing, see `source-file` wheel)

```python
from atlas_richie.sentinel_source_file import FileRuleSource

# 1.0 path (LegacyRuleSource impl, still works in 1.x)
source = FileRuleSource(
    path="/etc/sentinel/rules.json",
    poll_interval_sec=5.0,
)
source.start(repository)  # one-shot push + background polling
```

**1.0 path (still works in 1.x, zero code change)**: call
`engine.install_legacy_source(source, repository=repo)`.
**New path (M6.1+)**: call
`engine.assemble_sources([RuleSourceAssembly(source, priority, failover_after), ...], repository=repo)`.

The two entries are **mutually exclusive**: after calling one, calling the
other raises `SentinelConfigurationError("multimode_conflict")`. See
`MIGRATION-M6.md`.

### 3.3 Write a new Source (SnapshotRuleSource, M6.1+ recommended)

First prove the candidate system is a durable source of truth: a new
instance must recover the same audited snapshot after notification loss,
client offline, service restart, or failover. Once that premise holds,
implement the `SnapshotRuleSource` Protocol (M6.1+ recommended) or
`LegacyRuleSource` (1.0 compat, not recommended for new code).

**Production reference**: the `sentinel-source-nacos` wheel is a
complete `SnapshotRuleSource` implementation with 5-way rule data-id
decoding, 5-way error classification, state machine, bounded backoff,
log redaction, and idempotent `aclose()`. New sources should **read
this wheel first** rather than starting from scratch (PLANNING M6.1.1
-1.6 deliver a 1:1 mirror of Java `sentinel-datasource-nacos`).
See §3.6.

The minimum skeleton below is a **template only**; the real Nacos
behavior is fully implemented in the `sentinel-source-nacos` wheel:

```python
# path: your-extension/src/atlas_richie/sentinel_source_<name>/
# the main package does NOT import your SDK — only via the Port
from typing import AsyncIterator
from atlas_richie.sentinel.source.rule_source import SnapshotRuleSource
from atlas_richie.sentinel.rules.snapshot import RuleSnapshot

class MyRuleSource(SnapshotRuleSource):
    source_id: str  # declared at config time, e.g. "my-prod"

    async def snapshots(self) -> AsyncIterator[RuleSnapshot]:
        """Yield complete validated RuleSnapshot; failures do not yield
        (Supervisor marks the source stale and emits health event)."""
        async for snap in self._listener():
            yield snap  # already validated

    async def aclose(self) -> None:
        """Idempotent close: cancel listener, stop reconnect, close SDK."""
        ...
```

Usage:
```python
await engine.assemble_sources(
    [RuleSourceAssembly(
        source=NacosRuleSource(source_id="nacos-prod", ...),
        priority=100,
        failover_after=timedelta(seconds=5),
    )],
    repository=repo,
)
```

**No shim allowed**: do not wrap a 1.0 `RuleSource` as a `SnapshotRuleSource`
(the old `start(repository)` has no Engine / Supervisor reference, so it
cannot mount the "supervised arbitration" path; a shim would silently
change 1.0 behavior).

### 3.6 `sentinel-source-nacos` wheel (production `SnapshotRuleSource` reference)

This is the **first production extension** that consumes the new
`SnapshotRuleSource` contract end-to-end. New Source implementations
should read this wheel before writing their own.

**Path**: `components/sentinel/sentinel-source-nacos/src/atlas_richie/sentinel_source_nacos/`

**Public API** (5 + 1 symbols):

| Symbol | Purpose |
| ------ | ------- |
| `NacosAuth` | Username + password value object (password redacted in `__repr__`) |
| `NacosTLS` | CA + optional mTLS `cert`/`key` (PEM redacted in `__repr__`) |
| `NacosRuleSourceConfig` | Frozen DTO: `source_id` / `server_addresses` / `namespace` / `group` / `data_id_prefix` / `auth` / `tls` / 4 `timedelta` timing fields + `poll_interval` (M6.1.7) |
| `NacosSourceState` (StrEnum) | `CONNECTING` / `READY` / `STALE` / `DISCONNECTED` / `CLOSED` |
| `NacosSourceError` (StrEnum) | `AUTH` / `NOT_FOUND` / `EMPTY` / `DECODE` / `NETWORK` |
| `NacosRuleSource` | The `SnapshotRuleSource` implementation (M6.1.7 polling 架构) |

**5 data-id convention** (Java sentinel-datasource-nacos 1:1):

| Rule type | data-id (derived from `data_id_prefix`) |
| --------- | --------------------------------------- |
| `flow` | `{prefix}-flow-rules.json` |
| `degrade` | `{prefix}-degrade-rules.json` |
| `param_flow` | `{prefix}-param-flow-rules.json` |
| `system` | `{prefix}-system-rules.json` |
| `authority` | `{prefix}-authority-rules.json` |

Use `config.data_id_for(rule_type)` to get the exact data-id string.

**Lifecycle** (M6.1.3 + M6.1.7 polling 改造):

1. `__init__` validates config; state = `CONNECTING`; SDK client is
   **lazy** (not yet constructed).
2. First `__anext__` on `snapshots()`: pull 5 data-ids → decode → yield
   first `RuleSnapshot` → state = `READY` (or `STALE` on partial
   success).
3. **M6.1.7 polling** (替代 M6.1.0-1.6 push): 启动 `_poll_loop` 后台 task,
   每 `config.poll_interval` 秒拉 5 个 data-id, 跟上次 checksum 比对,
   变化 yield 新 snapshot。**不**把 SDK listener 作为正确性依赖；当前部署中
   未完成其可靠回调验证，因此 polling 是该扩展的确定性刷新路径。
4. `poll_interval` 默认 `1s`, 下限 `100ms` (default-deny 资源上限,
   ADR-SEN-007 追加); 用户可调
5. `aclose()` cancels the poll task, stops the SDK client, transitions
   to `CLOSED`. **Idempotent**.

**Error classification** (M6.1.4 + M6.1.7 调整):

| Error | Trigger | Recovery | State |
| ----- | ------- | -------- | ----- |
| `AUTH` | 401/403 / SDK `NacosException(error_code in (401, 403))` / "Insufficient privilege" message | **No auto-retry**; await human | `DISCONNECTED` |
| `NOT_FOUND` | `NacosException(error_code in (400, 404))` / "not found" / `content is None` (SDK 0.1.16 行为) | last-known-good preserved | `STALE` |
| `EMPTY` | `content == ""` / `content.strip() in ("[]", "null")` (SDK 3.2.0 缺失返回空字符串) | last-known-good preserved | `STALE` |
| `DECODE` | 其它 `NacosException` 4xx / JSON parse / field missing / type wrong | last-known-good preserved | `STALE` |
| `NETWORK` | `URLError` / `TimeoutError` / `ConnectionError` / `OSError` | bounded exponential backoff | `DISCONNECTED` |

Errors **do not** yield a new `RuleSnapshot` (last-known-good is
preserved in the caller-side `RuleRepository`).

**Redaction** (M6.1.5):

`last_error_message` and all `logger.warning(...)` calls go through the
`_redact` helper, which masks:

- `server_addresses` (entire tuple not exposed; `host:port` →
  `***:***`)
- `namespace`, `username`, `password`, `token`, `accessKey`,
  `secretKey`, `cert`, `key` (key=value / key:value → `***`)

**Operator observability**:

```python
source.state                    # current NacosSourceState
source.last_success_version     # RuleVersion | None
source.last_error               # NacosSourceError | None
source.last_error_message       # redacted str | None
source.error_count(NacosSourceError.NETWORK)  # per-type cumulative count
```

**Test count**: 112 passed + 1 skipped (real-Nacos placeholder);
main package 243 passed + 3 skipped unchanged (no regression).

**Hard isolation contracts** (verified by tests):

- `rg "_supervisor" components/sentinel/sentinel-source-nacos/src/`
  returns only docstring text (no real import of the main package's
  C layer).
- `NacosClient` / `NacosException` / `ConfigResponse` appear **only**
  in the internal `_NacosAdapter` (not in `__init__.py` or `codec.py`).
- Only the `sentinel-source-nacos` wheel declares
  `nacos-sdk-python>=2.0,<3.0`; main package dependency graph
  unchanged.

### 3.4 Source boundary rules (hard constraints)

- Do not block the caller (`start` returns immediately; the subscription
  loop runs as a background task).
- Do not do schema conversion (M2 schema registry lives in the main
  package).
- Do not cache stale rules.
- Do not retry on network errors (upstream / Dashboard's job).
- Do not call `RuleRepository.apply_snapshot` directly (new path: via
  Supervisor arbitration; old path: inside `start(repository)`, equals
  1.0 behavior).
- Do not declare your own priority / failover_after (new contract: the
  caller declares them via `RuleSourceAssembly`).
- No cross-process subscription / `event_name` string (cross-language
  wire is deferred to M6.5.7 envelope).

### 3.5 Source contract test

Each Source must pass `tests/test_sen_rule_source.py` contracts (M6.1.0d-1
extends to 26 LegacyRuleSource + 21 SnapshotRuleSource):

- `isinstance(source, RuleSource)` (Protocol runtime_checkable, 1.0 compat)
- `start` / `stop` idempotent (1.0)
- `latest` returns `None` or `RuleSnapshot` (1.0)
- After push, Repository `last_version` updates (1.0)
- File missing / parse failure does not raise (returns `None`) (1.0)
- `isinstance(source, SnapshotRuleSource)` + `source_id` non-empty (new)
- `snapshots()` async-iterates complete `RuleSnapshot`, no Repository ref (new)
- `aclose()` idempotent (new)
- Priority globally unique, `duplicate_priority` raises
  `SentinelConfigurationError` (new)
- Repository cannot be None, reject `Optional[RuleRepository]` (default-deny)

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
