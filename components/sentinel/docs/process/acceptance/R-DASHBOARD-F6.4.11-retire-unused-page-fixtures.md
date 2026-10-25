# F6.4.11 移除无消费者的旧页面演示 fixtures

## 目标

移除已被 HTTP Mock 场景替代、且在应用与测试中均没有导入者的旧整页静态演示数据；保留仍承担领域规则逻辑测试与旧编辑器 probe 测试输入的 `RULE_FIXTURES`。

## 变更

- 删除 `features/overview/fixtures/overviewFixtures.ts`、`features/realtime/fixtures/realtimeFixtures.ts`、`features/faults/fixtures/faultsFixtures.ts`、`features/system/fixtures/systemFixtures.ts`。
- 删除前全仓搜索确认这些导出只有定义和注释引用，没有运行时或测试消费者；当前页面请求数据由新 Console HTTP Port 与显式 demo MSW scenario 提供。
- 保留 `features/rules/fixtures/ruleFixtures.ts`：逻辑测试和 RuleWorkbench E2E probe 仍实际引用它，不能作为“看起来像旧数据”而误删。

## 验证与边界

- 完整 `npm run check` 通过：typecheck、format、lint、logic **247/247**、architecture **13/13**、HTTP **93/93**、协议与工具测试、i18n、生产/demo 构建、build-profile **2/2**、Sites **4/4**。
- 浏览器行为没有因未引用文件删除而变更；F6.4.10 已在同一开发轮次用 Codex 内置浏览器验证 binding、snapshot、version、plan 和 receipt。未启动 Chrome、Edge、CDP；未运行 `npm run test:e2e`。
- 此项只清理无消费者的静态 UI fixture，不表示全部 F6.4 完成，也不代表 Python、数据库、真实配置中心或正式浏览器 E2E 验收。
