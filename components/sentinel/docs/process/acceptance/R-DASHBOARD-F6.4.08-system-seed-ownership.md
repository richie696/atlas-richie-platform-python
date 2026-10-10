# F6.4.08 系统配置源 seed 归属与 handler 状态隔离

## 目标与实施

- 新增 app-owned `mockSystemScenario`，由应用装配层持有系统 Mock 的配置源身份和审计所需环境/应用/规则发布引用；审计操作者由 identity feature 的 canonical admin seed 注入，不再另写一份账号 ID。
- 系统连接探测的 `sourceId` 与配置源目录由同一 `sourceId` seed 驱动；配置源目录初始记录通过工厂参数注入，不在 feature handler 内重复定义。
- `createSourceRegistrationMockHandlers` 将 registry、操作回执、revision generation 和序号封闭在 handler factory 实例中，并提供局部 `reset()`。系统管理 mock composition 将这些 handlers 与观测 handlers 合并；不再使用模块级共享可变 registry。
- 系统观测 handler 同样成为 factory，接受 app-owned 身份事实和可注入时钟，便于固定时间的协议测试。

## 风险与测试设计

| 风险 | 层级 | 断言 |
| --- | --- | --- |
| 配置源列表与健康探测引用不同 source | HTTP Mock 集成 | 经真实 HTTP adapters 读取目录与连接探测，两者 source ID 完全一致 |
| 审计操作者不在登录身份目录 | HTTP Mock 集成 | 审计 actor ID 从 identity 的 canonical built-in admin seed 注入 |
| Mock 状态泄漏到下一场景/测试 | HTTP Mock 集成 | 写入新源后，factory `reset()` 恢复 seed 并清空 operation lookup |
| 时间依赖本机时钟导致边界抖动 | HTTP Mock 集成 | 注入固定 UTC clock，协议时间和 audit 查询一致 |
| 系统页面连接事实不符 | Codex IAB | 本地 demo/mock 打开系统管理，检查 Nacos 状态表和配置源目录均出现 `nacos-primary` |

## 验证结果

- `npm run typecheck`：通过。
- `npm run test:http`：**93/93**；包括 source/health 身份一致、canonical admin actor、固定时间查询和 reset 语义；受控 loopback transport 测试成功，仅绑定本机临时端口。
- `npm run test:logic`：**247/247**；`npm run test:architecture`：**13/13**；`npm run lint`、`npm run format:check`、`npm run build:demo`：通过。
- Codex 内置浏览器 IAB 的本地 demo 页面实际显示：连接探测中的 `nacos-primary · Nacos` 与下方登记目录中的 `nacos-primary`、`Primary Nacos` 相匹配；没有调用 Chrome、Edge 或 CDP。Demo build 仍有既存约 1.19 MB 初始 JS chunk 告警。

未运行 `test:e2e`（该命令会启动外部 CDP 浏览器）；未调用 Chrome/Edge；未连接 Python Console、数据库或真实 Nacos/Consul。此次只证明前端 Mock 的 seed 归属/隔离和实际页面渲染。

## 结果

完成 F6.4 的系统配置源身份与可变 Mock 状态一个子切片。F6.4 整项仍未完成：系统健康/协议事实的完整 seed、规则计划/版本和编辑器遗留 fixtures、其余 seed 家族与集中目录仍要盘点；本切片不代表完整 seed 集中迁移。
