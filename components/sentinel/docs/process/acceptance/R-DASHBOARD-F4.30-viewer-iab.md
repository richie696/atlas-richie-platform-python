# R-DASHBOARD-F4.30 查看者只读权限 IAB 验收（部分）

日期：2026-10-08  
状态：部分完成；F4.30 不勾选  
范围：本地 Dashboard Mock + Codex 内置浏览器；未访问 Python Console、数据库或真实配置源

## 场景与结果

- 使用独立的 `localhost:4173` origin 建立干净 Mock 浏览器状态，避免覆盖另一个 `127.0.0.1:4173` 标签的管理员 Mock session。通过登录页以合成 `viewer` 身份完成登录，页头显示 viewer；主导航只显示总览、应用与实例、规则、实时监控、故障分析，不显示系统管理。
- 直接打开 `#/accounts` 和 `#/roles?account=account-view`，两者均显示“只有当前管理员可以管理账号和角色”，没有渲染账号表格、账号编辑器或角色编辑器。路由 query 中的目标账号没有绕过 admin 访问要求。
- 直接打开 `#/rules?app=app-one` 并打开 `binding-app-one` 的完整规则集，viewer 可以读取规则快照/版本/发布信息；草稿区域明确显示“当前会话不能编辑规则；授权检查仍由后台逐请求执行”，创建活动计划按钮 disabled。未提交、修改或发布规则。
- IAB 可访问性树与截图分别确认了管理路由拒绝和规则工作台只读提示；页面顶部标明全部为示例数据。自动化 `npm run test:logic` 的 **253/253** 结果来自同一工作周期此前运行；本轮 `npm run test:http` 在仅开放本机 loopback listener 后 **95/95**。二者补充领域/HTTP 边界，不等同于生产权限证据。

## 未覆盖与结论

- 仅证明本地 Mock 前端对 viewer 的导航/路由保护和规则编辑 UI 表现；服务端每请求授权、Session 过期、真实账号/角色持久化未验收。
- 尚未以管理员 session 对内置账号/最后一名 active admin 的状态/角色变更做 UI 交互验收；不能为了测试而真正提升或撤销生产权限。
- 本记录的 IAB 页面行程未实际操作管理员角色写入，因此当时的浏览器证据没有覆盖保存失败保留草稿、并发冲突、会话失效时清理授权 facts 与跨页一致性。后续 mounted focused tests 已覆盖 last-admin 拒绝后保留草稿、冲突锁定旧 revision、读取最新状态失败仍保留草稿及成功后同步权威角色（推进清单 §15.1083）；这些测试不等同于 IAB 页面行程或已部署 Python 服务授权验收，故 F4.30 继续未勾。
- 全程只使用 Codex IAB；没有调用 Chrome、Edge、CDP。

## 2026-10-12 isolated localhost direct-route recheck

- In the isolated `localhost:5173` Mock, restored the pre-test viewer identity after a reversible role-save check. Direct navigation to `#/system?view=roles&account=account-admin` rendered the admin-only denial (“Only the current administrator can manage accounts and roles”) without rendering the role editor. The session menu and navigation remained viewer-scoped.
- This repeats the viewer direct-route boundary only. It does not satisfy last-active-admin UI protection, save-failure draft retention, concurrent revision conflict, Python authorization, or deployed session consistency; F4.30 remains open. No further account or role mutation was performed after restoring the original viewer role.
- Codex IAB only; no Chrome, Edge, CDP, backend, database, or configuration center.

## 2026-10-12 mounted built-in administrator protection recheck

- **Environment:** isolated local Vite origin `127.0.0.1:5202`, Codex IAB, explicit Mock profile and synthetic `admin` session. No Python Console, persistent database, real configuration center, or production identity was used.
- **Observed behavior:** opened System → Role Binding and selected the `admin` target. The detail showed `admin · active`, the explicit explanation that the built-in administrator role cannot be changed, both `admin` and `view` radio controls disabled, and Save/Discard disabled. No role command was submitted and no Mock account state was changed.
- **Boundary:** this re-confirms the mounted built-in-account UI guard only. The local scenario has no separately selectable non-built-in last-active-admin account, so it does not prove that distinct mounted branch. Save-failure draft retention, concurrent conflict, live Python authorization/session behavior, and the final cross-page E2E matrix remain open; F4.30 stays unchecked. The temporary tab and Vite server were closed.

## 2026-10-12 frontend/Mock/Python account authorization matrix

- **Source matrix:** frontend `decideControlPlaneAccess` rejects `view` from admin-only routes by role even if a forged identity includes `rules:write`, while `metrics:view` remains independently allowed; route metadata marks System, Accounts and Roles as admin-only. Mock account-management handlers require the explicit Mock principal to equal `admin`. Python Console account list/detail and command/operation routes each read the current server session and require `AccountRole.ADMIN`; authorization happens before directory or command service access.
- **Focused frontend checks:** `npm run test:logic:focused -- 'F2 admin and metrics requirements differ'` **1/1 passed**; `npm run test:logic:focused -- 'F2.6 route metadata distinguishes metrics viewers'` **1/1 passed**.
- **Mock HTTP check:** `npm run test:http:focused -- 'ACCOUNT-MOCK-AUTHZ|ACCOUNT-MOCK-IDENTITY: missing'` **2/2 passed**. Added an explicit synthetic viewer case proving account list, account detail, role command and operation lookup each return HTTP 403 `forbidden`; no actual Mock mutation is authorized.
- **Python Console check:** from `components/sentinel/sentinel-console`, `uv run --extra test pytest -q tests/test_account_commands_api.py tests/test_account_directory_api.py` **21 passed**. Added a detail-route viewer denial test that asserts the account-directory reader is never called. Existing tests cover viewer list, command mutation and operation lookup rejection; no Python production source changed.
- **Change scope:** only the Mock HTTP test, Python account-directory API test and this F4.30 record were edited. `npx prettier --check tests/http/accountIdentityMock.test.mjs` passed. The initial attempt to pass the full F4.6 title to the focused runner matched no test; rerun with its exact title (`F2.6 route metadata distinguishes metrics viewers`) passed.
- **Unverified boundary:** Codex browser surfaces reported `browsers: []`; no mounted IAB verification was available. No Chrome, Edge, CDP, full E2E, live Python server, database or real identity was used. These focused checks prove frontend policy logic and controlled Mock/ASGI route contracts, not deployed session/RBAC behavior or rendered denied UI. F4.30 remains open for the planned mounted and live/backend acceptance matrix.
