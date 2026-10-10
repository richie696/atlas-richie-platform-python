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

## 2026-10-10 补充：会话确认后卸载凭据表单

- **实现：**账号/密码草稿与字段校验现在由 login form 子树持有。只有 bootstrap/session 明确确认 anonymous 时显示初始表单；错误/限流时保留可修正输入，`result-unknown` 时仍显示禁用表单供核查状态；权威 session 成功或 setup gate 接管后直接卸载表单，避免以 Effect 同步复制状态或在路由通知前短暂保留密码。
- **验收用例：**扩展 `LoginEntryProbe`，在 `onAuthenticated` 发生时同步检查凭据表单是否已卸载，并将结果断言纳入最终 mounted login E2E。E2E 用例尚未运行。
- **验证：**Dashboard `npm run check:fast` 通过；`npm run test:logic:focused -- 'F4[.]22'` **5 passed**；实际登录页面 SSR `node --test --test-name-pattern='F4.22-LOGIN-PAGE-RENDER' tests/i18n/catalog.test.mjs` **1 passed**；`node --check tests/e2e/login-entry.e2e.test.mjs` 与 `git diff --check` 通过。未运行浏览器/完整 E2E，也未连接 Python Console。
- **边界：**本项加强 React 状态生命周期，不证明浏览器内实际卸载时序、真实 API 登录/429/停用账号行为或 Cookie/CSRF。F4.22 继续开放，最终 E2E 和真实后端集成仍是验收条件。
