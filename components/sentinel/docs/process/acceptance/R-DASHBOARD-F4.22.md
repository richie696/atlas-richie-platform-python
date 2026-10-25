# R-DASHBOARD-F4.22 登录凭据防默认提权验收（部分）

日期：2026-10-08  
范围：本地 Dashboard demo mock 登录 handler 与登录页面；不是 Python 后端认证验收。

## 结果

- [x] 非空未知用户名不会获得 admin。
- [x] 错误密码与未知用户名返回一致的未认证响应，不透露账号存在性。
- [x] 失败登录不会写入或升级 `sentinel.mock.role`。
- [x] demo 合成密码不会进入 localStorage mock state。
- [x] 已声明的本地 demo admin/viewer 身份只能获得各自固定角色。
- [ ] F4.22 全量验收：停用账号、429 限速、真实网络错误与服务端映射尚未接入本地 mock/Python API 端到端路径。

## 内置浏览器证据

只使用 Codex In-app Browser，在隔离的 `localhost:5183` origin 上测试；未启动 Chrome/Edge，也未运行 CDP E2E。

1. 未知用户名提交后仍处于登录页，显示“账号或密码错误，或当前账号无法登录”。
2. `admin` 配合错误密码提交后仍处于登录页，并显示同一文案。
3. `admin` 配合 demo 合成密码通过 session 回读后进入总览。
4. viewer UI 登录未单独执行；viewer 的固定角色由 HTTP 工作流测试覆盖。

## 自动化验证

- `node --test --test-name-pattern='F4.22-LOGIN-PAGE-RENDER' tests/i18n/catalog.test.mjs`：**1/1 passed**；实际 `LoginEntryPage` + `AuthenticationProvider` SSR 在简中/英文/日文覆盖已知拒绝、登录写入结果未知、session authority 不可用三态。检查非枚举拒绝文案、未知状态的显式 session 检查入口与禁用重放表单、不显示 raw error，以及服务不可用时隐藏登录表单。
- `npm run test:logic:focused -- 'F4[.]22'`：**5/5 passed**；覆盖已知拒绝可修正、unknown 不可重放、显式检查 session、有界 `Retry-After` 与编辑凭据后冷却仍在。
- `node --test tests/i18n/catalog.test.mjs`：**18/18 passed**。
- `npm run check:fast`：通过（typecheck、format、lint、43-path OpenAPI contract）。

- `node --test --test-name-pattern='IDENTITY-' tests/http/run.mjs`：7/7 passed。
- `npm run typecheck`：通过。
- 目标 ESLint：通过。
- `npm run i18n:check`：通过，三语键与插值一致。
- `npm run test:build-profiles`：2/2 passed；live-only artifact 排除 mock handler 的门禁通过。
- `npm run build:demo`：通过；保留既有 bundle warning。

## 安全边界

`synthetic-password` 是仅用于显式 demo build/MSW 的可公开合成测试口令，不是真实密码、默认账户密码或生产认证方式。真实 build profile 不包含此 handler；真实身份、停用状态、速率限制、Cookie/CSRF 及审计仍由 Python Console/API 定义和验收。

本次实际页面证据使用受控 workflow snapshot 的 server-side rendering，不执行点击/输入、React hydration、计时器冷却、页面路由或真实 HTTP；F4.22 继续未完成，完整浏览器/真实 Python 验收留在最终阶段。

## 2026-10-12 补充：登录 workflow、页面投影与 Python API 聚焦复验

- **验证：**在 `dashboard-prototype` 执行 `npm run test:logic:focused -- 'F4[.]22'`，**7 passed**；执行 `node --test --test-name-pattern='F4.22-LOGIN-PAGE-RENDER' tests/i18n/catalog.test.mjs`，**1 passed**。在 `sentinel-console` 执行 `uv run --extra test pytest -q tests/test_login_api.py tests/test_login_attempt_limiter.py tests/test_session_api.py`，**25 passed**。Python 用例覆盖未知/错误/停用账号一致拒绝、429 有界冷却、无效 CSRF/origin 在查凭证前拒绝、SQL 限流跨实例恢复与并发首失败串行化、session 匿名/有效读取。
- **边界：**这些是前端纯逻辑、实际组件 SSR 与 Python HTTP/SQLite 服务测试，不是 React 到 Python 的浏览器网络 E2E；未验证真实客户端冷却计时/键盘与焦点交互，也未对生产 MySQL 的登录限流执行本组测试。F4.22 仍未完成，最终 IAB/真实服务验收继续后置。

## 2026-10-10 补充：会话确认后卸载凭据表单

- **实现：**账号/密码草稿与字段校验现在由 login form 子树持有。只有 bootstrap/session 明确确认 anonymous 时显示初始表单；错误/限流时保留可修正输入，`result-unknown` 时仍显示禁用表单供核查状态；权威 session 成功或 setup gate 接管后直接卸载表单，避免以 Effect 同步复制状态或在路由通知前短暂保留密码。
- **验收用例：**扩展 `LoginEntryProbe`，在 `onAuthenticated` 发生时同步检查凭据表单是否已卸载，并将结果断言纳入最终 mounted login E2E。E2E 用例尚未运行。
- **验证：**Dashboard `npm run check:fast` 通过；`npm run test:logic:focused -- 'F4[.]22'` **5 passed**；实际登录页面 SSR `node --test --test-name-pattern='F4.22-LOGIN-PAGE-RENDER' tests/i18n/catalog.test.mjs` **1 passed**；`node --check tests/e2e/login-entry.e2e.test.mjs` 与 `git diff --check` 通过。未运行浏览器/完整 E2E，也未连接 Python Console。
- **边界：**本项加强 React 状态生命周期，不证明浏览器内实际卸载时序、真实 API 登录/429/停用账号行为或 Cookie/CSRF。F4.22 继续开放，最终 E2E 和真实后端集成仍是验收条件。

## 2026-10-11 补充：当前工作区登录合同复核

- **验证：**重新运行 `npm run test:logic:focused -- 'F4[.]22'`，**5/5 passed**；运行 `node --test --test-name-pattern='F4.22-LOGIN-PAGE-RENDER' tests/i18n/catalog.test.mjs`，**1/1 passed**。本轮实际覆盖 known rejection、unknown write/explicit session inspection、429 bounded delay 与凭据编辑期间冷却保留，并检查真实 `LoginEntryPage` SSR 的三种安全投影。
- **边界：**不证明浏览器计时、键盘/焦点/路由、真实 Python 登录 API、停用账号或 live 429；这些仍纳入最终 mounted IAB / full-stack E2E。没有启动浏览器或 Docker。

## 2026-10-12 补充：隔离来源 mounted 登录交互

- **环境：**Codex IAB 的隔离 `http://localhost:5173` 本地 Mock origin；仅输入仓库公开的合成用户名与无效测试口令，不访问真实身份服务。
- **验证：**空凭据提交显示必填提示；输入 `viewer` 与合成错误口令后以 Enter 提交，页面展示统一认证拒绝文案，用户名仍保留、密码仍掩码。点显隐控件可切换为“隐藏密码”，再次操作并提交后恢复遮蔽。随后使用仓库本地 Mock 的 `synthetic-password` 成功登录 viewer，导航至 overview，会话菜单明确显示 viewer；直接打开系统管理路由显示“只有当前管理员可以管理账号和角色”且没有管理页面内容。
- **边界：**只验证简体中文 mounted Mock 路径和已知正确/错误凭证；不证明完整三语 mounted、429 冷却计时、pending/unknown remask 时序、真实 Python 登录/停用状态与 Cookie/CSRF。F4.22 仍开放，完整 E2E 保持最后执行。

## 2026-10-12 补充：mounted 拒绝与有界 429 冷却

- **实际 Mock 登录页面：**在隔离的 `http://127.0.0.1:5203/#/login` 提交一次 `viewer` + 合成错误口令。页面显示统一非枚举认证拒绝、保留登录名，密码仍以掩码显示；未重试，也未连接 Python/生产身份服务。
- **429 fixture：**同一个隔离 Vite server 上短暂新增 `tests/e2e/probes/login-entry-mounted.html`，只用于挂载既有 `LoginEntryProbe`；其 test-only `rate` 控制将下一次 Port 调用固定为单次 `{status: 429, code: "rate_limited", retryAfterMs: 2500}`，没有撞真实/Mock 登录阈值。Codex IAB mounted 页面显示“登录受限，请在约 3 秒后重试”，提交按钮在冷却期间 disabled，调用计数为 1。冷却到期后页面回到可提交状态，调用计数仍为 1；期间没有第二次提交。
- **未覆盖边界：**从收到 429 到主动编辑密码的下一次工具交互时 2.5 秒期限已到，因此本次没有实际观察“活跃冷却期间编辑凭据仍保持 disabled”；该状态仍由既有 workflow focused tests/E2E source assertion 覆盖，不把它记作本次 mounted 证据。未覆盖 Python live HTTP、Cookie/CSRF、停用账号或生产限流。
- **隔离/清理：**临时 harness 已删除；只关闭本轮创建的 IAB tab 和 Vite session `36992`。端口 `5202` 在启动前已被占用，本轮未停止或修改该进程。没有访问/清理任何其他浏览器标签或容器。
- **结论：**补上 mounted Mock 拒绝和 test-only 单次 429 显示/禁用/期限后恢复切片；F4.22 仍因活跃编辑冷却计时、Python live session/限流链路与最终整站 E2E 未验收而保持开放。

## 2026-10-12 补充：活跃冷却逻辑与 Python/React HTTP 边界复核

- **React workflow：**`npm run test:logic:focused -- 'F4[.]22'`，**8/8 passed**。覆盖有界 `retryAfterMs`、期限内禁止二次 dispatch、期限后允许重试，以及登录错误被凭据编辑清除后冷却 feedback 仍可由 deadline 投影；这不是 React mounted input 编辑证据。
- **React HTTP 边界：**`npm run test:http:focused -- 'HTTP-ERROR-MATRIX|IDENTITY'`，**19/19 passed**。Console transport 将 canonical `429 rate_limited` 安全映射为 `AppErrorKind.RATE_LIMITED`，保留合法 `retryAfterMs` 且不泄漏响应正文；真实身份 HTTP/mock workflow 其它路径通过。
- **Python API 与 limiter：**`uv run --extra test pytest -q tests/test_login_api.py tests/test_login_attempt_limiter.py`，**21 passed**。API 负例断言有界 429 (`retryAfterMs` 最大 300000ms) 且在限流时不查凭证；同组 limiter tests 通过。使用测试内 SQLite/合成输入，无生产数据库或真实账号。
- **未完成 mounted 编辑动作：**本轮 CUA 子任务枚举不到任何可用 browser (`browsers: []`)，所以不能在当前授权边界内实测“429 仍活跃时分别编辑用户名/密码，提交继续 disabled”。已有 `tests/e2e/login-entry.e2e.test.mjs` 源码包含改密后仍 disabled、等到期再 enabled 的断言，但受禁止 Chrome/Edge/CDP 约束，本轮没有执行该 CDP runner；源码存在不是运行证据。
- **Python→React live 边界尝试：**曾启动绑定本地测试 API 的 Uvicorn（数据库为 `sqlite+aiosqlite:///:memory:`、限流固定合成值）及 Vite live 配置，但在发现本轮无 IAB 后未从浏览器发送登录请求，随即停止两服务。停止 Uvicorn 的 Ctrl-C 打断 asyncio teardown，日志出现 in-memory SQLAlchemy 连接关闭 `CancelledError`；进程已退出，临时数据库没有文件。另确认本轮启动的 Vite 服务已停。故这不是 Python→React live 通过证据；Python API、transport mapping 和 React UI/workflow 仍是独立层证据。
- **结论：**源码路径与自动化支持“活跃冷却期间编辑可修正凭据但提交应受 workflow deadline 阻止”的合同，未发现可复现缺陷；但缺少本轮 mounted active-edit 与 Python→React live 联调运行证据。F4.22 继续开放，不运行完整 E2E。

## 2026-10-12 补充：认证端点到 workflow 的 HTTP 冷却合同

- **自动化：**新增 `IDENTITY-HTTP F4.22` focused 用例，使用 MSW 合成 `/bootstrap`、`/auth/me`、`/auth/login` 响应，经正式 `ConsoleTransport`、Identity HTTP adapter 与 `AuthenticationWorkflow` 运行：`401 unauthenticated` 保持匿名且可清除已知拒绝；之后的 canonical `429 rate_limited` 保留有界 `retryAfterMs`，冷却期限内再次提交由 workflow 在 HTTP dispatch 前拒绝，期限届满才允许发出下一次请求。断言合成密码不进入 workflow snapshot。
- **验证：**`npm run test:http:focused -- 'IDENTITY-HTTP F4[.]22'` **1/1 passed**。这是本地合成 HTTP 合同，不访问 Python 服务、数据库或真实身份服务；未运行浏览器/E2E。
- **边界：**本用例把前端正式 HTTP adapter、通用 transport 解码与 workflow 组合起来，但并不证明 Python API/部署态限流、停用账号、cookie/CSRF、真实网络故障 UX 或 mounted 冷却计时。F4.22 继续开放，最终 React→Python 与整站 E2E 仍后置。
