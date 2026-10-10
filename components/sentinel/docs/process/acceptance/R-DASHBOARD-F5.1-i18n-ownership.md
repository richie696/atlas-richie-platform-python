# R-DASHBOARD-F5.1：国际化资源归属与业务数据边界

日期：2026-10-08  
状态：通过（前端资源治理切片）

## 验收范围

- 国际化继续使用集中 JSON 资源和 i18next，不在组件中以内联 TypeScript 对象维护翻译。
- feature namespace 与资源文件有显式、唯一 owner；三种 locale 的 key、值类型、插值参数和复数分支满足资源合同。
- CJK 审计覆盖真正的页面/UI 文案，同时不把服务端 wire 值、mock 场景数据或自由业务文本误判为 UI 翻译缺口。
- 使用 Codex 内置浏览器验证三个 locale 能切换并更新 Overview UI；浏览器只访问本地 demo HTTP Mock。

## 责任边界

`src/app/i18n/catalog.ts` 是 feature namespace 与 JSON 文件的资源 owner 清单。`tests/i18n/catalog.test.mjs` 对资源文件清单、重复/遗漏/越权 key、空或非字符串文案、三语 key 与插值 parity 做校验，并使用真实 i18next 实例验证三语复数呈现。

静态 CJK 审计分为两种确定性不同的区域：

- view 层（`src/app`、共享 UI、feature UI）中的中文确定是 UI 文案；全部继续接受扫描。
- model/state 层的中文需要逐项区分封闭枚举/标签与业务自由文本。
- `src/app/api/` 是 wire contract 和中心化 mock 场景数据的 owner。环境名、规则名称、业务备注或观测自由文本是业务内容，不因 locale 改变而重写，因此仅从“确定是 UI 文案”的 view 扫描中排除。
- feature fixtures 不属于 view 根目录；禁止据此新增宽泛的 fixture 目录豁免。
- 事件 severity/category 等有限领域值先映射到稳定领域 code，再由 presentation 层选取 i18n key；不直接把任意后端文本变成翻译键。

## 验收证据

### 自动化

| 命令                              | 结果                                                                                                                                                                 |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `npm run test:i18n-tools`         | 10/10 通过                                                                                                                                                           |
| `npm run i18n:audit -- --summary` | view/model 命中 0                                                                                                                                                    |
| `npm run i18n:check`              | zh-CN/en-US/ja-JP 各 1,147 个资源键；731 个静态可解析键校验通过                                                                                                      |
| `npm run check`                   | 退出码 0：类型、格式、lint/Hooks、架构 14/14、logic 247/247、HTTP 94/94、契约、browser/visual/i18n/verification 工具、生产/demo build、profile 2/2、Sites 4/4 均通过 |

`i18n:check` 仍报告 115 个动态 `t()` 调用无法静态解析。它们不作为静态全覆盖证据，后续由 F5.2 的显式动态键映射与运行断言收口。

### Codex 内置浏览器

在 `http://127.0.0.1:4189/#/overview?app=all&range=1h` 的 demo HTTP Mock 页面，通过界面语言选择器依次选取简体中文、English 和日本語。三种状态下分别观察到导航、Overview 标题、筛选器、统计卡片和图表操作文案随 UI locale 更新；route 保持 overview。环境值“演示环境”在英文/日文下仍保留原值，符合其作为 API 返回业务数据而非 UI 翻译资源的边界。

只使用 Codex 内置浏览器；没有调用 Chrome、Edge 或 CDP。mock 演示数据不能证明真实 Python API 或生产业务数据翻译效果。

## 已知非阻塞项与未覆盖范围

- `npm run check` 中生产与 demo bundle 有约 1.19 MB 初始 JS chunk 警告，以及依赖 Zod 的 PURE 注释提示；需在 F5.6 分包/容量评估中处理，不改变本次检查通过状态。
- 未穷尽 115 个动态 `t()` 调用、所有插值运行值、Intl 日期/数字时区组合；属于 F5.2。
- 未调用真实 Python Console，不验证后端/第三方任意自由文本的呈现策略。
- 未运行会启动外部 CDP 浏览器的 `npm run test:e2e`。
