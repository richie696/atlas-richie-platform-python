# Atlas Richie Platform Python 实施计划（提案）

> 状态：P0/P1、单 Provider HTTP Component 与 OAuth P1（client/resource server）已实施；框架适配器尚未开始。
>
> 目标：以 Python 原生方式落实 Java 技术中台已验证的**行为契约**，不翻译 Spring Bean、注解、Maven 模块或 JVM 并发实现。

## 1. 已确认的边界

- 仓库：`atlas-richie-platform-python`；导入命名空间：`atlas_richie.*`。
- 发布模型：单仓库、多独立发行包；`atlas-richie-platform` 仅是兼容组合与安装入口，不是代码巨包。
- 依赖方向：`contracts <- components <- adapters <- profiles/examples`。
- **框架无关是不可违反约束**：公共 API 不能依赖或暴露 FastAPI、Django、Flask、Starlette、Pydantic、SQLAlchemy、HTTPX、Redis、OpenTelemetry 等任何框架/SDK 类型。除明确记录的 `http` Component 对 HTTPX 的单实现依赖外，核心只依赖 Python 标准库与公开协议。
- 任何底层框架或 SDK 都只能通过独立 adapter/extra 连接，且 adapter 单向依赖组件；安装 adapter 不得改变核心或其他 adapter 的默认行为。
- Java 中台是能力与证据来源，不是 Python 的代码模板。每项迁移能力都要标注已验证、待环境验证、设计中或不迁移。
- [`CODE_QUALITY.md`](CODE_QUALITY.md) 是所有实现的硬门槛：公开 API 必须 Pythonic；具备协议、业务、安全、生命周期或兼容语义的值必须命名且单点拥有；同一生产行为只能有一个权威实现；OOP 边界与依赖方向必须可审查、可测试。

Java MCP 已具备 protocol、schema、stdio transport、server/client core、OAuth 与 testkit 的明确模块边界；Python 首期保留这些能力边界，但不会复刻 Spring Boot starter 或引入任何 Python 版“Spring”。

### Java 产品边界在 Python 中的映射

Python 采用与 Java **相同的产品分层、不同的基础层切分**：

```text
Java                            Python
----                            ------
atlas-richie-base       ->      minimal contracts + testing + release governance
atlas-richie-component  ->      component packages（当前唯一实施范围）
gateway-service          ->      future independent gateway application
antivirus-service        ->      future independent antivirus application
```

`base` 在 Java 中同时承载契约、依赖 BOM、Spring 上下文、Servlet、ORM 与测试支撑；Python 若照搬为一个运行时 `base` 包，会重新制造框架绑定的“公共杂物箱”。因此不发布泛化的 `atlas-richie-platform-base`：

- `contracts`：仅多个组件实际共享的、零运行时依赖的稳定协议与错误分类；
- `testing`：测试夹具、契约套件和隔离安装工具，不进入生产运行时；
- `platform`：仅发布组合、兼容矩阵和约束，不导出实现；
- `component-*`：每项可安装能力独立发布、独立测试、独立演进；
- Gateway/Antivirus：以后作为独立应用部署、配置和演进，只消费组件公开 API，不能把应用领域模型或框架依赖回灌组件库。

当前仓库先内聚 Component；Gateway 和 Antivirus 暂不创建空壳目录或伪实现。待组件在真实业务应用中被验证后，再决定它们是否位于独立仓库或本仓库的 `services/` 边界。

MCP 作为首个纵向 Component 的模块边界、双端协议与双向 OAuth 认证设计见 [COMPONENT_MCP_ARCHITECTURE_PLAN.md](COMPONENT_MCP_ARCHITECTURE_PLAN.md)。

## 2. 需要先冻结的工程决策

| 决策 | 建议 | 原因 |
|---|---|---|
| Python 基线 | Python `>=3.12`；CI 覆盖 3.12–3.14，3.15 仅预发布兼容检查 | 3.12 仍是主流生产版本，同时保留当前受支持版本的升级通道，避免为已结束常规支持的版本维持兼容层。 |
| 构建工作区 | `uv` 管理 workspace/lock，`uv_build` 构建 wheel/sdist | 锁定用于开发/CI，包元数据和构建保持 PEP 517/621 标准，并减少构建工具链。 |
| 版本策略 | 每个发行包独立 SemVer；平台聚合包只声明已验证组合 | 避免无关组件被同一版本号强行绑定。 |
| 协议规格 | `specs/mcp/` 维护版本化 JSON Schema、行为案例与互操作夹具 | 协议和黑盒测试先于 Python 私有类型。 |
| 初期依赖 | `contracts` 运行时零第三方依赖；MCP stdio 核心仅用标准库 | 能独立安装、可裁剪，也不让框架影响协议语义。 |

本机已安装 Homebrew Python `3.12.14` 与 `uv 0.12.10`；P0/P1 的构建和隔离安装验证以该环境执行。发布兼容性仍须由 CI 的完整 Python 矩阵证明。

## 3. 分期与交付门槛

### P0：Component 宪章与发布骨架

产物：根 `pyproject.toml`、`ARCHITECTURE.md`、`DEPENDENCY_POLICY.md`、`VERSIONING.md`、`RELEASE.md`、Component 规格模板、`specs/platform-release.toml`、Python 支持矩阵。

验收：依赖方向可静态检查；每个发行包有自己的 `pyproject.toml` 与 `src/`；文档明确公开 API、配置、错误、语义、provider、观测和验证状态。

### P1：Component 最小共享基础设施

范围：`contracts`、`testing`、平台聚合包，以及独立 wheel/sdist 安装检查；不创建 Gateway/Antivirus 应用。

验收：每一个 wheel 在干净虚拟环境中可安装、import，且 `pip check` 通过；共享 workspace 环境不能作为声明依赖正确性的证据。

### H1：单 Provider HTTP Component

范围：`atlas-richie-http`，以 HTTPX 为唯一内部实现；平台拥有不可变
request/response DTO、超时和连接限制、响应大小上限、错误分类、显式 client lifecycle、
request-id/audit/caller interceptor pipeline。无 Provider SPI，公开 API 不泄漏 HTTPX 类型。

非范围：HTTP server、框架 adapter、OAuth、重试、熔断、限流、全局 client、全局关闭
TLS 校验开关。重试和韧性策略以后由 concurrency/resilience 组件定义幂等与预算后再接入。

验收：HTTPX 受控 transport 覆盖请求 ID、切面顺序和短路、错误映射、响应上限、关闭和
安全默认值；真实 TCP/DNS/代理/企业 CA/HTTP2 为独立环境验证。

### P2：MCP stdio 可互操作闭环

范围：JSON-RPC 编解码与验证、`initialize` 协商、tools/resources/prompts 发现、tool 调用、请求 ID、受控错误、取消、通知/进度、关闭，以及 stdio transport。工具函数可以同步或 async；装饰器仅登记元数据，函数仍可直接调用。

非范围：ASGI/FastAPI、HTTP client/server、OAuth、自动插件发现、全局 DI、业务权限模型、缓存和持久化。这些不因 MVP 而被静默假实现。

验收：同进程黑盒 server/client、子进程 stdio、畸形帧、未知方法、schema 违规、取消、重复关闭和资源释放都由契约测试覆盖；交叉实现互操作另列为待环境验证。

### P3：MCP HTTP、协议桥与安全适配

范围：Streamable HTTP core transport、ASGI/WSGI 等公开协议桥、将现有 OAuth resource-server principal 显式注入 MCP HTTP 请求。FastAPI、Django、Flask 或任何其他框架都只能消费这些协议桥或提供各自的独立 adapter，不拥有 MCP 核心。

验收：HTTP transport 与协议桥不泄漏任何框架类型；安全未启用时不产生网络或后台副作用，启用后认证失败一律受控拒绝。

### P4：其余通用运行时能力

顺序：`concurrency -> secret -> logging -> tracing -> web -> tenant`。

- Concurrency：取消传播、截止时间、重试抖动、限流等待、熔断状态与批量顺序必须可测。
- Secret：首次加载失败 fail-closed；刷新仅保留已验证快照，并原子切换。
- Logging/Tracing：采用 OpenTelemetry/W3C 语义；敏感字段默认不得记录。

### P5：数据与 AI 能力

顺序：`cache -> storage -> vector -> document-parser -> chunking -> ai`。DAO、Liquibase、MongoDB 不复制 Java 实现，只另行定义事务、迁移账本与持久化治理语义。

## 4. MCP v0 详细边界

### 责任与数据所有权

- `contracts` 拥有跨组件生命周期、健康、描述符与稳定错误分类；不持有 MCP 或 Web 专属模型。
- `mcp` 拥有协议规范化、server/client 生命周期、工具注册表、调用上下文与 transport port。
- `stdio` transport 拥有流帧、读写、EOF 和资源关闭；不得知道工具业务语义。
- 业务应用拥有工具实现、授权决策、配置装配和进程入口。
- 后续 ASGI/WSGI 桥或框架 adapter 仅把运行时请求转换为 MCP transport input/output，不能反向被 MCP 核心依赖。

同步结果（如 `tools/call`）通过最小的调用 Port 返回；工具已变更、审计已产生等事实只在确有独立订阅者后以稳定事件发布。v0 不预置全局事件总线。

### 协议版本策略

公开 `McpServer`/`McpClient` 不暴露“新旧协议分支”。内部以版本化 `Dialect` 规范化 wire message，并由 negotiation 策略选择；不支持的版本返回稳定、可诊断的协议错误。每个 dialect 必须通过同一份 protocol/transport 契约测试，不能仅凭可解析而宣称兼容。

## 5. 编码前的设计模式候选

以下为已评估的候选；实施前须经确认。

| 具体位置 | 候选模式与设计 | 解决的问题与收益 | 误用防护与验证 |
|---|---|---|---|
| `McpServer`、`McpClient` 的公开入口 | **Facade**：少量稳定操作隐藏注册表、会话、编解码与关闭顺序 | 使用者不用了解 transport 或协议内部对象 | 不转发所有内部方法；API 按 server/client 消费者拆分。测试只经公共入口完成初始化、调用、取消与关闭。 |
| stdio、HTTP 等传输 | **Adapter** + 受控 **Factory Method**：core 的 transport port 由明确配置创建适配实现 | 隔离 `sys.stdin/out`、ASGI/HTTPX 等技术类型，新增 transport 不修改 protocol core | 工厂只选择 transport，不承载权限/业务路由；契约测试检查底层类型不越过 port、错误和关闭语义一致。 |
| 协议版本与编码差异 | **Strategy**：每个 `Dialect` 负责版本专属规范化/验证，Negotiator 负责选择 | 不把“若版本 A/B”散到 tool API 和 transport | 仅用于真实的独立版本差异；定义不支持版本、默认策略、冲突策略。各 dialect 执行同一兼容夹具。 |
| `@server.tool()` | **Decorator**：登记不可变工具元数据，不包装或替换业务函数 | 无侵入声明 schema/name/description，同时保留函数直接可测 | 装饰器不得做 I/O、自动启动或隐式鉴权；测试直接调用函数和经协议调用各一次。 |
| 调用横切点（P2 后段） | **Chain of Responsibility**：显式、有序的 invocation interceptor 链 | 可按需插入审计、trace、超时、鉴权，而不污染工具函数 | v0 只有当至少两个独立横切能力落地时才引入；固定顺序、短路、异常与无人处理语义均写入契约。 |

未采用：Singleton/Service Locator（隐藏依赖和测试污染）、Abstract Factory（尚无需成组替换的对象族）、Template Method（组合策略比继承层级更适合 Python）、Observer（尚无独立订阅者的事实流）、Builder（v0 配置字段不足以证明其复杂度）。

## 6. 初始 Component 包布局

```text
foundation/
  contracts/  # atlas-richie-contracts
  testing/    # atlas-richie-testing
  platform/   # atlas-richie-platform: extras + verified ranges only
components/
  mcp/        # atlas-richie-mcp
  http/       # atlas-richie-http；HTTPX 单实现，拥有调用切面
  oauth/      # atlas-richie-oauth；client/resource-server contracts
adapters/
  oauth-jose/ # atlas-richie-oauth-jose；JOSERFC 验签适配
  # concurrency、secret 等在各自阶段加入
adapters/     # 每个框架或 SDK 一个可物理裁剪的发行包；不属于 core
specs/
  component-contract-template/
  mcp/{api,configuration,semantics,providers,observability,conformance}/
  platform-release.toml
contract-tests/
examples/
tools/{release,dependency-check}/
```

ASGI/WSGI 协议桥与各框架/SDK adapter 只在 P3/P4 创建；目录预留不等于包、依赖或功能已经存在。`services/gateway`、`services/antivirus` 不在当前初始化范围内。

## 7. 发布与验证流水线

1. 格式、类型与静态依赖方向检查。
2. 各包独立构建 wheel 和 sdist。
3. 新建虚拟环境，仅安装目标 wheel 与其声明依赖。
4. import smoke、`pip check`、单元测试与公开符号检查。
5. 协议黑盒契约：成功、失败、边界、取消、时序与资源释放。
6. Python 版本矩阵；stdio 子进程互操作；HTTP adapter E2E 仅从 P3 起执行。
7. 第三方 SDK、OAuth、云 Provider、性能结果必须标为独立环境证据，不可由构建替代。

## 8. 下一次实施的输入与完成定义

P0/P1、H1 与 OAuth P1 已实施：workspace、foundation 三个发行包、`components/mcp`、
`components/http`、`components/oauth`(含 `oauth.jose` 子包)、仓库宪章、规格模板和隔离安装验证均已存在。后续不开始 Gateway、
Antivirus、OAuth/Redis 或框架 adapter，除非获得新的范围确认。

完成定义是：目录和包元数据符合依赖方向，文档与机器可读规格有单一来源，CI 能证明每包在隔离环境中安装和导入；它不是 MCP 运行时兼容完成声明。
