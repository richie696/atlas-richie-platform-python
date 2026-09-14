# Sentinel Dashboard 身份与账户 API 契约（V1 草案）

本契约服务于 Dashboard 与 Python 管理后台之间的身份控制面。Dashboard 不直接连接 Nacos/Consul，也不保存密码、密码哈希、访问令牌或初始化密钥。所有写操作由后台再次鉴权、校验并审计；前端路由隐藏只是交互优化，不是安全边界。

## 1. 统一约定

- 基础路径：`/api/v1`；媒体类型：`application/json`。
- 登录成功返回短时访问令牌和过期时间；生产实现优先使用 `HttpOnly`、`Secure`、`SameSite` Cookie，若采用 Bearer 则禁止写入 `localStorage`、URL、日志和分析事件。
- 除登录、初始化探测外，其余接口需要有效会话。规则写操作需要 `rules:write`；账户和角色管理接口只允许 `admin` 角色，不新增第三套业务权限。
- 角色是服务端固定枚举：`admin`、`view`。V1 一个账号只能绑定一个角色；角色的权限集合由服务端维护，客户端不得自行扩大权限。
- 所有时间使用 RFC 3339 UTC；所有列表支持 `page`、`pageSize`、`query`，服务端限制 `pageSize` 上限。
- 失败响应统一为：`{"error":{"code":"...","message":"...","requestId":"..."}}`。`message` 可展示文案不含堆栈、密码、令牌或敏感输入。

## 2. 初始化与登录

### `GET /system/initialization`

返回首次启动状态，不泄露是否存在具体用户名或密码。

```json
{"initialized":false,"requiresAdminSetup":true}
```

### `POST /system/initialization`

仅在 `initialized=false` 且部署侧初始化窗口有效时允许调用；成功后立即关闭初始化窗口。后台生成内置账号，密码只接受一次提交，不在响应中返回。

Request:

```json
{"username":"admin","displayName":"系统管理员","password":"<write-only>"}
```

Response: `201 Created`，返回 `AccountSummary`（不含 credential）。重复初始化返回 `409 initialization_completed`。

### `POST /auth/login`

Request：`{"username":"admin","password":"<write-only>"}`

Response：`200`，返回 `Session`；用户名不存在、账号停用和密码错误统一返回 `401 invalid_credentials`，避免账户枚举。

### `POST /auth/logout` / `GET /auth/me`

注销当前会话；`me` 返回当前 `AccountSummary` 与 `permissions`。会话过期统一返回 `401 session_expired`，前端跳转登录页并保留安全的原始页面路径。

## 3. 账户维护

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

创建普通账号。Request：`username`、`displayName`、`roleId`（`admin|view`）；V1 不接收初始密码，后台发送一次性设置密码流程或要求账号首次设置。需要 `accounts:write`。

### `PATCH /accounts/{accountId}`

仅允许修改 `displayName`、`status`。内置管理员不可删除；停用当前最后一个 admin 必须返回 `409 last_admin`。需要 `accounts:write`。

### `DELETE /accounts/{accountId}`

只允许删除非内置账号，返回 `204`；删除前必须二次确认并写审计事件。需要 `accounts:write`。

### `POST /accounts/{accountId}/password-reset`

管理员触发重置流程，返回 `202` 和 `requestId`，不返回临时密码。实际通知/一次性链接由后台安全模块负责。

### `POST /auth/password`

当前登录用户修改密码。Request：`currentPassword`、`newPassword`；服务端执行强度、历史复用、会话撤销策略。成功返回 `204`，密码错误统一 `401 invalid_credentials`，弱密码 `422 password_policy_violation`。

## 4. 角色绑定与权限

### `GET /roles`

返回固定角色和权限说明：

```json
{"items":[
 {"id":"admin","label":"管理员","permissions":["metrics:view","rules:write"]},
 {"id":"view","label":"查看者","permissions":["metrics:view"]}
]}
```

### `PUT /accounts/{accountId}/role`

Request：`{"roleId":"view","reason":"..."}`；服务端检查不能移除最后一个 admin，记录操作者、旧角色、新角色、理由和生效时间，返回更新后的 `AccountSummary`。需要 `accounts:write`。

## 5. Dashboard 页面模型

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
```

页面职责：登录页负责建立会话；账户维护负责账号状态与生命周期；角色绑定负责单角色选择和变更理由；修改密码只负责输入与服务端结果展示。任何页面都不直接处理密码哈希、令牌刷新、配置中心凭证或权限最终判定。

## 6. 审计与验证要求

后台至少记录登录成功/失败、初始化完成、账号创建/停用/删除、角色变更、密码修改/重置的 `requestId`、操作者、目标账号、结果和 UTC 时间；禁止记录密码、Authorization、Cookie、重置链接和原始请求体。

契约测试覆盖：未初始化/重复初始化、错误凭证不枚举、停用账号不能登录、最后一个 admin 保护、view 调用写接口返回 `403`、密码强度与确认、重复提交幂等、会话过期和跨页面返回路径。真实登录、Cookie/CSRF、TLS、初始化窗口和审计链需在后端集成环境验收，当前原型不宣称已接通。
