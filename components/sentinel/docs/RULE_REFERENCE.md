# Atlas Richie Sentinel — Rule Reference

> 5 类规则(Flow / Degrade / System / ParamFlow / Authority)+
> `ResourceSelector` + `RuleVersion` 协议。**Sentinel Rule** 的
> Python 翻译,沿用 Java 仓 5 年迭代沉淀的语义。
>
> 5 rule families (Flow / Degrade / System / ParamFlow / Authority) +
> `ResourceSelector` + `RuleVersion` protocol. Python translation of
> Sentinel Rules, mirroring 5 years of Java implementation iteration.

---

## 1. 通用(Common)

### 1.1 `Resource`

```python
from atlas_richie.sentinel.model.resource import Resource

r = Resource("orders-api")          # 名称
r = Resource("orders-api", kind=ResourceKind.COMMON)
r = Resource("orders-api", traffic_type=TrafficType.INBOUND)
```

| 字段 | 类型 | 默认 | 说明 |
| ---- | ---- | ---- | ---- |
| `name` | `str` | 必填 | 资源名(全局唯一,通常 `<METHOD> <host><path>`) |
| `kind` | `ResourceKind` | `COMMON` | `COMMON` / `RPC` / `API_GATEWAY` / `DATASOURCE` |
| `traffic_type` | `TrafficType` | `INBOUND` | `INBOUND` / `OUTBOUND` |
| `attrs` | `frozenset[str]` | `frozenset()` | 自定义 attribute(Metric / log 用) |

`Resource` 是 **frozen dataclass + slots**,构造后不可变;**所有**
字段必填,可选字段用默认值。

### 1.2 `ResourceSelector`

```python
from atlas_richie.sentinel.rules.selector import ResourceSelector, SelectorKind

s_exact = ResourceSelector.exact("orders-api")            # 精确
s_prefix = ResourceSelector.prefix("orders-")             # 前缀
s_glob = ResourceSelector.glob("orders-*-v1")            # glob
```

| 工厂 | 匹配规则 | 例子 |
| ---- | -------- | ---- |
| `ResourceSelector.exact("foo")` | 完全等于 `"foo"` | `exact("orders")` 匹配 `"orders"`,不匹配 `"orders-v2"` |
| `ResourceSelector.prefix("foo-")` | `name.startswith("foo-")` | `prefix("orders-")` 匹配 `"orders-api"` |
| `ResourceSelector.glob("foo-*")` | `fnmatch` 风格 glob | `glob("orders-*-v1")` 匹配 `"orders-api-v1"` |

**优先级**(高 → 低,同 priority 时按 `rule_id` 字典序):`EXACT` >
`PREFIX` > `GLOB`。这是 RuleIndex 的**确定性顺序**约定,跟 Java
仓的 5 年迭代结果一致。

### 1.3 `RuleVersion` + `RuleSnapshot`

```python
from atlas_richie.sentinel.rules.snapshot import RuleVersion, RuleSnapshot

v = RuleVersion(
    epoch=1,                       # 同一 epoch 内可重复,跨 epoch 拒绝
    revision=2,                    # 同一 epoch 内的递增
    checksum=RuleVersion.compute_checksum({"rules": ...}),  # 64-char hex
)

snap = RuleSnapshot(
    version=v,
    rules={"r1": rule1, "r2": rule2},
    applied_at_ns=time.time_ns(),
    source_id="my-source",
)
```

`RuleVersion` 强制不变量:

- `epoch >= 0`, `revision >= 0`
- `checksum` 必须 64-char hex(SHA-256)
- 同一 (epoch, revision) 不同 checksum → 拒绝(碰撞检测)
- 旧版本(lexicographic compare)→ 拒绝 + last-known-good 保留

`RuleSnapshot.rules` 用 `MappingProxyType` 包装,**构造后不可变**。

### 1.4 `RuleRepository`

```python
from atlas_richie.sentinel.rules.repository import RuleRepository

repo = RuleRepository()
ok = repo.apply_snapshot(snap)            # True / False
repo.subscribe(my_callback)               # 收到 RuleSnapshotAppliedEvent
v = repo.last_version                     # 当前版本
idx = repo.current_index                   # 当前 RuleIndex
```

`apply_snapshot` 8 步流程(详见 PLANNING §M1.5):

1. 验证 version
2. 编译 RuleIndex(失败 → 拒绝,保留 last-known-good)
3. 替换 last_version
4. 替换 current_index
5. 触发订阅者事件
6. 记录 metrics
7. 清理 stale state
8. 返回 True / False

### 1.5 双 Port Source 契约 (M6.1.0b, 双轨)

M6.1 阶段规则源拆为**双 Port** (API delta v3 决策 3, 见
`R-SENTINEL-M6.1.0b-api-delta.md`):

```python
from atlas_richie.sentinel.source.rule_source import (
    RuleSource,           # 1.0 公共符号, 1.x 是 LegacyRuleSource 的 type alias
    LegacyRuleSource,     # 1.0 旧契约 Protocol (start/stop/latest)
    SnapshotRuleSource,   # 新契约 Protocol (snapshots/aclose + source_id)
    RuleSourceAssembly,   # 公开 immutable assembly DTO
    FileRuleSource,       # 1.0 实现, 1.x 仍为 LegacyRuleSource
)
from datetime import timedelta
```

**1.0 路径 (1.x 仍可用, 零代码改动)**:
```python
source = FileRuleSource(path="/etc/sentinel/rules.json", poll_interval_sec=5.0)
source.start(repository)  # 1.0 形态, 直连 repository, 不经 Supervisor
```

**1.x 新路径 (多源 + failover + 内部 activation fact)**:
```python
await engine.assemble_sources(
    [
        RuleSourceAssembly(
            source=NacosRuleSource(source_id="nacos-prod", ...),
            priority=100,
            failover_after=timedelta(seconds=5),
        ),
        RuleSourceAssembly(
            source=FileRuleSource(source_id="local-fallback", path=...),
            priority=10,
            failover_after=timedelta(seconds=2),
        ),
    ],
    repository=repository,
)
```

**双入口互斥**: `assemble_sources` 与 `install_legacy_source` 在同一 `SentinelEngine`
实例上互斥;违反抛 `SentinelConfigurationError("multimode_conflict")`。
详见 `MIGRATION-M6.md` §1.A / §1.B / §3。

**Repository 所有权 (P1 #2)**: `RuleRepository` **没有** `close()` /
`aclose()`; 关闭责任在 Supervisor + 各 Source, `SentinelEngine.aclose()` 等它们。
**default-deny (P1 #5)**: `repository=None` / `Optional[RuleRepository]` 拒绝
(default-deny 收窄 5 类: 所有权 / 权限 / 故障策略 / 资源上限 / 跨进程语义)。

**弃用时钟**: `RuleSource.start(stop/latest)` 形态弃用, 1.x 全程保留,
1.x 阶段**不**发 deprecation warning; 弃用版本 = 1.x 末 (≥ 2 minor 或 6 个月,
以较晚者为准), **不得早于 2.0 删除**且需未来 ADR。

**新 extension 写 `SnapshotRuleSource`**: 见 `EXTENSION_GUIDE.md` §3.3;
**禁止 shim 包装 1.0 旧 `RuleSource` 为 `SnapshotRuleSource`** (违反 1.0
行为锁定, 改变 `start(repository)` 直连路径)。

**生产级 `SnapshotRuleSource` 实现**: `sentinel-source-nacos` wheel
是 M6.1.1-1.6 落地的完整参考实现, 含:

- `NacosAuth` / `NacosTLS` (脱敏值对象)
- `NacosRuleSourceConfig` (frozen DTO, 必填字段, 5 类 default-deny)
- `NacosSourceState` (StrEnum) + `NacosSourceError` (StrEnum)
- `NacosRuleSource` (完整 lifecycle + 5 类错误分类 + 退避 + 幂等 aclose + 脱敏)

详见 `EXTENSION_GUIDE.md` §3.6。安装:

```bash
uv add atlas-richie-sentinel-source-nacos
```

---

## 2. FlowRule(限流)

```python
from atlas_richie.sentinel.rules.flow import (
    FlowRule, FlowGrade, FlowBehavior, FlowControl, FlowScope,
)
from atlas_richie.sentinel.rules.selector import ResourceSelector

rule = FlowRule(
    rule_id="orders-qps-5",
    resource_selector=ResourceSelector.exact("orders"),
    grade=FlowGrade.QPS,                        # QPS / CONCURRENCY
    threshold=5.0,                              # 阈值
    behavior=FlowBehavior.REJECT,               # REJECT / WARM_UP
    control=FlowControl.REJECT,                 # REJECT / WARM_UP / QUEUE
    scope=FlowScope.DIRECT,                     # DIRECT / ORIGIN / ASSOCIATED_RESOURCE / CALL_PATH
    max_queueing_time=None,                     # QUEUE 时必填
    scope_reference=None,                       # 非 DIRECT 时必填
)
```

| 字段 | 必填 | 说明 |
| ---- | ---- | ---- |
| `rule_id` | ✅ | 全局唯一 |
| `resource_selector` | ✅ | 命中规则的目标资源 |
| `grade` | ✅ | `QPS`(时间窗内请求数) / `CONCURRENCY`(瞬时并发) |
| `threshold` | ✅ | 阈值;QPS 单位 req/s,CONCURRENCY 单位 in-flight |
| `behavior` | ❌ | `REJECT` / `WARM_UP`(冷启动,CONCURRENCY 不支持) |
| `control` | ❌ | `REJECT` / `WARM_UP` / `QUEUE`(排队,`max_queueing_time` 必填) |
| `scope` | ❌ | `DIRECT`(默认) / `ORIGIN` / `ASSOCIATED_RESOURCE` / `CALL_PATH` |
| `max_queueing_time` | ❌ | `QUEUE` 控制必填,`timedelta` |
| `scope_reference` | ❌ | `ORIGIN` / `ASSOCIATED_RESOURCE` / `CALL_PATH` 必填 |

**触发异常**:`FlowBlocked`(`block_reason=BlockReason.FLOW`)。

---

## 3. DegradeRule(熔断降级)

```python
from atlas_richie.sentinel.rules.degrade import DegradeRule, DegradeStrategy

rule = DegradeRule(
    rule_id="downstream-cb",
    resource_selector=ResourceSelector.exact("downstream-api"),
    strategy=DegradeStrategy.ERROR_RATIO,       # 见下表
    threshold=0.5,                             # 阈值(按 strategy 解读)
    stat_interval_ms=10_000,                   # 统计窗口
    min_request_amount=10,                     # 触发熔断的最小请求数
    retry_timeout_ms=5_000,                    # 熔断 → 半开 的等待时间
)
```

| Strategy | 阈值含义 | 触发条件 |
| -------- | -------- | -------- |
| `ERROR_RATIO` | 错误率 0~1 | `(error / total) > threshold` |
| `ERROR_COUNT` | 错误次数 | `error > threshold` |
| `SLOW_REQUEST_RATIO` | 慢调用率 0~1 | `(slow / total) > threshold` + `max_rt` 判定慢 |

**触发异常**:`CircuitBlocked`(`block_reason=BlockReason.CIRCUIT_OPEN`)。

**`max_rt`** 字段:仅 `SLOW_REQUEST_RATIO` 使用,单位 ms,慢调用的判
断阈值。

**`force_reset()` / `get_breaker_state()`**:DegradeSlot 暴露的状态
查询 API(M2.2 设计,不开 `force_open` / `force_close`,因为 M0 的
CircuitBreaker 状态机不支持)。

---

## 4. SystemRule(系统保护)

```python
from atlas_richie.sentinel.rules.system import SystemRule, SystemMetric

rule = SystemRule(
    rule_id="sys-cpu-80",
    metric=SystemMetric.CPU_USAGE,             # CPU_USAGE / LOAD / INBOUND_QPS / CONCURRENCY / AVG_RT
    threshold=0.8,                             # 0~1 比例
)
```

| Metric | 阈值含义 | 适配系统 |
| ------ | -------- | -------- |
| `CPU_USAGE` | CPU 占用率 0~1 | macOS / Linux (`/proc/stat` / `psutil.cpu_percent()`) |
| `LOAD` | 1-min load average / CPU 核数 | Linux |
| `INBOUND_QPS` | 全局入口 QPS | 任意 |
| `CONCURRENCY` | 全局并发 in-flight | 任意 |
| `AVG_RT` | 全局平均 RT(ms) | 任意 |

`SystemSlot` 接收 `system_rules: list[SystemRule]`(不通过
`RuleIndex`,因为 SystemRule 不需要 selector)。

**触发异常**:`SystemBlocked`(`block_reason=BlockReason.SYSTEM`)。

---

## 5. ParamFlowRule(热点参数限流)

```python
from atlas_richie.sentinel.rules.param_flow import ParamFlowRule, ParamFlowGrade

rule = ParamFlowRule(
    rule_id="param-user-qps",
    resource_selector=ResourceSelector.exact("orders"),
    grade=ParamFlowGrade.QPS,                   # QPS / CONCURRENCY
    threshold=10.0,
    param_keys=("user_id",),                   # 热点参数
    default_value="anonymous",
)
```

应用入口需要传参:

```python
async with engine.entry(
    Resource("orders"),
    args=InvocationArguments(args={"user_id": "u-123"}),
):
    ...
```

`ParamFlowSlot` 会按 `param_keys` 提取值,按 `default_value` 兜底,
按 `(resource, param_value)` 维度限流。

**触发异常**:`ParamFlowBlocked`(`block_reason=BlockReason.PARAM_FLOW`)。

---

## 6. AuthorityRule(黑白名单)

```python
from atlas_richie.sentinel.rules.authority import AuthorityRule, AuthorityStrategy

rule = AuthorityRule(
    rule_id="blacklist-bad-ips",
    resource_selector=ResourceSelector.exact("orders"),
    strategy=AuthorityStrategy.BLACK,           # WHITE / BLACK
    items={"10.0.0.5", "10.0.0.6"},
)
```

应用入口需要在 `context.extra` 提供 `origin`:

```python
async with engine.entry(
    Resource("orders"),
    context=SentinelContext(extra={"origin": "10.0.0.5"}),
):
    ...
```

`AuthoritySlot` 提取 `extra["origin"]`,对照黑 / 白名单决策。

**触发异常**:`AuthorityDenied`(`block_reason=BlockReason.AUTHORITY`)。

---

## 7. Rule 触发的异常总览(中文)

| 规则 | 异常类 | block_reason |
| ---- | ------ | ------------ |
| FlowRule | `FlowBlocked` | `FLOW` |
| DegradeRule | `CircuitBlocked` | `CIRCUIT_OPEN` |
| SystemRule | `SystemBlocked` | `SYSTEM` |
| ParamFlowRule | `ParamFlowBlocked` | `PARAM_FLOW` |
| AuthorityRule | `AuthorityDenied` | `AUTHORITY` |

5 个 `SentinelBlockedError` 子类**互不为子类**(单继承,平级),都
继承 `SentinelBlockedError(SentinelError)`。`except
SentinelBlockedError:` 统一捕获;`except FlowBlocked:` 单独捕获。

`RetryPolicy(retriable_exceptions=(...,))` 默认把 `Exception` 全部
视作可重试;**不**包含 `SentinelBlockedError`(M0 锁定:主动拒绝
不应被重试,会被快速失败 + 用户感知)。

---

## 8. 1.0 vs 1.x(中文)

| 规则 | 1.0 状态 | 1.x 计划 |
| ---- | -------- | -------- |
| FlowRule | ✅ | 增 QUEUE 限流精度 |
| DegradeRule | ✅ | 增 SLOW_REQUEST_RATIO + 滑动窗口精度 |
| SystemRule | ✅ | 增 `psutil` 精确值 |
| ParamFlowRule | ✅ | 增 top-N 热点统计 |
| AuthorityRule | ✅ | 增动态配置源(Nacos / 经 ADR 批准的持久化 Source) |

### 8.1 1.0 → 1.x Source 路径 (M6.1.0b 双 Port)

| 维度 | 1.0 (1.x 仍可用, 零代码改动) | 1.x 新路径 (M6.1.0b) |
| ---- | ---------------------------- | -------------------- |
| Protocol | `RuleSource` (= `LegacyRuleSource` alias) | `SnapshotRuleSource` (新契约) |
| 方法 | `start(repository)` / `stop()` / `latest()` | `snapshots() -> AsyncIterator[RuleSnapshot]` / `aclose()` |
| 引擎入口 | `source.start(repository)` 直连 | `await engine.assemble_sources([RuleSourceAssembly(...)], repository=...)` |
| 多源 / failover | ❌ | ✅ Supervisor 仲裁 priority / failover_after |
| 内部 fact | ❌ | ✅ `RuleSourceActivation` (C 层私有, observer 异常隔离) |
| 跨语言 wire | n/a | 推迟到 M6.5.7 envelope |
| 1.0 行为锁定 | ✅ | 1.x 全程保留 `RuleSource` alias + `FileRuleSource` 公共 API |
| 弃用时钟 | n/a | ≥ 2 minor 或 6 个月 (以较晚者为准), 不得早于 2.0, 需未来 ADR |
| Deprecation warning | n/a | 1.x 阶段**不**发 (避免 1.0 用户 noise) |
| 互斥约束 | n/a | `multimode_conflict` 防止 1.0 路径绕过 Supervisor |

详见 `MIGRATION-M6.md` (三类用户迁移路径 + 不可自动迁移场景 + 验证清单)。

---

## 9. 引用 / References

- Java Sentinel 5 年迭代:`atlas-richie-component/atlas-richie-cache`
  (Cache 包结构,Rule / Slot 设计同源)
- PLANNING §M2.1-2.7
- DESIGN §M2 + §M3
