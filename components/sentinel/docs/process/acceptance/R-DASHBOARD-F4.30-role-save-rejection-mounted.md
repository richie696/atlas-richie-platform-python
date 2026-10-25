# R-DASHBOARD-F4.30 角色保存被服务端拒绝时保留选择

日期：2026-10-12  
状态：前端 mounted 自动化切片通过；F4.30 总项仍开放  
范围：React 19 + happy-dom，真实 `RoleEditor` + 真实 account-management workflow；合成 Port，无 Python/DB/配置中心

## 覆盖场景

角色详情最初读取的是普通、非内置管理员的旧快照（`lastActiveAdmin=false`, revision `8`）。角色编辑器选择 `view` 后，服务端权威写入返回 `rejected:last_admin`，模拟并发变化使此账号已成为最后一个有效管理员。

用例通过实际 React 19 root 挂载 `RoleEditor`，使用真实 `createAccountManagementWorkflow` 和 Astryx `RadioGroup`；不是 SSR 或手工 render 替身。断言：

- 初始 `admin` 角色为干净状态，保存按钮禁用。
- 选择 `view` 只形成本地草稿，按钮变为可保存。
- 服务端拒绝只发出一次写请求；页面显示本地化的最后管理员拒绝说明。
- 拒绝后 `view` 仍保持选中且草稿仍可见，没有被组件清空。

## 验证

在 `components/sentinel/dashboard-prototype` 执行：

- `node --test tests/verification/role-editor-mounted-rejection.test.mjs`：**1 passed**。
- `npm run typecheck`：通过。
- `npx prettier --check tests/verification/role-editor-mounted-rejection.test.mjs`：通过。
- `git diff --check -- tests/verification/role-editor-mounted-rejection.test.mjs`：通过。

## 边界

此测试证明 mounted UI 在合成权威拒绝下保留草稿；不证明 Python Console 的事务/最后管理员保护、浏览器内完整导航/刷新、部署态权限或真实 DB 持久化。它没有运行完整 E2E，也没有调用 Chrome、Edge 或 CDP。因此只能作为 F4.30 的前端自动化证据，不关闭 F4.29/F4.30。
