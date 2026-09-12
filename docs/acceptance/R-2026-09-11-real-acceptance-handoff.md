# R-2026-09-11 真实验收 handoff

> 承接 `TASK_CHECKLIST.md` 的 `[ ]` 项 + 6 大类真实验收。
> `[x]` = 源码就绪且有受控证据；`[ ]` = 待落地；`[!]` = 风险/缺口。
> 受控测试、wheel 安装、CI 绿不等于真实互操作。

## 0. 现状快照（file:line 引用）

### 0.1 已就绪
- [x] HTTP 公共 facade + 受控 transport：`components/http/src/atlas_richie/http/client.py`、 `components/http/src/atlas_richie/http/models.py`
- [x] SSE 解析器（独立于 HTTPX）：`components/http/src/atlas_richie/http/sse.py:30-87`
- [x] ASGI 协议桥 + 服务端订阅/进度：`components/mcp/src/atlas_richie/mcp/transport/asgi/application.py:1-279`、 `components/mcp/src/atlas_richie/mcp/transport/asgi/streaming.py:1-182`（路径于 R-232 重整）
- [x] OAuth 2.1 客户端 + DPoP 核心 + JOSE 适配：`components/oauth/src/atlas_richie/oauth/*.py`、 `components/oauth/src/atlas_richie/oauth/jose/*.py`（路径于 R-232 重整）
- [x] MCP `2026-07-28` 核心、stdio、legacy 适配、MRTR、注册表、调用链：`components/mcp/src/atlas_richie/mcp/*.py`（stdio 已迁至 `transport/stdio/`）
- [x] MCP HTTP 出站 exchange（仅 JSON 响应）：`components/mcp/src/atlas_richie/mcp/transport/http/exchange.py:1-93`（路径于 R-232 重整）
- [x] MCP OAuth bridge + M2M profile（mock 层）：`adapters/mcp-oauth/src/atlas_richie/mcp_oauth/bridge.py:1-109`、 `adapters/mcp-oauth/src/atlas_richie/mcp_oauth/m2m.py:1-30`

### 0.2 关键缺口（直接对应 5 个最关键源码补齐项）
- [x] **resilience 组件（R-104 完成）** — `components/resilience/` 已落：`RetryPolicy` + `RetryExecutor`、`IdempotencyKey` 协议 + 3 个实现、`CircuitBreaker` + `CircuitState`、`TokenBucket` RateLimiter、`Bulkhead`；51/51 单测通过；独立 wheel 构建并被 `tools/release/verify_isolated_wheels.py` 在隔离 venv 中验证安装导入成功。
- [x] **MCP 客户端 SSE 消费 + progress 回调 + 取消传播（R-101 完成）** — `adapters/mcp-http/src/atlas_richie/mcp_http/sse_consumer.py`：`SseConsumerState` (StrEnum) + `SseMcpMessage` 不可变 dataclass + `consume_sse_response` async generator + `_LineBuffer` 跨 chunk 缓冲；`adapters/mcp-http/src/atlas_richie/mcp_http/exchange.py`：`AsyncHttpExecutor` Protocol 扩展 `open_stream`，`McpHttpExchange.__call__` 新增 `on_progress` / `cancellation_token` keyword-only 参数；`components/resilience/.../retry.py`：`RetryPolicy.first_byte_only: bool = False` + `FirstByteSignal` mutable marker。15 个 SSE 单测 + 4 个 first_byte_only 单测通过；现有 51 个 resilience 单测 + 4 个 mcp-http 单测不破坏。
- [x] **OIDC ID Token 验证 + RP-initiated logout（R-102 完成）** — `components/oauth/src/atlas_richie/oauth/id_token.py`：`IdTokenValidator`（frozen dataclass，持有 `TokenValidator` Protocol 做 JWT 验签，叠加 OIDC Core 1.0 §3.1.3.7 校验：nonce / auth_time+max_age / at_hash / c_hash，**Adapter 模式** = 复用通用 TokenValidator + OIDC 专属层）；`code_hash` helper；`components/oauth/src/atlas_richie/oauth/logout.py`：`RpInitiatedLogout` 入口 + `_RpInitiatedLogoutBuilder`（copy-on-write 链式） + `LogoutRequest` 不可变值对象（**Builder 模式**）。22 个 ID Token 单测 + 12 个 logout 单测通过；现有 10 个 oauth 单测不破坏。
- [x] **分布式缓存适配器骨架（R-103 完成 / 驱动实现待 cache 组件）** — `components/oauth/src/atlas_richie/oauth/cache.py`：`DistributedCache` Protocol（4 方法：`get` / `set` / `add_if_absent` / `delete`，全部 docstring + 类型签名）+ `InMemoryDistributedCache`（线程安全 + TTL 过期，**Adapter 模式** = 核心契约 + 多 backend 实现）。3 个 adapter 包骨架（`adapters/oauth-cache-redis/`、`adapters/oauth-cache-hazelcast/`、`adapters/oauth-cache-etcd/`）：每个暴露 `XxxDistributedCache` 类，方法体抛 `NotImplementedError("...等 cache 组件...")`，可构造可验空。契约单测 + 26 个 stub 单测通过；**DpopReplayStore / JWKS 暂不接入 DistributedCache**（等 cache 组件落地后下一轮 R-### 完成）。

### 0.3 矩阵差距引用
- [ ] MCP-P1-03（ASGI）：`docs/acceptance/mcp-2026-07-28-test-matrix.md:16` 标注 "no deployed ASGI server/SSE stream exercised"
- [ ] MCP-P1-04（Bearer）：`docs/acceptance/mcp-2026-07-28-test-matrix.md:17` 标注 "Fake validator only"
- [ ] MCP-P1-05（HTTP）：`docs/acceptance/mcp-2026-07-28-test-matrix.md:18` 标注 "Fake HTTP executor only"
- [ ] `http-component-test-matrix.md` 末段："DNS/proxy, enterprise CA, HTTP/2, real OAuth issuer or production network not verified"
- [ ] `oauth-component-test-matrix.md` 末段："Standards-compliant AS interoperability not verified"

## 1. R-### 编号约定

```text
R-1xx  源码补齐（5 个关键项）
R-2xx  真实环境（Docker / Keycloak / HTTPS / 域名）
R-3xx  真实 HTTP 验收
R-4xx  真实 OAuth/OIDC 验收
R-5xx  A ↔ B 双向验证
R-6xx  Java ↔ Python 互操作
R-7xx  官方协议与生产级
```

## 2. R-1xx：5 个关键源码补齐

### R-101 MCP 客户端 SSE 消费
- **范围**：`adapters/mcp-http/src/atlas_richie/mcp_http/exchange.py` 增加流式分支；新建 `sse_consumer.py`；扩展 `McpClient` 接收 `progress_callback`、`CancellationToken`
- **必须**：
  - 解析 `text/event-stream`，区分 `response` / `request` / `notification/.../progress` / `notifications/.../list_changed`
  - 进度回调单次完成时仅触发一次终态
  - 客户端断开 → 走 `DELETE`（如服务端支持）或发送 JSON-RPC `notifications/cancelled`
- **证据**：
  - 新单元测试：SSE 帧序列、混合 JSON/SSE、`progressToken` 幂等
  - E2E 接入 R-301
- **不属本 R-###**：服务端 `McpServer` 改动（除非 R-301 反推需要）

### R-102 OIDC ID Token 验证 + RP-initiated logout
- **范围**：
  - 新增 `components/oauth/src/atlas_richie/oauth/id_token.py`：`IdTokenValidator`、nonce/at_hash/c_hash/max_age 校验
  - 新增 `components/oauth/src/atlas_richie/oauth/logout.py`：`RpInitiatedLogout`（构造 end_session URL + post_logout_redirect_uri + id_token_hint + state）
  - `__init__.py` 导出
- **必须**：遵循 OIDC Core 1.0 §3.1.3.7、§3.1.3.8 与 RP-Initiated Logout 1.0
- **证据**：
  - 单元测试：iss/aud/nonce/at_hash/c_hash 失败路径
  - 集成测试：R-401 中开启 ID Token 流

### R-103 分布式缓存适配器（JWKS / introspection / DPoP replay）
- **范围**：
  - 抽象 `DistributedCache` 协议（`components/oauth/src/atlas_richie/oauth/cache.py` 新文件）
  - 三个 adapter：Redis（`adapters/oauth-cache-redis/`）、Hazelcast（`adapters/oauth-cache-hazelcast/`）、etcd（`adapters/oauth-cache-etcd/`，可选）
  - `DpopReplayStore` 协议已有 → 用 `DistributedCache` 实现
  - JWKS cache 改为 `DistributedCache` 后端
- **不属本 R-###**：底层 Redis 客户端本身的封装（用 `redis.asyncio` 直连）
- **证据**：
  - 单测：原子性、TTL、误删
  - 多进程互斥测试：2 个进程同时兑换 DPoP 防重放

### R-200 cache 组件重构（**DONE** — 2026-09-11）
- **范围**：撤掉 oauth 仓内嵌的 cache + 3 个 `adapters/oauth-cache-*` stub；为独立的 `components/cache/` 仓让位。
- **证据**：
  - [x] 删 `components/oauth/src/atlas_richie/oauth/cache.py` + 3 个 `adapters/oauth-cache-{redis,hazelcast,etcd}/` 目录
  - [x] `pyproject.toml` workspace / `foundation/platform/pyproject.toml` 同步去名
  - [x] `tools/release/verify_isolated_wheels.py` PACKAGES 列表同步
  - [x] 全量回归 162 单测 OK

### R-201 ~ R-213 cache 组件落地（**DONE** — 2026-09-11）
- **范围**：`components/cache/` 从零开发，对位 Java `atlas-richie-cache` 24 项功能
- **决策依据**：`docs/acceptance/R-cache-java-python-alignment.md`（22 个决策 + 30 段 / ~150 用例测试计划）
- **实现**：
  - Foundation：pyproject + README + `protocol.py`（DistributedCache + RedisBackend + KeyspaceListener + PubSubBus + DistributedLock + BloomFilter + IdGenerator + LockHandle + PubSubMessage + CacheConfig）+ `errors.py` + `core/{data_type,complexity_tier,ttl}.py` + `InMemoryDistributedCache` + `RedisDistributedCache`
  - 12 capabilities：`capabilities/{value,field,struct,collection,ranking,list,key,geo,hyper_log,bitmap,script,limiter}_ops.py`
  - Bounded structures：`structures/{capacity_limits,bounded_list_redis_scripts,bounded_queue,bounded_stack}.py`（Lua 原子 + meta:key 模式，`BOUNDED_MAX_LEN_CEILING=4999` 硬门槛）
  - Distributed lock：`lock/{lock_manager,distributed_lock}.py`（3 层 + Lua compare-and-delete + Redis INCR fencing token）
  - Bloom Strategy：`bloom/bloom_filter.py`（`InMemoryBloomFilter` bytearray 纯 Python + `RedisSharedBloomFilter` SETBIT/GETBIT pipeline + double-hashing md5+sha1）
  - Pub/Sub + Keyspace：`pubsub/{notification,keyspace_listener}.py`（thread-based listener + `__keyevent@*__:*` 解析）
  - L2：`l2/{l2_cache,anti_avalanche}.py`（cachetools.TTLCache Decorator + 1-10 分钟 random offset）
  - Perf Guard：`perf/perf_guard.py`（ComplexityTier enum + 5 档分级 + soft/hard 阈值 + string payload anti-pattern + batch read cap + structlog 集成）
  - Snowflake：`snowflake/id_builder.py`（64-bit layout：41 ts + 10 worker + 12 seq，workerId 从 Redis INCR 持久）
  - Config + Facade：`config.py`（pydantic-settings CacheConfig）+ `__init__.py`（Cache top-level facade）
- **证据**：
  - [x] **真 Redis 8.8.0 E2E 63/63 全过**：`uv run --project components/cache --extra test python -m unittest tests.e2e.test_redis_real`
  - [x] **in-memory E2E 20/20 全过**：`tests.e2e.test_in_memory`（fakeredis + pure-Python 路径）
  - [x] **测试计划全打勾**：`components/cache/TEST_PLAN.md` 30 段 / ~150 用例全 ✅
  - [x] **全仓 wheel 构建**：`uv build --all-packages` 生成 `dist/atlas_richie_cache-0.1.0-py3-none-any.whl`
  - [x] **隔离 venv wheel 验证**：装到空 venv + 真 Redis 烟测通过
  - [x] **全量回归 OK**：10 套件（mcp / oauth / http / resilience / cache / oauth-jose / mcp-http / mcp-oauth / mcp-schema / mcp-legacy）单测全过
- **修复的真实 bug 列表**（按修复顺序）：见 `components/cache/TEST_PLAN.md` 末尾段
  1. `add_if_absent` 比较 `b'OK' == "OK"` 永远 False → `bool(result)`
  2. `value_ops.get_with_lock` 漏 `local` 参数
  3. `BoundedStack.latest` 顺序反了
  4. `HashOps.get` / `get_many` / `ListOps.lpop` 等统一返回 `str`（非 `bytes`）
  5. `redis_distributed_cache.keys` 跨 namespace 清理时 `bytes.startswith(str)` 抛 TypeError
  6. `BoundedQueueOfferScript` 末尾 `return LTRIM` 永远返回 'OK' → 改为 `return LLEN`
  7. `BoundedGrowMaxLenScript` "已到顶" 返回 0 → 改为 `return current`
  8. pubsub 线程先 start 后 subscribe 有竞态 → 线程改在 subscribe 后懒启动
  9. pubsub handler 存在 unprefixed channel key，消息 channel 是 namespaced → loop 内 strip namespace 前缀再查表
  10. `geo_ops.add` `geoadd(name, *sum(...))` 在 redis-py 5.3 签名错 → 改为 flat sequence
  11. `setUp` 只在 test 后清 namespace，跨 test class 状态泄漏 → 在 `setUp` 开始先 bootstrap 一次清理
  12. 测试断言修正 6 处（bitop 长度 / FIFO overflow / union_store 期望 / lrem 期望 / keys pattern / keyspace probe）

### R-214 `GlobalCache` 静态外观类（**DONE** — 2026-09-11）
- **范围**：对位 Java `cn.richie696.component.cache.GlobalCache` 静态门面，给业务层一个 process-wide 单例入口
- **设计决策**：**不要 Spring 容器注入**，改用 env 懒构造（`logging.getLogger()` 风格）
  - `class GlobalCache` + 22 个 classmethod 访问器
  - 16 capability：`value()` / `field()` / `struct()` / `collection()` / `ranking()` / `list()` / `key()` / `geo()` / `hyper_log()` / `bitmap()` / `script()` / `limiter()` / `lock()` / `snowflake()` / `pubsub()` / `keyspace_listener()`
  - 6 参数化 builder：`queue()` / `stack()` / `bloom_in_memory()` / `bloom_shared()` / `l1()` / `perf_guard()`
  - 生命周期：`get()` 懒构造 + `set(cache)` 注入 + `reset()` / `close()` 释放
  - double-checked locking + GIL 原子读
- **环境变量**：`ATLAS_CACHE_REDIS_URL`（默认 `redis://localhost:63779/0`）、`ATLAS_CACHE_NAMESPACE`（默认 `default`）、`ATLAS_CACHE_PASSWORD`
- **架构调整**：把 `class Cache` 拆到 `cache_facade.py`，避免 `__init__.py` 循环导入
- **证据**：
  - [x] §24 E2E 7/7 全过（lazy init / singleton identity / set 注入 + close / reset / 16 访问器 / 6 builder / 幂等）
  - [x] 真 Redis 全 E2E 90/90 = 70 真 Redis + 20 in-memory
  - [x] 全仓回归 10 套件 OK
  - [x] wheel 重建 `atlas_richie_cache-0.1.0-py3-none-any.whl` OK

### R-215 包重组（**DONE** — 2026-09-11）
- **范围**：把 Python 仓 cache 组件的源码目录结构对齐 Java 仓，清晰划分"framework 框架层 / backends 后端层 / ops 能力层 / operations 复合结构 / config 配置层 / enums 枚举 / commons 工具"
- **Java 对位**（`cn.richie696.component.cache`）：
  - `ops/` ← Java 的 `cache/ops/`（drop `_ops` 后缀）
  - `operations/` ← Java 的 `cache/operations/`（Bounded 结构 + capacity limits + Lua 脚本）
  - `config/` ← Java 的 `cache/config/`（`cache_config.py` + `protocols.py`）
  - `commons/` ← Java 的 `cache/commons/`（`ttl.py` 等 cross-cutting 工具）
  - `enums/` ← Java 的 `cache/enums/`（`complexity_tier.py` + `data_type.py`）
  - `backends/{redis,in_memory}/` ← Java 的 `cache/redis/` + `cache/local/`（后端独立成子包）
  - `lock/` `pubsub/` `l2/` `perf/` `snowflake/` `bloom/` ← feature subpackages（与 Java 同构）
- **改名**：
  - `capabilities/*.py` → `ops/*.py`（去掉 `_ops` 后缀，更 Pythonic）
  - `core/{complexity_tier,data_type}.py` → `enums/`
  - `core/ttl.py` → `commons/ttl.py`
  - `structures/*.py` → `operations/*.py`
  - `protocol.py` → `config/protocols.py`
  - `config.py` → `config/cache_config.py`
  - `redis_distributed_cache.py` → `backends/redis/distributed_cache.py`
  - `in_memory_distributed_cache.py` → `backends/in_memory/distributed_cache.py`
- **自动化**：用 `_rewrite_imports.py` + `_fix_depth.py` 两遍脚本批量改 import（30 个文件），再手动修子包内 `__init__.py` 的 sibling import
- **证据**：
  - [x] 真 Redis E2E 90/90 = 70 真 Redis + 20 in-memory
  - [x] 全仓回归 10 套件 OK
  - [x] wheel 重建 `atlas_richie_cache-0.1.0-py3-none-any.whl` OK
- **命名收尾**（R-215 之后小调整）：`cache_facade.py` → `global_cache_manager.py`，文件名跟 Java 的 `GlobalCacheManager` 完全对位；类名 `Cache` 保持（公共 API 不动）

### R-216 文件名 = 类名（snake_case 规则）（**DONE** — 2026-09-11）
- **范围**：7 个文件因文件名 ≠ snake_case(类名) 重命名
- **重命名**：
  - `backends/redis/distributed_cache.py` → `backends/redis/redis_distributed_cache.py`（`RedisDistributedCache`）
  - `backends/in_memory/distributed_cache.py` → `backends/in_memory/in_memory_distributed_cache.py`（`InMemoryDistributedCache`）
  - `l2/l2_cache.py` → `l2/l2_distributed_cache.py`（`L2DistributedCache`）
  - `lock/lock_manager.py` → `lock/local_lock_manager.py`（`LocalLockManager`）
  - `snowflake/id_builder.py` → `snowflake/snowflake_id_builder.py`（`SnowflakeIdBuilder`）
  - `pubsub/notification.py` → `pubsub/notification_bus.py`（`NotificationBus`）
  - `operations/capacity_limits.py` → `operations/bounded_list_capacity_limits.py`（`BoundedListCapacityLimits`）
- **原则**：不再写跨语言注释（Python 仓和 Java 仓是独立对等的两个库）

### R-217 `Cache` → `GlobalCacheManager`（**DONE** — 2026-09-11）
- **范围**：`class Cache` 在 `global_cache_manager.py` 中与第三方库（`cachetools.Cache` / `aiocache.Cache` / `django.core.cache.Cache`）命名冲突，重命名为 `GlobalCacheManager`
- **影响**：
  - `from atlas_richie.cache import Cache` → `from atlas_richie.cache import GlobalCacheManager`
  - `Cache.memory()` / `Cache.redis()` → `GlobalCacheManager.memory()` / `GlobalCacheManager.redis()`
  - 业务层（`GlobalCache.value()`）保持不变
- **证据**：
  - [x] 真 Redis E2E 70/70 + in-memory 20/20 = **90/90**
  - [x] 全仓 10 套件回归 OK
  - [x] wheel 重建 OK

### R-104 resilience 组件（**DONE** — 2026-09-11）
- **范围**：新建 `components/resilience/`：
  - [x] `RetryPolicy`（指数退避 + 抖动 + max_elapsed + 幂等键）— `components/resilience/src/atlas_richie/resilience/retry.py`
  - [x] `IdempotencyKey` Protocol + 3 实现（`StatelessIdempotencyKey`、`NeverIdempotencyKey`、`CallableIdempotencyKey`）— `components/resilience/src/atlas_richie/resilience/idempotency.py`
  - [x] `CircuitBreaker`（closed/half_open/open + sliding window + 失败率阈值）— `components/resilience/src/atlas_richie/resilience/circuit_breaker.py`
  - [x] `TokenBucket` RateLimiter — `components/resilience/src/atlas_richie/resilience/rate_limit.py`
  - [x] `Bulkhead`（并发上限 + 等待队列）— `components/resilience/src/atlas_richie/resilience/bulkhead.py`
  - [x] `Clock` / `SystemClock` / `ManualClock` / `RandomSource` 注入 — `components/resilience/src/atlas_richie/resilience/clock.py`
  - [x] 错误类（`ResilienceError` / `RetryExhausted` / `RetryNotPermitted` / `CircuitOpen` / `RateLimitExceeded` / `BulkheadFull`）— `components/resilience/src/atlas_richie/resilience/errors.py`
- **接入点**（不在 R-104 内做，只标位置，下游 R-### 接入）：
  - `components/http/src/atlas_richie/http/client.py:HttpClientOptions` 增加 `resilience` 字段
  - `McpHttpExchange` 增加可选 `retry` 参数
- **证据**：
  - [x] 单测 51/51 通过：`uv run python -m unittest discover -s components/resilience/tests`
  - [x] 独立 wheel 构建：`uv build --all-packages` 生成 `dist/atlas_richie_resilience-0.1.0-py3-none-any.whl`
  - [x] `tools/release/verify_isolated_wheels.py` 隔离 venv 验证通过，依赖图无冲突
  - [x] `pyproject.toml` 工作区已注册，`foundation/platform/pyproject.toml` 聚合包已含 `atlas-richie-resilience`
- **未在 R-104 scope 内**（保留给后续 R-###）：
  - HTTP client 接入 resilience（在 R-301 / R-304）
  - MCP HTTP exchange 接入 retry（在 R-101 / R-304）
  - 分布式 token bucket / circuit breaker（R-103 顺带）

### R-105 可重复运行的 Docker + 真实网络验收脚本
- **范围**：
  - `tools/acceptance/` 目录：
    - `compose/keycloak.yml`（本地 Keycloak + 初始化 realm）
    - `compose/two-process.yml`（应用 A + 应用 B）
    - `scripts/run_real_http.py`、`scripts/run_real_oauth.py`、`scripts/run_two_process.py`
    - `scripts/assert.py`（统一失败/通过判定 + 快照保存到 `dist/acceptance/`，**绝不**写 token/secret/完整 header）
  - `pyproject.toml` 增加 `[tool.acceptance]` 段（profile、timeout、snapshots_dir）
- **必须**：
  - 凭证全部 env（`KEYCLOAK_REALM`、`KEYCLOAK_ADMIN_PASSWORD`、`TLS_CERT_DIR`），不入仓
  - `.gitignore` 增加 `dist/acceptance/secrets/`、`*.p12`、`*.key`
  - 所有结果携带版本 + 配置摘要（package version、Python、ASGI server、Keycloak version）
- **证据**：
  - 干跑 `tools/acceptance/scripts/run_real_http.py --dry-run` 在无 Keycloak 时也能输出"环境就绪 checklist"
  - 完整跑通后产出 `dist/acceptance/<date>/summary.md` + 每个 case 的 `*.json`（脱敏后）

## 3. R-2xx：真实环境

### R-201 Docker Keycloak + HTTPS
- `tools/acceptance/compose/keycloak.yml` + realm import（client `app-a`、`app-b`、audience mapping、scopes）
- 本地自签 CA：`tools/acceptance/certs/` 由脚本生成（不入仓）
- 固定测试域名（写入 `tools/acceptance/scripts/hosts.py`，不入 `/etc/hosts`，由脚本 patch container DNS）
- 固定 issuer/audience/tenant/scopes 写入 `tools/acceptance/scripts/constants.py`

### R-202 两个独立 Python 进程（A / B）
- 容器 A、B 各自独立 venv、Uvicorn
- 双方都注册 A↔B 镜像 DPoP client
- 启动后用 `tools/acceptance/scripts/healthcheck.py` 双侧探测

### R-203 反向代理 + HTTP/2 + 企业 CA（可选）
- Caddy/Traefik：HTTP/2、client cert、header mirror
- 主要为 R-301 / R-302 留位

## 4. R-3xx：真实 HTTP 验收

### R-301 Streamable HTTP 双向 JSON 响应 + SSE 进度
- 走真实 HTTPX，连接池、超时、TLS 全部真实
- 进度回调通过 R-101 验证

### R-302 长连接 / 订阅 / 断流
- 客户端断网后服务端能识别（`McpServer` 需在 `adapters/mcp-asgi/src/atlas_richie/mcp_asgi/streaming.py` 接入 disconnect 回调）
- 触发 cancel propagation

### R-303 客户端取消
- `DELETE` 路径 + `notifications/cancelled`
- 服务端任务必须真停（用 `asyncio.Task.cancel()` + cleanup）

### R-304 重试 / 幂等 / 限流 / 熔断
- 串联 R-104
- 故意制造 5xx → 验证指数退避、熔断半开、限流超限
- 幂等键：request id 镜像 + JSON-RPC `id`

## 5. R-4xx：真实 OAuth/OIDC 验收

### R-401 Authorization Server Metadata + PRM 真实发现
- Keycloak `.well-known/openid-configuration`、`.well-known/oauth-protected-resource`
- 客户端必须先 GET PRM 再选 AS

### R-402 Client Credentials 双向 M2M
- A 拿 token → call B；B 拿 token → call A
- 同一 keycloak、两个 client、audience 严格隔离

### R-403 Authorization Code + PKCE
- 用 Playwright/httpx 模拟浏览器 → 回调 → code → token
- 保存 wire fixture（不含 code、state 一次性值）

### R-404 JWKS 首次获取 / 缓存 / 未知 kid 刷新 / 密钥轮换
- 用 Keycloak admin API 触发 rotation
- 验证 R-103 分布式缓存下，两个进程都能正确切换

### R-405 Introspection fallback
- 用 access_token 调 introspection endpoint，验证 active=false 被拒

### R-406 DPoP 完整链
- `cnf.jkt` 与 JWK thumbprint 匹配
- `ath` = b64url(SHA-256(access_token))
- nonce（如果 AS 支持）
- 防重放走 R-103

### R-407 负向安全矩阵
| 用例 | 期望 |
|---|---|
| 错误 issuer | 401 + `iss` 错 |
| 错误 audience | 401 + `aud` 错 |
| scope 不足 | 403 + `insufficient_scope` |
| tenant 串用 | 401 + `tenant` 错 |
| 过期 token | 401 + `exp` 错 |
| 缺失 token | 401 + `WWW-Authenticate` + PRM URL |

### R-408 RP-initiated logout
- 用 R-102 退出后，资源服务器拒绝旧 token

## 6. R-5xx：A ↔ B 双向验证

按用户给的镜像图，每个用例双向跑：

### R-501 双向成功调用
- A Client → B MCP Server + B Client → A MCP Server
- 验证 `aud=B resource` / `aud=A resource` 双向正确

### R-502 audience 串用拒绝
- A 拿到的 token（aud=B）去调 A 自身 → 拒

### R-503 scope 不足 403
- token 缺 `tools:invoke` → `tools/call` 返回 403

### R-504 无 / 无效 token 401
- 缺失 / 篡改 / 过期 → 401 + `WWW-Authenticate`

### R-505 tenant 串用拒绝
- token 含 `tenant=a` 但调用方声明 `tenant=b` → 401

### R-506 DPoP 绑定
- 错误 method/uri → 401
- 重放旧 proof → 401（R-103 命中）

### R-507 MRTR state 在 registry revision 变化后失效
- 触发 A 的 registry reload → 旧 MRTR state 被拒

## 7. R-6xx：Java ↔ Python 互操作

四组必跑：

| 用例 | 客户端 | 服务端 | 目标 |
|---|---|---|---|
| R-601 | Python modern | Java modern | 主流路径 |
| R-602 | Java modern | Python modern | 主流路径反向 |
| R-603 | Python modern | Java legacy | 协议版本协商 |
| R-604 | Java legacy | Python legacy adapter | 老协议兼容 |

每组保存 wire fixture（截取 JSON-RPC body、header mirror、分页 cursor、错误码、SSE 帧、OAuth challenge、DPoP header）到 `dist/acceptance/java-interop/`，**不**保存 token、code、verifier、jti。

## 8. R-7xx：官方协议与生产级

### R-701 官方 MCP conformance / wire fixture
- 拉取官方 fixture 仓库（如有），跑 compliance 套件
- 输出未覆盖项清单

### R-702 并发 / 长连接 / 断线重连 / 故障恢复
- 100 并发 + keep-alive 30 分钟 + 主动断网 1 分钟

### R-703 性能基线 + 资源泄漏
- p50 / p95 / p99 latency、QPS、内存峰值、FD 峰值
- 关闭后 `RuntimeError` 触网 = 0

### R-704 安全扫描
- TLS（`testssl.sh` 或 `sslyze`）
- 依赖（`pip-audit` / `safety`）
- 容器（`trivy` 或 `grype`）
- OAuth 流程无 token 落盘

## 9. 凭证与安全红线

- **仅 env**：所有 secret 必须 `os.environ` 读取，仓库任何文件不得含真实值
- **示例值**：`tools/acceptance/scripts/constants.py` 用 `<set-in-env>`、`changeme` 之类占位
- **快照脱敏**：`tools/acceptance/scripts/assert.py` 的 `redact()` 必须覆盖：
  - `access_token` / `refresh_token` / `id_token` / `code` / `verifier` / `state` / `jti` / `dpop` 头
  - `Authorization` header 整体
  - `Set-Cookie` 任何敏感字段
- **不入仓**：`.gitignore` 增量：
  ```
  tools/acceptance/certs/
  tools/acceptance/realm-export/
  dist/acceptance/secrets/
  dist/acceptance/*/raw/
  ```

## 10. 推荐执行顺序

```text
R-104 (resilience 组件)  ← DONE 2026-09-11
   └─> R-101 (MCP 客户端 SSE)
          └─> R-102 (OIDC ID Token + logout)
                 └─> R-103 (分布式缓存)
                        └─> R-105 (Docker + 真实网络脚本骨架)
                               └─> R-201 (Keycloak + HTTPS)
                                      └─> R-202 (双进程)
                                             ├─> R-301 ~ R-304 (HTTP)
                                             ├─> R-401 ~ R-408 (OAuth)
                                             └─> R-501 ~ R-507 (A↔B)
                                                    └─> R-601 ~ R-604 (Java↔Python)
                                                           └─> R-701 ~ R-704 (官方 + 生产级)
```

R-104 已完成。下一项是 **R-101 MCP 客户端 SSE 消费**。

## 11. 当前 next

按 `TASK_CHECKLIST.md:74` 现指向 **R-101 MCP 客户端 SSE 消费 + progress 回调 + 取消传播**，依赖 R-104 已就绪。
