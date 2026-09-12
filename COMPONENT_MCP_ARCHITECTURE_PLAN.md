# Atlas Richie Python Component 与 MCP 架构规划

> 状态：**MCP `2026-07-28` core、stdio、Draft 2020-12 Schema、ASGI、HTTP client、OAuth resource-server bridge、协作式取消上下文、HMAC 保护的 MRTR state codec（绑定 server/ASGI、主体/tenant/scope/resource/registry revision）、原子 registry reload、固定的 trace/deadline/caller/audit 调用链、ASGI Streamable HTTP 的 SSE progress/订阅/断流清理、client 端 capability cache/失效/async 自动分页，以及隔离发行的 `2025-11-25` legacy dialect adapter 均已实现并有受控契约测试。SSE 只在 ASGI adapter 管理，不污染 MCP core；真实 HTTPS/SSE peer、真实 OAuth issuer 与跨语言互操作验收仍待应用集成阶段完成。**
>
> 决策目标：先建立框架无关、依赖最小、可独立发布的 Component 层；以此实现 Python 原生 MCP，使两个采用 Atlas Richie Component 的应用可以双向发现、调用和认证。

## 1. 规划依据与证据边界

本规划以 Java 中台的以下当前资产为行为来源，而不是逐行翻译来源：

| 来源 | 已抽取的事实 |
|---|---|
| `atlas-richie-mcp-parent/README.zh.md` | Java MCP 已拆为 API、protocol、schema、server core、HTTP/stdio transport、OAuth、Spring starter、testkit；业务 API 不感知协议与传输。 |
| `docs/zh/mcp-component-design.md` | 基线为 MCP `2026-07-28`，兼容 `2025-11-25`；modern 是无状态协议，要求 `server/discover`、每请求 `_meta`、`resultType`、Streamable HTTP、OAuth resource binding。 |
| `docs/zh/mcp-server-starter-business-tool-adaptation-plan.md` | Registry 必须原子替换；调用需要按协议校验、权限、Schema、取消、观测、业务处理、输出校验的顺序执行；业务配置不能执行任意代码/SQL。 |
| `mcp-protocol`、`mcp-server-core`、`mcp-transport-*`、`mcp-security-oauth` 源码与测试 | 当前 Java 实现确实存在 Dialect、Schema 预编译、不可变 Registry 快照、HTTP header/body 校验、stdio newline framing、PRM/OAuth URI policy 与 token-provider SPI。 |

Java 文档记录了其 P0–P3 的实现和单元测试状态；这仅作为 Python 的设计证据，**不构成 Python 兼容性、互操作性或生产认证已经验证的证据**。

## 2. Component 第一原则

### 2.1 不存在 Python 版 Spring

Python Component 是应用可选择的能力库，不是应用必须继承的运行时。核心不拥有 DI 容器、应用生命周期、HTTP 路由、ORM Session 或全局配置中心。

```text
任意 Python 应用 / 任意框架 / CLI / Worker
                    │ 显式构造、显式挂载
                    ▼
          可选 Framework / SDK Adapter
                    ▼
             Atlas Richie Components
                    ▼
     标准库 + 稳定协议 / 最小 Port
```

不可违反的规则：

- 核心包只依赖 Python 标准库；不得 import FastAPI、Django、Flask、Starlette、Pydantic、SQLAlchemy、HTTPX、Redis、OpenTelemetry、JWT 或某云 SDK。
- 公共 API 不得返回或接收上述框架/SDK 类型；只使用本组件 DTO、`typing.Protocol`、标准流/字节接口和 JSON 值。
- 业务应用显式传入依赖，例如 HTTP requester、token validator、审计 sink、时间源、存储器；禁止 Service Locator、导入即注册、模块扫描和隐式后台线程。
- 无可选 adapter 时，组件不进行网络访问、自动鉴权、自动发现或配置优先级修改；缺少必需能力必须失败明确，不能静默跳过安全或 Schema 校验。
- adapters 只依赖 core，永不反向依赖；多个 adapter 之间也不互相要求安装。

### 2.2 不照搬 Java `base`

Java `base` 同时有契约、BOM、Spring 上下文、Servlet/ORM 语境和测试支持。Python 把其真正可共享的部分拆开：

```text
foundation/contracts  -> 生命周期、健康、错误分类、能力描述等跨组件最小契约
foundation/testing    -> 夹具、black-box contract suite、隔离安装工具
foundation/platform   -> 兼容矩阵与发布组合，不含运行时实现
components/*          -> 可独立安装、版本化和裁剪的能力
adapters/*            -> **跨组件基础设施**(如 `adapters/cache-redis` 服务多个 component);不在此处放组件内部子能力(MCP 内部 transport/security/schema 在 R-232 已迁回 `components/mcp/` 子包)
```

不创建泛化 `base` 运行时包，也不让 Gateway、Antivirus 或任一业务服务进入 Component 依赖树。

### 2.3 依赖预算

| 分层 | 允许依赖 | 禁止依赖 |
|---|---|---|
| `contracts` | 标准库 | 所有第三方库、组件实现、框架 |
| `mcp` core | 标准库、`contracts` | JSON Schema 引擎、网络客户端、JWT/HTTP/ASGI 框架 |
| `mcp` testkit | core + 仅测试依赖 | 生产应用依赖 testkit |
| adapter | 自己负责的 SDK + core | 业务项目、其他可选 adapter |
| profile/example | 已选 adapter + component | 将自身配置或领域模型回灌 core |

“零依赖 core”不代表降低协议承诺：需要完整 JSON Schema、OAuth/JWKS、HTTP client 或 OTel 时，必须显式选择对应 adapter；若未安装，component 返回稳定的 `CapabilityUnavailable`/configuration error，而不是不校验地继续执行。

### 2.4 Python 支持窗口

- 发行包统一声明 `Requires-Python: >=3.12`，首个实现基线为 CPython 3.12。
- CI 的稳定兼容矩阵为 3.12、3.13、3.14；下一主版本仅做允许失败的预发布检查，升级为稳定版后再纳入正式门槛。
- 正常的 Python 小版本升级通过同一维护分支、兼容矩阵和包版本约束完成；Git 分支只用于不兼容的大版本产品线或延长维护，不为每个解释器小版本分叉代码。

## 3. Component 初始路线

当前仓库只建设 Component。Gateway 与 Antivirus 在拥有真实 Python 业务边界后，才作为独立应用消费组件。

| 优先级 | Component | 迁移目标 | 是否进入首期 |
|---:|---|---|---:|
| P0 | `contracts`、`testing`、发布治理 | 独立安装、能力/错误/生命周期契约 | 是 |
| P1 | `mcp` | 双端 Protocol-first MCP，先 stdio | 是 |
| P2 | `mcp-http`、`mcp-oauth`、`mcp-asgi` | 远程互调和双向 M2M 认证 | 是 |
| P3 | `http`、`concurrency`、`secret`、`logging`、`tracing` | 将 MCP 的可替换 runtime 能力外置 | 后续 |
| P4 | cache、storage、vector、文档与 AI | 数据及 AI 能力 | 后续 |

## 4. MCP 的 Python 包与模块边界

第一版避免把 Java 的十个 Maven module 等量复制成十个 PyPI 包。一个组件先保持内聚；只有存在可选依赖或独立发布节奏时才拆发行包。

```text
components/mcp/                         # atlas-richie-mcp
  src/atlas_richie/mcp/
    api/                                # 唯一业务可见入口、DTO、错误、Protocol
    protocol/                           # JSON-RPC、schema snapshot、Dialect、Negotiator
    server/                             # immutable registry、dispatcher、resource/prompt
    client/                             # protocol-neutral operations、paging/cache policy
    transport/stdio/                    # 标准库 newline JSON + 进程生命周期
    transport/http_core/                # framework-neutral request/response mapper
    security/                           # auth context、policy、OAuth port/PRM model
    _internal/                          # 不承诺稳定的实现细节

**R-232 重整后(2026-09-12)**:

```text
components/mcp/src/atlas_richie/mcp/
├── transport/{stdio,http,asgi}/         # 子包,单 wheel atlas-richie-mcp
├── security/oauth/                      # 子包,OAuth Bearer → ToolContext
├── schema/{port,jsonschema}/            # 子包,Schema 端口 + JSON Schema 实现
├── legacy/                              # 子包,2025-11-25 dialect
└── testkit/                             # 子包,协议夹具(Java mcp-testkit 对位)
```

原 `adapters/mcp-*` 6 个独立 wheel 全部合并进 `atlas-richie-mcp` 单 wheel,
无 Java mcp-parent 的多 jar 拆分(因为没有 pluggable backend 多实现需求)。
无 `adapters/mcp-wsgi` / `adapters/mcp-httpx` / `adapters/mcp-oauth-oidc` /
`adapters/mcp-otel`(未实现)。

初始发布 `atlas-richie-mcp` 只携带 core 和 stdio。HTTP、完整 JSON Schema、OAuth、ASGI、OTel 以 named extra 或独立 adapter 选择性安装，例如：

```text
atlas-richie-mcp                 # 核心 + stdio，不启动网络服务
atlas-richie-mcp[schema]         # 明确选择 JSON Schema adapter
atlas-richie-mcp[asgi,oauth]     # 远程 server 的推荐组合
atlas-richie-mcp[http-client]    # 远程 MCP Client 组合
```

extras 只能表达可验证的组合，不能暗中选择 FastAPI、Django 或任一业务框架。

## 5. 稳定 API 与所有权

### 5.1 业务应用能看到的 API

```python
from atlas_richie.mcp import McpClient, McpServer, ToolContext

server = McpServer(identity=server_identity, policies=[scope_policy])

@server.tool(name="inventory.query", required_scopes={"inventory:read"})
async def query_inventory(request: InventoryQuery, context: ToolContext) -> InventoryResult:
    return await inventory.query(context.tenant_id, request)

client = McpClient(transport=peer_transport, token_provider=peer_token_provider)
result = await client.call_tool(peer="inventory", name="inventory.query", arguments={...})
```

装饰器只登记不变的元数据；不启动 server、不执行 I/O、不扫描应用、不替换函数。复杂场景可显式注册 `ToolDefinition(handler=...)`。

| 层 | 拥有的数据与规则 | 不拥有的内容 |
|---|---|---|
| `mcp.api` | Tool/Resource/Prompt 描述、调用上下文、稳定错误、Capabilities | JSON-RPC 原始 map、HTTP request、框架 Principal |
| `mcp.protocol` | Dialect、wire 映射、版本协商、离线 schema snapshot | 业务工具、认证方式、网络 I/O |
| `mcp.server` | 不可变 registry、Schema gate、可见性、调用编排 | 业务事务、DAO、Web 框架 |
| `mcp.client` | 操作、分页/缓存策略、协商、目标 capability 校验 | 业务 token、框架 HTTP 客户端类型 |
| `mcp.security` | canonical resource、认证后的 `AuthContext`、授权 port | IdP SDK、明文 Token、用户目录 |
| adapter | 框架/SDK 与稳定 port 的转换 | 改写 component 语义或访问业务对象内部 |

`ToolContext` 最小字段为 `principal_id`、`principal_kind`（user/service）、`tenant_id`、`granted_scopes`、`deadline`、`cancellation`、`progress`、`trace_context`。它不包含 raw bearer token、HTTP request、JSON-RPC ID 或协议版本。

### 5.2 Server 调用顺序

```text
wire/transport validation
  -> protocol Dialect normalization
  -> authentication -> AuthContext
  -> tool visibility + scope authorization
  -> input Schema validation
  -> argument binding
  -> timeout/cancellation + tracing/audit interceptors
  -> business handler
  -> structured output adaptation + output Schema validation
  -> safe error mapping -> dialect encode -> transport response
```

Tool list 的可见性过滤不等于授权：`tools/call` 必须重新执行权限检查。工具名、输入、未知 Tool、业务错误、内部错误和认证错误必须是不同的错误类别；Token、SQL、内部 URL、堆栈和敏感字段绝不能进入 wire response。

### 5.3 Schema 规则

- Wire Schema 固定 JSON Schema Draft 2020-12，快照随仓库提交并附官方来源 commit/hash；构建不得联网拉取。
- core 只声明 `SchemaCompiler`/`CompiledSchema` Port 与确定性 violation 模型；`jsonschema` 或另一实现位于可选 adapter。
- 没有 Schema adapter 时，声明 input/output schema 的外部 Tool 不得启动或注册；不允许跳过验证。
- `$ref`、`$dynamicRef` 只允许同文档 `#` 引用；拒绝远程 fetch；限制 bytes、深度、节点、组合分支和验证预算。
- 类型注解只能提供便利性，不能替代显式或生成后冻结的 JSON Schema；Pydantic/数据类生成必须由独立 adapter 负责。

## 6. 协议、传输与兼容性

### 6.1 方言隔离

Python 初始实现 modern MCP `2026-07-28`；`McpDialect` 从第一天就是稳定内部扩展点，以防业务 API 出现协议分支。

| 语义 | modern `2026-07-28` | legacy `2025-11-25` |
|---|---|---|
| 发现 | `server/discover` | `initialize` |
| 上下文 | 每请求 `_meta` | 会话初始化后状态 |
| 结果 | 必含 `resultType=complete/input_required` | 缺省等价 `complete` |
| 交互输入 | MRTR `input_required` | server-initiated request |
| 通知订阅 | `subscriptions/listen` | 旧 SSE/会话语义 |

modern 请求必须携带 `io.modelcontextprotocol/protocolVersion` 与 `clientCapabilities`；HTTP `MCP-Protocol-Version` 与 body `_meta` 不一致时拒绝为 `HeaderMismatch (-32020)`。不支持版本返回 `UnsupportedProtocolVersion (-32022)` 与受支持版本列表。

P1 不承诺 legacy runtime；P5 才在 `mcp-legacy-20251125` adapter 中加入它。届时由同一份归一化模型和兼容矩阵验证，不能让 tool handler 判断版本。

### 6.2 Transport

| Transport | 规划 | 依赖 |
|---|---|---|
| stdio | P1，newline-delimited JSON，EOF 关闭，stdout 只写协议、stderr 只写日志 | 标准库 |
| Streamable HTTP core | P2，验证 POST/媒体类型/header-body mirror、Origin、取消、JSON/SSE 映射 | 标准库 DTO/Port |
| ASGI | P2，公开协议桥，任何 ASGI 框架可 mount | 无框架依赖 |
| WSGI | 后续可选同步桥 | 无框架依赖 |
| HTTPX/aiohttp/requests | adapter，由使用者选择 | 对应可选 SDK |
| HTTP+SSE / Content-Length stdio | 仅 legacy/custom adapter，默认关闭 | 可选 |

HTTP core 不保存 Session ID，不依赖粘性会话；一个 request 只产生自己的 JSON response 或 SSE stream。SSE 断开意味着 in-flight request 丢失，重试必须新建 request ID，且仅对已声明幂等、没有服务端处理证据的操作允许自动重试。

### 6.3 长流程、取消和缓存

- 取消是可传播的 `CancellationToken`，不是单纯 timeout；取消后 server 不响应，client 忽略迟到结果。
- timeout 有 request deadline 与 hard maximum；progress 可延长软 deadline，不能突破 hard maximum。
- MRTR request state 是 HMAC 完整性保护值，绑定 canonical resource、issuer/principal fingerprint、tenant、scope、过期时间和 registry revision；HMAC 不提供保密性，因此不得放入 secret 或敏感 continuation data，也不能依赖进程内 session。
- `discover`/list/read 的 cache key 必含 server identity、method、params、dialect；private cache 另含不可逆 authorization fingerprint 与 tenant。`tools/call` 和 `input_required` 不缓存。

## 7. 两个应用的双向访问与认证

### 7.1 角色模型

每个应用既是 MCP Server（暴露自己的能力），也是 MCP Client（调用对方能力）；它们不共享业务代码、内存 Session 或静态 Access Token。

```text
Application A                                      Application B
─────────────                                      ─────────────
MCP Server: resource = https://a.example/mcp      MCP Server: resource = https://b.example/mcp
MCP Client: target   = https://b.example/mcp      MCP Client: target   = https://a.example/mcp
        │                                                     │
        └───── trusted OAuth issuer / federation ────────────┘
```

推荐初期采用**共同受信任 OAuth Authorization Server**。将来如果两个应用各自使用 IdP，必须通过显式 issuer allowlist、JWKS/metadata 校验和同样的 audience/resource 规则建立 federation；不能仅凭 issuer 名称相同就互信。

### 7.2 双向 M2M 流程（默认）

服务到服务互调使用 MCP OAuth Client Credentials Extension：

```text
1. A -> B 的 /mcp：没有或携带失效 Token
2. B 返回 401 + WWW-Authenticate Bearer resource_metadata=... + 最小 scopes
3. A 读取 B 的 Protected Resource Metadata，验证 canonical resource 与允许的 issuer
4. A 向授权服务器申请：client_id=A, resource=https://b.example/mcp, scopes=B 所需集合
5. 授权服务器签发 aud=B_resource、iss=trusted_issuer、client_id/sub=A 的短期 Token
6. A 重试 B；B 验证签名、iss、aud/resource、exp/nbf、client identity、scopes、tenant policy
7. B -> A 使用完全镜像的流程，Token 的 aud 必须变为 A_resource
```

安全不变量：

- A 面向 B 的 Token 绝不能被 A 自己或其他资源接受；B 面向 A 同理。
- Client credential Token 代表 service identity，不能伪造成用户 subject。
- 两端的 `client_id`、issuer、canonical resource、scope、tenant/security realm 都是 token cache key 的一部分；缓存键只保留不可逆 fingerprint，绝不保存 Token。
- 认证失败是 401，scope/策略不足是 403；`tools/list` 可按身份过滤但不会替代 `tools/call` 的再次授权。
- Secret 通过以后独立的 Secret provider 注入；配置只保存 logical reference，不能保存 client secret 或 refresh token。
- TLS 是最低传输要求；mTLS 可作为部署层的第二身份信号，但不能替代 OAuth audience/scope 检查。

### 7.3 用户委托与禁止的 Token 透传

当 A 代表用户调用 B 时，选择 OAuth Authorization Code + PKCE 或经过安全审查的 token-exchange adapter；必须为 B 的 canonical resource 获得目标 Token。禁止把收到的 A audience Token 原样转发给 B。

授权码流必须用 PKCE S256、state、redirect URI exact match、issuer exact match 和 RFC 9207 `iss` 检查。refresh token 只保存在受控 confidential store，并支持 rotation/replay detection；不支持 refresh 时回到完整授权流程。

### 7.4 认证和框架的分界

`mcp.security` 定义：

- `TokenValidator`：输入 bearer token 与 expected resource，输出已验证 `AuthContext` 或稳定认证错误；
- `TokenProvider`：输入 resource、scope、principal profile，返回目标资源 Token 或显式未授权；
- `ProtectedResourceMetadataProvider`：发布 PRM；
- `AuthorizationPolicy` / `ScopeResolver`：在 tool 可见性和调用期进行最小授权；
- `UriPolicy`：拒绝非 HTTPS、user-info、fragment、内网/metadata IP、未允许 redirect 与 DNS rebinding 风险。

OIDC discovery、JWKS、JWT 验签、introspection、HTTP 请求、KMS/Secret、框架 principal 解析均由独立 adapter 实现。core 不解析任意 JWT，也不信任业务传入的 `tenantId` 或 `Authorization` header。

## 8. 可观测与运行安全

- request/response 的 trace context 在 HTTP header 与 MCP `_meta` 一致时才关联；冲突、超限 baggage 或未信任来源必须拒绝/清洗。
- 指标仅使用低基数维度：dialect、transport、method、tool、outcome、cache、cancellation；禁止 tenant、user、Token、完整 URI 与参数内容。
- 审计记录 principal/tenant/tool/policy decision/result class；destructive tool 另行审计。stdio stdout 零日志。
- `server/discover`、list、协议协商与 token/metadata endpoint 都要配置独立 timeout、retry boundary 和 circuit breaker；`tools/call` 默认不自动重试。

## 9. 设计模式候选（实施前需确认）

| 具体位置 | 候选模式 | 边界、收益与误用防护 | 验证 |
|---|---|---|---|
| 业务入口 `McpServer` / `McpClient` | **Facade** | 收敛 registry、dialect、transport 与关闭顺序；不暴露全部内部对象，也不变成全局容器。 | 只通过公开 API 完成发现、调用、取消和关闭的 black-box tests。 |
| Protocol 版本、认证 profile、重试选择 | **Strategy** | `Dialect`、`AuthProfile`、`RetryPolicy` 是真实独立变化轴；调用方只依赖稳定行为。 | 同一 fixture 测每个 dialect/profile 的成功、异常、unknown value 和兼容行为。 |
| ASGI/WSGI、HTTP client、OIDC、Schema、OTel | **Adapter** | SDK/框架类型只在 adapter 内转换为 Port/DTO，新增底层不改 core。 | 静态禁止 SDK 类型泄漏；每个 adapter 执行同一 transport/security contract suite。 |
| Tool 声明、授权、超时、审计、追踪 | **Decorator** + 有序 **Chain of Responsibility** | 装饰器只登记元数据；拦截链在至少两个独立横切能力落地后启用，顺序固定。 | 覆盖短路、错误、取消、顺序、脱敏和“执行中 registry 刷新”场景。 |
| transport / adapter 实例选择 | **Factory Method** | 由显式配置/构造参数创建已选实现，避免业务 `if framework == ...`。 | 覆盖缺失、冲突、未选中 adapter，禁止自动扫描/隐式选择。 |

不采用 Singleton/Service Locator（隐藏依赖）、Abstract Factory（当前没有必须成组切换的对象族）、Template Method（组合策略更适合 Python）、Observer 全局事件总线（尚无独立事实订阅者）。模式不会在未确认前进入实现。

## 10. 验证矩阵与阶段门槛

| 阶段 | 可交付结果 | 必须通过的证据 |
|---|---|---|
| P0 | Component 宪章、包边界、schema snapshots、testkit skeleton | 依赖方向与隔离 wheel install；无框架 import 检查。 |
| P1 | modern protocol + server/client core + stdio | JSON-RPC/dialect golden、newline/EOF、Tool registry atomic refresh、Schema fail-closed、取消/错误分类。 |
| P2 | HTTP core + ASGI bridge + OAuth ports | header/body mismatch、Origin、PRM canonicalization、URI SSRF policy、401/403、audience/scope rejection。 |
| P3 | M2M 双向认证 profile | 两个独立 Python process：A -> B、B -> A；每个方向分别验证无 Token、错误 issuer、错误 audience、过期 Token、scope 不足、tenant 串用与成功调用。 |
| P4 | 跨语言 modern interoperability | 任意遵循同一 MCP 版本的 client/server；官方 conformance 与 wire golden。 |
| P5 | legacy 2025 adapter、MRTR transport binding、subscriptions、delegated OAuth | modern/legacy 矩阵、MRTR state binding、断流、step-up、PKCE/refresh/replay 与 deprecated telemetry。 |

独立构建或 `pip check` 只能证明打包；A/B 双进程、真实 TLS/OAuth、跨语言互操作与官方 conformance 才是协议/认证验证。所有第三方 IdP、云 Secret、性能结果必须单独标记为环境证据。

## 11. 下一次实现范围

在确认第 9 节的模式候选后，只执行 P0/P1：初始化 foundation 与 `components/mcp`、固定 `2026-07-28` Schema 证据、定义最小 DTO/Port、实现 stdio 及其 black-box fixtures。不会创建 FastAPI/Django adapter、不会实现 OAuth Authorization Server、不会创建 Gateway/Antivirus，也不会宣称双向认证已经完成。
