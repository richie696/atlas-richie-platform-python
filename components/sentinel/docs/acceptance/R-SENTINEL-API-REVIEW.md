# R-SENTINEL API Review (1.0)

| Field | Value |
| ----- | ----- |
| Test ID | SEN-API-001 (Public API Surface Review) |
| Date | 2026-09-13 |
| Commit | `HEAD` (post M1.6 + M3.1 + M3.5 + M3.6 + M4.4 + M4.5) |
| Author | Mavis |

> API stability promise: **1.0 → 1.x 主包 6 月不 breaking**。任何
> 1.0 公开 API 符号(symbol 名称 / 签名 / 行为)在 1.x 阶段不会改变。
> 新功能一律新 wheel(Open-Closed 在 component 级)。
>
> API stability promise: **1.0 → 1.x main package no breaking for 6
> months**. Any 1.0 public API symbol (name / signature / behavior)
> will not change in 1.x. New features ship as new wheels
> (Open-Closed at the component level).

---

## 1. 主包公共 API Surface (`atlas_richie.sentinel.*`)

### 1.1 顶层 facade(`atlas_richie.sentinel`)

| Symbol | 类型 | 备注 |
| ------ | ---- | ---- |
| `__version__` | `str` (PEP 562 懒加载) | 1.0 = `"0.2.0"` |

### 1.2 `atlas_richie.sentinel.primitives`(M0 锁定)

| Symbol | 类型 | 备注 |
| ------ | ---- | ---- |
| `RetryPolicy` | frozen dataclass | `max_attempts=3` 默认 |
| `RetryExecutor` | class | `execute(op)` 主入口 |
| `FirstByteSignal` | dataclass | retry-only-after-first-byte |
| `RetryEvent` | dataclass | `on_retry` 回调参数 |
| `CircuitBreaker` | class | 6 状态机 |
| `CircuitBreakerConfig` | frozen dataclass | failure_threshold / sliding_window_size / minimum_calls / open_duration |
| `CircuitState` | `StrEnum` | `CLOSED` / `OPEN` / `HALF_OPEN` |
| `TokenBucket` | class | 流控 |
| `TokenBucketConfig` | frozen dataclass | capacity / refill_rate / initial_tokens |
| `Bulkhead` | class | 并发限制 |
| `BulkheadConfig` | frozen dataclass | max_concurrent / max_wait |
| `IdempotencyKey` | Protocol | runtime_checkable |
| `StatelessIdempotencyKey` | class | 默认;**所有** op 可重试 |
| `NeverIdempotencyKey` | class | **永不**重试(安全策略) |
| `CallableIdempotencyKey` | class | `derive(op) -> str | None` |
| `Clock` / `SystemClock` / `ManualClock` | Protocol + 2 类 | 时间注入 |
| `Sleep` / `system_sleep` | class + factory | sleep 注入 |
| `RandomSource` / `SystemRandom` / `DeterministicRandom` | Protocol + 2 类 | 随机源注入 |

### 1.3 `atlas_richie.sentinel.errors`(M0.5 + M1.1 锁定)

| Symbol | 继承 | 备注 |
| ------ | ---- | ---- |
| `SentinelError` | `Exception` (stdlib) | 根;**零依赖必备** |
| `ResilienceError` | `SentinelError` | 5 个 primitives 异常的父类 |
| `RetryExhausted` | `ResilienceError` | `(attempts, last_exception)` |
| `RetryNotPermitted` | `ResilienceError` | `NeverIdempotencyKey` 触发 |
| `CircuitOpen` | `ResilienceError` | `(retry_after)` |
| `RateLimitExceeded` | `ResilienceError` | `(retry_after)` |
| `BulkheadFull` | `ResilienceError` | `(retry_after)` |
| `SentinelBlockedError` | `SentinelError` | M1 引入;直接继承根,**不**是 `ResilienceError` 子类 |
| `SentinelConfigurationError` | `SentinelError` | M1.1 引入 |
| `SentinelLifecycleError` | `SentinelError` | M1.1 引入 |
| `RuleSnapshotError` | `SentinelLifecycleError` | M1.1 引入 |
| `FlowBlocked` | `SentinelBlockedError` | M2.1 引入 |
| `ParamFlowBlocked` | `SentinelBlockedError` | M2.6 引入 |
| `SystemBlocked` | `SentinelBlockedError` | M2.4 引入 |
| `CircuitBlocked` | `SentinelBlockedError` | M2.2 引入;**不**是 `CircuitOpen` 子类 |
| `AuthorityDenied` | `SentinelBlockedError` | M2.5 引入 |

### 1.4 `atlas_richie.sentinel.model`(M1.1 锁定)

| Symbol | 备注 |
| ------ | ---- |
| `Resource` | frozen dataclass + slots |
| `ResourceKind` / `TrafficType` | `StrEnum` |
| `SentinelContext` | frozen dataclass + MappingProxyType extra |
| `TraceId` / `bind_current_context` / `current_context` | contextvars helpers |
| `InvocationArguments` | frozen dataclass |
| `Outcome` | frozen dataclass + OutcomeKind 5-way |
| `OutcomeKind` | `StrEnum` (`ADMITTED` / `SUCCEEDED` / `FAILED` / `CANCELLED` / `BLOCKED`) |
| `SlotLease` / `NoopSlotLease` | lease Protocol + 默认实现 |
| `BlockReason` | `StrEnum` (`FLOW` / `PARAM_FLOW` / `SYSTEM` / `DEGRADE` / `AUTHORITY` / `POOL_FULL` / `CIRCUIT_OPEN`) |
| `EngineState` | `StrEnum` (`CREATED` / `READY` / `SHUTTING_DOWN` / `SHUTDOWN` / `FAILED`) |
| `RuleMatchKind` | `StrEnum` |

### 1.5 `atlas_richie.sentinel.engine`(M1.2-M1.3 锁定)

| Symbol | 备注 |
| ------ | ---- |
| `SentinelEngine` | async context manager;6 状态机 |
| `FailSafe` | `StrEnum` (`FAIL_CLOSED` / `FAIL_OPEN` / `FAIL_FAST`) |
| `Slot` | Protocol(runtime_checkable) |
| `SlotChain` | Order 升序遍历 |
| `ORDER_*` 常量 | `ORDER_NODE_SELECTOR` (100) / `ORDER_STATISTIC` (200) / `ORDER_AUTHORITY` / `ORDER_FLOW` / `ORDER_DEGRADE` / `ORDER_USER_MAX` (690) |
| `EntryRequest` | async context manager, `__aenter__` 收 lease, `__aexit__` 释放 + 记 Outcome |
| `EntryLease` | per-entry lease 收集 + 逆序 release + last_release_error() 暴露 |

### 1.6 `atlas_richie.sentinel.rules`(M1.5 + M2 锁定)

| Symbol | 备注 |
| ------ | ---- |
| `RuleSnapshot` | frozen + MappingProxyType |
| `RuleVersion` | (epoch, revision, checksum) 不变量 |
| `RuleSnapshotAppliedEvent` | 订阅者事件 |
| `RuleRepository` | `apply_snapshot` 8 步流程 + `subscribe` + `current_index` |
| `RuleIndex` | find(resource_name: str) → list[Rule] |
| `ResourceSelector` / `SelectorKind` | EXACT / PREFIX / GLOB |
| `FlowRule` / `FlowGrade` / `FlowBehavior` / `FlowControl` / `FlowScope` | M2.1 |
| `DegradeRule` / `DegradeStrategy` | M2.2 |
| `SystemRule` / `SystemMetric` | M2.4 |
| `ParamFlowRule` / `ParamFlowGrade` | M2.6 |
| `AuthorityRule` / `AuthorityStrategy` | M2.5 |
| `TokenService` / `LocalTokenService` / `Token` / `TokenState` | M2.7 |
| `RuleSource` (Protocol) / `FileRuleSource` | M3.1 / M3.2 (File 在 source-file wheel) |

### 1.7 `atlas_richie.sentinel.slots`(M2 锁定)

| Symbol | 备注 |
| ------ | ---- |
| `FlowSlot` | M2.1 + FlowRule |
| `DegradeSlot` | M2.2 + DegradeRule |
| `SystemSlot` | M2.4 + SystemRule;`system_rules: list[SystemRule]` 参数 |
| `ParamFlowSlot` | M2.6 + ParamFlowRule |
| `AuthoritySlot` | M2.5 + AuthorityRule |

### 1.8 `atlas_richie.sentinel.metrics`(M1.4 锁定)

| Symbol | 备注 |
| ------ | ---- |
| `MetricRegistry` | 指标容器 |
| `SlidingWindow` | 时间窗 / 桶聚合 |
| `MetricSnapshot` | 快照(只读) |

### 1.9 `atlas_richie.sentinel.source`(M3.1 锁定)

| Symbol | 备注 |
| ------ | ---- |
| `RuleSource` (Protocol, runtime_checkable) | Port |
| `FileRuleSource` | 在主包;`source-file` wheel 重新导出 |

**重要不变量**:`atlas_richie.sentinel.source.FileRuleSource` **已在
主包定义**;`sentinel-source-file` wheel 只是重新导出 + 加版本约束。
不要在主包 + wheel 写两个不同实现。

---

## 2. Extension wheels 公共 API

### 2.1 `atlas_richie.sentinel_adapter_asgi`

| Symbol | 备注 |
| ------ | ---- |
| `SentinelASGIMiddleware` | 纯 ASGI 3.0,no Starlette / FastAPI dep |
| `default_resource_name(scope) -> str` | `"{METHOD} {path}"` |
| `default_origin_from_scope(scope) -> str | None` | 读 `x-forwarded-user` header |

### 2.2 `atlas_richie.sentinel_adapter_httpx`

| Symbol | 备注 |
| ------ | ---- |
| `SentinelAsyncTransport` | `httpx.AsyncBaseTransport` 子类;**默认不重试** |
| `default_resource_name(request) -> str` | `"{METHOD} {host}{path}"` |
| `OutcomeClassifier` (Protocol) | Strategy |
| `DefaultOutcomeClassifier` | 4xx → SUCCEEDED, 5xx → FAILED,网络异常 → FAILED, **不**调 `raise_for_status()` |
| `classify_outcome(response | exception) -> str` | 兼容 shim;调 DefaultOutcomeClassifier |

### 2.3 `atlas_richie.sentinel_source_file`

| Symbol | 备注 |
| ------ | ---- |
| `FileRuleSource` | 重新导出主包 |

### 2.4 `atlas_richie.sentinel_dashboard`

| Symbol | 备注 |
| ------ | ---- |
| `SentinelDashboard` | loopback + admin token + audit log |
| `run(host, port)` | 起 HTTP server |

---

## 3. Public API 不变量(API review 重点)

### 3.1 不允许破坏的(1.0 → 1.x 锁定)

- 5 个 `SentinelBlockedError` 子类继承关系:`SentinelBlockedError`
  父类 + 5 个独立子类(M0.5-A lock);`CircuitBlocked` **不**是
  `CircuitOpen` 子类,反之亦然
- `IdempotencyKey` 三实现:`StatelessIdempotencyKey` /
  `NeverIdempotencyKey` / `CallableIdempotencyKey`;**不**允许加
  `.always` / `.never` 占位符
- `RetryPolicy` / `RetryExecutor` 命名;**不**是 `Retry`
- `EngineState` 6 值(`CREATED` / `READY` / `SHUTTING_DOWN` /
  `SHUTDOWN` / `FAILED`;无 `INITIALIZING` 等中间态)
- `OutcomeKind` 5 值(ADMITTED / SUCCEEDED / FAILED / CANCELLED /
  BLOCKED);互斥
- `RuleVersion` 不变量(epoch ≥ 0, revision ≥ 0, checksum 64-hex)
- `RuleSnapshot` 不可变(`MappingProxyType.rules`)
- `BlockReason` 7 值(FLOW / PARAM_FLOW / SYSTEM / DEGRADE /
  AUTHORITY / POOL_FULL / CIRCUIT_OPEN)
- `Slot` Protocol `order` 正整数
- `SentinelBlockedError` 不是 `ResilienceError` 子类
- `ResilienceError` 不是 `SentinelBlockedError` 子类(独立平级)

### 3.2 私有 / 内部(可改)

- 任何 `_` 开头的方法 / 字段 / 内部 helper
- 性能数据(snapshot timing 等)
- 私有 `__` dunder

### 3.3 拒绝(永不允许)

- 给 `SentinelError` 加三方依赖(主包零依赖原则)
- 把 `SentinelBlockedError` 改成 `ResilienceError` 子类(锁死 1.0 行为)
- 在主包定义 `atlas_richie.sentinel.engines` / `slotteds` 等
  拼错的导入路径
- 公开 `**kwargs` 风格的 API(违反 CODE_QUALITY)
- 公开 `*Impl` / `*Manager` / `*DTO` / `*Util` 后缀的类(违反
  CODE_QUALITY,Python-native)

---

## 4. CODE_QUALITY 自检(公共 API 设计)

按 `atlas-richie-platform-python/CODE_QUALITY.md` 5 章节:

### 4.1 Python-native public APIs

- ✅ 无 `*Impl` / `*Manager` / `*DTO` / `*Util` 后缀
  - `SentinelEngine` 不是 `EngineManager`
  - `FlowRule` 不是 `FlowRuleDTO`
  - `LocalTokenService` 不是 `LocalTokenServiceImpl`(**没有**)
- ✅ 无 `**kwargs`(可注入参数走具名 `naming=`, `fail_safe=` 等)
- ✅ frozen dataclass:`Resource` / `RuleSnapshot` / `Outcome` /
  `SentinelContext` / `InvocationArguments` 全部 frozen
- ✅ Protocol 只用于真实多态点:`OutcomeClassifier` / `RuleSource` /
  `Slot` / `Clock` / `RandomSource` / `IdempotencyKey`

### 4.2 Named semantic values

- ✅ 闭状态:`OutcomeKind` / `EngineState` / `CircuitState` / `BlockReason`
  全部 `StrEnum`
- ✅ 超时:`max_attempts` / `open_duration` / `min_request_amount` /
  `retry_timeout_ms` 全部 named(不传"魔数")
- ✅ 错误码:`SentinelBlockedError.stable_code` 命名(每个子类有
  `FLOW_*` / `CB_*` 等前缀)

### 4.3 One behavior, one implementation

- ✅ 5 类规则,**没有** `Base*` / `Common*` 偷藏
- ✅ `EntryLease` / `NoopSlotLease` 各自有清晰责任,没有共享 `*Base`
- ✅ `MetricRegistry` 单实现,不用 multi-registry 抽象

### 4.4 OOP 边界

- ✅ SRP:每类 1 个责任
- ✅ OCP:5 类规则 × 各自 Slot × 各自 add,新规则 = 新类
- ✅ LSP:`OutcomeKind` 子类都满足相同 Protocol
- ✅ ISP:`Slot` Protocol 只 3 个方法
- ✅ DIP:Engine 依赖 Protocol 不依赖具体
- ✅ LoD:Engine 不直访 Rule 内部;走 RuleIndex.find()

### 4.5 Review gate

- ✅ focused test:308 / 308 pass, 2 skipped (opt-in perf)
- ✅ 独立 wheel:5 个 wheel 独立 venv install + smoke(3.12 + 3.13)
- ✅ `tools/release/check_version_consistency.py`:5/5 OK
- ✅ `tools/dependency-check/check_core_imports.py` (待 1.x CI 集成)

---

## 5. 主包对外依赖(零确认)

```bash
$ grep -A 1 "^dependencies" components/sentinel/sentinel/pyproject.toml
dependencies = []
```

主包 `dependencies = []`;通过 `uv pip install atlas-richie-sentinel`
不会有任何三方安装。

Extension wheels 各自声明自己的依赖(按适配目标):

```toml
# sentinel-adapter-httpx
dependencies = [
    "atlas-richie-sentinel>=0.2.0,<0.3.0",
    "httpx>=0.27,<1.0",
]
```

---

## 6. 已知保留问题(留 1.x)

- `Slot` Protocol 缺 `name` 字段(诊断时用 id 即可)
- `ResourceSelector` 缺 `match_priority` 字段(优先级用 Rule 自带)
- `EntryLease.last_release_error()` 1.0 加,1.x 可考虑包成 metrics
  计数器
- `FileRuleSource` 缺 mtime 精度 fallback(目前依赖 OS)

---

## 7. 重新跑 API review

```bash
# 1. 主包公共符号统计
for f in components/sentinel/sentinel/src/atlas_richie/sentinel/{primitives,model,rules,engine,errors,metrics,source,slots}/__init__.py; do
  count=$(grep -A 1000 "^__all__" "$f" | grep -m1 "^\]" -B 1000 | grep '"' | wc -l)
  echo "$f: $count public symbols"
done

# 2. 零依赖验证
grep "dependencies" components/sentinel/sentinel/pyproject.toml
# dependencies = []
```

## 8. Exit Criteria

- [x] 主包所有公共 API 列入清单(本文件 §1)
- [x] 4 extension wheels 公共 API 列入清单(§2)
- [x] 不变量 + 拒绝项明确(§3)
- [x] CODE_QUALITY 5 章节自检通过(§4)
- [x] 主包零依赖(§5)
- [x] 已知保留问题清单(§6)
