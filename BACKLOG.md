# 未完成工作清单

> 截至 2026-11-19。已完成 62 项任务、71 个登记包（69 个 workspace 成员）。本清单只列**未完成**项。
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
- [ ] **trace 归一化**（S）
  TraceIdParser：traceparent / X-Request-Id 归一。
- [ ] **降级策略 / 看门狗 / hook bus / 热更新注册表**（M）
  degrade/watchdog/hook/reload 四组 SPI，纯算法。

### desensitize
- [ ] **MDC / 日志记录拦截**（S）
  JSON 消息脱敏已交付（#52）；MDC 上下文字段脱敏（SensitiveMdcTurboFilter 等价）未做。
- [ ] **清理过期 docstring**（S）
  service.py / registry.py 头部声称未移植但实际已存在的功能。

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