# Sentinel Dashboard React 原型迁移对照

本文件把现有演示原型映射到 `richie696-react-library/docs/REACT_ENGINEERING_STANDARD.md`。这是代码拆分顺序与所有权清单，不表示生产 API、配置中心写回或数据采集已经完成。迁移时保留六页路由、示例标识、交互和当前视觉基线。

## 当前文件与目标归属

| 当前内容 | 目标文件/目录 | 拆分后唯一职责 |
| --- | --- | --- |
| `main.tsx` | `app/bootstrap/main.tsx`, `app/providers/FrameworkProviders.tsx` | React 根挂载与稳定 Provider 选项；主题首屏初始化 |
| `App.tsx` 的 `initialPage`、`navigate`、`onNav` | `app/router/` 的路由导航适配 | hash/路径与筛选上下文同步，页面自身不处理全局路由 |
| `App.tsx` 的顶栏、导航、示例横幅、页脚 | `app/shell/DashboardShell.tsx` | 应用壳层；语言、浏览器在线状态与全局导航 |
| `App.tsx` 的 `Status`、`LinkButton`、`Panel`、`NumberCard`、`Select`、`Filters`、`Intro`、`Table` | `shared/ui/` | 业务中性展示；达到第二个 feature 复用后才提升，不必一次性全移 |
| `App.tsx` 的 `Trend` | `shared/ui/charts/TrendChart.tsx` + `chartTheme.ts` | 图表渲染和语义皮肤适配；不生成模拟数据 |
| `App.tsx` 的 `Overview` | `features/overview/ui/OverviewPage.tsx` | 总览组合与钻取；指标转换在 feature model/state |
| `App.tsx` 的 `Usage`、`HostRows`、`Applications` | `features/applications/ui/` | 实例列表、资源压力和选中实例视图 |
| `App.tsx` 的 `SentinelCode`、规则选项、默认集群配置 | `features/rules/model/rule.constants.ts` | 标准协议值、可选项和默认值的唯一来源 |
| `App.tsx` 的 `cloneRule`、`validationErrors` | `features/rules/model/rule.mapper.ts`, `rule.validation.ts` | 纯转换与纯校验；不依赖 React 或翻译组件 |
| `App.tsx` 的 `RuleField`、`RuleInput`、`RuleSelect`、`RuleToggle`、`RuleEditor` | `features/rules/ui/editor/` | 五类规则表单字段与局部交互，显式 props/callback |
| `App.tsx` 的 `VersionPlan`、`Rules` | `features/rules/ui/VersionPlan.tsx`, `RulesPage.tsx` | 版本计划展示、规则工作台组合；真实写回另建 workflow |
| `App.tsx` 的 `Realtime` | `features/realtime/ui/RealtimePage.tsx` | QPS/RT/拦截率/资源压力看板；样本窗口由 feature state 持有 |
| `App.tsx` 的 `Faults` | `features/faults/ui/FaultsPage.tsx` | 事件筛选、时间线和证据展示 |
| `App.tsx` 的 `System` | `features/system/ui/SystemPage.tsx` | 连接、采集、权限和协议诊断视图 |
| `demoData.ts` 的导航/时间范围 | `app/router/route.constants.ts`, `shared/model/time-range.ts` | 稳定 ID 与显示选项，禁止靠导航下标绑定图标 |
| `demoData.ts` 的应用、规则、版本、故障、连接数据 | 对应 `features/*/fixtures/` | 各 feature 的演示数据；生产 gateway 不导入 fixture |
| `demoData.ts` 的趋势生成、格式化 | `features/realtime/fixtures/`、`shared/format/` | 样本生成与纯数值格式化分离 |
| `ruleI18n.ts` 的 shell 文案 | `core/i18n/locales/` | 全局导航/示例/状态的三语文案 |
| `ruleI18n.ts` 的规则文案与字段名称 | `features/rules/i18n/` | 规则业务正式名称、帮助与错误文案 |
| `styles.css` 的根变量/结构值 | `core/styles/themes/_dark.scss`, `tokens/_structure.scss` | 皮肤值与结构值分离 |
| `styles.css` 的 shell/通用组件/六页选择器 | `app/shell/*.module.scss`、`shared/ui/**/*.module.scss`、`features/*/ui/**/*.module.scss` | 局部样式随组件归属；逐页移除全局选择器 |

## 一页的迁移闭环

1. 先抽纯数据、规则和 fixture，保持原型输出不变；不要在迁移过程中接真实 API。
2. 提取页面容器及其私有组件；让 `App` 只留下应用装配与路由出口。跨页面组件要等第二个消费者确定后再进 `shared`。
3. 迁移同页样式到 `*.module.scss`；从全局 CSS 删除已迁移选择器。深色默认皮肤的视觉值迁入 `themes/_dark.scss`，布局值迁入 `tokens/_structure.scss`。
4. 对该页核对导航、筛选、表单/图表状态、三语标签、键盘焦点、窄屏与构建；完成后再迁下一页。

先处理 shell 和规则工作台：它们承载路由/i18n/版本/表单最多，拆开后其它页面可沿用相同边界。之后处理实时监控与应用实例，再处理总览、故障分析和系统管理。若开始连接真实后端，另行建立 `api/*.endpoints.ts`、`*.dto.ts`、`*.gateway.ts`、`application/*`，不得把生产请求塞进现有 fixture 或页面组件。

当前 `useOnlineStatus` 只能说明浏览器报告的网络状态，不能解释配置中心、Agent 或管理服务是否健康。实时数据接入时分别建立 feature 数据源与健康状态，避免把这两种信号混为一谈。
