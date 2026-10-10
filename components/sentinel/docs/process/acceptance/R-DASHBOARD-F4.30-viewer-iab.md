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
- 保存失败保留草稿、并发冲突、会话失效时清理授权 facts 与跨页一致性仍未覆盖。故 F4.30 继续未勾。
- 全程只使用 Codex IAB；没有调用 Chrome、Edge、CDP。
