# Atlas Richie Sentinel Dashboard 交互设计原型

此目录是六页可点击的 **UI/UE 原型**，用于确认视觉基线、信息架构与操作动线。所有应用、规则、指标、连接与事件都是示例数据；它不连接 Python Sentinel、Agent Reporting、指标后端、Nacos 或 Consul，更不会写入规则。

## 页面与操作

| 页面       | 核心价值                                           | 当前可操作部分                                                                                                                                |
| ---------- | -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| 总览       | 一眼看出异常应用、全局 QPS/阻断变化和规则覆盖      | 15 分钟/1 小时曲线切换；跳应用实例                                                                                                            |
| 应用与实例 | 按宿主机定位异常实例，并比较所选容器压力与保护效果 | 筛异常、选实例、切容器/宿主机/进程、跳规则；无样本的层级明确说明                                                                              |
| 规则       | 找到资源、来源和版本，用完整字段理解草稿差异       | 应用/类型/资源过滤；五类 Sentinel 兼容规则专用表单、条件字段、JSON array 预览与本地校验；完整规则集版本、计划生效及指定回退基线；没有发布按钮 |
| 实时监控   | 并排对照 QPS、RT p95、拦截率和资源压力             | 指标/时间过滤、示例光标回放和暂停；不宣称真实推送                                                                                             |
| 故障分析   | 事件时间线与证据、下一步动作相邻                   | 应用/时间/级别过滤，切换事件并跳实例                                                                                                          |
| 系统管理   | 把配置源、采集、权限与协议健康边界说清             | 三分区切换；无凭证配置入口                                                                                                                    |

## 本地运行

在本目录执行 `npm install`、`npm run dev -- --host 127.0.0.1 --port 4173`。浏览器打开 `http://127.0.0.1:4173/`。页面 hash 可直接定位六个导航，如 `#applications` 或 `#rules`。

Dashboard 应用源代码已统一使用 TypeScript：`src/` 仅允许 `.ts` / `.tsx`，并由 `tsconfig.json` 管理编译边界。提交前运行 `npm run typecheck`、`npm run build` 与 `npm run test:sites`；它们只验证类型、原型构建和静态路由，不构成生产联调验收。

代码按正式 React 骨架组织：`src/app/` 负责应用装配、hash 路由与壳层，`src/shared/` 只承载真实跨 feature 复用，`src/features/` 按业务能力纵向组织。每个 feature 内部再分 `model/`（协议常量、领域类型、纯策略）、`state/`（状态机）、`ui/`（页面与私有组件）、`fixtures/`（演示数据，生产代码路径不导入）。路由静态地址、访问前置条件与时间窗口协议值集中在 `app/router/route.constants.ts`；feature 之间只经由 `features/<name>/index.ts` 公共出口互相引用。根 `src/App.tsx` 仅保留 Vite 兼容导出。职责清单见 [React 原型迁移对照](docs/REACT_REFACTOR_MAP.md)。

UI 组件库采用 **Astryx Core + Nivo Line**：两者使用 MIT 许可、React 19+ 兼容、无 PrimeNG Premium 订阅约束。Astryx Core 负责基础控件（Button / Dialog / Form / Table / Tabs / Tooltip），Nivo Line 负责可视化图表；Astryx Charts 的 canary 版本不属于本项目依赖范围。Astryx 仅作为**渲染适配层**——它不拥有 Sentinel 的业务模型、规则表单和页面布局，产品视觉目前由 `src/styles.css` 的全局语义 token 与类名承载（拆分为 `core/styles` + `*.module.scss` 是尚未开始的后续工作）。Astryx 依赖固定版本，升级单独验证。

当前页面的按钮、选择器、文本输入、数字输入、复选框、单选组、卡片、状态徽标和数据表均通过 `src/shared/ui` 的 Astryx 适配器渲染；图表 SVG 与业务表格行保留页面语义组合，不重复实现基础控件。

原型通过公共 npm registry 使用已发布的 React 底座：`@richie696/react-framework@^1.0.1` 与 `@richie696/react-framework-react@^1.0.1`。`ReactFrameworkProvider` 负责注入底座运行时，`useOnlineStatus` 用于展示浏览器在线/离线状态；这两个能力只服务于原型交互，不会连接生产服务。底座还提供了 `Url` / `HttpClient` / `PollingStore` / `TimeSeriesStore` 等能力，供后续接入 Console API 时使用（契约见 [Dashboard 改写方案](docs/REWRITE_PLAN.md)）。

后续 React 工程遵循 `richie696-react-library/docs/REACT_ENGINEERING_STANDARD.md` 索引下的通用 UI/UE、编码与项目骨架规范；底座 API 的具体场景见其 `RICHIE_FOUNDATION_USAGE.md`。本原型的大文件逐页拆分清单单独放在 [React 原型迁移对照](docs/REACT_REFACTOR_MAP.md)。

规则页采用 Sentinel 的五类规则字段作为配置输入兼容格式：`FlowRule`、`DegradeRule`、`SystemRule`、`AuthorityRule`、`ParamFlowRule`。同一规则类型的配置中心内容预览为 JSON array；它不包含额外的 `ruleType` 包装字段。`ParamFlowRule` 的 `classType` / `object` 仍须在真实的跨语言 codec 中按目标 runtime 校验，原型不把它承诺为通用类型系统。

规则工作台提供简体中文、English、日文三种语言。表单使用正式业务名称，例如「资源名称 / Resource name / リソース名」；`resource`、`count` 等标准键只在 JSON 配置内容中保留。语言切换不会改变草稿、版本或配置中心内容。公共导航和示例提示也接入同一语言选择；其余五页的完整文案迁移仍是后续原型工作，不能视为全控制台翻译完成。

版本区展示的是**完整规则集快照**，不是单条规则的独立开关。活动版本必须有明确的开始时间、结束时间、IANA 时区和回退目标版本；控制台原型只展示这套计划模型，不会创建版本、不调度任务、更不会写回配置中心。

正式管理控制台的数据口径、权限和 Nacos/Consul 写回边界见 [Dashboard 控制面设计](../docs/DASHBOARD_CONTROL_PLANE.md)。现有 `sentinel-dashboard` 仍是 per-process 诊断产品，不能把本原型视为其已实现能力。
