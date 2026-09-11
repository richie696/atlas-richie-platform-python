# R-220 M5 Handoff: `test_e2e_real_redis.py` 落地

**Date:** 2026-09-11
**Owner:** Mavis
**Status:** M5 **DONE** — 37/37 E2E tests green + 6 capability skips（pending
M1-M4 范围外的能力）。

## Goal

把 `components/cache/tests/e2e/test_redis_real.py` 925 行的 90 个真 Redis
E2E 测试**搬到新** `atlas-richie-cache-redis` 包，作为新 M1-M4 架构的端到端
**wiring smoke** 验证。

## Strategy

M5 不复制 1:1 旧测试。原因：

1. **新架构 API 形状变了** — `cache.value()` 旧 method → 新
   `cache.value_ops()` method（旧 cache-core 用 `value_ops` property，新
   `RedisProviderRegistrar` 用 method 形式 `value_ops()`）；旧
   `cache.queue(name, max_len=N)` 工厂 → 新
   `cache.bounded_queue_ops().create(name, max_len, clazz=str)`；旧
   `cache.lock().try_acquire(name, ttl)` 返回带 `fencing_token` 的 handle →
   新 `cache.lock_ops().optimistic(name).try_acquire()` 返回 `RedisDistributedLock`。
2. **能力范围不同** — 旧测试覆盖 L1 / Bloom / Snowflake / Keyspace /
   PerfGuard，但 M1-M4 没实化这些；旧 `NotificationBus` 有 `subscribe`，
   新 `NotificationOps` 只有 `publish`；旧 `EventBus` 有 `fire` /
   `register_listener`，新 `EventOps` 只有 `subscribe_key_event`。
3. **详细能力测试已在 M1-M4 各 manager 单测覆盖**（229 tests）—— M5 不重复
   单测粒度，专注**wiring + 跨切关注点**。

## What was built

### New file
- `components/cache-redis/tests/test_e2e_real_redis.py`（~24 KB，
  43 tests：37 active + 6 skip）

### Test structure

| Class | Tests | What it covers |
|---|---|---|
| `TestE2EInfrastructure` | 3 | Redis ping / credential mask / namespace in make_key |
| `TestE2EProviderRegistrarAccessors` | 16 | 全部 16 ops accessor 真实网络 round-trip |
| `TestE2EProviderRegistrarFunctionAccessors` | 8 | 8 个 function accessor ≡ ops accessor（同对象） |
| `TestE2ELockAtomicity` | 2 | Lua 原子 release + renewal watchdog |
| `TestE2EBoundedAtomicity` | 2 | Bounded queue drops oldest / bounded stack rejects |
| `TestE2ENamespaceIsolation` | 2 | 跨 namespace 不互踩 + cross-namespace key 不可见 |
| `TestE2EGlobalCacheFacade` | 4 | install / active 单例 / 互斥 / uninstall |
| `TestE2ESkippedCapabilities` | 6 | 6 个 M1-M4 范围外能力（带 R-### 跟进） |

### Coverage comparison (旧 vs 新)

| 旧 capability ID | 旧测试数 | 新 M5 处理 |
|---|---|---|
| 0.x Infrastructure | 3 | 3 active（ping / mask / namespace） |
| 1.x KV/String | 9 | 1 active（wiring）+ M1 单测覆盖详细 |
| 2.x Hash | 5 | 1 active（wiring）+ M2 单测 |
| 3.x Set | 3 | 1 active + 2 M2 单测 |
| 4.x ZSet | 4 | 1 active + M3.B 单测 |
| 5.x List | 2 | **skip**（无 ListOps；bounded list 替代） |
| 6.x Key | 3 | 1 active + M3.A 单测 |
| 7.x GEO | 2 | 1 active + M3.B 单测 |
| 8.x HLL | 2 | 1 active + M3.B 单测 |
| 9.x Bitmap | 2 | 1 active + M3.B 单测 |
| 10.x Script | 1 | 1 active + M3.A 单测 |
| 11.x BoundedQueue | 5 | 2 active（cap contract）+ M3.C 单测 |
| 12.x BoundedStack | 2 | 1 active + M3.C 单测 |
| 13.x Limiter | 2 | 1 active + M3.A 单测 |
| 14.x Lock | 3 | 2 active（atomicity / renewal）+ M4 单测 |
| 15.x Bloom | 2 | **skip**（不在 M1-M4，cache-core 有 contract） |
| 16.x L2 | 2 | **skip**（不在 M1-M4） |
| 17.x PubSub | 1 | 1 active（仅 publish 端，subscribe 端缺） |
| 18.x KeyspaceListener | 1 | **skip**（不在 M1-M4） |
| 19.x PerfGuard | 2 | **skip**（非 Redis 范围） |
| 20.x Snowflake | 2 | **skip**（不在 M1-M4） |
| 21.x Stampede | 1 | 0 active（M1 单测覆盖 `get_with_lock`） |
| 22.x Facade dispatch | 2 | 0 active（`TestE2EProviderRegistrarAccessors` 16 个 + Function 8 个覆盖了同样内容） |
| 23.x Failure modes | 1 | 2 active（namespace isolation + credential mask） |
| 24.x GlobalCache facade | 7 | 4 active（install / active / 互斥 / uninstall） |

**总计**：旧 90 测试 → 新 37 active + 6 skip = 43 tests。
**未覆盖**的 49 个旧测试，要么是 M1-M4 单测已覆盖（详细度更高），要么
是 M1-M4 范围外（6 个 skip）。

## Test results

```text
37 passed, 6 skipped in 4.37s
```

- **37 passed** — 全部真实 Redis 8.8.0 at 127.0.0.1:16379 round-trip。
- **6 skipped** — M1-M4 范围外的能力（带 R-### 跟进）。

整个 `components/cache-redis/tests/` 套件：
```text
266 passed, 8 skipped in 13.35s
```
（M1-M4 的 229 + M5 的 37 active + 8 total skips = 266/8）

## Capability gaps identified (M5+ roadmap)

1. **NotificationOps `subscribe`** — 当前只有 `publish` 端，缺
   Pub/Sub listener 异步接收。`RedisNotificationManager` 需新增
   `subscribe(topic, handler)` 返回 listener。
2. **EventOps `fire` / `register_listener`** — 当前只有
   `subscribe_key_event`（keyspace event API），缺进程内 in-process
   event bus。
3. **Bloom Filter** — `cache_core/contracts/bloom_filter.py` +
   `config/bloom_filter_config.py` 已就位，缺
   `RedisSharedBloomFilter`（Lua 原子 SETBIT + MGET）。
4. **L2 DistributedCache** — `cache_core/local/` 有 LocalCache
   （cachetools-backed），缺 L2 远程层 fan-out 逻辑。
5. **SnowflakeIdBuilder** — 缺 `RedisSnowflakeManager`（workerId
   持久化 + 64-bit 布局）。
6. **Keyspace Listener** — `cache_core/contracts/keyspace_listener.py`
   有 contract，缺 `RedisKeyspaceListener` 实现。
7. **ListOps** — 故意不出（Java 也无 `ListOps.java`），bounded
   list 替代。

## Test API corrections applied

迁移中发现的 5 个新 API vs 旧 API 关键差异：

1. `cache.value()` (旧 method) → `cache.value_ops()` (新 method)
2. `q.offer("a")` 旧返回 int 长度 → 新返回 bool
3. `q.grow()` 旧返回 int 新长度 → 新返回 bool
4. `s.script().eval("return 42")` 旧 1 参 → 新
   `m.eval(script, keys=[], args=[], result_type=int)` 4 参
5. `q.poll()` 在 `decode_responses=True` + `clazz=bytes` 组合下
   会触发"string argument without an encoding"——bounded queue/stack
   必须用 `clazz=str`

## Next: R-220 M5+ roadmap

按上述 7 个 gap 排 R-### 优先级：
- R-221: NotificationOps `subscribe` 完整实现（Pub/Sub 端到端）
- R-222: Bloom Filter `RedisSharedBloomFilter`（Lua 原子）
- R-223: L2 DistributedCache（LocalCache + Redis L2 fan-out）
- R-224: SnowflakeIdBuilder（Redis 持久 workerId）
- R-225: KeyspaceListener（Redis notify-keyspace-events）
- R-226: EventOps in-process bus

每个 R-### 完成后，对应 E2E skip 解除，capability 升级为 active 测试。
