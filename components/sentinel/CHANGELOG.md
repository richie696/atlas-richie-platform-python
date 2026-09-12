# Changelog

All notable changes to Atlas Richie Sentinel are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-09-13 — M0-M5 完整闭环 / 1.0 release baseline

### Added

**M0.1-M0.3** — 项目骨架 / 零依赖 / Sentinel 边界
- 单 wheel `atlas-richie-sentinel` (主包)
- `dependencies = []` 主包零三方依赖
- 内部模块 `atlas_richie.sentinel.{engine, errors, primitives, ...}`

**M0.4-M0.5** — 错误层 / `ResilienceError`
- 根异常 `SentinelError(Exception)` (stdlib)
- `ResilienceError(SentinelError)` — primitives 父类
- 5 个具体原语异常:`RetryExhausted` / `RetryNotPermitted` /
  `CircuitOpen` / `RateLimitExceeded` / `BulkheadFull`
- `IdempotencyKey` 真实类型:`StatelessIdempotencyKey` /
  `NeverIdempotencyKey` / `CallableIdempotencyKey`

**M0.6-M0.8** — `RetryPolicy` / `RetryExecutor` / `CircuitBreaker` /
  `Bulkhead` / `RateLimiter` / `DeterministicRandom` / `ManualClock`
  完整实现

**M0.9** — `git mv` Resilience 源码到 `atlas_richie.sentinel.primitives`
- 删 `components/resilience/`(无兼容 shim)
- 唯一 consumer: `foundation/platform` 更新依赖

**M1.1-M1.5** — SentinelEngine 6 状态机 + Slot 协议 + Rule 协议
- `SentinelEngine` (CREATED/READY/SHUTTING_DOWN/SHUTDOWN/FAILED)
- `SlotChain` (Order 升序 + 重复 id 拒绝)
- `EntryRequest` (async context manager, Outcome 5-way)
- `RuleSnapshot` / `RuleVersion` / `RuleRepository` /
  `RuleIndex` / `ResourceSelector` (EXACT/PREFIX/GLOB)

**M2.1-M2.7** — 5 类规则 + TokenService
- `FlowRule` (QPS / CONCURRENCY / WARM_UP / QUEUE)
- `DegradeRule` (ERROR_RATIO / ERROR_COUNT / SLOW_REQUEST_RATIO)
- `SystemRule` (CPU_USAGE / LOAD / INBOUND_QPS / CONCURRENCY / AVG_RT)
- `ParamFlowRule` (per-parameter hot-spot limiting)
- `AuthorityRule` (WHITE / BLACK by origin)
- `TokenService` Port + `LocalTokenService` 默认实现(1.0 always grants locally)

**M3.1** — `RuleSource` Protocol
- `_RuleSourceContractBase` 测试基类(子类 `__test__ = True` 启用 collection)
- `FileRuleSource`(在 `sentinel-source-file` wheel)

**M3.2-M3.4** — 4 extension wheels
- `atlas-richie-sentinel-source-file` — FileRuleSource 包装(JSON / YAML)
- `atlas-richie-sentinel-adapter-asgi` — 纯 ASGI 3.0 middleware
- `atlas-richie-sentinel-adapter-httpx` — HTTPX AsyncTransport
- `atlas-richie-sentinel-dashboard` — 控制面 / 指标(loopback + admin token + audit log)

**M4.1-M4.6** — 指标 / classifier / retry+CB composition
- `MetricRegistry` + `SlidingWindow`
- `OutcomeClassifier` Protocol + `DefaultOutcomeClassifier`
- `RetryExecutor` + `RetryPolicy` 完整组合语义

**M5.1-M5.6** — 文档 / matrix / 验收
- 4 个中英双语文档(QUICK_START / RULE_REFERENCE / EXTENSION_GUIDE / OPERATIONS)
- 2 个 acceptance 报告(R-SENTINEL-M1-baseline / R-SENTINEL-M5.4-matrix)
- 1 个 release handoff(R-SENTINEL-1.0-handoff)

### Fixed (M1.6 测试中暴露的真 bug)

- **并发 entry 共享 `_EngineContext._context_token`**:
  导致 `ValueError: Token was created in a different Context`
  - 修复:token 改存 `EntryLease._context_token` (per-entry)
- **lease 释放异常完全不可观测**:
  `EntryLease._release_errors` 收集但不暴露
  - 修复:新增 `EntryLease.last_release_error()`,
    `SentinelEngine._finalize_entry` 写到 `engine.last_error`

### Fixed (M3.5 测试中暴露的真 bug)

- **ASGI middleware 永远传 `(None, None, None)` 给 `entry.__aexit__`**:
  engine 永远看不到 CANCELLED / FAILED outcome
  - 修复:按实际异常类型传参(`asyncio.CancelledError` →
    CANCELLED, `BaseException` → FAILED)

### Documentation

- `docs/DESIGN.md` (1636 行,user-rewritten v2, ADR-SEN-001~015)
- `docs/PLANNING.md` (969+ 行, 58 sub-items 全部 [x])
- `docs/QUICK_START.md` (中英)
- `docs/RULE_REFERENCE.md` (中英)
- `docs/EXTENSION_GUIDE.md` (中英)
- `docs/OPERATIONS.md` (中英)
- `docs/RELEASE.md` (publish 流程)
- `docs/acceptance/R-SENTINEL-M0-handoff.md`
- `docs/acceptance/R-SENTINEL-1.0-handoff.md`
- `docs/acceptance/R-SENTINEL-M1-baseline.md`
- `docs/acceptance/R-SENTINEL-M5.4-matrix.md`

### Test Coverage (1.0 baseline)

| Wheel | Tests | Pass | Skip |
| ----- | ----: | ---: | ---: |
| `atlas-richie-sentinel` | 261 | 261 | 2 (perf 默认 skip) |
| `atlas-richie-sentinel-adapter-asgi` | 21 | 21 | 0 |
| `atlas-richie-sentinel-adapter-httpx` | 26 | 26 | 0 |
| **Total** | **308** | **308** | **2** |

Per-wheel test breakdown:

`atlas-richie-sentinel`:
- `test_bulkhead.py` (11)
- `test_circuit_breaker.py` (10)
- `test_composition.py` (5)
- `test_e2e_resilience.py` (12)
- `test_idempotency.py` (5)
- `test_rate_limit.py` (11)
- `test_retry.py` (19)
- `test_sen_core.py` (30) — M1.6 baseline
- `test_sen_rule.py` (36) — M1.6 baseline
- `test_sen_rule_source.py` (25) — M3.1 contract
- `test_sen_multiprocess.py` (3) — M3.6 multi-worker
- `test_sen_retry_cb_compose.py` (11) — M4.5 retry + CB
- `_helpers.py`
- `tests/benchmark/test_sen_perf.py` (1, opt-in `RUN_SEN_PERF=1`)

`atlas-richie-sentinel-adapter-asgi`:
- `test_asgi.py` (21) — M3.5 full ASGI protocol

`atlas-richie-sentinel-adapter-httpx`:
- `test_outcome_classifier.py` (26) — M4.4 classifier

### Wheels (1.0)

| Wheel | Version | PEP 625 slug |
| ----- | ------- | ------------ |
| `atlas-richie-sentinel` | 0.2.0 | `atlas_richie_sentinel` |
| `atlas-richie-sentinel-adapter-asgi` | 0.2.0 | `atlas_richie_sentinel_adapter_asgi` |
| `atlas-richie-sentinel-adapter-httpx` | 0.2.0 | `atlas_richie_sentinel_adapter_httpx` |
| `atlas-richie-sentinel-source-file` | 0.2.0 | `atlas_richie_sentinel_source_file` |
| `atlas-richie-sentinel-dashboard` | 0.2.0 | `atlas_richie_sentinel_dashboard` |

3 source version consistency(5/5):pyproject.toml / wheel METADATA /
sdist PKG-INFO 全部 `0.2.0` 一致。

### Out of scope (1.x)

- Nacos / Redis / Consul Source
- Cluster mode(跨进程 token 协调)
- gRPC / FastStream / WSGI Adapter
- Prometheus / OpenTelemetry Dashboard
- 3.10 / 3.11 / Linux x86_64 / Windows 兼容性(留给 1.x CI)
- 全 10 分钟 soak + 1 小时 soak(留给 1.x 阶段)

---

## [Unreleased] — 1.x 阶段 (2026-Q4+)

### Planned

- `atlas-richie-sentinel-cluster` — Cluster token client
- `atlas-richie-sentinel-source-nacos` — Nacos rule source
- `atlas-richie-sentinel-source-redis` — Redis pub/sub source
- `atlas-richie-sentinel-adapter-grpc` — gRPC interceptor
- `atlas-richie-sentinel-dashboard-prometheus` — Prometheus exporter
- 3.10 / 3.11 support(单独 milestone)
- 10 分钟 soak + 1 小时 soak 内存泄漏证据

### Design decisions locked

- 主包 `dependencies = []` 不变
- 1.0 公开 API 6 月内不 breaking
- 新功能 = 新 wheel(Open-Closed 在 component 级)
- 5 类规则语义不变(Java 仓 5 年迭代沉淀)
- per-process 状态机不变(1.0 已文档化)
- 主包 0 依赖原则不变

---

[0.2.0]: https://github.com/atlas-richie/atlas-richie-platform-python/releases/tag/atlas-richie-sentinel-0.2.0
[Unreleased]: https://github.com/atlas-richie/atlas-richie-platform-python/compare/atlas-richie-sentinel-0.2.0...HEAD
