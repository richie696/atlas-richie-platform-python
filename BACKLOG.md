# 未完成工作清单

> 截至 2026-11-18。已完成 58 项任务、71 个登记包（69 个 workspace 成员）。本清单只列**未完成**项。
> 优先级：P0 需你决策（阻塞）· P1 高价值缺口 · P2 剩余 provider · P3 未移植组件 · P4 技术债。
> 规模：S（<半天）· M（1–2 天）· L（>2 天，建议单独立项）。
> 原则：纯算法/契约 core 零第三方依赖；驱动隔离在适配器包；非必要不耦合，必要时桥接。

---

## P0 · 需要你决策（阻塞项）

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
- [ ] **`sentinel-source-redis` 139M 未跟踪目录处置**（S）
  空壳组件，权限系统曾拦截删除。需你明确授权删除或保留。
- [ ] **Java `LocalComposeDefaults.MYSQL_PASSWORD` 硬编码**（S，安全）
  `wjy123456` 明文在 Java main 代码。同类凭证问题，不在 Python 仓范围，需你定是否处理。

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
- [ ] **L1 统计 / read-through / write-through**（M）
  CacheDefinition 丢了 statisticsEnabled/storeByValue/readThrough/writeThrough/
  cache2kRefreshAhead 字段，相应能力缺失。
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
- [ ] **perf guard 命令复杂度分级表**（S）
  RedisOperationCatalog/ComplexityTier + String payload 形状规则（拒绝整集合塞 String）。
- [ ] **多 Redis 实例前缀路由**（M，需驱动）
  MultiRedisTemplate 的 prefix→instance 路由。

### web
- [ ] **组合请求上下文 / 过滤决策 SPI**（M）
  WebRequestContext/WebFilterDecision/拦截器链——目前 guard 各自为政，缺统一决策事件。
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