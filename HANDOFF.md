# Atlas Richie Platform Python

## 会话交接说明

本文档承接当前会话中已经形成的全部规划，作为 `atlas-richie-platform-python` 独立工程的后续实施基线。

目标不是简单地把 Java 类逐个翻译成 Python，而是建立 Atlas Richie Component 家族的 Python 原生技术中台：保持跨语言行为契约一致，同时采用 Python 社区标准的打包、异步、协议和扩展方式。

## 1. 已确定的产品与仓库命名

现有 Java 工程已经使用：

```text
atlas-richie-platform
```

Python 独立工程采用：

```text
GitHub repository: atlas-richie-platform-python
Project name:     Atlas Richie Platform Python
PyPI aggregate:   atlas-richie-platform
Import namespace: atlas_richie.*
```

推荐的组件发行包名称：

```text
atlas-richie-contracts
atlas-richie-testing
atlas-richie-mcp
atlas-richie-http
atlas-richie-concurrency
atlas-richie-secret
atlas-richie-logging
atlas-richie-tracing
atlas-richie-cache
atlas-richie-storage
atlas-richie-vector
```

GitHub 仓库使用 `-python` 后缀，是为了与已经存在的 Java 仓库区分；平台产品名本身保持为 Atlas Richie Platform。后续如果建设其他语言实现，可以沿用：

```text
atlas-richie-platform-go
atlas-richie-platform-rust
```

发行包名称在正式发布前必须再次检查 GitHub 和 PyPI 是否可用，但不应再改变产品根名。

## 2. 总体架构决策

采用单仓库、多发行包的 workspace 模式，而不是一个巨型 Python 包。

```text
业务应用
   │
   ▼
Profiles / Framework Integrations
   │
   ├──────────────► Adapters ─────► 第三方 SDK
   │
   ▼
Atlas Richie Components
   │
   ▼
Minimal Contracts
```

依赖方向必须保持单向：

```text
contracts ← components ← adapters ← profiles/examples
```

禁止：

- 组件之间循环依赖；
- 全局 DI 容器、Service Locator、隐式单例；
- 自动扫描用户模块并修改用户对象生命周期；
- 把所有公共代码堆进一个 `core` 包；
- 在核心包中直接引入 FastAPI、HTTPX、Redis、Pydantic、OpenTelemetry 等第三方库；
- 将业务领域模型、数据库表结构或具体厂商协议放入中台核心。

## 3. 推荐仓库结构

```text
atlas-richie-platform-python/
├── pyproject.toml                 # workspace 配置，不直接作为业务包
├── uv.lock                        # 开发和 CI 的统一锁文件
├── README.md
├── ARCHITECTURE.md
├── VERSIONING.md
├── DEPENDENCY_POLICY.md
├── SECURITY.md
├── RELEASE.md
├── packages/
│   ├── platform/                  # atlas-richie-platform 聚合包
│   ├── contracts/                 # atlas-richie-contracts
│   ├── testing/                   # atlas-richie-testing
│   ├── mcp/                       # atlas-richie-mcp
│   ├── http/                      # atlas-richie-http
│   └── concurrency/               # atlas-richie-concurrency
├── adapters/
│   ├── fastapi/
│   ├── httpx/
│   ├── redis/
│   └── opentelemetry/
├── profiles/
├── specs/
│   ├── component-contract-template/
│   ├── compatibility/
│   └── platform-release.toml
├── contract-tests/
├── examples/
└── tools/
    ├── release/
    └── dependency-check/
```

根目录 workspace 不负责承载全部代码。每个可发布包必须拥有自己的 `pyproject.toml`、`src/` 目录、测试和版本信息。

## 4. 聚合包设计

`atlas-richie-platform` 是安装和兼容性聚合包，不是代码大包。

建议支持：

```bash
pip install atlas-richie-platform
pip install "atlas-richie-platform[mcp]"
pip install "atlas-richie-platform[web]"
```

聚合包负责：

- 声明经验证的组件版本组合；
- 提供可选 extras；
- 提供平台级 README、兼容矩阵和迁移说明；
- 后期作为 Python 版 Maven BOM 的用户入口。

聚合包不负责：

- 导出所有组件实现；
- 默认安装全部第三方 SDK；
- 维护全局运行时容器；
- 隐式注册所有已安装插件。

除了聚合包之外，还应维护 `specs/platform-release.toml` 或 constraints 文件，记录一次平台验证过的组件版本组合。

## 5. `contracts` 最小边界

`atlas-richie-contracts` 必须保持零运行时依赖，内容只包括多个组件确实共享的稳定契约，例如：

- `Lifecycle`：启动、关闭和资源释放；
- `Health`：健康状态和检查结果；
- `ComponentDescriptor`：组件名称、版本、能力描述；
- `ComponentError`：稳定错误分类和可序列化信息；
- 必要的协议版本和能力标识。

不要过早把 tenant、request context、数据库模型、配置对象等全部放进 contracts。只有当两个以上组件需要完全一致的语义时，才提升为跨组件契约。

## 6. MCP 首个纵向组件

MCP 是第一个正式实现的 Python 组件，用于验证中台的端口、传输、生命周期、插件和契约测试设计。

建议公开 API：

```python
from atlas_richie.mcp import McpServer, McpClient

server = McpServer(name="demo")

@server.tool()
def get_weather(city: str) -> dict:
    ...

server.run_stdio()
```

MCP 第一阶段应覆盖：

- JSON-RPC 消息模型；
- stdio transport；
- Streamable HTTP transport；
- server/client 会话生命周期；
- tools、resources、prompts；
- capabilities 和协议版本协商；
- request id、错误映射、取消和超时；
- 任务/进度等最新协议能力；
- 鉴权与安全边界；
- 黑盒兼容性测试。

Python 版本不应要求用户继承复杂基类。装饰器只负责登记工具元数据，业务函数本身保持可直接调用。

框架适配单独放入 adapter：

```python
app.mount("/mcp", server.asgi_app())
```

MCP 核心应优先使用标准库；HTTPX、FastAPI、Uvicorn 等作为可选适配依赖。

## 7. 非侵入式开发方式

核心原则：显式构造、显式挂载、显式启用。

推荐方式：

- `Protocol` 定义端口；
- 构造器注入依赖；
- `dataclass` 表达配置；
- 装饰器登记工具、资源和中间件；
- `asgi_app()`、`run_stdio()` 等显式启动入口；
- 使用 adapter 包连接第三方框架；
- 使用 `importlib.metadata.entry_points()` 发现插件，但通过配置白名单显式启用。

不推荐：

- 全局 `ApplicationContext`；
- 类路径字符串自动扫描；
- import 模块即产生副作用；
- 安装一个插件包后自动改变系统行为；
- 用继承体系模拟 Spring Bean 生命周期。

## 8. 设计模式候选

第一阶段建议只使用以下模式：

| 模式 | 使用位置 | 目的 |
|---|---|---|
| Adapter | Redis、HTTPX、FastAPI、向量库 | 隔离第三方 SDK |
| Strategy | 重试、序列化、鉴权、传输 | 显式替换策略 |
| Facade | `McpServer`、`McpClient` | 提供简洁入口 |
| Decorator | MCP tool/resource/prompt、中间件 | 非侵入式声明和横切逻辑 |
| Chain of Responsibility | tracing、tenant、权限、日志 | 组合处理链 |
| Factory Method | 根据配置创建 provider | 隔离构造逻辑 |

暂不引入全局事件总线、复杂 Abstract Factory、强制模板方法和大型继承树。只有出现真实的第二实现和稳定变化轴后再抽象。

## 9. 同步、异步和依赖策略

建议：

- MCP、HTTP、消息、存储、向量等 I/O 组件采用 async-first；
- 脱敏、分块、I18n、状态机等纯计算组件保持同步；
- 不要为每个 API 同时维护 sync 和 async 两套完整实现；
- 同步业务接入异步组件时，提供明确的桥接 adapter，例如 `asyncio.to_thread`；
- 核心运行时只依赖 Python 标准库；
- 第三方库进入独立 adapter 或 optional extra；
- 开发工具依赖和运行时依赖必须严格分离。

## 10. 版本和发布策略

不要让所有组件共用一个版本号。

推荐：

- 每个发行包独立使用 SemVer；
- 组件 tag 例如 `atlas-richie-mcp-v0.1.0`；
- 组件之间使用窄范围兼容依赖，例如 `>=1.2,<2.0`；
- `uv.lock` 只作为仓库开发和 CI 基线；
- `platform-release.toml` 记录平台验证过的组合；
- 聚合包只发布经过验证的兼容组件范围；
- 破坏性变化必须同步更新组件规格和迁移文档。

## 11. 组件文档模板

每个组件都要维护同样的文档边界：

```text
README.md
docs/
├── api.md
├── configuration.md
├── semantics.md
├── providers.md
├── observability.md
├── security.md
└── conformance.md
```

文档必须优先说明：

- 输入；
- 输出；
- 错误；
- 配置；
- 使用场景；
- 限制；
- 第三方 provider；
- 已验证证据。

不要把 Java 类、Spring Bean、Maven 模块结构直接当成 Python 公共 API。应迁移行为契约，而不是实现结构。

## 12. 分阶段路线

### Phase 0：仓库宪章

创建：

- `ARCHITECTURE.md`；
- `DEPENDENCY_POLICY.md`；
- `VERSIONING.md`；
- `RELEASE.md`；
- 组件规格模板；
- Python 版本支持矩阵；
- 包命名和导入命名空间规则。

### Phase 1：最小基础设施

先实现：

- `contracts`；
- `testing`；
- workspace 和构建流程；
- 独立 wheel 安装验证；
- 依赖方向检查；
- 文档和发布自动化。

### Phase 2：MCP 样板组件

实现 MCP server/client 和协议兼容性测试，形成第一个可复用样板。

### Phase 3：MCP 周边平台能力

优先顺序：

```text
http → concurrency → secret → logging → tracing → web → tenant
```

### Phase 4：数据和 AI 能力

再逐步加入：

```text
cache → storage → vector → document-parser → chunking → ai
```

DAO、Liquibase、MongoDB 等 Java 特有模块不应直接照搬，应只保留迁移、事务、持久化和治理语义。

## 13. CI 与验证要求

每个发行包必须完成：

- 独立构建 wheel 和 sdist；
- 在干净虚拟环境中安装 wheel；
- 仅使用声明依赖进行 import smoke test；
- `pip check`；
- 单元测试；
- 契约测试；
- Python 版本矩阵测试；
- API 公共符号检查；
- 依赖漏洞检查；
- 包内容和 namespace 检查。

workspace 共享环境可能掩盖未声明依赖，因此不能只在 workspace 根目录运行测试。必须增加“每包独立安装”检查。

运行时验证还要区分：

- source/build 静态证据；
- 本地单元与契约测试；
- server/client 运行时测试；
- 浏览器或真实 HTTP E2E；
- 第三方服务和云环境验证。

构建成功不等于 MCP 协议行为、鉴权、路由或下游业务已经被证明。

## 14. 当前下一步

在这个独立工程中，下一轮建议按以下顺序开始：

1. 固化仓库名称、PyPI 名称和 Python 支持版本；
2. 创建根 workspace `pyproject.toml`；
3. 创建 `packages/platform`、`packages/contracts`、`packages/testing`、`packages/mcp`；
4. 编写 `ARCHITECTURE.md` 和组件规格模板；
5. 先完成 MCP 的 stdio 最小闭环；
6. 建立独立 wheel 安装和契约测试；
7. 再扩展 Streamable HTTP 和 adapter。

本文件是规划交接，不代表上述代码已经实现，也不代表所有运行时、第三方服务或云环境验证已经完成。

---

## 15. R-220 → R-M4 实施状态（截至 commit `233bd43`）

本文档第 1-14 章写于工程启动初期，定义了"做什么"。本节记录"做到了哪一步"，
方便后续接手者快速对齐实际状态 vs 规划基线。

### 15.1 仓库布局（已落地）

R-220 已采用本文档第 1 章的命名约定并搭建单仓多发行包 workspace：

```text
atlas-richie-platform-python/
├── foundation/
│   ├── contracts/      # atlas-richie-contracts (PlatformError 等)
│   ├── platform/       # atlas-richie-platform (aggregate)
│   └── testing/        # atlas-richie-testing (fixtures + fakes)
├── components/
│   ├── http/           # atlas-richie-http
│   ├── mcp/            # atlas-richie-mcp
│   ├── oauth/          # atlas-richie-oauth
│   ├── resilience/     # atlas-richie-resilience
│   └── cache/          # ← R-220 重点
│       ├── cache-core/   # atlas-richie-cache-core (Protocols + LocalCache)
│       └── cache-redis/  # atlas-richie-cache-redis (Redis backend)
├── adapters/           # 6 个 adapter 包（mcp-*, oauth-jose）
├── tools/              # sync_versions + release/* + dependency-check
├── versions.toml       # R-228: 15 包版本单一源
├── pyproject.toml      # workspace aggregator
└── uv.lock             # 已 commit
```

### 15.2 cache component 实施里程碑

| 里程碑 | 范围 | handoff doc | 状态 |
|---|---|---|---|
| R-220 | cache-core + cache-redis 完整骨架（16 ops + 11 function + 16 manager + 30-method `ProviderRegistrar` SPI） | `docs/acceptance/R-220-cache-redis-handoff.md` (+ m1/m2/m5 子文档) | DONE |
| R-221 | `NotificationOps.subscribe()` + `RedisNotificationListener` + `NotificationFunction` | `docs/acceptance/R-221-R-226-handoff.md` | DONE |
| R-222 | `BloomFilterConfig` + `InMemoryBloomFilter` + `RedisSharedBloomFilter`（BITSET + Lua 原子） | 同上 | DONE |
| R-223 | `L2DistributedCache`（L1 cachetools + L2 Redis）+ `L2CacheFactory`（per-config 缓存） | 同上 | DONE |
| R-224 | `RedisSnowflakeIdBuilder`（64-bit ID + Redis 持久化 workerId） | 同上 | DONE |
| R-225 / R-226 | 内部基础设施收尾 | 同上 | DONE |
| R-227 | cache parent restructure（`components/cache/{core,redis}/` 双包布局） | `docs/acceptance/R-227-cache-parent-restructure-handoff.md` | DONE |
| R-228 | `versions.toml` + `tools/sync_versions.py` 集中版本管理 | `docs/acceptance/R-228-central-version-management-handoff.md` | DONE |
| R-229 | 77 个 docstring 中英双语化（从 Java Javadoc 翻译） | `docs/acceptance/R-229-bilingual-docstring-migration-handoff.md` | DONE |
| R-230 | 12 个 glue 文件中英双语化（Python 原创，新写中文段） | `docs/acceptance/R-230-glue-files-bilingual-polish-handoff.md` | DONE |
| R-M4 | 10 个 `*_with_lock` 方法体实现（stampede prevention，per-key Lua 锁） | `docs/acceptance/R-M4-stampede-prevention-handoff.md` | DONE |
| R-M5.1 | `loader_timeout_millis` keyword 参数加到全部 10 个 `*_with_lock` | `docs/acceptance/R-M5-1-loader-timeout-handoff.md` | DONE |
| R-M5.2 | `L2DistributedCache.get_or_load()` (L1 + in-process stampede，per-key `threading.Lock` + `WeakValueDictionary`) | `docs/acceptance/R-M5-2-l1-stampede-handoff.md` (+ design `R-M5-2-l1-stampede-design.md`) | DONE |
| R-M5.3 / M5.3.7 | `L2DistributedCache.get_or_load_many()` + `L2CacheStats` 可观测性 + negative cache（M5.7/Phase A2 合并到 `3c65f34`） | `CHANGELOG.md` 描述（无独立 handoff） | DONE |
| R-M5.4 | `RedisPerfGuard` enforcement facade（5 managers，6 enforcement paths，零开销默认） | `docs/acceptance/R-M5-4-perf-guard-handoff.md` | DONE |
| R-M6 | `RedisCacheProperties`（pydantic-settings env 注入；23 字段 `RedisPerfSettings` + lock settings） | `docs/acceptance/R-M6-redis-cache-properties-handoff.md` | DONE |
| Phase B.0 | `foundation/contracts` 3 个 core 文件双语 docstring | 包含在 `ab8049a` commit message | DONE |
| Phase B.1–B.4 | `components/http` (15) + `components/mcp` (18) + `components/oauth` (11, R-231) + `components/resilience` (10) 全员双语 docstring | `docs/acceptance/R-231-oauth-bilingual-docstring-handoff.md` | DONE |
| Phase C | root `conftest.py` + `tests/integration/conftest.py` + pytest markers (`unit` / `integration` / `e2e`) | `a60a0c6` commit message | DONE |
| Phase D | cross-component integration tests（cache + http / mcp / oauth 共 3 文件 13 tests） | `bfaa7fa` commit message | DONE |
| Phase E | E2E tests（http / mcp / oauth / resilience 共 4 文件 38 tests；MCP client `request_id_offset` 修复） | `06ec5e3` commit message | DONE |

### 15.3 关键架构决策（与原规划的偏差）

1. **cache component 拆成两个 wheel 而不是一个**（R-227）：
   原规划是 `atlas-richie-cache` 单一包；实际拆为 `cache-core`（Protocols +
   LocalCache + 占位 backend 接口）与 `cache-redis`（具体实现）。理由：
   Dragonfly / KeyDB / 内存测试替身等未来 backend 可以做独立 wheel 而不
   拖入 Redis 依赖。
2. **`ProviderRegistrar` 协议 + 后端包互斥注册**（R-218 决定）：一进程
   一 provider，注册第二个抛 `StateError`。`CacheRegistry` 是 framework
   核心门禁，`RedisProviderRegistrar` / `InMemoryProviderRegistrar`（测试用）
   都实现同一 Protocol。
3. **stampede 锁与 business 锁两套独立**（R-M4）：`__stampede_lock__:{key}`
   vs `__lock__:{key}`，不同 namespace 不同语义，可共存。inline Lua 而非
   `RedisLockManager` 注入，4 个 manager 共享 module-level helpers。
   **两层 stampede 防御**（R-M4 + R-M5.2）：R-M4 的 Redis Lua 锁防御
   cross-process 重复 loader；R-M5.2 的 in-process `threading.Lock` 防御
   in-process 重复 loader（per-key，`WeakValueDictionary` 持有，弱引用
   自动 GC）。`L2DistributedCache.get_or_load` 走 in-process 锁；
   `RedisStringManager.get_with_lock` 走 Redis 锁；两者各司其职，
   caller 按需选用（与 Java 端 `L2DistributedCache` 无 stampede 锁一致）。
4. **`db_loader` 超时 backstop**（R-M5.1）：`loader_timeout_millis`
   keyword-only 参数 + `_call_db_loader_with_timeout` 共享 helper。
   `concurrent.futures.ThreadPoolExecutor(max_workers=1)` + `future.result
   (timeout=...)`，超时返 `None`（不写 cache、不抛异常），stampede 锁
   立即释放。Python 不支持 `pthread_cancel`，hung loader 线程
   best-effort 终止，是 backstop 而非硬保证。
5. **docstring 双语**（R-229 + R-230）：中段在上（Java Javadoc 翻译或 Python
   原创）+ 英段在下，锚点 `中文\n----` + `English\n--------`。后续所有新
   docstring 默认双语。
6. **uv_build 不支持 `dynamic = ["version"]`**：版本管理走 `versions.toml`
   + `tools/sync_versions.py` 同步方案，不走 PEP 621 dynamic version。
4. **docstring 双语**（R-229 + R-230）：中段在上（Java Javadoc 翻译或 Python
   原创）+ 英段在下，锚点 `中文\n----` + `English\n--------`。后续所有新
   docstring 默认双语。
5. **uv_build 不支持 `dynamic = ["version"]`**：版本管理走 `versions.toml`
   + `tools/sync_versions.py` 同步方案，不走 PEP 621 dynamic version。

### 15.4 现状指标（截至 Phase F commit `06ec5e3`）

```text
16 commits since Initial commit（全部已 push 到 origin/main）:
  5a925bb  R-220..R-229: bootstrap atlas-richie-platform-python + cache component
  1613654  R-230: bilingual polish for 12 top-level glue files
  233bd43  R-M4: stampede prevention for Value/String/Hash/Set/Struct
  d6cecd2  R-M4.x: CHANGELOG.md + HANDOFF.md 收尾
  7734524  R-M5.2: design doc
  375b13c  R-M5.1: loader_timeout_millis kwarg on all 10 *_with_lock methods
  c08ed30  R-M5.2: L2DistributedCache.get_or_load (L1 + in-process stampede)
  112be7e  R-M5.x: CHANGELOG.md + HANDOFF.md sync (R-M5.1 + R-M5.2 收尾)
  b9ec93f  fix: stabilize pre-existing flaky keyspace-event tests
  f416b46  bump: 0.1.0 -> 0.2.0
  02f8ec8  R-M6: RedisCacheProperties (pydantic-settings env injection)
  c61748e  M5.3: get_or_load_many + stats observability
  ab8049a  Phase B.0: foundation/contracts 双语 docstring (3 文件)
  3c65f34  M5.3.7 + Phase A2+A3 + Phase B (4 components bilingual)
  a60a0c6  Phase C: pytest markers (unit/integration/e2e) + cache-redis conftest
  0252da9  R-M5.4: RedisPerfGuard enforcement facade + manager wiring
  bfaa7fa  Phase D: integration tests for cache + http/mcp/oauth cross-component
  06ec5e3  Phase E: E2E tests for http/mcp/oauth/resilience components

Test counts (unit + integration, no E2E):
  pytest components/ -m "not e2e" -q
  → 773 passed, 2 skipped, 0 failures
  (cache 638 + non-cache 135; vs R-220 baseline 369 passed; +404 net)

Test counts (Phase E e2e subset):
  pytest components/{http,mcp,oauth,resilience}/tests/test_e2e_*.py -q
  → 79 passed, 2 skipped, 0 failures
  (the 2 skipped are pre-existing xfail keyspace listener tests)

Test counts (cache-redis E2E):
  pytest components/cache/cache-redis/tests/test_e2e_real_redis.py -q
  → 41 passed, 2 skipped, 0 failures (43 collected; needs real Redis + keyspace)

Bilingual docstring coverage: 194 files
  R-229: 77 files (Java Javadoc 翻译)
  R-230: 12 files (Python 原创 + 新写中文段)
  Phase B.0: 3 files (foundation/contracts)
  Phase B.1: 15 files (http)
  Phase B.2: 18 files (mcp)
  Phase B.3 + R-231: 11 files (oauth)
  Phase B.4: 10 files (resilience)
  + cache polish 中文段若干 (3c65f34)

Stampede prevention coverage:
  Cross-process (R-M4): 10 public methods across 4 managers
    RedisStringManager:  get_with_lock, get_from_string_with_lock
    RedisFieldManager:   get_with_lock, get_with_lock_typed,
                         get_object_from_hash_with_lock,
                         get_from_hash_with_lock,
                         get_from_hash_with_lock_typed,
                         get_many_with_lock
    RedisCollectionManager: get_with_lock, get_from_set_with_lock
    RedisStructManager:  get_with_lock, get_with_lock_typed
  In-process (R-M5.2): L2DistributedCache.get_or_load (1 method, all keys)
  Loader timeout (R-M5.1): all 11 stampede methods accept loader_timeout_millis
  Negative cache (M5.7/Phase A2): get_with_lock 接受 negative_cache_ttl

Stampede tests: 117 (R-M4) + 98 (R-M5.1) + 14 (R-M5.2) + 6 (M5.7) = 235 stampede-specific
Net test count delta: R-220 369 → 773 = +404 (+229 stampede + 175 other)

─── Two-layer stampede defense ───

  R-M4: cross-process funnel (Redis Lua SET NX PX)
  R-M5.2: in-process funnel (per-key threading.Lock + WeakValueDictionary)

  Caller chooses layer:
    L2DistributedCache.get_or_load(key, loader, ...)   → in-process only
    RedisStringManager.get_with_lock(key, ttl, loader) → cross-process (R-M4)
    Both methods re-use _call_db_loader_with_timeout   → loader timeout
```

### 15.5 仍待办（Stage 1 已完成；Stage 2 待启动）

**Stage 1 (atlas-richie-platform-python) — 已完成**:
- 4 个 component（cache / http / mcp / oauth / resilience）骨架 + 双语 docstring
- 16 ops + 11 function cache Protocol；Redis backend；stampede + perf guard + negative cache
- 3 阶段测试体系：unit (R-M5) + integration (Phase D) + e2e (Phase E)
- 18 handoff docs in `docs/acceptance/`
- 16 commits 全部 push 到 origin/main

**Stage 2 候选（按 HANDOFF §12 路线图 + 实战优先级）**:
- **secret component**（§60 任务清单：cache / secret / logging / tracing 中下一个）
- **logging + tracing components**（与 secret 并列）
- **storage / vector / document / AI components**（§61）
- **Gateway / Antivirus 应用层**（§62）
- **Java ↔ Python 互操作验证**（§66-70，conformance / wire fixture / 真实 IdP）
- **发布准备**：
  - `versions.toml` 15 个包目前都是 `0.2.0`（`f416b46` 已 bump）
  - 启用 GitHub Actions 中的 `ci.yml` + `publish.yml`（已写好，待推 PyPI 凭据）

**已知 pre-existing flakiness**（不在 R-M4/M5 范围，已知问题不阻塞发版）:
- `test_redis_event_manager.py::TestKeyspaceEventListener::test_expired_event_fires`
- `test_e2e_real_redis.py::TestE2ESkippedCapabilities::test_7_4_keyspace_listener`
  两者在 full-suite 跑时偶发失败（keyspace notification 时序敏感），
  单独跑或重跑均通过。已在 `b9ec93f` 加上 stabilizing fixture，后续单独
  闭环（建议用 `pytest --reruns 2` 或异步 listener 配 fixture 进一步稳定化）。
