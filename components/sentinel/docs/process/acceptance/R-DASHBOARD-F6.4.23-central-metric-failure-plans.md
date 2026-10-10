# F6.4.23 实时指标 Mock 故障计划集中归属

日期：2026-10-09  
状态：切片完成；F6.4 整项仍开放  
范围：前端 app-owned Mock scenario、MSW HTTP projection 与契约测试

## 变更

- `mockObservationScenario.ts` 现在是指标恢复/重试故障计划的唯一静态 seed owner：每个计划包含 application ID、一次性失败触发读次和 Console error code。
- `metricsMockHandlers.ts` 不再拥有 `FAILURE_ATTEMPT` 常量；它按 app scenario 执行读计数和一次性错误响应。HTTP status 从共享 `CONSOLE_ERROR_STATUS` 根据错误码映射，不复制数值状态码。
- Realtime HTTP 合同仍使用完整 feature adapter → Console transport → MSW handler → strict response mapper 路径，验证一次性 503 后的下一读恢复有效 QPS 数据。
- 架构测试 `F6.4.23` 保证故障计划位于 app scenario，并阻止恢复/首读阈值重新落回 handler。

## 验证

- `npm run test:http:focused -- 'METRICS-(MOCK|RECOVERY|MONITOR-RECOVERY)'`：**3/3 passed**。
- `npm run test:architecture`：**17/17 passed**，包含新 F6.4.23 seed-owner guard。
- `npm run check:fast`：exit 0，TypeScript、Prettier、ESLint 与 Console OpenAPI 42 paths 一致。

## 边界

这证明 Mock 故障注入事实集中管理，并通过 HTTP 路径按计划表现；它不证明 Python Console、真实网络、Collector 或生产故障恢复。未运行浏览器 E2E、完整 milestone gate、真实数据库或配置中心。F6.4 仍有其他 seed 家族待审，保持未勾。
