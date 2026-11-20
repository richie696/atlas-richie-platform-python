# 未完成工作清单

> 截至 2026-11-20。已完成 66 项任务、72 个登记包（70 个 workspace 成员）。本清单只列**未完成**项。
> 优先级：P0 需你决策（阻塞）· P1 高价值缺口 · P2 剩余 provider · P3 未移植组件 · P4 技术债。
> 规模：S（<半天）· M（1–2 天）· L（>2 天，建议单独立项）。
> 原则：纯算法/契约 core 零第三方依赖；驱动隔离在适配器包；非必要不耦合，必要时桥接。

---

## P0 · 需要你决策（阻塞项）

> 四项均已结项（见下）。P0 不再阻塞后续推进。

- [x] **Redis 密码轮换** —— 用户裁决：**不轮换**（2026-11-18；本机 dev 测试口令，无需轮换）。
  保留已完成的部分：Java 平台仓 `e2ecef2f`、AS 仓 `19cebcc9` 已把口令改为
  `REDIS_PASSWORD` 环境变量取值（`${REDIS_PASSWORD:}`），三仓均无硬编码残留，
  本机 `docker-scripts/redis/redis-local/.env`（0600）为唯一真源。
  **已知并接受的风险**：旧口令仍在私有远端历史中，且实例绑定 `0.0.0.0:16379`
  对局域网可达。若该实例日后要暴露到非本机网络、或私有仓库要转公开，需重新评估。
  **遗留缺口**：注入只做了仓库侧，`~/.zshrc` 未接线 `REDIS_PASSWORD`，
  本机跑 Java/AS 依赖 IDE 运行配置提供该变量（配置默认值为空，缺失会 AUTH 失败）。
- [x] **console 13 个 store 归属** —— 用户裁决：**保持独立，不接入**（2026-11-18）。
  console 是刻意独立的应用（自带 59969 行 src、86 个 persistence 文件），按
  `ARCHITECTURE.md` 的分层（"applications own lifecycle, dependency assembly"），
  持久化生命周期归应用自己管；接进 platform 组件层会把 console 绑进组件发布节奏，
  方向是反的。
  代价已知并接受：13 处 `async_sessionmaker(engine, expire_on_commit=False)` 样板继续
  分散（`expire_on_commit=False` 这类语义散落 13 处）。
  保留的可选动作：若 console 出现"写业务表 + 同事务写事件"的场景，可**复制 outbox 的
  写法**（复制模式不产生依赖）。
- [x] **`sentinel-source-redis` 139M 未跟踪目录处置**（S）—— 用户裁决：**删除**（2026-11-18）。
  已删。核查依据：该包在 M6.2 即被取消（`components/sentinel/docs/guide/使用手册.md`
  记「sentinel-source-redis 已删除 (M6.2 取消, 不在 1.0)」），本仓 pyproject /
  versions.toml / uv.lock 均未登记，全仓无代码引用；目录内只剩一个 139M 的 `.venv`
  与一个孤立的 `.pyc`，无任何源码。删除后 `uv sync --frozen` 与三项门禁均正常，
  sentinel 各包测试无连带影响。
- [x] **Java `LocalComposeDefaults.MYSQL_PASSWORD` 硬编码**（S，安全）—— 用户裁决：**暂不处理**（2026-11-19）。
  `wjy123456` 明文在 Java main 代码。同类凭证问题，不在 Python 仓范围，本轮不动 Java 仓代码。
  **决策已结，残余风险仍在**：该口令随 Java 仓源码分发。触发重评的条件——Java 仓
  转为公开、或该口令在非 dev 环境被复用。届时改为环境变量注入 + 随附 `.env.example`。

---

## P1 · 高价值缺口（审计发现，可移植）

### vector（RAG 链已通，缺这些更完整）
- [x] **投影版本 / manifest 与 bulk 批量入库**（M）
  投影状态机、版本→vectorId manifest、延迟清理 outbox 落在
  `atlas-richie-vector-persistence-sqlalchemy`；bulk 管线以可观测事件流驱动写入。
- [ ] **topology runtime / bootstrap / registry**（M）
  多 Store 命名拓扑、连接注册表、启动编排。Java 零 Spring 部分可移植。
  目前只能单 Store，无法按名路由多库。
- [ ] **rerank 模型绑定**（M，需驱动）
  `Reranker` SPI 已定义、`SearchOptions.rerank` 已消费，但无具体重排模型适配器。
- [ ] **diagnostics**（S）
  `VectorHealthReport` / 分类错误 / 健康快照，纯算法。

### statemachine
- [ ] **定义加载（YAML/JSON）**（M）
  目前机器只能 Python 代码定义；Java 有 YAML/JSON loader + 定义注册表。
- [ ] **异步批量 DB 落库**（M，吞吐优化）
  同步持久化已交付（#47）；Java 的 AsyncThreadStorageManager 批量 flush/去重/重排队
  是性能优化，正确性已覆盖，有真实负载再做。
- [ ] **registry 完整面 + 执行超时监控**（S）
  remove/contains/getNames/clear；executionTimeoutMs 慢 guard 监控。

### persistence
- [ ] **数据安全护栏**（M）
  乐观锁、批量更新行数上限、BlockAttack（禁全表 update/delete）、分页排序映射。
  机制是 MyBatis 特有，护栏语义可移植。
- [ ] **多组件 changelog 聚合**（S）
  对位 liquibase 的 ChangeLogRegistry + 通配解析 + 启动 dry-run。

### cache
- [x] **L1 统计 / read-through / write-through**（M）
  CacheDefinition 丢了 statisticsEnabled/storeByValue/readThrough/writeThrough/
  cache2kRefreshAhead 字段，相应能力缺失。
  → 已补齐：`CacheDefinition` 补 7 个字段 + `LocalCacheProperties` 补对应
  `default_*`；`cache-core` 内建统计（命中/未命中/读写/删除，且"过期淘汰"与
  "容量淘汰"分开计数）、按值存储、read-through（同一 key 的并发未命中合并为
  一次回源）、write-through（先改缓存再调写入器，与 JSR-107 同序）、refresh-ahead
  （后台续命，保留原 TTL 时长滑动过期）。
  逐行核对 Java `LocalCacheAutoConfiguration` 后确认这 5 个字段都被真实消费，
  不是死字段，值得移植。
  loader/writer 改为**注册可调用对象**（Python 无"按类路径字符串反射"惯用法），
  Java 的 `cacheLoaderClassName`/`cacheWriterClassName` 因此无对位字段。
  三处**刻意差异**已写进类文档与 README：`store_by_value` 默认 True、
  `refresh_ahead` 去 `cache2k` 前缀、`refresh_ahead_ratio` 为 Python 自定义。
- [x] **审计 / 软删字段自动填充**（M）
  core 出策略、SQLAlchemy 出列默认值；判定只有一份，adapter 全部回调 core。
- [x] **防雪崩 jitter 接线**（S）
  `get_random_extra_millis` 已实现但零调用；Java 在多处 set TTL 时叠加随机抖动。
  → 已接线：`cache-core` 的 `CacheFunction.get_random_extra_millis()` 成为全平台
  唯一抖动实现，`cache-redis` 三个 manager 各自的本地副本删除（分布顺带回归
  Java 的离散整分钟档：`nextInt(1, 11) * 60_000`）。逐行核对 Java 13 处调用点后，
  补齐 Python 侧缺的 5 处：String / Set / Hash 的 `*_with_lock` 回写路径 + 
  `RedisKeyManager.setExpiredTime`。
  两处**刻意不抖动**（都不是缓存条目）：底层 `ValueOps` op（`set_with_ttl` 等）、
  M5.7 负缓存标记（短抑制窗口，必须准点过期）。
- [x] **perf guard 命令复杂度分级表**（S）
  RedisOperationCatalog/ComplexityTier + String payload 形状规则（拒绝整集合塞 String）。
  → 已补齐：新增 `cache-redis.perf` 子包，1:1 对位 Java `redis/perf`——
  `RedisComplexityTier`（5 档）/ `RedisCommandMeta`（分级 + BIGKEY 探测建议）/
  `RedisOperationCatalog`（26 条预设）/ `RedisStringPayloadInspector`（形状判定）。
  `RedisPerfGuard` 补 `check_operation_tier`（白名单 → 非 O(1) 告警 →
  禁用档拦截，顺序同 Java `executeInternal`）与 `check_string_write_payload`。
  分级预设接到 12 个 manager 的 28 个调用点、形状检查接到 4 个 String 写入点
  （对位 Java 34 处）。此前 Python 侧 `check_complexity` 零调用、8 个 manager
  未注入 perf（registrar 里写明"延后到后续里程碑"）——本轮一并补上，
  catalog 没有死预设。
  两处**刻意差异**：Python 侧把策略判定与计时拆开（判定走
  `check_operation_tier`，计时仍由 `time_op` 承担）；形状检查必须拿
  **序列化前**的原始值——Java 的 `guardStringPayload` 拿到的是 `Object value`，
  Python 若沿用"先 `encode_value` 再检查"会丢掉集合形状，只剩弱启发式。
- [x] **多 Redis 实例前缀路由**（M）
  MultiRedisTemplate 的 prefix→instance 路由。
  → 已补齐：core 出路由契约（``cache_core.routing``：``CacheRouteKey`` 解析 /
  ``CacheRouteRegistry`` 前缀表 / ``CacheRouteError``，零第三方依赖），redis 侧出
  连接与转发（``cache_redis.routing``：``RedisCommandKeySpecTable`` 命令 key 位置表
  130+ 条、``RedisRoutingClient`` 路由 + key 改写、``RedisRoutingPipeline`` 按实例分组、
  ``MultiRedisDistributedCache`` 统一入口）。``RedisCacheProperties.slaves`` 提供配置面
  （对位 Java ``AtlasRedisProperties.slaves``），registrar 按配置装配主实例 + 从实例
  ——16 个 manager **零改动**即享受路由（对位 Java「业务无感」）。
  逐行核对 Java ``MultiRedisTemplate`` + ``RedisBaseAutoConfiguration.createRedisTemplate``
  后确认前缀路由是真实能力（路由表配置期静态装配），值得 1:1 对位。
  四处**刻意差异**：①Java 按第一个 key 选实例后把其余 key 剥前缀一起发过去
  （跨实例 key 会被**静默写错实例**），Python 直接报错；②Java API 面封闭，
  不存在「未知命令」，Python strict 模式下未登记命令**直接拒绝执行**（否则 key
  被静默写进主实例）；③路由表拆成「前缀→实例名」（core）与「实例名→连接」
  （redis）两半，可运行时增删（Java 只能配置期装配）；④派生 key（锁 / meta /
  负缓存标记）经 ``decorate_key()`` 继承路由前缀，保证与原 key 同实例。
  PUBLISH / 订阅一律走主实例（Java 端同样未覆写 publish）。
  98 条新测试，含一条**静态扫描守卫**：仓内 manager 用到的每条 redis-py 命令
  都必须在命令 key 位置表里登记，否则路由会漏掉它。

### web
- [x] **组合请求上下文 / 过滤决策 SPI**（M）
  WebRequestContext/WebFilterDecision/拦截器链——目前 guard 各自为政，缺统一决策事件。
  → 已补齐：新增 `web_protection.spi` 子包（`WebRequestContext` 契约 /
  `WebFilterDecision` 四字段不可变事件 / `WebInterceptor` + `WebInterceptorChain` /
  `DefaultWebInterceptorChain` / `MutableWebRequestContext` / attribute 常量），目录
  结构 1:1 对位 Java `web.core.spi` + `spi/support`；新增 `web_protection.interceptors`
  把 9 个 guard 包成拦截器（对位 Java `protection` 包），ASGI 中间件改**链驱动**
  （装配 ctx → 驱动链 → 短路按 ctx 的 status/headers/body 写回 → 否则调 app）。
  短路语义 1:1：标记 `mark_short_circuit` 且**不**调 `chain.proceed(ctx)`，异常由
  适配层兜底 5xx；「先触发者为准」由链短路天然保证。决策事件**双写**：ctx attribute
  （统一为 `platform.web.filter-decision`）+ 可选 `WebDecisionSink`（Java 走 HookBus，
  属本段「hook bus」那一项）。跨拦截器标志沿用 Java 的 attribute 自查模式，长连接
  旁路从「提前 return」改为「打标志 + 后续拦截器自查跳过」，`platform.web.*` 取值
  与 Java 逐字一致。
  五处**刻意差异**：①决策 attribute 统一（Java 每个拦截器各自一个名字，BACKLOG
  要的正是「统一决策事件」）；②限流 reason 保留 guard 细分粒度（Java 固定
  `rate_limit.exceeded`）；③网关身份可配置（Java 硬编码不可关，默认头名一致）；
  ④熔断拦截器未移植（状态机不属于请求级 guard）；⑤登录结果学习仍在适配层
  （Java 靠 `RequestLifecycleHookInterceptor`）。ASGI 拒绝字节与改造前逐字节一致；
  另修「header 单字符串值被按字符拆开」的静默坑。97 条新测试，web 套件 204 → 301。
- [x] **trace 归一化**（S）
  TraceIdParser：traceparent / X-Request-Id 归一。
  → 已补齐：新增 `web_protection.tracing` 模块，1:1 对位 Java `web.core.tracing`——
  `TraceIdParser`（纯算法：`traceparent` → `X-Request-Id` → 自生成 UUID v4，
  一律归一成 32 位 hex）与 `TraceIdInterceptor`（写 `ctx.trace_id` + 响应头
  `X-Trace-Id`，`ORDER=50` 排链首，对位 Java `OtelTracingInterceptor`）。
  ASGI 中间件默认装配该拦截器（`enable_trace_id=False` 可关），且响应头在
  **正常与短路两条路径**都写回 —— Java 侧只在短路路径写 ctx 响应头、正常路径
  靠容器层 `TraceIdInjectValve` 注入，而 Python 的 ASGI 中间件就是容器层。
  四处**刻意差异**：①类名取 `TraceIdInterceptor`（Java 那个 `Otel...` 前缀名
  不副实，本移植无 OTel 依赖）；②Java README 写的 `tracing.prefer-w3c` 开关在
  Java **源码里并不存在**，本移植对位源码；③`String.trim()`/`isBlank()` 换成
  ASCII 空白裁剪；④同名响应头以平台为准，线上 `X-Trace-Id` 恒等于
  `ctx.trace_id`。另注 Java 的 web trace 拦截器是**旧路径**（有 observability
  starter 时不装配），Python 仓尚无 observability 组件，该互斥规则届时沿用。
  46 条新测试，web 套件 301 → 347。
- [x] **降级策略 / 看门狗 / hook bus / 热更新注册表**（M）
  degrade/watchdog/hook/reload 四组 SPI，纯算法。
  → 已补齐：新增 `web_protection.degrade` / `.hang` / `.hook` / `.reload`
  四个子包，四组**框架无关** SPI，逐类对位 Java `web.core.degrade` / `.hang` /
  `.hook` / `.reload`。
  **degrade**：`Trigger`（EXCEPTION / HIGH_LATENCY / CUSTOM）/ `DegradeStrategy` /
  `DegradeResult`（状态码必须在 100–599，body 与策略名非空）/ `DegradeStrategyRegistry`
  + 默认实现（按 order 升序、同名按 name）/ `DegradeConfig`（`DegradeProperties`
  的纯 dataclass 版）/ `DegradeEvaluator`（识别触发 → 选策略 → 生成响应）；
  **hang**：`HangEvent`（栈帧上限 50）/ `WatchdogScheduler`（3 守护工作线程 +
  1 守护定时线程，`WatchHandle` 可取消，`shutdown()` 幂等）/
  `HangDetectionInterceptor`（三档 warn / dump / kill_switch，每档每次请求只触发
  一次）；**hook**：`HookEvent` 标记基类 + `RequestCompletedEvent` + `HookBus` /
  `DefaultHookBus`（同步发布、异常隔离、按**精确类型**分发）；**reload**：
  `Reloadable` + `ReloadEvent` + `HotReloadRegistry` / 默认实现（reload 时
  `current_state()` → `accept(state)`，带 bus 时发布 `ReloadEvent`）。
  ASGI 适配层新增三个可选接线：`hook_bus`（请求结束时派发
  `RequestCompletedEvent`，对位 Java `InterceptingFilter` 的 finally 块）、
  `degrade_evaluator`（在下游调用前后求值）、`extra_interceptors`（自建拦截器
  拼进平台链尾，`HangDetectionInterceptor` 的天然位置）。
  七处**刻意差异**：①**降级落点** —— Java 的 `DegradeInterceptor` 是链元素
  （链尾就是业务执行），Python 的链在 app **之前**跑完、链内拦截器看不到业务
  结果，故拆成框架无关的 `DegradeEvaluator` 由适配层在「包住 app 调用的位置」
  驱动；代价是判定期间下游响应被**缓冲**，响应不再流式（SSE / 长轮询不要纳入
  降级范围）；②**降级 body** 形状与 Java 的 `ApiResult.error(code,msg).toJson()`
  一致，但不依赖 `ApiResult` 契约类；③**Bean 反射兜底**（`fallbackBean` /
  `fallbackMethod`）未移植 —— Python 没有「按 bean 名反射」的惯例，改为注册一个
  `DegradeStrategy`；④**全局兜底**在 Java 源码里走不到（没有路由命中时判定器
  提前返回，是死代码），本移植加 `require_route_match=False` 开关让它可用，
  **默认值仍与 Java 一致**；⑤**看门狗 kill 档**的 `Thread.interrupt()` 无对位
  —— CPython 没有安全的线程中断手段，改为可选 `kill_interrupter` 回调（默认关，
  只记录不中断）；⑥**看门狗栈捕获**修正了 Java 差一个线程的问题（Java 拿到的是
  看门狗自己的栈）；⑦**事件总线**默认不创建（Java 的 `InterceptingFilter` 总是
  建一个），空 bus 每个请求也要查一次字典。另补齐 Ant `**` 零段匹配（Java 的
  `/api/**` 能匹配 `/api`，仓内既有的 `ant_pattern_to_regex` 不行）。
  92 条新测试，web 套件 347 → 439。

### desensitize
- [x] **MDC / 日志记录拦截**（S）
  JSON 消息脱敏已交付（#52）；MDC 上下文字段脱敏（SensitiveMdcTurboFilter 等价）未做。
  → 已补齐：新增包 `atlas-richie-desensitize-logging`，1:1 对位 Java
  `cn.richie696.component.desensitize.logging`（Java 侧是独立于 core 的第三个
  Maven 模块，Python 侧同样是独立包，依赖 desensitize-core、零第三方依赖）。
  落地：`MdcContext`（MDC 上下文）、`LoggingMaskingService` /
  `DefaultLoggingMaskingService`（脱敏 SPI）、`SensitiveMdcFilter` /
  `SensitiveLogArgFilter`（两个拦截点）、`MdcFormatter` + `mdc_of()`。
  Python 侧补齐了 Java 由 Logback 提供的三块地基：MDC（ThreadLocal →
  `contextvars.ContextVar`，asyncio 任务共用线程，ThreadLocal 会串味）、拦截点
  （TurboFilter → 标准库 `logging.Filter`，同样在 `Formatter.format()` 之前）、
  MDC 渲染（`includeMdc` → `MdcFormatter`）。
  六处**刻意差异**：①默认**不改写上下文**（Java 把脱敏值写回 MDC 且不还原，同线程
  后续日志永远是脱敏值），本移植默认只把脱敏快照挂到 `record.mdc`，
  `in_place=True` 可复刻 Java 行为；②脱敏服务**注入**（Java 是静态全局 +
  未初始化抛 `IllegalStateException`，Python 的 core 没有全局运行时）；
  ③`maskMdc` 失败捕获范围更宽（捕获任何异常并回退原值，脱敏不得打断日志链路）；
  ④`toMaskedMessage` 入参从 `ILoggingEvent` 换成 `logging.LogRecord`；
  ⑤无自动装配（Java 有 `LoggingDesensitizeAutoConfiguration`）；
  ⑥`SensitiveLogArgFilter` 是双保险（`SensitiveLogArg.__str__` 本身已脱敏），
  其价值在于让 `record.args` 不再持有敏感对象。
  38 条新测试，desensitize 套件 127 → 165。
- [x] **清理过期 docstring**（S）
  service.py / registry.py 头部声称未移植但实际已存在的功能。
  → 已补齐：清掉 4 处过期声明——`desensitize-core/service.py` 的模块 docstring
  说 `ObjectMaskingService` / `SafeLogSerializer` 未移植（两者都在
  `serializer.py` 且已从包导出）；`desensitize-core/registry.py` 的模块
  docstring 与 `resolve_field_type` docstring 说「注解驱动的字段解析未移植」
  （实际以 dataclass field metadata 形态落在 `support.py` + `serializer.py`，
  registry 只负责 `properties.fields` 显式映射那条路径）；
  `desensitize-core/README.md` 的 Scope 段仍把 logging 适配模块列为未移植
  （本轮已交付 `atlas-richie-desensitize-logging`）。真正仍未移植的只剩
  静态 `DesensitizeUtils` 全局绑定与 log/exception 的正则兜底——文档里保留
  了这条声明。

### document-parser
- [ ] **ParserProperties 配置面**（S）
  maxSegmentCharacters 默认 16KiB（目前 unbounded）等旋钮。
- [ ] **Read* 流式 API 对齐**（M）
  ReadEvent/ReadResult/ReadSummary/ReadListener 与 ParseEvent 的完整对位。

### storage-core
- [ ] **checksum / storage-class 面**（S，需驱动）
  ObjectStat 缺 CRC32/SHA256/storageClass；DirectUploadRequest 缺 expected size/MIME/checksum。

### tenant
- [ ] **SQL 自动 ORM 拦截**（M，**需先定义 ORM 模型**）
  do_orm_execute 自动注入租户谓词。目前交付显式助手（#56），自动拦截待平台有模型。
- [ ] **tenant-gateway 模块**（M）
  网关侧租户过滤 / token 吊销 / 过期通知 SPI。
- [ ] **租户开通 / 迁移管理**（L）
  provisioning/migration/状态机 reconcile，MyBatis+Vault 绑定，建议单独立项。

### concurrency
- [ ] **StructuredConcurrency 形态的 async facade**（M）
  gather_all/race/with_deadline/gather_batched 映射到 asyncio.TaskGroup。
- [ ] **CircuitBreaker 增量**（S）
  时间滑动窗口、forceOpen、同步 execute(task, fallback)（sentinel 已有 CB 基础）。

---

## P2 · 剩余 provider（按真实需求逐个接，每个 S–M）

### storage（已交付 core / s3 / local；剩 10）
- [ ] minio（S，可复用 s3 适配器，force_path_style）
- [ ] oss（阿里云）· [ ] cos（腾讯）· [ ] obs（华为）· [ ] tos（火山）· [ ] ks3（金山）
- [ ] azure blob
- [ ] ftp · [ ] sftp · [ ] smb（需各自驱动）

### vector（已交付 core / pgvector / chunk-adapter；剩 9）
- [ ] redis（RediSearch）· [ ] milvus · [ ] qdrant · [ ] weaviate
- [ ] neo4j · [ ] mongodb-atlas · [ ] dashvector · [ ] vikingdb · [ ] tencent-vectordb

> 每个 provider 需：能力声明 + 分数语义 + ACL 下推 + 真实后端集成测试（干净 skip 门禁）。
> 本机已有 milvus（19530）/ qdrant / weaviate / neo4j 容器可复用。

---

## P3 · 完全未移植组件（建议按需求立项，L）

- [ ] **ocr**（10 模块）——与 document-parser 纯图 PDF 直接相关，补上 RAG 才能处理扫描件。
  需 OCR 驱动（paddle/tesseract/云 OCR）。core 2176 行可先移植。
- [ ] **messaging-core**（2077 行）——12 个 provider 在 Java 侧本就是 20 行空壳，
  只有 core + pulsar(85) 有实质内容。
- [ ] **i18n**（712 行）
- [ ] **logging**（2294 行）
- [ ] **observability**（6 模块）
- [ ] **mongodb**（3907 行）
- [ ] **nats**（6545 行）· [ ] **mqtt**（13786 行）
- [ ] **grpc**（2155 行）
- [ ] **ai**（18356 行，最大模块）
- [ ] **microservice**（1140 行）
- [ ] **dao / liquibase 编排**（部分已被 persistence 覆盖，剩多组件聚合）

---

## P4 · 技术债 / 已知限制

- [ ] **cache 5 项 keyspace 通知测试满负载下不稳定**（S）
  测试自身注释承认 Redis activeExpireCycle 采样窗口问题；conf 已开 KEA。
  需查清是测试时序还是监听器问题（非环境性 CONFIG 禁用——conf 里 KEA 已开）。
- [ ] **streammq wire format 与 Java 不兼容**（已知取舍，非缺陷）
  Java 写单字段 `data`=Base64(JSON)，Python 写 `body`/`type`/`business_id`。
  你批准的「Python 原生核心」决定的后果：混编舰队无法互消费，也断掉 Java
  statemachine 状态同步流。若要互通需加兼容层（M）。
- [ ] **streammq metrics / health / admin / tracing**（M）
  README 标注刻意延后；backlog() 是唯一存活面。
- [ ] **document-fetcher DNS rebinding 窗口**（M，安全加固）
  校验与建连之间解析可能不同；彻底消除需把连接钉在校验过的 IP（自定义 transport）。
- [ ] **desensitize CUSTOM/customStrategy 死字段**（S）
  Java 侧也是死的，可清理或实现。
- [ ] **若干过期 docstring**（S）
  statemachine-redis/README「persistence 尚不存在」已过期；cache 测试 ACCESSED 说明等。

---

## 建议推进顺序

1. **P0 已清**：Redis 轮换与 console 归属均已裁决结项。
2. **P1 里挑已解锁的**：tenant SQL 自动拦截（需先定 ORM 模型）。
   （vector 投影版本 / bulk 管线已交付，见 CHANGELOG。）
3. **P2 按真实用到的 provider 接**，不要一次全接（每个都要真实后端测试）。
4. **P3 按业务需求立项**，ocr 与 RAG 链关联最紧。