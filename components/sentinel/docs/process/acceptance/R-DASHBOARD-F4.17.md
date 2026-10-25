# R-DASHBOARD-F4.17 会话能力、协议快照与审计查询验收

日期：2026-10-08  
范围：Dashboard 本地 demo HTTP/MSW 与 Codex 内置浏览器（IAB）。不包含 Python Console、真实 peer 协商、生产权限或审计存储验收。

## 验收结果

- [x] 系统管理权限 tab 只读呈现由 app 身份所有者提供的已确认 session snapshot：登录账号、账号标识、当前角色和闭合 capability 列表。它不再是静态权限清单，不增加独立 session store、权限编辑入口或会话凭证暴露。
- [x] 协议 tab 分别列出 rule-source、agent-reporting、token 的后端支持版本、实际协商版本、兼容状态和 UTC 观测时间；未观测到的协议明确显示“尚无观测”，整体部分状态不会被错误显示为全部兼容。
- [x] 审计仍是“系统管理”内现有分类 tab；没有新增顶级菜单。以有界 UTC 半开区间及 actor/action/result 条件读取，明确显示总量与页码；空筛选结果有独立 empty 状态。

## 内置浏览器证据

只用 Codex In-app Browser 访问 `127.0.0.1:5183` demo/MSW；未调用或启动 Chrome、Edge、CDP。

1. `view=permissions` 实际显示 `mock-admin`、管理员角色和 capability 表：查看流量与资源图表、编辑与发布流控规则均已授予。
2. `view=protocol` 显示 `rule-source-v1` 与 `token-v1` 实际协商版本兼容；`agent-reporting-v1` 只有支持版本，协商及观测时间为“尚无观测”；总体呈现部分未确认状态。
3. 协议 tab 初次访问出现系统信息读取失败。显式重试后 AX 树未变化；整页重载后恢复成上述部分协议事实。瞬态根因未确认，不将其描述为已修复。
4. `view=audit` 留在系统管理 tab，默认 UTC 时间窗口读到 2 条 demo 记录；填入不存在的 actor 并应用筛选后，显示 0 条及明确的当前筛选无记录状态。

## 自动化验证

- `npm run typecheck`：通过。
- 目标 ESLint、Prettier 检查：通过。
- `npm run i18n:check`：通过，三语资源对齐。
- `npm run test:logic`：242/242 passed。
- `npm run test:architecture`：13/13 passed。
- `npm run build:demo`：通过；保留既有 Zod PURE 注释警告和首包体积警告（初始 JS 约 1.18 MB）。
- 未运行 `npm run test:e2e`，该脚本会启动外部 Chrome/CDP；本轮没有调用 Chrome 或 Edge。未重跑需要 loopback listener 的 HTTP suite。

## 明确未验收

生产 Console 的版本公告与协商、跨语言兼容、实际连接状态、服务端权限策略/角色撤销、审计数据库持久化/完整性/服务端分页均未验收。本文件仅关闭 F4.17 的前端 demo/UI 切片，不代表最终真实端到端验收完成。
