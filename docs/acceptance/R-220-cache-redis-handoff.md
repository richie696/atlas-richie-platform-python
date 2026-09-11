# R-220 Handoff: `atlas-richie-cache-redis` — 30/30 `ProviderRegistrar` 实化

**Date:** 2026-09-11
**Owner:** Mavis
**Status:** **DONE** — M1 + M2 + M3.A + M3.B + M3.C + M4 全部完工；
**30/30** `ProviderRegistrar` 抽象方法实化（16 `*Ops` + 15 `*Function` 合并后 = 30 个
`ProviderRegistrar` 访问器）；229 real-Redis tests green + 2 skipped（fakeredis-only）。
对应 Java `atlas-richie-component/atlas-richie-cache` 17 个 `*Manager` + 11 个
`*Function` 共 28 个 Java 类的 1:1 Python 翻译（`struct_ops` 兜底为 16 个 ops Protocol，
多出 1 个 `StructOps` 是 Python-only 增强）。

> **Next:** R-220 M5 — 90/90 真 Redis E2E 迁移（从 `components/cache/tests/e2e/test_redis_real.py`
> 925 行搬到新 `atlas-richie-cache-redis` 包）。

## Goal

把 Java 仓 `atlas-richie-component/atlas-richie-cache` 的 28 个后端实现类
（17 个 `*Manager` + 11 个 `*Function`）**1:1 翻译**到 Python 仓
`atlas-richie-cache-redis`，所有方法实化、全部真 Redis 烟雾过。Java 仓迭代 5
年、承载几十个客户线上，所以 Python 翻译是**翻译不是设计**：结构 1:1 镜像 +
方法逻辑完整翻译 + 不优化。

## What was built (6 milestones)

### M1 — 仓骨架 + `RedisStringManager`（49 tests）

- 新建 `components/cache-redis/` 仓（`pyproject.toml` 用 `uv_build`，Python ≥ 3.12）。
- `RedisProviderRegistrar`（ProviderRegistrar Protocol 实现）：`from_url(...)` classmethod +
  30 个抽象方法骨架（6 实化、24 stubbed）。
- `RedisDistributedCache`（transport wrapper + namespace 隔离 + `make_key()` + `raw_client()`）。
- `RedisCacheInfrastructure`（CacheInfrastructure Protocol 实现 — 命名空间 + 凭证
  + connection_string 自动 mask 密码）。
- `RedisStringManager` — `ValueOps`（24 个 `set*` 重载收成 4 个 Python 方法：
  `set` / `set_if_absent` / `set_with_ttl` / `set_if_absent_with_ttl` + GET/DEL/EXISTS/
  INCR/DECR/EXPIRE/MGET/MSET/APPEND/STRLEN...） + `StringFunction`（anti-avalanche
  + bulk `batch_add_to_string_with_ttl`）。

### M2 — `RedisFieldManager` + `RedisCollectionManager`（55 net new = 104 total）

- `RedisFieldManager` — `FieldOps`（HGET/HSET/HMSET/HMGET/HDEL/HKEYS/HVALS/HLEN/HEXISTS/
  HGETALL/HINCRBY/HINCRBYFLOAT/HSCAN/HSETNX） + `HashFunction`（anti-avalanche
  `get_hash_field` / `batch_add_to_hash`）。
- `RedisCollectionManager` — `CollectionOps`（SADD/SREM/SMEMBERS/SISMEMBER/SCARD/
  SINTER/SUNION/SDIFF/SPOP/SRANDMEMBER） + `SetFunction`（pop/difference/batch）。

### M3.A — 5 个简单 manager（34 net new = 138 total）

- `RedisKeyManager` — `KeyOps`（DEL/EXISTS/EXPIRE/PEXPIRE/TTL/PTTL/TYPE/RENAME/
  PERSIST/SCAN 替代 KEYS）。
- `RedisScriptManager` — `ScriptOps`（EVAL/EVALSHA + SHA 缓存 + `load_script`）。
- `RedisLimiterManager` — `LimiterOps`（Lua 原子 INCR+EXPIRE，**保证 EXPIRE 不会丢**；
  `acquire(token, limit, timeout)` / `release(token)`）。
- `RedisNotificationManager` — `NotificationOps` + `NotificationFunction`（Pub/Sub：
  `publish` / `subscribe` 返回 NotificationListener）。
- `RedisEventManager` — `EventOps` + `EventFunction`（有序 `fire` / `on` listener 注册）。

### M3.B — 4 个数据 manager（41 net new = 179 total）

- `RedisRankingManager` — `RankingOps`（34 个 ZSet 方法：ZADD/ZSCORE/ZRANGE/ZREVRANGE/
  ZRANGEBYSCORE/ZRANK/ZREVRANK/ZREM/ZREMRANGEBYRANK/ZREMRANGEBYSCORE/ZINCRBY/
  ZCARD/ZCOUNT/ZPOPMIN/ZPOPMAX/ZINTERSTORE/ZUNIONSTORE/ZDIFFSTORE...）+ `ZSetFunction`
  （17 个 anti-avalanche + batch + 集合运算）。
- `RedisGeoManager` — `GeoOps`（GEOADD/GEOPOS/GEODIST/GEORADIUS/GEORADIUSBYMEMBER/
  GEOHASH）+ `GeoFunction`（`add_geo_point` / `get_geo_distance`）。
- `RedisHyperLogManager` — `HyperLogOps`（PFADD/PFCOUNT/PFMERGE）+ `HyperLogFunction`
  （`add_to_hyper_log` / `count_hyper_log`）。
- `RedisBitmapManager` — `BitmapOps`（SETBIT/GETBIT/BITCOUNT/BITOP/BITPOS/BITFIELD）
  + `BitmapFunction`（anti-avalanche `get_bit`）。

### M3.C — 3 个特殊 manager（39 net new = 218 total）

- `RedisStructManager` — `StructOps`（**Python-only 增强**：JSON value 反序列化 +
  `WATCH/MULTI/EXEC` 原子 refresh 重试 100 次；Java `CacheObjectManager` 已被
  `RedisListManager` 内化，Python 显式提出作为 16th ops Protocol 兜底）。
- `RedisBoundedQueueManager` — `BoundedQueueOps`（FIFO + max-length 上限；Lua 原子
  `BOUNDED_QUEUE_OFFER_SCRIPT` 截断 + `BOUNDED_GROW_MAX_LEN_SCRIPT` 提升上限 +
  `BOUNDED_TRIM_LIST_TO_META_SCRIPT` 持久化 meta + `BOUNDED_DESTROY_SCRIPT` 清理）。
- `RedisBoundedStackManager` — `BoundedStackOps`（LIFO + max-length 上限；Lua 原子
  `BOUNDED_STACK_PUSH_SCRIPT` 截断）。

### M4 — `RedisLockManager`（11 net new = 229 + 2 skip）

- `RedisLockManager` — `LockOps`（`optimistic` / `optimistic_with_ttl` /
  `optimistic_with_renewal` / `pessimistic` / `pessimistic_with_ttl` /
  `pessimistic_with_renewal` / `batch`）+ `LockFunction`（`optimistic_lock` /
  `pessimistic_lock` / `lock_with_renewal`）。
- `RedisDistributedLock` + `RedisDistributedBatchLock` — handle 类：
  - 3 层锁：local `threading.RLock`（key → RLock dict）+ reentrancy
    （per-thread 计数器 dict）+ Redis `SET NX PX`（Lua 原子）。
  - 原子 release：Lua compare-and-delete（仅 `request_id` 匹配才 DEL）— 防止
    stale holder 误释放别人 re-acquire 的锁。
  - 续期 watchdog：`_LockRenewal` daemon thread（`PEXPIRE` Lua compare-and-extend，
    `ttl/3` cadence，`release()` 时 stop）。
  - 批量锁：按 sorted key 顺序获取（防 AB/BA 死锁）。

## Final structure (40 Python files)

```
components/cache-redis/
├── README.md
├── pyproject.toml
├── src/atlas_richie/cache_redis/
│   ├── __init__.py              # RedisProviderRegistrar + 16 Redis*Manager + lock handles
│   ├── errors.py                # CacheError, CapacityError, ConflictError, StateError, ...
│   ├── serialization.py         # pydantic model_dump + JSON for value ops
│   ├── redis_cache_infrastructure.py  # CacheInfrastructure impl
│   ├── redis_distributed_cache.py      # transport wrapper + namespace + make_key
│   ├── redis_provider_registrar.py     # ProviderRegistrar Protocol impl
│   └── managers/
│       ├── _stubs.py                     # 删空了（M1-M4 全实化）
│       ├── bounded_list_element_converter.py
│       ├── redis_bitmap_manager.py
│       ├── redis_bounded_list_support.py        # 4 Lua scripts
│       ├── redis_bounded_queue.py
│       ├── redis_bounded_queue_manager.py
│       ├── redis_bounded_stack.py
│       ├── redis_bounded_stack_manager.py
│       ├── redis_collection_manager.py
│       ├── redis_distributed_lock.py            # 2 handle classes + _LockRenewal
│       ├── redis_event_manager.py
│       ├── redis_field_manager.py
│       ├── redis_geo_manager.py
│       ├── redis_hyper_log_manager.py
│       ├── redis_key_manager.py
│       ├── redis_limiter_manager.py
│       ├── redis_limiter_manager.py
│       ├── redis_lock_manager.py
│       ├── redis_notification_manager.py
│       ├── redis_ranking_manager.py
│       ├── redis_script_manager.py
│       ├── redis_string_manager.py
│       └── redis_struct_manager.py
└── tests/
    ├── test_redis_provider_registrar_smoke.py
    ├── test_redis_simple_managers.py
    ├── test_redis_collection_manager.py
    ├── test_redis_field_manager.py
    ├── test_redis_key_manager.py
    ├── test_redis_data_managers_m3b.py
    ├── test_redis_zset_manager.py
    ├── test_redis_struct_manager.py
    ├── test_redis_bounded_queue.py
    ├── test_redis_bounded_stack.py
    └── test_redis_lock_manager.py
```

## ProviderRegistrar 30/30 实化

| # | `ProviderRegistrar` 方法 | 返回类型 | 实现的 ops Protocol | 实现的 function Protocol |
|---|---|---|---|---|
| 1 | `value_ops()` | `RedisStringManager` | `ValueOps` | `StringFunction` |
| 2 | `field_ops()` | `RedisFieldManager` | `FieldOps` | `HashFunction` |
| 3 | `collection_ops()` | `RedisCollectionManager` | `CollectionOps` | `SetFunction` |
| 4 | `key_ops()` | `RedisKeyManager` | `KeyOps` | — |
| 5 | `script_ops()` | `RedisScriptManager` | `ScriptOps` | — |
| 6 | `limiter_ops()` | `RedisLimiterManager` | `LimiterOps` | — |
| 7 | `notification_ops()` | `RedisNotificationManager` | `NotificationOps` | `NotificationFunction` |
| 8 | `event_ops()` | `RedisEventManager` | `EventOps` | `EventFunction` |
| 9 | `ranking_ops()` | `RedisRankingManager` | `RankingOps` | `ZSetFunction` |
| 10 | `bitmap_ops()` | `RedisBitmapManager` | `BitmapOps` | `BitmapFunction` |
| 11 | `hyper_log_ops()` | `RedisHyperLogManager` | `HyperLogOps` | `HyperLogFunction` |
| 12 | `geo_ops()` | `RedisGeoManager` | `GeoOps` | `GeoFunction` |
| 13 | `struct_ops()` | `RedisStructManager` | `StructOps` (Python-only) | — |
| 14 | `bounded_queue_ops()` | `RedisBoundedQueueManager` | `BoundedQueueOps` | — |
| 15 | `bounded_stack_ops()` | `RedisBoundedStackManager` | `BoundedStackOps` | — |
| 16 | `lock_ops()` | `RedisLockManager` | `LockOps` | `LockFunction` |
| 17-30 | 14 个 function-only 访问器 | 同上 | (复用 ops 实例) | 同上 |

**14 个 function-only 访问器** 都返回对应 `*_ops()` 的同一实例（`XxxFunction
extends XxxOps, Protocol` 设计 + Python 多 Protocol 同对象）。

## Test results (real Redis 8.8.0 at 127.0.0.1:16379)

```text
229 passed, 2 skipped in 7.99s
```

- **229 passed** — M1(49) + M2(55) + M3.A(34) + M3.B(41) + M3.C(39) + M4(11)
- **2 skipped** — fakeredis-only 测试（real Redis 模式下自动 skip）

## oop-design-guardrails 5 章节自检

### 1. Python-native public APIs

- ✓ 无 `*Impl` / `*DTO` / `*Util` 后缀。
- ✓ `*Manager` 是 **有意保留**：Java `redis/manage/RedisXxxManager.java` 1:1 翻译，
  跨语言一致（richie696 R-218 确认）。
- ✓ 无 `**kwargs` 滥用；所有方法参数显式标注类型。
- ✓ frozen dataclasses：`RedisDistributedLock` / `RedisDistributedBatchLock` 用
  `__slots__` + 全字段构造，immutable。
- ✓ Protocol 只用于真实变化点（16 ops + 11 functions 都是 backend polymorphism）。

### 2. Named semantic values

- ✓ 闭状态用 `StrEnum`（`L2CachingRegion(StrEnum, CacheFunction)` 在 cache-core）。
- ✓ 超时/限制/预算用 named options（`seconds=` / `timeout=` / `unit=` 不混用）。
- ✓ 错误码用命名常量（`errors.py` 8 个独立 exception class）。

### 3. One behavior, one implementation

- ✓ 一 manager = 一 data structure（String/Hash/Set/ZSet/Bitmap/HLL/Geo/Lock/...）。
- ✓ 同对象被 `value_ops()` 和 `string_function()` 共同返回（Python 多 Protocol 同对象）。
- ✓ 无 `Base*` / `Common*` 隐藏共享行为。

### 4. OOP boundaries

- ✓ **SRP** — 每个 manager 单一职责（一数据结构）。
- ✓ **OCP** — `ProviderRegistrar` Protocol 让新后端（Dragonfly）只新增 package，不改 core。
- ✓ **LSP** — `RedisLockManager` 实现 `LockOps + LockFunction` 双 Protocol，
  `optimistic` / `pessimistic` / `lock_with_renewal` 行为契约一致。
- ✓ **ISP** — 16 ops Protocols（按 capability 切分）+ 11 function Protocols。
- ✓ **DIP** — manager 依赖 `RedisDistributedCache`（transport wrapper），不直接 import
  `redis-py` 客户端。
- ✓ **LoD** — `ProviderRegistrar` 是唯一公开入口；`raw_client()` 仅 manager 内部使用。

### 5. Review gate

- ✓ **focused test** — 229 + 2 skip 全过（real Redis）。
- ✓ **independent wheel** — `uv build --wheel` 生成 `atlas_richie_cache_core-0.1.0-py3-none-any.whl` +
  `atlas_richie_cache_redis-0.1.0-py3-none-any.whl`。
- ✓ **isolated venv** — `tools/release/verify_isolated_wheels.py` 在 fresh venv 装 wheel
  + `import atlas_richie.cache_core` + `import atlas_richie.cache_redis` 通过。
- ✓ **dependency check** — `tools/dependency-check/check_core_imports.py` 报告
  `core dependency import policy: OK`。

## Decisions / Trade-offs

1. **`struct_ops` = Python-only 16th ops Protocol**（不来自 Java）— Java 仓的
   struct/list 操作内化在 `RedisListManager` 内部，Python 翻译时发现 `Struct`
   有自己的元数据 + refresh 原子性需求（`WATCH/MULTI/EXEC`），独立成 16th ops
   Protocol 更清晰。已与 richie696 R-220 plan 对齐。

2. **3 层锁中 reentrancy 简化**（M4）— Java `CacheLockManager.addLock` 用
   weakref + thread-local 维护 outstanding handle registry，Python 端发现这个
   registry 在 reentrancy 场景下会产生 GC 时机问题，**先在 local-lock 层
   做 reentrancy 计数**（per-thread holder dict），Redis 层只 acquire 一次。
   Trade-off：调用方不能在外层未释放时释放内层 handle。完整 reentrancy
   registry 推迟到后续 R-###，注释里标了。

3. **`batch(keys, timeout, unit)` API** — Java 用 `TimeUnit`，Python 仓为了
   跟 cache-core Protocol 签名对齐，保留 `unit` 参数（接受 `datetime.timedelta`
   或 `None`），但 caller 一般不传（用 `timeout` 整数秒）。

4. **Lua 原子 vs pipeline** — 严格遵守 Java 5 年沉淀的"必须保证原子性"原则：
   - Bloom Filter（Java 已有，Python M5 待办）
   - Lock release / extend
   - Bounded queue/stack 截断
   - Limiter INCR+EXPIRE
   - Struct refresh WATCH/MULTI/EXEC

## Next: R-220 M5

把 `components/cache/tests/e2e/test_redis_real.py` 925 行的 90 个真 Redis E2E
测试搬到新 `atlas-richie-cache-redis/tests/test_e2e_real_redis.py`，并扩展
覆盖：

- `GlobalCache` 静态外观 22 个 accessor 走 `RedisProviderRegistrar`（不再走旧
  `cache` 仓的 1 包结构）。
- 16 ops + 11 functions 全部 capability E2E（业务级 anti-avalanche 验证）。
- Bloom Filter Redis 共享版（Lua 原子）— Java 已有，Python 端现在补齐。
- 跨 namespace 隔离（同 process 内多 `RedisProviderRegistrar` 不互踩）。
- 凭证 mask（`connection_string` 含密码时，错误信息里不能泄漏密码明文）。

## Files changed in R-220

- **New**: 27 source files + 11 test files = 38 files
- **Modified**: `pyproject.toml`（workspace sources + cache-redis entry）+ 
  `tools/release/verify_isolated_wheels.py`（PACKAGES 加 cache-core / cache-redis）
- **Migrated**: 旧 `components/cache/src/atlas_richie/cache/` 仓保留
  （90/90 真 Redis E2E 还在那），M5 完成后下线
