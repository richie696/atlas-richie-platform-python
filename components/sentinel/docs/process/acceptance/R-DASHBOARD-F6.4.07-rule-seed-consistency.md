# F6.4.07 规则发布 Mock 与中央身份 seed 一致性

## 目标与实施

- 规则 mock handler 现在通过显式工厂接收中央观测场景和内置管理员 ID；绑定只对该场景中存在的环境/应用可见。
- 规则 fixture 不再引用虚构作者 `demo-admin`、实例 `app-one-process-*` 或 `demo-epoch-*`。版本作者取 `account-admin`，发布回执以应用对应的现有实例和 `processEpoch` 为全集，库存来源使用中央场景值。
- 每次创建 handler 得到独立状态及 reset 操作，不再由 feature 模块级全局状态泄漏测试/演示数据。

## 风险与测试设计

| 风险 | 层级 | 断言 |
| --- | --- | --- |
| 规则绑定引用不存在的环境或应用 | HTTP Mock 集成 | 目录只返回中央场景已登记环境/应用的绑定；未知环境不返回绑定 |
| 版本作者与登录/账号目录脱节 | HTTP Mock 集成 | 基线版本和创建的新版本都使用中央管理员账号 ID |
| 发布回执引用虚构实例/进程代次 | HTTP Mock 集成 | 每条回执 ID、app 归属和 `processEpoch` 与中央实例 seed 一致，expected 等于该应用实例数 |
| 改造破坏规则工作流/状态恢复 | HTTP Mock 集成 | 原规则目录/快照/草稿、版本/发布/计划/重置用例继续通过；每个测试拥有独立可重置 Mock 状态 |
| 页面展示仍不吻合用户路径 | IAB | 本地 Mock 打开规则发布记录，检查作者与回执数；只使用 Codex 内置浏览器 |

## 验证结果

- `npm run test:http`：**92/92**；包括未知环境空目录、基线/新建版本作者 ID、发布回执实例/进程代次/预期数量与 inventory source。
- `npm run typecheck`、`npm run lint`、`npm run format:check`、`npm run test:logic`、`npm run test:architecture` **13/13**、`npm run build:demo` 均通过。Demo bundle 仍有约 1.19 MB 初始 JS chunk 告警，属于当前已知性能债，不是本切片新增错误。
- Codex 内置浏览器 IAB 中，规则页显示 `publication-event-flow-01` 对应 `version-event-flow`；加载回执后显示 **1/2 已生效、1 待加载**，目录来源 `synthetic-inventory`，两行身份分别为 `instance-1 / incarnation-1` 与 `instance-2 / incarnation-2`。

未运行自动 CDP 浏览器 E2E；未连接 Python Console、持久数据库或真实 Nacos/Consul。以上为前端 Mock/渲染验证，不证明生产服务端事件及规则生效链路。

## 结果

完成 F6.4 的一个 seed 一致性切片；完整 F6.4 仍未勾选。规则表单编辑器中的旧纯单测 fixtures，以及系统健康/摘要/计划/版本等其它演示数据仍需后续逐项盘点。
