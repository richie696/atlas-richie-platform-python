# F6.4 全 feature Mock seed 最终审计

日期：2026-10-09  
状态：F6.4 完成；后续 F6.x 与总目标仍开放

## 结论

七个 feature Mock 入口只负责 HTTP 投影和 handler-local 可重置状态。跨页面共享的演示事实由 `src/app/api/mock*Scenario.ts` 唯一持有：

- `MOCK_OBSERVATION_SCENARIO`：环境、应用与实例目录、指标事实/曲线、观测窗口及 Fleet/Realtime 受控读取场景。
- `MOCK_APPLICATION_SCENARIO`：由 observation 与 rule scenario 组合应用实例的规则回执，不复制身份 seed。
- `MOCK_IDENTITY_SCENARIO`：合成用户、角色、登录时间偏移、bootstrap profile 与 mock-only failure/storage controls。
- `MOCK_SYSTEM_SCENARIO`：配置源、连接/协议健康、审计事实与检查能力。
- `MOCK_RULE_SCENARIO`：规则 binding/snapshot、版本、发布、实例回执与计划。
- `MOCK_INCIDENT_SCENARIO`：事件模板、重复事件参数、证据身份/偏移/资源差值和关联规则。
- `MOCK_SCENARIO_NOW_MS`：app mock assembly 为全部适用 handler 注入同一时钟。

Feature fixture 的直接导入由架构测试限制在各 feature 的显式 `mock.ts` 出口；正式业务 UI 不导入 seed。新增的跨页面 HTTP 测试与既有 seed tests 核对共享目录 ID、规则覆盖统计、事件关联实例、登录/账号身份和统一读取时钟。

## 验证

- `npm run test:http`：**103/103 passed**。普通 sandbox 首轮 101/103，唯二失败均为受限 `127.0.0.1` 临时监听的 `EPERM`；在授权本机回环监听后，原命令完整重跑 103/103。未连接外网或真实服务。
- `npm run test:architecture`：**19/19 passed**。
- `npm run check:fast`：exit **0**，含 TypeScript、Prettier、ESLint 与 Console OpenAPI 42 paths 一致性。
- Codex 内置浏览器打开 `http://127.0.0.1:4173/#faults`，确认本地 demo 壳与事件时间线渲染；没有运行全页面 E2E，也没有调用 Chrome、Edge 或 CDP。

## 边界

本验收仅关闭前端 Mock seed 收口。它不证明 Python Console、真实 Reporter/Collector、关系数据库、Nacos/Consul、跨进程行为或生产 E2E。后续 F6.5 起仍按主推进清单执行。完整页面 E2E 只在里程碑验收节点进行，并仅使用 Codex 内置浏览器。

相关子切片：推进清单 §15.147–§15.151、§15.153–§15.155。
