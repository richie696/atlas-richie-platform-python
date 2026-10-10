# R-DASHBOARD-F4.23 会话菜单与安全回跳验收（部分）

## 本轮实现

- 头部会话入口使用服务端确认的账号名和角色，不再显示静态 `LD`；菜单按当前角色提供账户维护或修改密码入口，并提供显式退出操作。
- 退出请求处于 pending、结果未知、失败或未确认时，不伪报登出成功、不自动重放；通过“检查当前会话”重新读取服务端会话状态。
- 未登录访问受保护路由时，登录 URL 只保留站内 allow-list 路由标识 `returnTo`；登录成功后依据新确认的身份重新授权目标。非法目标、登录/初始化目标或新角色无权访问的管理目标都回落到总览。
- 改密要求重新认证时，登录成功后回到修改密码页；整个回跳只传路由 ID，不携带表单、凭据或任意外部 URL。

## 自动化证据

- `npm run typecheck`：通过。
- 目标 ESLint：通过。
- `npm run test:logic`：243/243 通过，其中 F4.23 覆盖 returnTo URL round-trip、拒绝外部 URL、按确认角色重新授权、viewer 管理页回落以及 login/setup returnTo 排除。
- `npm run test:architecture`：13/13 通过。
- `npm run i18n:check`：通过，三语消息键及插值一致；静态键提取报告 115 个动态 `t()` 调用需映射/运行测试补充，非全量静态证明。

## Codex 内置浏览器实测（本地 demo，仅 IAB）

- 从已登录账户页点击退出后，UI 显示“退出结果尚未确认”，并要求检查当前会话；没有自动重发退出命令。
- 点击检查后，确认当前会话已匿名并跳到 `#/login?returnTo=accounts&app=all&range=1h`，保留站内目标与无敏感性的应用/时间筛选。
- 用本地 demo `viewer` 身份登录后，因无账户管理权限安全回落至总览；会话菜单显示 `mock-viewer` / 查看者及“修改密码”入口。
- 查看者直接访问 `#/accounts` 时显示明确的权限拒绝页，没有渲染账户表格。
- 浏览器验证使用 Codex 内置浏览器；没有启动 Chrome、Edge 或 CDP。凭据仅为本地 demo 合成测试值，不是生产身份。

### 2026-10-08 补充：管理员会话退出与匿名深链

- 在本地 initialized Mock 情景中，以 `admin` / 合成密码登录，UI 确认身份后进入总览；会话菜单显示 `admin 管理员`，并提供“账户维护”和“退出登录”。
- 点击“退出登录”后，页面明确显示“退出结果尚未确认”，要求检查当前会话；没有自动重复发送退出命令。点击“检查当前会话”后确认匿名并进入 `#/login?returnTo=overview&app=all&range=1h`。
- **初次观察（已被修复后的复测取代）：**新鲜 IAB 会话曾出现 MSW `POST /api/v1/auth/logout` → `204 No Content`，但 UI 显示 `result-unknown`，且未自动发出 `/auth/me`。根因是 Fetch 拦截器把合法的空 `ReadableStream` 作为 204 body 返回，而 bounded response 仅接受 `body === null`，将其误判成非法响应并阻断确认 workflow。
- **修复与 IAB 复测：**204 响应现在会读取并确认 body 流为 0 字节；非空 body 仍被拒绝。以新的同源本地 Mock IAB 会话登录 `admin` 后退出，观察到 `POST /api/v1/auth/logout` → 204，随后自动 `GET /api/v1/bootstrap` → 200、`GET /api/v1/auth/me` → 200，并跳转至登录页；不再显示 `result-unknown`。新增 HTTP 回归分别覆盖空流接受与非空流拒绝。实现及验证记录见 dashboard 推进清单 §15.79。
- 退出后直接打开受保护的 `#/accounts`，前端守卫重定向到 `#/login?returnTo=accounts&app=all&range=1h`，只保留站内路由 ID 与非敏感筛选参数；账户管理内容未渲染。
- 登录页只显示登录名、密码、密码可见性和登录按钮，没有首次初始化入口。本段全部是本地 same-origin Mock 行为，不证明 Python `/auth/me` 或真实 logout 撤销。
- 同轮修复登录页本地必填错误提示：空表单提交后输入登录名会立即清除过期的本地必填提示；服务端认证错误仍由身份工作流单独展示。
- 只使用 Codex 内置浏览器；未启动 Chrome、Edge 或 CDP。所有凭据均为本地合成 fixture。

### 2026-10-09 补充：storage 写入未生效时的 Mock 登出回退

- **复现：**在旧 `127.0.0.1` 情景中，Mock role storage 仍读到 `admin`，注销写入即使没有抛异常但未实际保存，读取仍会返回 stale `admin`。
- **修复：**`writeMockPrincipal` 现在写入后读回校验；若 storage 拒绝写入或静默不保存，当前 Storage 对象范围内以内存 principal 覆盖读值，显式注销在当前页面立即保持匿名。切换 Storage 对象会清除该局部覆盖，不把一个浏览器上下文的状态泄漏到另一个上下文。
- **定向证据：**`node scripts/test/run-focused.mjs logic 'mock identity'` **3/3 passed**，新增旧 admin + `setItem` 静默失败回归；`npm run typecheck`、`npm run lint`、`npm run format:check`、`git diff --check` 通过。此切片未启动浏览器/E2E。
- **边界：**内存匿名覆盖不跨浏览器重载；持续不可写 storage 时不能保证 reload 后匿名。此修复仅解决 Mock 同页读回旧角色，不改变服务端会话事实，也不关闭下面仍开放的 F4.23 真实 Python 验收。

## 未完成与边界

- F4.23 整项仍未勾选。需要待 Python Console 接口装配后，对真实 `/auth/me`、logout、过期/撤销、服务端回读与 CSRF/Cookie 行为做端到端验证；本轮 demo mock 不能代替真实服务端证明。
- Mock logout 的 204 空流解析问题已由本地 HTTP 回归和 IAB 自动回读复测覆盖；真实 Python Console 的响应行为仍需后端装配后独立验收。
- **2026-10-08 后续 IAB 复核出现相反结果：**在管理员 Mock 页面两次显式点击“退出登录”，均停留在“退出登录未完成 / 退出请求未能确认完成”；点击“检查当前会话”后仍显示同一错误页。之后对当前标签做整页重载，应用恢复为已认证 admin 并重定向至 overview；没有自动重发 logout。这个刷新结果证明本地 Mock 会话仍被读作 admin，但不能区分 POST 未发出、handler 未命中或会话事实被其他来源恢复。与上面的成功 IAB 记录矛盾，因此 Mock 注销不能算稳定验收通过。
- 同轮 `npm run test:http`：**95/95 passed**，含 `IDENTITY-HTTP` 登录/会话回读/注销/会话回读，以及 `HTTP-204` 空响应流校验；沙箱普通运行时 loopback listener 被 `EPERM` 拒绝，在仅允许绑定本机 `127.0.0.1` 的测试提升后通过。该证据证明隔离 HTTP 测试链路，不证明 IAB 的 MSW Service Worker/页面装配行为。当前缺少浏览器网络请求观测，根因未定位；不得用 HTTP 单测绿色覆盖 IAB 失败。
- **新鲜会话对照：**另在隔离的 `http://localhost:4173` Mock origin，从匿名 UI 登录 viewer、退出后回到 `#/login?returnTo=rules...`；随后同一干净 origin 登录 admin、立即退出，也回到带相同站内 returnTo 的登录页。新鲜 viewer/admin 流程均成功，与旧 `127.0.0.1` 管理员长生命周期 Mock session 中的失败形成对照。§15.291 的定向修复覆盖了 storage 不生效时同页仍读回 stale admin；浏览器旧会话的再次渲染、reload 与网络行为尚未复测，因此不宣称整体根因或跨重载行为已验收。

### 2026-10-09 补充：本人账号角色/停用变更后的会话重读（定向工作流测试）

- 身份契约区分只读 `IdentitySessionObserver` 与账户维护专用 `IdentitySessionOwner`；后者附带 app 唯一认证工作流的 `revalidateAccess()`。账户管理仅在服务端确认当前本人账号的 role/status 变更后调用；直接 completed 和 unknown→原操作读取 completed 两种路径都覆盖。
- 测试矩阵覆盖本人降为 `view`、本人停用后变匿名、权限重读失败；每个场景都要求 admin account snapshot 立即清空，且不再刷新受保护目录。工作流关注已确认写入不能因随后 session read failure 被改报成未知/失败。定向逻辑 **6/6 passed**，前端 `check:fast` 通过。
- Python 的 SQL `/auth/me` reader 每次按当前 account role/status、session revocation/expiry 读取；新增同一 session digest 在 account role 提交变更后下一次读取返回新 role、保留 session epoch 的回归。`PYTHONPATH=src .venv/bin/pytest -q tests/test_current_session_persistence.py` **4 passed**（isolated SQLite），核对后端边界，但不是 PG/MySQL 或浏览器→Python acceptance。
- 该证据不代表浏览器实际跳转、真实 Python `/auth/me`/cookie/CSRF 或数据库验收；继续保留在 F4.23 的开放项中，不以测试替身代替服务端事实。
- 未对真实 Python 后端、数据库、生产身份提供者或生产凭据发起请求。
- 全自动 E2E 套件未运行；既有套件通过 CDP 驱动外部浏览器，本轮遵循“只用内置浏览器”要求，改用 IAB 手工交互验证，并以逻辑/架构测试补充。

### 2026-10-09 补充：F4.23 当前定向证据与最终 IAB 清单

- 站内路由回跳及登录后角色重新授权：`node scripts/test/run-focused.mjs logic 'authentication return route'` **1/1 passed**。
- 登出合同与 Mock 身份存储回退：`node scripts/test/run-focused.mjs logic 'logout'` **4/4 passed**；另 `npm run check:fast`、`npm run i18n:check`、E2E harness 文件 `node --check`、`git diff --check` 通过。
- 最终 IAB 必须确认：登录后会话菜单显示服务端/Mock authority 确认的账号与角色；viewer 显式登出后只回到站内 `returnTo`；用 viewer 重新登录后安全消费允许的目标，管理路由仍被拒绝；退出结果 unknown 时不伪报成功、不重复发送，检查会话后按 authority 结果收敛。
- 本轮未运行 CDP harness，也未启动 Chrome/Edge。逻辑与静态门禁不构成页面端到端证据，F4.23 继续未完成；真实 Python 会话过期/撤销、cookie/CSRF 和后端联调也未验证。

### 2026-10-10 补充：登录转场单一所有者

- **缺陷：**`LoginEntryPage` 已通过 `ConsoleLoginRoute` 的 `onAuthenticated` / `onSetupRequired` 回调负责登录成功和首次初始化跳转；`App` 全局身份守卫又对 `#/login` 的同一权威状态执行一次相同导航，形成重复副作用入口。
- **修复：**登录页转场由 feature route owner 单独拥有；`App` 全局守卫遇到公开登录路由立即返回，只处理非登录路由的身份守卫。没有新增设计模式或额外状态。
- **验证：**架构测试新增单一所有者约束，`npm run test:architecture` **23/23 passed**；`npm run test:logic:focused -- 'authentication return route'` **1/1 passed**；`npm run check:fast`（typecheck、format、lint、Console OpenAPI 43 paths）与 `git diff --check` 通过。主应用 E2E 增加了“登录确认只产生一次 overview replace 导航”断言，`node --check tests/e2e/app-authentication.e2e.test.mjs` 通过；浏览器 E2E 未运行。
- **边界：**F4.23 仍未完成；上述静态/逻辑证据尚未运行新增的 mounted E2E 断言，也未覆盖真实 Python `/auth/me`、logout/revocation、过期、Cookie/CSRF 或生产服务联调。按用户约定，完整浏览器 E2E 留至全部实现结束。
