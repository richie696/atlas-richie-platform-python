# R-DASHBOARD-F2.7 工作流与数据所有权验收

日期：2026-10-08  
范围：Dashboard React 前端 feature/workflow/resource 架构。  
不包含：Python Console、数据库事务/持久化、配置中心写回或完整浏览器 E2E。

## 风险与验证矩阵

| 风险/要求 | 验证方式 | 证据 |
| --- | --- | --- |
| 页面绕过 feature adapter 发 HTTP，或直接导入演示数据 | 实际 `src/features/**/ui` 源码架构门禁 | `npm run test:architecture` 新增 F2.7 ownership 扫描，14/14 通过 |
| 查询/写命令没有 feature owner | 源码职责审查 + workflow/resource 逻辑测试 | feature `application/` 负责读资源、命令编排、权限 owner 与结果观察；ui 只投影订阅快照并发起 use case |
| 确认成功后本地重复持有或伪造服务端状态 | account/rule/source/setup workflow 测试 | 账号成功后清理并重读当前列表/详情；规则命令只失效并回读对应数据；source 更新回读 registry；初始化回执后强制读取 bootstrap 确认 |
| 未知写结果被自动重试或被误报为失败/成功 | 逻辑与 HTTP 工作流测试 | requestKey 对应的显式 inspect；pending/not-found 不解锁重放；畸形回执保留 unknown |
| 视图派生值被复制成第二份业务 state | 对 UI state owner 分类审查 | state 仅用于表单草稿、URL 编辑草稿、临时筛选/选择、Dialog 与展开状态；服务端读快照仍由 query resource 持有，展示值由 render 派生 |

## 实现所有权审查

- 读路径由 feature resource/query owner 持有：fleet、实例、故障、实时监控、规则目录/草稿/发布和系统观测各在对应 feature `application/` 内构造。
- 持久命令与复杂多步转移位于 identity、rules、system 的 feature workflow；可见页面不直接创建 HTTP adapter、不直接调用全局 `fetch`，也不导入 `features/**/fixtures`。
- `tests/architecture/workflow-ownership.test.mjs` 遍历实际 feature UI 源，持续禁止 fixture import、HTTP adapter import/construction 和裸 `fetch()`。它补足原有 route-container/core transport 方向门禁。
- 重要的唯一所有者行为由 `tests/logic/account-workflow.test.mjs`、`rule-draft-workflow.test.mjs`、`rule-deployment-workflow.test.mjs`、`rule-directory.test.mjs`、`source-registration.test.mjs`、`initialization.test.mjs`、`authentication.test.mjs` 与 `password.test.mjs` 覆盖。
- 界面保留短生命周期的交互草稿属于 React state，不把输入框状态强行提升到 durable workflow；事实查询、命令回执、权限 owner 与未知事务仍归 workflow/resource。

## 本次执行证据

- `npm run typecheck`：通过。
- `npx eslint src/features/identity/ui/LoginEntryPage.tsx --max-warnings=0`：通过。
- `npx prettier --check`：本轮变更源文件与验收文档通过。
- `npm run test:logic`：247/247 通过。
- `npm run test:architecture`：14/14 通过，包含新增 F2.7 页面所有权门禁。
- `npm run build` 与 `npm run build:demo`：通过；保留 Zod 注释和约 1.19 MB 初始 JS chunk 的既有告警。
- `git diff --check`：通过。

## 结论与边界

F2.7 前端 feature/workflow/resource 分责与回归门禁已达到清单定义，现可勾选。此结论不表示命令已经进入 Python Console 或持久化；HTTP adapter/MSW 覆盖与真实后端仍分别留在 F6/B0。完整产品浏览器 E2E 也未完成，且本次没有启动 Chrome、Edge 或 CDP；IAB 只用于此前已经记录的局部交互验收。
