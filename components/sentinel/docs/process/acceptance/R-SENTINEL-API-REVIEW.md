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

### 1.5 `atlas_richie.sentinel.engine`(M1.2-M1.3 + **M6.1.0b** 锁定)

| Symbol | 备注 |
| ------ | ---- |
| `SentinelEngine` | async context manager;6 状态机 |
| `SentinelEngine.assemble_sources(assemblies, *, repository)` | **M6.1.0b 新增**;多源仲裁入口, 仅接受 `SnapshotRuleSource`; 互斥 `install_legacy_source`; default-deny `repository=None` |
| `SentinelEngine.install_legacy_source(source, *, repository)` | **M6.1.0b 新增**;1.0 兼容入口, 仅接受 `LegacyRuleSource`; 互斥 `assemble_sources` |
| `SentinelEngine.aclose()` | **M6.1.0b 行为扩展**;等 Supervisor 关闭所有 Source 任务; **不**关闭 Repository (被动容器) |
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

### 1.9 `atlas_richie.sentinel.source`(M3.1 + **M6.1.0b** 锁定)

| Symbol | 备注 |
| ------ | ---- |
| `RuleSource` (Protocol, runtime_checkable) | **M6.1.0b** type alias of `LegacyRuleSource`;1.0 公共符号保留, 1.x 全程**不**发 deprecation warning |
| `LegacyRuleSource` (Protocol, runtime_checkable) | **M6.1.0b 新增**;1.0 旧契约 (start/stop/latest); `RuleSource` 的 canonical 名 |
| `SnapshotRuleSource` (Protocol) | **M6.1.0b 新增**;新契约 (`snapshots() -> AsyncIterator[RuleSnapshot]` + `aclose()` + `source_id: str`); `assemble_sources` 仅接受本类型 |
| `RuleSourceAssembly` (frozen dataclass) | **M6.1.0b 新增**;公开 immutable assembly DTO; `__post_init__` 校验 priority≥0 / failover_after≥0 |
| `FileRuleSource` | 在主包;`source-file` wheel 重新导出;**M6.1.0b** 改写为 `LegacyRuleSource` 实现, 公共 API (start/stop/latest) 不变 |

**重要不变量**:`atlas_richie.sentinel.source.FileRuleSource` **已在
主包定义**;`sentinel-source-file` wheel 只是重新导出 + 加版本约束。
不要在主包 + wheel 写两个不同实现。

**M6.1.0b 双 Port 不变量**:

- `RuleSource` 与 `LegacyRuleSource` 是 type alias (同一对象), `RuleSource is LegacyRuleSource` 必须为 `True`
- `SnapshotRuleSource.source_id` 是非空 `str` (extension 显式声明; activation fact 用它)
- `LegacyRuleSource` 不出现在 `assemble_sources` 类型签名; `SnapshotRuleSource` 不出现在 `install_legacy_source` 类型签名
- 双入口互斥 `multimode_conflict`: 同 `SentinelEngine` 实例上 `assemble_sources` 与 `install_legacy_source` 互斥, 违反抛 `SentinelConfigurationError("multimode_conflict")`

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
- **`RuleSource` 是 `LegacyRuleSource` type alias** (M6.1.0b lock):
  `RuleSource is LegacyRuleSource` 必须为 `True`; 1.0 公共符号 1.x 全程
  保留, **不**发出 deprecation warning, 弃用时钟 ≥ 2 minor 或 6 个月
  (以较晚者为准), 不得早于 2.0 删除且需未来 ADR
- **`FileRuleSource` 公共 API** (M6.1.0b lock): start/stop/latest 三个
  公开方法签名 1.x 全程保留; 内部实现可改写为 `LegacyRuleSource` 形态,
  但行为不能变 (1.0 锁定承诺)
- **`RuleRepository` 被动容器** (M6.1.0b P1 #2 lock): **不**允许加
  `close()` / `aclose()` 方法; 关闭责任在 Supervisor + 各 Source;
  **不**允许把"用户负责关闭 Repository" 当作承诺
- **双入口互斥 `multimode_conflict`** (M6.1.0b lock): 同 `SentinelEngine`
  实例上 `assemble_sources` 与 `install_legacy_source` 互斥, 违反抛
  `SentinelConfigurationError("multimode_conflict")`
- **default-deny 收窄 5 类** (M6.1.0b P1 #5 lock): 影响 (1) 所有权
  (2) 权限 (3) 故障策略 (4) 资源上限 (5) 跨进程语义 的 optional 参数
  必须 ADR; 普通 timeout/分页/retry 走常规 API review

### 3.2 私有 / 内部(可改)

- 任何 `_` 开头的方法 / 字段 / 内部 helper
- 性能数据(snapshot timing 等)
- 私有 `__` dunder
- **`source._supervisor.RuleSourceSupervisor`** (M6.1.0b 私有): 多源
  仲裁, 选 active, fail-over; **不**进 `atlas_richie.sentinel.__all__`,
  extension 不可 import
- **`source._supervisor._RuleSourceBinding`** (M6.1.0b 私有): frozen
  dataclass (source_id / source / priority / failover_after); C 层
  私有, 公开 `RuleSourceAssembly` 是其 DTO 形态
- **`source._supervisor.activation.RuleSourceActivation`** (M6.1.0b
  私有): frozen dataclass (4 字段, **不**含时间戳 — M6.5.7 envelope 提供
  captured_at + received_at); C 层冻结内部 fact, 跨语言 wire 推迟
- **`source._supervisor.observer._RuleSourceActivationBus`** (M6.1.0b
  私有): 同进程 pub-sub; observer 异常隔离 (主链路不能被观测逻辑拖垮)
- **`source._supervisor.observer.ActivationObserver`** (M6.1.0b 私有但
  进 `_supervisor.__all__`): observer 协议, C 层内部测试可用, **extension
  不可订阅**; 用于主包内部 observer hook (同进程 only), 跨进程订阅
  由 M6.5.7 envelope 冻结

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

---

## 9. M6.1.0b delta 引用 (API delta v3 5 owner 签字)

M6.1.0b 是 1.0 → 1.x 第一批 API delta, 5 owner 已签字 (`maintainer` /
`B 契约` / `C 实现` / `测试` / `文档`)。权威文档:

- **`docs/R-SENTINEL-M6.1.0b-api-delta.md` v3** (22KB, 5 decision, 5 owner 签字栏)
- **`docs/rule_source_activation.md` v3** (C 层 `RuleSourceActivation` fact 完整 spec)
- **`docs/MIGRATION-M6.md`** (三类用户迁移路径 + 互斥约束 + Repository 所有权)
- **`docs/process/PLANNING.md` §M6.1.0 / §M6.1.0a / §M6.5.7**
- **`docs/DESIGN.md` §10.3 L1040-1089** (Supervisor 设计) / §13.3.1 (Agent Reporting 边界)

### 9.1 5 项决策摘要

1. **公开 / 私有 API 二元边界** (§1.5 / §1.9 / §3.2): `RuleSource` alias +
   `LegacyRuleSource` + `SnapshotRuleSource` + `RuleSourceAssembly` +
   `FileRuleSource` 公开; `_supervisor.*` 全 C 层私有, 不进 `__all__`,
   extension 不可 import
2. **`RuleRepository` 被动容器** (§3.1): 无 `close()` / `aclose()`; 关闭责任
   在 Supervisor + 各 Source, `SentinelEngine.aclose()` 等它们
3. **双 Port 不 shim** (§1.9 / §3.1): `LegacyRuleSource` (1.0 start/stop/latest)
   + `SnapshotRuleSource` (新 snapshots/aclose) 完全独立
4. **内部 fact `RuleSourceActivation`** (§3.2 / §1.9): frozen dataclass 4 字段
   (previous_source_id / source_id / version / reason), **不**含时间戳
   (M6.5.7 envelope 提供 captured_at + received_at); 跨语言 wire 推迟
5. **default-deny 收窄 5 类** (§3.1): 影响所有权 / 权限 / 故障策略 /
   资源上限 / 跨进程语义 的 optional 参数必须 ADR

### 9.2 M6.1.0d-1 实施扩展 (worker 报告确认)

worker 实施 d-1 时根据 `rule_source_activation.md` §7 添加了 1 个
**API delta 之外** 的 Protocol 字段, 需要在后续 ADR 中正式批准:

- **`SnapshotRuleSource.source_id: str`** (M6.1.0d-1 实施扩展):
  非空稳定字符串, extension 显式声明 (e.g. `"nacos-prod"`); Supervisor
  把它写入 `_RuleSourceBinding.source_id` 并出现在 `RuleSourceActivation`
  fact 的 `previous_source_id` / `source_id` 字段 (理由: activation fact
  需要稳定 source_id 标识, 避免 operator observability 失真; 不可由
  endpoint / path / token 自动构造, 保证 user intent)
- **API delta v3 §3.1 后续需补 1 段**: `SnapshotRuleSource.source_id`
  是非空 `str` 字段, 不允许 `""` / `None`; 详细理由见
  `rule_source_activation.md` §7

### 9.3 双 Port contract test 覆盖 (M6.1.0d-1)

| 测试文件 | 用例数 | 覆盖 |
| -------- | ------ | ---- |
| `tests/test_sen_rule_source.py` (既有 + 扩展) | 47 (26 Legacy + 21 Snapshot) | 双 Port 契约; 既有 1.0 行为锁定 + 新增 SnapshotRuleSource 契约 |
| `tests/test_sen_legacy_source_compat.py` | 9 | 1.0 alias + `FileRuleSource` 行为锁定 + Legacy 路径不发 activation |
| `tests/test_sen_supervisor_internal.py` | 17 | C 层 Supervisor 单元测试 (priority / failover / 3 条件 AND emit / aclose 幂等) |
| `tests/test_sen_rule_source_activation.py` | 11 | C 层 activation fact 契约 (3 条件 AND + observer 异常隔离 + 无时间戳) |
| `tests/test_sen_assemble_sources.py` | 14 | 公开装配入口契约 (lifecycle gate + multimode_conflict 双向 + duplicate_priority + repository_required) |

**总测试数**: M6.1.0d-1 实施后 sentinel 主包 **243 passed + 3 skipped** (基线 172 + 2; 新增 71 个测试; +1 skip 来自新 SnapshotRuleSource 在 yaml 路径跳过)。
