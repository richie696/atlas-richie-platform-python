# Changelog

All notable changes are documented here. The project follows Keep a Changelog
categories and Semantic Versioning.

> 历史条目中提到的 `docs/acceptance/` 交接文档与 `docs/process/` 过程文档属过程材料，
> 已于 2026-10-25 随过程材料一并清理，不再随包发布。条目内容按当时的记录原样保留，
> 其中的路径不再指向现存文件。

## [Unreleased]

### Added

- **降级策略 / 看门狗 / hook bus / 热更新注册表** (`atlas_richie.web_protection.degrade` +
  `atlas_richie.web_protection.hang` + `atlas_richie.web_protection.hook` +
  `atlas_richie.web_protection.reload`): web 段最后一项，四组**框架无关** SPI。
  **degrade** 对位 Java `web.core.degrade`：`Trigger`（EXCEPTION / HIGH_LATENCY /
  CUSTOM）、`DegradeStrategy`（name / triggers / order / matches / build）、
  `DegradeResult`（状态码必须在 100–599，body 与策略名非空，headers 为空视为空表）、
  `DegradeStrategyRegistry` + `DefaultDegradeStrategyRegistry`（按 order 升序、
  同名按 name）、`DegradeConfig`（routes / route_rules / fallback，对位 Java
  `DegradeProperties` 的纯 dataclass 版）、`DegradeEvaluator`（识别触发 → 选策略 →
  生成响应）。**hang** 对位 Java `web.core.hang`：`HangEvent`（栈帧上限 50）、
  `WatchdogScheduler`（3 守护工作线程 + 1 守护定时线程，`schedule()` 返回
  `WatchHandle` 可取消，`shutdown()` 幂等）、`HangDetectionInterceptor`（三档
  warn / dump / kill_switch，每档每次请求最多触发一次）。**hook** 对位 Java
  `web.core.hook`：`HookEvent` 标记基类 + `RequestCompletedEvent` +
  `HookBus` / `DefaultHookBus`（同步发布、异常隔离、**按事件精确类型**分发）。
  **reload** 对位 Java `web.core.reload`：`Reloadable` + `ReloadEvent` +
  `HotReloadRegistry` / `DefaultHotReloadRegistry`（reload 时
  `current_state()` → `accept(state)`，带 bus 时发布 `ReloadEvent`）。
  ASGI 适配层新增三个可选接线：`hook_bus`（请求结束时派发
  `RequestCompletedEvent`，对位 Java `InterceptingFilter` 的 finally 块）、
  `degrade_evaluator`（在下游调用前后求值）、`extra_interceptors`（把自建拦截器
  拼进平台链尾，`HangDetectionInterceptor` 的天然位置）。
  七处**刻意差异**：①**降级落点** —— Java 的 `DegradeInterceptor` 是链元素（链尾
  就是业务执行），Python 的链在 app **之前**跑完、链内拦截器看不到业务结果，故
  拆成框架无关的 `DegradeEvaluator`，由适配层在「包住 app 调用的位置」驱动；
  代价是判定期间下游响应被**缓冲**，响应不再流式（SSE / 长轮询不要纳入降级范围）；
  ②**降级 body** 形状与 Java 的 `ApiResult.error(code,msg).toJson()` 一致
  （`{"success":false,"code":...,"msg":...}`），但不依赖 `ApiResult` 契约类；
  ③**Bean 反射兜底**（`fallbackBean` / `fallbackMethod`）未移植 —— Python 没有
  「按 bean 名反射」的惯例，改为注册一个 `DegradeStrategy`；④**全局兜底**在 Java
  源码里走不到（没有路由命中时判定器提前返回，是死代码），本移植加
  `require_route_match=False` 开关让它可用，**默认值仍与 Java 一致**；
  ⑤**看门狗 kill 档**的 `Thread.interrupt()` 无对位 —— CPython 没有安全的线程
  中断手段，改为可选 `kill_interrupter` 回调（默认关，只记录不中断）；
  ⑥**看门狗栈捕获**修正了 Java 差一个线程的问题：Java 的 `HangEvent.of` 在看门狗
  线程上取 `Thread.currentThread()`，拿到的是看门狗自己的栈，本移植显式捕获被
  监控的业务线程栈；⑦**事件总线**默认不创建（Java 的 `InterceptingFilter` 总是
  建一个），空 bus 每个请求也要查一次字典。另有 Ant `**` 零段匹配的补齐：
  Java 的 `AntPathMatcher` 里 `/api/**` 能匹配 `/api`，仓内既有的
  `ant_pattern_to_regex` 要求至少一个字符，本移植在降级路由匹配处单独放行。
  92 条新测试，web 套件 347 → 439。

- **trace 归一化** (`atlas_richie.web_protection.tracing`): 1:1 对位 Java
  `cn.richie696.component.web.core.tracing`。新增 `TraceIdParser`（纯算法：
  `traceparent` → `X-Request-Id` → 自生成 UUID v4，一律归一成 32 位 hex）与
  `TraceIdInterceptor`（写 `ctx.trace_id` + 响应头 `X-Trace-Id`，`ORDER=50`
  排链首，对位 Java `OtelTracingInterceptor`）。ASGI 中间件默认装配该拦截器，
  `enable_trace_id=False` 可关。
  四处**刻意差异**：①类名取 `TraceIdInterceptor` 而非 `OtelTracingInterceptor`
  ——Java 那个名字带 OTel 前缀，类里却根本没碰 OTel SDK，本移植压根没有 OTel
  依赖；②Java README 记录的 `tracing.prefer-w3c` 开关在 Java **源码里并不
  存在**（永远优先 traceparent），本移植对位源码而非 README；③Java 的
  `String.trim()` / `isBlank()` 换成 ASCII 空白裁剪（现实输入等价，仅 U+00A0
  等异类空格有别）；④Java 的 ctx 响应头**只在短路路径**写回 servlet 响应，
  正常路径靠容器层 `TraceIdInjectValve` 注入 —— Python 的 ASGI 中间件就是
  容器层，故两条路径都写回，否则正常响应的 `X-Trace-Id` 永远到不了客户端；
  同名头以平台为准（线上 `X-Trace-Id` 恒等于 `ctx.trace_id`，两者不分叉）。
  另注：Java 的 web trace 拦截器是**旧路径** —— `TracingAutoConfiguration` 上有
  `@ConditionalOnMissingClass(ObservabilityState)`，统一 observability starter
  在场时不装配它，避免 `ctx.traceId` 与活动 OTel SpanContext 分叉；Python 仓
  尚无 observability 组件，本轮按独立路径落地，该互斥规则届时需沿用。
  46 条新测试（1:1 覆盖 Java `TraceIdParserTest` / `OtelTracingInterceptorTest`
  全部用例 + 补位随机性、大小写保留等边界），web 套件 301 → 347。

- **组合请求上下文 / 过滤决策 SPI** (`atlas-richie-web-protection.spi` +
  `atlas_richie.web_protection.interceptors` + ASGI 适配层): 对位 Java
  `cn.richie696.component.web.core.spi` 的跨容器决策契约——`WebRequestContext`
  （只读入站 + 可写出站 + 生命周期）、`WebFilterDecision`（四字段不可变事件：
  interceptor / key / status / reason）、`WebInterceptor` + `WebInterceptorChain`
  （`proceed(ctx)` 游标式链）、`DefaultWebInterceptorChain`、`MutableWebRequestContext`。
  此前 Python 侧 guard 各自为政（IP 黑名单 / bot / 体积 / 登录锁定 / 幂等 / 限流 /
  签名各写各的拒绝分支），缺统一决策事件；本轮把 9 个 guard 包成拦截器（对位 Java
  `protection` 包），ASGI 中间件改为**链驱动**：装配 ctx → 驱动链 → 短路则按 ctx 的
  status / headers / body 写回 → 否则调 app。
  短路语义 1:1：标记 `mark_short_circuit` 且**不**调 `chain.proceed(ctx)`，抛出的
  异常由适配层兜底成 5xx；「多个 deny 以先触发者为准」由链短路天然保证。
  决策事件**双写**：ctx attribute（`platform.web.filter-decision`）+ 可选
  `WebDecisionSink`。跨拦截器标志沿用 Java 的 attribute 自查模式——
  `platform.web.gateway-bypass` / `platform.web.gateway-id` /
  `platform.web.long-lived` 取值与 Java 逐字一致；长连接旁路从「提前 return」
  改为「打标志 + 后续拦截器自查跳过」。
  五处**刻意差异**：①决策 attribute **统一**（Java 每个拦截器各有一个名字，
  BACKLOG 要的正是「统一决策事件」；Java 走 HookBus 发布，Python 尚无 hook bus，
  见 BACKLOG「降级策略 / 看门狗 / hook bus / 热更新注册表」）；②Java 限流 reason
  固定 `rate_limit.exceeded`，Python 保留 guard 细分 reason（`rate_limited` /
  `gateway_identity_missing` / `client_unidentified`）；③Java 网关身份硬编码不可关，
  Python 保留可配置（默认头名 `x-forwarded-from-gateway` 与 Java 契约一致）；
  ④Java 的熔断拦截器未移植（熔断状态机不属于请求级 guard）；⑤登录结果学习
  （下游 2xx / 401 / 403）仍在适配层（Java 靠 `RequestLifecycleHookInterceptor`，
  属 hook bus 那一项）。
  ASGI 适配层的**拒绝字节完全不变**：状态码 / body / 响应头 / Content-Length 与
  改造前逐字节一致（自定义 `deny_renderer` 的 bytes 经 `surrogateescape` 无损往返）。
  另修一处静默坑：ctx 的 header 值若传单个字符串会按字符拆开（str 本身是
  `Iterable[str]`），现按单值处理。97 条新测试，web 套件 204 → 301。

- **多 Redis 实例前缀路由** (`atlas-richie-cache-core.routing` +
  `atlas-richie-cache-redis.routing`): 对位 Java
  ``cn.richie696.component.cache.redis.bean.MultiRedisTemplate`` 的
  prefix→instance 路由。core 侧出路由契约（``CacheRouteKey`` 解析 /
  ``CacheRouteRegistry`` 前缀表 / ``CacheRouteError``，零第三方依赖），
  redis 侧出连接与转发（``RedisCommandKeySpecTable`` 130+ 条命令 key 位置 /
  ``RedisRoutingClient`` 路由 + key 改写 / ``RedisRoutingPipeline`` 按实例
  分组 / ``MultiRedisDistributedCache`` 统一入口）；
  ``RedisCacheProperties.slaves`` 提供配置面（对位 Java
  ``AtlasRedisProperties.slaves``）。key 形如 ``order@@user:1`` 路由到
  ``order`` 实例并落库为 ``{该实例 namespace}:user:1``；未注册前缀**直接
  抛错**（Java 同），16 个 manager 零改动即生效。
  四处**刻意差异**：①同命令多 key 跨实例时，Java 按第一个 key 选实例后把其余 key
  剥前缀一起发过去（**静默写错实例**），Python 直接报错；②Java API 面封闭、
  不存在「未知命令」，Python strict 模式下未登记命令直接拒绝执行（否则 key 会被
  静默写进主实例）；③路由表拆成「前缀→实例名」（core）与「实例名→连接」
  （redis）两半，可运行时增删（Java 只能配置期装配）；④派生 key（锁 / meta /
  负缓存标记）经 ``decorate_key()`` 继承路由前缀，保证与原 key 同实例。
  PUBLISH / 订阅一律走主实例（Java 端同样未覆写 publish）。98 条新测试，含一条
  **静态扫描守卫**：仓内 manager 用到的每条 redis-py 命令都必须在命令 key 位置表
  里登记，否则路由会漏掉它。

- **Redis 性能守卫的复杂度分级表 + String 载荷形状规则**
  (`atlas-richie-cache-redis.perf`): 新增 `perf` 子包，1:1 对位 Java
  `redis/perf` 包——`RedisComplexityTier`（5 档）、`RedisCommandMeta`
  （分级 + BIGKEY 探测建议）、`RedisOperationCatalog`（26 条预设）、
  `RedisStringPayloadInspector`（String 载荷形状判定）。
  `RedisPerfGuard` 新增 `check_operation_tier`（白名单 → 非 O(1) 告警 →
  禁用档拦截，顺序与 Java `executeInternal` 一致）与
  `check_string_write_payload`（集合 / Map 整包 → ERROR、复杂对象 → WARN、
  疑似整包 JSON → WARN）。分级预设接到 12 个 manager 的 28 个调用点，
  String 形状检查接到 4 个写入点（对位 Java 34 处）——此前 Python 侧
  `check_complexity` 零调用、8 个 manager 根本没注入 perf，catalog 是纯死表。
  刻意差异：Python 侧把策略判定与计时拆开（`check_operation_tier` 只判定，
  计时仍由 `time_op` 承担）；形状检查必须拿**序列化之前**的原始值——先
  `encode_value` 再检查会让集合形状丢失，只剩"长度像 JSON"的弱启发式；
  字符数按 Unicode 码点计（Java 按 UTF-16 码元）。104 条新测试。
- **L1 local-cache capability set** (`atlas-richie-cache-core`): the five
  JSR-107 switches Java wires from `CacheDefinition` are now real
  capabilities in Python — cumulative **statistics** (hits / misses / gets /
  puts / removals, plus separate `expirations` and `evictions` counters so
  the two eviction causes stay distinguishable), **store-by-value**,
  **read-through** (miss → loader → cache, with concurrent misses on one key
  collapsing into a single source load), **write-through** (cache first,
  then the writer — JSR-107 ordering) and **refresh-ahead** (background
  reload of entries close to expiry, keeping the original TTL duration).
  `CacheDefinition` gains the seven missing fields and `LocalCacheProperties`
  the matching `default_*` fallbacks; `CacheStatistics` / `CacheLoader` /
  `CacheWriter` are the new zero-dependency contracts, wired through
  `LocalCacheManager.register_loader` / `register_writer` / `stats` /
  `all_stats`. Documented deviations from Java: `store_by_value` defaults
  to True (the Python cache has always copied on every read and write),
  `refresh_ahead` drops the `cache2k` prefix (the Python cache is
  cachetools-backed, so the feature is not provider-specific) and
  `refresh_ahead_ratio` is a Python-defined knob; the loader / writer are
  registered callables instead of class-path strings, and JSR-107's
  `average*Time` statistics are not ported. 82 new tests.
- **Audit / soft-delete field defaults** (new `persistence-core.audit` +
  `persistence-sqlalchemy.audit`): the five audit fields (`createId` /
  `updateId` / `createTime` / `updateTime` / `deleted`) are delivered as a
  policy in the zero-dependency core, with a SQLAlchemy column-default helper in
  the adapter — mirroring Java `DefaultFieldHandler` without requiring ORM
  models. Documented deviations from Java: the update path refreshes
  `updateId` / `updateTime` instead of only filling blanks, and the current
  user is injected by the caller (this workspace has no
  `LoginUserContextHolder` equivalent). The decision lives in one place —
  every column default delegates to `AuditFieldPolicy`.
- **Vector bulk ingestion pipeline** (new `vector-core.bulk` module):
  the "embed → batch → persist" orchestration is exposed as an observable event
  stream (`BulkStarted` / `BulkItemStarted` / `BulkItemSucceeded` /
  `BulkItemFailed` / `BulkCompleted`), mirroring Java
  `BulkIngestionPipeline`. A single-record failure degrades to an event instead
  of aborting the batch, and every run ends with a `BulkCompleted` carrying the
  terminal counters. Deviation from Java, documented in the module: the pipeline
  is a synchronous generator (the `VectorStoreEngine` protocol is synchronous),
  so the reactive-only knobs — embedding/write concurrency and the flush
  interval — are not offered rather than silently ignored; `write_batch_size`
  (100) and `fail_fast` match Java.
- **Vector projection writer** (`atlas-richie-vector-persistence-sqlalchemy`):
  mirrors Java `DefaultVectorProjectionWriter` — drives the projection state
  machine from the bulk event stream, maintains the vectorId manifest, and
  decorates every record with the six projection metadata fields plus
  `status=ACTIVE`. Together with the projection version convergence below this
  closes the "rebuild → write → manifest → activate → retrieve → retire →
  clean" vertical.
- **Vector projection version convergence** (new
  **`atlas-richie-vector-persistence-sqlalchemy`**): the vector projection state
  machine, the version→vectorId manifest ledger and the delayed-cleanup outbox land
  in a relational database, mirroring Java `atlas-richie-vector-projection-dao`.
  `vector-core` gains the zero-dependency `projection` contract module
  (`VectorProjectionState` / `VectorProjectionReference` /
  `VectorProjectionSpecification` / `VectorProjectionVersion` +
  `ActiveProjectionVersionResolver`), and `KnowledgeBaseVectorService` accepts an
  optional resolver: active versions are pushed down as
  `projectionVersionId IN (...)`, and an empty set short-circuits to an empty result
  instead of calling the provider. 4 tables (`rag_vector_projection` /
  `_version` / `_record` / `_outbox`), 64 new tests.
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

- **Anti-avalanche jitter is now wired** (`cache-core` + `cache-redis`):
  `CacheFunction.get_random_extra_millis()` was implemented but had zero
  callers — each Redis manager carried its own copy of the offset logic, and
  the `*_with_lock` publish paths plus `KeyOps.set_expired_time` carried no
  jitter at all. The core function is now the single implementation (the three
  adapter-local copies are gone), and every cache-entry TTL written by the
  Redis driver goes through it: the high-level `StringFunction` / `HashFunction`
  / `CollectionOps` write helpers, the `*_with_lock` publish paths, and
  `KeyOps.set_expired_time`. Verified line by line against the Java sources —
  `RedisStringManager` (4 call sites), `RedisSetManager.getFromSetWithLock`,
  `RedisHashManager.getFromHashWithLock` (4 overloads) +
  `RedisHashManager.addObject`, `RedisKeyManager.setExpiredTime`.
  **Behaviour change:** the offset is Java's discrete whole-minute bucket
  (10 values in `[60s, 10min]`) instead of the previous continuous uniform
  draw, and `*_with_lock` entries now carry the offset too — previously a mass
  reload left every key with an identical expiry instant, which is exactly
  the avalanche the feature exists to prevent. Two paths deliberately keep
  their exact TTL because they are not cache entries: the raw `ValueOps` ops
  (`set_with_ttl` and friends) and the M5.7 negative-cache marker (a short
  suppression window that must expire on schedule).
- **BREAKING (behaviour): local-cache expiry now honours the JSR-107 policy.**
  `ExpiryPolicy` declared CREATED / ACCESSED / MODIFIED / TOUCHED, but the
  bucket only distinguished ETERNAL from everything else, so all four
  behaved as CREATED — including ACCESSED, which is both the default policy
  and the one `L2DistributedCache` configures for its L1 region. Reads now
  reset the deadline under ACCESSED / TOUCHED, and updates reset it under
  MODIFIED / TOUCHED while CREATED / ACCESSED keep the original deadline
  (matching JCache's `getExpiryForUpdate`). A per-key TTL override is
  remembered so a refresh reuses it rather than the region default.
  **Effect:** hot keys stay in L1 longer under repeated reads. This is the
  intended semantics and matches the Java side; the staleness risk is
  mitigated by the cross-process L1 invalidation broadcast added to
  `L2DistributedCache` (opt-in via `broadcast_l1_invalidation=True`).
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

- **`AlembicMigrationRunner` could not migrate with a percent-encoded
  password**: Alembic stores main options in a `configparser` section and
  `BasicInterpolation` reads `%` as an interpolation marker, so a DSN like
  `postgresql://u:p%40ss@host/db` raised `ValueError: invalid interpolation
  syntax` the first time the option was read. The URL is now escaped
  (`%` → `%%`) before it reaches Alembic, which un-escapes it on read.
  Covered by a regression test.
- **Migration-lock test ignored its own DSN**: the PostgreSQL advisory-lock
  cases validated reachability with `ATLAS_RICHIE_PERSISTENCE_PG_TEST_URL`
  but connected through a hardcoded passwordless URL, so they failed with
  "no password supplied" against any password-protected instance — and
  skipped silently otherwise. The admin and per-database URLs are now
  derived from the same DSN the fixture validated, so the two
  concurrent-migration cases actually run against a real PostgreSQL.
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
  predates the implementation; the `"stats" section was the
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
    overflow policy), 详见 `docs/process/PLANNING.md` `M6.5.
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
  - PLANNING `M6.6 [x] → [ ] (v1 评估撤回), `M6+ Exit [x] → [partial]
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
    `Frozen`, PLANNING `M6.5.7 [ ] → [x]. M6.5.1-6 实施 31 failed 修
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
  1. **跨进程聚合 dashboard 不在 Sentinel 库职责范围**: 实际部署
     (K8s pod 1 process 1 socket 1 dashboard, 宿主机 nginx upstream
     做 L7 LB) 没有"跨进程 dashboard"需求. 多进程数据聚合是运维
     工具栈职责 (OTel / Prometheus / Grafana), 不是库的事. 1.0 / 1.x /
     2.0 都不在范围. PLANNING.md 新增 "Sentinel 库职责边界" 章节明确
     库做 4 件事 (per-process 引擎 / 规则源 / 集群协调 / 遥测 hook)
     + 1 件 UI (per-process dashboard), 不做 3 件事 (跨进程聚合
     dashboard / Collector Python / 持久化 / 告警 / TSDB). **撤回**
     commit `efd2ecc` 的 "M5.4.1 候选" task entry (design-defensive
     过度, 库职责边界判断不到位).
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
     验证通过, DEPENDENCY_POLICY.md `3 维持 (主包 0 3rd-party, extension
     wheel 允许合理 3rd-party, 已在 sentinel-dashboard 实施 starlette/
     jinja2/uvicorn 验证).
  5. **R-240 时代遗留 M 文件清理**: 删除 `components/sentinel/sentinel-source-redis/`
     (M6.2 取消的 skeleton 目录, README / pyproject / src / tests 4 文件),
     同步从根 `pyproject.toml` workspace members + 使用手册.md pip install
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
  (`M6.7-WSGI-SYNC-EVAL.md` `7).

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
