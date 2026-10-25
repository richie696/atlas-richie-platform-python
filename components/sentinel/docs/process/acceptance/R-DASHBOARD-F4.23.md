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

- F4.23 整项仍未勾选。真实 Python/MySQL SQL-composed ASGI 登录→`/auth/me`→logout→旧 cookie 重放已由 2026-10-12 补充覆盖；React 到 Python 的 mounted 页面链路、部署态会话过期及最终回跳/导航验收仍开放。
- Mock logout 的 204 空流解析问题已由本地 HTTP 回归和 IAB 自动回读复测覆盖；真实 logout 的 HTTP/Cookie/持久化撤销另见 2026-10-12 补充，但不等同于浏览器连接 Python 服务的端到端验收。
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

### 2026-10-11 补充：当前工作区窄回归复核

- `npm run test:logic:focused -- 'F4[.]23|authentication return route|logout'`：**5 passed**，覆盖安全回跳和重新授权、未知登出结果不可重放、Mock storage 写入不可靠时当前页维持匿名。
- `node --test --test-name-pattern='F4.23' tests/architecture/dependencies.test.mjs`：**1 passed**，确认公开登录路由导航由单一 route owner 负责。
- 尝试的 `npm run test:architecture:focused` 并非仓库脚本，返回 Missing script；没有测试在该命令下运行。已改用上述实际 Node 测试入口完成窄验证。
- 这些结果不替代 mounted 浏览器、Python `/auth/me`、服务端 logout/revocation、会话过期或 Cookie/CSRF 验收；F4.23 仍开放，完整 E2E 按计划留到所有实现完成后执行。

### 2026-10-12 补充：真实 MySQL 登录、登出与旧 cookie 撤销

- **实现：**扩展共享真实 SQL identity HTTP acceptance：在 SQL-backed login 与 session read、改密/重新登录之后执行真实 `/api/v1/auth/logout`；要求 `204` 空响应、session 与 CSRF 两个 cookie 均 `Max-Age=0`。随后用独立 HTTP client 重放旧 opaque session cookie，`/api/v1/auth/me` 必须返回匿名；最后直接核对 MySQL 中对应 session hash 的 `revoked_at` 已持久化。保留旧密码/新密码/opaque cookie/CSRF 原文不进入持久化 projection 的断言。
- **验证：**在 `components/sentinel/sentinel-console` 执行 `./tools/with_disposable_e2e_dependencies.sh uv run --extra test --extra mysql pytest -q tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_sql_identity_http_persists_credentials_and_sessions`，真实 MySQL `8.4.11` + Consul `1.21.1`，**1 passed**。首次窄运行只暴露测试 helper 漏 `hashlib` 导入，修正后重跑通过且无 warning。临时容器 `sentinel-e2e-mysql-30967de30b2ea9f74e54d0f8a4386feb`、`sentinel-e2e-consul-30967de30b2ea9f74e54d0f8a4386feb` 已按精确名称确认不存在。
- **边界：**证明 MySQL+Python SQL-composed ASGI HTTP/cookie/session 撤销路径，不证明 React 浏览器真实连接 Python、页面导航与 session expiry UX、生产 ingress/multi-worker 或 PostgreSQL 同一验收。F4.23 仍未完成，最终 IAB E2E 保持后置。

### 2026-10-12 补充：主开发端口 mounted IAB 会话闭环复验

- **环境：**只用 Codex 内置浏览器；主开发端口 `http://127.0.0.1:5173` 的本地 Mock，页面明确标示演示数据。登录使用仓库内合成身份，不访问真实服务、数据库或配置中心。
- **验证：**会话菜单确认显示 `admin 管理员`；退出后导航到 `#/login?returnTo=system&env=test-env&app=all&range=1h&account=account-view`。页面重载仍为匿名登录；用 admin 合成身份重新登录后按站内 returnTo 回到系统页。再次注销后，错误 viewer 密码显示统一的“账号或密码错误，或当前账号无法登录”文案，用户名 `viewer` 保留，密码仍掩码；使用正确 viewer 合成身份后，目标 `system` 因 viewer 无管理权限被重新授权为 `overview`，导航隐藏“系统管理”，会话菜单显示 `viewer`。
- **对照失败：**已有标签 `http://127.0.0.1:5174` 上的 admin 注销仍进入“退出登录未完成”；点击“检查当前会话”仍停留错误页，整页刷新又恢复 admin。该运行上下文与 `5173` 的新流程表现相反，当前没有浏览器网络观测可定位 5174 的 POST/handler/存储环节，不能宣称差异已修复，也不能拿 5173 成功覆盖该失败。
- **后续隔离：**在 5174 新开干净 IAB 标签，admin 注销正常回到带 returnTo 的登录页；旧标签仍停留 unknown。由新标签 logout 后再刷新旧标签，它读取到匿名并进入 login；在旧标签重新登录 admin 后再次注销也成功。由此将现象收窄为旧标签 mounted 状态/运行上下文异常，而不是 5174 端口稳定故障；但当前 IAB 无网络请求日志，无法证明旧标签失败发生在 dispatch、MSW handler 还是 transport/owner 阶段，因此根因仍未确认。
- **结论与边界：**新增证据证明主端口 mounted Mock 的身份菜单、注销、回跳刷新、错误凭证反馈与新身份授权路径；F4.23 继续开放，直到 5174 不一致运行态查清并完成与 Python 服务的 mounted 联调。该结果也不覆盖登录限速、真实过期/CSRF/deployed cookie 或生产服务。
- **工具边界：**未调用 Chrome、Edge 或 CDP；没有重置/删除 5174 的浏览器存储。完整自动 E2E 仍遵循“全部实现完成后再执行”的阶段约定。

### 2026-10-12 补充：viewer/admin 注销矛盾结果复核

- **应用级 Mock HTTP：**新增 `IDENTITY-APP-MOCK` 测试，使用正式 `createConsoleAuthentication` 与完整 `createAppConsoleMockAssembly`，分别恢复 admin/view 身份并执行 logout；两种身份均得到匿名 session，Mock principal 持久化为 `anonymous`。`npm run test:http:focused -- 'IDENTITY-APP-MOCK'` **1/1 passed**。
- **内置浏览器：**主开发端口 5173 上，先前一次 viewer 注销进入“退出登录未完成”；刷新后 `/auth/me` 仍确认 viewer。随后从确认的 viewer 菜单重试成功返回登录页；再做一次 viewer 登录→菜单注销也成功。之后 admin 登录时确认菜单显示 `admin 管理员` 且管理导航可见，显式注销成功返回登录页。过程未修改密码，也未清理浏览器 storage。
- **解释边界：**新证据把“viewer/logout 一直失败”的猜测排除，但不能消除先前单次 unknown 结果；浏览器运行态仍缺少请求/响应观测，无法证明该次失败发生于请求派发、handler、transport 或确认阶段。此前 5174 旧 mounted 标签的 unknown 也尚无可观察的网络根因；新标签和后续恢复后成功不能覆盖这两次异常。
- **关闭决定：**mounted Mock 的 admin/view 身份菜单、登录、注销与安全回跳已有成功复验；F4.23 整项仍未关闭，因为其包含的异常 logout 结果尚未定位，且 React mounted 页面到 Python session/Cookie/CSRF 的联调、过期/撤销部署验收仍未完成。未运行全量 E2E、未调用 Chrome/Edge/CDP。

### 2026-10-12 补充：隔离 localhost viewer 授权与注销刷新

- **环境：**Codex IAB 新标签使用 `http://localhost:5173`，与保留异常 owner 的 `127.0.0.1` origin 隔离；本地 Mock 合成 viewer。
- **验证：**合成 viewer 登录成功后菜单显示 `viewer 查看者` 且顶级导航不含“系统管理”。直接进入 `#/system?app=all&range=1h&view=accounts` 显示管理员专属拒绝状态，不呈现管理功能。返回 overview 后注销导航至 `#/login?returnTo=overview&app=all&range=1h`；刷新后仍为匿名登录页。
- **边界：**该切片再次证明 viewer 的客户端路由访问拒绝、logout 回跳和同 origin 刷新后的匿名投影；它不覆盖此前 `127.0.0.1:5173` 一次 unknown、5174 旧标签 unknown、真实 Python mounted session/Cookie/CSRF 或部署过期撤销。F4.23 保持开放。

### 2026-10-12 补充：重复 viewer 注销再次进入未知态

- **复现步骤：**在上述隔离 `localhost:5173` 标签第一次 viewer login→logout 成功并刷新仍匿名后，再次登录同一 Mock viewer；第二次从 overview 会话菜单显式注销时出现英文 `Sign-out did not complete` / `Check current server session`。点击一次只读会话核查仍停在 unknown。
- **保护动作：**没有重放 logout，没有刷新/关闭该 tab，也没有清除 storage；标签已保留供后续诊断。当前 UI 不提供 request/response 详情，无法定位本次在派发、Mock handler、transport 或 owner 确认的哪一步失败。
- **跨标签只读核对：**随后新开同源标签直接请求页面身份快照，顶栏仍显示 `viewer`。Mock handler 源码确认该身份来自同源 `localStorage` principal；因此这次 unknown 后的本地 Mock principal 实际仍为 viewer。该读回只说明 Mock storage 未被清成 anonymous，不等同于真实 Python/server session 状态，也无法单独断定 POST 未派发还是 handler/响应环节失败。临时只读标签已关闭；后续 IAB inventory 不再列出原 unknown 标签，因此不能声称现场目前仍可继续操作。
- **应用组合对照：**将 `IDENTITY-APP-MOCK` 扩展为在同一个 `createConsoleAuthentication` owner 与完整 app Mock assembly 内，分别执行 admin/view 首次 restore→logout 和再次 login→logout。focused HTTP **1/1 passed**，四个 logout 后 session 与 Mock principal 均为 anonymous。它说明重复周期的 app-level HTTP composition 正常，但不能覆盖 React mounted 的 unknown。
- **结论：**该重复周期让注销异常在 `localhost` 新隔离来源也可复现，排除了“仅 5174 旧标签”的解释；同时第一次成功不能覆盖第二次未知。F4.23 必须保持开放，优先查明多次登录/注销后的 mounted 状态与确认流程，再做 Python live 验收。

### 2026-10-12 补充：确定性 logout 401 不应转成 unknown

- **回归证据：**新增应用级 HTTP 回归，用正式认证 owner 模拟 logout 返回协议允许的 `401 unauthenticated`。修复前观察到 `Command observation cancelled`：通用 `expireOnUnauthorized` 回调同步调用 `AuthenticationWorkflow.expire()`，进而取消它正在处理的 logout 命令。该响应本来是确定性拒绝，却被错误归为 `result-unknown`。
- **修复：**Logout endpoint 不再要求通用 transport 在 401 上取消当前命令；workflow 已在发送前清除可信 access facts，失败后保持 `unavailable`，要求显式 `inspectSession()`。因此不会继续展示旧权限，且可消费稳定的 HTTP 错误并核查当前会话。
- **验证：**修复后新回归断言 401 以 `error` 保留、访问状态不可用，显式核查读回匿名；身份 HTTP **8/8 passed**、logout/returnTo logic **5/5 passed**、typecheck、Prettier 与 `git diff --check` 通过。
- **关闭边界：**这证明并修复了一个可确定的 401 自取消缺陷，但 IAB 既往 unknown 缺少请求/响应追踪，不能断言它就是此 401 路径；被保留的 unknown owner 未重放、未刷新。F4.23 仍需单独 mounted/真实 Python 会话验收，不能由该回归关闭。

### 2026-10-12 补充：再次登录后 admin Mock 注销未知态

- **环境：**Codex IAB 隔离 `localhost:5173`，本地 Mock。已完成 viewer→admin 登录、角色页 viewer 目标的临时保存 admin→恢复为 view、reload 回读成功，并已恢复原 viewer 会话。
- **复现：**viewer 从 overview 会话菜单注销时页面出现 `Sign-out did not complete` 与只读 `Check current session`。点击一次核查后仍处于同一 unknown 页面。
- **保护：**没有重发注销，没有刷新/关闭该 tab，没有清除 storage；tab 已 `markHandoff()` 保留。该现象在 admin 和 viewer 多周期内均出现过，进一步说明成功正向周期不能代表 mounted logout 稳定。
- **结论与边界：**现有 IAB 无 HTTP request/response 观测，无法区分请求 dispatch、Mock handler、响应验证或 owner/lifecycle 阶段；未知操作状态不推测。React→Python Cookie/CSRF/session 仍未验证，F4.23 保持开放。没有访问真实后端、数据库或配置中心。

### 2026-10-12 补充：隔离 origin 注销周期、owner 过期与 returnTo 窄复核

- **自动化：**`npm run test:logic:focused -- 'F4[.]23|authentication return route|logout'` **5/5 passed**，覆盖站内 allow-list、确认身份重新授权、logout 失败不恢复旧权限且不重放；`npm run test:logic:focused -- 'expire/cancel|foreground revalidation|foreground observer'` **3/3 passed**，覆盖 owner 过期时忽略迟到身份、前台权威重读和 observer 生命周期；`npm run test:http:focused -- 'IDENTITY-APP-MOCK|IDENTITY-HTTP|AUTH-APP-OWNER'` **8/8 passed**，覆盖 admin/view 重复登录登出、HTTP 会话读回、当前/过期 owner 401 处理；`npm run test:http:focused -- 'AUTH-APP-OWNER'` **3/3 passed**，单独复核 owner epoch/迟到旧请求/当前 malformed 401 过期语义。
- **mounted IAB：**隔离本地 Mock origin `127.0.0.1:5211`，匿名直达 `#/accounts?app=all&range=1h` 后重定向到 `#/login?returnTo=accounts&app=all&range=1h`。使用合成 viewer 登录后，该管理目标被重新授权并安全回落到 `#/overview?app=all&range=1h`；菜单身份显示 viewer。logout 导航到 `#/login?returnTo=overview&app=all&range=1h`，整页刷新后仍为匿名登录页；再次登录 viewer 回到 overview，再执行第二个独立 logout 周期也成功回到相同站内 returnTo，没有出现 `result-unknown`。全程不含凭据或敏感参数进入 URL。
- **会话 owner/过期边界：**mounted 页面证明单标签内连续登录/登出与匿名读回；owner epoch、401 过期和忽略迟到旧响应由上述应用组合/逻辑测试覆盖。没有通过手动改浏览器 storage、伪造 Cookie 或注入运行时代码模拟服务端过期，因此部署态过期后的页面 UX 和跨标签行为未由本次 IAB 证明。旧 mounted `unknown` 记录仍无法回溯其 dispatch/response 原因，不能由新鲜 origin 的成功覆盖。
- **结论：**本轮补齐安全 returnTo 与新鲜 Mock origin 多周期注销的定向证据，但 F4.23 仍不关闭；React mounted 页面直连 Python 的 Cookie/CSRF、实际服务端 session expiry/revocation 与部署态验收待 B0.5/最终 E2E。未运行完整 `test:e2e`，未调用 Chrome、Edge 或 CDP，未访问真实配置中心/数据库/生产身份服务。

### 2026-10-12 补充：session authority 暂不可用与确认为过期

- **自动化：**新增 `AUTH-APP-OWNER F4.23`，通过正式 `createConsoleAuthentication`、Console transport、identity HTTP adapter 与 MSW 建立登录 session 后，分别模拟 `/auth/me` 返回 `503 service_unavailable` 和 `401 unauthenticated`。503 后 owner 投影为 `unavailable` 且不暴露旧身份；确认 401 后立即进入 `expired`，不继续保留旧身份；后续 authority 回读 `null` 才恢复为匿名。
- **验证：**`npm run test:http:focused -- 'AUTH-APP-OWNER F4[.]23'` **1/1 passed**。全程是本地合成 HTTP，不访问 Python/数据库或部署服务；未运行浏览器/E2E。
- **边界：**这是正式 transport-owner 的合同测试，不是 React mounted 页面、Cookie/CSRF 部署态或服务端撤销的 live 验收。F4.23 继续开放。
