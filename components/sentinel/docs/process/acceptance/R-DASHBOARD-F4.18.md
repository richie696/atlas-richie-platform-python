# R-DASHBOARD-F4.18 系统身份 tab 与独立路由复用验收

日期：2026-10-08  
范围：Dashboard 前端页面装配、URL 与本地 demo/MSW；非 Python Console 或生产权限验收。

## 验收结果

- [x] 系统管理内嵌账户/角色视图与独立 accounts/roles 路由复用 Identity feature 公共页面、workflow factory、HTTP Port 与状态转移，不复制表单实现。
- [x] route owner 按认证 session 绑定并负责 workflow 的创建/dispose；不把一条跨路由可变 workflow store 长期挂到 app shell。
- [x] 稳定 URL 区分 `view=accounts|roles` 与 `#/accounts` / `#/roles`，角色目标通过相同 `account` query identity 传递；深链刷新维持目标选择。
- [x] 受保护路由权限使用统一 route/access gate；已有 logic 覆盖 administrator 与 viewer 要求不同。本轮只以 admin 会话验证可访问页面，没有通过 UI 伪造 role、提交角色变更或验证生产撤权。

## 内置浏览器证据

只用 Codex In-app Browser 的 `127.0.0.1:5183` 本地 demo/MSW；未启动或调用 Chrome、Edge、CDP。

1. `#/system?...&view=accounts` 显示 admin/viewer 两个 demo 账号及统一 Accounts 页面内容；顶部“账户维护”入口打开 `#/accounts`，同一列表字段与操作出现。
2. 系统 tab 内 viewer 行“角色绑定”打开 `view=roles&account=account-view` 并选中 viewer；独立 Accounts 页同一动作打开 `#/roles?account=account-view`，仍选中 viewer。
3. 独立角色路由刷新后 URL 与 viewer 选择保留，radio 显示原 view 角色，未修改时保存/放弃操作均禁用。
4. 一次返回系统账户 tab 时发生 demo 读取失败；点击 retry 未恢复。整页 reload 后成功读回两个账号。瞬态原因未知，故不宣称已经修复；完整的多次 route-switch 稳定性需后续继续监控。

## 自动化验证

- `npm run test:logic`：242/242 passed。
- `npm run test:architecture`：13/13 passed。
- typecheck、目标 ESLint/Prettier、i18n check、demo build：通过（与 F4.17 同轮运行）。
- 未运行 `npm run test:e2e`，避免脚本启动外部 Chrome/CDP。

## 未验收

生产 Python API、服务端角色授权/审计、session revoke 行为和数据持久化均未验收。IAB 只显示 demo/mock 数据，不能作为跨服务 E2E 通过的证据。
