# Sentinel Dashboard 控制面初始化与身份 API 契约（V1 草案）

本契约服务于 Dashboard 与 Python 管理后台之间的控制面。Dashboard 不直接连接 Nacos/Consul，也不保存密码、密码哈希、访问令牌、数据库口令或初始化密钥。所有写操作由后台再次鉴权、校验并审计；前端路由隐藏只是交互优化，不是安全边界。

Dashboard 已不是单纯的配置中心编辑器。它是 Sentinel 的管理控制面：配置中心持有**当前生效规则**，关系数据库持有**控制面事实**，指标/事件由 Agent Reporting 与后续指标存储承担。

| 存储层 | 权威内容 | 不存什么 |
| --- | --- | --- |
| Nacos / Consul | 当前完整规则快照、规则来源版本 | 账号、密码、审计、草稿、会话 |
| Dashboard 关系数据库 | 初始化状态、账号/角色、审计、草稿、规则版本/计划、发布记录、来源登记 | 当前生效规则的第二份权威副本、密码明文/哈希输出、原始大规模指标 |
| 指标/事件存储（后续） | Agent 指标、故障事件、长期趋势 | 规则发布决策、账号与凭证 |

## 1. 统一约定

- 基础路径：`/api/v1`；媒体类型：`application/json`。
- 登录成功返回短时访问令牌和过期时间；生产实现优先使用 `HttpOnly`、`Secure`、`SameSite` Cookie，若采用 Bearer 则禁止写入 `localStorage`、URL、日志和分析事件。
- 当引导状态不是 `ready` 时，除 `/system/bootstrap/*`、`/health` 外全部控制面 API 返回 `503 system_not_initialized`；前端强制进入 `#/setup`。
- 除登录、初始化探测外，其余接口需要有效会话。规则写操作需要 `rules:write`；账户和角色管理接口只允许 `admin` 角色，不新增第三套业务权限。
- 角色是服务端固定枚举：`admin`、`view`。V1 一个账号只能绑定一个角色；角色的权限集合由服务端维护，客户端不得自行扩大权限。
- 所有时间使用 RFC 3339 UTC；所有列表支持 `page`、`pageSize`、`query`，服务端限制 `pageSize` 上限。
- 失败响应统一为：`{"error":{"code":"...","message":"...","requestId":"..."}}`。`message` 可展示文案不含堆栈、密码、令牌或敏感输入。

## 2. 首次启动：系统初始化

### `GET /system/bootstrap`

服务在没有已配置数据库时仍可启动最小的 setup surface。它只暴露健康检查和本组 API；登录、规则、指标与账户 API 均不可用。返回状态不泄露用户名、数据库 DSN 或凭证。

```json
{
  "phase":"storage_required",
  "initialized":false,
  "availableDatabaseKinds":["postgresql","sqlite"],
  "requiresAdminSetup":true,
  "requiresRuleSourceSetup":true
}
```

阶段仅能按序推进：`storage_required → storage_ready → admin_required → source_required → ready`。后端持久化该状态并拒绝非法跳转；V1 使用明确枚举与迁移表，不引入额外状态类层级。

### `POST /system/bootstrap/database/validate`

仅在 setup window 开启时允许调用。临时验证数据库连通性、权限、字符集与迁移锁，不写业务数据。

```json
{
  "kind":"postgresql",
  "host":"db.internal.example",
  "port":5432,
  "database":"sentinel_control",
  "username":"sentinel",
  "password":"<write-only>"
}
```

本地体验可选择 `{"kind":"sqlite"}`；SQLite 不支持生产集群部署。成功返回 `requestId` 与受限的 `connectionSummary`，绝不回显口令或 DSN。

### `POST /system/bootstrap/initialize`

仅在引导状态未完成且部署侧 initialization window 有效时允许调用。该命令执行：保存受保护的数据库连接配置、创建 schema/migration、创建内置管理员、登记首个 Nacos 或 Consul 来源、写入初始化审计，再关闭初始化窗口。

数据库连接配置不能保存为明文。部署必须提供 `ATLAS_RICHIE_SENTINEL_BOOTSTRAP_KEY`（或等价受管密钥引用）；管理服务用该密钥加密本机安装配置。若没有密钥或受保护的持久化位置，服务拒绝初始化。

Request:

```json
{
  "database":{"kind":"postgresql","validationRequestId":"req-db-123"},
  "admin":{"username":"admin","displayName":"系统管理员","password":"<write-only>"},
  "ruleSource":{"kind":"nacos","endpoint":"https://nacos.example.com","namespace":"prod","credentialRef":"secret://sentinel/nacos"}
}
```

Response: `201 Created`，返回 `BootstrapStatus` 与 `AccountSummary`（均不含 credential）。重复初始化返回 `409 initialization_completed`；迁移或来源登记失败返回可恢复的稳定错误码，不能留下“账号已创建但系统未就绪”的半完成状态。

配置中心在首次启动不是可选的“数据库替代品”：它登记的是规则来源，关系数据库保存的是控制面元数据。后续可补充第二个来源，但多个来源的优先级和切换仍由既有 RuleSourceSupervisor 规则控制。

## 3. 登录与会话

### `POST /auth/login`

Request：`{"username":"admin","password":"<write-only>"}`

Response：`200`，返回 `Session`；用户名不存在、账号停用和密码错误统一返回 `401 invalid_credentials`，避免账户枚举。

### `POST /auth/logout` / `GET /auth/me`

注销当前会话；`me` 返回当前 `AccountSummary` 与 `permissions`。会话过期统一返回 `401 session_expired`，前端跳转登录页并保留安全的原始页面路径。

## 4. 账户维护

### `GET /accounts`

Query：`page`、`pageSize`、`query`、`status`。Response：

```json
{"items":[{
  "id":"account-admin","username":"admin","displayName":"系统管理员",
  "roleId":"admin","status":"active","builtIn":true,
  "lastLoginAt":"2026-09-14T06:21:00Z"
}],"page":1,"pageSize":20,"total":1}
```

### `POST /accounts`

创建普通账号。Request：`username`、`displayName`、`roleId`（`admin|view`）；V1 不接收初始密码，后台发送一次性设置密码流程或要求账号首次设置。仅 `admin` 可调用。

### `PATCH /accounts/{accountId}`

仅允许修改 `displayName`、`status`。内置管理员不可删除；停用当前最后一个 admin 必须返回 `409 last_admin`。仅 `admin` 可调用。

### `DELETE /accounts/{accountId}`

只允许删除非内置账号，返回 `204`；删除前必须二次确认并写审计事件。仅 `admin` 可调用。

### `POST /accounts/{accountId}/password-reset`

管理员触发重置流程，返回 `202` 和 `requestId`，不返回临时密码。实际通知/一次性链接由后台安全模块负责。

### `POST /auth/password`

当前登录用户修改密码。Request：`currentPassword`、`newPassword`；服务端执行强度、历史复用、会话撤销策略。成功返回 `204`，密码错误统一 `401 invalid_credentials`，弱密码 `422 password_policy_violation`。

## 5. 角色绑定与权限

### `GET /roles`

返回固定角色和权限说明：

```json
{"items":[
 {"id":"admin","label":"管理员","permissions":["metrics:view","rules:write"]},
 {"id":"view","label":"查看者","permissions":["metrics:view"]}
]}
```

### `PUT /accounts/{accountId}/role`

Request：`{"roleId":"view","reason":"..."}`；服务端检查不能移除最后一个 admin，记录操作者、旧角色、新角色、理由和生效时间，返回更新后的 `AccountSummary`。仅 `admin` 可调用。

## 6. Dashboard 页面模型

前端页面只依赖下列稳定视图模型：

```ts
type AccountSummary = {
  id: string; username: string; displayName: string;
  roleId: "admin" | "view";
  status: "active" | "disabled";
  builtIn: boolean; lastLoginAt: string | null;
};
type RoleSummary = {
  id: "admin" | "view"; label: string;
  permissions: Array<"metrics:view" | "rules:write">;
};
type Session = { account: AccountSummary; permissions: RoleSummary["permissions"]; expiresAt: string };
type BootstrapPhase = "storage_required" | "storage_ready" | "admin_required" | "source_required" | "ready";
type BootstrapStatus = { phase: BootstrapPhase; initialized: boolean; requestId?: string };
```

页面职责：初始化页只处理首次系统配置和后端结果；登录页负责建立会话；账户维护负责账号状态与生命周期；角色绑定负责单角色选择和变更理由；修改密码只负责输入与服务端结果展示。任何页面都不直接处理密码哈希、令牌刷新、数据库口令持久化、配置中心凭证或权限最终判定。

## 7. 审计与验证要求

后台至少记录初始化尝试/完成/失败、迁移版本、登录成功/失败、账号创建/停用/删除、角色变更、密码修改/重置的 `requestId`、操作者、目标账号、结果和 UTC 时间；禁止记录密码、Authorization、Cookie、重置链接、数据库 DSN/口令和原始请求体。

契约测试覆盖：未配置数据库时只开放 setup surface、错误连接不持久化、迁移失败可恢复、重复初始化、错误凭证不枚举、停用账号不能登录、最后一个 admin 保护、view 调用写接口返回 `403`、密码强度与确认、重复提交幂等、会话过期和跨页面返回路径。真实登录、Cookie/CSRF、TLS、数据库迁移锁、初始化窗口、受保护安装配置和审计链需在后端集成环境验收，当前原型不宣称已接通。
