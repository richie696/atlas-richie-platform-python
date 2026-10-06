# React Dashboard UI 库选型

## 结论

Sentinel Dashboard 采用 **Astryx Core + Nivo Line** 作为基础 UI 与图表标准，产品皮肤由本工程的 SCSS 语义 token 负责。Astryx 只提供 Button、Dialog、Form、Table、Tabs、Tooltip 等可访问基础控件，Nivo Line 负责折线、面积、坐标轴、Tooltip、标记线和响应式渲染；它们不拥有 Sentinel 的业务模型、规则表单或页面布局。

Astryx Core 与 Nivo 使用 MIT 许可，适合公开发布的开源 Dashboard；Astryx 当前仍处于 Beta，当前依赖固定为 `@astryxdesign/core@0.6.1`、`@astryxdesign/theme-neutral@0.6.1` 和 `@stylexjs/stylex@0.19.0`，升级必须单独验证。Astryx Charts 目前没有稳定版本，不属于本项目依赖范围。

## 为什么不是把组件库当设计系统

- 页面信息层级、深色运维视觉、状态色、密度和响应式布局由 Sentinel 维护。
- UI 控件通过 CSS variables 消费 `core/styles` 的语义 token，不能在业务页面散落品牌色和尺寸。
- Nivo Line 负责 QPS、RT、拦截率和资源压力图表；统一的 chart adapter 从同一套 token 读取坐标轴、网格、tooltip、面积渐变、标记线和序列颜色，并通过坐标映射支持双指标展示。
- Astryx 组件通过 `shared/ui` 适配器使用，只有出现第二个真实消费者后才提升；单个规则编辑器的组合仍属于 `features/rules/ui`。

## 当前替换边界

页面中的可替换交互控件已经统一经过 Astryx 适配层：

- `ActionButton` → Astryx `Button`
- `Select` → Astryx `Selector`
- `TextField` → Astryx `TextInput`
- `NumberField` → Astryx `NumberInput`
- `CheckboxField` → Astryx `CheckboxInput`
- `RadioGroup` → Astryx `RadioList` / `RadioListItem`
- `Panel` / `NumberCard` → Astryx `Card`
- `Status` → Astryx `Badge`
- `DataTable` → Astryx `Table`

表格内部的业务行、图表 SVG、语义布局容器仍由页面控制；它们不是简单替换控件，保留自有组合可以避免丢失行级交互、跨列布局和诊断语义。

## 候选对比

| 方案 | 许可与生态 | 优点 | 本项目判断 |
| --- | --- | --- | --- |
| Astryx Core | MIT；React 19+；Beta | TypeScript 组件、暗色模式、主题 token、无障碍基础控件和 CSS 覆盖能力 | **基础 UI 首选** |
| Nivo Line | MIT；D3 + React | 折线与面积图视觉控制力强，支持渐变、标记线、响应式 SVG/Canvas、Tooltip 和主题 | **图表首选** |
| Ant Design | MIT；企业后台成熟 | 表格、表单和数据密度体验好 | 可作为替代，但默认视觉与 Sentinel 基线差异较大 |
| Mantine | MIT；现代 Hook API | 开发体验好、组件覆盖广 | 可选，但大型控制台长期规范和生态证据不如 MUI |
| Chakra UI | MIT | API 简洁、可访问性基础好 | 适合轻量产品，复杂数据工作台需补更多组合 |
| Radix UI / shadcn/ui | MIT / MIT 组合 | Headless、自由度高 | 适合自建设计系统，不作为本阶段完整控件库 |

## 引入规则

1. 新页面必须优先使用 `shared/ui` 的 Astryx 适配器；不得在 feature 中直接引入另一套按钮、输入框或选择器实现。
2. 组件库仅作为渲染适配层；业务状态、权限、网络请求、规则校验和国际化仍归 feature 的 model/application/state 层。
3. 引入依赖前锁定版本并核对许可证；不引入 Astryx canary 图表、付费组件或会强制年度授权的组件。
4. 每次迁移必须保持键盘操作、焦点、loading/empty/error/denied 状态、三语文案和当前视觉基线，并通过 typecheck、build 与浏览器核对。
