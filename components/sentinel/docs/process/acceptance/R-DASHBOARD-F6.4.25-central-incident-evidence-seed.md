# F6.4.25 集中 Incident 证据变化 seed

日期：2026-10-09  
状态：切片完成；F6.4 整项仍开放  
范围：app-owned incident scenario、MSW evidence projection 与所有权测试

## 变更

- 将资源压力证据相邻样本的演示差值 `resourcePressureValueDelta` 放入 `MOCK_INCIDENT_SCENARIO`。
- Incident handler 仍负责从当前事件生成 wire evidence，但变化量由 app scenario 提供，不再是 handler 内嵌 seed。
- HTTP 回归断言证据投影遵守 scenario 指定变化量；架构测试检查 app 所有权并禁止 handler 重新硬编码 `0.03`。

## 验证

- `npm run test:http:focused -- 'INCIDENT-MOCK'`：**3/3 passed**。
- `npm run test:architecture`：**19/19 passed**，包含 F6.4.25 所有权约束。
- `npm run check:fast`：exit **0**，TypeScript、Prettier、ESLint 与 42-path Console OpenAPI 一致性均通过。

首次 `check:fast` 在类型检查阶段发现 scenario 接口漏声明该字段；补齐 `IncidentObservationScenario` 后同一门禁重跑通过。

## 边界

此切片只证明本地 MSW evidence 投影和 scenario 所有权，不证明 Python Console、数据库或真实事件采集。F6.4 仍开放；本轮不运行 milestone 全量门禁或页面 E2E，也不连接真实配置中心。
