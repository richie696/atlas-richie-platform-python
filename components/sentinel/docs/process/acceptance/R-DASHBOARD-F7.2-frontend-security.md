# F7.2 前端安全回归审计记录

日期：2026-10-12  
状态：focused logic / HTTP contracts 通过；mounted browser 与 live Python 边界未验收。  
范围：仅审计路由访问策略、身份 owner 状态投影、回跳 allow-list、Mock HTTP 权限和凭证边界；不替代 F7.2 完整验收。

## 核验结果

| 安全边界 | 证据与结果 |
| --- | --- |
| Viewer 只读 | `decideControlPlaneAccess("admin", ...)` 按确认身份的角色拒绝 viewer，即使 identity 携带伪造的规则写 capability 也不能获得管理访问；metrics 能力与 admin 身份分开判定。`navigationItemsForAccess(false)` 不展示管理导航。Mock HTTP 对账户列表、详情、角色变更、操作查询四类管理 endpoint 均返回 403。通过。 |
| 非法深链拒绝 | URL route parser 拒绝原型对象属性名等非法 route；route metadata 将管理路由标记为 `admin`；未确认身份不能获得 allow。setup 完成后不会因手写 setup URL 重新开放初始化。通过。 |
| Owner / 未知态不沿用管理身份 | workflow 的 `checking` snapshot 不暴露此前确认的 identity；已失效/刷新中的 access facts 不作为 allow；旧 owner 的迟到 bootstrap / HTTP 401 响应不会覆盖新 owner 的身份或 CSRF 状态。`App.tsx` 在非 allow 决策时返回身份反馈态；只有确认身份且 access decision 为 allow 才创建 `AppShell` 返回路径。源审查通过；没有本轮 mounted 浏览器证据。 |
| 登录回跳 allow-list | `returnTo` 只接受已知本地 route；外部 URL、未授权页面和非登录页携带的 `returnTo` 被丢弃；登录后再按服务端确认的角色授权，viewer 被导向安全的 Overview。通过。 |
| URL、storage、wire 凭证边界 | route serializer 不接受 password/token 等 secret 参数；legacy localStorage 值不会被提升为认证 header；Mock storage 仅保存合成身份/角色状态，测试断言不保存合成密码；身份响应 schema 不接受 password/cookie 等凭证，workflow snapshot 不包含登录密码，错误投影不会带出原始 password/provider body/cause。协议所需登录密码只允许进入登录写请求 body，不进入 URL、身份读取响应或持久化 storage。通过。 |

## 定向验证

在 `components/sentinel/dashboard-prototype` 执行：

```text
npm run test:logic:focused -- 'F2|F4.20 checking snapshots|F4.23 authentication return route|F2.6 route metadata'
60 passed, 0 failed

npm run test:http:focused -- 'IDENTITY-HTTP|IDENTITY-MOCK|HTTP-OWNER|HTTP-MSW|HTTP-ERROR|ACCOUNT-MOCK-AUTHZ'
15 passed, 0 failed
```

## 未覆盖边界

- 本轮未运行完整 E2E，未启动 Chrome、Edge、CDP 或测试浏览器，也未连接 Python 服务、数据库、配置中心或生产身份提供方。
- 本轮没有 mounted React 浏览器证据。`App.tsx` 的源代码审查和 workflow/route/HTTP contract 测试不能替代 mounted 页面渲染；F7.2 的浏览器级逐路由、刷新/返回及真实后端权限验收仍开放。
- 这份记录只收录本次实际执行的 focused 门禁和当前源码检查，不修改中央推进清单，也不单独关闭 F7.2。

## 2026-10-12 补充：认证凭证禁止写入浏览器 Storage

- 新增 `tests/logic/security-contracts.test.mjs`：用独立的 `localStorage` / `sessionStorage` spy 执行认证 workflow 的 restore + login，分别断言两种 storage 均无写入；另断言 workflow snapshot 不含 synthetic password，路由序列化只保留 allow-listed `returnTo`，不会将 username/password/token 写进 URL。
- 定向结果：`npm run test:logic:focused -- 'F7[.]2'` **1/1 passed**；权限 / 深链 / 回跳用例 `npm run test:logic:focused -- 'F2 access gates|F2 completed setup|F2 admin and metrics|F2 authorization never|F4[.]23 authentication return|F2 observation context|F2 route metadata'` **6/6 passed**；`npm run test:http:focused -- 'APP-MOCK-AUTHORIZATION-MATRIX|ACCOUNT-MOCK-AUTHZ|HTTP-LIVE-CONTROLLED|HTTP-MSW'` **4/4 passed**。
- 快速门禁：`/usr/bin/time -p npm run check:fast` **exit 0**，typecheck、format、lint、OpenAPI contract check 全部通过，耗时 **9.61 秒**。补充测试格式和工作区 whitespace 检查：`npx prettier --check tests/logic/security-contracts.test.mjs tests/logic/suite.mjs`、`git diff --check` 均通过。
- 证据边界：这是认证 owner 与路由/HTTP contract 的自动化证据，不证明任意浏览器扩展、浏览器密码管理器或其他代码路径绝不访问 Storage；没有运行 E2E、没有 mounted React/IAB 观察，也没有连接真实 Python 后端或验证真实服务端授权。账户写操作有 viewer 403 用例；规则/配置源写操作的 viewer 拒绝仍需核对专属 HTTP contract。F7.2 继续保持开放。
