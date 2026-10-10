# F6.4.06 故障事件与观测场景身份一致性

## 目标

故障 Mock 事件必须引用应用级 MOCK_OBSERVATION_SCENARIO 中真实存在的环境、应用、实例与进程代次。不能由故障 feature 独立维护一组可能过期的身份 seed，也不能把任意未知环境映射为演示事件。

## 实施

- app/api/mockConsoleHandlers.ts 将中央观测场景显式传给 createIncidentMockHandlers；feature fixture 仍只接收最小只读场景契约，不反向依赖 app/。
- incidentFixturesFor 从传入场景生成应用范围；实例标识、应用归属及 processEpoch 均取自场景。事件 fixture 不再硬编码 app-one/app-two、实例归属或 process-epoch-7。
- 未知环境返回空事件读模型。全局场景按实际应用目录生成 36 条演示事件，分页统计与目录一致。
- 中央实例 seed 显式持有 processEpoch；实例观察与故障事件详情共用该值，避免通过数组下标重复推导。

## 风险与验证

| 风险 | 验证 |
| --- | --- |
| 事件引用不存在的应用/实例，或实例归属错误 | HTTP Mock 测试遍历全部 36 条事件并断言应用、实例及其 processEpoch 均与中央场景匹配 |
| 未知环境被错误显示为真实样例 | HTTP Mock 测试断言未知环境返回 0 项、0 总数、0 影响应用 |
| 既有分页、详情与交互回归 | npm run test:http 92/92、npm run test:logic 247/247 |
| 类型、结构、格式或 demo 产物回归 | npm run typecheck、npm run lint、npm run format:check、npm run test:architecture 13/13、npm run build:demo 均通过 |
| 页面呈现未反映事件身份事实 | Codex 内置浏览器 IAB 实际登录 Mock 并打开故障分析：全范围 36 条、影响 3 个应用；首条详情显示 app-one / instance-1 / incarnation-1，证据区可打开 |

本次只通过 Codex 内置浏览器 IAB 验证；未启动或连接 Chrome、Edge、CDP。未运行自动浏览器 E2E，未连接 Python Console、关系数据库或真实配置中心。Mock 验证不代表生产事件接入或跨服务验收。

## 结果

完成 F6.4 的一个 seed 一致性切片，不勾选完整 F6.4。账号、规则、系统、静态健康/计划/版本等其它 fixture 家族及 F6 后续项仍待推进。
