# F6.4.13 隔离规则编辑器的纯测试 fixtures

## 验收目标

旧规则编辑器样例只服务于规则领域单测与 E2E probe，不属于产品运行数据。将这些输入迁入 `tests/fixtures`，保持测试覆盖与数据形状不变，并确保产品 `src/` 不再包含或导出这份旧编辑器 fixture。

## 风险与测试矩阵

| 风险 | 层级 | 断言 |
| --- | --- | --- |
| 移动 fixture 破坏编辑器状态/校验覆盖 | Logic + probe source | 逻辑 suite 与编辑器 probe 仍使用相同案例，通过现有测试入口覆盖 |
| 测试模块仍依赖产品私有 fixtures | Source scan | 引用统一指向 `tests/fixtures`；`src/` 下不再定义旧 RULE_FIXTURES/RULE_VERSION_FIXTURES/RULE_APP_FIXTURES |
| 将测试输入误当应用 Mock scenario 删除 | Regression | 不改新 Rules HTTP mock 的 app-owned `MOCK_RULE_SCENARIO` 与浏览器 Mock UI |

## 设计与模式评估

- 所有权：领域 fixture 由测试工程维护；产品 mock scenario 继续由 `src/app/api` 持有，数据边界不合并。
- 模式：评估 GoF 23 模式后不采用任何模式。这是测试资源路径调整，无运行时变化维度、对象创建或协作关系，不引入工厂/适配器/策略。
- 不运行 `npm run test:e2e`；当前它启动外部 CDP 浏览器。浏览器可见验证限 Codex IAB。

## 实施与验证记录（2026-10-08）

- 将 `RULE_FIXTURES`、`RULE_VERSION_FIXTURES`、`RULE_APP_FIXTURES` 从产品 `src/features/rules/fixtures` 移至 `tests/fixtures/ruleWorkbenchFixtures.ts`；更新逻辑测试和 E2E probe 的引用，编辑器生产代码不再提供演示账号/应用/规则 seed。新规则 HTTP Mock 继续使用 app-owned `MOCK_RULE_SCENARIO`，没有混入测试编辑器数据。
- **验证：**typecheck、format、lint、架构 **13/13**、logic **247/247**、demo build、`git diff --check` 通过；源扫描未发现旧路径引用。构建继续报告约 **1.19 MB** 初始 JS chunk。
- 没有运行 `npm run test:e2e`，不启动 Chrome、Edge 或 CDP；未连接 Python Console/真实外部服务。移动文件覆盖通过 logic tests 与类型/构建，但浏览器 E2E probe 未运行。

**状态：本子切片完成；F6.4 整项仍未完成。**
