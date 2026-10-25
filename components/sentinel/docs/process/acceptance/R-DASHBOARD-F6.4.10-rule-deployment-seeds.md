# F6.4.10 规则部署演示 seeds

## 验收目标

将规则 bindings、完整快照及其初始版本/发布/回执/计划的演示事实归属于 app-owned Mock 场景。Rules feature 的 mock handler 从显式输入构造可重置的模拟服务状态，不在 handler 内另造第二份初始业务事实；用户可见接口行为和 wire schema 保持不变。

## 验收矩阵

| 风险                              | 层级           | 断言                                                                                                                 |
| --------------------------------- | -------------- | -------------------------------------------------------------------------------------------------------------------- |
| 规则 seed 与中央应用/环境目录漂移 | HTTP Mock 集成 | 每个 binding 的环境和 app 必须属于注入 scenario；未知或缺失关联不可悄悄生成默认规则                                  |
| app 过滤查询与全量目录分支不一致  | HTTP Mock 集成 | 显式 appId 查询仅返回该 app 的 bindings，且分页回显与请求一致                                                        |
| 同一绑定的快照/版本引用断裂       | HTTP Mock 集成 | binding、snapshot、baseline/event version、publication 的 IDs、checksums、kind、records 一致；作者为 canonical admin |
| 回执引用非中央实例或进程代次      | HTTP Mock 集成 | 回执只出现所选 app 的已登记实例与 epoch；expected/applied/pending 数量正确                                           |
| 计划初始事实时间漂移              | HTTP Mock 集成 | 注入 clock 下计划开始/结束偏移、时区、恢复版本与 schema 验证稳定；reset 重新生成同一相对计划                         |
| seed 注入破坏现有命令路径         | HTTP Mock 集成 | binding 查询、snapshot、版本、发布、回执、计划读取及 create/cancel/draft/publish 幂等测试继续通过                    |
| 用户可见页面不兼容                | Codex IAB      | Rules 页面仍能呈现 bindings、历史版本、发布回执与计划；只读取和切换 UI，不要求真实 source 写入                       |

## 模式与边界

- 模式评估：没有 GoF 模式需要引入。此处是 app 明确注入不可变 demo facts，并由现有 feature-owned mock factory 装配既有状态 Map；增加抽象工厂、Builder、策略或事件只会重复已有边界。
- app scenario 是 demo 数据事实的所有者；Rules handler 仍拥有 mock command 的临时状态、请求校验与 wire 投影。它不是持久化、配置中心适配器或 Console 后端。
- 时间由注入的 clock 提供给 offset 投影；演示数据允许用相对时间表达未来计划，不在静态场景里冻结过期的绝对计划时刻。

## 实施状态

已完成本切片实现与 mock/UI 验证；mock/HTTP/IAB 测试不表述为 Python、数据库或真实配置中心验收。

## 实施与验证记录（2026-10-08）

- app-owned `mockRuleScenario.ts` 统一持有五个 bindings、五类完整快照、基线/活动版本、发布事实、实例回执和初始活动计划。应用/环境/实例/进程代次/配置源/admin 身份引用中央 observation、system、identity scenario；计划时间以注入 clock 加偏移投影，避免冻结过期时刻。
- Rules feature mock factory 接受显式 scenario，负责本地模拟器的临时命令状态、严格请求/响应校验、时间投影和 reset；移除旧的规则部署观察 fixtures。新增显式 `features/rules/mock` 导出，app 装配不依赖 feature 私有 model，也不通过 UI barrel 引入样式。
- 自动验证：完整 `npm run check` 通过，包含 typecheck、format、lint、logic **247/247**、architecture **13/13**、HTTP **93/93**、协议/浏览器工具/视觉/i18n/verification 工具、生产与 demo build、build profiles **2/2**、Sites **4/4**。随后增加 app 过滤目录断言，再次运行完整 HTTP suite **93/93**；其中隔离 loopback transport 只监听本机地址。i18n 工具记录每 locale **1147** keys、**732** 个静态可解析调用，另有 **115** 个动态调用不能由该静态检查证明完整。构建仍有已存在的 Zod PURE 注释提示和约 **1.19 MB** initial JS chunk 告警。
- Codex 内置浏览器仅用干净 IAB demo 会话验证：目录显示 **5** 个 binding；打开 `binding-app-one` 后读取 **1** 条 flow rule、展示 **2** 个不可变版本、`plan-event-flow-01` 待执行；读取 `publication-event-flow-01` 回执显示 **1/2 已生效、1 待加载**，并关联 `instance-1/incarnation-1` 与 `instance-2/incarnation-2`。旧 IAB 标签复用旧 Service Worker 时曾显示目录读取错误；新端口干净 IAB 会话复核通过。未启动 Chrome/Edge/CDP。
- **范围边界：**只完成 F6.4.10 规则部署 demo seeds 子切片，不勾完整 F6.4。未运行 `npm run test:e2e`（会启动外部 CDP 浏览器），未调用 Python Console、MySQL、Nacos、Consul 或真实 Collector；没有配置中心写入或持久化证据。
