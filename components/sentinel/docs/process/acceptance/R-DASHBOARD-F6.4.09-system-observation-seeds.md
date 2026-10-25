# F6.4.09 系统观测 Mock seeds

## 验收目标

将系统管理页健康探测、协议协商与审计事件的静态事实归属到 app-owned demo scenario；feature mock 只做时间投影、筛选、分页、schema 校验与 HTTP 响应。迁移期间保持现有用户可见语义和 wire contract。

## 验收矩阵

| 风险                              | 层级           | 断言                                                                                        |
| --------------------------------- | -------------- | ------------------------------------------------------------------------------------------- |
| seed 搬迁改变健康探测状态/有效期  | HTTP Mock 集成 | 经过 Console HTTP adapter 检查配置源、未配置指标后端、未知 Collector 三种情况及其时间字段   |
| seed 搬迁改变协议兼容事实         | HTTP Mock 集成 | 保持三条独立协议边界、supported/active/compatibility/observedAt 组合                        |
| 审计实体引用漂移或目标仍是幽灵 ID | HTTP Mock 集成 | 发布事件使用中央环境/应用/绑定/发布身份，改密事件 actor 与 target 都使用 canonical admin ID |
| 固定 seed 不适配查询窗            | HTTP Mock 集成 | 固定 clock 下仍正确执行半开时间范围、过滤和分页                                             |
| 用户界面显示意外变化              | Codex IAB      | 重新载入系统连接/协议/审计视图，检查文案与状态布局保持原有含义                              |

## 实施状态

已实现并完成本地验证；不得将 mock/HTTP 测试表述为 Python、数据库或真实配置中心验收。

## 实施与验证记录（2026-10-08）

- **seed 归属：**新增 app-owned `mockSystemScenario`，集中提供 primary Nacos 来源身份、连接/协议观测事实、审计事件关联 ID 与时间偏移。feature mock handler 通过工厂参数接收这些事实，仅负责将相对时间投影为 ISO UTC、过滤/分页、输入 schema 校验及 HTTP response；注入 clock 保留，registry 与 handler 的可变状态没有提升为全局 singleton。审计账号由 identity feature 的 canonical admin seed 注入，密码事件 target 不再使用旧 `admin-1`。
- **HTTP 合同验证：**`tests/http/systemObservation.test.mjs` 检查 source ID 一致、连接状态和时间偏移、规则配置/上报/集群配额三种独立协议事实、半开时间筛选及审计发布关联；发布审计引用中央 app/environment/binding/publication IDs，密码事件 actor/target 均引用 canonical admin。来源 registry reset 测试复用中央 primary source seed。`npm run test:http` **93/93 passed**。
- **Codex 内置浏览器（仅 IAB）：**本地 demo 系统管理页连接表同时显示 `nacos-primary · Nacos` 与 `nacos-primary / Primary Nacos`；协议页分别呈现 `rule-source-v1`、`agent-reporting-v1`、`token-v1` 的 supported/active/compatibility 状态，其中 reporting 的 active version 显示尚无观测；操作审计显示两条 seed 记录，发布与改密 actor 均为 `account-admin`，发布目标为 `app-one`，没有显示密码或规则正文。只做了页面读取与分类切换，没有提交数据。
- **全量工程门禁：**完整 `npm run check` 通过，包括 typecheck、格式、lint、logic **247/247**、architecture **13/13**、HTTP **93/93**、协议合同工具、i18n/build-profile/Sites 工具、production 与 demo build、build profile **2/2**、Sites **4/4**。i18n 检查报告每种 locale 1147 个 key、732 个静态可检查调用，另有 115 个动态调用无法静态解析；这不是动态 key 完整性证明。构建仍报告已有 Zod PURE 注释和约 1.19 MB 初始 chunk 警告。
- **额外修复的门禁漂移：**build-profile 测试曾断言旧 `mock-admin/mock-viewer`，与 F6.4.05 后 demo canonical ID `account-admin/account-view` 不符。已将断言更新为当前身份事实；`npm run test:build-profiles` **2/2 passed**，纳入上述全量门禁。
- **边界：**没有运行 `npm run test:e2e`，没有启动/连接 Chrome、Edge、CDP；按约束仅使用 Codex 内置浏览器。没有启动或请求 Python Console、MySQL、Nacos、Consul 或真实 Collector。该切片只收敛系统观测 mock seeds，不勾选 F6.4 总项，也不代表 Python/live/E2E 验收通过。
