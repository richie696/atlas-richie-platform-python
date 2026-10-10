# Dashboard 前后端现状与推进清单

> 完成状态：未全部完成。
> 文档性质：过程盘点与执行清单，不是公开协议冻结/发布签字。
> 日期：2026-10-07；源码基线：HEAD `c555b1a` + 当时未提交工作区。
> 盘点阶段范围：核对已发生的重构、逐页盘点、正式前端工程缺口与执行顺序；当时未修改应用源码。后续 F0 已实施，最新证据见 §10；始终未联调真实服务。
> 执行决定：2026-10-07 用户要求先完成前端结构/页面工程化，最后集中抽取 Mock 并在 HTTP 层拦截，真实 Python 后端实现与联调排在最后；追加确认作废 FixtureGateway，新增独立 HTTP 实现，不保留旧网关兼容方案。
> 验证节奏：实现阶段只运行当前改动所需的定向检查；按功能组完成后运行对应模块回归。完整浏览器 E2E 与跨前后端验收只在所有代码实现收口后的最终里程碑执行，不因单个改动重复启动整套流程；不得将定向测试结果表述为端到端验收。
> 清单维护：本文件为本轮唯一执行清单；完成任务须附代码/文档与适用验收证据再打勾。保留历史材料，不自动删除。

## 1. 结论与证据范围

前端已从单文件原型进入 **feature 职责拆分 + 本地交互状态 + 同步 fixture 网关** 阶段；不是空壳拆目录，但也不是已接通后台的正式控制台。

Python `sentinel-dashboard` 当前是 **Starlette/Jinja2 per-process 内嵌诊断服务**，不是 React Console 需要的身份、持久化、规则发布、跨实例观测管理服务。其能力可保留，但不能直接换前端 gateway 就完成产品对接。

盘点阶段实际检查：11 个路由/7 个 feature、页面面板与 Hook/model/store、网关/未提交 provider adapters、初始化/身份与 Console 草案、内嵌服务路由/数据/SSE 与测试源码。下表保留当时的静态结果，不代表 F0 修复后的门禁状态；最新浏览器与工程证据见 §10。没有启动真实 Console，没有访问 Nacos/Consul/数据库，没有运行后端测试。

| 本轮命令                         | 结果                                                                    | 能证明 / 不能证明                                                         |
| -------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `npm run typecheck`（frontend）  | **失败**：nacosAdapter.ts:111，RuleTypeSchema 无 discriminator 属性     | 当前工作区不满足类型门禁；不是网络 SDK 错误                               |
| `npm run i18n:check`（frontend） | **通过**：三语各 519 键，323 静态调用，58 动态调用报告                  | 键检查通过；不证明 fixture 自由文本也翻译或所有页面实际渲染正确           |
| `npm run build`（frontend）      | **通过，有大包警告**：主 JS 1,298.74 kB / gzip 396.84 kB；CSS 222.95 kB | Vite 打包与 Sites 制品生成；build 未串联 tsc，因此不能盖掉 typecheck 失败 |
| `npm run test:sites`（frontend） | **4/4 通过**                                                            | 静态资源/SPA 回退/API 不回退与 Sites 打包；不是页面交互或后端验收         |

本轮之前已有修改：`docs/CONSOLE_API_CONTRACT.md`；未跟踪 `dashboard-prototype/src/core/api/providers/`、`tests/api/`。保留已有工作，纳入“当前工作区”分析，不视作已提交/已验收。F0 只删除 nacosAdapter 中无消费者的两个猜类型 helper，未改厂商适配语义或原有测试。

### 1.1 这轮实际改过什么

以下为 git 历史与当前调用链核对，不将 commit message 中的历史测试结果当成本轮通过。

| 改动                   | 提交/当前证据                                  | 已得到的收益                                                   | 尚未达到的目标                                               |
| ---------------------- | ---------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------ |
| TS 与真实 feature 拆分 | `20234fd`、`a5c362d`、`afd9265`；legacy 已移除 | 七个 feature 下有 model/state/ui/fixtures；不是只套目录        | 仍缺 workflow/API/样式边界及反向依赖收口                     |
| URL 单一状态源         | `183fc08`；useHashRoute                        | app/range/account/view 可刷新恢复；不再双向同步多份 root state | 环境、实例、事件、版本上下文与访问守卫未闭环                 |
| 三语资源与翻译运行时   | `bb6ea67`、`97940e8`；24 个 JSON               | 使用 i18next/react-i18next，旧自制 Translator 不再承担应用翻译 | fixture 自由文本、插值/格式化/长文案渲染仍需验证             |
| 最小角色展示门禁       | `b306c74`、`e52ab78`；core/session             | 部分规则写入口区分 admin/view                                  | 演示默认 admin，不是认证；账户/计划/深链保护不足             |
| 页面读取经过网关       | `30b4505`、`d479932`                           | 数据入口收口，页面不直接 import fixture 文件                   | 页面仍 read*Sync，快照含函数，网络加载/失败没有走通          |
| HTTP 类与注入入口      | `c555b1a`；GatewayProvider/httpGateway         | 有 Context 注入和异步 GET 雏形                                 | Context 绑定 FixtureGateway，HTTP 类不可直接等价替换；未挂载 |
| 视觉工具与交互基线     | `c555b1a`；CDP、DOM/PNG 工具与 E2E 文件        | 具有真实渲染比较工具，优于只比较源码/DOM                       | 本轮未执行浏览器；新增命令/错误/权限状态需扩覆盖             |

因此不能继续沿用“只需换一个 gateway，11 个页面不动就能上线”的旧说明。本轮不是推倒七个 feature，而是补齐它们的职责、状态合同和完整用户路径。

## 2. 前端工程化进度

| 层        | 当前实际实现                                                        | 仍缺什么                                                                                       |
| --------- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| 技术栈    | React 19.2、TS、Vite、Astryx、Nivo；框架包声明 ^1.0.2               | 生产资产交付/运行配置/兼容门禁，不在此轮发布                                                   |
| 职责结构  | app/core/shared/7 features；页面、面板、model、state、fixtures 已拆 | feature api/DTO/mapper/workflow 尚缺；core/api 反向 import features                            |
| 导航      | 11 路由，URL app/range/account/view，系统 tab 与规则类型可恢复      | env/instance/resource/event/version 上下文；真实 bootstrap/session/角色守卫；路由 lazy         |
| 国际化    | i18next/react-i18next + app/i18n 三语八领域 JSON，共 24 文件        | fixture 业务说明/状态自由文本、所有动态插值与 Intl/render 验证；旧文档的 Translator 计划已过期 |
| 组件/图表 | shared UI 封装 Astryx；图表集中 TrendChart/chartTheme               | 质量状态/真实时间坐标、交互态/响应式像素验收                                                   |
| 状态      | 五类页面 Hook；账号 shared store；会话 Context                      | 服务端资源生命周期、取消、过期响应隔离、命令 pending/失败/缓存失效                             |
| API       | 同步 FixtureGateway；HttpConsoleGateway 6 个 GET 方法               | 页面仍消费 read*Sync；Provider 类型要求 FixtureGateway，HTTP 实现不能直接替换                  |
| 权限      | admin/view 演示身份；规则编辑/校验部分入口 useCan                   | 指标读取/账户角色保护、VersionPlan 入口、真实认证；localStorage 不能授予能力                   |
| 样式      | 2197 行 src/styles.css；src 下无 SCSS 文件                          | 语义 token/skin/组件模块分层与第三方覆盖 adapter                                               |
| 门禁      | typecheck/build/sites/i18n/E2E/视觉工具存在                         | 无 lint script（包括 Hooks）；本轮 typecheck 红，未复跑 build/浏览器验收                       |

`tsconfig` 设置 strict=true 但 noImplicitAny=false；不能以 strict 字样宣称所有参数都严格类型化。

### 2.1 “换一个 gateway 页面不动”现在不成立

`GatewayProvider.tsx` 的 `AnyGateway = FixtureGateway`；所有数据页调用 read*Sync，而 HttpConsoleGateway 只有异步 GET。Fixture snapshot 还含 readSeries/seriesForRange 等函数，无法来自 JSON。

HTTP 类仅实现读快照/连接/权限/指标/总览/应用，没有身份、实例、故障、草稿、发布、版本计划的命令；`getRuleSnapshot(): Promise<unknown>` 未提供可消费结构。`#get<T>` 强转响应，queryMetrics 注释说校验字段但源码未实施；参数只传 window/app/resource，缺 instance/scope/metrics。它还把网络、超时与未知错误归为 config_center_unavailable。

现有请求底座已装配，但该 HTTP 类另用 native fetch，未使用底座 Url/HttpClient/error 机制。不能通过存在 Provider 的名字推定生产请求已经复用底座；选定 wire 后应在 feature gateway 正式接入。

## 3. 逐页进度与关联源码

源码路径相对 `dashboard-prototype/src/`；设计中的每页数据与交互见 [页面能力与接口设计](../Dashboard页面能力与接口设计.md)。

| 页面       | 已有展示/本地交互                                        | 实际数据/副作用                              | 主要后端缺口                                  |
| ---------- | -------------------------------------------------------- | -------------------------------------------- | --------------------------------------------- |
| 总览       | 摘要、infra、趋势、应用表/下钻                           | readFleetOverviewSync；range 切片示例        | 全范围聚合、同窗卡片、质量/覆盖               |
| 应用与实例 | 宿主机矩阵、异常筛选、选中、scope/曲线                   | 固定 order 实例集；仅 container 示例         | 每应用目录、各 scope 实测、实例回执           |
| 规则       | 类型/资源筛选、五类表单、local draft/校验/JSON、示例版本 | readRulesSync + useRuleWorkbench，无发布写入 | 绑定、完整 codec、草稿、版本、发布/回滚、计划 |
| 实时监控   | 四类图、指标过滤、游标暂停恢复                           | fixture + 1.2 秒回放，非实时                 | 参数化窗口、质量、聚合、真实订阅              |
| 故障分析   | 统计/级别筛选、Timeline/Evidence/下钻                    | 静态事件，固定日内时间阈值                   | UTC 事件查询、迟到、分页、证据/审计关联       |
| 系统管理   | 五 tab、连接表、权限/协议说明                            | readSystemSync；其余常量                     | health、能力、真实审计、协议兼容状态          |
| 初始化     | DB/admin/source/complete 四步；三认证模式                | 测试连接只提示，finish 跳 login              | 一次性窗口、迁移锁、安全保存与恢复            |
| 登录       | 用户名/密码输入，选择演示角色                            | 任意非空输入可登录；未知用户名 admin         | 认证、Cookie/CSRF、过期/注销/me               |
| 账户维护   | 列表/新增 Dialog/启停/下钻                               | 本地 store，重新 load fixture                | 持久 CRUD、唯一名、最后 admin、授权           |
| 角色绑定   | 账号选择、admin/view radio                               | 只改内存                                     | 保存/冲突、会话失效、审计                     |
| 改密       | current/new/confirm 与本地校验                           | 通过即清空并报 success，没改后台             | 自助 API、旧密码验证、会话策略                |

当前主要入口：`main.tsx`、`app/App.tsx`、`core/api/{GatewayProvider,fixtureGateway,httpGateway,contracts}.ts(x)`；各页面在 `features/<feature>/ui/*Page.tsx`，身份状态在 `features/identity/state/`。

## 4. 当前后端能提供什么

`sentinel-dashboard/src/atlas_richie/sentinel_dashboard/app.py` 注册的源码事实：

| 类别      | 路径                                                                                          | 数据/语义                                                                 |
| --------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| JSON      | /health、/state                                                                               | 本进程 engine state/in-flight 等                                          |
| JSON      | /metrics                                                                                      | 累计 admitted/blocked/succeeded/failed/cancelled/avg_rt_ns                |
| JSON      | /rules、/rules/{rule_id}                                                                      | 当前 repository；default=str 序列化不等于规范 RuleSetSnapshot             |
| Admin     | /admin/rules/reload                                                                           | 从 rule_source.latest() 取缓存快照并 apply，源码没有触发远程 fetch 的调用 |
| Admin     | /admin/breaker/{rule_id}/reset                                                                | 本进程 force_reset，不是规则配置中心修改                                  |
| SSE       | /sse/metrics                                                                                  | 累计快照；ts 用 event-loop monotonic time，不是 UTC 事件时间              |
| 页面/静态 | /、/dashboard、/dashboard/rules、/dashboard/metrics、/dashboard/settings、/dashboard/audit 等 | Jinja2 + 内置 JS/CSS，不是 React dist                                     |

admin 路径采用固定 Bearer token，allow_admin 默认关闭；其他诊断读取不使用 Console 会话。audit 是内存最多 1000 条，不能支持关系库持久账户/规则审计。不存在 `/api/v1/*` Console 路由、账号/初始化数据库、厂商规则发布/计划、跨应用实例目录或指标/事件查询层。

`tests/test_dashboard.py` 确有 JSON/admin/HTML/SSE 内容与多帧测试源码；不能采信 sse.py 旧注释的“仅 endpoint 测试”。本轮未执行这些测试，也不以其存在证明 Console 已完成。

## 5. 已发现问题与后续落点

P0/P1 表示影响，不表示所有协议任务都提前实施。立即的前端正确性问题进入 F0；功能/结构问题进入 F1–F5；wire 冻结与厂商适配收敛进入 F6/B0。按用户最新决定，不以 Python 后端尚未实现为由阻塞页面工程化。

| 优先级 | 差异/问题                           | 证据                                                                                                 | 建议收敛方式                                                        |
| ------ | ----------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| P0     | typecheck 失败                      | nacosAdapter.ts:111 使用已删 discriminator                                                           | 修遗留猜类型死代码，输入类型由 binding/profile 指定                 |
| P0     | 新增账号事件中调用 Hook             | AccountMaintenancePage.tsx:64 调 useConsoleGateway                                                   | 顶层取 gateway，事件只用闭包；补创建交互/Hooks lint                 |
| P0     | 登录/路由是演示安全模型             | 未用 resolveAccessibleRoute；SessionProvider 无真实状态                                              | bootstrap → me → 路由守卫；错误不默认 admin                         |
| P0     | 账号事实跨页会被覆盖                | 三身份页 mount 都 loadAccounts(fixture)                                                              | 按会话/资源生命周期加载，一次服务端命令成功更新统一缓存             |
| P0     | 任意目标改密与本人改密混淆          | accounts 跳 change-password 带目标；页面 fallback 首账号                                             | self 改密不收目标 accountId；admin reset 单独定义                   |
| P0     | 配置正文格式冲突                    | 总体 §4.3 同类 array；Console §2 自定义字段；adapters 包 rules/Rules                                 | profile/codec 与 source addressing 分离，官方兼容字段不改形状       |
| P0     | provider 转换可能丢规则             | adapters extractDraft 只取 raw[0]；toRaw 只一条                                                      | 后台完整 snapshot codec；多条/空/未知字段往返契约                   |
| P0     | 寻址与能力判定错误                  | toAddress 忽略输入 binding，用 resource 造 key/空 namespace；Consul clusterFlow/paramException=false | 地址由明确绑定，存储能力与 runtime 执行能力分离                     |
| P0     | 统一响应未定                        | rewrite ApiResult+records；身份 items+error；HTTP 直接 JSON                                          | 只冻结一套 wire、统一 mapper/错误/分页，不静默容错                  |
| P0     | 发布阶段的失败事实易误报            | Console §3 failure 称停在 read-back-matched                                                          | 回读不一致应表示 written 但未 matched，带 operation ID 查询未知结果 |
| P1     | 路径有三套                          | rewrite session/setup/rulesets；身份 auth/bootstrap；Console rules                                   | 候选沿用身份路径+binding rulesets，记录草案 supersession            |
| P1     | 新建版本和发布混在同 endpoint       | rewrite versions 返回 PublishState                                                                   | 固化版本不发布；publication 用统一用例执行发布/回滚                 |
| P1     | 规则锁 version 与 native token 混称 | Console 单 version 字符串；设计三元 runtime                                                          | 区分 Console ID/baseVersion/nativeRevision/runtime 回执             |
| P1     | metrics 泛型不代表可验证            | HttpGateway direct as T；MetricPoint 仅 time+5 数值                                                  | schema 解析、UTC 时间、指标身份/单位/质量/null                      |
| P1     | 环境/范围仍示例                     | Filters env onChange noop；instance policy 写死 order/container                                      | 后台目录/支持范围，URL 与 cache key 含 env                          |
| P1     | 账户权限与规则写权限冲突            | rewrite accounts 用 rules:write；身份 admin only                                                     | 按角色 admin 管账号，能力保护对应规则/指标                          |
| P1     | KMS/部署-only旧边界过期             | Console §0 禁网页凭证，身份与 UI 支持 direct/none                                                    | 保留三模式一次录入；后台保护，不要求 KMS                            |
| P1     | 历史文档现状过期                    | REACT_REFACTOR_MAP/REWRITE_PLAN 否认已存在会话/i18n/选中回落                                         | 标日期/历史范围并更新当前主管，不沿旧完成表实施                     |

以上是初次盘点的问题快照，不推断所有问题已经运行复现。typecheck、事件 Hook 和多页回灌已在 F0 修复；任意目标改密的产品职责分离仍待 F4，不能因删 fallback 就当作已安全接入。新 provider 代码尚未装配进页面，因此其损坏风险是**未来接入阻断**，不是已经把线上规则写坏。

## 6. 目标结构与文件职责

沿用现有 app/core/shared/features，不另造框架，不按行数机械拆文件。目标是每个用户动作能沿“页面 → command/Hook → 纯规则/工作流 → gateway”查到唯一责任点。

```text
src/
  main.tsx                         # 启动，最终等待 Mock interceptor 就绪后挂载
  app/
    App.tsx                        # 壳、路由、访问态装配，不承载各页业务
    providers/                     # 底座、UI、会话、feature 数据服务装配
    router/                        # 路由表、URL 解析/校验、导航与 guard
    shell/                         # 顶栏、导航、账户菜单、状态横幅、页脚
    i18n/messages/{locale}/*.json   # 保留集中物理布局，按功能命名/拥有资源
  core/
    config/                        # 运行配置的解析/合法性，不存业务表单
    api/                           # HTTP 底座、通用错误/取消/请求追踪
    session/                       # 应用级会话生命周期和能力快照
    styles/                        # 单入口、reset、结构 token、皮肤、厂商适配
  shared/
    ui/                            # 真正跨页复用的 Astryx / Nivo 适配器
    model/                         # 确有跨 feature 消费的稳定值类型/观察语义
  features/<feature>/
    api/                           # 消费者 Port；最终 endpoints/DTO/schema/gateway
    model/                         # 领域事实、枚举/常量、纯校验和投影
    application/                   # 确实复杂的用例编排；简单流程不强造此层
    state/                         # 资源/命令生命周期、局部 store、React Hook
    ui/                            # 页面组合、私有面板、*.module.scss
    index.ts                       # 有外部消费者时才设公开入口
  mocks/                           # F6 才集中迁入；seed/handlers/scenarios/mock state
```

这些是责任落点，不要求每个 feature 都生成所有空目录。业务 wire/fixture 不留在通用 core；app 可以汇总 feature 服务，但 core 不反向 import feature/shared。底层共享组件不得依赖 app 路由或应用目录。feature 之间仅通过所需公开合同协作。

| 当前位置/问题                              | 重构落点                                              | 验收                                                                         |
| ------------------------------------------ | ----------------------------------------------------- | ---------------------------------------------------------------------------- |
| app/App 顶栏/导航/横幅与路由 switch        | shell 私有组件 + router 装配                          | App 不包含各页领域流程；保留既定顶栏视觉，不借技能改成新布局                 |
| core/api 业务 DTO/FixtureGateway/Providers | feature api；app 装配；F6 mocks；FixtureGateway 删除  | core 不 import features；Provider 不依赖旧类型，旧网关不移到测试目录继续保留 |
| shared/types + Filters import app          | 稳定跨页观察值与展示 props；路由 glue 归 app          | shared 不 import app；不复制两份路由/时间常量                                |
| model import UI 图表颜色/路由窗口          | model 保留指标身份，UI 做颜色投影；窗口值有稳定所有者 | model 无 UI/路由实现依赖                                                     |
| 账号 load/store 多页装载                   | identity 数据状态所有者 + 会话生命周期                | 切页不覆盖成功命令；退出/换会话不串数据                                      |
| 规则草稿 kind 与 draft 分离                | rules 判别联合、校验、草稿 workflow                   | 错误类型组合不能靠 as 强行通过                                               |
| styles.css 全局控制输入/按钮               | core styles + Astryx adapter +组件 module             | reset 不穿透所有控件；hint 长短不改变同排控件基线                            |
| 同步 fixture 的函数型快照                  | 过渡数据层；F6 JSON seed/HTTP handler                 | 最终响应可序列化；业务代码无 fixture/mock 分支                               |

底座 API 按安装版本 1.0.2 核对：HTTP 用 Url/HttpClient；单次资源优先 ObservableResource；定时刷新评估 PollingStore；有界窗口评估 TimeSeriesStore；订阅 Hook 只绑定生命周期。普通表单继续用本地 state，不为覆盖底座 API 引入 EventBus/锁/基类；新复杂服务抽象实施前按 OOP/FP 门禁确认责任与复用方案。

## 7. 执行清单（唯一当前顺序）

旧 D1–D4 编排被本节替代：没有取消后台、协议或验收任务，只把它们按 2026-10-07 用户要求分解并后移。D1 协议任务转入 F6/B0；D2 转入 F0–F6；D3 转入 B0；D4 转入 F7/B0。任务数不代表产品完成百分比，也不代表估时。

当前统计 **98 项：69 项已完成（D0 5 + F0 5 + F1 8 + F2 7 + F3 8 + F4 21 + F5 2 + F6 11 + F7 1 + B0.6 1），24 项前端待完成、5 项后置后台工作待完成**。每页三项是完整用户路径切片，不是三个按钮；任务细化后保留原 ID 并记录子项，不能用任务数估开发比例。

| 阶段 | 范围                                         | 本次待完成数 |
| ---- | -------------------------------------------- | ------------ |
| F0   | 当前正确性/类型阻断（5 项完成）              | 0            |
| F1   | 骨架/依赖/职责（8 项完成）                   | 0            |
| F2   | 状态/资源/用例边界（7 项完成）               | 0            |
| F3   | 皮肤/组件/布局（8 项完成，证据 §12）         | 0            |
| F4   | 11 页完整功能（含系统五 tab，21 项完成）     | 12           |
| F5   | 三语/质量/工程门禁（2 项完成）              | 5            |
| F6   | 协议反推/集中 Mock/全新 HTTP 实现/旧网关退役 | 1            |
| F7   | 前端验收/交接                                | 6            |
| B0   | Python 实现/真联调/制品交付，最后执行        | 5            |

此表随 2026-10-08 F4.05 scope 隔离交付更新；进度以 checkbox 和每项证据为准。

### D0：现状与需求反推

- [x] 按当前源码盘点 11 路由、页面交互、model/state/gateway 与后端接口。
- [x] 区分工程拆分、本地演示、网络实现和真实联调；核实类型/i18n门禁。
- [x] 抽取逐页功能/数据/接口候选，产出 [页面设计](../Dashboard页面能力与接口设计.md)。
- [x] 标出 Console/身份/改写方案间的冲突及前端现状缺陷；未自动修代码。
- [x] 核对重构提交、运行门禁，按正式前端规范展开结构/逐页/HTTP Mock/后台后置清单（2026-10-07，本文件）。

### F0：先修当前阻断（5 项）

- [x] **F0.1** 删除无消费者的 schemaTag/ruleTypeOf；CanonicalRule.ruleType 仍是输入，未补伪 discriminator；typecheck 通过。证据见 §10。
- [x] **F0.2** 新增账号事件使用顶层取得的 gateway；浏览器完成打开 Dialog、创建并确认列表可见。
- [x] **F0.3** App 唯一调用临时演示 bootstrap；AccountStore 按 gateway 身份幂等初始化，load 保留显式刷新含义；新增/改角色/启停后导航不回灌 fixture。真实会话隔离与刷新持久化仍待 F2/F6/B0。
- [x] **F0.4** 空回放不启计时器或取模零，空/有样本切换可恢复并清理；空应用显示空态，未知应用/账号/实例不回落其他对象；角色目标由 URL 拥有，系统 roles tab 保留上下文。
- [x] **F0.5** 新增 Hooks lint 和门禁负例，修复总览辅助函数 Hook、实时 useMemo 依赖、规则 Effect 闭包；npm run check 通过；保留 CSS/Sites 保护文件与修改前后截图。

### F1：正式工程骨架与依赖方向（8 项）

- [x] **F1.1** 提取 AppProviders/启动边界与稳定依赖装配；main 只启动/挂载，Provider 不在 render 重建服务。StrictMode 身份稳定浏览器回归通过，证据 §11。
- [x] **F1.2** 完成 AppShell、Header/Navigation/UserMenu/StatusBanner/Footer 私有职责；不把 shell 业务再塞进 shared 万能组件。保持既定视觉；真实账号菜单另属 F4.23。
- [x] **F1.3** 路由分包、Suspense 与 ErrorBoundary；覆盖未知路由、加载失败/重试和页面异常，不让一个页拖垮全站。加载器失败/重试与显式 reload 经浏览器验证；生产网络 chunk 故障另属 F7，未以加载器替身冒充。
- [x] **F1.4** core/api 去业务反向依赖；feature 定义最小异步读/写 Port，app 汇总/注入；Provider 面向 Port，不再以 FixtureGateway/其别名作为合同，不新增同步兼容 shim。旧 Provider 与同步消费者已随 F6.3/F6.12 联合验收退役；feature UI 不直接依赖底层 HTTP transport。证据 §15.26。
- [x] **F1.5** shared 去 app 依赖；整理 NavigationIntent/观察窗口/应用选项所有者，展示组件从 props 接收选项/command。完整源依赖图无 shared→app 或 feature→app，数值/图表投影与别名逻辑回归通过。
- [x] **F1.6** model 去 UI/路由实现依赖；纯策略/mapper 与 UI VM/图表 token 各有落点；wire/表单/model 类型不混用。规则编辑草稿、校验、物化及编辑会话迁到 feature `editor/`，HTTP/部署事实改由领域 `validRuleValue` 校验；实例状态文案由 presentation 根据指标映射 i18n，图表颜色语义放在 `shared/types`。AST 架构门禁阻止 model→editor/form、API wire→form 与 presentation→chart UI token；逻辑验证领域规则事实和草稿分别通过。证据 §15.27。
- [x] **F1.7** 增加必要 feature 公共出口和依赖检查，禁止跨 feature 深路径、core→feature、shared→app；JSDoc 说明稳定 API 的输入/失败/生命周期，删除失实历史注释。应用只通过 identity/system feature 入口装配登录、初始化、系统 tab 与显式 mock handlers；AST 源码图新增 app→feature 深路径门禁，稳定 setup/login/mock 入口注明输入、失败确认与 owner 生命周期；清理 HTTP 迁移、旧 demo 与旧 SCSS 状态等过期注释。证据 §15.28。
- [x] **F1.8** 收紧 noImplicitAny，落地格式/类型/lint 命令与路径别名约定；只升级确有理由的依赖，不借重构更换 React/Astryx/Nivo。strict 源码及 TS 浏览器探针、格式/Hooks/依赖/逻辑门禁均通过，React/Astryx/Nivo 版本未变。

### F2：资源、状态与用例边界（7 项）

- [x] **F2.1** feature 资源生命周期统一语义：idle/loading/refreshing/ready/empty/filtered-empty/denied/error/stale/partial；不用万能布尔组合产生非法状态。`QuerySnapshot` 用互斥判别联合表达生命周期；`QueryResource` 统一拥有超时、取消、同 key stale、换 key 隔离、权限撤销清除与资源释放，empty/filtered-empty/partial 由 feature 显式分类。查询 UI 对状态穷尽映射；身份/初始化等写工作流保留各自命令状态，不混入查询状态。证据 §15.12。
- [x] **F2.2** 读资源可取消/防过期响应；切 env/app/instance/range 的 key 完整，StrictMode/卸载/换会话清理正确；刷新保留可信旧数据并标 stale。跨会话 owner 回归及全量浏览器 E2E 证据见 §15.29；Codex 内置浏览器另检查了 Overview 与实时监控实际渲染状态。
- [x] **F2.3** 写命令 pending/success/error/conflict/结果未知；防重复点击、保留可修正表单、取消与重试显式；不默认重放发布/初始化/改密。基础生命周期逻辑和已装配的账户/改密/初始化/规则发布/来源登记页面浏览器用例见 §15.30；HTTP E2E 仍使用 MSW，不代表 Python 联调。
- [x] **F2.4** bootstrap/session 状态单一所有者；模型区分初始化未知/未完成/完成、未登录/认证中/已登录/过期；禁止坏存储默认 admin。当前工作流已统一为 app-scoped AuthenticationWorkflow；setup gate / initialization 只消费该 owner 的 projection；逻辑/HTTP/架构门禁与内置浏览器已初始化路由验证见 §15.32。首次未初始化 UI 仍未在当前内置浏览器会话直接呈现，全量浏览器 E2E 未跑。
- [x] **F2.5** URL 与临时交互分工；完善 env/instance/resource/event/version/规则类型上下文，replace/push/back 行为及未知目标校验，秘密不进 URL。规则类型由 Rules feature 将 `view` 解析为受控 Sentinel 类型并纳入 binding query；内置浏览器深链、筛选、刷新和返回证据见 §15.33。
- [x] **F2.6** admin/view 的导航、深链、区域和 command 门禁对齐；view 仅查看，无规则/账号/角色编辑；UI 不冒充服务端授权，不扩大 RBAC。路由访问级别与导航过滤共用 route metadata；查看者不显示系统管理，头像入口导向本人改密，命令仍由各自 workflow/服务端授权合同保护。逻辑 **232/232**、架构 **13/13**、typecheck/lint/format、production/demo build 通过；内置浏览器核验当前管理员规则页面渲染，查看者导航/头像路由与深链拒绝由纯逻辑和 workflow 正反例覆盖。见 §15.34；未运行 Chrome/Edge，不将 mock 权限当真实服务端授权。
- [x] **F2.7** 按真实复杂度提取 workflow/纯转移；派生值不复制进 state，成功命令经唯一数据所有者更新/失效；未迁页面暂用旧路径保持可运行，但 FixtureGateway 冻结、不加新方法；新能力用内部 async Port/测试替身，不把 fixture 散落回 UI。源码审查确认读/写 owner 位于 feature application/resource，UI 仅保留短生命周期交互草稿；新增架构门禁禁止页面直接 fetch、导入 HTTP adapter 或 fixtures。逻辑 247/247、架构 14/14、typecheck 和 live/demo build 通过。详见 [F2.7 验收](acceptance/R-DASHBOARD-F2.7-workflow-ownership.md)。

### F3：皮肤、组件和交互布局（8 项）

- [x] **F3.1** 建 core/styles 单 SCSS 入口：reset、结构/语义 token、选定暗色皮肤及主题扩展接口；保留当前视觉，不在本轮强加新皮肤/侧栏。静态门禁、90 条前端浏览器回归及修复后 29 态像素比较通过，证据 §12。
- [x] **F3.2** styles.css 按 shell/shared/feature 逐路径迁 module.scss；清除完成迁移区域的旧规则，不保留两套竞争 CSS。21 个局部模块、legacy 退役门禁、29 态像素一致、91 条前端浏览器回归通过；证据 §12.3。
- [x] **F3.3** Astryx 必要覆盖集中在中央 adapter，移除搜索框内层 input 与废弃 native select 覆盖，Radio 使用公开 slot；新增门禁及完整 94 条浏览器回归通过，证据 §12.4。
- [x] **F3.4** 统一 Text/Number/Select/Checkbox/Radio 字段布局；真实五类规则、集群、账号与初始化，以及三语长帮助/错误/窄容器、数值清空/分数/失焦/ARIA 均验证；94/94 回归，截图证据 §12.4。
- [x] **F3.5** DialogFrame 的尺寸/header/body/footer/滚动/焦点统一；320/360/768/1280、长日文、Tab/Shift+Tab、Enter/Escape、提交中关闭及嵌套 Selector 验证通过；9 条聚焦浏览器回归，证据 §12.5。
- [x] **F3.6** Nivo 皮肤、原始单位 tooltip、真实时间间距、窗口内显式事件、缺测/空/单点及可访问摘要统一；6 条图表 E2E 与完整 117 条回归通过，证据 §12.6。真实采集与业务发布事件仍属 F4/B0。
- [x] **F3.7** 壳/筛选/表格/矩阵/编辑器响应式收口；33 路由视口组合、宽屏导航、键盘横滚与 sticky 焦点通过；200% 等效 CSS viewport + DPR2 而非 OS 浏览器 zoom 实测，证据 §12.7。
- [x] **F3.8** QueryView/CommandFeedback/FeedbackPanel 区分空、拒绝、旧可信值、错误与命令未知结果；角色/焦点/对比度/减动画/目标浏览器断言通过，完整 117 条回归，证据 §12.8。ARIA 语义验证不冒称 NVDA/VoiceOver 人工验收。

### F4：逐页完成完整功能（11 页，各 3 项；参照正式页面设计对应章节）

每页必须有“读状态 + 用户命令 + 失败/恢复”闭环；以下先实现内部模型、纯规则、工作流与可注入资源合同，用测试替身验证。最终 HTTP wire 与集中 Mock 在 F6 实施，不假称已保存到配置中心或数据库。

#### 总览（设计 §2）

- [x] **F4.01** 总览容器只组装摘要/infra/趋势/应用列表，过滤和投影由 feature 管理；总应用数/告警数/列表不互相矛盾。Fleet 容器以单一 `FleetSnapshot` 组装四个区域，search/paging 只投影目录行；全范围已登记/需关注计数不随目录过滤变化。纯逻辑、Console HTTP/MSW 与内置浏览器分别验证了页码、命中、无匹配及全局计数；见 §15.35。指标是否来自真实生产采集仍属 F4.02/B0，不由本项替代。
- [x] **F4.02** 同一 env/app/window 的卡片与图表联动，质量/新鲜度/覆盖率显式；QPS/TPS/RT/CPU/内存按 scope 口径展示，缺测非零。Fleet 摘要/曲线共享一个 MetricBundle；应用目录行绑定自己的 `appId/application` 指标，不复制 fleet aggregate。单应用 HTTP 返回的 summary/series/行指标同 scope 与窗口；界面实测 QPS 卡片/曲线/应用行同步为 84 req/s，TPS 明确未接入，quality/coverage/asOf 可见。证据 §15.36。示例采集源不是生产 Agent 数据，真实聚合与采集口径仍待 B0。
- [x] **F4.03** 应用/异常/规则覆盖下钻携带上下文；支持 loading/空/partial/权限/刷新失败与重试。总览到实例/故障/规则均保留 env/app/window；IAB 实际验证 loading、ready/empty/partial、403 denied 不出现重试入口、503 error 显示“重试读取”，显式重试后恢复到合法 empty 态。mock-only 失败目标隔离在演示 HTTP handler，production build 不携带 handlers。见 §15.37、§15.41 与 [R-DASHBOARD-F4.03](acceptance/R-DASHBOARD-F4.03.md)。

#### 应用与实例（设计 §3）

- [x] **F4.04** 应用目录与实例目录分离；按 app/env 分组过滤，去 order-service/order-5 硬编码，无数据应用不显示别家矩阵。路由 allow-list 改为与当前目录一致的通用身份，退役旧静态应用/实例 fixture 和按应用名判定样例数据的策略；空选择不自动落到固定实例。Codex 内置浏览器验证 app-one 两行只属本 app、app-three 明确空态、无效 env 只显示环境选择器；环境切换纯逻辑测试覆盖保留目标环境中仍存在的同 app ID、并清除目标环境缺失的 app。逻辑 237/237、HTTP 80/80、架构 13/13、typecheck/lint/format/i18n 通过。详见 §15.38 与 [F4.04 验收记录](acceptance/R-DASHBOARD-F4.04.md)。演示目录目前仅有一个有效环境，第二个有数据环境的浏览器切换仍未覆盖；不代表真实 inventory 已接入。
- [x] **F4.05** 所选实例与 scope 的能力/趋势/版本回执联动；无 host/process/container 样本显示不可用，不借另一 scope 的数。曾发现旧 fixture 把进程指标声明为容器也可用，新增逻辑回归先复现失败后修正为仅进程层可用；Host/Container `metrics=null`，详情展示明确 unavailable，规则回执绑定所选 process epoch。内置浏览器验证显式选择、process 指标+回执、host/container 无借数以及返回 process 后恢复；逻辑 238/238、HTTP 80/80、typecheck/lint/format、production/demo build 通过。详见 [F4.05 验收记录](acceptance/R-DASHBOARD-F4.05.md)。证据仍是 MSW 合成实例，不证明生产 Agent 已声明或上报这些 scope。
- [x] **F4.06** 异常筛选/选择/实例消失/非法深链的状态转移与详情空态；去规则/故障/实时页保留 instance/window。修复路由 merge 只覆盖不清除字段的问题：显式清除实例选择时同时写入 `instanceId: undefined` / `metricScope: undefined`，更换环境/应用/时间窗时也删除旧目标。逻辑覆盖筛选后显式选择不漂移与清除后 query 参数消失；HTTP/MSW 覆盖实例 404、旧 process epoch 410→409；内置浏览器验证筛选目录仍保留原实例详情、非法深链明确空态/清除、去 Rules/Realtime/Faults 携带实例及精确窗口。见 §15.40 与验收记录 [R-DASHBOARD-F4.06](acceptance/R-DASHBOARD-F4.06.md)。

#### 规则（设计 §4）

- [x] **F4.07** 五类型表单用类型相关的草稿联合、条件字段与完整纯校验；有限数/枚举/整数/比率/窗口/参数例外/系统禁用值边界及字段级错误。整组工作台的实际控件、blur 校验失效、空集、保留其它记录与字段错误均通过浏览器；正式 App/HTTP 与厂商转换分别仍属 F4.08/F6/B0，不以此 checkbox 代替。
- [x] **F4.08** 完整规则集编辑：新建/修改/删除、草稿保存/放弃、未保存导航保护、JSON/差异/验证、来源 binding/profile；不以单条 preview 替代整组快照。Codex 内置浏览器完成人工路径：显式绑定/profile、整组快照编辑、加/删记录、整组 JSON 预览、保存修订、候选校验/差异、脏状态导航保护（取消保留输入）、放弃本地内容和删除本轮 mock 草稿。逻辑 **8/8**、规则 HTTP **6/6**、typecheck/format/lint/contract/i18n 通过；见 §15.42 与 [R-DASHBOARD-F4.08](acceptance/R-DASHBOARD-F4.08.md)。仅证明前端与 demo mock 路径，不证明 Python 持久化或配置中心写入。本轮另补充规则 binding 快照深链的取消/迟到响应隔离逻辑证明，详见 §15.229；真实页面切换与重试仍留到最终 E2E。
- [x] **F4.09** 版本/发布/回滚/活动计划前端路径完成：不可变版本、明确目标/恢复版本、UTC 与 IANA 时区、重叠拦截、取消与重新创建计划；发布与历史版本新发布可见，实例部分回执清楚区分待加载/待重启，且不把规则校验失败文案复用于回执。Codex 内置浏览器验证真实 React 页面与 demo HTTP 路径；部署逻辑 **19/19**、规则 mock HTTP **2/2**、架构 **13/13**、typecheck/format/lint/contract/i18n 通过。见 §15.43 与 [R-DASHBOARD-F4.09](acceptance/R-DASHBOARD-F4.09.md)。全量 CDP `test:e2e`（会启动 Chrome）未运行；结果未知由逻辑/HTTP 契约测试覆盖、未宣称已完成真实后端/运行时回滚验收。

#### 实时监控（设计 §5）

- [x] **F4.10** 正式实时监控路由拆分目录/查询装配、轮询 owner、状态条与同窗指标/图表；滚动/固定 UTC 窗口明确、暂停仅停浏览器读取、恢复立即重查；查询与样本点有界（每序列最多 1000 点），不以空序列造零或用 frame 回放。Codex 内置浏览器验证摘要/图表、TPS 缺测、暂停 6 秒窗口不变和恢复后最新窗口；完整 `npm run check` 通过（逻辑 239、HTTP 83、架构 13、typecheck/lint/format/contract/i18n/build/demo/build-profile/Sites）。见 §15.44 与 [R-DASHBOARD-F4.10](acceptance/R-DASHBOARD-F4.10.md)。未运行会启动 Chrome 的 `test:e2e`；旧未装配回放源待 F6 退役，真实 Python/Agent 采集未验证。
- [x] **F4.11** 环境/应用/实例/范围/指标/scope 查询选择与同窗摘要；暂停/恢复语义、筛选不误跳转已由此前 IAB 验收。2026-10-08 当前工作区 IAB 又确认 app-two→app-three 后 URL/控件同步，QPS 84→63；5 秒内读取时间推进。有效 app-two 的受控一次性 503 呈现 stale 与“重试读取”，保留 QPS 84；下一自动轮询恢复 ready，读取时间推进且重试入口消失。相关 focused monitor logic **2/2**、HTTP stale/recovery **3/3** 与 `check:fast` 通过（§15.130–§15.133）。这关闭前端 demo/UI 筛选与同窗轮询切片，不代表 Python Console/Reporter/Collector 真实数据或长时生产可用性；长时资源、后台节流、真实服务故障仍留 F4.12/B0。见 §15.45、§15.130–§15.133 与 [R-DASHBOARD-F4.11](acceptance/R-DASHBOARD-F4.11.md)。
- [x] **F4.12** 断线/陈旧/未接入/迟到/缺测状态、发布标注与安全重连；轮询先行，不虚构未存在的流式协议；卸载无后台泄漏。monitor 由单一轮询 owner 管理有界读取、超时、暂停/恢复、换查询/撤权清理；图表保留发布标注，缺测指标显式 unavailable。既有 IAB 已验证标注渲染及离开页面停止轮询；本轮重新运行聚焦 monitor logic **9/9**（含断网后保留原窗口、下一轮恢复、超时、迟到撤权响应隔离、StrictMode 可重启及 64-owner 生命周期压力）与 Console HTTP Mock recovery **1/1**，`npm run check:fast` 通过（§15.130–§15.137、§15.152、§15.165–§15.166、§15.302）。本项只关闭前端实现/契约切片；真实 Console/Reporter 故障与长时生产资源验收由 B0.4/B0.5 承接，完整跨页 E2E 按安排留最终节点。

#### 故障分析（设计 §6）

- [x] **F4.13** UTC 事件窗、迟到接收时间与稳定分页已由领域/HTTP 测试覆盖；故障 URL 持有 severity/category/opaque cursor 与 instance/app/process scope。内置浏览器已验证实例筛选、应用变化清实例、刷新恢复、第二页 20+4、分页保留所选证据、筛选清游标且统计仍为全范围。全量 `npm run check` 通过（逻辑 242、HTTP 86、架构 13、i18n/contract/build/demo/build-profile/Sites）。没有启动 Chrome/Edge；未运行其 CDP 自动化 `test:e2e`。真实 Python Console、Reporter/生产事件源仍未验收。见 §15.47 与 [R-DASHBOARD-F4.13](acceptance/R-DASHBOARD-F4.13.md)。
- [x] **F4.14** 事件详情使用严格的 `relatedRule:{environmentId,appId,bindingId,versionId,publicationId}` 投影，校验关联环境/应用/版本/发布身份一致；从发布事件可直达对应不可变版本与发布回执，刷新仍恢复所选版本/发布；趋势下钻保留事件/app/instance/精确 UTC 窗口并固定历史窗口。IAB 仅通过本地 demo HTTP mock 实测，事件文案和关系负例由三语/logic/HTTP 门禁覆盖；无根因推断、无规则写入。真实 Python Console、生产 Reporter、指标和配置中心数据仍未验收，见 §15.48 与 [R-DASHBOARD-F4.14](acceptance/R-DASHBOARD-F4.14.md)。
- [x] **F4.15** 事件深链与实例/规则/监控下钻保留 event/instance/window；过滤后选中失效、空/拒绝/缺证据/部分载入恢复。Codex 内置浏览器验证事件选择→级别过滤后 URL 移除 event、详情清空且不自动选首条；`severity=warning&category=resource` 显示明确筛选空态；未知 event 深链只显示目标不存在，不展示旧证据。Logic 覆盖 missing target/错关联、partial/unavailable、同键读取失败 stale、404 清旧数据及权限撤销/迟到响应；IAB 不模拟浏览器级权限失效与 partial transport。F4.14 已验收跨页精确 event/instance/window，F4.15 本地前端切片见 [R-DASHBOARD-F4.15](acceptance/R-DASHBOARD-F4.15.md)；生产 Python/Reporter 权限和协议验收仍未完成。

#### 系统管理（设计 §7，五 tab 包括 identity 公共页）

- [x] **F4.16** 连接 tab 完成 Nacos/Consul 登记、修改、验证与能力/健康/时间呈现；reference/direct/none 三模式，不强制 KMS，不回显既存凭证。IAB 验证新建表单含 Nacos/Consul 与三种认证方式、切 provider 后专属字段变化；编辑已有 source 默认保留凭证且不回显；合成检查展示能力及 UTC 有效期，并明确不会连接真实服务。修正检查异常误用“登记操作未确认”文案的问题；注册/检查职责由 Source HTTP/Workflow 安全测试覆盖。详见 §15.50 与 [R-DASHBOARD-F4.16](acceptance/R-DASHBOARD-F4.16.md)。真实 Python Console、关系库持久化与配置中心探测不由本 UI 项证明。
- [x] **F4.17** 权限 tab 展示已确认的当前会话能力快照；协议 tab 展示后台支持、实际协商、兼容状态与 UTC 观测时间；审计使用有界 UTC 查询及筛选，保持在现有系统管理 tab、不新增顶级菜单。IAB 与证据边界见 §15.51 / [R-DASHBOARD-F4.17](acceptance/R-DASHBOARD-F4.17.md)。这里只验证本地 demo/mock 投影，不代表生产协议协商或审计持久化。
- [x] **F4.18** 系统管理内的账户维护/角色绑定 tab 与独立 accounts/roles 路由复用 Identity feature 的同一页面、workflow factory、HTTP Port 和 URL 目标语义；由各自 route owner 负责 session-bound workflow 生命周期，不复制表单/store 实现。IAB 验证系统 tab 与独立页面显示一致、账号到角色跳转保留目标 account、刷新恢复选中角色；管理员门禁由路由/领域测试覆盖。详见 §15.52 / [R-DASHBOARD-F4.18](acceptance/R-DASHBOARD-F4.18.md)。本轮一次 tab 返回时出现读取失败，整页刷新后恢复，根因未知；生产权限仍未验收。

#### 首次初始化（设计 §8）

- [x] **F4.19** storage/admin/source/review 分步内容与单一草稿/导航/纯投影、异步提交工作流已分开；PostgreSQL/MySQL/本地 SQLite 及连接参数边界、类型负例与完整 **127/127** 前端回归通过，证据 §13.2。旧 demo App 装配退役仍属 F6，真实迁移/锁/持久化属 B0，不以该项冒充后端完成。
- [ ] **F4.20** 连接测试和初始化命令有 pending/字段错误/安全重试/失败恢复状态；切 DB/provider/auth 清理不适用秘密，完成/离开后清除敏感表单。2026-10-08 workflow→HTTP adapter→MSW 数据库/Consul fail-once 用例通过；2026-10-09 提取 `clearSetupSecrets()` 并由 `useSetupFlow.clearSensitive()` 复用，清理数据库用户名/密码、规则源凭证和管理员密码/确认，同时保留非敏感配置；SETUP-SECRET/COMMAND 相关 logic **10/10**、`npm run check:fast` 通过。另在 mounted React 页面通过 Codex IAB 验证离开确认后放弃会重回 setup 且用户名/密码为空（§15.145）；fresh-origin 成功初始化后页面显示 login，不再渲染 setup 表单（§15.146）。2026-10-09 新增字段级错误归属、全问题呈现和复核错误回跳，SETUP focused **15/15**、typecheck/format/lint/i18n 通过（§15.224）；并补充认证失败/网络不可达/不支持连接方式的稳定三语提示与显式重试逻辑（§15.292）。补齐 Nacos reference/direct、Consul direct、no-auth、source endpoint 的字段错误归属，以及数据库/来源连接失败 `connection` reason 的失败→重试成功覆盖；SETUP logic **17/17**、`check:fast` 通过。追加服务端稳定 `validation` 拒绝后不自动重放、显式修正重提采用新 request key、未确认凭证不进入 snapshot 的 workflow 合同，并按服务端稳定拒绝原因显示独立三语恢复提示；SETUP logic **19/19**、i18n catalog/callsite **13/13**、`check:fast` 与 `i18n:check` 通过（§15.303–§15.304）。连接检查 pending 时现禁用对应测试按钮并由 application workflow 拒绝同类重复调用（不取消原检查）；数据库与来源两类检查仍可并行，连接字段保持可编辑。实际 SetupWizard React SSR 渲染测试覆盖数据库/来源两步、三语和 idle/pending 两态（§15.308）；真实 InitializationPage 容器三语 SSR 覆盖连接检查 pending、初始化未知/失败、setup 关闭和字段错误反馈（§15.313）；本轮进一步覆盖数据库认证失败、规则源不支持反馈及当前数据库检查重试入口，setup logic **20/20**、catalog **17/17**、`npm run check:fast` 通过（§15.319）。本轮将服务端明确拒绝 `setup-closed` 收敛为不可写终态，即使 bootstrap 快照陈旧显示开放，也隐藏向导、清理敏感表单并阻止连接检查/重提；保留只读 bootstrap 重读入口，logic **22/22**、catalog SSR **18/18**、`check:fast` 与 `i18n:check` 通过（§15.331）。服务端回执不含字段路径，因此只展示脱敏通用拒绝，不猜字段归属。2026-10-10 增加连接检查输入投影隔离合同：数据库/规则源 check 仅验证和发送本分支输入，不因其他步骤无效而阻断，并省略管理员和未选 provider 凭证（§15.345）。仍需 mounted React 闭窗后的秘密清理实测和真实 Python 后端联调，故不勾；完整 E2E 仍留最终阶段。详见 §15.144–§15.146、§15.224、§15.292–§15.331、§15.345 与 [F4.20/F4.21 记录](acceptance/R-DASHBOARD-F4.20-F4.21.md)。
- [ ] **F4.21** 首次引导由 bootstrap 状态决定；未初始化强制 setup，完成后拒绝再进入，login 无入口、setup 无返回登录；仅成功确认后跳 login。2026-10-08 IAB 在独立 origin 实际走完本地 Mock 的一次性授权、SQLite 检查、管理员表单、Nacos 检查、初始化提交；回执后进入 login，登录页无 setup 入口，重开 `#/setup` 仍回 login，`/auth/me` 返回 `null`，证明该 Mock 流程没有自动登录。默认 Mock 首启场景现可用 `VITE_CONSOLE_MOCK_BOOTSTRAP_PROFILE=first-run` 选择；profile/HTTP 回归通过。2026-10-09 补充授权 workflow 在 POST 完成至 gate 权威回读期间的单飞合同，拒绝重复授权和会 supersede 回读的 refresh/inspect；定向 HTTP **2/2**、setup workflow **19/19**、`check:fast` 通过（§15.306）。本轮新增 `BootstrapAuthorizationGate` 三语组件 SSR，验证未授权/已授权/关闭三态中初始化子树仅在服务器确认授权后渲染（§15.314）。另外，当初始化命令收到 `setup-closed` 回执时，页面在闭窗终态除清除敏感字段外，还会经共享 AuthenticationWorkflow 强制重读 bootstrap/session，使 app 级路由守卫获得同一权威结果；源码通过 `check:fast`，浏览器 effects/跨 owner 路由仍留最终 IAB 验收（§15.332）。Python bootstrap 事务、并发锁、持久化/重启与真实后端仍未验收，故不勾选；详见 §15.119、§15.306、§15.314、§15.332 与 [F4.20/F4.21 记录](acceptance/R-DASHBOARD-F4.20-F4.21.md)。

  - 2026-10-10：新增多标签初始化完成后的前台身份重验逻辑合同；F4.21 focused logic **3/3 passed**。真实焦点/路由跳转和 Python 持久化仍待验收，详见 §15.438。

#### 登录（设计 §9）

- [ ] **F4.22** 登录凭据由 identity workflow 提交，禁止非空就成功/未知用户默认 admin；必填、错误凭证、停用、限速与请求失败区别显示。已有固定 demo 账号/统一拒绝语义；已知认证拒绝在用户修改凭据后清除、未知写入结果不可被编辑操作清除或重试（§15.182）；Python 登录路由/限流和身份化审计数据库切片定向测试 29 passed（§15.183）。NETWORK 错误属于 `result-unknown`，须核查会话且不能重放；bootstrap/session 读取失败单独显示控制台不可用与显式检查入口（§15.211）。429 采用有界 `retryAfterMs` 与三语冷却提示，编辑凭据不清除冷却（§15.307）。新增正式 `LoginEntryPage`/`AuthenticationProvider` 三语 SSR，覆盖认证拒绝、未知写入和 authority 不可用，聚焦逻辑 5/5、catalog 18/18、`check:fast` 通过（§15.320）。2026-10-09 修正最终浏览器 E2E 探针的 429 响应为真实 `rate_limited + retryAfterMs` 协议形状，并加入倒计时禁用提交、修改凭据不清冷却、到期恢复提交的断言；`F4.22` logic **5/5**、`node --check`、`check:fast` 通过（§15.333）。该浏览器用例尚未运行。键盘/完整页面、冷却计时实测及 Python→React 真实服务链路仍留待最终验收，故不勾。
  - 2026-10-10：将账号/密码草稿和字段错误移入登录表单子树；权威登录成功或 setup 接管后卸载表单，失败/限流保留可修正输入，unknown 仍禁用并保留核查入口。逻辑 **5/5**、三语登录 SSR **1/1**、`check:fast` 通过；最终 mounted 检查见 §15.351。该项继续未勾，真实 Python 链路和最终 E2E 未验收。
- [ ] **F4.23** session/me/logout/过期处理和安全回跳闭环；setup 状态未知不闪现管理页，导航/菜单显示真实账号而非 LD。新鲜 localhost Mock viewer/admin 登录后显式注销均成功并带站内 returnTo 返回登录；旧 `127.0.0.1` 场景另发现 storage 写入未生效时同页读回 stale admin，§15.291 已修复为写后核验并在失败时以内存匿名覆盖；页面重载后持久化仍取决于浏览器 storage 可写。定向 returnTo 逻辑 **1/1**、logout/Mock 身份逻辑 **4/4**、`check:fast`、`i18n:check` 与 E2E 源码语法检查通过（§15.334）。§15.352 修正 `App` 与 `LoginEntryPage` 重复拥有登录/setup 导航的问题；新增架构约束与最终 E2E 的单次导航断言，但浏览器用例暂未运行。最终 IAB 尚需实测“确认身份→会话菜单账号/角色→注销→站内 returnTo→重新登录后按新身份授权”；不使用 CDP/Chrome/Edge。服务端确认/撤销、过期与真实 Python API 尚未验收。详见 [F4.23 记录](acceptance/R-DASHBOARD-F4.23.md)、§15.79、§15.96、§15.291、§15.334 与 §15.352。
- [ ] **F4.24** 表单 autocomplete/密码可见性/键盘和三语错误；演示提示与真实模式不混用，登录失败不清掉可修正的账号输入、不泄露账号存在性。2026-10-08 IAB 本地 demo 发现并修复登录命令过渡态卸载 LoginEntryPage 导致输入丢失；新鲜显式 Mock 会话中，日/英/简中拒绝凭证均显示非枚举文案，用户名保留、密码遮蔽；英文 Enter 提交及密码显隐也已手工观察。§15.353 为真实 `LoginEntryPage` 增加最终 mounted E2E 的三语拒绝/账号保留/密码遮蔽/秘密不泄露断言，当前仅做语法检查，尚未运行。2026-10-10 generic login description 与 demo-only identity hint 已拆分，由 app build profile 仅在 demo 模式传入；三语实际 React SSR 隔离 **18/18**，`check:fast` 通过（§15.489）。键盘/可访问性自动化、IAB mounted、Python Console 行为仍待验收，故不勾。详见 §15.78、§15.353、§15.489 与 [F4.24 验收记录](acceptance/R-DASHBOARD-F4.24-login-route-owner-preservation.md)。

#### 账户维护（设计 §10）

- [x] **F4.25** 前端账号维护 Mock 切片完成：列表/筛选/分页与新增 Dialog；仅账号名/密码/admin|view，无显示名、无新增确认密码。Codex IAB 实测 21 条目录按 20+1 分页、往返边界、成功创建与重复账号留在 Dialog；`npm run test:logic` 247/247、`npm run test:http` 94/94。真实 Python Console、关系库持久化/唯一性并发和 React-to-Python E2E 仍属 B0 后端验收，不由本项打勾覆盖。
- [ ] **F4.26** 启停确认与成功后的统一数据更新；内置账号/最后 admin 保护及冲突/失败展示，command 不由 UI 临时生成正式 ID。已有 Codex IAB Mock 确认与本地保护证据（§15.73）；2026-10-09 `ACCOUNT-STATUS` focused **4/4** 补齐成功后刷新当前目录、request 带目标 ID+revision、服务端 last-admin rejection 保持 conflict 并映射正式文案，typecheck/format/lint 通过（§15.225）。新增已确认的本人账号停用后立即重读认证事实，避免继续展示已失效管理态（§15.309）。2026-10-10 账号列表现在会为被保护的内置管理员/最后有效管理员显示对应三语禁用原因，聚焦状态测试 **5/5**、三语实际组件 SSR **1/1**、`check:fast` 通过（§15.490）。仍缺真实 Python revision/最后 admin 并发验收与最终页面回归，整项不勾。
- [x] **F4.27** 账号操作仅 admin；目标 ID 无效不回落其他账号；“本人改密”与“管理员重置”明确分离，后者如纳入范围单独确认合同，不复用本人页。IAB 验证 viewer 无 System/账户入口且直接打开账户维护被拒绝；角色页缺失 ID 明确空态、无账号回退，fresh IAB 中无效深链→显式选 viewer 成功，角色仅 admin/view。逻辑/HTTP 契约覆盖 viewer 拒绝管理 Port、Mock HTTP 权限及本人密码独立 session-bound endpoint；当前无 admin reset 变体。完整 `npm run check` 通过，真实 Python Console 授权/持久化仍留 B0；见 §15.73–15.74 与 [F4.27 IAB 记录](acceptance/R-DASHBOARD-F4.27-role-target-iab-smoke.md)。

#### 角色绑定（设计 §11）

- [ ] **F4.28** URL 账号选择与详情/草稿同步；无效/停用/空列表有显式状态，角色仅 admin/view。IAB 已验证 viewer/admin 深链和账号切换同步 URL/详情、无效 ID 显示空目标且不回退，admin 受保护角色不可编辑；账号目录新增“忽略取消的迟到响应不得覆盖当前 target”定向逻辑测试；角色页深链 fallback 文案按读取状态区分（§15.230），并对停用、内置和最后有效管理员的只读角色控件显示明确原因，原因优先级逻辑已覆盖（§15.231）。角色账号目录已改为服务端搜索和 20 条分页，当前 URL 账号在筛选/翻页时保留为显式选项。页面级筛选/分页、disabled 与空目录及只读原因的渲染仍待最终 IAB 验收。详见 §15.213–§15.214、§15.230–§15.231 与 [F4.28/F4.29 IAB 记录](acceptance/R-DASHBOARD-F4.28-F4.29-role-binding-iab.md)。
- [ ] **F4.29** 草稿、保存/取消、保存 pending、版本冲突与刷新；不能切 radio 即假报持久化，影响会话的变更提示准确。IAB 确认切 radio 只建立本地草稿、路由离开并丢弃后重新读取已保存角色；本次代码收口移除了角色页第二套本地切换确认，账号切换统一交给应用级保护（§15.212）。当前补齐远端刷新规则：干净草稿跟随已确认的新角色/revision，脏草稿保留原基线并显示冲突（§15.232）；角色写入的 accepted-pending 必须先以原 request key 核查完成回执，未确认期间拒绝重复写入，确认后才刷新目录/详情（§15.233）。新增本人角色/状态变更的确认回执（包括后续查询 unknown 操作）会调用 app 唯一 AuthenticationWorkflow 重读 `/auth/me`；若角色降权或账号停用，当前 account workflow 立即撤权并清空管理数据，不再刷新管理员目录（§15.309）。页面会话提示、真实 Python 服务仍未覆盖；见 §15.95、§15.212、§15.232–§15.233、§15.309 与 [F4.28/F4.29 IAB 记录](acceptance/R-DASHBOARD-F4.28-F4.29-role-binding-iab.md)。
- [ ] **F4.30** 禁止 view 编辑，内置/最后 admin 保护与跨页状态一致，未保存切账号确认、保存失败不丢选择。IAB 在隔离 localhost Mock session 验证 viewer 主导航隐藏系统管理、直接访问 accounts/roles 被拒、规则可读但编辑提示只读且创建活动计划 disabled；未改变角色/账号。内置/最后 admin 保护、保存失败保留选择、并发冲突及真实 server authorization 仍未验收，详见 [F4.30 IAB 记录](acceptance/R-DASHBOARD-F4.30-viewer-iab.md)。

#### 修改密码（设计 §12）

- [ ] **F4.31** 当前密码/新密码/确认属于本人表单；从 session 取账号，不收任意目标 accountId、不 fallback 首个账号。2026-10-09 聚焦 logic 验证本人 owner、viewer 本人改密、未知/过期/匿名/换账号/换 session 拒绝；Python SQLite/ASGI 也验证 admin/view 均只能改本人。补充实际 `OwnPasswordPage` SSR 三语渲染：三个字段均为 password，autocomplete 语义正确，使用 session username 且无 accountId/目标选择（§15.318）；正式 mounted 页面渲染与改他人 URL 的 IAB 验收仍未完成。
- [ ] **F4.32** password policy/旧密码错误/限速/冲突与成功会话策略；确认仅本地，成功响应后才清空，不本地通过即成功。前端 logic 覆盖确认字段不进入 wire、表单校验、pending 单飞、已知错误可修正、timeout/5xx/取消/无效回执为 unknown 且不自动重放；Python 已补齐错误当前密码与账号作用域限速，429 携有界 `retryAfterMs`，attempt authority 故障 fail-closed（§15.339–§15.340）。真实页面提示与 Console 联调仍未验收。
- [ ] **F4.33** 密码清理、autocomplete、禁日志/URL/缓存；过期/取消/失败和提交中恢复，验证改他人 URL 无效。前端 logic 证明密码不进入 workflow snapshot 且 owner 变化取消观察；Python 改密 ASGI/SQLite 测试现 **8** 项。正式页面 autocomplete/键盘、浏览器存储/URL 与可见失败恢复仍需 Codex IAB 检查；本轮没有内置浏览器交互工具，未运行 CDP/Chrome/Edge，详见 [本人改密验收记录](acceptance/R-DASHBOARD-F4.31-F4.33-password.md)。

### F5：国际化、质量与工程门禁（7 项，相关测试随前述切片实施）

- [x] **F5.1** 保留集中 JSON + i18next，feature namespace/key 有明确 owner；视图文案审计将 UI 标签与 `app/api` 中 wire/mock 场景业务内容区分，封闭的事件/严重级别等 code 由 presentation 映射到翻译键，自由文本与环境/规则样例不强行翻译。JSON 资源归属/三语 parity 测试、界面审计回归、三语 IAB 总览切换及完整 `npm run check` 通过。证据 §15.76；115 个动态 `t()` 调用仍需 F5.2 做穷尽映射与运行校验，不据此声称动态键全覆盖。
- [ ] **F5.2** 三语 key/插值/选项穷尽、Intl 数值/日期/时区/复数与动态键测试；语言切换不修改协议枚举、草稿和 URL。当前 AST 报告 **22** 个动态 `t()` 调用；manifest 精确绑定调用文件/表达式、命名 runtime suite 与 suite 实际加载的 key producer，避免只检查 suite 名存在造成假绿（§15.456）。最新 `test:i18n-tools` **36/36**、i18n parity **1,220 keys/locale**、AST **1,065** 静态键，22 动态调用仍明确可见；`check:fast` 通过。共享 UTC 展示格式器已有 locale 日期覆盖（§15.215）；规则计划重复 DST 时刻选项投影证明标签随 zh-CN/en-US/ja-JP 本地化、UTC epoch 选项值不变且非法值拒绝（§15.226）。路由/session epoch/规则 binding 与 workflow 所有权及语言入口不导航断言见 §15.228。§15.358 已把正在编辑的规则草稿连续切换简中/英文/日文后核对草稿、URL、协议候选与单次保存内容的浏览器断言加入最终规则交互套件；尚未运行最终浏览器验收，且其它持草稿页面与日期/时区矩阵未完，因此不勾。
- [ ] **F5.3** 纯校验/mapper/状态转移单测与组件命令测试；优先复用 node:test 与现有 runner，确需新工具再证明缺口；测试不能只断言假 fixture。2026-10-09 系统观察 DTO / audit filter / resource ownership 定向逻辑 **8/8**，对应 HTTP mapper/MSW **5/5**，见 §15.180；这是切片证据，不完成整项矩阵。新增 route/rule-kind/system-tab/instance-layer/account-role 边界守卫的定向逻辑测试 **5/5**，见 §15.234–§15.235。2026-10-10 补规则 binding 注册 model/命令定向逻辑 **6/6**（来源 revision/provider 绑定、未授权不发送、成功/错配回执、pending 重复提交不产生第二次写入、执行中撤权、未知结果脱敏），见 §15.457；`check:fast` 通过。仍缺其他页面命令状态矩阵与挂载组件的真实用户命令路径，整项保持未勾。
- [ ] **F5.4** 扩浏览器交互矩阵：11 路由 + 系统 tab + 两角色 + setup gate + CRUD/版本/失败/无数据/跨页，逐项断言用户结果，不只导航成功。
- [ ] **F5.5** 逐路径像素/DOM/键盘验收；暗色既定基线、三语长文案、手机/平板/桌面/宽屏与 zoom/DPR；已知坏布局不得重拍为绿色基线。
- [ ] **F5.6** 路由/图表/编辑器分包与列表容量评估；刷新/订阅无重复、停止后无泄漏；记录首屏/交互/包体实际基线，不只调大 warning 阈值。Nivo renderer 已按图表挂载延迟加载；§15.355 修复 app runtime 从宽泛 identity HTTP barrel 带入 setup-only endpoint/schema 的问题，认证、初始化和身份管理现在各用窄 HTTP 入口；React 与 i18n runtime 共享 vendor chunk，Astryx/Zod 仍按路由自然分包。隔离 sourcemap builds 实测：production 最大 JS chunk **463,990 B**、manifest 静态闭包 **960,941 B / gzip 261,061 B**、41 deferred entries；demo 最大 JS chunk **467,680 B**、manifest 静态闭包 **964,634 B / gzip 262,231 B**、44 deferred entries；`BUILD-SETUP-LAZY`、`BUILD-CHUNKS` 均通过，未调整 500 KiB warning 阈值。浏览器传输/交互解析耗时、实时列表容量和订阅停止后泄漏仍缺运行证据；F5.6 不勾。
- [x] **F5.7** 加入独立前端 CI/统一 verify 脚本，类型/lint/格式/i18n/逻辑/构建/Sites 全闭环；实际专用端口完整浏览器 196/196 与 29 态稳定捕获通过，正负工具测试与 receipt 可复现。未 push，远程 CI 未执行；未传 baseline 的 runner 不冒称像素比较通过。证据 §14.2；最终 HTTP/Python 验收继续 F6/F7/B0。

### F6：最后集中抽取 Mock 与 HTTP 接线（12 项，不提前实现 Python）

> F6.1 最新逐字段合同审计记录见 §15.411–§15.436；上述局部修复与测试不代表整个 F6.1 完成。

- [ ] **F6.1** 按完成后的每页动作反推请求目录，收敛已有协议冲突，统一唯一 wire 的路径/DTO/错误/时间/分页/幂等/权限；输出 OpenAPI/Schema/正负样例而非再建第三套。2026-10-09 新增 Python 路由表与 OpenAPI 的路径/方法契约测试，覆盖完整可选身份端点装配，规范化 Starlette/OpenAPI path parameter 命名差异；聚焦 **1/1 passed**（§15.266）。2026-10-09 又对齐 bootstrap/session/logout 非法 request-id 的 `invalid_request` + HTTP 400，修正了 session/logout 的 HTTP 400 + `validation_failed` 错配；Python identity API **23 passed**，前端 bootstrap 错误保真 **1/1 passed**（§15.272）。同日将旧身份 API 文档明确标为历史非规范，并链接到唯一 Console 契约、生成 OpenAPI 和页面需求文档（§15.273）。2026-10-10 重新核验当前前端导出的 OpenAPI **43 paths / draft-partial** 与 Python 路由 parity **1/1 passed**（§15.359）；随后增加 operationId 唯一性、安全方案引用、request-id、成功/错误响应 schema、语义规则和命令未知结果标记完整性门禁，Python 合同测试 **2 passed**，前端 OpenAPI 生成校验通过（§15.361）。继续复核发现 OpenAPI 原先将可匿名调用的 session/login 错标为必须已有 session，且漏掉双提交 CSRF cookie；现修正为可选 BrowserSession + 显式 CsrfCookie 安全方案，并增加生成产物与 Python 契约断言（§15.362）。之后统一前后端 code/status registry 并强制 Python error response 校验，修正 3 个 observations 400 错码，Python 全部 API tests **223 passed**、前端 `check:fast` 通过（§15.363）。身份、账号、观测、故障分析、系统观测、配置源与规则生命周期目前全部 **43/43 operations** 均包含由运行时 DTO 校验并投影到 OpenAPI 的正负 HTTP exchange，共 **87 exchanges / 111 media examples**（§15.386–§15.387）。Fleet 查询参数已与 Python allowlist 和 scope 对齐（§15.388）；本人改密回执也已限定为后端唯一实现的 `reauthenticate`（§15.389）；Incident 查询的 scope、资源过滤与 app/instance 组合已对齐（§15.390）；实例目录搜索和观察身份的 Python/JavaScript UTF-16 计数已统一（§15.391–§15.392）；实例详情 OpenAPI scope 已收窄到 Python `InstanceLayer` 的 `host/container/process`（§15.393）；实例目录已收敛为 fleet/application 且不再声称支持实例/资源过滤（§15.394）。Incident opaque cursor 的 blank-character 与 Unicode scalar 判定现由前后端共享契约约束，查询 schema、纯模型、Python domain、API 拒绝与 OpenAPI pattern 测试均覆盖 U+001C/U+0085/U+FEFF、混合有效内容和孤立 surrogate；前端逻辑 **2 passed**、HTTP 不派发 **1 passed**、Python Incident timeline **13 passed**、OpenAPI 游标断言 **1 passed**、`npm run check:fast` 通过（§15.403）。此外核验了通用 UTC instant、system audit 查询、rule schedule JSON 三条时间路径：前端和 Python 均要求 UTC `Z` + 固定毫秒精度 + 1970–9999 年份，生成 OpenAPI 保留同一 pattern；前端 `HTTP-WIRE` **1 passed**，Python `test_utc_wire.py` + `test_system_audit_api.py` + `test_rule_mutation_parsing.py` **25 passed**，`check:fast` 通过（§15.404）。配置源检查及首次初始化检查已统一 UTF-16/blank/scalar 输入语义（§15.405–§15.407）；Fleet query search 的 UTF-16 长度与 endpoint strict 参数投影也已修正（§15.408）；观察目录 ID/name 的 Python 域校验现与前端 UTF-16/string-scalar schema 一致（§15.409）；bootstrap operator code 现统一为 32–1024 URL-safe ASCII，坏格式在 authority/transport 前拒绝，OpenAPI 正负样例已同步（§15.410）；首次初始化数据库检查也已对齐 host 边界空白、字符串 UTF-16 长度、用户名非空白标识与 scalar 约束，React/Python 聚焦验证及生成合同均通过（§15.411）。样例齐备不等于语义审计完成；仍需逐页核查唯一 wire 的路径/DTO/错误/时间/分页/幂等/权限并消除历史规范歧义，F6.1 不勾。
- [x] **F6.2** 按 feature Port 新增 Console HTTP adapters、endpoints/schema/mapper；Mock/live 共用基于 `@richie696/react-framework` `Url`/`HttpClient` 的 transport，Mock 仅由 MSW 在 HTTP 层拦截，外部响应经运行时 schema 校验后映射，不保留 FixtureGateway/旧同步 API。2026-10-10 复核并运行：`npm run typecheck` 通过；`npm run test:http` **141/141 passed**（含 API 正负样例、取消/超时/错误归一、MSW Mock、受控 loopback）；架构依赖与 mapper 门禁 **11/11 passed**；`npm run contract:check` 验证 **43 paths / draft-partial**；`git diff --check` 通过。F6.2 仅覆盖前端 adapter 实现；协议完整性审计仍归 F6.1，真实 Python 服务联调归 B0.5，完整浏览器 E2E 归 F7.1/F7.2/F7.3，均未因此宣称完成。
- [x] **F6.3** Provider/main/全部页面切至新异步查询/命令路径，移除 read*Sync/函数型 snapshot 调用；读写同走新 HTTP 实现，mock/live 只改变传输目的地，不替换 feature gateway。正式路由和全部页面浏览器 E2E 通过；证据 §15.26。
- [x] **F6.4** 七个 feature mock 入口只提供 HTTP 投影/可重置状态，固定目录、统一时钟、用户、健康/摘要、规则计划/版本、指标曲线及受控故障事实归 app-owned scenario；依赖方向、跨页面身份/统计一致性与全部 mock HTTP 合同均已验证。子切片及最终全量 HTTP/架构证据见 §15.147–§15.156；这只关闭 Mock seed 收口，不代表 Python/真实配置中心或整个项目 E2E 完成。
- [x] **F6.5** Browser/Node 共用 feature HTTP handlers，显式 app mock assembly 覆盖全部 42 个 Console operation 路径；按 HTTP method/path/query/body 处理并返回 Console wire shape、canonical status 与 headers，未实现请求由 fail-closed handler 拒绝。Node 完整 HTTP 套件与内置浏览器 demo 页面验证通过，详见 §15.157；不等价于 Python Console 实际服务集成。
- [x] **F6.6** Mock query 实际执行筛选/分页/window；账号、配置源、规则集 commands 驱动各 handler factory 隔离且可重建/显式 reset 的演示状态，覆盖角色/启停、草稿/版本/发布/计划。账号密码不进入账户行/操作回执；浏览器仅持久化明确 allowlist 的非敏感 bootstrap/role/failure flags。全套 HTTP 与新增 query/state/password 保密测试通过，详见 §15.158。2026-10-09 规则计划检查现有 Mock 状态时先经 `ActivationPlanSchema` 验证，再保留协议 `state` 原值投影；损坏状态 fail-closed，不再用字符串转换和类型断言伪装计划事实，取消后的原时段仍可重排。聚焦 HTTP **1/1**、`check:fast` 通过（§15.237）。
- [x] **F6.7** 增加明确 mock/live 运行配置与 base URL 校验，提供示例环境文件；启动在 HTTP interceptor 就绪后渲染，失败不偷发真实请求，mode 不给 page/store 分支。新增启动编排契约，mock/live/base URL 与失败关闭 focused tests **5/5**，`check:fast` 通过；内置浏览器 mock 启动冒烟到达登录表单。未运行完整 E2E/里程碑门禁，未接真实 Python 服务。详见 §15.159。
- [x] **F6.8** live 模式不加载 mock、不回落 fixture；本项目 Mock worker 仅在显式 demo profile 提供，不删除项目 Sites worker；生产构建排除 seed/worker/演示认证，demo 制品显式包含 mock。生产/demo 分别构建至临时目录、不覆盖既有 dist；artifact profile **3/3**、runtime focused **6/6**、`check:fast` 通过。未运行全量 E2E/里程碑门禁，未接真实 Python 服务。详见 §15.160。
- [x] **F6.9** 未匹配 Console API 的 Mock 请求 fail-closed、静态资源旁路、42 个 operation 声明错误/权限边界、超时/取消/迟到/畸形响应、HTTP 503 与真实无响应网络故障均有自动化覆盖；Mock 场景时间可显式固定，重建 app assembly 会重放相同时间/seed/一次性故障，Fleet 与实时指标故障计数器归各自 handler 实例，不再跨 assembly 污染。`npm run test:http` **112/112 passed**（含受控 loopback；普通 sandbox 禁止 bind，需批准的本机隔离 listener），`npm run check:fast`、`npm run test:architecture` **20/20**、`git diff --check` 通过。证据 §15.164。仅关闭 Mock/HTTP 场景与合同测试；完整浏览器 E2E、Python Console/真实网络依赖仍未验收。
- [x] **F6.10** 网络/流契约测试核对 DTO/sample/handler；源码确认当前没有应用级 SSE/EventSource/流式订阅（`ReadableStream` 仅用于有界读取普通 HTTP 响应）；受控真实 loopback HTTP 用例覆盖同一 transport 的 URL/query、request ID 与凭证头边界、canonical 503、请求中止及服务端响应关闭。HTTP wire/mock/operation 与 transport 全套 **109/109**，`check:fast` 通过；这是本机受控端点而非 Python 联调。详见 §15.162。未跑里程碑浏览器 E2E。
- [x] **F6.11** 前端 provider 边界已收口：规则 binding/profile 与完整 Sentinel 规则数组由 Console 合同表达；Nacos/Consul addressing、凭证和规则 source 转换不进入 React，前端只调用 Console HTTP。误置于前端的 provider adapters/伪语义测试已退役；`grade` 保持 Sentinel 数值编码，404 `not_found`、409 `conflict`、503 `unavailable` 保持不同语义，没有修改实现迎合过时断言。当前架构 **20/20**、规则模型/工作流 logic **30/30**、规则 HTTP + 操作错误矩阵 **8/8** 通过；细节见 §15.163。此项仅关闭前端边界，不声称 Python provider 转换或 Nacos/Consul 持久化完成（B0.3 仍开放）。
- [x] **F6.12** 新路径完成迁移后删除 fixtureGateway.ts、旧类型/单例/导出/装配/read*Sync、临时 useDemoAccountBootstrap 及废弃 HTTP 雏形；不保留旧网关作为兼容层或测试替身。扫描 src 的 import/export/调用无残留，测试不依赖旧网关；Mock HTTP 与受控 live 请求都经过新实现，类型/交互/视觉与请求失败回归通过。证据 §15.26。

### F7：前端完成验收与交接（7 项）

- [ ] **F7.1** Mock HTTP 模式跑通 setup → login → overview → 诊断 → 规则草稿/版本/发布演示 → 账号/角色 → 本人改密/注销；明确所有持久/发布为模拟。分段证据：首启 setup 见 §15.119；viewer/admin、观测页及 Mock 创建账号见 §15.120；规则草稿/版本/发布见 [F7.1 规则验收记录](acceptance/R-DASHBOARD-F7.1-rule-draft-iab.md)。这些是跨会话/分段 Mock 验证，完整同一流程、改密/注销与 Python 后端仍未验收，故不勾。
- [ ] **F7.2** 同路径的只读、非法深链、过期、失败/冲突/未知结果、刷新/返回与秘密不泄露验证；无默认 admin/fixture 授权生产路径。
- [ ] **F7.3** 类型/lint/build/i18n/逻辑/浏览器/像素门禁与容量记录收口；FixtureGateway 与同步 gateway 必须清零，不设保留例外；其他遗留文件/全局控件样式的允许例外需写明责任/退出条件。
- [ ] **F7.4** 按每页更新正式功能、数据结构、业务规则、接口和失败语义；Mock 覆盖与后端待实现明确标记，保证“一个页面一章”的设计可直接指导 Python。
- [x] **F7.5** 前端 README/AGENTS/职责地图/旧规划消除过期状态；运行配置、Mock 场景/重置/真实模式使用与调试说明齐全，无竞争计划。README 已修复规则发布能力与旧 FixtureGateway/applicationScope 描述，补齐 demo/first-run/live 与安全重置说明；AGENTS 和职责地图已统一为 React 前端 + Mock/live 现状，并把 2026-10-05 改写方案标为历史材料、不作为并行执行计划。证据 §15.478。
- [ ] **F7.6** 验证生产 dist 静态资源、base path、缓存/SPA 与 /api 回退边界；保护 Sites 制品和测试，为后续 wheel 打包给出 assets 清单，不此时发布。当前 production 构建 mock 排除 + setup 分包 focused **2/2**；刷新后 Console wheel 的 76 项资源逐项 hash/size 匹配，隔离安装该 wheel、无 Node 跑静态 ASGI 测试 **4/4 passed**。2026-10-10 修正非根 dashboard prefix 下 `/ops/sentinel/api` 和子路径误回退 HTML 的边界，静态 ASGI focused **4/4 passed**（§15.486）。仍需最终 Codex IAB 从已安装 wheel 渲染核验及 production launcher/deployment 验收，详见 §15.218、§15.486 与 [F7.6 记录](acceptance/R-DASHBOARD-F7.6-wheel-static-assets.md)。
- [ ] **F7.7** 形成前端交接记录：版本、制品、逐页操作映射、通过/失败/未测范围、Python 缺口；只有 F0–F7 全部闭环才称前端开发完成。

### B0：后置 Python 实现与真实联调（5 项待完成；B0.6 已完成；不计入前端实现完成）

- [ ] **B0.1** 确认独立 Console 服务落点与内嵌诊断兼容，依据 F6 契约落 Python DTO/路由/错误与真实权限，而非从旧单进程 API 裁掉页面需求。当前系统连接、协议、admin-only 审计、配置源目录、观测应用目录、实例目录、实例详情、通用指标、Fleet 总览、故障时间线、事件证据及规则 binding/snapshot/draft/version/publication/receipt/activation-plan/candidate-diff/validate 已有路由、有限 DTO/校验和宿主 authority 注入端口；bootstrap authorize/source-check、admin 注册源检查、登记命令及规则草稿/版本/发布/激活计划命令已有 HTTP/security adapter。规则 SQL 首切片现支持草稿 save/delete、验证回执绑定冻结版本、草稿/版本读取；标准 first-run composition 在配置独立规则命令 HMAC key ring 时，现将 `SqlAlchemyRuleBindingDirectoryReader` 装到同一 runtime SQL bridge，保留 host reader 覆盖（§15.458）；CLI API 服务可使用已登记 binding，但配置中心发布/计划 worker、生产目标策略与部署 acceptance 仍未完成。配置源 SQL store/migration、部署 keyring 配置与 async PostgreSQL/MySQL URL engine 构造已实现；另有显式 opt-in 的预置数据库 ASGI 生命周期 helper，可执行迁移、检查初始化标记并归还 engine。首次初始化已有 `SqlAlchemyBootstrapInitializationCoordinator` 跨 setup grant、目标数据库迁移、runtime locator、首管理员事务和关窗的 durable 编排；`build_first_run_sql_identity_app` 将同一 coordinator 装配为初始化 reader/initializer/operation reader，CLI `serve` 使用该显式组合。该 source-level 组合不等于 PG/MySQL 部署或生产 launcher acceptance。已登记来源与 bootstrap 首次来源检查现均有显式外部凭证 resolver Port 和 fail-closed 应用解析路径，但无 KMS/Secret 产品适配器；生产 SQL app 组合入口接受 deployment-owned checker/resolver 注入。Nacos 3 只读探测令牌现通过 `accessToken` 请求头传递而非 URL 参数（§15.298）。当前 Python 源码已有完整 42/42 OpenAPI 路由注册，包括 bootstrap initialize 与 operation recovery 的 HTTP/security adapter。Nacos/Consul 无认证只读探测已通过 disposable 服务验收（§15.490）；生产认证/TLS、自定义 CA、规则 publication/计划部署与实例回执仍未全部完成；其余生产事实源也尚未全部装配。规则工作流读路径见 §15.192–§15.202，命令接口见 §15.227，bootstrap source-check/authorize 见 §15.203–§15.204，admin 配置源见 §15.205–§15.209 与 §15.239，DB runtime URL 见 §15.210，bootstrap initialization adapter 见 §15.265，静态基线详见 §15.175–§15.178。该任务整体仍未完成。
- [ ] **B0.2** 实现 PostgreSQL/MySQL 迁移/首次 setup/凭证保护/首个 admin/身份/账号/角色/本人改密/审计；数据库与最后 admin 并发分别验收，SQLite 不替代生产 DB。当前已有 bootstrap/session/account-directory 读取、登录/注销、账号 create/status/role 写命令、本人改密、SQLite 局部事务切片和 SQL-backed 登录限流 adapter；限流策略、账号命令 HMAC key 与登录 client identity HMAC key 都已有严格部署环境配置解析，SQL identity routes 有显式组合入口，预置数据库 ASGI lifespan helper 可运行迁移、拒绝未初始化库并在退出/启动失败时释放 engine；新增首启 CLI/环境组合与 setup-window status/open/close 命令（§15.280），可显式装配 first-run ASGI app，缺省绑定 loopback，trusted proxy 配置显式进入 client resolver。PostgreSQL 16 与 MySQL 8.4.11 隔离实例现均已验证全量迁移、重复升级及真实事务竞争下的最后管理员保护（§15.442）。首次 setup 完整部署验收、真实 ingress/多 worker、installer secret delivery 与浏览器到 Python 联调仍开放。候选 PG/MySQL engine factory 先经部署 allowlist/DNS policy，并返回同一次解析派生的 prepared engine 与 locator target：PostgreSQL 固定已批准 IP 并保留 `verify-full` hostname TLS；MySQL 用已批准地址建连、原 hostname 做 TLS 校验并拒绝未验证 TLS。runtime locator v2 已将 URL 和 target metadata 一并加密，运行期 engine 恢复 pinned PG/MySQL 连接；legacy v1 locator 保持无 pin 的 operator-owned DNS 语义，fake-driver/SQLite 测试不冒称真实驱动/服务验收。目标数据库内现有首管理员/来源注册/初始化回执/audit/guard 单事务 adapter，首次迁移、runtime locator/setup-window coordinator 关窗与跨资源崩溃恢复现已有局部实现及重启恢复测试；setup-window 本地 CAS 现通过两个独立 spawned OS 进程竞争测试（§15.293），但不代表共享部署卷/NFS/多主机验收。首次初始化剩余责任与局部证据见 §15.134、§15.138–§15.141、§15.171–§15.172、§15.219–§15.221、§15.238、§15.274–§15.280、§15.293、§15.325 与 [B0.2 首启验收记录](acceptance/R-SENTINEL-CONSOLE-B0.2-bootstrap-authorization.md)，不据此勾选。
  - 2026-10-10 PostgreSQL 16 与 MySQL 8.4.11 真实隔离库首次初始化竞争、幂等重试、SQL 身份 HTTP 及授权首启 ASGI 路径验收均通过：单赢家/闭窗、receipt 去重、changed-input conflict、operator 隔离、首次管理员/来源加密持久化、登录/会话/改密/审计与所检查记录无明文凭证（§15.443–§15.446）。PG 全套 **5 passed**，MySQL 全套 **6 passed**；身份/初始化/账号回归 **34 passed**。详见 [持久化验收记录](acceptance/R-SENTINEL-CONSOLE-B0.2-persistence-foundation.md)。只覆盖隔离目标库能力，不关闭完整 B0.2。
  - 2026-10-09 身份/初始化/账户/system-observation HTTP adapter 已统一复用 `api.browser_security` 中的会话与 CSRF Cookie 常量；相关回归 **74 passed**，见 §15.335 与 [Cookie 协议记录](acceptance/R-SENTINEL-CONSOLE-B0.2-auth-cookie-contract.md)。此局部修复不关闭 B0.2。
  - 2026-10-09 本人改密现通过 SQL attempt-limit authority 对错误当前密码做账号作用域限速，`429 rate_limited + retryAfterMs`；限流表只保存 HMAC digest，且改密桶不与登录 IP 失败桶共享计数。局部 SQLite/ASGI 与 composition 回归 **20 passed**（§15.340）；PostgreSQL/MySQL、多 worker 与 production 启动注入验收仍开放。
- [ ] **B0.3** 实现 binding/profile、草稿/不可变版本/发布/回读/回滚/活动计划恢复和实例回执；Nacos+Consul 真环境验证，不把写入成功当全部实例生效。当前 SQL publish command 已能校验不可变目标/显式 baseline 身份，在同一事务接受 pending operation、保存不含凭证的精确 work payload 并创建 publication 初始事实；command idempotency/readback 复用原 request key；pending work 可用 SQL 租约认领/续租，以 claim token fencing phase 更新，并在三阶段全部成功后原子完成原操作、保留可回读终态 publication 与完成审计。确认失败且没有 unknown 阶段时，也可原子拒绝原操作、清除临时工作/租约并写拒绝审计，同时保留 publication 阶段事实；unknown 仍不可被终态拒绝。已新增 Nacos/Consul 精确目标持久化表、验证来源/映射 revision 的 SQL reader，以及只供可信服务器配置使用的 compare-and-set writer；pending publish payload V2 同事务冻结 provider target、target mapping revision 和 registered-source revision，缺失/过期/类型不匹配目标 fail-closed，后续配置变化不会重定向已受理工作。**本轮补齐带 admin/CSRF/idempotency/audit 的 `configure_target` 规则命令、受会话保护的 target read API、React 目标管理面板和独立三语表单；SQLite/ASGI 与 Mock HTTP 定向测试通过，见 §15.289 及 [目标管理验收](acceptance/R-SENTINEL-CONSOLE-B0.3-target-management.md)。**`ResolveRegisteredSourceConnection` 只按冻结 source ID/revision/provider 解析注册来源，并将部署凭证引用短暂解析为直接连接参数；严格、确定性的 Console Sentinel same-kind JSON array 编码器可将五类 `RuleSetVersion` 投影为规则字段并拒绝 profile 错配/不活动条件字段；`RunRulePublicationWorker` 已实现应用层阶段编排，执行中的 active lease 按租约周期续租、失去续租能力即停止执行（§15.296）；worker/outbox/SQL mutation store 定向 suite **36 passed**（§15.297）；`ConsulRulePublicationProvider` 已将既有 reader/writer 映射到 worker Port。worker 现在必须声明有限 `supported_providers`，SQL outbox 在认领阶段按冻结 target.provider 过滤，并由 `RulePublicationProviderRouter` 显式按目标 provider 路由（§15.268），避免一个 provider worker 抢占或误调另一 provider 的 pending 命令。新增 `create_consul_rule_publication_worker` 显式装配 SQL readers/outbox、Consul CAS/read-back adapter、source revision/credential resolver 与规则 profile encoder，要求部署方提供网络 target policy 并将 worker 注入 ASGI app（§15.269）；它不创建数据库、选择 DNS allowlist 或自动启用 worker。写结果未知时 worker 只读对账、绝不盲目重发。**新增 PLAN-EXEC-02 窄故障窗口回归：发布 outbox 已成功而 plan publication link 尚未写入时模拟 worker 丢失；租约到期后新 scheduler 恢复同一 publication，验证 operation/publication 及 accepted/completed phase audit 各仅一份、plan 只在 read-back 成功后推进（§15.324）。**Nacos 现增加独立 `NacosRulePublicationProvider` 与可选 `nacos-grpc` transport：固定目标复用 DNS pin、gRPC 端口需单独授权，非空 provider MD5 执行 CAS，收到成功响应后用 Admin HTTP 精确读回；Nacos 3.2.3 blank `casMd5` 是非 CAS，因此“新建 key”明确拒绝。gRPC transport 现按官方连接生命周期先执行 `ServerCheck`，再通过 bidirectional stream 发送带 namespace/source label/SDK 能力表的 `ConnectionSetupRequest`；协商开启时收到 `SetupAckRequest` 后必须回送带相同 requestId 的 `SetupAckResponse`，否则不发配置写入；协商关闭时采用 SDK 的 100ms 注册等待，然后才发 unary CAS。transport 协议定向 suite **12 passed**，provider/reader/policy/router/worker composition suite **43 passed, 4 skipped, 3 loopback tests deselected**；在 Nacos SDK 3.2.0 环境核对 protobuf schema、setup 请求/响应与注册顺序、setup 失败不发配置写入。**新增 PLAN-EXEC-01/08 真方言验收：**两个独立 SQLAlchemy connection pools 在 PostgreSQL 16 与 MySQL 8.4.11 上竞争活动计划租约，首次恰有一个 owner；到期接管也恰有一个新 owner，旧 token 续租被拒；另由两个 scheduler worker 同时运行竞争计划，只有赢家调用 SQL-backed publication enqueuer，输家无调用。MySQL 曾暴露 DATETIME 截断毫秒导致的租约边界错误，已通过迁移 `0020_millisecond_worker_leases` 与模型 `DATETIME(3)` 修复。**publication instance receipt 的 SQL store/分页读模型和 MySQL `DATETIME(3)` 毫秒往返现已实现，见 §15.480；Reporter/Collector 写入装配及权威 inventory 仍未完成。**跨方言结果为 PostgreSQL **7 passed**、MySQL **8 passed**，本次 receipt 窄验收 PostgreSQL/MySQL 各 **1 passed**，SQLite worker/store 回归此前 **38 passed**（§15.460、§15.467、§15.480 与 [活动计划验收记录](acceptance/R-SENTINEL-CONSOLE-B0.3-activation-plan-persistence.md)）。此证据不覆盖完整独立 ASGI 多 worker 生命周期、provider 真 CAS/未知结果恢复或 Reporter/Collector runtime ingress；Nacos create-only/真实 gRPC+TLS、真实 provider acceptance 仍未完成。B0.3 保持未勾，最终 E2E 未完成。详见 §15.264、§15.289、§15.324、§15.347、§15.460、§15.467、§15.480 与 [B0.3 provider conditional-write 记录](acceptance/R-SENTINEL-CONSOLE-B0.3-provider-conditional-write.md)。
- **B0.3 后续验收：**PLAN-EXEC-04 先有 worker conflict-after-read 单测（§15.461），再贯通 SQLite SQL plan、scheduled outbox、publication worker、scheduler recovery，证明竞态 CAS 被拒绝后计划持久化为 `blocked`（§15.462）；PLAN-EXEC-06 证明激活后、恢复前发生外部变更时，SQLite publication worker preflight 零写入并阻塞计划（§15.463），且 PostgreSQL/MySQL 两个 scheduler connection pools 在计划 blocked/lease cleared 后均领不到恢复 phase（§15.464）。provider 替身不是 Nacos/Consul 真 CAS，PG/MySQL 只验证真实 queue 而非完整 outbox 链；B0.3 仍未完成。
- **B0.3 PLAN-EXEC-07：**新增跨真实 SQL 方言的双向竞争验收。claim-wins：取消命令完成首次授权与幂等读取后暂停，独立 queue 池领取到期计划，再恢复取消；取消以 `conflict` 拒绝，claim 继续创建并关联一个 pending publication，持久计划保持 `activating`。cancel-wins：对到期计划持有真实事务行锁，取消命令处于 in-flight 等锁期间让独立 queue 查询；`SKIP LOCKED` 不得领取，释放锁后取消成功，之后仍无 activation claim。PostgreSQL 16、MySQL 8.4.11 各 **1 passed**；SQLite activation-plan command/scheduler 选择 **5 passed**。PLAN-EXEC-07 的数据库状态竞争准则已验证；B0.3 父任务仍未完成。见 §15.465 与 [B0.3 验收矩阵](acceptance/R-SENTINEL-CONSOLE-B0.3-activation-plan-persistence.md)。
- **B0.3 PLAN-EXEC-03：**新增完整 SQLite SQL plan→publication/outbox→worker→scheduler 恢复链：provider double 模拟 CAS 已在远端生效但返回 unknown；publication 持久化 unknown，计划仍 activating；到租约恢复后同一 publication 读到候选规则，不二次写 provider，仅在 read-back 成功后推进为 active。operation/publication/audit 均断言唯一。此处仍是 controlled provider，不证明真实 Nacos/Consul transport 或 OS 进程崩溃恢复；PLAN-EXEC-03 保持 partial，B0.3 不勾。见 §15.466 与 [B0.3 验收矩阵](acceptance/R-SENTINEL-CONSOLE-B0.3-activation-plan-persistence.md)。
- **B0.3 PLAN-EXEC-01：**在 PostgreSQL 16 与 MySQL 8.4.11 的真实 DB acceptance 中新增两个 scheduler worker 的受控竞争：赢家停在 publication port 时，独立 SQL pool 的输家完成调度但返回空结果；释放赢家后只产生一份由真实 SQL mutation store 创建的 pending publication，并关联到 activating plan。两个方言各 **1 passed**；与既有双 queue 单赢家/租约接管一起覆盖 PLAN-EXEC-01 的数据库与 scheduler 边界。SQLite mutation store、publication worker、activation-plan lifecycle 与 worker contract 定向回归 **45 passed**。仍未以独立 OS 进程运行，PLAN-EXEC-08 的 publication phase fencing 也未因此关闭；B0.3 不勾。见 §15.467 与 [B0.3 验收矩阵](acceptance/R-SENTINEL-CONSOLE-B0.3-activation-plan-persistence.md)。
- **B0.3 PLAN-EXEC-10（更新）：**§15.481 已在 PostgreSQL 16/MySQL 8.4.11 上启动两个真正独立的 `build_app` ASGI lifespan，门控后并发轮询同一 due plan，并验证只有一个持久发布副作用。§15.479 的“未模拟两个 ASGI lifespan”是当时有效的历史边界，现由 §15.481 扩展；进程在真实 provider effect 中途崩溃及跨进程 provider 阶段恢复仍未覆盖，故 PLAN-EXEC-10 仍 partial。
- [ ] **B0.4** 实现实例目录/同口径观测/历史与实时查询/故障事件/系统健康/协议审计；无法采集的 p95/TPS/scope 显式 unavailable，不造假值。系统连接页已从真实登记表读取 Nacos/Consul；对已保存且未变更配置的 admin probe 保存短期、无凭证结果，并按 source revision 投影状态/延迟/能力，候选配置不会污染系统页，revision 变化使旧探测回退 `unknown/no-probe`（§15.282–§15.283）。first-run composition 可注入宿主 reader；SQL audit reader 已默认读取 Console 自己持久化的账号/配置源/规则/校验/初始化事件，并明确允许仅系统初始化事件无账号 actor（§15.285、§15.287）。实例目录、metrics/fleet/incident、Collector 健康与真实协商协议版本仍须接入权威事实源，不注入时维持 unavailable/unknown；B0.4 不勾。
- [ ] **B0.5** live 模式逐页真实端到端、重启/断网/冲突/权限/持久化/计划恢复；对照同一协议正负样例，Mock 不替代真实依赖验收。
- [x] **B0.6** React production assets 随 Python wheel 打包，安装后的 ASGI 静态路由不需 Node；生产 bundle → marker-owned assets → wheel → 隔离安装 → `test_static_web.py` **4 passed** 已验证。精确范围、81 个当前构建资产和未覆盖边界见 §15.459 与 [F7.6 wheel 验收记录](acceptance/R-DASHBOARD-F7.6-wheel-static-assets.md)。此项不代表完整 Console live API、生产 CLI/反向代理、浏览器 E2E 或 PyPI 发布；发布仍须另行授权。

## 8. HTTP Mock 最终形态与完成标准

### 8.1 已确认：作废旧网关，新建 HTTP 实现

**决策已确认，迁移与退役已实施。** 当前 React 消费者已走统一异步 Console HTTP 入口；旧 FixtureGateway、同步 snapshot contract 与未接线 HTTP 雏形已移除，Mock 只在 HTTP 拦截层提供 Console wire 响应，live/mock 共用 feature gateway。后续仍须完成 F6.1/F6.2 逐页 wire 语义审计、真实 Python Console 联调及最终验收；这些不应再表述为“网关实现尚未开始”。

迁移顺序：F1.4 确定异步合同/Provider 依赖 → F2/F4 完成资源与用例 → F6.2 新 HTTP 实现 → F6.3 切换全部消费者 → F6.4–F6.10 集中 seed/请求拦截/两模式验证 → F6.12 删除旧实现与引用。未迁页面在此之前保持可运行，仅是过渡，不能因此勾选网关退役。此决定不把 Python 开发或真实服务请求提前。

逻辑单测可以对 feature Port 使用最小测试替身，但不保留 FixtureGateway 类/接口/单例。应用级 Mock 必须在 HTTP 层拦截，新 HTTP 实现不能内置 fixture 返回、mock/live 分支或 live 失败后示例兜底。

### 8.2 最终请求路径

```text
同一页面 → feature workflow/resource → feature Http gateway → 底座 HTTP
                                                           ├─ mock：网络拦截 → handler → mock state/seed
                                                           └─ live：Python Console
```

计划采用 [MSW 官方 Browser 集成](https://mswjs.io/guides/integrations/browser)：它在网络边界拦截；启动需 await worker.start() 避免首批请求漏网。此处是已选实现方向，**本轮未安装/实现**。浏览器 Service Worker 要求安全上下文（localhost 开发可例外）；其他内网 HTTP 地址的 mock 预览要提供 HTTPS/受控 Mock 服务备选，不能在拦截失败时透传生产。

配置使用一个语义清晰的模式入口（计划 `mock | live`）及 API base URL，最终命名在 F6.7 固化；构建与运行时配置二选一明确，不能声称修改 VITE 环境就能实时切换已打包制品。页面不能 import handlers/fixtures、不能有 mock 判断。live 断网必须显示错误而不是展示示例。

Mock 不产生真实安全隔离/持久化证据：浏览器模拟凭据只用明确合成测试值，绝不输入真实 Nacos/DB 凭证；初始化锁、最后 admin 事务、计划调度、配置回读/实例应用仍须 B0 验证。前端实现完整 ≠ Python 完成 ≠ 已发布。

## 9. 进入下一任务的顺序与打勾规则

F0 → F1/F2（责任与状态边界）→ F3/F4（按完整用户路径逐页迁移）→ F5 收口 → F6（协议反推、集中 Mock、HTTP 接线）→ F7（前端验收）→ B0（Python 实现/真联调）。相关测试每个切片就写/跑，F5/F7 是全工程收口，不是拖到最后才测试。

F1/F2 允许先明确页面所需的内部 async Port/错误状态；这不是提前实现后端/冻结 wire，更不是此时批量抽取所有 Mock。未迁旧路径仅暂时保持可运行，不继续扩展 FixtureGateway；最终在 F6 收敛为新 HTTP 实现与网络拦截，并删除旧网关。

每次推进记录任务 ID、代码/正式文档、运行命令/实际结果及未验证边界。结构迁移需行为/视觉保护；交互新增需成功与关键失败路径；只写文档或 build 绿不能勾页面功能。F0/F1 五项已完成，继续 F1.4/F1.6/F1.7 与 F2 的消费者、F3/F4 切片；用户要求自动推进至全部 E2E，但不自动 commit、发布、配置真实 Nacos/Consul 或初始化用户数据库。真实依赖验收使用隔离的本地测试拓扑。

### 9.1 测试反馈节奏（2026-10-09 更新）

- 按一个可独立审查的改动切片集中修改，切片完成后验证一次；不要每编辑一个文件就重复跑回归。先识别改动边界，只运行该边界需要的检查：前端代码切片执行 `npm run check:fast`，再跑受影响的逻辑/HTTP 用例；Python-only 切片只跑受影响的 Console unittest 模块与必要的 `compileall`，不触发无关的前端全套检查；纯文档切片不运行应用回归，按链接/命令/状态事实做定向核对即可。跨 feature/跨层切片才扩展到相应完整套件。
- 前端定向命令使用 `npm run test:logic:focused -- '<测试标题正则>'` / `npm run test:http:focused -- '<测试标题正则>'`；runner 会先验证至少有一个标题匹配，禁止零用例空跑成功。Python 切片优先使用 `python -m unittest tests.test_<受影响模块>`；迁移、事务、跨模块合同等风险无法由单模块覆盖时，再加对应 SQLite/真实隔离数据库集成用例。OpenAPI 或生成合同变更需跑 `npm run contract:check`，并运行对应 Python API 测试。
- milestone 前端静态收口执行 `npm run check:milestone`（完整非浏览器质量门禁，兼容入口 `npm run check:full`）；Console milestone 执行完整 `python -m unittest discover -s tests -v`，并按该 milestone 的风险矩阵运行 PostgreSQL/MySQL 等隔离依赖测试。两组门禁互不替代；仅执行受影响一侧时，不为了形式强制跑另一侧。
- 完整浏览器 E2E 与真实端到端验收统一留到全部计划代码完成后的最终验收，不在中间 milestone 重复执行，也不作为每次代码改动后的回归门禁。开发期间按改动范围运行 focused 单测/HTTP/契约检查和 `check:fast`；需要时可执行非浏览器的 `check:milestone`，但不得将其称为最终 E2E。最终验收前确认测试环境/依赖准备好，集中执行一次完整旅程；失败时只针对失败域修复并做聚焦验证，必要时稳定后再复跑最终旅程。浏览器路径只能使用 Codex 内置浏览器；不调用 Chrome、Edge 或 CDP。日常单测/HTTP Mock 不冒称浏览器 E2E，IAB 手测也不能替代 Python/数据库/配置中心真实联调。
- 日常反馈按证据成本分层：变更相关的静态检查/格式/lint/契约 → 受影响单测或 HTTP Mock → 必要时本地页面专项检查 → milestone 完整质量门禁与 E2E。每层只在风险或验收目标要求时升级；不得把快速验证描述成完整 E2E，也不得因前一切片的绿灯省略新改动所需的 focused check。

## 10. F0 实施与验收记录（2026-10-07）

### 10.1 责任落点

- `src/features/identity/state/useDemoAccountBootstrap.ts`：由 App 唯一调用的临时演示启动同步，不是新 HTTP 网关，不扩展 FixtureGateway，F6 整体退役。
- `accountStore.ts`：按数据源身份初始化，空列表也算已初始化；显式 load 可刷新；未知目标/同值写入保持快照引用与通知稳定，取消订阅可重复调用。
- identity UI：创建事件只读已捕获依赖，角色选择由 URL 单一拥有；独立角色页/系统角色 tab 共用同一目标语义。未知目标显示空态和返回入口，不呈现写表单。
- applications/realtime：删除未知实例回落；空目录显示三语提示；回放无数据时不启动 timer，数据恢复后仍可推进，卸载时释放。
- `eslint.config.mjs`：启用官方 `react-hooks/rules-of-hooks` 与 `exhaustive-deps`，不通过禁用规则或 suppression 收绿。TS 7 超出当前 typescript-eslint parser peer 范围，因此用 Babel 8 做语法解析，tsc 负责类型检查；完整类型感知 lint 仍待 F5。

### 10.2 当前验证证据

| 检查                            | 实际结果                                     | 证据范围                                                                                                                                                                                                   |
| ------------------------------- | -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `npm run check`                 | 通过                                         | typecheck、Hooks lint、lint 负例 3/3、逻辑 6/6、三语各 522 键、build、Sites 4/4；主 JS 1,300.61 kB / gzip 397.42 kB，大包警告留 F1 分包收口                                                                |
| `npm run test:e2e`              | **62/62，通过**；含新增 F0 回归 9 条         | Chrome 本地示例页面，含真实鼠标/输入交互、URL 与 DOM 状态等待、空回放生命周期；不证明后端身份/事务/真实配置中心                                                                                            |
| 5 页前后截图                    | 像素一致 5/5                                 | accounts、roles、change-password、applications、realtime；1280×900 CSS px，CDP scale=1；已查看账户与角色截图；不是全响应式/全部交互态验收                                                                  |
| DOM 比较                        | 3/5 原样相等，另外 2 页仅 React 控件 ID 变化 | roles/change-password 将生成 ID 独立归一化后完全相等；未改基线或掩盖 stylex/class 差异                                                                                                                     |
| `node --test tests/api/run.mjs` | **历史快照：18/20；两条旧断言不成立**             | 当时针对未装配 provider 草稿：一条要求把数值 `grade` 改成字符串类型，另一条把 404 当作 `version_conflict`。草稿和测试入口后续已按 §15.16 退役；此行仅保留历史，不是当前失败测试。正式合同按 F6.11/§15.163 核对，Python provider 语义仍属 B0.3 |
| 依赖/保护文件                   | 直接运行依赖版本未变，npm ls 无 peer 冲突    | 新增 lint 开发依赖与显式 esbuild；Node 要求 ^22.18.0 或 >=24.11.0；未改 src/styles.css、hosting、worker、Sites 打包脚本和测试                                                                              |

截图分别保存在 `/private/tmp/sentinel-f0-before-20261007/`、`/private/tmp/sentinel-f0-final-20261007/`（临时目录，非长期制品）。完整浏览器脚本为 `tests/e2e/app.e2e.test.mjs`，门禁负例为 `tests/lint/hooks.test.mjs`，状态逻辑回归为 `tests/logic/`。

### 10.3 未扩大完成范围

F0 仅修正当前路径的正确性。FixtureGateway 仍冻结保留，未删除、未新增其 API；临时同步装配不代表 F1/F2/F6 完成。刷新仍恢复演示数据，登录/改密仍是示例；未实现真实会话权限、最后管理员保护、请求拦截、Python Console、Nacos/Consul 接线或数据库初始化。原有 `CONSOLE_API_CONTRACT.md` 修改与 provider 测试保留，不以本轮修复为其签字。

## 11. F1 实施与验收记录（2026-10-07，进行中）

### 11.1 编码前边界与测试矩阵

先实施 F1.1–F1.3：`main` 只挂载；`app/providers` 拥有稳定装配；`app/shell` 拥有导航、用户入口、在线提示与示例横幅；`app/router` 拥有页面 lazy/Suspense/错误恢复。保持既有展示与 URL，不提前建立 HTTP 实现或扩展 FixtureGateway。GoF 逐项评估后，此切片只复用已有 Provider/组合边界，不新增业务模式或基类。React ErrorBoundary 类仅承担框架异常捕获，不承担业务编排。

| 验收 ID      | 风险/断言                                                                                                      | 层/证据                           | 清理                 |
| ------------ | -------------------------------------------------------------------------------------------------------------- | --------------------------------- | -------------------- |
| F1-BOOT      | main 不创建服务；依赖装配身份稳定；StrictMode/重渲染不重复初始化                                               | 源码结构门禁 + 实际浏览器         | 关闭独立测试页       |
| F1-SHELL     | 六导航/语言/用户入口、横幅/页脚、登录/setup 无壳保持                                                           | 完整交互回归 + 29 态 DOM/像素     | 临时截图目录独立保留 |
| F1-ROUTE     | 路由 lazy；loading、chunk 失败/重试、页面异常、换路由恢复；未知路由有明确恢复                                  | 注入最小加载器的边界测试 + 浏览器 | 卸载探针/释放监听    |
| F1-BUILD     | 主包变化和页面 chunk 可核对；类型/Hooks/逻辑/i18n/Sites 通过                                                   | build 清单 + `npm run check`      | 不更新坏视觉基线     |
| F1-DIRECTION | shared 导航意图/观察窗口契约不依赖 app；feature 不引入路由实现；model 不引用图表/React；显式临时退役债务受检查 | AST 依赖正/负例 + 全源图检查      | 无外部数据           |
| F1-STRICT    | noImplicitAny 严格启用；Consul 草稿任意类型输入不会读取原型键；格式/路径约定一致                               | 类型检查 + 校验正/负例 + 格式检查 | 不访问 Consul        |

此矩阵不证明 Python、配置中心、数据库或生产授权；全部开发完成后的真实 E2E 仍为 B0 必需门禁。

### 11.2 已落实与尚未验收边界

- main 仅挂载 StrictMode/AppProviders，底座配置为应用级稳定对象；七 feature 公开页面入口的 11 loader 经 RouteBoundary 装配。identity 演示 bootstrap 独立出口，不为启动同步拉入五个身份页面。
- 壳拆为 AppShell/Header/Navigation/UserMenu/StatusBanner/Footer；已有导航、语言、浏览器在线提示和示例横幅保持，用户菜单仍为演示占位，不声称真实 session。
- shared/navigation 是路由意图、观察窗口和值契约的唯一来源；feature 不再依赖 app 路由/i18n 类型。图表/标签/格式化投影迁入 presentation/i18n；identity 角色、数据库、来源、认证方式、setup 步骤文案也已从 model 分离。角色权限与数据库默认端口/适用性仍由 model 唯一拥有，投影穷尽校验已加入逻辑测试。规则数字领域值、编辑表单与编辑会话现已分别落在 `model/` 和 `editor/`，运行时 UI 文案留在 presentation/i18n（§11.5/§15.27）。
- AST 依赖门禁覆盖 static/export/type/dynamic import，含正负例与过期豁免校验。目前 17 条**精确** core 旧路径债务逐条关联 F6.11/F6.12；不允许新 reverse/private edge。此结果不是 core 已解耦，F1.7 不勾整项。
- strict/noImplicitAny、`@/` 路径别名、源码及浏览器 TS 探针格式/Hooks/typecheck 已进入门禁；Consul 类型守卫拒绝任意输入和 Object 原型键，未访问外部 Consul。
- `npm run check` 实际通过：32 条逻辑、3 条依赖门禁、3 条 Hooks 负例、4 条浏览器工具负例/清理、三语各 529 键、build/Sites 4 条；最近主包 765.44 kB / gzip 227.61 kB，图表独立 337.74 kB。主包超 500 kB 警告仍待 F5.6，不改阈值藏警告。
- 既有及新增 F1 浏览器用例 **79/79 实际通过**；新增 F2 React 生命周期用例首次全量 run 为 **79/80**，失败原因已由 Vite 日志确认：探针首次直接加载底座包触发依赖优化/整页重载，销毁探针。已将两个既有底座依赖列入预优化，单项复跑通过；当前继续全量复跑，不以单项通过覆盖失败记录。
- 最终结构/格式版本 29 态截图已复跑，全部 settle=2；与 `/private/tmp/sentinel-f1-before-20261007/` 比较像素 **29/29 一致**，当前截图 `/private/tmp/sentinel-f1-final-20261007/`。已查看账户页截图；1280×900，不代替 F3 响应式/200% 验收。DOM 经历史兼容归一化 **29/29 一致**；旧捕获抹掉 ID，其 ID/ARIA 关系不可恢复，不假称这部分已由旧 DOM 证明。当前 11 路由的真实控件 label/ARIA 唯一引用另由浏览器 11 条用例验证。
- Vite 预优化修复后全量浏览器 **80/80 通过**（无 skipped/cancelled）；F1 五项据此与最终像素证据勾选。之后共享查询 Hook 又补“新查询首个 commit 不显示旧身份数据”的防护及 5xx 写结果未知语义；38 条逻辑已通过，增强浏览器断言继续复跑，不用旧 80 条结果冒充新断言已验收。

验收工具修复：删除 E2E after 中强制成功退出；Chrome 启动 SIGABRT、命令超时、捕获未收敛均退出非零；CDP pending/listener/timer 与 Chrome 子进程/专用临时 profile 有界清理。保留失败记录，不给坏截图刷新基线。sandbox Chrome 不能启动，本机实际浏览器验收使用经授权的隔离进程；不更改或复用用户 Chrome profile。

DOM 工具新增 4 条正负例：保留真实 ID、控件引用、class/style/文字与 SVG 引用差异；先剔除 HMR 噪声再编号 React ID；新捕获同时保存 `.raw-dom`。只有历史快照兼容路径沿用旧策略，并在 compare 明示其证据限制。未修改旧基线文件、像素阈值或使用 ACCEPT_DOM/ACCEPT_RENDER。

### 11.3 F2 资源边界（先行测试，不代表页面已迁移）

`shared/state/queryResource.ts` 组合已发布 ObservableResource/StateStore，按完整 key 保留至多一份可信数据；401/403 丢弃旧值，换会话/环境/应用/实例/scope/window 不串数据；取消、reset、dispose 防迟到写回。`receivedAt` 为本地收到时间，不伪装成远端采样时间。

`commandResource.ts` 拥有重复提交与成功/失败/冲突/结果未知状态，不复制、持久化或记录秘密表单。已发写请求取消/断网/超时不等于服务端回滚，不自动重放；结果未知需显式核查再确认。feature 用例与服务端幂等/操作查询仍需各自完成。

| 验收                                                                      | 当前层                             | 不能替代的后续门禁                               |
| ------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------ |
| 查询状态、同 key stale、六 key 维度、迟到、拒绝清空、超时、无操作引用稳定 | 实际 TS 源码逻辑测试               | 各 feature Port/resource 消费者及网络响应 schema |
| 重复命令、409/422、断网/超时 unknown、取消后迟到成功无效                  | 实际 TS 源码逻辑测试               | 各页写表单、幂等键和 Python 事务                 |
| StrictMode、换查询取消、卸载后响应                                        | 实际 Hook 浏览器探针，继续全量验证 | 全部正式页面与最终 HTTP/live E2E                 |

这些组合器尚未替换页面旧同步取数；F2.1/.2/.3 保持未勾，不能用共享工具单测替代逐页完成。

### 11.4 F2 路由所有者与诊断上下文

- `routeSnapshot.ts` 替代按 hash 的模块全局缓存：每个路由所有者有一个有界缓存，key 包含 hash、默认账号和应用目录语义；同值保持快照引用，换默认账号/目录不返回旧值。显式未知账号/应用不回落别的对象，空目录保持空态。`useHashRoute` 已消费这条新路径，不保留 reset 全局缓存兼容函数。
- 白名单增加 env/instance/resource/event/version/scope/q，与 app/range/account/view 一起解析/编码；未知 query（包括 password/token）不进入导航合同。资源内 `?` 不再被 split 截断。秘密值仍禁止由调用方放进任何白名单字段。
- `Navigate` 支持第三参 history=push|replace 和可选 scroll；native replace 保留 history.state，并显式通知 external-store，因为 replaceState 本身不触发 hashchange。离散下钻 push、高频搜索 replace；跨页清理私有 view，显式 undefined 清目标，观察上下文保留。
- 浏览器探针使用实际 Hook/native history，已验证默认身份变更、完整诊断上下文、history.length、replace、显式清理与两次 back；同批增强资源首个 commit 不显示旧身份值。两条 focused E2E 均通过，正式 81 条全量复跑全部通过（0 fail/skip/cancel）；这是当前前端浏览器回归，不是 Python/配置中心真实联调验收。
- 最新 `npm run check` 通过：40 条源码逻辑、依赖 3、Hooks 3、浏览器工具 4、DOM 工具 4、三语 529/locale、构建与 Sites 4；最近主包 765.86 kB / gzip 227.87 kB。这个增加的字节数来自实际路由能力，不调告警阈值隐藏。

F2.5 整项仍未勾：URL 合同/基础效果已落地，但各页环境/实例/事件/版本的实际筛选、下钻、不存在目标和未保存表单保护尚需 F4 的消费者闭环，不能只用序列化单测宣称页面完成。

### 11.5 规则表单职责与校验（F1.6 / F4.07 部分交付）

- `model/ruleValue.ts` 拥有只读、数字类型的领域事实和不依赖表单的规则事实校验；`editor/ruleDraft.ts` 从它派生可空表单字段，不复制整套字段；`TypedRuleDraft`/`RuleWorkbenchEntry` 用映射判别联合绑定类别与内容。草稿类型、编辑校验、物化、单条/整组编辑状态机统一归 feature `editor/`，model 与 API 不再导入表单类型或通过临时草稿校验 wire 规则值。删除 `narrowDraft` 与 `{ } as RuleDraft`，TypeScript 正/负例保证错误配对不通过。
- `editor/ruleEditing.ts` 是纯草稿会话转移；`useRuleWorkbench` 唯一拥有目标、草稿、编辑状态与校验结果。类别/基线变更在 children commit 前收敛，不依赖 Effect 暴露上一个规则的草稿，也不复活已放弃会话；实际 StrictMode/LayoutEffect commit 探针通过。只调整当前组件 state 的条件保护遵循 React 官方模式，不写外部 store/DOM。
- 本地校验覆盖有限数、空值/布尔/非法数、数值枚举、正整数窗口/请求数、并发整数、条件关联/慢启动/排队字段、集群窗口等分、熔断比率、系统 -1/CPU 单位、来源分隔与参数例外必填/重复。领域仅产出稳定 issue code/path；三语消息与字段 ARIA 状态在 UI/Astryx 适配层处理。
- Astryx 数字框在规则表单允许分数和真正清空（null → 空输入，非 zero）；字段错误采用官方 status/ARIA，不新增全局样式覆盖。参数例外有稳定 formKey，编辑内容不更换 DOM 身份；该表单标识从预览剔除，不充当服务端 ID。
- 数字领域值不意味着“任何取值可发布”：现有本产品正阈值策略保持，Java Sentinel 某些零阈值合法性的差异不隐瞒。目标 runtime/codec 的支持矩阵、服务器资源上限、正式 wire mapper 与发布验证仍在 F4/F6/B0 收敛，不能把本地预览当完整规则集发布。

| 证据                                    | 当前结果                                                                    | 未覆盖范围                         |
| --------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------- |
| 源码严格类型与逻辑测试                  | 47/47；含七类规则边界测试和类别配对编译负例                                 | 外部 JSON runtime schema、真正发布 |
| 五类表单原生输入/失焦/字段 ARIA         | 5/5；首次 system 测试因测试标签遗漏“阈值”失败，修正到当前正式标签后重跑通过 | 新增/整组编辑/版本/冲突            |
| 分数与键盘清空                          | 1/1；预览为 1.5 / 空字符串，空输入显示校验错误而不是零                      | 完整统一字段布局 F3                |
| 草稿首次 commit / StrictMode / 空与返回 | 1/1；所有 commit 的目标类别等于草稿类别，无 Effect 延迟                     | 未保存导航确认、远端基线冲突 F4.08 |
| F2 前置视觉保护                         | 29/29 DOM 与像素一致；新捕获含 raw-dom，旧侧 ID 信息缺失已显式报告          | 后续规则控件变化的新视觉比较待执行 |

参数稳定行、内容编辑保焦点、删除相邻行和预览不泄漏 formKey 的 focused E2E 已通过（1/1）；首次测试误把标题作为 first-child，修正选择器后重跑。该段保留当时证据；当前统计以 §7 为准，不能把局部绿色回归称最终 E2E 已通过。

### 11.6 F1 值选择边界与 F2 认证工作流（部分交付）

- `Select` / `RadioGroup` 的字符串回调由 `valueSelection.ts` 对实际选项目录做成员校验，不用类型断言传递未经检查的 vendor 值，也不拿翻译标签当协议值。数字枚举的字符串转换属于 rules 字段适配，共享组件不隐式强转。TS 正/负例与逻辑测试覆盖未知角色、非法数字、原型键和标签，15 条聚焦浏览器验证覆盖集群、setup、角色与三语选择。
- identity 新增 `IdentityAccessPort`、`controlPlaneAccess`、`accessResource` 与 `authenticationWorkflow`。初始化/匿名/认证中/会话恢复/已登录/过期/不可用事实分离；坏存储或连接故障不会推断 admin，更不能重新开启 setup。sessionEpoch 是非秘密所有权标识，不是令牌。
- 一份 AuthenticationWorkflow 组合现有 query/command owners。登录 POST 成功之后仍需独立会话回读并匹配身份；退出立即撤掉私有身份。已发写请求超时/断网/取消为未知结果，不自动重发；显式 inspectSession 只观察当前会话，不宣称证明上一次全部副作用已完成。回读不一致/失败进入可恢复 unavailable，不停在无期限 loading。
- `AuthenticationProvider` 只订阅注入的稳定工作流，StrictMode 清理取消观察，不复制会话，不永久 dispose 将被立即复用的 owner；最终 disposal 归创建者。`authentication.ts` 是 app 的轻量装配出口，避免同步拉入五个页面。首次 bootstrap Hook 是独立读资源探针，不应与工作流在同一生产 app 同时创建两个会话 owner。
- 本批 `npm run check` 实际通过：类型/格式/Hooks、架构 8、逻辑 **78**、工具/三语 554 键、构建/Sites；主包 781.72 kB / gzip 234.04 kB，大包警告仍属 F5.6。bootstrap Hook 浏览器 2/2、认证 Provider/workflow 浏览器 2/2 均通过；后者实际鼠标/输入/StrictMode 验证重复提交、确认前禁止准入、退出、未知结果核查及不呈现原始异常。完整浏览器回归继续执行，不能用聚焦结果替代全量。

这些内部 async Port/工作流尚未装配到原型的旧同步页面；F1.4/F2.4/F4.22–24 **不勾整项**。旧 SessionProvider/demo 登录尚在 F6 待退役；没有 HTTP、Python 或生产授权完成的含义，也未通过包装 FixtureGateway 提供新能力。

## 12. 皮肤、组件与布局实施证据（F3）

### 12.1 SCSS 单入口（F3.1 完成）

`core/styles/index.scss` 按结构 token → dark skin → reset → Astryx → legacy 装配，`main.tsx` 仅引用该入口。原 `styles.css` 已移除；未迁移选择器归 `_legacy.scss`，不得双轨覆盖。暗色颜色与图表 token 保持原值，默认根节点与 `data-sentinel-skin="dark"` 使用同一皮肤；只预留主题选择接口，没有假称完成浅色皮肤或切换器。结构值不承载业务规则。

引入固定开发依赖 sass 1.105.1，未变更 React/Astryx/Nivo 运行依赖或保护的 Sites 文件。静态 `npm run check` 已通过：严格类型、格式、Hooks、依赖、47 条逻辑测试、浏览器工具、DOM 工具、三语、构建及 Sites；完整浏览器与像素回归完成后才勾 F3.1。F3.2 组件 module.scss 与 F3.3 全局穿透覆盖清理仍未完成。

首次完整浏览器复跑 89 条：82 passed / 7 failed，失败均为权限用例之后找不到规则编辑入口。实际失败定位在等待 `.rule-edit-button`，并非输入事件或校验失败；独立标签页共享同 origin 的 localStorage，前置只读身份污染了后续七个写用例。已在每个用例开始清理专用测试浏览器的 origin storage，并加入“只读 → 新用例管理员”的反污染用例；不修改产品授权、不跳过失败、不放宽断言，完整 90 条复跑中。

复跑已完成：**90/90 passed，0 fail/skip/cancel**（165.3s），原七条写用例在完整顺序中通过。这是 SCSS 单入口、规则与前置工程化的前端浏览器证据，尚不含随后应用壳 module.scss 的像素核验，也不是后端真实 E2E。

### 12.2 应用壳样式所有权（F3.2 部分，F3.1 视觉已收口）

`app/shell/AppShell.module.scss` 拥有应用壳、品牌、导航、用户入口、提示栏、内容容器和页脚的 44 条常规/响应式规则；对应 `_legacy.scss` 规则已删除。原语义 class 暂留作既有交互测试钩子，CSS 所有者是局部生成 class；不保留竞争全局定义。shared 与七 feature 的迁移仍待完成，不勾 F3.2。

首次 29 场景截图全部收敛，但仅 login/setup 像素一致，27 个有壳页面失败。浏览器 computed style 证实：(1) 产品 `--color-accent` 被 Astryx Theme 的同名中性色覆盖；(2) 较晚载入的 `.astryx-button svg` 覆盖同权重的导航 SVG 规则。修正为独立 `--sentinel-*` token 命名空间及组件域内更精确的 `main-nav button svg`。失败截图保留 `/private/tmp/sentinel-f3-entry-shell-20261007`，未 ACCEPT_RENDER、未改阈值。

新增 3 条样式架构门禁纳入 `test:architecture`：唯一有序入口、迁移选择器不得回流 legacy、组件颜色必须引用已定义的产品命名空间 token。修正后 `npm run check` 全绿（架构共 6、逻辑 47、三语 537/locale、构建与 Sites 等）。

修复后采集 `/private/tmp/sentinel-f3-fixed-shell-20261007`：29 态全部 settle=2，与 `/private/tmp/sentinel-f2-final-20261007` **像素 29/29 一致**，未使用 ACCEPT_RENDER，未放宽阈值。已查看 accounts/rules 实际截图，品牌蓝色与导航恢复。DOM 原始比较不等价，逐项审查仅为壳 module 生成 class、官方 detached status 移除旧附着状态 wrapper、熔断数字框增加正确 `aria-valuenow="10"`；使用显式 ACCEPT_DOM 与原因记录接受这些有意结构变化，没有扩大归一化抹除规则。1280 宽的旧导航截断仍保留为 F3.7 待修缺陷，并非响应式已验收。

### 12.3 shared / feature 样式归属（F3.2 已验收）

剩余展示规则已按共享组件与七个 feature 迁入 20 个局部模块（加壳共 21 个），颜色值移到 dark skin 的独立语义角色。跨页面展示原语归 `shared/ui/styles/Presentation.module.scss`，不导入其它 feature；`scopedClasses` 仅组合 CSS-module 与稳定语义 hook，模块数组在文件级固定，不操作子元素、DOM 或全局注册表。`_legacy.scss` 已空后删除，单入口不再载入竞争全局选择器；旧原生规则包装、Recharts 等无消费者样式同步移除。

先行 6 场景像素：4 一致，applications/account 失败，未接受坏图。应用实例表与 DataTable 基础单元格同优先级、身份标题与 Intro 同优先级，拆分后加载顺序改变；已为明确的 feature modifier 建立优先级，不依赖谁最后 import。修正后的两场景像素一致，未 ACCEPT_RENDER。完整捕获 `/private/tmp/sentinel-f3-owner-final-20261007` 29 态 settle=2，与 fixed-shell 像素 **29/29 一致**；raw DOM 沿既有归一化核对，仅 CSS Modules 生成 class 与 class 空白变化，显式 ACCEPT_DOM 记录原因，未改归一化器或像素阈值。新增跨 lazy 页面顺序的 computed-style 回归已单项通过，完整浏览器仍在执行，不提前勾任务。

`npm run check` 通过：架构 7（含全模块颜色/作用域/已定义 token 与 legacy 退役门禁）、逻辑 48（含 class 组合、原型键与无 mutation 负例）、Hooks 3、浏览器工具 4、DOM 工具 4、三语 537/locale、构建/Sites。主包 769.85 kB / gzip 229.93 kB，超限警告继续列为 F5.6 待办。后续 F3.3 控件覆盖、F3.4 对齐、F3.7 响应式仍未验收。

迁移后的 `npm run test:e2e` 完整执行 **91/91 pass，0 fail/cancel/skip，165.35s**。包含新增跨 lazy 页面的样式顺序场景、五类表单数值/ARIA、账号流、资源取消与首次 commit、三语等原有回归。至此勾 F3.2；这是本地示例前端，不证明 HTTP Mock、Python 或真实配置中心接线。

### 12.4 表单布局切片的实施与验收设计（F3.3/F3.4）

布局能力归 shared UI：复用 Astryx Field 的 label/description、control、detached status 三段结构，通过受控 FormGrid 的 CSS subgrid 为同排字段共享各段高度；不为帮助文案写固定高度、不穿透修改原生输入框背景/边框、不在 feature 写 Astryx 内部选择器。容器窄时单列重排，与 viewport 独立。厂商结构依赖只在中央适配文件，公开 width 参数用于填满字段。集群布尔项不与数值框混为同一字段排；后台协议和业务校验不属于布局组件。

| 风险                                                    | 最小验收                                                                         |
| ------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 帮助文本长短、三语换行、detached error 导致同排控件错位 | 浏览器比较控件 top/bottom；填空触发字段错误后复测，不用 DOM 存在冒充对齐         |
| 集群数字框聚焦轮廓冲突与 checkbox 被全局规则影响        | 实际输入/键盘聚焦截图 + computed style；仅改已确认冲突点                         |
| 规则面板、Dialog、初始化表单不同容器宽度                | 容器宽/窄截图及溢出断言，焦点和输入值保持                                        |
| 原规则数值与候选预览变化                                | 原五类规则行为用例继续通过，空数值仍拒绝保存；布局不承担校验                     |
| 枚举参数仍用裸编码、热点错误提供并发选项                | 集群阈值用正式三语枚举名称；热点只提供当前策略支持的 QPS；类型/逻辑/浏览器正负例 |

这是一轮明确的布局改善，不要求与旧错位像素等价；保留旧截图做差异核对并逐项查看新图。不新增页面基类、全局表单注册表或 DOM 后处理器。

2026-10-07 已实施：所有五类规则、集群子表单、账号创建、初始化步骤共用 FormGrid。集群阈值改正式下拉（单机平均额度 / 集群总额度），热点仅提供 QPS；三语字段名称与解释更新。Checkbox 不与数字项混排，Radio 卡片只给公开 RadioListItem slot 着色。规则搜索框改为拥有尺寸的外层容器，删除 `.search input` 和未消费的原生 select 覆盖；保留产品按钮及页面布局皮肤，没有再次全局删除样式。

全局 reset 只拥有字体继承、指针和键盘焦点；中央 `_astryx.scss` 记录 0.6.1 Field 三段结构、两层事件按钮 span、Dialog 公开布局 slot 等依赖。数字/文本框仅屏蔽已证实冲突的内层原生 outline，官方 wrapper 焦点仍在；架构门禁阻止 feature 穿透 input/select/label 或 Astryx 内置类。以当前源码和实际边框盒为证据，不用原生 input 的内缩坐标误判 Selector 对齐。

聚焦浏览器验证：五类规则 invalid 数值/ARIA/对齐均通过；集群开关、两类下拉、写入预览和聚焦通过；账号及初始化三个步骤通过。共享组件额外覆盖 zh/en/ja 长 help、detached error、560→260 容器重排，值不丢失。已查看 `/private/tmp/sentinel-f3-production-forms-20261007` 实际截图；完整回归继续执行，尚不以聚焦结果勾选。视觉采集等待有限开场动画结束，不接受半透明过渡帧。

视觉工具门禁同步加固：缺 PNG 必须失败，ACCEPT_DOM 与 ACCEPT_RENDER 独立记录，不再把接受结构差异误报为接受像素差异。7 条工具测试覆盖缺失图片、未授权 DOM 改动和仅 DOM 接受仍需像素一致；没有放宽像素阈值或修改旧基线。

最终 F3.3/F3.4 完整前端浏览器回归 **94/94 pass，0 fail/cancel/skip，178.59s**；静态门禁通过（架构 8、逻辑 49、三语 539/locale、视觉工具 7 等）。据此勾选两项。截图等待动画后重新生成，规则行为未被布局替换；仍是本地示例前端，并非 HTTP Mock / Python / 配置中心验收。下一项 F3.5 尚在实施，不包含在这次 94 条的完成声明内。

### 12.5 弹窗生命周期切片与验收（F3.5）

复用 Astryx native Dialog 的受控开闭、表单 backdrop 防误关闭、Escape 与调用者焦点返回；Frame 只提供一致的 header/content/footer 与尺寸边界。内容超高时仅 body 滚动，标题和提交动作保持可见；小表单不固定拉高到屏幕高度。提交中的关闭规则归 Frame 的 `isBusy` 输入：隐藏关闭入口并拒绝 dismiss，动作是否禁用与结果确认归用例，Frame 不启动请求、不模拟成功。Enter 由原生 form 提交，不能全局捕获 Enter 破坏下拉/IME 或重放命令。

验收包括：320/360/768/1280 实际 viewport + 长日文标题/说明、独立 body 滚动、Tab/Shift+Tab 焦点、Escape 关闭并返回触发器、form backdrop 不关闭、busy 期间 Escape/关闭请求无效、明确完成后关闭、输入值不因布局重排丢失。真实命令 pending/unknown 仍在 F2/F4/F6 后续切片完成，Probe 不代表后端提交验收。

实施复用 vendor 的公开 `useFocusTrap`，只补 Tab 循环，不传 `onEscape`，由 Dialog 独占 dismiss/返回焦点。修复真实 Chromium 在边界 Tab 进入浏览器 chrome 的问题；`Layout height="fill"` 使 body 独立滚动，footer actions 在窄屏换行而不溢出。hooks 子入口显式 Vite 预打包，排除首次动态加载导致 React 双实例与 Invalid Hook Call；没有忽略控制台错误。8 条 Frame 测试与真实“创建账号→角色→状态→返回”合计 **9/9 pass、0 fail/cancel/skip，21.88s**，当前 typecheck/lint 通过。截图 `/private/tmp/sentinel-f3-dialog-20261007/long-{320,360,768,1280}.png`，已查看 320/1280 的实际像素。上一节完整 94 条发生在此改动前，不能冒称为新 Frame 的完整回归；后续批次统一复跑完整套件。

### 12.6 图表共享合同（F3.6 完成）

`trendPlot.ts` 纯投影与 `TrendChart` 渲染分离。缺值/非有限数保留 null 间隙，不归零；零值单点可见，空序列和无效身份给明确反馈。`timestampMs` 采用真实线性时间距离，跨天同钟点仍为不同身份；旧演示 `time` 仅保留其展示点身份，不冒充 wire。单常量域与空域有有限边界，双轴转换仅用于坐标，tooltip/文本表保留原始数值与单位。Nivo 公开 onResize 根据容器调整刻度密度，首尾标签不被裁切，areaBaseline 与坐标域一致，避免填充逃出绘图区。

图表皮肤由 provider 实例内的 theme store 拥有，revision 明确通知刷新，不永久缓存首屏色值、不观察任意 DOM mutation。图表取消订阅由 React 管理。发布标记只能由 feature 显式提供且位于当前窗口；共享组件不再自动捏造 14:02。当前 realtime 明确提供示例事件；overview/applications 的实际发布事实由 F4 补，不能把旧硬编码对比数字当发布接口。

6 条图表浏览器测试覆盖间隙路径、单点/空/非法坐标、真实双轴 hover、主题刷新、320/1280 时间轴。8 条纯逻辑测试覆盖输入不变、比例/缺测、时间身份、边界/Intl 与 store 释放。实际页面截图 `/private/tmp/sentinel-f3-complete-charts-20261007` 的 overview-fleet/applications/realtime 均 settle=2；另有探针截图 `/private/tmp/sentinel-f3-charts-20261007`。已查看实时监控实际像素，保留深色网格、蓝/金线、柔和面积及虚线事件基线。新增可访问文字表、标签密度与响应式顶栏是有意变化，未覆盖旧截图、未用 ACCEPT_RENDER 掩盖回归。

### 12.7 响应式与密度（F3.7 完成）

宽屏保持既定单排导航，1280 长标题采用两排，窄屏顶栏不 sticky、账户入口始终可达；导航自身有界横滚，键盘能进入末个入口。Filters/Panel/Intro/规则 headline/actions 可换行且 min-width=0。规则工作区在受限宽度转单列，实例矩阵不因缩窄丢掉详情。系统 tabs 的局部横滚不再扩展整页。

DataTable 通过 Astryx **公开** transformScrollWrapper 的 htmlProps 标记/命名真正滚动区；不在外层重复创建假滚动区，vendor 继续拥有 role/group、tabIndex 与滚动。键盘 ArrowRight 实际改变 scrollLeft。html scroll-padding 与顶栏结构 offset 共同保证深处字段聚焦不被 sticky 遮挡。

6 条响应式测试：320×800/JA、640×450/DPR2/JA、1280×900/EN 各 11 路由（33 组合）；1920 单排、1280 双排、320 末导航键盘；表格横滚及 sticky 焦点。截图 `/private/tmp/sentinel-f3-responsive-20261007`，已查看 narrow-rules 与 desktop-realtime。640×450/DPR2 是 1280×900 的 **200% 等效布局与物理像素**，不声称测试了系统浏览器 zoom 菜单或所有硬件屏幕。

首次新版全量响应式 5/6 的唯一剩余失败来自 Vite 首次优化 Banner 时重载/双 React 实例；不忽略 consoleErrors。已增加 Banner 显式预优化，稳定源码后完整回归通过。

### 12.8 可复用状态反馈与本批总回归（F3.8 完成）

QueryView 对 idle/loading/empty/filtered-empty/denied/error 不渲染可信业务内容，refreshing/stale/partial 保留同 key 已取得的数据并明确说明；只给 read retry。CommandFeedback 单独处理 pending/success/error/conflict/result-unknown；未知结果只能核查，冲突只能读新版本，不自动重放写。业务说明由 capability 传入穷尽 copy，组件不显示原始异常/业务 payload。RouteBoundary/UnknownRoute 复用 FeedbackPanel，恢复动作仍由路由所有者执行。

Astryx info/success 为 status，warning/error 为 alert；测试按厂商公开合同核对，而非把 warning 错断为 status。320 长日文/动作不溢出，按钮可聚焦且目标 ≥24px；prefers-reduced-motion 生效。标题对比度按真实逐层 alpha compositing 后计算 ≥4.5，而非把半透明 warning 色当不透明背景。3 条反馈浏览器测试通过，截图 `/private/tmp/sentinel-f3-feedback-20261007/long-320.png` 已查看。验证的是浏览器 ARIA/live-region 与键盘语义，不宣称人工跑过 NVDA/VoiceOver。

本批 `npm run check` **通过**：类型/格式/Hooks、架构 8、逻辑 57、浏览器工具 4、视觉工具 7、三语 554 键/locale、build/Sites 4；主包 781.57 kB / gzip 234.00 kB，超 500 kB 警告继续留 F5.6。稳定源码完整 `npm run test:e2e` **117/117 pass、0 fail/cancel/skip，318.80s**（app 94 + chart 6 + Dialog 8 + feedback 3 + responsive 6）。F3 八项据此完成；仍有 69 前端和 6 后端任务，未实现 HTTP Mock/live、Python、数据库或真实配置中心 E2E，不因此标整个目标完成。

## 13. identity 页面用例切片（F4，实施中）

### 13.1 首次初始化的职责和预先验收矩阵

页面容器只组合步骤导航、反馈和动作，storage/admin/source/review 私有组件各持有展示；字段草稿由向导 Hook 管理。纯模型校验网络数据库参数、端口、管理员凭据、HTTP(S) 规则源地址与互斥认证；提交投影仅包含所选 DB/provider/auth 分支，确认密码不进入提交。切 DB/provider/auth 时删除不适用敏感字段，切回不复活凭证。服务端连接验证/初始化锁/保护密钥仍由 Python 所有，不把 URL 本地校验当 SSRF 防护。

| ID             | 断言                                                                                                          | 证据层                                         |
| -------------- | ------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| SETUP-SHAPE    | PostgreSQL/MySQL/SQLite 与 reference/Nacos direct/Consul direct/none 精确联合；不包含其它分支的凭证或 confirm | 类型负例 + 纯投影/输入不变测试                 |
| SETUP-VALIDATE | 必填、合法端口、管理员长度/一致性、含内联凭证/非 HTTP(S)/query/hash 的地址拒绝；SQLite 不要求网络字段         | 模型边界测试 + 实际页面前进失败/可修正         |
| SETUP-SECRET   | 切模式/数据库/来源清除不适用凭据，切回仍空；不写浏览器存储或 URL                                              | 纯转移 + 浏览器真实字段交互                    |
| SETUP-STEP     | 步骤组件拆分不改既定布局、label 与字段基线；日文/窄屏仍可达                                                   | 真实截图/DOM/键盘 + 现有响应式回归             |
| SETUP-COMMAND  | 连接验证只读；初始化 pending/冲突/未知结果独立，服务端确认 ready 后才关闭引导，未知不自动重发                 | 内部 Port/工作流 → F6 HTTP → B0 真 DB 逐层验收 |

这是切片前确定的验收设计；以下运行记录是实际证据，不能互相替代。

### 13.2 初始化向导的实现和当前证据

- `SetupWizard` 只组合四个步骤、状态与动作；`useSetupFlow` 只拥有临时草稿/步骤/本地校验。连接参数变化的用户命令先使旧检查失效再更新草稿，不用 Effect 在第一次提交之后才撤掉旧结论。纯提交投影和连接检查投影共用同一分支构造，不包含 inactive credentials 或 confirm。
- `InitializationPort` / `initializationWorkflow` 是内部消费者合同及副作用所有者，不是已冻结 HTTP wire。数据库/规则源检查不创建 schema 或持久化配置；初始化使用非秘密 requestKey、相关 operation 回执与独立 bootstrap 确认。请求超时/取消/5xx、回执错配或确认不可用均不能自动重放；not-found 也不证明回滚。已完成的别人的初始化只关闭窗口，不冒认本次成功。
- 新 `InitializationPage` 在真实 React/Astryx 控件上消费工作流：确认之前锁住步骤/提交，结果未知保留原请求核查动作，已知字段错误保留可修正输入；ready 后清理临时秘密并只通知路由一次。未初始化/可用窗口仍由服务端事实判定；query failure 不重新打开引导。
- 旧 `SystemInitializationPage` 当前仅是尚未迁移的 demo 装配，复用同一个 Wizard，不新增或包装 FixtureGateway。F6 装配新异步入口后删除旧装配；当前 App 仍未发生数据库连接、迁移或初始化，不能把新入口的端口替身测试称为实际后端初始化。
- 初始 3 项页面浏览器校验 **3/3**（8.39s）；原有 F3 表单/样式 **4/4**（14.44s）。新初始化容器/工作流真实浏览器 **3/3**（10.74s），覆盖连接检查失效、pending 防重复、超时后原请求核查、失败密码保留、已初始化不渲染向导；它们使用明确的最小 effect double，而非 FixtureGateway。
- 曾有 3 项新浏览器测试失败：并存两个 React root 的 ID 冲突使测试命中隐藏旧表单。隔离 root 使用明确 identifierPrefix 后重新执行 3/3；不改生产字段、不忽略 consoleErrors、不跳过断言。另修工具 label 到当前正式“检查执行结果”。实际截图 `/private/tmp/sentinel-f4-setup-20261007/{source,review}.png` 与 `/private/tmp/sentinel-f4-initialization-20261007/unknown.png` 已查看，步骤布局与核查按钮保持可达。
- 初始化切片完整静态 `npm run check` **通过**：严格类型/格式/Hooks、架构 8、逻辑 **91**、浏览器工具 4、视觉工具 7、国际化工具 4、三语 **573** 键/locale、build/Sites 4。主包 787.34 kB / gzip 235.65 kB，包体警告继续留 F5.6。该批全量浏览器结果已见下一段；这是历史基线，不代替后续源码验证。
- i18n 门禁的正则误把条件判断的 `production` 当作翻译键，现改 AST 提取实际 t 参数分支；另外校验跨 namespace 重复键与三语插值参数。4 项工具测试已接统一 check。尚未解析的变量调用仍报告，不声称“全部调用均已静态验证”；F5.2 整项未完成。

此前认证切片全量回归已实际完成 **121/121、0 fail/skip/cancel，327.64s**；这是初始化切片前的历史记录，不作当前新源码的全量证明。本批稳定源码完整 `npm run test:e2e` 已完成 **127/127、0 fail/skip/cancel，347.14s**（既有 121 + setup 3 + initialization 3），包含 33 个页面/viewport 组合、三语、旧表单布局及新向导命令交互。据此勾 F4.19；F4.20/F4.21 及 F6/B0 尚不勾完成，bootstrap 权限单一所有者/真实路由/HTTP/服务端锁与重启持久化仍须后续逐层验收。

### 13.3 后续本人改密切片的预先验收设计

业务目标不是管理员改任意账号密码。输入只有 current/new/confirm，目标由可信当前 session 拥有；confirm 只参与本地校验。政策默认沿现有最小长度，本地不得声称验证了旧密码正确或密码哈希已变更。

| ID                | 动作与断言                                                                               | 最小证据 / 后置范围                                  |
| ----------------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| PASSWORD-OWNER    | 未认证/过期不提交；URL 改 account 不改变本人目标；view 可修改本人密码但不能修改别人      | 内部工作流 + 实际页面；F6 HTTP / B0 服务端逐请求鉴权 |
| PASSWORD-VALIDATE | current 必填、最小长度与 confirm 一致；密码不 trim；失败保留可修正输入                   | 纯校验边界 + 浏览器输入                              |
| PASSWORD-OUTCOME  | pending 防重复；已知旧密码错误/弱密码/429 区分；超时/取消/5xx 不自动重放，也不自动报成功 | command owner + 浏览器可见安全反馈                   |
| PASSWORD-SESSION  | 成功确认才清空；按服务端会话处置回执撤身份/重新登录；旧 owner 的迟到结果不授予新身份     | 内部 owner / browser；B0 真实会话撤销与哈希验证      |
| PASSWORD-SECRET   | 确认不进提交；密码不在快照/URL/storage/log；清理归 mounted form，卸载不持久化            | 编译负例/纯投影/浏览器；B0 日志与真实响应审计        |

以上矩阵已按 §13.4 实施内部用例与真实渲染；HTTP/204 与会话处置的最终投影仍在 F6.1 收敛，不能仅据 204 推断其他会话已失效。

### 13.4 本人改密内部用例与渲染证据

- 新增 identity-owned `api/ownPasswordPort.ts`、纯投影 `model/ownPasswordChange.ts`、`application/ownPasswordWorkflow.ts`、`ui/OwnPasswordPage.tsx` 与轻量 `password.ts` 装配出口。不扩 FixtureGateway，不访问厂商、不调用 Python。
- workflow 绑定 accountId/sessionEpoch，观察已有认证 owner，view 可改本人；不接受 URL 目标。无当前密码/短密码/不一致在本地拒绝；密码逐字符保留，不提交 confirm，不生成目标 ID。
- 单次 command 负责 pending/已知错误/不确定写入；无 reset/replay。原始异常文本不进公开快照/界面。会话变更取消观察并忽略迟到成功；dispose 解绑监听并清空公开结果。
- `PasswordFields` 是旧 demo/新入口共享的无副作用字段组件；Hook 不再本地通过就清空。成功确认后清空并通知一次，会话处置由 app 根据明确回执实施。尚未接入旧 App，F4.31–33 保持未勾；管理员重置不在本轮范围。
- 预先 RED 基线为缺失模块；实施后逻辑 **98/98**（新增 7）、完整 `npm run check` 通过；三语 **585** 键/locale，主包 **790.29 kB / gzip 236.39 kB**，容量警告不隐藏。
- `node --test --test-concurrency=1 tests/e2e/password.e2e.test.mjs` **4/4 pass，0 fail/skip/cancel，9.25s**。测试用当前 session 的 view 用户，URL 带另一账号仍仅本人；真实 Astryx 输入/按钮验证必填、400/422/429 保留输入、pending 防重复、成功只通知一次并清空、超时不重放、过期迟到不成功。测试 Port 为合成替身，不是后端 E2E。
- 已实际查看截图 `/private/tmp/sentinel-f4-password-20261007/unknown.png`：统一 navy panel、黄色未知结果反馈、核查入口可用、凭证保持遮罩且保存禁用。探针按钮/诊断行仅测试 host，不是生产页面内容。该批冻结源码完整 `npm run test:e2e` 已通过 **131/131，0 fail/skip/cancel，360.14s**，包括 33 个响应式路由组合；没有 HTTP/Python 验收含义。
- 后续复查补充畸形回执负例（null/undefined/未知会话处置）：收到不合法回执不证明后台未修改，因此归结果未知且不准再次提交。修复后逻辑 **99/99** 通过；这是 131 项浏览器之后的新增代码，不冒称旧全量覆盖了新增边界。

### 13.5 账户与角色切片的预先验收设计

| ID             | 行为 / 不变量                                                                                         | 验证边界                                       |
| -------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| ACCOUNT-OWNER  | admin 才能读管理数据/写命令；换 session/env 清旧查询；不存在目标不 fallback                           | query/workflow + 实际页；B0 服务端逐请求鉴权   |
| ACCOUNT-CREATE | 仅 username/password/admin或view；唯一名冲突留 Dialog；pending 禁重复；确认成功才更新目录/清密码/关闭 | 校验/command + Dialog 浏览器；B0 幂等/唯一索引 |
| ACCOUNT-STATUS | 确认目标与动作，基于 revision；内置/最后有效 admin 保护；409 不覆盖新事实                             | 纯保护/command/query + 浏览器；B0 并发事务     |
| ACCOUNT-LIST   | 筛选/分页由查询合同拥有，切页不误借旧目录，空与失败不同；服务端生成 ID/版本                           | Port/query + 页交互；F6 wire/分页              |
| ROLE-DRAFT     | URL 目标与详情唯一；仅本地改 radio，不假报已保存；保存/取消、切账号未保存保护                         | draft policy + 实际页                          |
| ROLE-COMMIT    | revision 冲突留草稿，主动读最新再决定；成功更新统一目录；停用/内置/最后 admin 非绕过                  | command/query + 浏览器；B0 会话撤销与 DB 并发  |

先保持旧 demo 路由运行，内部新入口不得包装 FixtureGateway；HTTP 统一迁移后再删除旧页/同步 store 的过渡装配。筛选、草稿与读取状态不能存密码；未知 create 不自动再 POST，只有可核查的原请求身份才能解除不确定状态。

### 13.6 登录实际页面切片的预先验收设计

| ID              | 动作 / 结果                                                                                      | 验证边界                                        |
| --------------- | ------------------------------------------------------------------------------------------------ | ----------------------------------------------- |
| LOGIN-BOOTSTRAP | 未知/不可用不显示可提交登录；未初始化通知 app 强制 setup，页面无 setup 链接                      | 实际新容器 + 已有唯一 AuthenticationWorkflow    |
| LOGIN-FIELDS    | username/password 必填；保留可修正账号/密码；正确 autocomplete、键盘提交、密码可见性不改变字段值 | 实际 Astryx 控件 / 三语资源                     |
| LOGIN-FAILURE   | 错误凭证/禁止登录合并为安全文案、不透露账号存在；429 与未知网络写入区别；不显示原始异常          | Port 替身 / 真实浏览器；F6/B0 wire与真实认证    |
| LOGIN-CONFIRM   | POST 回执之后仍等独立 session 回读；不匹配/回读失败不可准入；只在已确认身份通知导航一次          | 实际容器 + 迟到响应 / StrictMode                |
| LOGIN-RECOVER   | 未知写入仅显式核查当前 session，不重发；核查失败不解锁；匿名确认才允许下一次主动登录             | workflow / 浏览器                               |
| LOGIN-SECRET    | 登录成功/主动离开清理密码，不存 URL/storage/event；演示默认 admin 不进入新容器                   | 实际输入/快照与持久化扫描；B0 日志 / Cookie安全 |

共享表单表面可由旧 demo 与新容器复用，但新容器不读同步网关、不调用旧 role setter，不在页面构造第二份认证 owner。最终统一 app 装配在 F6；不因新容器局部通过勾完整 F4.22–24。

### 13.7 登录入口实施与验证记录

- 新 `LoginEntryPage` 使用已有 AuthenticationProvider/Workflow；`LoginSurface` 拆出品牌/字段/布局，旧 demo 复用它但演示认证逻辑保持隔离。`presentation/loginFeedback.ts` 只映射事实为安全文案，不授予身份。新入口经轻量 authentication 公共入口导出。
- 当前初始化/会话未知不渲染可提交 form；确认未初始化且部署允许 setup 才通知引导。没有 setup 链接；连接故障不会创建管理员。凭证错误与禁止登录共用安全反馈，429 单独展示；密码可见性是显式本地控制。
- POST 成功之后等待独立 session 回读；确认身份后清密码，并按 sessionEpoch 通知一次。超时不重发，只能显式核查当前会话；这不宣称证明上一操作全部副作用完成。站内安全 returnTo 与 app 真实菜单仍待 F6 装配。
- 初次浏览器执行 3 项失败是测试误用“账号名”匹配既有正式“登录名” label 与校验文字，源码不据此改业务。修正测试后 **4/4** 通过；反馈投影拆分后的最终同批登录/改密聚焦复跑 **8/8、0 fail/skip/cancel，19.10s**。
- 当前完整 `npm run check` **通过**：逻辑 **99**、架构 8、Hooks 3、浏览器工具 4、视觉工具 7、国际化工具 4、三语 **597** 键/locale、构建/Sites 4；主包 **793.15 kB / gzip 237.00 kB** 警告留 F5.6。这是登录新源码的静态 + 聚焦证据，上一批 131 项全量是历史基线，不自动覆盖本次新代码。
- 已实际查看 `/private/tmp/sentinel-f4-login-20261007/known-error.png`：居中 navy 登录卡、错误 Banner、带正式标签的原生 Astryx 控件、遮罩密码和明确主按钮，无原始异常文本。截图顶部/底部诊断是测试 host 内容，不进入生产 UI。
- 新入口仍未装配旧 demo App，不勾 F4.22–24/31–33；真实身份/权限/哈希/会话撤销与 Cookie/CSRF 均须 F6/B0 验证，不能拿此 mock-Port 渲染替代后端验收。

### 13.8 账号与角色内部用例实施证据

- 新 `management.ts` 装配出口、AccountManagementPort、纯 AccountRecord/query/RoleDraft 模型、AccountManagementWorkflow、AccountsPage/CreateAccountDialog/RoleManagementPage；私有字段/目录/反馈/角色编辑器分离。旧 demo/新 Dialog 复用 AccountFields，不复制控件，不扩 FixtureGateway。旧 App 与同步 store 的实际退役仍待 F6。
- workflow 绑定当前 admin 的 accountId/sessionEpoch，权限撤销的首个发布立即清空目录/详情/操作身份；请求可取消，迟到响应不回填。分页/筛选由 Port 执行；不存在详情为明确空态，不用另一个账号。
- 创建只提交账号名/密码/角色；启停先确认并携带 revision；角色 radio 只编辑本地草稿，有保存/放弃/未保存切账号确认。内置/最后有效管理员提示不能替代 B0 的逐请求授权与并发事务。
- pending 单次；已知重名/版本冲突保留输入；超时/5xx/畸形回执归结果未知。原 requestKey 查操作并核对目标及预期字段后才解锁，not-found 不证明回滚；公开快照没有写入密码或原始异常。成功失效/回读目录，刷新失败不把已确认写入误报为可重复失败。
- 首次逻辑 1 项失败为 StateStore 订阅立即发送既有值，测试将授权前快照误算为撤权后的发布；按实际观察边界修正，没有放松首个撤权发布。补充恢复读取超时/错误目标与畸形回执负例后逻辑 **114/114**。
- 真正新增缺陷：ObservableResource timeout 只结束观察但不 abort loader；共享 query 在超时时复用底座 cancel，并设有界默认读取时限。浏览器又发现 QueryView ready/refreshing 改变树结构，导致角色编辑器重挂载丢草稿；保持同一子节点位置后冲突草稿回归通过，非重拍坏基线。
- 账号/角色 5 项 + 共享反馈 3 项聚焦浏览器回归 **8/8，0 fail/skip/cancel，18.60s**。Dialog 显式核查、分页/筛选、状态确认、内置保护、角色冲突保留/读新/保存、缺失目标均有用户结果断言。测试使用合成 Port，不是 HTTP/Python E2E。最新小修（新 Dialog 不显示上次成功、稳定动画截图与统一读取时限）的完整回归已实际完成：**140/140，0 fail/skip/cancel，376.79s**；新登录 4 项和账号/角色 5 项均在全量矩阵中执行。
- 最新完整 `npm run check` **通过**：类型/格式/lint、架构 8、逻辑 114、Hooks 3、浏览器工具 4、视觉工具 7、国际化工具 4、三语 **636** 键/locale、build/Sites 4；主包 **801.93 kB / gzip 239.47 kB**，容量警告仍留 F5.6。已查看实际 Dialog/角色页 PNG，稳定截图已重新捕获并查看；测试诊断控件不属于生产 UI。
- 本历史记录形成时，F4.25–30 尚未勾选：实际 App/系统 tab/全局路由离开保护/真实 HTTP 尚未接线；后台唯一索引、幂等操作记录、最后 admin 事务及会话撤销需 B0 单独证明。其后 F4.25 的前端 Mock 页面切片已由 §15.72 完成；F4.26–30 与 B0 后端验收仍未因此关闭。

### 13.9 观测页面下一切片的预先验收矩阵

按已有页面能力第 2/3/5/6 章反推消费者 Port；仅冻结内部能力需求，不提前复制另一份 Console wire。总览、实例、监控与事件页共享时间/质量基础值对象，但查询与展示由各 feature 拥有。先前端正式能力，再 F6 唯一 HTTP/MSW，再 Python。

| ID            | 行为与结果                                                                                       | 证据边界                             |
| ------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------ |
| OBS-OWNER     | query key 包含当前身份/环境/应用/实例/scope/实际 UTC 窗口；换 owner 清数据，缺失目标不 fallback  | 纯 key/owned query + 实际页；B0 鉴权 |
| OBS-METRIC    | QPS/TPS/p95/CPU/内存/阻断单位与来源/覆盖明确；无 histogram/TPS 不造 0；ratio 只在展示转换        | 纯边界/负例 + 卡片/曲线实际渲染      |
| OBS-WINDOW    | 明确 [from,to)，跨日/UTC、发布标记在窗口内；摘要与序列同窗/同 scope                              | Port 样例/校验/实际图表              |
| FLEET-READ    | 全范围统计与分页分母一致；没有关注对象不生成无效下钻                                             | 实际查询与呈现；B0 聚合              |
| INSTANCE-READ | 应用目录与实例目录分离；每一 scope 自有能力与样本，不挪用别的应用/层级                           | 分组/选择负例 + 页面                 |
| REALTIME-READ | 单一轮询 owner、无 overlap；暂停只停浏览器刷新，后台采集不受影响；断线 stale/恢复/取消与点数有界 | 可控时间/Port + 浏览器；F6 HTTP      |
| INCIDENT-READ | UTC 发生/收到时间区分、稳定分页，全范围统计不受分页改变；证据/版本/发布各自数据，不推断因果      | 时间边界/target/filter + 实际页      |

以上未声称已完成，不以静态 fixture、命名或局部 build 代替实际实现/验收。

### 13.10 总览与实时监控内部能力实施证据

- 新增 `overview/observation.ts` 与 `realtime/monitoring.ts` 正式内部装配出口。总览由一个 FleetPort 查询拥有同窗摘要/连接探测/曲线/分页目录；实时监控复用底座 PollingStore 调度和唯一 owned QueryResource 数据所有者，无 overlap、无第二份采样缓存。
- 公共观测模型明确 UTC `[from,to)`、scope、指标单位/source/denominator/coverage/quality，窗口至多 7 天、单序列至多 1000 点。ratio 只在呈现转换一次；TPS 未接入保留 null；p95 不由浏览器计算。窗口内发布标记允许处于两个采样点之间。
- 身份撤销首个发布清空观测；查询环境/应用/范围完整匹配，错误响应不得借旧 query 的数据。滚动读取失败保留原数据自身的窗口/asOf 并标陈旧，恢复只读取最新窗口；固定历史窗口不随刷新移动。暂停只停止当前浏览器的读取，不发送停止后台采集/流控的命令。
- 静态门禁 `npm run check` 已实际通过：类型/格式/lint、逻辑 **131/131**、架构 **8/8**、Hooks **3/3**、浏览器工具 **4/4**、视觉工具 **7/7**、国际化工具 **4/4**、build/Sites **4/4**；三语 **723** 键/locale。主包 **816.98 kB / gzip 243.31 kB**，F5.6 容量警告未豁免。
- 最终集中浏览器回归 **15/15，0 fail/skip/cancel，36.68s**（总览 4、实时 5、共享图表 6），执行真实 feature 页面及 Astryx/Nivo 渲染，使用测试 Port 而不是 HTTP。监控桌面及 320px 日文 PNG 已实际查看：`/private/tmp/sentinel-f4-observation-20261007/monitor-desktop.png`、`monitor-narrow-ja.png`；顶部测试诊断控件不属于生产界面。
- F4.01–03/F4.10–12 暂不勾：旧 App 的同步演示入口尚待 F6 退役；应用/实例/scope 目录装配未闭环，真实聚合/服务端采集与发布事实需 B0 证明。上一完整浏览器 **140/140** 不包括本节新增观测切片，不能当作当前全量证明。

### 13.11 应用与实例内部读能力实施证据

- 新增 `applications/observation.ts` 的消费者入口；InstancePort、目录与详情两个资源 owner、纯 query/实例/加载回执校验、筛选表单、页内宿主机分组、详情面板各自内聚。应用选项经 app 注入，实例页不拿当前页行数构造“全应用目录”。
- scope/query key 包含环境、应用、实例、实际窗口、采样步长及 processEpoch；目录包含分页/搜索/异常筛选。全范围统计不受当前页/异常筛选污染，宿主机分组明确仅当前页，目录指标明确为进程级摘要。
- 详情由显式选中身份拥有，不自动回落首行。分页/过滤隐藏不代表实例消失；换环境/应用/窗口不能显示不匹配详情。supportedScopes 决定各层能力，不支持返回 metrics=null，缺失实例为安全读错误。回执 applied 必须同 incarnation、desired/applied 版本一致且有收到时间。
- 最终集中浏览器 **13/13，0 fail/skip/cancel，36.31s**（实例 4、实时 5、总览 4）。首轮 **12/13** 的唯一失败是测试查找“仅异常”而界面为“仅看异常”；修正真实文案后全量复跑，不跳过。已实际查看 `/private/tmp/sentinel-f4-instances-20261007/instance-narrow-ja.png` 和 `instance-detail-ja.png`，320px 日文无页面横向溢出。
- 此切片 `npm run check` **通过**：逻辑 **137/137**、架构 **8/8**、Hooks **3/3**、浏览器工具 **4/4**、视觉工具 **7/7**、国际化工具 **4/4**、build/Sites **4/4**；三语 **736** 键/locale。国际化门禁拒绝的两个动态拼键已收口为明确健康/回执映射。主包 **820.35 kB / gzip 244.26 kB**，F5.6 未完成。
- 测试使用合成消费者 Port，不是 HTTP/Python。F4.04–06 暂不勾：旧 App 迁移、完整应用目录/规则绑定/故障下钻和真实采集回执仍未闭环。包括本节在内的完整浏览器回归已完成：**153/153，0 fail/skip/cancel，419.24s**；同份源码 `npm run check` 也通过（此时逻辑 143）。它仍是前端验收，且不包括随后新增的 §13.13 缺失目标修复。
- 全量运行期间交叉审查发现共享 QueryResource 把同 key 的 404/410 也按普通 read error 留 last-known-good。目录/实例/事件已被服务端明确认定不存在时，不应继续展示旧详情/加载回执；全量结束后已按先红后绿修复，后续验证见 §13.13，不能用既有“换 key 不借旧值”测试代替。

### 13.12 故障分析内部模型与读资源实施证据（尚无新页面）

- 新增 IncidentPort 的 timeline/evidence 读取与各自 owned QueryResource。时间使用 UTC 绝对毫秒，发生时间限定 `[from,to)`；接收时间独立允许迟到/客户端时钟偏差。按 occurredAt 倒序、同时间按 ID 代码点倒序检查，不在分页后重新排序。
- 全范围 total/critical/warning/info/ruleChanges/affectedApplications 与 severity/category 过滤结果及游标页分开；重复 ID、乱序、混 scope、畸形计数、空或超长游标拒绝为协议错误。key 包含所有查询维度；原列表不能借给另一环境，显式证据目标不能改成首个事件。
- Caption/事实采用有限带类型 code 的联合；无原始异常消息/traceback，自定义建议仅给只读视图目标，缺失实例/版本不生成无效动作。事实/来源/时间独立，证据完整/部分/不可用显式，有界最多 100 条，不从时间相邻推断根因。
- 新增 6 个负例/资源测试后逻辑 **143/143，0 fail/skip/cancel**，类型/lint/架构 **8/8** 通过。**还未实现该内部入口的真实页面、结构化文案及浏览器验收**，F4.13–15 不勾；旧 demo 时间线尚未迁移，最终 wire/HTTP/MSW/Python 仍后置。

### 13.13 权威缺失目标与进程更换的失效修复

- 先新增同 key 404、410、instance_incarnation_changed 三个纯资源回归，在原实现上实际 **143 pass / 3 fail**，均复现把权威缺失结果当作 stale 留旧值。
- QueryResource 对标准 404/410 清空 last-known-good，并提供纯 `invalidatesValue` 供 feature 表达额外权威失效；实例详情在 409 + 内部 `instance_incarnation_changed` 时清旧回执/指标，通用底层不认识实例业务。普通断网/超时仍保留同 key 的陈旧值，不把两类失败合并。取消/卸载也不能复活已失效数据。
- 观测反馈正式三语说明对象不存在/已移除；实例页额外要求刷新目录后显式选择新进程，不能自动改选或把旧 applied 文案留在页面。该错误码只是内部消费者合同，最终 wire 在 F6 收敛。
- 修复后逻辑 **146/146，0 fail/skip/cancel**、类型/lint/架构 **8/8**、三语 **738** 键/locale 通过。新增同 key 删除/更换实际页用例后，实例/反馈/总览/实时监控集中回归已完成：**17/17，0 fail/skip/cancel，45.13s**。当前最新完整 **153/153** 是修复前源码，不能替代本次聚焦证据。

### 13.14 故障分析正式内部页面实施证据

- 新 `faults/observation.ts` 装配入口与 IncidentObservationPage、Filters、Timeline、Evidence、纯事实呈现文件各有职责。复用共享读取反馈；feature 仅替换空态/证据不完整描述，不复制读取生命周期。无 FixtureGateway 扩展、无生产 fixture/HTTP provider 选择分支。
- 全范围统计不受分页或级别/类别过滤影响，filtered-empty 仍显示统计；默认不自动选首条。游标翻页保留显式事件、证据不重复请求；改变筛选清掉选择。来源、发生/接收/读取 UTC 时间、启动标识和发布身份独立展示，三种证据完整度明确；仅有限结构化事实三语映射，ratio 转换一次。
- 新增非 BMP ID 排序回归，修正 JS UTF-16 比较与声明的 Unicode 代码点倒序不一致；维持后台分页次序，前端不重新排序。旧历史记录不据此重新记作当时已经修正。
- `npm run check` 实际通过：逻辑 **147/147**、架构 **8/8**、Hooks **3/3**、浏览器工具 **4/4**、视觉工具 **7/7**、国际化工具 **4/4**、Sites **4/4**；三语 **767** 键/locale，静态提取不覆盖全部动态键。主包 **827.76 kB / gzip 246.31 kB** 警告仍待 F5.6，不提高限额掩盖。
- 浏览器首次沙箱内 Chrome 启动 SIGABRT，页面未执行，记作环境失败而非页面通过；允许本机浏览器执行后完整复跑故障 5 + 反馈 3：**8/8，0 fail/skip/cancel，18.30s**。源码运行期间冻结。实际查看 `/private/tmp/sentinel-f4-incidents-20261007/incident-evidence-ja.png` 与 `incident-narrow-ja.png`：桌面两列、证据元数据/动作与 320px 日文单列没有页面横向溢出；测试诊断内容不进入生产页面。
- F4.13–15 不提前勾：旧 App/URL/实例范围目录装配、关联指标/版本/发布审计实际读路径和完整 HTTP/Python 未完成。当前全量 **153/153** 是之前源码；本节只声明新页面的聚焦验收，整体 goal 继续执行。

### 13.15 规则整组编辑与部署合同的内部基础

- `ruleMaterialization/ruleSetEditing` 保持五类相关联合，完整新增/修改/删除/空数组提交保留源基线、未改记录和管理身份；数字必须先过纯校验，隐藏的条件值和 formKey 不进入候选。规范化不修改资源标识，只处理明确的来源列表/参数类型。
- `RuleSetPort` 是内部消费者需求，不是第二份已冻结 wire。持久草稿、不可变版本、三阶段 publication、逐实例 receipt、活动计划各有模型；版本不携带伪 active 状态，回执匹配 incarnation/version/checksum 才计 applied。全范围计数不是当前页统计，restart_required 明确不算生效。
- `ruleActivation` 明确 UTC 半开区间、IANA 时区和恢复版本；纽约夏令时缺失/歧义、加德满都 45 分钟偏移均有纯回归。浏览器不运行计划定时器；后端仍须事务校验重叠/基线并持久化恢复。
- `createRuleOperation` 组合底座 command/query/state：固定 binding/session，单次 dispatch、有限等待、结果未知仅查询原 requestKey。核对目标、修订、版本、基线及整组内容后才能解锁；pending/not-found/错误目标不能证明回滚。同步重入、撤权、迟到响应和错误脱敏已覆盖，不能用它替代服务端幂等事务。
- 当前 `npm run check` **通过**：逻辑 **165/165**、架构 8、Hooks 3、浏览器工具 4、视觉工具 7、国际化工具 4、Sites 4；三语 **767** 键/locale，主包 **827.76 kB / gzip 246.31 kB** 容量警告未豁免。同份源码完整前端浏览器回归已执行：**159/159，0 fail/skip/cancel，427.76s**，包括新增故障 5 项和实例同 key 缺失/更换回归。测试运行期间冻结源码；这不是 HTTP/Python/真实配置中心 E2E，不提前宣布整体 goal 达成。
- 新发现的正式对接风险：实际 Nacos codec 使用的 Flow scope、Degrade count/exceptionRatio/timeWindow 及其他类别字段，与五类兼容表单不等价。F6.11/B0.3 必须有明确 profile/能力校验并转换或拒绝，不能凭“Java-compatible”注释静默吞字段；见页面能力第 4.6 节。未修改 source-nacos 现有实现或用户协议文件。

接下来的内部规则工作台验收（尚未完成）：

| ID              | 预期结果                                                                    | 必需证据                           |
| --------------- | --------------------------------------------------------------------------- | ---------------------------------- |
| RULE-EDIT-OWNER | 权威快照刷新不覆盖 dirty；换绑定/离开确认；撤权立即隐藏草稿与验证结论       | 纯模型/工作流 + 实际页             |
| RULE-FULLSET    | 单条改动保留所有未改项；新 key 不变成正式 ID；非法整组/重复/外来记录拒绝    | 正负模型 + 实际请求候选            |
| RULE-DRAFT      | 已知冲突保留输入，未知写入不能重发；核查原操作后显示后台草稿修订            | 工作流 + 实际 Dialog/按钮          |
| RULE-VALIDATE   | 更改任意记录使旧校验/差异失效；迟到报告不可为新内容授予 publishable         | 可控迟到 Port + 浏览器             |
| RULE-FREEZE     | 固化要求当前已保存内容及同候选目标校验；不可变版本不是已发布                | 纯准入 + 工作流 + 页面             |
| RULE-PUBLISH    | 校验/写入/回读/实例载入独立；外部基线冲突不自动覆盖；回滚新发布不倒退 epoch | 工作流/页面；最终 F6/B0 真实配置源 |
| RULE-SCHEDULE   | 缺失/歧义本地时间明确选择/拒绝，恢复版本显式，取消/blocked 可见             | 模型/页面；最终后端重启恢复        |

F4.07–09 仍未勾：新整组工作台与版本/发布/计划 UI 尚未完成，旧同步 App 在 F6 才退役。HTTP/MSW/Python 与真实配置中心均不能被内部 Port 测试代替。

### 13.16 整组工作台内部页面与校验报告

- 正式内部页面已拆为源快照、编辑区、动作栏、五类既有表单、整组预览/差异/校验报告、固化版本 Dialog 与操作反馈。源刷新不改本地基线，空数组清空意图明确；删除后台草稿也丢弃本地修改，三语确认已说明。
- 纯候选提交增加结构检查：重复/空 formKey、外来/重复记录身份和异类规则拒绝。回归先在原实现上 **165 pass / 1 fail**，修复后 **166/166**；新增草稿工作流后逻辑 **173/173**。
- 国际化扫描器不再把所有 `*Key` 当翻译键，按明确文案元数据识别，保留不存在 key 的检查；新增负例先 **4 pass / 1 fail**，修复后 **5/5**。未把表单身份插入 locale 冒充修复。三语资源 **828** 键/locale；动态提取盲区仍如实报告。
- 当前 `npm run check` 全部通过：类型、格式、lint、逻辑 **173**、架构 **8**、Hooks **3**、浏览器工具 **4**、视觉工具 **7**、国际化工具 **5**、Sites **4**。主包 **843.85 kB / gzip 250.63 kB**，容量警告继续由 F5.6 收口，不调整阈值。
- 新内部页面首次浏览器失败暴露测试错误：输入 API 参数误用，以及未经过 Astryx NumberInput 的 blur/Enter 提交边界就检查模型。按真实控件提交修正后规则 6 + 反馈 3 实际 **9/9、0 fail/skip/cancel，23.01s**。补充数字框失焦后旧校验不可固化，以及准确可见区域截图后，规则 7 + 反馈 3 完整复跑 **10/10、0 fail/skip/cancel，25.11s**。截图曾因桌面内容高度/滚动上限不足以把编辑区放到 top<100 而失败，改查实际表单可见范围；不是跳过页面断言或提高布局溢出容差。
- 已实际查看 `/private/tmp/sentinel-f4-rules-20261007/rule-editor-narrow-ja.png` 和 `rule-editor-desktop-ja.png`：320px 日文完整单列表单、数字框、复选框与整组 JSON 没有页面横向溢出；桌面选择目录/双列字段/动作和预览分区清晰。没有 HTTP 或 Python 接线，F4.08/09 不提前勾。当前新增用例未纳入前一轮 **159/159**，全量仍待稳定切片后复跑。

### 13.17 版本发布与计划内部切片：实施前验收矩阵

保留既有 `RuleSetPort` 和 binding/session 级 `createRuleOperation`；独立读取资源持有版本/发布/回执/计划，发布工作流仅内聚准入与一次命令编排。源快照复用草稿工作台的唯一读取所有者，不建第二份权威源状态。不增加单例、基类或浏览器调度器。该方案延续已确认的 Port/命令/查询组合，所有外部真实写入仍属于 F6/B0。

| ID             | 必须证明的行为                                                                                                  | 验证层                         |
| -------------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| DEPLOY-READ    | 不同 binding/profile/目标 ID 的内容拒绝；旧响应、404/410、撤权不能残留目标内容                                  | 模型/读取资源/工作流           |
| DEPLOY-PUBLISH | 显式目标版本 + 最新源基线；陈旧/刷新中的事实不能授权发布；回滚走同一发布命令，源状态不乐观修改                  | 工作流 + 实际页面，最终 B0     |
| DEPLOY-PHASE   | 已受理命令、校验、配置写、回读、实例加载分别显示；UNKNOWN/restart-required 不算生效                             | 模型/页面，最终实际回执        |
| DEPLOY-LOOKUP  | 发布/计划与草稿共享一次队列；未知结果仅查原 requestKey；pending/not-found 不解锁                                | 工作流/浏览器                  |
| DEPLOY-PLAN    | 目标及恢复版必须显式且匹配 binding；UTC 半开窗口/IANA 时区/重叠检查；取消的 revision 与状态须匹配；无前端 timer | 模型/工作流/页面，最终后台恢复 |
| DEPLOY-OWNER   | 第一次撤权立即隐藏版本、发布、回执、计划；换 session 不能继承选择或写操作                                       | 工作流/实际页面                |

内部实施与实际证据：

- `ruleDeploymentResources` 持有版本目录/单版、发布目录/单次、实例回执和后台计划的独立资源；`ruleDeploymentWorkflow` 借用唯一源观察与 binding/session 命令 owner。完整目录有界且不静默截断；不同 binding/profile、重复身份、不合法时间/规则和旧 incarnation 正向回执拒绝。无 HTTP、没有客户端调度定时器。
- 发布确认捕获目标 checksum 和源版本/checksum/native revision；打开确认后源变化返回冲突，写次数为零，不用刷新后的新基线悄悄替换用户确认。回滚选择旧内容仍创建新的 publication，不乐观改源快照。计划要求显式目标/恢复版、未来半开 UTC 时间和完整重叠事实；重复时刻显式选 UTC、缺失时刻拒绝。
- read scope 先撤销、write projection 尚未通知时，也必须立即隐藏已完成命令内的规则正文；新增回归先实际 **180 pass / 2 fail**，修复两个 workflow 的安全投影后 **182/182**。草稿 inspector 不接管发布结果，避免核查成功但发布面板不更新；共享单次队列仍禁止未知结果时重发。
- 新页面分别为 Versions/Publication/Plans 读面板及 Publish/Plan/Cancel 三类共享 DialogFrame 内容。校验/配置写/回读各自显示，逐实例加载与全范围统计另列；restart-required 不计 applied。权限变化清除未提交 Dialog 意图。
- 当前 `npm run check` **通过**：类型/格式/lint、逻辑 **187/187**、架构 **8**、Hooks **3**、浏览器工具 **4**、视觉工具 **7**、国际化工具 **5**、Sites **4**；三语 **899** 键/locale，主包 **860.44 kB / gzip 255.29 kB**，容量门禁优化仍留 F5.6。
- 实际发布页面浏览器 **6/6，0 fail/skip/cancel，15.62s**。首轮失败是测试点击另一隐藏 Selector 中同名选项、以及使用不存在的“结束时间”标签；改为实际可见选项与正式“恢复时间”字段后全部重跑，不删用例。草稿 7 项此前同批回归全部通过。已实际查看 `/private/tmp/sentinel-f4-deployment-20261007/plan-narrow-ja.png` 和 `plan-desktop-ja.png`，320px 日文完整单列、UTC 范围/底部动作可见，桌面字段按统一网格对齐。
- 新组件仍属内部入口；规则绑定/草稿目录和全局离开保护、旧 App 装配退役、HTTP/MSW/Python/实际源与重启恢复未完成，F4.08/09 不提前勾。同份冻结源码完整前端浏览器回归已实际结束 **172/172，0 fail/skip/cancel，464.97s**（159 历史路径 + 整组工作台 7 + 发布/计划 6），包含 11 路由三组 viewport、三语、资源生命周期和命令负例。此结果是前端验收，不是 HTTP/Python/真实配置中心 E2E。

### 13.18 系统管理的后续验收设计（实施前）

保持 connections/permissions/protocol/accounts/roles 五个现有 URL tab，不添加租户、动态角色或审批流。账户/角色继续复用 identity 唯一能力；源配置、运行健康、能力协议及审计有各自消费者 Port，不让一个宽接口承担全部副作用。

| ID              | 必须证明的行为                                                                                                                                    | 证据层                                             |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| SYSTEM-SOURCE   | Nacos namespace 与 Consul datacenter 区分；登记/修改具有正式 source ID/revision；读取不携带凭证；修改默认保留，替换必须显式 none/reference/direct | 纯模型/工作流/实际 Dialog；最终 Python Secret 保护 |
| SYSTEM-CHECK    | 当前候选连通性/认证/能力可读；任一输入变化废弃旧测试，迟到结果不复活；测试不登记、不写规则                                                        | 可控 Port/浏览器；最终受控源                       |
| SYSTEM-COMMAND  | 登记/修改一次 dispatch；冲突保留可修正字段；未知结果原请求核查，not-found/pending 不证明回滚；完成/撤权/离开清秘密                                | 工作流/实际页；最终事务                            |
| SYSTEM-HEALTH   | 配置源/指标/Collector 各自健康/探测 UTC/能力，不由浏览器 online 判定；缺测不借值                                                                  | 纯守卫/Query/实际页                                |
| SYSTEM-PROTOCOL | 支持版本/实际版本/兼容状态独立；权限是会话真实能力，不是静态交付状态                                                                              | 读取资源/页面；最终后端                            |
| SYSTEM-AUDIT    | admin 查询独立审计窗口/筛选/分页；view 无审计请求；命令/发布关联但无正文、密码或 traceback                                                        | 正负资源/页面；最终真实审计                        |

这里是后续实施前边界，不新增冻结 wire，不宣称 F4.16–18 已完成。未决前端 source 表单职责要与首次初始化复用有限 provider/auth 字段校验，避免复制规则或跨 feature 私有路径。

内部读切片已经实施（尚未接真实 App/HTTP）：

- connection/protocol/audit 分别拥有纯模型和消费者 Port；共用私有有界身份/UTC 守卫，不把三类业务塞进一个宽 DTO。三类资源失败独立、权限独立；Collector 未配置、Consul 探测在读取时过期、后台协议版本不兼容分别可见，浏览器 online 不参与判断。
- `ObservedConnectionsPanel` 展示后台读取 UTC、探测 UTC/有效期/耗时/有限能力与脱敏失败分类；`ObservedProtocolsPanel` 展示支持版、协商版、兼容与观测时间，不再借交付清单作为事实。实际协商与支持版矛盾、无探测却 available、重复记录/能力与非法 UTC 拒绝。
- `ObservedAuditPanel` 有独立有界 UTC 窗口、actor/action/result 筛选及显式 Apply、页码/total/本页数量、原 requestKey 和发布链接目标。非法或反向/超过 31 天窗口不调 Port；view/撤权不调后台并即时清旧行。审计不携带密码、规则正文或任意日志。
- 纯回归发现修改 actor 时原毫秒窗口被截为分钟：新增测试先 **200 pass / 1 fail**，保留秒/毫秒且拒绝日历自动归一化后 **201/201**。三语 **1017** 键/locale，当前 `npm run check` 通过（逻辑 201、架构 8、Hooks 3、浏览器工具 4、视觉工具 7、国际化工具 5、Sites 4）；主包 **882.38 kB / gzip 260.16 kB** 容量警告继续待 F5.6。
- 系统面板 5 + 目录 4 同批实际浏览器 **9/9，0 fail/skip/cancel，20.75s**；已查看 `/private/tmp/sentinel-f4-system-20261007/narrow-ja.png` 和 `desktop-ja.png`：320px 日文筛选完整单列、桌面双列对齐，UTC/长表格由各自滚动区域承担。该轮发生在毫秒精度与共享 source 校验提取前，后续初始化/系统专项复跑独立记录，不能把旧结果冒充新源码。
- `shared/model/configurationSource` 提取首次初始化与正常 source 管理共用的纯 provider/auth/URL/凭证投影规则；setup 原有类型/入口保留，不复制 credential 校验。正常编辑默认 keep，切 provider 不得复用旧凭证，check 结果必须随字段变化失效，这些注册/修改页面与命令仍待后续实施。F4.16–18 未勾；协议最终解码、SSRF、Secret 保护与实际审计持久化均留 F6/B0。

### 13.19 规则目录与离开保护：实施前补齐项

完整编辑/部署切片有自己的只读与命令证明，但仍需要真实应用入口的目标选择。下一段按原 F4.08 分解，不额外增加任务总数：

- binding 目录按 environment/app/kind/search/page 查询；全范围 total 与本页行数区分，空/过滤无结果/读取失败分别呈现。不自动选第一条，不从其他应用借绑定；明确选中 ID 后才创建该 binding/session 的草稿、部署与唯一命令 owner。
- 持久草稿目录单独读取、仅编辑能力可读；按绑定核对 type/profile/identity/revision、完整有界集合不静默裁剪。保存/删除后的目录刷新不能把本地编辑区替换为首个草稿；已知 404 清缺失条目，不伪造创建成功。
- 打开另一草稿或换绑定遇到 dirty，必须说明丢弃范围并确认；拒绝后仍保留输入、目标和 URL。pending/unknown 写操作不允许把页面离开当作撤销事务；能在原操作界面核查，不能自动重发。
- 全局 SPA 导航保护属于 app/router 组合，feature 只提供 dirty/locked 与明确放弃动作；刷新/关闭的 `beforeunload` 只在存在本地未保存或未决写入时注册，卸载移除。账号角色采用同一机制，不新增另一套路由拦截器。
- 浏览器验证须覆盖目录过滤/页码、显式不存在目标、dirty 保留/放弃、源刷新不夺取编辑、未知操作阻止换目标、回退/深链/撤权与长文案布局。最终统一 HTTP/App 入口仍在 F6，内部组件存在不等于所有用户路径完成。

本轮内部实施与证据（尚未完成 App/SPA 全路径）：

- `ruleDirectory` 的查询身份含 environment/app/kind/search/page/pageSize；读取资源检查绑定所属范围、profile、重复 ID、总量/页容量，默认不选第一行。`RuleBindingDirectory` 用受控筛选和明确打开动作；跨查询的旧 total 不授权下一页按钮。
- `StoredDraftCatalog` 独立读取、固定 binding/session、撤权即隐藏；确认保存/删除后按原 requestKey 只刷新一次，不覆写本地输入。另一草稿的打开由工作流重新读取，dirty 先确认，取消保留。模态内读取失败反馈仍可见，未决命令禁用打开动作。
- 规则、发布/计划和角色编辑复用 `useBeforeUnloadGuard`；只针对 dirty/inspecting/pending/unknown 注册，卸载移除。SPA/back/hash 导航组合仍未接入，不能以关闭事件测试替代全局保护。
- 当前 `npm run check` **通过**：逻辑 **193/193**、架构 **8**、Hooks **3**、浏览器工具 **4**、视觉工具 **7**、国际化工具 **5**、Sites **4**；三语 **924** 键/locale。主包 **865.49 kB / gzip 256.39 kB**，不调整容量警告阈值。
- 目录实际浏览器最终 **4/4、0 fail/skip/cancel，10.44s**。前两次失败分别为测试双 Root 的 useId 冲突和 RegExp 断言参数；修正后完整重跑。初次 DOM 通过但像素显示 320px 筛选栏裁切，找到 `.content` 隐式 grid min-content 轨道被表格撑大；限定私有布局 `minmax(0,1fr)` 后新增可见控件边界断言并重新完整跑通。已实际查看 `/private/tmp/sentinel-f4-directory-20261007/narrow-ja.png` 与 `desktop-ja.png`：四个筛选字段窄屏完整单列，表格由自身滚动区域承载；没有新增 feature 内的 vendor 输入样式。
- 上一轮全量 **172/172** 是新增目录前源码；本节的 4 项是内部 Port/StrictMode 页面交互，仍不是统一 HTTP、Python、真实源和后端重启 E2E。F4.08/09 继续不提前勾，任务总量不变。

### 13.20 配置源登记/修改与命令时限：内部切片证据

- 首次初始化/系统专项在共享 source 纯校验及审计 UTC 精度修改后实际重跑 **11/11、0 fail/skip/cancel、29.08s**，不是沿用 §13.18 的旧源码结果。
- `commandResource` 统一持有默认 10 秒正有限时限，超时 abort 后已发出的写保持 unknown，不自动重放；规则操作移除重复的私有 timer，复用同一时限合同。新增回归先 **201 pass / 2 fail**，修复后 **203/203**；密码、初始化、账号等消费者不再无限 pending。
- system `sourceRegistration` 是独立纯登记模型，读取仅 name/provider/endpoint/location/ID/revision/authenticationMode/credentialConfigured，不包含密码、令牌、用户名或引用值。修改默认 keep；显式 replace 支持 credential-reference/direct/none。provider 切换清空地址/位置/凭证，不把 Nacos namespace 当成 Consul datacenter。
- `sourceRegistrationWorkflow` 分别拥有登记目录、候选连接检查和一次命令/原操作核查。每个输入变化废弃旧检查；测试不登记、不写业务规则，也不作为发布授权。保存需要当前可信 registry 与原 revision；字段顺序不同的等价读事实不能误报冲突。结果未知仅保留非秘密意图/原 requestKey，pending/not-found 不解锁。
- `SourceRegistryPanel` / `SourceRegistrationDialog` / `SourceRegistrationFields` / `SourceOperationFeedback` 按读目录、临时表单、有限凭证展示、命令反馈分责；复用共享 Astryx DialogFrame/FormGrid，不新增输入内层皮肤覆盖。冲突保留可修改字段；未知结果清秘密且禁重发，关弹窗仍可在目录面板查原操作。撤权卸载表单和意图，权限恢复不复活旧弹窗。
- source 新增 6 项回归，初轮 **206 pass / 3 fail**；两个实际问题是 provider 残留位置和对象插入顺序误冲突。撤权断言还需排除 `StateStore.subscribe` 的即时初始授权快照；安全投影仍明确按当前授权屏蔽所有读/命令结果。最终逻辑 **209/209**；`npm run check` 全链通过，三语 **1068** 键/locale，包体 **893.71 kB / gzip 262.88 kB**，未提高警告阈值。
- source 5 + 账号/初始化/密码 12 首轮实际浏览器 **16 pass / 1 fail**：测试错误使用不存在的“查询操作结果”文案。改为共享组件正式“检查执行结果”后，同份冻结源码 source 5 + 系统 5 + 草稿 7 + 发布/计划 6 完整实际重跑 **23/23、0 fail/skip/cancel、55.90s**；首批其它 12 项通过结果独立保留。已查看 `/private/tmp/sentinel-f4-source-20261007/narrow-ja.png` 与 `desktop-ja.png`，320px 日文单列、桌面同排字段对齐，长说明不会挤歪输入，底部动作可见。
- 这些是正式消费者的内部 Port/浏览器证据，尚未装配至实际 App / HTTP / MSW，也未访问真实 Nacos/Consul；Secret 保护、SSRF、事务/CAS、真实健康/审计和重启持久化仍在 F6/B0。F4.16–18 不提前画勾，完整前端回归在下一稳定切片重新执行。

### 13.21 当前会话权限及系统事实补充

- `ObservedPermissionsPanel` 从身份能力公开合同接收已确认 `ControlPlaneAccessState`，不读第二份 me、不建 session store；只展示当前 username/accountId/admin|view/两能力授予状态。unknown/expired/anonymous 隐藏历史身份；没有权限编辑控件。真实 App 装配沿用身份唯一 owner，静态角色说明不能冒充已授予权限。
- 两项新模型回归先 **209 pass / 2 fail**：缺少两种协议的单个 compatible 结果误标 ready，同时间审计行不检查身份排序。补齐三种边界覆盖判断；审计和故障共用真正有两类消费者的 `compareScalarText`，按 UTC/Unicode scalar ID 降序验证后台页，不在分页后客户端重排。修复后逻辑 **211/211**。
- `npm run check` 全链通过，三语 **1081** 键/locale，主包 **896.38 kB / gzip 263.52 kB**。最初新组件引用 identity 专用装配入口被架构门禁拒绝，改为公开 feature index 的 type-only 合同，不新增豁免或放宽门禁。
- 系统 6（含会话切换/过期）+ 故障 5 同份冻结源码实际浏览器 **11/11、0 fail/skip/cancel、23.66s**。三种权限事实不替代后台逐请求授权；App/HTTP、审计数据库分页稳定性与实际采集仍留 F6/B0。

### 13.22 全局离开保护：实施前合同与验收矩阵

按 F2.5/F4.08/30 补现有 hash 路由，不引入新路由框架。共享层只声明本地保护登记合同，app/router 唯一拥有 URL/history/确认 Dialog 副作用；feature 不引用 app 私有路径，也不持有第二份 URL。无秘密进入登记状态。

| 情景                          | 必须行为                                                                                               | 验证                    |
| ----------------------------- | ------------------------------------------------------------------------------------------------------ | ----------------------- |
| 多个 dirty / locked 消费者    | 合并登记；locked 优先，不把未知写结果当成可放弃的草稿                                                  | 纯控制器与真实页        |
| 站内 push / replace           | 受保护时 URL/已接受路由/原表单不先改变；取消保留，dirty 确认后才执行一次                               | 控制器/浏览器           |
| 已管理历史中的 back / forward | 路由消费者只读已接受位置，不因浏览器先改 hash 而卸载旧表单；恢复原历史位置后再确认，不追加“取消”历史项 | 实际 Chrome             |
| 外部未标记 hash / 非法深链    | 不猜历史偏移；恢复当前 URL，显式确认后才进入目标，未知目标不回落首条数据                               | 浏览器                  |
| 未决命令                      | pending/inspecting/unknown 禁止放弃导航，不取消后台事务、不自动重发；原页核查后才解锁                  | 控制器/实际命令         |
| 权限 / 会话变化               | 解除已卸载所有者登记，不复活跨会话意图；安全访问门禁仍是独立 owner                                     | 控制器/浏览器，最终 App |
| StrictMode / 卸载 / 关闭      | 注册/清理幂等；同一 app 一个 native beforeunload；无 provider 的内部消费者保留原关闭保护               | 纯回归/浏览器           |

这是实现前的有限组合合同，不宣称全部导航路径通过；F6 最终页面装配后仍需检验所有实际入口。

内部实施与实际验收（2026-10-07）：

- `navigationProtection` 只聚合组件生命周期的 dirty/locked 和本地放弃动作；不保存字段值、凭证、事务正文或 URL。`NavigationBoundary` 是 App 单一历史/确认 owner，`useHashRoute` 只读取已接受位置；原生 back/forward 先恢复历史再确认，不通过新增历史项“修复”取消。外部未标记 hash 不猜偏移，采用替换恢复并轮换本次历史分支身份。
- 首次初始化、账号创建、本人改密、角色、规则编辑/部署和 source 编辑通过共享 Hook 登记；pending/inspecting/unknown 强制 locked。关闭窗口只安装一个 App 级 beforeunload；内部独立消费者保留原 fallback。确认只清本地内容，不删除持久草稿、不取消后台已发事务、不重发未知写入。
- 七项新纯回归及 `npm run check` **全部通过**：逻辑 **218/218**、架构 **8**、Hooks **3**、浏览器工具 **4**、视觉工具 **7**、国际化工具 **5**、Sites **4**；三语 **1089** 键/locale，主包 **926.37 kB / gzip 273.01 kB**，容量警告仍待 F5.6。
- 新导航真实浏览器 **6/6、0 fail/skip/cancel、15.40s**；覆盖程序 push/replace、原生 back/forward、外部 hash、原始未知写结果核查、native close、Escape 及 320px 日文 Dialog。初轮 **0/6** 为探针误读 Vite CommonJS 的 `createRoot` 导出，修正加载方式后整组复跑，不归因业务或掩盖失败。已实际查看 `/private/tmp/sentinel-f4-navigation-20261007/narrow-ja.png` 与 `desktop-ja.png`，内容/动作完整且无裁切。
- App 已装配全局路由 owner，但实际页面仍有待 F6 退役的旧 demo 消费者；以上规则 Port 验证不代表全页面 HTTP/Python 路径。该份冻结源码的完整前端浏览器回归实际 **193/193、0 fail/skip/cancel、510.98s**；F2.5/F4.08/30 未提前勾选。
- 随后补齐版本名称/备注、发布原因、计划取消原因和活动计划七项临时输入的离开登记；仅清本地意图，不写后端。计划 pristine/reset 与每字段变更增加纯回归。定向浏览器首次 **21 pass / 1 fail**：Tab 经过关闭按钮触发 Astryx tooltip，首次 Escape 正确只关闭 tooltip，测试却误期望关闭 Dialog。诊断确认可见 top-layer 后改为逐层断言，未修改厂商或放宽安全合同；最终导航 8 + 发布/计划 7 + 草稿 7 **22/22、0 fail/skip/cancel、21.70s**。新的全量证据另行记录，不把此前 193 项冒充修改后已跑。

## 14. F5 工程门禁收口：实施前矩阵

已有 F4 内部页面、资源和命令切片进入稳定回归后实施本节，再进入 F6 的唯一 HTTP/App 迁移。F4 消费者/完整入口相关 checkbox 不以内部探针代替；F5/F7 最终矩阵随 F6 升级为同一网络路径，不能保留依赖 FixtureGateway 的验收假绿。

| 范围           | 断言与责任                                                                                                         | 证据/退出条件                                                                                          |
| -------------- | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| 国际化所有权   | 每个 JSON 键只归属其 feature 或 shared observation/shell；三语文件集合、键集合和插值相同；无原始字段名替代用户文案 | 文件/键负例；显式动态映射与 i18next plural 渲染测试；三语真实控件回归                                  |
| React 代码门禁 | 生产源码使用已安装官方 Hooks recommended 规则；类型由当前 tsc 检查；不以不受支持的 parser 冒称类型感知 lint        | 错 Hook、依赖、输入 mutation、render effect/purity 等负例；完整现有源码验证                            |
| 分包/容量      | root 只引用路由/Provider/skin；图表/编辑器/模态按可用性延迟；不能分包后只报小 entry 隐去初次加载依赖总量           | Vite manifest 的 entry+静态依赖/gzip、lazy 路由/编辑器实际分块；首屏/导航用户结果与按需 Dialog失败恢复 |
| 统一 verify    | 单脚本按静态→浏览器→视觉执行；浏览器需健康隔离 Vite/专用 Chrome profile；启动/服务失败/测试失败退出非零；有界清理  | 正/负脚本测试、本地实跑，清理只操作自己进程与临时目录；受保护 Sites 测试仍执行                         |
| CI             | 独立前端 job，不替换 Python CI、不触发发布；Node/Chrome/registry 前提明确；失败保留日志和截图                      | checked-in workflow 与本地同一 verify；远程执行另行标明，未 push 不称 GitHub run 通过                  |
| 像素保护       | DOM 与 PNG 独立；用户已确认暗色视觉继续保留；实际缺陷先修根因再截图                                                | 原 29 态稳定捕获比较与新增正式 UI 日文桌面/窄屏图，最终 F6 切换后有意差异逐项说明                      |

初始只读检查 `i18n:audit -- --summary` 显示源码视图/读模型 **0** 条硬编码 CJK；这只是线索，不代替动态字段/跨组件实际渲染。评估已安装 `eslint-plugin-react-hooks@7.1.1` recommended：生产 src 无新告警；原 test-only 效果双的直接控制 mutation 产生 31 条 immutability 诊断，后续处理见下方。

typescript-eslint [官方支持窗口](https://typescript-eslint.io/users/dependency-versions/) 当前为 TypeScript `>=4.8.4 <6.1.0`，而本工程使用 7.0.2；不无理由降级现有编译器或装入不受支持的 typed parser。Babel 负责现有 TS/JSX 语法，tsc 负责类型；此两者不等同 no-floating-promises/no-unsafe-* 类型感知规则，最终 HTTP decoder 和行为合同必须另行验证。

### 14.1 代码门禁与国际化资源：实施记录

- 官方 Hooks recommended 已实际启用，生产无 suppression；access/authentication/login/password/initialization/account-management 六组测试传输效果各有 private factory，内部状态、延迟释放与计数不通过可变 props 暴露，组件仅调用显式命令并读取无密码诊断副本。首次检查发现四处 useMemo 直接传 factory 不符合 recommended 的 inline factory 规则，修正后 lint 通过。六项正负门禁覆盖 Hook 顺序、effect 依赖、props mutation、render 非确定性、同步 effect 派生状态及合法效果命令。
- `catalog.ts` 是资源组装/所有权/插值身份的唯一纯合同。九个文件各有固定 key root，identity 的九类 root 显式归属；缺文件/额外文件/跨域键/空值/非字符串拒绝。runtime 和 keycheck 复用同一组装及三语 key/插值验证，不再复制正则或组装策略。
- 六种计数文案增加 i18next 原生 `_one/_other`，保留原基础键；三语 key 集合一致。真实独立 i18next instance 按三语言、六键、0/1/2 实际渲染测试（54 组合），英文 `1 rule` / `2 rules` 正确，不修改协议数值或草稿。资源/提取工具 **9/9**；现有 122 个变量调用仍如实报告，不能冒称全部动态键已静态穷尽。
- 本批完整 `npm run check` 实际通过：逻辑 **219/219**、架构 **8**、Hooks **6**、浏览器工具 **4**、视觉工具 **7**、国际化工具 **9**、Sites **4**；三语 **1101** 键/locale，主包 **931.03 kB / gzip 273.97 kB**，容量警告未调高。之后截图目录改为受控 `SENTINEL_TEST_ARTIFACT_DIR` 或系统临时目录下的具名套件路径，禁止 traversal，不删除外部基线；独立新增路径负例 **1/1**，跨平台与统一 runner 收口继续实施。
- 六组修改过的身份页面同份冻结源码实际重跑 **20/20、0 fail/skip/cancel、50.94s**（access/authentication/login/password/initialization/account-management），没有把测试效果工厂调整当作“只改测试所以不用回归”。正式应用的入口装配仍待 F6。

### 14.2 统一入口与后续依赖收口

- `scripts/verify.mjs` 与私有 `verification/process.mjs` 持有阶段编排和子进程效果；static → 专用 Vite → 完整浏览器 → 29 态稳定捕获 → 可选既有基线比较。每次单独生成证据目录和 receipt；不覆盖基线、不附着正在运行的用户服务。启动失败、非零退出、超时及 SIGTERM 不响应分别有限失败；只给自己创建的进程组发信号。截图库仍自行关闭 Chrome 并清理其独立 profile。
- runner 的三项真实正负测试最终 **3/3**：参数不得静默缩小范围；实际成功、非零、spawn failure、timeout 与拒绝 SIGTERM；健康 React 文档、拒绝端口和服务提前结束。首次运行端口负例因 sandbox 的 `listen EPERM` 失败，使用已授权本机回环权限完整复跑后通过，不删 socket 测试或以 Mock 替代。
- `npm run verify -- --static-only --artifacts /private/tmp/sentinel-f5-verify-20261007` 已实际结束，通过。证据 `/private/tmp/sentinel-f5-verify-20261007/sentinel-verify-FO9XFV/{static.log,receipt.json}`：逻辑 219、架构 8、Hooks 6、浏览器工具 5、视觉工具 7、国际化工具 9、runner 3、Sites 4，全无失败/跳过；receipt 的 scope 为 static、pixelComparison 为 not-requested，不误记为浏览器或像素验收。
- 独立 `.github/workflows/dashboard.yml` 已落地，保留既有 Python CI；Node/Chrome 缺失即失败，不跳过浏览器，always 保存证据。未提交、未 push，远程 CI 没有执行证明。本机统一 browser-only 已实际完成，receipt `/private/tmp/sentinel-f5-verify-20261007/sentinel-verify-IhvQio/receipt.json` 为 passed/browser：完整 **196/196、0 fail/skip/cancel、517.45s**，随后 **29/29** DOM/PNG 捕获均稳定 2 次收敛。pixelComparison 为 not-requested，没有把截图生成当成比较。独立对 F3 图表完成基线的总览/应用/实时监控三态实际严格比较 **3/3 DOM 等价与渲染一致**（总览 294px 差异在默认容差内，未提高容差或接受列表）；已查看当前规则、应用 PNG，暗色布局保持。此证据属于后续语言适配实施前源码，不冒称新修改已全量通过。
- 容量检查的根因不能只靠 manualChunks 掩盖：旧 AppProvider 静态导入 FixtureGateway、固定目录和同步 feature seed，仍使主入口含旧业务数据；真正的生产 seed 隔离依赖 F6 消费者/Provider 替换。F5.6 先建立静态入口/依赖总量观测，再与 F6.8/F6.12 一起验收，不因阶段表顺序而保留旧网关或对它新增能力。F5.1/.2/.4/.5 的完整 App 路径同样在 HTTP 装配后收口；当前内部页与工具通过不代替最终网络证明。
- 检查到的 Astryx 内部关闭/清除/分页标签原来回落英文，后续语言切片已实施：`AstryxProvider` 从 App 唯一 i18next locale 推导 vendor `InternationalizationProvider`，导入官方 zh-CN/ja-JP catalogs，英文沿用厂商自带；不复制 translator、不覆盖厂商 DOM。i18next v26 使用安装类型已支持的 `initAsync:false` 显式同步初始化；删除了旧注释中“语言进入 URL 会分享权限”的错误理由，语言与授权没有关联。

### 14.3 厂商语言与真实容量测量

- 同份冻结源码真实弹窗/导航/发布计划浏览器 **24/24、0 fail/skip/cancel、58.38s**，含新增关闭 ARIA 三语言往返、打开时切换不丢输入/URL/提交状态及关闭后焦点恢复。不是只查 JSON 或自行替换 Close 文案。全量修改后证据另行记录，不能把上一轮 196 冒充这一轮结果。
- `vite build` 输出真实 manifest；`scripts/build/bundle-report.mjs` 计算 entry 与递归静态依赖一次去重、各 lazy 入口完整依赖及首屏之外的增量，独立逐文件 gzip level 9。两项正负测试覆盖共享依赖、环、丢失 lazy 引用/资产、畸形记录和路径逃逸。报告仅覆盖 manifest 链接的 JS/CSS/assets，明确不含 HTML/public/未列入的 CSS URL 与运行请求，不冒称传输时延或全网络字节。
- 本批 `npm run check` 全链实际通过：逻辑 **219**、架构 **8**、Hooks **6**、浏览器工具 **5**、视觉工具 **7**、国际化 **9**、runner/容量 **5**、Sites **4**；三语 **1101** 键/locale。实际 manifest 首屏 JS **1,046,492B**、首屏 manifest 资产 **1,263,623B / gzip 339,712B**，**9** 个延迟入口；单主 chunk **1,046.49 kB / gzip 302.32 kB**。官方两语言 catalog 与厂商 ICU 支持增加包体是可见代价，500kB warning 未调整；生产 seed 排除和按需能力装配仍与 F6 一起收口，F5.6 不提前勾选。
- 修改后统一 browser-only 完整 **197/197、0 fail/skip/cancel、527.76s**，29/29 捕获稳定收敛；receipt `/private/tmp/sentinel-f5-localized-20261007/sentinel-verify-hM9bXE/receipt.json` 为 passed/browser、pixelComparison=not-requested。随后独立严格比较上一轮 29 态：**29 PNG 全部一致、27 DOM 等价**；accounts/system-accounts 仅隐藏 Close ARIA 与 tooltip 译为关闭，逐内容替换核对后 DOM 完全相等。只对这两处有理由接受 DOM 语言变化，无 ACCEPT_RENDER、未放宽像素容差，比较最终通过；没有覆盖旧基线。HTTP/App/Python E2E 仍未完成。

## 15. F6 唯一 HTTP 迁移：实施前合同收敛

当前内部正式页面已经给出异步 Port 和用户行为证据，不再从同步 FixtureGateway 推导字段。语言适配的全量浏览器冻结期间仅整理文档，未替换实际 App、不修改受测源码。Console 契约 §9 为唯一当前入口，旧 §0–8 保留沿革并明确失效，用户已有五项决策没有无痕删除；后续机器合同/HTTP 还未完成，F6.1 不勾选。

| 输入与实现职责       | 本轮决定 / 必须补的证据                                                                                                                                                                            |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| wire 及 schema       | `/api/v1`、直接类型化 JSON、严格对象/判别联合；feature wire schemas 为源，生成 JSON Schema/OpenAPI 与正负样例，不保留第三套 runtime 翻译/验证框架                                                  |
| typed JSON 依赖      | 拟采用 Zod 4，官方原生 toJSONSchema；JSON 类型与业务语义检查分离，不用 experimental fromJSONSchema/unrepresentable:any。精确版本/实际安装/生成校验后另记                                           |
| 日期与数字           | wire RFC3339 UTC、内部 epoch 毫秒由显式 mapper 转换；持续时长保留安全整数。绝不全局按字段后缀盲目转换，例如 stepMs/latencyMs 并非时间戳                                                            |
| 初始化缺口           | 一次性 operator 授权 + CSRF/Origin，setup 内新增启动授权字段；原四步和初始化 owner 复用，未授权不发 DB/source 检查。Cookie/operator 与管理账号会话分开，关闭窗口/重启不重新开放                    |
| App 目录缺口         | 增加独立 observation catalog 读面，真实环境/应用来自后台；不能以固定 APP_SCOPE_IDS 或一页实例矩阵推断全目录                                                                                        |
| side-effect 单一路径 | 稳定 application DI → feature HTTP → foundation HttpClient/Url，maxRetries=0；所有浏览器模式用同一实现，MSW 只在 HTTP 拦截，不注入 fixture gateway                                                 |
| command 与 revision  | setup/account/rules/source 各自安全 operation，原 key 核查不重发；domain rejected 与 HTTP 认证/shape 错误分开；账号/草稿/计划/源修订各有 owner，source native revision 不用 Console versionId 代替 |
| provider 边界        | Nacos/Consul addressing、凭证、SSRF、条件写/回读在 Python；profile 控制完整数组兼容，不静默丢规则；旧未提交前端 provider drafts 的评审/迁移继续 F6.11                                              |
| Mock/live 验证       | 未匹配 Console 请求 fail closed；两模式取消/超时/畸形/401/403/409/429/5xx 和命令未知结果证据。生产无 seed/worker/default admin，显式 demo 制品另行声明                                             |
| 最终 B0              | 新 Console 运行模式与既有 per-process 内嵌诊断保持兼容；真实隔离 PG/MySQL/Nacos/Consul、会话/CAS/审计/计划重启/打包静态资产 E2E，不写用户运行中的真实源                                            |

实施次序：先身份/setup/共同安全与时间 primitive schemas 及 HTTP 传输合同正负测试，再按观测/规则/系统消费者扩展；每一能力仍要与完整 App/Mock 的迁移收口，不能仅凭新增 adapter 勾整项。根路径、Cookie/CSRF、错误结构、目标身份、完整快照和计划时区等五类高影响配置不会靠宽 unknown 放行。

额外源码检查与版本前提（非已完成实现）：

- registry 只读核对：`zod@4.6.5` 为 MIT；`msw@3.0.2` 为 MIT，Node `>=22.12.0`，兼容工程选择的 Node 22.18。全量浏览器期间未安装或修改 package/lock；安装后必须再核对实际 API/类型与同一请求路径，不照旧 MSW 2 示例猜接口。
- 安装的 foundation `HttpClient` 在 managed headers 关闭后仍直接读 legacy `localStorage.user_id` 并注入 `x-user-id`；Console transport 必须用公开 request interceptor 去掉该身份头与无关旧 gateway/device 字段，不能把 MemoryStorage 或一个 config 开关当作已隔离证明。后台仅以 Cookie/session 鉴权，不信任上述头。
- foundation 在 response interceptor 后回调 onUnauthorized，并把原错误 body 保存在 AppError。Console adapter 必须重建脱敏有限错误，不把 raw responseBody/cause/message 传给业务；401 回调须关联原 requestId/当前会话 generation，避免忽略取消的旧响应把新登录踢出。csrf header 更新也须在对应安全响应解码及所有权确认后提交，不能不加区分地让任何迟到请求覆盖当前 token。
- 传输和 shape 的正负证据必须覆盖上述两个底座实际路径，不能只直接调用 schema 或注入成功 Port 冒充网络验收。
- wire 反推曾暴露内部观测合同缺口：分母仅整数、回执分页混用覆盖分母。该缺口已按下节模型/页面证据修正；不以未上报数假造权威 inventory。

### 15.1 观测分母与第一批真实 HTTP 合同

- `InventoryCoverage` 区分已知分母及非空权威来源、未知分母及 null 来源；回执分页 `total` 独立于 `expected`。未上报目标可为 null processEpoch，但 Applied 必须匹配当前真实 incarnation/version/checksum。覆盖判定不把未知分母转为 0，也不把“全部已上报”当成全部预期实例。逻辑由 219 增至 **221**；观测/规则回执真实页面 **13/13、0 fail/skip/cancel、31.42s**，含未知 inventory、未知 incarnation 及旧重启回执。已查看当前 320px 日文 fleet PNG，未使用旧路径截图冒充本轮。
- 已实际安装 Zod **4.6.5**、MSW **3.0.2** 并锁定版本。共同 transport 仅使用安装 foundation HttpClient/Url，禁用自动重试与旧身份头；验证请求相关 ID、严格 UTF-8/Content-Type、流式 1MiB 上限、JSON 深度、精确成功码与有限脱敏错误。CSRF 仅由当前 generation 的已验证响应进入内存；当前 malformed 401 仍撤销授权，旧 generation 401 不撤销新 owner。命令 ACK 无法验证仍为 result-unknown，不释放重提。
- bootstrap/登录/注销九个真实 consumer endpoint 和同源 OpenAPI 草案已落地：runtime Zod 同时生成 JSON Schema，逐 HTTP status 限定错误 code，204 无 body；引导授权不是管理员会话，operator code/DB/source credentials 仅写入。initialize ACK 不允许 not-found，原 key lookup 可返回 not-found 但不代表回滚。该批完整 `npm run check` **通过**：逻辑 221、HTTP 23、架构 8、Hooks 6、浏览器工具 5、视觉工具 7、i18n 工具 9、verify/容量 5、Sites 4；locale 1104。首屏 manifest JS 1,047,600B、资产 1,264,731B/gzip 339,959B，9 个延迟入口；仍未切 App，容量警告保留。
- 后续账号管理/本人改密五个 endpoint 已落地，机器合同当前 **14** 条路径、draft-partial，不误称已冻结全 Console。账号读面禁止密码/显示名称等额外字段；分页身份、条数、唯一 ID、built-in/last-admin 提示逐项验证。create/status/role 的 command receipt 校验原 key、目标/effect/新修订；not-found 仅查原操作合法。本人密码不接目标/confirm，不保存输入，无法确认时不重放。
- 本批 `typecheck` 通过；HTTP **30/30、0 fail/skip/cancel、427.76ms**，包含真实 foundation→MSW→已有账号/改密 workflow、拒绝多余凭据、畸形/异目标 ACK 保持未知及独立本机临时 HTTP 服务。首次 sandbox loopback `listen EPERM` 导致 29/30，不删测试；获临时 loopback 权限完整重跑后 30/30。OpenAPI 已重新生成 14 paths。Python尚未实现，HTTP MSW 或 Node loopback 不等同 Python/持久化/产品 E2E；App 与全模式组装及余下观测/规则/系统接口继续推进，F6 整项不提前勾选。

### 15.2 实例、故障分析和系统管理读取合同（继续实施，未完成 F6）

- 实例目录/详情新增独立严格 wire、UTC mapper、HTTP adapter 和 Port contract：`GET /api/v1/instances`、`GET /api/v1/instances/{instanceId}`。目录过滤及服务端分页是显式 query；详情身份由 path `instanceId` 唯一提供，`processEpoch`、scope、window 必须与回执和指标一致。服务端 410 `target_retired` 被投影成原详情 owner 可识别的 `instance_incarnation_changed`；一次进程替换会使旧 incarnation 指标与回执失效，而不把 URL path identity 重复塞进 query。测试发现并修复了 mapper 把 wire `receivedAt` 原字段和领域 `receivedAtMs` 同时带入的问题。
- 故障分析新增时间线/证据两个只读端点：`GET /api/v1/incidents`、`GET /api/v1/incidents/{incidentId}/evidence`。合同区分发生时间与接收时间（采集延迟可使接收时间晚于查询窗口），固定半开窗口、筛选、稳定排序、游标及全范围统计；事件标题只能由有限结构化事实构成，禁止任意业务日志、异常堆栈和推断根因。证据必须关联 path event ID、当前范围/过滤，且建议视图只用于导航。
- 系统管理新增独立连接、协议、审计 HTTP Port：`GET /api/v1/system/connections`、`GET /api/v1/system/protocols`、`GET /api/v1/system/audit`。连接健康是服务端探测并带到期时刻，不使用浏览器 online；协议支持集合与实际活动版本/兼容状态分开；审计使用独立有界 UTC 半开窗口、actor/action/result/page 筛选，拒绝密码、凭证、请求正文和自由日志。
- `CONSOLE_OPERATIONS` 从 feature 级 DTO/endpoint 声明生成 OpenAPI；本轮接入规则读写合同后共 **38 个路径**，状态仍为 `draft-partial`。已覆盖身份/bootstrap/accounts/本人改密、metrics/fleet/instances/observation-catalog/incidents/system-observation/rulesets，pending 为 system-commands。生成后 `contract:check` 通过；这不是完整协议冻结，也不是 Python 已实现。
- 新增 `GET /api/v1/observation/catalog`，返回当前会话可见的环境与应用选择项；同名 app ID 允许存在于不同环境，但每项必须指向已返回环境。其目的不是伪造实例 inventory 或自动选第一个应用。测试首次发现 wire `asOf` 被 mapper 泄漏到领域对象，已修为只投影 `asOfMs`。
- 本轮完整 `npm run check` **通过**：typecheck/format/lint、Hooks 6、架构 8、逻辑 **221**、HTTP **53**、machine OpenAPI 24 paths、浏览器/视觉/i18n/verification 工具、三语 1104 键/locale、production build 与 Sites 4；initial JS 1,047,600B，资产 1,264,731B / gzip 339,959B，chunk 警告保留。HTTP 包含获本机 loopback 权限后的真实临时 HTTP transport 验证。
- 尚未把这些 adapter 注入 `AppProviders`，旧 `FixtureGateway`/同步页面消费仍在，MSW browser worker 尚未组装；本轮没有运行 Python 后端。F6.1 的完整页面动作清单和最终协议评审仍未完成；F6.2 仍是分批 adapter，不打勾；F6.3–F6.12、F7 和全部 B0 继续未完成。38 个 OpenAPI 路径、HTTP 契约测试、原型浏览器 E2E 都不替代真实 React App → Python Console → 持久数据库/配置中心 → 重启恢复的 E2E。

#### 15.3 当前原型浏览器基线复验（2026-10-07）

- 在同一冻结源码上，`CHROME_BIN='/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge' npm run test:e2e` **199/199 passed，0 fail/cancel/skip，705.96s**。系统默认 Chrome 路径不存在导致的首次启动错误已通过显式 Chromium Edge 路径绕过；测试脚本本身尚未自动发现 Edge，因此这是本机受控浏览器运行证据，不是 CI 默认环境可移植性证明。
- 通过项覆盖身份/账号、路由/导航、全量 11 路由窄屏/桌面/200% 等效缩放、规则工作台/目录/部署、初始化与凭证安全、Nacos/Consul source UI、审计/权限撤销、图表和交互边界。规则未知结果不重放、源切换要求重新确认、跨权限迟到响应不可复活数据等负路径均已运行。
- 该结果证明当前交互原型回归稳定，不证明 `AppProviders` 已切到新 Console HTTP 适配器（当前仍注入 `FixtureGateway`），也不证明浏览器 MSW、Python Console、MySQL/PostgreSQL、Nacos/Consul 或重启持久化。F6/F7/B0 仍未完成；后续最终 E2E 必须在实际应用 HTTP 路径上重跑并通过。

#### 15.4 规则集合 Console HTTP 合同（F6.1/F6.2 分批交付）

- 已按现存唯一 Console API 合同为 `RuleSetPort` 增加严格 Zod wire、UTC mapper、全新 `createRuleSetHttp` 和 machine-contract：规则绑定分页、权威完整快照、草稿/版本/发布/回执/计划、候选校验/差异、幂等命令和原操作查询，共 14 operations。没有把实现反向注入页面，也没有把 `FixtureGateway` 改名为 HTTP 网关。
- 跨层语义覆盖：URL path target 与回包 identity 一致；列表回显完整 query；RuleValue 按五类严格判别；时间戳仅通过明确 `asOf/createdAt/updatedAt/observedAt` UTC mapper 转换；候选必须是完整、同 kind、有限值且 record ID 不重复；草稿/版本/发布/计划属于正确 binding；发布回执要匹配 publication、进程 incarnation、版本和 checksum，未知 inventory 不伪造分母；写命令从 body/request header 复用同一 requestKey，pending/not-found 只可核查不能重放。
- 本轮继续补齐系统管理来源写路径：Nacos/Consul 来源清单、无副作用连通性检查、条件登记/更新、原操作核查共 4 个 HTTP operations。wire 只读回安全来源元数据；直接凭证/引用 ID 仅写入，检查 POST 有 CSRF 但不是可重放持久写命令，登记/更新才使用 requestKey 幂等及未知结果核查。Port、UTC mapper、严格 Zod schema、机器合同和 OpenAPI 一并生成；现为 **42 paths / draft-partial / pending=[]**，但不代表整套页面动作已冻结或 Python 已实现。
- 来源清单/检查/登记/原操作核查的 HTTP 测试 **4/4 passed**；包含 credential 不回显、CSRF/Idempotency-Key 区分、输入拒绝不 dispatch、未知结果原 key 查询。修复 Console transport 超时边界：即便下游 `fetch` 忽略 `AbortSignal`，本层 deadline 仍终止观察并中止请求信号；迟到响应被丢弃，已 dispatch 写入保持未知、绝不重放。最新完整 `npm run check` 通过：typecheck/format/lint、architecture **8/8**、logic **224/224**、HTTP **64/64**、contract **42 paths / draft-partial / pending=[]**、browser/visual/i18n/verification tools、三语键校验、build、Sites **4/4**；HTTP 临时 TCP listener 使用仅本机绑定的授权运行。production bundle 初始 JS **1,144,293 B**，仍超 500 KB warning，必须后续处理。
- 已新增 `main` 负责的应用生命周期 transport + request-owner provider，并验证身份 Port 可用同一 transport 执行 bootstrap；所有 feature HTTP adapter 不静态汇总进主入口，以保留懒加载分包。显式 `mock | live` 配置、挂载前启动 MSW、live origin 校验、mock 未实现 `/api/v1/*` 返回 503 防透传仍存在；worker 文件由锁定版本 MSW CLI 生成并进 build 资产。当前页面仍未迁到 HTTP；没有 feature mock handler/mock state，生产 bundle 排除 mock/演示数据也未完成。因此 F6.5/F6.7 仍只部分实现，不勾整项。
- 当前同一代码状态下，`CHROME_BIN='/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge' npm run verify -- --browser-only --artifacts /private/tmp` 已实际结束 **passed**：browser E2E **199/199，0 fail/skip/cancel**，29 个视觉状态捕获全部 settle；receipt `/private/tmp/sentinel-verify-JOvqMd/receipt.json`，视觉目录 `/private/tmp/sentinel-verify-JOvqMd/visual/`。receipt 明确 `pixelComparison=not-requested`，所以不是像素基线对比证明；这些场景目前仍主要运行旧页面/fixture 路径，不是新 Console HTTP/App/Python E2E。
- 已知剩余：feature adapters 尚未进入各自的 App consumer；MSW 只有 fail-closed 兜底，没有浏览器/node 共用业务 handlers 或 mock state；整套页面统一异步接线、mock/live 请求目的地验证、完整 F6.1 页面动作审查及 Python Console 后端均未实现。F6.1/F6.2 不勾整项，F6.3–F6.12、F7、B0 仍未完成；隔离 HTTP/MSW 契约与原型浏览器通过不等于 React App → Python → 持久数据库/配置中心 E2E。

#### 15.5 总览页面 HTTP 首个纵向切片（F4.01/F6.3/F6.5/F6.6，部分交付）

- 总览路由已从同步 `OverviewPage` 切到正式 `FleetOverviewContainer`：由应用装配注入唯一 Console transport；先读授权环境/应用目录，再通过 `createFleetHttp` 查询总览。查询状态仍由 feature `QueryResource` 持有；UI 不选择 mock/live，也不直接访问 fetch。
- 为当前页面增加明确的 mock-only feature 入口与 MSW handlers：只在 mock 模式的 bootstrap 中动态加载；`GET /api/v1/observation/catalog` 提供单环境合成目录，`GET /api/v1/fleet/overview` 实际按 scope/window/page/pageSize/search 返回严格 wire shape；未匹配 API 继续 503 fail-closed。源数据放在总览 feature fixture；原 HTTP 测试改从同一个 seed 引用，避免复制第二份假数据。
- 浏览器 E2E **1/1 passed**（Edge / 本机 Vite `127.0.0.1:4175`）：从 `/#/overview` 实际进入新页面，断言三条 HTTP mock 应用记录及 QPS 值 123，控制台错误为 0。页面截图 `/private/tmp/sentinel-f6-fleet-evidence/sentinel-f6-fleet-http/overview.png` 已实际查看；截图仅证明本次 mock 页面渲染，不证明生产视觉基线像素等价。Node MSW + Console transport + catalog/fleet adapters 的组合测试 **1/1 passed**，覆盖分页、UTC 投影和未接入 TPS；全工程 `npm run check` 当前代码状态全部到达通过输出：typecheck、format、lint/Hooks、架构 **8/8**、逻辑 **224/224**、HTTP **65/65**、OpenAPI **42 paths / draft-partial**、浏览器/视觉/i18n/verification 工具、三语资源、build、Sites **4/4**。
- Build 报告初始 JS **1,148,762 B**、manifest 初始资源约 **1,365,893 B / gzip 370,180 B**、12 个延迟入口；单 chunk 500KB warning 仍在，不能算容量门禁收口。构建已见 MSW handler 作为延迟 mock chunk，但生产构建明确排除演示数据/worker 的 F6.8 尚未实现。
- **不勾选 F4.01/F6.3/F6.5/F6.6**：此处只完成总览读取切片；目录仍为合成单环境，尚无多环境/会话授权矩阵；其余页面仍有旧 `FixtureGateway`/同步消费，账号认证、setup、写命令、其他 feature mock state 都未接入。仍未运行 Python Console、真实会话、数据库/Nacos/Consul；mock 通过不得称为最终 E2E。应用实例观察页后续交付见 §15.6。

#### 15.6 应用与实例页面 HTTP 纵向切片（F4 / F6 部分交付）

- 应用页路由现在通过 app service 注入共享 Console transport，切换至 `ApplicationsObservationContainer`；环境/应用列表来自 `GET /api/v1/observation/catalog`，实例页目录与详情分别使用 `GET /api/v1/instances`、`GET /api/v1/instances/{instanceId}` adapter 和单独的 QueryResource owner。筛选、窗口、分页、搜索、环境/应用、选中实例及 scope 使用 URL/feature 查询身份；未从静态 `APPLICATION_SCOPE_IDS` 自动挑中 app，Applications route 保持 `all` 并允许按已授权目录选择。
- 明细只从当前目录快照中匹配明确的 instance ID，再带该进程 incarnation、scope、时间窗查询；过滤/分页不会自动换选其他实例。StrictMode 下 owner 清理只取消请求，不永久 dispose，避免开发模式 mount-effect replay 后资源不能再加载。旧 fixtureGateway 在其他页面仍存在，不能称全站迁移。
- 新增 applications feature 独立、显式注册的 MSW handler 与 canonical synthetic fixture；Node 端真实 Console transport + MSW + adapter 组合测试 **1/1 passed**，覆盖目录分页查询、UTC 投影和实例详情过程 epoch/scope。未把应用 fixture 引用到 overview 私有 fixture；目录 handler 与 fleet handler 由 app mock registry 统一组合，避免重复路由。
- 浏览器 E2E `applications-http.e2e.test.mjs` **1/1 passed**（Microsoft Edge、Vite `127.0.0.1:4175`）：显式 app/environment URL 加载目录，点击实例后读回执与 QPS 详情，URL 精确保留 `instance`/`scope`，无控制台错误。截图已查看：`/private/tmp/sentinel-f6-applications-evidence-final/sentinel-f6-applications-http/applications.png`。它是 mock HTTP 页面视觉证据，不是像素基线对比，也不是后端验收。
- 最新完整 `npm run check` 通过：typecheck / format / lint、Hooks **6/6**、架构 **8/8**、逻辑 **224/224**、HTTP **66/66**、OpenAPI **42 paths / draft-partial**、浏览器工具/视觉工具/i18n/verification 工具、三语资源、production build、Sites **4/4**。build 初始 JS **1,149,315 B**、manifest 初始资产 **1,366,446 B / gzip 370,265 B**，仍有单 chunk 超 500KB 警告；production 排除 mock/seed 仍未完成。
- **仍不勾 F4/F6 大项**：这两页只证明所选 mock 查询链路。应用目录是固定 test fixture；没有真正登录会话权限、API live 指向 Python、数据库/指标采集、跨环境实例完整度或多 worker 验收，实例详情也未在 Python Console 运行。下一条目继续迁移实时监控/故障/系统等页面，各自补真实 adapter、mock 场景和浏览器 E2E；所有页面连上后再集中跑一次完整浏览器和视觉套件。

#### 15.7 实时监控与故障分析 HTTP 纵向切片（F4 / F6 部分交付）

- 实时监控路由现由 `RealtimeObservationContainer` 装配 authorized observation catalog、`createMetricsHttp` 与实时轮询 monitor。窗口、应用、环境及监控暂停状态经页面路径实际执行；暂停只停止浏览器查询，不发送 Collector/Sentinel 命令。TPS 未接入时仍明确显示 unavailable，不由 QPS 推算。Realtime mock handlers 只从显式 mock registry 动态加载。
- 故障分析路由现由 `IncidentObservationContainer` 经共享 Console transport 读取事件目录、时间线和具体事件证据；完整统计只从服务端返回，不在页面按本页分页重算。URL 深链能恢复已选 `eventId`；证据包含结构化事实、发生/接收时间与完整度，不含业务日志/traceback，也不声称自动根因。筛选与分页仍由现有 incidents Port 合同约束。
- 为 incidents 新增 feature 私有合成 fixture、mock handlers 和 HTTP 组合测试。时间戳按查询窗口构造；handler 校验 scope/context/filter/cursor/pageSize，仅回传稳定字段；具体事件不可见时返回 not-found，不替换成首条事件。实时指标及 incidents mock 均经实际 `ConsoleTransport → MSW → feature adapter → QueryResource → 页面`，不是直接在组件里返回假数据。
- 本机浏览器页面 E2E 对总览、应用实例、实时监控、故障分析 **4/4 passed**（Edge + Vite `127.0.0.1:4175`）。其中故障测试验证列表、显式选择、事件 URL、两条证据事实；截图 `/private/tmp/sentinel-f6-four-pages-evidence/sentinel-f6-faults-http/faults.png` 已检查，无控制台错误。截图是当前 mock 页面视觉证据，不是像素基线比较，更不是真实后端验收。
- 最新 `npm run check` 全部通过：typecheck/format/lint、Hooks **6/6**、架构 **8/8**、逻辑 **224/224**、HTTP **68/68**、OpenAPI **42 paths / draft-partial / pending=[]**、浏览器/视觉/i18n/verification 工具、三语 **1104** 消息对齐、production build、Sites **4/4**。生产构建初始 JS **1,152,761 B**，manifest initial assets **1,369,892 B / gzip 371,108 B**；仍有单 chunk >500KB warning，mock/seed/worker 的生产排除与包体门槛尚未验收。
- **仍不勾 F4/F6 大项**：当前只有四个查询页接到正式 HTTP adapter；事件仍是 mock 数据。故障和实时 monitor 的客户端 access observer 仍是本 slice 的临时 session projection，尚未接入真实 Authentication/Session 权限生命周期；真正的 live origin、Python Console、MySQL 持久化、授权目录、采集器和重启恢复都未运行。Rules、System、Identity、setup/login 及页面操作仍需迁移；完整浏览器套件/像素回归须待页面整体接入后统一跑。F4/F6、F7、B0 总项及 Python/真实环境 E2E 均继续未完成。

#### 15.8 系统管理观测页面 HTTP 纵向切片（F4 / F6 部分交付）

- 系统管理路由现由 `SystemObservationContainer` 装配系统观测 HTTP ports/resources。连接探测、协议协商、操作审计使用三个独立 QueryResource 及既有严格 HTTP schemas；失败互相隔离。保留权限声明、账户维护、角色绑定组件原位；其中身份/账号依然是旧本地/fixture 路径，不因本次读模型迁移而宣称真实化。
- 原页面实际未展示已实现的审计面板，已增加独立 `audit` tab 和中/英/日正式标签；其筛选/分页仍由 audit Port 管理。publication 深链使用新增、语义独立的 `publicationId` URL 键，不复用 `versionId`。这只是导航上下文保真，规则页尚未实现按 `publicationId` 自动定位；接口仍需后续闭环。
- 审计访问的客户端快照暂按现有 demo session `admin`/`view` 做管理员可见投影，backend remains authoritative；这不是身份后端集成。Node HTTP/MSW 组合验证三类资源及脱敏字段；本机页面 E2E **1/1 passed**，覆盖连接/协议/审计 tab、列表数据、审计 deep link。截图 `/private/tmp/sentinel-f6-system-evidence-final/sentinel-f6-system-http/system-audit.png` 已检查并修复关联按钮/请求 ID 的换行碰撞。
- 当前整套质量门禁：`npm run check` 通过（typecheck/format/lint、Hooks **6/6**、架构 **8/8**、逻辑 **224/224**、HTTP **69/69**、OpenAPI **42 paths / draft-partial / pending=[]**、各测试工具、三语 **1105** 消息对齐、build、Sites **4/4**），随后 `git diff --check` 无输出。构建初始 JS **1,153,218 B**，manifest initial **1,370,349 B / gzip 371,175 B**；>500KB chunk warning 仍未解决。
- 五个已迁移页面（总览、应用实例、实时监控、故障分析、系统观测）同一源码状态浏览器回归 **5/5 passed**。该结果全部走显式 MSW mock，不能替代 Console Python 实现、MySQL/会话或配置中心的真实 E2E。F4/F6/F7/B0 等总任务保持未勾。

### 15.9 当前浏览器测试宿主修正与安全验证（2026-10-07）

- E2E 错误弹窗确认来自测试 runner 显式启动的 Microsoft Edge 子进程（测试机器没有默认 Google Chrome 可执行文件）；只读检查 macOS DiagnosticReports 确认 Edge **154.0.4258.62 主进程在启动阶段 SIGABRT / Abort trap 6**，faulting stack 经过 `TransformProcessType → _RegisterApplication → ___RegisterApplication_block_invoke`，发生在应用页面加载和断言之前。具体 macOS/Edge 启动根因尚未确定。该轮立即停止浏览器重跑，不把进程崩溃归类为页面断言失败，也不再以旧浏览器结果覆盖新源码状态。
- 修正 14 个隔离式组件探针的宿主前置条件：这些 probe 随后隐藏应用根节点并挂载独立测试组件，因此宿主改为等待公开匿名登录页面就绪，不再错误要求已认证的 `.app-shell`。实际 App 身份/权限流仍由独立 App E2E 验收；首次初始化页面仍使用专用未初始化状态注入。该改动只通过 Node 语法检查，**尚未启动浏览器验证**。
- 通过 Codex 内置浏览器继续真实 React App 验证，没有再启动 Edge。发现两个 App 路径缺陷并修正：① initialized mock bootstrap 违反严格 discriminated-union wire shape，导致登录恢复不可用；mock 现按生产 schema 返回，HTTP regression 覆盖 initialized restore 与 setup gate；② 账号/角色路由在 React StrictMode 的 Effect replay 中提前永久 `dispose()` 了 workflow，改用 `useOwnedDisposal`，仅在真实卸载或 owner 替换时释放。当前可观察证据：登录路由已恢复至总览；账号维护路由在 StrictMode 下显示 mock admin/viewer 两行，新增账号 Dialog 显示账号名、密码、角色三个字段；未提交任何账号写入。此为真实前端 + 显式 MSW mock 的浏览器证据，不是 Python/live backend 验收。
- 为 StrictMode 生命周期缺陷新增正式 App 回归：管理员从登录完成服务端事实恢复后进入账号管理，必须看到 mock 账号目录并可打开三字段创建 Dialog；测试已通过 `node --check`，尚未进入 Edge CDP E2E 执行。
- 本轮在本机授权 loopback 环境重跑完整 `npm run check` **通过**：typecheck、format、lint、Hooks **6/6**、架构 **8/8**、逻辑 **224/224**、HTTP **71/71**、OpenAPI **42 paths / draft-partial**、浏览器工具 **5/5**、视觉工具 **7/7**、i18n 工具 **9/9**、verification 工具 **5/5**、三语 **1116** 消息校验、build 与 Sites **4/4**。初始 JS **1,190,348 B**、manifest-linked assets **1,407,479 B / gzip 383,058 B**，13 个 deferred entries；>500KB 主 chunk 和生产包仍静态包含 Mock handlers，F6.8 仍未完成。改动后的账号页在 Codex 内置浏览器已实际显示两条 mock 账号记录并打开创建 Dialog；无写入提交、console error 为 0。完整 Edge/CDP E2E 与像素基线比较仍未运行。
- 本节之前记录的 typecheck/format/lint、Hooks **6/6**、架构 **8/8**、逻辑 **224/224**、视觉工具 **7/7**、i18n 工具 **9/9**、verification 工具 **5/5**、HTTP **70/70**、OpenAPI **42 paths / draft-partial**、三语 **1116** 消息校验及 Sites **4/4**均属于当时源码状态。以上两处修复后的 `npm run typecheck` 已通过；本轮 `npm run test:http` 在受限沙箱内为 **70/71**，唯一失败是本机 loopback listener `listen EPERM`，需授权环境重跑，不能沿用旧 70/70 结论覆盖新代码。
- 本轮生产 build 成功，但初始 JS **1,190,350 B**，仍有 >500 KB chunk warning；产物仍包含 mock handlers，故 F6.8 继续未完成。`npm run check` 全量命令本轮没有通过（`format:check` 曾发现三个新文件格式问题，按 Prettier 修复；后续分项格式检查通过；浏览器工具组未运行）。
- **未完成/未证明**：当前代码的完整自动化浏览器套件、正式截图/像素回归、React App→Python Console→隔离数据库/配置源路径均未验证。Edge 崩溃原因仍未知，Codex 内置浏览器的局部渲染检查不能替代完整测试矩阵。F5.4/F5.5、F6、F7、B0 不因此勾选，旧的 199/199 与 5/5 浏览器记录只代表各自历史源码状态。

### 15.10 生产与演示构建隔离（2026-10-07，F6.8 部分交付）

- 普通 `npm run build` 明确采用 `live-only` profile：构建期裁掉浏览器 MSW 启动器、应用 mock handler registry、旧 `FixtureGateway` provider 与 mock account identity；关闭 `publicDir`，不复制 `mockServiceWorker.js`。构建期 profile 同时传入 runtime resolver，生产包默认 live + 同源 API；可用 `VITE_CONSOLE_API_BASE_URL` 显式覆盖为安全 HTTP(S) origin，生产包拒绝 `VITE_CONSOLE_MODE=mock`，没有 fixture 回退路径。生产壳不显示 demo 状态条。
- 本地 `npm run dev` 保留显式 demo profile；`npm run build:demo` 产物固定在 `dist/demo/client`，保留 MSW 与 HTTP mock handlers，但不装配废弃的旧同步 `FixtureGateway`，不覆盖 `dist/client` 或 Sites 制品。`.env.example` / README 已说明两个 profile 和 API origin 使用方式。
- 新增产物门禁 `tests/build-profile.test.mjs`，只读取实际生成产物：要求 production 的文件名与 HTML/JS/CSS/manifest 不含 `mockServiceWorker.js`、mock registry、旧 gateway 和 mock identity 标记；同时要求 demo build 实际包含 worker、handler 与 mock role。生产+demo profile **2/2 passed**，Sites 静态产物/路由 **4/4 passed**。本轮授权 loopback `npm run check` **完整通过**：typecheck、format、lint、Hooks **6/6**、架构 **8/8**、逻辑 **224/224**、HTTP **71/71**、OpenAPI **42 paths / draft-partial**、browser tools **5/5**、visual tools **7/7**、i18n tools **9/9**、verification tools **5/5**、三语 **1116** 键、两种构建 profile 与 Sites。
- 构建记录：production initial JS **1,172,049 B**，manifest 首屏 **1,389,180 B / gzip 376,487 B**，10 deferred entries；去掉旧 provider 后 demo initial JS **1,175,718 B**，manifest 首屏 **1,392,849 B / gzip 377,551 B**，13 deferred entries。单 chunk 500KB warning 仍在，未通过人为调阈值处理。
- **F6.8 仍不勾选**：尚未完成切换/缓存/重新部署后的运行时浏览器 E2E；完整页面 mock/live 请求路径、Python Console 与真实后端仍待后续任务。此轮没有启动 Edge，也没有运行完整 CDP E2E/像素对比；本机构建产物检查与 live HTTP transport 测试不等于 App → Python Console E2E。`FixtureGateway` 源码及旧消费模块仍待页面迁移后由 F6.12 清理，单靠生产 tree-shaking 不会替代删除任务。

### 15.11 CDP 测试宿主拒绝 Edge（2026-10-07）

- `tests/e2e/cdp.mjs` 在创建临时 profile 和启动子进程之前检查 `CHROME_BIN`；Microsoft Edge.app、msedge 与 microsoft-edge 可执行文件路径会被明确拒绝，报错指导改用 Google Chrome/Chromium。该保护避免测试命令再次误启动已知会崩溃的 Edge；它不修复 Edge/macOS 的崩溃根因，也不将 Edge 纳入支持矩阵。
- 回归证据：`npm run test:browser-tools` **7/7 passed**（其中 `tests/e2e/cdp.test.mjs` **6/6**），包含独立 Node 子进程传入 Edge 路径并断言在 spawn 前失败；该检查没有启动浏览器。`npm run test:architecture` **8/8 passed**；`git diff --check` 对两个 CDP 文件通过。
- 本轮没有启动 Edge、Chrome 或 Chromium，也没有运行浏览器 E2E / 像素回归。浏览器完整验收仍未证明；目前本机没有已确认可用且获准启动的 Chrome/Chromium 宿主，不能用 Codex IAB 局部页面观察代替完整 CDP 矩阵。

### 15.12 F2.1 feature 查询生命周期收口（2026-10-07）

- 统一合同位于 `dashboard-prototype/src/shared/state/queryResource.ts`：`QuerySnapshot` 以 discriminated union 表达 idle/loading/refreshing、ready/empty/filtered-empty/partial、denied/error/stale；仅 refreshing/stale 等同 key 状态持有已信任数据，denied/error 不带旧数据。`createQueryResource` 统一超时、AbortSignal、请求 generation、owner reset/dispose、同 key stale 保留、权限撤销和权威 404/410 失效；空/筛选空/partial 语义由各 feature classifier 负责，避免从 wire DTO 任意猜测。
- `shared/ui/QueryView.tsx` 与 feature-owned query wrappers 穷尽呈现状态；发布/初始化/登录等写工作流使用独立 `CommandSnapshot` / 工作流状态，不和读取状态混用。查询 key、状态迁移与命令 unknown/conflict 边界由 `tests/logic/f2.test.mjs` 及同组 feature 契约测试覆盖。
- 本轮复验：`npm run test:logic` **224/224 passed**、`npm run typecheck` 通过；前述 `npm run test:architecture` **8/8 passed**。这证明模型/工作流门禁，不证明浏览器视觉矩阵或 Python/live 服务，因此 F5.4/F5.5/F6/F7/B0 不因此完成。

### 15.13 当前工作区全量静态门禁与浏览器宿主复核（2026-10-07）

- 在当前未提交工作区重新运行 `npm run check`，通过：typecheck、format、lint、Hooks **6/6**、架构 **8/8**、逻辑 **224/224**、HTTP **71/71**、Console OpenAPI **42 paths / draft-partial / pending=[]**、浏览器工具 **7/7**、视觉工具 **7/7**、i18n 工具 **9/9**、verification 工具 **5/5**、三语 **1116 messages/locale**、production/demo build profiles **2/2**、Sites **4/4**。HTTP live-controlled 用例绑定本机隔离 `127.0.0.1` 临时端口；第一次受限执行报 `listen EPERM`，获得该本机测试所需权限后重跑通过。没有连接外部服务。
- 当前 production build 初始 JS **1,172,049 B**、manifest 首屏资产 **1,389,180 B / gzip 376,487 B**；仍有单 chunk 超过 500 KB 的告警。构建门禁没有调大阈值。OpenAPI 仍是 `draft-partial`，门禁全绿不代表 Python API 已实现或协议已签字冻结。
- 为核对用户报告的 Edge 崩溃，检查确认当前 `CHROME_BIN` 未设置，默认路径是 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`；该文件不存在。机器应用目录当前发现 Edge 与 Safari，但没有 Google Chrome/Chromium。Edge 路径已由 CDP 启动器在任何临时 profile/spawn 前拒绝；`node --test tests/e2e/fleet-http.e2e.test.mjs` 在默认 Chrome `spawn ... ENOENT` 处失败，**未启动浏览器**。因此当前源码状态没有新增 CDP 页面验收/像素证据；不得复用之前以 Edge 跑出的历史结果为当前完成证明。
- 本次没有勾选 F4 页面任务或 F5.4/F5.5：静态、feature HTTP/MSW 与本机 loopback 证据不能替代 React 页面浏览器路径。继续推进业务逻辑/协议工作；完整 CDP 与视觉矩阵需在存在可用 Chrome/Chromium 执行宿主后运行。没有安装浏览器，也没有启动 Edge/Safari。

### 15.14 Codex 内置浏览器的总览路由观察（2026-10-07）

- 只读确认既有 `127.0.0.1:5173` 监听来自当前 `dashboard-prototype` 的 Vite；未停止或覆盖用户进程。通过 Codex 内置浏览器打开 `/#overview`，实际页面完成异步加载并呈现环境/应用/时间范围筛选、汇总指标、连接探测、趋势和应用目录。
- 当前 demo HTTP 视图显示应用总数 **3**、需关注 **1**、目录全范围 **3**，实际行是 `app-one/app-two/app-three`；TPS 明确为“尚未接入 / —”，不是伪造零；连接探测显示 Nacos unavailable。AX 快照中标题与交互均已呈现，路由未退回旧同步页面。
- 这是一次实际页面可访问性树/内容快照，不是像素截图或完整交互 E2E；没有在该页执行筛选、分页、下钻、刷新与失败恢复动作。因此不据此勾选 F4.01–F4.03 或 F5.4/F5.5，也不替代真实 Python Console。内置浏览器路径未启动 Microsoft Edge；CDP 自动化仍被本机缺少 Google Chrome/Chromium 阻塞。

### 15.15 F6.12 旧同步网关及其正式消费者退役（2026-10-07，部分验收）

- 正式应用路由此前已装配 feature HTTP containers；本轮删除仍被旧同步网关耦合的旧页面与公共出口，以及 `GatewayProvider.tsx`、`fixtureGateway.ts`、未挂载的 `httpGateway.ts`、旧 `contracts.ts`、临时 `bootstrap.ts` / `useDemoAccountBootstrap` 和仅服务于旧 provider 错误类型的反向 feature import。Nacos/Consul adapter 的错误类型收敛到 provider-owned `ProviderError`，不保留网关兼容 shim。现有 `AccountStore` 纯状态行为和其逻辑测试不因本次网关退役一并删除。
- 原 E2E `EmptyApplicationsProbe` 是通过 `FixtureGateway` 注入旧 `ApplicationsPage` 的测试路径，并非正式路由。已移除该探针/陈旧浏览器断言，新增 `APPLICATION-CATALOG-EMPTY` HTTP/MSW 测试：严格空 catalog 经 Console transport、feature HTTP mapper 和 query resource 后分类为 `empty`。这是网络/feature 数据层证据，不是已渲染 UI 的浏览器空态证据。
- 当前验证：typecheck 通过；逻辑 **224/224**、架构 **9/9**、HTTP **72/72**（含隔离 loopback live transport，授权后运行）、Edge 启动保护/浏览器工具 **7/7**。源码架构门禁现在要求旧 Gateway 文件不存在，并扫描禁止同步 Gateway API 回流。
- **F6.12 不勾选**：静态源码、mock HTTP 和受控 live transport 通过，但本轮没有运行改动后的正式页面浏览器交互/视觉回归（Edge 已禁止、Chrome/Chromium 缺失）；此外全工程 mock/live 请求目标和 Python Console 后端验收仍未闭环。不能把 HTTP/MSW、旧页面删除或静态构建单独称为 E2E 完成。

### 15.16 F6.11 前端配置中心适配草稿退役（2026-10-07，前端边界完成）

- 追踪 `src/core/api/providers` 全部使用者后确认：正式 React 路由、Console HTTP、MSW 与任何生产页面均不消费 Nacos/Consul RuleProviderAdapter；仅 `tests/api/providers.test.mjs` 和 F1 一个误把 Consul adapter 当通用规则类型校验器的测试引用它。Nacos/Consul 直连、厂商地址/错误猜测和 Sentinel wire 适配属于 Python Console provider 层，不属于浏览器。
- 删除未装配的 `core/api/providers` Nacos/Consul 适配器、注册表与伪厂商错误映射；删除相应两条矛盾/过时测试和仅为它们打包的 `tests/api/run.mjs`。保留实际 rules 边界：F1 非法 URL 类型检查现在直接调用 `features/rules/model/ruleKinds.ts` 的 `resolveRuleKindFilter`，不再绕道厂商代码。未为了旧断言覆盖 `grade: 2`，也未臆断 Nacos 404 的冲突语义。
- 这收敛了 F6.11 的**前端**要求：React 页面只请求统一 Console API；配置源凭证、Nacos/Consul 寻址、完整数组兼容与错误语义留给 Python Console。保留 Python 端 provider profile/wire 兼容、真实 Nacos/Consul 联调与审计为后续后端任务，不把删除前端草稿误报成服务端支持。
- 全量 `npm run check` 在完成上述迁移后 **通过**：typecheck、Prettier、lint、Hooks **6/6**、架构 **9/9**、逻辑 **224/224**、HTTP **72/72**、OpenAPI **42 paths / draft-partial / pending=[]**、CDP/浏览器工具 **7/7**、视觉工具 **7/7**、i18n 工具 **9/9**、verification **5/5**、三语 **1116 keys/locale**、production/demo build profiles **2/2**、Sites **4/4**。其中 HTTP 用例使用 MSW 或隔离的 `127.0.0.1` controlled endpoint；browser tools 只验证 Edge 被 spawn 前拒绝，**没有运行真实浏览器页面**。
- 当前 production 初始 JS **1,172,027 B**，manifest 首屏资产 **1,389,158 B / gzip 376,472 B**；demo 初始 JS **1,175,696 B**，资产 **1,392,827 B / gzip 377,546 B**。旧页面早已被 Vite tree-shake，因此源代码退役并未实质降低当前 bundle；>500KB 主 chunk 告警继续保留，不调阈值掩盖。
- 先前 `node --test tests/api/run.mjs` 的 **18/20** 是现已退役的无消费者 provider 草稿测试，不再属于正式 test command；其规则 kind 用例已由 rules 自己的纯模型路径覆盖。没有为旧测试修改产品语义。
- OpenAPI 仍为 `draft-partial`，Python Console、数据库、Nacos/Consul 持久配置读写和重启恢复未运行。此处“F6.11 不勾”是 2026-10-07 当时状态；当前前端边界复核与测试证据见 §15.163，F6.11 仅以前端范围完成。F6.12、F7/B0 与总体验收仍开放，不能从前端适配器退役推断跨边界完成。

#### 15.17 旧网关退役后的正式路由局部渲染观察（2026-10-07）

- 在 `FixtureGateway` 与旧同步页面退役、当前 `npm run check` 通过后的源码状态，通过 Codex 内置浏览器打开现有 Vite `/#/overview`。页面经正式 React 路由和新 HTTP feature container 加载，AX 内容显示 demo catalog 的 3 个应用、QPS/RT/拦截/资源指标，以及 Nacos unavailable 状态；TPS 显示“尚未接入”，没有伪造为 0。未启动 Edge，也未提交任何写命令。
- 这是当前修改后的一次真实渲染/可访问性树观察，仅覆盖总览路由首屏；没有截图像素比较、筛选/分页/下钻交互，也没有认证、Python 服务、数据库或真实配置中心参与。它补充局部页面证据，但不替代浏览器自动化矩阵或最终跨层 E2E，**F6.12/F7/B0 与总体验收仍不勾**。
- 本机通过 Spotlight 查询未发现 Google Chrome 应用 bundle；不再以 Microsoft Edge 作为 CDP 替代宿主。完整 CDP E2E 需要在存在可用 Google Chrome/Chromium 的执行环境中运行，期间 Edge 启动保护继续保留。

#### 15.18 React 职责地图纠正过期状态（2026-10-07，F7.5 部分交付）

- 重新对位 `main.tsx`、`AppProviders`、`routes.tsx`、Console runtime、11 个正式 route owner 与七个 feature 目录后，发现 `docs/REACT_REFACTOR_MAP.md` 仍描述正式页面使用 `FixtureGateway`、HTTP 雏形未挂载、初始化与账号页仍为 demo 页；这些描述已与当前源代码冲突。
- 重写职责地图为当前运行结构：挂载前解析 mock/live、MSW 边界、单一 Console transport、route owner 到 feature HTTP adapter、生产/演示构建隔离，并明确 OpenAPI `42 paths / draft-partial`、静态 `applicationScope.ts` 残留、旧内嵌 Dashboard 与独立 Console 的差异，以及未完成的 mock 状态、Python/live 和 CDP/像素证据。
- 本次只更新职责地图与本推进清单，没有改前端/后端代码；其文档结论按源代码和 §15.16 的实际门禁证据校验。F7.5 **不勾**：README、AGENTS、旧规划文件仍需逐项核对/标记历史，运行/调试说明与后端交接也未完成。全局 E2E 仍未通过。

#### 15.19 README/AGENTS/Console 合同状态同步（2026-10-07，F7.5 部分交付）

- 对照当前 `main.tsx`、Console runtime、MSW 启动、AppProviders、route owners 与 OpenAPI 生成物，修正了 dashboard README 中“部分页面仍走旧同步 Gateway”“旧网关尚待 F6.12 删除”“查询/命令组合器仍待全部页面迁移”等过期描述；改为准确记录正式路由 HTTP adapters、demo HTTP Mock、production live-only profile，以及仍未完成的 Python/live/E2E 边界。
- 更新 `AGENTS.md` 的网关状态与工作顺序，避免后续代理误把已删除 FixtureGateway 当迁移目标或复建兼容层。更新 `CONSOLE_API_CONTRACT.md §9.6` 的机器合同现状：42 paths、`draft-partial`、`pending=[]` 和 12 个 capability family；明确 pending 为空不等于逐页冻结、Python 实现或 E2E。
- `REACT_REFACTOR_MAP.md`、README 与本清单的 Markdown diff 检查通过；机器事实直接核对 `docs/protocol/console-api.openapi.json`。F7.5 **仍不勾**：`REWRITE_PLAN.md` 历史文档和页面能力文档的实现现状仍需逐页对位，运行/调试说明、Python 交接材料与全局验收仍未收口。

#### 15.20 页面章节与 Console machine operations 对位（2026-10-07，F6.1/F7.4 部分交付）

- 将 `Dashboard页面能力与接口设计.md §13` 更新为 11 个页面章节 → 当前 42 个 OpenAPI operationId/feature-owned API 入口映射；明确 catalog 等共享 operation 只有一个所有者，账户和角色变化共享 account command 合同，并分别标记 mock 或 Python capability 缺口。
- 对照当前 OpenAPI 的 `x-covered-capabilities`/`x-pending-capabilities` 元数据以及 `src/features/*/api` 实际源文件核对名称；`npm run contract:check` 通过，仍为 **42 paths / draft-partial / pending=[]**。`CONSOLE_API_CONTRACT.md` 与职责地图中机器入口状态已同步；既有 per-process Starlette/Jinja `sentinel-dashboard` 明确不是该 Console 服务实现。
- F6.1/F7.4 **不勾**：这只是把现有 machine operation 对位到页面章节，不是全页面操作审查/签字；诸如 runtime rule codec profile、真实指标事件能力、初始化威胁模型、异步命令、关系库事务和 wire 负例还需逐项冻结并由 Python 契约测试实现。Python Console 本身仍不存在。

#### 15.21 配置源注册 Mock 纵向切片测试矩阵（F4.16/F6.6，实施前冻结）

配置源管理复用现有 `SourceRegistrationPort → ConsoleTransport → MSW → SourceRegistrationWorkflow → SourceRegistryPanel` 边界；该切片不新增后端实现，也不将 Mock check 描述为真实 Nacos/Consul 探测。

| 场景                  | 预期证据                                                                                                                               |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| 管理员初始读取        | 连接页显示安全的 Nacos 示例注册；只含 endpoint/location/authenticationMode/credentialConfigured/revision，不返回 secret 或凭证引用标识 |
| Consul 注册/更新      | 真实 HTTP adapter 经注册 MSW handler 完成写入；密码/ACL token/凭证引用只存在于瞬时请求体，操作记录只保存 keyed digest 与脱敏 receipt   |
| 条件版本更新          | 匹配 expectedRevision 才更新并递增 revision；陈旧 revision 返回稳定 conflict receipt，目录状态不被覆盖                                 |
| 幂等键                | 同 requestKey + 同 payload 返回原结果；同 key + 不同 payload 返回 idempotency_conflict；operation lookup 只返回原脱敏结果              |
| 检查连接              | 必须带 CSRF、不要求 idempotency；只产生明确标记的合成结果，不变更 source registry、不宣称真实 provider health                          |
| 权限与协议负例        | 非管理员无法读取/检查/修改；缺 CSRF、缺/不匹配 idempotency-key、非法 body 均拒绝且不改变状态                                           |
| UI 组合与访问生命周期 | System / Connections tab 实际组合观测连接面板与注册表；source workflow 的授权绑定真实认证 session owner，卸载/owner 更换后释放         |

实施顺序记录：已先通过 MSW + ConsoleTransport + feature adapter + workflow 组合测试锁定上述安全行为，再增加 mock handler，并将现有 UI/Workflow 接入 Connections 路由。F4.16 只有在内置浏览器完成真实页面交互验证后才可勾选；该要求已在 §15.50 达成。F6.6 仍待 Python Console、关系库持久化与真实 provider 验收。页面 check 必须清楚标示为演示模拟。

本次实现记录：配置源注册 handlers 已并入显式 demo handler registry；连接 tab 现在组合连接状态和已登记配置源面板。mock 状态仅保存脱敏来源事实、HMAC keyed digest 与脱敏操作 receipt；直连密码、Consul ACL token、凭证引用均不进入 state/operation receipt。授权从 app 路由组合根传入的已确认 principal 投影取 `sessionEpoch`/`roleId`，不是 feature 间反向依赖或 URL/localStorage 权限。Source HTTP/Workflow 安全矩阵 **6/6 passed**；曾完成的完整 `npm run check` 通过（当时 HTTP **78/78**、逻辑/架构/lint/i18n/构建/构建隔离/Sites 均通过），OpenAPI 为 **42 paths / draft-partial**。本次 IAB 仅显示合成连接状态，不代表真实后端 E2E。生产构建仍报告 >500KB 主 chunk。F4.16 UI 现已勾选；F6.6 继续等待 Python Console、关系库持久化和真实 provider 验收。

### 15.22 当前前端 HTTP Mock 路径的完整浏览器 E2E 复验（2026-10-07）

- 已移除环境变量中的 `CHROME_BIN` 后运行完整 `npm run test:e2e`，CDP 启动器使用默认 Google Chrome，不再调用 Microsoft Edge。测试连接本机隔离 Vite mock 服务 `127.0.0.1:5175`；完整结果 **116/116 passed、0 fail/cancel/skip，385.81s**。覆盖身份/账号/角色、登录/setup/改密、fleet/实例/监控/故障/系统/规则、导航守卫与 11 个路由在窄屏、200% 等效 viewport 和桌面尺寸的真实渲染交互。截图写入测试 artifact 目录；响应式运行实际断言无横向溢出、导航可达、表格键盘滚动和 sticky header 焦点位置。
- 这轮先暴露 setup 页面在 StrictMode replay 后停留于“检查初始化授权”。实际页面确认 bootstrap HTTP 返回 `200 {initialized:false, setupAvailable:true, operatorAuthorized:true}`，而页面仍不前进；根因是 `SetupRouteOwner` 在普通 effect cleanup 中立即永久 `dispose()`，与 React StrictMode 的 cleanup/setup replay 冲突。现改用项目既有 `useOwnedDisposal` 延迟 owner 释放，setup 三条 E2E 通过。其他失败来自 `clickByText` 可选中隐藏 option、导航 probe 和正式 App 同时拥有浏览器 history、以及响应式用例在页面还处于认证/loading 时过早读 DOM；选择器现只选择可见节点，导航使用隔离测试 host，响应式用例等待真实页面状态。聚焦重跑导航/响应式 **14/14 passed**，完整套件 **116/116 passed**。
- `npm run check` 完整通过。首次受限执行唯一失败为 HTTP controlled-test 在本机 `127.0.0.1` 绑定 `EPERM`；未跳过该测试，获本机 loopback 权限重跑完整命令后 HTTP **78/78 passed**，`contract:check` 验证 **42 paths / draft-partial / pending=[]**，typecheck、format、lint、Hooks、架构、逻辑、HTTP、浏览器/视觉/i18n/verification 工具、production/demo builds、构建隔离和 Sites 均通过。构建仍报告主 JS chunk 大于 500 KB；没有通过调阈值隐藏。`i18n:check` 报告三语各 1117 条消息、704 静态可校验键，并如实提示 112 个动态 `t()` 调用未静态解析，不声称全量静态解析。
- **证据边界：**以上是 Google Chrome 中的 React 页面 + Console transport + 浏览器 MSW mock E2E，并非 Python Console、真实 MySQL/Nacos/Consul、重启持久化、真实身份 Cookie/CSRF 部署或多实例验收。OpenAPI 仍为 draft-partial，真实后端和发布/配置源持久化均未执行；因此不据此勾选 F4/F6/F7/B0 整项，也不宣称总目标完成。用户报告的 Edge 崩溃仍属既有 Edge 宿主问题；本次完整 E2E 没有启动 Edge。

### 15.23 Python Console 独立服务与 Bootstrap 查询首切片（2026-10-07，B0.1 部分交付；首版记录）

首版的聚合 bootstrap-state Port 已在 §15.24 拆分为数据库 initialization、deployment setup-window 和 request operator-session 三个独立 authority；本节的 7/7 是拆分前历史基线。

- 新增独立包 `components/sentinel/sentinel-console`，发行名为 `atlas-richie-sentinel-console`，Python >=3.12，使用 Starlette/ASGI。它与已有 `atlas-richie-sentinel-dashboard` per-process 内嵌诊断服务保持不同装配边界；没有将旧 Dashboard 路由裁剪/改名为 Console，也没有默认 admin 或默认内存生产 provider。
- 新增 `GET /api/v1/system/bootstrap` vertical slice：消费者拥有的状态读取与 bootstrap operator 会话验证 Ports、`ReadBootstrap` 用例、严格的有限 HTTP DTO/error mapping。初始化已完成仅投影 `{"initialized": true}`；仅在 setup window open 且本请求 opaque cookie 经 authority 验证时报告 operator grant；状态/会话 authority 不可用或返回非法类型均 fail closed 为有限 503，绝不伪装成首次初始化或未授权。invalid `x-request-id` 被拒绝且不回显输入。
- Python 3.12.14 + Starlette 0.52.1 + HTTPX 0.28.1 下，新 Console ASGI 合同测试 **7/7 passed**，新增源码 compileall 通过；既有 per-process `sentinel-dashboard` 原回归套件独立复跑 **22/22 passed**。离线构建新 Console sdist+wheel、检查 wheel 模块布局，并将 wheel 离线安装至临时 target 后成功从已安装 wheel import `build_app`。完整测试矩阵及范围限制记录在 [R-SENTINEL-CONSOLE-B0.1-bootstrap-read.md](../acceptance/R-SENTINEL-CONSOLE-B0.1-bootstrap-read.md)。
- **B0.1 仍不勾**：尚无生产 durable state/session provider、operator code exchange、CSRF/Origin、真实权限数据库、其余 Console operations、live socket/deployment 或浏览器到 Python 的端到端验证；B0.2–B0.6 均未完成。ASGI test doubles 和 wheel build 都不是数据库/真实后端验收。

### 15.24 Python Console B0.2 持久化基础首批实现与本地验收（2026-10-07，B0.2 未完成）

- 新增 SQLAlchemy async ORM 映射与 Alembic `0001_identity_control` migration，覆盖 singleton bootstrap guard、account、server session、initialization operation 与 bounded audit facts；迁移为 `username_key` 建立唯一约束、`admin/view` 角色、账号状态、修订和审计 outcome 约束，并初始化唯一 `initialized=false` guard row。账号名身份规则现由 `AccountUsername` 统一拥有：200 UTF-16 code units 上限、浏览器一致首尾空白裁剪、NFKC + locale-neutral lowercase、展示值保留原拼写、只持久化 64 位 SHA-256 查找键；数据库唯一约束拒绝大小写/兼容字符变体。该算法进入 create/login/bootstrap 契约，live Console 用例尚未接线。
- 新增 Argon2id `PasswordHashService`（显式有界参数）与版本化 AES-256-GCM `AesGcmSecretCipher`；加密信封绑定 owner/field AAD，支持活动 key id 轮换，拒绝篡改/错误上下文。新增测试覆盖密码单向验证、AES 往返/轮换/错误 key、上下文错配及密文篡改；数据库测试覆盖 schema、head 重复升级、唯一登录键、非法 role 和敏感字段不落表。
- 新增 `SqlAlchemyBootstrapInitializationReader`，只映射数据库 `initialized` 事实；setup-window 与 operator session 留在各自应用 Port。`GET /system/bootstrap` 现可在 ASGI 集成测试中读取迁移后的 SQLite guard；初始化完成时不再查询 setup-window/operator，guard 缺失或 SQLite 连接失败均 fail closed 为脱敏 503。
- 最终源码树测试 **22/22 passed**；从最新源码构建 sdist + wheel，检查确认 bootstrap adapter、migration runner、Alembic env 与 revision 进入 wheel；wheel 安装到独立临时 target 后，Console 测试也 **22/22 passed**。`compileall` 与 `git diff --check` 通过。测试依赖仅安装在 `/private/tmp`，未改项目 `.venv`。
- Postgres/MySQL 生产方言、真实 migration 与并发行为未验收：本机 Docker CLI 的 daemon socket 返回 permission denied；未连接或修改真实数据库。证据和风险矩阵见 `docs/process/acceptance/R-SENTINEL-CONSOLE-B0.2-persistence-foundation.md`。
- **B0.1/B0.2 继续不勾**：setup-window 的部署持久化实现、operator code exchange、CSRF/Origin、正式启动装配；setup 凭证持久化、真正首次 admin 初始化、账号/会话/角色/本人改密/审计用例、外置 bootstrap marker、多 worker 和最后 admin 并发保护，以及 PostgreSQL/MySQL 独立实例验收仍未实现。SQLite 集成和 wheel 测试不是生产数据库或浏览器 E2E。

#### 15.24.1 Account username identity 补充（2026-10-07）

- Python domain `AccountUsername`、64 字符 SHA-256 `username_key` ORM/初始 migration、React mock canonicalization 与 API semantic rules 已同步；数据库不保存规范化后的明文别名。
- 证据：Python 3.12.14 unittest vectors **4/4**，SQLite migration/persistence **5/5**（全角重复账号唯一冲突）；React logic **225/225**、聚焦 MSW mock duplicate **1/1**；最新 `npm run check` 完整通过，包含 typecheck/lint/format、架构/逻辑/HTTP/协议/i18n/构建/Sites 门禁，HTTP **79/79**。
- 最新 `env -u CHROME_BIN npm run test:e2e` 使用隔离临时 profile 的 headless Google Chrome 完成 **116/116 passed，0 failed/skipped/cancelled，405.8s**；覆盖完整 React 用户路径和响应式/渲染行为，但前端仍走 MSW/mock，不能视为 Python Console/数据库/provider 的真实 E2E。测试 launcher 明确拒绝 Microsoft Edge executable。
- `npm run test:http` 首次为 **77/78**（沙箱 `listen EPERM`）；经授权仅为本次测试开放隔离 loopback listener 后完整重跑通过。离线环境缺 pytest/Starlette，完整 pytest 套件未能启动；被选中的 Python `unittest` 模块运行通过。
- PostgreSQL/MySQL 执行、Unicode 运行时版本差异、实际 create/login/bootstrap 操作用例、服务重启/多 worker 与浏览器到 Python E2E仍未验收；B0.1/B0.2 保持未勾。

### 15.25 Python Console 当前会话读取切片（2026-10-07，B0.2 部分实现）

- 新增 `GET /api/v1/auth/me`：HTTP 适配器校验 request-id、只读取 `sentinel_session` HttpOnly cookie，并仅返回有限 Session DTO 或 JSON `null`。`ReadSession` 对缺失/畸形 token 映射匿名，合法 token 在越过 application Port 前以 SHA-256 派生查找摘要；原 cookie 不进入数据库接口或响应。
- 新增 `CurrentSessionReader` 最小读取 Port 与 `SqlAlchemyCurrentSessionReader`。每次查询同时校验会话未过期/未撤销、账号仍 active；只投影 account id、用户名、当前角色与 session epoch。domain 用 `AccountRole` / `SessionCapability` 将 admin/view 映射为有限能力；未知持久角色和持久化不可用 fail closed，不回退为匿名/管理员。
- 新增用例、领域、SQLite adapter 与 ASGI endpoint 测试；Python 3.12.14 本地全量 Console `unittest discover -s tests -v` **37/37 passed**，其中 11 项覆盖当前会话切片（domain/use-case、HTTP success/匿名/非法输入/异常、SQLite 有效/过期/撤销/停用/故障）；compileall、`git diff --check` 与本次源码 88 列检查通过。Starlette/HTTPX 取自已有独立 Sentinel venv，其他依赖来自 `/private/tmp`，未安装包/联网。该 ASGI + SQLite 证据不等于 PostgreSQL/MySQL 或真实浏览器登录验收。详见 [B0.2 验收记录](../acceptance/R-SENTINEL-CONSOLE-B0.2-persistence-foundation.md)。
- `build_app` 现在显式要求注入 `CurrentSessionReader`，无默认的匿名/demo provider；生产 startup 尚未提供真实 authority composition。此片不实现登录、注销、session 创建、CSRF nonce 轮换，也未连接 PostgreSQL/MySQL；SQLite 结果不替代生产数据库验收。
- **不勾 B0.2/B0.5**：会话读取切片不等于账号初始化、真实登录、账户 CRUD、CSRF/Origin、防重放、生产装配或浏览器到 Python 的身份 E2E。

### 15.26 F1.4/F6.3/F6.12 feature Port 注入及全量前端回归（2026-10-07）

- 将 Fleet、Applications/Instances、Rules、Realtime、Incidents、System 六个正式页面容器改为仅消费各自 feature-owned 异步 Port。HTTP adapter 在 `app/router/routes.tsx` 或 `ConsoleSystemRoute` 创建并注入；feature UI 不再导入 `ConsoleTransport`，也不再在 UI container 中自行构造 `create*Http`。Observation Catalog Port 仍由 Applications feature 持有，并由 app 对各消费者显式注入。
- feature public entries 补出路由装配需要的 Port 类型与 HTTP adapter factory；Core transport 仍是应用级横切能力，不含业务 endpoint/schema/fixture。`core/api` 依赖图无业务反向边，正式 feature UI 与 transport 隔离；原 `FixtureGateway`、旧同步出口和未挂载 HTTP 草稿仍由 F6.12 架构回归确认不存在，未引入兼容 shim。
- 新增架构测试锁定 app→adapter→feature Port 装配：禁止 feature UI container 直接依赖 Console transport 或构造 HTTP adapter，并检查应用路由实际注入 Port。`npm run test:architecture` **10/10 passed**；`npm run typecheck` 通过；完整 `npm run check` 通过，包含 format/lint/Hooks、逻辑、HTTP **79/79**、OpenAPI **42 paths / draft-partial / pending=[]**、browser/visual/i18n/verification 工具、production/demo builds、构建隔离、Sites **4/4**。构建保留 >500KB chunk 警告，未调阈值遮掩。
- `env -u CHROME_BIN npm run test:e2e` 使用默认 Google Chrome 完成全量正式页面交互回归：**116/116 passed，0 fail/skip/cancel，400.66s**。涵盖身份/账号/角色、初始化/登录/改密、页面 HTTP Mock、实例/监控/故障/规则/系统、权限撤销、请求失败/未知结果、Dialog 键盘焦点和窄屏/桌面尺寸。CDP 启动器对 Edge 路径在 spawn 前拒绝；本轮没有启动 Edge。`test:http` 中 `HTTP-LIVE-CONTROLLED` 通过隔离 `127.0.0.1` HTTP endpoint 验证共享 Console transport；首次沙箱内 loopback 返回 EPERM，随后仅在本地受控测试命令获得 loopback 执行权限后重跑，79/79 全过。
- **边界仍保持开放**：以上完成的是前端工程结构、浏览器 HTTP Mock 与受控 loopback transport 验收，不是 React → Python Console → PostgreSQL/MySQL → Nacos/Consul 的真实部署链路。F6.1/F6.2/F6.4–F6.11、F7 其余项目与 B0 未完成；OpenAPI 仍为 draft-partial；真实数据库迁移/重启恢复、生产 Cookie/CSRF/Origin、多 worker 和真实配置中心均未验证。该项不授权也未操作真实数据库或配置中心。

### 15.27 F1.6 规则编辑层与展示投影隔离（2026-10-07）

- 规则草稿、校验策略、领域值物化、Workbench entry 与单条/整组编辑状态机从 `features/rules/model/` 移入 `features/rules/editor/`。领域 `ruleValue.ts` 保留纯数值事实并新增 `validRuleValue`，HTTP adapter 与版本/部署校验均直接验证领域事实，不再伪造 form draft 再物化来校验 wire 输入。API wire DTO 仍只存在 `features/rules/api/`；表单临时字符串和 `formKey` 不会进入领域值或 wire contract。
- Applications 旧实例矩阵模型删除 `statusLabel/stateLabel` 展示字符串，由 presentation 根据观测指标和健康事实返回 i18n key，三语各增加正式翻译；实时图表系列色类型从 `shared/ui/charts` 提升到 `shared/types/charts`，presentation 的指标元数据不再依赖 UI 组件实现。
- AST 依赖门禁新增 model→editor/forms、API→editor/forms 与 presentation→shared chart UI token 负例；逻辑测试覆盖所有 rule fixtures 的领域值校验以及非法非有限/非数值事实。`npm run typecheck` 通过，`npm run test:architecture` **11/11 passed**，`npm run test:logic` **226/226 passed**。
- 此切片不改变规则编辑用户流程；五类草稿验证、参数例外稳定行和草稿/规则集测试均纳入同一逻辑回归。改动后完整 `npm run check` 通过（含 HTTP **79/79**、合同 **42 paths / draft-partial / pending=[]**、production/demo build、Sites 等门禁）。
- `env -u CHROME_BIN npm run test:e2e` 已尝试使用默认 Google Chrome，但 Chrome 在页面启动前以 `SIGABRT` 退出；受限环境下所有 E2E 因浏览器无法启动而失败，并无页面断言结果。随后仅申请本次隔离 Chrome 进程权限，自动审批服务因模型容量拒绝评审、命令没有执行。此次 E2E 因此**未验收**；没有调用 Edge，也没有访问真实 Console/provider/database。不得用 §15.26 的旧 E2E 结果替代本次改动后的页面回归。
- 后续截图显示的一次重试命令曾误把 `CHROME_BIN` 指向 Microsoft Edge，Edge 意外退出；该次没有页面断言结果。此为工具选择错误，已停止使用 Edge，不将其崩溃归因于产品页面；F1.6 的真实页面 E2E 仍未验收。

### 15.28 F1.7 feature 公共出口与 JSDoc 边界（2026-10-07）

- 应用层曾直接导入 identity 私有 UI、fixtures 和 system model。新增 `identity/login.ts`、`identity/mock.ts` 窄入口；初始化入口统一导出初始化页与授权 Gate；system 公共入口导出稳定 URL tab 标识。Setup/login/system 路由与 mock registry 已改用这些入口，应用源码不再深导入 feature 私有路径；显式 demo/mock handlers 仍只由 mock-mode registry 装配，不进入生产页面路径。
- `tests/architecture/dependencies.mjs` 新增 app→feature private-path 分类；正负例和真实源码图检查已锁定此边界，并保留 core→feature、shared→app、跨 feature 深路径和 feature model/API 反向依赖检查。`npm run test:architecture` **12/12 passed**。
- 新增/调整的稳定 setup、login、system 与 mock 入口 JSDoc 明确了 Port 输入、服务端确认/失败语义、secret 不进入 snapshot、以及 app owner 的 dispose/cancel 生命周期；删除 faults HTTP 迁移、setup legacy-demo 和 identity SCSS 迁移待办等已失真的注释。
- `npm run typecheck`、`npm run format:check` 通过。受控本机 loopback 权限下完整 `npm run check` 通过，覆盖 lint/Hooks、架构 **12/12**、逻辑、HTTP、OpenAPI、browser/visual/i18n/verification 工具、production/demo builds、build profile 与 Sites；生产构建仍保留 >500KB chunk 警告。沙箱内无授权的单独 `npm run test:http` 仍会因 `127.0.0.1 listen EPERM` 失败，因此该单项结果以完整检查中获准执行的通过结果为准。
- `env -u CHROME_BIN npm run test:e2e` 随后使用固定 Google Chrome 路径与每轮新建的 `sen-e2e-*` 临时 profile 完成全量浏览器回归：**116/116 passed，0 fail/skip/cancel，389.34s**。启动器在 spawn 前拒绝 Edge 路径；本次运行没有启动 Edge。Chrome 的本轮启动和全部 UI 断言均通过；Edge 崩溃来自此前误设置的 Edge override，不是产品页面失败。
- 本轮 E2E 只证明 dashboard-prototype 对 HTTP mock 的页面交互、权限、响应式与图表路径；仍未访问 Python Console、真实数据库或配置中心。前端→Python 的 live integration 与真实 provider/database 验收仍在后续 F6/B0。

### 15.29 F2.2 会话切换时的页面查询 owner 隔离（2026-10-07）

- 风险与归属：`AuthenticationWorkflow` 是应用级服务端会话事实所有者；路由页面及其 QueryResource 是页面级资源 owner。仅按 `currentRoute` 重置不够——同一路由从一个已认证 `sessionEpoch` 切换到另一个仍获授权的会话时，页面局部 state 与查询资源也必须失效。
- 实现决策：新增纯函数 `app/router/routeOwner.ts::routePageOwnerKey(route, sessionEpoch)`，按 `[route, server-confirmed sessionEpoch]` 构造页面 owner 身份。`App` 只从 `resolved/authenticated` access facts 读取 epoch，并把该 owner key 交给 `RouteBoundary`。owner 改变会卸载旧页面、触发既有 `useQueryResource` cleanup/cancel，再建立新页面资源；不增加第二份 session store、不把凭证放进 key，也不操作服务端身份。
- 验收矩阵：① 逻辑测试证明同路由同 epoch 稳定、epoch/route 变化必产生不同 owner；② Chrome E2E 经真实 `RouteBoundary` + `useQueryResource` + `QueryResource`，先加载旧会话值，再在同一路由改变 session epoch，断言新会话 pending 首帧不含旧值、旧信号被 abort、旧请求即使迟到也不能覆盖新值，最后新 owner 正常加载。
- 本次改动通过 `npm run typecheck`、`npm run format:check`、`npm run test:logic`（**227/227**）；全量 `npm run verify -- --browser-only` 通过，浏览器 E2E **117/117**、0 fail/skip/cancel。新增跨会话用例经真实 `RouteBoundary` / `QueryResource` 验证旧 owner 取消、迟到响应隔离与新 owner 正常加载；该轮像素比较为 not-requested，不作为视觉像素验收证据。
- 按用户最新要求停止使用 Chrome / Edge；随后启动仅监听 `127.0.0.1:49127` 的本地 Vite 服务，并通过 Codex 内置浏览器实际打开 Overview 与 `#realtime`：导航、筛选、HTTP mock 数据、指标覆盖状态及图表区域均可访问/渲染，未访问 Python Console、真实数据库或真实配置中心。F2.2 的页面查询 E2E 已完成；全套 dashboard 后端联调与剩余验收仍在后续任务范围内。

### 15.30 F2.3 写命令生命周期与页面消费验收（2026-10-07）

- `createCommandResource` 用封闭状态联合表达 idle/pending/success/error/conflict/result-unknown；请求发出前取消不产生未知写，发出后的取消/超时/断网/5xx 不伪装回滚、不重放；pending 和 unknown 阻止重复执行，Form state 不由底层资源复制/清空，dispose 使迟到结果失效。
- 账户、角色、本人改密、初始化、规则草稿/版本/发布与来源登记工作流将“读原操作结果”与“重发写命令”分开，并校验目标/requestKey/当前授权；确认冲突/失败保留可修正意图，未知回执不能靠 not-found 直接解锁。全量 E2E 中账户管理、角色、密码、初始化、规则工作区/发布计划及来源登记用例覆盖 pending 防双击、字段保留、unknown 不重放、原操作核查、权限撤销/迟到回执等行为。
- 本次已完成的逻辑门禁 **227/227**，全量浏览器 E2E **117/117，0 fail/skip/cancel**；该证据验证前端/HTTP mock 语义，不证明 Python 持久化幂等和 operation lookup，后者仍属于 B0/F6 联调。此后遵照用户要求仅使用 Codex 内置浏览器，不再启动 Chrome 或 Edge。

### 15.31 F2.4 会话默认值故障修正与剩余 bootstrap 所有权（2026-10-07）

- 发现 `core/api/mock/mockRole.ts::readMockPrincipal()` 在 `window` 缺失、localStorage 读取失败、键缺失或值非法时默认返回 `admin`；这会让显式 mock 模式把坏存储提升为管理权限。现改为只接受精确的 `admin` / `view`，其它情况统一匿名 `null`，删除无调用方且会把匿名转成 admin 的 `readMockRole()`。正式身份仍只能来自服务端 `/auth/me`；`AuthenticatedSessionBridge` 仅把该快照投影到旧能力显示 Context，不持有第二份认证事实。
- 新增 `mock-role.test.mjs` 覆盖无 `window`、缺值、非法值、匿名值、storage 异常、显式写入的内存态及两种有效角色；新增 HTTP mock 负例证明缺失/错误角色不能读取 admin 账号目录。测试夹具已改为显式设置 admin，不再借默认值授权。`npm run test:logic` **229/229**、获准本机回环后的 `npm run test:http` **80/80**、`npm run typecheck`、`npm run lint`、`npm run format:check` 均通过。
- Codex 内置浏览器实测：reload 后空身份落到 `/login`；使用仅限本地 mock 的合成账号完成登录，URL 转到 `/overview`，页面呈现全局运行概览和明确标注的示例观测数据。该浏览器环境没有可用的 `window.localStorage`，因此 mock 身份只在显式 mock 登录后保留于模块内存；缺值/损坏存储依旧匿名。未启动 Chrome/Edge；尚未重跑完整浏览器回归/截图基线，因此此交互烟测不等于完整 E2E，也不代表 Python/真实数据库验收。
- F2.4 的 bootstrap/session 状态归属已由 §15.32 收口；本节保留最初发现记录，不再表示现状。

### 15.32 F2.4 bootstrap/session 单一 owner 收口（2026-10-08）

- `AuthenticationWorkflow` 是 app-scoped bootstrap/session 唯一事实 owner；`SetupRouteOwner` 通过 `createSetupIdentityPorts` 将同一 owner 的 `restore()` 投影为 setup authorization 与 initialization 所需的窄 Port，setup 工作流不再直接创建 `/system/bootstrap` 读取器。初始化前的 `operatorAuthorized` 从 wire 到 `AccessFacts` 保留，已初始化与 setup unavailable 均 fail-closed；setup 完成后不可通过深链重新进入。
- HTTP authentication 刷新中的 bootstrap nonce preflight 只为 CSRF transport 获取新鲜 nonce；其 bootstrap body 不进入第二份 app/session state。`AuthenticatedSessionBridge` 仍只是 capability-visibility projection，不拥有身份事实。浏览器 mock role 缺失/损坏只产生匿名态，不产生 admin。
- `npm run typecheck`、`npm run lint`、`npm run format:check`、`npm run test:logic` **230/230**、`npm run test:architecture` **13/13**、获准本机回环后 `npm run test:http` **80/80**、`npm run contract:check`、`npm run build` 与 `npm run build:demo` 均通过。构建包含上游 Zod 注释提示及初始 JS chunk >500KB 提示，不影响退出码；作为包体积优化后续项观察。
- Codex 内置浏览器当前已有显式 mock 会话，实际总览成功渲染且 synthetic/mock 标签可见；直接打开 `/login` 或 `/setup` 均由已初始化且已认证状态守卫返回总览。此次没有启动 Chrome/Edge。首次未初始化 setup 页面尚不能从当前会话直接呈现；全量自动化 E2E 未跑，故不把上述静态/逻辑/HTTP与单路径 UI 证据描述为全量 E2E。

### 15.33 F2.5 URL 上下文与规则类型筛选收口（2026-10-08）

- `NavigationContext` 已覆盖环境、应用、时间标签与精确窗口、账号、实例、资源、事件、版本、发布、binding、采集 scope、搜索及 feature-owned `view`；序列化只输出允许字段，凭证 query 被忽略，时间范围和未知 feature 视图按 fail-closed 规则解析。历史控制器分别保留 push/replace、受保护前进/后退、未知历史位置恢复与禁止外链行为。
- 补齐 Rules feature 之前未实际消费 `view` 的缺口：规则目录初始 `kind` 由 `resolveRuleKindFilter` 投影；切换规则类型以 replace 写入 URL、清除不再匹配的 binding/publication 选择；打开具体 binding 保留该视图。非法规则类型回到“全部类型”，不会近似猜测。
- 逻辑门禁 **231/231**、架构门禁 **13/13**、typecheck/lint 通过。Codex 内置浏览器实测：`#/applications?env=test-env&app=app-one&range=15m&instance=instance-2&scope=process` 深链恢复对应实例；“查看规则”保留环境/应用/精确 from-to/实例/scope；浏览器返回恢复原实例与观察数据；规则页 `view=degrade` 只列熔断 binding，UI 切成流量控制后 URL 变为 `view=flow` 且只列 flow binding，刷新仍恢复该筛选。全程未启动 Chrome/Edge；这不代表其余页面的完整 E2E 或真实 Python API 验收。

### 15.34 F2.6 admin/view 路由与 shell 能力投影收口（2026-10-08）

- `ROUTES` 现在是页面访问级别的唯一静态来源：公共登录、一次性 setup、普通会话、metrics 查看、admin 操作分别显式声明。App 的守卫直接消费 `accessFor()`；删掉旧的弱 `resolveAccessibleRoute()`，避免另一个只看 authenticated/initialized、会漏掉 role/capability 的访问判定入口。
- 主导航按 `admin` 元数据隐藏系统管理；查看者规则页仍可读取规则目录/详情，但规则编辑能力继续由 `RulesWrite` capability 与 rule workflow 限制。管理员头像入口去账号维护；查看者头像入口去本人改密，避免把只读账号导向管理拒绝页。`isAdministrator()` 在 identity policy 层集中解释闭合 role id，UI 不重复裸角色值。上述 shell 仅改善呈现与路线，绝不替代 Python server 对 route/API command 的鉴权。
- 访问正反例覆盖 metrics 与 admin 深链、权限 capability 缺失、试图伪造 rules:write 的 viewer、查看者导航隐藏 admin 项、查看者/管理员头像目标，以及账号/系统审计/规则命令 owner 测试。逻辑 **232/232**，架构 **13/13**，typecheck、lint、format 检查通过；production build 与显式 demo build 均通过，包体警告仍为 Zod PURE 注释提示及 >500KB 初始 chunk。
- 页面检查只使用 Codex 内置浏览器：管理员规则页在 `view=flow` 下可加载并显示唯一匹配 binding；查看者可见项/路由拒绝由纯逻辑和命令 workflow 测试证明。本次没有通过浏览器直接切换到 viewer 会话，故不把这项单列为完整 viewer E2E；全量自动化 E2E 和真实 Console/Python 授权仍未完成。

### 15.35 F4.01 总览计数与目录投影一致性（2026-10-08）

- `FleetOverviewContainer` 负责目录/环境/查询装配，`FleetOverviewPage` 只组合摘要、连接探测、趋势和应用目录；搜索编辑、过滤与分页投影留在 Overview feature。摘要及关注目标来自同一快照的全范围事实，目录文案明确区分“已筛选”与“全范围”，不把当前页行数拿来充当服务总数。
- 新增 `FLEET-PROJECTION` 逻辑测试：环境全量、第二页、命中搜索、零命中搜索时 total/attention 不变，而目录 total/items 随 search/page 投影；单应用 scope 单独回到 1/1。扩展 `FLEET-MOCK` HTTP 用例验证实际 Console transport/feature adapter 对零命中搜索仍返回全范围总数 3、关注数 1、过滤目录 0 行。
- `npm run test:logic` **233/233 passed**；获准本机 loopback 后 `npm run test:http` **80/80 passed**。Codex 内置浏览器实际交互输入 `app-three` 并提交，页面显示全范围“已登记应用 3 · 需关注 1”，目录显示“已筛选 1 个 · 全范围 3 个”且唯一行是 `app-three`；输入 `missing` 时展示明确“没有符合筛选条件的对象”。截图/AX 均来自 Codex 内置浏览器；没有启动 Chrome/Edge。
- **证据边界：**这是前端 demo HTTP/MSW 与页面渲染证据；容器实际组合和全域统计投影已完成，但真实环境数据、生产告警聚合规则、Python Console 与持久化仍未验收，不能由此勾选 F4.03 或声称全量 E2E 完成。

### 15.36 F4.02 总览指标 scope 与应用目录行一致性（2026-10-08）

- 修复 demo observation 装配错误：应用目录曾把 fleet aggregate 的 QPS summary 复制到每个 application row。现在 `snapshotFor()` 根据每行 `appId` 构造 `scope=application` 的指标 bundle；示例 QPS 由稳定 fixture 常量提供（app-one 42、app-two 84、app-three 63），fleet 卡片/曲线仍读取 fleet scope。未知实例覆盖率投影只更新 quality/coverage，不覆盖行自身指标。模型注释明确两种 scope 的边界。
- 逻辑与 HTTP/MSW 回归锁定：fleet aggregate 和各应用行不混用；单应用查询的 summary、series、row metrics 具有同一 appId/application scope；缺失采样仍以 null 保留；fleet 分页目录 app-three QPS 为 63，而 fleet aggregate 为 123；选中 app-three 后服务返回的应用 scope QPS 为 63。F4.01 的过滤空结果仍保持全范围 fleet counts。
- `npm run test:logic` **233/233 passed**；获准本机 loopback 后 `npm run test:http` **80/80 passed**；`npm run typecheck`、`npm run lint`、`npm run format:check`、production/demo builds、`npm run contract:check` 均通过；`git diff --check` 通过。构建保留 Zod Rollup PURE 注释和初始 chunk >500KB 警告，不调整阈值掩盖。
- Codex 内置浏览器实测：fleet 目录行 app-one/app-two/app-three 分别显示 QPS 42/84/63，fleet summary 为 123；选中 app-three 并 reload 后卡片与目录行同为 63；切到 app-two 后卡片、行及图表采样同为 84 req/s。TPS 明确显示未接入，coverage 3/4、partial quality 与 `asOf` 时间可见。全部页面浏览器检查仅使用 Codex 内置浏览器；没有启动 Chrome 或 Edge。
- **证据边界：**以上 fixture/MSW 与 UI 证明的是前端 scope 映射及 mock transport，不证明 Python Console/Agent 或生产采集器的真实指标。完整浏览器 E2E 本轮未运行（不启动 Chrome/Edge）；真实指标聚合和采集仍依赖 B0/F6。下一项按清单推进 F4.03。

### 15.37 F4.03 总览下钻与观测状态路径（2026-10-08）

- 总览现在提供到故障分析、规则覆盖以及应用实例视图的真实交互入口。规则覆盖按每行 appId 和 application scope 定位；所有下钻使用可分享的 URL 保存环境与精确 RFC3339 `from/to`，Overview、Faults、Rules 的筛选/绑定切换均保留已进入的窗口。相对时间参数只在 URL 缺少或包含无效边界时按一个固定 anchor 解析，避免每次切页滑动窗口。
- 补充逻辑回归 `OBS-ROUTE-WINDOW`、`FLEET-DRILLDOWN`；浏览器手动路径由 Codex 内置浏览器执行：`app-two` 从 Overview 到 Faults 显示同一 env/app/window 和三条对应事件；Overview 的规则覆盖行到 Rules 显示应用 `app-two`、0 个匹配绑定及“来源没有规则或记录”的明确空态；行级“查看实例”打开同 app 且相同 window 的实例目录。Overview 的 partial 覆盖状态亦实际可见。没有启动 Chrome 或 Edge。
- `typecheck`、`format:check`、`lint`、架构 **13/13**、逻辑 **235/235**、HTTP **80/80**、`contract:check`、production/demo build、`git diff --check` 均通过。HTTP 测试中的受控 loopback 用例在授权后通过；构建仍有初始 chunk >500KB 警告，不影响成功状态。
- **剩余验收：**shared QueryView/QueryResource 已有 loading/empty/partial/denied/stale/error/retry 实现和逻辑覆盖，但本轮仅在内置浏览器直接看到 partial/empty/ready 路径；denied、失败后 stale/error 与点击重试的可见状态尚未人工复测。故 F4.03 保持未勾。
- **证据边界：**内置浏览器使用本地 mock/MSW，不证明 Python Console 鉴权、真实规则源、Agent 遥测或生产聚合；不构成全量 E2E。

### 15.38 F4.04 应用/实例目录隔离（2026-10-08）

- 当前应用页由 authorized catalog 和 instance HTTP Port 分别装配；实例查询带明确 `environmentId`、可选 `appId`、精确时间窗，结果按返回记录自己的 `hostId` 分组。无选中实例时显示显式选择提示；应用无记录时显示空态，不以其他应用填充。
- 路由装配中的临时演示 allow-list 已与当前合成目录统一为 `app-one/app-two/app-three`。删除无消费者的旧静态 `APPLICATION_FIXTURES` / `ORDER_INSTANCE_FIXTURES`，移除按 `order-service` 判定是否有实例的策略与固定 `order-5` 默认选择；同步移除应用页三语中已不再使用的旧矩阵文案。
- Codex 内置浏览器验证（没有调用 Chrome/Edge）：`app-one` 显示两行且均标为 app-one；改到 `app-three` 显示“该范围没有已登记对象；不使用其他应用的数据。”且没有实例矩阵；深链使用 `missing-env` 时页面只提供环境选择器，旧应用实例数据不残留。
- `npm run typecheck`、`npm run format:check`、`npm run lint`、`npm run i18n:check`、逻辑 **236/236**、架构 **13/13**、HTTP **80/80** 和 `git diff --check` 通过。HTTP 的受控 loopback case 经授权绑定临时本机端口后通过。
- **限制：**mock catalog 目前只有一个有效环境，所以另一个“有效且有数据”的环境切换尚无 fixture 覆盖；这里只证明精确 env 查询路径和非法环境隔离。真实 Console inventory、跨环境生产 ACL、采集状态和全量浏览器 E2E 仍待 F6/F7/B0。

### 15.39 F4.05 实例 scope 与版本回执一致性（2026-10-08）

- F4.05 的回归测试先暴露了 mock 能力声明错误：一个只含 `processMetrics` 的观察实例同时声明 Process 与 Container supported，导致 container 详情复用了进程层指标。现在 fixture 的 `supportedScopes` 仅包含 Process；Host/Container 响应合法地返回 `metrics: null`，详情页显示“该实例未接入此采集层级；不会借用其他层级的指标。”，不渲染卡片/图表。
- 逻辑测试验证 Host/Container/Process 三种 scope、所选实例的 incarnation、receipt epoch、指标 context；HTTP/MSW 通过同一个 Console transport 对三种 scope 发请求，只有 Process 返回 metrics。内置浏览器（没有调用 Chrome/Edge）验证未选择时保持空提示；选择 `instance-1` 后 URL 携带 instance 与 process scope、版本回执显示 `version-one`；切换 Host/Container 均无指标且显式不可用，切回 Process 后自己的采样恢复。
- `npm run test:logic` **238/238**、`npm run test:http` **80/80**，typecheck/lint/format、production/demo builds、`git diff --check` 均通过。受控 loopback HTTP case 经授权绑定临时端口；构建继续报告既有 Zod PURE 注释与首包 >500KB 警告。
- **证据边界：**证明前端领域模型、mock HTTP 与渲染一致，不证明生产 Agent 的 scope 能力公告、规则加载收敛或真实观测数据；这些仍属 F6/B0。

### 15.40 F4.06 实例选择生命周期与上下文导航（2026-10-08）

- 风险与缺陷：路由 `navigate()` 会把当前 URL context 与新 context merge；字段省略代表保留，而不是清除。应用页点击“清除实例选择”时原先省略 `instanceId` / `metricScope`，导致失效深链仍留在 URL、清除操作看似无效。现新增纯函数 `withoutInstanceSelection()`，以显式 `undefined` 清除实例和层级；应用/环境/窗口变化同样移除旧目标。
- 回归测试先锁定 route merge 语义：旧 context 含 instance/scope，新 context 执行 clear 后生成路由不再含二者，搜索仍保留。HTTP/MSW 对真实 Console adapter 覆盖缺失实例 404，以及退休 epoch wire 410 映射为明确 `instance_incarnation_changed` 409；既有 QueryResource 测试覆盖权威 404/410 清除旧值。
- Codex 内置浏览器（仅 IAB；没有调用 Chrome 或 Edge）验证筛选为 `instance-2` 时目录只显示该行，而详情仍明确为用户之前选择的 `instance-1 · incarnation-1`；不会自动切换实例。Rules/Realtime 详情动作以及 Faults 主导航均保留所选实例与精确 `from/to`。非法 `instance=not-real` 显示“实例不存在或已移除”；点击清除后 URL 删除 `instance` 和 `scope`，详情回到显式未选中提示。
- 验证：typecheck、format、lint、i18n 通过；逻辑 **239/239**、HTTP **81/81**、架构 **13/13**；production/demo builds 与 `git diff --check` 通过。完整 HTTP 命令第一次在普通 sandbox 下因 loopback `listen EPERM` 失败；仅对本次本机隔离监听命令授权重跑后全部通过。build 仍有既存 Zod 注释与初始 chunk >500KB 警告。
- **证据边界：**IAB 渲染来自本地 demo/mock；HTTP 404/410 为 MSW contract，不证明 Python Console 实际产生这些状态。没有运行启动 Chrome/Edge 的 `test:e2e`，也没有验收真实 Python 服务、数据库、Nacos/Consul；F4.06 focused acceptance 不等同全量 E2E。验收记录：[R-DASHBOARD-F4.06](acceptance/R-DASHBOARD-F4.06.md)。

### 15.41 F4.03 总览读取状态人工验收补齐（2026-10-08）

- F4.03 的路由与观测状态矩阵已补齐人工可见的权限拒绝和失败恢复路径。演示 HTTP handler 新增两个仅供验收的保留目标：`mock-forbidden-application` 固定返回 403/`forbidden`；`mock-recovering-application` 首次返回 503/`service_unavailable`，用户显式重试后返回合法空快照。计数器局限于 opt-in demo mock handler，测试显式重置；生产 adapter/build 不引入这些处理器。
- Codex 内置浏览器验证（只用 IAB，没有启动 Chrome/Edge）：403 页面显示无权查看且不提供重试入口；503 页面显示安全失败提示与“重试读取”，点击后重新请求并转为合法 empty 状态，没有伪造行或残留旧错误。此前 §15.37 与 §15.40 记录的总览下钻、精确时间窗、实例上下文保持及非法目标清除证据继续有效。
- 验证：`npm run typecheck`、`npm run format:check`、`npm run lint`、`npm run i18n:check`、逻辑 **239/239**、HTTP **82/82**、架构 **13/13**、production/demo builds、build-profile **2/2** 和 `git diff --check` 通过。HTTP 受控 loopback 用例经批准后绑定临时本机端口；构建仍有既存 Zod 注释和首包 >500 KB 警告。
- **证据边界：**拒绝和恢复来自 synthetic demo HTTP 响应，证明前端 handler/adapter 与可见交互，不证明 Python Console 的权限策略、服务端重试语义或生产遥测。全量 `test:e2e` 未运行；其脚本会启动外部 Chrome/CDP，不符合当前浏览器约束，故不能宣称 E2E 全部通过。验收记录：[R-DASHBOARD-F4.03](acceptance/R-DASHBOARD-F4.03.md)。

### 15.42 F4.08 完整规则集草稿编辑路径（2026-10-08）

- 通过唯一 binding 打开对应 source snapshot/profile；工作台以完整 rule set 为编辑单位，单条表单修改后 JSON 预览完整数组。新增/移除记录均作用于本地候选；保存创建/更新完整持久草稿并接收后台 revision，删除草稿与丢弃本地编辑是不同操作，不将草稿保存伪装为配置中心发布。
- Codex 内置浏览器（只用 IAB）实际执行：新建本地候选，阈值从 2000 改到 2100，新增第二条规则并在二次确认后移除；预览显示完整数组。保存后界面显示无未保存修改与 `draft-revision-2`；服务端候选兼容校验通过，整组差异按当前基线显示 0 项。再改为 2200 后尝试切换页面，导航对话框阻止切换；选择“留在当前页面”后仍显示 2200 和未保存态。随后确认放弃，只回到已保存的 2100；最后删除本轮新建的 mock 持久草稿并核实工作台回到“从当前快照建立草稿”。所有提交只到本地 demo MSW，不接真实配置中心。
- 自动验证：`node --test --test-name-pattern='RULE-(DRAFT|SET)' tests/logic/run.mjs` **8/8**；`node --test --test-name-pattern='RULE-(BINDINGS|SNAPSHOT|CANDIDATE|COLLECTIONS|COMMAND|MOCK)' tests/http/run.mjs` **6/6**；typecheck、format、lint、`contract:check` 与 `i18n:check` 通过。规则 wire 的严格完整集合/身份校验、requestKey/结果未知不重放由 HTTP tests 覆盖。没有运行会启动 Chrome 的 `test:e2e`；IAB 手动证据是实际渲染路径，不扩张成全量 E2E。
- 模式评估：持久命令与操作核查沿用既有命令合同；rule-kind 是闭合类型联合，binding profile 是服务端校验的事实，本切片不新增 GoF 模式。基线/当前候选的显式值快照和简单枚举状态足够，不引入 Memento、Strategy 或状态对象。
- **证据边界：**这证明 React 页面、HTTP adapter/mock contract 与交互组合，不证明 Python Console 数据库持久化、CAS/配置中心写回、实际运行时加载或跨语言兼容。以上仍由 B0/F6/F7 与后续受控服务联调验收。

### 15.43 F4.09 版本发布、回执与活动计划（2026-10-08）

- `RuleSet` 的版本目录、发布阶段、实例回执和后台活动计划使用独立查询/命令事实。历史版本不可变；回滚建模为选择历史内容并发起新的发布，不回退运行版本序号；活动计划要求明确 target、restore、起止时间与 IANA 时区，浏览器不执行启动/恢复 timer。
- 通过 Codex 内置浏览器（仅 IAB，无 Chrome/Edge）在规则页实测：打开演练版本并确认其冻结内容；提交活动版本后刷新看到独立发布记录、目标校验/配置写入/回读阶段；再选历史基线创建另一条新发布记录。针对预置的部分回执，UI 显示“1/3 已生效、1 待加载、1 待重启”，并逐实例显示 applied/pending/restart-required；修正了原先误用“规则配置校验失败”的 partial 文案。计划路径实测明确 target/restore 与 UTC 时间、重叠计划被阻止、待执行计划可带原因取消且读回“已取消后续计划”，取消后合法非重叠计划可保存并由计划列表读回。页面提示关闭浏览器不会取消后台计划。
- 测试：部署相关逻辑 **19/19**、规则 mock HTTP **2/2**（包含独立 binding 的 baseline、回执统计、409 overlap、取消、再创建、reset），`test:architecture` **13/13**；typecheck、format、lint、Console contract、i18n 和 `git diff --check` 通过。未运行会启动 Chrome/CDP 的完整 `test:e2e`。
- **证据边界：**浏览器写入全部只到本地 demo MSW，reload 后回到种子状态。长序列中曾观察到一次后续读取短暂 stale/error；重新加载种子并分开复测发布后恢复，focused contracts 未复现，详见验收记录。历史基线是 mock 中当前源快照，故界面证明“发布历史版本的新命令与读回”，不是配置中心实际变化后的运行时回滚；未知命令结果由 workflow/HTTP 合同测试覆盖，不等同于 IAB 实测。Python 持久化、Nacos/Consul CAS、后台调度器、Agent 实例真实载入与重启限制均未通过真实服务验证。Acceptance：[R-DASHBOARD-F4.09](acceptance/R-DASHBOARD-F4.09.md)。

### 15.44 F4.10 实时监控查询、轮询与窗口（2026-10-08）

- 正式 `#/realtime` 路由使用 `RealtimeObservationContainer → createRealtimeMonitor → LiveMonitoringPage`：容器持有查询组合，monitor 是唯一刷新/取消/快照 owner，页面和 `MonitoringStatusBar` 只呈现状态与操作，统一观测组件呈现同窗摘要和曲线；活跃路径不再使用按 `frame` 推进的静态样本回放。
- 每次 rolling 读取生成精确 UTC 窗口；fixed 窗口保持不变。每序列最大 1000 点，monitor 替换已验证窗口包，不另行 append 点列。暂停不会发送后端命令；恢复立即重读最新窗口。IAB 实测同窗摘要、曲线、未接入 TPS、6 秒暂停稳定及恢复读取后的新窗口。
- 全量 `npm run check` 到达并通过末项：logic **239/239**、HTTP **83/83**、architecture **13/13**、Hooks lint **6/6**、browser-tools **7/7**、visual-tools **7/7**、i18n-tools **9/9**、verification-tools **5/5**、build-profile **2/2**、Sites **4/4**，并通过 typecheck/format/lint/contract/i18n 与 production/demo build。`test:e2e` 未运行（其脚本会启动 Chrome/CDP）；未调用 Chrome/Edge。
- **证据边界：**当前 IAB 会话使用本地 demo MSW/合成指标。首次从规则页切入曾短暂出现一次通用读取失败，重新进入实时路由后正常，根因未确定，已留存为 Mock/UI 稳定性观察。老 frame 回放相关文件尚有未装配的旧路径引用，当前正式路由不加载；统一清理属于 F6。此项不证明 Python Console、Reporter/生产采集、断网下的真实服务恢复或全量 E2E。验收记录：[R-DASHBOARD-F4.10](acceptance/R-DASHBOARD-F4.10.md)。

### 15.45 F4.11 实时监控实例与 scope 选择（2026-10-08）

- **实现：**实时路由经 Applications 公开 Port 读取实例目录；选择实例时以目录中的 app/instance identity 与 `supportedScopes` 构造实时查询；环境/应用变化清除实例，清除实例恢复 Fleet/Application 汇总；不支持的实例 scope 不发指标请求；中/英/日文标签已补齐。查询资源使用 StrictMode 可重放的取消/延迟释放边界。
- **自动检查：**本次重新执行完整 `npm run check` 退出码 0，覆盖 TypeScript、格式、lint、逻辑、HTTP、架构、i18n、构建与 Sites；新增 `MONITOR-FILTERS` helper 测试。第一次沙箱内运行仅因 HTTP loopback 测试监听被拒（`listen EPERM`）未完成，获准本地监听后完整重跑通过。
- **内置浏览器：**本地 demo 中选中 instance-1 得到 URL `instance=instance-1&scope=process` 和“进程”上下文；清除回到 `scope=application`；切换 app 仍留在实时路由，app-two 的 instance-3 也可选中。
- **本次筛选复核：**Codex IAB 从有效 app-one 切换到 app-two，URL 查询 app 与控件选中项一致，摘要 QPS 从 42 变为 84 req/s，路由未离开实时页。单次有效应用切换通过，不替代长时间轮询稳定性验收。
- **未完成门槛：**两个 IAB 标签后续都出现 stale；语义化重试、暂停→恢复未即时清除 stale；整页 reload 后恢复到 partial，且 6 秒后读取时间推进。error/warn 控制台为空，但无法区分 request/mock transport、计时器节流或 owner 生命周期根因。故仍不能证明长时筛选/轮询稳定，F4.11 不勾。项目自动化 `test:e2e` 会启动 Chrome，本阶段不运行；遵照用户最新要求，浏览器操作只允许使用 Codex 内置浏览器，且手工 IAB 结果不冒充自动化 E2E。演示数据不证明 Python/生产采集链路。详见 [R-DASHBOARD-F4.11](acceptance/R-DASHBOARD-F4.11.md)。

### 15.46 F4.12 实时监控异常状态、发布标注与资源释放（2026-10-08）

- **实现修正：**`RealtimeObservationContainer` 现对 monitor 使用 `useOwnedDisposal`，卸载时 dispose 订阅及 PollingStore；保留 StrictMode 延迟释放行为。指标 mock wire 现在传递 fixture annotations；此前丢失发生在 mock adapter，不是图表渲染层。仅 app-one fixture 有窗口中点的 publication 标注。
- **检查：**全量 `npm run check` 退出码 0：logic 240/240、HTTP 85/85、architecture 13/13、Hooks lint 6/6、browser/visual/i18n/verification 工具均通过，production/demo builds 及其余资源门禁通过。隔离 HTTP listener 仅绑定 localhost；未启动 Chrome/Edge。
- **内置浏览器：**app-one 的 QPS、p95、拦截率、CPU、内存图表可见“规则发布”标注；从实时页导航到总览后等待超过一个轮询间隔，`/api/v1/metrics/query` 日志时间戳不再变化。
- **受控恢复证据：**HTTP 85/85 包含 `METRICS-RECOVERY` 的成功→503→成功与失败→重试成功，以及 `METRICS-MONITOR-RECOVERY` feature monitor+Console HTTP 全链路 focused test **1/1 passed**。IAB 中 `mock-retry-metrics` 手动重试成功；新开 `mock-recovering-metrics` 标签观察到 `200→503→200...` 后恢复正常 partial 且读取时间前进。之前的后台标签停止产生请求日志后仍显示 stale，不能证明成功响应被 UI 拒绝；根因未证实，不再据该旧标签现象归因为浏览器渲染/查询所有权缺陷。
- **未完成门槛：**未对真实 Console/Reporter 做断网及迟到故障注入；未做长期内存剖析；普通 monitor 曾在旧 IAB 标签中显示 stale，但标签停止产生请求日志，无法归因；自动化 `test:e2e` 会启动 Chrome/CDP，本阶段遵照用户要求不运行。一次性 mock 自动恢复路径已获 Node 与 IAB 正向验证，但 F4.12 仍不勾选，详细边界见 [R-DASHBOARD-F4.12](acceptance/R-DASHBOARD-F4.12.md)。

### 15.47 F4.13 故障筛选 URL 所有权与浏览器历史（2026-10-08）

- 故障分析 `severity`、`category` 与有界 opaque `cursor` 现在由故障路由 URL 持有；仅故障页面解析这些参数，过滤变更重置 cursor，未知枚举/超长 cursor 不进入查询。未引入新模式对象，沿用路由上下文、纯查询投影和现有 Incident Port。
- 使用 Codex 内置浏览器（未启动 Chrome/Edge）实际操作严重度“严重”与类别“资源压力”：URL 记录两项；浏览器后退恢复到只选择“严重”；刷新后严重度恢复、类别回到“所有类别”。严重过滤后筛选结果为 1、全范围统计仍为 3。
- 验证：typecheck、逻辑 **242/242**、lint、架构 **13/13**、格式与 diff 检查通过；HTTP **85/85** 通过。HTTP 测试只在获得本机隔离 `127.0.0.1` listener 权限后运行。
- 补齐后端反推边界：复用授权实例目录 `InstancePort`，选择实例绑定 `(environmentId, appId, instanceId, process)`；改变应用或清除实例正确恢复应用/全局范围。mock 事件为 24 条，分页按 20+4 实际验证；第二页的全范围统计仍为 24，继续选严重度后 URL cursor 消失、筛选结果为 8，统计仍为 24，事件选择随非 cursor 过滤清除。跨页时显式选中的事件与 evidence URL 保持不变。
- Codex 内置浏览器实测：实例选项来自目录；实例下钻后显示 6 条 instance-1 事件与实例范围统计，`instance=instance-1&scope=process` 刷新后恢复；切回“全部应用”后 instance/scope 从 URL 清除。未使用 Chrome/Edge。自动化 `test:e2e` 的 CDP 运行按用户明确要求跳过；这不影响本页内置浏览器交互验收，但不能表述为 Chrome E2E。
- 验证：完整 `npm run check` 通过：typecheck、format、lint、logic **242/242**、architecture **13/13**、HTTP **86/86**、OpenAPI contract、browser-tool utilities、visual/i18n/verification、i18n parity、production/demo builds、build profiles、Sites worker。HTTP 的 loopback 用例经授权隔离 listener 运行。构建报告仍提示初始 JS chunk 约 1.18 MB 超过 500 KB 警告线；本切片未处理该既存体积问题。
- **后续边界：**Python Console incidents 查询与 Reporter/生产事件源的真实网络数据尚未实现/验收；F4.14/F4.15 详情关联数据及跨 feature 下钻保持未完成。细节见 [R-DASHBOARD-F4.13](acceptance/R-DASHBOARD-F4.13.md)。

### 15.48 F4.14 事件事实投影与历史下钻（2026-10-08）

- `IncidentEvidence.relatedRule` 从一个不充分的 `relatedVersionId` 改为显式 nullable relation：`environmentId/appId/bindingId/versionId/publicationId`。wire 是 strict object；领域验证要求环境/应用归属匹配事件、发布 ID 匹配事件 publication、版本 ID 匹配结构化发布/生效事实；缺少关系时不显示 rules 入口。此字段是事件详情后端必须实现的 read projection，不由浏览器从 caption 或 publication 字符串拼装 binding。
- 规则跳转现在同时传 binding、version、publication、事件和观察上下文；Rule Console 的 route owner 根据 URL 分别加载准确不可变版本和发布审计。IAB 中点选发布事件后确认 `version-event-flow` 与 `publication-event-flow-01` 显示为选中；刷新 URL 深链后相同目标仍恢复。
- 事件到指标的跳转保留原始 event、app、instance、scope 和 UTC from/to。`eventId` 存在时实时监控以 fixed window 初始化，因此不会在进入页面后的轮询中把历史事件对照窗偷偷滑动；本地 IAB 页的查询上下文和实际显示窗口一致。
- 只在 Codex 内置浏览器中用新建本机隔离 Vite 端口验证，使用合成 viewer 与 demo MSW；未启动 Chrome/Edge，未运行 CDP `test:e2e`。原 5173 标签曾显示泛化读取失败，复因未证实，新隔离实例加载当前源码后没有重现。
- 自动化结果：typecheck、lint、format、logic **242/242**、HTTP **86/86**、contract **42 paths / draft-partial / pending=[]** 通过。关系错配负例覆盖所属 app 与 publication；真实 Console/Python/Reporter/指标生产关联均未运行。
- F4.14 前端 mock 投影与 IAB 切片可勾选；当时空/拒绝/过滤选中失效矩阵尚待 F4.15 收口。生产服务验收和总目标继续未完成。详细证据见 [R-DASHBOARD-F4.14](acceptance/R-DASHBOARD-F4.14.md) 与后续 [R-DASHBOARD-F4.15](acceptance/R-DASHBOARD-F4.15.md)。

### 15.49 F4.15 事件深链与失效恢复（2026-10-08）

- 路由继续由 URL 持有 event、instance、scope 与 UTC window；F4.14 的规则/监控下钻已验证精确身份和时间窗。本切片不增加另一套选择 store，也不从列表首条推断 event。
- 内置浏览器先显式选择 `incident-resource-pressure`，再把级别筛选改为“警告”：URL 中 `event` 被清除，选中证据面板卸载并清理，列表没有静默选择第一条。随后 `severity=warning&category=resource` 呈现“当前筛选没有匹配事件；全范围统计仍保留”与显式未选择提示。
- 直接打开 `event=missing-event` 的有效筛选深链时，时间线仍按筛选展示；详情只显示 404 的“选定对象不存在或已移除”安全状态，没有把旧证据保留或替换成别的事件。普通无 event 深链同样显示显式选择提示，不自动选首条。
- 生命周期逻辑 **242/242** 通过，故障测试覆盖 partial/unavailable 领域投影、缺失/错目标拒绝、同键失败 stale、404 清理旧值，以及权限撤销时清除旧数据并拒绝迟到响应。共享 `QueryView` 对 denied/error/stale/partial 分别呈现不同状态；本次 IAB 未执行角色撤销或注入 partial HTTP 响应，因此这两项不是浏览器实测。HTTP **86/86** 与上轮完整 `npm run check` 结果通过；本切片未改业务源码。
- 只使用 Codex 内置浏览器 `127.0.0.1:5183` 的本地 demo/MSW；未启动 Chrome/Edge，未运行会启动 CDP 浏览器的 `npm run test:e2e`。从先前实时页直接切换到故障页时曾出现一次泛化读取失败，刷新后恢复；具体原因未确认，不能把该瞬态描述为产品故障或成功根因修复。
- 范围只关闭本地前端 F4.15 切片。Python Console incidents/evidence API、Reporter 生产事件、服务端权限撤销与真实跨服务 E2E 未验收；F4.16 UI 后续单独验收，见 §15.50。

### 15.50 F4.16 配置中心登记 UI（2026-10-08）

- 内置浏览器只访问 `127.0.0.1:5183` demo/MSW。系统管理连接页显示 Nacos 示例配置、运行探测状态、探测/读取 UTC 时间、有效截止、耗时与已确认能力，并提示 demo check 不连接真实 Nacos/Consul。
- 新增表单显示 Nacos/Consul，认证方式为凭证引用、直接录入、无需认证；不要求 KMS。切换 provider 会转为对应 namespace/datacenter 和 Nacos user/password 或 Consul ACL token 字段。编辑已有 source 默认“保留已有凭证”，UI 仅显示凭证已配置状态，不展示真实凭证或引用值。
- 对已有 Nacos source 执行只读演示连接检查，IAB 实际显示合成的成功状态、能力与 UTC 检查时间；没有登记/修改 source 或业务规则。此前在未重载的 HMR 状态第一次点击检查时出现泛化异常文案；重载后同一只读检查成功，根因未证实。检查异常曾错误复用“操作结果未确认”文案，修复为独立的三语“连接测试未能完成”反馈，与写入操作未知结果完全分开。
- 验证：typecheck、目标 ESLint、目标 Prettier、三语 i18n parity 通过；logic 242/242 通过。`npm run test:http` 有 85/86 通过，唯一失败为受限环境无法绑定隔离 loopback listener（`listen EPERM 127.0.0.1`）；其中 source registry/check/command/authorization 等 source HTTP/mock 用例均通过。未运行 Chrome/Edge/CDP。
- F4.16 关闭的是前端 UI 切片。此处没有真实凭证输入/保存，也没有调用真实配置中心；Python Console 持久化、服务端 Secret 保护、SSRF、条件更新、真实能力探测与 F6.6 保持未验收。

### 15.51 F4.17 会话能力、协议快照与审计查询（2026-10-08）

- **实现：**系统管理权限 tab 由静态 `PermissionsPanel` 改为 `ObservedPermissionsPanel`；app 路由把身份模块已确认的 `ControlPlaneAccessState` 通过 props 传入，面板只读显示用户名、账号标识、角色和 capability 当前授予状态，不新增会话读取、权限写入或 feature 私有依赖。协议 tab 使用现有观察资源分别呈现 rule-source、agent-reporting、token 三项后台支持版本、实际协商版本、兼容状态及 UTC 观测时间；没有观测到的项明确显示“尚无观测”。
- **Codex 内置浏览器（仅 IAB）：**权限 tab 显示 `mock-admin` / 管理员及流量查看、规则编辑发布两项能力已授予。协议 tab 实际显示规则配置 `rule-source-v1` 已协商且兼容、集群配额 `token-v1` 已协商且兼容；事件上报仅显示服务端支持 `agent-reporting-v1`，协商与时间为“尚无观测”，总览明确“部分链路或版本尚未确认”。第一次路由读取先出现通用读取失败，重载后显示上述部分快照；具体瞬态原因未确认。审计位于相同的系统管理分类 tab，没有新增顶级菜单；默认 UTC 半开时间窗读取 2 条 demo 记录，按不存在的 actor 筛选后读回 0 条的明确空状态。
- **自动化验证：**typecheck、目标 ESLint、Prettier、i18n 检查通过；逻辑 **242/242**、架构 **13/13** 通过；demo build 通过。build 仍显示既有 Zod PURE 注释警告及 initial JS 约 1.18 MB 的 chunk-size 警告。此次未执行会启动外部浏览器/CDP 的 E2E，也未重跑会因受限 loopback listener 失败的全量 HTTP 门禁。
- **边界：**本切片证明前端把当前 demo session/protocol/audit read facts 投影到 UI；不证明 Python Console 的生产版本协商、实际 peer 兼容、服务端 capability 授权、审计落库/完整性/分页一致性或角色撤销后的生产行为。完整后端与跨语言验收仍待 F6/B0。

### 15.52 F4.18 系统内身份页与独立路由复用（2026-10-08）

- **实现/边界：**系统管理的账户维护、角色绑定 tab 与独立 `#/accounts`、`#/roles` 路由均组合 Identity feature 导出的 `AccountsPage` / `RoleManagementPage`、同一 `createAccountManagementWorkflow` factory 和 `createAccountManagementHttp` Port；表单与业务状态转移不在 System feature 复制。每个 route owner 按会话生命周期创建并 dispose 自己的 workflow，不共享跨路由可变实例。系统 `view=accounts|roles` 与独立 route 分别由稳定 URL route/view 持有，角色目标统一使用 `account` query。
- **Codex 内置浏览器（仅 IAB）：**系统 tab 的账户维护列表显示 admin/viewer 两条 demo 记录；顶部账户入口转到独立 `#/accounts`，相同列表/字段/操作出现。系统账户行的“角色绑定”导航到 `#/system?...&account=account-view&view=roles` 并选中 viewer；独立账户页的同一操作导航到 `#/roles?...&account=account-view`，页面选中 viewer、未改角色时保存/放弃均禁用。独立角色深链整页刷新后仍恢复 viewer 选择与原角色，不发生默认账号漂移。
- **读取观察：**一次系统 tab 离开后重返时列表呈现明确读取失败状态，显式 retry 未在当前页面恢复；整页 reload 后列表成功读回 admin/viewer。原因未确认，因此仅把“深链刷新能恢复”视为验证通过，并保留该瞬态作为 demo/mock 稳定性问题，不推断是共享 Identity 实现造成。
- **自动化：**共享逻辑仍由 `npm run test:logic` 242/242、`npm run test:architecture` 13/13 覆盖；本轮 F4.17 同时通过 typecheck、目标 lint/format、i18n 和 demo build。权限决策测试覆盖 admin/view 差异；本轮 IAB 未切换/撤销角色，也未提交角色修改。
- **边界：**仅证明前端页面/URL/会话 owner 组合与本地 demo。生产服务账号权限、角色变更审计、session invalidation、角色读取一致性与 Python Console E2E 仍待 F6/B0。

### 15.53 F4.22 登录 mock 未知用户提权修复（2026-10-08，部分证据）

- **问题与修复：**身份 mock 原先只校验用户名/密码非空，并把所有未知用户名映射为 admin。现在仅允许明确 demo 身份 `admin` / `viewer` 配合 demo-only 合成密码 `synthetic-password`；角色从固定账号表确定。未知用户名与错误密码使用相同的 401 `unauthenticated` 响应，失败路径不写入/升级 mock role。该凭据只存在于被明确隔离的 demo mock handler，不是生产账号/默认密码，真实认证仍由 Python 后端实现。
- **HTTP 工作流测试：**`IDENTITY-MOCK` 定向测试 2/2；完整 `IDENTITY-*` 筛选用例 7/7。覆盖 admin/viewer 固定角色、未知账号拒绝、错误密码拒绝、失败后 anonymous role 保持不变，以及既有独立 session 回读工作流。
- **Codex 内置浏览器（仅 IAB）：**localhost 新 origin 的干净 demo 会话中，未知用户与错误密码均留在登录页并显示同一安全文案；`admin` + 合成 demo 密码经过确认后进入总览。没有调用 Chrome/Edge/CDP。viewer 的 UI 浏览器登录本轮未单独重置会话验证，角色映射由 HTTP 工作流测试覆盖。
- **门禁：**typecheck、目标 ESLint、三语 i18n key parity、build-profile 2/2、demo build 均通过。demo 构建保留既有 Zod PURE 注释警告及约 1.18 MB 初始 JS chunk 提示。
- **状态边界：**F4.22 整项仍未勾选；用户修正凭据后的错误恢复见 §15.182，Python 停用账号/拒绝凭证/429 限流路由与 SQLite adapter 的后续定向测试见 §15.183。页面级真实网络失败恢复、IAB 状态呈现和 Python 生产 composition 尚未验收。F4.24 的生产模式/演示提示分离与 session 过期 UI 也未由本记录关闭。

### 15.54 F4.23 会话菜单与安全回跳（2026-10-08，部分证据）

- **实现：**头部 UserMenu 使用确认身份的用户名与角色，按角色显示账户维护/修改密码快捷入口并提供显式登出。新增站内 `returnTo` 路由上下文，登录完成后按已确认角色重新授权；非法、setup/login 或无权目标都回落总览。logout pending/结果未知/失败/未确认均提供会话检查恢复路径，不自动重发命令。
- **自动化：**`npm run typecheck` 通过；目标 ESLint 通过；逻辑测试 243/243、架构测试 13/13、三语 i18n key parity 通过。详见 `acceptance/R-DASHBOARD-F4.23.md`。
- **Codex 内置浏览器（仅 IAB）：**本地 demo 账户页退出后先显式显示“结果尚未确认”；检查会话后确认匿名并保留 `returnTo=accounts`。viewer 登录后安全回落总览，菜单呈现查看者身份与改密入口；viewer 直接访问 `#/accounts` 被拒绝，账户表未渲染。未使用 Chrome、Edge 或 CDP。
- **状态边界：**F4.23 整项仍未勾选。当前只有本地 demo mock 证明界面/导航/前端守卫；真实 Python `/auth/me`、logout、会话过期撤销、Cookie/CSRF 及生产角色行为待后端装配后验收。全自动 E2E 未运行，因为现有套件驱动外部浏览器；本轮改以 IAB 手工验证并辅以逻辑/架构测试。

### 15.55 F4.20 / F4.21 首次初始化路由与初始化会话语义（2026-10-08，部分证据）

- **问题与实现：**setup 工作流的普通 bootstrap 读取此前每次都触发全局认证恢复；React StrictMode/路由 gate 的并发读取会把唯一 auth owner 重置到 `checking`，造成 setup 首启加载循环/提交后退回首步。现在普通读取复用已确认的路由事实；用户主动重查、初始化命令前和命令回执后继续强制从 authority 刷新。应用在 setup authority 已确认后容忍工作流自身的短暂 revalidation，不为中间态重建向导。
- **身份边界：**mock 初始化完成只关闭 setup，不创建或登录管理员账号；成功确认后跳登录页，登录依然要求用户单独提交并完成服务端身份回读。首次初始化 fixture 将 principal 显式置为 anonymous，避免残留 demo 身份伪装成自动登录。
- **Codex 内置浏览器（仅 IAB）：**在本地 demo/MSW 首启场景走完 storage/admin/config-source 表单、review、提交；确认向导不回到第一步，随后落到登录页。未初始化时直接访问 login 会被替换为 setup；初始化后再访问 setup 则回登录。全过程未启动或连接 Chrome、Edge、CDP。该手工 IAB 证据只代表 mock 页面与路由交互，不是 Python 后端 E2E。
- **自动化/构建：**本轮重新通过 typecheck、lint、format、逻辑 **243/243**、架构 **13/13**、HTTP **88/88**（包含隔离 localhost transport）、Console contract、三语 i18n、build profile **2/2**、Sites worker **4/4** 和 demo build。HTTP loopback 仅在单次测试命令获得本地 listener 权限后运行；未连接外部服务。构建继续报告既有 Zod PURE 注释及约 1.19 MB 初始 JS chunk 警告。
- **未关闭：**F4.20 的全部网络失败/恢复、字段级状态、安全清理分支尚未逐项验收；F4.21 的 Python bootstrap 事务、并发锁、持久化/重启与真实 source write-back 尚未实现验收，故两项仍保持未勾。`npm run test:e2e` 会启动外部 CDP 浏览器，本轮按用户约束未运行；IAB 手测不替代它，也不替代真实服务验收。记录见 [R-DASHBOARD-F4.20-F4.21](acceptance/R-DASHBOARD-F4.20-F4.21.md)。

### 15.56 F4.21 同源多标签初始化后的前台权威刷新（2026-10-08，部分验证）

- **问题：**两个同源标签中一个完成首启后，另一个仍可能持有旧 `uninitialized` 快照；原实现只在认证 Provider 首次挂载时读取 bootstrap/session。
- **实现：**`AuthenticationProvider` 监听窗口 `focus` 与文档 `visibilitychange`，可见时让唯一 `AuthenticationWorkflow` owner 强制重读 bootstrap/session。刷新时守卫进入 checking；已过期会话、登录/登出结果未知、已有失败待显式检查或另一个身份操作正在执行时不会自动恢复。初始化回执触发的显式 `restore()` 可 supersede 尚未完成的后台前台刷新，防止用旧响应确认写入。
- **自动化证据：**逻辑门禁 **246/246** 覆盖 authority 状态变化、未知写保护、显式初始化确认优先级，以及 focus/visibility observer 的可见性过滤和清理；最终完整 `npm run check` 通过，包括 HTTP **89/89**、架构 13/13、build-profile 2/2 与 Sites worker 4/4。
- **浏览器证据边界：**使用两个 IAB 标签复现旧标签保留 setup 的初始问题；完成另一个标签的初始化后，旧标签仍显示其内存快照，reload 后才进入 login。IAB 控制接口本轮没有提供可验证的真实标签焦点切换操作，因此 listener 尚未在真实标签切换中被 IAB 触发确认；页面 reload 不作为替代证据。Chrome/Edge/CDP 均未调用。
- **状态：**F4.21、F4.20 仍不勾选；仍需 IAB 可实现的真实焦点/可见性验收，并需 Python bootstrap、事务/并发、持久化、重启及配置中心权威读写验证。详见 [R-DASHBOARD-F4.20-F4.21](acceptance/R-DASHBOARD-F4.20-F4.21.md)。

### 15.57 Python Console B0.2 账号目录只读切片（2026-10-08，部分实现）

- 新增管理员专用 `GET /api/v1/accounts?page&pageSize&search&status?` 与 `GET /api/v1/accounts/{accountId}`。每次请求使用 `sentinel_session` 重新解析当前角色：匿名 401、`view` 角色 403；不依赖前端隐藏控件授权。查询严格拒绝未知/重复参数、超界分页/搜索与非法状态；详情未找到遵守现有前端合同返回 `200 null`。响应只包含 id、账号名、角色、状态、built-in、last-login、revision 与 last-active-admin 安全事实，使用 `no-store`/`Vary: Cookie`。
- 复用现有 consumer-owned read Port + SQLAlchemy adapter；`build_app` 要求显式注入 `AccountDirectoryReader`。新增 Alembic `0002_account_directory_facts`，`built_in` 对既有账号默认 false、`last_login_at` 可空，并约束 built-in 账号必须是 active admin；列表派生唯一 active admin 状态。schema 查询显式选取安全列，不读取/序列化密码哈希、会话或审计数据。
- 证据：Python **3.12.14** Console 全套测试 **46/46 passed**，涵盖管理员读取、匿名/查看者拒绝、严格查询解析、脱敏错误、SQLite 分页/筛选/搜索、SQL wildcard 转义、built-in 约束、唯一 active admin 派生状态、迁移 schema 与数据库故障映射；`compileall`、生产源码 88 列检查及 `git diff --check` 通过。依赖取自本机已存在临时环境，没有下载依赖、连接真实 DB、启动浏览器或修改生产数据。
- **仍不勾 B0.2：**仅实现账号目录查询与两个 additive schema facts；创建/停用/角色变更、最后管理员并发保护、登录/会话建立、本人改密、审计写入、真实启动装配、MySQL/PostgreSQL 迁移/隔离级别与重启恢复尚未验收。当前没有把 React UI 接到 Python 本地服务；无浏览器 E2E 证据。矩阵详见 [R-SENTINEL-CONSOLE-B0.3-account-directory.md](../acceptance/R-SENTINEL-CONSOLE-B0.3-account-directory.md)。

### 15.58 F6.4.01 移除应用装配层静态应用 ID（2026-10-08，切片完成）

- **实现：**删除 `src/app/applicationScope.ts` 中 `app-one/app-two/app-three` 静态目录，应用装配不再向路由快照传 demo ID。`RouteSnapshotOptions.applicationScopeIds` 改为可选；通用 resolver 仍支持调用方显式提供权威 catalog，空目录不伪造身份。当前 fleet 路由默认 `app=all`，显式 app query 保持不变。
- **Codex 内置浏览器（仅 IAB）：**隔离本地 demo/mock 下登录后实际渲染 Applications，深链 `#/applications` 保持 `app=all` 并显示全应用三实例矩阵；导航至 `#/applications?app=orders` 保留 `orders`，目录没有该对象时展示明确空状态，不替换为其他应用。未启动/连接 Chrome、Edge 或 CDP；未访问 Python Console、数据库、真实配置中心。
- **验证：**`npm run typecheck`、`format:check`、`lint` 通过；`test:logic` 246/246、`test:architecture` 13/13 通过。完整 `npm run check` 通过：HTTP 89/89、OpenAPI 42 paths（draft-partial，pending=[]）、browser utilities 7/7、visual utilities 7/7、i18n 工具 9/9、build-profile 2/2、Sites 4/4，以及生产/demo build。初次受限执行因临时 loopback listener 返回 `EPERM`；仅授权本地 listener 后，同一完整命令通过。构建保留现有 Zod 注释与约 1.19 MB 初始 chunk 告警。
- **边界：**只关闭 F6.4 的静态 app-scope 注入子切片，不勾完整 F6.4；其余 feature fixtures/mock handler 的统一收口仍未完成。自动 `test:e2e` 因会启动 CDP 浏览器而按用户要求跳过。详细证据见 [R-DASHBOARD-F6.4.01-remove-static-app-scope-seed.md](acceptance/R-DASHBOARD-F6.4.01-remove-static-app-scope-seed.md)。

### 15.59 F6.4.02 总览与实例观测共享演示场景（2026-10-08，切片完成）

- **实现：**新增 app-owned `mockObservationScenario`，集中持有观测场景的环境、应用目录、UTC 窗口、每应用 QPS 与实例 identity。Applications/Fleet feature 提供显式 scenario 注入的 mock-handler factory，不反向 import `app/`。总览聚合 QPS 由 42 + 84 + 63 计算为 189；应用与实例的对应 QPS 相同；未知应用的观测返回 `no_samples`，不再借用 app-one 的 42。
- **自动化：**typecheck、逻辑测试 **247/247**、HTTP **89/89**（含隔离 loopback transport）、架构 **13/13**、format、lint、生产/demo 构建、build-profile **2/2**、Sites worker **4/4** 通过。
- **Codex 内置浏览器（仅 IAB）：**总览显示 189 req/s；`#/applications?env=test-env&app=app-one` 显示两条 app-one 实例且每条 42 req/s。未启动/连接 Chrome、Edge 或 CDP。
- **边界：**F6.4 整项仍未勾；仅集中观测页共用的身份/时间/QPS 数据。规则、身份、故障、系统、实时监控及健康/计划/版本等其它 seed 家族仍待迁入。构建保留已有 Zod PURE 注释和约 1.19 MB 初始 JS chunk 告警；本记录不代表浏览器 E2E 或 Python/live 联调通过。详见 [R-DASHBOARD-F6.4.02-central-observation-scenario.md](acceptance/R-DASHBOARD-F6.4.02-central-observation-scenario.md)。

### 15.60 F6.4.03 实时监控 mock 使用应用级观测场景（2026-10-08，切片完成）

- **实现：**Realtime mock handler factory 显式接收 app-owned `MockObservationScenario`，不从 feature 反向导入 app。应用实时 QPS 与场景目录一致；fleet QPS 从已登记应用求和；未知应用返回 `no_samples` 和 null 观测值/采样时间。重试/合成暂态失败路径不会为未知应用伪造指标。
- **自动化：**`npm run check` 完整通过，覆盖 typecheck、format、lint、逻辑/架构/HTTP、协议合同、工具测试、i18n、生产/demo build、build profiles 与 Sites worker；HTTP **89/89**、logic **247/247**、architecture **13/13**、build profiles **2/2**、Sites **4/4**。构建继续报告已存在的 Zod PURE 注释和约 1.19 MB 初始 JS chunk 告警。
- **Codex 内置浏览器（仅 IAB）：**demo/mock 下打开实时监控 `app-two` 路由，确认所选应用与 `HTTP QPS 84 req/s` 一致。没有调用 Chrome、Edge 或 CDP。
- **边界：**仅关闭 F6.4 的实时 QPS/场景一致性切片，不勾完整 F6.4。其它实时 UI fixture、规则、身份、故障、系统、健康、计划、版本及图表 seed 家族仍待处理；本记录不代表 Python/live 联调或浏览器 E2E 通过。详情见 [R-DASHBOARD-F6.4.03-central-realtime-seed.md](acceptance/R-DASHBOARD-F6.4.03-central-realtime-seed.md)。

### 15.61 F6.4.04 跨页面观测指标与实例事实一致（2026-10-08，切片完成）

- **实现：**app-owned `MockObservationScenario` 扩展为唯一的三应用/四进程演示事实源，QPS 按进程聚合；p95、拦截率、CPU、内存等非加性指标使用明确的合成汇总值。新增纯投影 `metricBundleFromFacts`，缺失的事实保持 unavailable，不再把缺失当 0，也不再把应用级 QPS 冒充为进程值。总览、实时监控和实例矩阵共享值、时间窗、指标级分母/覆盖率及来源元数据；未知应用无样本，未知实例保持 not-found。
- **自动化：**typecheck 与 `git diff --check` 通过；逻辑测试 **247/247**。完整 `npm run check` 通过：HTTP **90/90**、架构 **13/13**、OpenAPI/验证工具、i18n、生产/demo build、build profiles **2/2**、Sites **4/4**。HTTP transport 使用隔离 loopback listener，没有访问外部服务。构建保留已有 Zod PURE 注释和大初始 chunk 警告。
- **Codex 内置浏览器（仅 IAB）：**本地 Mock 页面中，总览和实时监控均显示 fleet **189 req/s、63 ms p95、4% 拦截率、49% CPU、50% 内存**，各项覆盖 **4/4**；应用/实例页显示 4 个进程 QPS **22、20、84、63**，与应用及 fleet 汇总一致。未启动或连接 Chrome、Edge、CDP。
- **边界：**只关闭跨页面观测值/样本覆盖的一致性切片，不勾 F6.4 整项；规则、身份、故障、系统等其它 mock seed 家族仍需收口，且不代表真实 Reporter/Collector、Python Console 或 live E2E 验收。详见 [R-DASHBOARD-F6.4.04-observation-metric-consistency.md](acceptance/R-DASHBOARD-F6.4.04-observation-metric-consistency.md)。

### 15.62 F6.4.05 登录身份与账号目录使用同一 Mock seed（2026-10-08，切片完成）

- **实现：**identity feature 的 `identityMockScenario.ts` 成为本地登录及账号目录的唯一初始身份 seed，统一 account ID、用户名、角色、状态和内置标识。登录与 `/auth/me` 返回账号目录中的 `account-admin/admin` 或 `account-view/viewer`，不再出现无法在账号目录找到的 `mock-admin/mock-viewer`。移除无消费者且字段重复的 `identityFixtures.ts`，更新领域注释；会话授权仍仅按现有 Mock role 处理，密码仍不存入 seed/会话/账号响应。
- **自动化：**HTTP **91/91**（包含身份+账号目录联合 handler 测试、会话恢复、View 角色 403、密码不出现在账号响应）；逻辑 **247/247**；typecheck、lint、architecture **13/13**、build-profile **2/2** 通过；源码扫描无旧 fixture 引用，`git diff --check` 通过。
- **Codex 内置浏览器（仅 IAB）：**Mock 登录管理员后，Shell 会话菜单实际显示 `admin`。未启动或连接 Chrome、Edge、CDP。
- **边界：**仅统一前端 Mock 的身份事实，不代表 Python Console 登录、数据库持久化、真实会话或跨进程验收；F6.4 整项仍未勾。详见 [R-DASHBOARD-F6.4.05-identity-seed-consistency.md](acceptance/R-DASHBOARD-F6.4.05-identity-seed-consistency.md)。

### 15.63 F6.4.06 故障事件引用中央应用/实例/进程身份（2026-10-08，切片完成）

- **实现：**故障 Mock handler 通过应用装配显式接收 `MOCK_OBSERVATION_SCENARIO`；事件按中央应用目录生成，实例与 `processEpoch` 从同一实例 seed 读取，未知环境不再落入默认演示数据。中央场景实例显式持有进程代次，实例观察与故障详情复用同一值。
- **自动化：**`npm run test:http` **92/92**；`npm run test:logic` **247/247**；typecheck、lint、format、architecture **13/13**、demo build 均通过。HTTP 测试验证 36 条事件的应用/实例/代次引用，和未知环境空结果。
- **Codex 内置浏览器（仅 IAB）：**登录本地 Mock 后故障分析显示全范围 36 条、3 个应用；打开首条事件展示 `app-one / instance-1 / incarnation-1` 及两项观测证据。没有调用 Chrome、Edge 或 CDP。
- **边界：**仅关闭故障事件 seed 一致性切片，不勾完整 F6.4；其它 feature fixture 与静态健康/计划/版本数据仍待盘点。本轮未运行自动浏览器 E2E、Python Console、数据库或真实配置中心。详见 [R-DASHBOARD-F6.4.06-incident-seed-consistency.md](acceptance/R-DASHBOARD-F6.4.06-incident-seed-consistency.md)。

### 15.64 F6.4.07 规则作者与发布实例回执引用中央 seed（2026-10-08，切片完成）

- **实现：**规则 Mock handler 改为场景注入工厂，绑定受中央 environment/application 目录约束；基线/新版本作者指向内置 `account-admin`；发布回执只针对对应 app 的真实合成实例，引用其 `processEpoch`，expected 与应用实例目录计数一致，inventory source 来自共享场景。每个工厂有隔离可重置状态。
- **自动化：**HTTP **92/92**；typecheck、lint、format、logic、architecture **13/13**、demo build 通过。覆盖未知环境、版本作者、实例/epoch、回执统计/来源与已有草稿/版本/计划命令路径。构建保留已知约 1.19 MB 初始 JS chunk 告警。
- **Codex 内置浏览器（仅 IAB）：**规则页发布记录 `publication-event-flow-01` 指向 `version-event-flow`；加载后展示 **1/2 已生效、1 待加载** 与 `instance-1/incarnation-1`、`instance-2/incarnation-2`。未调用 Chrome、Edge 或 CDP。
- **边界：**只关闭规则 Mock 的身份/回执 seed 切片，不勾完整 F6.4；规则编辑旧 fixtures 和系统健康/摘要/计划/版本等其它 seed 仍待检查。本轮未跑自动浏览器 E2E 或真实 Python/DB/config-center 联调。详见 [R-DASHBOARD-F6.4.07-rule-seed-consistency.md](acceptance/R-DASHBOARD-F6.4.07-rule-seed-consistency.md)。

### 15.65 F6.4.08 系统配置源 seed 归属与 handler 状态隔离（2026-10-08，切片完成）

- **实现：**新增 app-owned `mockSystemScenario` 承载系统配置源身份及审计上下文；内置管理员从 identity canonical seed 注入。系统健康 `sourceId` 与可变配置源 registry 使用同一 seed；来源登记和系统观测 handlers 改为显式工厂，可注入时钟，registry/operation/revision 状态只属于对应 factory，提供局部 reset。
- **验证：**`npm run typecheck`、`npm run lint`、`npm run format:check`、`npm run test:logic` **247/247**、`npm run test:architecture` **13/13**、`npm run test:http` **93/93**、`npm run build:demo` 均通过。HTTP 测试验证 source ID 对齐、审计 actor 对齐管理员身份、固定时间与 reset 后回到原始 seed。Demo build 的既存初始 JS chunk 约 **1.19 MB** 告警保留。
- **Codex 内置浏览器（仅 IAB）：**系统管理页实际显示连接探测 `nacos-primary · Nacos`，且来源目录同样显示 `nacos-primary / Primary Nacos`。未启动/连接 Chrome、Edge 或 CDP。
- **边界：**只完成 F6.4 的系统来源身份与 handler 状态隔离子切片，不勾完整 F6.4。健康/协议的其余静态 seed、规则计划/版本和编辑器旧 fixtures、其它 feature seed 尚待盘点。未运行自动浏览器 E2E，未连接 Python Console、数据库或真实配置中心。详见 [R-DASHBOARD-F6.4.08-system-seed-ownership.md](acceptance/R-DASHBOARD-F6.4.08-system-seed-ownership.md)。

### 15.66 F6.4.09 系统健康、协议与审计 mock seeds 归属（2026-10-08，切片完成）

- **实现：**app-owned `mockSystemScenario` 现在承载配置源身份、连接/协议/审计 seed、中央环境/应用/绑定/发布关联 ID 和相对时间偏移；identity canonical admin 通过装配注入。系统观测 feature handler 只投影时间、筛选/分页、校验 schema 并返回 HTTP；注入 clock 与工厂隔离状态保留。改密审计 target 改用 `account-admin`，不再残留幽灵 `admin-1`。另修正 build-profile 测试仍断言旧 `mock-admin/mock-viewer` 的漂移，改为当前 canonical ID。
- **验证：**完整 `npm run check` 通过：typecheck、format、lint、logic **247/247**、architecture **13/13**、HTTP **93/93**、协议/i18n/浏览器工具/视觉/i18n 工具/verification 工具、production/demo build、build-profile **2/2**、Sites **4/4**。i18n 工具记录 1147 keys/locale、732 个可静态解析调用和 115 个动态调用；后者不构成静态完整性证明。保留现有 Zod PURE 注释与约 1.19 MB 初始 chunk 告警。
- **Codex 内置浏览器（仅 IAB）：**连接页确认连接探测与来源目录共用 `nacos-primary`；协议页显示 rule-source-v1、agent-reporting-v1、token-v1 独立协商状态；审计页显示 2 条事件，发布关联 `app-one`，发布/改密 actor 为 `account-admin`。未提交表单或变更数据。没有启动/连接 Chrome、Edge、CDP。
- **边界：**只完成系统观测 mock seed 收口，不勾完整 F6.4。没有运行自动 E2E，没有请求 Python Console、MySQL、Nacos、Consul 或真实 Collector；mock/IAB/HTTP 证据不能替代真实后端验收。详见 [R-DASHBOARD-F6.4.09-system-observation-seeds.md](acceptance/R-DASHBOARD-F6.4.09-system-observation-seeds.md)。

### 15.67 F6.4.10 规则部署演示 seeds 归属（2026-10-08，切片完成）

- **实现：**新增 app-owned `mockRuleScenario.ts` 统一承载五类 rule bindings/snapshots、baseline/event versions、publications、实例 receipts 与初始 activation plan；应用、环境、实例/进程代次、配置源和管理员身份均引用中央 mock scenarios。时间通过 injected clock + offset 投影。Rules mock factory 只拥有模拟命令的暂态状态、校验、wire 投影与 reset；移除旧规则部署 fixture，并增加显式 `features/rules/mock` public mock entry，保持 app 装配不依赖 feature 私有 model/UI barrel。
- **验证：**完整 `npm run check` 通过：typecheck、format、lint、logic **247/247**、architecture **13/13**、HTTP **93/93**、协议/i18n/浏览器工具/视觉/verification 工具、生产和 demo build、build-profile **2/2**、Sites **4/4**。随后新增 appId 过滤目录断言并再次运行 HTTP suite **93/93**；loopback 用例仅监听本机地址。i18n 静态检查为每 locale **1147 keys**、**732** 个静态可解析调用，另有 **115** 个动态调用不能由静态检查证明；保留已有 Zod PURE 注释和约 **1.19 MB** 初始 JS chunk 告警。
- **Codex 内置浏览器（仅 IAB）：**干净 demo 会话确认目录有 **5** 个 binding；打开 `binding-app-one` 后读取 1 条规则、显示 2 个不可变版本与 `plan-event-flow-01` 待执行计划；读取 `publication-event-flow-01` 回执显示 **1/2 已生效、1 待加载**，并引用 `instance-1/incarnation-1` 与 `instance-2/incarnation-2`。旧 IAB 标签复用旧 Service Worker 时曾出现目录读取错误，干净 IAB 会话复核正常。未启动 Chrome、Edge 或 CDP。
- **边界：**只关闭 F6.4.10 子切片，不勾完整 F6.4。未运行会启动外部 CDP 浏览器的 `npm run test:e2e`；未请求 Python Console、MySQL、Nacos、Consul 或真实 Collector；无真实配置中心写入、持久化或 E2E 验收结论。详见 [R-DASHBOARD-F6.4.10-rule-deployment-seeds.md](acceptance/R-DASHBOARD-F6.4.10-rule-deployment-seeds.md)。

### 15.68 F6.4.11 移除无消费者的旧页面演示 fixtures（2026-10-08，切片完成）

- **实现：**删除无任何运行时/测试引用的总览、实时监控、故障、系统旧整页静态 fixtures；当前页面数据来自 feature HTTP adapters 与显式 MSW scenario。规则 `RULE_FIXTURES` 仍被规则逻辑和编辑器 probe 测试使用，因此保留为测试 fixture，不误删活跃依赖。
- **验证：**完整 `npm run check` 通过：typecheck、format、lint、logic **247/247**、architecture **13/13**、HTTP **93/93**、协议/浏览器工具/视觉/i18n/verification 工具、i18n、生产/demo build、build-profile **2/2**、Sites **4/4**。构建仍有既存 Zod PURE 注释和约 **1.19 MB** 初始 JS chunk 告警。
- **边界：**只退休四份无消费者文件，不勾完整 F6.4；没有启动 Chrome/Edge/CDP，也没有运行外部 CDP 的 `npm run test:e2e`。详见 [R-DASHBOARD-F6.4.11-retire-unused-page-fixtures.md](acceptance/R-DASHBOARD-F6.4.11-retire-unused-page-fixtures.md)。

### 15.69 F6.4.12 身份 Mock 场景归属与 handler 隔离（2026-10-08，切片完成）

- **实现：**账号 seed、合成口令、first-run storage key/failure mode 集中到 app-owned `mockIdentityScenario.ts`；Identity 与 Account Management Mock 通过 feature public entry 显式接收场景，模块级账号/初始化/幂等状态改为 handler factory 实例闭包所有。删除旧 feature scenario 源；测试、规则/系统 mock 引用和 first-run probe 共用新场景。
- **验证：**typecheck、format、lint、Hooks lint、架构 **13/13**、logic、`contract:check`、demo build 通过；HTTP **94/94**，含账号目录初值一致性、敏感口令不泄漏及多 factory 状态隔离。HTTP controlled-loopback 因沙箱 EPERM 首次失败，经批准本机 loopback 后通过。
- **Codex IAB：**内置浏览器 Mock 登录后进入系统管理/账号维护，实际呈现 `admin` 与 `viewer` 目录及管理员操作入口。未调用 Chrome、Edge、CDP，未运行外部 CDP 的自动 E2E。
- **边界：**只完成身份 Mock 场景子切片，不勾完整 F6.4；没有 Python Console、数据库或真实服务验证。详情见 [R-DASHBOARD-F6.4.12-central-identity-mock-scenario.md](acceptance/R-DASHBOARD-F6.4.12-central-identity-mock-scenario.md)。

### 15.70 F6.4.13 隔离规则编辑器的纯测试 fixtures（2026-10-08，切片完成）

- **实现：**将仅供规则逻辑测试与 E2E probe 使用的 `RULE_FIXTURES`、`RULE_VERSION_FIXTURES`、`RULE_APP_FIXTURES` 移到 `tests/fixtures/ruleWorkbenchFixtures.ts`，产品 `src/` 不再承载这份旧编辑器示例数据。app-owned Rules HTTP scenario 保持独立不变。
- **验证：**typecheck、format、lint、架构 **13/13**、logic **247/247**、demo build、源引用扫描、`git diff --check` 通过。没有运行会启动外部 CDP 的 `npm run test:e2e`，未调用 Chrome/Edge/CDP。
- **边界：**只隔离规则编辑器测试数据，不勾完整 F6.4；该切片无 IAB 新页面行为变化。详情见 [R-DASHBOARD-F6.4.13-isolate-rule-editor-test-fixtures.md](acceptance/R-DASHBOARD-F6.4.13-isolate-rule-editor-test-fixtures.md)。

### 15.71 F4.25 账户维护 IAB Mock 冒烟验收（2026-10-08，部分证据）

- Codex 内置浏览器实际验证 Mock 管理员登录、System 内账户维护列表、按账号名筛选、仅账号名/密码/角色的新增 Dialog、成功创建和重名拒绝后保留可修正输入；关闭临时会话后，重新启动回到 canonical 两账号场景。未启动 Chrome/Edge/CDP。
- 补做分页准备时，第二次合成账号创建在 UI 进入“执行结果尚未确认”，一次显式结果查询仍未解除；没有重放写操作，因而没有构造出多页数据。该 Mock 执行结果/只读核查路径需单独排查，不能据此宣称分页已验证。
- `npm run test:logic` **247/247 passed**；`npm run test:http` 首次因 sandbox loopback `EPERM` 为 **93/94**，经批准仅监听 `127.0.0.1` 后 **94/94 passed**。这些验证针对 React 工作流和 HTTP Mock。
- **当时 F4.25 仍不勾：**本次尚未在页面中构造超过一页的账号目录，因此没有 IAB 渲染分页边界证据；自动 `npm run test:e2e` 未运行以遵守用户禁止 Chrome/Edge/CDP 的约束。后续分页闭环见 §15.72。Python Console、真实持久化和 DB 唯一性/并发仍未验证。详情见 [R-DASHBOARD-F4.25-accounts-iab-mock-smoke.md](acceptance/R-DASHBOARD-F4.25-accounts-iab-mock-smoke.md)。

### 15.72 F4.25 账号目录分页 IAB 验收完成（2026-10-08）

- 全新 Mock/IAB 会话通过新增账号 Dialog 创建 19 条合成记录，结合 `admin` / `viewer` 共 21 条；等候界面显示服务端确认及目录总数后才继续，未重放写命令。之前一次过早读取的“结果尚未确认”没有在该完成感知流程中复现。
- 实际点击下一页确认第 1 页 20 条、第 2 页 1 条；第 2 页上一页可用、下一页禁用；返回第 1 页恢复 20 条，上一页禁用、下一页可用。自动化 `npm run test:logic` 当次 **247/247 passed**，`npm run test:http` 当次 **94/94 passed**；后者只绑定 `127.0.0.1` 临时端口。
- 更新后的 F4.25 仅表示前端 Mock 页面切片已验收。没有启动 Chrome/Edge/CDP；临时 IAB tab 已关闭且本地服务已停止。Python Console、真实关系库和 React-to-Python E2E 仍未验收。详见 [R-DASHBOARD-F4.25-accounts-iab-mock-smoke.md](acceptance/R-DASHBOARD-F4.25-accounts-iab-mock-smoke.md)。

### 15.73 F4.26/F4.27 账号状态与角色访问 IAB 冒烟（部分证据）

- 在新的 Mock/IAB 会话中验证内置 admin 的停用按钮禁用；普通 viewer 停用先显示确认 Dialog，取消后仍启用，确认后 Dialog 关闭且列表回读“已停用”。
- 注销遇到结果未知时按页面提供的“检查当前会话”核查，确认后回到登录；`viewer` 登录后系统管理导航入口不存在，直接访问账号维护深链显示“只有当前管理员可以管理账号和角色”。
- 补做双 IAB 标签并发探测：标签 A 停用 `viewer` 后，标签 B 的旧页面仍可提交并显示成功，而非 `conflict`。核对代码发现账号 Mock handler 的账号/版本状态是 factory 闭包内存，且每个页面分别装配 Mock worker，因此不同标签没有共享写入权威；此结果不能代表未来共享 Python Console 的 revision 冲突行为，也不能据此判定真实服务端校验有 bug。跨会话冲突需由共享后端 E2E 或显式共享的测试权威验证，未重放写操作。
- 这只证明 demo Mock 的渲染/前端访问控制，不证明 Python Console 服务端授权、最后 admin 并发保护、真实 revision 冲突或数据库事务。该阶段结束时 F4.26/F4.27 均未勾；F4.27 后续在 §15.74 完成 React + Mock 前端验收，**F4.26 仍未勾**。全过程只使用 Codex IAB，未启动 Chrome/Edge/CDP；临时标签与本地服务关闭。详见 [F4.26 验收记录](acceptance/R-DASHBOARD-F4.26-accounts-status-iab-smoke.md)。

### 15.74 F4.27 无效角色目标与角色选项 IAB 验收

- Codex IAB 本地 Mock 验证 `#/roles?account=does-not-exist` 显示“未找到账号；不会自动选择其他账号”，选择器未回落首个账号；新鲜页面显式选 `viewer` 成功渲染其当前角色与仅 admin/view 两项。viewer 无系统导航、直接进入账号维护拒绝已见 §15.73。完整 `npm run check` 通过：类型/格式/lint、Hooks 6、架构 13、logic 247、HTTP 94、contract、工具/i18n、production/demo build、profile 2、Sites 4；HTTP listener 获准后仅绑定 `127.0.0.1`。构建仍有约 1.19 MB 初始 JS chunk 告警（F5.6 待办）。当前 wire 只有 create/status/role；本人改密走独立 session-bound workflow，没有管理员重置功能。此项完成 React + Mock 前端能力；Mock 不证明 Python Console 权限/持久化，留 B0。未访问 DB/配置中心，只使用 Codex IAB。详情见 [R-DASHBOARD-F4.27-role-target-iab-smoke.md](acceptance/R-DASHBOARD-F4.27-role-target-iab-smoke.md)。

### 15.75 F2.7 工作流、查询资源与页面所有权收口（2026-10-08）

- **实现审查：**Feature 的查询资源、业务写 workflow 与纯规则按职责分开；UI 保留表单/筛选/临时选择等短生命周期 state，不持有第二份服务端快照。账号、规则、配置源和初始化命令在唯一 workflow 中核验回执、更新或失效所属资源；结果未知依旧只允许显式 inspect。
- **回归防护：**新增 `tests/architecture/workflow-ownership.test.mjs`，扫描实际 feature UI 文件，拒绝直接 `fetch`、创建/导入 HTTP adapter 或导入 feature fixture。`npm run test:architecture` **14/14**，逻辑 **247/247**，typecheck、目标 ESLint/Prettier、live/demo build 与 diff whitespace 检查通过。
- **边界：**只关闭 React 前端分层任务 F2.7；不代表 Python API、数据库/配置中心持久化或端到端产品 E2E 已完成。没有启动 Chrome、Edge 或 CDP。验收详情见 [R-DASHBOARD-F2.7-workflow-ownership.md](acceptance/R-DASHBOARD-F2.7-workflow-ownership.md)。

### 15.76 F5.1 国际化资源归属与业务数据边界（2026-10-08）

- **资源治理：**继续使用集中 JSON + i18next；`src/app/i18n/catalog.ts` 明确每个 feature namespace 与唯一资源文件 owner。`tests/i18n/catalog.test.mjs` 校验资源清单、owner/foreign key、三语 key/插值 parity、非字符串/空文案，并通过实际 i18next 实例验证三语复数分支。
- **审计修正：**CJK 审计原先把 app-owned API/mock 场景种子报告成界面漏译。现只将 `src/app/api/` 从“确定是 UI 文案”的 view 扫描排除；页面、共享组件仍照常扫描，feature model/state 仍要求人工判定。封闭领域 code 映射到 i18n，业务自由叙述和环境/规则样例作为内容保留。新增 `tests/i18n/audit.test.mjs` 固定该边界，当前 view/model 命中 **0**。这不是将任意路径全局忽略，也不代表视图运行时无漏译已由静态扫描穷尽。
- **自动化验证：**`npm run test:i18n-tools` **10/10**；`npm run i18n:audit -- --summary` **0 view/model 命中**；`npm run i18n:check` 显示 zh-CN/en-US/ja-JP 各 **1,147** 键、**731** 个可静态解析调用通过，另有 **115** 个动态 `t()` 调用待 F5.2 显式映射/运行校验。
- **Codex 内置浏览器：**在本地 demo HTTP Mock 的 Overview 页面切换简体中文、English、日语；各自确认导航、页面标题、筛选器/统计/图表操作标签随 UI locale 改变。`演示环境` 是后端/mock 返回的业务环境名，保持原值，不被 UI locale 改写。观察 URL 在切换后保持同一 overview route。全程使用 Codex IAB，未启动 Chrome、Edge 或 CDP。
- **完整门禁：**`npm run check` 退出码 **0**，包括 typecheck、Prettier、ESLint/Hooks、architecture **14/14**、logic **247/247**、HTTP **94/94**、contract、browser/visual/i18n/verification 工具、i18n、production/demo build、build profile **2/2** 与 Sites **4/4**。构建保留现有 Zod PURE 注释提示和约 **1.19 MB** 初始 JS chunk 警告；这属于 F5.6，不影响命令成功。
- **边界：**完成 F5.1 的资源归属与“UI 文案 vs 业务内容”治理，不代表 F5.2 动态键/插值/日期数字时区全面验收，也不证明 Python Console、真实 API 或产品级端到端联调。详情见 [R-DASHBOARD-F5.1-i18n-ownership.md](acceptance/R-DASHBOARD-F5.1-i18n-ownership.md)。

### 15.77 F5.2 三语动态键静态审计与规则草稿语言切换（2026-10-08，部分证据）

- **静态解析改进：**`tests/i18n/source-keys.mjs` 可穷尽本地别名、条件/逻辑分支、跨文件导入的有限导出文案映射及枚举计算属性映射；增补对应正例测试。可静态校验的键由 **731** 增至 **917**，当前仍有 **43** 个变量型 `t()` 调用未静态解析，继续逐项映射或补真实运行覆盖，不做 allow-all，也不据此勾 F5.2。
- **Intl 数字回归：**`tests/logic/observation.test.mjs` 增加 `formatMetricReading` 的 `en-US` / `de-DE` 数字差异断言，并确认格式化不改协议数字；现有图表用例继续覆盖 locale 时间标签，计划/时区模型已有 DST 边界用例。仍需核对所有活跃页面完整的日期/时区格式场景。
- **补齐 locale 展示漏洞：**总览应用表 QPS 从硬编码 `zh-CN` 改为接收当前 i18next locale；实例健康状态标签使用 `HealthLevel` 穷尽映射替代未受检查的字符串模板。新增总览数字分组与 CPU 优先/内存次之/阈值相等不触发的状态映射回归用例。
- **日期/实例格式补漏：**实例矩阵 QPS 也改为 active locale；账号最后登录时间按界面 locale 格式化，同时固定 UTC 时区并显式标注 UTC，避免机器时区造成同一审计时刻的歧义。新增 `en-US` / `de-DE` / `ja-JP` 实例 QPS 格式和三语 UTC 时间回归测试。Codex IAB 在应用与实例页实际切换 English、日本語，业务标识保持不翻译，上报时间仍显示 UTC。
- **完整资源运行渲染：**i18n 工具新增真实 i18next 实例对每个 locale 的所有非复数 catalog 键及插值参数渲染检查；既有测试继续覆盖三语复数的 0/1/2 分支。工具套件现 **14/14**。
- **有限动态键真实产生器覆盖：**逻辑测试直接执行实际导航权限过滤、角色 presentation、应用健康和实例健康/资源压力 key producer，再用三语真实 i18next catalog 渲染输出；不复制 producer 的期望键清单。logic 当前 **253/253**，仍有其他调用点待覆盖。
- **内置浏览器草稿验收：**本地 demo 环境选中 `binding-app-one`，开始一份未保存的流控草稿并设置资源为 `POST /api/i18n-check`。依次切换 English、简体中文、日本語，界面文案随语言切换；URL 始终为 `#/rules?env=test-env&app=app-one&range=1h&binding=binding-app-one`，资源值、草稿未保存状态及配置预览保持不变，协议枚举 `grade=1 / strategy=0` 未变。随后丢弃本次临时本地编辑并确认恢复为示例原值；没有保存草稿或发布。
- **内置浏览器总览 locale 验收：**另在 `#/overview?app=all&range=1h` 以 synthetic viewer 切换简体中文、English、日本語再恢复中文；文案/时间展示改变而 URL query 与业务身份不变。demo 的 QPS 小于千位分隔阈值，数值分组差异以 unit test 验证。只使用 Codex 内置浏览器，没有启动 Chrome、Edge 或 CDP。
- **验证：**新增映射覆盖后完整 `npm run check` 退出码 **0**：typecheck/format/lint、architecture **14/14**、logic **253/253**、HTTP **94/94**、contract、工具/i18n、production/demo build、build profile **2/2**、Sites **4/4** 均通过。`i18n:check` 为三语各 **1,147** 键、**917** 静态校验、**43** 动态调用待处理。HTTP live controlled test 仅绑定本机回环地址。内置浏览器仅访问本机 demo；未访问真实配置中心或数据库。
- **边界：**仅记录 F5.2 的资源渲染/复数、部分动态映射、数字格式和语言切换/URL/草稿证据。43 个变量型调用仍需逐类映射或与运行用例关联；活跃页面日期/时区场景和其余草稿页面尚未穷尽，F5.2 保持未勾。详见 [R-DASHBOARD-F5.2-i18n-dynamic-keys-and-locale-switch.md](acceptance/R-DASHBOARD-F5.2-i18n-dynamic-keys-and-locale-switch.md)。

### 15.78 F4.24 登录命令过渡态保留表单 owner（2026-10-08，部分证据）

- **根因与修复：**登录 workflow 在命令执行/已知拒绝收尾期间会依次发布 `authenticating`、`checking`，未知结果则为 `unavailable`。App 原先以全屏反馈替换登录页，导致 `LoginEntryPage` owner 卸载并丢掉其本地账号输入。现在只在登录命令非 idle 且处于这些阶段时保留 public Login route 的原组件；该页面继续负责锁定控件/显示反馈，未放行任何私有页面。增加了 App 登录失败保留用户名的自动化回归用例，但现有文件 E2E 依赖 Chrome/CDP，本轮未运行。
- **Codex 内置浏览器：**仅用 IAB 在本机显式 Mock 模式提交合成未知账号/错误密码。初次旧标签页曾显示通用回退；新鲜 IAB 标签页复测后，日文、英文、简体中文均展示对应的非枚举凭证拒绝文案，用户名保留、密码遮蔽；英文 Enter 提交与密码显隐也可用。旧标签页通用回退的根因仍未确认；手工单次交互不等于完整键盘/无障碍验收。
- **代码验证：**`npm run typecheck`、`npm run lint` 与完整 `npm run check` 通过；完整统计 architecture **14/14**、logic **253/253**、HTTP **94/94**、build profiles **2/2**、Sites **4/4**。首次运行的 HTTP live-controlled 回环监听被 sandbox EPERM 拒绝，使用仅限本机回环测试的授权运行完整门禁后通过。check 内 browser-tools 是 CDP launcher 的单元/策略测试，不是浏览器 E2E。
- **边界：**F4.24 保持未勾。live-only 提示隔离、全量键盘/可访问性覆盖、登录状态重试语义和 Python Console 集成仍未验收。浏览器验证仅用 Codex 内置浏览器；不启动 Chrome、Edge 或 CDP。详见 [R-DASHBOARD-F4.24-login-route-owner-preservation.md](acceptance/R-DASHBOARD-F4.24-login-route-owner-preservation.md)。

### 15.79 F4.23 Mock logout 的空 204 响应确认（2026-10-08，部分证据）

- **根因：**MSW 对 `204 No Content` 返回已关闭的空 `ReadableStream`，而 bounded response 只接受 `response.body === null`。因此合法空流被误判为响应协议错误，transport 把成功 logout 映射为 `console_response_invalid`，身份 workflow 才显示 `result-unknown` 并跳过自动会话回读。
- **修复：**`boundedResponse` 对 204 消费 body stream 并确认其为 0 字节；遇到任何非空 chunk 仍拒绝，同时保留 abort/cancel 处理。HTTP 回归覆盖空 stream 接受和非空 stream 拒绝。
- **验证：**HTTP 套件 **95/95** 通过（包括本机 loopback controlled test）；内置浏览器新的同源本地 Mock 会话中，合成 admin 登录后退出，IAB 日志顺序为 logout **204** → bootstrap **200** → auth/me **200**，页面自动回到 login，不再显示结果未知。此前浏览器调试探针已移除。
- **边界：**这关闭的是本地拦截层的 204 空流处理问题，不代表 F4.23 完成。Python Console 的真实 logout/revocation、session readback、cookie/CSRF、过期和服务端确认仍需真实后端验收；本轮不运行驱动外部浏览器的 E2E 套件，不访问真实配置中心或数据库。

### 15.80 Python Console 当前全量回归复核（2026-10-08，非完成验收）

- 使用 Python **3.12.14** 对当前 `sentinel-console` 源码执行 `python -m unittest discover -s tests -v`，**46/46 passed**；使用已有隔离依赖路径，没有安装依赖或联网。
- 本次证明既有 bootstrap 查询、`/auth/me` 读取、账号目录只读和 SQLite 本地持久化切片未回归；不证明 PostgreSQL/MySQL、多 worker、启动装配或真实浏览器到 Python。
- **B0.2 继续未勾：**Python 当前仍缺登录/注销/会话创建、CSRF/Origin、账号写操作、真实 setup 持久化流程及生产数据库并发验证。完整分层边界见 [B0.2 验收记录](../acceptance/R-SENTINEL-CONSOLE-B0.2-persistence-foundation.md)。

### 15.81 Python Console 注销与会话撤销切片（2026-10-08，B0.2 部分实现）

- `/system/bootstrap` 补齐前端登录前的 CSRF preflight：生成/复用同值的 `x-sentinel-csrf` 与 Secure、HttpOnly、SameSite=Strict `__Host-sentinel_csrf` cookie（Path=/、无 Domain），不在页面模型或持久浏览器存储中暴露。注销写操作再以精确 Origin、单一 header/cookie 双提交与服务端保存的 CSRF digest 三重校验；通过后原子撤销 session 并清除 session 与 CSRF 两个 cookie。
- 新增真实 ASGI `POST /api/v1/auth/logout` 写路径：会话撤销 Port 与只读 session Port 分离；SQLAlchemy adapter 根据会话摘要查找记录，以 constant-time CSRF digest 比对后，通过限定 `session_hash + csrf_hash + expires_at + revoked_at IS NULL` 的更新撤销当前会话。原始 Cookie/CSRF 值不会进入应用 Port 或数据库。
- `build_app` 强制注入 revoker 和非空的浏览器 Origin allowlist。Origin 配置只允许 HTTP(S) origin（不接受路径/查询/片段/凭证）；请求拒绝缺失、重复、不匹配 Origin 或重复 CSRF/Cookie 凭证。无效/过期/撤销会话映射 401，CSRF/Origin 错误 403，authority 故障或非法 Port 结果映射无细节 503。仅撤销确认后返回空 204 并清除 Secure、HttpOnly、SameSite=Lax Cookie。
- **验证：**Python 3.12.14 Console 源码全套 **59/59 passed**，覆盖 CSRF preflight 创建/复用、ASGI 正常及负例、SQLite 真实持久撤销、`/auth/me` 后续匿名回读、到期/错误 CSRF/存储故障；`compileall`、`git diff --check`、新增 Python 文件 88 列检查通过。React 侧 `contract:generate`、typecheck、OpenAPI `contract:check` 与 HTTP 测试 **95/95 passed**（本机 loopback 测试在获准后重跑通过）。只用隔离 SQLite 与本地 ASGI 测试，没有访问真实 DB/配置中心；本切片不需要浏览器运行验证，也未调用 Chrome/Edge。
- **B0.2/F4.23 仍不勾：**尚缺 Python 登录与 session 创建/nonce 轮换、完整真实启动组合和前端接入；PostgreSQL/MySQL、多 worker、部署与浏览器到 Python E2E 未验收。注销 API 的 ASGI 测试不是端到端产品验收。详见 [B0.2 验收记录](../acceptance/R-SENTINEL-CONSOLE-B0.2-persistence-foundation.md)。

### 15.82 Python Console 登录与 session 创建测试设计（2026-10-08，历史记录）

本节保留实现前的测试设计快照。登录/session 创建现已实现；当前源码验证与剩余边界见 §15.138 及 [B0.2 验收记录](../acceptance/R-SENTINEL-CONSOLE-B0.2-persistence-foundation.md)。

- 对齐既有 `/api/v1/auth/login` OpenAPI 与前端 identity contract，明确后续验收要覆盖：CSRF/Origin 先验拒绝、账号名规范化、非枚举凭证拒绝、密码不泄漏、账号限流、session/CSRF nonce 同步轮换、SQLite 持久化及 `/auth/me` 回读、存储故障安全拒绝，以及未知写结果不重放。
- 测试设计已写入 [B0.2 验收记录](../acceptance/R-SENTINEL-CONSOLE-B0.2-persistence-foundation.md)。实施边界拟新增 SQLAlchemy 认证 Adapter，将数据库凭证查询/Argon2 校验适配为应用层有限结果；OOP 技能门禁已向用户请求确认该 Adapter 方案，确认前不写该实现。
- **React 完整工程门禁：**当前源码 `npm run check` 退出码 **0**：typecheck、format、lint、Hooks **6/6**、架构 **14/14**、logic、HTTP **95/95**、OpenAPI **42 paths / draft-partial / pending=[]**、browser/visual/i18n/verification 工具、生产/demo builds、build-profile **2/2**、Sites **4/4** 均通过。i18n 静态检查仍报告 **43** 个动态 `t()` 调用无法静态解析；生产与 demo 首屏 JS 分别 **1,189,752 B / 1,193,497 B**，仍高于 500 KB 警告线，F5.2/F5.6 不勾。这个门禁不执行 Chrome/CDP 浏览器 E2E；本轮页面检查只使用 Codex 内置浏览器。
- **仍不勾 B0.2/F4.23：**尚无 Python `/auth/login`、session 创建与 nonce 轮换实现；反向代理信任和多 worker 下登录限流策略也须在实现/验收中明确。该测试设计和前端工程门禁不是实现或真实端到端验收证据。

### 15.83 F5.6 首屏国际化目录按需加载（2026-10-08，部分完成）

- **实现：**`app/i18n/messageCatalogs.ts` 为每个 locale 显式声明 9 个 JSON namespace 的动态导入；`i18n/config.ts` 通过 i18next backend 在初始化/切换时加载所需语言，memoize 成功 catalog，加载失败则清除失败 Promise 供重试。`main.tsx` 等待首个 locale 初始化后再 render，避免首帧显示翻译 key。用户切换语言成功后才保存本机偏好；资源 chunk 失败时保留原 locale 并显示可翻译的重试提示。三语 parity 仍由读取源 JSON 的 CI 测试完整校验。
- **自动化证据：**新增 `I18N-RUNTIME-LAZY` 集成测试，使用 Vite SSR module runner 执行真实 i18next backend：启动只注册当前 zh-CN、依次切换 en-US / ja-JP 后才加载相应 catalog，测试 **6/6 passed**。类型、ESLint、Prettier、国际化检查通过；i18n 静态工具 **15/15**。完整生产构建 manifest 初始 JS 从 §15.82 的 **1,189,752 B** 降至 **944,459 B**（少 **245,293 B，约 20.6%**）；manifest-linked 初始资源 **1,162,464 B / gzip 313,920 B**，38 个延迟入口。该结果是文件级构建测量，不代表真实网络传输时延。
- **完整工程门禁复核：**获准绑定本机 loopback 后，当前源码完整 `npm run check` 退出码 **0**；生产构建、demo 构建、build-profile **2/2** 与 Sites **4/4** 均完成。此次新构建入口 JS **948,204 B**、manifest-linked 初始资源 **1,166,209 B / gzip 315,032 B**，与前一次独立测量略有变化，但仍显著高于 500 KB 警戒线。该命令不包含驱动外部浏览器的 E2E。
- **Codex 内置浏览器：**只在 IAB 打开本机 demo 页面，实际看到 setup 初始页面正常渲染为中文；当前全新隔离 tab 停在初始化页，未提交初始化，也未改认证/数据库/配置中心状态。三语按需切换由上面的真实 i18next runtime 测试覆盖；没有启动 Chrome、Edge 或 CDP。
- **边界：**此切片只关闭 locale JSON 不再全量进入首屏的问题；Astryx 官方语言资源、i18next/ICU、Zod 和 React runtime 仍使首屏 JS **944,459 B**，仍超过 500 KB 警戒线。图表/规则编辑器 chunk、首屏/交互性能测量及全页面容量核查仍属于 F5.6，F5.6 不勾。F5.2 的 43 个动态 `t()` 调用和页面完整 IAB 三语矩阵也尚未穷尽。未访问真实 Python Console、数据库或配置中心。

### 15.84 F5.6.01 延迟加载 Astryx 非活动语言目录（2026-10-08，自动化完成、浏览器语言切换未验）

- **依赖证据：**Vite/Rollup entry 模块报告发现 `AstryxProvider` 的静态 zh-CN、ja-JP 导入把两份官方 ICU JSON 带入首屏。改为按语言动态导入；main bootstrap 等待当前 locale 目录，统一 `changeLocale()` 先 await Astryx 目录再切 i18next，只有整个切换成功才持久化偏好。失败 Promise 被驱逐，允许再次加载。
- **自动化：**ASTRYX-I18N-LAZY 使用真实 Vite SSR module runner 核对当前目录、en-US 的 Astryx 内置回落、zh-CN→ja-JP 切换前资源加载和失败后重试；BUILD-I18N-LAZY 对 production manifest 静态闭包/动态可达性做断言。TypeScript、i18n 工具 **16/16**、Prettier、ESLint、build profile **3/3** 通过。
- **内置浏览器：**IAB 重载本机 `#/setup` 页面，实际确认中文 setup 页面正常显示。此初始化页没有 locale selector；不提交初始化的前提下，无法从该隔离页面完成 locale picker 的手动验收。无 Chrome / Edge / CDP。浏览器语言切换留待可授权登录/初始化的页面流程中验收。
- **完整工程门禁：**当前源码 `npm run check` 退出码 **0**：typecheck、format、lint、Hooks **6/6**、架构 **14/14**、logic **253/253**、HTTP **95/95**、OpenAPI **42 paths / draft-partial / pending=[]**、浏览器工具策略 **7/7**、视觉工具 **7/7**、i18n 工具 **16/16**、verification **5/5**、build profile **3/3** 与 Sites **4/4** 通过。三语各 **1,148** 键，**918** 静态校验，另有 **43** 动态 `t()` 调用仍待 F5.2。
- **包体变化：**production entry JS **830,593 B**，初始 manifest closure **1,048,598 B / gzip 285,825 B**；较 §15.83 entry JS 减少 **113,866 B（约 12.1%）**。这不是网络时延证明；单个 entry 仍超 500 KB 警戒线，F5.6 保持未勾。完整记录见 [F5.6.01 验收记录](acceptance/R-DASHBOARD-F5.6.01-astryx-locale-lazy-load.md)。
- **边界：**自动化和内置浏览器启动渲染有证据，但此轮未完成 IAB 内 locale picker 可视切换、其它图表/编辑器分包、列表容量或交互性能测量；不得勾 F5.6。未访问 Python Console、真实数据库或配置中心。

### 15.85 F5.2 有限 map / iteration 动态键审计（2026-10-08，部分完成）

- **静态提取器：**`tests/i18n/source-keys.mjs` 新增有限字面数组/对象展示字段在 `map()` 中的解析，以及有限字符串列表在 `map()` / `for...of` 中的 key 追踪；跨文件只读取显式翻译字段，不把业务 `id` / 自由值视为文案。计算属性、缺失字段和非字面值仍失败关闭并报告。
- **测试：**新增本地及导入 map、字符串列表、有限/非有限输入测试；`npm run test:i18n-tools` **21/21**，`npm run test:logic` **253/253**。静态审计从 **918** 个键 / **43** 个未解析调用推进到 **941** 个键 / **22** 个未解析调用；三语各 **1,148** 键。
- **工程门禁：**最终完整 `npm run check` **exit 0**：Hooks **6/6**、architecture **14/14**、logic **253/253**、HTTP **95/95**、browser/visual/i18n/verification 工具、build profile **3/3**、Sites **4/4** 均通过。此命令不运行 browser E2E。entry JS **834,343 B**、manifest 初始资源 **1,052,348 B / gzip 286,924 B**，F5.6 仍未达标。
- **内置浏览器约束：**只用 Codex IAB 打开本地 setup 页，确认初始化页文案及字段正常渲染；页面无语言切换器，未提交初始化，故该操作不计入 F5.2 三语/草稿矩阵。未启动 Chrome、Edge 或 CDP；未访问真实 Console、数据库或配置中心。
- **边界：**F5.2 不勾选。仍有 22 个动态调用待逐类静态映射或真实 key producer runtime 覆盖；活跃页面日期/时区与其他草稿/URL 语言切换尚未穷尽。详情见 [F5.2 验收记录](acceptance/R-DASHBOARD-F5.2-i18n-dynamic-keys-and-locale-switch.md)。

### 15.86 F5.2 身份与规则文案 producer 运行时关联（2026-10-08，部分完成）

- **新增自动化：**`I18N-DYNAMIC-IDENTITY` 用真实 Vite SSR 模块执行账号/密码/初始化校验及 setup/role presentation producers，并在 zh-CN / en-US / ja-JP 的真实 i18next 实例中验证实际输出；`I18N-DYNAMIC-RULE-COPY` 执行真实 `useRuleCopy()` Hook，递归检查三语规则工作台文案没有裸 key 或未解析插值。
- **验证：**i18n 工具 **23/23**、logic **253/253**、`i18n:check` 通过；静态提取 **941** 个键，仍有 **22** 个调用无法静态解析。当前完整 `npm run check` **exit 0**，包括 production/demo build、build profile **3/3** 与 Sites **4/4**。生产 entry JS **834,343 B**，初始 manifest closure **1,052,348 B / gzip 286,924 B**，F5.6 仍未达标。
- **边界：**新增 runtime 覆盖关闭了一部分 identity/setup/role/rule dynamic producers，不代表 22 个调用已全部关联。活跃页面三语日期/时区、持草稿页与 URL 状态切换的 IAB 矩阵仍未穷尽；此轮为模块级自动化，没有执行浏览器验收。浏览器限用 Codex IAB，未启动 Chrome、Edge、CDP；未访问真实 Console、数据库或配置中心。F5.2 保持未完成。详见 [F5.2 验收记录](acceptance/R-DASHBOARD-F5.2-i18n-dynamic-keys-and-locale-switch.md)。

### 15.87 F5.2 有限解构映射与记录字段投影（2026-10-08，部分完成）

- **实现：**i18n AST 审计支持有限 map 对象解构字段和有限本地记录的固定字段投影，补上规则工作台规则类型/字段文案映射与内联 map 标签等被真实数据流证明为有限的键；动态数组源、计算字段和未知值仍 fail closed。
- **验证：**`npm run test:i18n-tools` **26/26**；新增有限 map 解构、本地 record lookup 正例，以及动态 map / 计算字段反例。`npm run i18n:check` 通过：静态键 **1,015**，未解析动态调用由 **22** 降至 **17**；三语目录各 **1,148** 键。完整 `npm run check` **exit 0**；构建 entry **834,343 B**、初始资源 **1,052,348 B / gzip 286,924 B**，F5.6 仍未达标。
- **边界：**尚余 17 个动态调用，主要是函数输出与 UI prop 数据流，需由安全静态映射或真实 producer/runtime 测试逐项闭合；页面级 IAB 三语/日期/时区/草稿 URL 验收矩阵也未穷尽，F5.2 保持未完成。本轮未启动任何外部浏览器/CDP，亦未访问真实后端依赖。详见 [F5.2 验收记录](acceptance/R-DASHBOARD-F5.2-i18n-dynamic-keys-and-locale-switch.md)。

### 15.88 F5.2 导航、实例健康与身份反馈动态文案覆盖（2026-10-08，部分完成）

- **实现：**新增 `I18N-DYNAMIC-PRESENTATION`，在 Vite SSR 中执行真实导航、实例状态、账号命令反馈、登录状态反馈 producer，覆盖两种导航权限、实例健康/资源压力和身份流程拒绝/等待/未知/成功状态；producer 实际生成的所有键都由三种 locale 的 i18next 逐一渲染校验。
- **验证：**新增测试后 `npm run test:i18n-tools` **27/27**；完整 `npm run check` **exit 0**，HTTP **95/95**、架构 **14/14**、Hooks **6/6**、verification **5/5**、build profiles **3/3**、Sites **4/4** 均过。静态审计仍为 **1,015** 键 / **17** 个未解析调用；production entry **834,343 B**、manifest 初始资源 **1,052,348 B / gzip 286,924 B**，F5.6 未完成。
- **边界：**运行测试关闭了多个动态 producer 的语言资源映射风险，但不自动消除 17 个静态解析报告；`RuleCatalogPanel.detailLabel` 尚无源码调用方，需决定退休无消费者组件还是为新消费者验证。F5.2 仍未完成：页面级 locale picker、日期/时区、草稿与 URL 保持矩阵尚未完整 IAB 验收。本轮未启动 Chrome/Edge/CDP，亦未访问真实 Console、数据库或配置中心。详见 [F5.2 验收记录](acceptance/R-DASHBOARD-F5.2-i18n-dynamic-keys-and-locale-switch.md)。

### 15.89 F5.2 删除 RuleCatalogPanel 固定文案的动态 prop（2026-10-08，部分完成）

- **实现依据：**源码全局引用检索确认 `RuleCatalogPanel` 没有消费者，`detailLabel` 仅在该组件的 props 与 JSX 内出现；该文案实际只有 `rules.catalogDetail` 这一种固定语言键。删除 `detailLabel` props，组件直接翻译固定 key，避免通过 props 将静态文案键变成任意动态字符串。
- **验证：**`npm run test:i18n-tools` **27/27**、`npm run i18n:check`、typecheck、lint、`git diff --check` 通过；完整 `npm run check` 在修改后 **exit 0**，HTTP **95/95**、logic **253/253**、build profiles **3/3**、Sites **4/4** 通过。静态键 **1,016**，未解析调用降至 **16**。entry JS **830,593 B**、初始资源 **1,048,598 B / gzip 285,825 B**，F5.6 仍未达标。
- **边界：**无页面呈现变化；F5.2 仍需逐项处理 16 个动态 producer/callsite，并在 Codex IAB 完成页面语言切换、日期时区与草稿 URL 保留验收。本轮没有启动 Chrome/Edge/CDP，也未访问真实 Console/DB/配置中心。详见 [F5.2 验收记录](acceptance/R-DASHBOARD-F5.2-i18n-dynamic-keys-and-locale-switch.md)。

### 15.90 F5.2 Codex 内置浏览器规则草稿语言切换验证（2026-10-08，部分完成）

- **验证：**仅在 Codex IAB 的本机 Vite demo 中选择 `binding-app-one`，编辑未保存的流控草稿并临时改资源名；切换 English / 日本語 后，规则页文案变化，而 hash URL、应用/绑定筛选、资源名、未保存标记、配置 JSON 与 wire 数值保持。切回简体中文后确认丢弃测试编辑，恢复原始示例内容。
- **边界：**未调用 Chrome、Edge、CDP；页面是 Mock/demo，不证明 Python 服务端或真实配置源联调。本轮没有代码变化，也未重跑门禁。只关闭规则草稿 locale 场景；其他持草稿页、日期/时区矩阵与 16 个动态调用仍未穷尽，F5.2 不勾。详情见 [F5.2 验收记录](acceptance/R-DASHBOARD-F5.2-i18n-dynamic-keys-and-locale-switch.md)。

### 15.91 F4.11 双标签与路由往返实时轮询复核（2026-10-08，当前未复现）

- **IAB 观察：**在两个 Codex 内置浏览器标签中同时打开实时监控，单/双标签及“总览 → 实时监控”路由往返后的约 30 秒观察期内，`读取时间` 持续前进，页头保持定时读取；两页均显示有效 Mock 指标与明确的 TPS 缺测，没有进入 stale/error。
- **回归：**`npm run test:logic` **253/253 passed**（含 monitor poll/stale/owner/timeout）；`npm run i18n:check` 通过（三语各 **1,148** 键，静态解析 **1,016**，剩余动态调用 **16**）；`git diff --check` 通过。本轮未重跑全门禁。
- **边界：**这次不能复现历史 stale 症状，但未查明过去的触发原因，也不覆盖长时间运行、断网/限流、浏览器休眠或 Python/生产采集路径。没有代码改动、没有运行 Chrome/Edge/CDP；F4.11 保持未勾，详见 [F4.11 验收记录](acceptance/R-DASHBOARD-F4.11.md)。

### 15.92 F5.2 Codex 内置浏览器语言与路由复核（2026-10-08，部分完成）

- **IAB 验证：**没有启动 Chrome、Edge 或 CDP。已存在 IAB 标签的实时路由显示“页面暂时无法显示”；新建 IAB 标签后总览、实时监控及应用页可加载。实时监控切换到 English 后文案变更，导航至规则/应用再返回仍保持 English；切回简体中文后恢复中文，`#/realtime?app=all&range=1h` 查询上下文保留。旧标签失败与新标签成功的原因未知；不视作浏览器或应用故障已修复。页面均标明 Mock/demo，未访问 Python Console、真实数据库或配置中心。
- **发现与边界：**English 应用页的环境选择项显示 `演示环境`，源码确认这是 Mock API 的环境实体 `name`，不是界面静态标签；实体名称按当前约定不随 UI locale 翻译。规则页本次未完成规则数据区加载验收，日期/DST 和其他持草稿页面矩阵仍未穷尽。F5.2 仍未完成。
- **检查：**`npm run i18n:check` 通过，三语各 **1,148** 键、静态键 **1,016**，仍有 **16** 个动态 `t()` 调用未静态解析；本轮未修改代码、未重跑完整门禁。详见 [F5.2 验收记录](acceptance/R-DASHBOARD-F5.2-i18n-dynamic-keys-and-locale-switch.md)。

### 15.93 当前前端完整工程门禁复跑（2026-10-08）

- **验证：**默认沙箱第一次运行 `npm run check` 时，typecheck、format、lint、Hooks、架构、logic 和 HTTP 中 **94/95** 项通过；剩余唯一失败是受控 HTTP 测试监听 `127.0.0.1` 时被沙箱拒绝（`listen EPERM`）。获准仅对本机 loopback 测试提升权限后，完整 `npm run check` **exit 0**。其中 HTTP **95/95**、logic **253/253**、Hooks **6/6**、架构 **14/14**、verification **5/5**、build-profile **3/3**、Sites **4/4**；production 与 demo 构建均成功。
- **边界：**该命令的 `test:browser-tools` 是测试工具策略/制品单测，不启动 E2E 浏览器。未运行 `npm run test:e2e`；页面证据仅来自 Codex IAB。`i18n:check` 仍为三语各 **1,148** 键、静态 **1,016** 键、**16** 个动态调用未静态解析；F5.2/F5.6 和 Python Console 真实集成都未因此关闭。没有访问真实 Console、数据库、Nacos 或 Consul。

### 15.94 F4.11 实时轮询 stale 在新 IAB 标签再次复现（2026-10-08）

- **IAB 观察：**新建 Codex IAB 标签直接打开实时监控，初始成功显示 `test-env` Mock 指标（QPS 189、p95 63 ms、拦截率 4%、CPU 49%、内存 50%；TPS 明确 unavailable）。约 20 秒后进入 stale，提示读取失败且沿用上次成功数据；再观察约 12 秒，读取时间仍冻结在 `2026/10/8 06:45:14–07:45:14 UTC`。通过键盘 Tab + Return 激活“重试读取”后状态变为“正在刷新”，约 14 秒后重新 stale、读取时间未推进。与此同时，另一新 IAB 标签成功轮询约 27 秒；后续第三个新 IAB 标签也成功轮询约 30 秒，二者读取时间推进且未 stale。说明是间歇性，不支持归因于特定组件，也不代表持续稳定。
- **证据边界：**地址栏直开 metrics API 得到 SPA fallback，不是 API JSON 证据。根因仍未知，可能因素尚未被逐一验证。本轮只使用 Codex IAB，无 Chrome、Edge、CDP，也没有访问真实 Python Console/数据库/配置中心；未运行 E2E 自动化。
- **状态：**这是对先前短时未复现结果的补充，不推翻其当时观察；它证明 stale 能在新标签复现，但不能证明触发条件或真实生产链路。F4.11 继续未勾。详见 [F4.11 验收记录](acceptance/R-DASHBOARD-F4.11.md)。

### 15.95 F4.28/F4.29 角色绑定深链与本地草稿 IAB 验收（2026-10-08，部分完成）

- **实现/观察：**F4.28 账号 URL target 被选择器与详情共同使用；F4.29 角色 Radio 先变本地草稿，Save/Discard 明确可用，未直接持久化。切账号出现确认对话框；丢弃本地变化、离开再打开时恢复 Mock 已保存角色。无效账号深链明确不回退。IAB 在同标签执行 reload 后仍见本地草稿，随后 Discard 回到已保存角色；该行为与新标签/路由卸载重入不同，暂列为 IAB 刷新生命周期不一致，不作业务根因结论。
- **验证：**`npm run test:logic` **253/253 passed**，覆盖显式目标与空目录路由解析、角色联合和基线草稿政策；IAB 只对现有两个 active mock 账号做只读/本地草稿交互，没有发角色保存命令。
- **边界/状态：**未构造 disabled/空目录场景；保存成功、冲突、pending/unknown、真正硬刷新以及目标账号会话失效影响未完成。无真实 Python/API/DB 验收；没有启动 Chrome、Edge、CDP。F4.28/F4.29 继续未勾，详见 [R-DASHBOARD-F4.28/F4.29](acceptance/R-DASHBOARD-F4.28-F4.29-role-binding-iab.md)。

### 15.96 F4.23 后续 IAB 注销复核与此前成功记录矛盾（2026-10-08）

- **IAB 观察：**在长期存在的 `127.0.0.1` 管理员 Mock session 页面两次显式点击“退出登录”，均出现“退出登录未完成 / 退出请求未能确认完成”；点击“检查当前会话”后仍显示相同提示。随后新建 IAB 标签打开 `#/login` 被重定向至 overview；原标签整页重载后也回到已认证 `admin` 的 overview。另在隔离的 `localhost` fresh origin 用 viewer 和 admin 各完成一次登录→注销，均回到带站内 returnTo 的 login。由对照可提出旧会话 lifecycle 候选，但无法区分 stale CSRF、请求未发送、MSW 未命中或其他来源；没有自动重发、不修改 localStorage、不构造权限变更。
- **隔离 HTTP 对照：**dashboard `npm run test:http` 普通沙箱运行 **94/95**，唯一失败为受控 loopback test server `listen EPERM`；按项目测试需要只对本机 `127.0.0.1` listener 提升权限复跑，**95/95 passed**。其中 `IDENTITY-HTTP` 和 `HTTP-204` 证明隔离 HTTP adapter 可完成 login/read/logout/read 及空 204 解析，不覆盖 IAB 页面/MSW Service Worker 装配。页面运行与隔离测试结论冲突，不能用单测绿色覆盖浏览器失败。
- **状态/边界：**对比新鲜会话成功与旧管理员会话失败后，根因仍未定位，需浏览器网络层请求/响应证据和可控旧会话恢复/失效场景。F4.23 继续未勾。只使用 Codex IAB，无 Chrome、Edge、CDP；未访问 Python Console、数据库或真实身份服务。

### 15.97 F4.30 查看者只读与管理深链拒绝 IAB 验收（2026-10-08，部分完成）

- **IAB 验证：**为避免接触另一个 origin 中管理员 Mock 状态，在 `localhost:4173` 新建隔离 Mock session，通过 UI 登录 viewer。总览仅显示 metrics 主导航；直接访问 `/accounts` 与 `/roles?account=account-view` 均为明确的 admin 拒绝页，无账号表/角色编辑器。打开 `binding-app-one` 规则集后，规则快照/版本可读，草稿区显示当前会话不能编辑，活动计划创建按钮 disabled；未写规则或更改账号。
- **自动化旁证：**同一工作周期此前 `npm run test:logic` **253/253**；本轮 `npm run test:http` 在隔离 loopback listener 获准后 **95/95**。证明本地领域权限策略和 HTTP contracts，不证明运行 Python server 权限。
- **状态/边界：**F4.30 保持未勾：尚未验收内置/最后 admin 保护的 UI 保存结果、保存失败/冲突保留草稿及目标会话失效跨页状态。仅使用 Codex IAB；未调用 Chrome、Edge、CDP，未连接真实后端/数据库/配置中心。详见 [R-DASHBOARD-F4.30](acceptance/R-DASHBOARD-F4.30-viewer-iab.md)。

### 15.98 F7.1 规则草稿 IAB 未知回执与 HTTP 工作流级对照（2026-10-08，未完成）

- **IAB 事实：**在 `127.0.0.1:4173` 管理员 Mock 规则页面，阈值本地改为 `2100` 后预览正确；点击保存后进入“尚不能确认操作结果”，按原身份检查仍未知并锁定。本轮只读复核仍见相同锁定状态；没有重放未知写请求。另一个隔离 `sentinel.localhost` fresh-origin 对一次合成 admin 登录报通用失败。不同 origin / session 表现不一致，但当前没有证据确定根因。
- **自动化对照：**在 `tests/http/ruleSetMock.test.mjs` 新增工作流级用例，真实串接 `createRuleDraftWorkflow + createRuleOperation + ConsoleTransport + MSW handlers + HTTP adapter`。修改候选阈值为 `2300` 后，mock 回执为 `completed`，字段值与 saved revision 均被 workflow 接受，dirty 清除。`npm run test:http` 本轮 **94/95**；唯一失败为 sandbox 禁止 `HTTP-LIVE-CONTROLLED` 在 `127.0.0.1` 启动 listener（`EPERM`），新增及其他 94 项通过。本轮未提升权限重跑。
- **解释边界：**隔离 Node/MSW 集成通过，只排除领域工作流/同一 HTTP adapter 契约中的明显回归；不能证明正在运行的浏览器 demo 页面或 MSW Service Worker 装配正常。IAB 写入处于未知状态，按幂等安全规则禁止重放。详见 [F7.1 规则草稿 IAB 记录](acceptance/R-DASHBOARD-F7.1-rule-draft-iab.md)。
- **浏览器约束与范围：**只使用 Codex 内置浏览器检查；没有启动 Chrome、Edge、CDP，也没有运行会驱动外部浏览器的 `npm run test:e2e`。没有访问 Python Console、数据库、Nacos、Consul 或生产服务。F7.1 继续未勾。

### 15.99 F7.1 干净 IAB 会话规则发布回执复验（2026-10-08，部分完成）

- **用户浏览器约束：**后续页面/E2E 验收统一只用 Codex 内置浏览器 IAB；不调用 Chrome、Edge 或 CDP。本轮只在 IAB 新 tab 操作，没有使用外部浏览器自动化。
- **新会话实际页面：**新建干净 IAB tab 后，规则页完整走过阈值修改 `2105` → 保存（`draft-revision-2`，dirty 清除）→ 兼容性校验 → 固化版本 `version-3` → 发布 → 读取实例回执。兼容性校验、配置中心写入和回读均显示确认成功；实例回执如实显示 `0/2` 已生效、2 个待加载，来源 `synthetic-inventory`，实例/epoch 为 `instance-1/incarnation-1` 和 `instance-2/incarnation-2`，未伪造载入版本。新发布候选此前漏建 pending receipts 的 Mock 缺口已在 `ruleSetMockHandlers.ts` 修复，HTTP 回归覆盖了目标应用完整实例范围与不伪造字段。
- **旧操作仍未知：**前一 IAB tab 中的保存操作依然是 unknown/locked；没有重放，也没有声称其结果已解决。干净会话的成功说明新流程可用，但未证明旧 tab 与新 tab 差异根因，也不覆盖真实服务。
- **工程门禁：**`npm run test:http` 在沙箱内受控 loopback listener 因 `EPERM` 失败一次；明确限于本机 `127.0.0.1` 的权限运行后 **95/95 passed**。完整 `npm run check` 随后 **exit 0**；格式、类型、lint、架构、逻辑、HTTP、契约、browser-tool/visual/i18n 工具、生产/demo 构建、build-profile 和 Sites 检查均通过。构建保留大于 500 kB chunk 的提示。`npm run check` 未启动 E2E 浏览器。
- **边界/状态：**F7.1 仍不勾：setup、login、overview、应用与实例、实时监控、故障分析、系统管理、账号/角色、改密、注销的整条 IAB 流程尚未全部验收；旧 unknown 仍未解决。所有页面证据仅针对本地 demo/mock，不代表 Python Console、数据库或真实配置中心验收。详见 [F7.1 规则草稿 IAB 记录](acceptance/R-DASHBOARD-F7.1-rule-draft-iab.md)。

### 15.100 仅使用 Codex IAB 的 dashboard 页面验收续测（2026-10-08）

- **浏览器边界：**按用户要求，所有人工页面操作都通过 Codex 内置浏览器 IAB 完成；未启动/调用 Chrome、Edge 或 CDP。`npm run check` 的 browser-tools 是本地策略单测，不启动浏览器。
- **干净标签通过：**在 fresh IAB 标签中，总览显示应用指标、缺测覆盖、图表数据与配置连接事实；应用与实例显示 `app-one` 的两个实例/epoch 与指标；实时监控显示六类指标、缺测数据和轮询控制，展开 QPS 明细展示采样点；故障分析显示 12 条事件，选中压力事件后读取到匹配 instance/epoch、发生/接收/读取时间及观测事实；系统管理连接页、权限页、协议页和审计页均能显示 Mock 事实。账户维护在另一个 fresh IAB 标签显示 admin/viewer 两行账号；角色绑定可选择 admin/viewer，并显示当前角色。角色仅切换查看目标，没有保存或修改账号权限。
- **标签级不稳定仍在：**先前的长生命周期标签切换到 overview/applications/realtime 时读数失败且手工重试未恢复；相同本机 origin 的新 IAB 标签随即能成功读取这些页面。另一个测试标签的账户列表也曾失败；再建 fresh 标签直接打开同一系统页则成功，角色目录亦能读到两账号。没有足够网络/服务端证据定位根因，不能将其归结为缓存、Service Worker 或业务代码问题；F4.11 的实时 stale 风险和此处标签差异继续开放。
- **只读与安全边界：**未提交账号创建、账号状态或角色变更；改密页只读确认当前密码/新密码/确认新密码三字段可见，未输入或保存任何密码，也未触发注销；没有写真实配置中心。直接访问 `#/setup` 在已初始化状态被路由重定向到 overview，未触碰初始化数据。页面均明确为演示数据。账户/角色路由具备只读展示证据，但完整 auth/写入工作流未验；真正更改密码属于凭证操作，必须由用户本人接手完成。
- **状态：**页面级 fresh-tab 冒烟扩大覆盖，不等同 F7.1 全链路 E2E；setup/login/改密/注销及部分失败与恢复场景仍未完成，F7.1 不勾。也不代表 Python Console、关系数据库或真实 Nacos/Consul 验收。

### 15.101 Python Console 当前回归基线（2026-10-08）

- **验证：**使用已有隔离 Python 3.12 环境运行 `python -m unittest discover -s tests -v`，当前 Console 测试 **59/59 passed**，覆盖 bootstrap、session read/revoke、账号目录、SQLite migration 与密码/密文工具。
- **边界：**该基线不覆盖尚未实现的 `/auth/login`、session 创建/CSRF nonce 轮换、生产启动装配、PostgreSQL/MySQL 或浏览器到 Python E2E；测试仅用合成 authority 与隔离 SQLite，没有访问真实数据库/配置中心，也没有启动 Chrome、Edge、CDP。
- **后续门槛：**登录切片所需的 SQLAlchemy credential persistence Adapter 方案仍需按 §15.82 的 OOP 设计确认门槛处理；本次只复跑测试，未新增生产实现或迁移。

### 15.102 IAB 本地服务恢复核验（2026-10-08）

- **观察：**现存 Codex IAB 标签最初显示“页面暂时无法显示”。沙箱内对 `127.0.0.1:4173` 的探测受 loopback 隔离影响；获准的只读 HEAD 请求返回 HTTP **200**，重复启动 Vite 则确认该端口已经占用。没有结束或替换现有进程。
- **IAB 复核：**对原标签执行一次显式 reload 后，总览恢复显示 Mock 页面和完整指标/应用表；约 25 秒后再次检查，页面仍可读，没有显式错误状态。读取时间在这段观察期间未变化，但总览静态时间窗口本身不能证明后台轮询故障；因此不将其归因于代码或宣称长时稳定性。
- **范围：**本轮只通过 Codex 内置浏览器操作；未调用 Chrome、Edge、CDP，也未运行 browser E2E。未访问真实 Console、数据库或配置中心。若后续需要长时轮询结论，应在明确会自动刷新的实时页面按其公开刷新语义单独验收。

### 15.103 F6.9 未匹配 Console Mock API fail-closed HTTP 回归（2026-10-08，局部完成）

- **风险与测试：**未知 `/api/v1` operation 不得落到 live 网络、泄露无效 request ID，也不得吞掉静态资源。新增 `unmatchedConsoleApi.test.mjs`，与现有 transport HTTP runner 一起执行真实 MSW Node handlers。
- **缺陷与修复：**回归先证明未知子路径被正确拦截，但裸 `/api/v1` 被原正则漏掉，导致 DNS 直连/`ENOTFOUND`，违背 fail-closed。终止处理器 matcher 已收敛为匹配 API 根路径或其 `/` 子路径，不捕获 `/api/v1ish`、静态资源之外的路径。
- **结果：**未知 PATCH 子路径与 API 根路径都返回 `503 dependency_unavailable`；响应严格匹配 `ConsoleErrorSchema`，合法 request ID 保留，格式错误但可传输的值使用固定安全 ID且不反射原值。静态资源经 MSW `onUnhandledRequest: bypass` 到受控 `127.0.0.1` HTTP server，而这两类未知 API 均未抵达该 server。三项新增用例全部通过。
- **验证：**`npm run test:http` 普通沙箱结果为 **97/98**，唯一失败是既有受控 loopback live-transport 用例遭 `listen EPERM`；获准仅绑定本机回环地址后重跑为 **98/98 passed**。新增测试文件 `prettier --check` 通过，`git diff --check` 通过。
- **统一门禁：**matcher 修复后完整 `npm run check` **exit 0**，含 typecheck、lint/format、logic、HTTP、contract、工具测试、production/demo build、build-profile **3/3** 与 Sites **4/4**。该命令没有驱动浏览器；`i18n:check` 仍有 **16** 个动态调用无法静态解析，production entry JS **830,593 B**、demo entry **834,343 B** 均超过 500 kB 警戒线，分别保留在 F5.2/F5.6。
- **边界：**只改统一 Mock terminal handler 的 URL matcher；API wire 和 live route 不变。F6.9 其它 status/error、timeout/断网/迟到/畸形响应组合及确定性时钟矩阵仍未闭合。测试只触及隔离 MSW 与本机临时 HTTP endpoint；未访问外部服务、Python Console、真实 DB/配置中心，也未启动/调用 Chrome、Edge 或 CDP。

### 15.104 F4.11 新鲜 IAB 实时读取短时复验（2026-10-08，未关闭）

- **操作与观察：**原 IAB 标签在本轮自动续接后已不属于当前浏览器会话；新开 Codex IAB 标签直接进入 `#/realtime?app=all&range=1h`。页面以显式 Mock 身份显示“正在定时读取”、样本覆盖与缺测状态；两次相隔约 10 秒和 18 秒的可访问树检查中，读取时间均向前推进且无 stale/error。渲染截图确认页面处于实时监控而非空壳/错误 fallback。
- **工具边界：**一次等待 30 秒的单次 UI 操作超过内置浏览器工具执行时限，随后重新绑定 IAB 已恢复；这不是页面失败证据。继续的分段观察总计约一分钟，没有切换 Chrome/Edge/CDP、没有重试写命令、没有更改过滤条件或 Mock 数据。
- **结论：**新鲜 IAB session 的短时周期读取正常，但无法解释此前同 origin 旧标签 stale/失败，也没有跨长时运行、路由往返与浏览器后台/前台恢复证据。F4.11 继续不勾，不据短时 mock 观察宣称问题修复或服务端稳定。

### 15.105 F4.11 按用户要求仅用 Codex IAB 续测（2026-10-08，stale 再现）

- **工具约束：**用户明确要求不再调用 Chrome；本轮只通过 Codex 内置浏览器打开已有 `127.0.0.1:4173` 标签检查页面，未启动/调用 Chrome、Edge、CDP，也未运行 `npm run test:e2e`。
- **页面证据：**实时监控页最初显示“正在定时读取”，但同时标出“刷新失败，以下是上次成功读取的数据，并非最新状态”。窗口标题为 `2026/10/8 08:23:58–09:23:58 UTC`，读取时间冻结在 `09:23:58`；指标为上一成功样本（QPS 189、p95 63 ms、拦截率 4%、CPU 49%、内存 50%，TPS unavailable）。IAB 可访问节点映射当时失效，无法确认“重试读取”点击是否成功，因此不把它计作已发起的重试。
- **恢复观察：**对同一实时页执行显式 reload 后，页面在 `09:29:34 UTC` 回到部分数据（TPS 缺测）而非 stale；约 10 秒、15 秒、30 秒后的读取时间分别推进至 `09:29:54`、`09:30:19`、`09:31:09 UTC`，共观察约 55 秒，没有再次 stale。随后在相同 IAB 页面点击“暂停刷新”，约 10 秒后依然为暂停状态且读取时间保持 `09:32:34 UTC`；点击“恢复并读取最新窗口”后立即回到定时读取，窗口/读取时间更新至 `09:33:04 UTC`。这验证当前合成页面的暂停/恢复 UI 语义，不证明原间歇故障已消失。
- **诊断边界：**已证实 IAB 曾真实显示 stale，reload 后短时恢复；但页面没有暴露具体传输错误，本轮未取得浏览器网络/console 错误，因此不能推断是 MSW、请求 URL、轮询 owner 或浏览器会话中的哪一层。源码中 mock metrics handler 对 `metrics/query` 有明确成功响应，单测也覆盖服务恢复，但这些均不能解释/排除当前浏览器状态。后续须继续沿受控日志/传输证据定位；不通过刷新/重放未知写命令处理。页面标记为 demo/mock，未访问 Python Console、数据库或真实配置中心。
- **状态：**F4.11 继续不勾。页面 stale 可由 reload 暂时恢复，但间歇故障仍未定位；此观察不代表每个 IAB 标签都失败，也不构成真实后端 E2E。

### 15.106 F6.9 Console 错误码 canonical status 矩阵回归（2026-10-08，局部完成）

- **风险与验证层：**ConsoleTransport 必须只接纳 OpenAPI runtime error registry 声明的错误码与对应 HTTP status；若 status/code 不匹配，应作为无效响应失败关闭。此次为 HTTP adapter contract 测试，复用现有 Node/MSW runner，不调用浏览器。
- **测试：**新增 `HTTP-ERROR-MATRIX`，迭代 `CONSOLE_ERROR_STATUS` 的每个已声明错误码，逐项发起真实 `ConsoleTransport.send` 请求。检查 canonical status/code、对应 AppError kind、同一 correlation ID、稳定通用错误文案、不保留 response body/cause；另外验证 401 只触发一次当前身份失效、其他错误不触发，以及仅 `rate_limited` 会暴露受限 `retryAfterMs`。
- **结果：**`npm run test:http` **99/99 passed，0 fail/skip/cancel**；其中包含已有仅绑定 `127.0.0.1` 的 controlled HTTP transport 测试。随后完整 `npm run check` **exit 0**（typecheck、format、lint、架构/逻辑/HTTP/契约/工具测试、i18n 与 production/demo build、build-profile 3/3、Sites 4/4）。检查不含 `test:e2e`，未启动浏览器、访问 Python Console、数据库、配置中心或外部服务。
- **保留问题：**生产 entry JS **830,593 B**、demo entry **834,343 B**，仍超过 500 kB 构建警戒线，留在 F5.6 继续处理；本次没有通过提高 warning 阈值消除告警。
- **边界：**这是全局协议状态映射的自动化证据，不等于每个 feature 的 UI 错误呈现、断网/恢复故障注入、真实 Python response 兼容或 F6.9 完整失败矩阵；F6.9 继续未勾。

### 15.107 F5.6 移除不需要的 Astryx runtime Theme compiler（2026-10-08，局部完成）

- **决策依据：**source map 的 entry 归属统计发现 Astryx `Theme` runtime provider 会携带完整动态主题生成路径。本应用只用静态构建的 neutral theme CSS，固定深色模式，没有 runtime theme creation/switch，因此 `AstryxProvider` 去掉运行时 `Theme` 与 built theme object import，在 `index.html` 根元素声明 `data-theme="dark"` 和 `data-astryx-theme="neutral"`；locale provider、预构建 CSS 和图表主题 Provider 保留。
- **验证：**完整 `npm run check` exit 0，HTTP **99/99**、Hooks **6/6**、architecture **14/14**、build profile **3/3**、Sites **4/4** 均通过，生产及 demo 构建成功。此命令不运行 E2E 浏览器脚本。仅使用 Codex IAB 检查本机实时监控页完成渲染；页面同时处于既有 Mock stale/last-good 状态，本轮没有传输错误根因证据，不作归因。未调用 Chrome / Edge / CDP。
- **包体：**production entry **756,914 B**，manifest 静态初始闭包 **974,919 B / gzip 265,049 B**；demo entry **760,664 B**，初始闭包 **978,669 B / gzip 266,317 B**。较上一基线各少 **73,679 B**，但 entry 仍超过 500 KB；source-map attribution 估计 production entry 约 **493,944 B** 与 `zod/v4/core/doc.js` 映射关联，需注意这是生成后映射的归属估值而非源码文件尺寸。
- **边界：**真实同步依赖分块、Zod Mini 语义/API 迁移可行性、图表/编辑器加载时序、列表容量和交互性能仍未验收。未提升 chunk warning 阈值；F5.6 保持未勾。详见 [F5.6.02 验收记录](acceptance/R-DASHBOARD-F5.6.02-astryx-theme-runtime.md)。

### 15.108 F6.4.14 集中管理读失败/恢复场景 ID（2026-10-08，局部完成）

- **实现：**总览 forbidden/recovery 与实时监控 recovery/retry 的保留应用 ID 移至 app-owned `MOCK_OBSERVATION_SCENARIO.readScenarios`。feature handlers 只消费注入的 scenario；HTTP 测试从相同 canonical seed 读取 ID，不再依赖 feature handler 私有常量。
- **架构门禁：**`workflow-ownership.test.mjs` 扫描真实源码，要求 feature fixtures 只能经对应 feature 的 `mock.ts` 入口导入，并要求上述场景 ID 只定义于 `app/api/mockObservationScenario.ts`。
- **验证：**typecheck 通过；架构 **15/15**、逻辑 **253/253**、HTTP **99/99** 通过。普通沙箱下两个既有 loopback HTTP 测试会 `listen EPERM`；仅允许绑定本机 `127.0.0.1` 后复跑通过。未运行浏览器 E2E；未使用 Chrome、Edge、CDP，也未访问 Python Console、数据库、Nacos、Consul 或外部服务。
- **边界：**只关闭读失败/恢复场景 ID 的统一归属与导入约束，不勾完整 F6.4；其它 seed 家族仍需盘点。本轮证据不是生产后端或浏览器验收。详见 [F6.4.14 验收记录](acceptance/R-DASHBOARD-F6.4.14-centralize-read-failure-scenario-ids.md)。

### 15.109 F6.4.15 集中故障与总览场景事实（2026-10-08，局部完成）

- **实现：**新增 app-owned `MOCK_INCIDENT_SCENARIO` 集中故障模板、重复事件、证据与规则发布关联；总览配置连接身份/状态/延迟复用 System scenario。修正规则覆盖演示事实：app-one `1/2`，app-two 与 app-three `0/1`，不再把同一覆盖数字套给无规则绑定的应用。
- **验证：**typecheck 通过；架构 **15/15**、逻辑 **253/253**、HTTP **100/100**。Codex IAB 在 `127.0.0.1:5173/#overview` 实际渲染确认以上覆盖状态，以及与 System 相同的 Nacos primary / available / 12 ms 连接事实。全程未调用 Chrome、Edge 或 CDP；未访问 Python Console、真实数据库、Nacos、Consul 或外部服务。
- **边界：**只关闭一组故障/总览场景 seed 一致性切片，不勾完整 F6.4；其它静态健康、规则、实时、版本/计划与剩余演示数据仍需清点。IAB + Mock/HTTP 证据不是真实后端集成或完整 E2E。详见 [F6.4.15 验收记录](acceptance/R-DASHBOARD-F6.4.15-centralize-incident-and-fleet-scenario-facts.md)。

### 15.110 F6.4.16 实例规则加载回执与发布场景一致（2026-10-08，局部完成）

- **实现：**新增 app-owned `MOCK_APPLICATION_SCENARIO` 组合观测库存与规则发布事实。app-one instance-1 的加载回执为新活动版本，instance-2 仍在旧基线并待加载；无规则绑定的 app-two/app-three 不再伪报 `version-one`。总览规则覆盖从同一实例回执推导，feature projection 不再持有版本/回执魔法值。
- **验证：**全量 `npm run check` **exit 0**；其中架构 **15/15**、逻辑 **253/253**、HTTP **100/100**。Codex IAB 实际打开总览和应用详情，分别确认覆盖 **1/2、0/1、0/1**，instance-1 “当前进程已加载”及 instance-2 “等待当前进程加载”。未调用 Chrome、Edge、CDP；未访问 Python Console、真实数据库、Nacos、Consul 或外部服务。详见 [F6.4.16 验收记录](acceptance/R-DASHBOARD-F6.4.16-compose-instance-rule-receipts.md)。
- **边界：**只关闭总览—发布—实例回执的跨页面 seed 一致性；F6.4 仍未勾，完整清单中其它 seed 尚需逐项盘点。本证据是 Mock HTTP 与 IAB 渲染，不是真实后端集成或产品级 E2E。

### 15.111 F6.4.17 集中确定性 demo 曲线场景（2026-10-08，局部完成）

- **实现：**QPS、p95、拦截率、CPU、内存的相对曲线 profile 集中在 app-owned `MOCK_OBSERVATION_SCENARIO`；总览/实时/实例模拟读取按请求窗口与 step 插值投影，不再复制摘要值形成平线或插入无因缺口。每条曲线终点与摘要值一致、UTC 点落在半开窗口内并受 1000 点上限约束；TPS/未知目标继续无值、无点。真实 HTTP 响应映射不变。
- **验证：**完整 `npm run check` **exit 0**，架构 **16/16**、逻辑 **254/254**、HTTP **100/100**、build-profile **3/3**、Sites **4/4**。Codex IAB 实际渲染实时监控页并查看图表，QPS、p95、拦截率、CPU、内存均为 **60/60** 点；目视确认 QPS、p95、CPU、内存曲线非平线。未调用 Chrome、Edge、CDP；自动 `test:e2e` 未运行；未访问 Python Console、数据库、配置中心或外部 Collector。详见 [F6.4.17 验收记录](acceptance/R-DASHBOARD-F6.4.17-centralize-demo-series-profiles.md)。
- **边界：**仅完成 demo 曲线 seeds 的归属与投影；F6.4 整项仍未勾，其他静态 scenario 仍需盘点。Mock/IAB 证据不代表真实 Reporter/Collector 历史数据、Python 联调或完整产品 E2E。构建既有 >500 kB chunk 警告保留，未调整门槛。

### 15.112 Python Console 登录与 session 创建本地切片（2026-10-08，部分实现）

- **实现：**新增可显式装配的 `/api/v1/auth/login` 路由、登录用例、SQLAlchemy 凭证读取与事务化 session 写入；执行精确 Origin + 双提交 CSRF 校验、密码枚举统一拒绝、严格有界 JSON 解析（重复 key / 非法 Unicode 拒绝）、限流 authority 失败关闭、opaque session/CSRF token 轮换，仅保存 token digest，并更新 last-login。轮换只撤销同一账号的旧 session。登录路由要求部署注入 32-byte HMAC key 对限流身份作 keyed digest，不隐式信任 forwarded header。成功后通过 `/auth/me` 验证会话身份回读。
- **验证：**Python 3.12.14 Console unittest **68/68 passed**；其中登录专项 **9/9**；`compileall`、`git diff --check` 与新增生产 Python 源码 88 列检查通过。使用隔离依赖路径与 in-memory SQLite；未安装依赖或联网。
- **边界：**限流仅由测试 Port double 提供，生产 multi-worker limiter、trusted-proxy client identity、Console startup/CLI、PostgreSQL/MySQL 锁与事务、初始化/账号写命令、审计及 React-to-Python E2E 均未验收。按用户要求只使用 Codex IAB 检查现有演示总览页；该页明确为 Mock 数据，不是 Python API 联调。未调用 Chrome、Edge 或 CDP。B0.2、F7.1 保持未勾。详见 [B0.2 验收记录](acceptance/R-SENTINEL-CONSOLE-B0.2-persistence-foundation.md)。

### 15.113 前端完整工程门禁与 IAB 登录入口复查（2026-10-08，部分验证）

- **门禁：**在 `components/sentinel/dashboard-prototype` 执行 `npm run check`，普通沙箱首次因两项受控 `127.0.0.1` listener 用例出现 `listen EPERM` 而止于 HTTP 组；仅允许本机 loopback 后以同一完整命令复跑，最终 exit **0**。覆盖 typecheck、Prettier、ESLint、Hooks/架构/逻辑/HTTP、OpenAPI contract、浏览器工具单测、视觉/i18n/验证工具、生产与 demo 构建、build-profile、Sites。该门禁没有运行驱动式浏览器 E2E。
- **产物现状：**生产入口 JS **756,914 B**，manifest 初始资产 **974,919 B / gzip 265,049 B**；demo 初始 JS **760,664 B**，manifest 初始资产 **978,669 B / gzip 266,321 B**。构建仍有 >500 KB chunk 警告；i18n 静态审计仍报 **16** 个动态 `t()` 调用未静态解析，虽资源 parity 与运行时本地化测试通过，F5.2/F5.6 仍不关闭。
- **IAB：**本机 Vite 服务 `127.0.0.1:5184` 总览渲染出完整 Mock 指标/图表/应用表；同一 origin 新标签访问 login 因已认证状态重定向回 overview。切到隔离的 `localhost:5184` origin 后，登录页实际显示登录名、密码、密码显隐和登录按钮。页面横幅声明示例数据；此处仅证明 IAB 渲染，未提交表单或触及 Python Console。
- **边界：**只使用 Codex IAB；未启动/调用 Chrome、Edge 或 CDP，未运行自动 E2E。当前门禁通过不代表 React→Python→数据库的真实路径。F7.1、F7.2 及 B0.2 等集成目标仍未关闭。

### 15.114 按用户要求仅使用 Codex IAB 进行页面冒烟（2026-10-08，部分验证）

- **浏览器约束：**全程只操作 Codex 内置浏览器当前的本机 Vite demo 标签；没有启动或调用 Chrome、Edge 或 CDP，也没有运行会驱动外部浏览器的 `npm run test:e2e`。
- **页面证据：**IAB 实际渲染总览、应用与实例、规则集绑定目录/规则工作台、实时监控、故障分析、系统管理、账号维护与角色绑定页面。规则页在初始“选择…”时仅显示环境选择入口，显式选择“演示环境”后绑定目录和五类规则绑定可见；打开 `binding-app-one` 后可见权威快照、草稿、不可变版本、发布回执与活动计划区。实时页展示 60/60 个样本且 TPS 明确为未接入。账号新增 Dialog 显示账号名、密码、角色三项；关闭前未提交创建命令。角色绑定选择 viewer 后显示当前查看者角色，未触发保存。
- **安全/环境边界：**所有页面顶部明确标记为示例数据；未提交身份、规则、配置源或角色写命令，未触及 Python Console、数据库、Nacos、Consul 或生产服务。该轮属于本机 Mock 页面冒烟，不是 React→Python 或持久化端到端验收。
- **状态：**没有因路由可见性关闭任何完整 E2E milestone；F4、F5、F6、F7 与 B0.2 的既有未完成项仍按各自验收条件处理。自动化 `npm run check` 的最近结果记录于 §15.113，本轮没有重跑。

### 15.115 F4.11 前台可见 IAB 实时轮询复测（2026-10-08，短时成功但未收口）

- 新建可见 Codex IAB 标签直接打开本机实时页；Mock 曲线均为 60/60 点，TPS 明确 unavailable。约 30 秒后读取时间从 `12:11:38 UTC` 推进至 `12:12:18 UTC`，仍为“正在定时读取”，未观察到 stale/error。
- 这只是一次前台短时成功，与既有新标签 stale 复现并存；不解释偶发原因，也不代表长期稳定、后台节流恢复或真实服务采集。F4.11/F4.12 保持未勾。详见 [R-DASHBOARD-F4.11](acceptance/R-DASHBOARD-F4.11.md)。
- 仅使用 Codex IAB；没有调用 Chrome、Edge 或 CDP，没有访问 Python Console、数据库、Nacos、Consul 或外部 Collector。

### 15.116 F4.11 不可见与可见 IAB 标签并行结果不同（2026-10-08，根因仍待确认）

- 同一时间窗口检查两个本地 Mock 实时标签：创建为 `visible:false` 的标签 95 停在 `12:10:56 UTC` 且 stale；`visible:true` 的标签 96 继续前进至 `12:13:08 UTC` 且保持定时读取。两者都显示同一 `test-env` 汇总查询。
- 这将浏览器标签可见性/后台节流列为优先调查假设，但尚无 `document.visibilityState`、请求/worker 日志或单变量隐藏—前台恢复实验，不能确认为根因或据此修改轮询语义。详见 [R-DASHBOARD-F4.11](acceptance/R-DASHBOARD-F4.11.md)。
- 仅使用 Codex IAB；未调用 Chrome、Edge、CDP，也未触及 Python Console、数据库、Nacos、Consul 或外部 Collector。F4.11/F4.12 仍未关闭。

### 15.117 F4.11 后台创建标签后续恢复轮询（2026-10-08，修正 15.116 结论）

- 对标签 95 继续等待约 30 秒后，读取时间从先前冻结的 `12:10:56 UTC` 推进至 `12:16:16 UTC`，stale 提示消失，Mock 样本恢复有效。可见标签 96 同时推进至 `12:16:23 UTC`，保持定时读取。故“创建为不可见的标签持续 stale”并未成立；后台/不可见与当时 stale 仍是相关性观察，不是稳定复现。
- 该复测没有对同一标签做受控的显式隐藏/前台切换，也没有请求/worker/可见性状态日志，不能判断恢复是轮询自恢复、计时器延迟还是标签可见状态改变所致。撤回“后台标签在并行观察期间仍 stale”的持续性表述；保留 15.116 的时点快照与本次后续恢复证据。
- 全程只使用 Codex IAB，未调用 Chrome、Edge、CDP；仅访问本机 Mock demo，未触及 Python Console、数据库、Nacos、Consul 或外部 Collector。F4.11/F4.12 继续未勾，stale 根因与长时稳定性仍未验收。

### 15.118 当前工作树完整前端门禁与 Mock 登录到总览（2026-10-08，部分验收）

- **完整门禁：**当前工作区 `components/sentinel/dashboard-prototype` 的 `npm run check` 最终 **exit 0**。覆盖 typecheck、格式、ESLint/Hooks、架构、logic、HTTP、OpenAPI contract、浏览器工具/视觉/i18n/verification、生产与 demo build、build-profile、Sites。普通沙箱首次有两项受控 loopback HTTP 测试因 `listen EPERM` 失败；只放行测试绑定本机 `127.0.0.1` 后完整命令通过。门禁不包含 `npm run test:e2e`，不会启动 Chrome。
- **IAB Mock 流程：**新建 Codex 内置浏览器 `localhost:5184` 标签直接访问 `#/setup`，按当前 Mock bootstrap 状态重定向到 `#/login`；使用测试专用的内置 admin 合成凭证登录后，到达 `#/overview?app=all&range=1h`。总览呈现 3 个应用、关注数 1、HTTP QPS 189、p95 63 ms、TPS unavailable、连接来源 `synthetic-console`，页面显式声明示例数据。没有执行初始化/数据库/配置中心写操作。
- **边界与下一步：**这只闭环了已初始化 Mock 状态下的登录→总览路径，不证明首次未初始化 setup 提交成功；本次可观察到当前新标签的 Mock bootstrap 默认已初始化，且未通过页面或可用 UI 工具改写浏览器存储来伪造首启状态。F7.1 整条 setup→login→诊断→规则→账号/角色→改密/注销流程仍未完成；setup 首启路径、规则写模拟、会话失败/冲突与 Python 后端均继续开放。IAB 是唯一使用的浏览器，未调用 Chrome、Edge、CDP；未连接真实 Console、数据库、Nacos/Consul 或 Collector。
- **构建现状：**production entry JS **756,914 B**，初始 manifest closure **974,919 B / gzip 265,049 B**；demo entry **760,664 B**，closure **978,669 B / gzip 266,321 B**。>500 KB chunk 告警保留，F5.6 不关闭。

### 15.119 F4.20/F4.21 干净 origin 的首启 Mock 页面闭环（2026-10-08，前端部分验收）

- **Mock 场景可选：**`MOCK_IDENTITY_SCENARIO` 增加初始化默认状态；仅 demo Mock handlers 装配读取 `VITE_CONSOLE_MOCK_BOOTSTRAP_PROFILE=first-run`，默认仍为 `initialized`。缺少 localStorage 状态时按 profile 读取；显式存储的当前状态仍优先。新增 HTTP workflow 回归覆盖首次读取为 locked、通过 authorization HTTP 后获得 setup grant、授权与 session principal 分离。`.env.example` 说明该 profile 只返回合成结果，不连接真实服务。
- **IAB 页面流程：**在干净 `localhost:5185` origin 中，`#/setup` 显示一次性授权门禁；输入合成授权码后进入初始化向导。SQLite 本地开发选项连接检查显示“连接可达”；创建合成首个 admin 后，Nacos 使用合成域名/namespace 且选择“不启用认证”，规则源 Mock 检查显示“连接可达”。确认摘要并提交后，路由进入 `#/login`。Login 无 setup 链接；再导航到 `#/setup` 后仍落到 login。只读打开同 origin `/api/v1/auth/me` 得到 `null`，初始化不创建登录会话。
- **隔离与安全：**首次授权码、管理员口令、host/source 均为合成测试值，只发往本机 demo 的 MSW 拦截层；本地 handler 会接受格式有效的测试授权码并只记录初始化标记，不保存数据库/配置源/管理员口令或初始化完整 body。没有访问 Python Console、真实数据库、Nacos、Consul 或 Collector；也没有读写浏览器存储来伪造初始状态。
- **验证：**新增首启授权 HTTP workflow 回归通过；完整 `npm run check` 在只允许现有受控测试绑定本机 `127.0.0.1` 后 **exit 0**，覆盖 typecheck、format、lint、Hooks/architecture/logic/HTTP、contract、browser-tool/visual/i18n/verification、i18n、live/demo build、build-profile、Sites。格式/类型与 Mock HTTP 新场景均通过；构建仍有既有 >500 kB chunk 警告和 Zod 注释提示。`npm run check` 不运行浏览器 E2E。
- **状态与更正：**本节补齐并替代 §15.118 关于“尚未证明首次 setup 提交成功”的结论；§15.118 当时的 initialized 登录流程记录保留为历史。F4.21 仍未勾：页面只证明前端 + 本地 Mock 路径；服务端 bootstrap 授权、原子初始化/并发锁、数据库迁移与凭证保存、配置源注册、重启持久化都还没有真实 Python Console 验收。F4.20 也仍未勾，因失败恢复、凭证切换后清理、组件卸载后的敏感内存清理尚未逐项验收。

### 15.120 F7.1 IAB 只读与管理员 Mock 页面补验（2026-10-08，部分验收）

- **浏览器约束：**仅使用 Codex 内置浏览器和本机 `127.0.0.1:5186` demo；未调用 Chrome、Edge、CDP，也未运行 `npm run test:e2e`。Vite 首次启动因沙箱不允许 loopback listener 失败；限定本机回环地址授权后启动成功。页面所有 API 请求由 demo MSW handler 拦截。
- **页面与权限结果：**实际浏览总览、应用与实例、实时监控、故障分析和规则目录；实时页呈现 60/60 曲线点，TPS 显示未接入。查看者直达 `#/accounts` 显示“只有当前管理员可以管理账号和角色”。经本机 Mock 登录页使用仓库声明的合成 `admin / synthetic-password` 登录后，导航出现系统管理，系统页读取配置源/连接状态等演示事实。
- **账号路径：**管理员打开系统管理账户维护页，新增 Dialog 字段为账号名、密码、角色；提交 `e2e-operator` 合成账号后列表读回 3 个账号，角色为查看者。Mock handler 对密码仅计算进程内 keyed digest，不复制进账号/操作状态；请求被本机 MSW 拦截，不到 Python 服务。角色绑定页可列出并定位该账号；本轮未保存角色变更、未扩大权限。
- **未覆盖/不夸大：**没有完成角色写入/冲突/最后管理员保护、账号停用失败恢复、规则草稿/版本/发布、改密/注销在同一全新全链路中的组合验收；没有 Python Console、数据库、Nacos、Consul 或生产服务参与。浏览器页面通过不等于协议/持久化 E2E，F7.1 继续不勾，F7.2 与 B0 继续开放。

### 15.121 F5.2 JSON 派生的动态翻译键类型门禁（2026-10-08，部分完成）

- **实现：**英文 JSON bundle 类型注册为 i18next `CustomTypeOptions.resources`，并启用 `strictKeyChecks`。shared translation API 通过 `ParseKeys<"translation">` 推导 `TranslationKey`，避免 shared 反向导入 app。展示映射/动态 producer 中的无限制 `string` 收窄为资源键联合，不改写 native `t()` 调用。typecheck 纳入无效 key 的负向 probe，证明不存在的 key 会被 TypeScript 拒绝。
- **验证：**`npm run typecheck`、`npm run format:check`、`npm run lint` 通过；`npm run test:architecture` **16/16**；`npm run test:i18n-tools` **27/27**；`npm run i18n:check` 显示三语各 **1,148** 键、AST 静态可校验 **1,016** 键，另有 **17** 个变量调用 AST 无法枚举。完整 `npm run check` 在获准 loopback 测试监听后 **exit 0**，最终 `git diff --check` 通过。
- **边界：**仅 typecheck 证明动态 key 必须存在于 JSON 字典，不单独证明每个生产器三语运行行为或页面日期/时区。F5.2 仍未勾：17 个调用的 producer/runtime 可审计关联及活跃页面日期/DST/草稿/URL locale 矩阵未闭合。此轮未启动浏览器或 CDP，也没有运行页面 E2E；没有 Python Console、数据库或真实配置中心参与。详见 [F5.2 验收记录](acceptance/R-DASHBOARD-F5.2-i18n-dynamic-keys-and-locale-switch.md)。

### 15.122 F5.2 动态调用点逐项链接三语 producer runtime 测试（2026-10-08，部分完成）

- **实现：**新增 `tests/i18n/dynamic-callsite-coverage.test.mjs`，以 `i18n:check` 实际 AST unresolved 输出为输入，严格比对 17 个 callsite 与命名 runtime 测试 ID 的映射；无映射、多余映射或测试 ID 不存在都会失败。规则发布阶段的三个动态标签抽为 feature presentation 投影，由 RulePublicationPanel 和新 runtime 测试共同调用。
- **验证：**`npm run typecheck` 通过；`npm run test:i18n-tools` **29/29**，含 17 callsite 集合映射、identity/setup、navigation/status/feedback、rule copy、deployment label 四组真实 producer 的三语 runtime 渲染。`i18n:check` 维持三语各 **1,148** 键、静态 **1,016** 键及可见的 **17** 个 unresolved callsites。变更后完整 `npm run check` **exit 0**；最终 `git diff --check` 通过。
- **边界：**动态调用清单与 producer 测试的可审计关联子项已形成自动门禁；F5.2 仍未勾，页面日期/相对时间/DST、其它草稿页三语切换与 URL/协议保持矩阵未验完。本轮未启动浏览器、CDP，也没有运行产品页面 E2E；未访问 Python Console、数据库或真实配置中心。详见 [F5.2 验收记录](acceptance/R-DASHBOARD-F5.2-i18n-dynamic-keys-and-locale-switch.md)。

### 15.123 F5.2 统一观测 UTC 时间本地化（2026-10-08，部分完成）

- **实现：**新增共享 `formatUtcDateTime(epochMs, locale)` 展示函数，将故障时间线/证据、规则版本/草稿/激活计划，以及系统审计/连接/协议/配置源观测的用户可见时间按当前界面语言格式化；时区固定 UTC 并显示 `UTC`。协议 ISO 时间、`<time dateTime>` 机器值、路由查询与排序事实不变。自动逻辑回归覆盖 zh-CN/en-US/ja-JP 的格式差异与 UTC 事实保留。
- **Codex IAB：**本机 demo 故障时间线在日文显示 `2026/10/08 ... UTC`，切到英文显示 `Oct 8, 2026 ... UTC`；查询 URL 的 ISO UTC 时间不变。点击事件后详情观察读取返回刷新失败且无可信数据，不算详情成功验收。未启动/调用 Chrome、Edge 或 CDP；Vite 临时服务已停。临时 IAB 标签关闭被浏览器 URL policy 拒绝，保留在本机连接错误页，没有尝试绕过。
- **验证：**typecheck 与逻辑测试 **255/255** 通过；随后完整 `npm run check` 执行到 Sites 组并通过，包括格式、lint、架构、HTTP、contract、工具/i18n、live/demo build、build-profile、Sites。i18n 仍为三语各 **1,148** 键、静态 **1,016** 键、17 个明确报告的动态调用。该门禁不包含页面 E2E；构建保留既有大 chunk 警告。文档补充后重跑 `git diff --check`。
- **状态：**F5.2 仍未关闭；活跃页面日期/相对时间/DST/草稿/URL 三语矩阵与故障详情观察读取尚未全部完成。没有触及 Python Console、数据库、Nacos/Consul 或真实服务。

### 15.124 F5.2 故障详情读取与三语切换复验（2026-10-08，页面子项通过）

- **复验结果：**在全新 Codex IAB 本机 demo `127.0.0.1:5194` 中，故障列表成功加载；选择 `incident-resource-pressure` 后准确读回两条证据及完整详情。上一轮 `5192` 的详情读取失败未能稳定复现，已更正为一次性失败观察，不作为代码缺陷或持续阻塞。
- **三语 UI 验收：**在同一选中事件/详情上往返简体中文 → 日本語 → English → 简体中文。发生/接收/证据/读取时间均本地化并标 UTC；事件 ID 与详情保持；URL 查询身份和窗口参数未改变，最终恢复中文。只证明该故障页面/选中详情路径，不扩展为所有路由通过。
- **边界：**仅 Codex IAB + 本机 MSW Mock；未调用 Chrome、Edge、CDP，未连接 Python Console、数据库、配置中心或生产服务。Vite 临时服务已停；IAB 关闭标签再次受 Browser Use URL policy 阻止，标签留在服务停止后的连接错误页。
- **状态：**该详情读取与三语稳定性子项已有成功证据；F5.2 和完整 E2E 目标仍开放，其他页面日期/DST/相对时间、草稿/URL 矩阵及后端集成尚未全验收。

### 15.125 F4.11 新鲜 IAB 前台轮询窗口（2026-10-08，短时通过、风险未关闭）

- **页面证据：**本机 `127.0.0.1:5195` 的 Codex IAB 新鲜 demo 会话进入 `#/realtime?env=test-env&app=all&range=1h`，显示 60/60 条 QPS/RT/拦截/CPU/内存样本与有效 Mock 摘要（QPS 189、p95 63 ms、拦截 4%、CPU 49%、内存 50%）；TPS 为 unavailable。多次读取时间从 `13:48:21` 推进至 `13:50:46 UTC`，约 80 秒内未见 stale/error。
- **证据边界：**这是前台短测；此前已有新 IAB 标签 stale 反例。未做网络故障注入、前后台受控切换、长时资源检查或真实 Console 联调，故不能归因或证明稳定性。F4.11/F4.12 继续未勾。
- **约束：**只使用 Codex IAB；未调用 Chrome、Edge、CDP；本地临时 Vite 服务已停止，没有触及 Python Console、数据库或真实配置中心。

### 15.126 分层测试命令与 milestone E2E 节奏（2026-10-08）

- **实现：**新增 `check:fast`（类型、格式、lint、OpenAPI 一致性）与 `check:full`（原完整 `check` 内容）；保留 `npm run check` 为完整回归兼容别名。新增 `test:logic:focused` / `test:http:focused`，通过 Node test name pattern 只执行匹配测试，并在无匹配时拒绝运行；`npm run verify` 默认静态验证，不启动外部浏览器。README 明确日常改动跑 fast + 受影响测试，milestone/合并前跑完整门禁，完整浏览器路径只在 milestone 做。
- **验证：**`npm run check:fast` 通过；`npm run test:logic:focused -- 'MONITOR-FILTERS'` **1/1 passed**；`npm run test:http:focused -- 'METRICS-MONITOR-RECOVERY'` **1/1 passed**；不存在的测试名以退出码 **2** 拒绝（不是空跑绿灯）；新增 runner Prettier 检查通过。没有执行全量 `check:full` 或浏览器 E2E。
- **边界：**本次只建立更快的开发反馈路径，不降低 milestone 全回归标准。未运行会启动 Chrome/CDP 的 E2E；后续完整页面验收只用 Codex IAB，并将页面 E2E 与真实 Python/数据库/配置中心验收分别记录。

### 15.127 总览图表不再展示无数据依据的发布前后差值（2026-10-08）

- **实现：**总览趋势展示移除固定 `14:02` / `24.1K → 17.6K` / `1.8% → 8.6%` 等与当前查询曲线无对应关系的示例时间和差值。趋势标题改为当前筛选窗口；说明要求只有 Console 在同一 scope/window 明确返回发布身份、事件时间与有效前后样本，页面才可展示发布对比。对应设计已写入 `Dashboard页面能力与接口设计.md` §2.2；比较 DTO 与缺样本语义仍属于未冻结的 F6.1。
- **验证：**`npm run check:fast` exit 0（typecheck、Prettier、ESLint、OpenAPI contract）；`npm run i18n:check` 通过，zh-CN/en-US/ja-JP 各 1,145 条消息且键/插值一致；`npm run test:logic:focused -- 'FLEET-(SNAPSHOT|PROJECTION)'` 2/2 passed；`git diff --check` 通过。
- **边界：**本切片处理的是未挂载的旧 `FleetTrendPanel`，正式 `FleetOverviewPage` 当前通过 `MetricCharts` 渲染，故本轮没有声称页面截图/UI E2E 已验收或正式路由视觉发生变化。没有运行全量 `check:full` / E2E；没有访问 Python Console、数据库、Nacos、Consul 或生产服务。F6.1/F6.4 保持未勾。

### 15.128 默认检查改为快速反馈，完整 E2E 限定在 milestone（2026-10-08）

- **命令分层：**`npm run check` 现在映射 `check:fast`，用于日常变更；受影响逻辑/HTTP 用 focused runner。新增 `npm run check:milestone` 映射完整非浏览器 `check:full`，仅在页面/milestone 收口或合并前执行。`npm run verify` 明确执行静态快检，不启动浏览器。
- **E2E 节奏：**完整页面 E2E 仅在 milestone 验收节点执行，并遵循用户要求使用 Codex 内置浏览器；外部 CDP `npm run test:e2e` 不执行。非浏览器的完整自动门禁与页面 E2E 是不同验收证据，互不替代。
- **动机：**上一轮虽已有 `check:fast`，但兼容别名 `npm run check` 仍指向全量回归；调整后常见命令不再意外触发全量逻辑/HTTP/构建测试，完整覆盖仍由显式 milestone 命令保留。

### 15.129 总览发布标记与数值比较协议边界复核（2026-10-08）

- **源码事实：**正式 `FleetSnapshot` 将严格同 query 的 `MetricBundle` 纳入快照；运行时合同核对 context/window/metric set/step/asOf。该 bundle 已包含带口径 metadata 的实际 `MetricSeries.samples` 与 `ObservationAnnotation`；正式 `MetricCharts` 使用它们绘制曲线和事件标记。
- **决策：**当前用户交互只有同时间轴曲线与发布标记，不展示独立的 before/after 数值卡片；无需新增重复的 `releaseComparisons` DTO。页面不得从曲线相关性宣称因果。未来若明确加入数值对比，必须在 F6.1 冻结样本挑选、距离上限、scope/cohort 可比性和缺样本语义之后再定 wire shape。
- **记录：**同步修正《Dashboard 页面能力与接口设计》§2.2 中“FleetSnapshot 缺比较 DTO”的过度断言。该判断只覆盖当前曲线/标记展示，不关闭 F6.1；Console 聚合和真实 metric/annotation 来源仍未实现验收。
- **验证边界：**由现有 strict wire schema、`validMetricBundle` 和正式组件数据流静态核验；本轮不加无消费者 DTO、不改 OpenAPI，也未运行浏览器 E2E/全量门禁。F6.1/F4.11/F4.12 均保持未勾。

### 15.130 实时 monitor stale 与 HTTP 自动恢复用例复核（2026-10-08，组件/HTTP 证据）

- **用例：**`npm run test:logic:focused -- 'MONITOR-(POLL|STALE)'` 验证同 query 短暂失败保留原始可信值和窗口，后续成功替换，而不是追加旧数据；轮询无重叠，pause 会取消 pending read。结果 **2/2 passed**。
- **传输路径：**`npm run test:http:focused -- 'METRICS-MONITOR-RECOVERY|FLEET-HTTP'` 验证同一 monitor 经 `metrics/query` HTTP adapter/MSW 在一次受控 503 后自动恢复，以及 FleetSnapshot 全范围口径/缺失 inventory 保持 partial。结果 **3/3 passed**。
- **结论与边界：**代码合同支持瞬时 stale 后自动恢复，但无法解释不同 IAB session 间歇性 stale 的实际观察；测试使用受控 MSW/Port，不证明页面真实轮询、网络恢复或长时资源回收。F4.11/F4.12 继续未勾，完整 E2E 留待对应 milestone；没有运行完整门禁或外部浏览器。

### 15.131 有效目录应用的 stale → 自动恢复页面验收（2026-10-08）

- **发现：**既有恢复探针 ID 不在 `applications` 目录，选择器无法到达；开发 StrictMode 还会重放初次 effect，可能在页面已稳定展示旧数据前消耗“第二次读取失败”探针。
- **修复：**恢复 probe 绑定有效 `app-two`（QPS 84），retry probe 绑定有效 `app-three`（QPS 63）；将 app-two 一次性 503 后移至第三次 read。HTTP 合同覆盖成功→成功→503→恢复成功，monitor 测试在故障前保存最新成功 bundle 并断言 stale 期间不替换。
- **验证：**`npm run test:http:focused -- 'METRICS-(MOCK|RECOVERY|MONITOR-RECOVERY)'` **3/3 passed**；`npm run test:logic:focused -- 'MONITOR-(POLL|STALE)'` **2/2 passed**；`npm run check`（快速别名）exit 0。Codex IAB 本机 demo 深链 `#/realtime?env=test-env&app=app-two&range=15m` 首先显示 QPS 84、p95 58 ms、拦截率 3%、CPU 43%、内存 49%；随后出现 stale 提示及重试按钮；下一自动 poll 后提示/按钮消失且读取时间前进，所选应用与有效样本仍在。
- **边界：**只运行页面专项 IAB 与 focused/fast checks，不运行 `check:milestone` 或全量浏览器 E2E。Vite/MSW 合成响应不是 Python Console/Collector/Reporter 网络故障证据；未覆盖后台标签、真实迟到响应、撤权或长时资源。F4.11/F4.12 仍开放，历史 stale 的真实根因未证实。

### 15.132 首次初始化 workflow 的连接失败恢复聚焦回归（2026-10-08）

- **实现与合同：**数据库和 Consul fail-once HTTP Mock 用例现经 `InitializationWorkflow` 驱动，不再只直调 HTTP Port。断言包含请求 pending/loading、503 后 error、用户显式重试后 ready/reachable，并确认 database password 与 ACL token 不进入 workflow snapshot；bootstrap 仍未初始化。
- **验证节奏：**workflow/HTTP focused **1/1**、连接检查 logic focused **1/1**、`npm run check:fast` 通过。测试名正则首次过窄导致 runner 明确报告“no tests were run”并退出 2，修正匹配后才实际执行测试。未运行 `check:milestone`、完整 E2E 或浏览器。
- **边界：**这是前端状态所有者 + HTTP 适配器 + MSW 的聚焦证据，不是页面/真实后端 E2E。F4.20/F4.21 继续未勾；全量页面 E2E 仅在 milestone 执行。

### 15.133 F4.11 当前工作区的应用筛选、轮询与 stale 自动恢复（2026-10-08）

- **应用筛选：**Codex IAB 在本机 demo 中从 app-two 切换到 app-three；URL `app` 与选择器均变为 app-three，实时页没有跳转；摘要 QPS 从 **84** 变为 **63 req/s**，p95 从 **58** 变为 **46 ms**。前台观察中读取时间推进 **5 秒**。
- **恢复状态：**新鲜可见 app-two 标签首先显示 QPS **84 req/s**。受控 HTTP mock 在一次轮询返回 503 后，页面 `data-query-state=stale`，显示“刷新失败，以下是上次成功读取的数据，并非最新状态。”与“重试读取”，且仍保留 QPS 84；下一自动轮询约 10 秒后 stale 消失、读取时间前进、QPS 84 保留、重试按钮消失。未点击重试，证明是自动恢复路径。
- **自动检查：**monitor poll/stale logic **2/2**、Metrics mock/recovery/monitor HTTP **3/3**、`npm run check:fast` exit 0。浏览器只使用 Codex IAB；第一次隐藏标签采样未捕获短暂错误，后续改用可见 fresh tab 并检测 DOM `stale` 状态后取得上述证据。
- **结论边界：**F4.11 的前端页面筛选/摘要/轮询行为在本地 demo 已验收；F4.12 仍开放后台节流/迟到/撤权/长时资源与真实网络恢复，Python Console/Reporter/Collector 没有参与。没有运行 milestone E2E、Chrome、Edge、CDP，也没有访问真实 DB/Nacos/Consul。

### 15.134 Python Console 当前源码回归基线复核（2026-10-08）

- **执行：**在 `components/sentinel/sentinel-console` 使用隔离的 Python 3.12.14 环境运行 `PYTHONPATH=src:/private/tmp/sentinel-console-deps.viomBu:/Users/richie696/Projects/workspace/atlas-richie-platform-python/components/sentinel/sentinel/.venv/lib/python3.12/site-packages /private/tmp/sentinel-console-account-identity-env-20261007/bin/python -m unittest discover -s tests -v`，当前源码 **68/68 passed**，耗时约 2.3 秒。覆盖 bootstrap/session/account-directory 读取、登录/注销 ASGI 流程、SQLite 本地持久化、密码与密钥保护等现有切片。
- **结论：**当前本地 Console 实现没有发现单测回归；该结果更新的是验证基线，不关闭 B0.1/B0.2。
- **未验收：**生产启动/CLI、multi-worker 限流与可信代理身份、初始化和账号写命令、PostgreSQL/MySQL 事务/并发、多 worker 部署，以及 React→Python→持久化真实浏览器 E2E 仍未完成。只使用隔离 SQLite/ASGI 测试依赖；未访问真实数据库、Nacos、Consul，也未启动 Chrome/Edge/CDP。

### 15.135 首次初始化命令/凭证分支当前聚焦复核（2026-10-08）

- **验证：**`npm run test:logic:focused -- 'SETUP-(SHAPE|VALIDATE|SECRET|COMMAND|CHECK)'` **13/13 passed**；`npm run test:http:focused -- 'IDENTITY-MOCK|BOOTSTRAP-(HTTP|ACK)|IDENTITY-INPUT'` **9/9 passed**。覆盖网络/SQLite 提交投影、数据库/provider/auth 切换清除不相关凭证、初始化成功回读、pending/unknown/拒绝/冲突/超时、取消后不重放、setup 连接检查 503 后恢复与敏感值不进入快照。
- **源码核对：**首次初始化路由 owner 持有 workflow 并在卸载时取消；离开保护登记的 discard 回调是 `clearSensitive`。这确认清理路径已接线，但 focused logic/HTTP 不能证明实际 React 页面点击/离开时序。
- **边界：**本轮尝试启动本地 Vite 以用 Codex IAB 做局部页面验收，但 sandbox 在 `127.0.0.1:5197` 监听时返回 `EPERM`，且已有 IAB 标签对应的 `5196` 服务不可达；未改用 Chrome/Edge/CDP。未运行 `check:milestone` 或完整 E2E，F4.20/F4.21 仍未勾；需在可启动本地服务的环境补页面级路径，以及 Python Console 真实集成。

### 15.136 首次初始化字段专项 IAB 复核（2026-10-08，部分页面证据）

- Codex IAB 在本机 `first-run` Mock profile 中实际打开 `#/setup` 并通过合成一次性授权进入向导。SQLite 连接检查显示“连接可达”；管理员字段空提交显示必填错误。
- PostgreSQL → MySQL → PostgreSQL 切换后，先前录入的 PostgreSQL 用户名/密码不再恢复。规则源步骤实际可选“在控制台填写凭证”，并显示 Nacos 用户名/密码输入路径，未被凭证引用模式锁死。
- 流程停在规则源登记步骤，未提交最终初始化或写命令。合成输入仅发往本机 MSW；标签已关闭，Vite 已停止。没有访问 Python Console、真实 DB/Nacos/Consul，也没有启动 Chrome、Edge、CDP。
- **边界：**只补充实际页面渲染与该数据库类型切换分支；没有验收规则源连接结果、完整秘密清理矩阵、取消/卸载内存清理或 Python 初始化事务。F4.20/F4.21 继续未勾。详情见 [F4.20/F4.21 验收记录](acceptance/R-DASHBOARD-F4.20-F4.21.md)。

### 15.137 F4.12 撤权后迟到实时查询回归（2026-10-08）

- **风险与责任边界：**实时监控数据由 `createRealtimeMonitor` 持有轮询/选择状态，`createOwnedQueryResource` 投影 app session access owner 并在撤权时 reset 底层 `QueryResource`。最坏竞态是 Port 忽略 AbortSignal，旧 response 在撤权后才 resolve，错误地复活敏感 metrics。
- **实现：**在 `tests/logic/realtime-monitor.test.mjs` 增加 `MONITOR-LATE-REVOKED`，无需改生产代码：启动 pending read → 撤销 metrics:view → 断言 abort/denied/no data/no selection → 让 abort-ignoring Port 返回旧数据并确认 denied 仍无数据且无重试 → 切到新 owner 后新读成功。
- **验证：**定向用例 **1/1 passed**；monitor 相关聚焦测试 **8/8 passed**；`npm run check:fast` exit 0（typecheck、format、lint、42-path Console OpenAPI contract）。未运行 `check:milestone`、完整浏览器 E2E 或 Python Console 联调。
- **结论边界：**代码级撤权竞态已有逻辑证据；没有 IAB 直接撤权浏览器流程、真实 server authorization、网络故障、多小时 soak 或内存剖析。F4.12 不关闭。

### 15.138 Python Console 登录聚焦回归与当前切片状态（2026-10-08）

- **聚焦验证：**在 `components/sentinel/sentinel-console` 使用隔离 Python 3.12.14 环境执行 `python -m unittest tests.test_login_api -v`，登录 API **9/9 passed**。覆盖 Origin/CSRF 前置拒绝、异常限流依赖 fail-closed、请求体/request-id 校验、错误凭证非枚举、成功后 session/CSRF digest 持久化及 `/auth/me` 回读、旧 cookie 跨账号不撤销等路径。
- **当前实现核对：**`Login` 用例、登录 ASGI adapter、SQLAlchemy credential reader 与 session writer 均已存在；`build_app` 仍要求显式注入登录服务和部署 HMAC key。登录限流只有 Port/test double，尚无生产多 worker 安全实现；trusted-proxy client identity、正式启动组合及 PostgreSQL/MySQL 并发行为也未验证。
- **结论：**此聚焦回归更新登录切片证据，并 supersede §15.82 的“未实现”历史状态；不表示 B0.2、F4.23 或 F7.1 完成。运行基于隔离 SQLite/ASGI，无生产数据库访问、无浏览器或前后端 E2E。

### 15.139 Python Console 账号密码领域校验（2026-10-08）

- **实现：**新增 `AccountPassword` 不可变值对象，按账号创建合同校验 12–1024 个 UTF-16 code units，与 React/JavaScript 的 `.length` 一致；不 trim/normalize 密码，拒绝 unpaired surrogate，并通过隐藏 repr 防止常见调试输出直接泄漏明文。
- **验证：**隔离 Python 3.12.14 环境执行 `python -m unittest discover -s components/sentinel/sentinel-console/tests -p 'test_account_password.py' -v`，**4/4 passed**；新增两个 Python 文件 88 列检查通过。
- **边界：**这是即将实现的 account-create 用例可复用的领域子切片，当前尚未接入写 API/Argon2 adapter。没有 PostgreSQL/MySQL、ASGI 页面或真实浏览器验收；B0.2 不关闭。

### 15.140 Python Console 账号命令本地写路径（2026-10-08，B0.2 部分实现）

- **实现：**新增 account command application、CSRF/Origin 保护的 `POST /api/v1/accounts/commands` 与 actor-bound `GET /api/v1/accounts/operations/{requestKey}`、SQLite SQLAlchemy 事务适配器、`0003_account_command_receipts` migration 和 allow-list 响应投影。create/status/role 命令在事务内复验管理员会话与 CSRF，账户变更、HMAC 指纹回执和审计事件同事务提交；明文密码只用于 Argon2id/HMAC 计算，不进入回执、审计或响应。`build_app` 仅在显式注入 command service 时注册写路由，尚非生产启动装配。
- **验证：**Python 3.12.14；账户命令 ASGI + 隔离 SQLite 测试 **6/6 passed**，包含幂等重放、变更输入冲突、保留旧 HMAC key 后轮换重放、角色/状态/版本/内置与最后管理员约束、viewer/跨操作者隔离、Origin/CSRF/重复 JSON 与密码不泄漏。Console 全量 unittest **78/78 passed**；`compileall` 与本次路径 `git diff --check` 通过。完整命令和风险边界记录在 [B0.2 验收记录](acceptance/R-SENTINEL-CONSOLE-B0.2-persistence-foundation.md)。
- **边界：**全部数据库证据是内存 SQLite，guard-row `FOR UPDATE` 的 PostgreSQL/MySQL 语义、并发幂等/最后管理员竞争、生产 fingerprint key 注入与轮换生命周期、重复用户名并发、setup/account startup wiring、本人改密、可信代理与生产登录限流均未验收；没有连接真实数据库或配置中心，没有 React→Python 浏览器 E2E。**B0.2 保持未勾。**本节 supersede §15.139 中“账号密码尚未接入命令”的当前状态描述，不删除其领域值对象测试事实。

### 15.141 Python Console 本人修改密码切片（2026-10-08，B0.2 部分实现）

- **实现：**新增 `POST /api/v1/auth/password` 用例、最小凭证读取/事务写入 Port 与 SQLAlchemy 适配器。账号只从当前会话解析；要求当前密码、CSRF 与精确 Origin；写事务再次校验 session/CSRF/旧 hash，Argon2id 更新、该账号全部会话撤销和不含凭证的审计事件同事务提交。成功按 OpenAPI 允许的 `reauthenticate` disposition 返回并清除 session/CSRF cookie；客户端不得因响应未知而重放密码命令。admin/view 均可改自己的密码，无目标账号/确认密码字段。
- **验证：**改密切片 ASGI + SQLite **5/5 passed**；Console 全量 unittest **83/83 passed**；Python compileall、scoped `git diff --check` 通过。覆盖两种角色成功路径、错误当前密码无副作用、Origin/CSRF/非法/重复 JSON 拒绝、会话全撤销、密码 hash 与审计安全、DB 写事务故障回滚。
- **边界：**只证明本地隔离 SQLite/ASGI；PostgreSQL/MySQL 行锁与并发改密未验收，unknown-ACK 浏览器不重放流程尚无 React→Python milestone E2E；服务启动仍需显式注入 `own_password_service`，未接生产 composition。**B0.2 保持未勾。**本节 supersede §15.139 对本人改密尚未实现的历史现状，不替代其领域值对象测试记录。

### 15.142 测试分层与里程碑 E2E 节奏收口（2026-10-09）

- **决策：**一个独立代码切片集中修改、集中验证，不按文件或每次编辑重复全量回归。前端切片跑前端快门禁和受影响 logic/HTTP focused tests；Python-only 切片跑受影响 Console unittest 模块及必要 compileall，不跑无关的前端门禁；协议/生成合同变更增加 `contract:check` 与对应后端 API 测试。纯文档只核对文档事实和链接。
- **里程碑：**前端 milestone 跑 `npm run check:milestone`；Console milestone 跑完整 unittest，并按风险矩阵执行隔离 PostgreSQL/MySQL 集成验证；完整浏览器旅程只在明确 milestone 验收时执行，且仅用 Codex 内置浏览器。完整静态门禁、完整浏览器 E2E、真实数据库/配置中心验收是不同证据，不相互替代。
- **验证边界：**本项只调整执行流程约定，无产品代码改动；完成文档差异/链接/命令脚本存在性检查即可，不触发应用回归。不得调用 Chrome、Edge 或 CDP；失败域先聚焦修复，稳定后仅在 milestone 需要时复验完整旅程。

### 15.143 首次初始化写路径的 runtime 配置持久化前置条件（2026-10-09）

- **源码/协议证据：**OpenAPI `POST /api/v1/system/bootstrap/initialize` 要求数据库配置、首个 admin、首个规则源及跨 worker/重启持久的初始化锁/完成标记；当前代码只有 bootstrap 状态读取与初始化 operation schema，没有写路由、runtime DB locator 或部署持久化 setup-window 实现。把 DB 密文仅存入目标库无法解决重启连接顺序：读取密文前仍需先连接目标库。
- **处理：**没有实现只对 SQLite 单进程成立的假闭环。B0.2 验收设计新增 BOOT-INIT-01…05 风险矩阵，要求先定义部署拥有的 runtime locator/marker authority 及外部配置变更与目标 DB 迁移/首 admin 事务的失败恢复，然后按 focused SQLite → 隔离 PostgreSQL/MySQL → restart/multi-worker milestone 分层验证。没有引入 GoF Command 层级；同步用例的持久回执仍是数据库幂等边界。
- **状态：**这是 B0.2 首次初始化实现的明确前置设计工作，不关闭 B0.2；账号/会话/密码既有 SQLite 切片保持原证据边界。没有连接或修改任何真实数据库/配置中心，也没有运行 E2E。

### 15.144 初始化表单秘密清理函数与聚焦验证（2026-10-09）

- **实现：**新增 identity model 的纯函数 `clearSetupSecrets()`，不可变地清除数据库登录用户名/密码、Nacos/Consul/凭证引用字段及管理员密码/确认；保留账号名、数据库/来源地址等非敏感设置。`useSetupFlow.clearSensitive()` 统一委托该函数，同时沿用 connection-check invalidation 与提示清理。初始化确认成功 Effect 和离开保护的 discard callback 继续通过该命令清理，不另存第二份草稿。
- **验证：**`npm run test:logic:focused -- 'SETUP-(SECRET|COMMAND)'` **10/10 passed**；新增用例断言全部 secret-free、非敏感设置保留、输入快照未被修改。`npm run check:fast` exit 0（typecheck、Prettier、ESLint、OpenAPI `contract:check`）。无全量逻辑/HTTP/浏览器 E2E。
- **边界：**测试证明纯状态投影与工作流取消合同，不代表 React 已挂载表单在实际用户确认离开/初始化成功后的渲染路径，也不能保证 JavaScript 引擎物理擦除不可变字符串。F4.20 未关闭；未访问 Python Console、数据库、Nacos、Consul 或生产服务。

### 15.145 Python wheel 内 Dashboard 静态资源交付切片（2026-10-09）

- **实现：**新增 `npm run build:console-assets`，复用正式 live build 与既有 Sites 制品步骤，再将 Vite manifest 引用的生产文件复制到 Console 包内 `atlas_richie/sentinel_console/web/` 并生成文件字节数/SHA-256 清单。复制脚本校验 manifest 路径、缺失产物、Demo service worker，并只允许替换带本组件生成标记的目标目录。Python `build_app` 自动挂载已打包资源；根 HTML/SPA fallback 使用 `no-cache`，`/assets/*` 使用一年 immutable 缓存，未知 `/api` 返回统一 JSON 404，不回退为 HTML。浏览器标题同步改为正式 Console 名称。
- **验证：**`npm run build:console-assets` 成功，复制 **76 个生产文件 / 2,125,829 bytes**；`npm run test:sites` **4/4 passed**，`npm run test:build-profiles` **3/3 passed**，`npm run check:fast` 通过，Prettier 检查通过。Console 静态交付 ASGI 测试 **2/2 passed**；因改动位于共享 ASGI composition，Console unittest **85/85 passed**，compileall 通过。`uv build` 成功生成 sdist + wheel；wheel 安装到隔离 target 后，不依赖 Node 执行同一静态 ASGI 测试 **2/2 passed**。
- **范围：**该切片只证明生产静态文件已包含在 wheel 且 ASGI 可服务根路径/资源/SPA 深链/API 404 边界；没有实现非根 base path、正式启动/CLI、部署反向代理、数据库及全部 Console API，也没有执行完整页面 E2E。F7.6 与 B0.6 均保持未勾，产品总体 E2E 留在里程碑节点；本轮只运行局部 build/contract/unit 检查。

### 15.145 F4.20 未保存初始化凭证的挂载页面丢弃路径（2026-10-09）

- **页面证据：**仅使用 Codex 内置浏览器访问本机 `127.0.0.1:5196`，Vite 以 `VITE_CONSOLE_MOCK_BOOTSTRAP_PROFILE=first-run` 启动。通过一次性授权页后，在真实 `InitializationPage` 中填入合成数据库主机、用户名和密码；尝试切到 login 时实际出现共享“离开当前页面？”确认。选择“放弃更改并离开”后，因 bootstrap 仍未初始化，导航重新受路由保护落到 setup；重新呈现的数据库用户名/密码均为空。全部输入只供同源 Mock，未提交初始化命令。
- **验证边界：**这是 F4.20 的局部 mounted-page/IAB 行为证据，不是完整 E2E，也不证明 JavaScript 引擎物理擦除字符串。未检查成功提交后的 mounted-page 清理、全部字段级错误、Python Console 或持久化。没有运行 `check:milestone` / 完整 E2E；未调用 Chrome、Edge、CDP，也未连接数据库、Nacos、Consul 或生产服务。F4.20/F4.21 仍未勾。

### 15.146 F4.20 初始化成功后的挂载页收尾路径（2026-10-09）

- **页面证据：**为避免复用 `127.0.0.1:5196` 上既有 admin Mock session 污染结果，使用全新 `localhost:5196` origin。first-run 授权、合成 PostgreSQL 连接检查、合成管理员及 Nacos 匿名连接检查均经真实 React 页面提交到同源 MSW；初始化回执后 URL 为 `#/login?app=all&range=1h`，登录表单可见且没有管理页外壳，证明页面没有自动登录。合成密码仅在本地输入，没有写入验收文档；IAB 页面评估显示登录表单仍在、页面可访问的 storage API 不可用，因此不声称完成持久化层秘密扫描。
- **测试隔离发现：**先前使用已有的 `127.0.0.1:5196` origin，残留演示管理员 session 让完成后落到 overview；此尝试作废，不作为初始化自动登录证据。fresh-origin 复验稳定落到 login。`localhost:5196` 的合成 Mock 初始化状态现为 initialized；后续 first-run 页面验证应使用新的隔离 origin。
- **验证节奏与边界：**仅做 F4.20/F4.21 页面切片检查，没有运行完整 E2E 或 `check:milestone`；只用 Codex IAB，未调用 Chrome、Edge、CDP。没有真实 Python Console、数据库、Nacos 或 Consul。成功后的 workflow 清理仍由 `InitializationPage` 的完成 Effect 调用 `clearSensitive()`；本次 UI 证据证明的是成功路由/未自动登录，不等于 JavaScript 引擎物理覆写表单字符串。F4.20/F4.21 保持未勾。

### 15.147 F6.4.18 Mock handler 共用会话级时钟（2026-10-09）

- **实现：**新增 app-owned `MOCK_SCENARIO_NOW_MS`，在显式 demo Mock 装配时采样一次，并以同一个 `mockClock` 注入应用目录、故障时间线/证据、规则集、系统观测和配置源登记 handlers。query-scoped metric/instance 样本仍按请求 window 派生，不把观察时间误当采样时间。架构约束移除两个已不存在的恢复场景 seed 名。
- **验证：**`npm run test:http:focused -- 'MOCK-CLOCK-HTTP|OBSERVATION-SEED-CONSISTENCY|INCIDENT-MOCK|INSTANCE-MOCK'` **7/7 passed**；`npm run test:architecture` **16/16 passed**；`npm run check:fast` 通过。观测一致性测试显式重试演示场景中一次性的合成 503，并在测试前后 reset handler 状态。
- **边界：**仅证明 app Mock assembly 下三个响应时间戳共用同一采样时刻，以及所选观测/实例/故障 HTTP 用例通过；没有运行 `check:milestone`、浏览器 E2E 或 Python Console/真实数据库/配置中心。F6.4 整项仍未勾。详情见 [F6.4.18 验收记录](acceptance/R-DASHBOARD-F6.4.18-central-mock-clock.md)。

### 15.148 F6.4.19 中央 Mock 场景的环境、应用与规则源展示身份（2026-10-09）

- **实现：**观察场景引用系统场景的规范 environment/application ID；实例目录的环境显示名取自 app-owned observation scenario；规则 binding 的 source label 和 resource location 分别由系统 source name 与规范 application ID 派生。架构守卫限制 `test-env`、`app-one`、`演示环境`、`Primary Nacos` 仅由指定 app scenario 持有。
- **验证：**HTTP 聚焦用例 **12/12 passed**，覆盖总览/应用/实例/故障/规则场景及新加目录显示名和规则 source label 一致断言；`npm run test:architecture` **16/16 passed**；`npm run check:fast`、改动文件 Prettier 与 `git diff --check` 通过。
- **边界：**仅关闭所列 ID/name 副本；F6.4 其余静态健康、摘要、版本/计划、用户和场景差异盘点仍开放。没有运行 `check:milestone` 或浏览器 E2E，也没有访问 Python Console、数据库、Nacos、Consul 或生产服务。详见 [F6.4.19 验收记录](acceptance/R-DASHBOARD-F6.4.19-central-display-identities.md)。

### 15.149 F6.4.20 集中实例目录身份与能力 seed（2026-10-09）

- **实现：**实例的 container/process ID、支持的观测 scope 与最近上报偏移量由 app-owned `MOCK_OBSERVATION_SCENARIO` 持有；实例 HTTP fixture 只投影 scenario，不再自己生成这些展示事实。新增 `features/applications/model.ts` 作为不加载 UI 的公开领域词汇入口，避免 app Mock scenario 依赖 feature 私有路径或把无关 SCSS/UI 纳入 HTTP 测试 bundle。架构守卫检查 scenario 持有身份值、投影不重复构造，并约束该模型入口不引入 UI。
- **验证：**聚焦 HTTP `OBSERVATION-SEED-CONSISTENCY|MOCK-CLOCK-HTTP` **2/2 passed**；架构 **16/16 passed**；`npm run typecheck` 通过；两份改动 MJS 经 Prettier 检查，`git diff --check` 通过。完整 `check:fast` 在该次入口小修前通过；为节约回归成本，本切片没有重复运行。
- **边界：**仅集中实例目录身份/能力/时间 seed，不勾 F6.4 整项；剩余静态健康、摘要、用户、规则计划/版本等家族仍待盘点。没有运行里程碑全量检查或 E2E，没有使用 Chrome、Edge、CDP、Python Console、数据库、Nacos、Consul 或生产服务。详见 [F6.4.20 验收记录](acceptance/R-DASHBOARD-F6.4.20-central-instance-identities.md)。

### 15.150 F6.4.21 集中配置源检查的 Mock 场景事实（2026-10-09）

- **实现：**配置源检查 Mock 的不可达主机、回执有效期和能力列表移入 app-owned `MOCK_SYSTEM_SCENARIO.sourceCheck`；初始系统连接与检查成功响应共用同一份能力列表。source-registration handler 只按场景做合成分支，不再持有这几项演示 seed。新增系统 model 公开入口供 app 场景读取能力枚举，并扩展架构守卫阻止 fixture 重复定义这些事实。
- **验证：**HTTP 聚焦测试 `SOURCE-MOCK-CHECK` **2/2 passed**，覆盖可达/不可达结果及有效期；`npm run test:architecture` **16/16 passed**；`npm run check:fast` 通过，含 TypeScript、格式、lint 和 OpenAPI 检查。改动测试 Prettier 和 `git diff --check` 通过。
- **边界：**只集中配置源检查演示 facts；动态 source 注册/修订号仍由 handler 的可重置状态机生成，非静态 seed。F6.4 仍未勾；没有运行里程碑全量检查或 E2E，也没有触达真实 Console、数据库、Nacos、Consul 或生产服务。详见 [F6.4.21 验收记录](acceptance/R-DASHBOARD-F6.4.21-source-check-mock-scenario.md)。

### 15.151 F6.4.22 账号最近登录 seed 使用应用 Mock 时钟（2026-10-09）

- **实现：**管理员和查看者的最近登录时间由 app-owned `MOCK_IDENTITY_SCENARIO` 保存为相对 `lastLoginOffsetMs`，账号目录 Mock handler 按注入时钟投影 ISO 时间；app handler assembly 给它传入共用 `mockClock`。移除与运行时 app Mock 时钟脱节的固定日期字符串。新增 HTTP 断言核对账号目录时间与场景 offset，并扩展架构守卫约束所有权和时钟注入。
- **验证：**HTTP 聚焦 `IDENTITY-MOCK-SEED` **1/1 passed**；架构 **16/16 passed**；`npm run check:fast` 通过，覆盖类型、格式、lint、OpenAPI 一致性。
- **边界：**只证明 Mock 账号目录时间由场景 offset 与固定 app Mock clock 投影；真实身份服务的最近登录持久化/时区行为不在本 slice。F6.4 仍未勾；未运行里程碑全量或 E2E、未使用浏览器/Chrome/Edge/CDP，也未连接 Python Console、数据库或配置中心。详见 [F6.4.22 验收记录](acceptance/R-DASHBOARD-F6.4.22-central-identity-clock.md)。

### 15.152 F4.12 重复实时监控 owner 的轮询/订阅释放压力回归（2026-10-09）

- **测试：**`MONITOR-LIFECYCLE-STRESS` 连续创建 64 个实时监控 owner，各完成首个合成读取后 dispose；随后等待超过配置的单个轮询周期。
- **结果：**每个 owner dispose 后 access subscription 计数归零、selection 清空、观察状态 idle；全部销毁后读取数仍为 64，未见轮询 timer 或订阅随 owner 数量累积。
- **验证：**`npm run test:logic:focused -- 'MONITOR-LIFECYCLE-STRESS'` **1/1 passed**；`npm run check:fast` exit 0（typecheck、Prettier、ESLint、OpenAPI contract）。该切片未运行全量逻辑/HTTP、milestone gate 或浏览器 E2E。
- **边界：**64 次确定性 owner 生命周期压力回归不是多小时真实浏览器 soak，也不是宿主内存/CPU profiling；不覆盖后台标签节流、Python Console/Collector 网络中断。F4.12 继续未勾。完整边界见 [F4.12 验收记录](acceptance/R-DASHBOARD-F4.12.md)。

### 15.153 F6.4.23 集中实时指标 Mock 故障计划（2026-10-09）

- **实现：**恢复型与首读失败型指标场景的目标应用、注入读次和错误码移入 app-owned `MOCK_OBSERVATION_SCENARIO.readScenarios.metricFailures`。Realtime handler 只执行该计划并依据公共错误映射生成 HTTP 状态，不再持有 `FAILURE_ATTEMPT` seed 常量。
- **验证：**Realtime mock/恢复/monitor-recovery HTTP 聚焦 **3/3 passed**；架构 **17/17 passed**，新增 F6.4.23 所有权守卫；`npm run check:fast` exit 0。
- **边界：**只集中实时指标受控失败场景并验证 Mock HTTP 恢复；F6.4 其他 seed 家族尚待盘点，仍不勾。没有运行浏览器 E2E/milestone gate，也没有调用 Python Console、Collector、真实数据库或配置中心。详见 [F6.4.23 验收记录](acceptance/R-DASHBOARD-F6.4.23-central-metric-failure-plans.md)。

### 15.154 F6.4.24 集中 Fleet overview Mock 恢复故障计划（2026-10-09）

- **实现：**fleet recovery 的目标 application ID、触发读次和错误码迁入 app-owned `MOCK_OBSERVATION_SCENARIO.readScenarios.fleetFailure`；overview handler 按计划注入一次失败，HTTP status 由公共 Console 错误映射解析。原 forbidden application 403 场景保留。
- **验证：**Fleet mock/seed/recovery HTTP 聚焦 **3/3 passed**；架构 **18/18 passed**，包含 F6.4.24 所有权门禁；`npm run check:fast` exit 0。
- **边界：**只验证 Mock HTTP 失败后可恢复，不代表真实 Python Console/网络故障恢复；F6.4 仍未勾。没有运行完整 milestone gate 或浏览器 E2E，未连接数据库或配置中心。详见 [F6.4.24 验收记录](acceptance/R-DASHBOARD-F6.4.24-central-fleet-failure-plan.md)。

### 15.155 F6.4.25 集中 Incident 证据变化 seed（2026-10-09）

- **实现：**将故障证据中资源压力样本的演示变化量 `resourcePressureValueDelta` 从 HTTP handler 移入 app-owned `MOCK_INCIDENT_SCENARIO`。handler 继续负责按 scenario 生成 wire evidence，但不再内嵌具体数值。
- **验证：**`npm run test:http:focused -- 'INCIDENT-MOCK'` 覆盖 evidence 投影与关联实例查询；`npm run test:architecture` 覆盖 seed 所有权，禁止 handler 重新硬编码变化量；`npm run check:fast` 验证类型、格式、lint 与 OpenAPI 一致性。具体结果以本次命令实际输出为准。
- **边界：**仅收口故障证据的一个演示变化量，F6.4 仍未勾；本切片不是完整里程碑，未运行 `check:milestone` 或页面 E2E，也未连接 Python Console、数据库、Nacos 或 Consul。

### 15.156 F6.4 Mock seed 全 feature 最终盘点与验收（2026-10-09）

- **盘点结论：**应用目录/实例/环境/统一演示时钟由 observation scenario 所有；账号与 bootstrap 配置由 identity scenario 所有；配置源、健康/协议/审计事实由 system scenario 所有；规则快照/版本/发布回执/计划由 rule scenario 所有；故障模板/证据参数由 incident scenario 所有。Fleet、应用实例、Realtime 与系统/身份/规则 handler 都仅从显式 scenario 做 wire 投影或承载测试状态。业务 UI 不导入 Mock fixtures，feature fixtures 仅经各自的 `mock.ts` 由 app Mock assembly 引入。
- **一致性证据：**架构门禁检查 fixture 依赖所有权、固定身份/故障计划/指标曲线的唯一归属；HTTP 测试覆盖 `OBSERVATION-SEED-CONSISTENCY`、`MOCK-CLOCK-HTTP`、`IDENTITY-MOCK-SEED`、`SYSTEM-MOCK-SEED`、`FLEET-MOCK-SEED` 及规则版本/回执/计划 scenario，确保跨页面 ID、统计与时间一致。
- **验证：**`npm run test:http` **103/103 passed**；首次 sandbox run 有 2 项仅因绑定本机 `127.0.0.1` 被 `EPERM` 阻止，获准仅限回环监听后同一完整 HTTP 套件重跑通过。`npm run test:architecture` **19/19 passed**；`npm run check:fast` exit **0**（TypeScript、Prettier、ESLint、42-path OpenAPI 一致性）。Codex 内置浏览器打开 `http://127.0.0.1:4173/#faults`，确认本地 demo route 与 timeline 可见；本轮没有跑完整页面 E2E。
- **边界：**F6.4 关闭的是前端 demo seed 所有权及 HTTP Mock 一致性，不证明 Python Console、真实指标/Reporter、MySQL/PostgreSQL、Nacos/Consul 或生产权限。完整产品 E2E 按验证节奏留在里程碑验收；本记录不关闭 F6.5 以后任务或总目标。详情见 [F6.4 最终 seed 审计](acceptance/R-DASHBOARD-F6.4-seed-audit.md)。

### 15.157 F6.5 Console operation 到 MSW handler 全覆盖（2026-10-09）

- **实现：**新增 `MOCK-OPERATION-COVERAGE`，从运行时 `CONSOLE_OPERATIONS` 与 app-owned `APP_CONSOLE_MOCK_HANDLERS` 比对 method/path（包括 path parameter 规范化）；以后 OpenAPI/runtime 新增 operation 而未注册 HTTP Mock 时测试失败。浏览器 demo 与 Node HTTP 测试都使用同一批 feature handler factories；未匹配 Console API 仍由独立 terminal handler fail closed。
- **验证：**新增覆盖门禁 focused **1/1 passed**；完整 `npm run test:http` **104/104 passed**（含 MSW operation 覆盖、各 feature 的 query/body/error/stateful HTTP contracts 和隔离回环 transport）；`npm run check:fast` exit **0**；新测试文件 Prettier 检查通过。Codex 内置浏览器已打开本地 demo 的 Faults 页面并确认 feature Mock HTTP 返回 timeline。完整页面 E2E 未运行。
- **边界：**该测试证明每个 Console operation 都注册一个 MSW method/path handler，并由完整 HTTP 测试证明当前协议响应；不证明真实 Python provider、生产部署或未实现功能的后端行为。F6.6 的演示状态初始化/重置/筛选分页行为仍单独跟踪。详情见 [F6.5 验收记录](acceptance/R-DASHBOARD-F6.5-mock-operation-coverage.md)。

### 15.158 F6.6 Mock 查询、命令状态与敏感值隔离（2026-10-09）

- **实现核对：**账户 Mock 按 search/status/page/pageSize 过滤与分页，角色/状态命令更新 handler-local 目录并按 request key 幂等；账号密码不复制到账户行/操作回执。账户与 identity handler 通过新 factory 获得独立初始 seed；规则 handler 显式 reset 版本/发布/回执/计划状态，配置源 handler reset 恢复唯一 canonical registry seed。观测查询按各自 context/window/page/filter 求值；浏览器持久状态限于 schema 固定的 Mock bootstrap、角色和故障开关。
- **验证：**新增 `ACCOUNT-MOCK-QUERY`、`ACCOUNT-MOCK-COMMAND-STATE`，并加强 `ACCOUNT-MOCK-ISOLATION` 的行/回执密码不泄漏断言；定向集合 **3/3 passed**。完整 `npm run test:http` **106/106 passed**（完成该三项用例实现时），覆盖账户、identity、rule draft/version/publication/plan、source registry/reset、fleet/instance/incident/metrics query 与 HTTP 合同；之后追加的密码行/回执断言又通过同一 focused 集合 **3/3**。`npm run check:fast` exit **0**，新增 HTTP 测试 Prettier 检查通过。
- **边界：**Mock 状态是浏览器进程内/handler factory 生命周期，不是生产持久层；真实 Python 数据库、跨进程共享、重启持久性仍由 B0/F7 验收。没有运行完整页面 E2E或 `check:milestone`。详情见 [F6.6 验收记录](acceptance/R-DASHBOARD-F6.6-mock-state-and-query-semantics.md)。

### 15.159 F6.7 Mock/live 运行配置与启动隔离（2026-10-09）

- **交付：**集中解析 `mock | live` 与 API origin；mock 禁止设置真实 API base URL，live 校验绝对 HTTP(S) origin、禁止凭证/path/query/hash；生产 live-only 默认同源且禁止 mock。新增可测试的 Console 启动编排：等待请求拦截边界 ready 后才创建服务并挂载 React。
- **验证：**mock/live/base URL/启动顺序/拦截失败关闭 focused logic **5/5 passed**；`npm run check:fast` exit **0**；Codex 内置浏览器在本地 mock profile 到达登录表单；Prettier 与 `git diff --check` 通过。
- **边界：**浏览器仅为启动冒烟，不是完整页面 E2E；没有运行 `check:milestone` 或真实 Python Console/live endpoint。生产构建隔离与 demo worker 只在显式 demo 制品中保留由 F6.8 继续验收。详情见 [F6.7 记录](acceptance/R-DASHBOARD-F6.7-runtime-mode-and-bootstrap.md)。

### 15.160 F6.8 Live/demo 产物隔离（2026-10-09）

- **验证：**live 与 demo Vite builds 均写入 `/tmp` 临时目录，保留仓库中既有 ignored `dist/`；`tests/build-profile.test.mjs` 对这两个确切产物 **3/3 passed**，证明 live 不含 MSW worker/handler/demo identity，而显式 demo 包含 mock worker/handlers；Astryx 延迟语言包检查通过。runtime focused **6/6**、`npm run check:fast` exit **0**。生产/demo 构建提示依赖注释和 >500 kB chunk warning，作为 F5.6 体积评估事项，不影响当前 artifact isolation assertions。
- **边界：**未运行全页面 E2E 或 `check:milestone`；未连接 Python Console/live endpoint；产物隔离不证明真实部署的缓存刷新。保留项目自有 `worker/index.js` 不变。详情见 [F6.8 记录](acceptance/R-DASHBOARD-F6.8-live-and-demo-build-isolation.md)。

### 15.161 F6.9 故障注入隔离、恢复、权限矩阵与操作级 HTTP 错误矩阵（2026-10-09）

- **实现：**`MOCK_INCIDENT_SCENARIO` 增加 app-owned `timelineFailure` 计划（仅匹配指定 app 的首个有效 timeline read 返回 `service_unavailable`）；incident handler factory 只持有自己的读次状态，并从公共错误码映射 HTTP status。跨 feature 全套测试曾发现未限定 app 的故障计划会污染共享 incident 测试；已收窄作用域并加恢复/重建 factory 回归。新增 `HTTP-OPERATION-ERROR-MATRIX`，按 42 个 `CONSOLE_OPERATIONS` 遍历各 endpoint 声明的每个错误码，通过真实 Console transport 与 MSW 校验 HTTP status、错误 kind/code/request ID、安全消息与 body/cause 不泄露，以及 401 会话失效边界。新增 `APP-MOCK-AUTHORIZATION-MATRIX`，使用组合后的应用 Mock handlers 验证 view 角色可以读取图表指标、账号/配置源/规则草稿管理数据被 403 拒绝，且 403 不触发身份失效。
- **验证：**`APP-MOCK-AUTHORIZATION-MATRIX` 聚焦 **1/1 passed**；`node --test tests/architecture/workflow-ownership.test.mjs` **7/7 passed**；`npm run check:fast` exit **0**；经批准允许测试绑定隔离 loopback 后，完整 `npm run test:http` **109/109 passed**。普通 sandbox 首次全量 HTTP 运行的 loopback bind `EPERM` 已通过授权重跑排除为环境限制，不计作产品测试失败。
- **边界：**操作矩阵证明已登记 endpoint 的声明错误映射，组合权限测试证明 demo Mock 下的查看者边界；两者都不证明真实 Python 服务授权、每个 feature 的 UI 错误呈现或全部断网 stale/retry 生命周期。目前仅新增 Incident timeline 一条确定性 feature 故障计划。真实外网/Python Console/数据库/配置中心未覆盖。完整 E2E 与 `check:milestone` 按节奏留在里程碑节点，F6.9 仍未完成。

### 15.162 F6.10 受控 live HTTP 传输成功/错误/取消契约（2026-10-09）

- **实现与核对：**扩展 `HTTP-LIVE-CONTROLLED`，使用隔离本机 loopback HTTP listener（非 MSW、非替身 Port）验证 `ConsoleTransport`：成功响应的 path/query 与 request ID、无 `Authorization`/用户身份头；服务端 canonical `503 service_unavailable` 被映射为安全结构化错误；请求发出后由调用者 abort，客户端得到 `CANCELLED` 且受控服务端观察到连接关闭。当前 API 没有 SSE/EventSource/订阅型流；`ReadableStream` 仅在 transport 用于对普通 JSON 响应做有界读取，不代表产品级 stream API。
- **验证：**`npm run test:http:focused -- 'HTTP-LIVE-CONTROLLED'` **1/1 passed**；组合 F6.9 改动后 `npm run check:fast` exit **0**，完整 `npm run test:http` **109/109 passed**。普通 sandbox 不允许 loopback bind；该聚焦及完整 HTTP 重跑通过已批准的本机隔离 listener。
- **边界：**这是真实本机 HTTP socket 上的 transport 验收，不是 Dashboard live runtime 全页面、Python Console、真实网络或真实认证联调；DTO/sample/mock handler 对齐由同套 HTTP wire 与 42-operation mock coverage 检查支撑。没有执行 `check:milestone` 或浏览器 E2E，按测试节奏留待里程碑。

### 15.163 F6.11 前端 provider 边界与过时协议断言复核（2026-10-09）

- **职责核对：**当前正式规则 wire 使用 `RuleBinding.profile` 标识目标兼容 profile，并以 `RuleSetCandidate.rules[]` 承载完整规则集；五类规则 `grade` 字段在模型与严格 Zod wire schema 中均为数值编码。前端配置源注册通过 `/api/v1/system/sources` Console HTTP Port，Nacos/Consul 字段只作为 Console 请求数据，不在浏览器实现 provider SDK、地址探测或 Nacos/Consul API 路径。生产/Mock 共用 Console contract。
- **错误语义：**真实规则命令结果拒绝的 `not_found` → 404、`conflict` → 409、`unavailable` → 503 映射仍分别存在于 `ruleOperation.ts`；普通读取 endpoint 对缺失目标 404 也按 `not_found` 处理。没有将未知 404 伪改成版本冲突，也没有把 `grade` 数值改写成规则类别字符串。§10.2 中旧 `tests/api/run.mjs` 的 18/20 是 provider 草稿退役前历史，不是当前正式测试入口或当前失败。
- **退役/验证：**当前源码不存在 `src/core/api/providers` 和 `tests/api/run.mjs`；依赖架构保护在 `npm run test:architecture` **20/20 passed** 中执行。F1/规则模型与工作流聚焦 **30/30 passed**；规则目录/快照/候选/集合/命令/Mock + 全操作错误矩阵 **8/8 passed**；`git diff --check` 通过。完整 HTTP 与 `check:fast` 当前证据沿用同一工作区最近结果 §15.161–§15.162。
- **结论与边界：**F6.11 的 React 前端职责与历史伪适配器/断言问题均已收口，故 checklist 勾选仅代表“浏览器只请求统一 Console、不承担 provider 兼容”。Python Nacos codec 与五类规则 profile 的字段语义差异、Consul/Nacos 真实存储、凭证/SSRF 防护、持久化回读及重启恢复均仍属 B0.1/B0.3；不得把本节作为后端兼容或真实配置中心验收。未运行里程碑 E2E。

### 15.164 F6.9 Mock 场景时钟、故障隔离与断网恢复收口（2026-10-09）

- **设计边界：**Mock clock 与 app-level handler assembly 归 `src/app/api`；每次 `createAppConsoleMockAssembly(nowMs)` 创建新 handler 集合并共享同一个不可变 epoch clock。默认演示仍在模块加载时捕获一次当前时间；自动化可注入固定 epoch。Fleet 与 metrics 的 fail-once 计数由各自 handler factory closure 持有，不使用模块级 Map/reset API；incident、rule、source、account 等原有状态仍由各自 handler factory 拥有。
- **真实缺陷修复：**此前 Fleet/metrics 故障计数是模块级全局状态，handler 实例并不独立；改为实例级闭包。增加 app assembly 固定时间与重建回放测试，验证相同 HTTP 故障顺序和成功 payload 可复现。新增实时指标合成 network-failure plan：第一次读由 MSW 返回无 HTTP 响应，transport 映射为安全的 `NETWORK` 错误且不自动重试；显式下一次读取返回 `no_samples` 成功结果。故障目标使用保留的 `mock-network-outage`，不污染正常 app seed 和产品主流程。
- **验证：**定向 `METRICS-NETWORK-RECOVERY` / `MOCK-SCENARIO-REPLAY` **2/2**；完整 `npm run test:http` **112/112**；`npm run check:fast` 通过（typecheck、Prettier、ESLint、Console OpenAPI drift check）；`npm run test:architecture` **20/20**；`git diff --check` 通过。完整 HTTP 套件内 loopback 测试使用批准的本机隔离 listener；未运行浏览器 E2E 或 `check:milestone`，符合 `docs/TESTING_CADENCE.md`。
- **结论与边界：**F6.9 的声明错误/权限矩阵、拦截器/静态资源边界、HTTP/网络/时序错误、安全映射与可复现 mock time/seed 已由当前 HTTP/架构证据覆盖，故 checklist 勾选。该结论不代表页面级加载/刷新错误视觉验收，也不代表 Python Console、数据库、Nacos/Consul 或真实网络断连验收；后者仍由 F7 与 B0 负责。

### 15.165 F4.12 实时监控网络错误语义与安全恢复提示（2026-10-09）

- **实现：**实时观测页现在将 `AppErrorKind.NETWORK` 与通用服务错误区分：首次失败时说明没有可信数据、下一轮会自动重试且可手动重试；已有同范围可信快照时明确标为陈旧，告知其时间事实及继续轮询。共享 `ObservationQueryView` 仅开放能力级 `error/stale` 文案覆盖，保留原有查询状态、只读重试与数据留存契约；raw transport message 不进入文案。中/英/日资源同步。
- **Mock 可达性：**一次性网络故障探针从目录外 synthetic ID 移到目录有效的 `app-three`；网络计数与 HTTP 503 计数独立，避免两种故障相互消费计数。HTTP 用例覆盖 503→有数据→无响应网络错误→同应用恢复，transport 不对无响应请求隐式重试。
- **验证：**`npm run test:logic:focused -- 'REALTIME-READ-COPY'` **3/3**；`npm run test:http:focused -- 'METRICS-NETWORK-RECOVERY'` **1/1**；`node --test tests/architecture/workflow-ownership.test.mjs` **7/7**；`npm run check:fast` exit **0**；`npm run i18n:check` 通过，三语各 1147 个键；`git diff --check` 通过。
- **Codex IAB：**在本地 demo 的有效 `app-three` 实时页观察到正常部分指标、缺测 TPS 和保持轮询；本轮观察期间没有出现网络故障提示，因此没有记录为断网 UI 通过。只确认页面仍可用，不等于故障路径通过。
- **边界：**未运行 `check:milestone` 或完整页面 E2E；未访问 Python Console/Reporter/Collector，也未做长时浏览器/宿主资源剖析。F4.12 继续未勾；待网络故障在页面中的可重复注入与 IAB stale→恢复路径验收，以及真实服务端故障/资源剖析。

### 15.166 F4.12 网络故障 Mock 在有效数据后确定性触发（2026-10-09）

- **修复：**一次性断网场景不再依赖 app-three 的绝对请求序号。HTTP handler 先完成指定的服务端 503 和成功读取，再等待目标应用产生两个成功指标响应后注入一次 transport 网络错误；下一次轮询允许恢复。这样降低 StrictMode 首次挂载/取消重放提前消费故障点的风险，并且保留恢复读与“无隐藏重试”合同。
- **验证：**`npm run test:http:focused -- 'METRICS-NETWORK-RECOVERY'` **1/1 passed**，断言 `503 → 200 → 200 → NETWORK → 200`；`npm run check:fast` exit **0**；`npm run i18n:check` 通过（三语各 1147 keys）；`git diff --check` 通过。
- **边界：**IAB 本轮无可访问标签且设备报告锁屏，未进行可见页面检查；本测试证明受控 Mock/HTTP 序列，不证明页面 banner/stale/recovery 已渲染，也不证明 Python Console/Reporter/Collector 真实网络恢复。完整 milestone/E2E 按验证节奏未运行，F4.12 继续未勾。

### 15.167 F5.2 实时网络提示动态翻译调用点映射（2026-10-09）

- **复现：**先运行 `node --test tests/i18n/dynamic-callsite-coverage.test.mjs`，该门禁失败并明确列出 `LiveMonitoringPage.tsx` 中 `t(readCopy.error)` 与 `t(readCopy.stale)` 两个未登记调用，证实仅有 TypeScript 动态 key 约束不足以满足逐项 producer/runtime 追踪。
- **修复：**把两处调用分别登记到 `I18N-DYNAMIC-PRESENTATION`；该真实 producer 测试通过 `realtimeReadCopy` 生成 NETWORK 首次失败与 stale 键，再由三语真实 i18next 实例断言不回显 key 且插值完整。没有新增第二套翻译表或复制资源键白名单。
- **验证：**动态调用映射 focused 测试 **1/1 passed**；`npm run test:i18n-tools` **29/29 passed**；`npm run check:fast` exit **0**；`npm run i18n:check` 三语各 **1,147** 个键、静态可校验 **1,013**，报告的 **19** 个动态调用与 manifest 精确集合一致；修改测试的 Prettier 检查及 `git diff --check` 通过。
- **边界：**这里只关闭 19 个动态调用到 producer runtime suite 的可审计映射；并不关闭页面级日期/时区/DST、持草稿和 URL 状态的三语 IAB 矩阵，也未运行 milestone/full E2E。F5.2 保持未勾选。

### 15.168 F7.6 Vite 与 Console ASGI 非根路径基线（2026-10-09）

- **实现：**新增严格解析 `SENTINEL_CONSOLE_BASE_PATH`，默认 `/`，允许规范部署前缀（如 `/ops/sentinel/`），拒绝不规范路径及占用 `/api` 的前缀。`build_app` 增加显式 `dashboard_base_path` 参数；静态 ASGI 路由在该前缀提供首页、fingerprinted assets 与 SPA 深链，根 `/api` 仍由 API 路由拥有。README 记录构建/ASGI 前缀需一致以及可选反向代理剥离方案。
- **验证：**`node --test tests/build-profile.test.mjs tests/build-path.test.mjs` **5/5 passed**；`npm run check:fast` exit **0**（typecheck、格式、lint、42-path OpenAPI 一致性）；Console 定向 `test_static_web` **4/4 passed**；`compileall` 通过，改动 Python 文件 88 列检查通过。隔离 Vite 构建产物 `index.html` 的 JS/CSS 均引用 `/ops/sentinel/assets/`。
- **边界：**这证明前缀配置、产物 URL 和 ASGI 静态路由，不证明反向代理、生产启动器环境装配、部署缓存头/SPA 行为或安装 wheel 启动。Sites 制品保护检查和 `/api` 真实代理仍未验收。本切片未运行 `check:milestone` 或完整浏览器 E2E；F7.6 与 B0.6 继续未勾。详见 [F7.6 静态资源交付验收记录](acceptance/R-DASHBOARD-F7.6-wheel-static-assets.md)。

### 15.169 B0.2 初始化数据库连通性检查 HTTP 安全切片（2026-10-09）

- **实现：**新增 `POST /api/v1/system/bootstrap/database-check` 的受控 HTTP adapter 与 checker Port。路由先校验 setup、当前操作者授权、精确 Origin、double-submit CSRF、request ID 和严格数据库候选结构；仅返回有限 reachability/reason，不迁移或写入数据。checker 未装配时 fail closed。部署显式 kind/CIDR/port target policy 拒绝宽泛 `/0`、越界/混合/过量 DNS answer、link-local/unspecified/multicast，并产出可 pin 的 IP 集合。新建 `BootstrapDatabaseConnector` 将该 policy 接至 PostgreSQL/MySQL 一次性 `SELECT 1` 探测：PostgreSQL 传 `hostaddr` + `verify-full`；MySQL 以批准 IP 建 TCP，并用原 hostname 完成 TLS identity 校验；两者均有有界超时、可部署 CA 信任配置和脱敏错误分类。MySQL adapter 当前依赖 asyncmy 私有 TLS-upgrade hook，因此 mysql extra 精确 pin `asyncmy==0.2.16`，需在升级时重新验证。此处“SQLite 未支持”状态由 §15.170 更新。
- **验证：**初始 Python 3.12 Console 定向测试 **22/22 passed**（connector adapter 8 + CIDR/DNS policy 8 + database-check ASGI 6）；初始证据不含 SQLite adapter。使用隔离 ASGI test client、fake driver、合成 DNS；无真实数据库、配置中心、提交凭证或浏览器访问。
- **边界：**connector 尚未接入生产启动组合；生产 PG/MySQL/SQLite 与 TLS/socket 验收仍未完成。fake-driver 测试不证明真实服务兼容。Console 全量测试、`check:milestone` 和完整页面 E2E 本轮未运行。**B0.2 继续未勾。**详见 [B0.2 数据库连通性检查验收记录](acceptance/R-SENTINEL-CONSOLE-B0.2-database-connectivity-check.md)。

### 15.170 B0.2 SQLite 部署路径只读连通检查（2026-10-09）

- **责任边界：**`BootstrapDatabaseConnector` 仍是应用 Checker Port 的基础设施适配器；SQLite 文件位置只可由服务部署组合传入为绝对 `Path`，浏览器 DTO 不新增 path 字段，不接受调用者选择服务器文件。未配置路径按 `unsupported` 返回。
- **行为：**配置 SQLite 路径后，仅以 SQLite URI `mode=ro` 打开既有数据库，设置连接级 `query_only` 并执行 `SELECT 1`；不存在的文件返回 `connection`，不创建文件。该探测不执行 schema migration。首次安装选择 SQLite 时必须由部署预置空数据库文件；否则连接检查不会报可达。该局部能力不替代未来 setup 初始化事务与迁移实现。
- **验证：**Python 3.12 聚焦 Connector/target policy/HTTP 测试 **25/25 passed**；新增既有 DB 只读检查、缺失文件不创建、相对部署路径拒绝。运行环境为隔离临时 SQLite 文件、fake PG/MySQL driver、合成 DNS 与 ASGI test client；没有访问真实数据库/配置中心或浏览器。Console 全量套件、生产组合装配和 `check:milestone`/完整 E2E 未运行。
- **结论：****B0.2 继续未勾。**SQLite adapter 已有本地只读证据，但生产启动装配、首启创建/迁移 owner、PG/MySQL 真服务并发与 TLS/socket、真实浏览器→Python 路径仍开放。详见 [B0.2 数据库连通性检查验收记录](acceptance/R-SENTINEL-CONSOLE-B0.2-database-connectivity-check.md)。

### 15.171 B0.2 登录限流的显式可信代理地址策略（2026-10-09）

- **落点与策略：**登录 HTTP adapter 原先直接读取 ASGI peer 计算 HMAC 限流身份；现新增不可变 `ClientAddressResolver`。默认只使用直接 peer 并忽略所有转发头。只有显式配置的严格非全局 CIDR 命中直接 peer 时才解析 `X-Forwarded-For`；从右向左跳过受信代理地址，选择最近的非代理地址。空/畸形链回退到直接 peer；不解析 RFC `Forwarded` 或客户端自报 `X-Real-IP`。策略注入 `build_app` / login route，限流仍使用既有多 worker `LoginAttemptLimiter` Port。
- **验证：**Python 3.12 `test_login_api` **13/13 passed**；使用隔离 ASGI/SQLite 检查直接客户端伪造转发头不改变限流身份、受信代理多跳解析、畸形链回退、非规范/可路由公网 CIDR（含 `/1`）拒绝和登录 route 实际 HMAC 身份。没有连接真实反向代理、数据库或配置中心。
- **边界：**这是可注入策略，不是生产环境变量解析或可信 ingress 配置；需要 launcher 明确构造并注入受信 CIDR，同时验证真实代理确实按约定追加且覆盖/清理外部头。multi-worker limiter、生产装配和真实代理验收仍未完成，因此 **B0.2 不勾**。详情见 B0.2 持久化验收记录。

### 15.172 B0.2 SQL-backed 登录限流状态（2026-10-09）

- **实现：**新增 `console_login_attempt` migration/model 与 `SqlAlchemyLoginAttemptLimiter`。限流键仅接受 API 边界生成的 64 位小写 HMAC 摘要；持久字段只有 digest、窗口起点、失败数、封锁截止和清理截止，不保存原始 IP/用户名。要求调用方显式传 `LoginAttemptLimitPolicy`（阈值、窗口、封锁时长），不引入暗中默认安全策略。失败状态通过 PG/SQLite `ON CONFLICT DO NOTHING` 或 MySQL no-op duplicate-key insert-if-absent 后 `SELECT FOR UPDATE` 更新；成功清除该 digest；数据库错误安全失败。过期记录在每进程有界 mutation 周期内批量清理。
- **验证：**Python 3.12 聚焦 `test_login_attempt_limiter`、`test_login_api`、`test_persistence_foundation` **25/25 passed**。含数据库 adapter 与 ASGI 组合的错误密码→429、阻断时间、成功清理、8 个并发 SQLite 首次失败/阈值饱和、同一 SQLite 文件的双 engine 共享、DB 不可用 fail-closed，以及 PG/MySQL/SQLite SQL 语句编译；`compileall` 和新增生产/测试源 88 列检查通过。
- **边界：**SQLite 同进程/双 engine 测试不证明生产多 worker；方言 SQL 编译不证明 PG/MySQL 执行与行锁语义。当前尚未接入 `build_app` 生产组合或 launcher/env policy，未跑 disposable PG/MySQL 多连接并发、进程重启、真实 ingress 或浏览器→Python E2E。**B0.2 继续未勾**；详细记录见 [B0.2 持久化验收记录](acceptance/R-SENTINEL-CONSOLE-B0.2-persistence-foundation.md)。

### 15.173 Dashboard 日常与里程碑验证入口拆分（2026-10-09）

- **实现：**普通 PR/push 只运行 `check:fast`；GitHub Actions 增加手动 `fast` / `milestone` 选择，只有选择 `milestone` 才运行完整非浏览器 `check:milestone`。完整页面 E2E 仅在里程碑通过 Codex 内置浏览器执行；不调用 Chrome、Edge 或 CDP。同步更新前端 AGENTS、README 与 `docs/TESTING_CADENCE.md`，新增 workflow cadence 守卫测试。
- **验证：**`node --test tests/verification/cadence.test.mjs` **3/3 passed**；相关 Markdown、测试和 workflow Prettier 检查通过；`git diff --check` 通过。跨 feature HTTP adapter suite 在同一工作周期受控 loopback listener 权限下 **112/112 passed**，见 §15.174 与 [F6.2 验收记录](acceptance/R-DASHBOARD-F6.2-rule-timestamp-mapping.md)。
- **边界：**未触发 GitHub Actions，不能声称远程 workflow 已运行；未运行 milestone gate 或浏览器 E2E。配置守卫和本地验证不是远程 CI/页面验收证据。详细规则见 [验证节奏验收记录](acceptance/R-DASHBOARD-validation-cadence.md)。

### 15.174 F6.2 跨 feature HTTP adapter 套件复验（2026-10-09）

- **验证：**完成前端各 feature API mapper 的静态入口盘点后，运行 `npm run test:http` **112/112 passed**。普通 sandbox 首次运行中两个需要本机 loopback 监听的用例报 `EPERM`;对绑定隔离 `127.0.0.1` 临时端口的同一测试命令取得受控执行后全量通过。测试未访问外部服务、数据库或配置中心。
- **边界：**这是基于 MSW/受控本机 HTTP 的消费端适配与 transport 证据，不证明 Python Console 已实现或兼容全部 42 个 operation，不证明真实配置中心/数据库，也不等同浏览器或跨层 E2E。F6.2 仍待真实 Python Console 对接及逐项 mapper 审核收口。

### 15.175 B0.1 Python Console 路由覆盖基线（2026-10-09）

- **核对范围：**比对 `components/sentinel/docs/protocol/console-api.openapi.json` 的 method/path operation 与 `sentinel-console/src/atlas_richie/sentinel_console/app.py` 的路由组合及 `api/` 路由工厂。
- **结果：**OpenAPI 有 **42** 个 operation。该基线时 `build_app` 无条件组合 Bootstrap 状态、数据库探测、当前 session、连接、协议和审计观察、logout 与账户目录 list/detail，共 **9** 个；依赖存在时另组合 login、账户命令/操作回查、本人改密，共 **4** 个，因此当时源码上限是 **13/42**。后续增量与当前覆盖见 §15.184。其余 operation 尚未定义/装配到 Python app；主要缺口为 bootstrap authorize/source-check/initialize/operation、metrics、fleet、instances、observation catalog、incidents、registered sources 与完整 ruleset 工作流。连接、协议和审计路由均为宿主注入式读路径，尚无生产事实源装配，不能据此宣称这些能力已上线。
- **证据边界：**这是从受控 OpenAPI 文件和 Python 路由源码得出的静态覆盖盘点，不是 runtime 路由、权限或 wire 响应验证；可选依赖也不代表存在生产 composition。没有启动服务、访问真实数据库/配置中心或运行浏览器 E2E。B0.1 保持未勾；逐路由开发必须继续以对应 Console operation schema、权限语义和错误矩阵为准。

### 15.176 B0.1 协议观察读取 API 首切片（2026-10-09）

- **实现：**新增 `GET /api/v1/system/protocols`，认证后允许 `admin` 与 `view` 读取。消费方拥有的 reader Port 注入部署侧协议观察快照；DTO 限定 `rule-config`、`agent-reporting`、`cluster-token` 三个边界，支持版本、活动版本、兼容性、观察时间彼此独立校验，快照时间以 UTC 毫秒格式序列化。活动协商事实不从 SDK 常量推断；未观测边界允许省略，未装配 reader 或事实源不可用时返回无细节的 `503 service_unavailable`。
- **验证：**定向 Python 测试 `test_system_protocols_api.py` + `test_session_api.py` **10 passed**；覆盖两种角色、匿名拒绝、session/authority 不可用、缺失事实源、非法 request id、wire 时间格式和 DTO 不变量；`git diff --check` 通过。按测试节奏未运行完整 E2E。
- **未完成：**当前 `build_app` 默认未注入生产 `SystemProtocolsReader`，因此当前无宿主配置时该 endpoint 会返回 503；协议 schema 也尚未加入独立的 Python OpenAPI validator / live service composition 验收。本切片不勾选 B0.1。

### 15.177 B0.1 系统连接观察 API 首切片（2026-10-09）

- **实现：**新增 `GET /api/v1/system/connections`，复用已登录会话访问边界，允许 `admin` 与 `view` 读取。Consumer-owned `SystemConnectionsReader` 注入服务端探测快照；领域 DTO 校验三种链路类别、Nacos/Consul source identity、有限健康/能力/失败枚举、唯一标识、非负有限 latency、UTC aware 时间、probe expiry 与快照时间；wire 不含 URL、凭证或原始异常。缺失类别保持缺失，不合成“健康”；未装配 reader 或权威不可用返回 `503 service_unavailable`。
- **验证：**定向 `test_system_connections_api.py`、`test_system_protocols_api.py`、`test_session_api.py` 共 **15 passed**；覆盖 admin/view、匿名/坏 request-id、缺失或失效 authority、不可伪造健康、有限时间/耗时及安全投影；`git diff --check` 通过。未运行完整 E2E。
- **未完成：**生产 source registry、metrics backend、reporting collector 的探测器尚未装配到 `build_app`，因此 endpoint 当前默认返回 503；Python/OpenAPI 自动响应校验和真实服务检查仍开放。本切片不勾选 B0.1。

### 15.178 B0.1 系统审计只读 API 首切片（2026-10-09）

- `GET /api/v1/system/audit` 严格按 OpenAPI 校验 UTC 毫秒时间窗、31 天上限、actor/action/result/page/pageSize、重复/未知参数；仅 admin 可读，权限检查先于存储访问。
- `SqlAlchemySystemAuditReader` 支持审计持久化当前已写入的账号创建/角色/状态和本人改密事实；采用半开时间窗、asOf 上界、新到旧及事件 ID 稳定排序、最多 100 条分页。只投影有限动作/结果和安全标识，不包含请求体、凭证、密码或原始异常。
- 已知 limitation：表结构允许 actor/target 为空；DTO 合同不允许伪造这类必填标识，当前 adapter 对落入页面的空/未知持久化事实 fail-closed 返回 503。生产 composition 尚未注入 audit reader，因此当前默认 503。
- **验证状态：**定向 SQLite/API 测试因当前可用 Python 环境缺少 SQLAlchemy 未能收集；尚无测试通过结论。该切片不等于完整 Console 回归、生产数据库、多实例部署或浏览器 E2E。

### 15.179 React 重构后的快速工程门禁（2026-10-09）

- **验证：**在 `components/sentinel/dashboard-prototype` 运行 `npm run check:fast`，TypeScript、Prettier 检查、ESLint 与 Console OpenAPI 生成物检查全部通过；OpenAPI 当前 **42 paths / draft-partial**。
- **边界：**这是静态/工程快速门禁，不包含 logic/http 全套测试、构建、完整页面旅程、浏览器 E2E、Python Console 或真实服务验收。依照已拆分的节奏，不因本次验证再触发全套 E2E。

### 15.180 系统观察与审计模型定向逻辑验证（2026-10-09）

- **命令：**`npm run test:logic:focused -- 'SYSTEM-(PROBE|PROTOCOL|AUDIT)'`；`npm run test:http:focused -- 'SYSTEM-(CONNECTIONS|PROTOCOLS|AUDIT|AUDIT-INPUT|MOCK-SEED)'`。
- **结果：**逻辑 8/8、HTTP mapper/MSW 5/5 passed。覆盖连接探测范围与过期、协议协商/覆盖、audit UTC 半开范围与分页过滤、日期输入与精度、admin owner 撤权/迟到响应、Unicode tie-break 排序、wire 投影/输入边界及 mock scenario 一致性。
- **边界：**HTTP 测试使用 MSW，不证明 Python audit SQLAlchemy adapter 或真实 DB；自动化逻辑/HTTP 也不证明 React 页面渲染。完整逻辑矩阵及 browser E2E 仍按里程碑执行。

### 15.181 审计 requestId 跨层语义对齐（2026-10-09）

- **实现：**审计记录的 wire 字段统一为 `requestId`，表示持久化审计事件原始 HTTP correlation ID；与当前读取请求的 `x-request-id` 及命令幂等键 `requestKey` 明确区分。React strict schema、mock、页面、Python DTO/serializer/reader、OpenAPI 和跨层定向用例同步。
- **验证：**前端 `SYSTEM-AUDIT` 逻辑 **5/5**、`SYSTEM-(AUDIT|MOCK-SEED)` HTTP/MSW **3/3**；Python `test_system_audit_api.py` **5 passed**；`npm run check:fast`（类型、格式、lint、42-path OpenAPI contract）通过；Python `compileall` 与 `git diff --check` 通过。最初记录时缺少 SQLAlchemy，后续依赖同步与数据库 reader 验证见 §15.183。
- **边界：**HTTP/MSW 与 API/SQLite 测试均不证明真实 React → Python 部署链路或生产数据库。F6.1/F6.2 与最终真实链路验收状态不因字段更名而改变。

### 15.182 F4.22 登录凭据编辑后的错误恢复（2026-10-09）

- **实现：**Identity 的唯一 `AuthenticationWorkflow` 增加受限 `clearLoginFailure()`：仅清除已确定的 `error/conflict` 登录结果；登录仍 pending、session 已过期、登录成功但 session 回读失败、或 `result-unknown` 时不重置命令。登录页编辑用户名/密码时清除已知失败反馈并保留表单；未知结果继续要求显式会话检查，不能因修改输入而重复登录请求。
- **验证：**`npm run test:logic:focused -- 'F4\\.22'` **2/2 passed**，分别断言已知拒绝可清除且 access 仍为 anonymous、超时未知结果不能清除或再次派发；Codex 内置浏览器在 `http://localhost:5196/#/login?app=all&range=1h` 验证空表单必填提示、错误凭据的统一拒绝反馈、编辑密码后错误反馈清除；`npm run check:fast`（typecheck、Prettier、ESLint、42-path OpenAPI contract）通过；`git diff --check` 通过。
- **边界：**仅为登录页专项 IAB 检查，不是完整页面 E2E；没有测试真实 Python 登录链路、网络失败 UI、键盘/三语矩阵或生产服务。Python Login API 数据库定向测试见 §15.183；完整 E2E 仍只在相关里程碑执行。

### 15.183 Python Console 登录与审计 SQLite/API 定向验证（2026-10-09）

- **环境：**按 Console README 使用 `uv sync --extra test --extra sqlite-local`，只同步到包自己的 `.venv`；首次尝试使用沙箱不可写的用户 uv 缓存失败，改用 `/tmp/sentinel-console-uv-cache`。没有访问外部数据库或配置中心。
- **验证：**`.venv/bin/pytest -q tests/test_login_api.py tests/test_login_attempt_limiter.py tests/test_system_audit_api.py tests/test_system_audit_persistence.py` **29 passed**（5.53s）。覆盖登录成功/匿名拒绝/停用拒绝/CSRF-Origin、限流和数据库错误 fail-closed、SQLite 持久化/分页审计读取及 admin-only API。该结果补充 §15.181 初次执行时 SQLAlchemy 缺失的数据库验证空缺。
- **边界：**SQLite 是隔离测试数据库；不证明 PostgreSQL/MySQL 并发语义、生产配置与多 worker 限流、Console launcher composition、真实配置中心、React→Python 浏览器链路或完整 E2E。F4.22 与 B0.1/B0.2 仍未完成。

### 15.184 B0.1 配置源目录读取 API 首切片（2026-10-09）

- **实现：**依据 `readRegisteredSources` 与 `GET /api/v1/system/sources` 协议新增消费方 Reader Port、只读应用用例、冻结领域快照和 HTTP 投影。仅 admin 可读取；Nacos/Consul provider 专属字段分别投影为 `namespace`/`datacenter`。模型不含凭证或引用值字段；仅暴露认证模式与是否已配置凭证的布尔事实。没有 reader 注入或权威不可用时安全返回 `503 service_unavailable`，不推测空 registry、不探测远程 provider、不写入配置中心。
- **验证：**`PYTHONPATH=src .venv/bin/pytest -q tests/test_registered_sources_api.py tests/test_system_connections_api.py` **10 passed**；覆盖 Nacos/Consul wire 形状、UTC 毫秒、no-store、admin/view/匿名、无效 request-id、session/registry unavailable、endpoint/认证矛盾/重复 ID/超过 500 条/无时区时间拒绝，以及共用配置源 Provider 枚举后的系统连接回归。相关模块 `compileall` 与 `git diff --check` 通过。
- **覆盖更新：**OpenAPI 的 42 个 operation 中，`build_app` 可注册路由增至最多 **14/42**（比 §15.175 基线新增本路由）；这只是源码组合覆盖，不等于 14 个生产能力可用。source reader 没有生产持久化 adapter，默认组合仍返回 503，数据库表、Nacos/Consul 真实探测与写回、完整 React→Python 路径和 E2E 都未完成；B0.1 与 F6.2 继续不勾。详情见 [配置源目录读取验收记录](acceptance/R-DASHBOARD-B0.1-registered-sources-read.md)。

### 15.185 B0.1 观测环境/应用目录读取 API 首切片（2026-10-09）

- **实现：**依据 OpenAPI `readObservationCatalog` 增加 `GET /api/v1/observation/catalog`。消费方拥有的 `ObservationCatalogReader` Port 与只读用例由 `build_app` 显式注入；冻结领域值对象校验时区感知的采样时刻、非空标识/名称和每类最多 1,000 项。admin/view 登录角色可读，匿名请求拒绝；无事实源或 authority 不可用时返回脱敏 `503 service_unavailable`，不构造 demo fallback、不访问账号目录、不改变配置中心。
- **验证：**新 API 定向测试及系统观察相邻路由 `test_observation_catalog_api.py`、`test_system_connections_api.py`、`test_system_protocols_api.py`、`test_system_audit_api.py`、`test_registered_sources_api.py` **26 passed**；`compileall`、88 列检查和 `git diff --check` 通过。测试覆盖 admin/view 精确 wire 响应和 UTC 毫秒、`no-store`/`Vary: Cookie`、匿名/非法 request-id/session/authority 失败、安全 503 与目录值边界。
- **覆盖更新：**依 §15.184 的最大源码组合计数，OpenAPI 42 个 operation 中最多可注册 **15/42**。这只证明有对应受控路由，不代表当前存在生产 ObservationCatalogReader；默认仍为 `503 service_unavailable`，真实 catalog 持久化/采集装配、前后端 live 请求及浏览器 E2E 尚未验收。B0.1、F6.1/F6.2 与 B0.5 继续未勾。验收记录见 [B0.1 观测目录读取](acceptance/R-DASHBOARD-B0.1-observation-catalog-read.md)。

### 15.186 B0.1 实例目录读取 API 首切片（2026-10-09）

- **实现：**依据 OpenAPI `readInstanceCatalog` 增加 `GET /api/v1/instances`，包含 consumer-owned `InstanceCatalogReader`、查询用例、冻结领域事实与严格 HTTP 投影。目录 scope 仅接受 fleet/application，并与 `appId` 一致；host/container/process 属于详情 scope。校验分页、窗口、query identity、完整六项进程指标、覆盖质量、回执与 `processEpoch` 绑定及分页总数。admin/view 具备 `metrics:view` 可读；未知/重复/不合法 query 返回 `400 invalid_request`，权威目标缺失/限流映射为 404/429，reader 未装配/故障返回脱敏 503，不伪造空结果。
- **验证：**实例目录新测试与观测目录、系统连接/协议/审计、配置源读取相邻 API 共 **33 passed**；Console `compileall`、88 列检查、`git diff --check` 通过；前端 `npm run contract:check` 验证 OpenAPI **42 paths** 通过。未运行完整 E2E，遵守 §15.179 的快速/定向与里程碑验收节奏。
- **覆盖更新：**按 §15.185 的最大源码组合计数，最多可注册路由 **16/42**，但 `build_app` 仍无生产 `InstanceCatalogReader`，默认 503；生产 inventory/Reporter/Collector 装配、PostgreSQL/MySQL 持久化策略、真实 React→Python 联调和浏览器 E2E 均未验收。B0.1、F6.1/F6.2、B0.4 与 B0.5 继续未勾。详见 [B0.1 实例目录读取](acceptance/R-DASHBOARD-B0.1-instance-catalog-read.md)。

### 15.187 B0.1 实例详情与进程观测读取 API 首切片（2026-10-09）

- **实现：**依据 OpenAPI `readInstanceObservation` 增加 `GET /api/v1/instances/{instanceId}`，由独立 `InstanceObservationReader` Port、查询用例、不可变查询/MetricBundle/Series/Annotation/InstanceObservation 值对象和严格 serializer 组成。path `instanceId` 与 query 的 environment/app/processEpoch/scope/window/step 共同确定事实；详情 scope 仅 host/container/process。支持的 scope 必须带 query 一致的六项 operational metric summary+series；未支持的 scope 显式 `metrics: null`。receipt/identity/metrics 必须绑定同一 processEpoch；退休 incarnation、目标缺失、限流和 authority 不可用分别投影 410/404/429/503。与目录路由共享 query parsing 和实例 serializer，不复制 wire 投影。
- **验证：**实例目录/详情与观测目录、系统连接/协议/审计、配置源读取 API 定向套件 **37 passed**；Console `compileall`、88 列检查、`git diff --check` 通过；前端 `npm run contract:check` 的 42 paths 检查通过。覆盖 admin/view、精确 incarnation/query 回读、unsupported scope 无指标借用、非法 query 不触达 reader，以及 404/410/429/503 错误边界。本次没有 UI 改动，不启动完整 E2E。
- **覆盖更新：**最大源码组合增至 **17/42**。`build_app` 未注入生产 `InstanceCatalogReader` 或 `InstanceObservationReader` 时目录/详情均安全返回 503；生产 inventory/Reporter/Collector 事实装配、持久化/聚合策略、真实前后端部署联调及浏览器 E2E 未验收。B0.1、B0.4 和 B0.5 仍未勾。详见 [B0.1 实例详情读取](acceptance/R-DASHBOARD-B0.1-instance-observation-read.md)。

### 15.188 B0.1 通用指标查询 API 首切片（2026-10-09）

- **实现：**依据 OpenAPI `readMetrics` 增加 `GET /api/v1/metrics/query`。新增通用 `ObservationContext`/`MetricQuery`/`MetricBundle`/`MetricSeries`/annotation 领域约束和 consumer-owned `MetricsReader`；query 有界、严格拒绝未知/重复参数，指标选择逗号分隔且唯一，step 确保每条序列不超过 1,000 个点。只由 authority 提供指标/聚合结果；不自行计算 QPS/TPS/p95、填零或推断覆盖率。实例详情与通用指标查询共享 context/bundle serializer；缺省未装配 Reader 时返回 503。
- **验证：**目录、详情、通用指标 API 与系统连接/协议/审计、配置源及观测目录相邻 route 完整 Python Console 套件 **166 passed、1 skipped**；`compileall`、88 列检查、`git diff --check` 与 `npm run contract:check`（OpenAPI 42 paths）通过。仅为 Python API/领域与协议生成物验证，不包含 Reporter/Collector、真实 DB、浏览器页面或 E2E。
- **覆盖更新：**源码最大路由组合增至 **18/42**，不是 18 项生产能力。`MetricsReader` 尚未由生产聚合/时序存储装配；默认无 reader 返回 503，真实 telemetry 集成、React→Python 联调、部署和里程碑浏览器 E2E 均未验收。B0.1、B0.4、B0.5 持续未勾。详见 [B0.1 通用指标查询](acceptance/R-DASHBOARD-B0.1-metrics-query-read.md)。

### 15.189 B0.1 Fleet 总览读取 API 首切片（2026-10-09）

- **实现：**依据前端 `readFleet` 合同新增 `GET /api/v1/fleet/overview`。Fleet 查询值对象约束 fleet/application scope、UTC window、有限 step 与页参数；不可变快照校验 authority query echo、总体计数与当前分页边界、六类全局/应用指标、查询窗口、独立依赖健康事实。通过消费者拥有的 `FleetOverviewReader` 注入观测 authority；Route 负责 request-id/session/`metrics:view`、严格 query parse、稳定错误映射及 wire serialization。总数不从当前页推导，未接入指标不补 0。没有新增 GoF 模式或 demo fallback。
- **验证：**Fleet、观测目录、实例目录/详情/指标 API 定向套件 **26/26 passed**；覆盖 admin/view、匿名拒绝且 authority 未调用、fleet/application 精确 scope、重复/未知/非法 scope/越界查询、缺失/不可用 authority、404/429 错误映射和错误 query echo fail-closed。Python Console 源码与相关测试 `compileall` 通过，涉及 Python 文件 **88 列检查通过**。
- **覆盖与边界：**最大源码路由组合增至 **19/42**。`build_app` 尚未装配生产 `FleetOverviewReader`，默认仍返回 503；没有真实 inventory/telemetry 聚合、规则覆盖事实、Nacos/Consul/Collector probe、PostgreSQL/MySQL、React→Python live 页面或里程碑 E2E 证据。Fleet fixture 仅用于隔离 ASGI 合同测试；B0.1、F6.2、B0.4、B0.5 保持未勾。详见 [Fleet 总览读取验收](acceptance/R-DASHBOARD-B0.1-fleet-overview-read.md)。

### 15.190 B0.1 故障时间线读取 API 首切片（2026-10-09）

- **实现：**依据前端 `readIncidentTimeline` 合同增加 `GET /api/v1/incidents`。领域 DTO 固定四类结构化 caption、severity/category 枚举、半开时间窗口、scope identity、分页 cursor、全范围统计与 canonical 时间排序；不接收原始日志/异常文本，不推断因果。以消费者拥有的 `IncidentTimelineReader` 注入事实源；Route 负责会话和 `metrics:view`、未知/重复参数拒绝、边界解析、稳定错误码与 wire serializer。缺失 Reader 安全返回 503，无 demo fallback；本切片不含 evidence detail。
- **验证：**`test_incident_timeline_api.py` 与 Fleet、实例/观测目录相邻 API 定向套件 **31/31 passed**；覆盖 admin/view、匿名拒绝、fleet/process scope、severity/category、游标、UTC 时间和 pageSize、重复/未知/错误参数、authority 404/429/503、query mismatch fail-closed，以及结构化 fact 序列化。Python Console 源码及新测试 `compileall`、修改 Python 文件 88 列检查、前端 `npm run contract:check`（42 paths）及 `git diff --check` 通过。
- **覆盖与边界：**最大源码路由组合增至 **20/42**。`build_app` 尚未装配生产 `IncidentTimelineReader`，默认仍返回 503；Reporter/Collector 事件持久化、服务端过滤/游标、真实 Python 启动装配、React→Python live 页面及里程碑浏览器 E2E 未验收。隔离 ASGI authority fixture 只证明路由合同。B0.1、F4.16、B0.4、B0.5 保持未勾。详见 [故障时间线读取验收](acceptance/R-DASHBOARD-B0.1-incident-timeline-read.md)。

### 15.191 B0.1 故障事件证据读取 API 首切片（2026-10-09）

- **实现：**依据 `readIncidentEvidence` 合同新增 `GET /api/v1/incidents/{incidentId}/evidence`。复用 timeline 的结构化 IncidentFact/ObservedIncident 和共享严格 query parser；另设窄 `IncidentEvidenceReader` Port、只读用例与证据快照。事件 path ID、环境/scope/window/严重级别/类别必须精确回显；事件缺失或不匹配过滤由 authority 统一 404。模型约束 complete/partial/unavailable 与事实数量、事实 ID 唯一、suggested view 可用性；相关规则必须来自权威身份且匹配事件 application/publication/version，禁止基于文案或邻近时间推断。无生产 Reader 安全返回 503，不伪造证据或根因。
- **验证：**`test_incident_timeline_api.py` 当前覆盖 timeline/evidence 与 Fleet、实例/观测目录相邻 API **36/36 passed**；证据测试覆盖 admin/view/匿名、事件与 query 身份、明确关联规则、非规则事件不推断关联、过滤外事件 404 语义、分页 cursor 最大 512、UTC/结构化事实、400/404/429/503 与 fail-closed。Console `compileall`、涉及 Python 文件 88 列检查、前端 `npm run contract:check`（42 paths）与 `git diff --check` 通过。
- **覆盖与边界：**最大源码路由组合增至 **21/42**。未装配生产 `IncidentEvidenceReader` 时默认 503；Reporter/Collector 原始证据归档、证据时序关联的生产语义、数据库持久化、React→Python live 页面和里程碑 E2E 尚未验收。ASGI authority doubles 只证明合同适配。B0.1、F4.16、B0.4、B0.5 仍未勾。详见 [故障事件证据读取验收](acceptance/R-DASHBOARD-B0.1-incident-evidence-read.md)。

### 15.192 B0.1 规则绑定目录读取 API 首切片（2026-10-09）

- **实现：**依据前端 `readRuleBindings` 合同新增 `GET /api/v1/rulesets`。支持 environment、可选 app/kind/search 与显式分页；领域冻结值对象校验身份、类型、UTF-16 字符长度、filtered total/page 边界、唯一 ID 和精确环境/应用/类型过滤。`ReadRuleBindings` 校验 authority query echo；HTTP adapter 拒绝未知/重复/缺失参数、非 ASCII 十进制与越界分页，admin/view 登录用户可读，匿名用户拒绝。DTO 仅有脱敏 `location` 展示事实；不包含凭证/原始连接选项/规则正文，无 reader 时返回 503，不启用 demo fallback。
- **验证：**规则绑定、Incident timeline 与 Fleet overview 定向 API 套件 **24/24 passed**；覆盖 admin/view、query echo/filter/pagination、非法/重复/未知参数、匿名/会话故障、缺少 authority、404/429/503、错配响应 fail-closed 和敏感 location 拒绝。Console `compileall`、本切片 Python 文件 **88 列检查**、`npm run contract:check`（42 paths）与 `git diff --check` 通过。
- **覆盖与边界：**最大源码路由组合增至 **22/42**。尚未接入生产规则目录 authority、Nacos/Consul/DB 读取、React→Python live 页面或 rule snapshot/draft/version/deployment 后续接口；本次不运行完整浏览器 E2E，按验证节奏留至里程碑。B0.1 与 F4.16/F6.2 等业务验收不因合同 adapter 通过而勾选。详见 [规则绑定目录读取验收](acceptance/R-DASHBOARD-B0.1-rule-binding-directory-read.md)。

### 15.193 B0.1 规则权威快照读取 API 首切片（2026-10-09）

- **实现：**依据前端 `readRuleSetSnapshot` 合同新增 `GET /api/v1/rulesets/{bindingId}/snapshot`。领域使用不可变类型表达五类 Sentinel 规则，校验原生编码、数值约束、cluster window、参数例外与 caller 唯一性；Snapshot 校验完整记录数、记录 ID、绑定规则类别、checksum/revision 和时区时间。消费者拥有的 Reader Port 与只读用例要求 path binding 精确回显；serializer 将内部 snake_case typed DTO 投影为官方 camelCase 协议，不含凭证/原始连接参数。admin/view 会话可读，缺失 authority 默认 503，无空快照 fallback。
- **验证：**快照、规则绑定目录、Incident timeline 与 Fleet overview 定向 API 套件 **32/32 passed**；覆盖 admin/view、匿名/Session authority 故障、五类规则 wire 投影、binding mismatch fail-closed、原生规则值边界/重复 ID/毫秒精度、400/404/429/503。Console `compileall`、涉及 Python 文件 **88 列检查**、`npm run contract:check`（42 paths）与 `git diff --check` 通过。
- **覆盖与边界：**最大源码路由组合增至 **23/42**。生产规则源 adapter/持久化及 Nacos/Consul 回读未接入，reader 未装配时默认 503；草稿、版本、校验、发布操作和 React→Python live 页面继续开放。本轮没有执行完整 E2E，留到里程碑；B0.1/F4.16/F6.2 仍未因本适配器切片勾选。详见 [规则快照读取验收](acceptance/R-DASHBOARD-B0.1-rule-set-snapshot-read.md)。

### 15.194 B0.1 规则草稿集合读取 API 首切片（2026-10-09）

- **实现：**新增 `GET /api/v1/rulesets/{bindingId}/drafts`。领域不可变 DTO 覆盖完整保存草稿、基线 version/checksum、source revision、更新时间及 typed records；集合限制 1,000 个草稿，每个草稿最多 1,000 条规则。复用规则快照的五类 typed RuleRecord 与 wire serializer，避免宽泛 dict 和重复投影。`RuleDraftReader` Port/只读用例校验精确 binding，HTTP 层只允许 `rules:write` 会话（当前 admin），拒绝 viewer/匿名，缺少 reader 返回 503，不合成空列表。
- **验证：**草稿、规则快照、规则绑定、Incident timeline 与 Fleet overview 定向 API 套件 **39/39 passed**；覆盖 admin/view/匿名、跨绑定/重复 identity、集合上限、规则 kind、毫秒时间、错误映射和 reader 缺失。Console `compileall`、相关 Python 文件 **88 列检查**、前端 `npm run contract:check`（42 paths）与 `git diff --check` 通过。
- **覆盖与边界：**最大源码路由组合增至 **24/42**。草稿的生产 DB adapter/事务与多 worker 一致性、真实页面联调和 Nacos/Consul 配置源状态都未验证；缺失生产 reader 时仍安全 503。本轮未运行完整 E2E；单草稿读取、草稿写入/冲突、版本、校验、发布接口继续开放，B0.1/F7.1 不勾选。详见 [规则草稿读取验收](acceptance/R-DASHBOARD-B0.1-rule-drafts-read.md)。

### 15.195 B0.1 单条规则草稿读取 API 首切片（2026-10-09）

- **实现：**新增 `GET /api/v1/rulesets/{bindingId}/drafts/{draftId}`，用于打开选定草稿。为满足接口隔离，与草稿集合读取分设 `RuleDraftDetailReader` Port，但复用同一 `StoredRuleDraft` 模型、typed RuleRecord 和 wire serializer。admin (`rules:write`) 可读；view/匿名拒绝。bindingId/draftId 精确匹配，不匹配 fail-closed；非法 path 在触达 authority 前返回 400，缺 reader 默认 503。
- **验证：**草稿详情、草稿集合、规则快照、规则绑定、Incident timeline 与 Fleet overview 定向 API 套件 **42/42 passed**；覆盖 admin/view/匿名、路径校验、跨绑定/draft identity 错配、完整 typed payload、无 reader、404/429/503 与异常细节脱敏。Console `compileall`、相关 Python 文件 **88 列检查**、前端 `npm run contract:check`（42 paths）与 `git diff --check` 通过。
- **覆盖与边界：**最大源码路由组合增至 **25/42**。真实草稿持久化查询、生产启动装配、React→Python 页面路径和多 worker 一致性未验证；本轮未运行完整 E2E，留至里程碑。规则写入/冲突、版本、候选校验、发布等接口仍开放；B0.1/F7.1 不勾选。详见 [单草稿读取验收](acceptance/R-DASHBOARD-B0.1-rule-draft-detail-read.md)。

### 15.196 B0.1 规则版本集合与详情读取 API 首切片（2026-10-09）

- **实现：**新增 `GET /api/v1/rulesets/{bindingId}/versions` 与 `GET /api/v1/rulesets/{bindingId}/versions/{versionId}`。版本用不可变 typed DTO 表示完整规则记录、base version/checksum、名称/备注、UTC 创建时间和创建者；集合限制 1,000 个版本，每个版本最多 1,000 条规则。两个窄 Reader Port 由 Console 宿主显式注入；身份已登录即可读取，缺 reader 默认 503；路径与返回 binding/version ID 必须精确匹配，错误或错绑的 authority 结果 fail-closed。没有数据库或配置中心 adapter，也不实现冻结/发布。
- **验证：**版本、草稿列表/详情、规则快照/绑定、Incident timeline 与 Fleet overview 定向 Python 套件 **51/51 passed**；源码 `compileall` 通过、相关 Python 文件 88 列检查通过；前端 `npm run contract:check` 的 OpenAPI **42 paths** 对位通过。覆盖匿名拒绝且不触达 Reader、非法路径、admin/view 会话读取、完整记录序列化、UTC 毫秒、错配身份、无 reader、404/429/503 与异常内容脱敏；测试记录见 [规则版本读取验收](acceptance/R-DASHBOARD-B0.1-rule-versions-read.md)。
- **覆盖与边界：**最大源码路由组合增至 **27/42**。Reader 仍未连接生产规则存储/配置源，默认返回 503；B0.3 的持久版本权威、数据库/配置中心真实集成，及 React→Python 页面 E2E 仍未完成。未运行完整 Console 套件或 milestone E2E，按验证节奏留至里程碑；B0.1、B0.3、F7.1 均不因该切片打勾。

### 15.197 B0.1 规则发布记录列表与详情读取 API 首切片（2026-10-09）

- **实现：**新增 `GET /api/v1/rulesets/{bindingId}/publications` 与 `GET /api/v1/rulesets/{bindingId}/publications/{publicationId}`，覆盖发布记录列表与精确详情。领域 DTO 将候选校验、配置中心写入、配置中心回读作为互相独立的阶段；保留成功、失败、进行中、待处理和结果未知等状态，避免把“写入成功”混为“配置已回读/实例已加载”。列表/详情 Reader Port 分离，由宿主显式装配；无 reader 时安全返回 503。接口不接生产持久化、不执行配置中心写入、不证明实例生效。
- **验证：**规则发布、版本、草稿列表/详情、规则快照/绑定、Incident timeline 与 Fleet overview 定向 Python 套件 **61/61 passed**；前端 `npm run contract:check` 确认 OpenAPI **42 paths**；OpenAPI 中已有发布列表、详情及回执路径。本轮未运行完整 Console 测试或浏览器 E2E。
- **覆盖与边界：**最大源码路由组合增至 **29/42**。没有生产 publication authority/数据库 adapter/配置中心回读或实例回执；React→Python 真服务页面验收仍未完成。B0.1、B0.3、F7.1 保持未勾；详细证据见 [规则发布记录读取验收](acceptance/R-DASHBOARD-B0.1-rule-publications-read.md)。

### 15.198 B0.1 发布实例回执分页读取 API 首切片（2026-10-09）

- **实现：**新增 `GET /api/v1/rulesets/{bindingId}/publications/{publicationId}/receipts?page={page}&pageSize={pageSize}`，对齐 `readRulePublicationReceipts`。先读取并校验精确 publication，再读取分页回执；详情权限使用既有 browser-session read 边界。Domain 校验全量计数、expected/inventorySource 配对、页边界、页内唯一实例、当前页不超过聚合计数、应用状态与当前/已加载 process epoch/target version/checksum/时间的一致性。使用独立 `RulePublicationReceiptReader` Port；缺少 reader 安全返回 503。
- **验证：**发布回执、publication/version/draft/snapshot/binding、instance catalog、incident timeline、Fleet overview 定向 Python 套件 **80/80 passed**；`npm run contract:check` 验证 OpenAPI **42 paths**；`compileall`、相关 Python 文件 88 列和 `git diff --check` 通过。测试覆盖 viewer/admin 读取、匿名拒绝、重复/越界 query、未装配、publication/page/target 错配、applied 身份证据、未知 incarnation、总体分母/状态数和 404/429/503 脱敏映射。
- **覆盖与边界：**最大源码路由组合增至 **30/42**。生产 receipt/inventory authority、Reporter/Collector 持久 ingest、多 worker 一致性、真实 instance load 和 React→Python 页面联调均未证明；未运行完整 Console 套件或 milestone E2E。B0.1、B0.3、B0.4、B0.5 继续未勾。详见 [发布回执分页读取验收](acceptance/R-DASHBOARD-B0.1-rule-publication-receipts-read.md)。

### 15.199 B0.1 规则激活计划集合读取 API 首切片（2026-10-09）

- **实现：**新增 `GET /api/v1/rulesets/{bindingId}/plans`，对齐 `readRuleActivationPlans`。新增不可变 plan/collection DTO 与 `RuleActivationPlanReader`；校验唯一身份、binding 归属、最多 1,000 条、UTC 毫秒时间、递增激活窗口、目标/恢复版本不同、IANA 时区及有限 scheduler 状态。用例由 API session gate 调用；无 reader 默认 503。GoF 模式评估无适用模式，不增加额外抽象。
- **验证：**发布/回执/激活计划/版本/草稿/快照/binding/instance catalog/incident/Fleet 定向套件 **85/85 passed**；前端 `npm run contract:check` 对 OpenAPI **42 paths** 通过；Python `compileall`、相关文件 88 列检查、空白检查和 `git diff --check` 通过。未运行完整 Console 套件或浏览器 E2E。
- **覆盖与边界：**最大源码路由组合增至 **31/42**。没有生产 scheduler persistence、任务执行器或计划重启恢复；配置中心发布、实际恢复版本切换、实例加载和 React→Python 页面链路仍未验收。B0.1、B0.3、B0.5 保持未勾。详见 [激活计划读取验收](acceptance/R-DASHBOARD-B0.1-rule-activation-plans-read.md)。

### 15.200 B0.1 完整规则候选集差异读取 API 首切片（2026-10-09）

- **实现：**新增 `POST /api/v1/rulesets/{bindingId}/diff`，用不可变 `RuleSetCandidate` 表示完整候选，以现有五类 Sentinel typed value 做严格解析和领域验证；只读取 path 指定 binding 的当前快照，精确核对 profile/kind/version/checksum/source revision。新增、删除、替换按稳定 identity 计算，不触发草稿、版本或配置源写入；未知 baseline identity 和 stale base 返回 409。服务端对按输入顺序规范化的候选值计算 opaque SHA-256，不将其声称为 Nacos/Consul codec 校验或发布许可。共享 browser Origin/CSRF 校验提取为 API 内部 helper，并供既有账户命令与本人改密复用。
- **验证：**候选差异、snapshot、account command、own-password 定向 Python 套件 **29 passed**；`compileall`、新/改 Python 文件 88 列检查、`git diff --check` 与前端 `npm run contract:check`（OpenAPI 42 paths）通过。覆盖混合变化、路径/基线错配、权限/CSRF、五类规则、严格字段、authority 失败及 checksum 顺序语义。未运行全套或浏览器 E2E。
- **覆盖与边界：**源码最大路由组合增至 **32/42**。provider codec validation receipt、生产 snapshot authority、Nacos/Consul 发布/CAS/回读、live 页面和最终 E2E 仍未完成；B0.1、B0.3、F7.1 保持未勾选。详细范围见 [规则候选差异验收](acceptance/R-DASHBOARD-B0.1-rule-candidate-diff.md)。

### 15.201 B0.1 规则候选 profile 校验 route 首切片（2026-10-09）

- **实现：**增加 `POST /api/v1/rulesets/{bindingId}/validate`，复用严格候选 schema，并在 admin/rules:write、Origin、CSRF、request-id 校验后调用宿主 `RuleCandidateValidationAuthority`。Authority 合同明确要求按当前 source baseline/profile 校验并先持久化 receipt；Use case 校验返回的 binding/profile/base checksum/candidate checksum 必须与请求完全一致。新增不可变 receipt/issue 值对象，publishable 必须无 issue，issue code 有限、path 只允许 schema 字段路径；未注入 authority 安全返回 503，过期候选 409。
- **验证：**规则候选 validate/diff 定向 Python 测试 **18/18 passed**；Console `compileall`、新增/修改 Python 文件 88 列检查、`git diff --check` 通过；前端 `npm run contract:check` 确认 OpenAPI **42 paths**。覆盖成功及不可发布回执、错误路径拒绝、权限/CSRF、authority 缺失/不可用、陈旧冲突、错绑回执 fail-closed。未运行浏览器 E2E。
- **覆盖与边界：**源码最大路由组合增至 **33/42**，但 production 尚无 profile validator 或 durable receipt authority，默认 route 返回 503；不能据此认为可冻结或发布。Nacos/Consul 真实配置中心、生产 DB、React→Python live E2E 仍未完成。B0.1、B0.3、F7.1 保持未勾。详见 [候选校验 API 验收](acceptance/R-DASHBOARD-B0.1-rule-candidate-validation.md)。

### 15.202 B0.1 规则候选校验分责与 receipt 持久化（2026-10-09）

- **实现：**将旧的组合 authority 拆成明确应用层职责：当前 `RuleSetSnapshotReader` 提供权威基线，`RuleCandidateProfileValidator` 只做 profile 语义校验，`RuleValidationReceiptWriter/Reader` 管理持久事实。校验用例重新核对 binding/profile/kind/version/checksum/source revision，服务端生成 candidate checksum 与 validation ID；过期候选拒绝为 409。新增 SQLAlchemy receipt adapter 与 `0005_rule_validation_receipts` migration，receipt 和 `rules.validate` 审计事实单事务提交，数据仅包含校验身份、checksum、有界 issue code/field path、actor/request/time，不存规则正文或配置凭证。生产 profile validator、生产 compose 未配置时继续 fail closed（503）。
- **验证：**候选校验、候选 diff、receipt SQL adapter 定向测试 **21/21 passed**（隔离内存 SQLite，包含 migration、回读、非 publishable receipt、审计同事务与 DB 故障映射）；Console `compileall` 通过；前端 `npm run contract:check` 校验 OpenAPI **42 paths**。全量 Console suite 与完整浏览器 E2E 均未运行，按要求留到最终里程碑。
- **覆盖与边界：**最大可注册路由组合仍是 **33/42**。此切片没有 Nacos/Consul profile codec 校验、production SQL 方言运行、启动 composition、真实后端联调；本地 SQLite 证据不代表 PostgreSQL/MySQL。B0.1、B0.3、F7.1 保持未勾选；当前 route 若缺任一必要依赖仍返回 503。详见 [候选校验 API 验收](acceptance/R-DASHBOARD-B0.1-rule-candidate-validation.md)。

### 15.203 B0.2 首次配置源连通性检查 HTTP 安全切片（2026-10-09）

- **实现：**增加 `POST /api/v1/system/bootstrap/source-check` 与 `BootstrapSourceChecker` 应用端口。HTTP 层校验 request-id、精确 Origin、双提交 CSRF、当前 bootstrap operator 与严格 provider union；Nacos `namespace`、Consul `datacenter` 不混用；支持 no-auth、credential-reference、direct 三种模式。direct 凭证/reference 不进入 dataclass repr/equality，响应只回传有限可达性事实并带 `no-store`。数据库与配置源检查改为共用 bootstrap browser proof。checker 缺失或不可用均 fail-closed 返回 503。
- **验证：**source-check 与 database-check 定向 ASGI 测试 **11/11 passed**，覆盖 Nacos/Consul 凭证映射、权限拒绝前置、额外字段/错误 URL 拒绝、无 checker 与 checker 故障脱敏；Console `compileall` 通过。未运行 Console 全量套件或浏览器 E2E，按验证节奏留到里程碑。
- **覆盖与边界：**源码最大路由组合增至 **34/42**。本切片没有真实 Nacos/Consul connector 或 production composition；解析 URL 不是 SSRF 防护。生产 checker 仍必须实现 endpoint allowlist、DNS pinning、TLS identity、禁止 redirect 与有界 timeout；没有连接真实配置中心，也没有写入/注册规则源。B0.1、B0.2、B0.3 未关闭。详见 [配置源连通性检查验收](acceptance/R-SENTINEL-CONSOLE-B0.2-source-connectivity-check.md)。

### 15.204 B0.2 Bootstrap operator 授权交换 HTTP 切片（2026-10-09）

- **实现：**增加 `POST /api/v1/system/bootstrap/authorize` 与 `BootstrapAuthorizationAuthority` 注入端口。路由校验 request-id、精确允许 Origin、严格 write-only operatorCode，再委托部署 authority 原子执行 setup gate/code 验证、按可信 client address 限流和 opaque grant 创建；不实现进程内 fallback。成功只返回 `authorized:true`，设置最长 15 分钟、Secure/HttpOnly/SameSite=Strict grant 与 CSRF cookie；grant 值使用受限 URL-safe 字符并从 repr/equality 排除。拒绝、setup closed、限流、authority 故障分别返回稳定的 403/409/429/503。
- **验证：**authorize/source-check/database-check ASGI 定向测试 **16/16 passed**，覆盖格式/Origin 前置、Cookie 属性及期限、有限失败映射、无/不可用 authority fail-closed 和凭证不回显。未执行 Console 全量套件或浏览器 E2E。
- **覆盖与边界：**源码最大可注册路由组合增至 **35/42**。无 production authorizer 注入；setup window 的持久 owner、operator code provisioning/rotation、跨 worker rate limit/grant authority、启动装配和真实浏览器→Python 登录前置授权仍未验收。不得将测试 authority 当生产认证；B0.1/B0.2 继续开放。详见 [Bootstrap 授权交换验收](acceptance/R-SENTINEL-CONSOLE-B0.2-bootstrap-authorization.md)。

### 15.205 B0.1 管理员配置源无副作用检查 HTTP 切片（2026-10-09）

- **实现：**增加 `POST /api/v1/system/sources/check` 与 `RegisteredSourceChecker` 端口。HTTP 层要求有效会话/admin、精确 Origin、CSRF、严格 Nacos/Consul source schema；更新已有源的 `sourceId` / `expectedRevision` 必须成对，`keep` 凭证仅允许已有源。应用输入 secrets/reference 均不进入 repr/equality；响应只返回短期 checked/expires 时间、read/conditional-write/watch 有限 capability 或 finite failure reason。该操作不写 registry 或 rules，缺少 checker 503、rate limited 429。
- **验证：**source-check、account-command 与 bootstrap authorize/source-check/database-check 定向 ASGI 套件 **27/27 passed**；Console `compileall` 通过。OpenAPI contract 检查仍为 42 paths；未执行浏览器 E2E 或完整 Console suite。
- **覆盖与边界：**源码最大可注册路由组合增至 **36/42**。production checker 尚未接入；HTTP endpoint 语法检查不构成 SSRF 防护。endpoint allowlist、DNS pinning、TLS/redirect/timeout 策略、secret vault resolution、Nacos/Consul 真实能力探测、启动装配和写回 acceptance 仍开放。B0.1/B0.3 不勾选。详见 [管理员配置源检查验收](acceptance/R-SENTINEL-CONSOLE-B0.1-registered-source-check.md)。

### 15.206 B0.1 已登记配置源命令与原操作查询 HTTP 切片（2026-10-09）

- **实现：**在 `build_app` 注册 `POST /api/v1/system/sources/commands` 与 `GET /api/v1/system/sources/operations/{requestKey}`。新增不可变注册/条件更新命令、有限 operation 状态和值对象及 `RegisteredSourceMutationAuthority` port。写路径要求管理员会话、精确 Origin、双提交 CSRF、request-id、唯一 Idempotency-Key，并强制 header key 与 body requestKey 相同；更新要求 sourceId + expectedRevision。查询仅限管理员，并将 actor/session digest 传入 authority。成功/拒绝回执只包含有限状态和无秘密的 RegisteredConfigurationSource facts；未装配 authority 返回 503，不使用进程内假持久层。
- **验证：**配置源命令聚焦 ASGI 测试 **7/7 passed**（加入条件更新场景后）；加入该场景前，配置源命令/连通检查、账号命令、bootstrap authorize/source-check/database-check 组合测试 **33/33 passed**。Console `compileall`、前端 OpenAPI `contract:check`（42 paths）及 `git diff --check` 通过。完整浏览器 E2E 未运行，留至最终里程碑。
- **覆盖与边界：**Python 源码组合新增两条操作，最大覆盖从 **36/42** 到 **38/42**。本节只证明 HTTP/security contract；持久化与加密证据见 §15.207。Nacos/Consul 写入和 production 启动装配仍开放，B0.1/B0.3 不勾。详见 [已登记配置源命令验收](acceptance/R-SENTINEL-CONSOLE-B0.1-registered-source-commands.md)。

### 15.207 B0.1 配置源登记持久化、条件更新与凭证加密（2026-10-09）

- **实现：**新增 Alembic `0006_registered_sources`，建立配置源安全事实、加密凭证 envelope 和原始 operation 回执表。`SqlAlchemyRegisteredSourceStore` 同时提供 `RegisteredSourceMutationAuthority` 与 safe registry reader；管理员/会话/CSRF digest 在事务内重验，register/update 与 operation receipt/audit 同事务。更新使用 expected revision 条件写；幂等 replay 保存版本化 HMAC（支持旧指纹 key rotation），不同 payload 冲突；原始密码/token/reference 通过现有 AES-256-GCM + source-bound AAD 加密，操作表仅存安全结果，不存请求正文。`keep` 只在 provider 相同且 revision 匹配时保留现有 ciphertext。未把凭证传给 Nacos/Consul，也未新增进程内 fallback。
- **验证：**SQLite 内存 DB 执行全量 migration 后，registered-source store、真实 ASGI→SQLite 注册/目录读取/原回执路径、command HTTP、source-check ASGI 测试 **21/21 passed**；覆盖注册加密、可读事实、不回显明文、幂等重放/冲突、指纹 key rotation、条件更新/过期 revision、keep 凭证、not-found 回执、事务内管理员/CSRF/会话重验、操作读取隔离及 secret AAD 绑定。Console `compileall` 与 `git diff --check` 通过；完整浏览器 E2E 未运行，留至最终验收。
- **覆盖与边界：**仍为 **38/42** 路由。SQLite 仅验证 migration/事务语义，不代表 PostgreSQL/MySQL 并发、部署 key rotation、KMS/vault reference resolution、生产 application composition；Nacos/Consul real network write/read 仍未实现。B0.1/B0.2/B0.3 保持未勾选。详见 [配置源持久化验收](acceptance/R-SENTINEL-CONSOLE-B0.1-registered-source-persistence.md)。

### 15.208 B0.1 已登记配置源 `keep` 凭证解析与检查组合链路（2026-10-09）

- **实现：**增加 `RegisteredSourceCredentialResolver` Port 和 `CheckRegisteredSource` 应用用例。选择 `keep` 检查时，按 source ID、期望 revision 与 provider 精确读取 SQL 中的加密凭证；SQL adapter 以 source-bound AES-GCM AAD 解密成仅本次调用持有的 ephemeral input，再由应用用例覆盖本次表单编辑的 endpoint/location 后交给 checker。缺失/过期 revision、解密损坏或凭证解析 authority 故障均 fail-closed；HTTP 响应不包含凭证。`build_app` 显式注入 resolver，不存在隐式默认 provider。
- **验证：**聚焦 registered-source store、ASGI→SQLite→解密→fake checker、command API、check API **21/21 passed**；覆盖既有 Nacos 凭证按精确 revision 取回、对 endpoint/location 使用当前表单值、actor 透传、密码不进入 API 响应。该 checker 是测试替身，不是真实 Nacos 检查。
- **覆盖与边界：**仍为 **38/42** 路由。此切片证明已登记直连凭证的应用内解析路径，不证明外部凭证引用解析、生产 key/DB composition、Nacos/Consul 网络探测/写回、PostgreSQL/MySQL 并发或全量 E2E；上述仍留在最终里程碑验收。B0.1/B0.2/B0.3 不勾选。详见 [配置源持久化验收](acceptance/R-SENTINEL-CONSOLE-B0.1-registered-source-persistence.md)。

### 15.209 B0.1 配置源运行密钥配置与 SQL store 显式装配（2026-10-09）

- **实现：**增加 `RegisteredSourceKeyConfiguration.from_environment()`，显式读取部署注入的 AES-256-GCM active/retained key ring 与 source-command HMAC active/retained key ring；拒绝缺字段、重复 key ID、非 base64、AES key 非 32 字节、fingerprint key 小于 32 字节、active ID 不在 ring。keyring 放入只读 mapping，repr 不显示 key bytes。`compose_registered_source_store(engine, configuration)` 统一构造 cipher 并装配 SQL store；完整变量定义与轮换约束写入 Console README。
- **验证：**新增 key configuration/composition 聚焦测试 **3/3 passed**：active/retained key 解析、非法配置拒绝、repr 隐藏、active key AES-GCM 加解密及组合返回 SQL adapter；没有打开外部数据库连接。
- **覆盖与边界：**测试证明配置解析和对象组装，不证明生产密钥注入、DB URL/engine 启动、迁移生命周期、部署轮换演练、credential reference resolver 或 provider 网络连接。Console full launcher 与真实 Nacos/Consul adapter 仍未完成；B0.1/B0.2/B0.3 保持未勾选。详见 [配置源持久化验收](acceptance/R-SENTINEL-CONSOLE-B0.1-registered-source-persistence.md)。

### 15.210 B0.2 部署提供的 PostgreSQL/MySQL runtime URL 与 async engine 构造（2026-10-09）

- **实现：**新增 `ConsoleDatabaseConfiguration.from_environment()` 与 `create_engine()`，仅支持显式异步驱动 URL：`postgresql+psycopg`、`mysql+asyncmy`；强制 username/password/host/database，拒绝 SQLite 和同步驱动，不发生 dialect 回退。URL 对象不进入 repr；SQLAlchemy engine 启用 `hide_parameters=True` 与 `pool_pre_ping=True`。此模式适用于部署已提供的数据库连接，不执行连通检查或 migration，也不替代首次 Setup 页面保存 locator。
- **验证：**runtime database URL 聚焦测试 **3/3 passed**，覆盖 PostgreSQL/MySQL URL 解析、SQLite/同步驱动/缺失字段拒绝、repr 密码脱敏及 engine factory 调用参数。engine factory 由测试 spy 替代，未连接数据库。
- **覆盖与边界：**未实现 driver-extra 安装验收、真实 PG/MySQL、生产 launcher/lifespan/engine disposal、migration 编排、首次初始化外置 runtime locator/setup-window/completion-marker owner。B0.1/B0.2/B0.5 不勾。详见 [Runtime database URL 验收](acceptance/R-SENTINEL-CONSOLE-B0.2-runtime-database-url.md)。

### 15.211 F4.22 登录网络失败与未知写入结果的安全反馈（2026-10-09）

- **实现核对：**登录写请求一旦 dispatch 后遇 `NETWORK`/超时，通用 `CommandResource` 将其定义为 `result-unknown`；`loginFeedback` 优先显示未知结果，并提供显式“检查当前会话”，不会让改输入清除未知状态或自动再次派发。bootstrap/session 只读网络失败落到 `access.phase=unavailable`，单独显示控制台状态不可用和显式检查动作。确认这种区别优于把登录 POST 网络故障文案写成可直接重试的“连接失败”。
- **验证：**新增 `F4.22` 定向 logic 用例，断言 NETWORK 失败不会被当作已知拒绝、不能重放；会话检查恢复后才清除未知状态。`I18N-DYNAMIC-PRESENTATION` 定向测试 **1/1 passed**，核对读取不可用与写入未知两种反馈及三语动态文案；`npm run check:fast` 的 typecheck、Prettier、ESLint、OpenAPI **42 paths** 检查通过。未运行浏览器 E2E。
- **边界：**验证覆盖 workflow/presentation 的隔离代码路径，不证明用户页面、真实 Python 服务和部署链路；F4.22 继续未勾，完整页面与跨层验证留至最终验收。

### 15.212 F4.29 角色切换复用应用级导航保护（2026-10-09）

- **实现：**移除 `RoleManagementPage` 自己维护的 dirty flag / “切账号丢弃” Dialog。角色选择只发起带 account ID 的 URL 导航；未保存草稿、待确认写入等保护统一由 `NavigationBoundary` 读取 `NavigationProtectionRegistry` 决策，草稿丢弃仍由 `RoleEditor` 注册的 discard callback 执行。这样同一切换不会先经过页面确认、再被应用级保护重复拦截；账号深链和无默认账号回退策略不变。
- **验证：**`npm run test:logic:focused -- 'NAVIGATION'` **7/7 passed**，覆盖 dirty push/replace 在确认前不改变 URL、取消保留输入、确认后才导航，以及 pending/unknown 写入时锁定不允许丢弃；`npm run check:fast` 的 TypeScript、Prettier、ESLint 与 OpenAPI **42 paths** 均通过。未运行浏览器 E2E，按既定节奏留到最终里程碑验收。
- **边界：**该改动统一了两层确认所有权，不等于完成角色页面保存成功/拒绝/冲突/unknown、停用/空目录和硬刷新语义验收；F4.28/F4.29 仍保持未勾。

### 15.213 F4.28 快速切换账号时丢弃迟到详情（2026-10-09）

- **实现/验证：**为账号 workflow 增加竞态回归：账号 `one` 的详情读取挂起时切到 `two`，先让 `two` 成功、再释放 `one`；前一请求以 `CANCELLED` 结束，公开 detail 仍是 `two`。`npm run test:logic:focused -- 'ACCOUNT-SELECT'` **1/1 passed**。
- **边界：**该用例证明 workflow/query-resource 代次隔离，不是 React 页面渲染或浏览器 URL 的 E2E；disabled/空目录、服务端冲突和最终 IAB 页面验收仍未完成，F4.28 保持未勾。

### 15.214 F4.28 角色账号目录搜索与分页（2026-10-09）

- **实现：**角色绑定页移除“首 100 个账号”的固定目录限制，改为复用账号目录 Port 的服务端 search/page/pageSize 查询，默认每页 20 条；搜索回到第一页，上一页/下一页保留当前筛选。当前 URL target 即使不在当前页/筛选结果中，也保留为独立选项；详情未确认时不自动改选其他账号。账号变化仍只发起导航，由应用级保护处理未保存草稿。
- **验证：**账号 list/filter 与新加的账号详情迟到响应竞态 focused logic **3/3 passed**；`npm run check:fast` 的 TypeScript、Prettier、ESLint 和 OpenAPI **42 paths** 检查通过。完整 E2E 未运行，遵循最终验收节奏。
- **边界：**当前只验证目录查询合同与导航/URL 状态所有权；未用页面运行时或 IAB 验证搜索、翻页、长账号名、窄屏布局和键盘操作。F4.28 继续未勾。

### 15.215 F5.2 共享 UTC 本地化格式器收口（2026-10-09）

- **实现：**扩展 `shared/presentation/utcDateTime.ts`，以共享格式器统一 UTC epoch 的 locale-aware 展示，并支持显式日期/时间样式及按场景决定是否附加 `UTC`。账号最近登录、实例目录、依赖探测及观测上下文已改为复用该格式器；协议时间戳和查询边界仍保持原始 UTC instant，不因界面语言改变。
- **验证：**聚焦逻辑测试 `npm run test:logic:focused -- 'F5\\.2 (observed UTC instants|shared UTC formatter)'` **2/2 passed**，覆盖 zh-CN/en-US/ja-JP、紧凑日期样式、UTC 标记职责与跨夏令时日期附近的瞬时时间不变；`npm run check:fast` 的 TypeScript、Prettier、ESLint、OpenAPI **42 paths** 检查通过。没有运行浏览器 E2E，按约定留到最终验收。
- **边界：**仅证明格式化器和调用点编译/逻辑合同，未证明页面语言切换时视觉呈现、DST 表单交互、URL/草稿保持；F5.2 继续未勾。

### 15.216 F5.6 图表 renderer 延迟加载（2026-10-09）

- **实现：**`TrendChart` 不再静态导入 `@nivo/line`，改由 React `lazy` 在图表有样本且实际渲染时请求 renderer；`Suspense` 加载态使用固定图表高度内的本地化状态，不改变数据映射、Nivo 参数或缺测/空态规则。
- **验证：**`npm run check:fast`、`npm run i18n:check` 通过（三语各 **1,148** keys，静态 **1,011** keys，**19** 个动态调用仍由类型约束且需 producer runtime 证据）；production `npm run build` 成功；新增 `BUILD-CHART-LAZY` focused build-profile **1/1 passed**，断言 Nivo 不在初始闭包、可从 deferred import 到达且报告测量到独立 chunk。manifest 将 Nivo 输出为独立 `nivo-line` deferred chunk（**333,738 B / gzip 113,267 B**）；初始闭包为 JS **757,204 B / gzip 226,878 B**、CSS **218,005 B / gzip 38,305 B**，总计 **975,209 B / gzip 265,183 B**。构建仍提示超 500 KB chunk；本改动只证明加载拆分，不宣称交互延迟改善。
- **边界：**没有运行完整 E2E 或浏览器，也没有证明 pending 文案在真实页面的可见时长、图表加载失败恢复或图表页面性能指标；留至最终 Codex IAB 验收。F5.6 保持未勾。

### 15.217 F5.6 首屏认证与首次初始化代码分包（2026-10-09）

- **实现：**把 identity access 与 bootstrap setup 的 URL/schema/HTTP adapter 分成独立模块；应用启动和认证只导入 bootstrap/session/login/logout 合同，setup 路由单独导入初始化授权、数据库/配置源检查和初始化命令。原兼容 wire/endpoint/HTTP 汇总模块仍供合同生成与既有测试使用，但应用路由不从宽 barrel 引入。`WriteOnlySecretSchema` 也独立于 provider-specific configuration-source schema，避免认证只读通用凭证形状时拖入 Nacos/Consul setup union。
- **验证：**`npm run check:fast` 通过（typecheck、format、lint、OpenAPI `42 paths`）；身份 HTTP/MOCK 聚焦套件 **11/11 passed**、F2.4 setup/auth owner logic **1/1 passed**；production `npm run build` 成功；新增 `BUILD-SETUP-LAZY` manifest 闭包回归 **1/1 passed**，断言 database-check、source-check、bootstrap initialize 仅出现在动态闭包、不在首屏静态闭包。初始 JS 为 **743,767 B / gzip 222,695 B**，较 §15.216 所记录构建减少 **13,437 B / gzip 4,183 B**；懒加载 setup 的增量闭包测得 **61,486 B JS / gzip 23,008 B**。完整 E2E 按节奏留到全部代码完成后的最终验收。
- **边界：**包体差值证明构建产物依赖边界发生变化，不证明首屏下载/交互时延或页面实际呈现改善；没有运行浏览器或全量回归。`BUILD-SETUP-LAZY` 依赖生成的 production manifest，需在构建后执行。F5.6 继续未勾选。

### 15.218 F7.6 当前 production build 到隔离 Python wheel 的资源核验（2026-10-09）

- 实现/验证：基于当前 dist/client 运行 node scripts/package-console-assets.mjs，在拥有 .dashboard-assets.json 的生成目录内刷新 76 个资源（2,128,797 bytes）。以 uv build --no-cache --no-build-isolation --out-dir private-temp 生成 sdist/wheel；独立解读 wheel 内 marker，验证列出的 76/76 文件均存在且逐项 byte count/SHA-256 一致。将 wheel 安装到独立临时 target（不安装依赖、不使用 Node），以 Console 自有虚拟环境运行静态 ASGI 测试，4 passed；覆盖 wheel 包资源发现、根与 deep-link、未知 /api JSON 404、prefixed ASGI asset/deep-link、cache headers 和 non-canonical path 拒绝。BUILD-LIVE + BUILD-SETUP-LAZY focused 2/2 passed，确认 production wheel 来源构建不含 Mock worker/handlers，初始化专属 endpoint 仍在 setup 延迟闭包；Console compileall 通过。
- 边界：证明当前 wheel 中静态资产完整并能由 Python ASGI 静态路由提供，不证明 production CLI/lifespan、代理部署前缀改写、浏览器实际渲染、Python API 全链路或外部依赖验收。未跑 E2E，也未启动监听服务；完整 E2E 留到所有代码完成后。F7.6 与 B0.6 保持未勾选。

### 15.219 B0.2 登录限流策略部署配置解析切片（2026-10-09）

- **实现：**新增 `LoginAttemptLimitConfiguration`，从 `SENTINEL_CONSOLE_LOGIN_FAILURE_THRESHOLD`、`SENTINEL_CONSOLE_LOGIN_FAILURE_WINDOW_SECONDS`、`SENTINEL_CONSOLE_LOGIN_BLOCK_DURATION_SECONDS` 显式读取无默认值策略；缺失、非规范整数、零/负数与超范围配置均 fail closed。配置只持有阈值与时间，不包含客户端身份或密钥；`to_policy()` 复用现有 `LoginAttemptLimitPolicy`，没有重写 SQL 限流状态机。新增 `compose_sql_login()`，将现有 SQL credential/session/limiter adapters 与 Argon2 service 注入原 `Login` use case；调用方仍显式传入 engine、限流策略和 session TTL。
- **验证：**Console 定向 pytest **5/5 passed**；覆盖配置解析正/负例与 composition 将 engine/policy/session TTL 传给既有 ports/use case。新增模块与测试 `compileall` 通过；未连接数据库、未启动应用，也未运行完整 E2E。第一次 `uv run --offline` 因沙箱不能访问用户级 uv cache 未执行，改用项目现有 `.venv/bin/python` 完成同一范围的测试。
- **边界：**已完成 SQL 登录依赖组装函数，但 production ASGI/lifespan 仍未调用它，也未将配置接入可运行的服务入口；HMAC identity key、限流 env 部署/轮换、可信代理配置及真实数据库并发未验。因此 B0.2 不勾。下一步将继续完成 Console runtime/lifespan composition，同时不虚构首次 setup 的持久化 owner。

### 15.220 B0.2 账号命令 HMAC 密钥配置与 SQL 组合切片（2026-10-09）

- **实现：**新增 `AccountCommandKeyConfiguration.from_environment()`，读取账号命令 fingerprint active key ID 与 active/retained HMAC key ring；校验 key ID、base64、重复 ID、最小 32-byte key、active key 必须存在，配置映射不可变且 repr 隐藏 key bytes。新增 `compose_sql_account_commands(engine, configuration)`，复用现有 SQL 事务 store、Argon2 hasher 与 `MutateAccount` 用例，不新增命令业务规则。
- **验证：**账号命令 key 配置、client identity key、SQL identity composition 与既有登录 composition 定向测试 **11/11 passed**；覆盖缺失/无效配置、重复 key ID、短 key、active key 不匹配、密钥不回显/keyring 不可变、composition 参数透传及核心 identity routes 注册。目标源码与测试 `compileall` 通过；未创建数据库连接、未启动监听服务、未执行 E2E。
- **边界：**README 已记录部署环境变量及保留旧 HMAC key 的轮换要求；production launcher/lifespan 尚未调用账号命令 composition，也未完成 PostgreSQL/MySQL 多 worker 并发和部署密钥轮换演练。**B0.2 继续未勾。**本切片仅证明安全配置解析与显式对象装配。

### 15.221 B0.2 SQL 身份服务组合入口（2026-10-09）

- **实现：**新增 `ClientIdentityKeyConfiguration`，严格读取独立的登录客户端身份 HMAC key，要求 base64 解码后至少 32 bytes 且 repr 不显示 secret。`compose_sql_identity_runtime()` 统一装配账号目录、当前会话读取/撤销、登录、账号命令和本人改密能力，复用同一个 `PasswordHashService`；`build_sql_identity_app()` 将这些 SQL-backed capability 接入现有 `build_app`，并使用 SQL bootstrap initialized reader。setup-window、bootstrap operator/session verification 与 initialize write authority 继续由部署显式提供，不采用内存缺省或推断未初始化。
- **验证：**账号命令 key、client identity key、SQL identity composition 与已有登录 composition 定向测试 **11/11 passed**；目标 Python 模块 `compileall` 通过；88 列检查无超长行。未建立 DB 连接、未运行 migration/ASGI server 或完整 E2E。
- **边界：**composition 仅适用于 schema 与身份初始状态已经准备好的数据库，engine/migration/lifespan 仍归调用方；setup-window 与跨资源 bootstrap 初始化 owner 尚未实现。没有 PostgreSQL/MySQL 真服务、多 worker 或 React→Python 浏览器验收，**B0.2 继续未勾**。README 已列出运行配置及边界。

### 15.222 B0.1/B0.2 SQL 注册配置源装配（2026-10-09）

- **实现：**扩展 `build_sql_identity_app()`：显式提供 `RegisteredSourceKeyConfiguration` 时，使用 deployment-owned keyring 组装 `SqlAlchemyRegisteredSourceStore`，并将它作为 registry reader、mutation authority、原凭证 resolver 接入 `build_app`；checker 保持独立显式注入，未配置仍安全 503。无 key configuration 时不构造凭证加密/store，也不提供进程内替代数据。
- **验证：**identity composition 定向用例覆盖 source key config→SQL store→三个既有 ports 的装配透传；同批组合测试及 route-registration 检查 **11/11 passed**。未打开数据库连接、未执行 migration、未访问配置中心或运行 E2E。
- **边界：**打通已有 SQL registry adapter 与 ASGI composition，不等于生产 `create_engine`/lifespan/迁移入口已经完成；checker 未提供时连接测试拒绝服务，Nacos/Consul 真实安全探测和 conditional write 仍未实现。B0.1/B0.2/B0.3 保持未勾。

### 15.223 B0.1 Nacos/Consul 有界只读连通检查适配器（2026-10-09）

- **实现：**新增 `RegisteredSourceTargetPolicy`，由部署显式配置 provider/hostname/port/CIDR allowlist，解析后要求 DNS 所有答案均获准并以 pinned resolver 固定目标；新增 aiohttp JSON transport，关闭环境代理继承与 redirect，验证 TLS 主机身份，限定 3 秒请求超时与 64 KiB 响应体，认证连接强制 HTTPS。Nacos 适配器使用 Nacos 3 `/v3/auth/user/login` + `/v3/admin/cs/config/list` 验证命名空间只读列表；Consul 适配器以 GET `/v1/kv/?keys=true` 做短 blocking query，根据 `X-Consul-Index` 回报 WATCH。两个适配器均不写规则、不声称 conditional-write。`build_sql_identity_app()` 支持显式注入 target rules 后装配生产 checker；未给出 allowlist 时不建立默认网络权限。Opaque credential reference 暂时 fail-closed，等待部署 Secret resolver。
- **验证：**source checker target/adapter 聚焦测试 **8/8 passed**，并与现有 API/store 套件合计 **14/14 passed**；覆盖混合 DNS 拒绝、域名 pin、认证 HTTP 拒绝、Nacos 只读鉴权与不泄密、Consul GET/read/watch 判定及 resolver host/port 约束。没有监听真实 socket（沙箱禁止 bind），没有访问真实配置中心、数据库、浏览器或完整 E2E。
- **边界：**证明实现和测试替身契约，不证明 Nacos 3 / Consul 的真实实例兼容、身份插件/ACL 差异、运维 CIDR allowlist 配置正确、TLS 证书部署或 Secret reference resolver。没有绑定具体 dataId/key 的连接输入，READ 是 namespace/全局 key-list 的只读可访问性检查，不代表某个规则条目已校验。真实双配置中心验证留给里程碑。B0.1/B0.2/B0.3 继续未勾。

### 15.224 F4.20 初始化字段级错误归属与复核回跳（2026-10-09）

- **实现：**`SetupIssue` 附加 `SetupField` 归属；DB 缺失值逐字段返回，Nacos 用户名/密码分别返回必填问题，其它地址、凭证引用、Consul token、端口、管理员密码与确认均关联到各自控件。Flow 只记录用户已尝试校验的步骤，字段错误从当前 draft 实时重算；用户改正一项时仅移除已不成立的错误，其余问题继续呈现。完成提交复核时依据首个拥有字段的错误回到对应步骤。Wizard 投影到字段级 Astryx `TextField.error`，三语通用必填文案和全局错误摘要位于 locale JSON。
- **验证：**`npm run test:logic:focused -- SETUP` **15/15 passed**；`npm run typecheck`、`npm run format:check`、`npm run lint`、`npm run i18n:check` 通过。新增测试覆盖多个 DB 缺项、管理员字段、规则源引用归属和修复步骤解析。
- **边界：**只验证纯模型、TypeScript、格式/lint 与 locale 完整性；未运行 rendered UI/IAB/完整 E2E，未接真实 Python、数据库或配置中心。尚未证明长翻译/窄屏下错误控件视觉布局；网络错误和秘密清除全矩阵也未闭环，F4.20/F4.21 保持未勾。

### 15.225 F4.26 账号启停命令成功/拒绝路径聚焦合同（2026-10-09）

- **验证：**新增 workflow tests 验证确认停用命令只携带选定账号的服务端 ID、当前 revision 和 service-owned request key；只有 correlated `completed` 后才失效/重读当前目录并看到新状态。对并发产生的 `last_admin` 拒绝，mutation 维持 conflict、反馈映射 `management.lastAdmin`、目录仍保留停用前事实。与纯模型保护测试合计 `ACCOUNT-STATUS` focused **4/4 passed**。
- **门禁：**`npm run typecheck`、`npm run format:check`、`npm run lint` 通过。未运行浏览器 E2E，遵循最终一次执行；也没有真实 Python/数据库，因此这不是事务、revision fencing 或多会话最后管理员验收。F4.26 仍不勾。

### 15.226 F5.2 规则计划 DST 时刻选项的本地化投影（2026-10-09）

- **实现：**将 `RulePlanFields` 中重复时刻的选项投影提取到 `features/rules/presentation/scheduleTime.ts`。标签按当前 locale 格式化，并明确附 UTC；提交值仍是 UTC epoch-millisecond 字符串，不从本地化标签反推协议值。选项和值对象冻结，非法负数/非安全整数时刻拒绝。
- **验证：**`npm run test:logic:focused -- SCHEDULE-LOCALE` **1/1 passed**，覆盖纽约 DST 回拨的两个 occurrence、三种 locale、显式 UTC、协议 option value 不变和非法时刻拒绝。`npm run check:fast` 的 typecheck、format、lint、Console OpenAPI **42 paths** 检查通过；完整 E2E 留在全部实现后的最终验收。
- **边界：**这是 presentation 投影与纯逻辑测试，不是语言切换时保留真实页面草稿/URL 的浏览器证明；该矩阵仍未闭环，F5.2 保持未勾。

### 15.227 B0.1 规则工作流命令与原操作读取 HTTP 首切片（2026-10-09）

- **实现：**新增冻结的规则变更 command/application contract，明确覆盖 `save_draft`、`delete_draft`、`freeze_version`、`publish`、`create_plan`、`cancel_plan` 六类现有 OpenAPI 命令；HTTP parser 对 body/variant 字段严格拒绝缺失或额外字段，并核验 binding、幂等键与 UTC 毫秒计划时间；版本校验回执 ID 由 parser 按身份字段解析，实际回执存在性和归属必须由 authority 验证。新增管理员写命令 `POST /api/v1/rulesets/{bindingId}/commands` 与管理员原操作回读 `GET /api/v1/rulesets/{bindingId}/operations/{requestKey}`。写入需有效 request-id、Origin、CSRF、admin session，`Idempotency-Key` 必须与 body `requestKey` 精确一致；authority 同时收到 actor、session/CSRF digest 和 request ID，回查按原 actor/session/binding/key 限定。操作投影只允许 typed result / finite rejection reason，不输出异常详情或秘密。缺 authority 时 fail-closed 返回 503，不使用进程内模拟状态。
- **验证：**规则命令 HTTP + 六类严格 parser 测试 **8/8 passed**；并与草稿、版本、发布、激活计划、候选校验/差异、快照和绑定 API 套件合计 **80/80 passed**。涵盖 admin accepted/pending、幂等冲突先于 authority、view 写/读拒绝、原操作者 session digest 传递、authority 缺失 503、六种 command DTO，以及额外字段/未知 kind/绑定不匹配/非法 UTC 时间拒绝。目标源码 `compileall`、前端 `npm run check:fast`（包括 OpenAPI 42 paths）、`git diff --check` 通过。完整 Console/browser E2E 未运行，留至全部代码完成后的最终里程碑。
- **覆盖与边界：**按 §15.209 前最大源码注册集合 **38/42** 计，本切片增加两个 method/path operation，最大可注册数 **40/42**；剩余 `POST /api/v1/system/bootstrap/initialize` 与 `GET /api/v1/system/bootstrap/operations/{requestKey}` 尚未实现。没有规则命令 durable authority、版本/发布/计划 SQL workflow、配置中心条件写入、Nacos/Consul 回读、生产 startup/lifespan composition 或浏览器→Python 验收；本切片只交付 HTTP/auth/parser/serializer 边界，不宣称规则可保存或发布。B0.1/B0.3/F7.1 仍未勾。验收记录见 [规则命令 HTTP 首切片](acceptance/R-SENTINEL-CONSOLE-B0.1-rule-commands.md)。

> 注：上述规则命令切片增加源码可注册操作总数至 40/42；此前最近的配置源持久化章节 §15.207/§15.208/§15.209 所述 38/42 是当时历史基线，不作回写。

### 15.228 F5.2 语言切换与规则页面所有权聚焦保护（2026-10-09）

- **实现：**新增架构回归断言，锁定 locale 仅作为页面展示输入；`RouteBoundary` owner identity 仍由 route + server session epoch 构成，Header 的语言切换不发导航，规则 binding key / draft workflow owner 不依赖 locale。避免后续 i18n 改造重建草稿或改写 URL 的回归。
- **验证：**`node --test --test-name-pattern='F5.2 changing display locale' tests/architecture/dependencies.test.mjs` **1/1 passed**。完整 architecture suite 首轮发现身份 API 绕过 feature 公共出口的问题；将 `consoleAuthentication` 与 `SetupRouteOwner` 改为从 `features/identity/http` 装配后，architecture suite **21/21 passed**，`npm run typecheck`、`git diff --check` 通过。未运行浏览器 E2E，遵循最终验收节点执行。
- **边界：**该测试证明源码所有权边界，不是实际渲染的浏览器行为证据；Rule draft 页面切换 zh-CN/en-US/ja-JP 后表单值、dirty 状态、URL 和协议枚举仍需最终 E2E / Codex 内置浏览器验证，F5.2 继续未勾。

### 15.229 F4.08 规则深链快照读取取消与迟到结果保护（2026-10-09）

- **实现：**将 `RuleBindingOwner` 的裸 `useEffect`/`AbortController` 快照读取改为规则 feature 的 `createRuleBindingSnapshot` + 既有 `useQueryResource`。资源绑定当前 selected ID，复用代次保护、session access owner、错误分类与查询反馈；错误/无效深链现在有显式读取状态和重试，不再静默留白；URL target A 的迟到响应即使底层 Port 忽略 abort，也不能覆盖 target B。
- **验证：**规则 binding 逻辑聚焦 **6/6 passed**，新增覆盖“Port 忽略 abort 的迟到 A 不覆盖 B”与“响应 binding ID 不匹配拒绝”。`npm run check:fast` 通过：typecheck、format、lint、Console OpenAPI 42 paths。
- **边界：**无浏览器运行；URL 快速切换、错误重试的真实 React 渲染以及不同 binding 草稿完整交互留到最终 Codex 内置浏览器 E2E。本节只记录 F4.08 的规则 binding 深链读取补强，不改变 F4.28 账号角色项状态。

### 15.230 F4.28 角色深链 fallback 读取状态不误报（2026-10-09）

- **实现：**角色页当前 URL 账号不在目录已加载页时，fallback 选项文案改为由详情 `QuerySnapshot` 状态决定：只有 authoritative `empty` 显示未找到；`error`、`denied`、`stale` 与无当前目标证据的 loading/旧目标状态分别映射失败、权限、陈旧和读取中。避免页面切换或请求失败时把旧快照误投影为账号不存在。
- **验证：**`npm run test:logic:focused -- 'ROLE-TARGET-COPY'` **1/1 passed**，覆盖 empty/error/denied/stale 与 idle/loading/refreshing/ready/filtered-empty；`npm run check:fast` 通过：typecheck、format、lint、Console OpenAPI 42 paths。
- **边界：**未运行浏览器；当前页面 fallback 的实际视觉呈现、账号目录页面筛选/分页、disabled/空目录及完整草稿生命周期留到最终 Codex 内置浏览器验收，F4.28 保持未勾。

### 15.231 F4.28 角色编辑限制原因国际化提示（2026-10-09）

- **实现：**角色编辑器在停用账号、内置账号或最后一个有效管理员被保护而锁定时，显示对应 warning 提示；优先展示“账号停用”，再展示内置账号保护、最后管理员保护。提示由纯 presentation projection 从已读取的账号事实生成，不改变前端或服务端授权决策；简体中文、英文、日文资源同步新增。
- **验证：**`npm run test:logic:focused -- 'ROLE-RESTRICTION-COPY'` **1/1 passed**，覆盖三类限制、无约束账号及限制优先级；`npm run i18n:check` 通过，三语各 1153 键、插值一致；`npm run check:fast` 通过：typecheck、format、lint、Console OpenAPI 42 paths。
- **边界：**未运行浏览器；提示在不同 viewport/键盘/真实后台授权下的渲染未验证，F4.28 仍未完成。

### 15.232 F4.29 远端角色刷新与本地草稿基线协调（2026-10-09）

- **实现：**新增纯模型投影 `reconcileRoleDraft`。同一账号的新权威记录到达时，干净本地草稿更新到远端 role/revision；脏草稿继续保留用户选择和原 revision，使现有冲突提示与服务端条件写入继续生效；记录目标 ID 不匹配时建立新目标基线。RoleEditor 将 reconciled draft 用于渲染、保存、dirty 判断与角色规则校验，不通过 Effect 延迟同步。
- **验证：**角色域逻辑聚焦 `npm run test:logic:focused -- 'ROLE-'` **6/6 passed**，覆盖干净同步、脏草稿冲突保留、目标切换重置及原有 admin/view、保护和 fallback 规则。`npm run check:fast` 通过：typecheck、format、lint、Console OpenAPI 42 paths。
- **边界：**未运行浏览器；干净远端刷新后的 radio 值、脏草稿冲突提示、保存/读取最新交互及会话撤权页面行为仍需最终 Codex 内置浏览器验收；F4.29 保持未勾。

### 15.233 F4.29 角色写入 pending 与原操作确认路径（2026-10-09）

- **实现/验证：**新增角色命令 workflow 用例：服务器接受但暂未完成时，快照进入 `result-unknown`，同一角色命令不能再次发出；通过原 request key 查询到完成回执后才转为 success，并刷新目录和目标详情。`npm run test:logic:focused -- 'ROLE-PENDING'` **1/1 passed**，`npm run check:fast` 通过：typecheck、format、lint、Console OpenAPI 42 paths。
- **边界：**使用合成 Port 证明 workflow 状态与请求次数，不证明真实 Python operation persistence、页面反馈可见性或跨进程恢复；这些仍留最终验收，F4.29 保持未勾。

### 15.234 F6.2 URL/模型枚举运行时收窄（2026-10-09）

- **实现：**为规则类型、系统 Tab 与实例采集层增加基于协议常量的运行时 guard；规则筛选、系统 tab 深链、应用实例页与实时监控页的 metric scope 解析不再以 `includes()` 后的类型断言冒充类型证明。实例详情 query 校验和响应支持范围检查共用同一 guard，保持非法值拒绝/默认回退语义。
- **验证：**`npm run test:logic:focused -- 'F1 rules reject|INSTANCE-DETAIL|SYSTEM-TAB'` **3/3 passed**；`npm run check:fast` 通过：TypeScript、Prettier、ESLint、Console OpenAPI 42 paths。
- **边界：**这是 URL/模型输入检查切片；不等于完成 F6.2 全部 wire/model mapper audit，不证明 Python Console 或真实服务联调。未运行浏览器 E2E，按最终里程碑统一验收。

### 15.235 F5.3 路由、导航与角色值域断言清理（2026-10-09）

- **实现：**增加本地 `RouteId` 与主导航 ID runtime guard，登录回跳和图标查表不再在 membership 检查后做类型断言；规则目录选项直接按 `RULE_KINDS` 协议顺序生成；账号角色 ID guard 直接检查权威角色目录，删除不必要的 record 类型强转。
- **验证：**路由/角色/规则/实例/系统 tab 边界测试聚焦 **5/5 passed**；`npm run check:fast` 通过：TypeScript、Prettier、ESLint、Console OpenAPI 42 paths。
- **边界：**无浏览器或真实后端运行；该批纯边界测试不关闭 F5.3 全量模型、组件命令与页面矩阵。

### 15.236 F6.2 API mapper 类型断言架构护栏（2026-10-09）

- **实现：**新增架构测试扫描 feature/shared/core API 源码，禁止将不可信输入通过 `as any`、`as unknown` 或直接领域类型断言伪装成已验证 DTO；`as const` 静态声明与显式 wire schema 解析不受影响。
- **验证：**`node --test tests/architecture/wire-mapper-assertions.test.mjs` **1/1 passed**。
- **边界：**这是防回归静态护栏，不验证每个 operation 的 schema、字段投影、跨语言 wire 兼容或真实 Python 响应；F6.2 仍需逐项 audit 和服务联调。

### 15.237 F6.6 规则计划 Mock 状态校验与语义保留（2026-10-09）

- **实现：**规则计划命令在做时间冲突检查前，对 Mock 状态中已有计划逐项执行 `ActivationPlanSchema.safeParse`；畸形内部状态返回稳定 `dependency_unavailable`，合法状态则完整保留 pending/activating/active/restoring/completed/blocked/cancelled 等协议值，不通过 `String(...) as "pending"` 转换类型。现有取消后创建重叠时段用例覆盖 cancelled 不再阻止新计划。
- **验证：**`npm run test:http:focused -- 'RULE-MOCK-DEPLOYMENT'` **1/1 passed**；`npm run check:fast` 通过：TypeScript、Prettier、ESLint、Console OpenAPI 42 paths。
- **边界：**这是隔离 Mock handler 的状态校验，不证明 Python 持久化计划调度、跨重启恢复或真实配置中心发布。

### 15.238 B0.2 预置数据库 ASGI lifespan 生命周期切片（2026-10-09）

- **实现：**新增显式 opt-in 的 `install_preprovisioned_database_lifecycle()`，仅适用于部署已提供数据库并已完成首次初始化的模式：ASGI startup 执行已打包 Alembic 迁移，随后通过持久初始化标记 fail-closed；未初始化时拒绝进入应用 lifespan，成功关闭或启动失败时均释放该 helper 接管的 engine。保留原 `build_sql_identity_app()` 的调用方生命周期默认契约，不接管首次数据库选择、初始化写入、setup-window owner 或生产 launcher。
- **验证：**新增隔离文件型 SQLite 测试 **2/2 passed**，覆盖迁移后初始化库进入并保留既有 lifespan、未初始化库启动拒绝及两个分支的 engine disposal。与身份组合、持久层测试合计 **10/10 passed**；目标 Console `compileall` 与 `git diff --check` 通过。期间发现并修正一条未跟随当前迁移 head 的既有断言（`0004_login_attempt_limits` → `0006_registered_sources`）。没有连接 operator/production 数据库，没有启动服务或浏览器。
- **边界：**这是已预置数据库运行模式的 opt-in helper，不等于独立可执行 launcher 或生产 composition；SQLite 只证明本地迁移/lifespan 合同，不证明 PostgreSQL/MySQL 锁、迁移、TLS/网络或多 worker。首启跨资源 persistence owner 仍未决定；当时因此尚未实现 bootstrap initialize/operation API（后续 HTTP adapter 见 §15.265），B0.1/B0.2 保持未勾；完整 E2E 按全部代码完成后的最终验收执行。

### 15.239 B0.1 配置源外部凭证引用解析 Port（2026-10-09）

- **实现：**新增 deployment-owned `SourceCredentialReferenceResolver` application Port 与 secrets repr/equality 屏蔽的 `ResolvedSourceCredentials` frozen value object；`CheckRegisteredSource` 与 `CheckBootstrapSource` 均在交给 provider checker 前先解析引用，按 provider 校验 Nacos username/password 或 Consul ACL token 形状，再构造仅当前调用持有的 direct-auth input。resolver 未注入、返回空值、失败或 provider 不匹配统一 fail-closed 为 503，不降级匿名检查；已有 `KEEP` 精确 source/revision 解密路径与直接凭证路径不变。`build_app` 与 `build_sql_identity_app` 仅接受显式 deployment 注入，不默认选择 KMS、Kubernetes Secret 或其他供应商。
- **验证：**新增 application 定向测试覆盖 Nacos/Consul 映射、未配置/解析失败/provider 错配 fail-closed、直接凭证旁路；ASGI 测试覆盖初次 setup 与已登记来源两条引用解析、秘密不回 HTTP/repr；加上 checker/API/SQL composition 测试合计 **31 passed**。Console `compileall` 与 `git diff --check` 通过；没有运行浏览器 E2E、真实 Secret 服务、Nacos/Consul 或数据库。
- **边界：**这是可供部署注入的 Port，不是某个 vault/KMS/容器平台实现；真实凭证注入/轮换与网络探测仍待最终部署验收，B0.1/B0.2 不勾选。完整 E2E 保留在全部代码完成后的最终验收。

### 15.240 B0.3 Nacos/Consul 条件写能力官方文档核对（2026-10-09）

- **核对：**本记录仅核对了 Nacos 3.x Admin HTTP API（GET 提供 `md5`/`modifyTime`，HTTP Publish 参数没有 expected-revision/CAS），当时未覆盖 SDK gRPC。后续源码核查发现 `nacos-sdk-python` 3.x 的配置发布请求带 `cas_md5/casMd5`，见 §15.249；因此本条“无条件写 primitive”结论只适用于 Admin HTTP，不适用于 SDK gRPC。
- **实现约束：**Console 已冻结的规则发布合同要求 provider-side conditional write + read-back。不得用 Nacos HTTP pre-read `md5` 后再 unconditional publish 冒充 CAS；Consul writer 可按原生 CAS 实现。Nacos SDK gRPC CAS 尚未进入 Console 实现，未通过 key mapping、目标安全策略、create/update、结果分类、回读与真实服务验证前仍不可发布。
- **边界：**这是 Admin HTTP 文档静态核对，不是 Nacos/Consul 实例验收；本记录未连接外部配置中心。B0.3 保持未勾，最终 E2E 未运行。

### 15.241 F5.2 快速连续切换语言时的 latest-wins 收敛（2026-10-09）

- **实现：**新增 app-owned `createLatestLocaleSwitcher`：目录准备阶段允许并发，但 i18next locale commit 串行；较旧请求在提交前被更新请求取代时不再应用，也不写本机 locale 偏好。若新选择发生于旧 commit 已开始之后，新请求排队收敛到最终 locale，旧请求不持久化。`useLocaleSetter` 将 `writeStoredLocale` 作为成功提交回调传入，storage 所有权仍留在 locale preference 模块。
- **验证：**`npm run test:logic:focused -- I18N-` **4/4 passed**，包含较旧加载晚到、apply 中出现新请求、准备失败不应用/不持久化，并复用现有 Intl 数值用例。`npm run check:fast` 通过：TypeScript、Prettier、ESLint、Console OpenAPI **42 paths**。
- **边界：**这只证明 locale switcher 的异步所有权与纯逻辑合同；未运行浏览器，也未证明实际 Rule 页面切换时 draft dirty/value、URL 与协议值保持不变。按最终验收策略，完整 E2E 留待所有实现切片完成后执行；F5.2 继续未勾。

### 15.242 B0.3 Consul 规则 KV 条件写基础设施切片（2026-10-09）

- **实现：**新增 `ConsulRuleSourceWriter`，复用既有 DNS-pinned / SSRF allowlist / TLS / redirect-disabled HTTP transport；创建只使用 `cas=0`，更新只使用精确非零 `ModifyIndex`，不做自动重试；CAS true 后读取原 key 元数据，必须核对 exact key、base64 解码后的候选字节和严格递增的 `ModifyIndex` 才返回收据。stale CAS 是 conflict；授权拒绝单独分类；超时或无法读回是 outcome unknown。Nacos 写入仍保持 unsupported。
- **验证：**`sentinel-console/.venv/bin/python -m pytest -q tests/test_consul_rule_source_writer.py` **6 passed**；改动模块与测试 `compileall` 通过。测试使用受控 transport，不连接真实 Consul/Nacos。
- **边界：**此 adapter 尚未接入 durable `RuleMutationAuthority` 的原请求操作、事务化 receipt/audit、冲突重读路径或应用组装；目前也未在真实 Consul 做并发两 writer 验收。B0.3 继续未勾，完整 E2E 仍只在全部实现后执行。详见 [B0.3 provider conditional-write capability gate](acceptance/R-SENTINEL-CONSOLE-B0.3-provider-conditional-write.md)。

### 15.243 B0.1 SQL 规则草稿命令与读取首切片（2026-10-09）

- **实现：**新增 `console_rule_draft`、`console_rule_operation` 迁移和 SQLAlchemy command store。当前只接受 `save_draft` / `delete_draft`：写入前在事务内重验 active admin session/CSRF；再由 deployment 注入的 exact binding reader 确认 binding 存在，save 还必须匹配绑定的 kind/profile。Draft、原操作结果、审计事实同事务提交；revision CAS、binding 隔离、HMAC 输入指纹、原结果回放和有限 `unsupported` freeze/publish/plan receipt 已实现。新增 SQL 草稿 list/detail reader，并由 SQL identity app 组合入口装配。发布/冻结/计划尚无持久生命周期或配置中心副作用。
- **验证：**`PYTHONPATH=src:tests .venv/bin/python -m unittest tests.test_rule_mutation_store tests.test_rule_mutation_parsing tests.test_rule_drafts_api tests.test_identity_composition -v` **22/22 passed**；Python 3.13 `compileall` 与 `git diff --check` 通过。覆盖五种规则完整 round-trip、空集合、admin/view/CSRF、CAS/冲突、幂等精确回执、绑定 kind/profile 拒绝、SQL 列表/详情读取和 app reader 组合；仅用隔离 SQLite 与测试 binding authority。
- **边界：**写 authority 尚未接入生产 SQL app：启动组合仍需传入安全 key ring 与生产 exact-binding reader；没有 PostgreSQL/MySQL 行锁/并发、多 worker 或 deployment key rotation 验收。版本、发布、Consul conditional writer、Nacos unsupported policy 与计划调度仍未贯通，不能宣称规则可发布或运行时已生效。B0.1/B0.3 不勾选；完整 E2E 留到所有代码完成后统一执行。详见 [规则命令验收记录](acceptance/R-SENTINEL-CONSOLE-B0.1-rule-commands.md)。

### 15.244 B0.1/B0.3 通过精确验证回执冻结不可变版本（2026-10-09）

- **实现：**迁移 `0008_rule_versions` 新增不可变 SQL version 表与 validation receipt 外键，并安全扩展 operation result 检查约束。`freeze_version` 在当前管理员事务内锁定精确 draft revision，重新计算完整候选 checksum，要求 receipt 的 binding/profile/base/candidate checksum 全匹配且 `is_publishable=true`；只有满足条件才原子创建 version、operation receipt 和 audit。原始 operation 回执可回放同一个版本。新增 SQL 版本 list/detail reader，并在 SQL identity app 组合中装配；records 解码时重新验证 schema 和 checksum。publish 与 plan 仍拒绝为 `unsupported`，不调用 Consul/Nacos。
- **验证：**Python 3.13 `compileall` 通过；Console mutation/parsing/draft API/version API/SQL composition 定向组合 **32/32 passed**；覆盖 stale revision、non-publishable validation receipt 拒绝、完整版本 round-trip、幂等版本回放和 list/detail；`git diff --check` 通过。测试仅使用隔离 SQLite 与合成 binding reader。
- **边界：**SQL 并发/行锁需要 PostgreSQL/MySQL 兼容测试，当前 SQLite 不证明；不可变性靠无更新 API、权限与 SQL 约束，并未做防数据库管理员篡改机制。配置中心发布、publication/read-back/runtime receipt、激活计划仍未实现；B0.1/B0.3 不勾选。完整 browser E2E 留在所有代码完成后的最终验收。

### 15.245 B0.1 规则命令密钥与 SQL 写权威显式组合（2026-10-09）

- **实现：**新增独立 `RuleCommandKeyConfiguration`，从部署环境读取规则命令 HMAC key ring；密钥至少 32 字节、repr 隐藏、映射不可变、错误不回显 key material。新增 `compose_sql_rule_mutation_authority(engine, key_configuration, binding_reader=...)`，并使 `build_sql_identity_app(...)` 可从该配置和 authoritative exact-binding reader 显式组合 SQL 命令 authority。半配置和 direct authority + 组合输入混用均拒绝。规则命令 key domain 独立于账户命令与配置源 keyring。
- **验证：**Console Python 3.13 配置解析、identity composition、SQL mutation 目标测试 **15/15 passed**；覆盖环境缺失/坏 Base64/重复 key/短 key/未知 active id、key 不可变及脱敏、authority composition 输入传递和 existing SQL command/freeze workflow。未运行浏览器。
- **边界：**仍未提供具体生产 binding directory adapter，部署必须注入权威 reader；没有 PostgreSQL/MySQL 多 worker、密钥轮换部署或真实配置中心验收。publish/plan lifecycle 仍未完成，B0.1/B0.3 不勾选；完整 E2E 只在全部代码完成后的最终验收执行。

### 15.246 B0.1 规则 binding authority 移出 SQL 事务（2026-10-09）

- **实现：**规则 mutation 首先在短 SQL 事务内鉴权并检查幂等回执；新命令再查询 deployment-owned binding reader，此时不持有 SQL 事务；随后开启写事务并重新核验 admin session/CSRF 与幂等键，再按已读到的精确 binding 执行写入、回执和审计。由此外部目录延迟不会占住 SQL 事务；读取期间会话被撤销或并发同键请求已提交时，写事务会拒绝/回放，不重复写。
- **验证：**新增 SQLite focused regression，在 binding reader 执行期间断言无 SQL transaction，并在其返回前撤销 admin session；命令第二次授权拒绝，确认无 draft 或 operation receipt 落库。Rule mutation store 测试 **10/10 passed**；无真实数据库/远端 binding 服务。
- **边界：**binding authority 与 Console SQL 仍是不同持久化权威，无法跨两个系统原子锁住 binding 生命周期；后续 concrete adapter 需使用一致的 binding identity/profile/source 版本合同。该切片未增加规则发布能力；B0.1/B0.3 不勾，完整 E2E 留在最终节点。

### 15.247 B0.3 Consul 精确快照读取适配器（2026-10-09）

- **实现：**新增只读 `ConsulRuleSourceReader`，在既有 DNS-pinned/SSRF allowlist/TLS transport 上读取精确 KV key，分别表达 key 不存在、读取被 ACL 拒绝和无法建立可信快照；对 HTTP 200 必须核对唯一记录、精确 key、base64 value 与正整数 `ModifyIndex`。快照 repr 隐藏规则字节，且 value/revision 存在性必须成对。读取与写入共用独立的 Consul key/revision support 模块，连精确 KV response decoding 也只有一份实现。
- **验证：**本切片结束时 reader + writer 受控 transport 聚焦测试 **13/13 passed**，覆盖 exact key、datacenter/token、404 absent 与已存在空 value 的区分、错误 key/metadata、网络超时、ACL 拒绝、目标策略拒绝及意外程序错误透传；Python 3.13 `compileall` 与 `git diff --check` 通过。未连接真实 Consul/Nacos、未运行浏览器或完整 E2E。
- **边界：**这只是 B0.3 后续发布恢复的只读基础设施；尚未接入持久化 publication/原始 request key 恢复、SQL composition、API 回执或真实服务。B0.3 仍未勾选，完整 E2E 保留最终里程碑。

### 15.248 B0.3 配置源传输故障分类收窄（2026-10-09）

- **实现：**Consul exact reader 与 CAS writer 共用有限的传输异常集合（aiohttp 网络/协议错误、OS 网络错误、超时）；取消 `except Exception` 对外部传输整段兜底。writer 在 PUT 发出后遇到这些异常仍返回 `OutcomeUnknown`，保持不得盲目重试；读取遇到传输异常仍 fail-closed。意外 `RuntimeError` 等程序错误不再被伪装成配置源故障。
- **验证：**Consul reader + writer focused **13/13 passed**，包含读取/写入传输异常分类和程序错误透传；没有运行完整 Python regression、浏览器 E2E 或访问真实 Consul。
- **边界：**只修复适配器的故障语义，不新增 publication saga，不代表 SQL receipt 持久化、生产 composition 或真实配置中心验收完成；B0.3 继续未勾，完整 E2E 留在最终节点。

### 15.249 B0.3 Nacos SDK gRPC 条件写能力核对（2026-10-09）

- **核对：**纠正 §15.240 将 Admin HTTP API 的参数缺口外推到整个 Nacos 的结论。`nacos-sdk-python` 3.x 对外暴露 `ConfigParam.cas_md5`，gRPC publish request 将其作为 `casMd5` 发送；Nacos server request handler 把该值传入配置操作层。对应 source/API evidence 列于 [B0.3 provider conditional-write capability gate](acceptance/R-SENTINEL-CONSOLE-B0.3-provider-conditional-write.md)。
- **实现方向：**Nacos Console writer 必须基于 SDK 支持的 gRPC CAS，不得降级为 Admin HTTP pre-read + unconditional publish。适配器还必须满足 deployment-pinned endpoint 与 TLS server identity、冻结 namespace/group/dataId 映射、create/update 语义、冲突/unknown 分类和精确 read-back；SDK CAS 尚不等于 Console 发布可用。
- **边界：**本切片为官方 SDK/server 源码及当前本地 SDK API 的能力审查，不是 Nacos 3.2.3 实例验收；没有连接配置中心、没有新增 writer 代码。Nacos 适配器实现与受控测试继续推进，真实服务器检查和跨服务 E2E 留在最终验收。

### 15.250 B0.3 激活计划 SQL 持久化首切片（2026-10-09）

- **实现：**新增 migration `0009_rule_activation_plans` 与计划 SQL model；`SqlAlchemyRuleMutationStore` 现可在同一事务内创建 `pending` activation plan、校验两个不可变版本均属于同一 binding、拒绝活动/待执行窗口重叠、按精确 revision 取消待执行计划并保存 typed original-operation receipt/audit。计划 reader 已接入 SQL identity app composition，按 binding 读有界排序结果。共享版本行锁串行化同 binding 的计划创建检查；跨方言生产锁/并发仍待验收。
- **验证：**`tests/test_rule_mutation_store.py` **10 passed**；覆盖版本不存在/非法时区拒绝、创建与幂等回放、窗口重叠冲突、计划读取、revision 更新取消与 stale cancel 冲突。测试启动并执行 Alembic 全迁移链至 `0009`，使用隔离 SQLite；`compileall` 与 `git diff --check` 通过。
- **边界：**计划目前只持久化为 `pending`，不触发配置源写入；尚无调度器、执行 claim/lease、publish/restore operation 关联、崩溃恢复和实例 receipts，不能宣称按时生效。PostgreSQL/MySQL 并发和全量 E2E 留待最终验收；完整 E2E 本切片未运行。

### 15.251 B0.3 发布阶段 SQL 持久化与 CAS 推进首切片（2026-10-09）

- **实现：**新增 migration `0010_rule_publications` 与 `RulePublicationRecord`，分别保存 validation、provider write、exact read-back 三阶段状态/时间/有限原因；SQL reader 提供按 binding 有界的完整历史和 binding+publication 精确详情，重建时经过领域不变量校验。`SqlAlchemyRulePublicationStore` 可校验不可变 target/base version 后创建全 awaiting publication，并按 exact binding、publication identity 和 expected phase state 事务性 CAS 推进；纯 domain transition 禁止跳过或回退阶段。`build_sql_identity_app` 装配 SQL reader。
- **验证：**`sentinel-console/.venv/bin/pytest -q tests/test_rule_publication_reader.py tests/test_rule_publications_api.py tests/test_identity_composition.py` **24 passed**；覆盖 migration、创建/版本校验、相位 round-trip 与单调转移、重复/stale 状态冲突、跨 binding 隐藏、空历史及 SQL composition；Python 3.13 `compileall` 与 `git diff --check` 通过。使用隔离内存 SQLite，未启动浏览器或真实 provider。
- **边界：**recorder 尚未接入 `PublishRuleVersion` durable command/outbox，也未接入 Consul/Nacos writer、计划调度/重启执行或 instance receipts；publication 当前仍不能由用户发布命令产生，不能证明配置已写入或实例已加载。B0.3 不勾；完整 E2E 仍留到最终节点。

### 15.252 B0.3 publish 命令持久化受理首切片（2026-10-09）

- **实现：**migration `0011_rule_publish_outbox` 扩展 operation receipt，允许仅 publish 命令进入 `pending`，并将有限 work payload 与 `RulePublicationRecord` initial phases、audit 在同一 SQL transaction 写入。提交前检查 binding、immutable target version/checksum/profile 和 publishable validation receipt；如果 `expectedVersionId` 有值，必须在同 binding 且校验 baseline checksum。保存 expected version/checksum/source revision 与 publication identity，不复制完整规则、凭证或 operator reason。相同 request key 精确返回既有 pending 状态；原操作查询仍绑定 actor/session/binding/key。
- **验证：**`sentinel-console/.venv/bin/pytest -q tests/test_rule_mutation_store.py tests/test_rule_mutation_parsing.py tests/test_rule_commands_api.py tests/test_rule_publication_reader.py tests/test_rule_publications_api.py` **39 passed**；覆盖迁移、版本/baseline 校验、事务化 pending+publication、原操作回读、原 key 幂等、字段隔离、已有 publish API pending 契约；Python 3.13 `compileall` 与 `git diff --check` 通过。运行使用隔离 SQLite 和合成 binding directory。
- **边界（本切片当时）：**当时尚无 outbox lease/claim worker，因此不会调用 provider；没有 Consul/Nacos 写入、重启后调度、未知结果恢复、operation completion/receipt，也没有 source target key mapping。后续进展见 §15.253。B0.3 继续未勾，完整 E2E 留待最终节点。

### 15.253 B0.3 SQL 发布工作认领租约首切片（2026-10-09）

- **实现：**新增 migration `0012_rule_publish_leases`，为 pending publish operation 增加有界尝试次数、当前 claim fencing token 和租约到期时间；新增 `SqlAlchemyRulePublishOutbox.claim_ready()`，按创建顺序并发安全地认领有限数量工作，只选择 pending publish，重新校验持久化 work payload 的有限 schema。租约有效期最多 5 分钟；到期后重新认领会生成新 token 并递增 attempt，旧 token 不再是当前数据库 claim identity。`renew_claim()` 使用当前 token + 原 lease expiry CAS 续租，拒绝过期 claim 或旧 lease revision；`advance_claimed_phase()` 同事务检查 operation/binding/publication/token/lease 与 phase CAS，新 token 接管后旧 claim 不能落迟到 phase 结果。
- **验证：**`tests/test_rule_mutation_store.py` + `tests/test_rule_publication_reader.py` **16 passed**，覆盖首次认领、有效租约不可重复认领、到期换 token、attempt 递增和租期上界；SQLite migration 从头升级通过。此为局部 SQL 测试，不是跨进程/多方言证明。
- **边界：**claim adapter 尚未连接 provider worker，也没有 dispatch outcome reconciliation、operation completion 或 source target key mapping；数据库 fencing 不能撤销已发出的 provider 网络请求，不代表配置中心写入或运行时应用完成。Consul/Nacos 均未调用，B0.3 继续未勾；完整 E2E 留待全部代码完成后的最终节点。

### 15.254 B0.3 SQL 发布工作租约续期（2026-10-09）

- **实现：**`SqlAlchemyRulePublishOutbox.renew_claim()` 对仍有效的 claim 使用 request/operation/binding/token/原 expiry 条件做 CAS 续期，最大租期仍受 5 分钟限制；旧 claim revision 重放、到期后续期、越界时长都明确拒绝。新 lease revision 返回为新的 frozen claim 值，不原地修改旧对象。
- **验证：**发布 outbox 生命周期 focused 场景 **1/1 passed**，覆盖同 token 续租、旧 expiry revision 冲突、有效期内不可被另一 worker 抢占、租约到期后换 token、旧 token phase 更新拒绝及新 owner 对 running phase 记录 unknown reconciliation 事实；Python `compileall` 与 `git diff --check` 通过。
- **边界：**这是 SQLite 同一数据库上的定向状态/持久化检查，不代表 PostgreSQL/MySQL 并发租约、多进程真实争抢，也没有启动 provider worker；provider 网络副作用还需要原生 CAS 和精确回读保护。完整 E2E 留到所有代码完成后的最终验收。

### 15.255 B0.3 publish 成功回执原子完成（2026-10-09）

- **实现：**`complete_claimed_publication()` 只接受仍有效的 claim，且 validation/configuration_write/read_back 三个持久阶段全部为 succeeded、观测时间不晚于完成时间；同事务将 operation pending→completed、保存完整安全 `RulePublication` 快照、清除 transient payload/lease，并添加同一 operation ID 的完成审计。mutation store 现可严格解码该 publication 回执，使原 actor/session/binding/request-key 查询得到相同终态快照。`reject_claimed_publication()` 只对已确认的 failed 阶段执行 pending→rejected，拒绝含 unknown 的 publication；同事务清除 transient work/lease、记录有限拒绝原因与一条审计，同时保留 publication 阶段事实。重复终态变更均冲突。
- **验证：**Python 3.13 `compileall`、`git diff --check` 通过；Console mutation/API 聚焦集 **39/39 passed**，覆盖成功完成/原操作回读/一次性审计/重复终态冲突、known failure 安全拒绝和 unknown 禁止完成/拒绝。测试使用隔离 SQLite，不调用 provider。
- **边界：**本能力只收敛已经分别持久化的阶段结果，不负责配置源读取/CAS/回读，也没有 production worker 调度。真实 Consul/Nacos、PostgreSQL/MySQL 并发、计划恢复、实例 receipts 和最终 E2E 仍开放，B0.3 不勾选。

### 15.256 B0.3 服务端精确发布目标契约（2026-10-09）

- **实现：**新增 `NacosRulePublicationTarget`（namespace/group/dataId）与 `ConsulRulePublicationTarget`（datacenter/key）两个互斥的 provider-specific 值对象及 `RulePublicationTargetReader` Port。目标必须由服务端按精确 binding 解析；值对象拒绝空/超长/控制字符身份和非法 Consul KV key。另新增 provider-specific 严格持久化 mapper，拒绝未知字段和不匹配的 provider shape。浏览器 `RuleBinding.location` 仍仅为展示事实，未用于写目标推断；无 target 不回退默认 key。
- **验证：**目标值对象、binding-scoped Port 与 provider-specific 严格 mapper 定向测试 **4/4 passed**；与 mutation、publication/API 聚焦集合并 **43/43 passed**。Python `compileall` 与 `git diff --check` 通过。测试未连接真实配置中心。
- **边界：**此切片只冻结消费侧精确目标契约，尚未实现目标注册/持久化 reader、binding target 管理页面/API、worker 或 provider 调度；B0.3 继续未勾，完整 E2E 仍留至最终节点。

### 15.257 B0.3 发布受理冻结 provider target 与 source revision（2026-10-09）

- **实现：**新增 migration `0013_rule_publication_targets`、binding-scoped SQL target reader 与生产 mutation composition 装配。`VersionedRulePublicationTarget` 显式携带 target mapping revision 与配置源 revision；publish work schema V2 在同一受理事务中保存这两项 revision 和严格编码的 Nacos namespace/group/dataId 或 Consul datacenter/key。outbox claim 只解码持久快照，不再查询当前映射；目标缺失时拒绝为 `unavailable`，不生成 pending work。
- **验证：**Console 定向 mutation/publication/target 测试 **46 passed**；覆盖 SQL reader round-trip、target 缺失 fail-closed、持久 payload 精确目标和两类 revision 在后续映射/来源变更后的冻结，以及 Alembic 全链升级。Python `compileall` 通过；本轮未运行完整 E2E、浏览器或真实 provider 测试。
- **边界：**目前还没有授权的 target mapping 写入 API/UI，也没有 worker 使用 frozen source revision 调用 provider；provider执行、未知结果恢复和完整生命周期仍开放。B0.3 不勾选；完整 E2E 只在所有代码完成后的最终验收执行。

### 15.258 B0.3 拒绝过期或 provider 不匹配的 registered source revision（2026-10-09）

- **实现：**SQL target resolver 现在与 registered-source 表联合读取，要求 target mapping 的 `source_id` 对应已登记来源，source revision 必须仍为当前版本，且 provider 必须与 Nacos/Consul target 类型一致。缺少来源、版本已更新或 provider 不一致均不向发布命令提供目标，避免把已登记来源更新后的 endpoint/认证配置静默用于旧 mapping。
- **验证：**Console mutation/publication/target 聚焦集合 **47/47 passed**；新增 stale registered-source revision 拒绝测试，并保留 target mapping/来源 revision 冻结检查。Python `compileall` 通过；未运行浏览器、完整 E2E 或真实 provider 测试。
- **边界：**source revision 在命令受理后变化时，已冻结 work 仍不会重定向；worker 必须以冻结 revision 调用 resolver，若凭证版本不可取应进入安全失败/未知结果恢复，不能自动使用新 revision。target mapping 管理入口和 worker 尚未完成。

### 15.259 B0.3 受信任服务端精确目标配置 CAS 写入（2026-10-09）

- **实现：**新增 `RulePublicationTargetWriter` port 与 `SqlAlchemyRulePublicationTargetWriter`，并提供明确的 SQL composition factory。创建使用 expected revision `None` 的 create-only 语义；更新要求精确匹配当前 target revision。事务内锁定并核对 registered source 当前 revision/provider，再写入 Nacos/Consul 精确目标与新 opaque revision；冲突不会覆盖并发配置。此为可信 server-side provisioning port，不含浏览器认证/CSRF/idempotency/audit，不得直接挂成 HTTP endpoint。
- **验证：**Console mutation/publication/target 聚焦集合 **50/50 passed**；覆盖 target create/update、旧 mapping revision 冲突、registered-source revision/provider 不匹配拒绝、reader 回读及原发布冻结回归。Python `compileall` 通过；未运行浏览器、完整 E2E 或真实 provider。
- **边界：**尚无受授权的 server provisioning workflow 与持久化审计，因此用户不能从 Dashboard 管理 target；尚未连接 provider worker。不得把内部 repository writer 误当成产品管理入口，B0.3 保持未勾。

### 15.260 B0.3 按冻结 registered-source revision 解析 provider 连接（2026-10-09）

- **实现：**新增应用用例 `ResolveRegisteredSourceConnection`，只以持久化发布命令中冻结的 `source_id + source_revision + provider` 调用现有 `RegisteredSourceCredentialResolver`。它校验返回连接的来源身份、revision、provider 与认证模式；过期/缺失/交叉 provider/`KEEP` 状态拒绝。对存储的 opaque credential reference，调用部署注入的 `SourceCredentialReferenceResolver`，验证凭证 provider 后生成仅驻留在调用栈中的直接连接输入；异常输出为通用不可用错误，秘密不进入 repr/错误文本。该能力作为后续可信 provider worker 的精确 source-revision seam，不开放 HTTP API、不自动回退到新 revision。
- **验证：**`tests/test_resolve_registered_source_connection.py` 新增覆盖冻结 revision、未认证来源、Nacos 凭证引用解析、错误/过期/错误 provider/KEEP 拒绝、凭证 authority 错误脱敏等 **6 项**；`compileall` 通过。初次扩大到现有 source-store 测试时有 2 个既存用例因夹具固定过期时间而失败（读操作使用当前系统时钟）；本切片改以独立新增用例和 source-check API 回归验证，不据此修补无关时钟夹具。
- **边界：**尚未有 worker 消费该解析能力；不证明 SDK 调用、网络安全策略、真实 provider 写/read-back 或未知结果协调。SQLite/数据库服务和浏览器均未接触，B0.3 未勾，完整 E2E 仍留在所有实现完成后。

### 15.261 B0.3 Console Sentinel 版本到同类规则 JSON 编码器（2026-10-09）

- **实现：**新增 `application/rule_value_projection.py`，将五类 typed `RuleValue` 的规范 camel-case 字段集中投影，供 Console API 快照序列化与发布编码共用。新增 `RulePublicationPayloadEncoder` Port 与 `SentinelRuleVersionJsonEncoder`；将单一 rule-kind 的 immutable version 编码为 provider-neutral UTF-8 JSON array，保持版本记录顺序、排序对象键、紧凑序列化并拒绝 NaN/Infinity。provider payload 不包含 Console-only `RuleRecord.id` 或 API 的 `kind/value` 包装。编码器按装配时的精确 profile ID 工作，拒绝 profile 不匹配、cluster mode 关闭却附 clusterConfig、非 slow-ratio grade 却携带 slowRatioThreshold 和无法 JSON 编码的持久化值。
- **验证：**新增五类 schema 字段/数字枚举/嵌套 cluster 与热点参数、管理 ID 隔离、确定性和数组顺序、profile 不匹配、条件字段矛盾、非有限持久值测试；`tests/test_sentinel_rule_version_encoder.py`、rule snapshot/version API、候选 validation API 共 **30 passed**。Python `compileall` 通过；本切片未连接真实数据库、配置中心或浏览器。
- **边界：**纯编码器测试不证明 Java RuleSource 解码、配置中心协议接受/持久化或 provider 回读；profile validator/receipt、provider CAS worker 与未知结果协调仍未完成，B0.3 不勾，完整 E2E 保留最终验收。

### 15.262 B0.3 发布 worker 生命周期编排首切片（2026-10-09）

- **实现：**将 `RulePublishWorkClaim` 移入应用层发布 Port，避免 Application 依赖 Infrastructure claim DTO。新增 provider-neutral `RulePublicationProvider` 与精确快照 DTO，以及 `RunRulePublicationWorker`：读取并校验 claim 对应的 immutable version/publication；以同一编码器编码 candidate 和显式 baseline；按冻结 `source_id + source_revision + provider` 解析短暂连接；在 provider CAS 前对远端当前值与 baseline bytes 精确比较；分别持久化 validation、write、read-back 状态；只有 exact candidate read-back 后才完成原操作。对失去响应的 CAS，持久化 `UNKNOWN` 并停止重发；后续租约认领仅通过精确远端读取将 `RUNNING/UNKNOWN` 调和为成功，或保留未知，不盲写。领域迁移增加 `UNKNOWN -> SUCCEEDED/FAILED`，仅用于受 claim fencing 的权威后续观察。
- **验证：**新增 `tests/test_rule_publication_worker.py` 覆盖完整成功顺序、过期 claim 下“配置中心已写入但响应丢失”的对账且无第二次写入、baseline 漂移时零写入拒绝。worker、publication store/outbox、publication reader、encoder 定向套件共 **27 passed**；变更文件 `compileall` 通过。
- **边界：**这只是 Application 编排与替身契约测试；生产 composition 尚未装配，实际 Consul/Nacos provider adapter 未接入该 Port，数据库并发/多 worker、进程崩溃点、真实网络 provider CAS 和运营恢复流程仍未验证。B0.3 保持未勾；完整 E2E 仍只在所有代码完成后的最终节点执行。

### 15.263 B0.3 Consul 发布 provider Port 适配器（2026-10-09）

- **实现：**新增 `infrastructure/consul_rule_publication_provider.py`，将 binding 冻结的 Consul KV key 映射到 worker 的通用配置快照与 CAS 契约：`ModifyIndex` 作为 provider revision，精确 value bytes 原样传递；读取与写入的冲突、拒绝、不可用、未知结果映射到应用层稳定异常，不携带底层异常消息。复用现有 DNS pinning/TLS/redirect/超时安全策略、Consul reader 和 CAS writer；没有引入第二套 HTTP client。
- **验证：**新增 adapter contract tests 校验冻结 key/revision/value 转换及 CAS conflict 映射；adapter、worker、Consul reader/writer、SQL publication/outbox、rule encoder 定向测试共 **42 passed**；变更 Python 文件 `compileall` 通过。
- **边界：**Adapter 仍需由生产运行装配显式绑定，并未接触真实 Consul；worker 到 provider 的组合测试、受控本地 HTTP endpoint、SQL 多 worker/失租接管及两个真实 writer 的竞争验收仍未完成。Nacos provider 尚无 worker adapter。B0.3 不勾；完整 E2E 留到最终节点。

### 15.264 B0.3 发布 worker ASGI 生命周期托管（2026-10-09）

- **实现：**新增 `RulePublicationWorkerLoop` 与 opt-in `install_rule_publication_worker_lifecycle`。ASGI lifespan 启动有界 outbox polling，轮次异常只记录稳定异常类型、不输出异常正文或配置 payload，随后退避到下一轮；关闭时取消在途 worker task 并等待其结束。验证了轮询参数边界、一次迭代失败后仍可继续，以及 shutdown cancellation。
- **验证：**`tests/test_rule_publication_worker_lifecycle.py`、既有 worker 与 Consul adapter focused suites 共 **9 passed**；测试确认 `build_app` 注入 worker 后由 ASGI lifespan 启动并在退出时停止；未运行全量 E2E。
- **边界：**组合根现在提供显式注入接线，但部署仍须自行构造 worker 及其 SQL/provider/source resolver 并选择是否启用；并发正确性依赖持久化 outbox lease/fencing。本切片未接真实 SQL、多进程、Consul 或 Nacos，也未验证在途网络请求的远端提交状态；取消后由既有 `RUNNING/UNKNOWN` 对账语义处理。B0.3 继续未勾，完整 E2E 留到所有实现完成后的最终节点。

### 15.265 B0.1 Bootstrap initialize/operation HTTP adapter（2026-10-09）

- **实现：**新增初始化一次性命令 DTO/use case/authority Ports，并在独立 Console `build_app` 注册 `POST /api/v1/system/bootstrap/initialize` 与 `GET /api/v1/system/bootstrap/operations/{requestKey}`。写路径严格校验 JSON 字段、Origin/CSRF、request/idempotency key 与数据库/首个管理员/首个规则源类型；读取路径验证原始 bootstrap operator grant，可在 setup 窗口关闭后读取原操作安全回执。响应只暴露稳定状态/拒绝原因/operation ID，不回传或记录数据库、源凭证与管理员密码；输入 DTO 自身也校验领域类型。真实初始化 authority 和 operation reader 未装配时 fail-closed。
- **验证：**初始化 API、既有 database-check/source-check adapter 聚焦测试 **21 passed**；覆盖有效映射、数据库/管理员/规则源凭证整体不泄露、Origin/CSRF/idempotency 拒绝、无效字段拒绝、授权回读与 authority 缺失 fail-closed。测试只用隔离 ASGI doubles；全量 E2E 按执行策略保留在全部实现完毕后的最终验收。
- **边界：**没有绕过 §15.143 的跨资源持久化 ownership gate；尚缺部署拥有的 runtime DB locator/setup marker、初始化与目标数据库迁移/首 admin/规则源登记的失败恢复、真实 durable operation authority、production launcher composition 及 PostgreSQL/MySQL 重启/多 worker 验收。因此 42/42 是路由注册覆盖，不代表 bootstrap 功能端到端可用，B0.1/B0.2 继续未勾。未连接或修改真实数据库/配置中心。

### 15.266 F6.1 Python route/OpenAPI method parity guard（2026-10-09）

- **实现：**新增 `sentinel-console/tests/test_console_openapi_route_parity.py`。测试以生产所需 endpoint 全部装配的 `build_app` route table 对照唯一 `console-api.openapi.json`，逐项比较 `/api/v1` 路径和 HTTP 方法；只规范化框架间 path-parameter 名称/类型注解差异，不把遗漏 endpoint 或方法差异隐藏掉。这样能防止 API 路由代码和协议目录各自演进后出现漏登记。
- **验证：**在 `components/sentinel/sentinel-console` 执行 `.venv/bin/pytest -q tests/test_console_openapi_route_parity.py`，**1 passed**。
- **边界：**这里只验证 endpoint path/method 覆盖，不校验 request/response schema、错误码、时间精度、分页/幂等/权限细节，也不表示 HTTP 到 Python authority 的业务链路可用；未运行浏览器、完整 E2E 或外部服务验收。

### 15.267 B0.3 Nacos Python SDK 3.2.0 生产传输接缝审计（2026-10-09）

- **核对：**本机缓存的 `nacos-sdk-python==3.2.0` 确认 `ConfigParam.cas_md5` 会进入 gRPC `casMd5` 请求；但公开 `get_config()` 只返回配置正文，SDK 内部收到的服务端 MD5 被丢弃，无法提供 worker 所需的权威 CAS 基线。SDK 自行构造 gRPC channel 与 auth refresh client，没有公共注入 DNS-pinned transport 的接缝；私有 transport 替换会使认证链路脱离统一安全策略。其 TLS `server_name_override` 配置也未应用到 gRPC channel option，不能安全地假定可用部署 hostname 校验已 pin 的 IP。
- **决策边界：**不以 Admin HTTP “先读后无条件写”替代 CAS，也不 monkeypatch SDK 私有实现。Nacos publish 暂时必须 fail-closed；后续只能基于上游公开的 MD5 read/transport injection、维护经过审查的窄 SDK fork，或实现最小且版本化的 Nacos gRPC transport（含认证、TLS/SNI、DNS pin、CAS 结果分类和精确回读），并验证目标 Nacos 版本的 create-only CAS 行为。这是当前 adapter 的实现阻塞，不是取消 Nacos 支持。具体证据见 [B0.3 provider conditional-write capability gate](acceptance/R-SENTINEL-CONSOLE-B0.3-provider-conditional-write.md)。
- **验证与范围：**只做 SDK 源码审计及文档记录；未连接 Nacos、未写 provider adapter、未运行浏览器或完整 E2E。B0.3 继续未勾选。

### 15.268 B0.3 按 provider 能力分区认领发布工作（2026-10-09）

- **实现：**`RulePublicationProvider` 现在必须声明有限 `supported_providers`；`RunRulePublicationWorker` 将该集合传给 outbox；SQL `claim_ready` 仅认领冻结 `work_payload.target.provider` 属于本 worker 支持集合的命令。新增 `RulePublicationProviderRouter` 按目标 provider 将读/CAS 写调用委托到显式配置的 adapter，并拒绝未配置或连接/目标 provider 不一致的请求。当前只有 Consul adapter 声明真实实现；Nacos 未实现时不会被 Consul worker 抢占。
- **验证：**SQLite SQL mutation/outbox、worker、Consul provider 与 provider-router suites 聚焦运行 **21 passed**；专门断言 Consul 支持集合不会认领 Nacos 命令、Consul 命令可被对应 worker 认领、provider router 只调用与目标匹配的 adapter。`compileall` 通过。
- **边界：**没有 Nacos adapter 或 production worker composition；router 的 mock Nacos collaborator 仅验证路由，不表示 Nacos 功能已实现。真实服务/浏览器和完整 E2E 保留最终节点，B0.3 不勾选。

### 15.269 B0.3 Consul durable worker 显式组合工厂（2026-10-09）

- **实现：**新增 `create_consul_rule_publication_worker`，将 SQL outbox/publication/version readers、Consul pinned reader/CAS writer/provider、冻结来源连接与秘密引用解析、指定 Sentinel profile 编码器组装成单个仅支持 Consul 的 durable worker。部署方必须显式提供 `AsyncEngine`、注册来源 DNS/network target policy、凭证解析器和规则 profile；工厂不创建/销毁 engine、不读取环境变量、不配置 allowlist、不自动启动后台轮询。
- **验证：**SQLite migrations + 显式网络/凭证依赖下创建 worker，并确认空 outbox 的 `run_once` 安全返回空结果；本轮 B0.3 定向 suites **22 passed**，`compileall` 通过。没有提交命令因此没有 provider 网络流量。
- **边界：**这为预配置数据库部署提供可复用组合件，不解决 first-run DB locator/初始化 gate，不提供 production launcher，也未在真实 Consul 验收 CAS。Nacos 仍须 wait for safe transport implementation；未运行浏览器或完整 E2E。

### 15.270 B0.2 加密 runtime database locator 与 engine resolver（2026-10-09）

- **实现：**新增应用层 `RuntimeDatabaseLocator` 与 `RuntimeDatabaseLocatorStore` Port、deployment-owned POSIX 文件适配器及独立 path/key-ring 环境配置。URL 用 AES-256-GCM 加密，AAD 绑定固定 owner、field 与 locator revision；严格 JSON schema 拒绝重复/未知字段，secret 不进入值对象 repr 或错误。Sidecar advisory lock 串行化同机 worker，revision CAS 防止并发首写/更新覆盖；要求绝对路径、预建且无 symlink 的父目录、无跟随打开、regular file、0600、同目录临时文件+fsync+原子替换+目录 fsync。`ConsoleDatabaseConfiguration.from_bootstrap_candidate()` 将 setup 表单里的 PostgreSQL/MySQL 字段安全构造成 async URL（拒绝 SQLite/缺失密码/无效端口，不连接），`from_locator()` 校验解密 URL，`create_runtime_database_engine()` 仅在 locator 缺失时返回 setup mode，不回退环境 URL/SQLite；locator 故障 fail-closed。并将 account/rule/source/runtime 的 base64 key-ring 解析收敛到一个 helper。
- **验证：**locator/store/config、runtime DB URL、AES secret 和三个既有 key-configuration 聚焦套件共 **27 passed**；覆盖密文/脱敏、create/update CAS、竞争首写唯一胜者、错误密钥/篡改/权限/symlink 拒绝、独立 key 环、候选字段映射/拒绝及 locator→lazy engine/setup-mode 映射；`compileall` 与变更源码 88 列检查通过。只使用本地临时目录及 engine spy，没有连接数据库/配置中心或运行完整 E2E。
- **边界：**尚未接入 Console ASGI lifespan/production launcher、bootstrap 目标库迁移/首管理员/规则源事务与失败恢复、setup-window/operator authority 外置持久化；本地 POSIX 锁/原子替换的部署挂载、多主机/NFS 语义未验。因此 B0.2 继续不勾；完整 E2E 仍仅在全部代码完成后的最终节点执行。

### 15.271 B0.2 setup-window 本地持久 authority 首切片（2026-10-09）

- **实现：**新增部署配置 `SetupWindowConfiguration` 与 `SENTINEL_CONSOLE_SETUP_WINDOW_PATH`，可显式创建 `SetupWindowFileStore`；文件缺失一律视为 closed，不存在隐式 open 默认。Adapter 实现 `SetupWindowReader` + CAS `SetupWindowController`，严格 UTF-8/JSON schema、duplicate/unknown field、schema/revision 校验；损坏、权限过宽、symlink、非 regular file 或不可读时映射为 `BootstrapAuthorityUnavailable`。复用 `LocalAtomicFileStore` 的本机 POSIX sidecar lock、0600 atomic replacement、fsync 与 byte-CAS。应用层新增独立 controller Port；配置仍由部署组合显式注入，不伪称已接入生产 launcher。
- **验证：**setup-window store/config、runtime database locator store、database runtime、secret protection、三类 command-key 配置聚焦集合 **40 passed**；覆盖首次缺失为 closed、显式开关、陈旧 revision/并发 CAS 单赢家、损坏及重复/未知字段、错误编码、symlink/宽权限拒绝、环境配置和既有 locator regression。Python compileall 与 `git diff --check` 通过。只使用本地临时文件/SQLite，不启动浏览器、完整 E2E、真实 DB 或配置中心。
- **边界：**暂不声称跨进程挂载/多主机/NFS 语义；没有 initializer 完成后关窗的跨存储恢复/原子性，没有生产 lifespan/launcher 接线、外置 operator grant 或真实挂载验收。B0.2 继续不勾；完整 E2E 仅留最终验收节点。

### 15.272 F6.1 身份接口非法请求错误码一致性（2026-10-09）

- **实现：**对齐 `GET /system/bootstrap`、`GET /auth/me`、`POST /auth/logout` 的非法 `X-Request-ID` 拒绝语义：统一返回 `invalid_request` / HTTP 400；`validation_failed` 保留给 HTTP 422。此前 session/logout 用 400 返回 `validation_failed`，违反前端 `CONSOLE_ERROR_STATUS` 映射，可能使 transport 无法按稳定错误码投影。bootstrap 的正式前端 Endpoint 已声明该错误，并新增 controlled HTTP 测试确认 transport 保留类型错误。
- **验证：**Console `tests/test_bootstrap_api.py tests/test_session_api.py tests/test_logout_api.py` **23 passed**；前端 `IDENTITY-HTTP: bootstrap invalid_request` **1 passed**；TypeScript typecheck 与 OpenAPI `contract:check` 42 paths 通过；Markdown/源码 `git diff --check` 通过。未运行完整 E2E。
- **边界：**仅关闭一个身份接口错误状态映射差异，不完成 F6.1 逐页面 wire/错误/时间/权限矩阵。详细记录见 [F6.1 identity error contract](acceptance/R-DASHBOARD-F6.1-identity-error-contract.md)。

### 15.273 F6.1 过时身份 API 草案的规范边界标识（2026-10-09）

- **修正：**`dashboard-prototype/docs/api/IDENTITY_AND_ACCESS_API.md` 仍描述旧的 bootstrap phase、token/session 与账号 API，和当前 Console Endpoint/Port 不一致。顶部现明确标为历史决策输入、禁止直接指导 Python 路由实现，并链接唯一 Console API 契约 §9、生成 OpenAPI 与逐页需求文档；正文历史草案保留，不伪装成当前实现。
- **验证：**目标文档链接均存在；本项纯文档切片通过 `git diff --check`。未跑构建、单测或 E2E。
- **边界：**文档标记消除了错误规范来源，但不完成 F6.1 的 machine contract/字段矩阵审计，也不证明 API 与 Python 行为等价。

### 15.274 B0.2 目标数据库首次初始化事务切片（2026-10-09）

- **实现：**新增 `SqlAlchemyBootstrapInitializationTransaction`，在调用方已经选定并准备好的目标数据库中，单个 SQL 事务写入内置 admin 的 Argon2 hash、注册来源及其加密凭证、HMAC 输入指纹与操作回执、脱敏 audit 和 `console_guard.initialized`。相同操作人/request key/输入可恢复原 receipt；同 key 不同输入返回稳定 409 `idempotency_conflict`；已初始化目标库返回持久拒绝；中途写错回滚全部事务。来源密文序列化收敛为 registry 与 bootstrap 共用的 `encrypt_registered_source_credentials()`，不会写入明文 token/password/reference。
- **验证：**Python 3.12.14 定向 ASGI bootstrap API **8 passed**、目标库初始化事务 + 隔离 SQLite **6 passed**、source-store 回归 **8 passed**；覆盖完成、回放、输入冲突、setup closed、密码哈希失败回滚、管理员密码/来源凭证不泄漏、Nacos 直接凭证与 Consul 凭证引用的注册加密及凭证解密验证。`compileall` 与 `git diff --check` 通过。source-store 首轮测试中 2 个旧测试因固定会话时间已经过期而失败；将会话 fixture 改为运行时 UTC 后对应 8 项全部通过。
- **边界：**这是目标 DB 内部事务，不是可供公网直接启用的 setup launcher：engine 由调用方提供，本实现不解析/固定用户提供的数据库网络地址，不创建目标数据库、不运行 migration、不写 runtime locator、不关闭外部 setup window，也没有跨存储崩溃恢复组合。证据仅来自隔离 SQLite；PostgreSQL/MySQL 行锁/并发、部署密钥轮换、生产 lifespan 与真实配置中心均未验收。B0.2 仍未勾，完整浏览器 E2E 仍留到所有代码完成后的最终验收。

### 15.275 B0.2 经部署策略固定地址的首次数据库引擎 factory（2026-10-09）

- **实现：**新增 `BootstrapDatabaseEngineFactory`，复用部署提供的 `BootstrapDatabaseTargetPolicy`。工厂先验证候选字段，再只解析一次 host/port/kind；拒绝策略外目标后才构造 lazy async engine，SQLite 不接受为首次生产目标。返回的 `PreparedBootstrapDatabase` 包含 engine、secret-suppressed locator URL 与该次解析得到的 `RuntimeDatabaseTarget`；PostgreSQL 固定首个 allowlisted IP 并强制 `verify-full` hostname TLS，MySQL 固定 allowlisted addresses、原 hostname 做 TLS 校验且要求 verified TLS。调用方负责 dispose engine。
- **定向验证：**PG pinned-IP/TLS 参数、策略拒绝时不创建 engine、MySQL fake driver 的 socket IP/TLS hostname 分离、禁用证书验证拒绝与可选 driver 缺失稳定失败，具体命令和结果见验收记录 §“Pinned bootstrap SQL engine factory”。
- **边界：**尚未接 coordinator、launcher/lifespan、Alembic migrate-before-use、locator 持久化和 setup-window 关窗。fake driver 不等于真实协议验证；本切片不连接网络，也不跑完整 E2E。B0.2 继续未勾。

### 15.276 B0.2 runtime locator 持久固定地址与运行期恢复（2026-10-09）

- **实现：**`RuntimeDatabaseTarget` 保存规范 hostname 与一个或多个非特殊 IP；locator schema v2 把 URL 与 target 放进同一 AEAD payload，v1 仍可读并明确保持未 pin 语义。runtime resolver 核对 locator hostname 与 URL hostname 一致，PG 通过 `hostaddr` + `verify-full` 直连，MySQL 使用共享 pinned async creator，对固定 IP 建连且以 locator hostname 验证 TLS，避免首次接入后重新解析 UI 提交的 hostname。
- **验证：**隔离 locator 测试覆盖 v2 加密/读回及 v1 兼容；runtime 测试覆盖 PG/MySQL pin 参数与 hostname 错配拒绝。完整命令和结果见 B0.2 验收记录。
- **边界：**仍未将 prepared bootstrap result 写入 locator，也未实现跨数据库/部署文件 coordinator 的 crash recovery；PG 目前持久并使用解析结果中的首个 allowlisted IP。v1 locator 和 deployment URL 保持 operator-owned unpinned 模式。真实 PG/MySQL 网络/TLS、restart、多 worker 和最终 E2E 均未运行。B0.2 继续未勾。
### 15.277 B0.2 跨存储初始化 coordinator 与局部 crash-recovery 合同（2026-10-09）

- **实现：**新增 `SqlAlchemyBootstrapInitializationCoordinator`，在独立本地 POSIX 初始化锁内重验 operator/setup grant，创建候选 pinned engine，先跑 Alembic，再将加密 runtime locator 持久化，最后委托目标库单事务写首管理员、配置源、回执、审计与 initialized guard；成功后幂等关闭外置 setup window 并释放 engine。locator 已存在且目标 URL 相同的重试复用原 pinned target，避免重新解析 DNS；下次 bootstrap 读取通过 DB guard 关闭“DB 已 commit、外置 marker 尚未 close”后的残留 open 状态。`SetupWindowFileStore` 的 CAS close 增加有界重试；本地锁 context manager 对 task cancellation 也释放 fd/flock。
- **验证：**Python 3.12.14 coordinator、pinned factory、初始化事务 **16 passed**；setup-window 与 runtime locator store **20 passed**；改动模块 `compileall` 通过。覆盖 side-effect 次序、迁移失败不写 locator、数据库不可用后复用 pinned locator、授权拒绝前不触发 DB、guard recovery、并发 close 与取消后释放锁。测试使用 fakes、临时文件和既有 SQLite transaction tests；未启动浏览器或完整 E2E，未连接 PG/MySQL/Nacos/Consul。
- **边界：**coordinator 仍未装配进 production launcher/ASGI app；operator-code provisioning/rotation 与跨 worker grant/rate-limit authority、统一 PG/MySQL TLS trust configuration、正式 startup/lifespan 和真实多 worker/restart/部署挂载验证未完成。故 B0.2 不勾；完整 E2E 按 §15.142 只在全部开发完成后的最终验收执行。验收记录见 [B0.2 persistence foundation](acceptance/R-SENTINEL-CONSOLE-B0.2-persistence-foundation.md)。

### 15.278 B0.2 首次初始化后的惰性 runtime engine 与 ASGI lifespan（2026-10-09）

- **实现：**新增内部 `RuntimeDatabaseEngineProvider` 与 `RuntimeDatabaseEngineBridge`，复用 SQL adapter 已使用的 `connect()` / `begin()` 边界。locator 缺失时保持 setup mode 且所有 SQL 访问 fail-closed；setup coordinator 写入 locator 后，当前进程的下一个 SQL 操作惰性创建、迁移并缓存 engine，无需重启。并发首次访问共用单一初始化锁；engine 已激活后 locator revision 改变则 fail-closed，不热切换数据库。ASGI lifespan 启动时若 locator 已存在先迁移/验证，shutdown 统一释放 pool；`build_sql_identity_app()` 可注入 provider，并强制 lazy-runtime 组合同时显式提供 coordinator 的 initialization reader、writer、operation reader 与 DB checker。
- **验证：**Python 3.12.14 定向测试 **12/12 passed**：惰性 provider/SQLite lifespan 6 项、SQL identity composition 4 项（含缺失 coordinator 拒绝及生命周期接线）、既有预配置数据库 ASGI lifecycle 2 项；`compileall` 与目标变更文件 `git diff --check` 通过。覆盖 setup 完成后无重启访问、并发只建一个 engine、迁移失败清理/重试、revision 改变拒绝、启动迁移与 shutdown dispose。只使用 SQLite、mocks 和局部 ASGI lifespan，没有连接真实 PG/MySQL、启动浏览器或运行完整 E2E。
- **边界：**这是 ASGI/SQL composition 可复用块，尚无完整 CLI/production launcher、部署环境统一组合、operator-code provisioning/rotation 与跨 worker grant/rate-limit authority，也未验证 PG/MySQL、多进程、生产 TLS trust 与部署挂载。SQL bridge 只保留已有 adapter 用到的两个 engine 访问方法，不导出为产品 API。B0.2 仍不勾，完整浏览器 E2E 按用户要求留到所有代码完成后的最终验收。

### 15.279 B0.2 部署级 bootstrap code authority 与 authorize CSRF（2026-10-09）

- **实现：**新增 `BootstrapAuthorizationConfiguration`，从必需部署环境输入读取 write-only operator code、绝对状态文件路径与独立 HMAC key；新增 `LocalBootstrapAuthorizationAuthority`，同时实现 code exchange 与 opaque operator-session verifier Port。仅将 code/client/grant 的 keyed fingerprints、有限失败窗口和短期 grant expiry 存入 0600 atomic file；本地 POSIX workflow lock 串行化共享该主机文件系统的 worker，code 消费后不可重用，配置 code 变化使旧 grant 失效。初始化关闭 setup window 后仍允许短期 verifier 供原 request receipt 恢复，但新的 code exchange/initialize 仍被 setup-window owner 拒绝。另修复 authorize HTTP adapter 原本仅校验 Origin、遗漏 CSRF cookie/header 双提交的问题。
- **验证：**Python 3.12.14 定向组合 **32/32 passed**，覆盖 authority + authorize API + bootstrap read + initialization coordinator；另 `test_identity_composition` **5/5 passed**，含配置型 authority 接入双 Port。覆盖真实文件 authority 经 ASGI authorize route、错误码不落盘、跨 authority 对象限流与 one-time 并发单赢家、重启/过期/rotation、closed-window 原操作恢复、csrf mismatch 在触达 authority 前拒绝。`compileall` 与 `git diff --check` 通过。无真实 operator secret、数据库、浏览器或完整 E2E。
- **边界：**仅保证同一主机的 POSIX lock/atomic replace；测试不是独立 OS process，更不证明 NFS/多节点集群语义。operator code/key 的生成与轮换仍由部署 Secret 管理，生产代理拓扑/可信客户端地址、多 worker 部署挂载及密钥轮换均未验证。B0.2 仍不勾，完整 E2E 留最终验收。详见 [B0.2 bootstrap authorization](acceptance/R-SENTINEL-CONSOLE-B0.2-bootstrap-authorization.md)。

### 15.280 B0.2 首次安装 ASGI 组合入口（2026-10-09）

- **实现：**新增 `FirstRunSqlIdentityConfiguration` 与 `build_first_run_sql_identity_app()`，以显式部署配置装配 setup-window 与加密 runtime-locator 文件 store、bootstrap code authority、初始化锁、跨存储 coordinator、只读 DB checker、惰性 runtime provider、SQL identity composition 与 ASGI lifespan。setup-window 不会被默认打开，runtime locator/authority 文件在 app 构造时不创建；网络策略、TLS 信任、key material、路径和 browser origins 全部显式配置。`sentinel-console serve` / `python -m atlas_richie.sentinel_console serve` 现通过环境组合启动，默认只绑定 `127.0.0.1`；Uvicorn 不隐式改写 proxy headers，trusted CIDR 传入 app resolver。`setup-window status/open/close` 提供明确的本机开窗管理，open 要求 operator credential，revision CAS 防止静默覆盖。PostgreSQL 与 MySQL 都可指定私有 CA bundle，MySQL hostname verification 与 required certificate validation 保持开启；`SENTINEL_CONSOLE_DASHBOARD_BASE_PATH` 可使 CLI 组合与非根路径前端产物对齐。部署 parser 拒绝 wildcard DB network、错误来源目标/浏览器 origin、缺失 key 和非绝对 CA 路径；authority 文件路径必须互异，会话时长必须为正。同一 Nacos/Consul checker 可由首次 source-check 与已登记 source-check 共用，并通过适配器只执行只读探测。
- **验证：**composition smoke **2/2 passed**、首次 source checker adapter **2/2 passed**；本切片 CLI + setup-window store + deployment parser + first-run composition + identity composition + static-web base-path suite **21/21 passed**（项目现有 Python 3.13.15 venv），`compileall` 与 `git diff --check` 通过。无真实 DB/网络/反向代理，不启动浏览器，未运行完整 E2E；尝试从在线依赖补装因 sandbox 网络限制未能完成，已复用项目 venv。
- **边界：**CLI 与环境组合已实现，但不等于生产部署验收。仍需 operator secret 投递/轮换、多 worker 与共享挂载策略、真实反向代理 client identity、PostgreSQL/MySQL migrations/并发和浏览器到 Python 最终链路验收。local authority files 仅承诺单机 POSIX 锁，不承诺 NFS/多主机。B0.2 不勾，完整 E2E 仅在所有实现任务完成后执行。

### 15.281 F5.2 重构后动态国际化 producer 覆盖对齐（2026-10-09，局部完成）

- **实现/测试：**动态 `t()` 静态审计当前发现 21 个 AST 无法枚举的调用点；更新显式调用点清单以匹配实际源码，并补充角色编辑限制原因与角色深链 fallback 查询状态的 producer 三语 runtime 覆盖。初始化表单校验 producer 的期望键同步为现行 `setup.required`，移除已不再由该表单验证产生的旧键预期。
- **验证：**`npm run i18n:check` 三语各 1153 条消息、1012 个静态可校验键且无模板拼键；`node --test tests/i18n/dynamic-callsite-coverage.test.mjs tests/i18n/catalog.test.mjs` **12/12 passed**；`npm run typecheck` passed。
- **边界：**此切片修复了清单漂移并增强 producer 级三语覆盖，不证明每个动态分支在页面上的实际视觉效果、所有有草稿页面切换语言时 URL/草稿不变，也不关闭 F5.2；完整页面/浏览器矩阵继续放在最终验收，不在每个小改动后触发 E2E。

### 15.282 B0.4 注册配置源到系统连接观察的真实只读投影（2026-10-09，局部实现）

- **实现：**新增 `RegisteredSourceSystemConnectionsReader`，复用 SQL 注册源读取 Port，将实际注册的 Nacos/Consul identity 投影为 `config-center` 观察记录；注册记录只证明“已配置”，所以状态为 `unknown`、原因 `no-probe`，不填延迟/能力/探测时间，不包含 endpoint/凭证。权威注册表为空时返回明确 `unconfigured/not-configured`。注册表不可用时转为有限 `SystemConnectionsAuthorityUnavailable`，HTTP 边界仍返回安全的 503。SQL identity app 在未显式注入更完整的 host-owned connection reader 时装配该投影；显式 reader 优先。
- **验证：**新投影、system connections HTTP、SQL identity composition、first-run composition 定向测试 **15/15 passed**；Console 源码及相关测试 `compileall` 通过。测试仅用合成 sources、SQLite/ASGI 既有替身组合，不连接真实数据库或 provider。
- **边界：**这是系统连接页的一种真实配置事实，不是 Nacos/Consul 连通性探测；metrics backend、reporting collector、实例目录、资源压力/QPS/TPS/RT、protocol active-version 均仍需要各自权威数据源与实现。B0.4 保持未勾；浏览器 E2E 按约定留至全部代码完成后的最终验收。

### 15.283 B0.4 已登记配置源的探测结果持久化与 revision 隔离（2026-10-09，局部实现）

- **实现：**新增 `console_registered_source_probe`（v0014）保存每个已登记来源最近一次非敏感探测事实，包含 source revision、探测/过期时间、单调时钟测得的 latency、能力枚举和有限失败原因；没有 endpoint、凭证或原始异常。仅 `keep` 已存凭证且提交探测的 sourceId/revision/provider/endpoint/location 仍精确匹配当前注册事实时才写入；注册前检查、凭证引用检查和草稿 endpoint 检查只返回本次结果，不污染系统页。系统连接读取仅按当前 sourceId + revision 查询，配置 revision 变化后旧探测退回 `unknown/no-probe`；删除 source 由 FK cascade 清理。SQL identity composition 将同一 store 装配为 recorder/reader，显式 connection reader 仍优先。
- **验证：**Python 3.12.14 `py_compile` 修改文件通过；Python 3.13.15 venv 下 source-store ASGI/SQLite 集成、连接投影、source-check API、identity composition 定向测试 **15/15 passed**；覆盖未保存候选不写入、已保存配置检查后系统页显示可用/能力/延迟、revision 改变后旧 probe 不再生效；`git diff --check` 通过。未连接真实数据库或 Nacos/Consul；本次不运行浏览器或完整 E2E。
- **边界：**这是最近一次、带 TTL 的配置中心只读探测，不是持续健康轮询；过期状态由既有前端 TTL 标识表达。仍需接入真实探测器/部署实例验收，以及 metrics backend、reporting collector、实例目录和资源指标数据源。B0.4 保持未勾；完整 E2E 按用户决定只在所有实现任务完成后的最终验收执行。

### 15.284 B0.4 系统协议观察 Port 接入 first-run ASGI 组合（2026-10-09，装配完成）

- **实现：**将既有 `SystemProtocolsReader` 从 `build_sql_identity_app` 暴露到 `FirstRunSqlIdentityConfiguration`，并原样传入 `build_app`。协议事实仍由宿主 runtime authority 提供；未注入 reader 时该 route 继续不可用，不从 Python 包版本推断 active protocol，也不把 supported 静态清单冒充协商结果。此改动复用现有消费方 Port，不新增通用 Service、事件或其他模式。
- **验证：**Python 3.12.14 `py_compile` 修改文件通过；Python 3.13.15 venv 下 identity composition、first-run composition 与 system-protocol API 测试 **13/13 passed**。无真实 runtime protocol authority 或浏览器验收。
- **边界：**只打通宿主事实源的依赖装配，不产生协议版本事实；仍需 Sentinel runtime/collector 实际提供 supported/active/compatibility 的来源、服务组合和最终系统页验证。B0.4 保持未勾。

### 15.285 B0.4 系统/遥测查询 Ports 透传 first-run ASGI composition（2026-10-09，装配完成）

- **实现：**`FirstRunSqlIdentityConfiguration` 现可接收宿主提供的 `SystemConnectionsReader`、`SystemAuditReader`、`SystemProtocolsReader`、`ObservationCatalogReader`、`InstanceCatalogReader`、`InstanceObservationReader`、`MetricsReader`、`FleetOverviewReader`、`IncidentTimelineReader` 与 `IncidentEvidenceReader`，逐个透传至 identity/ASGI app。显式系统连接 reader 仍覆盖默认 registered-source 投影；不注入时不伪造 metrics/collector/active protocol 健康。组合层不创建未知事实源，reader 本身仍负责每个 query 的 scope、权限、freshness 与 unavailable 语义。
- **验证：**Python 3.12.14 `py_compile` 修改文件通过；Python 3.13.15 venv 下 identity/first-run composition、系统协议/连接/审计、observation catalog、fleet overview、实例目录、incident timeline APIs 定向测试 **59/59 passed**；组合测试断言宿主 reader 原对象逐项透传；`git diff --check` 通过。未访问真实数据源或浏览器。
- **边界：**此切片只完成 runtime Ports 装配；当时 SQL identity app 尚未默认装配审计读取器，审计默认 SQL 事实源随后由 §15.287 补齐。metrics/collector、app/instance inventory、incident 或 protocol reader 未接入时，对应 API 仍 unavailable/unknown。B0.4 保持未勾，最终 E2E 仅在全部实现任务之后执行。

### 15.286 前端当前 TypeScript 基线复核（2026-10-09，定向门禁）

- **验证：**在当前工作树的 `components/sentinel/dashboard-prototype` 执行 `npm run typecheck`（`tsc --noEmit`），退出码 **0**。这是本轮当前 React 源码的静态类型证据，不代表 lint、生产构建、页面渲染或 E2E 通过。
- **验证节奏：**继续按本清单开头的约定执行：实现期间做与改动匹配的定向检查和功能组回归，完整浏览器与跨前后端 E2E 只留到全部实现收口后的最终里程碑。
- **边界：**本次没有修改应用代码，也未运行全量检查或浏览器；F7 与 B0 的未完成项不因 typecheck 通过而关闭。

### 15.287 B0.4 SQL 持久化审计事件接入默认 Console composition（2026-10-09，垂直功能切片）

- **实现：**SQL audit reader 现映射审计表当前所有受支持写入动作：账号创建/角色/状态/改密、配置源登记/更新、规则候选校验、草稿保存/删除、版本固化、发布、活动计划创建/取消及首次系统初始化。`SYSTEM_INITIALIZE` 是唯一允许 `actor_id = null` 的动作；其他动作缺少操作者仍 fail-closed，不合成身份。`build_sql_identity_app` 未收到宿主 `SystemAuditReader` 时默认装配 `SqlAlchemySystemAuditReader`；显式注入仍覆盖默认值。React 端同步有限 action union、strict wire schema、actor 可空模型和系统操作者文案，并更新 3 种语言与生成的 Console OpenAPI。此处审计范围是 Console 自身已有 SQL audit facts，不包括尚未接入的 Agent / Collector 事件。
- **定向验证：**Python `pytest tests/test_system_audit_persistence.py tests/test_identity_composition.py tests/test_system_audit_api.py -q` **16 passed**，覆盖现有写入动作映射、首次初始化无 actor、非初始化无 actor 拒绝、未知持久化 action fail-closed 与默认/显式 composition。前端 `npm run typecheck` 通过，SYSTEM-AUDIT logic **5/5**、HTTP **3/3**，`npm run contract:generate` + `npm run contract:check` 验证 **42 paths**，`npm run i18n:check` 三语各 **1156** 项通过。
- **边界：**验证使用现有 SQLite/受控 HTTP 测试，不是 PostgreSQL/MySQL 真实部署或浏览器 E2E；Collector/Agent reporting 事件、系统审计页面渲染仍未验收。完整 E2E 留待所有开发任务收口后执行。

### 15.288 B0.3 first-run ASGI composition 托管发布 worker（2026-10-09，组合层接线）

- **实现：**`FirstRunSqlIdentityConfiguration` 新增可选的 `RunRulePublicationWorker` 注入，经 SQL identity composition 原样传入 `build_sql_identity_app` 的生命周期入口。Console 组合只接受宿主已经配置好的 worker，不在 first-run CLI 中猜测发布来源、DNS/TLS 策略或凭证解析器；未注入时仍不启动 worker。启动、有限轮询、单次异常隔离与 ASGI 关闭取消仍由既有 `RulePublicationWorkerLoop` 管理，没有新增第二套后台任务框架。
- **设计/验证：**GoF 23 模式表已评估，本切片复用既有应用服务 Port 与 ASGI 生命周期协作，不引入新的 GoF 模式或 provider 实现。first-run composition 定向测试断言显式 worker 对象被原样透传；既有 `test_rule_publication_worker_lifecycle.py` 验证启动、停止、失败后继续和输入边界。
- **边界：**这只让部署组合能够把已配置 worker 纳入 app lifespan，不构造或启用 Consul/Nacos worker，也不证明后台发布或真实 provider 行为。worker 的具体部署装配、安全 target provisioning API、计划恢复及 Nacos CAS 仍开放；本切片不运行完整 E2E。

### 15.289 B0.3 规则发布目标管理 API 与前端垂直切片（2026-10-09）

- **实现：**复用 `POST /api/v1/rulesets/{bindingId}/commands`，新增严格 `configure_target` 命令解析、SQL target CAS、命令幂等回执与审计原事务写入，并保留现有 admin/session/CSRF 校验。新增 `GET /api/v1/rulesets/{bindingId}/publication-target`，按当前 session 返回精确目标/target revision/source revision；未配置时显式返回 `target: null`，只读 provider 地址字段，不投影凭证或规则正文。SQL identity composition 装配既有 `SqlAlchemyRulePublicationTargetReader`。React 增加目标 DTO、strict wire schema、HTTP Port/operation、规则部署 workflow、Astryx Dialog 管理面板、Nacos/Consul 字段和中英日文案；HTTP Mock 支持读取、配置、重新读取及过期 revision 冲突。Console OpenAPI 已由 feature schema 重生成至 **43 paths**。
- **定向验证：**Python `pytest tests/test_rule_publications_api.py tests/test_rule_mutation_store.py -k 'target_read or configure_publication_target or configure_target_rejects_stale_source' -q` **4 passed**；前端 `npm run typecheck`、`npm run lint` 通过；focused HTTP Mock 规则部署测试 **1/1 passed**，覆盖首次空目标、配置、读回和 stale CAS；`npm run contract:generate` 生成 43 paths。
- **验证边界：**曾运行一次完整 `npm run test:http -- --runInBand`，暴露此前遗漏的 schema transform 不可导出 JSON Schema、路由数 42→43 断言和受沙箱限制的 loopback `EPERM`；已修 schema/路由断言，但未重跑完整 HTTP 套件。没有运行完整 E2E、没有打开外部浏览器、没有连接真实 Python 部署/数据库/Nacos/Consul。SQLite 不证明 PostgreSQL/MySQL 并发；Mock 通过不证明 rendered UI。目标管理代码现已具备独立单测/契约证据，B0.3 仍因 provider 发布/回读、计划恢复、instance receipt、生产组合和真实验收未完成而保持未勾。

### 15.290 B0.3 Consul worker 支持首次安装的惰性数据库桥接（2026-10-09）

- **实现：**修复首次安装组合边界不一致：发布 worker 只使用 SQL engine 的 `connect()` / `begin()`，但 Consul worker factory 曾强制要求具体 `AsyncEngine`，因此不能接收 setup 完成后才激活的 `RuntimeDatabaseEngineBridge`。改为校验最小结构化 SQL connection contract，不绑定某个 engine 实现；真实 `AsyncEngine` 行为保持不变。
- **定向验证：**`pytest tests/test_rule_publication_worker_composition.py -q` **2 passed**。新增测试用未配置 locator 构造惰性 bridge 并成功组装 worker；测试不执行 SQL、不连接 Consul，也不创建后台生命周期。`git diff --check` 通过。
- **边界：**这只让部署拥有者可以用同一个首次安装 engine bridge 显式装配 Consul worker；没有自动选择目标策略、解析部署凭证、启用 worker、触发 provider 网络请求或实现计划恢复。Nacos CAS 与真实 PostgreSQL/MySQL/Consul、多 worker 和最终 E2E 仍未验收；B0.3 保持未勾。

### 15.291 F4.23 Mock storage 写入失败时保持登出匿名（2026-10-09，局部修复）

- **问题与实现：**复现 Mock 管理员角色保留在 `localStorage`、注销写入被忽略但未抛错时，读取路径仍优先返回旧 `admin`。现在写入后读回校验目标值；storage 抛错或静默未保存时，将当前 storage 对象关联的内存 principal 作为同页覆盖，因此显式注销立即保持匿名。切换到另一个 storage 对象时丢弃旧内存覆盖并重新读取，避免跨测试/浏览器上下文污染。
- **定向验证：**新增“旧 admin + setItem 静默失败 + 注销仍匿名”回归；Mock identity logic **3/3 passed**，`npm run typecheck`、`npm run lint`、`npm run format:check`、`git diff --check` 均通过。测试不启动浏览器或 Python 服务。
- **边界：**浏览器重载会丢失内存覆盖；若 storage 持续不可写，不能保证跨重载匿名态。生产 session 真相仍由 Python 服务端负责；该修复只关闭 Mock 同页状态回退，不关闭 F4.23，也不替代最终浏览器/真实后端验收。

### 15.292 F4.20 首次连接检查原因与安全重试（2026-10-09，局部完成）

- **实现：**初始化页根据服务端稳定原因枚举分别展示认证失败、网络连接失败和当前方式不支持的简中/英文/日文提示；原始异常消息与凭证仍不进入页面文案。通用 transport/网络错误继续使用通用安全提示。用户再次显式检查时以新结果替换先前失败事实，不自动重试、不保存凭证。
- **定向验证：**`npm run test:logic:focused -- 'SETUP-CHECK'` **2/2 passed**，覆盖数据库认证失败和配置源方式不支持后显式重试得到可达，以及 setup snapshot 不含合成数据库/管理员秘密；HTTP 受保护 endpoint 在实际 bootstrap authorize/CSRF 顺序后保留数据库/来源稳定失败原因，`BOOTSTRAP-CHECK` **1/1 passed**；`npm run check:fast` exit **0**（typecheck、format、lint、OpenAPI contract）；`npm run i18n:check` 通过（三语各 1,175 keys），`npm run test:i18n-tools` **29/29 passed**。
- **边界：**当前测试覆盖 workflow 的失败/重试语义和原因值，不是 React 页面渲染、真实网络诊断或 Python Console 联调；完整浏览器 E2E 按约定留在全部代码完成后的最终验收。F4.20/F4.21 仍未关闭。

### 15.293 B0.2 setup-window CAS 独立 worker 进程竞争（2026-10-09，局部验证）

- **实现：**新增 `spawn` 模式的双进程测试；两个独立 Python 进程共享一个 disposable 本地 setup-window 文件和同一预期 revision，同时写不同状态。测试要求只有一个更新成功，另一个观察到 CAS revision conflict，最后落盘快照必须与成功者返回的 revision/state 完全一致。
- **验证：**`PYTHONPATH=components/sentinel/sentinel-console/src .venv/bin/pytest -q components/sentinel/sentinel-console/tests/test_setup_window_file_store.py` **13 passed**。
- **边界：**证明当前本地 POSIX 测试文件系统上的多进程锁/CAS，不证明 NFS、Kubernetes 多副本共享卷、跨主机锁语义或 PostgreSQL/MySQL 首次初始化并发。部署拓扑验收与 B0.2 整体仍开放。详细测试设计见 [B0.2 local process lock](acceptance/R-SENTINEL-CONSOLE-B0.2-bootstrap-local-process-lock.md)。

### 15.294 B0.3 发布 worker 对账时等待 provider 最终可见（2026-10-09，局部验证）

- **实现/测试：**扩展 durable publication worker 的受控 provider 测试替身，模拟写请求已被接受但首次回执丢失、后续一次精确读取仍返回旧快照、再下一次读取才观察到候选字节。回归要求中间读取继续保持 `unknown`，不能误报冲突或完成；候选精确可见后才推进 read-back/completion，并断言 provider write 全程只调用一次。
- **验证：**`PYTHONPATH=components/sentinel/sentinel-console/src .venv/bin/pytest -q components/sentinel/sentinel-console/tests/test_rule_publication_worker.py` **4 passed**；针对新增文件 `git diff --check` 通过。未运行浏览器 E2E 或访问真实 provider。
- **边界：**这是应用 worker 对“结果未知 + provider 读延迟”的局部恢复合同测试，不证明 SQL lease fencing、Nacos/Consul 最终一致性、真实网络或多 worker 部署。真实 provider 与完整发布恢复仍属 B0.3，最终 E2E 留至全部实现后。

### 15.295 B0.3 Worker 单条领取避免批次排队期间租约提前消耗（2026-10-09，局部实现）

- **实现：**`RunRulePublicationWorker.run_once(limit=N)` 不再一次领取 N 条后顺序执行；现在每轮只领取一条，执行结束再领取下一条，最多处理 N 条。每条任务的 lease 因此从即将开始执行时才启动，慢任务不会消耗同批后续任务的租约。未知结果不会在同一轮里立即重复领取同一 request key；仍由下一次轮询恢复。拒绝 `limit < 1` 和错误违反“单条领取”Port 的实现。
- **定向验证：**`test_rule_publication_worker.py` **6 passed**，新增 `run_once(limit=5)` 回归确认 worker 以 `limit=1` 逐次向 Outbox 领取，成功完成后停止；越过 100 上限在接触 Outbox 前拒绝；原有 provider write/read-back、未知回执恢复/最终可见与基线冲突测试继续通过。`git diff --check` 通过。Ruff 未运行：当前 `.venv` 没有 `.venv/bin/ruff`。
- **边界：**这修复的是批次内部尚未开始的排队 lease 风险，不延长单条任务自身超过配置 lease duration 的情况；若 provider 请求可超过 lease，仍需由具体 provider timeout/后续续租设计覆盖。没有证明真实数据库、多 worker、配置中心或网络行为；完整 E2E 保持待全部实现后的最终节点，B0.3 不勾选。

### 15.296 B0.3 长发布操作中的 claim lease 心跳续租（2026-10-09，局部实现）

- **实现：**应用 `RulePublishOutbox` Port 声明既有 SQL `renew_claim` 能力；worker 在单条发布执行期间按 lease duration 的三分之一触发续租，把每次新返回的不可变 claim 快照用于后续 phase/completion/rejection fencing。续租失败会取消当前执行并向生命周期边界传播失败；若取消时 provider 写已 dispatch，持久 phase 保持可 reclaim 的 `running/unknown` 事实，后续 worker 继续精确对账，不盲目重发。执行结束或取消时心跳任务会被停止并 await 清理。
- **定向验证：**`test_rule_publication_worker.py` **8 passed**。新增真实异步慢 provider 场景（60ms lease、110ms read），验证多次续租后仍能完成且 provider 只写一次；另注入 outbox 续租失败，断言 worker 停止且未产生 provider write/错误终态。`py_compile` 与 `git diff --check` 通过。测试不启动 SQLAlchemy/数据库，因此只证明应用编排和可替换 Port 行为。
- **边界：**本轮在组件专属虚拟环境补跑 worker/outbox/publication SQL 与 mutation-store suite，合计 **36 passed**；未验 PostgreSQL/MySQL、多 worker 竞争、真实 provider 请求取消语义或服务重启恢复。完整 E2E 仍待全部实现后的最终节点，B0.3 不勾选。

### 15.297 B0.3 修复 SQL 规则命令测试的过期 session fixture（2026-10-09，定向验证）

- **原因与修复：**`test_rule_mutation_store.py` 的 admin/view 测试 session 固定在 `2026-10-09 09:00 UTC` 到期，而 SQL read authorization 使用真实 UTC 时钟；同日之后运行便在 operation receipt/read-back 上返回 401。夹具现以测试启动时的 `datetime.now(UTC) + 1 day` 创建 session，使验证不再依赖具体运行时刻；业务事件时间仍保留固定 `_NOW`。
- **验证：**`PYTHONPATH=src .venv/bin/pytest -q tests/test_rule_publication_worker.py tests/test_rule_publication_worker_lifecycle.py tests/test_rule_publication_worker_composition.py tests/test_rule_publication_reader.py tests/test_rule_mutation_store.py` **36 passed**。本地默认 `.venv` 缺 SQLAlchemy；改用 `sentinel-console/.venv` 执行，未安装依赖或访问网络。
- **边界：**此修复仅令 SQLite SQL/worker 定向测试对运行时间稳定，不证明 PostgreSQL/MySQL、真实 Consul/Nacos、多 worker 或部署运行；没有运行完整 E2E，按验证节奏留在最终验收。

### 15.298 B0.1 Nacos 3 探测令牌不进入 URL（2026-10-09，协议修正）

- **问题与实现：**[Nacos 3 官方 Quick Start](https://nacos.io/en/docs/latest/quickstart/quick-start-kubernetes/) 要求管理 API 通过 `accessToken` 请求头认证；Nacos 注册源只读探测此前把短期登录令牌放入 `accessToken` query 参数。现改为仅通过请求头发送，绝不进入 URL/query；同时拒绝空 access token，不继续尝试 Admin API。对直接认证输入也删除了 `assert` 假设，缺少用户名/密码时返回稳定的 unsupported 探测结果。
- **验证：**注册源 checker、首次来源 adapter、setup source-check API 与 registered-source API 定向套件合计 **25 passed**（checker 文件单独 **9 passed**）；新增合同断言令牌在 header 中且 query 不含 `accessToken`，并拒绝空 token。`compileall` 通过。Ruff 未安装于组件虚拟环境，未运行。
- **边界：**该修复仅针对 Nacos 3 的只读连接探测，不实现配置发布 CAS、不证明真实 Nacos 版本/权限插件行为。没有访问真实 Nacos、运行完整 E2E 或配置写入；真实 provider 验收仍留在最终里程碑。

### 15.299 F5.6 当前生产包体隔离画像（2026-10-09，基线记录）

- **方法：**从 `components/sentinel/dashboard-prototype` 执行 `vite build --outDir /private/tmp/sentinel-console-profile-current --emptyOutDir`，再对该临时产物运行 `node scripts/build/bundle-report.mjs /private/tmp/sentinel-console-profile-current`；未覆盖仓库现存 dist/Sites 产物。
- **结果：**生产入口 JS **756,750 B**；manifest 初始静态依赖 closure **974,755 B / gzip 265,171 B**；另有 **41 个 deferred entries**。Nivo line renderer 位于独立 **333,740 B / gzip 113,480 B** 延迟 chunk，不属于首屏闭包；Astryx 全局 CSS 主文件 **218,005 B / gzip 40,180 B**。构建通过，但仍提示单 chunk 超过 500 KB。
- **判断：**现有路由与图表已按需加载。只添加 vendor chunk 会重排相同静态依赖，不会降低初始下载总量，因此本次不为消除 warning 添加手工拆包。下一步应按真实模块来源评估共享 JS/全量 Astryx 样式，而不是调大 warning 阈值或复制组件样式。
- **边界：**该临时生产构建证明当前源码可由 Vite 产出并提供包体基线，不证明浏览器传输/解析性能、Sites/wheel 产物或视觉渲染；没有运行浏览器或 E2E。F5.6 继续未完成。

### 15.300 B0.3 允许取消被阻塞的活动计划（2026-10-09，局部修复）

- **问题与实现：**页面设计合同明确允许取消尚未执行或已阻塞的计划，但 SQL mutation store 只接受 `pending`。现在取消命令对 `pending` 与 `blocked` 两种状态统一要求精确 revision，并通过 SQL 条件更新竞争保护；其它生命周期状态与旧 revision 仍返回 conflict。未改变“取消不代表回滚已发生发布”的语义。
- **回归证据：**先在当前代码上运行新增的被阻塞计划取消断言，复现 `REJECTED`（预期应完成）；修复后 `.venv/bin/pytest -q tests/test_rule_mutation_store.py` **16 passed**，覆盖 pending/blocked 的当前 revision 成功与 stale revision 冲突。目标模块及测试 `compileall` 通过，`git diff --check` 通过。
- **边界：**仅使用迁移链至 `0009` 的隔离 in-memory SQLite；没有 PostgreSQL/MySQL 并发、计划执行 worker、发布恢复、外部配置源或 browser E2E 证据。B0.3 继续未勾，完整 E2E 仍留最终验收。

### 15.301 B0.3 活动计划持久 Claim、发布关联与读回门禁（2026-10-09，SQL 垂直切片）

- **实现：**新增 Alembic `0016_rule_activation_plan_leases`，为活动计划保存 claim token、lease expiry 与 attempt count；新增 application `RuleActivationPlanWorkQueue` Port 和 SQL adapter。到期 pending 原子转为 activating，到期 active 原子转为 restoring；过期的 activating/restoring 可由另一个 worker 换新 token 接管。续租、关联 publication、blocked 与完成迁移均要求 plan revision/state/token 仍匹配。只有与计划关联的 publication 验证、配置写入、精确读回三阶段都持久成功，计划才能进入 active/completed。没有进程内计划定时器，也没有在 SQL claim adapter 内执行 provider 写入。
- **定向验证：**SQLite migration chain 至 `0016` 下，活动计划 queue 与创建/重叠/取消测试 **4 passed**；覆盖到期 activation、重复 claim 不重复领取、续租、到期接管、旧 token 冲突、到期 restoration、未完成 read-back 拒绝、verified publication 完成 activation/restoration 及 blocked 释放租约。新增 Python 源码/迁移/测试 `compileall` 与 `git diff --check` 通过。
- **边界：**SQLite 忽略 `FOR UPDATE SKIP LOCKED`，所以这不是多连接/多进程、PostgreSQL/MySQL claim 竞争证据。Claim queue 尚未接调度循环和系统 execution command/outbox 创建；不证明重启恢复后唯一 publication、system actor audit、provider 发布、runtime receipt 或实例收敛；真实配置中心及完整 E2E 均未运行。B0.3 不勾，最终 E2E 仍只在所有代码收口时运行。详情见 [活动计划持久化记录](acceptance/R-SENTINEL-CONSOLE-B0.3-activation-plan-persistence.md)。

### 15.302 F4.12 实时监控前端切片关闭（2026-10-09，聚焦验证）

- **确认范围：**按清单顺序回到尚未勾选的 F4.12。复核正式 monitor application/UI、指标 HTTP mapper 与 publication annotations；现有实现由单一 monitor owner 管理轮询、窗口查询、超时、暂停/恢复、权限撤销与 dispose，不创建第二份样本缓存，也不把缺测指标伪装成零。
- **定向验证：**`npm run test:logic:focused -- 'MONITOR-'` **9/9 passed**；`npm run test:http:focused -- 'METRICS-MONITOR'` **1/1 passed**；`npm run check:fast` 通过（typecheck、Prettier、ESLint、Console OpenAPI 43 paths）。覆盖迟到撤权响应、超时、stale 保留与自动恢复、StrictMode 生命周期以及 64 个 owner 的轮询/订阅释放。图表 publication 标注、有效 app-two stale→自动恢复和切离路由后停止轮询沿用 acceptance 文档中的既有 IAB 页面证据。
- **边界：**本轮未打开浏览器、未启动 Chrome/Edge/CDP、未运行 E2E。F4.12 仅关闭前端代码和其定向合同；真实 Console/Reporter/Collector 故障与生产主机长时资源剖析归 B0.4/B0.5 或最终运行验收，不以 Mock 冒充。最终跨页 E2E 继续留到所有实现完成后。详细证据见 [F4.12 验收记录](acceptance/R-DASHBOARD-F4.12.md)。

### 15.303 F4.20 服务端验证拒绝与明确重提合同（2026-10-09，定向逻辑）

- **协议边界：**当前 bootstrap initialize operation receipt 仅包含 `status`、`requestKey`、`operationId` 与稳定 `reason`（`validation` / `setup-closed` / `dependency`），没有服务器字段路径或逐字段问题列表。前端不伪造字段归属；可精确定位的错误由本地纯校验负责，服务端 `validation` 拒绝映射为通用、脱敏的拒绝反馈。
- **实现与验证：**新增 `SETUP-COMMAND server validation receipt` workflow 测试：服务端已知拒绝保持 `rejected/validation`，状态快照不含初始化密码；workflow 不自动重放，用户后续明确提交修正后的输入时产生新的 request key，只有完成回执加 bootstrap 权威确认才进入 `ready`。`npm run test:logic:focused -- 'SETUP-'` **18/18 passed**；`npm run check:fast` 通过（TypeScript、Prettier、ESLint、Console OpenAPI 43 paths）。
- **边界：**仅证明前端 workflow 的已知拒绝与显式重提状态合同，不证明 mounted 页面保留/呈现所有字段、不等于服务端给出可定位的字段错误；没有运行 IAB 或 E2E，也未连接真实 Python Console、数据库、Nacos 或 Consul。F4.20/F4.21 仍未完成，完整 E2E 继续留到全部代码完成后。

### 15.304 F4.20 初始化拒绝原因的三语恢复反馈（2026-10-09，定向验证）

- **实现：**新增 `initializationFeedbackKey` 纯投影，将 `validation`、`setup-closed`、`dependency` 三种已知拒绝映射到各自提示，不将服务端缺失的 field path 伪装成字段错误。简中、英文、日文说明分别给出修正后明确提交、重新读取系统状态或检查依赖后明确重试的动作；未知写结果仍使用“先核查原操作、不要重复初始化”的独立提示。
- **测试：**`SETUP-PRESENTATION` 覆盖三种拒绝原因和未知结果映射；`I18N-DYNAMIC-SETUP-FEEDBACK` 通过实际 i18next catalog 在三种 locale 断言文案非空、键可解析且三原因文案不同；动态调用点登记至 producer runtime test。`npm run test:logic:focused -- 'SETUP-'` **19/19 passed**，`node --test tests/i18n/catalog.test.mjs tests/i18n/dynamic-callsite-coverage.test.mjs` **13/13 passed**，`npm run check:fast` 与 `npm run i18n:check` 通过（三语各 1,177 条）。
- **边界：**这是真实 locale catalog + 前端 projection 的测试，不是 mounted 页面、浏览器或 Python 后端验收；没有访问数据库/配置中心，也没有运行完整 E2E。F4.20/F4.21 保持未完成。

### 15.305 F4.20 初始化拒绝反馈的实际 React 组件渲染（2026-10-09，SSR 定向验证）

- **实现：**将 `InitializationFeedback` 实际组件加载进 Vite SSR 模块图，在 React `I18nextProvider` 内以 `renderToStaticMarkup` 渲染 `validation`、`setup-closed`、`dependency` 三个拒绝快照；对每个 locale 检查组件最终 HTML 含对应恢复文案，并且不输出请求标识或凭证 sentinel。该证据比只测试 key→catalog 映射多覆盖一层真实 UI 组件组合，但不是浏览器 mount/E2E。
- **验证：**`npm run test:logic:focused -- 'SETUP-'` **19/19 passed**；`node --test tests/i18n/catalog.test.mjs tests/i18n/dynamic-callsite-coverage.test.mjs` **13/13 passed**，包括三语下真实 `InitializationFeedback` 组件渲染；`npx prettier --check tests/i18n/catalog.test.mjs` 通过。
- **边界：**SSR 不执行浏览器交互、表单事件或 CSS 布局，不替代 mounted 页面各状态验收；无 Python Console/真实数据库/配置中心。F4.20/F4.21 仍开放，完整 E2E 留在实现最终阶段。

### 15.306 F4.21 一次性 setup 授权命令与权威回读单飞（2026-10-09，聚焦合同）

- **修复：**一次性授权的 `command` 在 POST 返回成功后会结束自己的 pending 状态，但实际用例直到强制 gate read-back 确认才完成。workflow 现把互斥范围延伸到整个用例窗口；重复授权、外部 bootstrap refresh 与 inspect 在此期间返回 `DUPLICATE`，不能覆盖待确认的读回。成功或失败离开窗口后正常释放；one-time code 不出现在 workflow snapshot。
- **验证：**`npm run test:http:focused -- 'IDENTITY-MOCK: first-run|BOOTSTRAP-AUTH'` **2/2 passed**；`npm run test:logic:focused -- 'SETUP-'` **19/19 passed**；`npm run check:fast` exit **0**（typecheck、Prettier、ESLint、Console OpenAPI 43 paths）。
- **边界：**该测试证明浏览器端 Port/workflow 合同，不证明服务端并发消费一次性 code、持久授权事务或页面渲染。未运行 E2E、Chrome/Edge/CDP，也未连接真实 Python Console/数据库/配置中心。F4.21 继续开放。

### 15.307 F4.22 登录限流延迟的可恢复 UI 冷却（2026-10-09，局部实现）

- **实现：**登录容器只接受 HTTP 429 + 稳定 `rate_limited` code 的 `AppError.retryAfterMs`，并按 Console wire 的 `RetryAfterMs` 上限归一化；缺失、零值或非法 delay 不擅自制造等待。挂载页以内存 deadline 管理冷却，冷却中仍可编辑账号/密码，但禁用按钮并阻止表单 Enter 重提；定时结束后恢复提交。用户编辑凭据会清除已知拒绝反馈，但不会清除服务端要求的冷却。三语新增带秒数的限流文案；服务端限流策略仍为最终权威。
- **验证：**`npm run test:logic:focused -- 'F4[.]22'` **5 passed**，覆盖已知/未知错误边界、有效/缺失/零/负/非有限/超界 retry delay 与编辑后保持冷却提示；`node --test tests/i18n/catalog.test.mjs` **12 passed**，动态 callsite coverage **1 passed**，`npm run i18n:check` 通过（三语各 1,180 条）；`npm run check:fast` exit **0**（TypeScript、Prettier、ESLint、Console OpenAPI 43 paths）。
- **边界：**尚未用挂载浏览器交互验证倒计时、可编辑输入与提交拦截视觉/键盘行为，也未跑 Python→React 真实服务链路或完整 E2E。冷却 Hook 目前由 typecheck/lint 覆盖，retry metadata 与反馈 projection 有定向逻辑测试；F4.22 整项继续未勾，最终 E2E 按约定留到所有实现完成后。

### 15.308 F4.20 连接检查防重复提交且保留表单可编辑（2026-10-09，React SSR 切片）

- **实现：**`InitializationPage` 从 database/source query snapshot 派生独立 pending 标记并传入向导；pending 期间仅禁用对应的连接检查按钮，不锁定连接表单。application workflow 也拒绝同类 pending 检查的重复调用，但数据库与来源检查互不阻塞；用户仍可修改数据库/provider/auth 配置，既有 `invalidateChecks()` 会取消迟到检查并清除旧确认。
- **验证：**`npm run test:logic:focused -- 'SETUP-CHECK'` **3 passed**，覆盖连接结果脱敏、字段变更失效、迟到响应不能复活及同类单飞/异类并发；`node --test tests/i18n/catalog.test.mjs` **13 passed**，新增真实 `SetupWizard` SSR 测试覆盖 storage/source 步骤在三语下的 idle/pending 两态，断言 pending 按钮禁用且连接字段仍存在并可编辑；`npm run check:fast` exit **0**（TypeScript、Prettier、ESLint、Console OpenAPI 43 paths）。
- **边界：**SSR 证明实际 React 树的 disabled/field 属性投影，不模拟浏览器点击、焦点、网络中止或 CSS；数据库与规则源仍为测试 Port/静态 fixture，没有连接 Python Console、真实数据库、Nacos 或 Consul。F4.20 继续未勾，完整 mounted 页面及真实后端验收留至最终 E2E。

### 15.309 F4.26/F4.29 本人账号角色或状态变更后重读会话 authority（2026-10-09，前端工作流切片）

- **实现：**`IdentitySessionObserver` 现在明确暴露 app 唯一 `AuthenticationWorkflow.revalidateAccess()`；账户管理工作流只在服务端确认当前登录账号自身的 `role`/`status` 变更后调用它。直接成功回执与 unknown 操作通过原 request key 查得完成回执走同一收口。会话重读若确认降为 view、匿名或不可用，既有 session subscription 会立即撤销 account workflow，清空目录/详情/命令快照，且不再发管理员数据刷新；重读失败不把已确认的账号写入谎报为失败。
- **定向验证：**`npm run test:logic:focused -- 'ACCOUNT-SELF-MUTATION|ACCOUNT-STATUS / ROLE-COMMIT|ROLE-PENDING|ACCOUNT-OWNER'` **6/6 passed**，覆盖本人 role→view、本人 active→disabled，直接与 inspect-confirmed 两种回执路径，以及 authority 重读失败；断言失权后快照归零且不触发第二次列表请求。`npm run check:fast` 通过（TypeScript、Prettier、ESLint、OpenAPI 43 paths）；目标文件 `git diff --check` 通过。
- **边界：**测试使用隔离 session observer，不是浏览器页面或 Python API 联调。另新增 SQL session reader 回归：同一 session digest 在 account role 提交变更后，下一次权威读取返回新 role 且保留 session epoch；隔离 SQLite suite **4 passed**。真实数据库、Cookie/CSRF、降权后的页面跳转/提示仍待最终集成验收；F4.26/F4.29/F4.23 均不因本切片勾选，完整 E2E 依约留在所有实现完成后。

### 15.310 B0.3 scheduled publication 的无会话执行身份 schema（2026-10-09，SQLite 持久化切片）

- **设计边界：**复用已有持久化 publish operation/outbox，不伪造 plan 创建者的账号会话。人工 operation 必须同时有 account actor + session hash；无 actor/session 的 scheduled publish 必须关联现存 `origin_plan_id` 与 `activation|restoration` 阶段，并由唯一约束保证每个 plan phase 只有一份 operation。计划创建事件保留管理员 initiator；系统完成/拒绝事件以 null actor、阶段化 action 和 plan target 表示 executor，双方用 plan ID 关联。该模型复用既有持久命令与有限状态，不新增第二套 provider 执行路径或 GoF 模式。详见 [B0.3 活动计划验收记录](acceptance/R-SENTINEL-CONSOLE-B0.3-activation-plan-persistence.md)。
- **实现：**新增 migration `0017_scheduled_rule_publication_origin`，拓展 SQL operation 的可空 actor/session 及 plan/phase 来源列；DB 约束拒绝“无 session 但无 plan 来源”，防止 sessionless write 被误当普通用户命令。publish claim DTO 现保留计划来源；完成/拒绝审计使用系统 action 和 plan target，不写入虚构账号。
- **验证：**`PYTHONPATH=src .venv/bin/pytest -q tests/test_rule_mutation_store.py`，SQLite migration chain 到 `0017` 后 **20 passed**。新增回归实际插入并读回无 actor、无 session、带 plan/phase 的 operation，并确认无 actor/session 且无来源的操作触发数据库约束拒绝。
- **边界：**本切片尚未实现 plan scheduler enqueue、publication 关联/重启重用、计划恢复调度与完整 audit projection；SQLite 不证明 PG/MySQL 并发唯一性。未访问真实数据库或配置中心，未运行完整 E2E。B0.3 保持未完成。

### 15.311 B0.3 定时发布系统审计投影对齐（2026-10-09，跨层契约切片）

- **修复：**发现 outbox 已能写 `rules.activation_plan.activate` / `.restore`，但 SQL audit reader 没有 storage→enum 映射，且领域不变量只允许初始化事件缺少 actor，导致 scheduler 将来写入后审计查询会 fail-closed。现新增 `plan-activate` / `plan-restore` 有限动作映射；仅系统初始化和这两类计划执行动作允许 `actorId=null`，其它用户动作继续要求账号 actor。Dashboard 严格 wire/model、三语正式动作名称及系统执行者 fallback 对齐；OpenAPI 由既有生成器更新。
- **验证：**Console `test_system_audit_api.py`、`test_system_audit_persistence.py`、`test_rule_mutation_store.py` **32 passed**；额外覆盖无 actor scheduled action 读回、过滤和 API enum 参数。前端 `SYSTEM-AUDIT` logic **5/5**、HTTP **3/3**；`npm run check:fast`、`npm run i18n:check`（三语各 1,182 键）及 OpenAPI `contract:check`（43 paths）通过。
- **边界：**本切片解决的是审计读写契约一致性，不证明 scheduler 已创建这些事实；执行用例、计划与 publication 原子/幂等关联、lease 接管、多进程/PG/MySQL、真实 provider 及完整 E2E 仍未验收。B0.3 继续未勾，最终 E2E 留到所有实现收口。

### 15.312 B0.3 活动计划调度到 durable publish outbox（2026-10-09，SQLite 编排切片）

- **实现：**新增 `RunRuleActivationPlanWorker` 应用编排与 SQL enqueuer：对到期 activation/restoration claim 以稳定 plan-phase request key + publication UUID 创建或恢复既有 publish operation/outbox；批次内执行前先续租，事务内再次校验 claim 的 plan revision/state/token/lease，并原子写 operation、精确 frozen target payload 与 system audit。operation actor/session 始终为空且受 migration 0017 origin 约束。activation 显式选择 promo version、以 restore version 作 CAS baseline；restoration 切回明确 restore version、以 activation version 作 baseline。没有新增 provider 执行路径，继续由既有 publish worker 消费。
- **阶段收敛：**新增 ASGI worker lifecycle 与 `build_app` / identity / first-run composition 显式注入。仅当既有 publication operation 完成且三段 publication（validation、provider write、read-back）均持久化成功后，scheduler 才关联并推进 plan；pending 留在 `activating/restoring`，已知拒绝转 `blocked`。scheduler 和 publication worker 可由宿主显式装配/分别托管，不隐式创建凭证、网络策略或外部服务。
- **验证：**`test_run_rule_activation_plan_worker.py` + `test_rule_activation_plan_worker_lifecycle.py` + `test_rule_publication_worker_lifecycle.py` + `test_first_run_composition.py` + `test_rule_mutation_store.py` + `test_rule_activation_plans_api.py` 定向套件 **43 passed**；`compileall` 与 `git diff --check` 通过。SQLite orchestration 覆盖 activation→read-back→restoration→read-back 完整计划状态路径、sessionless system audit、显式 CAS baseline、pending 不提前 active、缺少精确发布目标时拒绝并 block、过期 claim 重领复用单一 operation/publication/audit，以及应用启动/关闭取消 scheduler task。
- **边界：**provider成功阶段在 SQL 测试中模拟，不代表真实 Consul/Nacos 写入；SQLite 不证明 PostgreSQL/MySQL 的 row lock、跨进程并发/崩溃恢复。PLAN-EXEC-01..10 中多 worker、真实 CAS baseline 冲突、external edit 与 restoration 竞争、runtime instance receipt/收敛仍开放。未运行浏览器或最终 E2E，未访问真实数据库/配置中心；B0.3 不勾。

### 15.313 F4.20 初始化页面和字段错误五态三语 SSR（2026-10-09，定向组件渲染）

- **实现：**新增真实 `InitializationPage` 容器 SSR 测试，组合其 workflow snapshot、`SetupWizard` 与 `InitializationFeedback`。在三种 locale 下覆盖连接检查 pending、初始化结果未知、初始化失败、bootstrap 已关闭，并单独渲染实际向导的多字段校验失败；pending 只禁用对应检查按钮，unknown 锁定 setup 并给出核查动作，已初始化不渲染向导，字段错误和 alert 摘要可见，raw error/request key/secret sentinel 不进 HTML。
- **验证：**`node --test tests/i18n/catalog.test.mjs tests/i18n/dynamic-callsite-coverage.test.mjs` **16/16 passed**；Prettier check 通过。
- **边界：**这是真实组件树的 SSR 静态 HTML，不执行挂载 Effect、用户点击、焦点/键盘、CSS/响应式或路由行为；workflow snapshot 为受控替身，不是 Python 联调。F4.20/F4.21 仍未勾，完整 E2E 留到所有剩余实现完成后。

### 15.314 F4.21 bootstrap 授权 gate 三态三语 SSR（2026-10-09，定向组件渲染）

- **实现：**新增实际 `BootstrapAuthorizationGate` SSR 覆盖，分别投影服务器确认的未授权开放窗口、已授权开放窗口与关闭窗口。protected child sentinel 证明只有授权快照能渲染 setup 子树；未授权快照显示密码型授权字段，关闭状态提供关闭反馈而不开放表单。
- **验证：**`node --test tests/i18n/catalog.test.mjs tests/i18n/dynamic-callsite-coverage.test.mjs` **17/17 passed**；Prettier check 通过，`git diff --check` 通过。
- **边界：**受控快照的 SSR 不执行授权表单交互、React hydration、路由转换或 Python API；不证明服务端对每个初始化 endpoint 的原子授权。未运行浏览器/完整 E2E、未连接数据库或配置中心，F4.21 保持未完成。

### 15.315 F4.20 Python 首启数据库/配置源检查路由合同（2026-10-09，聚焦 API 测试）

- **验证：**Sentinel Console 的 `test_bootstrap_database_check_api.py` 与 `test_bootstrap_source_check_api.py` **14 passed**；覆盖受控 checker 的首启 API 请求、输入与授权拒绝、安全响应及有限失败原因。结果形状和前端连接状态联合一致。
- **边界：**测试使用 checker 替身，不连接真实 PostgreSQL/MySQL/Nacos/Consul；不覆盖实际 connector/TLS/凭证解析、真实 initialization persistence 或 React→Python 运行时联调。HTTPX cookie 接口产生 deprecation warnings。F4.20 和 B0.1/B0.2 仍不勾，完整 E2E 留到实现收口。

### 15.316 B0.1 配置源目标显式零端口拒绝（2026-10-09，安全边界修复）

- **问题与修复：**`RegisteredSourceTargetPolicy` 原先用 `parsed.port or default_port` 解析端口，会把显式 `:0` 当成“未填写端口”并回退到 HTTP/HTTPS 默认端口。现在只有端口真正缺省时才选择协议默认值；显式 `0` 保持为非法端口并无法命中 deployment allowlist，避免策略层对非法目标给出错误的通过判定。
- **验证：**新增 `http://nacos.internal:0` 回归；`PYTHONPATH=components/sentinel/sentinel-console/src components/sentinel/sentinel-console/.venv/bin/pytest -q components/sentinel/sentinel-console/tests/test_registered_source_checker.py` **10 passed**；目标模块/测试 `compileall` 与 `git diff --check` 通过。
- **边界：**这是地址策略单元回归，不证明实际网络传输、Nacos/Consul 版本与 ACL 兼容；本轮未访问真实 DB/配置中心，未运行浏览器或完整 E2E。B0.1 仍未勾，完整 E2E 留到所有实现完成后。

### 15.317 B0.2 首启数据库检查 API 到只读 connector 的隔离 SQLite 集成（2026-10-09）

- **覆盖：**在 ASGI in-process client 中走真实受保护 `/api/v1/system/bootstrap/database-check` 路由，并注入真实 `BootstrapDatabaseConnector`；SQLite 文件由测试临时目录预置，HTTP 请求只能指定 `kind=sqlite`，数据库路径只来自 checker 的部署配置。成功探测后比对原始文件字节不变；缺失目标返回稳定 `unreachable/connection` 且不创建文件。first-run composition contract 同时断言 `build_first_run_sql_identity_app` 装配真实 connector。
- **验证：**Sentinel Console API+connector+composition 定向 suite **20 passed, 1 skipped**；包含既有路由安全、SQLite 只读/不创建文件与 PostgreSQL/MySQL fake-driver/TLS 参数用例。本集成未开 TCP socket，不访问外部数据库；1 项 MySQL optional-extra 检查因驱动未安装跳过。
- **边界：**证明 ASGI HTTP adapter→真实 connector→临时 SQLite 的局部集成，不替代 PostgreSQL/MySQL 驱动、TLS、部署 allowlist、首启跨资源迁移/恢复、多 worker 或真实浏览器验收。B0.2 继续不勾，完整 E2E 留在全部实现收口后。

### 15.318 F4.31 本人改密实际 React 页面三语 SSR 字段合同（2026-10-09）

- **覆盖：**通过 Vite SSR 加载正式 `OwnPasswordPage` 和 Astryx `TextInput` 渲染路径，在简中/英文/日文下确认实际页面只有当前密码、新密码、确认密码三个输入；三者都以 `type=password` 呈现，autocomplete 依次为 `current-password` / `new-password` / `new-password`。页面说明使用注入的 session username，不展示 account ID 或任意账号目标入口。
- **验证：**`npm run test:logic:focused -- 'PASSWORD-(VALIDATE|OWNER|OUTCOME)'` **6 passed**；`node --test --test-name-pattern='F4.31-PASSWORD-PAGE-RENDER' tests/i18n/catalog.test.mjs` **1 passed**；`npm run check:fast` 通过。
- **边界：**SSR 不执行浏览器 hydration、输入/键盘交互、CSS/autocomplete 实际浏览器行为、成功/失败后的清理与导航，也不是 Python HTTP 联调；未运行 Chrome/Edge/CDP 或完整 E2E。F4.31–F4.33 继续未勾，最终页面与真实服务验收保持在收尾阶段。

### 15.319 F4.20 首启数据库/规则源失败反馈和恢复入口 SSR（2026-10-09）

- **覆盖：**扩展实际 `InitializationPage` 三语 SSR 状态矩阵：数据库认证失败与规则源不支持分别投影为专用本地化反馈，不展示服务端原始细节；数据库失败时当前 storage 步骤的显式重试按钮保持可用。规则源当前步骤下的重试按钮及 pending 行为仍由 `F4.20-SETUP-CHECK-RENDER` 单独覆盖，避免将不在当前步骤的按钮错误当作页面必现内容。
- **验证：**页面聚焦 SSR `node --test --test-name-pattern='F4.20-SETUP-PAGE-RENDER|F4.20-SETUP-CHECK-RENDER' tests/i18n/catalog.test.mjs` **2 passed**；setup workflow `npm run test:logic:focused -- 'SETUP-'` **20 passed**；完整 catalog `node --test tests/i18n/catalog.test.mjs` **17 passed**；`npm run check:fast` 与 `git diff --check` 通过。
- **边界：**受控快照 SSR 不执行浏览器点击、连接请求、字段更改/旧检查取消、成功恢复交互、CSS 或 Python 联调；未运行完整 E2E。F4.20 仍保持未勾。

### 15.320 F4.22 登录实际 React 页面三语状态安全呈现 SSR（2026-10-09）

- **覆盖：**从 Vite SSR 模块图加载正式 `LoginEntryPage` + `AuthenticationProvider`，简中/英文/日文渲染三类 workflow 快照：已知凭据拒绝（保持匿名、可继续编辑并允许用户明确重试）、登录结果未知（锁定表单并显示显式检查 session 入口）、session authority 不可用（隐藏新登录表单并给出安全恢复入口）。页面不渲染 raw error 或账号存在性细节。
- **验证：**`node --test --test-name-pattern='F4.22-LOGIN-PAGE-RENDER' tests/i18n/catalog.test.mjs` **1 passed**；`npm run test:logic:focused -- 'F4[.]22'` **5 passed**；`node --test tests/i18n/catalog.test.mjs` **18 passed**；`npm run check:fast` 通过。
- **边界：**SSR 不执行浏览器输入保留/键盘、429 冷却计时器、焦点、导航或 Python API；logic 和渲染均为本地受控用例，不证明实际网络行为。F4.22 保持未勾选，完整浏览器与真实后端验收留至最终阶段。

### 15.321 F4.20 已确认 setup gate 的重读期间保留（2026-10-09）

- **缺口与修复：**`App` 曾在 render 阶段调用 `setState` 记住 setup gate 是否授权；移入 Effect 又会触发同步级联渲染，不符合当前 React lint 契约。现在认证 workflow 是最近一次确认 facts 的唯一 owner：读取中快照只附带“setup open 且 operator 已授权”的 bootstrap facts，绝不附带旧 authenticated identity；最新重读失败会清除保留事实。路由只在该明确 setup gate 重读时短暂保留向导。初次未知、登录态、未授权 gate、失败态均不能借此访问 setup。
- **验证：**`npm run test:logic:focused -- 'F4[.]20'` **4/4 passed**，覆盖 authorized/open 条件、pending 时序、成功关闭、失败后清除及 authenticated identity 不泄漏；相关 authentication/expiry/logout 子集 **14/14 passed**；`npm run check:fast` exit **0**（TypeScript、Prettier、ESLint、43-path OpenAPI contract）。
- **边界：**这是 workflow/route policy 单测与静态门禁，不是 mounted React/IAB、Python bootstrap 联调或部署验收；未运行浏览器和完整 E2E，也未连接数据库/配置中心。F4.20/F4.21 仍未勾，最终 E2E 留在全部实现完成后。

### 15.322 F4.24 登录表单语义三语 SSR 补强（2026-10-09）

- **覆盖：**扩展正式 `LoginEntryPage` SSR 测试：三种 locale 的已知凭据拒绝页面仍有 username + password 两个可修正输入；账号字段为 `autocomplete=username`，密码遮蔽且为 `autocomplete=current-password`；有显式 submit 按钮，密码显隐控件初始 `aria-pressed=false` 并提供显示密码文案。未知结果表单仍锁定，session authority 不可用时不展示登录表单。
- **验证：**聚焦 `node --test --test-name-pattern='F4.22-LOGIN-PAGE-RENDER' tests/i18n/catalog.test.mjs` **1/1 passed**；完整 catalog SSR/i18n suite **18/18 passed**；`npm run check:fast` exit **0**；`npx prettier --check tests/i18n/catalog.test.mjs` 与 `git diff --check` 通过。
- **边界：**SSR 只证明正式组件输出的字段语义与可修正 UI，不执行表单事件、Enter 键、密码显隐点击或输入保留；这些实际交互和 Python Console 链路留在最终内置浏览器/E2E 验收。F4.24 保持未勾选。

### 15.323 B0.1 配置源检查实际 HTTP transport loopback 合同（2026-10-09）

- **覆盖：**在隔离本机临时 HTTP server 上运行真实 `PinnedAioHttpJsonClient`，不替换其 aiohttp transport。Nacos 用 allowlisted literal `127.0.0.1` target 返回 config-list JSON，断言 `/nacos` context path、GET method 与 namespace/page query；Consul 返回 302 到未授权目标，断言检查被归类为 connection failure 且 transport 不跟随 redirect。
- **验证：**`components/sentinel/sentinel-console/.venv/bin/python -m unittest tests.test_registered_source_checker -v` **12/12 passed**。该命令仅绑定 ephemeral `127.0.0.1`，未连接外部地址；定向用例在沙箱默认策略下因禁止 bind 被拒，使用该单条测试命令的限定授权后通过。
- **边界：**这是 transport 与 provider 请求构造的 loopback 集成，不是 Nacos 3/Consul 服务兼容性验收；没有真实 TLS、认证/ACL、数据库或注册配置，也未执行浏览器/E2E。B0.1 仍未完成，完整 E2E 继续留在所有实现任务之后。

### 15.324 B0.3 活动计划 publication link 丢失后的 SQL 恢复（2026-10-09）

- **需求/责任边界：**针对 PLAN-EXEC-02 的精确崩溃窗口：活动计划 worker 已将 scheduled publish command/outbox/audit 持久化，但还未将 publication ID 关联回 plan；不新增执行路径，复用 SQL outbox 和稳定 plan-phase identity。
- **实现与验证：**新增 SQLite 集成回归：创建到期计划并领取 lease，直接执行 scheduled enqueue 后故意跳过 association；通过现有 outbox 将 validation/write/read-back 三阶段写成成功并完成 operation。随后在 lease 过期后新建 queue、store 和 scheduler，确认恢复原 publication 并把 plan 推进为 active。断言 scheduled operation、publication、accepted audit、completed audit 各唯一一条。`pytest -q tests/test_rule_mutation_store.py tests/test_run_rule_activation_plan_worker.py` **30 passed**；`python -m compileall -q src/atlas_richie/sentinel_console` 通过，修改文件定向尾随空白扫描无匹配。
- **边界：**这是跨新编排实例的 SQLite 持久恢复模拟，不是强制终止/重启 OS 进程，也不调用真实 Nacos/Consul provider；SQL 成功阶段为受控测试事实，不能证明服务端写入或 runtime instance receipt。SQLite 不证明 PostgreSQL/MySQL 的锁竞争与多 worker 唯一性；PLAN-EXEC-02 仍 partial，B0.3 不勾，最终 E2E 留在所有实现项之后。

### 15.325 B0.2 首启 ASGI 初始化到持久化 SQLite 的端到端服务切片（2026-10-09）

- **实现与覆盖：**新增真实 `build_first_run_sql_identity_app` HTTP 集成测试，串接部署 setup-window file、一次性 operator-code grant、CSRF、初始化 API、跨存储 coordinator、migration chain、target SQLite 初始化事务、runtime locator 加密文件、operation receipt 与初始化后 bootstrap gate。提交合成 PostgreSQL candidate，但在 engine factory/read-back seam 使用真实临时 SQLite 文件，避免任何远程数据库 socket；HTTP 路由、协调器、migrations 和 SQLite 事务均为正式实现。
- **关键断言：**初始化前 bootstrap 回 `initialized=false`；授权后提交会回 `completed`，完成后 bootstrap 回 `initialized=true` 且 grant 不能再次兑换；相同已关闭 setup 下重发初始化得到 403。operation receipt 可用原 grant 读回。SQLite 只有一个 initialized guard、内置 admin、operation receipt 与 Consul source；admin password 为 Argon2 hash，ACL token 存储为密文；operator code/database/admin/source secrets 不进入相关响应或部署状态文件。
- **验证：**`pytest -q tests/test_first_run_http_persistence_integration.py tests/test_first_run_composition.py tests/test_bootstrap_initialization_coordinator.py tests/test_bootstrap_initialization_transaction.py tests/test_bootstrap_authorize_api.py tests/test_bootstrap_initialization_api.py tests/test_bootstrap_persistence_integration.py tests/test_bootstrap_api.py` **42 passed**；`python -m compileall -q src/atlas_richie/sentinel_console tests/test_first_run_http_persistence_integration.py` 通过。既有 HTTPX 依赖测试产生 10 条 per-request cookies 弃用警告，本次新集成用 client-cookie 生命周期，无新增警告。
- **边界：**这是后端 ASGI→正式 coordinator→临时 SQLite 的 service integration，不是 React 浏览器→Python、PostgreSQL/MySQL driver/TLS/migration/locking、真实 Nacos/Consul 或部署/多 worker 验收；B0.2 不勾，最终跨服务 E2E 继续留在所有实现完成后。

### 15.326 B0.2 Alembic head 幂等测试随迁移图演进（2026-10-09）

- **缺口与修复：**`test_migration_is_idempotent_at_head` 把当前 revision 硬编码为 `0006_registered_sources`，但迁移已推进到 `0017_scheduled_rule_publication_origin`，导致基础设施测试组长期遗留红灯。测试现在从实际 Alembic `ScriptDirectory` 读取唯一迁移 head，并分别断言首次版本与 head 一致、重复执行后版本不变。同步修正 README 将已存在的 `serve`/`setup-window` CLI 和环境组合误写为尚未实现的问题，同时保留未完成的真实部署/PG-MySQL验收边界。
- **验证：**先观察到旧断言失败（1 failed、4 passed，实际 head 为 `0017_scheduled_rule_publication_origin`）；修复后 `.venv/bin/pytest -q tests/test_persistence_foundation.py` **5 passed**，`.venv/bin/python -m compileall -q src/atlas_richie/sentinel_console/infrastructure/persistence/migrations tests/test_persistence_foundation.py` 通过。
- **边界：**该修复确保 SQLite 基础设施测试跟随迁移目录，不证明 PostgreSQL/MySQL 的真实迁移、并发或部署 acceptance；B0.2 继续未勾，完整 E2E 仍留在全部实现完成后。

### 15.327 F4.20 初始化 workflow 强制 bootstrap 刷新参数透传（2026-10-09）

- **根因：**`InitializationWorkflow.restore(forceRefresh?)` 的公开契约允许强制刷新，但实现忽略参数并始终调用内部默认 `false`；初始化回执后的权威 bootstrap 确认因此不能要求绕过缓存。
- **回归与修复：**新增 Port 观察测试，先观察到 `restore()`/`restore(true)` 实际收到 `[false, false]`；实现改为显式接收并传递 `forceRefresh`。修复后断言为 `[false, true]`。修改范围仅限 identity initialization application workflow 与 logic test。
- **验证：**`npm run test:logic:focused -- 'SETUP-BOOTSTRAP restore forwards an explicit force refresh'` **1/1 passed**；`npm run test:logic:focused -- 'SETUP-'` **21/21 passed**；`npm run check:fast` exit **0**（typecheck、Prettier、ESLint、43-path Console OpenAPI contract）。
- **边界：**验证证明 workflow→Port 参数传递，不证明浏览器挂载路径、HTTP 缓存策略、Python bootstrap 或真实服务行为。F4.20/F4.21 仍不勾；未启动浏览器，也未运行完整 E2E。

### 15.328 F5.2 规则草稿切换三语时保留规则与协议上下文（2026-10-09，验收用例已补）

- **新增：**在 `tests/e2e/rule-set-http.e2e.test.mjs` 增加正式页面用例：从显式 flow 规则绑定进入编辑、修改阈值形成未保存草稿，再依次切换英文、日文和简体中文；每次均断言未保存状态与规则预览值保留，且 hash 中的 binding/view 等协议上下文完全不变。测试已纳入现有 `test:e2e` 文件列表，不另建浏览器框架。
- **验证：**`npm run test:logic:focused -- 'I18N-'` **4/4 passed**；`node --check tests/e2e/rule-set-http.e2e.test.mjs` 通过，改动文件无行尾空白。
- **边界：**遵循“全部实现完成后再跑完整 E2E”，本轮没有启动任何浏览器或执行该用例；因此仅证明测试语法有效，尚未证明运行时交互通过。F5.2 继续未勾，最终使用 Codex 内置浏览器验收，禁止 Chrome/Edge/CDP。

### 15.329 B0.3 Nacos SDK 缓存与 create/update CAS 语义复核（2026-10-09）

- **新核对：**按官方 `nacos-sdk-python==3.2.0` 源码复核 `get_config()` 的调用顺序：先查 failover cache，再发 gRPC 查询；`disable_use_config_cache` 仅禁止查询报错后的普通本地缓存回退，不能证明 failover 命中不是旧值。公开结果仍只有 content；SDK 将服务端 NOT_FOUND 映射为 `""`，不返回 query MD5 / existence fact。Nacos Server 3.2.3 只有在 `casMd5` 非空时进入 CAS persistence；空值走 non-CAS 的 `updateForExist`/create 分支，所以空字符串 MD5/`cas_md5=""` 不能被当成 create-only CAS。详细证据已追加到 [B0.3 provider conditional-write capability gate](acceptance/R-SENTINEL-CONSOLE-B0.3-provider-conditional-write.md)，并链接到 SDK/Server 对应固定版本源码。
- **下一步约束：**继续维持 Nacos publication fail-closed；不能仅靠 SDK cache flags、对 `get_config()` 内容本地求 MD5 或空 CAS 字段宣称满足 CAS。适配实现仍须提供权威远端存在性/MD5、data+auth 双通道 DNS pin/TLS identity、明确 create/update conditional semantics、有限冲突/unknown 结果以及精确读回。Consul 已有实现不受此限制。
- **验证与范围：**官方源码静态核对；未修改 provider runtime、未联系 Nacos/Consul/数据库、未运行完整 E2E。B0.3 保持未勾。

### 15.330 F4.20 MySQL 首启连通性检查清理异常归一化（2026-10-09）

- **根因：**`BootstrapDatabaseConnector._check_mysql()` 在连接/只读查询错误已分类后，于 `finally` 中直接 `await connection.ensure_closed()`；若 asyncmy 在关闭期间抛出驱动异常，会越过现有分类并将底层异常泄漏为未归一化服务错误。新增回归先观察到该异常确实逸出。
- **修复：**只捕获 asyncmy 驱动错误、`OSError` 和 `TimeoutError` 这三类已知清理失败。探测/查询成功但连接清理失败时，返回安全的 `unreachable/connection`；原本的认证拒绝分类不被清理异常覆盖；取消及程序错误仍继续传播。
- **验证：**`.venv/bin/pytest -q tests/test_bootstrap_database_connector.py -k close_driver_error_is_normalized` 修复前 **1 failed**（私有 cleanup detail 逸出）；修复后 `.venv/bin/pytest -q tests/test_bootstrap_database_connector.py tests/test_bootstrap_database_check_api.py` **19 passed, 1 skipped**。17 条 HTTPX cookie deprecation warnings 来自现有测试 client API，与此改动无关。
- **边界：**受控 asyncmy driver 替身和 SQLite/ASGI API 测试，不连接真实 MySQL/PostgreSQL，也不证明 React mounted 初始化流程或数据库真实凭证行为；F4.20/B0.2 继续未勾，完整 E2E 仍留最终阶段。

### 15.331 F4.20 服务端关闭首启窗口后阻断陈旧页面继续操作（2026-10-09）

- **根因与回归：**初始化服务端可返回稳定 `setup-closed` 拒绝，但 workflow 原样暴露为可再次提交的普通 `rejected` 状态；如果浏览器 bootstrap 快照仍显示开放，React 页面会继续展示向导。新增 logic 用例先复现该状态错配，并新增三语 `InitializationPage` SSR 用例覆盖“服务端 closed 回执 + stale-open bootstrap”。
- **修复：**将 `setup-closed` 回执规范化为不可写 `closed` 终态；初始化与 DB/source 检查均拒绝继续，向导隐藏；页面进入关闭终态后调用 `clearSensitive()`，反馈提供只读 bootstrap 重读按钮用于校正陈旧快照。其它 `validation` / `dependency` 拒绝仍保留可修复语义；普通 pending/unknown 写状态策略不变。
- **验证：**修复前逻辑测试 **1 failed**（实际状态仍为 `rejected`），SSR 测试 **1 failed**（stale-open 情况仍渲染 setup wizard）；修复后 SETUP logic **22/22 passed**、`tests/i18n/catalog.test.mjs` **18/18 passed**、`npm run check:fast` 与 `npm run i18n:check` 通过、`git diff --check` 通过。
- **边界：**SSR 不运行 React effects，因此不能据此声称 mounted 页面已实测密码 DOM 清空；未启动浏览器，也未运行完整 E2E。Python Console 真实闭窗授权/持久化仍未验收，F4.20 与 B0.1 继续未勾。

### 15.332 F4.21 服务端闭窗事实同步到 app 级路由守卫（2026-10-09）

- **缺口：**`InitializationWorkflow` 与应用级 `AuthenticationWorkflow` 共享同一 bootstrap authority，但 setup 组件收到另一个操作者已关闭窗口的 `setup-closed` 回执后，只更新局部快照并展示关闭提示；若不再刷新共享 owner，App 路由守卫可能暂时保留旧的 setup 访问事实。
- **修复：**闭窗状态的 React effect 清理敏感表单后，额外调用 `workflow.restore(true)`；经 `createSetupIdentityPorts` 该调用重读 app 唯一 AuthenticationWorkflow 的 bootstrap/session authority。权威结果由现有 App guard 处理：已初始化则转 login，不可用则进入 fail-closed recovery；未增加第二个 bootstrap owner，也不直接伪造导航。
- **验证：**F4.20 setup-route revalidation logic **4/4 passed**；实际 `InitializationPage` 三语 SSR **1/1 passed**；`npm run check:fast` 与 `git diff --check` 通过。逻辑层另验证 closed 状态仍允许显式只读刷新、禁止初始化及连接测试（§15.331）。
- **边界：**SSR 不执行该 React effect，未验证跨 owner 响应式路由跳转；完整 mounted 初始化/E2E 仍留最终阶段。F4.21/B0.2 继续未勾，不连接真实数据库或配置中心。

### 15.333 F4.22 登录限速最终浏览器用例按 wire 契约验证冷却计时（2026-10-09）

- **缺口：**原 `LoginEntryProbe` 的 rate mode 只返回 HTTP 429，缺少 `code=rate_limited` 与有界 `retryAfterMs`。该模拟响应只覆盖通用 rate-limit 文案，未激活产品真实 `useLoginCooldown` 定时器，因此旧 E2E 不能证明按钮锁定、编辑凭据保留 cooldown 或倒计时到期恢复。
- **修正：**探针现在返回 `retryAfterMs=2500` 的真实协议错误形状；`login-entry.e2e.test.mjs` 增加按钮冷却中 disabled、修改密码仍 disabled、倒计时后重新 enabled 的页面断言。
- **验证：**F4.22 logic **5/5 passed**、`node --check tests/e2e/login-entry.e2e.test.mjs`、`npm run check:fast` 和 `git diff --check` 通过。
- **边界：**本轮按用户要求未运行浏览器或全量 E2E；E2E 文件语法检查不证明倒计时 DOM 行为，等待最终产品验收节点执行。F4.22 仍未勾，Python→React live 登录链路也未验收。

### 15.334 F4.23 安全回跳与登出逻辑定向验证（2026-10-09）

- **验证：**`node scripts/test/run-focused.mjs logic 'authentication return route'` **1/1 passed**；`node scripts/test/run-focused.mjs logic 'logout'` **4/4 passed**（含传输失败保持 unknown、禁止重复登出、Mock storage 静默失败仍保持同页匿名）；dashboard `npm run check:fast`、`npm run i18n:check`、`node --check tests/e2e/app-authentication.e2e.test.mjs` 与 `git diff --check` 通过。
- **最终 IAB 路径：**待最终 E2E 节点手工验证已确认 principal 的菜单身份、显式登出后的站内 `returnTo`、重新登录后由新确认身份授权/消费回跳，以及 viewer 不可进入管理页。未新增或运行 CDP 测试；没有启动 Chrome/Edge。
- **边界：**逻辑测试证明 allow-list 与角色重新授权，以及 workflow 的登出状态合同，不证明 React mounted 菜单/跳转、浏览器 storage 生命周期或 Python `/auth/me`、过期/撤销、Cookie/CSRF。F4.23 仍未勾；Mock 与后端真实服务集成留待最终验收。

### 15.335 B0.2 身份 Cookie 协议常量单一归属（2026-10-09）

- **缺口与修复：**login/logout/session/account/bootstrap 等 HTTP adapter 各自重复声明 `sentinel_session` 与 `__Host-sentinel_csrf`，有协议字段漂移风险。现在由已有 `api.browser_security` 持有两项协议常量，相关 adapter 统一导入；未新增 service/抽象，也未改变 Cookie 属性、授权或 CSRF 校验流程。
- **附带测试修正：**bootstrap 非法 request-id 测试原本断言响应文本不含子串 `bad`，随机生成 UUID 偶然含该子串时会产生假失败。现在精确断言服务端 request ID 与响应头一致、不反射非法请求值且可解析为 UUID。
- **验证：**身份、初始化、账户与 system-observation Python API 定向回归合计 **74 passed**（首批 57、共享 system read 路由 17）；`compileall` 通过；源码扫描确认生产 API 中两个 Cookie 字面值各只定义于 `browser_security.py`；`git diff --check` 通过。该包未配置/安装 Ruff，本轮未声称 Ruff 检查通过。
- **边界：**测试使用 ASGI 与隔离测试数据库；不证明 PostgreSQL/MySQL 部署，也不是 React→Python 浏览器 E2E。B0.2 仍未完成。

### 15.336 F4.20 外部初始化闭窗时清理仍挂载的敏感草稿（2026-10-09）

- **发现与修复：**向导挂载期间，另一初始化者可能使权威 bootstrap 变为 `initialized=true`，或关闭一次性 setup 窗口（`setupAvailable=false`）。页面此前会隐藏向导，但 `knownClosed` 只看本页面初始化命令回执，因而没有调用 `clearSensitive()`。现在通过 `isSetupAuthorityClosed()` 将权威 bootstrap 关闭事实纳入同一终态，触发敏感草稿清理、取消离开确认保护并隐藏向导；本页面自身正在提交/确认的事务不被误判为外部闭窗，`ready` 成功态仍走原完成回调。反馈仍由 bootstrap projection 区分“已初始化”与“当前不可用”。
- **验证：**`npm run test:logic:focused -- 'SETUP-LIFECYCLE'` **1/1 passed**，覆盖 idle 闭窗、成功态不误判、提交/检查中不抢占和 `setup-closed` 回执；`npm run test:logic:focused -- 'SETUP-SECRET'` **2/2 passed**；`node --test tests/i18n/catalog.test.mjs` **18/18 passed**（覆盖已初始化 bootstrap 不渲染向导及成功回执不再渲染敏感表单）；`npm run check:fast` exit **0**（TypeScript、Prettier、ESLint、43-path OpenAPI contract）；`git diff --check` 通过。
- **边界：**聚焦逻辑与 SSR 不执行 mounted React effect，尚未在浏览器中观察闭窗后内存草稿清理；该运行时验证留给最终 E2E/IAB 节点。没有启动 Chrome/Edge/CDP，也没有连接真实 Python、数据库或配置中心。F4.20 继续未勾。

### 15.337 B0.1 Consul 认证拒绝状态映射（2026-10-09）

- **回归：**新增 Consul ACL 检查受控用例，分别返回 HTTP 401/403，要求稳定映射到 `authentication`，不泄漏 ACL token。
- **修复：**`ConsulRegisteredSourceChecker` 将 401 与 403 统一识别为认证/授权失败；其余非成功、非空键空间 404 仍按连接/读取语义处理。
- **验证：**修复前新回归 **1 failed**，准确暴露 HTTP 401 被误报为 `connection`；修复后 provider adapter 聚焦 **6 passed**，整份源检查 suite 排除 loopback 子类 **11 passed**，Python `compileall` 与 `git diff --check` 通过。
- **边界：**尝试运行整份 suite 时，两个既有本机 loopback integration test 因沙箱禁止绑定 `127.0.0.1` 失败（`PermissionError: Operation not permitted`）；未请求权限提升。Nacos/Consul 真实实例、TLS/ACL 版本兼容仍未验证，B0.1 继续未勾。见 [B0.1 配置源检查验收记录](acceptance/R-SENTINEL-CONSOLE-B0.1-registered-source-check.md)。

### 15.338 B0.1 Nacos 认证端点故障状态映射（2026-10-09）

- **回归：**新增 Nacos 登录端点 HTTP 429/500/502/503 用例，要求不能误报成凭证错误；修复前用例失败，观测到响应均错误落入 `authentication`。
- **修复：**Nacos 登录端点仅将 401/403 映射为 `authentication`；其它非 200 响应映射为 `connection`；200 但 access token 缺失/为空仍映射为 `authentication`。不保留原始响应内容或用户凭证。
- **验证：**Nacos/Consul 认证与服务端故障聚焦 **4 passed**；源检查 suite 排除被沙箱阻断的 loopback integration 类后 **12 passed, 2 deselected**；Python `compileall` 与 `git diff --check` 通过。
- **边界：**两个真实 aiohttp loopback transport 测试仍无法在当前沙箱绑定 `127.0.0.1`，因此没有声称完整 suite 通过；未请求权限提升。真实 Nacos/Consul 及 TLS/ACL 兼容、B0.1 全部合同和 E2E 仍未验收。

### 15.339 F4.31–F4.33 / B0.2 当前密码错误响应合同闭环（2026-10-09）

- **发现：**前端 `OwnPasswordPage` 按 HTTP 400 预留“当前密码错误”提示，但后端把错误当前密码和失效 session 都映射为 401 `unauthenticated`；会话错误无法指导已登录用户修正密码。
- **实现：**`ChangeOwnPassword` 将“账户/session 已无效”与“当前密码校验错误”拆为不同用例异常；后者映射 HTTP 400 `current_password_invalid`，前者保留 HTTP 401 `unauthenticated`。前端 error catalog、own-password endpoint contract 和文案投影现按稳定错误码一致处理；正式 Dashboard 功能设计、验收记录与 43-path OpenAPI 已同步。
- **验证：**修复前 API 回归 **1 failed**（错误密码得到 401）；修复后 Python `tests/test_own_password.py` **6 passed**，覆盖错误密码不变更哈希/会话/audit 及未知 session 仍 401；前端 `OWN-PASSWORD-ERROR` **1/1 passed**，证明错误后保留当前 session 并允许显式修正后再提交；`node --test tests/i18n/catalog.test.mjs` **18/18 passed**，三语页面 SSR 显示正确的当前密码错误提示；`npm run contract:generate` 更新 43-path OpenAPI，`npm run check:fast` 通过。
- **边界：**SSR 与 MSW 合同不等于 mounted 页面或真实浏览器→Python E2E；改密专用限速、PG/MySQL、生产 app 装配和浏览器路径仍开放。F4.31–F4.33、B0.2 均不因此勾选。

### 15.340 F4.31–F4.33 / B0.2 本人改密失败限速（2026-10-09）

- **职责边界：**`ChangeOwnPassword` 编排当前密码尝试计数与封锁结果；限流通过用例拥有的最小 Port 调用既有 SQL attempt-limit adapter。复用现有部署阈值/窗口/封锁策略，按 account ID + 用途前缀派生 HMAC digest，改密失败桶独立于登录 IP 桶，数据库中不保存明文账号。没有 GoF 模式适用：单个同步流程的一项策略依赖，不需要再套代理/装饰器/责任链。
- **实现：**错误当前密码原子增加该账号失败计数；封锁期间服务在执行 Argon2 verify/hash 前返回 `OwnPasswordRateLimited`，API 映射 `429 rate_limited` 并回传有界 `retryAfterMs`。attempt authority 故障 fail-closed 映射 503；正确当前密码校验后先清理该账号失败桶，再执行原有哈希更换、撤销会话和审计事务。身份 SQL composition 显式装配 limiter 与部署 HMAC key；前端 API 错误协议此前已包含 rate_limited，无新前端分支。
- **验证：**先新增并运行限速测试，修复前因 `ChangeOwnPassword` 尚无限速依赖而失败；完成后 `PYTHONPATH=src .venv/bin/pytest -q tests/test_own_password.py tests/test_identity_composition.py tests/test_login_attempt_limiter.py tests/test_console_openapi_route_parity.py` **22 passed**。另 `npm run contract:check` 验证 OpenAPI 43 paths，Python `compileall` 与 `git diff --check` 通过。覆盖两次错误后限流、限流请求不再执行密码 verifier、admin/view 账号桶隔离、限流 authority 故障 fail-closed 及既有限流器回归。SQLite 测试不证明 PostgreSQL/MySQL 并发锁与真实多 worker 行为。
- **边界：**限速策略沿用登录环境变量配置，尚无独立改密阈值；未执行 PostgreSQL/MySQL、多 worker 部署、真实 React→Python 浏览器 E2E。F4.31–F4.33、B0.2 仍未勾，F7.1/F7.2/F7.7 与最终 E2E 仍按总清单顺序后置。

### 15.341 F4.20/F4.21 授权 gate 权威终态清理一次性授权码（2026-10-09）

- **发现与修复：**若一次性部署授权码已输入，但 bootstrap 在当前 gate 仍挂载时由另一个操作者授权或关闭，原组件会转为受保护子树/关闭反馈，却保留本地授权码 state。现在 gate 订阅自己的 workflow，并且只在权威快照确认 `authorized` 或 `closed` 后清空；未确认失败仍保留可修正输入。
- **验证：**前端 setup logic **23/23 passed**；`npm run check:fast` 通过（typecheck、format、lint、Console OpenAPI 43 paths）。
- **边界：**这修复了敏感状态生命周期，但 workflow logic 与 SSR 不执行实际 React subscription effect；真实 DOM 清理仍待最终 IAB。F4.20/F4.21 不勾，真实 Python 后端/数据库/配置中心未参与。

### 15.342 B0.1 Nacos/Consul HTTP token header 控制字符防护（2026-10-09）

- **修复：**Nacos login 返回 access token 进入后续 `accessToken` header 前拒绝 ASCII 控制字符，稳定分类为 `authentication`；Consul ACL token 进入 `X-Consul-Token` 前做同一防护，格式不安全时分类为 `unsupported` 且不发出 provider 请求。既有 Provider Checker Port 和 Nacos/Consul 适配器边界不变，无新增设计模式或 abstraction。
- **验证：**新增两条回归先在旧实现上复现失败；修改后 provider checker、registered/bootstrap source check API 与首启适配测试合计 **30 passed, 2 deselected**；Python `compileall` 通过。
- **边界：**两个 loopback transport 用例因本轮明确排除而未运行；无真实 Nacos/Consul、TLS/ACL、数据库或浏览器验收。B0.1 不勾。

### 15.343 B0.1 Nacos 成功码严格类型校验（2026-10-09）

- **缺陷与回归：**Python 中 `False == 0`，Nacos 响应 `{"code": false}` 之前因 `code in {0, "0"}` 被误判为成功。新增回归先运行并失败，确认 checker 错误报告 source reachable。
- **修复：**只接受精确整数 `0` 或字符串 `"0"`；布尔值与其他格式都稳定分类为 `connection`。沿用现有 provider adapter 职责与 Port，不新增抽象或设计模式。
- **验证：**修复前回归 **1 failed**；源检查 suite（排除受沙箱限制的 loopback 类）**16 passed, 2 deselected**；注册源及首启 HTTP/security 联合聚焦 **32 passed, 2 deselected**；`compileall` 和 `git diff --check` 通过。联合运行有 25 条既有 HTTPX per-request cookies deprecation warnings。
- **边界：**未连接真实 Nacos/Consul、数据库或浏览器，未运行完整 E2E。B0.1 保持未勾选。

### 15.344 B0.1 Nacos/Consul HTTP header 值拒绝非 ASCII 字符（2026-10-09）

- **缺陷与回归：**原 token 校验只拒绝控制字符，允许可打印 Unicode。Nacos login 返回 Unicode access token 后仍会尝试第二次 HTTP 请求；Consul checker 也可能在可控请求 seam 下把 Unicode ACL token 报为可达，但实际 HTTP header 编码不受保证。两个新用例在修复前均失败。
- **修复：**统一只允许可见 ASCII HTTP header 值；Nacos 响应 token 不符合要求时映射 `authentication`，Consul 候选 ACL token 不符合要求时在 DNS/HTTP 之前映射 `unsupported`。无新增 Port、抽象或设计模式。
- **验证：**注册源 checker / API / bootstrap checker / 首启 API 聚焦套件 **34 passed, 2 deselected**；Python `compileall` 与 `git diff --check` 通过。25 条 HTTPX per-request cookies deprecation warnings 属测试接口既有用法。
- **边界：**未验证真实 HTTP transport、Nacos/Consul、TLS/ACL、数据库或浏览器；完整 E2E 未运行。B0.1 仍未勾选。

### 15.345 F4.20 初始化连接检查输入投影隔离合同（2026-10-10）

- **缺口：**初始化提交 DTO 已有投影测试，但数据库与规则源连接检查各自的最小输入尚未直接验证。若连接检查误用完整初始化 DTO，可能携带无关管理员/provider 凭证；若复用完整向导校验，也会让数据库连通性受来源字段阻断，或反之。
- **测试：**新增 `F4.20 SETUP-CHECK-PROJECTION` 聚焦 logic 用例。数据库检查只投影数据库参数，不受管理员及规则源字段无效影响；规则源检查只投影选定 provider/authentication 分支，不受数据库及管理员字段无效影响；Nacos/Consul 未选凭证及管理员/数据库秘密不进入相应结果。
- **验证：**`npm run test:logic:focused -- "SETUP-CHECK-PROJECTION"` **1/1 passed**。
- **边界：**仅为纯投影合同测试，不挂载 React、不执行连接网络，不证明 mounted React effect、页面内存清理或真实 Python API；完整 E2E 仍留最终阶段。未使用 Chrome/Edge/CDP，未访问真实数据库/Nacos/Consul。F4.20 继续未勾。

### 15.346 B0.3 Nacos 3 精确配置读取适配器（2026-10-10）

- **职责与依据：**新增 Nacos 规则配置的权威读取侧，供后续发布 worker 获取精确 provider 基线和 unknown-write reconciliation 使用。Nacos Admin API 官方定义 `GET /nacos/v3/admin/cs/config`，按 `namespaceId/groupName/dataId` 读取并返回内容与 MD5；适配器仍属于 infrastructure，不改变 application publication Port。认证登录抽取为 Nacos provider 共用 helper，检查器和规则读取复用同一 token 安全校验。
- **实现：**沿用 `RegisteredSourceTargetPolicy` DNS allowlist 与 `PinnedAioHttpJsonClient`，仅读取冻结 source 的单一命名空间/分组/dataId；严格验证响应三元身份、内容 UTF-8 bytes 与服务端 MD5 一致，内容从 repr 隐藏。HTTP 404/未知状态不推断配置不存在，fail-closed。HTTP transport 的有界响应尺寸可按消费方显式设置，Nacos reader 上限为 512 KiB 内容加响应元数据；access token 限 8192 字符且仅接受可见 ASCII。
- **验证：**`PYTHONPATH=src .venv/bin/pytest -q tests/test_nacos_rule_source_reader.py tests/test_registered_source_checker.py -k 'not Loopback'` **26 passed, 3 deselected**；`PYTHONPATH=src .venv/bin/python -m compileall -q src/atlas_richie/sentinel_console` 通过。3 个 loopback 测试因当前沙箱禁止绑定本地监听 socket 未执行；本轮未连接真实 Nacos/Consul。
- **边界：**此 reader 不是完整 `RulePublicationProvider`，未实现 gRPC CAS，也未解决 Nacos 首次创建的 create-only 语义；发布仍 fail-closed。B0.3/B0.1 不勾选，Console worker/service composition、真实 provider 验收和最终 E2E 仍开放。官方字段参考：[Nacos Admin API](https://nacos.io/en/docs/latest/manual/admin/admin-api/)。

### 15.347 B0.3 Nacos 3 现存配置 gRPC CAS 发布适配器（2026-10-10）

- **设计：**沿用已存在的 `RulePublicationProvider` 与 provider Adapter 边界，不改 Application Port、不引 SDK 私有对象。Console 自己生成最小 Nacos `Payload`/`Metadata` protobuf envelope，先通过 unary `Request` 做 `ServerCheck`，再通过 `/BiRequestStream/requestBiStream` 发送 `ConnectionSetupRequest` 注册连接，最后才发送 unary `ConfigPublishRequest`。setup 请求携带冻结 source namespace、`source=sdk` 标签、SDK 版本及与 Nacos Python SDK 3.2.0 对齐的能力表；server check 宣告能力协商时，Console 等待 `SetupAckRequest` 并通过同一双向流回送 `SetupAckResponse` 与原 requestId，否则遵循 SDK 的 100ms 注册 settle。注册 stream 在 unary 调用期间保持打开并排空服务端消息，随后取消并释放。source target policy 检查 HTTP 和 gRPC 两个端口，并在第二个端口复用同次 DNS pin 结果；HTTPS 使用配置 hostname 作为 gRPC TLS authority。Nacos 的短期认证 token 通过已存在的 pinned HTTP 登录 helper 获取，仅透传到 gRPC header。
- **实现范围：**新增 `NacosRuleSourceWriter`、`NacosRulePublicationProvider` 和 `create_nacos_rule_publication_worker`；只接受非空 provider MD5，对已存在目标做 `casMd5` 条件写，冲突映射为业务 conflict，成功后必须通过精确 Admin HTTP read-back 确认内容与 MD5。dispatch 后超时/无效响应/读回不匹配归 `outcome-unknown`，不自动重发。新增 `nacos-grpc` optional dependency，基础 Console 安装不引入 grpc/protobuf。
- **明确限制：**Nacos 3.2.3 对空 `casMd5` 走非 CAS 写路径，因此 create-only 当前不实现，缺失 revision 在发出网络请求前拒绝；目标 key 需预先存在并有精确可读 MD5。gRPC 真实握手/TLS trust chain 与 Console 全流程部署尚未验证，不能视为 Nacos 完整接入或 B0.3 完成。
- **验证：**Console provider writer/reader/policy/router/worker composition 定向套件 **43 passed, 4 skipped, 3 deselected**；在 `nacos-sdk-python==3.2.0` 环境，writer + protobuf/connection-setup 套件 **12/12 passed**。fake gRPC channel 检查了 ServerCheck → ConnectionSetup → SetupAckRequest/SetupAckResponse → CAS 顺序、缺失 setup ack 时不发送配置写入；SDK descriptor 对照、`compileall`、`git diff --check` 通过。未连接真实 Nacos/Consul，也未执行完整 E2E。
- **验收记录：**[B0.3 provider conditional-write](acceptance/R-SENTINEL-CONSOLE-B0.3-provider-conditional-write.md)。B0.3 仍未勾选。

### 15.348 B0.3 Nacos 3 create-only CAS 契约边界复核（2026-10-10）

- **源码观察：**Nacos Server 3.2.3 的 `publishConfig` 在 `casMd5` 非空时进入 `insertOrUpdateCas`；该具体持久层对现存 key 使用期望 MD5 条件更新，对缺失 key 走插入分支，插入会按候选内容重新计算并存储 MD5。空 `casMd5` 明确落入非 CAS 写路径。
- **决策：**不以伪造/非法 MD5 sentinel 依赖该内部实现。SDK 的公开 `publishConfigCas` 契约把 `casMd5` 定义为旧内容 MD5；Nacos Admin 普通 Publish 文档说明已存在配置会被更新，Import 只列 `policy=ABORT` 参数/默认值而未定义所需的原子 create-if-absent 契约。因此 `expected_revision=None` 继续在网络 dispatch 前拒绝。
- **依据：**验收记录新增 create-only 源码/API 边界说明及 Nacos 3.2.3 服务端源代码链接。未连接真实 Nacos、未验证所有受支持存储后端，也未执行并发创建验收。
- **结果：**这是对“不做 sentinel hack”的证据化决策，不关闭 create-only 能力或 B0.3。恢复实现前提是找到官方/版本化条件创建合同，并在支持矩阵覆盖并发创建、冲突分类、精确读回。

### 15.349 F4.20 初始化权威闭窗后的同步秘密清理（2026-10-10）

- **缺口：**此前页面在 passive `useEffect` 中收到初始化成功/服务端 `setup-closed` 后才调用 `clearSensitive()`。虽然终态 render 已隐藏向导，凭证仍可能短暂留在挂载中的 React draft，直到 passive effect 执行。
- **修复：**`InitializationPage` 将终态清理改到 `useLayoutEffect`，React 提交终态 UI 后、浏览器绘制前清除连接/管理员秘密并使连接检查失效；普通 effect 继续负责权威 bootstrap 重读和一次性完成导航。清理仍由既有 setup flow 唯一拥有，没有新增模式或共享状态副本。
- **验证：**Dashboard `npm run check:fast` 通过（typecheck、format、lint、OpenAPI contract）；`node --test --test-name-pattern='InitializationPage' tests/i18n/catalog.test.mjs` **1/1 passed**；`git diff --check` 通过。
- **边界：**此定向目录用例为 SSR，不执行 layout effect；本次没有内置浏览器工具，也未使用 Chrome/Edge/CDP，因此没有声称 mounted React 的时序验收。F4.20 仍未勾，最终浏览器 E2E 依计划留待全部实现完成。

### 15.350 F4.20 外部闭窗后秘密清理的最终 mounted 用例（2026-10-10）

- **新增验收：**扩展实际初始化页 probe：在含合成管理员/数据库秘密的挂载页面中由另一初始化者关闭 setup，再以新的权威 bootstrap 快照重新开放测试入口；返回管理员和数据库步骤应看到密码与用户名均为空。
- **验证：**E2E 源文件 `node --check tests/e2e/initialization.e2e.test.mjs` 通过；Dashboard `npm run check:fast` 通过；聚焦 `SETUP-LIFECYCLE|SETUP-SECRET` **3 passed**；`git diff --check` 通过。完整/浏览器 E2E 未执行。
- **边界：**此处只准备了最终验收用例并通过静态/逻辑检查，没有实际运行 mounted 页面。Python 持久化、真实数据库/规则源仍未参与；F4.20/F4.21 保持未勾，完整 E2E 留在全部实现收口后。

### 15.351 F4.22 登录成功后凭据子树在导航通知前卸载（2026-10-10）

- **实现：**`LoginCredentialForm` 在真实 anonymous 会话期间局部拥有账号/密码及字段校验。认证成功或 setup gate 接管时，父级按已确认 bootstrap/session facts 不再渲染凭据子树；错误、限流和未知结果分别保留可修正或只读核查所需表单。移除 Effect 内同步清状态，遵守 React Hook lint 与单一状态所有权。
- **验收用例：**`LoginEntryProbe` 在 `onAuthenticated` 时检查 credential form 是否已经卸载；对应断言追加至 `tests/e2e/login-entry.e2e.test.mjs`，但本轮不运行浏览器。
- **验证：**Dashboard `npm run check:fast` 通过；`npm run test:logic:focused -- 'F4[.]22'` **5 passed**；`node --check tests/e2e/login-entry.e2e.test.mjs` 与 `git diff --check` 通过。
- **边界：**逻辑测试未挂载 React；E2E 仅语法检查，未验证实际 DOM 卸载时序或真实 Python login/session/429。F4.22 仍未勾，最终端到端验收仍待全部开发完成。

### 15.352 F4.23 登录转场单一导航所有者（2026-10-10）

- **缺陷与修复：**`LoginEntryPage` 已由 `ConsoleLoginRoute` 回调负责已确认身份与 setup 状态导航；`App` 全局守卫同时处理 `ROUTE.Login`，会对同一权威快照重复调用导航。现在公开登录路由只由 feature route owner 处理转场，`App` 全局守卫仅处理非登录路由。
- **模式评估：**已按 GoF 决策表评估；这是消除重复 Effect 所有权，不存在需要新增的模式候选，不引入中介者/外观/事件总线。
- **验证：**新增架构约束后 `npm run test:architecture` **23/23 passed**；`npm run test:logic:focused -- 'authentication return route'` **1/1 passed**；Dashboard `npm run check:fast` 与 `git diff --check` 通过；E2E 文件 `node --check tests/e2e/app-authentication.e2e.test.mjs` 通过。完整 E2E 没运行。
- **边界：**`app-authentication.e2e.test.mjs` 已增加登录确认只触发一次 overview replace 的 mounted 断言，未在浏览器执行。F4.23 仍未勾；真实 Python session/logout/expiry/revocation、Cookie/CSRF 及浏览器→Python 联调仍开放。

### 15.353 F4.24 登录拒绝状态的三语 mounted E2E 用例（2026-10-10）

- **新增：**最终登录 E2E 现通过真实 `LoginEntryPage` 在简中、英文、日文分别提交合成拒绝凭据，并断言非枚举错误、用户名保留、密码遮蔽，以及凭据和原始异常不进入可见文本/浏览器存储。
- **验证：**`node --check tests/e2e/login-entry.e2e.test.mjs`、`git diff --check` 通过；未运行 CDP 浏览器/E2E。
- **边界：**仅新增可执行验收用例，不代表 mounted 浏览器结果或真实 Python Console 登录行为。F4.24 保持未勾，最终 E2E 留待所有实现完成。

### 15.354 F5.6 当前 production/demo 分包画像（2026-10-10）

- **方法：**在 `components/sentinel/dashboard-prototype` 分别执行 `npm run build` 与 `npm run build:demo`，由项目 `scripts/build/bundle-report.mjs` 计算 Vite manifest 的静态入口闭包；构建产物位于忽略的 `dist/client` 与 `dist/demo/client`。
- **结果：**production 入口 JS **756,914 B**、静态闭包 **974,919 B / gzip 265,263 B**、41 个 deferred entries；demo 入口 JS **760,469 B**、静态闭包 **978,474 B / gzip 266,437 B**、44 个 deferred entries。Nivo line **333,740 B / gzip 113,480 B** 在 deferred chunk。两个构建成功，仍有入口 chunk 超过 500 KB 的 Vite warning。
- **判断：**路由与图表分包已经生效，但入口包体没有低于当前 warning 门槛。本轮只刷新基线，没有引入 manualChunks，也没有通过调大阈值隐藏问题；后续需先归因初始 JS 的剩余 runtime，再评估按实际启动路径可拆的代码。
- **边界：**manifest 静态闭包不等于 demo bootstrap 在挂载前动态加载的全部网络字节，也不证明浏览器压缩传输、解析/交互耗时、列表容量或刷新/订阅释放；本轮没有运行浏览器或 E2E。F5.6 保持未勾。

### 15.355 F5.6 首屏 runtime 分组与依赖边界复核（2026-10-10）

- **归因：**临时 sourcemap build 显示原入口中主要包体包括 React DOM、Astryx、IntlMessageFormat、Zod、i18next；源映射只说明当前生成代码归属，不将包原始体积当作浏览器下载量。
- **问题与修复：**宽泛 identity HTTP barrel 由 app auth runtime 导入，导致 setup database/source check 与 initialize endpoint/schema 混入启动静态依赖。新增 `authenticationHttp.ts`、`setupHttp.ts`、`managementHttp.ts` 作为按能力拆分的 feature 公共入口，更新 Console runtime owners；`BUILD-SETUP-LAZY` 现在验证 setup endpoint 仅能从动态 setup 路由到达。
- **实验与回退：**将 Astryx Core/Zod 设为全局 manual chunk 会将低频页面依赖提升进首屏静态闭包，增加约 **211 KB**，因此撤销这两条分组。最终仅将 React runtime 与 i18n runtime 作为共享 chunk，保留 Astryx/Zod 的原路由边界。
- **产物：**隔离 sourcemap builds 的最大 JS chunk 为 production **463,990 B**、demo **467,680 B**；manifest 静态闭包分别 **960,941 B / gzip 261,061 B** 与 **964,634 B / gzip 262,231 B**，分别有 41 / 44 个 deferred entries。相对本轮首个 profile 减少约 14 KB 静态资产与约 4 KB gzip；不宣称用户感知提速。新增 BUILD-CHUNKS 回归保护所有输出 JS chunk 不超过 Vite 默认 500 KiB warning 上限。
- **验证边界：**production/demo sourcemap builds 均成功，`BUILD-SETUP-LAZY`、`BUILD-CHUNKS` 等 build profile **6/6** 通过；`npm run check:fast` 在最终 source patch 后运行。未运行完整 E2E 或内置浏览器。真实传输与解析耗时、MSW mount 前加载、列表容量、刷新重复和停止订阅释放仍开放；F5.6 不勾选。

### 15.356 B0.1 配置源检查协议测试复核（2026-10-10）

- **范围：**重跑 Nacos/Consul provider checker、registered-source check API、bootstrap checker 与 bootstrap source-check API 的受控测试；覆盖 credential-reference 的 use-case 解析、只读能力投影、认证失败分类及失败时无凭证回显。
- **命令与结果：**在 `components/sentinel/sentinel-console` 执行 `PYTHONPATH=src .venv/bin/pytest -q tests/test_registered_source_checker.py -k 'not Loopback' tests/test_registered_source_check_api.py tests/test_bootstrap_registered_source_checker.py tests/test_bootstrap_source_check_api.py`，**34 passed, 2 deselected**。出现 25 条既有 HTTPX per-request cookie deprecation warnings。
- **边界：**两个 loopback transport tests 因 sandbox 已知禁止本地 bind 而未执行；没有连接真实 Nacos/Consul、数据库或浏览器。该测试证明受控 adapter/API 协议，不证明厂商实例兼容、生产网络/TLS/ACL 或 B0.1 完成。详细记录见 [B0.1 source-check 验收记录](acceptance/R-SENTINEL-CONSOLE-B0.1-registered-source-check.md)。

### 15.357 F4.20 初始化生命周期定向复核（2026-10-10）

- **复核范围：**按用户要求暂不运行完整浏览器 E2E，重新执行 setup secret/provider-switch/discard 逻辑用例，以及实际 `InitializationPage` 的 open/locked/closed/failed 状态 SSR 用例。
- **命令与结果：**`npm run test:logic:focused -- 'SETUP-LIFECYCLE|SETUP-SECRET'` **3/3 passed**；`node --test --test-name-pattern='F4.20-SETUP-LIFECYCLE|F4.20-SETUP-PAGE-RENDER' tests/i18n/catalog.test.mjs` **1/1 passed**。
- **边界：**SSR 不运行 layout effect，逻辑测试不挂载 DOM；仍不能证明 mounted 页面的秘密清理时序。未运行浏览器或 Python E2E，F4.20 保持未勾，mounted 检查继续并入最终 E2E。

### 15.358 F5.2 规则草稿语言切换最终浏览器断言（2026-10-10）

- **新增用例：**`tests/e2e/rule-workspace.e2e.test.mjs` 增加三语顺序切换场景。先创建未保存的规则编辑，再经应用级 `changeLocale` 加载简中/英文/日文目录；逐语断言活动语言和翻译目录已应用、URL 不变、草稿值及 dirty 状态保留、切换本身不产生写操作/协议候选。最后仅显式保存一次，并核对候选仍绑定原 binding/profile/base checksum 且规则值不变。
- **验证：**仅完成本测试源语法检查与文档 diff 检查；按用户要求，未运行浏览器 E2E 或完整回归。
- **边界：**这只是最终浏览器套件的新增断言，尚无实际页面运行证据；不关闭 F5.2，继续留到全体实现完成后的最终 E2E。

### 15.359 F6.1 前端 OpenAPI 产物与 Python 路由 parity 复核（2026-10-10）

- **命令与结果：**在 `dashboard-prototype` 执行 `npm run contract:check`，生成声明与受控 OpenAPI 文件一致，包含 **43 paths**，状态为 `draft-partial`；在 `sentinel-console` 执行 `PYTHONPATH=src .venv/bin/pytest -q tests/test_console_openapi_route_parity.py`，**1 passed**。
- **边界：**该 parity 用例证明现有路径/方法映射，不证明逐页 request/response 字段、错误矩阵、权限、时间/分页/幂等语义已全部审完；`draft-partial` 也明确表示合同仍未冻结。未运行真实服务或浏览器，F6.1 保持未勾。

### 15.360 F4.20/F4.21 首启前后端定向测试复跑（2026-10-10）

- **前端命令与结果：**在 `dashboard-prototype` 执行 `npm run test:logic:focused -- 'SETUP-(COMMAND|SECRET|LIFECYCLE)'`，**13 passed**。覆盖 secret 分支清理、授权窗口终态、初始化单飞/权威确认、未知回执核查、已知拒绝后显式重提和取消/销毁边界。
- **Python 命令与结果：**在 `sentinel-console` 执行 `PYTHONPATH=src .venv/bin/pytest -q tests/test_bootstrap_initialization_api.py tests/test_bootstrap_initialization_coordinator.py tests/test_bootstrap_initialization_transaction.py tests/test_bootstrap_persistence_integration.py tests/test_first_run_http_persistence_integration.py tests/test_first_run_composition.py tests/test_first_run_deployment_configuration.py`，**32 passed**；HTTPX 输出 10 条 per-request cookie deprecation warnings。
- **边界：**两侧均为聚焦自动化证据。Python integration tests 使用本地/受控数据库与 ASGI fixtures，不证明 PostgreSQL/MySQL 真实部署、Ingress 多 worker、真实配置中心写入或跨服务浏览器 E2E。前端未运行 mounted 浏览器 secret-clear 用例或完整 E2E；未访问任何未授权服务。F4.20/F4.21/B0.2 保持未完成。

### 15.361 F6.1 OpenAPI 操作级 wire 完整性门禁（2026-10-10）

- **测试设计：**对唯一生成的 Console OpenAPI 逐 operation 核对 operationId 唯一、摘要/tag/语义规则齐全、安全方案引用有效、必需 request-id 存在、成功响应含正确 JSON/body 形状、错误响应带稳定错误码及 schema；POST/PUT/PATCH 必须显式声明 JSON request body，唯一无 body 的 logout 作为明示例外。另保留 Python app route table 与 OpenAPI 路径/方法逐项比较。
- **命令与结果：**在 `sentinel-console` 执行 `.venv/bin/pytest -q tests/test_console_openapi_route_parity.py`，**2 passed**；在 `dashboard-prototype` 执行 `npm run contract:check`，唯一前端协议产物与运行时 endpoint/schema 声明一致，**43 paths / draft-partial**；仓库根 `git diff --check` 通过。
- **边界：**该门禁校验 OpenAPI 结构完整性与 Python 注册路由形状，不证明 Python endpoint 的实际响应/授权与每个 schema 语义一致，也未完成逐页字段/时间/分页/幂等协议审计。没有启动服务或连接真实数据库/配置中心，未运行浏览器或完整 E2E；F6.1 仍不勾。

### 15.362 F6.1 修正匿名 session 与 CSRF Cookie 的 OpenAPI 安全语义（2026-10-10）

- **发现：**Python `GET /auth/me` 可在无 session cookie 时返回匿名状态，`POST /auth/login` 接受首次登录且只把已有 session cookie 作为待替换的旧会话；两者此前却在 OpenAPI 中把 `BrowserSession` 写成必需。CSRF 写接口实际校验 `__Host-sentinel_csrf` cookie 与 `x-sentinel-csrf` header 双提交，旧 OpenAPI 只列了 header。
- **修复：**`anonymous` 现在生成无 session 或可选 BrowserSession 两种 OpenAPI security alternative；`endpoint.csrf` 会组合必需 `CsrfCookie` scheme，登录表达为 CSRF cookie 必需且 session 可选，logout 表达为 BrowserSession 与 CSRF cookie 同时必需。补充协议设计文档；测试逐一保护所有带 CSRF header 的 operation，并固定 login/session/logout 组合语义。
- **验证：**先运行新增断言确认旧产物因缺少 `CsrfCookie` 失败；生成 OpenAPI 后 `npm run check:fast` 通过（typecheck、Prettier、ESLint、43-path contract check）；`sentinel-console` 定向 `tests/test_console_openapi_route_parity.py` **3 passed**，登录/匿名 session 路由合同 `PYTHONPATH=src .venv/bin/pytest -q tests/test_login_api.py tests/test_session_api.py` **17 passed**。
- **边界：**这是基于前端 endpoint metadata、Python route code 与生成合同的协议修正及受控契约测试；没有运行实时 ASGI 登录请求，也未连接数据库/配置中心或运行浏览器 E2E。F6.1 仍需逐页审计和后端响应语义验证，保持未勾。

### 15.363 F6.1 前后端错误码状态统一与 API 回归（2026-10-10）

- **实现：**Console OpenAPI 生成顶层 `x-error-status` registry；Python `http_support.error_response` 使用冻结的 code→status 表并拒绝未知 code 或 status 错配。合同测试核对两个 registry 相等，并检查所有 operation 允许的错误码落在其声明的 HTTP status。
- **缺陷修复：**共享 system-read helper 的默认坏 request-id 错误原为 `validation_failed` / 400；`/observation/catalog`、`/system/connections`、`/system/protocols` 和规则命令操作读取存在错误投影。现均为规范的 `invalid_request` / 400，更新三个过时 API 断言。
- **验证：**`dashboard-prototype` 执行 `npm run contract:generate && npm run check:fast`，43 paths OpenAPI、类型、格式与 lint 全部通过；`sentinel-console` `tests/test_console_openapi_route_parity.py` **5 passed**；所有 `tests/test_*_api.py` **223 passed**，耗时 7.73 秒，另有既有 HTTPX cookie deprecation warnings（62）。
- **边界：**API 测试使用本地 ASGI/受控 authority，不证明生产 DB/配置中心、部署网络或浏览器端到端；完整 F6.1 页面/DTO/时间/分页/幂等/权限审计仍未完成。

### 15.364 F6.1 时间与游标长度 wire 边界（2026-10-10）

- **协议对照：**前端 `UtcInstantSchema` 仅接受带 `Z` 的严格 UTC 毫秒时间，年份限制为 1970–9999。共享 `utc_timestamp()` 此前对 naive datetime 调用 `astimezone()`，会隐式依赖运行机器本地时区，且 UTC 转换跨越 wire 年份边界时可能越界；Python 查询解析此前也允许 0001–1969 年。故障游标前端按 JavaScript UTF-16 字符串长度限制 512，Python 域模型此前按 Unicode 码点计数，允许 257 个 emoji（514 个 UTF-16 单元）。
- **修复与测试：**序列化器现在拒绝 naive datetime，先归一化为 UTC，再检查 UTC 年份范围；转换溢出转成稳定 `ValueError`，保留既有微秒截断到毫秒的 wire 行为。查询解析收紧到 1970–9999；Python 游标长度现按 UTF-16 单元与前端一致。`tests/test_utc_wire.py` 覆盖时间规范化、naive/越界拒绝、严格 Z/毫秒格式和非法日历日期；incident domain/API 测试覆盖 512/514 UTF-16 单元边界。修复前新增反例先失败，修复后通过。
- **验证：**在 `sentinel-console` 执行 `PYTHONPATH=src .venv/bin/pytest -q tests/test_utc_wire.py tests/test_*_api.py`，**235 passed**；62 条既有 HTTPX per-request cookie deprecation warnings。
- **边界：**该切片验证共享 Python 序列化边界和 API 测试回归，不代表已完成所有 DTO 字段的逐页 schema 对照、真实 PostgreSQL/MySQL 行为或浏览器 E2E；F6.1 仍保持未勾。

### 15.365 F6.1 分页 OpenAPI 上限与 Python 游标长度契约（2026-10-10）

- **契约门禁：**新增 Python contract test 扫描当前生成 OpenAPI 的全部 query 参数：所有 `page` 均为 1–1,000,000，所有 `pageSize` 均为 1–100；incidents `cursor.maxLength` 必须等于 Python `MAX_INCIDENT_CURSOR_LENGTH`。这使前端 schema 变化不能静默偏离后端已冻结的上限。
- **行为覆盖：**incident domain 用例接受恰好 512 个 UTF-16 单元的游标并拒绝 514 个；API 用例确认越界游标在 authority 调用前以 `invalid_request` / 400 拒绝。新增解析器测试逐个调用 Fleet、Instances、Accounts、System Audit、Rule Bindings、Publication Receipts 六类 Python parser，验证 page=1,000,000/pageSize=100 原值保留，并拒绝 page/pageSize 的 0、1,000,001、101 越界。
- **验证：**`dashboard-prototype` 执行 `npm run contract:check`，**43 paths / draft-partial** 与唯一 OpenAPI 产物一致；`sentinel-console` 执行 `.venv/bin/pytest -q tests/test_pagination_wire_bounds.py tests/test_console_openapi_route_parity.py`，**39 passed**。UTC + API 测试切片 §15.364 为 **235 passed**。
- **边界：**本切片验证六类真实 query parser 和生成 schema 的上下界，但非每个路由的 ASGI/权限/authority 全组合；事故 timeline、账户、系统审计等读模型的跨页排序稳定性及生产持久化仍未完成验证；F6.1 不勾。

### 15.366 F6.1 幂等 request key 跨前后端统一（2026-10-10）

- **发现：**四类幂等命令（bootstrap、account、registered source、rule set）在 Python/OpenAPI 中约定 request key 为 1–128 位 `[A-Za-z0-9._:-]`，且必须同时匹配 `Idempotency-Key` 与 body `requestKey`。规则 feature 的 transport 已按 `RequestKeySchema` 校验请求，但 `ruleSetWire.ts` 的 command/operation request、response 以及 operation path parameter 错用了通用 `OpaqueIdentifierSchema`，OpenAPI 因而把 wire 上限放宽到 200。新增契约断言先复现失败。
- **修复：**规则 command DTO、操作回执的四种状态、request DTO、operation parameter 与 OpenAPI path metadata 全部改用唯一 `RequestKeySchema`；重新生成 `console-api.openapi.json`。contract test 现在验证四类命令均有必需幂等 header、body requestKey、未知结果标记、原操作查询路径，以及请求/回执/path 上限和 Python regex 一致。
- **验证：**`dashboard-prototype` 执行 `npm run check:fast` 通过（typecheck、Prettier、ESLint、43-path contract check）；`npm run test:http:focused -- 'RULE-COMMAND|OPERATION'` **4 passed**。`sentinel-console` 执行 `PYTHONPATH=src .venv/bin/pytest -q tests/test_console_openapi_route_parity.py` **7 passed**，以及 command adapter/application slice **29 passed**（20 条既有 HTTPX cookie deprecation warnings）。
- **边界：**这些证据覆盖协议生成、前端 transport 与 Python command 测试；不证明数据库并发去重/进程重启恢复、生产部署或浏览器 E2E。F6.1 仍需完整 DTO/权限及未知回执语义审计，保持未勾。

### 15.367 F6.1 OpenAPI UTF-16 字符长度语义（2026-10-10）

- **发现：**Python 对公开字符串上限按 UTF-16 code units 校验；标准 JSON Schema `maxLength` 按 Unicode code points 计数。新增边界测试又证明当前 Zod `.max(n)` 也按 code points 计数：例如 101 个 emoji 会通过 200 上限，但 Python 拒绝。此前合同只用标准 `maxLength`，所以文档与两个运行时都没完整表达既定边界。
- **修复：**新增共享 `utf16BoundedString(n)`，在保留标准 `.max(n)` 的同时用 ECMAScript 无 `u` 正则按 UTF-16 code units 限长；将所有直接的有界 wire 字符串迁移到该 helper。OpenAPI 生成器递归输出 `x-max-utf16-code-units`，并说明消费者需执行此 Console 扩展约束；不改变 Python 已冻结的上限。CONSOLE_API_CONTRACT、React 重构地图与页面接口文档同步当前 **43 paths** 和长度语义。
- **测试设计与结果：**前端合同测试遍历所有生成的受限字符串 schema，并验证 200 ASCII/100 emoji 接受、101 emoji 拒绝；Python 路由/合同测试检查全部 schema 扩展及 Python 代表性领域边界。修复前分别由 Python 缺少扩展断言、Zod 101 emoji 通过复现；修复后 `dashboard-prototype`: `npm run test:http:focused -- 'CONSOLE-MACHINE'` **3 passed**、`npm run check:fast` 通过；`sentinel-console`: `.venv/bin/pytest -q tests/test_console_openapi_route_parity.py tests/test_account_username.py tests/test_rule_bindings_api.py tests/test_registered_sources_api.py` **24 passed**。`npm run contract:generate` 与 `contract:check` 均确认 **43 paths / draft-partial**。
- **边界：**验证覆盖所有生成的字符串长度 schema 元数据及 Python 代表性运行时边界，不替代每个字段独立业务验证；未启动浏览器/服务或连接真实依赖，未运行完整 E2E。F6.1 仍保持未勾。

### 15.368 F6.1 OpenAPI 逐操作角色/能力权限合同（2026-10-10）

- **发现：**43 个 operation 虽有 `security` Cookie/session 描述，但 admin、`metrics:view`、`rules:write` 仍主要写在自然语言 `x-semantic-rules` 中；生成合同消费者无法机器判定逐接口额外授权，Python 路由则已实现 admin role 或 session capability 门槛。
- **实现：**`ConsoleOperationContract.requiredAccess` 为每个 operation 显式声明不可变角色/能力要求，并由 OpenAPI 统一输出 `x-required-access: { role, capabilities }`。`security` 继续单独描述 session/bootstrap/CSRF 机制；生成器拒绝未知/重复能力，以及未受 session 保护却声明角色/能力的 operation。43 个接口均有该字段，21 个接口声明了额外角色/能力限制；覆盖 admin 账号/来源/审计/命令核查、六类 `metrics:view` 观测、规则草稿校验/比较能力，以及 admin + rules:write 规则命令。更新 §9 当前协议说明，并修正应用目录实际为 session-only、草稿读取由 `rules:write` 保护的表述。
- **测试设计：**前端从同一 runtime registry 断言每个 OpenAPI operation 均精确投影 `requiredAccess`，扩展值只允许当前 admin role 和两项既有 capability，敏感访问必须同时要求 session。Python parity test 对全部 operation 执行穷尽授权矩阵断言；另复跑对应账号、观测、来源、规则路由现有 viewer/admin 负例和正例。
- **验证：**`dashboard-prototype`: `npm run contract:generate`、`npm run check:fast`、`npm run test:http:focused -- 'CONSOLE-MACHINE'`（4 passed）；OpenAPI contract check 为 **43 paths**。`sentinel-console`: `.venv/bin/pytest -q tests/test_console_openapi_route_parity.py tests/test_read_session.py tests/test_account_directory_api.py tests/test_system_audit_api.py tests/test_registered_sources_api.py tests/test_registered_source_check_api.py tests/test_registered_source_commands_api.py tests/test_fleet_overview_api.py tests/test_instance_catalog_api.py tests/test_incident_timeline_api.py tests/test_rule_bindings_api.py tests/test_rule_set_snapshot_api.py tests/test_rule_drafts_api.py tests/test_rule_candidate_diff_api.py tests/test_rule_candidate_validation_api.py tests/test_rule_commands_api.py`，**124 passed**；`git diff --check` 通过。新增 Python 契约断言在实现前因 operation 缺失 `x-required-access` 先失败。
- **边界：**这次补齐 machine-readable authorization 声明并回归现有 route policy，不修改 Python route 实现；不等于 43 个接口均已在生产 `build_app` 装配，也不替代真实 DB/配置中心、跨服务浏览器 E2E 或完整 F6.1 全字段协议审计。未运行浏览器/全量 E2E；F6.1 仍不勾。

### 15.369 F6.1 全操作 request-id 错误矩阵（2026-10-10）

- **发现：**`authorize_system_read()` 对缺失或非法 `X-Request-ID` 明确返回 `400 invalid_request`。逐项对照发现 observation catalog、system connections/protocols 和 registered sources 四个 endpoint 未声明这个可达错误，OpenAPI 错漏 400 response；既有 ASGI 用例已证明这些路由拒绝非法 request ID。
- **修复：**四个 endpoint 的错误矩阵现在包含 `invalid_request`；system observation 的共享错误列表承载共同失败，不再让 audit endpoint 重复追加。契约测试扩展为遍历全部 **43 operations**：每个必需 `X-Request-ID` 都必须允许 `400 invalid_request`。重新生成唯一 OpenAPI JSON，并在 `CONSOLE_API_CONTRACT.md` §9.6 冻结缺失/非法 request ID 的 400 语义和禁止回显规则。修复前新增断言先因 observation catalog 失败，随后扩展检查再捕获 registered sources 的遗漏。
- **验证：**`dashboard-prototype`: `npm run contract:generate`、`npm run contract:check`、`npm run test:http:focused -- 'CONSOLE-MACHINE'` **4 passed**、`npm run check:fast` 通过（typecheck/格式/lint/43-path OpenAPI）。`sentinel-console`: `.venv/bin/pytest -q tests/test_console_openapi_route_parity.py tests/test_observation_catalog_api.py tests/test_system_connections_api.py tests/test_system_protocols_api.py tests/test_registered_sources_api.py` **31 passed**；`git diff --check` 通过。
- **边界：**这是四个明确的 endpoint-error/OpenAPI 契约闭环，不代表其余 wire DTO/错误矩阵已逐项审完；未运行完整 E2E、浏览器或真实外部依赖。F6.1 仍不勾。

### 15.370 F6.1 规则校验/比较错误矩阵与副作用边界（2026-10-10）

- **发现：**`validateRuleCandidate` 与 `compareRuleCandidate` 共用命令错误集合，导致声明了 Python 路由不会产生的 `idempotency_conflict`、`unsupported_profile`，同时漏掉 `browser_write_proof()` 明确返回的 `csrf_failed`。两者虽是 POST + CSRF，但都不是带 request key 的幂等命令；且校验会持久化 receipt/审计，纯比较则无持久化写入。
- **修复：**为两个候选操作建立独立 `candidateErrors` 集合：继承读取类错误，加入 `csrf_failed`、`conflict` 和 `validation_failed`，不暴露幂等冲突或不支持 profile 错误。OpenAPI parity test 精确断言两个 operation 的完整错误集合，修复前失败显示“缺少 csrf_failed、多出 idempotency_conflict/unsupported_profile”。同步修正 `CONSOLE_API_CONTRACT.md` §9 操作矩阵，区分 validate receipt/audit 持久化与 diff 无持久化副作用，并注明二者不是幂等命令。
- **验证：**`dashboard-prototype`: `npm run contract:generate`、`npm run check:fast` 通过；`npm run test:http:focused -- 'CONSOLE-MACHINE|RULE-CANDIDATE'` **5 passed**。`sentinel-console`: `.venv/bin/pytest -q tests/test_console_openapi_route_parity.py tests/test_rule_candidate_validation_api.py tests/test_rule_candidate_diff_api.py` **29 passed**；`git diff --check` 通过。
- **边界：**该切片证明前端可执行 endpoint 错误声明与 Python 候选 API 现有分支对齐，并修正文档的持久化副作用描述；不证明 DB 并发、production composition、provider 写入或 E2E。F6.1 仍不勾。

### 15.371 F6.1 首次初始化 operator exchange 的 CSRF 契约（2026-10-10）

- **发现：**Python `bootstrap_authorize_route()` 必须验证 `__Host-sentinel_csrf` cookie 与 `x-sentinel-csrf` 双提交证明；但前端 `AuthorizeBootstrap` endpoint 标记 `csrf: false`，故正式 transport 不会发送从 bootstrap GET 响应捕获的 nonce，首次 operator-code exchange 会被后端以 `csrf_failed` 拒绝。错误集合也错列了该 route 不会返回的 `bootstrap_unauthorized`，同时漏掉 `csrf_failed`。
- **修复：**将该 endpoint 标记为 CSRF-protected，使生成 OpenAPI 声明 `CsrfCookie` 与必需 `x-sentinel-csrf` header；operation 错误码改为与 Python exchange route 一致的 `invalid_request`、`forbidden`、`csrf_failed`、`conflict`、`rate_limited`、`service_unavailable`。在 bootstrap HTTP transport 测试中断言 authorize 请求确实发送由先前 bootstrap 响应建立的 CSRF nonce，并用 Python contract test 精确核对 security 与完整错误码。
- **验证：**修复前新增契约断言因缺 CSRF error / 错列 bootstrap_unauthorized 失败；修复后 `dashboard-prototype`: bootstrap/console/candidate focused HTTP **7 passed**、`npm run check:fast` 通过（类型、格式、lint、43-path OpenAPI）。`sentinel-console`: parity、bootstrap authorize、candidate validate/diff、observation catalog、system connections/protocols、registered sources API slice **57 passed**；`git diff --check` 通过。
- **边界：**证明前端 transport 合同会携带测试中的 CSRF header，且 Python route 现有 ASGI 用例验证双提交拒绝语义；未运行浏览器、真实安装服务或完整 E2E。F6.1 仍不勾。

### 15.372 F6.1 bootstrap/source observation 逐路由错误码精确化（2026-10-10）

- **发现：**继续对照 Python endpoint 分支发现来源操作回执路由把非法 request ID 错报为 `422 validation_failed`，与唯一协议 `400 invalid_request` 不符；系统观察、来源注册表与首次初始化多个 OpenAPI operation 还复用了通用错误列表，声明了路由没有的 `forbidden` / `rate_limited` / `not_found`，或遗漏可达错误。
- **修复：**来源回执错误 request ID 改为 `invalid_request`/400，并增加实际 ASGI 负例。分别收窄 observation catalog、system connections/protocols/audit、registered-source registry 的错误集合；将 bootstrap database/source check、initialize 与 initialization lookup 的 OpenAPI 错误码按各自 Python route 分支精确声明。Python parity test 对这 9 个 operation 的错误集合做精确相等检查，避免 generic allowlist 漂移。
- **验证：**修复前新 ASGI 用例复现来源回执返回 422（期望 400）；合同断言复现 readObservationCatalog 错报 forbidden/rate_limited。修复后 `dashboard-prototype`: `npm run check:fast` 通过（typecheck、格式、lint、43-path OpenAPI），Console/bootstrap/candidate focused HTTP **6 passed**。`sentinel-console`: parity、bootstrap authorize/database/source/initialization、registered source command、observation catalog、system connections/protocols/audit、registered sources 测试 **79 passed**（51 条既有 HTTPX per-request cookie deprecation warnings）；`git diff --check` 通过。
- **边界：**这些是基于实际 ASGI adapter 分支的逐 operation 错误合同收口，不是对 43 个 endpoint 所有动态 authority 异常的完整运行时矩阵，也未覆盖生产装配、外部服务、浏览器或完整 E2E；F6.1 仍不勾。

### 15.373 F6.1 账号读取与变更错误矩阵精确化（2026-10-10）

- **发现：**账号 list/detail/operation lookup 共用的前端读取错误策略将 `rate_limited` 声明给没有限流分支的 Python 路由；账号 mutation 路由同样没有 rate-limit adapter，却重复声明该错误码。新增精确矩阵测试先失败并捕获 list 与 mutation 两处错报。
- **修复：**收窄账号读取和 mutation 的 endpoint errors；新增 OpenAPI parity 测试逐项冻结 list、detail、mutation、operation lookup 四类账号 operation 的完整错误集合。更新 `CONSOLE_API_CONTRACT.md` 记录路由实际可达错误及 unknown operation 作为安全 `not-found` observation、不是 HTTP `not_found` 的区别，并重新生成唯一 OpenAPI。
- **验证：**`dashboard-prototype`: `npm run check:fast` 通过（TypeScript、格式、lint、43-path OpenAPI），账号 focused HTTP **10 passed**；`sentinel-console`: OpenAPI parity + account directory API **19 passed**；`git diff --check` 通过。
- **边界：**该切片只收口 account endpoint 错误矩阵；未新增 account mutation ASGI route 测试，未覆盖 production app assembly、真实数据库、浏览器或 E2E。F6.1 整体仍未完成，checkbox 不变。

### 15.374 F6.1 本人改密错误矩阵精确化（2026-10-10）

- **发现：**`changeOwnPassword` endpoint 将 `forbidden` 纳入可达错误，但 Python route 只依据当前 session actor 修改本人密码，不按 role 拒绝；错误仍包含正确的 CSRF、当前密码错误、输入校验、会话、限流与服务不可用分支。
- **修复：**移除不可达 `forbidden`，新增 OpenAPI parity 完整错误集合断言，并在 Console 协议说明中固定本人改密错误矩阵及其不含 role-based 拒绝的语义。
- **验证：**修复前新增 parity 断言捕获多出的 `forbidden`；修复后 `dashboard-prototype`: `npm run check:fast` 通过、account/password focused HTTP **12 passed**；`sentinel-console`: parity、account directory、own-password **28 passed**；`git diff --check` 通过。
- **边界：**只证明 route-visible error 与 OpenAPI 声明一致，不证明生产密码库装配、真实数据库/限流跨进程行为或浏览器/E2E。F6.1 整体仍未完成，checkbox 不变。

### 15.375 F6.1 bootstrap/session/login/logout 访问错误合同核对（2026-10-10）

- **核对：**为匿名 bootstrap、session observation、login 和 logout 增加逐 operation 精确错误矩阵；同步断言 login/logout 的 OpenAPI 要求 CSRF header，避免匿名初始化链路与已登录会话边界混用。
- **结果：**现有 Python adapter 的可达错误与 endpoint 合同一致：bootstrap `invalid_request/service_unavailable`；session `invalid_request/unauthenticated/service_unavailable`；login 另有 `csrf_failed/rate_limited`；logout 有 `csrf_failed` 但不具备限流分支。此切片没有发现需要修改的 API endpoint 声明。
- **验证：**新增 parity 用例通过（1 passed）；本次仍需与账号和本人改密 slice 的完整回归合并观察，不单独称身份协议全量验收。
- **边界：**仅是 OpenAPI 对照源码路由的静态合同证明；没有替代 login/logout ASGI 错误路径测试、production composition、浏览器或 E2E。F6.1 整体仍未完成，checkbox 不变。

### 15.376 F6.1 规则接口错误矩阵及 Mock 业务拒绝语义对齐（2026-10-10）

- **发现：**规则 API 共用的 `readErrors/writeErrors` 将 `forbidden`、`not_found`、`rate_limited`、`conflict`、`unsupported_profile` 泛化给多个实际不产生这些 HTTP 错误的 operation；publication-target 不存在目标的 Python 语义是 `target: null`。首轮精确 parity 断言先捕获 readRuleBindings 多报 `forbidden`；收紧后已有 Mock 集成用例又揭示其把已授权命令业务冲突当 HTTP 409，而 Python `RuleMutationStore` 持久化 `rejected` operation 并以 202 返回。
- **修复：**拆分 session read、draft permission、候选、operation lookup 与 publication-target 错误策略；`mutateRuleSet` 只声明路由真实 HTTP 错误。新增覆盖 13 个 rule operation 的完整 OpenAPI error matrix。Mock 中配置源 revision/target 冲突、计划重叠/取消冲突及业务不存在/语义拒绝统一保存并返回 `202 rejected`，publication-target 未登记返回 null；对应测试改为验证 durable operation observation。协议文档解释 transport HTTP 冲突与已接受业务拒绝的区别，并重新生成 OpenAPI。
- **验证：**`dashboard-prototype`: rule focused HTTP **8 passed**，`npm run check:fast` 通过（类型、格式、lint、43-path contract）；`sentinel-console`: parity + bindings/snapshot/drafts/versions/publications/plans/commands/candidate API tests **100 passed**；`git diff --check` 通过。
- **边界：**Mock 对齐不构成持久数据库并发/跨进程证明；`publication-target` 及 mutation 生产 composition、Nacos/Consul、浏览器/E2E 仍未验收。F6.1 仍整体未完成，checkbox 不变。

### 15.377 F6.1 账号命令 Python ASGI 错误/安全路径覆盖（2026-10-10）

- **缺口：**此前账号命令仅有应用层命令测试、账号目录 read route 测试与 OpenAPI error parity，`account_command_routes` 本身没有 ASGI 请求边界验证，未能证明实际 Cookie/Origin/CSRF/request-key/角色顺序及拒绝响应。
- **补齐：**新增 `test_account_commands_api.py`，通过 Starlette `ASGITransport` 验证 admin create 的安全业务拒绝回执（密码不出现在 repr/response）、缺 CSRF、view 越权、header/body requestKey 冲突、revision 非规范数值拒绝、原操作 unknown 的 `not-found` observation 与 authority 故障脱敏；拒绝请求不调用 command service。
- **验证：**账号 command API、账号目录 API、应用层命令和 Console OpenAPI parity 聚焦合并 **33 passed**。
- **边界：**这些 adapter 测试用受控 session/command doubles，证明 HTTP/security 适配语义，不证明 SQL transaction/并发不变量（由独立持久层测试负责）、production composition、真实浏览器或 E2E。F6.1 仍整体未完成，checkbox 不变。

### 15.378 F6.1 指标/实例/故障观测错误矩阵精确化（2026-10-10）

- **发现：**对照 fleet、instance、metrics、incident Python routes 与 frontend endpoint declarations 后，`readIncidentTimeline` 漏报 Python `IncidentTimelineTargetNotFound` 分支，权威目录目标缺失会返回 HTTP 404 `not_found`，但客户端 adapter 会把其当作未声明/无效响应处理。
- **修复：**timeline endpoint 补充 `not_found`；新增 parity test 精确冻结 fleet、instance catalog/detail、metrics query、incident timeline/evidence 六个 operation 的完整错误集合，特别区分实例 incarnation 退役的 410 `target_retired` 与普通目标缺失。同步更新协议说明并重生成 OpenAPI。
- **验证：**修复前新增 parity 断言因 `readIncidentTimeline` 缺少 `not_found` 失败；修复后 `dashboard-prototype`: `check:fast` 通过、观测 HTTP focused **26 passed**；`sentinel-console`: parity + fleet/instance catalog/incident timeline ASGI **51 passed**。
- **边界：**该切片对齐观测 API error semantics，不是完整 query/time/page DTO audit，也未覆盖 production telemetry dependencies、浏览器或 E2E。F6.1 仍整体未完成，checkbox 不变。

### 15.379 F6.1 已登记配置源错误矩阵与查看者 Mock 权限夹具（2026-10-10）

- **发现：**逐 operation 对照配置源 Python route 与 OpenAPI 后，`mutateRegisteredSource` 原来复用过宽的 HTTP 错误集合，额外声明了实际不会从该 route 产生的 `not_found` 和 `conflict`；业务拒绝由已受理 operation 回执表达，不等同 HTTP 冲突。新增的精确矩阵断言覆盖 read/check/mutate/operation lookup 四类端点。前端 focused suite 同时发现查看者读取配置源 Mock 用例失败，根因是测试 `localStorage.getItem()` 对所有 key 恒返回 `view`，与 `run()` 先写 admin 的流程冲突，最终回退到缓存的 admin principal。
- **修复：**前端 mutation endpoint 改用独立 `commandErrors` 精确列表（invalid request、认证/授权、CSRF、幂等冲突、校验、限流及服务不可用）；同步 Console API 合同文档并重新生成 OpenAPI。权限测试夹具改为按 key 持久读写 `localStorage`，先由 harness 建立 admin 再明确切换 view，从而真实覆盖 403 拒绝断言。
- **验证：**`dashboard-prototype`: `npm run contract:generate`、`npm run check:fast` 通过，`npm run test:http:focused -- 'SOURCE|SYSTEM'` **18 passed**。`sentinel-console`: `.venv/bin/pytest -q tests/test_console_openapi_route_parity.py tests/test_registered_source_check_api.py tests/test_registered_source_commands_api.py` **34 passed**。格式化与生成 OpenAPI 一致性检查通过。
- **边界：**Mock 权限用例只证明前端演示模式的 handler 拒绝语义；Python API 用受控依赖验证 route/error contract，不代表真实配置中心访问、生产 DB、部署或浏览器 E2E。F6.1 的逐页 DTO/时间/分页/幂等/权限完整审计仍未完成，checkbox 不变。

### 15.380 F6.1 协议样例交付状态纠正（2026-10-10）

- **发现：**`CONSOLE_API_CONTRACT.md` 顶部声称逐 DTO 正负样例已生成，但基线生成物有 43 paths、`example/examples` 节点为 0。HTTP 测试中虽有分散样例，不能据此声称已有覆盖每个 operation 的统一样例目录。
- **修正：**收窄文档声明为 Runtime Schema/OpenAPI 已生成；明确正负样例目前分散在自动化测试，统一 operation 样例目录尚未交付。避免把局部测试覆盖误报为 F6.1 样例要求已完成。
- **验证：**修改前 Node 只读扫描确认 `{paths: 43, exampleNodes: 0, status: draft-partial}`；后续样例实现进度见 §15.381。`git diff --check` 通过。
- **边界：**纠正文档声明不关闭协议样例要求，checkbox 不变。

### 15.381 F6.1 配置源 operation 正负样例进入唯一 OpenAPI 生成链（2026-10-10）

- **实现：**`ConsoleOperationContract` 增加 operation-owned exchange examples；OpenAPI generator 将请求/响应样例投影到标准 media-type `examples`，并在 `x-contract-examples` 保留完整请求路径/查询/正文与响应交互。配置源 registry、check、mutation、operation lookup 四个 operation 各新增一正一负，共 8 个 exchange；包含 `202 pending`、安全 `200 not_found` 观察、角色拒绝、错误 request-body 校验等不同边界，无真实凭证。
- **验证：**contract tests 用运行时 Zod 输入/输出 schema、错误 code/status registry 与生成 examples 双向断言 8 个 exchange。OpenAPI 实际统计为 **43 operations / 4 operations with examples / 8 exchanges / 12 media examples**，仍为 `draft-partial`。`dashboard-prototype`: `npm run check:fast` 通过，`npm run test:http:focused -- 'CONSOLE-MACHINE|SOURCE|SYSTEM'` **23 passed**。`sentinel-console`: OpenAPI parity + registered-source read/check/command API suites **39 passed**。`git diff --check` 通过。
- **边界：**样例目录当前只覆盖 4/43 operations；其它 operation 的正负 request/response 例子仍需逐组补齐并由 runtime schemas 与 Python route tests 验证。受控测试不代表真实 DB/配置中心、部署或浏览器 E2E；F6.1 不勾。

### 15.382 F6.1 账号 operation 正负样例与同步回执状态对齐（2026-10-10）

- **实现：**账号目录读取、账号详情、账号变更和变更核查四个 operation 纳入同一 OpenAPI 样例链。变更包含最终 `completed` 成功回执、`rejected/username_taken` 业务拒绝以及非法角色输入；请求密码均为合成样例，不进入任何响应。明确 V1 账号命令在 HTTP 请求内同步完成：wire 回执仅有 `completed/rejected`，查询另可返回 `not-found`；React command resource 的 `pending` 只表示请求仍在途，HTTP 响应丢失才进入 `result-unknown` 并触发显式核查。
- **修正：**移除前端账号 wire DTO/Port/工作流允许的伪 `pending` 回执及其 E2E probe 分支。原测试改为覆盖真实 HTTP in-flight 单飞与“写请求超时 → `not-found` 仍锁定 → 最终 `rejected` 确认”的同步命令语义；初始化和规则发布等真正异步命令的 `pending` 协议保持不变。
- **验证：**OpenAPI 生成后统计为 **43 operations / 8 operations with examples / 17 exchanges / 24 media examples**；operation 样例测试同时断言账号 command schema 拒绝 `pending`。`dashboard-prototype`: `npm run test:logic:focused -- 'ACCOUNT-CREATE|ROLE-IN-FLIGHT'` **5 passed**，`npm run test:http:focused -- 'CONSOLE-MACHINE'` **5 passed**，`npm run check:fast` 通过（typecheck/format/lint/contract check）。`sentinel-console`: `.venv/bin/pytest -q tests/test_console_openapi_route_parity.py tests/test_account_directory_api.py tests/test_account_commands_api.py` **29 passed**；`git diff --check` 通过。
- **边界：**这是前端协议样例、工作流合同与 Python 已实现账号命令状态的定向对齐，不证明生产数据库并发、部署网络或浏览器完整 E2E；统一样例仍覆盖 8/43 个 operation，F6.1 不勾。

### 15.383 F6.1 身份与首次访问核心操作正负样例（2026-10-10）

- **实现：**`readBootstrap`、`authorizeBootstrap`、`readSession`、`login`、`logout` 与 `changeOwnPassword` 加入 operation-owned 正负 HTTP 样例，并由唯一 OpenAPI 生成器输出。样例覆盖初始化授权与匿名/管理员会话、成功登录与凭据拒绝、CSRF 失败、空 204 注销、本人改密重新认证及旧密码拒绝；凭证均为 synthetic 占位值且只出现在 write-only 请求中。
- **验证：**`npm run test:http:focused -- 'CONSOLE-MACHINE'` **5 passed**，逐样例校验请求/响应 DTO、状态码、error code 与 OpenAPI projection。`dashboard-prototype`: `npm run check:fast` 通过；`sentinel-console`: `tests/test_console_openapi_route_parity.py`、bootstrap authorization/read、login/logout/session 和 own-password API suite **70 passed**。生成物统计现为 **43 operations / 14 operations with examples / 29 exchanges / 41 media examples**。
- **边界：**样例和受控 API 测试不证明真实浏览器、真实部署授权码、数据库、session cookie 的跨进程行为或生产环境；F6.1 继续未勾。

### 15.384 F6.1 首次初始化数据库/配置源检查及初始化 operation 样例（2026-10-10）

- **实现：**补齐 `checkBootstrapDatabase`、`checkBootstrapSource`、`initializeConsole` 与 `readInitialization` 的正负 operation examples。覆盖 SQLite 可达、非法端口、Nacos 无认证连接、危险 URI 在联网前拒绝、幂等初始化 pending、非法数据库受理前拒绝，以及原 operator 查询 completed/not-found；所有数据库、管理员密码均是 synthetic write-only 值，响应不返回配置内容。
- **验证：**`npm run test:http:focused -- 'CONSOLE-MACHINE'` **5 passed**；`dashboard-prototype`: `npm run check:fast` 通过。`sentinel-console`: OpenAPI route parity + bootstrap read/authorize/database-check/source-check/initialization API tests **61 passed**。当前生成物为 **43 operations / 18 operations with examples / 37 exchanges / 55 media examples**；Python suite 输出 40 条 httpx per-request-cookie deprecation warnings，不影响测试通过。
- **边界：**API 测试使用受控 checker/SQLite 场景，不代表真实 Nacos、MySQL/PostgreSQL、部署授权码或多 worker 并发验收；样例仍只覆盖 18/43 operations，F6.1 不勾。

### 15.385 F6.1 系统连接、协议与审计 operation 样例（2026-10-10）

- **实现：**`readSystemConnections`、`readSystemProtocols`、`readSystemAudit` 增加正负 examples。连接快照保留未探测 Collector 的 `unknown/no-probe`；协议快照区分已协商 reporting v1 与尚未观测的 rule-config；审计样例包含 UTC 半开窗口、稳定分页与安全记录字段，并覆盖 view 角色拒绝。正负响应均经各自 Runtime Schema 和 OpenAPI response/error registry 校验。
- **验证：**`npm run test:http:focused -- 'CONSOLE-MACHINE'` **5 passed**；`dashboard-prototype`: `npm run check:fast` 通过。`sentinel-console`: OpenAPI route parity + system connections/protocols/audit API tests **37 passed**。OpenAPI 当前为 **43 operations / 21 operations with examples / 43 exchanges / 61 media examples**。
- **边界：**受控 Python API reader 不证明生产连接探测、真实 Collector 协商或生产审计存储；总 operation 样例覆盖 21/43，完整浏览器 E2E 保留最终阶段，F6.1 不勾。

### 15.386 F6.1 观测、实例与故障分析 operation 样例（2026-10-10）

- **实现：**`readFleet`、`readMetrics`、`readInstanceCatalog`、`readInstanceObservation`、`readObservationCatalog`、`readIncidentTimeline`、`readIncidentEvidence` 加入 operation-owned 正负 HTTP exchange，并进入同一 OpenAPI 生成链。正例覆盖未接入采集器时的显式 `unknown/not_integrated` 与空 coverage、观测选择目录、主机层级不支持时的 `null` 指标、空故障时间线、结构化资源压力证据；负例覆盖 metrics:view 拒绝、已退役实例 incarnation、事件不可见/不存在。时间窗、分页、scope 和 processEpoch 均按 wire DTO 保留；缺测不会被伪装成零值，证据不包含 traceback 或业务日志。
- **验证：**`dashboard-prototype`: `npm run contract:generate` 成功；`npm run test:http:focused -- 'CONSOLE-MACHINE'` **5 passed**；`npm run check:fast` 通过（typecheck、格式、lint、OpenAPI 一致性）。`sentinel-console`: `.venv/bin/pytest -q tests/test_console_openapi_route_parity.py tests/test_fleet_overview_api.py tests/test_instance_catalog_api.py tests/test_observation_catalog_api.py tests/test_incident_timeline_api.py` **57 passed**。生成物统计为 **43 operations / 28 operations with examples / 57 exchanges / 75 media examples**，状态仍为 `draft-partial`。
- **边界：**schema/OpenAPI 与受控 reader 测试不等于真实 Reporter/Collector、浏览器全流程或生产部署验收；仍有 15 个 operation 缺少正负 exchange，其他 wire 语义全量审计亦未收口，因此 F6.1 不勾。

### 15.387 F6.1 规则生命周期 operation 样例与领域不变量校验（2026-10-10）

- **实现：**规则绑定/快照、草稿、候选校验/差异、不可变版本、发布阶段、实例回执、激活计划、发布目标与异步命令核查的 15 个 operation 全部加入正负 exchange，并纳入统一 OpenAPI 生成链。样例明确基线 checksum、草稿 revision、validation ticket、发布写入/回读阶段、未知实例分母、future plan、Nacos 精确目标（不含凭证）、pending/rejected/原 requestKey completed/not-found 之间的关系。
- **验证：**`dashboard-prototype`: `npm run contract:generate`、`npm run check:fast` 通过，`npm run test:http:focused -- 'CONSOLE-MACHINE'` **6 passed**。测试除 43 operation 的 path/query/body/response/error/OpenAPI 样例逐个 Zod 校验外，另验证规则 snapshot、候选 validation/diff、发布阶段、receipt 总数与未知分母、计划时间和目标、异步 operation 结果与原命令绑定等领域不变量。`sentinel-console`: 本批相关 OpenAPI parity + 规则 binding/snapshot/draft/validation/diff/version/publication/plan/command/target API tests **112 passed**。当前 OpenAPI **43/43 operations with examples / 87 exchanges / 111 media examples**，仍为 `draft-partial`。
- **边界：**Python 测试使用受控 authority，Nacos/Consul 和 PostgreSQL/MySQL 未连接；样例 + 代码级领域检查仍不等于逐页错误/时间/分页/权限/幂等的人工审定、运行服务跨层 E2E 或发布签字。F6.1 继续未勾。

### 15.388 F6.1 Fleet 查询参数与作用域合同对齐（2026-10-10）

- **问题与修复：**Fleet 概览 OpenAPI 曾从共享观察上下文 schema 错误继承可选 `instanceId`、`resource` 及 `host/container/process` scope，但 Python 运行时只允许 fleet/application 粒度。前端 Fleet query schema 现排除实例/资源参数并把 scope 枚举限制为 `fleet/application`；Python allowlist 删除伪可选字段，未知参数仍以 `invalid_request` 拒绝；`appId` 与 scope 的组合仍由两端领域校验保证。Mock handler 继续通过相同 strict schema 拒绝未声明 query。
- **验证：**新增 parity 断言要求 observation、incident、audit、rule 查询端点的 OpenAPI query 名称集合严格等于 Python 路由 allowlist；Fleet API 负向测试分别覆盖 `instanceId` 与 `resource`。`sentinel-console`: `.venv/bin/pytest -q tests/test_console_openapi_route_parity.py tests/test_fleet_overview_api.py` **29 passed**。`dashboard-prototype`: `npm run contract:generate`、`npm run check:fast` 通过；`npm run test:http:focused -- 'CONSOLE-MACHINE'` **6 passed**；生成物仍是 **43 paths / draft-partial**。
- **边界：**此修复仅收敛 Fleet 查询语义，不代表其余 42 个 operation 已完成人工逐项语义审计；无真实 Python 部署联调或浏览器 E2E。F6.1 继续未勾。

### 15.389 F6.1 本人改密回执与 Python 当前会话策略对齐（2026-10-10）

- **问题与修复：**前端 `OwnPasswordReceiptSchema` / OpenAPI 曾接受 `retained` 与 `reauthenticate` 两个回值，但 Python `OwnPasswordDisposition` 仅实现 `reauthenticate`，并在同一事务中更新密码哈希、撤销该账号全部会话、写审计。当前 wire 收紧为唯一 `reauthenticate`；Port、workflow 与契约文案同步。未知/不支持回执继续按结果不确定处理且禁止重放。
- **验证：**新增 OpenAPI parity 断言要求 `sessionDisposition.const == reauthenticate`。`dashboard-prototype`: `npm run test:logic:focused -- 'PASSWORD-'` **8 passed**；`npm run test:http:focused -- 'PASSWORD-HTTP|AUTH-APP-OWNER'` **4 passed**；`npm run contract:generate` 与 `npm run check:fast` 通过。`sentinel-console`: `.venv/bin/pytest -q tests/test_console_openapi_route_parity.py tests/test_own_password.py` **30 passed**。
- **边界：**无 PostgreSQL/MySQL、多 worker 部署或真实页面→Python 服务验收；全量 E2E 继续留到最终阶段。F6.1 尚有其他 operation 的时间、权限、错误与幂等语义待审，不勾选。

### 15.390 F6.1 Incident 查询作用域与资源过滤对齐（2026-10-10）

- **问题与修复：**Incident query wire 原先复用了通用 observation context，允许 `host/container` scope 与 `resource` 参数；Python incident domain 实际仅接受 `fleet/application/process`，要求 scope 与 `appId/instanceId` 一致，并拒绝 resource。前端 timeline/evidence 请求与响应 schema 现限制为三种 scope、`resource: null`，请求参数不再声明 resource；前端 query validator 同步拒绝不一致身份组合。Python allowlist 从 timeline/evidence 查询中移除 resource，未知参数会在到达 authority 前按 `invalid_request` 拒绝；领域校验保留作纵深防御。
- **验证：**新增前端逻辑正反例覆盖 fleet/application/process 身份组合、host/container/resource 和不一致组合；`npm run test:logic:focused -- 'INCIDENT-SCOPE'` **1 passed**。新增 OpenAPI parity 断言检查两个 operation 的 query allowlist、无 resource 参数及 scope enum；`sentinel-console`: `.venv/bin/pytest -q tests/test_console_openapi_route_parity.py tests/test_incident_timeline_api.py` **33 passed**。`npm run contract:generate` 成功；`npm run check:fast`（typecheck、format、lint、contract check）通过；`git diff --check` 通过。
- **边界：**API 测试使用受控 ASGI authority，不代表生产服务联调；未连接数据库/配置中心，未运行浏览器或完整 E2E。F6.1 仍需完成其他 operation 的逐项语义审计，保持未勾选。

### 15.391 F6.1 实例目录搜索长度的 UTF-16 wire 语义对齐（2026-10-10）

- **问题与修复：**前端 `utf16BoundedString(200)` 和 JS 模型按 UTF-16 code units 限制 `search`，Python `InstanceCatalogQuery` 原先使用 `len(str)` 按 Unicode code points 计数，使 101 个 astral emoji（202 UTF-16 units）能通过 Python、却被前端拒绝。Python 领域模型现用显式 UTF-16 长度计算并仍在可信领域边界校验；100 个 emoji（200 units）有效，101 个无效。
- **验证：**前端实例目录逻辑正反例覆盖普通字符及 100/101 个 emoji，`npm run test:logic:focused -- 'INSTANCE-CATALOG'` **1 passed**。Python domain/API 增加相同边界与 authority 前拒绝测试；`.venv/bin/pytest -q tests/test_console_openapi_route_parity.py tests/test_incident_timeline_api.py tests/test_instance_catalog_api.py` **48 passed**。`dashboard-prototype`: `npm run check:fast` 通过；`git diff --check` 通过。
- **边界：**这是实例目录搜索字段边界语义的局部证明，不自动证明其他 identifier/text 字段的 Unicode 长度、真实数据库搜索排序或生产部署；这些仍需 F6.1 全面语义审计及后续真实联调，未运行浏览器 E2E。

### 15.392 F6.1 观察身份标识长度的 UTF-16 wire 语义对齐（2026-10-10）

- **问题与修复：**观察域共享的 `_is_identifier` 原先按 Python Unicode code point 数限制 200 字符，而前端 `OpaqueIdentifierSchema` 按 UTF-16 code units 限制 200。实例目录与实例观测中复用该 helper 的环境、应用、实例、资源、process epoch、metric source、annotation 等身份因此存在相同边界差异。现在 `_is_identifier` 统一通过该领域模块的 UTF-16 计数校验；边界为 100 个 astral emoji 有效、101 个拒绝。
- **验证：**新增 domain/API 正反例；`.venv/bin/pytest -q tests/test_console_openapi_route_parity.py tests/test_incident_timeline_api.py tests/test_instance_catalog_api.py` **49 passed**，涵盖超长 astral `environmentId` 在查询 authority 前以 `invalid_request` 拒绝。前端 `npm run test:logic:focused -- 'INSTANCE-CATALOG|INCIDENT-SCOPE'` **2 passed**；OpenAPI 声明仍由既有 `CONSOLE-MACHINE` 样例及 `check:fast` 校验，`git diff --check` 通过。
- **边界：**该变更修复 Python 观察域共享身份校验，不等于其他业务域所有字符串均完成 Unicode 审计，也不证明生产数据存储的比较/索引语义或真实服务部署；完整 E2E 留在最终阶段。

### 15.393 F6.1 实例详情查询 scope 与 Python InstanceLayer 对齐（2026-10-10）

- **问题与修复：**`readInstanceObservation` 前端请求/响应 schema 原复用五值通用 `ObservationScope`，会在 OpenAPI 中对外声明 `fleet/application` 可用；Python parser 构造 `InstanceLayer`，只接受 `host/container/process`。详情请求与回执 context，以及回执中嵌套 metrics query context，现均使用 feature-owned `INSTANCE_LAYER` 枚举；操作语义明确 fleet/application scope 对此端点无效。实例目录 scope 仍保持其独立的 fleet/application 合同。
- **验证：**Python OpenAPI route parity 新增 query scope 与响应中 nested metrics scope 的精确 enum 断言；`.venv/bin/pytest -q tests/test_console_openapi_route_parity.py tests/test_instance_catalog_api.py` **38 passed**。`dashboard-prototype`: `npm run contract:generate` 成功；`npm run test:http:focused -- 'INSTANCE-WIRE|CONSOLE-MACHINE'` **7 passed**，`npm run test:logic:focused -- 'INSTANCE-DETAIL'` **1 passed**；`npm run check:fast` 通过。
- **边界：**这是 OpenAPI/Runtime schema 与受控 ASGI 路由边界验证，不代表真实 Reporter/Collector 或生产观测数据可用；未运行浏览器 E2E 或连接真实服务，F6.1 继续未勾选。

### 15.394 F6.1 实例目录 scope 与过滤器同 Python 域合同对齐（2026-10-10）

- **问题与修复：**实例目录领域只允许 fleet/application scope，且要求 `instanceId/resource` 为 null；原前端查询 schema 继承通用 scope/过滤字段，Python allowlist 也错误接受这两个字段后才由 domain 拒绝。现请求 schema 与 OpenAPI 只声明 fleet/application、可选 appId 和目录过滤字段；响应 query context 将 instanceId/resource 限为 null。Python parser allowlist 直接拒绝 instanceId/resource，并构造固定 null identities；Mock adapter 同步移除无效字段分支。HTTP adapter 改为显式投影受支持参数，避免把通用 helper 生成的 `undefined` 键传给 strict object。
- **验证：**OpenAPI parity 覆盖 query allowlist、query scope、响应 context scope；Python `.venv/bin/pytest -q tests/test_console_openapi_route_parity.py tests/test_instance_catalog_api.py` **38 passed**，包含 instanceId/resource 在 authority 前拒绝。前端 `npm run test:http:focused -- 'INSTANCE|CONSOLE-MACHINE'` **12 passed**、`npm run test:logic:focused -- 'INSTANCE-CATALOG|INSTANCE-DETAIL'` **2 passed**、`npm run check:fast` 通过。首次运行的 focused HTTP test 确实捕获 strict schema 的 adapter undefined-key 回归，修正后整组通过。
- **边界：**mock/adapter 与受控 ASGI 契约测试不代表生产观测事实源部署可用；没有运行真实服务联调或浏览器 E2E，F6.1 仍有其他 operation 需要逐项审计。

### 15.395 F6.1 发布回执分页拒绝未知/重复查询参数（2026-10-10）

- **问题与修复：**前端 `PublicationReceiptParametersSchema` 是严格对象，只允许 `page` 与 `pageSize`；Python `_page_arguments` 原先只检查这两个字段的唯一性和范围，未拒绝额外 query 参数，导致两端对相同 HTTP 请求有不同接受结果。Python parser 现逐项读取 query，拒绝未知字段、重复字段、缺失字段及超出范围的分页值，保持唯一 query wire 与前端 schema 一致。
- **验证：**新增 API 负例覆盖未知 `resource` 参数和重复 `pageSize`；在 `components/sentinel/sentinel-console` 执行 `.venv/bin/pytest -q tests/test_rule_publications_api.py tests/test_pagination_wire_bounds.py tests/test_console_openapi_route_parity.py`，**72 passed**。
- **边界：**证明受控 ASGI HTTP 路由与前端 strict schema 的这项分页边界一致；不证明生产部署/持久层或浏览器 E2E。F6.1 仍未完成，继续审计其他 operation。

### 15.396 F6.1 账户 revision 与 Python BIGINT CAS 语义对齐（2026-10-10）

- **问题与修复：**Python 账户持久层以正 `BIGINT` revision 做条件更新，HTTP parser 要求规范十进制字符串且上限为 `9223372036854775807`；前端却把读写 revision 声明为普通 opaque identifier，账户 Mock 还生成 `revision-admin-1` 等生产端不会接受的值。现新增精确正 `BIGINT` 十进制 wire schema，保留字符串传输以避免 JS 精度损失；账户 Mock 从单调递增的十进制字符串生成 revision；账户 HTTP/工作流测试样例同步使用可实现的 wire 值。唯一 OpenAPI 生成链现输出相同边界 pattern。
- **验证：**前端 `npm run test:http:focused -- ACCOUNT` **11 passed**、`npm run test:logic:focused -- ACCOUNT` **19 passed**、`npm run check:fast` 通过（typecheck、Prettier、ESLint、OpenAPI contract check）；OpenAPI 生成 **43 paths / draft-partial**。Python `.venv/bin/pytest -q tests/test_account_commands_api.py tests/test_console_openapi_route_parity.py` **27 passed**；含最大合法 BIGINT 可达命令层、0/前导零/非数字/越界 revision 在执行前返回 `400 invalid_request`。
- **边界：**只收敛账户 revision 协议和 Mock 事实，不证明真实 SQL 数据库并发/事务、部署或浏览器 E2E；F6.1 仍有其他 operation 需逐项审计。

### 15.397 F6.1 UTC 时间戳合同边界双端验证（2026-10-10）

- **审计结论：**前端 `UtcInstantSchema`、Python `parse_utc_timestamp` / `utc_timestamp` 与生成的 Console OpenAPI 对绝对时间的 wire 约束一致：UTC `Z`、固定 3 位毫秒、年份 1970–9999、拒绝 offset/local 时间和非法日历日期。未发现本次审计范围内的实现差异。
- **补充验证：**前端 `HTTP-WIRE` 用例新增 1970 与 9999 两个边界、2000 闰年、2100 非闰年及非法日期检查，同时断言两端毫秒转换结果；Python `tests/test_utc_wire.py` 对 parser 与 serializer 增加相同年份端点和 Gregorian 闰年用例。`npm run test:http:focused -- HTTP-WIRE` **1 passed**；`npm run check:fast` 通过（typecheck、format、lint、43-path OpenAPI contract check）；`.venv/bin/pytest -q tests/test_utc_wire.py` **17 passed**。
- **边界：**这是时间戳格式与转换边界的前后端合同证据，不验证生产时钟同步、数据库精度/时区配置、真实服务部署或浏览器 E2E。F6.1 仍需审计其余 operation，保持未勾选。

### 15.398 F6.1 实时指标查询选择编码与拒绝语义对齐（2026-10-10）

- **审计结论：**前端以唯一 `MetricId[]` 建模并以逗号列表编码 GET `metrics`；Python 保持请求次序，在 `MetricQuery` 域校验中拒绝未知值、重复项和空项。逗号编码长度上限与所有可选 `MetricId` 的最大编码相同；无效 selection 不会访问下游 authority。未发现本次审计范围内的 wire 或错误语义差异。
- **验证：**React HTTP focused 新增 `METRICS-QUERY` 覆盖空数组、重复 metric、未知 metric、含空分项，并断言 transport 调用数为 0：**1 passed**。Python `test_metrics_query_rejects_invalid_selection_before_authority` 扩充相同四类输入，均断言 `400 invalid_request` 且 reader 调用数为 0：**1 passed**。既有有效查询响应断言保持 selection 顺序；`npm run check:fast` 通过，OpenAPI **43 paths / draft-partial**。
- **边界：**这证明 metrics query 的 selection 输入边界与拒绝前置条件，不证明 Collector 数据质量、真实权限部署、实时窗口容量或浏览器 E2E；F6.1 仍需继续审计其他 operation，保持未勾选。

### 15.399 F6.1 非有限指标数值的 Python 拒绝路径收敛（2026-10-10）

- **问题与修复：**前端指标语义校验以 JavaScript 有限 `Number` 为边界；Python 指标 reading/sample 对普通 `float('inf')` 会抛领域 `ValueError`，但对 `10**1000` 这类超出 binary64 有限范围的 Python `int`，`math.isfinite` 会先抛 `OverflowError`，绕过稳定的领域拒绝语义。新增共享的私有有限数校验，将该转换溢出判为非有限；reading 与 sample/series 路径现在一致抛 `ValueError`。
- **验证：**Python `tests/test_instance_catalog_api.py` **17 passed**，新增 reading 与 sample 两条超大整数拒绝断言；React `OBS-METRIC` **1 passed**，补充 `Infinity` 指标拒绝；`npm run check:fast` 通过（typecheck、format、lint、OpenAPI 43-path 检查）。
- **边界：**修复的是 Python 数值验证异常分类并与客户端有限数模型对齐；未定义业务指标的精度/整数安全范围，不证明 Collector 实际采集值、生产存储/部署或浏览器 E2E。F6.1 仍需继续审计其他 operation，保持未勾选。

### 15.400 F6.1 指标 selection 上限从指标注册表派生（2026-10-10）

- **问题与修复：**实时指标 query parser 的最大逗号编码长度原先硬编码为 `89`，而 React 从 metric ID 枚举计算；当前两端恰好一致，但 Python 新增/删除 metric 时存在接受边界静默漂移风险。现改为从 domain `METRIC_UNITS` 计算逗号编码长度，保留单一指标注册表事实源。
- **验证：**Python `test_metrics_query_bound_is_derived_from_all_registered_metric_ids` 用全部已注册 metric ID 验证最长合法 selection 能解析，附加字符的越界 selection 被拒；`tests/test_instance_catalog_api.py` **18 passed**。React `METRICS-QUERY` 与 `OBS-METRIC` 各 **1 passed**；`npm run check:fast` 通过，OpenAPI 仍为 **43 paths / draft-partial**。
- **边界：**证明 Python 解析边界会随指标注册表演进而派生，不证明未来新增指标本身已获 UI/Collector/业务评审或部署；F6.1 其他 operation 审计仍开放。

### 15.401 F6.1 Console wire 数值共用有限 binary64 边界（2026-10-10）

- **问题与修复：**把 metrics 中发现的超大 Python `int` `math.isfinite()` 溢出横向追查到 Fleet 连接延迟和 Incident fact；这些类型同样投影为 JavaScript `Number`，旧逻辑会将 `OverflowError` 泄漏出稳定领域拒绝路径。将拒绝 bool/非数值/超出有限 JSON binary64 范围的共用检查放入 `domain.observation_limits.is_finite_json_number`，metrics reading/sample/series、Fleet latency、Incident fact 和 RuleSnapshot 数值校验统一复用；删除了各处重复的有限数判断。
- **验证：**Python instance catalog、fleet overview、incident timeline、rule-set snapshot API/domain suite **46 passed**，其中新增 Fleet latency 与 Incident pressure 超大整数拒绝回归；前端 `OBS-METRIC` **1 passed**、`FLEET` **6 passed**。未改前端运行时代码；客户端现有 Zod number/显式有限值校验仍是消费者边界。
- **边界：**这收敛 JSON 有限数值转换异常和领域错误类型，不定义各业务指标的精度/安全整数策略，也不证明生产 Collector 数据、持久层或部署；未运行完整浏览器 E2E，F6.1 仍未完成。

### 15.402 F6.1 标识符空白与 Unicode scalar 语义前后端对齐（2026-10-10）

- **问题与修复：**实际复现了 JavaScript `\S` 与 Python `str.strip()` 的接受集合不同：前端接受独占 U+001C/U+0085、Python 拒绝；Python 接受独占 U+FEFF、前端拒绝。两端现使用显式稳定 blank 字符集（包含上述值），非空白内容判断不再依赖运行时 Unicode whitespace API。另发现前端有界字符串 schema 接受孤立 UTF-16 surrogate，而 Python UTF-16 编码会抛 `UnicodeEncodeError`；前端所有 `utf16BoundedString` 值现拒绝孤立 surrogate，Python `read_json_object` 对任意嵌套 JSON string/key 递归 fail-closed，观察标识符模型也安全拒绝孤立 surrogate。合法 emoji 与含 FEFF 的非空白标识符继续通过。
- **验证：**前端 `HTTP-WIRE` **1 passed**，覆盖 U+001C/U+0085/U+FEFF/全角空格、混合有效字符、孤立 surrogate 和合法 emoji；Python instance identifier、未知/重复 query 边界与 account command JSON body 测试共 **24 passed**，非法输入返回 `400` 且不执行写入。`npm run contract:generate` 更新唯一产物，`npm run check:fast` 通过：typecheck、Prettier、ESLint、43-path OpenAPI contract check。
- **边界：**这对齐 Console 有界字符串/观察标识符及 JSON 请求入口的 Unicode 可表示性，不替代每个业务字段的长度/字符策略审计，不证明数据库 collation/编码部署或完整浏览器/真实后端 E2E；F6.1 仍需继续审计。

### 15.403 F6.1 Incident opaque cursor 空白与 Unicode scalar 判定对齐（2026-10-10）

- **问题与修复：**Incident cursor 原先由 Python `str.strip()` 与前端 `String.trim()` 判定空值，U+001C/U+0085/U+FEFF 的接受集合不一致；前端纯模型还用局部 `.trim()` 检查。现将 Console 明确的非空白 wire 字符集暴露为共享前端契约，Incident 查询输入/响应 schema 与纯模型复用；Python Incident domain 复用目录领域的同一字符策略，不再按运行时默认 whitespace 判空。另将 Unicode scalar 检查用于 cursor 纯模型与 Python domain，防止孤立 surrogate 被前端模型接受或使 Python UTF-16 编码抛出非领域异常；生成的 OpenAPI 同步反映 cursor pattern。
- **验证：**前端 `F4.13 incident filters` **2 passed**、`INCIDENT-INPUT` **1 passed**（空白/surrogate cursor 在 HTTP dispatch 前拒绝）；Python `tests/test_incident_timeline_api.py` **13 passed**（非法查询返回 400，领域直接构造稳定拒绝），OpenAPI pagination/cursor 约束 **1 passed**，包含 U+001C/U+0085/U+FEFF/全角空格拒绝与 FEFF 混合有效 cursor 接受；`npm run contract:generate` 后 `npm run check:fast` 通过（43 paths / draft-partial）。
- **边界：**证明 incident cursor 的前后端空值/长度基础合同一致，不代表 opaque cursor 的签名、过期、排序键编码或持久化实现已完成；其他分页 token/receipt 仍需逐项确认，完整浏览器 E2E 与真实 Console 联调仍留后续。

### 15.404 F6.1 UTC 时间 wire 在观测、审计与规则计划入口对齐（2026-10-10）

- **核对与修复：**比较 React `UtcInstantSchema`、Python 通用观测时间 parser、system audit 私有 parser 与 rule schedule mutation parser；均要求 `Z`、恰好三位毫秒、合法公历日期及 1970–9999 UTC 年份，输出统一规范化为 UTC 毫秒。源代码和生成 OpenAPI 未发现偏差；补充 system audit 负例以直接锁定缺失精度、offset、过量精度与下界年份均被拒绝，并强化 rule schedule parser 对应负例，避免后续放宽时静默漂移。
- **验证：**前端 `HTTP-WIRE` **1 passed**；Python `tests/test_utc_wire.py`、`tests/test_system_audit_api.py`、`tests/test_rule_mutation_parsing.py` 合计 **25 passed**；前端 `npm run check:fast` 通过，OpenAPI 校验 **43 paths / draft-partial**。
- **边界：**本次证明的是客户端 schema / HTTP 输入 parser / 规则变更 parser / 生成合同的 UTC 时间格式一致；不证明外部 Reporter 时间源准确、数据库时区配置或生产环境数据质量，F6.1 其他 operation 审计仍开放。

### 15.405 F6.1 系统观察与配置源标识符语义归一（2026-10-10）

- **问题与修复：**继续逐项审计时发现 `systemReadGuards.identifier()` 的 JavaScript `.trim()` 与 Python `str.strip()` 对 U+001C/U+0085/U+FEFF 的接受集合不同；系统观察 DTO 和配置源 name schema 也只校验非空长度，可能接受纯空白或孤立 surrogate。前端新增无 Zod 依赖的 `core/api/protocol/wireString.ts` 作为纯字符串原语，model 通过它验证，Zod schema 复用同一 Unicode scalar / blank policy；系统标识字段改用 `OpaqueIdentifierSchema`，审计 actor filter 明确允许空串或有效标识。Python 新增 `domain.wire_strings`，把稳定空白字符、Unicode scalar 和 UTF-16 长度语义从实例目录收敛为 Console domain 共享原语，系统连接、协议、审计、配置源及来源命令/检查解析统一调用；凭证值和其他非标识文本未被错误套用标识符规则。
- **验证：**前端系统观察 logic **8 passed**、系统观察/来源注册 HTTP **7 passed**；Python 系统审计、连接、协议、来源读取/命令与 OpenAPI 路由契约 **54 passed**。`npm run contract:generate` 更新 OpenAPI 后，`npm run check:fast` 通过：typecheck、Prettier、ESLint、43-path OpenAPI contract check。
- **边界：**覆盖系统读取标识、配置源名称、审计 actor 输入/回执以及相关 Python domain/API 拒绝边界；不代表所有业务文本字段的 Unicode 策略均已审定，也不验证数据库编码/collation、真实配置中心/关系库或完整 E2E。F6.1 仍需完成所有 operation 的逐项语义审计。

### 15.406 F6.1 配置源检查 UTF-16 长度与非空语义一致（2026-10-10）

- **问题与修复：**来源检查 API 的 Python parser 原用码点数 `len()` 校验 endpoint、namespace/datacenter 与认证字段，而前端 Zod `utf16BoundedString` 使用 UTF-16 code unit；补充非 ASCII astral 字符就能使 Python 放过前端拒绝的超限请求。用户名/凭证引用还存在 FE `.min(1)` 接受纯 blank、Python `.strip()` 拒绝的反向漂移。Console `wire_strings` 新增 scalar-safe bounded-text 判断；source parser 对所有有界字段按 UTF-16 计数，对 username/reference 使用明确的共享非空白规则，密码/token 保留“非空但可含空白”的秘密语义；注册来源 domain 的文本/endpoint 也拒绝孤立 surrogate。FE 对 username/reference schema 显式采用同一 nonblank pattern。
- **验证：**前端 `SOURCE-CHECK-WIRE` 覆盖 Nacos/Consul endpoint、namespace/datacenter、reference、username、password、ACL token 的 astral UTF-16 超限和空白用户名/引用，**1 passed** 且所有拒绝都在 HTTP dispatch 前；Python 同一来源检查路由的对应负例返回 `400 invalid_request` 且 checker 零调用。系统观察/配置源相关 Python API、domain 与 OpenAPI parity **61 passed**；OpenAPI 重新生成后前端 `npm run check:fast` 通过，43 paths / draft-partial。
- **边界：**证明 source check 的字段长度和用户名/引用 blank policy 与前端 wire schema 一致；不验证真实 Nacos/Consul 连通性、秘密解析或持久化，也不代表其他功能字段都已完成逐项 Unicode 审计；F6.1 继续开放。

### 15.407 F6.1 bootstrap 配置源检查复用统一 wire 字符串边界（2026-10-10）

- **问题与修复：**F6.1.406 收敛的 admin 来源检查之外，首次初始化的 `/system/bootstrap/source-check` 仍有独立 parser，继续用 Python 码点 `len()` 与 `.strip()` 判断，导致相同配置源表单在 setup 阶段和系统管理阶段采用不同合同。现改为复用 `domain.wire_strings`：endpoint/location/密码/ACL token 按 Unicode scalar-safe UTF-16 长度验证，用户名/凭证引用使用相同非空白标识符策略；密码/token 仍只要求非空，不误拒绝有意提供的空白字符。删除重复 endpoint 上限常量。
- **验证：**新增受控 bootstrap ASGI 测试覆盖 Nacos/Consul endpoint、namespace/datacenter、引用、用户名、密码、ACL token 的 astral 字符超限，纯空白 username/reference 在 checker 执行前返回 `400 invalid_request`；直接 parser 用例拒绝孤立 surrogate。`uv run --extra test pytest -q tests/test_bootstrap_source_check_api.py tests/test_registered_source_check_api.py` **17 passed**。
- **边界：**只证明首次初始化与已登记来源检查复用相同的输入边界，不证明凭证解析/KMS、真实 Nacos/Consul 连通性、数据库或浏览器 E2E；F6.1 全量 operation 审计仍未完成。

### 15.408 F6.1 Fleet query 搜索边界与 strict 参数投影对齐（2026-10-10）

- **问题与修复：**逐字段复核 Fleet endpoint 时发现 Python `FleetQuery` 对 `search` 使用码点 `len()`，与 React `utf16BoundedString(200)` 对 astral 字符按 UTF-16 code unit 的边界不同；Python 现复用 scalar-safe `is_bounded_wire_text`。同一条真实 HTTP 适配路径还将包含 `instanceId/resource: undefined` 的通用观察参数对象直接交给 Fleet strict schema，导致符合业务类型的 fleet query 在 dispatch 前始终被拒绝；现由 endpoint 显式投影其自身支持的 `environmentId/appId/scope/from/to` 字段。
- **验证：**前端 observation HTTP 测试新增 101 个 astral 字符及孤立 surrogate 均在 transport dispatch 前拒绝，并显式校验 Fleet query/query-parameter schema；FLEET/METRIC 聚焦 HTTP **13/13 passed**，`npm run check:fast` 通过。Python `tests/test_fleet_overview_api.py` 增加领域和 ASGI 搜索负例；与 bootstrap/source-check/registered-source/OpenAPI parity 相关 suite 合计 **75 passed**。
- **边界：**证明 Fleet 搜索字符串边界、endpoint request projection 与受控 Python authority/React HTTP adapter 一致；不验证真实 Reporter/Collector 查询数据或浏览器 E2E，F6.1 仍需继续审计其他 wire 语义。

### 15.409 F6.1 Observation Catalog ID/name 的 Unicode wire 约束对齐（2026-10-10）

- **问题与修复：**观察环境/应用目录响应复用前端 `OpaqueIdentifierSchema` 和 `utf16BoundedString(200)`，Python domain 却用码点 `len()`、默认 `.strip()`，会接受前端拒绝的 astral 超长标识及孤立 surrogate。现复用 `domain.wire_strings`：ID 使用非空白 bounded identifier，名称使用 scalar-safe UTF-16 bounded text 且保留前端允许纯空白名称的语义。
- **验证：**domain 测试新增 101 个 astral 字符超限、环境/应用 ID/名称孤立 surrogate 拒绝；`tests/test_observation_catalog_api.py`、`tests/test_console_openapi_route_parity.py`、`tests/test_fleet_overview_api.py` 合计 **37 passed**。
- **边界：**证明 catalog Python 值对象约束与当前前端 schema/OpenAPI 长度规则一致；不验证生产目录来源的数据库编码/collation 或浏览器 E2E，F6.1 继续开放。

### 15.410 F6.1 Bootstrap operator code 格式与部署 authority 对齐（2026-10-10）

- **问题与修复：**React authorization schema 允许 16–1024 位任意 Unicode 文本，HTTP adapter 也按 Python `len/strip` 接受；但部署 authority 的配置格式实际是 32–1024 位 URL-safe ASCII，导致格式不合法的内容通过 transport/authority 后才以认证拒绝返回，且此前正向 OpenAPI 样例本身短于配置格式。Python 将唯一 operator-code 语法放入 `application.authorize_bootstrap`，API parser 与文件 authority 共用；React schema 收紧为同一 ASCII 字符集/长度，Operation semantic rule 与正负样例同步为形状有效的 synthetic code，重新生成唯一 OpenAPI。
- **验证：**React `BOOTSTRAP|CONSOLE-MACHINE` **11 passed**，其中新用例验证短码、astral、边界空白、BOM、超长输入均在 transport dispatch 前拒绝；`npm run contract:generate` 与 `npm run check:fast` 通过，OpenAPI **43 paths / draft-partial**。Python bootstrap authorize API、文件 authority 与 OpenAPI parity **39 passed**，格式负例均在 authority exchange 前返回 `400 invalid_request`。
- **边界：**证明格式约束与部署 authority 实现一致，不验证授权码实际部署、限流/跨进程配置或真实浏览器 E2E；F6.1 其余 operation 语义审计仍开放。

### 15.411 F6.1 首次初始化数据库检查与初始化提交共用输入边界（2026-10-10）

- **问题与修复：**`/system/bootstrap/database-check` 的 React schema 与 Python candidate parser 对 host 边界空白、Unicode scalar 与 UTF-16 长度处理不一致。React host 现拒绝跨语言 blank 字符集中的首尾空白；Python 复用 `domain.wire_strings` 的 scalar-safe UTF-16 有界文本/标识符及边界空白策略。database 继续只要求非空 bounded text，密码继续只要求非空 bounded secret，不额外 trim 用户输入。
- **验证：**新增前端 HTTP 负例覆盖超长 astral host/database/username/password、尾随 U+001C、孤立 surrogate 和 U+0085 空白用户名，均在 transport dispatch 前拒绝；`npm run test:http:focused -- 'BOOTSTRAP-DATABASE-WIRE|CONSOLE-MACHINE'` **7 passed**。Python ASGI 检查接口覆盖相同负例及 JSON 转义孤立 surrogate，并确认 checker 未被调用；初始化提交接口再覆盖 host/username/password 负例并确认 initializer 未被调用。`uv run --extra test pytest -q tests/test_bootstrap_database_check_api.py tests/test_bootstrap_initialization_api.py tests/test_console_openapi_route_parity.py` **39 passed**。`npm run contract:generate` 生成 **43 paths / draft-partial**，`npm run check:fast` 通过（typecheck、format、lint、contract check）。
- **边界：**这是受控 checker/ASGI 与前端 transport/OpenAPI 的合同验证，不证明真实 PostgreSQL/MySQL 连接、部署初始化事务或浏览器 E2E；F6.1 仍需完成其他 operation 的逐项语义审计。

### 15.412 F6.1 登录用户名空白语义与 AccountUsername 统一（2026-10-10）

- **问题与修复：**React `UsernameSchema` 按 ECMAScript `\s` 判断非空，允许账号名以 U+0085 / U+001C 结尾；Python login API 曾额外使用 Python 默认 `str.strip()`，会改变这类账号名并造成用户无法登录或查到另一个规范化用户名。HTTP adapter 现复用 `AccountUsername` 的 UTF-16 长度、Unicode scalar、ECMAScript trim 与规范化规则，并将值对象产出的 display value 传给登录用例；未增加第二套用户名策略。
- **验证：**前端 identity wire 正例覆盖 `operator\u0085`、`operator\u001c`，负例覆盖全空白 NBSP/BOM；`npm run test:http:focused -- 'IDENTITY-WIRE|IDENTITY-HTTP'` **5 passed**，`npm run check:fast` 通过。Python SQLite-backed login API 测试创建尾随 U+0085/U+001C 的账号并真实登录成功；`uv run --extra test pytest -q tests/test_login_api.py tests/test_account_username.py` **18 passed**。
- **边界：**使用本地隔离 SQLite 与受控 HTTP ASGI，不代表生产 DB collation 或浏览器完整认证 E2E；最终 E2E 仍保留在所有开发任务完成后的验收阶段。

### 15.413 F6.1 规则生命周期文本与时区空白策略统一（2026-10-10）

- **问题与修复：**规则 workflow 与 React wire schema 原先只限制名称/原因 `min(1)`，会让普通空格、U+0085、U+001C、U+FEFF 通过客户端；Python mutation parser 和激活计划 domain 用 `str.strip()` 又与共享跨运行时 blank set 不完全一致。现在冻结版本名、发布原因、取消原因、计划时区及其响应字段均使用 React `NON_BLANK_WIRE_CONTENT`；workflow 在提交前应用同一 helper；Python mutation parser、RuleSetVersion 与 RuleActivationPlan 共用 `domain.wire_strings` 的有界文本/非空内容语义。保留 `ZoneInfo` 对 IANA 时区的语义校验，不更改自由文本 note。
- **验证：**前端 schema 覆盖 4 类 blank 输入对 freeze/publish/cancel/create-plan/version/plan response 的拒绝；逻辑测试验证 blank version name 与 publish reason 在 command dispatch 前拒绝，`npm run test:http:focused -- 'RULE-WIRE'` **1 passed**、`npm run test:logic:focused -- 'RULE-DRAFT-WIRE|DEPLOY-WIRE'` **2 passed**。`npm run contract:generate` 生成 **43 paths / draft-partial**，`npm run check:fast` 通过。Python mutation parser、version/activation-plan domain、bindings 与 OpenAPI parity suite **48 passed**。
- **边界：**测试覆盖共享合同与受控 API/domain，不连接真实配置中心/数据库，也未运行最终浏览器 E2E；F6.1 其余 operation 审计仍继续。

### 15.414 F6.1 Sentinel 规则候选必填文本空白语义统一（2026-10-10）

- **问题与修复：**React `RuleValueSchema` 对 resource、limitApp、refResource、classType 仅做最小长度校验，参数例外 object 甚至允许空串；Python `rule_snapshots` domain 则把同类必填字段按 Python `str.strip()` 判定非空，并用 UTF-16 encode 计长（孤立 surrogate 会抛底层异常）。现由前端复用 `NON_BLANK_WIRE_CONTENT` 定义规则文本 schema，Python domain 复用 scalar-safe `is_bounded_wire_text` 与同一 blank policy，保持已有业务不变量、不再各自解释空白集合。
- **验证：**前端覆盖空格、U+0085、U+001C、U+FEFF 对规则 resource 与参数例外 object 的拒绝，HTTP focused **2 passed**；Python 候选验证 API 对同类输入均在 profile validator 执行前拒绝；候选验证、快照、规则 mutation/version/plan/binding、OpenAPI parity 合并套件 **65 passed**。schema 变更后生成 **43 paths / draft-partial** OpenAPI，`npm run check:fast` 通过（typecheck、format、lint、contract check）。
- **边界：**这里证明候选 wire/domain 的空白边界，不等于 Sentinel Profile/provider 的完整字段兼容性、Nacos/Consul 或持久数据库验收，也未运行最终 E2E；F6.1 继续开放。

### 15.415 F6.1 规则绑定标识与显示文本空白语义统一（2026-10-10）

- **问题与修复：**前端规则绑定响应 schema 使用共享 `OpaqueIdentifierSchema`，并把 source label/location 当作必填文本；Python `RuleBinding` 却以 `str.strip()` 和本地 `utf-16-le` 编码判断非空/长度，导致 U+FEFF 这类共享合同认定为空白的值可被 Python domain 接受。现将 Python 标识符、文本和 location 边界收敛到 `domain.wire_strings` 的 scalar-safe UTF-16 / blank helper；前端 sourceLabel/location 明确使用同一跨运行时 blank 集合。
- **验证：**前端对 id/environment/app/profile/source、sourceLabel、location 覆盖普通空格、U+0085、U+001C、U+FEFF 拒绝，HTTP focused **1 passed**；Python domain 与 ASGI query 对同类空白作拒绝，bindings/candidate/OpenAPI parity suite **39 passed**。合同重新生成 **43 paths / draft-partial**，`npm run check:fast` 通过。
- **边界：**此项证明规则绑定必填文本的空白边界，不覆盖安全 location 的前端脱敏校验、publication target 的完整长度/控制字符边界或真实服务；F6.1 仍开放，未运行最终 E2E。

### 15.416 F6.1 配置中心发布目标字段长度与字符约束对齐（2026-10-10）

- **问题与修复：**Python mutation parser/domain 将 Nacos namespace/group/dataId 与 Consul key 按最多 512 个 UTF-16 单元处理，并拒绝空白、C0/DEL 控制符及非 Unicode scalar；React 两处发布目标 schema 却复用最多 200 单元的通用标识符。现区分 source/binding opaque ID（200）与 provider target text（512），在规则 mutation 与 target snapshot 响应 schema 中统一要求 bounded scalar text、非空白，并拒绝控制符；Python target domain 复用 `wire_strings` 的 scalar-safe UTF-16/blank 语义，同时保留既有 provider 路径约束。
- **验证：**React 覆盖 512 BMP/256 astral 单元可接受、513 单元拒绝、U+FEFF 与 target/source/binding 控制符拒绝，规则 HTTP focused **4 passed**。Python 覆盖 domain 与 mutation parser 的相同 512/513 UTF-16 边界、astral 字符及非法 blank/control/surrogate，publication target、mutation、candidate、binding、OpenAPI parity suite **54 passed**。重新生成 **43 paths / draft-partial** OpenAPI，`npm run check:fast` 通过。
- **边界：**此项覆盖规则发布目标的 Console wire/parser/domain，不证明目标连接探测、真实 Nacos/Consul 写入或数据库读取部署；F6.1 与 B0.3 仍未完成，未运行最终 E2E。

### 15.417 F6.1 规则校验回执与 Python domain 不变量对齐（2026-10-10）

- **问题与修复：**Python `RuleValidationIssue` 限制 path 为固定安全字段路径、recordIndex 小于 1000；`RuleCandidateValidationReceipt` 要求 `isPublishable` 当且仅当 issues 为空。React `RuleValidationReportSchema` 原先只验证 path 是任意非空文本、recordIndex 非负、各字段形状正确，因而会接受 Python domain 明确拒绝的响应。现 React response schema 同步固定 path pattern、0–999 的索引界限和 publishability/issues 一致性。
- **验证：**React 覆盖合法最大 recordIndex、非法 path、1000 索引、发布状态与 issues 不一致及合法空 issues 回执，HTTP focused **1 passed**；Python candidate validation API/domain 与 OpenAPI parity tests **31 passed**。合同重新生成 **43 paths / draft-partial**，`npm run check:fast`（typecheck、format、lint、contract check）通过。
- **边界：**这是候选校验回执的运行时协议检查，不替代 Profile 对 Sentinel 字段的完整语义验收、真实 Python 服务部署或最终浏览器 E2E；F6.1 仍开放。

### 15.418 F6.1 发布实例回执分页不变量与 Python domain 对齐（2026-10-10）

- **问题与修复：**Python `RulePublicationReceiptPage` 已要求已知 `expected` 等于完整回执 `total`、五种状态计数之和等于 `total`、当前页条目不越界且实例 ID 不重复，并要求当前页各状态数量不超过全量状态计数；React `PublicationReceiptPageSchema` 之前只校验 `expected` 与 `inventorySource` 同时已知/未知，导致不一致分页能通过 HTTP 响应解析。现 schema 补齐相同分页与计数不变量；规则 API operation semantic rules 同步写明这些约束，重新生成唯一 OpenAPI。选中发布的 binding/version/checksum/incarnation 语义仍由 workflow/domain context 校验，不把上下文约束重复塞进无上下文 wire parser。
- **验证：**React `RULE-RECEIPT-PAGE-WIRE|RULE-RECEIPTS` **3 passed**，覆盖合法未知分母页、expected mismatch、状态总计不等、页面越界、重复实例、页内状态超出全量计数，以及 publication/binding/page/pageSize/version/checksum 与请求上下文不匹配；Python `tests/test_rule_publications_api.py tests/test_console_openapi_route_parity.py` **39 passed**。OpenAPI 生成 **43 paths / draft-partial**，`npm run check:fast`（typecheck、format、lint、contract check）通过。
- **边界：**Python domain 原本已有不变量，本次未改其业务实现；没有连接真实 Agent/Collector、配置中心或生产数据库，也未运行最终浏览器 E2E。F6.1 仍整体未完成。

### 15.419 F4.20 首启秘密清理与 Console 路由定向复核（2026-10-10）

- **复核：**重新检查 `InitializationPage`、`useSetupFlow` 与 mounted 生命周期探针。权威完成/闭窗时页面在 layout effect 中调用既有 `clearSensitive()`；其会撤销连接检查、清除数据库用户名/密码、规则源凭证和管理员密码/确认，并保留非敏感配置。`tests/e2e/initialization.e2e.test.mjs` 已包含“外部闭窗→重新开放→返回各步骤检查秘密为空”的 mounted 断言，但按用户决定，最终浏览器 E2E 目前不运行。
- **定向验证：**前端 `npm run test:logic:focused -- 'SETUP-LIFECYCLE|SETUP-SECRET'` **3 passed**；`node --test --test-name-pattern='F4.20-SETUP-LIFECYCLE|F4.20-SETUP-PAGE-RENDER' tests/i18n/catalog.test.mjs` **1 passed**。Python Console bootstrap、数据库/规则源检查、初始化 API、初始化事务和持久化集成测试 **47 passed**（`uv run --extra test pytest -q tests/test_bootstrap_api.py tests/test_bootstrap_database_check_api.py tests/test_bootstrap_source_check_api.py tests/test_bootstrap_initialization_api.py tests/test_bootstrap_initialization_transaction.py tests/test_bootstrap_persistence_integration.py`）。未连接真实 MySQL/PostgreSQL、Nacos/Consul 或部署服务。
- **状态边界：**该证据确认前端逻辑/渲染切片和 Python 隔离 API/SQLite 路径当前通过；不证明 mounted React layout-effect 的浏览器时序、跨进程部署或真实依赖联调。F4.20 仍不勾，等待最终内置浏览器 E2E 与获准的真实服务验收；完整 E2E 继续留到所有实现完成后。

### 15.420 F6.1 发布实例回执 incarnation 不变量双端收敛（2026-10-10）

- **差异与修复：**Python `RulePublicationReceipt` 已拒绝“无 `process_epoch` 却声称已加载事实”以及不完整/跨 incarnation 的 `applied` 回执；React 领域 validator 原先会拒绝这类数据，但 HTTP 入口使用的 `PublicationReceiptSchema` 没有同等条件校验。现 wire schema 在网络解析边界即执行相同字段间不变量，避免 invalid response 越过 HTTP DTO parser；`ruleSetContract.ts` 的 `readRulePublicationReceipts` semantic rules 同步说明无 incarnation 的 unknown 约束及 applied 时间/目标要求，OpenAPI 由唯一生成器更新。
- **验证：**`npm run test:http:focused -- 'RULE-RECEIPT-WIRE|RULE-RECEIPT-PAGE-WIRE|RULE-RECEIPTS'` **4 passed**，覆盖合法 applied/unknown 与缺失 epoch、错误状态、伪造 loaded version/checksum/时间及 page/population/context 负例；Python `tests/test_rule_publications_api.py tests/test_console_openapi_route_parity.py` **39 passed**。`npm run contract:generate` 生成并 `npm run check:fast`（typecheck、format、lint、contract check）验证 **43 paths / draft-partial**。
- **边界：**没有连接真实 Agent/Collector、配置中心或生产数据库，也未运行最终浏览器 E2E；这里只关闭了一个回执 wire 差异，F6.1 逐项合同审计与 F6.2 联调仍未完成。

### 15.421 F6.1 系统审计 actor 缺省权限语义双端对齐（2026-10-10）

- **差异与修复：**Python `AuditRecord` 只允许 `system-initialize`、`plan-activate`、`plan-restore` 缺少账号 actor；React 纯模型与 HTTP wire schema 此前接受任何 action 的 `actorId: null`。现在由 system audit 模型提供唯一 `validAuditActor` 规则，wire schema 与页面数据校验共用；OpenAPI `readSystemAudit` 语义规则明确了这三个例外动作。
- **验证：**前端模型测试确认三类系统动作允许 null、账号动作拒绝 null；HTTP 测试确认非法 `account-create + actorId:null` 被拒绝，前述三类系统动作仍被接收。`npm run test:logic:focused -- SYSTEM-AUDIT` **5 passed**，`npm run test:http:focused -- SYSTEM-AUDIT` **4 passed**，`npm run check:fast` 通过（typecheck、format、lint、43 paths OpenAPI contract check）。Python `uv run --extra test pytest -q tests/test_system_audit_api.py` **8 passed**，新增 domain 正反例保护。
- **边界：**没有连接生产数据库或部署 Console，也未运行最终浏览器 E2E；此项关闭一个系统审计响应不变量，F6.1 逐页 request/response/权限与错误矩阵审计仍未完成。

### 15.422 F6.1 账号目录 Unicode 标量边界与 React wire schema 对齐（2026-10-10）

- **差异与修复：**账号目录 Python parser 曾自行调用严格 UTF-16 编码计算 `search` / account path ID 长度；孤立 surrogate 会抛 `UnicodeEncodeError`，而 React `utf16BoundedString` 将非 Unicode scalar 输入稳定判为无效。现在 parser 复用 `domain.wire_strings.is_bounded_wire_text` 与 `is_bounded_wire_identifier`：搜索仍允许空值与空白内容，但要求 scalar-safe 且不超过 200 UTF-16 units；path ID 与前端 opaque identifier 共用非空白、scalar-safe、有界语义。移除重复长度算法并将 200 上限命名化。
- **验证：**Python `uv run --extra test pytest -q tests/test_account_directory_api.py tests/test_console_openapi_route_parity.py` **28 passed**；新增孤立 surrogate 搜索拒绝且不抛编码异常、detail path ID 在授权前拒绝用例。React `npm run test:http:focused -- ACCOUNT` **11 passed**，`npm run check:fast` 通过（typecheck、format、lint、43 paths OpenAPI contract check）。
- **边界：**surrogate 负例在 Python parser/route 边界直接构造，真实 URL 编码器可能会先替换非法 UTF-16；未连接真实身份数据库或部署 Console，也未运行最终浏览器 E2E。F6.1 其余 operation 审计仍开放。

### 15.423 F4.32 本人改密密码长度上限本地与 wire 边界对齐（2026-10-10）

- **差异与修复：**Python 改密 API 与 React write-only secret wire schema 都限制密码不超过 1024 个 UTF-16 单元，但本人改密表单只校验最小长度；超长输入会被送入 adapter 后才由 schema 拒绝，页面无法给出明确本地策略反馈。现将通用 write-only secret 上限命名为共享模型常量，identity 密码策略复用该上限；当前密码和新密码超限均返回结构化 `password.tooLong`，新密码三语提示从同一策略参数展示 12–1024 的长度范围。
- **验证：**`npm run test:logic:focused -- PASSWORD-VALIDATE` **1 passed**，覆盖当前/新密码超限拒绝及 512 个 astral 符号（1024 UTF-16 单元）边界接受；`npm run test:http:focused -- OWN-PASSWORD-INPUT` **1 passed**，确认 schema 拒绝超长新密码且 transport 调用数为 0；i18n catalog 与 identity producer **2 passed**；`npm run check:fast` 通过（typecheck、format、lint、43 paths OpenAPI contract check）。
- **边界：**当前 Astryx `TextInput` 公共 props 未暴露原生 `maxLength`，因此不依赖非公开 prop 或 DOM 注入；用户可输入超长值，但会在提交时得到本地错误，HTTP schema 仍作为无请求兜底。未运行 mounted 浏览器或最终 E2E；F4.31–F4.33 与 B0.2 仍未完成。

### 15.424 F5.2 动态翻译调用清单随身份页面迁移对齐（2026-10-10）

- **差异与修复：**`LoginSurface` 已承载登录表单校验文案，但动态调用清单仍把 `t(issue.key, issue.params)` 归属到旧 `LoginEntryPage`，使精确 callsite→producer manifest 与当前源码不一致。现将 manifest 更新为 `LoginSurface` 实际调用位置；对应 identity runtime suite 会从 `validateLoginCredentials` 产生问题并在真实 i18next 三语目录中渲染，不将 mock key 清单当作 producer。
- **验证：**`npm run test:i18n-tools` **36/36 passed**，包括动态调用清单精确集合比较和 producer runtime suites；`npm run i18n:check` 通过，三语各 **1,183** keys、静态可枚举 **1,028**，当前保留 **22** 个动态调用由类型门禁和 runtime suite 映射覆盖。
- **边界：**这只收敛代码迁移后过期的 manifest 路径，不是页面级三语交互验收；语言切换下日期/时区/DST 与持草稿页面 URL 保持仍未全部在 IAB 实测，因此 F5.2 不勾。未运行完整 E2E。

### 15.425 F6.1 账号目录记录、响应与查询上下文不变量（2026-10-10）

- **差异与修复：**React HTTP adapter 会拒绝格式错误的账号记录、与请求页码/页大小不符、违反状态筛选、分页数量矛盾或重复 ID 的列表，以及 ID 与请求路径不符的详情；Python 路由此前直接序列化目录 Port 结果，可能把不一致数据成功返回。现账号记录值对象验证标识符/用户名、角色/状态、布尔标志、正 SQL BIGINT revision 与内置/最后管理员关系；分页值对象验证页范围、页大小、JavaScript 安全整数 total、与 total 一致的精确页长和唯一有界 ID。SQL reader 将筛选 total、当前页和 active-admin 计数放在单条 CTE 查询中，避免 PostgreSQL READ COMMITTED 下多语句读到不同快照；`ReadAccountDirectory` 再校验结果对应原查询/目标 ID，并将畸形 authority 结果统一转为不泄露细节的 `service_unavailable`。
- **验证：**Python `uv run --extra test pytest -q tests/test_account_directory_api.py tests/test_account_directory_persistence.py tests/test_account_commands_api.py tests/test_console_openapi_route_parity.py` **43 passed**；`compileall` 通过。新增记录/分页不变量正反例、错误页码/筛选/目标 fail-closed HTTP 覆盖，以及 SQL event 断言查询 total、页内容和管理员事实仅由一条 SELECT/CTE 返回。
- **边界：**未连接生产身份数据库或部署 Console，也未运行最终浏览器 E2E；此项只收敛账号目录 query/response 上下文合同，F6.1 其他 operation 审计和最终 E2E 仍开放。项目未配置 Ruff，尝试 `uv run ruff` 因本地缺少该工具未执行；测试通过，格式/类型门禁需由仓库现有统一命令继续核验。

### 15.426 F6.1 系统审计 authority query 回显校验（2026-10-10）

- **差异与修复：**React `validAuditPage` 校验响应内的 query 与本次请求完全一致；Python `SystemAuditPage` 虽验证了其内部记录符合携带的 query，但 `ReadSystemAudit` 此前未核对该 query 是否为调用方请求，因而一个错误 reader 可把另一筛选条件的审计页作为 200 返回。现在 use case 验证 page 类型与 query identity，不匹配时转换为现有 `service_unavailable` 稳定错误，API 不序列化另一查询的审计记录。
- **验证：**Python `uv run --extra test pytest -q tests/test_system_audit_api.py tests/test_console_openapi_route_parity.py` **31 passed**；新增请求 `plan-activate`、authority 返回 `account-create` 页的负例，确认 503 且正文不包含错配审计 action；`compileall` 与 `git diff --check` 通过。
- **边界：**未连接生产审计数据库或部署 Console，也未运行最终浏览器 E2E；本项只关闭系统审计读取的 query-response 绑定，F6.1 其他 operation 审计仍开放。

### 15.427 F6.1 配置源健康探测按 source revision 精确关联（2026-10-10）

- **差异与修复：**系统连接投影的设计要求探测事实绑定当前注册源 revision。聚合器现按 `(source_id, revision)` 精确关联，忽略过期 revision、对重复当前探测 fail-closed。继续审计发现持久化 probe reader 虽匹配调用方快照 revision，却没有在同一 SQL 语句确认该 revision 仍是当前登记版本；若登记在两个读取之间更新，旧快照可能仍拼接旧探测。现 probe 查询通过单条 JOIN 同时要求 probe revision 等于数据库当前 source revision，再与调用方快照核对；旧配置的健康事实不再被返回。
- **验证：**先新增确定性 SQLite 回归并观察到旧实现失败（更新 source 后仍返回旧 revision probe），修复后测试通过。`uv run --extra test pytest -q tests/test_registered_source_store.py tests/test_registered_source_connections_reader.py tests/test_system_connections_api.py tests/test_registered_source_store_api_integration.py` **21 passed**；覆盖旧/当前 revision 关联、登记变更后旧探测被拒绝、重复当前 revision fail-closed，以及系统连接 API/持久化回归。
- **边界：**这是隔离的 Python/SQLite 测试，不连接生产 Nacos/Consul 或数据库，也未运行最终浏览器 E2E；只关闭探测事实 revision 关联语义，F6.1 其他 operation 审计仍开放。

### 15.428 F6.1 系统观察与配置源 Reader 返回类型 fail-closed（2026-10-10）

- **差异与修复：**React 的 system-protocols、system-connections、observation-catalog 与注册配置源 HTTP mapper 均拒绝畸形快照；对应 Python 四个 read use case 此前直接透传 Reader 结果，若宿主 Reader 违反 Port 返回类型（例如返回 `None`），API 序列化会抛未分类异常。现由各自用例在 authority 边界校验对应快照类型，并映射到既有 authority-unavailable 错误；API 返回稳定 `503 service_unavailable`，不泄漏内部细节。领域快照仍由原 domain value object 负责字段不变量，没有新增模式或通用校验层。
- **验证：**`uv run --extra test pytest -q tests/test_system_protocols_api.py tests/test_system_connections_api.py tests/test_observation_catalog_api.py tests/test_registered_sources_api.py tests/test_console_openapi_route_parity.py` **46 passed**；`uv run python -m compileall -q src/atlas_richie/sentinel_console` 与 `git diff --check` 通过。新增四个 API 回归确认错误 authority 快照均 fail-closed。
- **边界：**本项验证 Python authority/HTTP 边界与 OpenAPI 路由映射，不连接真实部署 reader、数据库或配置中心，也未运行最终浏览器 E2E；F6.1 的逐 operation 协议审计仍未完成。

### 15.429 F6.1 协议快照 OpenAPI 上限与领域边界一致（2026-10-10）

- **差异与修复：**Python `SystemProtocolsSnapshot` 最多允许 `ProtocolBoundary` 枚举对应的 3 种边界，React `validSystemProtocols` 也要求边界已知且唯一；但 wire schema/OpenAPI 将 `items` 的 `maxItems` 写为通用集合上限 1000，使公开 schema 接受领域不可能接受的重复/超量候选。现 React schema 上限从 `PROTOCOL_BOUNDARY_IDS.length` 派生，避免重复魔法数字；支持版本列表上限也改由命名常量提供。重新生成 OpenAPI。Python 合同测试同时锁定边界数量、支持版本数量以及 `kind`/`compatibility` 枚举与 Python domain 一致。
- **验证：**先新增 Python 合同负例，确认旧 artifact 为 1000 而领域上限为 3；更新 schema/artifact 后 `npm run check:fast` 通过（含 typecheck、format、lint、contract:check），`npm run test:http:focused -- SYSTEM-PROTOCOLS` **1 passed**，Python OpenAPI 合同测试 **2 passed**。
- **边界：**此项收敛一个运行时 schema/OpenAPI 与 Python domain 的数量上限，不代表全部协议语义审计已结束，也未运行最终浏览器 E2E。

### 15.430 F6.1 系统连接枚举跨语言一致性门禁（2026-10-10）

- **审计结论：**系统连接的类别、状态、provider、能力与脱敏失败原因目前在 Python domain 和 React wire schema 中一致；之前 OpenAPI route parity 测试只检查路径/方法和错误矩阵，没有把这组关键读模型枚举与 Python domain 逐项绑定，后续单边改名可能出现 API 文档与服务器合法值分叉。新增合同测试从生成 OpenAPI 提取五组枚举，并逐组与 Python StrEnum/Provider enum 比较；未发现当前值差异，也不改变运行时行为。
- **验证：**`uv run --extra test pytest -q tests/test_console_openapi_route_parity.py -k 'system_protocol_snapshot_limit or system_connection_enums'` **2 passed**；`uv run python -m compileall -q src/atlas_richie/sentinel_console` 通过。React 生成合同此前由 §15.429 的 `npm run check:fast` 验证。
- **边界：**这是静态跨语言 schema/domain 合同门禁，不验证生产 Collector/Nacos/Consul 的事实采集，也未运行最终浏览器 E2E；F6.1 仍保持开放。

### 15.431 F6.1 观测目录名称空白与集合关系双端对齐（2026-10-10）

- **差异与修复：**React `validObservationCatalog` 已拒绝空白显示名、重复环境 ID、重复 `(environmentId, applicationId)` 及引用不存在环境的应用；Python domain 此前只检查非空/长度，Snapshot 不验证唯一性和归属关系。且前端使用 JavaScript `.trim()`、Python 仅 `bool(value)`，对 U+001C/U+0085 等双方约定的 wire blank 字符语义不同。现在前后端 name 校验复用对应的跨运行时 `hasNonBlankWireContent` / `has_non_blank_wire_content`；Python `ObservationCatalogSnapshot` 增加环境唯一、应用 scoped identity 唯一和环境引用完整性约束，同时保留不同环境可使用相同应用 ID 的既有语义。
- **验证：**新增负例先分别证明旧 Python 接受 wire blank 名称/不一致集合、旧 React 接受夹在普通空格间的 U+001C/U+0085 名称；修复后 `uv run --extra test pytest -q tests/test_observation_catalog_api.py tests/test_console_openapi_route_parity.py` **31 passed**，`npm run check:fast` 通过，`npm run test:http:focused -- CATALOG-WIRE` **1 passed**。
- **边界：**这是 Python domain/HTTP 与 React HTTP mapper 的合同测试，不连接生产 inventory/Collector 或数据库，也未运行最终浏览器 E2E；F6.1 其余 operation 审计及 F6.2 HTTP 切换仍开放。

### 15.432 F6.1 配置源 endpoint URL 语法跨层一致（2026-10-10）

- **差异与修复：**Python `RegisteredConfigurationSource` 原先用正则校验 endpoint，可接受无主机、非法端口、无效 IPv4、malformed IPvFuture、空 DNS label 和百分号编码主机；React 的 WHATWG URL 校验会拒绝其中多项。现新增 domain-owned `is_safe_source_endpoint` 与唯一 UTF-16 长度常量，校验 HTTP(S)、端口解析、IPv4/IPv6、IDNA DNS label 与 wire 禁止项；registered-source value object、首次 source-check 和登记 source-check parser 共用该规则。React 在共享纯协议函数中实施同一支持子集，并由表单规则及 Zod 请求/响应 schema 共用，避免 UI 与 HTTP mapper 分叉。仅允许规范 IPv4 文本，拒绝浏览器会静默规范化的八进制/十六进制/缩写主机；保留规范 IPv4、IPv6 和 IDN。SSRF、DNS pin、TLS 与目的地址策略仍属于部署/connector policy，不由此语法校验代替。
- **验证：**Python domain 负例先在宽松实现下失败；修复后配置源/OpenAPI 定向套件先 **54 passed**，加入 IDNA target regression 后合并的 checker/API suite **75 passed**，`compileall` 与 `uv lock --check --offline` 通过；invalid host 不会到达 source checker。React `SOURCE-REGISTRY`、`SOURCE-CHECK-WIRE`、`SOURCE-ENDPOINT` 各 **1 passed**；`npm run check:fast` 通过（typecheck、format、lint、OpenAPI contract）。
- **边界：**测试验证 domain、API parser 与 React HTTP mapper 的语法合同，不连接真实配置中心、数据库或部署网络；不证明 SSRF 防护/真实 DNS/TLS 行为，也未运行最终浏览器 E2E。F6.1 仍开放。

### 15.433 B0.1 配置源探测目标与 HTTP client 的 IDNA 主机名一致（2026-10-10）

- **问题与修复：**源探测 allowlist 原先使用 Python 标准库的 IDNA2003 转换；例如 `faß.de` 被规范为 `fass.de`，但 aiohttp/yarl 的 URL host 使用非转译 UTS #46 结果 `xn--fa-hia.de`。Pinned resolver 会因两者不同拒绝请求（fail-closed，但合法 IDN 配置无法探测）。现 Console 将 `idna>=3.7,<4.0` 声明为直接依赖，allowlist 规则与请求 endpoint host 统一采用 `idna.encode(..., uts46=True, transitional=False)` 后再匹配和 DNS pin；端点仍须通过显式 host/network/port allowlist。
- **验证：**先添加 `faß.de` 回归并在旧实现观察到 `'fass.de' != 'xn--fa-hia.de'`；修复后 `tests/test_registered_source_checker.py` 与配置源 API/OpenAPI suite 合计 **75 passed**，`compileall`、`uv lock --check --offline` 通过。目标策略结果与 yarl `URL.raw_host` 相同；不代表真实 DNS/配置中心联通。
- **边界：**只修正 DNS allowlist 与 aiohttp/yarl 之间的规范化一致性，不放宽网络 allowlist、不访问外网、不验证真实 TLS/配置中心；生产 SSRF/部署验收仍未完成。

### 15.434 F6.1 配置源 URL 校验不得静默规范化原始输入（2026-10-10）

- **差异与修复：**React `ConfigurationEndpointSchema` 原使用 Zod 4 的 `.url()`；实测它会把 URL 首尾空白静默规范化掉，导致共享 refine 只看到清理后的字符串，表单纯校验和 Python domain 对同一 wire 值给出不同结论。现移除会改写解析结果的 `.url()`，保留非变换的 HTTP(S) 语法正则、共享完整 endpoint 校验器和 `format: uri` OpenAPI 元数据；端点原文有空白时在本地拒绝，不做隐式修正。
- **验证：**先扩充 `SOURCE-ENDPOINT` 纯模型负例，旧代码对前导空白输入返回合法（测试失败）；再增加 `SOURCE-CHECK-WIRE` 检查前导/尾随/主机内空白均在传输前拒绝，并断言合法 Unicode IDN endpoint 在 wire schema parse 后逐字保留。修复后 React `SOURCE-ENDPOINT` **1 passed**、`SOURCE-CHECK-WIRE` **1 passed**、OpenAPI `contract:generate` / `contract:check` 通过且仍输出 `format: uri`，`npm run check:fast` 通过；Python 配置源 checker/API/OpenAPI 定向套件 **75 passed**。
- **边界：**这是输入保真与前后端 URL 语法合同修复，不验证生产配置中心、真实网络、TLS 或部署 SSRF 策略；F6.1 仍开放，完整 E2E 留最终阶段。

### 15.435 F6.1 配置源 URL Unicode 空白与 IPv6 字面量跨语言对齐（2026-10-10）

- **差异与修复：**Python `str.isspace()` 不包含 U+FEFF，而 React `\s` 与 Python 对 U+0085/U+001C 等字符的定义也并不一致，导致同一 endpoint 的拒绝结果存在运行时差异。现在 Python 规则按 `isspace() + U+FEFF`，React 按 Unicode `White_Space` 属性加 Python 额外的 U+001C–U+001F 与 U+FEFF，保持显式同一集合。另发现 React 把 bracketed IPv6 字面量交给 IPv4 数值主机规范化比较，错误拒绝 `::ffff:192.0.2.1`；现在只对非 bracketed hostname 执行 WHATWG IPv4 规范化检测，IPv6 仍由 URL parser 校验。
- **验证：**先添加 Python U+FEFF negative regression，旧 domain validator 未抛错；React 聚焦用例覆盖 U+FEFF/U+0085/U+001C 拒绝和 IPv4-mapped IPv6 接受/wire 原文保留。修复后 React `SOURCE-ENDPOINT` **1 passed**、`SOURCE-CHECK-WIRE` **1 passed**、`npm run check:fast` 通过（OpenAPI 43 paths verified）；Python 配置源 checker/API/OpenAPI 定向套件 **75 passed**。
- **边界：**这是 URL 输入字符与 IP 字面量语法的一致性修复；不验证 DNS pin、网络 allowlist、真实 IPv6 连接、TLS 或生产配置中心。F6.1 仍开放，完整 E2E 留最终阶段。

### 15.436 F6.1 规则数值 wire 类型与 JavaScript 精度边界对齐（2026-10-10）

- **差异与修复：**React 规则 DTO 把 `warmUpPeriodSec`、`timeWindow`、`maxThread`、`durationInSec` 等后端整数语义字段声明成普通有限数值，因而接受分数；Python 规则 domain 会拒绝。多个 Python domain 还各自重复定义 JavaScript 安全整数上限，而规则值没有统一限制。现新增 domain-owned `wire_numbers` 单一事实源，集中定义 `MAX_SAFE_JSON_INTEGER` 与安全 JSON 数值/整数校验；规则 domain 所有数值均要求有限且绝对值不超过该上限，整数值必须为精确 Python int。React 规则 schema 区分 safe integer 与有界 number，OpenAPI 对整数投影 `type: integer` 和精度范围。
- **验证：**新增 `RULE-VALUE-WIRE` 负例证明旧 schema 接受 warm-up 分数；修复后 `RULE-VALUE-WIRE` **1 passed**，React `npm run check:fast` 通过且 OpenAPI 43 paths 已重生成核验。Python 新增大于 safe-integer 的规则阈值拒绝用例，规则快照/候选/变更、binding、publication、instance catalog、system audit 定向套件 **73 passed**，`compileall` 通过。
- **边界：**该修复锁定规则数值 JSON 的跨语言精度/整数表示，不替代规则字段的完整业务语义验证，也未连接真实配置中心或运行最终浏览器 E2E；F6.1 仍开放。

### 15.437 F4.20 外部闭窗秘密清理最终验收用例扩展（2026-10-10，待最终 E2E）

- **缺口：**现有 `SETUP-LIFECYCLE` mounted 用例覆盖外部关闭/重新开放后管理员密码和数据库用户名清空，但该页面路径没有携带配置源凭证，因而不能证明 Nacos 用户名/密码也在同一生命周期清空。
- **变更：**扩展 `tests/e2e/initialization.e2e.test.mjs` 的最终验收场景：先在已挂载的初始化页面填入合成 Nacos 账号/密码，再模拟外部关闭并重新开放 setup，回到来源步骤断言两字段为空，随后继续检查管理员密码、数据库用户名为空，并检查页面文本及浏览器 storage 不含合成凭证。
- **验证状态：**新增 E2E 脚本经 `node --check tests/e2e/initialization.e2e.test.mjs` 通过；当前初始化秘密清理 logic 定向用例 **3 passed**，`npm run check:fast` 通过（typecheck、项目格式门禁、lint、43 paths contract check）。项目 `format:check` 不包含 `tests/e2e/*.mjs`；单独对该既有压缩风格文件运行 Prettier 会提示格式差异，本轮未重排整文件。没有运行 CDP 浏览器或完整 E2E；新增 mounted Nacos 凭证断言尚未执行，最终验收须确认其可达且通过。
- **边界：**合成数据，不连接真实配置中心/数据库，不证明 JavaScript 引擎物理擦除字符串。F4.20 仍未关闭。

### 15.438 F4.21 多标签初始化完成后的前台身份重验合同（2026-10-10，逻辑测试）

- **缺口：**F4.21 的多标签页面行为此前主要有内置浏览器手测记录；前后台事件 helper 的既有测试只验证可见性门控和 listener 清理，没有直接证明另一标签完成初始化后，当前 setup 标签返回前台会采用最新 bootstrap 并将访问事实更新为匿名。
- **验证：**新增逻辑测试先装载已授权的未初始化事实，再将服务端事实切换为 initialized；隐藏态触发 focus/visibilitychange 不读 bootstrap，可见态 focus 后重新读取 bootstrap 与 session，最终快照为 `resolved/anonymous`，并确认卸载时两个 listener 均移除。`npm run test:logic:focused -- 'F4\\.21|F2 foreground observer|F2 explicit bootstrap'` **3 passed**。
- **边界：**这是 workflow + 前台事件适配器的逻辑合同，不模拟真实浏览器焦点/visibility 时序，也不代替初始化成功后真实 Python 持久化、跨标签 mounted 页面路由重定向或最终 E2E；F4.21 仍未关闭。

### 15.439 F4.22 登录工作流与正式页面状态定向复核（2026-10-10）

- **验证：**`npm run test:logic:focused -- 'F4[.]22'` **5/5 passed**；`node --test --test-name-pattern='F4.22-LOGIN-PAGE-RENDER' tests/i18n/catalog.test.mjs` **1/1 passed**。覆盖已知拒绝与未知写入的区分、冷却 metadata 上限/保留、实际 `LoginEntryPage` 对安全错误状态的三语渲染。
- **边界：**仅为定向 workflow 与 SSR 渲染复核；不执行浏览器键盘/计时器/焦点/导航行为，不连接 Python Console。完整 mounted 和真实后端链路继续留在全部实现完成后的最终验收；F4.22 保持未勾。

### 15.440 B0.1 配置源只读探测实现状态更正（2026-10-10）

- **源码核对：**Nacos 3.x 与 Consul 的 `RegisteredSourceChecker`、SSRF 有界目标策略、固定 DNS 解析结果的 HTTP transport 和 `compose_provider_registered_source_checker()` 已实现；首次启动组合可用显式部署目标规则创建 checker，并将同一只读能力接到 bootstrap source-check。配置源探测不会写规则，规则发布/回读仍归 B0.3。
- **验证：**`uv run --extra test pytest -q tests/test_registered_source_checker.py tests/test_first_run_deployment_configuration.py tests/test_first_run_http_persistence_integration.py -k 'source or registered or first_run'` **29 passed**。
- **状态更正与边界：**B0.1 原摘要中“配置源 checker 未完成”已过时，当前代码与本地兼容端点测试证明该能力已实现；这不证明真实 Nacos/Consul、生产 DNS/TLS/network policy、部署 Secret resolver 或 PG/MySQL 运行验收。B0.1 因生产应用装配/权威数据源与真实服务边界仍保持未勾。

### 15.441 B0.2 最后管理员并发保护边界复核（2026-10-10）

- **源码核对：**`SqlAlchemyAccountCommandStore.execute_command()` 在账号鉴权和读取目标账号之前，于同一写事务内锁定唯一 `ConsoleGuardRecord` 行；所有账号 create/status/role 命令共享此 guard，因此 PostgreSQL/MySQL 行锁语义会串行化最后管理员检查与修改。现有实现未发现“仅锁各自账号行”的并发缺陷，不做无依据的 SQL 改写。
- **验证：**`uv run --extra test pytest -q tests/test_account_commands.py` **6 passed**，覆盖 SQLite/ASGI 账号命令基础与最后管理员顺序保护。
- **边界：**SQLite 不实现 PostgreSQL/MySQL 相同的 `SELECT ... FOR UPDATE` 行锁语义；此结果不能证明两个数据库的真实并发竞争与隔离级别。B0.2 仍需在受控 PostgreSQL/MySQL 环境执行并发最后管理员验收后才能关闭。

### 15.442 B0.2 PostgreSQL 迁移与最后管理员并发验收（2026-10-10）

- **缺陷与修复：**隔离 PostgreSQL 16 首次迁移发现 Alembic 默认 `alembic_version.version_num` 为 `VARCHAR(32)`，而 `0017_scheduled_rule_publication_origin` 超过 32 字符，导致 migration 0017 完成后 Alembic 更新版本号失败。migration 0017 现先在 PostgreSQL/MySQL 将版本列扩为 `VARCHAR(128)`，再记录该 revision；不会改写既有 revision identity。MySQL 8.4.11 首次迁移还发现 `console_guard.singleton_id` 主键隐式成为 `AUTO_INCREMENT`，与 singleton check constraint 冲突；初始 migration 与 SQLAlchemy mapping 现均显式声明 `autoincrement=False`。
- **验收：**新增显式 opt-in 的 PostgreSQL/MySQL integration tests，仅接受 loopback/受控测试主机和 `sentinel_console_test_*` 数据库名。一次性 PostgreSQL 16 与 MySQL 8.4.11 容器均从空库执行全量 migration 并重复升级；两者都用 DB trigger 延迟管理员角色更新，制造两个并发自降权事务竞争，结果是一笔完成、一笔以 `last_admin` 拒绝，最终恰好保留一个活动管理员。MySQL 另验证 128 字符版本列与 singleton 非自增列。PostgreSQL migration/concurrency **1 passed**；MySQL migration/schema/concurrency **2 passed**；SQLite persistence/account/migration 回归 **13 passed, 3 skipped**；`compileall` 与 `git diff --check` 通过。所有临时容器均使用无持久卷和 loopback 端口，验收结束已删除。
- **边界：**这是隔离 PostgreSQL/MySQL migration 与并发事务证据，不是现有运行数据库或生产部署验收；首次初始化完整生命周期、多 worker、反向代理与 React→Python E2E 仍未验证。B0.2 继续未勾。

### 15.443 B0.2 PostgreSQL/MySQL 首次初始化竞争验收（2026-10-10）

- **验收实现：**新增 `sentinel-console/tests/bootstrap_database_acceptance_support.py`，通过真实 `SqlAlchemyBootstrapInitializationTransaction` 对同一隔离数据库并发提交两次首次初始化；临时 DB trigger 延迟获胜事务提交 guard，要求恰好一笔 `completed`、一笔 `setup-closed`，持久化状态恰好一名 built-in admin 与一个 registered source、两份幂等 receipt/audit，并检查管理员、配置源、数据库密码均未以明文进入所检查的 account/source/receipt/audit 记录。仅清理本次唯一 username/request key 对应数据及临时 trigger。
- **验证：**PostgreSQL 16 隔离容器验收 **2 passed**（首次初始化竞争 + migration/repeat-upgrade/最后管理员并发）；MySQL 8.4.11 隔离容器验收 **3 passed**（首次初始化竞争 + migration/schema/最后管理员并发）。定向 Console regression **25 passed, 5 skipped**；跳过项仅为未提供显式隔离数据库 URL 时的 opt-in PG/MySQL 用例。所有真实数据库均为无持久卷、loopback 端口的一次性容器并在测试退出时移除。
- **修正：**首次断言误将审计 `request_id` 视为另一个随机 ID；源码实际把原幂等 `request_key` 写入审计。以数据库记录为准修正测试后，两种方言均通过，未修改业务事务实现。
- **边界：**此证据证明 PostgreSQL/MySQL 目标库事务对并发首次初始化只允许一个 winner，并覆盖被检查记录的凭证不泄漏；不证明跨存储 coordinator 崩溃恢复、正式数据库迁移运维、部署 Secret 投递、TLS/ingress/多 worker 或 React→Python 浏览器链路。B0.2 保持未勾，完整 E2E 仍留最终节点。

### 15.444 B0.2 首次初始化幂等重试与 operator 隔离（2026-10-10）

- **验收：**扩展 PG/MySQL opt-in 套件：两个分别构造的 SQL adapter 对同一 operator、request key、canonical input 并发请求，返回相同 `completed` receipt；新构造的 adapter 仍可读回/重放该持久回执，数据库仅有一条 operation/audit、一个 built-in admin/source；同 key 不同 input 必须返回 `BootstrapInitializationIdempotencyConflict`；另一个当前有效 operator 使用原 key 必须 `BootstrapInitializationForbidden`。每次测试用唯一 username/request key，trigger 与精确范围行在 `finally` 清理。这里证明 adapter 重建，不声称独立 OS worker/process 验收。
- **验证：**PostgreSQL 16 disposable suite **3 passed**；MySQL 8.4.11 disposable suite **4 passed**。B0.2 聚焦回归 **25 passed, 7 skipped**（7 个仅在显式设置隔离 PG/MySQL URL 时运行的用例）；`compileall`、88 列检查与 `git diff --check` 通过。MySQL 首轮失败仅为新建测试 trigger 名超过 MySQL 64 字符限制，缩短夹具标识符后真实数据库重跑通过，未改业务实现。
- **边界：**这覆盖目标数据库内 receipt 去重与 actor/input 绑定，不代表跨存储 coordinator 在多 worker 丢响应/进程崩溃后的恢复、实际 installer secret 注入、部署拓扑或浏览器→Python 流程。B0.2 未完成，最终完整 E2E 未执行。

### 15.445 B0.2 PostgreSQL/MySQL SQL 身份 HTTP 链路验收（2026-10-10）

- **验收：**扩展 PG/MySQL opt-in suite，通过真实 `build_sql_identity_app` 与 ASGI 请求验证持久管理员登录、`/auth/me` 会话身份读取、本人改密、旧 session 撤销、旧密码拒绝、新密码登录及对应审计。随后直接检查数据库：密码以 Argon2id hash 存储，新 hash 只匹配新密码；session/CSRF 仅保存 hash；旧 session 已撤销；审计 action/outcome 正确；所检查的 account/session/audit projection 不含测试密码、session/CSRF 原值。测试只写入唯一 synthetic account，并在 `finally` 删除精确 account/session/audit/login-attempt 行及复位专用空库 guard。
- **验证：**一次性 PostgreSQL 16 全套 **4 passed**，MySQL 8.4.11 全套 **5 passed**；身份/初始化/账号焦点回归 **34 passed**。Python `compileall`、源码 88 列检查、`git diff --check` 均通过。MySQL 首轮失败因就绪探测命中官方镜像临时初始化实例（`port: 0`）后实例关闭；改为确认容器映射的 TCP 3306 可连接后完整重跑通过，属于验收启动夹具修正。
- **边界：**这是本地隔离容器中 SQL-backed ASGI identity path 证据，不等于真实浏览器对接、生产 TLS/ingress、installer secret delivery、多 worker 部署或全量 setup coordinator 跨存储故障恢复。B0.2 继续未勾；完整 E2E 仍按计划留到全部开发完成后。

### 15.446 B0.2 PostgreSQL/MySQL 授权首启 ASGI 路径验收（2026-10-10）

- **验收：**新增 `assert_first_run_http_persists_on_real_database()`，以真实 `build_first_run_sql_identity_app` 走完整 ASGI 路径：未初始化 bootstrap → operator authorize → 完整初始化提交 → 持久 receipt 回读 → bootstrap initialized/closed → 合法输入重提被拒绝。PostgreSQL/MySQL 实际保存首个 built-in admin、Argon2id password hash、加密后的 Consul 凭证及初始化记录；runtime locator / operator authority 文件不含数据库密码或 operator code 原文。
- **验证：**PostgreSQL 16 disposable suite **5 passed**；MySQL 8.4.11 disposable suite **6 passed**；login/password/identity/bootstrap 焦点回归 **34 passed**。`compileall` 和本次 Python 文件 88 列门禁通过。无浏览器、真实配置中心或持久卷参与。
- **边界：**为了只接触 loopback 一次性容器，测试替换了 bootstrap engine factory 的网络连接创建，但仍运行真实 SQL dialect、Alembic、首启 coordinator/事务、runtime locator 文件加密和 setup-window authority；因此不证明生产 DNS pin/TLS 或部署 secret injection。最终 React→Python browser E2E 仍未运行，B0.2 继续未勾。

### 15.447 B0.2 首启后 runtime locator 重启装载与 ASGI 释放（2026-10-10）

- **验收补强：**在 §15.446 的授权首次初始化之后，从同一部署文件路径重建完整 first-run ASGI app；其 `RuntimeDatabaseEngineProvider` 从加密 locator 重读目标/revision，lifespan startup 对真实 disposable PostgreSQL/MySQL 执行幂等 migration，再通过 bootstrap read API 读回 initialized guard；shutdown 必须且只释放 runtime engine 一次。复用现有 provider/lifecycle 所有权，不新增 GoF 模式、公共 API 或生产配置分支。
- **验证：**PostgreSQL 16 disposable acceptance **5 passed**；MySQL 8.4 disposable acceptance **6 passed**；runtime-provider + SQLite 首启聚焦回归 **7 passed**；Python 源码编译、88 列检查和 `git diff --check` 通过。验收先发现 MySQL 临时容器需要 `log_bin_trust_function_creators` 才允许低权限测试用户建并发 trigger；随后 restart app 测试又发现测试 coordinator 也需映射到 disposable URL。新容器加测试参数、补同一 loopback 映射后全套通过；未改产品配置。Ruff 未安装，未声称 Ruff 检查通过。
- **边界：**runtime/provider 与 restart-time coordinator 的 engine factory 均指向 loopback disposable DB URL，因此证明 locator 解密/读取、ASGI 重启启动、真实方言 migration/readiness、API 回读与资源释放，但不证明生产 DNS pin、PostgreSQL `verify-full`、MySQL TLS identity、安装器 Secret 投递、Ingress/多 worker 或 React→Python E2E。没有使用现有数据库或配置中心；B0.2 仍未勾，完整 E2E 留在全部实现后的最终验收。

### 15.448 F6.1 OpenAPI 产物与 Python 路由合同定向复核（2026-10-10）

- **验证：**在 `dashboard-prototype` 执行 `npm run contract:check`，生成物与唯一运行时合同一致，共 **43 paths**，状态仍明确为 `draft-partial`；`npm run test:http:focused -- 'CONSOLE-MACHINE'` **6 passed**，覆盖 43 个 operation 正/负 wire examples、运行时 Zod DTO、OpenAPI 投影、规则状态不变量、权限合同和 UTF-16 边界；随后执行 `uv run --project ../sentinel-console pytest -q ../sentinel-console/tests/test_console_openapi_route_parity.py`，**24 passed**。
- **边界：**本次 Python parity suite 验证路由、权限/错误矩阵与相关边界，不等价于把 43 组样例逐一发送到 Python endpoint；也未完成逐页 wire 冻结审查、真实 HTTP 服务联调或最终 E2E。OpenAPI 仍是 draft-partial，F6.1 保持未勾；未连接真实配置中心或数据库。

### 15.449 F4.20 setup 工作流与 HTTP 首启合同复跑（2026-10-10）

- **验证：**在 `dashboard-prototype` 执行 `npm run test:logic:focused -- 'SETUP-'`，**24 passed**，覆盖 setup 分支投影、字段错误归属、敏感数据切换/清理、连接检查并行与失效、初始化拒绝/未知/核查/单飞及取消释放；执行 `npm run test:http:focused -- 'BOOTSTRAP-(HTTP|ACK)'`，**2 passed**，覆盖授权、检查命令与初始化回执核查不重放。
- **边界：**当前无新的前端逻辑缺陷由这两组测试暴露。它们不执行已挂载 DOM / React Effect 的最终秘密清理浏览器用例，也不证明完整 Python 持久化/部署路径；按既定节奏不运行浏览器 E2E。F4.20 仍保持未勾，继续推进其它实现，最终统一做 IAB E2E。

### 15.450 B0.1 首启规则命令安全配置装配（2026-10-10）

- **实现：**`FirstRunSqlIdentityConfiguration.from_environment()` 现可从现有独立规则命令 key 环境变量加载 HMAC key ring；host-owned `RuleMutationBindingReader` 必须作为显式参数与完整 key ring 成对提供。无 reader 但配置了 key、reader 缺 key、无效 key ring、直接构造部分配置、或混用预构建 authority 均 fail-closed；secret 不进入配置 `repr`。规则命令 SQL Composition Root 将原 reader/key 对传给既有 authority composition，不派生/复制 binding facts。README 同步注明 standalone CLI 暂无具体 binding authority，不宣称该路由已可用。
- **测试设计与验证：**先在该记录新增 deployment-config/composition 风险矩阵，再运行目标用例；新增前的测试明确以缺失 keyword API 和静默忽略 key 环境变量失败。实现后执行 `uv run --project components/sentinel/sentinel-console pytest -q components/sentinel/sentinel-console/tests/test_rule_command_key_configuration.py components/sentinel/sentinel-console/tests/test_first_run_deployment_configuration.py components/sentinel/sentinel-console/tests/test_first_run_composition.py`，**17 passed**。
- **边界：**仓库仍无生产 `RuleMutationBindingReader` 权威实现，standalone CLI 不启用规则命令；本切片仅打通安全配置到已存在 SQL composition 的宿主接线。未接触真实数据库/Nacos/Consul，未运行完整 Console suite 或最终浏览器 E2E；B0.1 保持未勾。

### 15.451 B0.1 Console SQL 规则 binding 目录只读 authority（2026-10-10）

- **设计与所有权：**明确 Console SQL 仅保存 binding 管理元数据（binding/app/environment/kind/profile/source/location），不保存规则数组或快照；规则正文仍只存在所选 Nacos/Consul 配置项。未引入 GoF 模式：这是既有 SQL composition 上的单一读取 adapter，无对象创建算法、独立可替换流程或多方协作复杂度。
- **实现：**新增 Alembic `0018_rule_binding_directory`、`RuleBindingRecord` 和 `SqlAlchemyRuleBindingDirectoryReader`；后者同时实现目录分页读取与按精确 binding ID 查询，必须 join 同 binding 的注册来源和 publication target，核对 source/provider/target/location 一致后才映射 DTO。目录查询按 env/app/kind/search 排序、过滤和分页；缺来源/目标、损坏 target 或映射不一致 fail closed。规则目标 CAS 写入在同事务同步 metadata 的 source/location。SQL identity composition 未提供替代 reader 时默认装配此目录 reader。
- **验证：**新增 SQLite migration/SQL reader 用例，覆盖过滤、搜索、稳定分页、孤立 binding 拒绝、跨 source/target 不一致拒绝、target 位置更新同步；与 binding API、target reader/writer、identity/first-run composition 和 deployment-config 一起执行 `sentinel-console/.venv/bin/pytest -q tests/test_rule_binding_directory_reader.py tests/test_rule_bindings_api.py tests/test_rule_publication_targets.py tests/test_identity_composition.py tests/test_first_run_composition.py tests/test_first_run_deployment_configuration.py`，**41 passed**。改动源码/测试 `compileall` 与 `git diff --check` 通过。
- **未完成边界：**目前没有 admin API/UI 注册或修改 binding metadata，不能通过 Dashboard 创建可用 binding；新 SQL reader 只读已有可信记录，SQL 目录默认仍为空。规则命令 mutation 仍需部署显式配置 key ring 和 exact-binding reader；未验证 PostgreSQL/MySQL migration 并发、真实 Nacos/Consul 或 React→Python 页面链路。B0.1、F6、最终 E2E 均不据此勾选。

### 15.452 B0.1 binding 创建的受保护 SQL 命令首切片（2026-10-10）

- **设计先行：**先记录 RB-01–RB-07 风险测试矩阵于 [B0.1 binding registration 验收记录](../../sentinel-console/acceptance/R-SENTINEL-CONSOLE-B0.1-rule-binding-registration.md)，并在[逐页 API 设计 §4.4](../Dashboard页面能力与接口设计.md)增加 `POST /rulesets` 候选；约束为 admin + Origin/CSRF + 幂等键，来源/provider/revision 来自已登记来源权威，Nacos/Consul 目标严格联合，单事务写 binding metadata + target + receipt + audit；不写规则数组，不访问配置中心。评估 GoF 23 模式后不新增模式，沿用单一用例/Port/SQL adapter。
- **实现：**新增注册命令、Use Case、严格 provider-body parser、admin-only `POST /api/v1/rulesets`、`RuleBindingRegistrationRecord`/Alembic `0019_rule_binding_registration` 与 SQL authority。事务内二次校验 admin/session/CSRF、精确注册来源 revision/provider；相同 actor/session+key+内容恢复原 binding，重用 key 改内容返回 idempotency 冲突；绑定唯一键、目标、幂等回执和 `rule-binding-create` 审计一起提交。SQL identity composition 默认装配新 authority。
- **验证：**新增 migration-driven SQLite atomicity/retry/role/CSRF/source revision/provider/scope 用例及 ASGI admin/view/Origin/body-negative 用例；执行 `PYTHONPATH=src .venv/bin/pytest -q tests/test_rule_binding_registration_store.py tests/test_rule_bindings_api.py tests/test_rule_binding_directory_reader.py`，**21 passed**；Console source `compileall` 通过。
- **后续对齐：**React consumer Port/HTTP adapter、OpenAPI `createRuleBinding` operation + positive/negative examples、三语 `rule-binding-create` audit action 已补，集中证据见 §15.453。页面表单和 app-configured MSW scenario 仍未实现。
- **未完成边界：**PostgreSQL/MySQL binding migration/并发请求未验收，真实 Nacos/Consul 未连接。该切片不勾 B0.1/F6/F7，不代表端到端可从 Dashboard 创建 binding；最终 IAB 与 React→Python E2E 仍仅在全部实现后执行。

### 15.453 B0.1 规则 binding 注册的 React/OpenAPI 消费者合同（2026-10-10）

- **实现：**React rules model/API 增加 credential-free `RuleBindingRegistration` 与 `RuleSetPort.registerBinding()`；provider target schema 与 Python 对齐：Nacos namespace/group/dataId 和 Consul key 最长 512 UTF-16 units，空白/控制字符拒绝，Consul 路径拒绝 traversal；POST adapter 使用 strict schema、HTTP 201、Idempotency-Key 与现有 CSRF transport，并校验返回 binding 身份和命令一致。OpenAPI machine operation 为 `createRuleBinding`，admin + `rules:write`；endpoint 单独声明错误集合，未把 registration 的 `conflict` 扩散到其它 mutation。三语 system audit catalog 接受 `rule-binding-create`。
- **验证：**React `npm run check:fast`、`npm run i18n:check` 通过；`npm run test:http:focused -- 'RULE-BINDING|CONSOLE-MACHINE'` **10 passed**（正/负 schema、Nacos/Consul wire boundary、带 CSRF/idempotency 的 201 adapter、响应身份错配拒绝、全部 OpenAPI examples/权限/error-code 投影）；Python `PYTHONPATH=src .venv/bin/pytest -q tests/test_console_openapi_route_parity.py tests/test_rule_binding_registration_store.py tests/test_rule_bindings_api.py tests/test_rule_binding_directory_reader.py` **45 passed**，Python compileall 通过。
- **边界：**React 端尚未有页面 registration form，也未将该 endpoint 接入 app-configured stateful MSW handler；单个 MSW adapter contract test 不证明完整 Demo scenario 可注册后回读。PG/MySQL 的 0019 upgrade/concurrent same-key registration、真实 Nacos/Consul、UI mounted flow 和最终全量 E2E 未执行。只完成对齐切片，B0.1/F6/F7 checkbox 保持未勾。

### 15.454 B0.1 规则绑定登记 UI 与共享来源 Mock（2026-10-10）

- **实现：**Rules feature 新增管理员专用“登记规则绑定”Dialog：来源目录经系统 feature 的只读 HTTP Port 获取，来源 ID/revision/provider 从权威目录选取；Nacos 与 Consul 使用各自精确目标字段。提交只登记绑定元数据，不写规则正文；复用现有 `RuleSetPort.registerBinding()`、CSRF、幂等请求键和统一 `DialogFrame`。成功后导航到新 binding。
- **Mock：**App mock composition 将 system source registry 的安全只读快照共享给 rule handler。登记来源、创建 binding、规则目录查询、空快照读取、publication target 读取走同一组 HTTP adapter；同键同 payload 返回原回执，同键变更 payload 返回冲突。Mock 新 binding 只生成空规则快照，不伪造配置中心写入。
- **验证：**`npm run check:fast` 通过（TypeScript、格式、ESLint、OpenAPI parity）；`npm run i18n:check` 通过（三语资源无缺键/模板拼键）；`npm run test:http:focused -- 'RULE-BINDING-REGISTRATION-MOCK|RULE-BINDING|CONSOLE-MACHINE'` **11 passed**，其中新增用例从 system HTTP 注册合成 Nacos source，再从 rules HTTP 创建/重放/读回绑定、空快照和精确目标。中途门禁捕获并修正 effect 内同步设状态及动态国际化拼键。
- **边界：**未运行 mounted UI/E2E（按约定留到全部实现完成），未连真实 Python 部署、数据库、Nacos/Consul；PG/MySQL migration/concurrent retry 仍待验收。此切片不勾 B0.1/F6/F7。

### 15.455 B0.1 PostgreSQL/MySQL binding registration 并发幂等验收（2026-10-10）

- **设计核对：**检查 `SqlAlchemyRuleBindingRegistrationStore` 后确认，同一 admin account/session 的写命令会先在事务内锁定 account/session 行，再查询幂等回执；并发同 key 请求因此在回执查询前已由既有 SQL authority 串行化。没有增加第二把锁、服务层协调器或新的 GoF 模式；新增 RB-08 跨方言测试来证明既有行为。
- **测试实现：**`tests/rule_binding_registration_database_acceptance.py` 为每次验收生成隔离身份/source/request/binding；测试持有专用 session 行锁，启动两个由独立 `SqlAlchemyRuleBindingRegistrationStore` 实例处理的相同命令，确认两个授权锁查询均已进入后再释放竞争。断言两次返回同一 binding，数据库中 binding、精确 target、幂等 receipt、创建 audit 各恰好一行；`finally` 仅删除本次生成的关联 ID 数据。
- **验证：**新鲜、无持久卷、仅 loopback 随机端口的一次性 PostgreSQL 16 容器执行 `tests/test_postgresql_acceptance.py`，**6 passed**；一次性 MySQL 8.4 容器执行 `tests/test_mysql_migration_acceptance.py`，**7 passed**。数据库用户/来源/命令均为合成数据；验收结束已按精确容器名移除。改动后再次运行 SQLite registration + 两方言并发聚焦选择，**9 passed, 11 deselected**；测试文件/生产模块 `compileall` 与 `git diff --check` 通过。
- **结论与边界：**现有 SQL 锁行为在两种真实方言的并发持久层验收中满足“同 key + 同 admin/session/payload 只写入一次并可安全回放”；本切片未改生产 transaction code。没有访问真实部署数据库、Nacos/Consul 或浏览器；React→Python mounted E2E 继续留到全部实现完成后。B0.1/F6/F7 不据此勾选。

### 15.456 F5.2 动态 i18n 调用与真实 key producer 的关联门禁（2026-10-10）

- **缺口：**原 `I18N-DYNAMIC-CALLSITE-COVERAGE` 将每个 AST 无法枚举的 `t()` 调用映射到一个有名 runtime suite，但只检查 suite 名在 `catalog.test.mjs` 中存在；错误映射到不相关 suite 时仍可能通过，不能证明调用数据来自所声明的 key producer。
- **修复：**manifest 每一项现包含源文件、调用表达式、suite ID 与 production producer 模块路径。自动化仍精确对比 `i18n:check` 实际报告的动态调用集合，并进一步截取该命名 runtime test block，断言 block 确实 `ssrLoadModule()` 声明的 producer 模块；本次将 22 个调用逐项绑定到导航、实例状态、身份校验/呈现、setup、实时状态、规则文案或发布标签 producer，不降低 AST 未解析数量，也不使用 allow-all。
- **验证：**`npm run test:i18n-tools` **36 passed**；`npm run i18n:check` **1,220 keys/locale**、**1,065** AST 静态键、22 个动态调用保留且全部被精确 producer manifest 接管；`npm run check:fast` 通过（typecheck、format、lint、OpenAPI contract）。完整 E2E 未运行。
- **未完成边界：**此项加强静态 callsite→runtime producer 的可审计关系，不证明测试中每个组件已挂载，也不替代真实页面三语交互。规则编辑草稿、其他持草稿页面、日期/时区/DST 与 URL 在语言切换期间的 IAB 矩阵仍待最终 E2E；F5.2 继续未勾。

### 15.457 F5.3 规则 binding 登记的纯逻辑与命令边界（2026-10-10）

- **缺口：**binding 登记已接入规则页面、HTTP adapter 与 stateful Mock，但 logic suite 没有直接覆盖表单候选到注册命令的来源快照绑定，以及命令在权限/回执/网络不确定状态下的行为。
- **测试：**复用 `node:test` focused runner，新建 `tests/logic/rule-binding-registration.test.mjs` 并登记到 logic suite。6 个断言组覆盖 Nacos/Consul 有效目标与 provider 字段隔离、输入归一化和缺字段拒绝；来源 revision 过期与 owner 未授权均不发请求；成功回执精确匹配登记身份、错配回执拒绝；pending 时第二次提交被拒绝且只有一次实际写入；执行中 owner 撤权时不接受迟到回执；网络异常只暴露稳定错误状态且命令进入 `result-unknown`，不泄露上游详情。
- **验证：**`npm run test:logic:focused -- 'RULE-BINDING-REGISTRATION'` **6 passed**；`npm run check:fast` 通过（TypeScript、格式、lint、OpenAPI contract）；`git diff --check` 通过。初次测试发现 Consul 测试输入未设置页面要求填写的 datacenter，修正测试输入后通过；未改生产行为。
- **未完成边界：**这证明 model/application command 边界，不证明 `RuleBindingRegistrationDialog` 的挂载交互、键盘/焦点、pending/失败/unknown 页面呈现或 IAB 完整路径；不证明 Python 真实服务联调。F5.3 继续未勾，相关浏览器与跨端验收按清单留到最终阶段。

### 15.458 B0.1 first-run CLI 默认 SQL binding authority 装配（2026-10-10）

- **缺口：**规则写命令的 key ring 已可通过 deployment environment 配置，但 `FirstRunSqlIdentityConfiguration` 同时强制要求额外注入 exact binding reader；标准 `sentinel-console serve` CLI 没有 Python 对象注入入口，导致标准 SQL 部署即便已有 Console-owned binding/source/target 表和 key ring，也无法启用其自身的规则 mutation authority。
- **修复：**标准 first-run composition 在 key ring 存在且没有 host override 时，将已有 `SqlAlchemyRuleBindingDirectoryReader` 装到同一个 `RuntimeDatabaseEngineBridge`，该 reader 同时提供列表与 exact binding 查询；CLI 注册 API 能读取自身 authority。host 自定义 reader 仍优先；reader 无 key ring、direct authority 与 SQL composition 混用仍 fail-closed。未从请求参数推断 binding，也未启用 Nacos/Consul worker。
- **模式与职责：**复用既有 SQL adapter 与调用方 Port，在 composition root 做明确选择；不新增 GoF 创建/行为模式，不把 SQL 类型放进 application/domain，也不改变 configuration-center 对规则正文的所有权。
- **验证：**`PYTHONPATH=src .venv/bin/pytest -q tests/test_first_run_composition.py tests/test_first_run_deployment_configuration.py tests/test_rule_command_key_configuration.py tests/test_cli.py tests/test_rule_binding_directory_reader.py tests/test_identity_composition.py tests/test_rule_mutation_store.py` **55 passed**。首次运行暴露 `test_identity_composition.py` 的完整 app-call 断言遗漏当前已装配的 binding-registration authority；补齐该既有契约断言后全组通过。Python import/pytest 运行通过，后续补跑 `compileall` 与 `git diff --check`。
- **未完成边界：**未连接真实 PostgreSQL/MySQL 实例、Nacos/Consul 或浏览器；SQL binding registration 的方言验收与 UI→CLI 实际用户链路另有记录/仍需最后验收。此项只解决标准 CLI 的 reader 装配，B0.1/B0.3 继续未勾；最终前后端 E2E 仍待全部代码实现后执行。

### 15.459 B0.6 当前 React production bundle 打入并从隔离 wheel 提供（2026-10-10）

- **发现与修复：**当前 React 源码生产构建包含 81 个 manifest-linked 运行文件；仓库中 marker-owned `sentinel-console/web/` 仍是旧产物，缺少其中 45 个文件且 `index.html` 不一致。运行现有 `node scripts/package-console-assets.mjs` 只刷新该生成目录，得到 81 个文件、2,169,601 bytes。
- **wheel 证据：**`uv build --out-dir /tmp/sentinel-console-wheel.yVPTV2` 成功生成 0.1.0 sdist/wheel；wheel 中 81 个资产逐一匹配 `.dashboard-assets.json` 的路径、字节数和 SHA-256，未包含 `mockServiceWorker.js`。`uv pip install --target /tmp/sentinel-console-wheel-install --no-deps ...whl` 隔离安装后，以该安装目标优先的 `PYTHONPATH` 执行 `tests/test_static_web.py`，**4 passed**；覆盖安装 wheel 的静态首页/深链、asset cache、API 404 与非根前缀路由，不需要 Node runtime。
- **验证范围：**前端 `npm run build` 成功，构建报告 42 个 deferred entries；`git diff --check` 在本记录更新后执行。wheel 检查只用于本机隔离目录，没有发布 PyPI，也没有访问真实数据库/Nacos/Consul。
- **任务状态：**B0.6 的“React assets 随 Python wheel 打包且安装后由 ASGI 静态路由服务、不需 Node”交付已完成并勾选。该证据不关闭 F7.6 的已安装 wheel IAB 渲染及生产 launcher/reverse-proxy 验收，也不关闭 B0.5/live API、全量最终 E2E 或发布授权。

### 15.460 B0.3 活动计划 claim 的 PostgreSQL/MySQL 并发与毫秒租约验收（2026-10-10）

- **实现：**新增可复用的真实数据库 acceptance fixture，以 UUID 隔离活动计划、规则版本、来源和验证回执；通过两个独立 SQLAlchemy queue 实例/连接池并发 claim，断言首次只有一个 owner。租约到期后再次竞争，断言只有一个 attempt-2 新 owner、claim token 已轮换，旧 token 的续租被拒。
- **缺陷修复：**真实 MySQL 首轮验收发现 `DATETIME` 默认精度为整秒，会截断 lease expiry 毫秒并破坏旧 owner/新 owner 边界。增加迁移 `0020_millisecond_worker_leases`，将 operation 与 activation-plan 两个 lease expiry 字段改为 `DATETIME(3)`，模型声明同步；MySQL acceptance 检查 information_schema 精度，downgrade 在存在 active lease 时拒绝降精度。没有放宽测试时钟或断言。
- **验证：**一次性 loopback PostgreSQL 16 完整 acceptance **7 passed**；一次性 MySQL 8.4 完整 acceptance **8 passed**；SQLite mutation/scheduler/provider worker 回归 **38 passed**；`compileall`、`git diff --check` 通过。Ruff 未安装在该组件虚拟环境。PostgreSQL 用例重跑曾因复用了已由首启用例初始化的测试库而失败；改用新鲜隔离库后完整 **7/7 passed**。两只临时数据库容器已停止并由 `--rm` 清理。
- **进度解释与边界：**这是 B0.3 中 PLAN-EXEC-01/08 的真实 SQL claim/lease 验收；PLAN-EXEC-01 的 scheduler 输家无发布副作用另见 §15.467。仍未证明独立 OS 进程、真实 provider CAS/未知结果恢复或实例 receipt，故父任务 B0.3 不勾，98 项总数和未完成数不变；完整 E2E 仍按约定留到所有实现任务结束后。对应数据库细节见 [活动计划持久化验收记录](acceptance/R-SENTINEL-CONSOLE-B0.3-activation-plan-persistence.md)。

### 15.461 B0.3 Provider CAS 冲突不覆盖外部变更（2026-10-10，worker 边界）

- **场景：**发布 worker 读取当前配置后，模拟外部 actor 在 CAS 前先修改配置；provider 对旧 revision 的条件写返回稳定 `RulePublicationProviderConflict`。
- **验证：**`test_cas_conflict_after_read_does_not_overwrite_external_change` 断言 worker 返回 `REJECTED`、持久工作边界收到拒绝、未标记完成、写调用只有一次、外部配置字节保持原值且 configuration-write 阶段为 `FAILED/CONFLICT`。现有 `test_rejected_operation_blocks_claim_without_publication_link` 验证 activation-plan scheduler 收到冲突拒绝后将计划阻塞，不继续关联/完成。
- **结果与边界：**发布 worker 与计划 worker 的失败反应现有分层证据，PLAN-EXEC-04 从 open 细化为 partial。新增测试使用受控 provider double，不证明 Nacos/Consul 服务端 CAS 并发、SQL 中 plan/publication/audit 的同一组合事务，也未验证恢复阶段不发起 restore；这些仍待 provider/service acceptance。完整 E2E 留在全部实现后。
- **验证：**`PYTHONPATH=src .venv/bin/pytest -q tests/test_rule_publication_worker.py tests/test_run_rule_activation_plan_worker.py`：**14 passed**；`compileall` 与 `git diff --check` 通过。

### 15.462 B0.3 SQL 计划遇到 CAS 冲突后阻塞且不执行恢复（2026-10-10）

- **实现：**在现有 `test_rule_mutation_store.py` 集成夹具中新增完整 SQL 编排用例：创建真实 SQLite 持久计划/不可变版本，经 scheduler 写入 scheduled operation/outbox；真实 `SqlAlchemyRulePublishOutbox`、publication/version SQL reader 与 `RunRulePublicationWorker` 运行；唯一替身是配置源 provider，它在读取后模拟外部修改并对旧 revision 返回 CAS conflict。
- **断言：**external value/revision 不变；发布 operation 被拒绝、write 阶段为 `failed/conflict`；租约到期后 scheduler 恢复该计划并持久化 `blocked`；进入 deactivate/restoration 时间后没有 restoration operation，provider 写调用仍恰为一次。
- **验证：**单用例 `1 passed`；相关 mutation store + publication worker + activation scheduler 套件 `40 passed`。
- **边界：**证明 SQL workflow 与受控 CAS 冲突结果的组合行为，不证明 Nacos/Consul 服务端的真实原子竞争，不证明 PostgreSQL/MySQL 上完整 plan→publication CAS 链；当时 PLAN-EXEC-04/06 均仍 partial/open。后续 restoration 外部变更证据见 §15.463；B0.3 不勾，完整 E2E 延后到实现收口。

### 15.463 B0.3 已激活计划检测外部变更并安全阻塞恢复（2026-10-10）

- **实现：**用 SQLite SQL plan/outbox 先将 activation publication 的 validation/write/read-back 三个持久阶段标为 succeeded，再由 scheduler 完成 activation；只在此之后把受控 provider 当前值改为外部修改内容。计划到达 deactivation window 后，scheduler 创建 restoration operation，真实 SQL publication worker 对比当前值与 frozen activated baseline。
- **断言：**preflight 将 restoration 标记为 `failed/conflict`；provider 写调用为 0，外部 revision/bytes 未变；scheduler 恢复后计划为 `blocked`；只存在同一 restoration operation，没有重复恢复操作。
- **验证：**新用例单独 **1 passed**；与 mutation-store、publication worker、activation scheduler 套件合计 **41 passed**；相关 Python `compileall` 通过。
- **边界：**本用例证明外部编辑已在 restoration read 前发生时不会覆盖。未模拟 restoration 读取完成后到 CAS 之间的第二次外部写入竞态（由 PLAN-EXEC-04 覆盖其 worker/SQLite 链路但非 restore phase）；未运行真实 provider 或 PostgreSQL/MySQL 完整工作流。PLAN-EXEC-06 仍 partial，B0.3 不勾，最终 E2E 未执行。

### 15.464 B0.3 PostgreSQL/MySQL blocked plan 排除恢复 claim（2026-10-10）

- **测试：**扩展 `rule_activation_plan_database_acceptance.py` 的双 worker acceptance。完成独立 connection pool 的首次单赢家 claim 与租约过期单赢家接管后，使用当前新 owner 调用既有 `block_claim`；在计划的 restoration deadline 之后让两个独立 queue 再次竞争 `claim_due`。
- **断言：**计划持久状态为 `blocked`，claim token 与 expiry 清空；两个 queue 均返回空 claim 集合，不会把被阻塞计划转入 `restoring`。
- **验证：**一次性 PostgreSQL 16 acceptance 用例 **1 passed**；一次性 MySQL 8.4 acceptance 用例 **1 passed**。各自使用新建 `sentinel_console_test_claimblock` 数据库和 loopback-only 临时容器；容器已停止并自动删除，测试 helper 在 `finally` 精确删除合成账户、版本、回执及计划行。
- **边界：**这是两个真实数据库方言上的 plan queue/claim 状态验收，不含 SQL publish outbox、provider CAS 或独立 OS scheduler 进程；对应 PLAN-EXEC-04/06 只补充 blocked 状态的数据库证据，整体仍 partial。B0.3 未完成，最终 E2E 未运行。

### 15.465 B0.3 取消与 activation claim 竞争验收（2026-10-10）

- **交错设计：**claim-wins 场景让真实 `SqlAlchemyRuleMutationStore.mutate(CancelRuleActivationPlan)` 在首次授权/幂等事务之后由 binding-reader gate 暂停；另一个 SQLAlchemy engine/pool 的真实 `SqlAlchemyRuleActivationPlanWorkQueue` 领取到期计划，再恢复取消并检查 conflict。cancel-wins 场景用独立事务锁住第二个到期计划；取消命令通过 binding reader 进入最终事务并等待该行时，scheduler 的 `SKIP LOCKED` 查询必须为空；释放锁后命令完成取消，再查询仍无 claim。两种时序均由显式 gate/DB lock 控制，没有依赖任意 sleep 猜竞态。
- **完成发布窗口：**取消必须返回持久 `rejected/conflict`；scheduler claim 随后通过真实 scheduled publication SQL 入队并关联 publication。断言 outbox operation `pending`、恰有对应 publication、计划仍为 `activating` 并持有当前 claim token/publication ID，拒绝回执不能把已启动 phase 表示为 cancelled。
- **验证：**一次性 loopback PostgreSQL 16 acceptance **1 passed**；一次性 loopback MySQL 8.4.11 acceptance **1 passed**；现有 SQLite activation-plan command/scheduler 选择 **5 passed**。`compileall` 与定向 `git diff --check` 通过。fixture 的 session epoch 首轮超过数据库字段上限，依真实 schema 将合成 epoch 收短后双数据库重跑通过；生产代码未改。
- **清理与边界：**测试在 `finally` 按本次 UUID 删除账户/session、计划、版本、回执、操作、publication 与 audit；容器使用本轮精确命名、loopback 随机端口与 `--rm`。本证据覆盖 claim-wins、cancel-wins 两种受控交错及 claim 后 publication acceptance/association，PLAN-EXEC-07 的数据库状态竞争准则已验证。未验证 OS 进程崩溃、多 ASGI worker、真实 Nacos/Consul CAS/provider side effect 或浏览器；B0.3 父任务仍未勾，完整 E2E 延后至所有实现完成。

### 15.466 B0.3 provider unknown outcome 的计划恢复（2026-10-10）

- **场景：**SQLite SQL integration 先由 scheduler 创建并关联 activation publication。Provider double 将完整候选写入其远端状态后故意抛 `RulePublicationProviderOutcomeUnknown`，模拟服务端可能已提交但响应丢失；其后的 reads 返回已应用内容。
- **安全断言：**第一次发布后 publication 的 configuration-write phase 为 `unknown`、read-back 尚未开始、operation 仍 pending，activation plan 仍为 `activating`；plan lease 到期接管后复用同一 operation/publication，不新建发布；publication worker 读取并精确确认候选时不再次调用 provider write；只有 read-back 完成且 publication 完成后 scheduler 才将 plan 置为 `active`。同一 plan 下 operation、publication、completed audit 各只有一条。
- **验证：**新增 `test_activation_unknown_provider_write_recovers_same_publication_without_rewrite` 单测 **1 passed**；之后包含 `test_rule_mutation_store.py`、publication worker、activation-plan lifecycle 与 `test_run_rule_activation_plan_worker.py` 的定向 suite **45 passed**。没有变更生产代码，测试通过独立新 worker 实例推进租约恢复，未修改既有 worker 私有 clock/state。
- **边界：**此链路使用 controlled provider double，证明真实 SQL 状态/租约/回执编排，而非真实 Nacos/Consul transport 的超时或 CAS 语义；也未杀进程、重启 ASGI 或验证跨主机 worker。PLAN-EXEC-03 细化为 partial，B0.3 不勾，完整 E2E 仍延后。

### 15.467 B0.3 双 scheduler 单赢家且输家无发布命令（2026-10-10）

- **交错设计：**在已有两个独立 SQLAlchemy queue pool 的真实数据库验收中再构造两个 `RunRuleActivationPlanWorker`，以 gate 将赢家暂停在 publication enqueuer；第二个 scheduler 在另一个 pool 上运行同一时刻的 `run_once()`。不依赖 sleep 估算竞态，只有在赢家进入 enqueuer 后才启动输家。
- **断言：**输家返回空 outcome，门控 enqueuer 调用次数仍为 1；释放赢家后，真实 `SqlAlchemyRuleMutationStore.enqueue_scheduled_publication` 创建唯一待处理 operation/publication，队列将 publication ID 关联回同一 `activating` 计划。publication 三个阶段最初均为 `awaiting`，不将入队误报为 provider 已成功。
- **验证：**PostgreSQL 16 与 MySQL 8.4.11 独立 acceptance 各 **1 passed**；两个真实方言均经过迁移、独立连接池竞争与 fixture 精确清理。`ruff` 检查通过。
- **边界：**两个 scheduler 是同进程内的独立 worker/SQL pool，不等价于独立 OS 进程或多机故障验收；也不覆盖真实 provider CAS/unknown transport、process kill/restart、runtime instance receipt。PLAN-EXEC-01 的数据库/scheduler side-effect 准则已验证；B0.3 父项仍未勾，最终 E2E 仍留到实现任务全部完成后。

### 15.468 F5.2 动态翻译调用覆盖门禁确认实际加载 producer（2026-10-10）

- **修复：**动态 `t()` 调用覆盖测试不再只确认对应 runtime suite 文本中出现 producer 路径；现在必须在 suite 代码中匹配到 Vite `ssrLoadModule()` 对该精确 producer 的实际加载，避免注释/无关字符串造成假绿。
- **验证：**动态 callsite-to-producer 映射 **1 passed**；三语动态 producer/catalog 定向 suite **18 passed**。未运行完整浏览器 E2E。
- **边界：**这是 F5.2 动态 key 测试可信度的一项收口，不代表全部 locale-switch 草稿保留、数值/日期/时区展示矩阵均验收完成；F5.2 继续未勾。

### 15.469 B0.3 一次性 Consul 服务端 CAS acceptance（2026-10-10）

- **实现：**新增 opt-in `tests/test_consul_rule_source_writer_acceptance.py`，每个用例自行启动 `hashicorp/consul:1.21.1` disposable dev server，loopback 随机端口、无 volume、唯一容器名；只允许精确 `127.0.0.1/32 + mapped port`，用真实 `ConsulRuleSourceWriter/Reader` 读写唯一合成 key。
- **验证：**创建 CAS `0`、按真实 `ModifyIndex` 更新、过期 index 被服务端拒绝并读回新 revision；另用双请求 barrier 让两个 writer 同时以 CAS `0` 竞争同一不存在的 key，恰一个成功、另一个 conflict，最终内容/revision 与赢家回执相同。真实服务验收 **2 passed**；provider/reader/router/worker 定向套件 **21 passed**、默认无副作用模式 **2 skipped**。测试结束后确认没有遗留 `sentinel-consul-cas-*` 容器。
- **边界：**证明真实 Consul 单 writer create/update/stale-CAS 与双 writer create-only 单赢家；不证明 ACL/TLS、生产 DNS allowlist、多进程 Console 或完整 SQL 发布工作流。B0.3 仍未勾，Nacos create-only/部署联调与实例回执等仍开放。

### 15.470 B0.3 `serve` 显式装配持久规则发布 worker（2026-10-10）

- **实现：**`sentinel-console serve` 的环境配置新增可选 `SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDER` 与 `SENTINEL_CONSOLE_RULE_PUBLICATION_PROFILE_ID`。默认不启用；启用时必须同时配置规则命令 HMAC key ring，并且所选 provider 必须已有显式 registered-source 网络授权。First-run composition 复用延迟连接的 runtime SQL bridge、加密 registered-source store、已选 provider 的目标授权和现有 Consul/Nacos worker factory；单进程只选择一个 provider。凭证引用仍仅通过宿主注入的 resolver 解析，不自动假设 KMS、TLS 策略或凭证来源。
- **验证：**新增环境默认关闭、显式配置、缺 key、未知 provider、未授权 provider 拒绝测试，以及 composition factory/目标策略/凭证 resolver 注入测试；deployment configuration、first-run composition、worker composition 与 CLI 定向 suite 共 **22 passed**。
- **边界：**未访问真实数据库或配置中心，未证明 worker 对部署中的 ACL/TLS/DNS 授权正确、配置中心 CAS/read-back、实例级生效回执或多进程运行；只补齐部署可显式装配路径。B0.3 父项继续未勾，完整浏览器 E2E 仍按约定延后到全部实现收口。

### 15.471 F6.2 故障分析 HTTP 参数投影与合同回归（2026-10-10）

- **修复：**Incident HTTP adapter 不再把通用观察上下文的 `resource: undefined` 透传给严格 incident query schema；请求参数只投影已定义的 environment/app/instance/scope/time 字段，并增加不发送 resource 的回归断言。同步修复 HTTP 合同测试的合成 bootstrap code 长度、由运行时 registry 驱动 operation 数量断言，以及 RuleSet mock 测试缺失的 handler 工厂导入。
- **验证：**受影响定向用例 **13 passed**；完整 HTTP 合同组 **141 passed / 0 failed**；`npm run test:architecture` **23 passed**（含 F6.2 未知 wire 到领域类型禁止断言门禁）；`npm run check:fast`（typecheck、format、lint、contract generation）通过。
- **边界：**这一切片修复 Incident 请求投影并恢复 HTTP 合同套件，不等于完成 F6.2 全部 44 个 operation / 页面行为审计；未运行浏览器或 Python 联调。清单总数不变，F6.2 仍未勾，完整 E2E 仍留最终里程碑。

### 15.472 B0.3 发布阶段回执丢失后的幂等回放（2026-10-10）

- **实现：**发布 outbox 的阶段 CAS 现在识别同一有效 claim 下完全相同的、合法的阶段转换重放，并返回已持久化的发布事实；不接受不同阶段值或已被新 claim token 接管的旧 worker。合法转换关系由领域层集中定义，避免 outbox 复制状态机规则。
- **验证：**SQLite 持久 mutation-store 用例覆盖初次阶段提交后以相同 expected/next phase 回放并得到相同 publication；已有用例继续验证过期接管后旧 token 的阶段更新被拒。`test_rule_mutation_store.py`、`test_rule_publication_worker.py`、`test_rule_publication_worker_lifecycle.py` **41 passed**；`compileall` 通过，修改文件尾随空白扫描无发现。
- **边界：**补齐 PLAN-EXEC-08 的 publication phase replay 与 SQL fencing 切片；不证明独立 OS process takeover、多进程启动、Nacos/Consul 完整真实发布或实例级生效回执，故 B0.3 保持未勾。完整 Dashboard E2E 未运行，仍留到所有实现任务完成后。

### 15.473 F4.20 初始化闭窗清理验证准备与 IAB 结果（2026-10-10）

- **准备：**新增只存在于 `tests/e2e/probes/` 的 mounted lifecycle harness，加载真实 `InitializationPage`、`useSetupFlow` 与 `InitializationWorkflow`，并在产品构建入口之外运行；先修正 harness 必须等待应用 i18n 与 Astryx locale catalog 加载后才能 render 的初始化顺序。
- **已验证：**仅使用 Codex 内置浏览器和本机 Vite；可访问 mounted 页面并填入合成数据库、管理员、Nacos 直接凭证，通过前端连接检查进入复核页。触发“另一初始化者关闭 setup”后，IAB 的后续交互/状态读取超时，无法观察闭窗后的表单/路由状态；没有据此断言 UI 成功或存在确定的 React 错误。没有调用 Chrome、Edge 或外部服务。
- **定向门禁：**`npm run check:fast` 通过；`npm run test:logic:focused -- 'SETUP-LIFECYCLE|SETUP-SECRET'` **3 passed**；`node --test --test-name-pattern='F4.20-SETUP-LIFECYCLE|F4.20-SETUP-PAGE-RENDER' tests/i18n/catalog.test.mjs` **1 passed**；`node --check tests/e2e/initialization.e2e.test.mjs` 与本次文件 `git diff --check` 通过。完整 E2E 未运行。
- **边界：**mounted 外部闭窗后的实际清理仍未验收，F4.20 继续未勾；应在最终浏览器验收继续用 IAB 重试并检查具体闭窗状态。测试页未连接 Python、数据库、Nacos 或 Consul。清单待办数不变。

### 15.474 F5.2 数字格式器使用受支持的活动界面语言（2026-10-10）

- **修复：**规则绑定目录、规则发布回执和系统连接探测曾直接把可能为空的 `i18n.resolvedLanguage` 传给 `Intl.NumberFormat`，这会静默退回运行宿主默认区域设置，与产品当前语言不一致。三处现统一使用 `i18n.resolvedLanguage ?? i18n.language`；连接观测数字和时间也复用同一 locale，避免格式来源分叉。
- **验证：**F5.2 数值、UTC 日期、语言标签与时区用例 **8 passed**；新增 AST 架构门禁禁止 `Intl.NumberFormat` / `Intl.DateTimeFormat` 直接消费可空的 `i18n.resolvedLanguage`；架构测试 **24/24**、`npm run check:fast`（typecheck、format、lint、OpenAPI contract check）与 `git diff --check` 通过。
- **边界：**这是 F5.2 区域设置正确性切片，不覆盖全部动态 key、页面草稿跨语言持久性或浏览器矩阵；清单总数不变，F5.2 继续未勾，完整 E2E 仍留最终验收。

### 15.475 F3 样式架构测试更新已迁移文件路径（2026-10-10）

- **修复：**样式所有权架构测试仍读取已迁移/改名的 `realtime/ui/Realtime.module.scss`；按当前文件所有者改为 `Monitoring.module.scss`，避免架构测试在读取阶段直接 ENOENT。
- **验证：**完整 `npm run test:architecture` 已重跑，**23 passed**；该测试集同时覆盖 F5.2 草稿与 URL 所有权、F6.2 mapper 不把未知 wire 断言为领域类型。
- **边界：**修复的是过期测试夹具路径，不扩大 F3/F5/F6 的产品验收结论；完整 E2E 未运行。

### 15.476 B0.4 Reporting V1 Collector 依赖边界复核（2026-10-10）

- **发现：**`reporting-protocol-02-transport-v1.md` 文件头声称 transport 已 Frozen/5-owner sign-off，但正文仍明示 pending draft 且 MUST NOT 按已冻结标准实现；V1 freeze record 的 Freeze Declaration 只冻结 envelope。另 transport §2 明确 V1 不承载 raw RT 或 generic metrics。它不能单独作为真实 QPS/RT/TPS 的数据源合同。
- **处理：**本轮不新增 Collector 专用 wire、不从规则执行事件推造指标。B0.4 继续要求权威观测源；Reporting transport 的状态矛盾和指标采集合同须先在已有协议决策中澄清，Collector/Reporter 联调不得以当前矛盾文档冒称完成。
- **边界：**这是避免违反协议边界的审计结果，不是 B0.4 实现；未访问 Collector/Reporter 网络服务、数据库、Nacos 或 Consul，B0.4 仍未勾。

### 15.477 B0.4 Reporting transport 状态元数据与正文一致（2026-10-10）

- **修正：**Reporting V1 transport 英文/中文文档头曾标注 Frozen 与 5-owner sign-off，但正文及 freeze record 均表明 transport 仍待签字、尚未冻结；已将双语文档元数据统一改为 Transport draft / Pending owner sign-off。仅 envelope schema 的冻结声明保持不变。
- **验证：**核对双语文档头与正文状态一致；本次两文件 `git diff --check` 通过。
- **边界：**没有替协议 owner 冻结或签署 transport，也没有扩展协议承载原始指标；Collector 指标事实源和 Reporter/Collector 联调仍未实现，B0.4 不勾。

### 15.478 F7.5 当前前端工程说明清理与运行模式对齐（2026-10-10）

- **更新：**README 现说明规则草稿/校验/版本/发布/计划能力、demo 与 first-run Mock profile、live API 配置、安全重置方式及 fail-closed 行为；移除已不存在的 `app/applicationScope.ts` 与旧同步 FixtureGateway 当前残留说法。AGENTS 和 React 职责地图明确这是正式 React 前端工程、Mock/live 的真实边界、未完成的 Python/live 验收及“最终阶段才跑 E2E，不使用 Chrome/Edge/CDP”。`REWRITE_PLAN.md` 保留为带历史标记的 2026-10-05 材料，并指向唯一当前清单，不再作为并行计划。
- **验证：**对四份文档执行过期状态关键词检查与 `git diff --check`；未运行应用测试，因为本次只改文档。
- **边界：**此项只关闭文档/运行说明维护，不证明 live Python Console、真实服务、完整页面交互或最终 E2E；前端剩余 **25** 项、后置后台工作 **5** 项。

### 15.479 B0.3 activation lease 跨 OS 进程恢复（2026-10-10）

- **实现：**PostgreSQL/MySQL 共享验收 helper 新增 `spawn` 子进程用例。一个子进程创建独立 SQLAlchemy engine 并领取到期 plan 后退出；lease 到期后另两个新子进程各自建 pool 同时竞争，断言只有一个 attempt-2 claim、claim token 已更新且没有无关 plan 被领取。子进程异常、等待门超时或进程不能退出都会使测试失败，不默认为“未取得 claim”。
- **验证：**在隔离临时 PostgreSQL 16 容器执行 `tests/test_postgresql_acceptance.py -k independent_activation_plan_workers_fence_and_recover`：**1 passed, 7 deselected**；在隔离临时 MySQL 8.4.11 容器执行 `tests/test_mysql_migration_acceptance.py -k independent_activation_plan_workers_fence_and_recover`：**1 passed, 8 deselected**。两个临时数据库容器均已停止。Python `compileall` 通过。
- **边界：**将 PLAN-EXEC-10 从 open 提升为 partial，但没有模拟两个 ASGI lifespan 并发启动/轮询，也未在 provider side effect 中途杀进程；不覆盖真实 Nacos/Consul、不关闭 B0.3。前端待办数仍 25，后端父任务仍 5；完整 E2E 留最终阶段。

### 15.480 B0.3 实例规则发布回执 SQL 持久化与分页读模型（2026-10-10）

- **设计边界：**复用既有 `RulePublicationReceipt` 不可变领域事实和 `RulePublicationReceiptReader`；新增最小写入 Port 与 SQL store，不新增 GoF 模式、不开放 Reporter HTTP 路由，也不定义/冻结跨语言上报字段。实例清单权威来源尚未接入，因此响应的 `expected` / `inventorySource` 继续为 `null`，不可用“已知实例数”猜测覆盖率。
- **实现：**新增 `0021_rule_publication_receipts`，以 `(publication_id, instance_id)` 保存当前投影；写入必须匹配精确 binding/publication/target version，APPLIED checksum 必须等于 publication checksum。相同回执可幂等重放；过旧时间、同一时间冲突事实拒绝。SQL reader 按 instance ID 稳定分页，并在同一条 SQL 查询里提供全量各状态计数，超末页仍保留准确计数。MySQL 时间列为 `DATETIME(3)`；first-run SQL identity app 已装配此 reader。
- **验证：**SQLite/Alembic receipt 写读测试、等时重放/旧回执冲突/错版本拒绝、跨页计数/空页、SQL composition 与 HTTP receipt contract 合计 **34 passed**；新建隔离 disposable PostgreSQL 16 与 MySQL 8.4.11 上的迁移、两个并发相同初始回执幂等写入、毫秒时间往返各 **1 passed**。MySQL 首轮实测发现默认 `DATETIME` 截秒，修成 `DATETIME(3)` 后复测通过。两个临时数据库容器已停止；`compileall` 与 `git diff --check` 通过。ruff 不可用（仓库 `.venv/bin/ruff` 不存在）。
- **边界：**尚无 Reporter/Collector 到写入 Port 的接入、跨语言上报协议签字、权威实例 inventory/expected denominator 或浏览器联调；故 B0.3 保持未完成，后端待办仍 5 项，当时前端待办为 25 项（F6.2 后为 24 项），最终 E2E 未运行。此持久化层要求 producer 提供可排序的 `last_report_at`；上报方如何确定该时间仍由待冻结的协议决定。

### 15.481 B0.3 两个独立 ASGI lifespan 并发调度（2026-10-10）

- **覆盖：**扩展 PLAN-EXEC-10 acceptance：两个 `spawn` 子进程各自创建独立 SQL engine、publication command store 和实际 `build_app` ASGI lifespan；共享 barrier 确保两边 scheduler loop 都已启动后才同时释放 `claim_due()`。同一 due plan 最终只产生一个 outbox publication enqueue、一个 operation/publication、一次 claim attempt，且 plan 关联赢家的 publication ID。
- **验证：**隔离 PostgreSQL 16：`tests/test_postgresql_acceptance.py -k independent_activation_plan_workers_fence_and_recover` **1 passed, 8 deselected**；隔离 MySQL 8.4.11：`tests/test_mysql_migration_acceptance.py -k independent_activation_plan_workers_fence_and_recover` **1 passed, 9 deselected**；生命周期/应用 worker 局部回归 **8 passed**；Python `compileall`、`git diff --check` 通过。两只本轮创建的 loopback disposable DB 容器已停止。
- **边界：**不访问 Nacos/Consul、不验证真实 provider CAS；也未模拟 provider side effect 中途进程崩溃及其后完整阶段恢复。PLAN-EXEC-10 扩大为已验证实际多 ASGI 进程启动/争用，但仍是 partial；B0.3、前端最终 IAB/完整 E2E 均未关闭，待办计数不变。

### 15.482 B0.3 Consul KV writer 独立真实服务验收（2026-10-10）

- **验证：**显式启用 `tests/test_consul_rule_source_writer_acceptance.py`，使用测试自行创建的 `hashicorp/consul:1.21.1` 临时 dev server。两项均通过：单 key create/update/stale `ModifyIndex` 冲突和精确 read-back；两个并发 CAS-0 create-only writer 只有一个 server-side winner，最终 KV 与 winner receipt 一致。结果 **2 passed in 1.71s**。
- **清理/边界：**只绑定随机 loopback 端口与随机 key；测试 teardown 移除唯一命名容器，运行后 `docker ps -a --filter name=sentinel-consul-cas` 无残留。未访问已运行 Consul/Nacos；此证据不包含 ACL/TLS 部署策略、SQL outbox 到 Consul 的完整发布链、Nacos provider 或 React→Python E2E。B0.3 仍未完成。

### 15.483 F6.2 新 Console HTTP adapter 实现收口（2026-10-10）

- **实现边界：**前端 feature Ports 已由各自 `api/*Http.ts` 实现，endpoint/DTO/schema/mapper 分层；全局 transport 使用 `@richie696/react-framework` 的 `Url`/`HttpClient`，Mock 与 live 共用该 transport，显式 demo 模式只在 HTTP 层由 MSW 拦截。旧同步 FixtureGateway 已删除，不以别名或兼容层保留。将真实 Python 服务联调从 F6.2 拆回 B0.5，完整页面 E2E 仍归 F7 最终验收，避免把两个系统边界混为一个前端实现任务。
- **验证：**在 `components/sentinel/dashboard-prototype` 执行 `npm run typecheck`（通过）、`npm run test:http`（**141/141 passed**，包含所有 Console operation 正负样例、Mock HTTP、错误/取消/超时及受控 loopback）、`node --test tests/architecture/wire-mapper-assertions.test.mjs tests/architecture/dependencies.test.mjs`（**11/11 passed**）、`npm run contract:check`（**43 paths / draft-partial**）及根目录 `git diff --check`（通过）。据此关闭 F6.2 前端 adapter 实现范围；该证据不表示真实 Python 联调或浏览器 E2E 已通过。
- **当前计数：**前端开放 **24** 项，后置后台开放 **5** 项。此计数只表示父级任务状态，不能把一个父项中的局部实现/测试当作整个能力已闭环。

### 15.484 B0.3 SQL outbox 到真实 Consul 发布闭环（2026-10-10）

- **覆盖：**在既有 SQL rule mutation fixture 上受理 admin 发布命令，运行正式 `create_consul_rule_publication_worker` composition，经 SQL outbox claim、payload 编码、Consul KV CAS-0 写入和精确 read-back 完成发布；断言 SQL operation/publication 终态、敏感操作原因未泄漏，并再次运行 worker 不产生第二次 KV revision。
- **验证：**`SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 uv run --no-sync --extra test pytest -q tests/test_rule_mutation_store.py -k consul_worker_publishes_sql_outbox_to_real_consul`：**1 passed**；`uv run --no-sync --extra test pytest -q tests/test_rule_mutation_store.py tests/test_rule_publication_worker_composition.py tests/test_consul_rule_source_writer_acceptance.py`：**32 passed, 3 skipped**。验收测试使用随机名称、临时 loopback 端口、随机 KV key 和自行启动的 Consul 1.21.1 容器；运行后无 `sentinel-consul-worker-*` 残留。
- **边界：**该证据闭合 Consul 的 SQL outbox→worker→CAS→回读路径，但使用 SQLite 内存库，未覆盖生产 PostgreSQL/MySQL 与真实 Consul 同时组合、ACL/TLS、Nacos 写入/新建 key、实例 Reporter/Collector 接入及前端→Python 浏览器联调；B0.3 和最终 E2E 均仍未完成。当前总计 **69/98** 项完成，前端 **24** 项、后置后台 **5** 项待完成。

### 15.485 B0.3 PostgreSQL/MySQL SQL outbox 到真实 Consul 闭环（2026-10-10）

- **覆盖：**新增共享 opt-in acceptance helper，并接入 PostgreSQL/MySQL 真方言验收类。各自隔离数据库上创建随机账号/会话/版本，真实 SQL mutation 接受 publish 命令；正式 Consul worker claim SQL outbox、编码 frozen rule version、向本轮启动的随机 loopback Consul 执行 CAS-0 并精确读回；断言 operation/publication 成功、操作原因不泄漏，worker 重跑不增加 Consul `ModifyIndex`。通过后在 finally 清理随机 SQL 行和唯一命名容器。
- **验证：**隔离 PostgreSQL 16 + Consul 1.21.1、MySQL 8.4.11 + Consul 1.21.1：**2 passed in 5.08s**；SQLite worker/composition/Consul writer focused 回归 **32 passed, 2 skipped, 1 deselected**；`compileall` 通过。临时数据库与 Consul 容器均已停止；未访问共享数据库、已配置 Nacos/Consul 或真实部署服务。复现与边界见 [B0.3 跨 SQL 方言 Consul 验收](acceptance/R-SENTINEL-CONSOLE-B0.3-real-consul-sql-dialects.md)。
- **边界：**现在已覆盖 Consul 的真实 SQL outbox→CAS→read-back 组合（PostgreSQL/MySQL），不再把这一组合列为缺口；仍缺 Consul ACL/TLS 部署验收、Nacos 写入/新建 key、Reporter/Collector 运行接入、权威实例 inventory、前端→Python 浏览器联调与其它 PLAN-EXEC 崩溃窗口验收。B0.3、B0.5 和最终 E2E 保持未完成；总计仍 **69/98** 项，前端 **24** 项、后置后台 **5** 项待完成。

### 15.486 F7.6 非根 dashboard base path 的 API 404 边界（2026-10-10）

- **缺陷：**dashboard 部署在 `/ops/sentinel/` 时，根路径 `/api/*` 已由 Console JSON 404 handler 兜底，但误请求 `/ops/sentinel/api/*` 会被 SPA catch-all 返回 `index.html`（HTTP 200），使 API 路径错误看起来像成功的页面响应。
- **修复：**静态路由在 SPA fallback 前为 root `/api` 和 dashboard-prefix `/ops/sentinel/api` 同时注册精确路径与子路径拒绝路由；API 不会因部署前缀误差落入 SPA fallback。API 方法集合抽为单一常量，避免两组前缀规则漂移。
- **验证：**在 `components/sentinel/sentinel-console` 执行 `.venv/bin/pytest tests/test_static_web.py -q`：**4 passed in 0.23s**。新增断言覆盖精确 `/ops/sentinel/api` 与 `/ops/sentinel/api/not-registered` 均为 `404 not_found` JSON 且不返回 HTML/不缓存；现有根 API、prefix 页面/assets、deep link、slash redirect 仍通过。
- **验证扩展：**重新构建 Console wheel 到 `/tmp/sentinel-console-f7.6-package-20261010`，隔离安装到 `/tmp/sentinel-console-f7.6-installed-20261010`（`uv pip install --target ... --no-deps`），设置 `PYTHONPATH` 指向安装 target 后执行 `tests/test_static_web.py -q`：**4 passed in 0.33s**。证明 wheel 包含路由修复且无须 Node 才能通过该 ASGI 验收。
- **边界：**没有对安装后的 wheel 执行 Codex IAB 页面渲染，也未做 production launcher 或反向代理实测。因此 F7.6 保持未完成，完整 E2E 留到最终阶段。

### 15.487 B0.3 Nacos 3.2.4 gRPC update-CAS 真实验收（2026-10-10）

- **实现与缺陷修复：**新增显式 opt-in 的 `tests/test_nacos_rule_source_writer_acceptance.py`，只接受 `http://127.0.0.1:<port>` 并调用当前 production reader/writer。真实 Nacos 3.2.4 loopback 测试证明 Admin API seed、服务端 MD5 read、gRPC CAS update、精确 HTTP read-back 与 stale-MD5 冲突保护。测试揭露 Nacos 3.2.4 的冲突 envelope 为 `ConfigPublishResponse + resultCode=500 + errorCode=500 + 固定 CAS conflict message`，不符合 adapter 只识别旧 `errorCode=20005` 的假设；writer 现在识别上述精确错误形状，其他 500 不因此误判为 CAS conflict。
- **验证：**临时 `nacos/nacos-server:v3.2.4`（image digest `sha256:1c191c30c8cd5ff2a72bf576555dbaa57a616378c55168651a74aefadedf7708`）仅将 8848/9848 映射至 loopback 18848/19848，无挂载卷；合成 dataId 在 teardown 删除，容器在验收后移除。Opt-in 真实验收 **1 passed**，`tests/test_nacos_rule_source_writer.py` **10 passed**；普通 Nacos 500 仍分类为结果未知的负向断言也通过。可复现命令和 upstream CAS source 见 [B0.3 provider conditional-write 记录](acceptance/R-SENTINEL-CONSOLE-B0.3-provider-conditional-write.md)。
- **边界：**此验收关闭 Nacos auth，使用 plaintext gRPC；不代表生产认证/TLS、自定义 CA、集群一致性、create-only CAS、SQL worker composition 或实例级激活。SQL outbox → Nacos worker 后由 §15.488 补充验收；本节本身只证明 provider writer。B0.3 仍未完成；完整 E2E 仍留最终阶段。

### 15.488 B0.3 SQL outbox → Nacos 3.2.4 CAS worker 闭环（2026-10-10）

- **覆盖：**扩展现有 SQL mutation acceptance：先在 SQL 写入不可变 baseline version 和发布候选版本，再将 baseline 的 `SentinelRuleVersionJsonEncoder` 精确输出预置到本轮 Nacos config；以 Nacos server MD5 接受 publish command，运行正式 `create_nacos_rule_publication_worker`，验证 operation/publication 完成、provider 内容逐字节等于候选版本、回读 MD5 更新、reason 不泄漏，worker 重跑不产生第二次写入。
- **修正：**首次失败原因是 acceptance fixture 用任意 JSON 配置冒充“空 SQL 基线”，worker 正确将它当作外部配置漂移并返回 conflict。现由真实 SQL 基线版本和同一生产编码器生成 provider 初始值；没有放宽生产冲突检测。
- **验证：**`SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE=1 uv run --no-sync --extra test --extra nacos-grpc pytest -q tests/test_rule_mutation_store.py -k nacos_worker_publishes_sql_outbox_to_real_nacos`：**1 passed, 29 deselected**；`compileall` 和该文件 `git diff --check` 通过。测试自行启动 Nacos 3.2.4 disposable 容器，只绑定 loopback、无数据卷，并在 teardown 删除容器及唯一 config。详细边界见 [B0.3 条件写验收](acceptance/R-SENTINEL-CONSOLE-B0.3-provider-conditional-write.md)。
- **边界：**关闭的是 SQLite acceptance 下 SQL outbox → 现存 key gRPC CAS → read-back 的本地链路；未证明 Nacos create-only、PG/MySQL + Nacos、生产 auth/TLS/custom CA、provider side-effect 中断恢复或实例应用。B0.3 不勾，开放计数不变；未运行完整 E2E。

**B0.3 当前状态校准：**Consul SQL outbox→真实 provider 的 SQLite/PostgreSQL/MySQL acceptance 见 §15.484–§15.485；Nacos provider CAS 和 SQL outbox→worker→read-back 分别见 §15.487–§15.488。后续描述不再将“Nacos SQL worker 未验收”列作开放项。仍开放 Nacos create-only、Nacos + PostgreSQL/MySQL 联合、生产 TLS/auth、自定义 CA、provider side-effect 崩溃恢复，以及 Reporter/Collector 实例回执接入；因此不能勾完整 B0.3。

### 15.489 F4.24 登录页 demo/live 文案隔离（2026-10-10）

- **缺口：**通用 `login.description` 资源残留演示账号提示，且正式登录页此前没有展示这段说明，无法清楚表达 demo 登录使用合成身份、live 登录不应出现 demo 信息。
- **修复：**通用说明现在只描述登录后的控制台能力；新增三语 `login.demoNotice`，明确本地模拟、不连接生产服务/配置中心及演示账号。app 层 `ConsoleLoginRoute` 依据编译 profile 传递 `demoMode`，identity feature 只负责渲染对应文案；登录表单保留当前职责，无任何凭证写入存储。
- **验证：**`dashboard-prototype` 的 `node --test tests/i18n/catalog.test.mjs` **18/18 passed**，包含 zh-CN/en-US/ja-JP 实际 React SSR 比较 live/demo 分支；`npm run check:fast` 通过 typecheck、format、lint 与 Console OpenAPI **43 paths / draft-partial** check。`npm run build` 与 `npm run build:demo` 均成功，构建产物路由 chunk 分别确认为 `demoMode:false` / `demoMode:true`。后续 focused login SSR **1/1** 又锁定密码显隐按钮为 `type=button`、本地化名称和 `aria-pressed`。
- **边界：**没有启动浏览器、没有执行完整 E2E；未验证 production dist 的视觉呈现，也未连接 Python Console。键盘/辅助技术自动化、IAB mounted 和真实后端验证仍开放，F4.24 不勾；任务总计和 24 前端 / 5 后端开放计数不变。

### 15.490 B0.1 Consul 登记源只读连接检查真实服务验收（2026-10-10）

- **实现：**在既有 opt-in disposable Consul acceptance 和 loopback-only Nacos acceptance 中调用正式 `ConsulRegisteredSourceChecker` / `NacosRegisteredSourceChecker` 与 pinned HTTP transport，分别检查真实 KV key-list / blocking-query 和 Nacos Admin config-list 接口；对比探测前后合成规则配置值与 revision/checksum，确保探测不写规则。
- **验证：**Consul 探测 `1 passed`，Nacos 3.2.4 探测 `1 passed`；checker 与两个 provider writer acceptance 文件的非 acceptance focused 回归 **21 passed, 5 deselected**。Consul 使用测试自行启动的 `hashicorp/consul:1.21.1` disposable dev server 和随机 loopback 端口/key；Nacos 使用 `nacos/nacos-server:v3.2.4`、loopback `18848/19848`、无持久卷，测试生成并清理唯一 config，容器随后移除。既有 Consul KV 内容及 `ModifyIndex`、Nacos 配置值与 MD5 均未改变。
- **边界：**证明两个 provider 无认证模式的真实只读连接探测；Consul ACL/TLS 尚未验收。Nacos 真实凭证与 HTTPS trust-boundary 另见 §15.491，但那一项使用 TLS bridge，不证明 Nacos 自身 TLS listener 或部署 CA 装配。部署策略装配与 Dashboard→Python 浏览器 E2E 仍未验收；B0.1 保持未完成。

### 15.491 B0.1 Nacos 3.2.4 认证与 HTTPS trust-boundary 验收（2026-10-10）

- **修正测试路径：**原验收直接将 Nacos 凭证发往 HTTP，被现有 `RegisteredSourceTargetPolicy` 正确拒绝（认证模式必须 HTTPS）；没有放宽安全策略。改为使用本轮自建、仅 loopback 可达的 TLS bridge，bridge 将请求转发给本轮启动的 Nacos 3.2.4 auth-enabled disposable 实例。客户端为合成 hostname 生成匹配 SAN 的临时证书并通过注入的 `SSLContext` 明确信任；正式 pinned transport 仍执行 HTTPS 主机名验证、目标 allowlist 与 loopback DNS pin。
- **验证：**真实 Nacos admin 认证：正确凭证获得只读 `READ` 能力，错误密码稳定映射 `AUTHENTICATION`；两种结果均不泄漏凭证。自定义 TLS context 若不校验 peer 证书与 hostname 会拒绝；系统 trust store 和显式信任测试 CA 的校验 context 可用。`SENTINEL_CONSOLE_RUN_NACOS_AUTH_ACCEPTANCE=1 .venv/bin/pytest -q tests/test_registered_source_checker.py tests/test_registered_source_nacos_auth_acceptance.py`：**24 passed in 20.60s**；Python `compileall` 与目标文件 `git diff --check` 通过。Nacos 容器和临时 TLS 证书目录均由测试 teardown 清理，结束后无 `sentinel-nacos-auth-*` 容器残留。
- **边界：**TLS 在测试 bridge 终止，bridge 到 disposable Nacos 使用 loopback HTTP；因此证明真实 Nacos credential/login/read 行为经受信任 HTTPS client transport 可工作，但不证明 Nacos 原生 TLS listener、Consul ACL/TLS 或生产集群部署。私有 CA 环境变量及 composition 注入随后由 §15.492 补齐；B0.1 与最终 Dashboard→Python E2E 继续未完成。

### 15.492 B0.1 注册配置源私有 CA 部署配置与 HTTP composition（2026-10-10）

- **实现：**新增可选 `SENTINEL_CONSOLE_REGISTERED_SOURCE_ROOT_CERTIFICATE`，只接受绝对 CA bundle 路径，使用 `ssl.create_default_context(cafile=...)` 构造保留证书与 hostname 校验的 `SSLContext`，不暴露在配置 repr。first-run composition 将其传给 Nacos/Consul registered-source checker 和选定 publication worker 的 HTTP reader/writer；预配置数据库的 `build_sql_identity_app` composition 可注入同一类 context。`PinnedAioHttpJsonClient` 对自定义上下文再次校验 `CERT_REQUIRED + check_hostname`；无 CA 配置时继续使用运行环境 system trust。Nacos gRPC TLS 不由此环境项配置。
- **验证：**生成临时真实 PEM CA 并从环境解析，断言其进入校验 context trust store；覆盖相对路径拒绝与不泄漏路径、first-run checker composition、publication worker composition、预配置 SQL composition，以及 TLS context 禁止关闭 peer/hostname 校验。与真实 Nacos 3.2.4 auth-enabled HTTPS trust-bridge acceptance 联跑：**52 passed in 13.57s**；Nacos 正确凭证得到只读 `READ`，错误凭证映射 `AUTHENTICATION`；Python `compileall` 与改动范围 trailing-whitespace 扫描通过，测试容器 teardown 后无残留。部署说明已同步至 sentinel-console README。
- **边界：**未用真实部署挂载的 CA 文件连接生产 Nacos/Consul，也未验证 Nacos 原生 TLS listener、gRPC TLS、Consul ACL/TLS、Ingress 或集群 secret rotation；本地证据仅关闭 CA path→validated SSL context→HTTP composition 代码链。B0.1/B0.3 与最终 Dashboard→Python E2E 保持开放，98 项计数不因该切片改变。

### 15.493 F5.2 locale 数字格式器收敛与动态 key producer 覆盖修复（2026-10-10）

- **实现：**将分散于 overview、applications、rules、faults、system、charts 与 observation 的区域数字格式调用统一到 `shared/presentation/formatLocaleNumber.ts`，移除 overview/applications 中重复的单用途格式包装。补齐 `AccountDirectory` 动态状态限制文案 `t(statusRestriction)` 的 callsite manifest；对应 runtime suite 现在通过 Vite 实际加载 `accountStatusPresentation.ts` 并断言 built-in / last-admin producer key，而不只依赖 suite 名称存在。
- **验证：**`npm run test:i18n-tools` **37/37 passed**；`npm run test:logic:focused -- 'OBS|INCIDENT|F5\.2'` **17/17 passed**；`npm run check:fast` 通过 typecheck、format、lint 与 Console OpenAPI **43 paths / draft-partial** contract check。
- **边界：**这是共享数字格式及一个动态翻译 producer 的局部收敛，不代表动态 key、所有持草稿页面三语切换、日期/时区/DST 矩阵已经穷尽；F5.2 仍未勾，前后端开放父任务计数不变，完整浏览器 E2E 留到最终验收。
