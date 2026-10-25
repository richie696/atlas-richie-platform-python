# F6.4.24 Fleet overview Mock 恢复故障计划集中归属

日期：2026-10-09  
状态：切片完成；F6.4 整项仍开放  
范围：app-owned observation scenario、Fleet MSW HTTP projection 与合同测试

## 变更

- 将 fleet recovery 受控故障的目标 application ID、一次性失败读次和错误码放入 `MOCK_OBSERVATION_SCENARIO.readScenarios.fleetFailure`。
- `fleetMockHandlers.ts` 不再自己定义“第一次请求失败”；它按 scenario 的计划计数并注入响应，HTTP 状态由共享 `CONSOLE_ERROR_STATUS` 按错误码映射。
- 保留原有的 forbidden application 场景，不改变 403 语义；恢复场景仍在首个失败后返回成功的空结果。
- 增加架构门禁 `F6.4.24`，验证计划由 app scenario 所有且 handler 不含内嵌恢复阈值/旧 ID 属性。

## 验证

- `npm run test:http:focused -- 'FLEET-(MOCK|MOCK-READ-STATES)'`：**3/3 passed**，覆盖 seed consistency、实际 HTTP adapter 查询及 403/503→恢复。
- `npm run test:architecture`：**18/18 passed**，包含新 F6.4.24 所有权门禁。
- `npm run check:fast`：exit 0，TypeScript、Prettier、ESLint 与 Console OpenAPI 42 paths 一致。

## 边界

这只证明本地 MSW 的 Fleet recovery 计划归属和 HTTP 合同，不代表 Python Console/真实网络的故障恢复。没有运行完整 milestone gate 或浏览器 E2E，也未连接真实数据库或配置中心；F6.4 仍有其他 seed 家族待盘点。
