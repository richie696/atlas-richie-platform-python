# R-SENTINEL Design Doc — Atlas Richie Sentinel 家族 (M0..M5+)

> **Status**: 设计文档,所有 M0..M5 milestone 的总览。
> **Author**: Mavis (root session 2026-09-12)
> **Target**: 1.0 GA 发布到 PyPI,Apache 2.0 开源

## 1. 背景与目标

### 1.1 为什么做这个

Java 生态的 **Alibaba Sentinel** 是事实标准的"服务级 + 业务级"双层防护框架,被 Spring Cloud Gateway / Dubbo / gRPC 等十几种集成方广泛使用。Python 生态**没有对位**的框架:

- `pybreaker` / `stamina` — 只做 circuit-breaker(无系统级防护)
- `aiolimiter` / `limits` — 只做 rate-limit
- `prometheus-client` — 只做 metrics(给 system protection 做数据源,无执行)
- 没有任何一个库做"resource 抽象 + 多类型规则 + slot chain + sliding window 统计"

后果:**Python 服务做网关 / 微服务时,只能选择**
1. 直接用 Java 端 Sentinel 跨语言调用(性能 + 部署复杂)
2. 自己拼凑多个库(没有统一抽象,运维灾难)
3. 完全裸奔(被 DDoS 一次才知道需要防护)

### 1.2 跟 Java 端对位关系

Java 网关 `atlas-richie-gateway-service` 的 `application-gateway.yml` 已经使用 5 大 Sentinel 规则(详见 `pom.xml` + `application-gateway.yml`)。Python 端 Atlas Richie 平台需要**对位实现**这 5 大规则,使 Java 端转 Python 端(或混合部署)的团队无需重新学习 API。

### 1.3 双层防护模型(本设计的核心)

```
┌──────────────────────────────────────────────────────────┐
│  Layer A — Ingress / System Protection                    │
│  整个 Python 服务不被打爆                                  │
│  ┌────────────────────────────────────────────────────┐  │
│  │  ASGI middleware (sentinel-adapter-asgi)           │  │
│  │  - SystemSlot: CPU / Load / 入口 QPS / avg RT      │  │
│  │  - WorkerSlot: 守护 asyncio 任务队列                │  │
│  │  → 触发 SystemRule → 整服务 503                     │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │  PoolGuard (sentinel-adapter-httpx)                │  │
│  │  - httpx 出站连接池水位 hook                         │  │
│  │  - 单 host 连接数 / 等待队列长度 → 主动拒绝          │  │
│  └────────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────┤
│  Layer B — Per-Resource Business Protection               │
│  每个业务接口按规则走                                       │
│  ┌────────────────────────────────────────────────────┐  │
│  │  @sentinel_resource("order:create", flow=[...])    │  │
│  │  - FlowRule (QPS / 并发 / 预热 / 排队)              │  │
│  │  - DegradeRule (慢调用 / 异常比例 / 异常数)         │  │
│  │  - ParamFlowRule (按 header/query/cookie)          │  │
│  │  - AuthorityRule (白/黑名单)                       │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

## 2. 家族拆分(10 个 wheel,Mono-version)

### 2.1 拆分原则(richie696 2026-09-12 明确)

> "通常一个完整的功能就应该是一个独立组件,别人安装一个,就具备一个能力,可以选择来进行安装,也方便进行功能剪裁自己用不到的能力。"

应用:
- 一个**完整功能** = 一个**独立 wheel**
- **单个 rule 类型不拆**(Flow/Degrade/ParamFlow/System/Authority 共享类型,拆了管理成本↑剪裁灵活性不变)
- **Primitives** 单独 wheel(底层,被上层所有用)
- **Adapter** 每个一种集成协议一个 wheel(ASGI / httpx / 未来: gRPC / Kafka consumer)
- **Source** 每个一种规则源一个 wheel(file / nacos / redis)
- **Dashboard** 和 **Cluster** 单独 wheel

### 2.2 依赖图

```
   ┌─────────────────────────────┐
   │ atlas-richie-sentinel-dashboard │ (M5, FastAPI 控制台)
   │ 依赖:core + rules              │
   └─────────────────────────────┘
                  │
   ┌──────────────┴──────────────┐
   │                              │
┌──┴──────────────────┐  ┌──────┴──────────────────┐
│ adapter-asgi        │  │ adapter-httpx          │
│ ASGI ingress 防护   │  │ httpx 出站连接池保护    │
│ 依赖:core + rules   │  │ 依赖:core               │
│ + source-file       │  │                         │
└─────────────────────┘  └─────────────────────────┘
        │                              │
        └──────────────┬───────────────┘
                       │
        ┌──────────────┴──────────────┐
        │ atlas-richie-sentinel-rules │ (M3-M4)
        │ Flow / Degrade / ParamFlow  │
        │   / System / Authority      │
        │ 依赖:core                   │
        └─────────────────────────────┘
                       │
       ┌───────────────┼───────────────┐
       │               │               │
   ┌───┴────────┐  ┌────┴──────┐  ┌────┴────────┐
   │source-file │  │source-nacos│  │source-redis│  (M2 + M6+)
   │YAML/JSON   │  │Nacos       │  │Redis pub/sub│
   │依赖:core + │  │依赖:core + │  │依赖:core + │
   │  rules     │  │  rules     │  │  rules     │
   └────────────┘  └────────────┘  └────────────┘
                       │
        ┌──────────────┴──────────────┐
        │ atlas-richie-sentinel-core  │ (M1)
        │ Resource / Context / Slot / │
        │ SlotChain / RuleManager /   │
        │ SlidingWindow                │
        │ 依赖:primitives              │
        └─────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │atlas-richie-sentinel-primitives│ (M0)
        │ retry / CB / rate-limit /     │
        │ bulkhead / idempotency / clock│
        │ 依赖:stamina + aiolimiter     │
        └─────────────────────────────┘

   (独立 wheel,延后做)
        ┌─────────────────────────────┐
        │ atlas-richie-sentinel-cluster│ (M6+, 集群模式)
        │ 依赖:core + redis            │
        └─────────────────────────────┘
```

### 2.3 用户安装矩阵

| 用户需求 | `pip install` |
|---|---|
| 只想用 retry/CB/bulkhead(老 R-104 用法) | `atlas-richie-sentinel-primitives` |
| 业务限流(per-resource 装饰器) | `sentinel-{primitives,core,rules,source-file}` |
| 完整 Sentinel 入口防护(网关) | 上面 + `sentinel-adapter-asgi` |
| 还要看实时 dashboard | 上面 + `sentinel-dashboard` |
| 出站 HTTP 连接池保护 | `sentinel-{primitives,core,adapter-httpx}` |
| 集群模式(多实例统一管控) | 上面 + `sentinel-cluster` |
| 完整 Sentinel + Nacos 规则源 | 全部 10 个 wheel |

### 2.4 版本协调

**Mono-version**(跟 Java Sentinel 风格一致):所有 `atlas-richie-sentinel-*` 共享版本号。

| 版本 | 含义 | 状态 |
|---|---|---|
| `0.0.1a1` | 只有 primitives | skeleton,已 commit |
| `0.0.1b1` | + core | 计划:M1 R-SENTINEL-1 |
| `0.0.2a1` | + rules | 计划:M2 R-SENTINEL-3 |
| `0.0.2b1` | + source-file | 计划:M2 R-SENTINEL-2 |
| `0.1.0a1` | + adapter-asgi | 计划:M2 |
| `0.1.0b1` | + adapter-httpx | 计划:M4 R-SENTINEL-4 |
| `0.2.0rc1` | 全部 alpha wheel,API 冻结 | M5 前 |
| `1.0.0` | GA,API 稳定承诺启动 | M5 R-SENTINEL-5 |
| `1.1.0` | + dashboard 完整版(可选 web UI) | post-1.0 |
| `2.0.0` | + cluster + nacos + redis source | M6+ |

## 3. 各 wheel 详细设计

### 3.1 `atlas-richie-sentinel-primitives`(M0)

**职责**:底层原语,被 core 内部用,也可被用户直接用(老 R-104 兼容)。

**公开 API**:
```python
from atlas_richie.sentinel_primitives import (
    # Retry
    RetryPolicy, RetryExecutor, RetryExhausted, RetryNotPermitted,
    # CircuitBreaker
    CircuitBreaker, CircuitState, CircuitOpen,
    # RateLimit
    TokenBucket, RateLimitExceeded,
    # Bulkhead
    Bulkhead, BulkheadFull,
    # Idempotency
    IdempotencyKey, StatelessIdempotencyKey, NeverIdempotencyKey, CallableIdempotencyKey,
    # Clock / Random
    Clock, SystemClock, ManualClock, RandomSource,
    # Errors
    ResilienceError,
)
```

**3rd-party deps**:
- `stamina>=0.10,<30.0` — retry + circuit-breaker(底层用)
- `aiolimiter>=1.1,<2.0` — rate-limit(底层用)

**自研部分**:
- `Bulkhead`(`asyncio.Semaphore` wrapper,50 行)
- `IdempotencyKey` Protocol + 3 实现(我们的契约,框架特定)
- `Clock` / `ManualClock` / `RandomSource`(测试 deterministic 注入)

**测试覆盖**:
- 单元测试 51+ 项(从 R-104 继承 + stamina/aiolimiter 集成)
- 目标覆盖率 ≥ 90%

**里程碑**:
- M0.1: 把 R-104 的 5 primitive 从 `atlas_richie.resilience.*` 迁到 `atlas_richie.sentinel_primitives.*`
- M0.2: 替换 retry/CB 实现为 stamina 薄 wrapper(原 750 行 → 100 行)
- M0.3: 替换 rate-limit 实现为 aiolimiter 薄 wrapper
- M0.4: 保留 Bulkhead / IdempotencyKey / Clock 自研
- M0.5: 老的 `atlas-richie-resilience` wheel 改成 4 行 shim,re-export + DeprecationWarning
- M0.6: 公开 API 清单(`__all__`)+ README 4 段
- M0.7: 跑 framework 整体 + isolated verify 验证 shim 不破坏 http/mcp/oauth

### 3.2 `atlas-richie-sentinel-core`(M1)

**职责**:规则引擎核心。**不包含具体 rule 类型**。

**核心抽象**:

#### 3.2.1 `Resource`
```python
@dataclass(frozen=True, slots=True)
class Resource:
    name: str  # 唯一标识,如 "order:create"
    type: ResourceType = ResourceType.COMMON
    # COMMON / WEB / RPC / DB / CACHE / MQ

@dataclass(frozen=True, slots=True)
class Entry:
    resource: Resource
    context: Context
    created_at: float
    invoker_chain: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class Context:
    name: str  # context name, e.g. "gateway_in"
    origin: str | None  # 来源标识(AuthorityRule 用)
    attachments: Mapping[str, Any]  # 参数 + 元数据

    def get(self, key: str) -> Any | None: ...
    def put(self, key: str, value: Any) -> None: ...
```

#### 3.2.2 `Slot` 协议 + `SlotChain`
```python
@runtime_checkable
class Slot(Protocol):
    def entry(self, ctx: Context, resource: Resource, count: int, args: list, ...) -> None:
        """Entry 前置检查:失败抛 BlockException"""
    def exit(self, ctx: Context, resource: Resource, count: int, args: list) -> None:
        """Entry 退出时:统计 + 检查 Degrade"""

class SlotChain:
    def add_slot(self, slot: Slot) -> None: ...
    def entry(self, ctx, resource, count, args) -> None: ...
    def exit(self, ctx, resource, count, args) -> None: ...

# 内置 Slot(在 sentinel-core 实现,不需要 sentinel-rules 包)
class NodeSelectorSlot: ...    # 选 resource 对应的 DefaultNode
class ClusterBuilderSlot: ...  # 维护 context 节点树
class StatisticSlot: ...       # 统计 pass/block/exception/RT
```

#### 3.2.3 `Rule` 抽象 + `RuleManager`
```python
@dataclass(frozen=True, slots=True)
class Rule(ABC):
    resource: str  # 资源名 pattern,支持 * 通配
    enabled: bool = True

    @abstractmethod
    def matches(self, resource_name: str) -> bool: ...

class RuleManager:
    def load(self, source: RuleSource) -> None: ...
    def get_rules(self, resource: str, rule_type: type[R]) -> list[R]: ...
    def register_listener(self, listener: RuleUpdateListener) -> None: ...
```

#### 3.2.4 `SlidingWindow`(对位 Java `LeapArray`)
```python
@dataclass
class SlidingWindowMetric:
    pass_count: int
    block_count: int
    exception_count: int
    rt_total_ms: float
    rt_min_ms: float
    rt_max_ms: float
    timestamp_ms: int

class SlidingWindow:
    """1 秒窗口,100 桶(10ms 每桶),O(1) 写入 + O(100) 求和。"""
    def __init__(self, window_size_ms: int = 1000, bucket_count: int = 100): ...
    def add_pass(self, count: int = 1) -> None: ...
    def add_block(self, count: int = 1) -> None: ...
    def add_exception(self, count: int = 1) -> None: ...
    def add_rt(self, rt_ms: float) -> None: ...
    def current(self) -> SlidingWindowMetric: ...
    def reset(self) -> None: ...
```

**实现策略**:
- 内部用 `sortedcontainers.SortedDict` 维护时间序桶
- 写入是 O(log n)(n=100,可接受)
- 读取是 O(n)(100 桶求和,可接受)
- 备选:手写环形 buffer 走 `array.array('q')`(极致性能但代码复杂,M5 benchmark 决定)

**里程碑**:
- M1.1: `Resource` / `Context` / `Entry` 数据结构
- M1.2: `Slot` Protocol + `SlotChain`
- M1.3: `NodeSelectorSlot` / `ClusterBuilderSlot` / `StatisticSlot`
- M1.4: `SlidingWindow` + benchmark(目标: 单核 100K QPS 下延迟 < 1ms)
- M1.5: `Rule` 抽象 + `RuleManager` in-memory
- M1.6: 30+ 单测,不发 PyPI(只本地 alpha)

### 3.3 `atlas-richie-sentinel-rules`(M3-M4)

**职责**:5 个具体 rule 类型。共享类型集中,不开 5 个 wheel。

#### 3.3.1 `FlowRule`(M3)
```python
@dataclass(frozen=True, slots=True)
class FlowRule(Rule):
    grade: Grade  # QPS / THREAD(并发)
    count: float  # 阈值
    control_behavior: ControlBehavior  # REJECT / WARM_UP / QUEUE
    
    # 预热模式额外参数
    warm_up_period_sec: int | None = None
    
    # 排队等待模式额外参数
    max_queueing_time_ms: int | None = None
```

#### 3.3.2 `DegradeRule`(M3)
```python
@dataclass(frozen=True, slots=True)
class DegradeRule(Rule):
    grade: DegradeGrade  # RT(慢调用比例) / EXCEPTION_RATIO / EXCEPTION_COUNT
    count: float
    time_window_sec: int
    min_request_amount: int = 5
    slow_ratio_threshold: float | None = None  # RT mode
    stat_interval_ms: int = 1000
```

#### 3.3.3 `ParamFlowRule`(M4)
```python
@dataclass(frozen=True, slots=True)
class ParamFlowRule(Rule):
    grade: Grade  # QPS
    count: float
    param_idx: int  # 参数索引(从 0 开始)
    param_exceptions: tuple[ParamFlowItem, ...]  # 特定参数值差异化阈值

@dataclass(frozen=True, slots=True)
class ParamFlowItem:
    key: str  # 参数值,如 "vip_user"
    count: float  # 该参数值专用阈值
    class_type: str  # 参数类型:STRING / INT / LONG
```

#### 3.3.4 `SystemRule`(M2)
```python
@dataclass(frozen=True, slots=True)
class SystemRule(Rule):
    highest_system_load: float | None = None  # Linux load
    highest_cpu_usage: float | None = None   # 0.0 ~ 1.0
    qps: float | None = None                  # 入口 QPS 上限
    avg_rt: float | None = None                # 平均 RT 上限(ms)
    max_thread: int | None = None              # 并发线程数上限
    ingress_qps: float | None = None           # 入口 QPS 独立阈值
```

#### 3.3.5 `AuthorityRule`(M4)
```python
@dataclass(frozen=True, slots=True)
class AuthorityRule(Rule):
    strategy: AuthorityStrategy  # WHITE / BLACK
    limit_origin: str  # 来源(如 header key "X-Origin" 的值 "partner-A")
```

**里程碑**:
- M3.1: `FlowRule` + FlowSlot + 预热 / 排队
- M3.2: `DegradeRule` + DegradeSlot + 慢调用窗口
- M4.1: `ParamFlowRule` + ParamFlowSlot
- M4.2: `SystemRule` + SystemSlot(CPU/Load 采集用 `psutil`)
- M4.3: `AuthorityRule` + AuthoritySlot
- 50+ 单测

### 3.4 `atlas-richie-sentinel-adapter-asgi`(M2)

**职责**:把任意 ASGI app(FastAPI / Starlette / Quart)接入 Sentinel。

```python
from fastapi import FastAPI
from atlas_richie.sentinel_adapter_asgi import (
    SentinelASGIMiddleware, SentinelASGIConfig,
)

app = FastAPI()
app.add_middleware(
    SentinelASGIMiddleware,
    config=SentinelASGIConfig(
        system_rules=[
            SystemRule(highest_cpu_usage=0.8, max_thread=200),
        ],
        resource_naming="path",  # "path" / "method:path" / custom callable
        in_flight_limit=500,
    ),
)

# Per-resource 装饰器(可选)
@app.post("/orders")
@sentinel_resource("order:create", flow=[FlowRule(grade=Grade.QPS, count=100)])
async def create_order(): ...
```

**ASGI middleware 流程**:
```
请求进入
  ↓
1. ctx = Context(name=app_name, origin=headers.get("X-Origin"))
2. entry = Entry(resource=Resource("POST /orders"), context=ctx)
3. SlotChain.entry(ctx, resource, count=1)  # ← FlowSlot / SystemSlot 触发
4. 等待下游 app 处理(scope.send / scope.receive)
5. 异常时:StatisticSlot.add_exception()
6. 正常完成时:StatisticSlot.add_pass() + add_rt()
7. SlotChain.exit(ctx, resource, count=1)  # ← DegradeSlot 检查 RT
8. 释放 entry
```

**关键决策**:
- ASGI 是协议层,不绑任何 web framework
- `psutil` 采集 CPU,每 1 秒 1 次(避免抖动)
- 触发了 SystemRule → 直接 503,不放行

**里程碑**:
- M2.1: `SentinelASGIMiddleware` 骨架
- M2.2: SystemSlot 集成 + psutil 采集
- M2.3: WorkerSlot(可选,守护 asyncio 队列)
- M2.4: 跟 `sentinel-rules` + `sentinel-source-file` 集成
- M2.5: 1 个 demo FastAPI 服务 + E2E 测试(5 种降级场景)

### 3.5 `atlas-richie-sentinel-adapter-httpx`(M4)

**职责**:httpx 出站连接池保护(Java Sentinel 没有对位 — Python 端创新)。

```python
import httpx
from atlas_richie.sentinel_adapter_httpx import SentinelHTTPTransport

transport = SentinelHTTPTransport(
    pool_max_connections=100,        # 全局活跃连接上限
    pool_max_queue_size=200,        # 等待队列上限
    per_host_max_connections=20,    # 单 host 上限
    per_host_block_threshold=0.8,   # 单 host 占比 > 80% 警告
)
async with httpx.AsyncClient(transport=transport) as client:
    resp = await client.get("https://api.example.com/data")
```

**实现**:子类化 `httpx.AsyncBaseTransport`,在 `handle_async_request` 前置检查 + `__aexit__` 后置统计。

**关键决策**:
- 主动 raise `PoolExhausted`(用户 catch 后可降级 / 重试 / 走备份)
- 不阻塞,直接拒绝(快失败)
- 暴露 `/admin/pool-stats` endpoint 给 dashboard 拉数据(M5)

**里程碑**:
- M4.1: `SentinelHTTPTransport` 骨架
- M4.2: pool 水位 hook
- M4.3: per-host 隔离
- M4.4: 跟 `sentinel-rules` 集成(per-host FlowRule)
- 30+ 单测

### 3.6 `atlas-richie-sentinel-source-file`(M2)

**职责**:从 YAML / JSON 文件加载所有 5 类 rule,支持 `watchfiles` 监听热重载。

```yaml
# rules.yaml
flow:
  - resource: order:create
    grade: qps
    count: 100
    controlBehavior: reject
  - resource: order:query
    grade: thread
    count: 50
degrade:
  - resource: pay:charge
    grade: rt
    count: 200
    timeWindow: 10
    minRequestAmount: 10
    slowRatioThreshold: 0.5
system:
  - highestSystemLoad: 4.0
    highestCpuUsage: 0.8
    qps: 300
    maxThread: 200
```

**使用**:
```python
from atlas_richie.sentinel_source_file import FileRuleSource
from atlas_richie.sentinel_core import RuleManager

manager = RuleManager()
source = FileRuleSource("/etc/sentinel/rules.yaml", manager=manager)
source.start()  # 启动 watchfiles,文件改了自动 reload
```

### 3.7 `atlas-richie-sentinel-source-nacos`(M6+)

**职责**:从 Nacos 拉 rule,long-poll 刷新。1:1 对位 Java `sentinel-datasource-nacos`。

**5 个 data-id**:
- `gateway-flow-rules.json`
- `gateway-degrade-rules.json`
- `gateway-param-flow-rules.json`
- `gateway-system-rules.json`
- `gateway-authority-rules.json`

**为什么 M6+ 才做**:Nacos 是 Java 生态强项,MVP 阶段 file 源够用。

### 3.8 `atlas-richie-sentinel-source-redis`(M6+)

**职责**:Redis pub/sub 规则源。轻量级替代 Nacos,适合不想引入 Nacos 的小团队。

### 3.9 `atlas-richie-sentinel-dashboard`(M5)

**职责**:FastAPI 控制台,暴露:
- `GET /api/metrics?resource=order:create` → QPS / pass / block / RT histogram
- `GET /api/rules?type=flow` → 规则列表
- `POST /api/rules?type=flow` → 推送规则(立即生效)
- `GET /api/resources` → 当前被监控的所有 resource
- `GET /healthz`

**MVP 阶段只有 REST API,web UI 留作 v1.1**。

### 3.10 `atlas-richie-sentinel-cluster`(M6+)

**职责**:分布式集群模式。Token server / embedded 模式,1:1 对位 Java `sentinel-cluster`。

**为什么 M6+ 才做**:MVP 阶段单进程 FlowRule 够用;集群模式需要 cluster server 部署,跟 dashboard 一起做更合理。

## 4. M0 → M5 Milestone 详细拆分

### 4.1 M0 — primitives 迁移 + 公开化(本周,5h 工作量)

| 任务 | 时间 | 备注 |
|---|---|---|
| 4.1.1 写本设计文档(R-SENTINEL-design.md) | 0.5h | **已写** |
| 4.1.2 创建 10 个 wheel 骨架 | 1h | **已建**(`components/sentinel/*`) |
| 4.1.3 workspace pyproject/versions/verify_isolated_wheels 加 10 wheel | 0.5h | **已加** |
| 4.1.4 `uv lock` 验证 | 0.2h | **已过** |
| 4.1.5 `uv pip install` 10 wheel,import 测试 | 0.2h | **已过** |
| 4.1.6 commit + push M0-skeleton | 0.3h | **本文件** |
| 4.1.7 M0 handoff doc | 0.5h | 计划:本次 session 末尾 |
| **M0 后续**(下一个 session) | | |
| 4.1.8 R-104 内容迁到 `sentinel_primitives` | 2h | |
| 4.1.9 retry/CB → stamina 薄 wrapper | 2h | |
| 4.1.10 rate-limit → aiolimiter 薄 wrapper | 1h | |
| 4.1.11 `atlas-richie-resilience` 改 shim | 0.5h | |
| 4.1.12 51 单测 + framework 整体 + isolated verify | 1h | |

### 4.2 M1 — core 规则引擎(R-SENTINEL-1,~3 天)

| 任务 | 时间 |
|---|---|
| Resource / Context / Entry / Node 数据结构 | 0.5 天 |
| Slot Protocol + SlotChain | 0.5 天 |
| NodeSelectorSlot / ClusterBuilderSlot / StatisticSlot | 0.5 天 |
| SlidingWindow + benchmark | 1 天 |
| Rule 抽象 + RuleManager in-memory | 0.5 天 |
| 30+ 单测 | 0.5 天 |
| R-SENTINEL-1 handoff + commit | 0.5 天 |
| 发 PyPI `0.0.1b1` | 0.1 天 |

### 4.3 M2 — system rule + ASGI ingress + file source(R-SENTINEL-2,~3 天)

| 任务 | 时间 |
|---|---|
| SystemRule + SystemSlot + psutil 集成 | 0.5 天 |
| SentinelASGIMiddleware 骨架 + ASGI 协议层 hook | 1 天 |
| WorkerSlot(守护 asyncio 队列) | 0.5 天 |
| sentinel-source-file 实现 + watchfiles 集成 | 0.5 天 |
| 1 个 FastAPI demo + 5 种降级 E2E | 0.5 天 |
| R-SENTINEL-2 handoff + commit + 发 PyPI `0.1.0a1` | 0.5 天 |

### 4.4 M3 — Flow + Degrade(R-SENTINEL-3,~2 天)

| 任务 | 时间 |
|---|---|
| FlowRule + FlowSlot(REJECT / WARM_UP / QUEUE) | 1 天 |
| DegradeRule + DegradeSlot | 0.5 天 |
| 30+ 单测 | 0.5 天 |
| R-SENTINEL-3 handoff + 发 PyPI `0.1.0b1` | 0.2 天 |

### 4.5 M4 — ParamFlow + Authority + httpx pool guard(R-SENTINEL-4,~3 天)

| 任务 | 时间 |
|---|---|
| ParamFlowRule + ParamFlowSlot | 0.5 天 |
| AuthorityRule + AuthoritySlot | 0.5 天 |
| SystemRule(M4 之前 M2 已有,M4 加 QPS / avg RT 完整实现) | 0.5 天 |
| SentinelHTTPTransport + PoolGuard | 1 天 |
| 20+ 单测 | 0.5 天 |
| R-SENTINEL-4 handoff + 发 PyPI `0.2.0rc1` | 0.2 天 |

### 4.6 M5 — dashboard + demo + docs + 1.0 GA(R-SENTINEL-5,~3 天)

| 任务 | 时间 |
|---|---|
| dashboard FastAPI app + metrics + rule push | 1 天 |
| 完整 demo 服务(类比 Java gateway) | 0.5 天 |
| mkdocs 文档站(5 篇文档 + 1 个 tutorial) | 0.5 天 |
| benchmark 报告(每秒 10K+ QPS,slot chain 延迟 < 1ms) | 0.5 天 |
| CHANGELOG + migration guide + 1.0 release notes | 0.3 天 |
| 1.0.0 commit + 发 PyPI + GitHub release | 0.2 天 |

### 4.7 M6+ — post-1.0

- `sentinel-cluster` 多实例模式
- `sentinel-source-nacos` Nacos 数据源
- `sentinel-source-redis` Redis pub/sub 数据源
- 1.1: dashboard web UI
- 2.0: 跨语言(gRPC / Go 客户端)

## 5. 跟同类产品对比

| 维度 | Atlas Richie Sentinel | pystamina-py | pybreaker | Java Sentinel |
|---|---|---|---|---|
| **多语言跨端** | Python only | Python only | Python only | Java only |
| **双层防护** | 入口 + 业务 | 无 | 无 | 入口 + 业务 |
| **Slot chain 抽象** | 有 | 无 | 无 | 有 |
| **系统级自适应** | 有(M2+) | 无 | 无 | 有 |
| **热点参数** | 有(M4) | 无 | 无 | 有 |
| **黑白名单** | 有(M4) | 无 | 无 | 有 |
| **Cluster 模式** | 计划(M6+) | 无 | 无 | 有 |
| **Dashboard** | 计划(M5) | 无 | 无 | 有 |
| **3rd-party 依赖** | stamina + aiolimiter | 无 | 无 | 无 |
| **公开到 PyPI** | 是 | 是(社区) | 是(社区) | n/a |
| **维护状态** | 2026 启动 | 活跃(Hynek) | 半维护 | 活跃(Alibaba) |

**核心差异**:
- Sentinel 是**唯一一个**做"入口 + 业务"双层的 Python 框架
- 同时有 **system protection**(CPU/Load 自适应降级)
- 同时有 **hot-spot / authority** 5 大 rule 全套

## 6. 测试策略

### 6.1 测试覆盖率目标

- 单测覆盖率 ≥ 90%(per wheel)
- 集成测试覆盖 5 种降级场景 × 2 个保护层
- E2E 跑 1 个 demo 服务 1000+ QPS 持续 10 分钟,验证无内存泄漏

### 6.2 性能 benchmark

- Slot chain 入口检查延迟:< 1ms(单核 10K+ QPS)
- SlidingWindow 写入延迟:< 100us
- 规则匹配延迟(1000 rules):< 5ms

### 6.3 兼容性

- Python 3.12 / 3.13 / 3.14(workspace `stable-python`)
- ASGI 协议(支持任何 ASGI 框架)
- 老的 `atlas-richie-resilience` import 100% 兼容(M0 shim)

## 7. 风险与缓解

| 风险 | 缓解 |
|---|---|
| stamina/aiolimiter 升级 break | pyproject 锁上界,CI 跑 matrix |
| psutil 在 alpine / musl 不兼容 | 文档说明 linux/macOS only,Windows 走 WMI 备选 |
| httpx AsyncBaseTransport 升级 break | 锁 httpx < 0.28,等上游稳定再放宽 |
| Nacos / Redis source 在 M6+ 才发现设计错误 | MVP 用 file source,降低前期风险 |
| Cluster 模式设计错误导致推倒重来 | 1.0 前不做 cluster,推迟到 1.1+ |
| 5 个 rule wheel 边界判断错误 | 1.0 之前保持 1 个 rules wheel,1.1+ 视情况拆分 |

## 8. 跟现有 wheel 的关系

| 现有 wheel | 跟 Sentinel 关系 |
|---|---|
| `atlas-richie-resilience` | M0 改成 4 行 shim,re-export from `sentinel-primitives` |
| `atlas-richie-http` | 0.x 阶段通过 shim 用 primitives;1.0 GA 前可选择性迁移到 `sentinel-primitives` |
| `atlas-richie-mcp-http` | 同上 |
| `atlas-richie-secret` 系列 | 不相关,独立仓 |
| `atlas-richie-cache` 系列 | 不相关,独立仓 |
| `atlas-richie-mcp` | 0.x 不动;1.1+ 可选接入 `sentinel-adapter-asgi` |

## 9. 时间表

| Week | Milestone | PyPI version |
|---|---|---|
| 2026-W37(本周) | M0-skeleton | (无,本地) |
| 2026-W38 | M0-migration(原 R-104 迁完) | `0.0.1a1` alpha |
| 2026-W39 | M1 core | `0.0.1b1` beta |
| 2026-W40 | M2 ingress + file source | `0.1.0a1` alpha |
| 2026-W41 | M3 flow + degrade | `0.1.0b1` beta |
| 2026-W42 | M4 paramflow + authority + pool | `0.2.0rc1` RC |
| 2026-W43 | M5 dashboard + 1.0 GA | `1.0.0` GA |
| 2026-W44+ | M6+ cluster / nacos / redis | `1.1.0` / `2.0.0` |

## 10. 决策记录(关键设计选择)

1. **Mono-version**:所有 sentinel-* wheel 共享版本号(跟 Java Sentinel 风格)
2. **单个 rule 类型不拆**:5 个 rule 合并到 1 个 wheel(共享类型,降低管理成本)
3. **primitives 用 stamina + aiolimiter**:不重造 retry/CB/rate-limit 轮子(2026-09-12 决策)
4. **保留 Bulkhead / IdempotencyKey / Clock 自研**:这是我们的契约,需要 DIP 注入
5. **ASGI 不绑任何 web framework**:用纯 ASGI 协议,FastAPI/Starlette/Quart 都支持
6. **httpx PoolGuard 是 Java 没有的创新**:Python asyncio 共享连接池,需要主动拒绝
7. **M6+ 才做 cluster / nacos / redis source**:MVP 用 file + dashboard push 够用
8. **dashboard MVP 只做 REST API**:web UI 留 v1.1
9. **老的 `atlas-richie-resilience` 改 shim**:backwards compat,1.0 前完成内部迁移,2.0 删

---

**下一步**:commit + push M0-skeleton,然后下一次 session 启动 M0-migration(把 R-104 5 primitive 迁到 sentinel-primitives,改 shim)。
