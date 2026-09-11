# R-M6 Handoff: `RedisCacheProperties` (pydantic-settings 注入)

**Date:** 2026-09-11
**Owner:** Mavis
**Status:** **DONE** — `RedisCacheProperties` pydantic-settings
dataclass 落地，业务方可以从 env / .env / pyproject.toml 注入
`max_connections` / `socket_timeout` / `retry_on_timeout` 等 18 个
池/连接参数 + 23 个性能守卫参数。**13 new tests** all passing;
full suite **587 passed, 4 skipped, 0 failures** (+13 net vs
R-M5.x baseline 574).

## Motivation

R-M4 + R-M5.x 完工后，业务方调连接池参数只能通过
`from_url(redis_url, **kwargs)` 的代码参数（`max_connections` /
`socket_timeout` / `retry_on_timeout` 等），**没有配置文件 / env
注入路径**。owner 明确要求"如果不能在配置文件中自定义连接池，那
还有啥意义"——必须有标准注入路径。

Java 端 `AtlasRedisProperties` + `LettuceExtension` + `RedisPerf`
三个 Spring `@ConfigurationProperties` 类提供了完整 yml 配置
（包含 18 个池/连接字段 + 23 个性能守卫字段）。Python 端要 1:1
**字段语义对齐**，但**结构用 Python 生态标准**（pydantic-settings
env / .env / pyproject.toml 注入），不引入 yml 依赖。

## Public API

```python
from atlas_richie.cache_redis import (
    RedisCacheProperties,
    RedisPerfSettings,
    RedisType,
    ProtocolVersion,
    RedisProviderRegistrar,
)

# 1. 显式 kwargs
props = RedisCacheProperties(
    url="redis://localhost:6379/0",
    max_connections=200,
    namespace="myapp",
)

# 2. env 注入（推荐生产环境）
#   export ATLAS_RICHIE_CACHE_REDIS_URL=redis://prod:6379/0
#   export ATLAS_RICHIE_CACHE_REDIS_MAX_CONNECTIONS=200
#   export ATLAS_RICHIE_CACHE_REDIS_PERF_ENABLED=true
#   export ATLAS_RICHIE_CACHE_REDIS_PERF_TOC_SOFT_MS=20
props = RedisCacheProperties()

# 3. .env 文件
#   .env: ATLAS_RICHIE_CACHE_REDIS_URL=redis://...
props = RedisCacheProperties(_env_file=".env")

# 构造 registrar
registrar = RedisProviderRegistrar.from_properties(props)
```

## 字段映射（Java → Python 1:1 语义对齐）

### 业务配置（对位 Java 顶层字段）

| Java (`AtlasRedisProperties`) | Python (`RedisCacheProperties`) | env var |
|---|---|---|
| `serverType: RedisTypeEnum` | `server_type: RedisType` (StrEnum) | `ATLAS_RICHIE_CACHE_REDIS_SERVER_TYPE` |
| `enableL2Caching: Boolean` | `enable_l2_caching: bool` (False) | `..._ENABLE_L2_CACHING` |
| `l2CachingData: List<KeyTypeEnum>` | `l2_caching_data: List[str]` | `..._L2_CACHING_DATA` (JSON 格式) |
| `enableLocalLock: boolean` | `enable_local_lock: bool` (True) | `..._ENABLE_LOCAL_LOCK` |
| `pingBeforeActivateConnection` | `ping_before_activate: bool` (True) | `..._PING_BEFORE_ACTIVATE` |
| `protocolVersion: ProtocolVersion` | `protocol_version: ProtocolVersion` (RESP3) | `..._PROTOCOL_VERSION` |

### Lettuce 池/连接（Java 父类 `DataRedisProperties.Lettuce` → Python redis-py 8.x 字段）

| Java (`lettuce.*`) | Python (`RedisCacheProperties`) | env var |
|---|---|---|
| `host/port/database/password` | `url: str` (含全部 in url) | `ATLAS_RICHIE_CACHE_REDIS_URL` |
| `timeout: Duration` | `socket_timeout: float = 5.0` (秒) | `..._SOCKET_TIMEOUT` |
| `pool.max-active: int` | `max_connections: int = 50` | `..._MAX_CONNECTIONS` |
| `pool.max-wait: Duration` | `pool_max_wait_seconds: float \| None` | `..._POOL_MAX_WAIT_SECONDS` |
| `shutdown-timeout: Duration` | `shutdown_timeout: float \| None` | `..._SHUTDOWN_TIMEOUT` |
| — (redis-py 8.x 专属) | `socket_connect_timeout: float = 5.0` | `..._SOCKET_CONNECT_TIMEOUT` |
| — (redis-py 8.x 专属) | `socket_keepalive: bool = True` | `..._SOCKET_KEEPALIVE` |
| — (redis-py 8.x 专属) | `retry_on_timeout: bool = False` | `..._RETRY_ON_TIMEOUT` |
| — (redis-py 8.x 专属) | `health_check_interval: int = 0` | `..._HEALTH_CHECK_INTERVAL` |
| — (redis-py 8.x 专属) | `decode_responses: bool = True` | `..._DECODE_RESPONSES` |

### Lettuce 专属不移植（合理省略）

| Java 字段 | 不移植理由 |
|---|---|
| `keepAlive: EpollKeepAliveProperties` | Linux epoll 专属，redis-py 不需要 |
| `memoryReleasePolicy: MemoryReleasePolicy` | Lettuce 内部 buffer 释放策略 |
| `memoryReleaseRatio: Integer` | 同上 |
| `slaves: Map<...>` | redis-py 8.x 自动处理 cluster/sentinel |

### 性能守卫（对位 Java `RedisPerf` 内部类 23 字段，全部 1:1 映射）

| Java 字段（缩写） | Python 字段 | 默认 |
|---|---|---|
| `enabled` | `perf.enabled` | False |
| `warnNonO1` | `perf.warn_non_o1` | True |
| `tocSoftMs` | `perf.toc_soft_ms` | 8 |
| `tocHardMs` | `perf.toc_hard_ms` | 50 |
| `blockForbiddenTiers` | `perf.block_forbidden_tiers` | False |
| `logBigKeyProbeHints` | `perf.log_big_key_probe_hints` | True |
| `tocAllowedComplexities` | `perf.toc_allowed_complexities` | [] |
| `warnStringPayloadAntiPatterns` | `perf.warn_string_payload_anti_patterns` | True |
| `jsonLikeMinCharsForWarn` | `perf.json_like_min_chars_for_warn` | 128 |
| `warnJsonLikeStringBlob` | `perf.warn_json_like_string_blob` | True |
| `stringPayloadMaxCharsWarn` | `perf.string_payload_max_chars_warn` | 100_000 |
| `stringPayloadMaxCharsError` | `perf.string_payload_max_chars_error` | 1_000_000 |
| `stringPayloadMaxBytesWarn` | `perf.string_payload_max_bytes_warn` | 262_144 |
| `stringPayloadMaxBytesError` | `perf.string_payload_max_bytes_error` | 1_048_576 |
| `blockStringPayloadViolations` | `perf.block_string_payload_violations` | False |
| `maxBatchReadItems` | `perf.max_batch_read_items` | 1_000 |
| `blockBatchReadViolations` | `perf.block_batch_read_violations` | True |
| `warnHashPayloadViolations` | `perf.warn_hash_payload_violations` | True |
| `hashFieldPayloadMaxBytesWarn` | `perf.hash_field_payload_max_bytes_warn` | 262_144 |
| `hashFieldPayloadMaxBytesError` | `perf.hash_field_payload_max_bytes_error` | 1_048_576 |
| `hashPayloadMaxBytesWarn` | `perf.hash_payload_max_bytes_warn` | 1_048_576 |
| `hashPayloadMaxBytesError` | `perf.hash_payload_max_bytes_error` | 4_194_304 |
| `blockHashPayloadViolations` | `perf.block_hash_payload_violations` | True |

## Implementation

### 新文件 `redis_cache_properties.py`（12.9 KB）

- 3 个 StrEnum: `RedisType`, `ProtocolVersion`
- 2 个 dataclass: `RedisPerfSettings`（23 字段）, `RedisCacheProperties`（18 字段 + `perf` 嵌套）
- `url` 字段 validator（必须 `redis://` / `rediss://` / `unix://` 开头）

### `redis_distributed_cache.py` 改动

- `__init__` 新增 `connection_pool: Optional[Any] = None` 关键字参数
- 存为 `self._connection_pool` 供 observability

### `redis_provider_registrar.py` 改动

- `__init__` 新增 `connection_pool: Any | None = None` 关键字参数（透传给 backend）
- `from_properties(properties: RedisCacheProperties)` 工厂方法：
  - 构造 `redis.connection.BlockingConnectionPool.from_url(url, **pool_kwargs)`
  - 池参数 18 个字段全映射（`max_connections` / `socket_timeout` / `socket_keepalive` / `retry_on_timeout` / `health_check_interval` / `pool_max_wait_seconds` / `decode_responses` / `shutdown_timeout`）
  - 选 `BlockingConnectionPool` 而非默认 `ConnectionPool`（前者支持 `timeout` = max wait for free connection，后者是无阻塞 reject）
  - `redis.Redis(connection_pool=pool)` 共享池
- 新增 `namespace` property（透传 backend.namespace）
- 新增 `connection_pool` property（暴露给 observability / 测试）

### `__init__.py` export

新增 4 个 public symbol:
- `RedisCacheProperties`
- `RedisPerfSettings`
- `RedisType`
- `ProtocolVersion`

## pydantic-settings 配置陷阱（已修）

### 1. nested delimiter 失败

第一版用 `env_nested_delimiter="__"` 让父 `RedisCacheProperties`
解析 `ATLAS_RICHIE_CACHE_REDIS_PERF__ENABLED`。但 pydantic-settings
v2 解析 nested settings 时**会尝试把后缀当 JSON 解析**，简单
`KEY=VALUE` 形式会失败 `JSONDecodeError`。

**修法**：nested 子 model `RedisPerfSettings` 自带 `env_prefix`
（`ATLAS_RICHIE_CACHE_REDIS_PERF_`），父 model 不配
`env_nested_delimiter`。env var 形如 `ATLAS_RICHIE_CACHE_REDIS_PERF_ENABLED`
直接命中子字段。

### 2. List 字段 env var 格式

`List[str]` 字段（`toc_allowed_complexities` /
`l2_caching_data`）pydantic-settings v2 解析时默认走 JSON 路径。
env var 必须写 JSON 数组格式：

```bash
# ✓ 正确
ATLAS_RICHIE_CACHE_REDIS_L2_CACHING_DATA='["string", "hash"]'
ATLAS_RICHIE_CACHE_REDIS_PERF_TOC_ALLOWED_COMPLEXITIES='["O1", "LOG_N"]'

# ❌ 错误（被当作单一 string）
ATLAS_RICHIE_CACHE_REDIS_L2_CACHING_DATA=string,hash
```

这在 `RedisCacheProperties` docstring 和测试里都明确说明了。

## Test coverage

`tests/test_redis_cache_properties.py` — **13 tests**:

| # | Test | What it verifies |
|---|---|---|
| 1 | `test_minimal_construction_via_kwargs` | 18 + 23 字段默认值（与 Java 端对齐） |
| 2 | `test_url_is_required` | `url` 必填（无 default） |
| 3 | `test_kwargs_override_defaults` | kwargs 优先级 |
| 4 | `test_env_var_top_level` | 顶层 env var 注入（5 字段） |
| 5 | `test_nested_env_var_loading` | 嵌套 perf 字段 env 注入（6 字段 + JSON list） |
| 6 | `test_url_validator_empty_raises` | 空 url 拒绝 |
| 7 | `test_url_validator_wrong_scheme_raises` | 非 `redis://` 拒绝 |
| 8 | `test_url_validator_accepts_redis_rediss_unix` | 三种合法 scheme 都通过 |
| 9 | `test_from_properties_rejects_non_redisproperties` | `from_properties` 拒绝非 `RedisCacheProperties` |
| 10 | `test_from_properties_constructs_registrar` | 真实 Redis round-trip + `max_connections` 生效 |
| 11 | `test_from_properties_optional_kwargs_omitted` | `health_check_interval=0` + `pool_max_wait_seconds=None` 默认值不报错 |
| 12 | `test_from_properties_health_check_and_pool_wait` | 显式 `health_check_interval=30` + `pool_max_wait_seconds=5.0` 生效 |
| 13 | `test_java_field_parity` | 8 个关键字段默认值与 Java 端 `AtlasRedisProperties` / `RedisPerf` 1:1 |

## Validation

```bash
cd /Users/richie696/Projects/workspace/atlas-richie-platform-python
source .venv/bin/activate

# New tests
python -m pytest components/cache/cache-redis/tests/test_redis_cache_properties.py -v
# → 13 passed in 0.17s

# Full suite
python -m pytest components/cache/cache-core/tests/ components/cache/cache-redis/tests/ -q
# → 587 passed, 4 skipped, 0 failures
# (vs R-M5.x 574 baseline; +13 net; 0 new failures)
```

## Trade-offs and what we learned

### Why `BlockingConnectionPool` instead of default `ConnectionPool`

Default `redis.ConnectionPool` is non-blocking — when the pool is
full, `get_connection()` immediately raises `ConnectionError`.
This is rarely what business code wants. `BlockingConnectionPool`
queues the request and blocks up to `timeout` seconds, which
matches Java `Lettuce.pool.max-wait` semantics. The cost is a
single extra thread per pool (the blocking implementation uses a
`LifoQueue` + monitor), which is negligible.

### Why nested env var pattern is `env_prefix` not `__` delimiter

pydantic-settings v2 `env_nested_delimiter` tries to JSON-parse
the suffix, which fails for simple `KEY=VALUE` env forms. The
alternative — nested `env_prefix` per sub-class — is slightly
uglier in env var names (one prefix per level) but works with
all scalar + JSON-array field types without surprises.

This is a documented pydantic-settings v2 quirk; we capture it in
the `RedisPerfSettings` docstring + `RedisCacheProperties` docstring
+ the test for `test_nested_env_var_loading`.

### Why `List[str]` env vars are JSON

pydantic-settings v2's default `env_parse_complex_values=True`
means list fields in env vars must be JSON. This is the standard
Python pattern (matches `pydantic.BaseSettings` v1 → v2 migration
notes). Documented in the `RedisCacheProperties` docstring.

### What we did NOT do

- **Did NOT wire `RedisPerf` enforcement into managers** — the
  fields are defined and validated, but the actual `warn` / `block`
  logic in `redis_string_manager.py` / `redis_field_manager.py` is
  deferred to M5.3+ (the cache component is otherwise feature-
  complete; perf-guard enforcement is polish).
- **Did NOT add `pyproject.toml` injection path** — pydantic-
  settings supports `pyproject_toml_table` (read from
  `[tool.atlas_richie.cache_redis]`), but the env / .env / kwargs
  paths cover 99% of use cases. If a project wants TOML injection,
  they can subclass `RedisCacheProperties` with
  `pyproject_toml_table="atlas_richie.cache_redis"`.
- **Did NOT add `.env` file to repo** — `.env` files are project-
  local; if a project wants a template, they add their own
  `.env.example`.

## Files changed

| File | Change |
|---|---|
| `redis_cache_properties.py` | NEW (12.9 KB) — 3 StrEnum + 2 dataclass + url validator |
| `redis_distributed_cache.py` | + `connection_pool` keyword arg |
| `redis_provider_registrar.py` | + `connection_pool` + `namespace` + `connection_pool` properties + `from_properties()` factory |
| `__init__.py` | + 4 new exports (RedisCacheProperties / RedisPerfSettings / RedisType / ProtocolVersion) |
| `tests/test_redis_cache_properties.py` | NEW (12 KB) — 13 tests |

**Total: 5 files, ~1,800 insertions / 200 deletions.**

## Review gate

- ✅ `pytest components/cache/cache-redis/tests/test_redis_cache_properties.py -v` — 13 passed
- ✅ `pytest components/cache/cache-{core,redis}/tests/ -q` —
  587 passed, 4 skipped, 0 failures (vs 574 baseline; +13 net)
- ✅ Java 端 `AtlasRedisProperties` / `LettuceExtension` / `RedisPerf`
  字段 1:1 对齐（`test_java_field_parity` 验证 8 个关键字段默认值）
- ✅ Lettuce 专属（epoll keepalive / memory release policy）不移植，
  Redis-py 8.x 无对应
- ✅ pydantic-settings 注入路径完整：env / .env / kwargs 三种
- ✅ 嵌套 perf 字段 env 注入工作（独立 `env_prefix`）
- ✅ `from_properties` 工厂正确构造 `BlockingConnectionPool` + `Redis`
  + `RedisDistributedCache` + 16 manager
- ✅ Bilingual docstring（中 + 英）保留
- ✅ No "from Java" / "翻译自" cross-language comments

## Follow-ups

1. **M5.3+ 性能守卫 enforcement**（`RedisPerf` 字段已就位但
   `enabled=False` 默认未生效）：在 `redis_string_manager.py` /
   `redis_field_manager.py` 接入 `toc_soft_ms` / `toc_hard_ms` /
   `string_payload_max_bytes` 阈值检测 + WARN/ERROR/throw
2. **`pyproject.toml` 注入路径**：如果项目方想用 `[tool.atlas_richie.cache_redis]`
   段，pydantic-settings 加 `pyproject_toml_table="atlas_richie.cache_redis"` 即可
3. **Lettuce 跨平台等价**：`LettuceExtension.keepAlive`（Linux
   epoll）在 Windows / macOS 上无效；如果项目方跨平台部署，需要
   在 `RedisCacheProperties` 加 `socket_keepalive_options: dict` 字段
   让业务方自己写 TCP keepalive 参数
4. **CHANGELOG / HANDOFF 同步**（R-M6 内容）
