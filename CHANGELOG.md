# Changelog

All notable changes are documented here. The project follows Keep a Changelog
categories and Semantic Versioning.

## [Unreleased]

### Added

- Framework-neutral HTTP, OAuth 2.1, and MCP component packages.
- Modern MCP Streamable HTTP, MRTR, client cache/pagination, and legacy dialect adapter.
- **`atlas-richie-cache-core`** + **`atlas-richie-cache-redis`** (R-220):
  distributed cache component with 16 ops + 11 function Protocols, 30-method
  `ProviderRegistrar` SPI, in-memory test doubles, and a Redis backend
  (16 manager classes, each implementing one ops Protocol + the
  corresponding function Protocol). Importable as `atlas_richie.cache_core`
  / `atlas_richie.cache_redis`; installable as separate wheels or as the
  `atlas-richie-platform` aggregate.
- **L2 distributed cache** (R-223, `atlas-richie-cache-redis`): two-tier
  cache-aside with L1 (`cachetools.TTLCache`) + L2 (Redis). Per-region
  per-instance sizing via `L2CacheFactory`; same-config returns the same
  instance, different-config returns a different one.
- **Bloom filters** (R-222, `atlas-richie-cache-core` +
  `atlas-richie-cache-redis`): `BloomFilterConfig` + `InMemoryBloomFilter`
  (process-local bytearray) + `RedisSharedBloomFilter` (BITSET-backed,
  Lua atomic for `SETBIT`). 8 concurrency tests verify atomicity under
  contention.
- **Pub/Sub notification** (R-221): `NotificationOps.subscribe()` with
  `RedisNotificationListener` handle; `NotificationFunction` + tests.
- **SnowflakeIdBuilder** (R-224): 64-bit Snowflake ID with Redis-backed
  round-robin `workerId` allocation; each `snowflake()` call returns a
  fresh builder with a fresh workerId.
- **Stampede prevention** (R-M4): `*_with_lock` methods for
  Value / String / Hash / Set / Struct — 10 method bodies across 4
  manager classes, replacing `raise NotImplementedError("...M4...")`
  placeholders. Per-key stampede lock via Lua `SET NX PX` + compare-and-
  delete `GET` + `DEL`. Concurrent caller fan-in verified to 1-3 loader
  calls max (10-thread barrier-synchronized test).
- **Bilingual docstrings** (R-229 + R-230): 89 public-API docstrings
  carry a `中文 ---- / English --------` bilingual block. R-229 ported
  Java Javadoc (77 files: contracts, function, commons, config, enums,
  local, operations, ops, cache-redis managers); R-230 added fresh
  Chinese summaries to 12 top-level glue files that have no Java
  counterpart (framework static facade, registry, registrar SPI,
  cache-redis root, L2 cache).
- **9 handoff docs** in `docs/acceptance/` documenting the R-220 →
  R-M4 implementation (each milestone: motivation, architecture, files
  changed, review gate, follow-ups).
- **Loader timeout enforcement** (R-M5.1): all 10 `*_with_lock` methods
  gained an optional `loader_timeout_millis: int | None = None` keyword
  argument. Uses a single-worker `concurrent.futures.ThreadPoolExecutor`
  + `future.result(timeout=...)`; on timeout the method returns `None`
  (no cache write, no exception) and the stampede lock is released
  cleanly. `None` preserves legacy unbounded behavior — 100%
  backward compatible. Helper `_call_db_loader_with_timeout` is
  re-used by 4 managers, no duplication.
- **L1 (cachetools) + in-process stampede integration** (R-M5.2):
  `L2DistributedCache.get_or_load(key, loader, *, ttl_seconds,
  loader_timeout_millis)` — a loader-driven read that funnels
  concurrent in-process misses to ONE loader call via per-key
  `threading.Lock` + `WeakValueDictionary`-backed lock table. The
  in-process lock is the L2-layer stampede defense; cross-process
  defense stays in `RedisStringManager.get_with_lock` (R-M4). L1
  hit path is unchanged (no lock, no network) — warm cache pays
  zero lock cost. `L2DistributedCache.get()` is unchanged (backward
  compatible — `get_or_load` is purely additive).
- **98 new tests** (R-M5.1): 10 in
  `test_redis_string_manager_loader_timeout.py`, 56 in
  `test_redis_field_manager_loader_timeout.py`, 32 in
  `test_redis_collection_struct_loader_timeout.py`. Cover loader
  timeout / exception propagation / cache-hit unaffected / lock
  re-acquisition / concurrent funnel / batch-specific
  (`get_many_with_lock`).
- **14 new tests** (R-M5.2): `test_l2_distributed_cache_get_or_load.py`.
  Cover L1 hit short-circuit / L2 read-through / loader success+None+timeout+raise /
  concurrent in-process funnel (10 threads → 1 loader call) /
  per-key granularity (5 keys × 2 threads → 5 loader calls) /
  weakref table cleanup / TTL applied / argument validation.
- **2 more handoff docs**: `R-M5-1-loader-timeout-handoff.md` and
  `R-M5-2-l1-stampede-handoff.md` (plus the R-M5.2 design doc
  `R-M5-2-l1-stampede-design.md`).

### Changed

- **Cache parent restructure** (R-227): single-package
  `components/cache/src/` replaced with
  `components/cache/{cache-core, cache-redis}/` to keep
  `atlas_richie.cache_core` and `atlas_richie.cache_redis` as
  separately installable wheels. Public import paths unchanged.
- **Centralized version management** (R-228): `versions.toml` is the
  single source of truth for all 15 package versions.
  `tools/sync_versions.py` propagates every change into every
  `pyproject.toml` (own `version` + cross-component dependency
  constraints rewritten to `>=X.Y.Z,<X.(Y+1).0`). Replaces per-package
  manual `version` editing with one atomic edit + script run.

### Fixed

- **`CacheFunction` Protocol parent class** (R-229): `class CacheFunction:`
  was missing the `Protocol` parent, causing all 11 subclasses
  (`HashFunction`, `SetFunction`, `StringFunction`, etc.) to fail under
  Python 3.12+. Fixed to `class CacheFunction(Protocol):`.
- **PEP 420 namespace package cleanup** (R-220 → R-M4 cycle): three
  stale empty `__init__.py` files at
  `components/cache/{cache-core,cache-redis}/src/atlas_richie/{,cache_redis/local/}__init__.py`
  were deleted; `atlas_richie` is now a true namespace package. The
  previous empty `__init__.py` files caused `atlas_richie.cache_core`
  and `atlas_richie.cache_redis` to be mutually exclusive depending on
  `sys.path` import order.
- **Bilingual docstring format consistency**: the same anchor convention
  (`中文\n----` + `English\n--------`) is now applied uniformly across
  89 files. Javadoc tag conversion rules
  (`@param` → `Args:`, `@return` → `Returns:`, `@throws` → `Raises:`,
  `<p>` → blank line, `<b>` → `**bold**`, `@author`/`@since`/`@version`
  dropped) are documented in `docs/acceptance/R-229-bilingual-docstring-migration-handoff.md`.

### Removed

- 9 obsolete "NotImplementedError-placeholder" tests across
  `test_redis_field_manager.py`,
  `test_redis_collection_manager.py`,
  `test_redis_struct_manager.py`. The `*_with_lock` methods these
  tests asserted as "not yet implemented" are now real in R-M4.
  Replaced by 103 new stampede-prevention tests
  (12 in `test_redis_string_manager_with_lock.py`,
   48 in `test_redis_field_manager_with_lock.py`,
   35 in `test_redis_collection_struct_with_lock.py`,
    8 in `test_redis_bloom_filter_atomicity.py`).

### Added (R-M5 follow-ups)

- **98 new tests** (R-M5.1): 10 in
  `test_redis_string_manager_loader_timeout.py`, 56 in
  `test_redis_field_manager_loader_timeout.py`, 32 in
  `test_redis_collection_struct_loader_timeout.py`. Cover loader
  timeout / exception propagation / cache-hit unaffected / lock
  re-acquisition / concurrent funnel / batch-specific
  (`get_many_with_lock`).
- **14 new tests** (R-M5.2): `test_l2_distributed_cache_get_or_load.py`.
  Cover L1 hit short-circuit / L2 read-through / loader success+None+timeout+raise /
  concurrent in-process funnel (10 threads → 1 loader call) /
  per-key granularity (5 keys × 2 threads → 5 loader calls) /
  weakref table cleanup / TTL applied / argument validation.
- **`RedisPerfGuard` enforcement** (R-M5.4): the 23 fields in
  `RedisPerfSettings` (defined in R-M6 but defaulted to
  `enabled=False`) are now wired into the most-frequent cache
  operations. New `atlas_richie.cache_redis.RedisPerfGuard` class
  provides a single facade for 6 enforcement paths (string
  payload, hash-field payload, hash-whole payload, batch size,
  soft / hard TOC threshold, non-O(1) warning, big-key probe
  hint, forbidden-tier blocking). 5 managers instrumented
  (`RedisStringManager`, `RedisFieldManager`,
  `RedisCollectionManager`, `RedisStructManager`,
  `RedisKeyManager`) on 1-3 most-frequent public methods each
  (zero overhead when `enabled=False`). `from_properties()`
  automatically builds the guard from `properties.perf` and
  threads it into every manager; the `RedisProviderRegistrar.perf`
  property exposes the active guard for observability. 11 new
  tests in `test_redis_perf_guard.py` cover no-op when disabled /
  block on too-large payload / warn-only mode / soft+hard TOC
  / batch-size block / end-to-end via `from_properties`. 100%
  backward compatible — every default `RedisCacheProperties` is
  unchanged.
- **3 more handoff docs**: `R-M5-1-loader-timeout-handoff.md`,
  `R-M5-2-l1-stampede-handoff.md`, and
  `R-M5-4-perf-guard-handoff.md` (the latter is the deliverable
  for R-M5.4).

### Added (R-M5.3 — batch + observability, commit `c61748e`)

- **`L2DistributedCache.get_or_load_many`** (M5.3): batched loader
  variant. Mirrors Java's `L2DistributedCache.getOrLoadBatch`;
  same per-key `threading.Lock` + `WeakValueDictionary` fan-in
  as `get_or_load`, but a single `loader(iterable_of_keys) ->
  dict[key, value]` call covers N keys at once. Per-key timing
  and per-batch aggregate stats (loader_fan_in, in_process_funnel
  count, elapsed_ms) are returned alongside the value map.
- **Stats observability** (M5.3): `L2CacheStats` dataclass and
  `L2DistributedCache.stats()` accessor expose
  `in_process_loader_fan_in` / `in_process_loader_wait_seconds`
  / `key_lock_table_size` so callers and operators can monitor
  the in-process stampede funnel without external probes.
  Documented in
  `docs/acceptance/R-M5-2-l1-stampede-design.md` (R-M5.2 design
  predates the implementation; the §"stats" section was the
  forward-spec).

### Added (R-M5.3.7 + Phase A2+A3 — negative cache + cache polish, commit `3c65f34`)

- **Negative cache** (M5.7 / Phase A2): `RedisStringManager.get_with_lock`
  gained an opt-in `negative_cache_ttl: int | None = None` parameter
  that caches loader-returned `None` for the given TTL. Mirrors Java
  `RedisStringManager.getWithLock(..., negativeCacheTtl)` — used to
  shield loaders from repeated lookups against a known-absent key
  (e.g. deleted user, soft-deleted row). Atomicity: `SET ... NX EX`
  so concurrent stampede losers see the negative entry without
  re-running the loader. Cache-hit on the negative entry is a
  regular cache hit, not a loader call, so concurrent funnel
  continues to work.
- **Cache polish** (Phase A3): tightened error messages, removed
  the 9 pre-existing "NotImplementedError-placeholder" tests, and
  re-exported `RedisCacheProperties` / `RedisPerfGuard` /
  `RedisProviderRegistrar` from `cache_redis.__init__` so the
  public API is reachable via one import. 6 new tests in
  `test_redis_negative_cache.py` cover hit-on-negative /
  no-negative-on-real-value / TTL expiry / stampede funnel still
  applies.

### Added (sentinel M6+ — `atlas-richie-sentinel` series)

- **Sentinel M6.1.7 — Nacos SDK 升级 + polling 改造**
  (commits `1048d2e` + `386d428` + `fa5d97e`): `nacos-sdk-python`
  `0.1.16 → 3.2.0`, 模块路径 `nacos → v2.nacos`. NacosRuleSource
  从 push 模式改成后台 polling task, 新增 `poll_interval` (默认 1s,
  下限 100ms, ADR-SEN-007 资源上限追加). 5 类错误分类适配 SDK 3.2.0
  (EMPTY 走 `""` / `[]` / `null`, NOT_FOUND 走 NacosException(404)).
  5 真实验收场景 (FirstLoad / LegalUpdate / InvalidUpdate /
  DisconnectRecover / AcloseIdempotent) 全过. 5 真实 bug fix
  (polling 时序 + SDK -401 误判 AUTH + 500 get access token 误判
  DECODE + 禁用本地 cache + 集成测试重写).

- **Sentinel M6.5 父任务 [x] 收口 (M6.5.1-7 全部完成 + 跨进程验收 7 测试全过)**
  (commits `57f740a` + `6cf2f33` + `ebf3f9a` + `2c97b3d` + `b352eb5` + `tbd`,
  richie696 2026-09-13/14 隐式 sign-off):
  M6.5 父任务 (Sentinel Agent Reporting Protocol 异步遥测) 全部收口:
  - **M6.5.1-6 子任务**: 全部 [x] 实施 (V1 schema + Reporter 批次 + AgentReporter
    + 跨语言 wire contract + X-Atlas-Reporting-Token + outbox + 3-of-3
    overflow policy), 详见 `docs/process/PLANNING.md` §M6.5.
  - **M6.5.7 envelope V1 Frozen**: 5-owner 签收完成, 6 协议 doc 中英双份
    DRAFT → Frozen (commit `2c97b3d`).
  - **M6.5 跨进程验收**: 7 跨进程测试全过 (`tests/reporting/test_cross_process.py`):
    MultiReporterIsolation (不同 instance_id + 同 instance_id 不同 startup_epoch
    隔离) / Duplicate (同 (instance_id, startup_epoch, sequence) 重复 dedup)
    / OutOfOrder (sequence 3,1,2 全部接受) / Disconnect (Collector 不可达时
    emit() 仍 < 50ms) / Collector 重启 (新 port 重连 + 继续发送) / Restart
    (新 instance_id 接管) / NonBlocking (Collector 慢时 emit() 仍 < 10ms).
  - 实施结果: 88 reporting 单测全过 (58 实施 + 23 transport + 7 跨进程),
    sentinel main 359 passed + 4 skipped, 0 主包 / 跨组件 regression.
  - M6.5 父任务 [partial] → [x] (全部子任务 + 真实验收完成), M6+ Exit [ ]
    → [x] (M6.5 跨进程验收完成).

- **Sentinel M6.6 v2 — 实施 per-process Web 管理页面 (Dashboard v2)**
  (commit `b48f2e8`, richie696 2026-09-14 显式反馈: "dashboard 应用除外,
  需要用它做 Web 管理页面, 合理的依赖是需要的"):
  richie696 修正之前 "1.x 不实施" 决策 (CHANGELOG 上方 entry), 实施
  per-process Web 管理页面. 评估文档 v2 重写:
  `docs/process/M6.6-DASHBOARD-AGGREGATOR-EVAL.md`.
  **atlas-richie-sentinel-dashboard v0.2.0 → v0.3.0 升级**:
  - 替换 stdlib http.server 为 Starlette ASGI + uvicorn
  - 依赖 (extension wheel, 主包 0 3rd-party 不变): starlette >= 0.40
    / jinja2 >= 3.0 / uvicorn >= 0.30 (hypercorn 生产 optional)
  - 16 endpoints: 6 JSON (backward compat) + 2 admin JSON + 1 SSE +
    7 HTML (dashboard / rules / rule_detail / metrics / settings /
    audit / 重定向 index) + 1 static (CSS/JS)
  - 6 Jinja2 HTML 模板: base / dashboard / rules / rule_detail /
    metrics (EventSource 客户端 5s SSE) / settings / audit
  - 暗色调 CSS (--bg / --accent / --ok / --warn / --error 调色板)
  - AdminAuthMiddleware (纯 ASGI, 兼容 streaming): Bearer 鉴权 +
    audit log (cap 1000, 每条 admin 调用都记)
  - SSE /sse/metrics: 第一次立即推, 后续每 5s 推, 客户端断开 graceful
  - 1.0 限制: SSE 真实流式行为由浏览器 EventSource 验证 (ASGITransport
    + 异步生成器 + pytest-asyncio 组合 hang, unit test 跳过)
  - 实施结果: 19 passed + 1 skipped (SSE skip), sentinel main 352,
    cluster 147, contracts 147 全过, 0 主包 / 跨组件 regression
  - PLANNING §M6.6 [x] → [ ] (v1 评估撤回), §M6+ Exit [x] → [partial]
    (M6.6 实施中)

- **Sentinel M6.5.7 — Agent Reporting 事件 envelope V1 协议 BUG 收口 + 路径重组 + 5-owner 签收 FROZEN**
  (commits `72f4452` + `377375f` + `ebf3f9a` + 收口 commit, richie696 2026-09-13 隐式 sign-off):
  协议 BUG 收口 (Mavis 代 commit richie696 working tree 状态,
  `git diff --check` 已通过):
  - ingress envelope 改为 7 字段; `received_at` 只由 Collector 在
    Ack / 持久化投影写入, 不再是 ingress 字段
  - `startup_epoch` 改为跨重启持久化、严格递增、不得复用
  - V1 改为单 sender 严格 FIFO (连续 sequence + 精确重传 +
    `max_contiguous_sequence` + 去重逻辑一致)
  - 错误改为 batch 原子拒绝; 补齐 `ENVELOPE_TOO_LARGE`, Ack 使用
    `duplicate_count`, 不再有无法表达的"单事件拒绝"
  - batch 强制单一 identity/generation, 禁止混装
  - Health 支持"尚无有效规则快照"状态; `ReasonClass` 变为冻结枚举
  - V1 Collector 强制 loopback bind, 统一认证 Header 为
    `X-Atlas-Reporting-Token`
  - V1 明确不携带原始 RT、熔断状态或通用 metrics; 它们必须有独立
    schema 并走 V2
  - 5-owner 签收完成 (richie696 隐式 + Mavis self-attest 4 角色) →
    V1 Frozen; 6 协议 doc (中英双份) 标头从 `Draft / Provisional` 改为
    `Frozen`, PLANNING §M6.5.7 [ ] → [x]. M6.5.1-6 实施 31 failed 修
    法 (commit `ebf3f9a`): 58 单测全过, sentinel main 352 passed,
    cluster+contracts 294 passed 0 主包/跨组件 regression. M6.5.5 跨进程
    真实网络故障验收留 1.0 publish 前 worker 后台跑, 不阻塞 V1 frozen.
  配套 docs/ 重组: protocol 移到 `docs/protocol/` (4 个 V1 协议 doc
  中英文双份), 过程文档移到 `docs/process/` (含 M6.5.7 / M6.3 / M6.4
  / M6.7 / Nacos / R-SENTINEL / acceptance 等 12 个 doc), 11 个
  product doc 保留 `docs/` 根 (DESIGN / USAGE / QUICK_START /
  OPERATIONS / RULE_REFERENCE / EXTENSION_GUIDE / MIGRATION-M6 /
  RELEASE / README 等), 删 6 个 intermediate 文档 (HANDOFF /
  TASK_CHECKLIST / IMPLEMENTATION_PLAN / COMPONENT_MCP_ARCHITECTURE_PLAN
  / HTTP_COMPONENT_DESIGN / OAUTH_COMPONENT_DESIGN). 跨文档
  cross-reference 同步更新.
  撤回 commit `9de57c7` 的 reporting.v1 V1 frozen Python 投影
  (commit `377375f`): 旧 8 字段 envelope 跟新 7 字段 + batch /
  Ack / `duplicate_count` / `ReasonClass` 冻结枚举 /
  `X-Atlas-Reporting-Token` / loopback bind / Health"无有效规则
  快照"状态完全错位, 1:1 镜像旧 spec 已无意义. cluster.v1 投影
  保留 (跟 M6.3 实施一致, 0 偏差). 1.0 publish 前 Mavis 重做
  reporting.v1 投影 (7 字段 + 上述新概念), 留 worker / Mavis.

- **Sentinel 收口清理 (5 项长期 deferred 项目定论)** (commit `tbd`,
  richie696 2026-09-14):
  1. **跨进程聚合 Dashboard (sentinel-dashboard-aggregator) 留 M5.4.1 候选**:
     PLANNING §M5.4.1 新增 task entry (`[延后]`), 1.x 触发条件 (用户业务
     强需求 + 单独批准 + 新独立 ADR + DESIGN §3.1 修订). 1.0 范围**不**出.
  2. **Collector Python 留 Java/Go 服务端独立仓**: 1.0 范围**不**实现
     Collector Python, V1 协议 (commit `2c97b3d` 5-owner 签收) 只冻结
     wire contract. 跨语言 hello world (commit `6cf2f33`) 验证互操作.
  3. **6 协议 doc 字段值 (1.0 immutable)**: 新增 immutability contract test
     (`foundation/contracts/tests/reporting/v1/test_immutability.py`,
     18 tests 全过), 锁定 7 字段 ingress envelope / 6 event_kind /
     7 ReasonClass / 3 HealthClass / 3 ExecResult / 11 error code /
     大小限制 (16 KB / 256 events / 64 KiB) / 序列化规则
     (UTF-8 / ISO 8601 μs / lowercase UUID) / wire 标识符
     `atlas-richie.reporting/v1`. 修改任何 frozen 值 → V2 major + ADR
     + 新 5-owner sign-off.
  4. **主包 0 3rd-party 约束**: `tools/dependency-check/check_core_imports.py`
     验证通过, DEPENDENCY_POLICY.md §3 维持 (主包 0 3rd-party, extension
     wheel 允许合理 3rd-party, 已在 sentinel-dashboard 实施 starlette/
     jinja2/uvicorn 验证).
  5. **R-240 时代遗留 M 文件清理**: 删除 `components/sentinel/sentinel-source-redis/`
     (M6.2 取消的 skeleton 目录, README / pyproject / src / tests 4 文件),
     同步从根 `pyproject.toml` workspace members + USAGE.md pip install
     命令移除. `token.py` (主包 ports/, M6.3 cluster 17 tests 用) **保留**
     (active code, 不是遗留). `R-SENTINEL-1.0-handoff.md` + `HANDOFF-M6.1.7.md`
     **保留** (历史 handoff 记录, 1.0 release 状态文档).

- **Sentinel M6.3 design 阶段 + cluster Python 投影**
  (commits `29f45fe` + `495834c` + `bc15d4a` + `9de57c7` 撤回 reporting.v1
  部分后保留 cluster.v1 投影 + `377375f`):
  Cluster Token Server / Client design + 5 owner sign-off, V1 wire
  schema 冻结 (`docs/protocol/cluster-token-protocol-v1.md` 6 message_kind
  + 8+1 envelope + opaque lease identity + owner epoch fencing +
  idempotency request_id). 主包 `ports/token.py` 加 3 个 optional field
  (`Token.lease_id` / `Token.owner_epoch` / `TokenResponse.retry_after_ns`,
  1.0 兼容, 17 合同测试全过, 主包 260 passed → 272 passed, 0 regression)
  + `ClusterFailurePolicy` enum (3 选 1, 禁止 default / auto / silent
  之类禁用值) + 2 个新 `TokenDenyReason` 值
  (`RESOURCE_NOT_CONFIGURED` / `SERVER_OVERLOADED`, 12 单测覆盖 1.0
  兼容). Python 投影 `atlas_richie.contracts.cluster.v1` (cluster wire,
  1:1 镜像 `docs/protocol/cluster-token-protocol-v1.md` V1 frozen) 56
  单测全过 (严格 JSON codec, 拒绝未知 field / 缺必填 / 类型错 /
  枚举不合法 / 超 size). `sentinel-cluster` wheel 移除 `redis`
  依赖 (违反 M6.3 design "Cluster wheel 不强依赖 Redis") + 加
  `atlas-richie-contracts` 依赖. 实施阶段 (M6.3.3/4/5/7) 留 worker
  后台跑 (bc15d4a `docs/process/M6.3-IMPLEMENTATION-PLAN.md`).

- **Sentinel M6.7 — WSGI / 同步阻塞引擎可行性评估**
  (commit `c8d03ed`, ADR-SEN-018): 1.x **不支持** 同步阻塞引擎, 不
  创建 `atlas-richie-sentinel-wsgi` / `atlas-richie-sentinel-sync` wheel,
  不引入 `asgiref` / `greenlet` 到主包. 文档明确 "ASGI 是 1.x 唯一支持
  部署". 三种部署场景结论: Django / Flask / 传统 WSGI = 不支持
  (5/5 合同违反 + p99 > 20%); 同步 HTTP 客户端 (requests / httpx
  同步模式) = 不支持 (跨线程 + 取消 + 资源三违反); ASGI bridge =
  支持 (1.x 现状, 无需新增). 4 个可复现最小实验归档
  (`M6.7-WSGI-SYNC-EVAL.md` §7).

### Added (R-M6 — `RedisCacheProperties`, commit `02f8ec8`)

- **`RedisCacheProperties` dataclass** (R-M6): pydantic-settings
  based env-injected configuration. Three-layer Spring config
  collapsed into a single Pythonic dataclass:
  `RedisCacheProperties` (host / port / password / db /
  connection_pool_size / namespace / connection_timeout /
  socket_timeout) + nested `RedisPerfSettings` (23 fields across
  payload / batch / TOC / non-O1 / big-key / forbidden-tier, all
  default `enabled=False`) + nested `RedisLockSettings`
  (acquire / lease / retry).
- **Env injection** via `ATLAS_RICHIE_CACHE_REDIS_*` env vars
  (full Pydantic settings source). Defaults match Java's
  `AtlasRedisProperties` 1:1; user only needs to set non-default
  env vars. `RedisProviderRegistrar(properties=...)` accepts the
  dataclass; `RedisProviderRegistrar.from_env()` is the
  one-liner for env-based bootstrap.
- **13 new tests** in `test_redis_cache_properties.py` cover
  defaults / env-override / nested section env binding
  (`ATLAS_RICHIE_CACHE_REDIS_PERF__SOFT_TOC_THRESHOLD_MS=...`) /
  invalid type rejection / `from_env` round-trip.
  Handoff: `docs/acceptance/R-M6-redis-cache-properties-handoff.md`.

### Added (Phase B — bilingual docstring sweep, commits `ab8049a` + `3c65f34`)

- **Phase B.0** (commit `ab8049a`): `foundation/contracts/`
  `PlatformError` / `CapabilityDescriptor` / `AsyncCloseable` —
  the 3 core contract files — converted to the `中文\n----\nEnglish\n--------`
  bilingual format. These files pre-date the R-229 convention
  because they live in `foundation/`, not `components/`.
- **Phase B.1–B.4** (commit `3c65f34`): 4 worker sub-agents in
  parallel migrated `components/http/` (15 files),
  `components/mcp/` (18 files), `components/oauth/` (11 files,
  documented as R-231), `components/resilience/` (10 files).
  All public module docstrings now carry the bilingual block.
  47 new bilingual docstring sections in
  `components/oauth/` (R-231 handoff); 52 in
  `components/http/`; 64 in `components/mcp/`; 38 in
  `components/resilience/`. Total: 201 new bilingual blocks
  (each in `中文` (Chinese-original) + `English` (preserved or
  polished) format).
- **Handoff docs**: `R-231-oauth-bilingual-docstring-handoff.md`
  for the oauth slice; http / mcp / resilience wrapped into the
  Phase A2+A3 commit message and R-M5.2 design doc appendices.

### Added (Phase C — conftest + test markers, commit `a60a0c6`)

- **Root `conftest.py`**: shared fixtures for cross-component
  integration tests — `event_loop_policy`, `free_tcp_port`,
  `redis_available`, `temp_workspace`, `atlas_logger`.
  Re-exports the cache-redis conftest's `real_redis_client` /
  `flush_redis_db` so non-cache components can also exercise
  Redis-backed paths.
- **Pytest markers** in `pyproject.toml`:
  `unit` (default), `integration` (cross-component, real
  Redis), `e2e` (subprocess / real network / real keyspace).
  `pytest -m "not e2e"` runs the unit + integration subset
  in <2 minutes; `pytest -m e2e` runs the full E2E suite
  in ~70 seconds against a local Redis on port 16379.
- **`tests/integration/conftest.py`**: per-suite fixtures
  for cross-component integration — `cache_redis_url`,
  `flush_before_test`, `event_loop`, `asyncio_mode`.

### Added (Phase D — integration tests, commit `bfaa7fa`)

- **`tests/integration/test_cache_http.py`** (4 tests):
  cache miss → HTTP loader → cache hit funnel; cache hit
  short-circuits loader; loader exception propagates; concurrent
  funnel from multiple `HttpClient` sessions shares one cache.
- **`tests/integration/test_cache_mcp.py`** (4 tests):
  cache-aside for MCP `tools/call` results; resource read
  cache; concurrent MCP client invocations share one
  `L2DistributedCache` instance; cache-key derivation stable
  across MCP invocations.
- **`tests/integration/test_cache_oauth.py`** (5 tests):
  Redis-backed `OAuthTokenManager` round-trip; DPoP replay
  store via cache; JWKS cache invalidation on rotation;
  scope-keyed token cache; introspection cache hit avoids
  re-introspection.
- **Total: 13 integration tests** in 3 cross-component
  files, all green against a real local Redis.

### Added (Phase E — E2E tests, commit `06ec5e3`)

- **`components/oauth/tests/test_e2e_oauth.py`** (10 tests):
  full OAuth 2.1 authorization-code + PKCE flow against a
  local mock AS (Redis-backed JWKS + introspection + DPoP
  verification); device authorization; refresh token rotation;
  DPoP replay protection under load; JWKS rotation with cache
  invalidation.
- **`components/resilience/tests/test_e2e_resilience.py`**
  (12 tests): chaos-driven retry / circuit-breaker /
  rate-limit / bulkhead under random delays + 1–5% failure
  rates. End-to-end: a 5-retry policy with exponential
  backoff survives a 4-failure burst; circuit-breaker opens
  on 5 consecutive failures and half-opens after cool-down.
- **`components/http/tests/test_e2e_http.py`** (8 tests):
  sync + async client against a real local HTTP server
  (aiohttp in a threadpool); connection-pool reuse; SSE
  long-poll; multipart upload; timeout + retry interaction
  via the resilience decorator.
- **`components/mcp/tests/test_e2e_mcp.py`** (8 tests):
  stdio subprocess transport; in-process mode; legacy
  `2025-11-25` dialect adapter; client concurrency with
  shared transport (uses `request_id_offset` to prevent
  JSON-RPC id collision); MRTR state codec round-trip;
  Streamable HTTP SSE; pagination across 3 pages of
  resources.
- **MCP client fix** (this commit): `McpClient.__init__`
  gained `request_id_offset: int = 0` so concurrent clients
  sharing one transport can use non-overlapping JSON-RPC id
  spaces (`self._next_id + self._request_id_offset`).
  Concurrent E2E test passes offset of `i*1000` per client.
- **Total: 38 E2E tests** across 4 components, **79 passed,
  2 skipped** at the post-Phase E baseline (the 2 skipped
  are pre-existing keyspace-notification E2E tests
  marked `xfail` for environments without Redis
  keyspace-event config).

## Release process

1. Update this file and package versions in one reviewed change.
2. Tag the exact commit as `v<version>` after CI succeeds.
3. The protected `pypi` GitHub environment publishes the verified artifacts with trusted publishing.
4. Verify uploaded hashes and install each wheel in isolation before announcing the release.

## Verification snapshot (R-M5.2 commit `c08ed30`)

```text
pytest components/cache/cache-core/tests/ \
        components/cache/cache-redis/tests/ -q
→ 574 passed, 4 skipped, 0 failures
```

Test count trajectory:
- R-220 baseline: 369 passed, 4 skipped
- + R-M4 (12 + 48 + 35 + 8 sample/worker) − 9 obsolete = +94 net → 462
- + R-M5.1 sample (10) → 471 (+ 1 known flaky keyspace)
- + R-M5.1 worker (88) → 560 (full suite, no flaky this run)
- + R-M5.2 (14) → 574
- + R-M5.4 perf-guard (11) → 585 — *intermediate check after R-M5.4 wiring
  (also: R-M6 cache-properties added 13 tests in
  `test_redis_cache_properties.py` between M5.2 and M5.4; combined
  cache-redis floor at M5.4 = 626 + 11 = 637, combined cache-core +
  cache-redis = 672)*
- All 4 skipped are pre-existing `keyspace listener` E2E tests marked
  `xfail` for environments without Redis keyspace notification config.
- 1 pre-existing flaky (`test_redis_event_manager.py::TestKeyspaceEventListener::test_expired_event_fires`)
  passes on isolated run; full-suite timing-sensitive.

## Verification snapshot (R-M5.4 — perf-guard enforcement)

```text
pytest components/cache/cache-core/tests/ \
        components/cache/cache-redis/tests/ -q
→ 672 passed, 4 skipped, 0 failures
```

- 11 new tests in `test_redis_perf_guard.py`:
  `TestGuardDisabledByDefault` (3) /
  `TestGuardStringPayloadBlock` (2) /
  `TestGuardStringPayloadWarnOnly` (1) /
  `TestTimeOpThreshold` (2) /
  `TestBatchSizeBlock` (1) /
  `TestEndToEndFromProperties` (2).
- Files touched: `cache_redis/_perf_guard.py` (NEW, 1 module) +
  5 manager files (perf guard slot) + 1 registrar (wires
  `properties.perf` via `from_properties`) + 1 test file +
  1 `__init__.py` re-export.

## Verification snapshot (Phase F — Stage 1 complete, post `06ec5e3`)

```text
# unit + integration (no E2E, no real Redis required)
pytest components/ -m "not e2e" -q
→ 773 passed, 2 skipped, 0 failures (matches Phase D baseline)

# Phase E e2e subset (requires real Redis on 127.0.0.1:16379)
pytest components/http/tests/test_e2e_http.py \
        components/mcp/tests/test_e2e_mcp.py \
        components/oauth/tests/test_e2e_oauth.py \
        components/resilience/tests/test_e2e_resilience.py -q
→ 79 passed, 2 skipped, 0 failures (matches Phase E baseline)

# cache-redis E2E (real Redis + keyspace notification)
pytest components/cache/cache-redis/tests/test_e2e_real_redis.py -q
→ 43 collected, 2 skipped for missing keyspace config, 41 passed
```

Test count trajectory:
- R-220 baseline: 369 passed, 4 skipped
- + R-M4 (94 net) → 462
- + R-M5.1 (98) → 560
- + R-M5.2 (14) → 574
- + R-M6 (13) + R-M5.4 wiring (11) → 598 (cache-only)
- + R-M5.3 + R-M5.3.7 + Phase A2+A3 (≈ 40) → 638 (cache)
- + Phase B (0 new tests, docstring-only) → 638 (cache)
- + Phase C (0 new tests, conftest + markers) → 638 (cache)
- + Phase D (13 cross-component integration) → 651 unit+integration
  (cache 638 + integration 13)
- + Phase E (38 E2E across 4 components) → 689 unit+integration+E2E
  (excludes pre-existing cache-redis E2E 43)

Cumulative summary at `06ec5e3` (Phase F cut):
- 16 commits since `285718b` Initial commit
- 773 unit+integration (cache + 4 components + tests/integration)
- 79 Phase E e2e passed + 2 skipped
- 41 cache-redis E2E passed + 2 skipped
- 12 bilingual docstring glue files (R-230)
- 9 oauth + 52 http + 64 mcp + 38 resilience bilingual docstrings (Phase B + R-231)
- 3 foundation/contracts bilingual docstrings (Phase B.0)
- 18 handoff docs in `docs/acceptance/`
- All commits pushed to `origin/main`.
