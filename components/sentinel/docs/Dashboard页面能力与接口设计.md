# Sentinel Dashboard 页面能力与接口设计

> 文档状态：设计草案，未冻结 Console wire protocol。
> 日期：2026-10-07。读者：产品、前端、Python 管理服务开发者。
> 范围：11 个页面路由及其内部交互；不是现有功能的生产可用声明。
> 使用方法：先读共同边界，再按页面进入功能、数据、接口与验收条件。

## 0. 产品目标与主管来源

控制台帮助运维人员完成“发现异常 → 定位应用/实例 → 查看保护规则 → 安全调整 → 确认真实生效”，而不是仅显示一组菜单。

| 能力域         | 用户问题（来自既有产品需求）           | 用户结果                                         | 页面入口                       |
| -------------- | -------------------------------------- | ------------------------------------------------ | ------------------------------ |
| 运行观测       | 不知道压力、请求量、延迟和阻断如何变化 | 同范围、同时间轴的可解释观测与实例下钻           | 总览、应用与实例、实时监控     |
| 规则治理       | 内存修改丢失、规则难配置、大促后难恢复 | 完整快照写回配置中心、不可变版本、计划与生效跟踪 | 规则                           |
| 故障调查       | 有异常但缺时间线和上下文               | 可追溯事实、相关版本、指标窗口和下一步           | 故障分析                       |
| 控制面运维     | 无法区分浏览器、采集、配置源或服务故障 | 组件健康、覆盖、权限与审计事实                   | 系统管理                       |
| 安全启动与访问 | 首次无数据库、无管理员，或账户权限不清 | 一次初始化、安全登录、简单 admin/view 管理       | 初始化、登录、账户、角色、改密 |

本文主管**页面用例及页面数据需求**，不另建第二套已冻结协议。关联来源：

- [规则控制台与运行观测设计](DASHBOARD_CONTROL_PLANE.md)：产品总体边界、指标口径、配置中心写回与规则兼容 profile。
- [Console API 契约](CONSOLE_API_CONTRACT.md)：现有 Console 通信草案；后续收敛后的 wire 定义应在此维护，而非同时修改多份表。
- [初始化与身份 API](../dashboard-prototype/docs/api/IDENTITY_AND_ACCESS_API.md)：现有身份草案；账号/初始化需求作为输入，最终 wire 定义应归并到 Console 契约，保留本文件为阅读入口。
- [Agent Reporting envelope](protocol/reporting-protocol-01-envelope-v1.md)、[transport](protocol/reporting-protocol-02-transport-v1.md)、[freeze record](protocol/reporting-protocol-03-freeze-record-v1.md)：保持已有版本与冻结规则。
- [Cluster Token 协议](protocol/cluster-token-protocol-v1.md)：独立准入协议，浏览器不参与 Token 请求。

历史草案之间存在不一致；当前 F6 的唯一通信收敛入口为 `CONSOLE_API_CONTRACT.md` §9，旧 §0–8 仅保留沿革。本文接口/DTO 均为**页面需求投影**，不代表签字、已实现或已经对外发布；唯一 wire schema、示例和错误码落回该契约入口，不在本文件重复机器字段。

## 1. 共同边界与数据约束

### 1.1 前后端责任

```text
页面 UI → feature Hook/store → feature gateway（校验/映射）
                               ↓ Console API
Python 管理服务 → 控制面数据库 / Nacos、Consul 适配器 / 指标、事件查询
业务应用 → RuleSource 消费配置中心；Reporter 上报事实；Token Client 请求额度
```

前端拥有局部表单、选中项、展示、URL 观察上下文；后台拥有认证授权、规则校验、持久化、发布冲突、版本/计划执行、审计与真实聚合。不能把前端当前的本地模拟业务逻辑直接翻译成后台实现。

Nacos/Consul 持有当前生效规则；控制面数据库保存账号、审计、草稿、不可变版本、计划和发布记录。版本记录必须能重建候选完整快照，但它不是应用启动时的另一条权威 RuleSource。指标和事件不能无限塞入控制面数据库，也不由浏览器自行采集。

现有 `sentinel-dashboard` 是 Starlette/Jinja2 的 per-process 内嵌诊断服务。独立 Console 不因目录名相同就继承其鉴权/观测范围；新增服务目录和 Python 发布包的最终归属需在实现前确认。保留内嵌诊断兼容接口，不把 `/admin/rules/reload` 当作配置中心发布。

### 1.2 权限与入口状态

首版固定 `admin` / `view` 两个角色，不引入租户、组织树或审批角色。`admin` 管理规则和账号；`view` 仅查看允许的观测/只读信息，不执行任何编辑命令。个人改密与注销属于会话自助操作，两角色都可用，不算管理权限。

`metrics:view` 和 `rules:write` 是已有能力标识；账号、角色及管理审计由服务端检查 `admin`，不能用 `rules:write` 代替账号管理授权。客户端展示与后端逐请求鉴权必须一致；缺少指标权限时不请求受保护数据。

启动先查询 bootstrap，再恢复会话。状态 `unknown/loading/error` 不能默认当作已初始化或管理员。未初始化强制 setup；初始化完成禁止再次 setup；未认证进入 login；已认证按角色开放页面。初始化后的数据库暂时不可用是服务降级，不应重新开启 setup。

### 1.3 观察上下文、时间与缺失值

候选 `ObservationQuery`：`env`、可选 `appId/resource/instanceId`、`from/to`（RFC 3339 UTC）、`stepMs`、`scope`、`metrics`。相对窗口 `15m/1h` 先解析为明确 `[from,to)`；后台返回实际执行窗口，不能只改标签。具体参数名与既有 `app/window` 草案需统一后冻结。

页面 URL 已支持 `app/range/account/view/env/instance/resource/event/version/scope/q`；各页实际查询与下钻的消费者迁移仍待完成。`all` 是 UI 哨兵值，查询时省略 `appId`，不当作真实应用。未注册应用/实例显示不存在，不静默回落到另一应用的数据。环境目录来自后台，不能继续使用无操作的“生产”下拉框。

所有身份 ID 用字符串。时间用 RFC 3339 UTC，展示由 Intl/locale 与用户时区处理；大整数版本序号用十进制字符串，不按字典序比较。后台的原生配置索引、Console 版本 ID 与 runtime `(epoch,revision,checksum)` 分别命名，不互相代替。

### 1.4 共同 DTO 需求（候选字段，不是现有接口）

| 数据            | 字段与语义                                                                                                   |
| --------------- | ------------------------------------------------------------------------------------------------------------ |
| `Page<T>`       | `items/page/pageSize/total`；稳定排序与最大 pageSize。事件时间线可采用 cursor，不能伪装精确 total            |
| `Coverage`      | `expected/reported/unknown`、`asOf`、`inventorySource`；无权威实例目录时 expected 为 null，不宣称全量覆盖    |
| `MetricReading` | `value: number                                                                                               | null`、`unit`、`scope`、`source`、`sampledAt`、`window`、`quality`、`coverage` |
| `MetricSeries`  | `metric`、`unit`、`scope`、`source`、`window{from,to,stepMs}`、`points[{at,value}]`、`quality`、`coverage`   |
| `DataQuality`   | `available/not_integrated/no_samples/stale/partial` 与稳定 `reasonCode`；网络和鉴权错误独立处理，不混入 0 值 |
| `Annotation`    | `id/at/kind/bindingId/versionId/publicationId`；来自实际发布或生效记录，只画窗口内标记                       |
| `FieldIssue`    | `path/code/params`；前端按三语资源翻译，不直接展示厂商原始错误或字段名标签                                   |
| `ApiFailure`    | `error{code,requestId,issues?,retryAfterMs?}`；message 仅可为脱敏兜底，不是唯一判定依据                      |

DTO 不携带 ReactNode、函数、样式 tone、翻译后的单位字符串或 `seriesForRange`；界面 VM 与 wire DTO 分离。数据的名称可以是运维录入内容；系统产生的状态、建议、错误由稳定 code + params 翻译。

QPS、TPS、RT、阻断与 CPU 的口径沿用总体设计：没有业务事务埋点不展示 TPS；无 histogram 不展示可聚合 p95；host/container/process 不混用；分母为 0 时比率为 null。CPU/阻断 ratio 采用 0..1 的候选 wire 表达，由 mapper 转换为百分数。各实例的 p95 不取平均。实际 memoryBytes 与 limitBytes 同时提供才计算使用率。

### 1.5 HTTP、命令和流的共同候选策略

下文章节路径均相对于 `/api/v1`。为避免两份会话规范，候选沿用身份稿的 `/auth/*` 和 `/system/bootstrap*`；规则采用显式 `/rulesets/{bindingId}/*`，防止写错环境或配置项。现有 `/rules/publish` 等无 binding 路径尚无 Console 服务端实现，迁移决定仍需记录。

候选成功返回类型化 JSON（列表为 Page），失败按 ApiFailure，空成功为 204。现有改写计划的 `ApiResult<T>` 与之不同：必须在冻结时选择一种 wire 信封；如底座请求机制需要 ApiResult，gateway 可显式适配，不能两端各自猜测或直接强转。分页也只能冻结一种形状。

写操作按用途定义幂等，不机械要求登录和改密的响应被缓存重放：规则发布、版本、计划、初始化与账号创建使用 `Idempotency-Key`；同 key 不同 body 拒绝，用户超时重试查询原操作结果。自动重试要依赖服务端真实幂等保证，前端防重按钮不是保证。更新草稿/账号需带其独立的基线 revision；不能拿运行规则版本锁账号记录。

HTTP 错误至少区分 400 输入、401 会话、403 权限、404 不存在、409 冲突/重复初始化/最后管理员、422 语义校验或回读不一致、429 限速、503 控制面/依赖不可用。网络、超时、取消、协议解析失败属于客户端错误，不能统称配置中心不可用。

Cookie 会话需 HttpOnly/Secure/SameSite、CSRF 与 Origin 校验；跨源部署还需受限 CORS。密码、DSN、Token、引用解析结果、Authorization/Cookie 均不进入 URL、localStorage、日志或返回体。setup 应有部署侧一次性窗口/引导保护，不能被第一个匿名访问者抢占。

F6 反推补充：一次性 operator authorization code 通过本系统 setup 的启动授权字段输入，不放 URL 或本机持久存储；后台建立受限 bootstrap-operator Cookie，仅能检查/初始化/核查原操作。未获授权时不能向任意数据库/源执行连接检查。这个入口与四步配置分离但仍由唯一 bootstrap 身份 owner 管理，不引入默认 admin 或第二份会话 store。底座传输 adapter 内存持有的会话绑定 CSRF header 是防伪令牌、不是页面身份 DTO 或 bearer 登录凭证；该有限 header 交换是“响应不回读业务秘密”的明确安全例外。

OpenAPI 的 `security` 明确区分身份 Cookie 与 CSRF 证明：`anonymous` 表示无 session cookie 或可选 `BrowserSession` 均可；需要 CSRF 的操作在每个身份候选上再要求 `CsrfCookie`，并仍显式要求 `x-sentinel-csrf` header。因此首次登录不要求已有登录 session，但必须先由 bootstrap 获取配对 CSRF cookie/header；`GET /auth/me` 可无 cookie 并返回匿名状态。CSRF cookie 与 header 是双提交校验的两个部分，不可把 CSRF Cookie 单独视作用户认证。

实时可以先采用参数化轮询；SSE 是后续等价通道而非必须先做的底座。选 SSE 时冻结鉴权、event/id、heartbeat、序列去重、断线重取和过期处理；该流是 Console 读模型，不修改 Reporter 的已冻结事件协议。

## 2. 总览 `#/overview`

### 2.1 功能与交互

回答“哪个应用需要关注，变化和保护行为是否同步”。显示异常摘要、配置源健康/规则覆盖、QPS/阻断趋势、应用状态表。选择具体应用下钻应用页；时间切换重新查询对应窗口；点击应用表行/异常入口保留环境与时间；发布标记进入规则版本或发布记录。

### 2.2 页面数据

`FleetOverview`：`asOf/window/coverage/attention/applications/connectionSummary/annotations`。
`attention` 含总应用数、关注数、关注 appIds 与 `reasonCode/params`；无关注项时不可下钻未定义 ID。
`ApplicationSummary` 含 `appId/name/health/healthReasons/instanceCoverage/ruleDelivery` 与 HTTP QPS、RT p95、阻断率、实例平均 CPU/内存的 MetricReading。CPU 平均值须声明分母和采样覆盖，不标为宿主机 CPU。
总览卡片与曲线共享所选 `env/app/window/scope` 的同一 MetricBundle；应用目录行的指标绑定各自行内 `appId` 的 application scope，不得将 fleet 汇总复制到每个应用行。TPS 未接入/无样本必须保留 null 与质量状态，覆盖率与读取时间随指标一起展示。

发布标记与曲线对照使用同一份 `FleetSnapshot.metrics`：该 `MetricBundle` 必须与 `FleetSnapshot.query` 的 scope、时间窗、指标集、采样步长一致，且与快照 `asOf` 对齐；`series` 携带实际样本和口径元数据，`annotations` 携带窗口内的 publication identity 与事件时间。它足以绘制真实曲线和发布竖线，不需要复制一份 pairwise comparison DTO。页面不得把时间相关性表述为发布导致的因果结论。

“发布前后数值/变化率”是独立产品能力，不得按窗口名称、固定示例或前端自行挑选的最近点伪造。若后续确认要展示这类数值，F6.1 必须先冻结服务端选择样本的规则（严格事件前/后的样本、最大时间距离、指标 source/denominator/coverage 可比性、缺样本状态及是否允许显示变化率），再决定是否需要独立 DTO；缺少可比样本时只展示未提供/不可比较，不补零或估算。当前正式页面仅画同窗 series 与 annotation，不展示独立的发布前后数值卡片。

| 动作       | 候选接口                                      | 结果与责任                                                  |
| ---------- | --------------------------------------------- | ----------------------------------------------------------- |
| 首屏/刷新  | `GET /fleet/overview?env&from&to`             | 同一观测时点的摘要；后台完成范围与聚合                      |
| 应用表分页 | `GET /applications?env&from&to&page&pageSize` | Page<ApplicationSummary>；统计不是当前页行数                |
| 趋势窗口   | `GET /metrics/query`                          | MetricSeries[] + Annotation[]；禁止浏览器由累计值造 QPS     |
| 下钻       | 无写接口                                      | 导航传 appId/env/window，发布标记传 publicationId/versionId |

### 2.3 当前实现与验收条件

正式 hash 路由已加载 `FleetOverviewContainer`，通过应用 Console transport 装配 `FleetPort` 和目录 Port；`FleetOverviewPage` 组合查询编辑器、上下文/刷新、摘要、连接探测、`MetricCharts` 与分页目录。旧 `FleetTrendPanel` 不再是正式页面消费者，不能作为正式路由的视觉或 E2E 证据。后台仍需负责同一环境/应用/实际窗口的聚合与筛选；当前契约是 draft-partial，真实 Python 联调尚未完成。

新模型的窗口为内部 UTC epoch 毫秒 `[fromMs,toMs)`，F6 adapter 再转换为唯一 RFC3339 wire。query key 包括 owner、环境、应用、实例、资源、scope、窗口、采样步长、搜索及页码；scope/单位/返回 query 不匹配应报协议错误，不借另一应用数据。MetricReading/MetricSeries 明确 source、denominator、coverage、quality；QPS/资源调用率/TPS 是独立指标，比率只在展示转成百分数，TPS 未接入不补 0，p95 不由前端平均。点列至多 1000 点、窗口至多 7 天，缺测保持 null 间隙；窗口内事件不必恰好落在采样点才绘制。

全范围应用数/关注数与筛选结果总数/当前页行数分开；下钻只能使用显式目标，并携带精确 from/to，不重新算“最近 15 分钟”。连接探测呈现其自身探测时间，不等于所选应用流量或规则已生效。新入口目前未装配实际 App、HTTP 或 Python；纯负例与浏览器 Port 测试的完成状态见推进清单，不据此宣称真实聚合已实现。

目标验收：空目录、无权限、部分覆盖与依赖离线分别可辨；摘要/表格/曲线同范围；窗口外不画发布标记；具体应用下钻后不出现别的应用实例。此处仅定义预期，未执行真实验收。

## 3. 应用与实例 `#/applications`

### 3.1 功能与交互

回答“问题在哪个实例、哪个采集层”。应用摘要与规则覆盖 → 宿主机分组矩阵 → 所选实例详情。可筛异常、折叠宿主机、选实例、切 host/container/process、切时间、跳规则。异常筛选不改全应用分母；选中实例从完整目录解析，过滤隐藏不等于实例删除。

### 3.2 页面数据与接口

`InstanceSummary`：`instanceId/appId/env/hostId/containerId/processId`、`processEpoch`、`lastReportAt/status/healthReasons/supportedScopes`、`ruleDelivery`、指标摘要。pid 仅展示；实例重启需识别新进程 incarnation，旧进程回执不能证明新进程已加载。
`InstanceCatalog`：Page<InstanceSummary> + 全范围 coverage/异常计数；分页后不要仅按一页分组假装完整宿主机拓扑。
`InstanceDetail`：身份、scope、MetricSeries[]、已加载规则版本、保护规则摘要。

| 动作          | 候选接口                                                             | 结果                                             |
| ------------- | -------------------------------------------------------------------- | ------------------------------------------------ |
| 应用目录/摘要 | `GET /applications`、`GET /applications/{appId}`                     | 目录与所选应用读模型                             |
| 矩阵/异常筛选 | `GET /applications/{appId}/instances?env&statusFilter&page&pageSize` | 应用限定的实例集合 + 未过滤分母                  |
| 实例详情      | `GET /instances/{instanceId}`                                        | 身份、supportedScopes、规则回执                  |
| 层级/时间曲线 | `GET /instances/{instanceId}/series?scope&from&to&stepMs`            | MetricSeries[]，未接入层级不复制另一层数据       |
| 查看规则      | 导航规则页                                                           | appId/env/bindingId/resource，避免打开不相关规则 |

### 3.3 当前实现与验收条件

旧 App 保留演示矩阵/详情直至 F6，一般应用没有借用订单实例样本；该路径的 scope 与保护阈值仍是示例，不能当作正式数据合同。新增内部 `applications/observation.ts`：InstancePort 分别提供实例目录和显式详情，资源拥有者、查询校验、筛选、宿主机分组、加载回执及指标展示已按职责分离，不增加 FixtureGateway 方法。

目录查询包含环境、可选应用、实际窗口、页码、搜索及异常筛选；全范围实例数/关注数与过滤总数、当前页行数分开。宿主机分组仅标当前页，进程级摘要不会冒称容器或宿主机指标。应用选项由 app 注入目录，实例行不得反过来充当完整应用目录；真实目录装配仍待 F6。

所选详情独立于分页/异常筛选，隐藏一行不意味着实例不存在，也不自动改选首行。环境/应用/窗口不匹配时不渲染旧详情。详情查询和返回均绑定 instanceId/appId/environmentId/processEpoch/scope/step/window；进程更换不能借旧数据。加载回执的 processEpoch 必须匹配，applied 还要求 desiredVersionId 等于 appliedVersionId 且有收到时间；发布/回读成功不能替代该回执。

普通断网/超时保留同 query 的 last-known-good 并标陈旧；权威 404/410 则清空已知旧目标，不能显示旧加载回执。服务端确认进程 incarnation 更换时也清旧详情，要求用户刷新目录再显式选择当前进程；不存在“自动改选其他实例”。内部失败码及最终 HTTP 形状在 F6 固化，不能把所有 409 都无差别当作实例重启。

supportedScopes 由实例事实给出，所选不支持层级返回显式 metrics=null；支持层级须提供完整且匹配查询的 MetricBundle。缺失实例为明确读错误，不能用另一对象填补。新页面目前只在内部 Port 浏览器探针中验证，未接 HTTP/Python。完整目录摘要、规则绑定定位及故障下钻仍需后续闭环；不能据此提前勾选 F4.04–06。

目标验收：应用切换只显示自身实例；选中项不存在展示明确空态；host/进程不支持展示“未接入”；QPS/阻断双轴单位正确；列表、详情与规则回执中的 instanceId/processEpoch 一致。

## 4. 规则 `#/rules`

### 4.1 功能与交互

回答“配置从哪里来、影响谁、如何安全改动并确认生效”。应用/环境/绑定 → 类型/资源搜索目录 → 检视/草稿 → 五类专用表单/JSON 预览 → 服务端校验/差异 → 固化版本 → 发布/生效跟踪。版本计划负责指定期间使用某个版本及明确恢复版本。

**当前可观察动作**：搜索、类型筛选、选择规则、复制本地草稿、编辑字段、本地校验、JSON 预览、查看示例版本。创建版本按钮仅输出预览提示。**目标待补动作**：新建/删除或停用规则、持久草稿、差异确认、发布、回滚、生效回执、计划创建/取消；不能把它们记作已实现。

### 4.2 绑定、快照与版本数据

| 对象                 | 字段与不变量                                                                                                                            |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `RuleBinding`        | `bindingId/appId/env/ruleType/sourceId/profile/activeVersionId` 与脱敏的配置定位摘要；一个绑定同一时刻只有一个写入目标                  |
| `RuleRecord`         | `ruleId/ruleType/resource?/definition`；System 无 resource。ruleId 是管理身份，不擅自写入兼容规则对象                                   |
| `RuleSetSnapshot`    | `bindingId/profile/ruleType/rules[]/version/nativeRevision/asOf`；rules 为整组，读取空数组与读取失败不同                                |
| `RuleDraftRecord`    | `draftId/bindingId/baseVersion/draftRevision/rules[]/updatedAt`；数字输入可以暂为空文本，提交 DTO 必须解析为有限数值                    |
| `RuleValidation`     | `validatedChecksum/profile/isPublishable/issues[]/targetCapabilities`；一次结论仅对同一内容及同一目标有效                               |
| `RuleDiff`           | `baseVersion/candidateChecksum/changes[{ruleId,path,operation,before,after}]`；新增/删除/禁用均可解释                                   |
| `RuleVersion`        | `versionId/baseVersionId/bindingId/checksum/createdAt/createdBy/name/note/ruleCount/profile`；内容不可变，是否 active 来自绑定/发布事实 |
| `Publication`        | `publicationId/bindingId/targetVersionId/baseVersion/progress/result/createdAt`；每阶段独立事实与脱敏失败原因                           |
| `ApplicationReceipt` | `instanceId/processEpoch/loadedVersion/checksum/appliedAt/status/lastReportAt`；未知不是成功                                            |
| `ActivationPlan`     | `planId/bindingId/versionId/activateAt/deactivateAt?/restoreVersionId/timeZone/state`；目标版本不可变，时间转换有明确 IANA 时区         |

runtime RuleVersion 三元组与 Console versionId 必须可映射，但不能直接采用页面示例字符串代替 checksum/epoch。源切换纳入绑定/发布状态，不靠 provider 字符串比较版本。

### 4.3 五类表单合同

兼容字段语义由总体设计 §4.3 主管；这里记录页面交互与后端校验需求：

| 类型      | 输入/条件交互                                                                                                                      | 后端必查                                                                 |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Flow      | resource/limitApp/grade/count/strategy/controlBehavior；非直接 refResource、warm-up 时间、排队上限；clusterMode 条件 clusterConfig | 有限数、枚举/单位、条件组合、关联资源/调用链支持、集群失败策略与资源上限 |
| Degrade   | 策略切换改变 count 单位；timeWindow/minRequestAmount/statIntervalMs；慢调用 slowRatioThreshold                                     | 比率与计数范围、整数约束、窗口、最低样本与目标 runtime 支持              |
| System    | 五个可启用阈值；禁用用 -1，CPU ratio 显示与序列化转换                                                                              | 至少一项启用、各项范围、CPU 0..1、采样能力                               |
| Authority | resource、origin 列表、黑/白名单；说明未匹配来源的行为                                                                             | origin 规范化/分隔符、枚举、可信来源识别能力                             |
| ParamFlow | resource/grade/count/durationInSec/paramIdx；例外项增删与 classType/object/count                                                   | 非负整数索引、有限阈值、窗口、例外值类型与跨语言 codec 支持              |

Nacos 和 Consul 都是存储/分发载体，**不会因为使用 Consul 就不支持 clusterFlow 或参数例外**。执行能力由 runtime/codec/profile/部署拓扑决定；存储能力另分 CAS/history/watch/read/write。未支持的字段或未知字段必须拒绝发布，不能删掉后继续写。兼容 profile 的配置正文是同类 JSON array；浏览器不加 `{rules: ...}` / `{Rules: ...}` 厂商包装。

旧 demo JSON 预览仅 `[draft]`；新内部工作台已经展示完整同类候选数组，保留未编辑规则，显式支持空数组清空。后台仍须核对当前绑定基线、完整校验和原子条件；前端完整预览不能替代后端保护。一个 binding 单次原子写；多个类型/binding 的联合发布不能承诺跨 Nacos/Consul 原子性，应逐绑定显示部分成功。

### 4.4 交互接口候选

| 用例           | 接口                                                              | 请求 → 返回                                                                       |
| -------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| 绑定目录       | `GET /rulesets?appId&env&ruleType`                                | → Page<RuleBinding>                                                               |
| 创建绑定       | `POST /rulesets`                                                  | admin + Origin/CSRF + Idempotency-Key；精确 source revision + Nacos/Consul target → RuleBinding；只写控制面绑定/target 元数据，不写规则正文 |
| 权威快照       | `GET /rulesets/{bindingId}/snapshot`                              | → RuleSetSnapshot                                                                 |
| 草稿列表/新建  | `GET/POST /rulesets/{bindingId}/drafts`                           | 新建带 baseVersion/rules → RuleDraftRecord                                        |
| 草稿读/存/删除 | `GET/PATCH/DELETE /rulesets/{bindingId}/drafts/{draftId}`         | 更新带 draftRevision/rules；冲突不覆盖                                            |
| 服务端校验     | `POST /rulesets/{bindingId}/validate`                             | 完整 rules/profile/baseVersion → RuleValidation                                   |
| 差异预览       | `POST /rulesets/{bindingId}/diff`                                 | baseVersion + 候选 rules → RuleDiff；避免规则正文进 GET URL                       |
| 固化/列版本    | `POST/GET /rulesets/{bindingId}/versions`                         | draftId/draftRevision/name/note → RuleVersion；固化不等于发布                     |
| 历史快照       | `GET /rulesets/{bindingId}/versions/{versionId}`                  | → 不可变版本内容                                                                  |
| 发布/查记录    | `POST/GET /rulesets/{bindingId}/publications`                     | targetVersionId/baseVersion/reason → Publication；写/回读，不阻塞等待所有实例     |
| 查询发布结果   | `GET /rulesets/{bindingId}/publications/{publicationId}`          | → 阶段进度/失败与目标身份                                                         |
| 逐实例生效     | `GET /rulesets/{bindingId}/publications/{publicationId}/receipts` | → Page<ApplicationReceipt> + Coverage                                             |
| 回滚           | 同一个 `POST .../publications`                                    | 旧版本作为内容目标、当前版本作为基线，生成新发布/runtime 版本，不倒退运行版本序号 |
| 建立/查计划    | `POST/GET /rulesets/{bindingId}/activation-plans`                 | versionId/时间/restoreVersionId/timeZone → ActivationPlan                         |
| 取消计划       | `POST /rulesets/{bindingId}/activation-plans/{planId}/cancel`     | plan revision/reason → 状态；已启动动作不能伪装从未执行                           |

以上是完整功能所需候选，不要求一次实现所有接口。保留旧 `/rules/rollback` 还是采用统一 publications，用冻结记录选择一种公开入口，不能重复形成两条发布业务逻辑。

创建绑定请求只接受 `requestKey/bindingId/environmentId/appId/kind/profile/sourceId/sourceRevision/target`。`target` 是严格 provider 联合：Nacos 仅允许 `provider/namespace/group/dataId`，Consul 仅允许 `provider/datacenter/key`；来源名称、provider、revision 必须由已登记来源行验证，不能由浏览器声明来源标签或任意 endpoint。绑定元数据、精确目标、幂等回执及 `rule-binding-create` 审计在同一关系库事务提交。相同 actor/session、幂等键和内容重复提交返回原绑定；同键不同内容返回 `idempotency_conflict`，重复环境/应用/类型或来源 revision 冲突返回 `conflict`。该命令不探测配置中心、不创建规则数组，也不隐式选择默认来源。

### 4.5 发布、计划与失败语义

必须分开“校验通过 → 配置中心写入成功 → 回读一致 → 实例已加载”。发布失败返回 publicationId、已发生阶段与重查入口；写超时为结果未知，不能自动重写或当作未写。回读不一致时不把它显示为 matched，更不自动覆盖外部修改。

后台每次发布检查 binding 和当前基线，Consul 使用真实 CAS；Nacos 无等价原子条件写时只能重读比较并限制写者，不能宣称相同保证。草稿切规则、切绑定或离开页面前提示未保存；后台更新 active snapshot 不自动冲掉本地 dirty 草稿。

计划须持久化，由后台调度：检查时间先后/时区歧义、重叠窗口、目标版本、明确恢复版本；重启后恢复、幂等执行，遇到外部新配置进入 blocked，不盲目回退。当前 Cluster 额度变更需重启的限制必须单列“待重启”，加载规则回执不证明新额度已执行。

### 4.6 当前实现与验收条件

已完成五类相关草稿联合、条件字段与本地边界校验，以及完整规则集的纯新增/修改/删除/物化模型；编辑一条保留其余记录及源基线，临时表单 key 不冒充管理身份。规则标识按字面保留；来源列表/参数类型只做已明确的规范化。空规则集是显式整组候选，不等于读取故障。

新增内部 `RuleSetPort`、不可变内容版本/独立发布三阶段/逐实例回执/活动计划模型，以及绑定当前 session 的 `createRuleOperation`。命令结果未知时禁止重发，仅查询原 requestKey；必须核对绑定、目标、版本/修订和整组内容才能解除未知状态。配置中心回读一致不证明丢失的写回执已经收到，也不证明实例加载；旧进程的回执不能算当前进程生效。

计划包含明确恢复版本、UTC 起止和 IANA 时区；本地时间的缺失/歧义不隐式选取时间点。浏览器只校验和显示，不执行定时发布。

内部 `RuleSetWorkbenchPage` 已实现整组编辑、记录新增/删除、保存/删除持久草稿命令、JSON/差异/校验、保存后固化版本的 Dialog。动作栏、表单、报告和反馈分别维护；源刷新不冲掉 dirty，编辑后旧校验/差异立即取消并失效；未知写入仅核查原操作，Dialog 内也有核查入口。失败保留可修正输入，撤权卸载本地确认意图。Astryx 数字框的实际 blur/Enter 提交边界已由浏览器测试覆盖，提交新值后不能固化旧校验内容。

新增内部 `RuleDeploymentPanel` 把版本内容、发布校验/写入/回读阶段、实例加载回执、后台计划分开读取和展示；发布/创建计划/取消计划使用共享 DialogFrame。发布弹窗固定捕获目标与源基线，期间源变更要求重新确认，不自动接受新基线；回滚是选历史内容创建新发布，不倒退运行身份。目标/恢复版本都须显式，重复本地时刻显示 UTC 选择，缺失分钟不能提交；待重启不计入生效覆盖。取消只针对待执行/阻塞计划，不暗示恢复已发生的发布。

页面已在 StrictMode 下做实际控件、320px 日文与桌面截图验证，仍**没有接入 App 正式路由或 HTTP/Python**；绑定/草稿目录和未保存跨页保护待后续闭环。旧 demo 的本地 workbench/`VersionPlan` 仍待替换，不能把内部 Port 测试计作数据库持久化或真实发布验收。

对接风险已按实际源代码核查：当前 `sentinel-source-nacos/codec.py` 并非五类 Java-compatible profile 的完整实现。Flow 使用 `scope/scopeReference` 而非 `strategy/refResource`；Degrade 对 count 取整数、从 exceptionRatio 取比例且 timeWindow 按毫秒；System/Authority/ParamFlow 也有不同字段语义。F6/B0 必须提供明确 profile/能力校验与转换，或拒绝不支持的字段；禁止沿用该 codec 的兼容性注释作为验收证据，禁止删字段后假报发布成功。Nacos/Consul 存储差异不能替代 runtime 能力校验。

目标验收：两配置源读/写/冲突/离线；编辑一条保留整组其他规则；非法字段不落盘；同幂等键不重复发布；外部变更不被覆盖；未知实例不算生效；计划服务重启继续且不覆盖新日常配置；view 深链/API 均不可写。

## 5. 实时监控 `#/realtime`

### 5.1 功能与交互

同时间轴展示 HTTP QPS、RT p95、阻断率、CPU/内存，配摘要和发布标记；选择窗口/指标，暂停或恢复刷新，下钻应用或故障。图表暂停只是停止展示刷新/订阅，不暂停采集、更不影响限流。

### 5.2 数据与接口

`RealtimeBundle`：`query/window/asOf/summary: MetricReading[]/series: MetricSeries[]/annotations/streamStatus`。
`StreamStatus`：`mode/liveState/lastFrameAt/quality/paused`。实时连接状态与浏览器 online 独立；UI 指标筛选可以本地隐藏已取得序列，若减少请求则缓存键需含 metrics。

| 动作          | 候选接口                                    | 结果                                              |
| ------------- | ------------------------------------------- | ------------------------------------------------- |
| 历史窗口/摘要 | `GET /metrics/query`                        | 同窗口 summary/series/annotations                 |
| 实时刷新      | 同查询轮询，或 `GET /metrics/stream`（SSE） | 返回已聚合 Console 点，不是原始累计 registry 快照 |
| 暂停/恢复     | 无写接口                                    | 取消订阅/停刷新，恢复重新补齐当前窗口             |

SSE 候选 `id` 为不透明游标，`event` 区分 metrics/heartbeat/reset/error，data 是类型化帧；断线不保证无限历史回放，游标过期须重查。帧重复/乱序按序列身份处理；切筛选取消旧流，旧窗口帧不可写新缓存；窗口有界且卸载释放。具体帧 schema 待 Console 协议冻结，不复用 Reporter wire 的业务事件名。

### 5.3 当前实现与验收条件

旧 App 仍是静态 fixture 游标回放，F6 会统一退役，不把旧 `StreamStatus` 宣称成真实网络状态。新内部入口 `realtime/monitoring.ts` 已新增 `RealtimePort`、`RealtimeSelection`、`RealtimeMonitor` 与 `LiveMonitoringPage`；后者只组合控制条、状态条、同窗摘要与曲线。选择应用/指标会重新查询当前监控页，不再隐式下钻应用页；实例/scope 选项待应用目录能力共同接线，完整 F4.11 尚不能勾选。

轮询先行，不增加未经验证的 SSE 协议。底座 PollingStore 提供无 overlap 的 tick，QueryResource 提供有界超时、AbortSignal 与过期响应隔离；默认 5 秒、允许 100ms–60s 的显式间隔，每个 tick 只有一次只读尝试，无隐藏重放。调度 store 不持有第二份指标缓存，保留至多一个校验通过的窗口包，至多 1000 点/序列，恢复是重新取数而非循环历史游标。

`windowMode=fixed` 保持实际 UTC 窗口；`rolling` 以最初窗口的时长/选定对象作为稳定逻辑 owner，每次读取用当前时钟形成独立的具体 MetricQuery/HTTP key。旧可信值保留自身 `query.window/asOf`，不能在刷新失败时改成新的时间假装新鲜；页面上下文与卡片/曲线均取这份值实际的窗口。暂停只停止浏览器读取并取消 pending，不通知采集器或 Engine；恢复立即读取最新窗口。切身份/撤能力首个发布清数据、停止 tick；改变环境/应用/指标/范围会取消旧 owner，迟到值不能写回。

新入口目前通过内部 Port 逻辑和实际页面浏览器测试，未装配 App、HTTP 或 Python。准入、指标采集/真实聚合、在线状态与后端断网验收仍需 F6/B0；不从浏览器 online 认定 Collector 健康。具体失败与验证证据在推进清单更新。

目标验收：无 histogram/TPS 埋点不造值；窗口与卡片一致；断线显示旧数据时间不伪装新鲜；恢复去重/补齐；暂停不导致无界缓存；权限拒绝不画空流量。

## 6. 故障分析 `#/faults`

### 6.1 功能与交互

环境/应用/实例/时间/严重度/类别筛选 → 事件统计与倒序时间线 → 显式选中事件事实/建议 → 打开相关应用、实例或规则版本。选定的环境、应用、实例和时间构成统计范围；severity/category/cursor 只缩窄列表，不改变该范围的统计；统计不能只数当前页。相关性不代表因果，建议动作不自动修改规则。

### 6.2 数据与接口

`IncidentSummary`：`incidentId/occurredAt/receivedAt/severity/category/appId/env/instanceId?/processEpoch?/sourceEventId?/publicationId?/titleCode/params`。
`IncidentEvidence`：有限结构化观察事实、证据完整度和可读目标投影；事件关联规则采用 `relatedRule:{environmentId,appId,bindingId,versionId,publicationId}|null`，均为服务端规则/审计数据的权威 opaque identity，并必须与事件所属环境和应用一致；客户端不从标题、规则正文或应用名称推断。原始异常消息、traceback、frame locals 不进页面/协议。

| 动作   | 候选接口                                           | 结果                                                        |
| ------ | -------------------------------------------------- | ----------------------------------------------------------- |
| 统计   | `GET /incidents?environmentId&appId&instanceId&from&to&severity&category&cursor&pageSize` | 响应携带当前环境/应用/实例/时间范围统计；不受 severity/category/cursor 影响 |
| 时间线 | 同上                                                | 稳定倒序、服务端游标分页；同时间用 incidentId 作次排序；返回查询回显、filteredTotal 与 nextCursor |
| 证据   | `GET /incidents/{incidentId}/evidence?environmentId&appId&instanceId&from&to&severity&category` | 按事件 ID、实例范围和活动筛选读取 IncidentEvidence + 有界关联事实；明确 complete/partial/unavailable |
| 规则版本/发布审计 | `GET /rulesets/{bindingId}/versions/{versionId}` 与 `/publications/{publicationId}` | 从证据的精确 `relatedRule` 下钻；发布 receipts 继续使用规则页自己的分页读取，不把 incident 事件当作发布成功证明 |
| 趋势对照 | `GET /metrics?...&from&to` | 使用事件同一 app/instance/window 查询独立指标序列；事件与管理事实只作时间相关标记，不做因果推断 |
| 下钻   | 无写接口                                           | 保留事件窗口与 app/instance/event/version/publication；缺少确切目标时不渲染无效动作 |

category 是 Console 聚合分类，不增加 Reporter V1 event_kind。采集事件与发布审计用 sourceEventId/publicationId 关联去重；收到时间和发生时间分开，迟到/客户端时钟偏差可观察。存储保留期须由选定事件后端声明，暂不承诺无限历史。

### 6.3 当前实现与验收条件

旧 App 的 Timeline/Evidence 仍按演示 date/HH:mm:ss 与固定窗口工作，最终替换在 F6。新增 `faults/observation.ts` 内部入口：`IncidentPort`、IncidentQuery/Page/Evidence 值对象、两个身份绑定读 owner，以及正式页面/筛选/时间线/证据组件。该页复用应用 feature 的授权实例目录 Port；实例选择将 `(environmentId, appId, instanceId)` 与 `process` scope 写入可分享 URL/query，不通过用户输入任意实例标识。HTTP/mock 按实例作用域过滤；IAB 验收了实例切换、筛选联动、刷新恢复和两页游标。真实 Python Console 与生产事件源仍未联调。

内部事件时间采用 UTC epoch 毫秒，发生时间限定观察窗 `[from,to)`，收到时间独立允许迟到或时钟偏差；不得用接收时间代替发生时间过滤。倒序按 occurredAt、同时间按 ID 代码点排序，前端校验但不在分页后重排。全范围统计与 severity/category 筛选结果、游标页分开；nextCursor 不重复当前 cursor，空页不能继续循环游标。

标题/事实是有限、类型化的 code 参数联合，由呈现层三语映射，不接收任意原始异常/业务日志作标题。证据单列 source/at 与完整/部分/不可用状态，有界 100 条；建议仅提供存在的只读实例/指标/规则视图目标，没有自动修改或根因断言。Console 分类不改变 Reporter V1 event_kind。F6 冻结 JSON wire 时还须对额外字段、内容长度和来源脱敏实施运行校验，内部 TS 类型与语义谓词不是网络解码器。

页面显示当前选定环境/应用/实例/时间范围的统计、筛选结果总数与本页数量，过滤无结果仍保留范围统计。统计独立于 severity/category/cursor。选择事件是显式操作；游标翻页不替换或重复加载所选证据，改变环境/应用/实例/时间/级别/类别会清除选中事件并把 cursor 复位。游标只是不透明分页位置，不能由客户端算偏移或重排服务端页。收到时间、发生时间、读取时间、来源事件与发布记录各自展示；证据的 `relatedRule` 必须匹配事件 publication/version identity，规则导航定位到对应 binding/version/publication 的独立只读读取投影；趋势导航使用同 app/instance/UTC 窗口并以事实标记作时间对照，不展示根因断言。明确 404/410 清除旧证据，普通断网保持同 query 陈旧事实且安全提示；撤权首个通知清全部事实/统计。前端 mock 与 IAB 验收见 F4.14 记录；真实指标/规则/发布 API、Python Console 与生产网络仍需验收。

目标验收：跨日/时区/迟到时间正确；分页不改变总统计；同事件不重复统计；关联查不到明确不可用；展示“观察事实”而非未经证明的根因。

## 7. 系统管理 `#/system?view=...`

### 7.1 功能与交互

五子视图：connections、permissions、protocol、accounts、roles；账号/角色复用第 10/11 章，不另写一套逻辑。普通系统面板只读，setup 的初始登记与凭证录入不因此被取消。

- 连接与采集：配置源、指标查询后端、Collector 真实连通性、最近探测、延迟与覆盖。
- 权限与审计：当前会话能力、服务端固定角色、真实操作记录；不能用四步说明图冒充审计查询。
- 协议与版本：Console/Reporter/Cluster 的支持版本和安装/配置状态，区分未配置、不兼容、降级、运行。

### 7.2 数据与接口

`ConnectionStatus`：`connectionId/kind/provider?/state/checkedAt/latencyMs?/coverage?/capabilities/reasonCode`；kind 与状态为协议枚举，毫秒不是“123 ms”字符串。
`SystemCapabilities`：runtime profile 支持、存储 CAS/history/watch 与 source 身份分开；不带写凭证。
`AuditEntry`：`auditId/at/actorId/action/targetId/result/requestId/publicationId?`；可按角色和操作追溯，不携带原始 payload。
`ProtocolStatus`：`component/supportedVersions/activeVersion/compatibility/state`；静态协议知识与实时组件状态不是一份事实。

| 用例           | 候选接口                                         | 授权                                                              |
| -------------- | ------------------------------------------------ | ----------------------------------------------------------------- |
| 连接/覆盖      | `GET /system/connections`                        | 已登录，敏感部署信息脱敏                                          |
| 能力与角色声明 | `GET /system/permissions`、`GET /roles`          | 当前用户可读；非任意自定义角色                                    |
| 管理审计       | `GET /system/audit?from&to&action&page&pageSize` | admin                                                             |
| 协议/版本状态  | `GET /system/protocols`                          | 已登录                                                            |
| 已登记配置源   | `GET /system/sources`                            | admin；仅返回来源 ID/修订及脱敏连接元数据，不返回凭证或引用值     |
| 测试候选连接   | `POST /system/sources/check`                     | admin + CSRF；只探测连接/读/条件写/watch 能力，不登记、不修改规则 |
| 登记/条件更新  | `POST /system/sources/commands`                  | admin + CSRF + 原 requestKey；更新必须比较 source revision        |
| 核查原来源命令 | `GET /system/sources/operations/{requestKey}`    | admin + 原操作者/操作归属；not-found/pending 不得解锁重发         |

补充第二配置源是独立管理能力。source-registration HTTP adapter、严格 wire schema、UTC mapper 和 4 个 API operations 已进入 OpenAPI 生成；正式 `SystemObservationContainer → SystemPage → SourceRegistryPanel` 现将配置源登记/修改面板装配到 connections tab，授权使用当前认证 identity 的 `sessionEpoch` 与 admin 事实，身份 owner 替换/卸载时释放 workflow。当前 demo 模式通过显式 MSW handlers 提供内存 Nacos 示例、Consul/Nacos 写入、条件 revision、原操作查询和合成检查；这不是 Python 后端或真实 provider 检查。生产 build 仍是 live-only，不能据 demo 页面推定“真实连接编辑已完成”。

正式前端的连接编辑目标：登记 Nacos/Consul 使用独立后台赋予的 source ID/revision，provider 与位置明确区分；新增和凭证替换采用 none/reference/direct 类型分支，修改已有连接默认保留凭证、不返回明文或密钥引用值。用户必须主动选择替换才录入新凭证。测试连接只产生当前候选的可达/认证/能力观察，不登记、不修改规则，也不证明应用已加载。endpoint/provider/location/auth 任一变化立即撤销旧测试结论；未决登记/修改命令按原 requestKey 核查，不重发。后台负责 SSRF 边界、Secret 保护和实际配置源访问。

该目标为消费者内部需求，不在此新增另一份冻结 wire；F6 根据实际表单、状态及错误动作收敛到唯一 Console 协议。

### 7.3 当前实现与验收条件

旧 App 的 tab 由 URL `view` 控制，仍使用同步 fixture 连接及静态权限/交付说明；它将在 F6 退役，不是正常管理数据路径。

正式内部入口 `system/observation.ts` 已有独立 health/protocol/audit Port 与读取资源、三类面板。连接展示探测/有效截止/读取 UTC、毫秒耗时、有限能力、脱敏失败；过期按后台读取瞬间判断，不把浏览器在线当健康。协议支持版、实际协商版、兼容性/时间独立校验。审计仅 admin 投影授权，有独立 UTC 半开范围、actor/action/result 与分页，Apply 非法条件不发请求；仅返回有限审计投影和原请求/发布关联，不含敏感正文。未接真实 `/system/*`、旧 App 或后台持久化，不能将内部组件验收表述为真实 API 已实现。

配置源的纯 provider/auth/URL/凭证投影与 setup 共用 `shared/model/configurationSource`。正式页面已实际挂载 `SourceRegistryPanel` / Dialog / Fields / OperationFeedback 到 connections tab；正常编辑按已读 ID/revision 默认 keep，不回显密码/令牌/用户名/引用值，显式 replace 支持三种认证模式。切 provider 清除地址、位置和秘密并禁止 keep；测试结果随任一输入变化失效，测试不登记、不写规则、不授权发布，保存由后台重新验证。未知写结果清除临时秘密，只查原 requestKey，pending/not-found 不解锁重发；冲突保留可修正字段但不得静默采用新 revision 覆盖。source workflow 以当前认证 session owner 和 admin 事实授权，owner 失效时释放。demo handler 只持有脱敏配置事实及不可逆 keyed digest，不留存提交凭证；连接检查有明确的模拟说明且不会访问 provider。真实 Python 持久化/CAS/Secret 保护和浏览器渲染回归仍分别验收，证据见推进清单 §15.21。

目标验收：未知/不可达/权限失败分别显示；配置源健康不由浏览器 online 判定；非 admin 不看管理审计/账户写入口；URL 深链与刷新保留正确 tab；没有凭证回显。

## 8. 首次初始化 `#/setup`

### 8.1 功能与交互

启动授权 → 系统存储 → 内置管理员 → 首个规则来源 → 确认并提交。启动授权是 F6 安全收敛新增的前置区域，不改变原配置四步：输入部署提供的一次性 operator code，确认 grant 后才允许 DB/source 连接检查和初始化；不能通过占据第一个匿名请求自动成为管理者。仅未初始化可达，无“返回登录”；完成后替换到 login，并永久关闭初始化操作。后端 bootstrap 状态才是事实，前端 stepIndex 只代表表单进度，不是数据库迁移状态。授权码与各类连接密码一样仅在临时输入中存在，确认/离开清理，不进 URL 或确认页。

### 8.2 数据与接口

`BootstrapStatus`：phase/initialized/availableDatabaseKinds/availableAuthModes；不返回连接口令。
`DatabaseDraft`：kind=postgresql/mysql/sqlite，网络库 host/port/database/username/password；sqlite 仅本地。
`AdminDraft`：username/password，确认字段只在表单使用，不重复发送后台。
`RuleSourceSetup`：provider/endpoint/namespace（Nacos）或 datacenter（Consul）、认证联合；具体 group/dataId/key 留到绑定登记或使用显式可见默认值，不允许暗中按资源名造 key。

| 交互               | 既有身份草案路径（候选沿用）                  | 结果                                                                          |
| ------------------ | --------------------------------------------- | ----------------------------------------------------------------------------- |
| 强制路由判定       | `GET /system/bootstrap`                       | 未初始化 phase 或最小 ready 状态                                              |
| 测试数据库         | `POST /system/bootstrap/database/validate`    | 不持久化业务数据；短时 validationRequestId + 脱敏摘要                         |
| 测试规则源（补充） | `POST /system/bootstrap/rule-source/validate` | 连接、认证、读写能力及匿名警告，不执行规则覆盖                                |
| 完成初始化         | `POST /system/bootstrap/initialize`           | 后台保存受保护安装配置、迁移、创建唯一内置 admin、登记 source，成功返回 ready |

认证为互斥联合：`credential_reference`（部署可解析引用，不要求 KMS）；`direct`（Nacos username/password、Consul aclToken，一次录入后台保护）；`none`（明确匿名与风险）。切模式/来源需清理不适用敏感字段，不能提交所有模式凭证。

database validate 不能靠一个 requestId 自动拥有永久可用 DSN：后台须定义其绑定的引导会话、参数摘要、短 TTL 与一次性消费；凭证只在受保护临时边界保存或 initialize 时重新提交。需由 bootstrap service 在未配置数据库时持久管理安装状态，不能要求先在未连接的数据库查询 initialized。

### 8.3 失败与验收条件

后台控制一次性窗口与并发锁；失败可恢复、不保留 ready 假状态、无默认密码，完成后再次初始化返回 409。部署受管密钥可来自文件/Kubernetes Secret，不必须接 KMS；保护位置/密钥缺失明确错误。连接校验防 SSRF、端口/协议限制和凭证泄露。

当前四步内容已拆为存储、管理员、规则源与确认组件。纯校验覆盖网络数据库必填项/严格整数端口、管理员密码长度/一致性、HTTP(S) 来源地址和三类互斥认证；提交只包含当前数据库/来源/认证分支，确认密码与其它分支秘密不进入载荷。切换数据库/来源/认证方式清理不适用凭据，切回不复活；SQLite 不提交网络参数。

新增异步初始化入口与内部 Port/工作流已通过逻辑及真实 React/Astryx 页面交互测试，尚未装配到 App 的旧 demo 路径。该入口的连接测试只检查可达性，不创建 schema、不持久化配置；字段变化立即撤销旧检查结论。初始化提交具备 pending/已知失败/冲突/结果未知/核查/确认完成区分：服务端操作回执必须关联原 requestKey，且独立 bootstrap 确认已初始化，才通知路由进入登录并清理临时凭据。已知错误保留可修正表单，已发请求超时不重放；not-found 不能解释为已回滚，别人的初始化完成也不冒认为本次成功。

F6 需把这些内部能力投影到唯一 HTTP 契约，包括原请求结果核查、初始化操作者的保护与授权、requestKey/operationId 生命周期；它们不是登录凭证，不能仅靠知道 ID 就读取初始化操作。初始化 body/密码不得作为服务端操作回执返回，HTTP 层的错误必须脱敏。当前逻辑和浏览器 Port double 不证明真实迁移/锁/加密/持久化，App demo 的测试连接提示与本地跳登录将在 F6 退役。

目标验收：未配置库可启动 setup；错误连接不变 ready；并发只能初始化一次；重启仍关闭 setup；服务故障不重新引导；三类认证与两生产 DB 都有真实边界验证。实际运行记录及未验证边界见 [推进清单 §13](process/R-DASHBOARD-前后端现状与推进清单.md)。

## 9. 登录 `#/login`

### 9.1 功能、数据与接口

账号名/密码登录，无 setup 入口；会话成功后按安全 returnTo 返回可访问页面。导航壳需个人菜单/注销入口，不能把 avatar 永远跳账户管理当作个人账户。

`LoginRequest`：username/password；`Session`：`account{accountId,username,roleId,status}/capabilities/expiresAt`。会话由后台生成，不由输入用户名映射角色；密码不得持久化，返回体不含密码/哈希。

| 动作          | 候选沿用接口        | 行为                                                                |
| ------------- | ------------------- | ------------------------------------------------------------------- |
| 登录          | `POST /auth/login`  | Cookie 会话 + Session；非法、停用、未知账号统一 invalid_credentials |
| 刷新恢复/权限 | `GET /auth/me`      | 当前 Session；过期明确 401                                          |
| 注销          | `POST /auth/logout` | 撤销会话、清客户端受保护缓存，返回 204                              |

### 9.2 当前实现与验收条件

新 `LoginEntryPage` 订阅 app 唯一 `AuthenticationWorkflow`，不读 fixture、不设置本地角色、不自行建第二份认证 owner。`LoginSurface` 只拥有品牌/字段/布局与临时密码可见性，旧 demo 与新入口复用；`presentation/loginFeedback` 将命令/准入事实映射为安全三语文案。

新入口在未知/不可用时不提供可提交登录，已确认未初始化且 setupAvailable 才通知 app 强制引导；不展示 setup 导航入口。错误凭证与禁止登录用相同安全文案，429 单独展示；已知失败保留可修正输入。超时写入不自动重放，只能显式核查当前 session，失败不恢复准入。POST 成功仍需独立会话回读与匹配；确认身份后清密码并按 sessionEpoch 只通知一次，站内安全回跳由 app 拥有。

上述新入口已用实际浏览器/测试 Port 验证，未切入旧 App。旧 LoginPage 仍用 fixture 匹配角色、未知用户名默认 admin；SessionProvider 的 localStorage 演示角色无真实认证含义。两者在 F6 统一切线后删除，不能把新入口的局部通过当成生产守卫已闭环。

目标验收：错误凭证、停用、过期/注销、refresh、view 直达管理 URL 被拒；会话身份只信后台，修改 localStorage 无法授权。

## 10. 账户维护 `#/accounts` / 系统 accounts 子视图

### 10.1 功能与交互

admin 查看账户列表、新增账号 Dialog、启停账号、跳角色绑定。业务输入只有**账号名、密码、角色**，没有显示名称，也不要求新增时确认密码；状态、内置标记、最近登录属于后台元数据。

旧 demo 列表仍有带任意目标的“修改密码”链接，F6 退役；新内部 `AccountsPage` 仅提供角色绑定与状态命令，不提供管理员重置。个人改密见第 12 章，管理员重置他人密码不在本轮范围，不将目标 accountId 塞进个人改密请求。

### 10.2 数据与接口

`AccountSummary`：accountId/username/roleId/status/builtIn/lastLoginAt|null/revision；neverLoggedIn 使用 null，而非中文字符串。AccountCreate：username/password/roleId；返回后台创建的 ID 和摘要，不返回秘密。

| 动作 | 候选沿用接口                               | 规则                                                    |
| ---- | ------------------------------------------ | ------------------------------------------------------- |
| 列表 | `GET /accounts?page&pageSize&query&status` | admin；服务端分页/筛选                                  |
| 新增 | `POST /accounts`                           | admin + Idempotency-Key；唯一用户名与强度后台校验       |
| 启停 | `PATCH /accounts/{accountId}`              | status + revision；不能停用最后有效 admin，停用撤销会话 |
| 角色 | 导航 roles                                 | 传目标 ID，不修改个人会话身份                           |

删除/重置链接虽出现在旧身份契约，当前 UI 不存在；不将它们列为本轮页面已有功能。纳入首版前需补确认交互、安全合同和测试。

### 10.3 状态与验收条件

新 `CreateAccountDialog` 共用 DialogFrame/AccountFields；验证失败保持输入并显示安全反馈；网络/5xx/畸形回执不关闭成“已创建”，进入结果未知并禁止再次提交。仅收到与 requestKey/目标及预期字段一致的完成回执才清除 mounted 表单并关闭；目录由唯一 workflow 失效/回读，刷新失败不能把已确认提交改为可重复的失败。账号名重复/最后管理员/内置账号/版本冲突单独处理。字段级服务端问题投影在 F6 冻结 wire 时落实，不假称已完备。

`AccountManagementWorkflow` 的 directory/detail/mutation 绑定当前 accountId/sessionEpoch；仅当前 admin 可读写。分页与筛选走 async Port，状态变更先确认，命令携带 revision，服务端生成 ID；公开操作身份不含密码。操作核查为有界、可取消的只读请求；not-found 不是回滚证明，不能解锁再次写入。内部 Port/页面已做测试替身验证，未挂旧 App，不能冒称持久化或 Python 联调。

F0 已修创建回调中的非法 Hook：事件使用组件顶层取得的 gateway；临时演示启动 Hook 由 App 唯一装配，AccountStore 按 gateway 身份幂等初始化，页面导航不回灌示例。新增/改角色/启停在同一浏览器文档内跨页保留；刷新仍重建示例，不宣称持久化。目标验收仍需：跨页/刷新读取持久事实；创建失败不插入列表；重试只一账号；view API 与深链不可新增/启停；最后管理员并发保护由 DB 事务保证。

## 11. 角色绑定 `#/roles` / 系统 roles 子视图

### 11.1 功能、数据与接口

admin 明确选择目标账号，查看当前角色/状态，绑定固定 admin 或 view。没有自建角色/能力编辑；新内部入口采用**显式保存/放弃**，radio 只改本地草稿，不即时持久化。草稿包含 accountId/revision/baseRoleId/roleId；保存携带原 baseline revision。额外 reason 字段尚无当前 UI 消费者，不在内部 Port 伪造，F6 按页面与审计需求收敛。

读 AccountSummary 和 `RoleSummary{roleId,capabilities}`；label/description 前端翻译，后台不返回唯一中文角色名称。

| 动作         | 候选沿用接口                                         | 规则                                             |
| ------------ | ---------------------------------------------------- | ------------------------------------------------ |
| 账号选择     | `GET /accounts`、`GET /accounts/{accountId}`（补充） | admin；未知 ID 返回不存在，不回落改第一个账号    |
| 固定角色目录 | `GET /roles`                                         | 固定 admin/view，不接受任意 capability 写入      |
| 保存         | `PUT /accounts/{accountId}/role`                     | roleId/reason/revision → 更新后的 AccountSummary |

### 11.2 当前实现与验收条件

旧 demo radio 仍直接改本地 store，F6 退役。新 `RoleManagementPage` 通过同一 AccountManagementWorkflow 读取显式 URL 目标；未选/不存在不 fallback，停用/内置/最后 admin 保护由纯策略提示及 command 双层校验。`RoleEditor` 按账号 ID 挂载而不按 revision 重建，刷新不抹掉未保存草稿；409 保留选择，主动读最新后重新决定。切账号有未保存确认，unknown 禁换目标/重放并可核查原操作；全局路由离开保护和系统 tab 复用在 F6 真实装配时完成。后台授权、最后 admin 事务、会话撤销与审计仍未实现。

目标验收：改角色后会话能力按后台策略失效/刷新，不因缓存继续允许写；并发不能移除最后 active admin；未知账号不改他人；返回账户页显示最新角色；view 不见保存入口且 API 拒绝。

## 12. 修改密码 `#/change-password`

### 12.1 功能、数据与接口

当前登录用户输入旧密码、新密码、确认新密码；确认仅本地防输错。页面主体显示自身 username，不能任意从 URL 选择目标。

`PasswordChangeForm`：current/new/confirm；wire `POST /api/v1/auth/password` 仅接收 `currentPassword/newPassword`。成功返回 HTTP 200 `{sessionDisposition: "reauthenticate"}`；后端事务修改哈希并撤销该账号所有 session，然后清除当前 session/CSRF Cookie，前端仅在确认回执后清空字段并跳转重新登录。当前密码错误返回 HTTP 400 `current_password_invalid`，不修改哈希、不撤销 session；缺失/失效 session 仍返回 HTTP 401 `unauthenticated`；弱密码返回 422 `validation_failed`。连续输错达到部署配置的尝试阈值后返回 HTTP 429 `rate_limited` 和有界 `retryAfterMs`；改密桶按已认证账号的用途隔离 HMAC 标识，不存储原始账号，且不与登录 IP 桶互相清理。客户端确认字段不进入 wire。PostgreSQL/MySQL 并发与生产部署验收仍未完成。

### 12.2 当前实现与验收条件

新的本人入口 `OwnPasswordPage` / `createOwnPasswordWorkflow` 使用会话身份，不接受目标 accountId；单个 workflow 绑定可信 account/sessionEpoch，并观察已有认证所有者。`prepareOwnPasswordChange` 仅提交 currentPassword/newPassword，密码不 trim，confirm 只本地校验。`usePasswordForm` 本地通过不再清空；只有确认成功或主动离开才清理临时输入。Console 用例层区分当前密码错误和当前 session 无效，分别映射 `current_password_invalid` 与 `unauthenticated`；前端按稳定错误码映射三语提示，不以所有 HTTP 400/401 猜测失败语义。错误密码验证不写密码审计事件；数据库未提交密码变更。

内部 `OwnPasswordPort` 的 receipt 只接受实际服务端返回的受控 `sessionDisposition`；当前 Console 实现固定返回 `reauthenticate`，并撤销全部 session。未知写入不提供 reset/replay：超时/5xx/提交后取消保留不确定性，用户重新登录核实；已知当前密码错误、弱密码与服务端限速分别反馈并保留可修正输入。Console 当前密码错误与 session 401 使用不同稳定码；改密服务在凭证校验前读取 SQL 共享限流状态，错误密码原子累计，达到封锁期则不再执行密码 hash 验证，并映射为 `429 rate_limited`。它复用部署显式配置的阈值/窗口/封锁时长，但以账号作用域 HMAC digest 形成独立桶；正确当前密码验证后清除该账号失败状态。PostgreSQL/MySQL 生产事务、跨 worker 部署与页面→Python 实际链路仍需验收。换会话取消观察，迟到成功不能提交给新 owner。

新入口已用实际页面和测试 Port 验证，本轮未装配到旧 demo App；旧任意目标演示页与账户列表链接仍待 F6 统一退役，不能据内部入口宣称整个应用已安全接线。密码不进入 snapshot/URL/storage/日志/事件；后端哈希、撤销和权限仍待 B0。

目标验收：旧密码错误不更改哈希；本人改密与管理员重置不混用；成功按后台定义撤销其他会话；过期跳登录；刷新无明文；URL 改 account 不可更改他人密码。

## 13. 协议交付与页面设计完成条件

工程执行以 2026-10-07 确认顺序为准：先完成前端页面职责、业务规则、状态与样式边界，再从完整页面用例统一抽取通信 DTO/操作并集中实现 HTTP Mock，最后实现 Python Console 与真实联调。当前正式路由已经改为 feature-owned Console HTTP adapter；页面交互全量验收和 Mock 状态闭环仍未完成。前期可用内部异步 Port 与测试替身验证页面，不把内部 Port 或生成的 draft machine contract 冒充成已签字 wire。

先按上述用例确认功能，再生成/维护统一 OpenAPI 与 JSON Schema、成功/失败样例及 Python/TypeScript 契约测试；不能只靠 TS 泛型 `as T` 接受网络响应。每个 operation 关联页面动作、输入、响应、权限、错误、副作用、幂等和分页/时间语义。

服务端内部按功能拆 bootstrap、identity、rule-governance、observation、incidents、system，不按每张页面复制一套发布/鉴权业务。页面读模型可以独立投影，共享的规则版本/权限只有一个主管。

实现验证分层：字段/mapper/纯校验 → gateway 与 mock Console → 后台持久化/厂商依赖 → 浏览器真实闭环。至少覆盖加载/空/拒绝/错误/陈旧/部分状态、重复/冲突、跨页导航与敏感字段不泄露。图表和表单另做实际像素/键盘/响应式验证，类型检查和 DOM 等价不代替渲染验收。

最终 mock 与 live 共用同一套 feature HTTP gateway/资源/命令：mock 在传输边界拦截请求，返回同协议响应；live 请求 Python 后端。页面与 store 无 mock 分支、不直接 import 示例数据；live 失败不回落示例。初始化、登录、账户、草稿、版本、计划等模拟写命令有可重置状态而非固定成功，浏览器模拟不能证明服务端权限/事务/持久化或定时调度成立。

### 13.1 页面动作到当前 machine operations 的映射

下表将页面章节与目前生成的 `docs/protocol/console-api.openapi.json` operationId 对位，供 Python Console 按能力实现；共享 operation 不代表页面各自拥有副本。路径、请求/回执细节以 `features/<feature>/api/*Contract.ts` 和生成 OpenAPI 为准。当前合同仍为 `draft-partial`，后端实现前必须通过逐页动作审核并继续确认 profile/能力边界。

| 页面章节                   | 当前 HTTP 能力/operationId                                                                                                                                                                                                                                                                                          | 代码责任入口                                                                         | 当前限制                                                     |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------ |
| §2 总览                    | `readObservationCatalog`（共享），`readFleet`                                                                                                                                                                                                                                                                       | `features/overview/api/fleet*`；应用目录由 `applications` feature 提供               | mock fleet，不是真实采集                                     |
| §3 应用与实例              | `readObservationCatalog`（共享），`readInstanceCatalog`，`readInstanceObservation`                                                                                                                                                                                                                                  | `features/applications/api/*`                                                        | 没有真实 Agent inventory/metrics                             |
| §4 规则                    | `readRuleBindings`、`readRuleDrafts`、`readRuleDraft`、`readRuleOperation`、`readRuleActivationPlans`、`readRulePublications`、`readRulePublication`、`readRulePublicationReceipts`、`readRuleSetSnapshot`、`readRuleVersions`、`readRuleVersion`、`mutateRuleSet`、`compareRuleCandidate`、`validateRuleCandidate` | `features/rules/api/ruleSet*`                                                        | Python Nacos/Consul CAS/回读、codec 对齐与集群实际生效未验证 |
| §5 实时监控                | `readObservationCatalog`（共享），`readMetrics`                                                                                                                                                                                                                                                                     | `features/realtime/api/metrics*`                                                     | HTTP Mock 可演示；生产数据采集/SSE 未接                      |
| §6 故障分析                | `readObservationCatalog`（共享），`readIncidentTimeline`，`readIncidentEvidence`                                                                                                                                                                                                                                    | `features/faults/api/incident*`                                                      | Python 事件仓储/Reporting 消费未实现                         |
| §7 系统管理                | `readSystemConnections`、`readSystemProtocols`、`readSystemAudit`、`readRegisteredSources`、`checkRegisteredSource`、`mutateRegisteredSource`、`readRegisteredSourceOperation`                                                                                                                                      | `features/system/api/*`                                                              | Python 探测、Secret vault、权限审计/CAS 未实现               |
| §8 首次初始化              | `readBootstrap`、`authorizeBootstrap`、`checkBootstrapDatabase`、`checkBootstrapSource`、`initializeConsole`、`readInitialization`                                                                                                                                                                                  | `features/identity/api/*` + `app/router/SetupRouteOwner`                             | 无真实 MySQL/PostgreSQL 初始化或一次性窗口                   |
| §9 登录                    | `login`、`logout`、`readSession`                                                                                                                                                                                                                                                                                    | identity HTTP + app authentication owner                                             | cookie/CSRF/限速需 Python 部署验收                           |
| §10 账户维护、§11 角色绑定 | `listAccounts`、`readAccount`、`readAccountOperation`、`mutateAccount`                                                                                                                                                                                                                                              | identity `accountManagement*`；角色是账户 command 的受限变化，不单独复制 role 表协议 | 数据库事务、最后 admin 并发和跨会话撤权未验证                |
| §12 本人改密               | `changeOwnPassword`（并由登录/session 核实当前 actor）                                                                                                                                                                                                                                                              | identity `ownPassword*`                                                              | 哈希、会话处置及密码拒绝策略未接 Python                      |

43 paths 由 12 个 capability family 生成；`pending=[]` 表示目前被导出的 operation family 都有 machine contract，不代表页面动作冻结。有界字符串使用标准 `maxLength` 并附加 `x-max-utf16-code-units`，显式表达 JavaScript/Python 共用的 UTF-16 长度边界。`applicationScope.ts` 尚保留演示应用目录；live 目录必须由授权 `readObservationCatalog` 提供，不能在 URL 解析处继续回退成固定 app。

### 13.2 网关迁移现状与实现边界

网关决定现已在前端源码落实：旧 `FixtureGateway`、同步页面/exports 与未挂载 HTTP 雏形已退役；正式 route owners 使用新的 feature HTTP adapters，并共享同一个 Console transport。demo mock 在 HTTP boundary 拦截，live 请求同一 adapter 的 Python API。Nacos/Consul 连接信息、凭证、完整数组 codec 和配置源写回属于 Python provider，不在浏览器中直连。

前端交付仍有未完成项：页面状态/失败矩阵和交互视觉验收、Mock command 跨页面状态一致性、应用目录演示残留、OpenAPI 最终签字，以及完整浏览器验收。此处静态源/transport 检查不能替代真实渲染；Codex 内置浏览器局部观察也不替代完整 CDP E2E。

### 13.3 Python Console 目标责任

按上述能力 family 实现独立管理 Console，不从既有 per-process `sentinel-dashboard` 的路由/权限或 Jinja 页面裁剪出管理服务。初始服务能力至少拆分 bootstrap/identity、rule governance、observation/incidents、system source registry；共享授权与事务策略由服务层统一拥有。持久化使用受支持的 PostgreSQL/MySQL；Nacos/Consul 是规则事实源，Console relational DB 持有账号、审计、草稿/版本元数据、计划和来源登记。用户真实数据库及真实配置源只能在隔离联调时经授权验证。
