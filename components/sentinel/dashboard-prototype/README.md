# Atlas Richie Sentinel Dashboard React 前端

此目录是正在工程化的 Sentinel Dashboard 前端：六个主导航页，加初始化、登录、账户、角色、本人改密，共 11 条路由。正式路由已通过 feature-owned Console HTTP adapters 使用统一 transport；本地 demo profile 在 HTTP 边界由 MSW 返回演示数据。OpenAPI 仍为 `draft-partial`，独立 Python Console、真实数据库/配置中心和最终跨层 E2E 尚未完成，因此不要把 demo 内容当生产事实，也不要填写真实数据库或配置中心凭证。完整任务进度以[唯一推进清单](../docs/process/R-DASHBOARD-前后端现状与推进清单.md)为准。

## 页面与操作

| 页面       | 核心价值                                           | 当前可操作部分                                                                                                                                |
| ---------- | -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| 总览       | 一眼看出异常应用、全局 QPS/阻断变化和规则覆盖      | 15 分钟/1 小时曲线切换；跳应用实例                                                                                                            |
| 应用与实例 | 按宿主机定位异常实例，并比较所选容器压力与保护效果 | 筛异常、选实例、切容器/宿主机/进程、跳规则；无样本的层级明确说明                                                                              |
| 规则       | 找到资源、来源和版本，用完整字段理解规则生命周期   | 应用/类型/资源过滤；五类 Sentinel 兼容规则表单与 JSON array 预览；草稿、校验、不可变版本、发布回执和计划/回退工作流。Mock 模式只产生演示状态，不写真实配置中心 |
| 实时监控   | 并排对照 QPS、RT p95、拦截率和资源压力             | 指标/时间过滤、示例光标回放和暂停；不宣称真实推送                                                                                             |
| 故障分析   | 事件时间线与证据、下一步动作相邻                   | 应用/时间/级别过滤，切换事件并跳实例                                                                                                          |
| 系统管理   | 把配置源、采集、权限与协议健康边界说清             | 连接、权限、账户、角色、协议五 tab；demo 响应经 HTTP Mock，生产探测/持久化仍待 Python Console                                                 |

## 本地运行

在本目录执行 `npm install`、`npm run dev -- --host 127.0.0.1 --port 4173`。浏览器打开 `http://127.0.0.1:4173/`。页面 hash 可直接定位六个导航，如 `#applications` 或 `#rules`。

本地 `npm run dev` 使用 demo build profile，在 HTTP 边界由 MSW 提供 Mock；无须配置真实服务。首次引导演示可在 `.env.local` 设置 `VITE_CONSOLE_MOCK_BOOTSTRAP_PROFILE=first-run`，默认 profile 为 `initialized`。需要改回初始演示数据时清除该站点的浏览器数据并重启 dev server。若显式设置 `VITE_CONSOLE_MODE=live`，必须同时设置 `VITE_CONSOLE_API_BASE_URL` 指向受控 Console；live 模式不安装 MSW，缺少配置或启动失败时应用不会发 API 请求。不要在 `.env*`、URL 或日志中放入凭证。

正式 `npm run build` 生成 live-only 生产制品：默认 API 同源，不包含 MSW worker、Mock handler 或演示身份；跨域后端可在构建时设置 `VITE_CONSOLE_API_BASE_URL` 为不带 path/query/凭证的绝对 HTTP(S) origin。`npm run build:demo` 是显式的独立演示制品，输出到 `dist/demo/client`，不会覆盖 Sites 使用的 `dist/client`。未匹配 Console API 在 demo profile 下 fail closed，不会透传真实服务。

部署在 origin 根路径以外时，构建前设置 `SENTINEL_CONSOLE_BASE_PATH`，例如 `SENTINEL_CONSOLE_BASE_PATH=/ops/sentinel/ npm run build`；ASGI 直挂该前缀时，`build_app` 的 `dashboard_base_path` 必须配置为相同值。反向代理也可剥离此前缀并转发到根路径静态路由，但必须把同源 `/api/*` 转发到 Console API，不能回退到 SPA。路径必须以 `/` 开始和结束，不允许点段、query/hash，也不能占用 `/api`。

Node.js 要求为 `^22.18.0 || >=24.11.0`（与 Hooks lint 的开发工具兼容）；锁文件固定依赖，正常安装优先 `npm ci`。

Dashboard 应用源代码已统一使用 TypeScript：`src/` 仅允许 `.ts` / `.tsx`，并由 `tsconfig.json` 管理编译边界。验证分为日常反馈和阶段收口两层，避免每个小改动都重复构建生产包、Demo 包并跑全套辅助门禁：

- 日常改动运行 `npm run check`（等价于 `check:fast`：typecheck、格式、lint、OpenAPI 契约生成物一致性），再只跑受影响的逻辑/HTTP 测试，例如 `npm run test:logic:focused -- 'MONITOR-FILTERS'` 或 `npm run test:http:focused -- 'METRICS-MONITOR-RECOVERY'`；脚本会先校验确有测试标题匹配，避免空跑绿灯。若改动跨 feature，再运行对应完整 `test:logic` / `test:http`。
- 普通 PR/push 只运行 `npm run check:fast`。页面/跨层 milestone 收口时，手动触发 GitHub Actions 并选择 `milestone`，或本地运行 `npm run check:milestone`（等价于 `check:full`），执行完整非浏览器自动化门禁、生产与 Demo 构建、构建隔离和 Sites 测试。它不运行页面 E2E。
- 完整页面 E2E 延至所有计划实现完成后的最终验收，并使用 Codex 内置浏览器逐页面记录路径、状态、可见断言和证据。当前 `npm run test:e2e` 是外部 CDP 浏览器路径，遵循用户约束不运行；不把 DOM/单测结果冒称浏览器 E2E。`npm run verify` 只执行静态快检，不启动外部浏览器。

具体触发条件、扩展验证范围的判断和各层证据边界见[验证节奏](docs/TESTING_CADENCE.md)。

这些前端证据都不是 Python Console、关系数据库或真实配置中心联调验收。

### 可复现验收

`npm run verify` 执行静态快检；它不构建产物、不启动浏览器。里程碑完整静态/自动化门禁使用 `npm run check:milestone`；浏览器 E2E 另按上述约束通过 Codex 内置浏览器完成。

传 `--artifacts <父目录>` 指定证据位置；`--visual-baseline <已有快照目录>` 才会严格比较像素和 DOM，不自动接受差异或覆写基线。没有比较基线时 receipt 明示 `pixelComparison: not-requested`，不能声称像素回归通过。`--static-only` / `--browser-only` 是显式局部验证范围，不算完整验收。已加入独立 Dashboard GitHub workflow，不替换 Python CI；尚未提交或触发远程执行。

Hooks lint 使用官方 recommended，类型由当前 tsc 独立验证（不是类型感知 ESLint）。国际化资源按九个功能文件集中维护，runtime/门禁复用纯所有权与三语 key/插值合同；计数文案使用 i18next 原生复数，而不复制自建国际化运行时。

工程职责按 React 骨架组织：`src/app/` 负责稳定 Provider 装配、lazy hash 路由、异常恢复与私有壳层，`src/shared/` 只承载真实跨 feature 复用，`src/features/` 按业务能力纵向组织。feature 的 `model/` 拥有领域值与纯策略，`api/` 拥有 wire schema、mapper、endpoint 和 HTTP adapter，`application/` / `state/` 拥有用例及资源生命周期，`ui/` 组合页面。feature fixtures 仅用于构造明确的 demo HTTP Mock 或测试，不是生产请求回退。旧 `FixtureGateway`、同步页面与未挂载 HTTP 雏形已从源码退役；演示目录和跨页场景由 `src/app/api/` 的 app-owned Mock scenario 组装，不作为生产 catalog。路由意图/时间窗口的唯一值定义在 `shared/types/navigation.ts`；URL 解析和访问元数据归 `app/router/`。根 `src/App.tsx` 仅保留 Vite 兼容导出。当前职责见 [React 职责地图](docs/REACT_REFACTOR_MAP.md)。

UI 组件库采用 **Astryx Core + Nivo Line**：两者使用 MIT 许可、React 19+ 兼容、无 PrimeNG Premium 订阅约束。Astryx Core 负责基础控件（Button / Dialog / Form / Table / Tabs / Tooltip），Nivo Line 负责可视化图表；Astryx Charts 的 canary 版本不属于本项目依赖范围。Astryx 仅作为**渲染适配层**——它不拥有 Sentinel 的业务模型、规则表单和页面布局。样式单入口为 `src/core/styles/index.scss`，结构 token、暗色语义皮肤、reset、Astryx 适配已分层；壳、shared 与 feature 展示规则归各自的 `*.module.scss`，旧全局样式已退役。共享表单、Dialog、图表、状态反馈与响应式在 F3 完成验收（117 条前端浏览器回归，证据见推进清单 §12）；这不代表页面异步用例、HTTP 或 Python 已完成。Astryx 依赖固定版本，升级单独验证。

当前页面的按钮、选择器、文本输入、数字输入、复选框、单选组、卡片、状态徽标和数据表均通过 `src/shared/ui` 的 Astryx 适配器渲染；图表 SVG 与业务表格行保留页面语义组合，不重复实现基础控件。

前端通过公共 npm registry 使用已发布的 React 底座：`@richie696/react-framework@^1.0.2` 与 `@richie696/react-framework-react@^1.0.2`，锁文件固定解析版本。`ReactFrameworkProvider` 注入底座运行时；`useOnlineStatus` 只说明浏览器在线/离线，不代表配置中心或 Console 健康。读取/命令状态使用明确 owner；统一 HTTP transport 位于应用级 Console 服务，feature adapters 复用底座 `Url` / `HttpClient`，Mock 通过 MSW 拦截同一路径。具体现状与尚缺边界见 [React 职责地图](docs/REACT_REFACTOR_MAP.md) 和唯一推进清单。

后续 React 工程遵循 `richie696-react-library/docs/REACT_ENGINEERING_STANDARD.md` 索引下的通用 UI/UE、编码与项目骨架规范；底座 API 的具体场景见其 `RICHIE_FOUNDATION_USAGE.md`。本原型的大文件逐页拆分清单单独放在 [React 原型迁移对照](docs/REACT_REFACTOR_MAP.md)。

规则页采用 Sentinel 的五类规则字段作为配置输入兼容格式：`FlowRule`、`DegradeRule`、`SystemRule`、`AuthorityRule`、`ParamFlowRule`。同一规则类型的配置中心内容预览为 JSON array；它不包含额外的 `ruleType` 包装字段。`ParamFlowRule` 的 `classType` / `object` 仍须在真实的跨语言 codec 中按目标 runtime 校验，原型不把它承诺为通用类型系统。

Dashboard 文案使用简体中文、English、日文 JSON 资源和 i18next；规则表单使用本地化业务名称，协议字段名只保留在 JSON 配置预览中。语言切换不修改草稿、版本或协议值。三语资源/key 门禁已接入工程检查；全部路由的真实渲染、长文案、交互及格式表现仍按推进清单验收，不能仅凭 key 完整就称视觉国际化全部完成。

版本区展示的是**完整规则集快照**，不是单条规则的独立开关。活动版本必须有明确的开始时间、结束时间、IANA 时区和回退目标版本；控制台原型只展示这套计划模型，不会创建版本、不调度任务、更不会写回配置中心。

正式管理控制台的数据口径、权限和 Nacos/Consul 写回边界见 [Dashboard 控制面设计](../docs/DASHBOARD_CONTROL_PLANE.md)。现有 `sentinel-dashboard` 仍是 per-process 诊断产品，不能把本原型视为其已实现能力。
