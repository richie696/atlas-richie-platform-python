# R-DASHBOARD-F6.2 RuleSet 时间字段映射验收

日期：2026-10-09  
状态：**RuleSet 时间投影切片通过；F6.2 整体保持未完成**

## 修复范围

`features/rules/api/ruleSetMapper.ts` 对 wire DTO 做日期到 epoch 毫秒的映射，之前在存储草稿、版本、发布阶段、实例回执和计划对象上使用 `...value` 展开，令原始 `updatedAt` / `createdAt` / `observedAt` / `appliedAt` / `lastReportAt` / `activateAt` / `deactivateAt` 字段混入 UI 域模型；类型断言掩盖了这类多余属性。本次改为逐字段投影，仅暴露领域模型字段。规则协议枚举 schema 改为直接从已有常量对象创建，删除字符串数组断言；报告、差异和非 completed 操作的 mapper 返回值也不再使用 `as Rule…` 断言。

## 验证

- `npm run test:http:focused -- 'RULE-(SNAPSHOT|COLLECTIONS|RECEIPTS)'`：**3/3 passed**。除映射数值外，明确断言领域对象没有原始 wire 时间键。
- `npm run check:fast`：通过；包括 `tsc --noEmit`、格式检查、ESLint 与 OpenAPI 42 路径一致性检查。
- 2026-10-09 追加跨 feature HTTP adapter sweep：`npm run test:http` **112/112 passed**，覆盖 identity/bootstrap/account/password、metrics/fleet/instance、incident、system/audit/source registry、rule set 与核心 Console transport。首次在普通沙箱执行时，两条需要绑定本机 loopback 的测试因 `EPERM` 未起监听；获得受控本机回环 listener 权限后，同一命令全量通过。测试没有访问外部服务。
- `git diff --check`：通过。

## 边界

RuleSet 时间投影缺陷已修复；跨 feature HTTP 套件通过证明当前 mock/受控 HTTP adapter 的合同测试状态，但不单独证明所有 mapper 的逐字段审阅已完成，也不证明 Python Console 真实服务兼容。真实 Python Console 端到端联调未完成；未运行完整 `check:milestone` 或浏览器 E2E。F6.2 继续未勾选。
