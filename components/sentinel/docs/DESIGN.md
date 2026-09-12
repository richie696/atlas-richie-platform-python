# Atlas Richie Sentinel 产品与架构设计

> Status: Accepted architecture, implementation pending
>
> Version: Design baseline v2
>
> Updated: 2026-09-13
>
> Target: Python 3.12 / 3.13 / 3.14, public PyPI release, Apache-2.0
>
> Product name: Atlas Richie Sentinel

本文是 Atlas Richie Sentinel 的唯一总体设计基线，替代此前的 M0..M5 草案。
旧草案中关于 stamina 同时提供熔断、aiolimiter 等价于 Token Bucket、
primitives/core/rules 分成三个基础 wheel、ASGI 强依赖 Starlette 和文件规则源、
HTTPX 读取内部连接池水位、全局内存可以直接被独立 Dashboard 读取等设计不再有效。

## 1. 产品定位

Atlas Richie Sentinel 是一套面向 Python 服务的流量治理与韧性保护产品。它提供统一的
资源模型、规则模型、准入引擎、熔断状态机、滑动窗口统计、运行时指标和扩展协议，
既能保护整个进程的入口流量，也能保护单个业务资源和出站依赖。

它不是 Java Sentinel 源码的 Python 移植，也不复制 Java 的类结构。产品在行为语义上
参考成熟 Sentinel 模型，但必须使用 Python 社区习惯的 API、类型、异步生命周期和包结构。

### 1.1 核心目标

1. 安装一个主包即可获得完整的本地 Sentinel 能力。
2. 主包默认零第三方运行时依赖，不绑定任何 Web、HTTP、配置中心或监控框架。
3. ASGI、HTTPX、文件、Nacos、Redis、Dashboard 和 Cluster 作为独立扩展能力安装。
4. 同时覆盖入口保护、业务资源保护和出站依赖保护。
5. 所有规则、状态迁移、拒绝结果和指标口径都有稳定、可测试的行为契约。
6. 不使用魔法字符串表达公开配置；Python API 使用 Enum、不可变值对象和 Protocol。
7. 不依赖全局单例；同一进程允许存在多个相互隔离的 SentinelEngine。
8. 具备公开发布所需的类型提示、文档、兼容承诺、性能基线和安全边界。

### 1.2 非目标

Atlas Richie Sentinel 1.0 不承诺：

- 替代 CDN、WAF、L4/L7 网关或云厂商的 DDoS 防护。
- 自动解决进程外、主机外或集群级的强一致限流。
- 自动识别可信调用方身份；AuthorityRule 只消费认证系统提供的可信 origin。
- 读取 HTTPX/httpcore 私有连接池字段。
- 与 Java Sentinel 的内部类、包名、线程模型或 Dashboard 协议完全相同。
- 在没有 Cluster 或指标上报链路时聚合多个进程的实时状态。
- 在 1.0 中同时支持所有异步运行时。1.0 以 asyncio 为执行模型。

### 1.3 与 Java Sentinel 的关系

对齐范围是行为契约，而不是实现形式：

- Flow：QPS、并发、直接拒绝、预热、匀速排队。
- Degrade：慢调用比例、异常比例、异常数量、熔断恢复和半开探测。
- ParamFlow：按调用参数或协议字段进行热点参数限流。
- System：入口 QPS、平均响应时间、进程负载、CPU 使用率、在途请求数。
- Authority：可信 origin 的白名单或黑名单。

兼容层可以读取约定的 Java 风格配置字段，但 Python 领域模型统一使用 snake_case、
明确枚举和 Python 语义名称。兼容编码器属于边界层，不能污染核心对象。

### 1.4 三个保护层

~~~text
Layer A: Ingress / Process
ASGI 请求 -> event-loop lag / CPU / load / ingress QPS / average RT / in-flight
                         |
                         v
                   SystemRule

Layer B: Business Resource
async function / code block -> Authority / Flow / ParamFlow / Degrade
                         |
                         v
                 SentinelEngine entry

Layer C: Outbound Dependency
HTTPX attempt -> concurrency / queue budget / Flow / CircuitBreaker / Retry
                         |
                         v
                SentinelAsyncTransport
~~~

三个保护层共享同一 Resource、Rule、Outcome、MetricSnapshot 和错误语义，但协议对象、
资源命名和失败分类由各自 Adapter 负责。Retry 是调用编排能力，不自动套在所有 Entry 外层。

### 1.5 1.0 能力边界

| 能力 | 1.0 | 后续 |
|---|---|---|
| 本地资源准入与五类规则 | 完整 | 持续兼容增强 |
| asyncio 业务 API | 支持 | Trio/同步引擎按独立设计评估 |
| ASGI HTTP | 支持 | WebSocket 消息级、更多协议 Adapter |
| HTTPX async transport | 支持 | 其他 HTTP 客户端 Adapter |
| File Source | 支持 | Nacos、Redis 等远程 Source |
| 多 worker | 明确 per-process | Cluster 提供共享配额和聚合状态 |
| Dashboard | embedded per-process | 独立聚合控制面和 Web UI |
| Java 兼容 | 规则语义与配置 codec | 跨语言控制面协议 |

## 2. 已批准的产品决策

### 2.1 Resilience 并入 Sentinel

现有 atlas-richie-resilience 是 Sentinel 的前置研发成果，不再作为长期独立产品存在。
其中 Retry、CircuitBreaker、TokenBucket、Bulkhead、IdempotencyKey、Clock、
RandomSource 及其测试迁入 Sentinel 主包。

迁移完成后的目标状态：

- 仓库中不存在 components/resilience。
- workspace、versions、lock、发布脚本和文档不再引用 atlas-richie-resilience。
- HTTP、MCP 等内部消费者改为导入 atlas_richie.sentinel。
- 不向 PyPI 发布兼容 shim。
- 通过 git mv 保留代码历史；迁移不等于复制一份代码。

如果迁移期间必须保持主分支可运行，可以在同一个开发分支内按“新增目标包、迁移消费者、
删除旧包”的顺序完成，但最终合并状态不得遗留双份实现。

### 2.2 不引入 stamina 和 aiolimiter

主包不依赖 stamina 或 aiolimiter：

- stamina 是重试封装，不提供本产品要求的完整熔断状态机。
- aiolimiter 实现 Leaky Bucket，不能作为 TokenBucket 的等价实现。
- 现有自有实现已经包含幂等重试、首字节保护、可注入时钟、熔断状态机和真正的令牌桶。
- 引入语义不一致的第三方库会增加适配、版本锁定和行为漂移成本。

产品只实现自身公开契约需要的能力，不以复刻第三方库全部功能为目标。

### 2.3 主能力合并为一个 wheel

原语、引擎和规则是一个完整产品内部的三个模块，不是三个可独立交付的完整能力。
因此不再发布 sentinel-primitives、sentinel-core、sentinel-rules 三个基础 wheel。

主发行包为：

- PyPI distribution：atlas-richie-sentinel
- Python package：atlas_richie.sentinel

安装主包后即可使用所有本地原语、SentinelEngine、五类规则、内存规则仓库和内存指标。

### 2.4 核心不依赖平台 contracts

atlas-richie-sentinel 不依赖 atlas-richie-contracts。Sentinel 的异常、生命周期、
规则快照、事件和扩展 Protocol 由 Sentinel 自己拥有。

正确依赖方向是：

~~~text
atlas-richie-http / mcp / user application
                    |
                    v
          atlas-richie-sentinel
~~~

Sentinel 不能反向依赖 Atlas Richie 平台基础包，否则无法成为真正独立的 PyPI 产品。

## 3. 发行包与模块结构

### 3.1 公开发行包

| Distribution | Python import | 完整能力 | 必需运行时依赖 |
|---|---|---|---|
| atlas-richie-sentinel | atlas_richie.sentinel | 原语、引擎、规则、内存仓库、内存指标 | 无 |
| atlas-richie-sentinel-asgi | atlas_richie.sentinel.adapters.asgi | ASGI 入口保护 | atlas-richie-sentinel |
| atlas-richie-sentinel-httpx | atlas_richie.sentinel.adapters.httpx | HTTPX 出站保护 | sentinel + httpx |
| atlas-richie-sentinel-source-file | atlas_richie.sentinel.sources.file | JSON/YAML 文件规则源和热更新 | sentinel + PyYAML + watchfiles |
| atlas-richie-sentinel-source-nacos | atlas_richie.sentinel.sources.nacos | Nacos 规则源 | sentinel + Nacos SDK |
| atlas-richie-sentinel-source-redis | atlas_richie.sentinel.sources.redis | Redis 规则源 | sentinel + redis |
| atlas-richie-sentinel-dashboard | atlas_richie.sentinel.dashboard | 管理 API 和可选 Web UI | sentinel + FastAPI/Uvicorn |
| atlas-richie-sentinel-cluster | atlas_richie.sentinel.cluster | 分布式 Token Client/Server | sentinel + selected transport |
| atlas-richie-sentinel-observability | atlas_richie.sentinel.observability | Prometheus/OpenTelemetry 导出 | sentinel + selected exporter |

未实现的扩展 wheel 不得发布空壳版本。所有已发布 wheel 使用同一 major.minor 兼容线，
发布流水线统一验证依赖闭包和交叉版本兼容。

主 wheel 可以提供 system 可选 extra 安装 psutil 采样器，但默认安装仍保持零第三方依赖：

~~~bash
pip install "atlas-richie-sentinel[system]"
~~~

命名空间所有权：

- 主 wheel 独占 atlas_richie/sentinel/__init__.py 和所有顶层公开符号。
- 扩展 wheel 只能增加 adapters、sources、dashboard、cluster 下的叶子包。
- 扩展 wheel 不得重复打包或覆盖主包的 __init__.py。
- 所有扩展必须声明与主 wheel 兼容的 major.minor 范围。
- 构建流水线检查 wheel 文件清单，阻止两个 distribution 写入同一个文件。

### 3.2 主包内部结构

~~~text
atlas_richie/sentinel/
├── __init__.py                 # 稳定公开 Facade
├── engine/
│   ├── sentinel_engine.py
│   ├── entry.py
│   ├── slot.py
│   ├── slot_chain.py
│   ├── resource_registry.py
│   └── lifecycle.py
├── model/
│   ├── resource.py
│   ├── context.py
│   ├── argument.py
│   ├── decision.py
│   ├── outcome.py
│   └── enums.py
├── rules/
│   ├── base.py
│   ├── selector.py
│   ├── flow.py
│   ├── degrade.py
│   ├── param_flow.py
│   ├── system.py
│   ├── authority.py
│   ├── repository.py
│   └── snapshot.py
├── slots/
│   ├── node_selector.py
│   ├── statistic.py
│   ├── authority.py
│   ├── system.py
│   ├── flow.py
│   ├── param_flow.py
│   └── degrade.py
├── primitives/
│   ├── retry.py
│   ├── circuit_breaker.py
│   ├── token_bucket.py
│   ├── bulkhead.py
│   ├── idempotency.py
│   ├── clock.py
│   └── random_source.py
├── metrics/
│   ├── sliding_window.py
│   ├── registry.py
│   ├── snapshot.py
│   └── sink.py
├── ports/
│   ├── rule_source.py
│   ├── system_metric_sampler.py
│   ├── origin_resolver.py
│   ├── parameter_extractor.py
│   └── event_sink.py
└── errors/
    ├── base.py
    ├── block.py
    ├── configuration.py
    └── lifecycle.py
~~~

目录用于表达职责，不要求每个文件只有一个小类。紧密协作且共同变化的私有对象可以放在
同一模块中，禁止为了形式上的 OOP 制造无价值类。

### 3.3 依赖规则

~~~text
public facade
      |
      v
engine -----> rules -----> primitives
  |            |               |
  +----------> metrics <-------+
  |
  +----------> ports

adapters / sources / dashboard / cluster
                  |
                  v
          public facade + ports
~~~

硬约束：

- primitives 不依赖 engine、rules、adapters。
- rules 不依赖任何协议适配器或规则源。
- engine 不导入 HTTPX、ASGI、FastAPI、Nacos、Redis、PyYAML 或 psutil。
- 扩展包只能通过公开类型和 ports 与主包协作。
- 扩展包之间不直接依赖具体实现；组合由应用启动层完成。
- 第三方 SDK 类型不得出现在主包公开 API 中。

### 3.4 安装与最小使用

~~~bash
pip install atlas-richie-sentinel
~~~

~~~python
from atlas_richie.sentinel import (
    FlowBehavior,
    FlowGrade,
    FlowRule,
    Resource,
    ResourceSelector,
    SentinelEngine,
)

engine = SentinelEngine(
    rules=(
        FlowRule(
            rule_id="order-create-qps",
            resource=ResourceSelector.exact("order:create"),
            grade=FlowGrade.QPS,
            threshold=100,
            behavior=FlowBehavior.REJECT,
        ),
    ),
)

async with engine:
    async with engine.entry(Resource("order:create")):
        await create_order()
~~~

SentinelEngine 本身是 async context manager：进入时启动内部生命周期，退出时停止接收新
Entry、清理等待者并关闭受其所有的后台任务。由调用方传入且未转移所有权的依赖不由
Engine 擅自关闭。

## 4. 设计模式与误用防护

### 4.1 Facade：SentinelEngine

SentinelEngine 是用户完成资源保护所需的统一入口，负责协调规则仓库、SlotChain、
指标注册器、资源注册器和生命周期。

它不是 God Service：

- 不解析 YAML。
- 不读取 ASGI scope。
- 不创建 HTTPX Client。
- 不操作 Redis/Nacos。
- 不渲染 Dashboard。

### 4.2 Chain of Responsibility：SlotChain

规则检查天然具有有序检查、短路拒绝和退出回收语义，使用责任链。

必须明确：

- 固定的默认顺序。
- 自定义 Slot 的插入位置和优先级冲突处理。
- 中途拒绝时已获得资源的逆序回滚。
- 正常、异常、超时和取消时的逆序退出。
- Slot 自身异常与业务拒绝的区别。

### 4.3 State：CircuitBreaker

熔断器使用显式 CLOSED、OPEN、HALF_OPEN 状态机。所有合法迁移集中定义，
不允许在 DegradeSlot、HTTPX Adapter 和 Dashboard 中各写一套状态判断。

状态机必须定义并发探测名额、打开时间、恢复条件、强制打开/关闭和重置行为。

### 4.4 Strategy：可变化算法

以下位置使用最小 Protocol：

- ResourceNameResolver：协议请求如何映射为资源名。
- OriginResolver：如何获得可信调用方标识。
- ParameterExtractor：如何提取位置参数、关键字参数或协议字段。
- SystemMetricSampler：如何采集 CPU、load 和进程指标。
- Clock、Sleep、RandomSource：确定性测试和运行时实现。

只有存在真实替换点时才定义 Protocol；固定的内部计算直接使用普通对象和方法。

### 4.5 Adapter：外部技术边界

ASGI、HTTPX、文件、Nacos、Redis、Prometheus/OpenTelemetry 都是 Adapter。
Adapter 负责类型和错误翻译，不能把 SDK 类型传给 engine。

### 4.6 Observer：观测事件

准入、拒绝、完成、异常、规则更新和熔断状态迁移可以发布稳定事件给 EventSink。
事件仅用于观测和独立响应，不参与必须立即返回结果的规则判断。

事件投递必须有有界队列、丢弃策略和内部错误指标，不能因监控后端故障阻塞业务请求。

### 4.7 明确不采用

- 不采用全局 Singleton 保存规则和指标。
- 不采用 Service Locator 动态查找依赖。
- 不用继承树表达不同规则；规则是不可变数据，Slot/Controller 承担行为。
- 不用事件总线替代同一次准入流程中的直接调用。
- 不读取第三方库私有字段来伪装稳定能力。

## 5. 核心领域模型

### 5.1 Resource

~~~python
@dataclass(frozen=True, slots=True)
class Resource:
    name: str
    kind: ResourceKind = ResourceKind.COMMON
    traffic_type: TrafficType = TrafficType.INTERNAL
~~~

约束：

- name 去除首尾空白后不能为空。
- name 长度和字符集可配置，默认拒绝不可打印字符。
- kind 使用 ResourceKind Enum，不使用 type 字段遮蔽 Python 内置名称。
- traffic_type 使用 INTERNAL、INBOUND、OUTBOUND；SystemSlot 只处理 INBOUND。
- ASGI Adapter 固定产生 INBOUND，HTTPX Adapter 固定产生 OUTBOUND，普通业务 API 默认 INTERNAL。
- 动态路径必须由 ResourceNameResolver 归一化，禁止把订单号、用户 ID 等直接放入资源名。

### 5.2 Context 与 InvocationArguments

~~~python
@dataclass(frozen=True, slots=True)
class SentinelContext:
    name: str
    origin: str | None = None
    attributes: Mapping[str, object] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class InvocationArguments:
    positional: tuple[object, ...] = ()
    keyword: Mapping[str, object] = field(default_factory=dict)
    protocol: Mapping[str, object] = field(default_factory=dict)
~~~

Context 是不可变请求信息，不提供 put 方法。Slot 的可变运行态放在私有 EntryState，
避免 frozen dataclass 内部藏可变字典。

attributes 和 protocol 在构造时复制并只读暴露。密码、令牌、Cookie 原文等敏感信息
不得写入 Context、指标标签或 SentinelEvent。

### 5.3 EntryRequest、EntryLease 与 Outcome

~~~python
@dataclass(frozen=True, slots=True)
class EntryRequest:
    resource: Resource
    context: SentinelContext
    arguments: InvocationArguments
    permits: float = 1.0

class EntryLease:
    async def __aenter__(self) -> Entry:
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        ...
~~~

EntryLease 是一次准入事务的所有者，记录成功进入的 SlotLease。退出时严格逆序释放，
且 __aexit__ 固定返回 False，不吞掉业务异常。

Outcome 至少区分：

- ADMITTED：已获准进入。
- SUCCEEDED：业务正常完成。
- FAILED：业务异常完成。
- CANCELLED：任务或客户端取消。
- BLOCKED：规则拒绝，带 BlockReason 和 rule_id。

pass_count 表示 ADMITTED，不等价于 SUCCEEDED。block 不进入成功/失败统计，
但必须进入总请求和拒绝原因统计。

### 5.4 异步执行模型

1.0 的 SentinelEngine 是 asyncio-first：

~~~python
async with engine.entry(
    Resource("order:create"),
    context=context,
    arguments=arguments,
):
    await create_order()
~~~

装饰器只是一种便捷 Facade：

~~~python
@sentinel_resource(
    "order:create",
    engine=engine,
)
async def create_order(command: CreateOrder) -> Order:
    ...
~~~

约束：

- 装饰器保留原函数签名、名称、文档和类型提示。
- 1.0 不在同步函数内部偷偷启动 event loop。
- try_entry_nowait 可以为同步调用提供纯立即准入能力，但不执行 QUEUE 等等待行为。
- 同步阻塞引擎和 WSGI Adapter 属于后续明确里程碑，不能在 1.0 文档中暗示已支持。
- asyncio 对象不得跨 event loop 复用；错误使用应尽早抛 LifecycleError。

### 5.5 嵌套资源与 contextvars

Engine 使用 contextvars 维护当前 Entry 栈，使嵌套调用可以形成稳定调用路径：

~~~text
ASGI:POST /orders
└── order:create
    ├── inventory:reserve
    └── payment:authorize
~~~

约束：

- Entry 进入时保存 ContextVar token，退出时使用 token 精确恢复，不直接覆盖全局值。
- 同一 asyncio Task 内允许嵌套 Entry。
- 新建 Task 会继承当前 context；会脱离请求生命周期的后台任务必须通过公开 detach API
  清除 Sentinel 调用栈。
- 调用路径只保存资源标识，不保存业务参数。
- 最大嵌套深度可配置，超过上限抛 SentinelLifecycleError，避免递归或错误埋点耗尽内存。

### 5.6 Block handler 与 fallback

Engine 的核心行为是返回准入或抛 SentinelBlockedError，不自行制造业务返回值。
装饰器可以接受应用拥有的 BlockHandler/Fallback callable：

- BlockHandler 只处理规则拒绝。
- Fallback 只处理调用方明确声明的业务异常。
- 两者必须与被装饰函数的返回类型兼容。
- handler 自身失败保留异常链，不递归再次进入同一 Sentinel resource。
- Adapter 可以把拒绝映射为协议响应，但不能隐藏业务异常。

## 6. SlotChain 与准入生命周期

### 6.1 Slot 协议

~~~python
class Slot(Protocol):
    @property
    def order(self) -> int:
        ...

    async def enter(
        self,
        request: EntryRequest,
        state: EntryState,
    ) -> SlotLease:
        ...

class SlotLease(Protocol):
    async def complete(self, outcome: Outcome) -> None:
        ...

    async def release(self) -> None:
        ...
~~~

complete 在 release 前最多调用一次，release 必须幂等且最多产生一次外部副作用。
一个 Slot 如果没有资源需要释放，可以返回不可变 NoopSlotLease。逆序释放期间某个
Lease 失败不能阻止其他 Lease 继续释放；所有释放错误汇总为内部事件并保留异常上下文。

### 6.2 默认顺序

| Order | Slot | 职责 |
|---:|---|---|
| 100 | NodeSelectorSlot | 获取或创建有界 ResourceNode |
| 200 | StatisticSlot | 建立计时和统计外层 Lease |
| 300 | AuthoritySlot | 校验可信 origin |
| 400 | SystemSlot | 进程级入口保护 |
| 500 | FlowSlot | QPS、并发、预热、排队 |
| 600 | ParamFlowSlot | 热点参数流控 |
| 700 | DegradeSlot | 熔断状态判断和半开探测 |

顺序常量集中定义，禁止在多个模块中重复数字。自定义 Slot 必须声明唯一 order；
冲突默认抛 ConfigurationError，不通过加载顺序隐式决定。

### 6.3 进入和退出

~~~text
创建 EntryRequest
    |
    v
依次 enter Slot
    |
    +-- Blocked --> 逆序 release 已进入 Slot --> 记录 BLOCKED --> 抛 SentinelBlockedError
    |
    +-- Internal error --> 逆序 release --> 记录 INTERNAL_ERROR --> 按配置 fail-safe
    |
    v
执行业务
    |
    +-- success ----+
    +-- exception --+--> 生成 Outcome --> 逆序 complete/release
    +-- cancel -----+
~~~

默认 fail-safe：

- 规则明确拒绝：fail closed，抛对应 SentinelBlockedError。
- Sentinel 内部观测失败：fail open，并记录内部错误。
- 核心状态损坏、规则快照不可解释：fail fast，拒绝启动或拒绝更新，不在运行中静默猜测。
- SystemMetricSampler 暂时不可用：只跳过依赖该指标的规则，并暴露 degraded health；
  不影响其他规则。

asyncio.CancelledError 归类为 CANCELLED，不默认计入异常比例，也不得被重试或吞掉。

## 7. 规则模型

### 7.1 Rule 基础契约

~~~python
@dataclass(frozen=True, slots=True, kw_only=True)
class Rule:
    rule_id: str
    enabled: bool = True
    priority: int = 0

@dataclass(frozen=True, slots=True, kw_only=True)
class ResourceRule(Rule):
    resource: ResourceSelector
~~~

Rule 是所有规则共享的身份和启用契约。Flow、Degrade、ParamFlow、Authority 继承
ResourceRule；SystemRule 直接继承 Rule，因为它作用于当前 Engine 的全部入口资源，
不携带伪造的 resource 字段。

规则是不可变数据，不在子类中实现 matches。资源匹配由 RuleIndex 和
ResourceSelector 统一完成，避免每种资源规则复制匹配代码。

规则及其子类统一使用 kw_only=True。这既避免基类默认字段与子类必填字段产生
dataclass 参数顺序冲突，也让包含多个阈值的规则必须以名称构造。

~~~python
@dataclass(frozen=True, slots=True)
class ResourceSelector:
    pattern: str
    match_kind: ResourceMatchKind = ResourceMatchKind.EXACT
~~~

ResourceSelector 支持：

- EXACT：默认且最快。
- GLOB：显式选择并在加载时编译。
- PREFIX：适合受控命名空间。

1.0 不支持任意正则表达式，避免 ReDoS 和不可控匹配开销。

匹配优先级：

1. enabled 为 true。
2. EXACT 优先于 PREFIX，PREFIX 优先于 GLOB。
3. 同类型按 priority 降序。
4. 仍相同则按 rule_id 升序，确保确定性。

加载规则时构建索引，运行时禁止对全部规则做线性扫描。

### 7.2 FlowRule

~~~python
@dataclass(frozen=True, slots=True, kw_only=True)
class FlowRule(ResourceRule):
    grade: FlowGrade
    threshold: float
    behavior: FlowBehavior = FlowBehavior.REJECT
    scope: FlowScope = FlowScope.DIRECT
    scope_reference: ResourceSelector | None = None
    warm_up_period: timedelta | None = None
    max_queueing_time: timedelta | None = None
~~~

FlowGrade：

- QPS
- CONCURRENCY

FlowBehavior：

- REJECT
- WARM_UP
- QUEUE

FlowScope：

- DIRECT：只看当前资源统计。
- ORIGIN：按可信 SentinelContext.origin 分区统计。
- ASSOCIATED_RESOURCE：当关联资源达到压力阈值时限制当前资源。
- CALL_PATH：仅对匹配父级调用路径的请求生效。

校验规则：

- threshold 必须大于 0。
- WARM_UP 必须提供正数 warm_up_period。
- QUEUE 必须提供非负 max_queueing_time。
- CONCURRENCY 不接受 WARM_UP。
- ASSOCIATED_RESOURCE/CALL_PATH 必须提供 scope_reference。
- DIRECT/ORIGIN 不接受 scope_reference。
- ORIGIN 缺少可信 origin 时的行为必须显式配置为聚合到 unknown 或拒绝，不能随机跳过规则。
- 等待被取消时必须撤销队列占位或保证调度算法不会泄漏容量。

### 7.3 DegradeRule

~~~python
@dataclass(frozen=True, slots=True, kw_only=True)
class DegradeRule(ResourceRule):
    strategy: DegradeStrategy
    threshold: float
    statistical_window: timedelta
    open_duration: timedelta
    minimum_request_count: int = 5
    slow_call_threshold: timedelta | None = None
    half_open_probe_count: int = 1
~~~

DegradeStrategy：

- SLOW_CALL_RATIO
- ERROR_RATIO
- ERROR_COUNT

语义：

- SLOW_CALL_RATIO 的 threshold 是 0..1 比例，且必须提供 slow_call_threshold。
- ERROR_RATIO 的 threshold 是 0..1 比例。
- ERROR_COUNT 的 threshold 是统计窗口内异常数量。
- 样本量不足 minimum_request_count 时不得因比例规则打开。
- OPEN 到期后进入 HALF_OPEN，探测成功数量达到配置值才恢复。
- HALF_OPEN 任一探测失败立即重新 OPEN。
- 强制打开、强制关闭和重置只通过明确管理 API 执行并产生审计事件。

DegradeSlot 复用 primitives 中唯一的 CircuitBreaker 状态机，不再实现第二套熔断逻辑。

### 7.4 ParamFlowRule

~~~python
@dataclass(frozen=True, slots=True)
class ParameterSpec:
    source: ParameterSource
    key: str | int
    extractor_id: str | None = None

@dataclass(frozen=True, slots=True)
class ParameterOverride:
    value: str | int | float | bool
    threshold: float

@dataclass(frozen=True, slots=True, kw_only=True)
class ParamFlowRule(ResourceRule):
    parameter: ParameterSpec
    threshold: float
    behavior: FlowBehavior = FlowBehavior.REJECT
    overrides: tuple[ParameterOverride, ...] = ()
    max_distinct_values: int = 1_000
    idle_ttl: timedelta = timedelta(minutes=10)
~~~

ParameterSource：

- POSITIONAL
- KEYWORD
- HEADER
- QUERY
- COOKIE
- CUSTOM

ParameterSpec 必须校验 source 与 key 的组合：POSITIONAL 只能使用非负整数，
KEYWORD/HEADER/QUERY/COOKIE 只能使用非空字符串，CUSTOM 必须提供 extractor_id。
ParameterOverride 只接受可稳定序列化的标量值，并在加载时完成规范化。

HTTP 字段名由 Adapter 归一化后放入 protocol，不让核心依赖 HTTP 对象。
CUSTOM 通过注册的 ParameterExtractor ID 选择实现，不接受任意 import 字符串。

热点参数状态必须受 max_distinct_values 和 idle_ttl 约束。超过基数上限时使用明确的
overflow bucket 或拒绝新值，行为由枚举配置，不能无限创建字典项。

### 7.5 SystemRule

~~~python
@dataclass(frozen=True, slots=True, kw_only=True)
class SystemRule(Rule):
    strategy: SystemProtectionStrategy = SystemProtectionStrategy.DIRECT
    highest_system_load: float | None = None
    highest_cpu_usage: float | None = None
    highest_event_loop_lag: timedelta | None = None
    ingress_qps: float | None = None
    highest_average_rt: timedelta | None = None
    max_in_flight: int | None = None
~~~

不再同时存在 qps 和 ingress_qps，也不使用 max_thread 描述 asyncio 请求。

SystemMetricSampler 是可注入 Port：

~~~python
class SystemMetricSampler(Protocol):
    async def sample(self) -> SystemMetricSnapshot:
        ...
~~~

默认主包不安装 psutil。需要 CPU/load 规则时显式安装并配置对应采样器。
采样器每个周期最多运行一次，结果带 sampled_at 和 stale_after。过期指标不得继续用于拒绝。

加载依赖 CPU/load 的规则但没有配置对应采样器属于配置错误，快照不得生效。
Engine 正常运行后采样器的暂时失败才按 degraded health 处理，并跳过依赖失效指标的判断。

所有 SystemRule 都是当前进程语义。多 worker 总量不是各 worker 自动共享的总量。

SystemProtectionStrategy：

- DIRECT：任一已配置硬阈值达到条件时拒绝新入口请求。
- ADAPTIVE_CAPACITY：CPU/load/event-loop lag 只作为过载触发信号，同时根据近期完成 QPS、
  最小稳定 RT 和当前 in-flight 估计可安全并发容量，只有触发信号与容量不足同时成立才拒绝。

自适应容量初始估算遵循 Little's Law 的保守形式：

~~~text
estimated_capacity = max(1, stable_completed_qps * minimum_stable_rt_seconds)
~~~

这不是对 Java 实现代码的复制。窗口选择、冷启动最小样本、异常流量是否参与、
容量上下限和恢复滞回都必须成为明确配置并有基准验证。样本不足时退回已配置的 DIRECT
硬阈值；没有硬阈值时不凭不完整数据拒绝请求。

event-loop lag 是 Python asyncio 服务的重要过载信号，由主包使用调度延迟采样；
CPU/load 等宿主指标由可选 SystemMetricSampler 提供。

SystemSlot 仅对 Resource.traffic_type 为 INBOUND 的 Entry 生效。业务内部调用和出站请求
不会重复消耗入口系统阈值，但仍可受各自的 Flow、Degrade 和 ParamFlow 规则保护。

### 7.6 AuthorityRule

~~~python
@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorityRule(ResourceRule):
    strategy: AuthorityStrategy
    origins: frozenset[str]
~~~

AuthorityStrategy 为 ALLOW_LIST 或 DENY_LIST。

origin 必须来自受信任的 OriginResolver，例如：

- 已验证 JWT 的 client_id/sub。
- 网关验签后的应用标识。
- mTLS 证书身份。
- 应用内部已认证的服务账号。

直接读取客户端可伪造的 X-Origin 只能作为显式启用的不可信示例，不能成为生产默认值。

## 8. Resilience 原语整合

### 8.1 Retry

保留并完善：

- max_attempts 和总耗时预算。
- 指数退避、上限和可注入 jitter。
- 可重试异常谓词。
- IdempotencyKey gating。
- 流式调用 first-byte 保护。
- on_retry 观测事件。
- Clock、Sleep、RandomSource 注入。

规则：

- 默认不重试所有 Exception；调用方必须明确异常范围。
- CancelledError、认证失败、参数错误和 SentinelBlockedError 默认不可重试。
- retry_after 可以覆盖下一次退避，但仍受总预算约束。
- 每次真实网络 attempt 独立经过出站流控和并发保护。
- 重试不能隐藏最终异常类型；RetryExhausted 保留最后异常链。

### 8.2 CircuitBreaker

现有实现作为迁移起点，统一扩展为 DegradeRule 所需状态机：

- count-based 和 time-based 统计窗口。
- failure count、failure ratio、slow call ratio。
- CLOSED、OPEN、HALF_OPEN。
- 并发安全的半开探测许可。
- 强制状态仅用于管理和测试。
- 每次状态迁移产生 CircuitStateChangedEvent。

状态和指标由对应 Engine 实例拥有，不放在模块级全局字典。

### 8.3 TokenBucket

保留真正的 Token Bucket：

- capacity。
- refill_rate。
- tokens_per_acquire。
- try_acquire。
- 有界等待 acquire。
- retry_after。
- 单调时钟。

必须补齐：

- 同一 event loop 内并发调用的原子性。
- 等待公平性和取消清理。
- 浮点边界和长时间运行误差。
- 明确不能跨进程提供全局限流。

### 8.4 Bulkhead

Bulkhead 限制 in-flight 操作，不使用 thread 术语：

- fail-fast 或有界等待。
- async context manager 自动释放。
- 重复 release 和未 acquire release 必须暴露编程错误。
- 取消、超时和业务异常都不能泄漏 permit。
- 提供当前使用量和拒绝数快照，不暴露底层 Semaphore。

### 8.5 IdempotencyKey

IdempotencyKey 是 Retry 的安全策略，不是幂等结果存储：

- StatelessIdempotencyKey 只允许调用方已声明无副作用的操作重试。
- CallableIdempotencyKey 从稳定业务字段生成 key。
- NeverIdempotencyKey 禁止重试。
- key 不写入普通日志和指标；需要关联时记录不可逆摘要。
- Sentinel 不承诺缓存业务结果、去重数据库写入或代替服务端幂等实现。

需要跨请求结果去重时，应由业务或独立幂等组件拥有持久化状态；Retry 只根据
IdempotencyKey 判断再次执行是否被允许。

### 8.6 Clock 与随机源

所有时间窗口、超时、状态迁移和采样使用单调 Clock。墙上时间仅用于展示事件时间，
不能用于计算窗口和超时。

ManualClock 和 DeterministicRandom 是正式测试支持能力，不是 tests 私有复制品。

## 9. 指标、滑动窗口和资源治理

### 9.1 SlidingWindow

使用标准库实现固定大小环形时间桶，不引入 sortedcontainers。

设计：

- window_duration 必须能被 bucket_count 整除。
- 桶索引由 monotonic clock 计算。
- 过期桶在访问时原位重置，不排序、不分配长期对象。
- 写入和快照的临界区短且不执行 await。
- 统计对象不向外暴露内部可变桶。

MetricSnapshot 至少包含：

- admitted_count
- blocked_count，按 BlockReason 分类
- success_count
- failure_count
- cancelled_count
- total_rt
- min_rt
- max_rt
- configurable latency buckets
- sampled_at
- window_duration

### 9.2 资源基数

ResourceRegistry 必须配置：

- max_resources。
- idle_ttl。
- cleanup_interval。
- overflow policy。

默认禁止无限创建动态资源。达到上限时记录 ResourceCardinalityExceededEvent，
并根据策略聚合到 overflow resource 或拒绝注册。

### 9.3 指标标签

指标只允许低基数标签：

- resource
- resource_kind
- traffic_type
- rule_kind
- block_reason
- outcome

禁止将用户 ID、订单号、URL 原始查询参数、异常消息或 token 放入指标标签。

## 10. 规则仓库与动态规则源

### 10.1 RuleSnapshot

~~~python
@dataclass(frozen=True, slots=True)
class RuleVersion:
    epoch: str
    revision: int

@dataclass(frozen=True, slots=True)
class RuleSnapshot:
    schema_version: str
    version: RuleVersion
    rules: tuple[Rule, ...]
    source_id: str
    created_at: datetime
    checksum: str
~~~

规则源负责产生快照；RuleRepository 负责校验、编译索引和原子替换。
epoch 标识一次连续版本历史，revision 是同一 epoch 内单调递增的非负整数。
不同 epoch 不能凭字符串大小猜测新旧，必须由 Source 重连策略或管理操作显式接纳。

### 10.2 更新语义

规则更新必须满足：

1. 完整读取。
2. 解析到边界 DTO。
3. 映射为领域 Rule。
4. 校验所有字段和组合约束。
5. 编译 ResourceSelector 和规则索引。
6. 生成校验后的不可变快照。
7. 单次原子交换。
8. 发布 RuleSnapshotAppliedEvent。

任一步失败都保留 last-known-good，不允许先清空旧规则。

版本相同且 checksum 相同的更新是幂等 no-op；版本相同但 checksum 不同必须拒绝并报警。
同一 epoch 的旧 revision 默认拒绝。每个 source_id 拥有自己的完整规则快照，更新只替换
该来源的规则集合；多个来源的有效视图按照显式 source priority 合并，不能由最后回调时间
隐式覆盖。

### 10.3 RuleSource Port

~~~python
class RuleSource(Protocol):
    def snapshots(self) -> AsyncIterator[RuleSnapshot]:
        ...

    async def aclose(self) -> None:
        ...
~~~

RuleSource 以异步迭代器单向产生快照，不持有具体 RuleManager/RuleRepository，
RuleRepository 也不反向拉取具体 Source。Engine 的 RuleSourceSupervisor 拥有消费任务、
取消和关闭顺序，Source 不在 start 方法中隐藏创建后台任务。

RuleSource 必须定义：

- 首次迭代成功/失败的启动行为。
- 迭代结束、监听退出和重连。
- 指数退避与 jitter。
- 消费速度慢于更新速度时的合并或背压策略。
- stale 状态。
- aclose 的幂等性。
- 凭证来源和日志脱敏。

### 10.4 File Source

支持 JSON 作为规范格式，YAML 作为便捷格式。

- 文件写入采用临时文件加原子 rename。
- watcher 事件去抖并允许同一文件产生多次事件。
- 读取过程中遇到半文件时保留旧快照并重试。
- 文件不存在、权限错误、语法错误和规则校验错误分别报告。
- 文件 Source 不由 ASGI Adapter 自动安装或启动。

### 10.5 Nacos 与 Redis Source

Nacos 和 Redis 实现同一 RuleSource 契约，并执行同一套 contract tests。

Redis pub/sub 只负责变更通知时，规则正文需要有可恢复存储；单纯 pub/sub 不能保证
离线期间消息补偿。必须选择以下一种：

- Redis key 保存最新快照，pub/sub 只发送版本通知。
- Redis Streams 提供可恢复消费。

Nacos/Redis 更新都必须携带 version/checksum，且不得把 SDK 返回类型传入主包。

## 11. ASGI Adapter

### 11.1 边界

ASGI Adapter 使用纯 ASGI callable，不继承 Starlette Middleware，不强制依赖 FastAPI、
Starlette、Quart 或文件规则源。

~~~python
app = SentinelASGIMiddleware(
    app,
    engine=engine,
    resource_name_resolver=MethodRouteResolver(),
    origin_resolver=AuthenticatedScopeOriginResolver(),
)
~~~

### 11.2 协议生命周期

- http scope：从请求进入到最后一个响应 body 完成。
- 流式响应：必须等 more_body=False 或异常/断连后退出 Entry。
- 客户端断连：记录 CANCELLED，不计为业务异常。
- websocket：1.0 默认不保护；启用时必须定义连接级和消息级资源。
- lifespan：永不进入业务流控。
- 下游在 response start 后失败：不得再次发送新的 HTTP 错误响应，只记录失败并关闭。

### 11.3 默认 HTTP 映射

| BlockReason | HTTP status | Retry-After |
|---|---:|---|
| FLOW / PARAM_FLOW / CONCURRENCY | 429 | 可计算时返回 |
| SYSTEM_OVERLOAD | 503 | 可计算时返回 |
| CIRCUIT_OPEN | 503 | 返回预计恢复时间 |
| AUTHORITY_DENIED | 403 | 不返回 |
| INTERNAL_CONFIGURATION | 500 | 不返回 |

响应体使用稳定的错误 code、resource、reason、request_id；不暴露规则全文、阈值、
堆栈或敏感上下文。

### 11.4 进程语义

ASGI Adapter 的默认计数是每个 worker、每个 Engine 实例独立。文档和配置示例必须明确：

~~~text
configured threshold × worker count = approximate process-group capacity
~~~

如果需要跨 worker 精确总量，必须使用 Cluster 能力。Dashboard 不能把单 worker 数据
描述成整个服务数据。

## 12. HTTPX Adapter

### 12.1 能力名称

第一版能力命名为 OutboundConcurrencyGuard，而不是 PoolGuard。它保护出站请求并发和
排队预算，但不声称能够读取 HTTPX 内部 TCP 连接池真实队列。

### 12.2 实现边界

使用公开的 httpx.AsyncBaseTransport 包装默认或用户提供的 transport：

~~~python
transport = SentinelAsyncTransport(
    wrapped=httpx.AsyncHTTPTransport(limits=limits),
    engine=engine,
    resource_name_resolver=OriginResourceResolver(),
)
~~~

约束：

- 不访问 httpcore 私有属性。
- per-origin key 由 scheme、normalized host、effective port 组成。
- permit 必须在响应流 EOF 或 aclose 后释放，不能在 handle_async_request 返回时释放。
- 请求构建失败、DNS、连接、TLS、读写、HTTP 状态和取消分别映射 Outcome。
- Adapter 不默认重试；重试由明确的 RetryPolicy 组合。
- 每次网络 attempt 都重新执行流控和并发保护。
- 用户传入 transport 的 aclose 必须被正确转发且只执行一次。

### 12.3 与 Circuit Breaker 的关系

出站资源建议命名：

~~~text
httpx:{scheme}://{host}:{port}
~~~

Circuit Breaker 是否把某个 HTTP 状态视为失败由 OutcomeClassifier Strategy 决定。
默认只把连接错误、超时和 5xx 计为候选失败，4xx 不自动计为下游故障。

## 13. Dashboard 与控制面

### 13.1 1.0 模式

1.0 Dashboard 先提供嵌入式管理 API，只查看或修改所在 Engine 实例：

- GET /api/v1/resources
- GET /api/v1/metrics
- GET /api/v1/rules
- PUT /api/v1/rule-snapshots/{source}
- GET /health/live
- GET /health/ready

不使用 POST 逐条修改规则作为主接口；控制面提交完整快照，复用 RuleRepository 的原子更新。

### 13.2 安全默认值

- 默认只绑定 loopback。
- 默认只读。
- 开启写操作必须配置认证和授权。
- 所有更新记录 principal、source、old_version、new_version、checksum 和结果。
- 不记录规则中的敏感扩展字段。
- 浏览器模式需要明确 CORS 和 CSRF 策略。
- 健康检查不泄露文件路径、Redis/Nacos 地址或凭证。

### 13.3 聚合模式

独立聚合 Dashboard 需要 Agent Reporting Protocol 或 Cluster，不能直接读取其他进程内存。
该协议必须定义：

- instance_id 和启动纪元。
- 指标增量或快照序号。
- 重复、乱序和离线处理。
- 上报频率、背压和最大缓存。
- mTLS/OAuth 或等价的实例认证。

未实现该协议前，产品只宣称 embedded per-process Dashboard。

## 14. Cluster

Cluster 是 1.0 后独立里程碑，但核心必须预留 TokenService Port，避免未来重写 FlowSlot。

集群模式必须明确：

- Token Server 与 embedded server 两种部署模式。
- 请求 ID、规则版本和资源键。
- 网络超时、重试和幂等。
- fail-open、fail-closed 或 local-fallback 策略。
- 服务器不可用时的容量风险。
- 多节点时间和窗口语义。
- stale owner fencing。
- 指标聚合与规则发布关系。

集群验收必须至少使用两个活动实例，并覆盖 server crash、网络分区、超时、
恢复、重复请求和规则版本切换。单进程 mock 不能证明集群能力。

## 15. 配置与兼容

### 15.1 规范格式

JSON 是跨语言和签名校验的规范格式；YAML 是 File Source 的人工编辑格式。

规范配置包含：

- schema_version
- source_id
- version.epoch
- version.revision
- generated_at
- rules

未知 schema major 必须拒绝。未知字段默认拒绝，只有显式 forward-compatible 扩展区允许保留。
checksum 对字段排序、数字和 Unicode 规范化后的 JSON 内容计算，不能直接对 YAML 原文字节计算。

~~~json
{
  "schema_version": "1.0",
  "source_id": "local-file",
  "version": {
    "epoch": "orders-service",
    "revision": 12
  },
  "generated_at": "2026-09-13T12:00:00Z",
  "rules": []
}
~~~

### 15.2 Python API

Python API 使用：

- snake_case。
- Enum/StrEnum。
- datetime.timedelta 表达时间。
- frozen dataclass 表达规则和快照。
- Protocol 表达消费者拥有的可替换能力。
- collections.abc 中的抽象容器类型。
- async context manager 表达准入生命周期。

禁止：

- 公共参数接收 path、thread、string 等未约束魔法字符串。
- 用 dict[str, Any] 代替稳定规则模型。
- 让调用方传入第三方 SDK 对象。
- 为模仿 Java 创建 Bean、Manager 单例或深继承层级。

### 15.3 Java 配置兼容

可选 codec 可以接受 Java 风格字段，例如 maxThread、timeWindow、controlBehavior，
并在边界映射为 Python 领域对象。映射规则有独立 contract tests。

Java 配置兼容不意味着：

- Python 内部继续使用 thread 命名。
- 两端在不同 worker/进程模型下拥有相同吞吐量。
- 未实现的 Cluster/Dashboard 协议被视为兼容。

## 16. 异常与拒绝契约

~~~text
SentinelError
├── SentinelConfigurationError
├── SentinelLifecycleError
├── RuleSnapshotError
└── SentinelBlockedError
    ├── FlowBlockedError
    ├── ParamFlowBlockedError
    ├── SystemBlockedError
    ├── CircuitOpenError
    ├── AuthorityDeniedError
    └── BulkheadFullError
~~~

SentinelBlockedError 至少携带：

- stable code
- BlockReason Enum
- resource
- rule_id
- retry_after
- message

message 面向开发者但不得作为程序判断依据。Adapter 只根据 code/reason 映射协议响应。

第三方异常必须通过 raise ... from exc 保留 cause。禁止吞掉规则源、采样器或 transport
异常；允许 fail-open 的位置也必须产生内部指标和可观测事件。

## 17. 线程、事件循环和多进程契约

### 17.1 asyncio

- EngineState 为 CREATED、STARTING、RUNNING、CLOSING、CLOSED、FAILED。
- 合法迁移集中定义为 CREATED -> STARTING -> RUNNING -> CLOSING -> CLOSED；
  启动失败进入 FAILED，FAILED 只能显式 close，不能自动复活。
- 一个 Engine 绑定首次启动它的 event loop。
- Engine.start 和 Engine.close 幂等；重复调用不能重复创建或关闭后台任务。
- close 后拒绝新 Entry，等待中的 Entry 被取消并清理。
- close 可以配置 graceful_timeout；到期后取消仍在执行的内部等待任务，但不强杀业务协程。
- 运行时规则快照可原子替换，不阻塞事件循环执行文件/网络 I/O。

### 17.2 线程

公共只读快照可以跨线程读取；运行时准入状态默认只保证所属 event loop 内安全。
如果未来支持线程池调用，必须通过明确线程安全 Facade，不以 GIL 作为并发正确性证明。

### 17.3 进程

主包全部状态都是 per-process。fork 前创建的 Engine 不可在 fork 后继续使用；
每个 worker 在启动生命周期内创建并启动自己的 Engine。

多进程总量、聚合指标和统一熔断状态只有 Cluster/Reporting 能力可以提供。

## 18. 可观测性

主包提供稳定事件和快照，不依赖 prometheus-client 或 OpenTelemetry。

事件包括：

- EntryAdmitted
- EntryBlocked
- EntryCompleted
- CircuitStateChanged
- RuleSnapshotApplied
- RuleSnapshotRejected
- ResourceCardinalityExceeded
- SentinelInternalError

EventSink 必须非阻塞或使用有界缓冲。默认 NoopEventSink 不创建后台任务。
可选 Prometheus/OpenTelemetry Adapter 负责标签映射和导出。

~~~python
class EventSink(Protocol):
    def emit(self, event: SentinelEvent) -> None:
        ...
~~~

emit 不执行网络 I/O。需要远程发送的 Adapter 将事件放入自己的有界队列，由其明确拥有的
后台任务发送；队列满时按配置丢弃最新或最旧事件，并增加 dropped_events 指标。

所有事件应包含 engine_id、resource、时间、规则标识和 request correlation ID；
不得包含业务参数原值和凭证。

## 19. 测试设计与证据门禁

覆盖率是诊断指标，不是完成标准。关键状态机、规则分支和资源释放必须通过行为测试证明。

### 19.1 风险到测试矩阵

| ID | 风险 | 最低证据 | 发布门禁 |
|---|---|---|---|
| SEN-CORE-001 | Slot 中途拒绝泄漏 permit | 单元 + 组件测试 | 每个进入点故障注入，逆序释放断言 |
| SEN-CORE-002 | CancelledError 被吞或计为失败 | asyncio 组件测试 | 等待、业务执行、流式响应三个取消点 |
| SEN-CB-001 | 熔断状态错误 | 状态迁移测试 | 合法/非法迁移、并发半开、时间推进 |
| SEN-SYSTEM-001 | 系统自适应阈值错误地放过/误拒 | 确定性时钟 + 2 策略 + sampler 失败降级 | CPU/load/event-loop-lag/in-flight 指标采集正确性，指标采样器失败时按 fail-safe 降级 |
| SEN-FLOW-001 | QPS/并发越界 | 确定性时钟测试 | 边界、burst、等待、公平、取消 |
| SEN-PARAM-001 | 热点参数造成内存增长 | 基数/淘汰测试 | overflow 和 idle TTL |
| SEN-AUTH-001 | 黑白名单/可信 origin resolver 误判 | origin 不可信 + ALLOW/DENY 互斥 + 配置错误拒绝 | 默认所有客户端 origin 不可信；DENY_LIST 命中即拒；OriginResolver 配置错误也拒绝并写审计 |
| SEN-RULE-001 | 热更新产生半快照 | RuleSource contract test | 解析失败、乱序、重复、原子交换 |
| SEN-ASGI-001 | 流式响应提前释放 | ASGI 协议集成测试 | body EOF、断连、异常 |
| SEN-HTTPX-001 | 响应流未关闭导致 permit 泄漏 | HTTPX 集成测试 | EOF、aclose、异常、取消 |
| SEN-MP-001 | 多 worker 口径误判 | 两进程测试 | 每进程阈值和指标隔离 |
| SEN-DASH-001 | 未授权规则修改 | 安全集成测试 | 无认证、越权、CSRF/CORS、审计 |
| SEN-CLUSTER-001 | 集群故障重复或超发 | 双实例真实依赖测试 | crash、分区、恢复、去重 |
| SEN-PERF-001 | 引擎开销或内存回归 | 基准 + load/spike/soak | 与已批准基线比较 |

### 19.2 单元测试

- 所有规则构造校验和枚举映射。
- ResourceSelector 匹配、优先级和索引。
- SlidingWindow 桶轮转、边界时间、重置和快照。
- TokenBucket refill、浮点边界、等待预算。
- CircuitBreaker 所有状态迁移。
- Retry 预算、jitter、幂等和 first-byte。
- RuleSnapshot checksum、版本和不可变性。
- 异常分类与 HTTP 映射。

时间相关测试使用 ManualClock，不使用真实 sleep。

### 19.3 组件与契约测试

- SentinelEngine + 全部默认 Slot 的成功、拒绝、异常、取消和关闭。
- 所有 RuleSource 运行同一套契约测试。
- 所有 EventSink 运行同一套非阻塞、异常隔离和脱敏测试。
- Python/Java 配置 codec 使用共享 fixture 验证语义映射。
- public import、__all__、类型检查和 wheel 隔离安装。

### 19.4 集成测试

- File Source 使用真实临时文件和 watcher。
- ASGI 使用真实协议消息序列，不只依赖框架 TestClient。
- HTTPX 使用受控下游服务验证流式响应和连接错误。
- Dashboard 使用真实 ASGI 进程验证认证、更新和审计。
- Nacos、Redis、Cluster 必须在对应真实或协议兼容服务上验证。

Mock 只能证明本层编排，不能作为真实 Redis/Nacos、多进程或网络行为的验收证据。

### 19.5 性能与容量

M1 建立基线，后续里程碑只能在批准阈值内回归。首次基线未完成前，文档不声称具体 QPS。

基准必须记录：

- commit、Python 版本、OS、CPU。
- 规则数量和资源数量。
- 并发度和事件循环。
- p50、p95、p99、max，而不只记录平均值。
- CPU、RSS、分配次数和 GC。

场景：

- 无规则准入。
- 单 FlowRule。
- 五类规则同时存在。
- 1,000 条 exact 规则索引命中和未命中。
- 热点参数达到基数上限。
- 10 分钟 load、突发 spike、至少 1 小时 soak。

“10 分钟无崩溃”不能表述为“证明无内存泄漏”。内存验收使用稳定负载下 RSS/对象数量
斜率和资源淘汰后的回落证据。

### 19.6 发布证据

每次发布记录：

- 对应 requirement/test ID。
- 执行命令和 CI run。
- commit 和 wheel hash。
- Python/OS matrix。
- 失败、跳过、flaky 和未验证边界。
- 真实外部依赖的环境身份和清理结果。

## 20. 安全与隐私

- AuthorityRule 不承担认证，只消费可信身份。
- Dashboard 写操作必须认证、授权和审计。
- 配置文件和动态源不得包含明文密钥。
- 日志、指标和事件不得记录 token、Cookie、Authorization、用户参数原值。
- 规则 glob 在加载时编译；不允许不受控正则。
- 所有外部字符串有长度限制。
- 错误响应不暴露内部阈值、SDK 错误和堆栈。
- 规则更新支持 checksum；远程来源根据部署需要增加签名验证。
- 依赖扩展 wheel 分别进行供应链扫描，主包保持最小攻击面。

## 21. 迁移与实施里程碑

里程碑不绑定虚假的小时估算，以退出条件作为完成依据。

### M0：包结构与 Resilience 合并

- [x] 确认统一 Sentinel 产品边界。
- [x] 确认核心不引入 stamina/aiolimiter。
- [x] 确认采用 Facade、责任链、State、Strategy、Adapter、Observer。
- [ ] 创建 atlas-richie-sentinel 主 wheel。
- [ ] 使用 git mv 迁入 Resilience 源码和测试。
- [ ] 删除 sentinel-primitives/core/rules 三个基础 wheel 骨架。
- [ ] 去除主包对 atlas-richie-contracts 的依赖。
- [ ] 更新所有内部消费者 import。
- [ ] 删除 components/resilience 及发布配置。
- [ ] 现有 67 个 Resilience 测试迁移后全部通过。
- [ ] 主 wheel 独立构建、安装和 public import 验证通过。

退出条件：仓库只有一份原语实现，不再存在 Resilience 产品或兼容 shim。

### M1：Engine、生命周期和指标内核

- [ ] 实现领域模型和异常体系。
- [ ] 实现 SentinelEngine、EntryLease、Slot/SlotLease、SlotChain。
- [ ] 实现原子回滚、取消和关闭语义。
- [ ] 实现环形 SlidingWindow、MetricRegistry、ResourceRegistry。
- [ ] 实现 RuleSnapshot、RuleRepository、ResourceSelector/RuleIndex。
- [ ] 完成 SEN-CORE、SEN-RULE、SEN-PERF 基线。

退出条件：无具体协议框架时，可通过公开 API 保护一个 async 业务资源。

### M2：五类规则

- [ ] FlowRule/FlowSlot，覆盖 direct/origin/associated/call-path。
- [ ] DegradeRule/DegradeSlot，并复用唯一 CircuitBreaker。
- [ ] ParamFlowRule/ParamFlowSlot 和基数治理。
- [ ] SystemRule/SystemSlot/SystemMetricSampler，覆盖 direct 和 adaptive capacity。
- [ ] AuthorityRule/AuthoritySlot。
- [ ] 完成所有规则边界、状态、并发和组合测试。

退出条件：五类规则均有稳定契约、确定性测试和组合行为证据。

### M3：File Source 与 ASGI

- [ ] 实现 RuleSource contract test kit。
- [ ] 实现 JSON/YAML File Source 和 last-known-good 热更新。
- [ ] 实现纯 ASGI Middleware。
- [ ] 实现资源命名、可信 origin 和参数提取 Strategy。
- [ ] 验证普通响应、流式响应、断连、取消、异常、lifespan。
- [ ] 完成真实多 worker 语义测试。

退出条件：任意 asyncio ASGI 应用无需依赖 FastAPI/Starlette 即可接入。

### M4：HTTPX 出站保护

- [ ] 实现 SentinelAsyncTransport。
- [ ] 实现全局和 per-origin 并发/排队保护。
- [ ] 包装响应流并在 EOF/aclose 释放。
- [ ] 实现 OutcomeClassifier。
- [ ] 与 Retry/CircuitBreaker 组合测试。
- [ ] 禁止任何 httpcore 私有 API 使用。

退出条件：受控真实下游服务上的正常、失败、超时、流式和取消场景通过。

### M5：Embedded Dashboard、文档和 1.0

- [ ] 实现 per-process embedded 管理 API。
- [ ] 默认 loopback/read-only，写操作认证授权审计。
- [ ] 完成中英文 Quick Start、规则手册、扩展开发和运维边界文档。
- [ ] 完成 Python/OS matrix、isolated wheel、性能和 soak 门禁。
- [ ] 完成 API review、CHANGELOG、迁移说明和 SBOM。
- [ ] 发布 1.0.0。

退出条件：主包和已实现扩展达到公开 API 稳定承诺，所有未验证边界明确列出。

### M6+：集群与聚合控制面

- [ ] Nacos Source。
- [ ] Redis 可恢复 Source。
- [ ] Token Server/Client。
- [ ] 双实例故障和恢复验收。
- [ ] Agent Reporting Protocol。
- [ ] 聚合 Dashboard 和 Web UI。
- [ ] WSGI/同步阻塞引擎可行性评估。

## 22. 版本与发布策略

- 0.x：API 可调整，但每次破坏性变化必须写 CHANGELOG。
- 1.0：主包本地保护能力稳定。
- 1.x：兼容地增加 Adapter、Source、Dashboard 和观测能力。
- 2.0：只有公开 API 或配置 schema 出现不可兼容变化时使用。

规则：

- 不再用 alpha/beta 版本号表示“某个基础 wheel 还没有内容”。
- 不发布空 wheel。
- 所有 wheel 在独立干净虚拟环境中安装验证。
- sdist 和 wheel 都必须构建、安装、import 和运行 smoke test。
- 公共符号集中在 atlas_richie.sentinel.__all__。
- 私有模块允许演进，公共 API 遵循语义化版本承诺。
- Atlas Richie Sentinel 的文档应明确它是独立项目，不冒充 Alibaba 官方实现。

## 23. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 自研状态机出现边界错误 | 显式状态表、ManualClock、属性/并发测试 |
| asyncio 取消导致许可泄漏 | EntryLease 统一所有权、故障注入、finally 逆序释放 |
| 动态资源/参数耗尽内存 | max cardinality、TTL、overflow policy、soak |
| 多 worker 用户误以为全局限流 | 配置和 Dashboard 明示 per-process，Cluster 才提供全局 |
| 规则热更新出现部分生效 | 不可变 RuleSnapshot、全量校验、原子交换、last-known-good |
| Dashboard 成为未授权控制面 | loopback/read-only 默认、认证授权、审计、负向测试 |
| HTTPX 升级破坏 Adapter | 只用公开 Transport API、版本 matrix、contract tests |
| 扩展依赖污染主包 | 每个扩展独立 wheel，主包零第三方依赖 |
| 与 Java 行为认知不一致 | 行为兼容矩阵、共享配置 fixture、明确不兼容边界 |
| 过早追求高 QPS 牺牲正确性 | 先建立行为契约，再以可重复 benchmark 优化 |

## 24. 1.0 Definition of Done

只有同时满足以下条件才可以发布 1.0：

- atlas-richie-resilience 已完全移除，仓库没有双份实现。
- 主包默认零第三方运行时依赖。
- 安装 atlas-richie-sentinel 即具备原语、Engine 和五类规则。
- ASGI、HTTPX、File Source、Embedded Dashboard 分别可独立裁剪。
- 所有公开字符串选项都有 Enum 或稳定值对象。
- Slot 回滚、取消、熔断迁移、热更新原子性有自动化证据。
- 所有状态和指标明确为 per-engine、per-process 或 cluster，没有模糊口径。
- Dashboard 默认安全，Authority 不信任客户端自报身份。
- 性能报告包含环境、p50/p95/p99、CPU、RSS 和长时间趋势。
- Python 3.12/3.13/3.14 的 wheel 构建、隔离安装和核心测试通过。
- 文档明确已实现、计划中、真实依赖已验收和未验收边界。
- 没有依赖 Java/Spring/FastAPI/Starlette 才能使用主包。

## 25. 决策记录

| ID | 决策 | 状态 |
|---|---|---|
| ADR-SEN-001 | Resilience 代码迁入 Sentinel，最终删除原产品 | Accepted |
| ADR-SEN-002 | primitives/core/rules 合并为 atlas-richie-sentinel 主 wheel | Accepted |
| ADR-SEN-003 | 主包不依赖 stamina、aiolimiter、atlas-richie-contracts | Accepted |
| ADR-SEN-004 | 1.0 使用 asyncio-first Engine，生命周期使用 async context manager | Accepted |
| ADR-SEN-005 | SlotChain 使用 Lease 记录进入状态并逆序释放 | Accepted |
| ADR-SEN-006 | 熔断器使用唯一 State Machine，DegradeSlot 不重复实现 | Accepted |
| ADR-SEN-007 | 规则源发布不可变全量快照，仓库原子替换 | Accepted |
| ADR-SEN-008 | ASGI Adapter 不依赖 Starlette 和 File Source | Accepted |
| ADR-SEN-009 | HTTPX 只保护可观测的请求并发，不读取 httpcore 私有池状态 | Accepted |
| ADR-SEN-010 | 1.0 Dashboard 是 embedded per-process 控制面 | Accepted |
| ADR-SEN-011 | Cluster 和聚合 Dashboard 在 1.0 后交付 | Accepted |
| ADR-SEN-012 | Java 对齐以行为契约和配置 codec 为边界 | Accepted |
| ADR-SEN-013 | 嵌套资源使用 contextvars 维护调用路径，并提供后台任务 detach | Accepted |
| ADR-SEN-014 | SystemRule 区分硬阈值与 Python-aware adaptive capacity | Accepted |
| ADR-SEN-015 | SystemRule 是 Engine 入口级规则，不伪装成 ResourceRule | Accepted |

后续实现如果需要改变 Accepted 决策，必须先更新本表、说明原因、迁移影响和验证计划，
不能在代码中静默偏离设计。

## 26. 规范与参考基线

实现和评审时优先参考协议或项目官方资料，不根据第三方文章猜测行为：

- Alibaba Sentinel 规则总览：https://sentinelguard.io/zh-cn/docs/basic-api-resource-rule.html
- Alibaba Sentinel 流量控制：https://sentinelguard.io/zh-cn/docs/flow-control.html
- Alibaba Sentinel 熔断降级：https://sentinelguard.io/zh-cn/docs/circuit-breaking.html
- Alibaba Sentinel 系统自适应保护：https://sentinelguard.io/zh-cn/docs/system-adaptive-protection.html
- Alibaba Sentinel 热点参数：https://sentinelguard.io/zh-cn/docs/parameter-flow-control.html
- ASGI specification：https://asgi.readthedocs.io/en/latest/specs/main.html
- HTTPX custom transports：https://www.python-httpx.org/advanced/transports/
- Python contextvars：https://docs.python.org/3/library/contextvars.html

参考资料用于核对行为、协议和边界，不授权复制其他项目的源码。任何“对齐”声明都必须有
本项目自己的契约测试和真实运行证据。
