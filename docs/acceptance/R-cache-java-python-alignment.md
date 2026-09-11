# atlas-richie-cache: Java→Python 对齐指导

> 来源：`/Users/richie696/Projects/workspace/atlas-richie-platform/atlas-richie-component/atlas-richie-cache`
> 阅读对象：richie696
> 目的：Java 版已经成熟 + 生产验证过；Python 版尚未起步。本文档先列 Java 的设计事实，再映射到 Python 生态的最佳替代品，**等你过目后再决定 Python cache 组件的最终 scope**。

---

## A. Java 版全景

### A.1 包结构（112 个 .java，约 12000 行）

```
cn.richie696.component.cache
├── bloom/            # Redisson + Guava 两种 Bloom Filter 实现
├── commons/          # CacheKeyUtils、GeoPointResult
├── config/           # @ConfigurationProperties + Spring Boot 装配
├── enums/            # CacheProvider / KeyTypeEnum / L2CachingRegion
├── function/         # 11 个 *Function 接口（门面，不绑实现）
├── local/            # JSR-107 本地缓存（Caffeine / Ehcache / cache2k）
│   ├── config/       # LocalCacheProperties、CacheDefinition、AutoConfiguration
│   ├── enums/        # CacheProvider、ExpiryPolicy
│   ├── manage/       # LocalCache、LocalCacheManager、ExpiryWrapper
│   └── util/         # DefensiveCopyUtils
├── operations/       # BoundedList(BoundedQueue/BoundedStack) + Lua scripts + CapacityLimits + ElementConverter
├── ops/              # 16 个 *Ops 接口（API 表面，绑定到 redis.manage.Manager）
│   └── impl/         # 11 个 *OpsImpl（Spring 装配时的实现）
├── redis/            # 真正的 Redis 客户端 + 治理层
│   ├── bean/         # MultiRedisTemplate、MultiStringRedisTemplate
│   ├── config/       # RedisAutoConfiguration
│   │   └── base/     # AtlasRedisProperties、LettuceExtension、RedisBaseAutoConfiguration
│   ├── enums/        # RedisTypeEnum (STANDALONE / SENTINEL / CLUSTER)
│   ├── manage/       # 17 个 *Manager（每个 Redis 数据类型一个）
│   │                 # + AtlasRedisCacheManager + CacheLockManager + CacheSyncListener + MessageSubscriber
│   ├── migration/    # MigrationWindowValidator（启动期强制迁移校验）
│   ├── perf/         # RedisPerfGuard + RedisComplexityTier + RedisCommandMeta
│   │                 # + RedisOperationCatalog + RedisStringPayloadInspector
│   └── snowflake/    # IdBuilder（基于 Redis 持久 workerId 的雪花 ID）
└── redis/            # （已列）
```

### A.2 24 项核心功能（按 `docs/en/Cache-Core-Capabilities.md` 提炼）

| # | 功能 | Java 关键类 | 复杂度档 | Pattern | 配置前缀 |
|---|---|---|---|---|---|
| 1 | **KV / String 存储** | `RedisStringManager` | O(1) | Facade + delegate | `platform.component.cache.redis` |
| 2 | **Hash 操作** | `RedisHashManager` | O(1) | Facade + delegate | 同上 |
| 3 | **Set 操作** | `RedisSetManager` | O(1) | Facade + delegate | 同上 |
| 4 | **ZSet 操作（排行榜）** | `RedisZSetManager` | O(log n) | Facade + delegate | 同上 |
| 5 | **Key 管理（EXISTS/DEL/TTL/RENAME/RENAMENX）** | `RedisKeyManager` | O(1) / O(n) | Facade + delegate | 同上 |
| 6 | **批量操作（pipeline）** | `RedisStringManager` | (inherits) | Pipeline | 同上 |
| 7 | **GEO（地理）** | `RedisGeoManager` | O(log n) | 包装命令 | 同上 |
| 8 | **HyperLogLog（UV 统计）** | `RedisHyperLogManager` | O(1) | 包装 PF* | 同上 |
| 9 | **Bitmap（签到）** | `RedisBitmapManager` | O(1) | 包装 BIT* | 同上 |
| 10 | **Lua 脚本** | `RedisScriptManager` | SCRIPT_OR_UNKNOWN | Script executor | — |
| 11 | **限流（滑动窗口）** | `RedisLimiterManager` | SCRIPT_OR_UNKNOWN | 滑动窗口 + Lua | — |
| 12 | **有界 Queue（`queue()`）** | `RedisBoundedQueueManager` / `BoundedQueue` | O(1) + SCRIPT | Bounded FIFO + meta + Lua | `BOUNDED_MAX_LEN_CEILING=4999` |
| 13 | **有界 Stack（`stack()`）** | `RedisBoundedStackManager` / `BoundedStack` | O(1) + SCRIPT | Bounded LIFO + meta + Lua | 同上 |
| 14 | **L2 二级缓存（本地加速）** | `LocalCache` + `CacheSyncListener` | — | 本地缓存 + keyspace 同步 | `enable-l2-caching` / `l2-caching-data` |
| 15 | **Bloom Filter（穿透防护）** | `BloomFilterFacade` (Guava/Redisson) | — | Strategy (2 impl) | `platform.cache.bloom-filter` |
| 16 | **缓存击穿防护（`*WithLock`）** | `RedisStringManager` 等 | (inherits) | L2 → Bloom → Redis → Lock → DB | — |
| 17 | **分布式锁** | `RedisLockManager` + `CacheLockManager` | — | 三层（local → reentrant → Redisson FencedLock） | `enable-local-lock` |
| 18 | **性能守卫（Perf Guard）** | `RedisPerfGuard` | Runtime governance | Decorator + 复杂度分级 | `platform.component.cache.redis.perf.*` |
| 19 | **多 Redis 实例路由** | `MultiRedisTemplate` | — | 路由表 + 命名 key | `platform.component.cache.redis.slaves` |
| 20 | **Pub/Sub + Keyspace Notification** | `RedisEventManager` / `RedisNotificationManager` | — | Pub/Sub | Redis server 需 `notify-keyspace-events KEA` |
| 21 | **本地缓存（独立于 L2）** | `LocalCacheManager` + JSR-107 | — | JSR-107 标准 | `platform.cache.local` |
| 22 | **迁移窗口校验（`@MigrationWindow`）** | `MigrationWindowValidator` | — | 启动期强制校验 | — |
| 23 | **雪花 ID 生成器** | `IdBuilder` (Snowflake) | — | Snowflake + Redis 持久 workerId | — |
| 24 | **Spring Boot 自动装配** | `RedisAutoConfiguration` | — | Spring `@Configuration` | — |

### A.3 关键设计模式（从代码 / 文档提炼）

| Pattern | 落地位置 | 关键说明 |
|---|---|---|
| **Facade** | `GlobalCache`（虽然本文档不展开，但 README 提到） | 业务永远只跟 `GlobalCache.value()/.field()/.struct()` 打交道 |
| **Strategy（2 实现）** | Bloom Filter（Guava / Redisson） | `CacheProperties.bloomFilter.type` 选 GUAVA / REDISSON |
| **Decorator（治理）** | `RedisPerfGuard` | 包住每个 Manager 调用，注入复杂度 + 延迟 + 写入抗模式检测 |
| **三层 Lock Fallback** | `RedisLockManager` | local JVM lock → 可重入检测 → Redisson FencedLock（fencing token） |
| **Bounded Collection + Meta Key** | `BoundedQueue` / `BoundedStack` | 真正的 List + 旁挂 `{key}:meta` 存 maxLen，写入用 Lua atomic 维持容量 |
| **Anti-Pattern Runtime Detection** | `RedisStringPayloadInspector` + `RedisPerfGuard.checkStringWritePayload` | 检测 Collection / Map / 超大 text 塞进 String |
| **Migration Window** | `@MigrationWindow` annotation + `MigrationWindowValidator` | 启动时校验"软开关必须按期打开"——到期不打开直接拒启动 |

### A.4 关键设计原则（从 Java README + 设计文档提炼）

1. **抗 BIGKEY**：bounded queue/stack 上限 4999；L2 仅 STRING/HASH 入缓存（LIST/SET 不入，因为体积大）
2. **抗缓存雪崩**：TTL = 业务时间 + `getRandomExtraMillis()`（1~10 分钟随机偏移）
3. **抗缓存击穿**：`*WithLock` 系列（L2 → Bloom → Redis → 分布式锁 → DB）
4. **抗缓存穿透**：Bloom Filter
5. **跨实例 L2 一致性**：依赖 Redis keyspace notifications（`notify-keyspace-events KEA`）
6. **治理早于功能**：`RedisPerfGuard` 是每个 Manager 调用的必经路径，不走治理就发版是违规
7. **本地锁优先**：同一 JVM 高频争锁走 local lock，0.01ms 命中，99% 不打 Redisson
8. **性能档位**：O(1) / O(log n) / LINEAR_N / WORSE / SCRIPT_OR_UNKNOWN 五档
9. **拒绝静默**：序列化失败 WARN 不 throw；String 滥用 ERROR + 可选 block
10. **强制迁移**：`@MigrationWindow` 截止日期后字段不 = true，应用拒启动

### A.5 关键 Lua 脚本（提炼自 `BoundedListRedisScripts.java`）

1. `GROW_MAX_LEN_SCRIPT`：maxLen × 2，封顶 4999
2. `TRIM_LIST_TO_META_SCRIPT`：按 meta 裁剪 List 长度
3. `BOUNDED_QUEUE_OFFER_SCRIPT`（推断）：RPUSH + LTRIM 原子写入 + 容量强制
4. `BOUNDED_STACK_PUSH_SCRIPT`（推断）：满则 0，未满则 RPUSH 返回 1
5. `SLIDING_WINDOW_RATE_LIMITER_SCRIPT`（在 `RedisLimiterManager`）：INCR + EXPIRE 原子

---

## B. Java→Python 框架最佳替代品

### B.1 核心库选型矩阵

| Java 依赖 | Python 替代品 | 推荐度 | 备注 |
|---|---|---|---|
| **Lettuce**（Redis async client） | `redis-py` >= 5.0（含 `redis.asyncio`） | ⭐⭐⭐⭐⭐ | 官方维护，5.x 起 async + sync 双 API |
| **Redisson**（分布式 Java Redis 客户端，封装了 lock/bloom/queue/stream） | **没有完整对应物**，按能力拆 | ⭐⭐⭐（分能力选） | Redisson 是个"大而全"的客户端；Python 生态分得更细，按能力选单一库 |
| **Redisson FencedLock**（fencing token） | `redis-py` + 自己实现 fencing token | ⭐⭐⭐ | Python 没现成的，需要自己写 Redis 脚本实现 RedLock + fencing |
| **Caffeine**（JVM 本地缓存） | `cachetools` >= 5.3（同步 LRU/TTL）+ `py-cachetools` async 版本 | ⭐⭐⭐⭐ | 简单场景够用；高 QPS 看 `pylru` 或 `cachebox` |
| **Ehcache / cache2k** | — | — | Python 生态不直接对位这两个 |
| **JSR-107 (`javax.cache`)** | `cachetools`（不严格符合 JSR-107，但 API 类似） | ⭐⭐⭐ | 不强求 1:1 |
| **Spring Data Redis** | 直接用 `redis-py` / `redis.asyncio` | ⭐⭐⭐⭐⭐ | Python 项目不依赖 Spring，无需替代 |
| **Spring Boot `@ConfigurationProperties`** | **Pydantic v2 Settings**（`pydantic-settings`） | ⭐⭐⭐⭐⭐ | 类型校验 + env 读取 + immutable + 字段文档 |
| **Lombok `@Data`/`@RequiredArgsConstructor`** | **dataclasses(frozen=True, slots=True)** | ⭐⭐⭐⭐⭐ | 已用，本项目 `CODE_QUALITY.md` 第 1 条硬约束 |
| **Guava `BloomFilter`** | `pybloomfiltermmap3`（磁盘版）或 `bbloom-filter`（内存版） | ⭐⭐⭐ | 选 `bbloom-filter` 简单场景够用 |
| **Redisson `RBloomFilter`**（共享） | **自己用 Redis SETBIT 实现**（简单） 或 `redis-py` + `bitarray` | ⭐⭐⭐ | 共享 bloom 自己写 Lua 脚本 |
| **Lombok `@Slf4j`** | `structlog` 或标准 `logging` | ⭐⭐⭐⭐ | 推荐 `structlog`，结构化日志对治理友好 |
| **Jackson `ObjectMapper` / `TypeReference`** | `pydantic` v2 + `orjson` | ⭐⭐⭐⭐⭐ | pydantic 已经是事实标准 |
| **Spring `AutoConfiguration`（`@ConditionalOnExpression`）** | 不需要——Python 用 DI 容器少；用 `pydantic-settings` + 普通 init | ⭐⭐⭐⭐ | 看 `wired-protocol` 那种轻量 DI 库，或直接手写 factory |
| **Hibernate Validator（`@Min`/`@NotNull`）** | `pydantic` v2 `Field(ge=0, max_length=...)` | ⭐⭐⭐⭐⭐ | pydantic 直接对位 |
| **Snowflake（`IdBuilder`）** | `pysnowflake` 或自己写（80 行） | ⭐⭐⭐⭐ | 自己写更可控，参考 `pysnowflake` 思路 |
| **Jedis（备用 client）** | 不需要，redis-py 单一库 | — | — |
| **SLF4J + Logback** | `structlog` + `logging.config.dictConfig` | ⭐⭐⭐⭐ | 结构化日志 |
| **JUnit 5** | `unittest`（标准库）+ `pytest`（业界） | ⭐⭐⭐⭐ | 本项目用 `unittest` 跟 Java `*ManagerTest` 一致 |

### B.2 Python 第三方库选型推荐

#### B.2.1 客户端层
- **`redis>=5.0`** — Redis 客户端（sync + async 都有）
- **`redis.asyncio`** — async 接口（如果走 R-104 那种 async 模式）

#### B.2.2 L1（本地）缓存
- **`cachetools>=5.3`** — TTL/LRU/TTLCache，足够 80% 场景
- **`pylru`** — 如果需要更激进的 LRU
- **`cachebox`** — 如果要 async LRU（罕见）

#### B.2.3 序列化
- **`pydantic>=2.0`** — 域模型 + 校验（首选）
- **`orjson`** — 快速 JSON（如果不想用 pydantic 的序列化）

#### B.2.4 Bloom Filter
- **`bbloom-filter`** — 纯 Python 内存 bloom，简单场景
- **`pybloomfiltermmap3`** — 磁盘版 mmap（持久）
- **自己写 Lua + Redis SETBIT** — 共享 bloom，多实例同步

#### B.2.5 配置 / 启动期校验
- **`pydantic-settings>=2.0`** — 类型化配置读取
- **`pydantic.Field(ge=..., le=...)`** — 内置校验
- **手写 `MigrationWindowValidator` + `@migration_window` decorator** — 强制迁移

#### B.2.6 日志
- **`structlog>=24.0`** — 结构化日志
- **标准 `logging`** — 简单场景

#### B.2.7 测试
- **`unittest`**（本项目用） / `pytest`
- **`pytest-asyncio`**（如果走 async 测试）
- **`fakeredis>=2.20`** — 纯 Python Redis 仿真，跑测试不需要真 Redis

#### B.2.8 锁 / 分布式协调
- **自己写（基于 `redis-py` + Lua）** — `acquire` / `release` / `fencing token` / `watchdog` 都自己实现
- **`pottery>=3.0`** — Python Redlock 实现（含 redis-lock / leader-election）—— 备选

#### B.2.9 L2 跨实例同步（替代 Java 的 keyspace notification）
- **`redis-py` `pubsub()`** — Redis 0.9+ 都有 pub/sub
- **自己起 background task 订阅 `__keyevent@*__:del`/`__:set`**

---

## C. Python 仓 `components/cache/` 推荐结构（待你拍板）

> **注意：以下结构是"假如全面对位 Java 版"的草案**。R-103 已经把 `DistributedCache` Protocol 落到 OAuth 仓里——这是错误的（你刚纠正过）。重构的方案是：

### C.1 新仓 `components/cache/`（独立组件）

```
components/cache/
├── pyproject.toml
├── README.md
├── src/atlas_richie/cache/
│   ├── __init__.py
│   ├── clock.py                    # 已有等价物：components/resilience/.../clock.py
│   ├── errors.py
│   ├── core/                       # 核心数据模型 + 简单 KV
│   │   ├── __init__.py
│   │   ├── cache_key.py            # CacheKey 命名规范
│   │   ├── entry.py                 # CacheEntry + ValueType 枚举
│   │   ├── ttl.py                   # Ttl + 抗雪崩 random offset
│   │   ├── data_type.py             # STRING/HASH/SET/ZSET/LIST/BITMAP/GEO/HLL
│   │   └── value_codec.py           # 序列化：pydantic 优先
│   ├── capabilities/                # 11 个 redis 数据类型的 facade
│   │   ├── __init__.py
│   │   ├── string_ops.py            # 等价 Java ValueOps
│   │   ├── hash_ops.py              # 等价 HashOps
│   │   ├── set_ops.py
│   │   ├── zset_ops.py
│   │   ├── list_ops.py
│   │   ├── key_ops.py
│   │   ├── geo_ops.py
│   │   ├── hyperlog_ops.py
│   │   ├── bitmap_ops.py
│   │   ├── script_ops.py            # Lua 脚本
│   │   └── limiter_ops.py           # 滑动窗口
│   ├── structures/                  # BoundedQueue / BoundedStack
│   │   ├── __init__.py
│   │   ├── bounded_queue.py
│   │   ├── bounded_stack.py
│   │   ├── capacity_limits.py       # BOUNDED_MAX_LEN_CEILING=4999
│   │   └── bounded_list_redis_scripts.py  # 3+ 个 Lua
│   ├── l2_local.py                  # L2 本地加速（cachetools / pylru）
│   ├── bloom_filter.py              # Strategy: bbloom / redis-lua
│   ├── distributed_lock.py          # Local lock pool + Redis RedLock + fencing
│   ├── perf_guard.py                # Decorator：复杂度分级 + 慢查询 + String 抗模式
│   ├── complexity_tier.py           # O1 / LOG_N / LINEAR_N / WORSE / SCRIPT_OR_UNKNOWN
│   ├── migration_window.py          # 强制迁移校验
│   ├── snowflake.py                 # ID 生成器
│   └── protocol.py                  # DistributedCache Protocol（已有 stub，搬过来）
└── tests/...
```

### C.2 通用仓 `adapters/cache-{redis,hazelcast,etcd}/`（待 stub 化）

`adapters/cache-redis/` — 主适配（Java Lettuce 替代）
`adapters/cache-hazelcast/` — 替代品 stub
`adapters/cache-etcd/` — 替代品 stub

### C.3 删除 OAuth 仓里的 `cache.py` 和 `adapters/oauth-cache-*`

彻底拆分 OAuth 不再"拥有" cache 协议。

### C.4 依赖 OAuth / HTTP / MCP 之后可以挂载

- OAuth：`DpopReplayStore` 可选地接收 `DistributedCache` 实例（多进程防重放）
- HTTP：response 可选地进 L2
- MCP：sub-resource 可选地进 L2
- 它们都是 `components/cache/` 的 consumer，互不依赖

---

## D. 22 题决策（richie696 确认 2026-09-11）

| # | 议题 | 你的决策 |
|---|---|---|
| 1 | **MVP scope** | **D — 全部 24 项** |
| 2 | 删除 OAuth 仓里的 `cache.py` | **是，完全删除**；OAuth 仓只是 cache 组件的 consumer |
| 3 | 3 个 adapter stub 包重命名 + 接入范围 | **现阶段只接入 redis**；Hazelcast/etcd 不建；oauth-cache-* 全部删除 |
| 4 | Snowflake ID | **含**；workerId 存 Redis（与 Java 一致，**不是**无状态雪花） |
| 5 | L2 + Keyspace Notification 同步 | **含**（cachetools + redis-py pubsub） |
| 6 | Bloom Filter | **含**（内存 + Redis 共享双实现） |
| 7 | 分布式锁（三层 fallback） | **含** |
| 8 | Perf Guard | **含**（Decorator + ComplexityTier） |
| 9 | 限流（滑动窗口） | **含**（Lua INCR+EXPIRE） |
| 10 | 有界 Queue / Stack | **含**（meta + Lua） |
| 11 | Pub/Sub | **含** |
| 12 | MigrationWindow 强制迁移 | **不用**（v2 再考虑） |
| 13 | 多 Redis 实例路由 | **不用**（单实例起步） |
| 14 | GEO / HLL / Bitmap / ZSet | **都要**（24 项全做） |
| 15 | 配置加载 | **用 pydantic-settings** |
| 16 | 本地缓存 provider | **用 cachetools 单一实现**（不做多 provider 抽象） |
| 17 | 序列化 | **用 pydantic v2** |
| 18 | 日志格式 | **用 structlog** |
| 19 | 测试时 Redis 仿真 | **用 fakeredis** |
| 20 | platform 聚合包依赖更新 | **是** |
| 21 | OIDC ID Token 是否注入 `DistributedCache` | **不需要**（OAuth 不强依赖 cache） |
| 22 | oauth-cache-* adapter 包处理 | **删除**（连同 R-103 那批 stub） |

---

## E. Java 仓值得保留到 Python 仓的设计要素（"高保真"清单）

1. **24 项功能的命名 1:1**（中文 + 英文）
2. **`BOUNDED_MAX_LEN_CEILING = 4999`** 的容量红线
3. **`L2CachingRegion.GLOBAL_CACHE` 命名规范**
4. **`RedisComplexityTier` 五档分级**（O1 / LOG_N / LINEAR_N / WORSE / SCRIPT_OR_UNKNOWN）
5. **`perf.{toc-soft-ms, toc-hard-ms, max-batch-read-items}` 三档阈值**
6. **`l2-caching-data: [STRING, HASH]` 默认白名单**（LIST / SET 不入 L2）
7. **`enable-local-lock` 默认 true**
8. **`@MigrationWindow` 启动期强制迁移**
9. **三层锁 fallback（local → reentrant → Redis）**
10. **`{key}:meta` 旁挂 key 存 maxLen 的 bounded collection 模式**
11. **L2 随机偏移 1-10 分钟抗雪崩**
12. **`BoundedListElementConverter` 反序列化失败 WARN 不 throw**
13. **`RedisStringPayloadInspector` 检测 Collection / Map 整包塞 String**
14. **`CacheSyncListener` 订阅 keyspace notification 跨实例 L2 失效**
15. **`@ConditionalOnExpression` 表达多后端**——Python 可用 `pydantic` 字段 + `__post_init__` 校验

## F. 实施分阶段建议（草案，等你拍板 scope 后定）

> 假设你的选项是 **C**（Protocol + InMemory + 真实 Redis adapter + 1 项治理：Perf Guard）

| 阶段 | 内容 | 时间感 |
|---|---|---|
| **R-200** 重构 OAuth 仓 | 删 `components/oauth/.../cache.py`；删 `adapters/oauth-cache-*`；3 个 stub 重新放到 `adapters/cache-*` | 30 min |
| **R-201** 新建 `components/cache/` 仓 | Protocol 搬过来 + 真实 `RedisDistributedCache` 实现 get/set/add_if_absent/delete + TTL | 1-2 天 |
| **R-202** L1 本地缓存 + L2 加速 | `cachetools` 包装 + 装饰 RedisDistributedCache | 1 天 |
| **R-203** Perf Guard | `ComplexityTier` 枚举 + Decorator 包住每个 capability | 1 天 |
| **R-204** 分布式锁 | 三层 fallback + fencing token | 1-2 天 |
| **R-205** Bloom Filter | Strategy: 内存 + Redis 共享两实现 | 0.5 天 |
| **R-206** 有界 Queue / Stack | Lua 脚本 + meta key 模式 | 1 天 |
| **R-207** MigrationWindow 强制迁移 | `pydantic-settings` + 启动期 validator | 0.5 天 |
| **R-208** 限流（滑动窗口） | Lua + INCR+EXPIRE | 0.5 天 |
| **R-209** GEO / HLL / Bitmap / ZSet | 每项 50-100 行 | 1-2 天 |
| **R-210** 多 Redis 路由 | 命名 client + 路由表 | 1 天 |
| **R-211** Snowflake ID | 自己写（80 行） | 0.5 天 |
| **R-212** Pub/Sub + Keyspace Notification | `redis-py` pubsub + background task | 1 天 |
| **R-213** Spring Boot 等价自动化配置 | 退化为 `pydantic-settings` + 简单 init | 0.5 天 |
| **R-214** 单测 + 集成测试 + `fakeredis` | 每个 capability 1-2 个单测 + 集成测试 | 2 天 |
| **R-215** 文档 + handoff + 矩阵 | 复用 R-104/R-101/R-102/R-103 的交付模式 | 0.5 天 |

总计约 12-15 天。

---

## G. 给我你的决策

我等你的回答后开工。**请把 D 节那 22 个问题的答案**给我（或者简单说 "MVP 做 X" / "全做" / "只做 v1 stub"），然后我按你的选择起 R-200 计划。

如果 D 节你只回答 1（scope 选择），其他默认我建议的也行——但请显式说"其他按你建议"以免我猜错。

---

**文档版本**：2026-09-11 v0.1（基于 `Cache-Core-Capabilities.md` 24 节 + `Redis-L2-and-Performance-Guard-Design.md` + 11 个核心 Manager / 6 个 ops/* 源码 + AtlasRedisProperties 字段集）
