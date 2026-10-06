# Sentinel Dashboard React 原型职责对照

本文件记录 `dashboard-prototype` **当前实际**的目录职责与后续待办，对照
`richie696-react-library/docs/REACT_ENGINEERING_STANDARD.md`。

它不是迁移计划，也不表示生产 API、配置中心写回或数据采集已经完成。原型仍使用
标注的示例数据。

## 验证方式

重建页面时不得改变展示效果。本工程用 `tests/visual/capture-baseline.mjs` 对 22 个
用例（11 条路由 + 时间窗口 / 单应用与全部应用 / 15m vs 1h 等筛选组合 + 系统管理
5 个 tab + 非法 tab 回落）捕获**归一化 DOM** 与整页 **PNG**，并把两个信号**分开**比较。

```bash
node tests/visual/capture-baseline.mjs capture <outDir>
node tests/visual/capture-baseline.mjs compare <baseDir> <newDir>
ONLY=realtime,faults node tests/visual/capture-baseline.mjs capture <outDir>
ACCEPT_RENDER=faults node tests/visual/capture-baseline.mjs compare <baseDir> <newDir>
```

**为什么必须比 PNG，不能只比 DOM。** 本工程视觉由 `styles.css` 的全局 class 驱动，
DOM 归一化后逐字节相等可以证明「这次改动没动到影响渲染的结构与类名」。但它**证明不了
当前渲染是正确的**——DOM 可以在完全不变的前提下渲染成错的。

真实踩过的坑（2026-10-05 修复）：故障分析页的事件时间线一直是坏的，事件内容被压进
12px 首列逐字换行，而 DOM 比对 16/16 全绿。根因是 Astryx `Button` 会把 children 包在
两层 span 里——外层 `display:contents`，**内层是真实盒子**——于是 `.event` 的
`grid-template-columns: 12px 60px 1fr 15px` 只剩一个 grid item。修复是纯 CSS
（`styles.css` 中 `.event > span > span { display: contents }`），DOM 未变、像素改变。

因此工具现在会单独报告「DOM 等价但渲染不同」，并要求用 `ACCEPT_RENDER` 显式声明才放行。

**渲染比对用容差像素 diff，不用文件摘要。** 跨进程启动的 Chrome 之间存在抗锯齿与字体
栅格化抖动，直接比 sha256 会误报。实测同页两次捕获：

| 量级 | 差异像素 | 占比 | 最大通道差 | 判定 |
| --- | ---: | ---: | ---: | --- |
| 抗锯齿抖动（`realtime-15m`） | 7 | 0.0006% | 32 | 容差内 |
| 抗锯齿抖动（`overview-*`） | 89 | 0.0077% | 44 | 容差内 |
| 真实布局回归（`faults-15m`） | 7849 | 0.68% | 233 | **判为回归** |

默认阈值 `TOLERANCE_RATIO=0.0005`、`TOLERANCE_MAX_DELTA=80`，约为抖动上限的 6 倍与 1.8 倍。
两个条件任一超限即判为回归：只看比例会漏掉「面积小但对比极大」的错位，只看最大通道差
会把抗锯齿误判为回归。PNG 解码在 `tests/visual/png-diff.mjs`，用 Node 内置 `zlib`
自实现，保持零新增依赖。

退出码非 0 即存在差异，`compare` 会打印首个 DOM 差异位置与前后文，以及渲染差异的
像素数、占比、最大通道差和 `bbox` 区域。基线自身须先验证确定性才能用作判据。基线 PNG
也是判据的一部分：**修复布局缺陷后必须重新基线化**，否则下一个人会把坏布局当成基线。

## 当前结构

```text
src/
├── main.tsx                    # 挂载 + Provider 装配
├── App.tsx                     # Vite 入口兼容导出（无实现）
├── ruleI18n.ts                 # 共享三语字典 + 翻译函数
├── styles.css                  # 全局语义 token 与全部选择器
├── app/
│   ├── App.tsx                 # 应用壳组合 + 路由映射
│   ├── applicationScope.ts     # 路由作用域用的应用目录（装配层所有者）
│   ├── providers/AstryxProvider.tsx
│   ├── router/
│   │   ├── route.constants.ts  # 路由 id / 静态地址 / 访问条件 / 时间窗口协议值
│   │   └── navigation.ts       # 主导航图标绑定（按 RouteId，不按下标）
│   └── shell/AppShell.tsx
├── shared/
│   ├── types/dashboard.ts      # 跨 feature 稳定契约 + MetricPoint
│   └── ui/                     # Astryx 适配层（15 个组件）+ charts/TrendChart
└── features/<name>/
    ├── model/                  # 协议常量、领域类型、纯策略
    ├── state/                  # 状态机
    ├── ui/                     # 页面容器 + 私有组件
    ├── fixtures/               # 演示数据，生产代码路径不导入
    └── index.ts                # 公共出口（仅 identity 当前需要）
```

## 已完成的迁移

| 迁移前 | 当前归属 | 说明 |
| --- | --- | --- |
| 路由白名单、导航数组、`NAV_ICONS[index]` | `app/router/route.constants.ts` + `navigation.ts` | 图标按 `RouteId` 显式绑定，缺项/多项编译失败 |
| 时间范围中文字面量（`"最近 15 分钟"`） | `route.constants.ts` 的 `TIME_RANGE` | 协议值 `15m`/`1h`；标签经 `TIME_RANGE_LABEL_KEY` 走语言资源 |
| `app/App.tsx` 里的路由判断与全局筛选 props | `route.constants.ts` 的 `pathFor` / `routeFromPath` / `resolveAppIdForRoute` | 筛选上下文进 URL query，刷新与深链可恢复 |
| `app/App.tsx` 的顶栏、导航、横幅、页脚 | `app/App.tsx` + `AppShell` | 壳层只拥有应用骨架，页面不处理全局路由 |
| `LegacyDashboard.tsx` 的 `Status` / `LinkButton` / `Panel` / `NumberCard` / `Select` / `Filters` / `Intro` / `DataTable` | `shared/ui/` | 只保留有真实跨 feature 消费者的组件 |
| `LegacyDashboard.tsx` 的 `Trend` | `shared/ui/charts/TrendChart.tsx` | Nivo Line 渲染；主题在组件内集中，不生成模拟数据 |
| `LegacyDashboard.tsx` 的 `SentinelCode`、规则选项、集群默认值 | `features/rules/model/ruleKinds.ts` / `ruleOptions.ts` / `ruleDraft.ts` | 协议值唯一来源；标签由语言资源按下标配对 |
| `LegacyDashboard.tsx` 的 `cloneRule`、`validationErrors` | `features/rules/model/rulePolicy.ts` | 纯策略，不依赖 React 与翻译；返回结构化问题而非已翻译字符串 |
| `LegacyDashboard.tsx` 的 520 行 `RuleEditor` | `features/rules/ui/RuleEditor.tsx`（分发器）+ `ui/editors/*`（五类表单）+ `ui/fields/RuleFields.tsx` | 按规则类型拆分，条件字段逻辑内聚 |
| `LegacyDashboard.tsx` 的 `VersionPlan`、规则页 | `features/rules/ui/VersionPlan.tsx` + `RulesPage.tsx` + `state/useRuleWorkbench.ts` | 版本、目录、草稿状态机各有单一所有者 |
| 单文件内的 `Usage` / `HostRows` | `features/applications/ui/InstanceMatrixPanel.tsx` | 折叠状态留在局部，未提升 |
| `SystemPage` 的五个 tab 正文 | `features/system/ui/{Connection,Permissions,Protocol}Panel.tsx` + identity 公共出口 | tab 状态留在页面容器 |
| `IdentityPages.tsx`（五个页面同文件、双份账号 state） | `features/identity/ui/*Page.tsx` + `state/accountStore.ts` | 账号列表单一所有者；跨页订阅同一快照 |
| 全局 `src/demoData.ts`（529 行，跨 feature 共享） | 各 `features/*/fixtures/` | 每个 feature 拥有自己的读模型与采样口径 |

跨 feature 的 demo 造数函数**故意按 feature 各存一份**（`makeTrendSeries` /
`seriesForRange`）。原实现让总览曲线、单实例曲线和实时曲线共用一个全局序列，导致
不同页面的取数口径被绑在一起；接入 Console API 后由各自的 `scope` 决定查询范围。

## 尚未开始的工作

以下条目在方案里已定义，但**当前代码中不存在**，不要按已实现对待：

| 事项 | 目标 | 现状 |
| --- | --- | --- |
| 样式分层 | `core/styles/{index,_reset}.scss`、`themes/_dark.scss`、`tokens/_structure.scss`、组件侧 `*.module.scss` | 全部 2107 行仍在单一 `src/styles.css`，`.scss` 文件数为 0 |
| 图表主题适配器 | 集中读取 CSS token 的 chart adapter | Nivo `theme` 写在 `TrendChart.tsx` 内部，尚未抽成独立 adapter |
| Console API 层 | `features/*/api/{*.endpoints,*.dto,*.mapper,*.gateway}.ts` | 不存在；契约草案见 [Dashboard 改写方案](REWRITE_PLAN.md) §6 |
| 会话与能力 | `core/session/`（`metrics:view` / `rules:write`） | 不存在；`route.constants.ts` 的 `resolveAccessibleRoute` 已预留守卫入口，但当前无会话快照喂给它 |
| i18n 分层 | `core/i18n/locales/`、各 `features/*/i18n/` | 三语字典仍集中在 `ruleI18n.ts`；只有规则工作台、shell 导航、筛选项与少量副标题完成迁移 |
| 门禁 | Hooks lint、feature 契约测试 | 目前只有 `typecheck`、`build`、`test:sites` 与视觉基线比对 |
| 路由分包 | 按 route 的 lazy import | 当前 11 条路由全部打进单一 bundle，构建产物约 1.1 MB |
| 规则页筛选进 URL | 搜索词写入 query | 类型筛选**已完成**（`view=<rule kind>`，7 个用例覆盖）；搜索词是高频自由文本，仍在组件 state。做成可分享需要给 `navigate` 增加 replace 语义（避免每次按键推一条历史），属于 API 变更 |
| **筛选后选中项回落** | 类型筛选排除当前选中规则时，检视器应回落到第一条可见规则，并同步草稿 | 仍是「选中项被过滤掉 → 检视器空态」。深链到 `view=degrade` 时必然命中，因为默认选中项是 `entries[0]`（flow）。既有缺陷，非 URL 化引入；修它需要重构 `useRuleWorkbench` 的草稿生命周期（选中项派生 + 草稿随选中同步），应单独一轮并配视觉验证 |
| 交互态视觉基线 | 勾选「仅看异常」、切 scope、暂停回放、选中事件等交互后的渲染 | 工具只捕获首屏。已手工验证的路径见下，但未固化为门禁 |

## 导航状态：什么进 URL，什么不进

可分享的导航状态进 URL query，由 `app/router/route.constants` 的 `NavigationContext`
统一序列化与解析；不可分享的留在组件本地。已进 URL 的：

| query 键 | 含义 | 所属 feature 校验 |
| --- | --- | --- |
| `app` | 选中的应用 id | 路由边界（`resolveAppIdForRoute` 收敛粒度） |
| `range` | 时间窗口 | 路由边界（`isTimeRange`） |
| `account` | 身份页操作的账号 id | 页面消费时校验 |
| `view` | 路由内子视图（系统管理的 tab） | `features/system` 的 `resolveSystemTab` |

**协议值与展示文案必须分离。** tab 的 `SYSTEM_TAB` 曾用中文标签同时充当状态值与展示
文本，和时间范围曾经的 `"最近 1 小时"` 是同一类错误：改一次文案就让已分享的链接失效。
现在 id（`permissions`）进 URL，标签由 `SYSTEM_TAB_LABEL` 提供。`view` 的合法值集合属于
拥有它的 feature，所以校验放在 feature 侧而不是路由边界——`app/router` 不应该知道某个
页面有几个 tab。

这条改造的直接收益是**补上了验证盲区**：tab 还在组件 state 的时代，视觉基线只捕获得到
默认 tab，其余 4 个 tab 的任何改动都没有自动回归保护。现在 5 个 tab 各有一个用例，
外加一个 `view=bogus` 的回落用例。

未进 URL 的：筛选条上的「只看异常」、实例 scope 切换、事件选中、播放游标 —— 它们是页面
内部的临时选择，不是可分享的观察范围。

## 边界约束

- **图表配色归皮肤所有。** Nivo 的主题只吃具体颜色值——SVG 呈现属性不是 CSS 声明，
  `fill="var(--chart-qps)"` 不会解析。因此 `shared/ui/charts/chartTheme.ts` 负责在运行时
  把 `--chart-*` token 读成真实色值，无 DOM 环境回落到与 token 逐字一致的常量。
  新增序列时：先在 `:root` 登记 token，再传 `primary` / `secondary` / `danger` 语义键，
  **不要在页面里写十六进制**。切主题后需 `resetChartTokenCache()`。

- **Astryx 组件用自己的一套排版刻度锁定纵向度量，皮肤覆盖字号时必须一并接管。**
  通过 `shared/ui/ActionButton` / `Status` 渲染时有两个反复出现的坑：
  1. **children 多包一层盒子**。`Button` 的实际结构是
     `button > span(contents) > span(真实盒子) > …`，依赖「直接子元素」的 CSS
     （`display: grid` + `grid-template-columns`、`>` 子选择器）会失效，因为真正的
     子元素不是 grid item。修法：结构选择器 `.event > span > span { display: contents }`。
  2. **固定 `height` + 固定 `line-height`**。`Button` 有
     `.x1ueg155 { height: var(--size-element-md) }`（32px），`Badge` 有
     `.x1grt7ep { height: var(--spacing-5) }`（20px）配
     `line-height: var(--text-supporting-leading)`（1.6667）。本皮肤独立设定
     `font-size` 与 `padding`，两套刻度不同步时文本行盒装不进被锁定的固定高度。
     实测：徽标 20px 盒装 18.3px 行盒 + 8px padding，需 26.3px，溢出 6.3px 且整体偏下。
     **中文全角字形比拉丁字形更高，错位在中文界面尤其明显。**
     修法：皮肤一旦覆盖某组件的 `font-size` / `padding`，就在同一条规则里
     `height: auto` 并给一个明确的 `line-height`。

  实测结论：普通单类选择器即可压过 Astryx 的 `:not(#\#)` 提权（样式表在
  `astryx.css` 之后加载，同特异度后者胜），**不需要 `!important`，也不需要照抄
  `:not()` 手法**。

  排查手法：dump 目标元素的 class 列表 → 在 `node_modules/@astryxdesign/core/dist/astryx.css`
  里查这些 class 的 `height` / `line-height` / `font-size` → 与皮肤在该元素上设的
  `font-size` / `padding` 做减法，看行盒是否装得下。

  当前受影响并已修的只有两处：故障分析的事件行（Button，双坑叠加）与状态徽标
  （Badge）。按钮类 `.primary-button` / `.secondary-button` 实测 30px 盒、上下留白
  10px / 8px，溢出对称且仅 2px，未修。
- 若开始连接真实后端，另行建立 `api/*.endpoints.ts`（用底座 `Url` + `defineUrlCatalog`
  集中管理端点）、`*.dto.ts`、`*.mapper.ts`、`*.gateway.ts` 与 `application/*`，
  **不得**把生产请求塞进现有 fixture 或页面组件。端点契约见
  [Dashboard 改写方案](REWRITE_PLAN.md) §6。
- 规则发布必须区分「已验证 / 配置中心写入成功 / 回读一致 / N 个实例已加载」四个状态，
  前一个状态不能被 UI 文案合并为后一个。
- TPS 必须由业务事务埋点定义，不得由 HTTP QPS 推算；没有可聚合 histogram 时不画 p95。
- 宿主机 / 容器 / 进程三层指标各自独立；某层未接入时显示「未接入」，不伪造数据。
- 当前 `useOnlineStatus` 只说明浏览器报告的网络状态，不能解释配置中心、Agent 或管理
  服务是否健康。实时数据接入时分别建立 feature 数据源与健康状态。
