# Console API 契约（冻结版本 0.19.0）

> 当前执行入口：**§9–§22**。§0–8 保留为旧草案输入与决策沿革，不再直接指导实现。
> §9 依据正式异步页面 Port 定义职责；feature DTO Runtime Schema 与 OpenAPI 已生成。
> 当前 contract 有 **68/68** operations / **64 paths**；0.8.0 原有 operation 保持 wire 等价，0.9.0 新增规则状态观察读取，后续版本累加首次初始化授权、监控源管理、HOST metrics、host-to-Reporter associations，0.16.0 新增旧 process epoch 的规则加载历史独立只读查询，0.17.0 新增认证后的部署引导目录读取，0.18.0 为监控源删除回执增加 `source_in_use` 稳定拒绝原因，0.19.0 新增 Console 全局系统时区设置读取与更新。历史 contract 的请求/响应样例继续由 OpenAPI 生成并验证。Console API wire **0.4.0 已于 2026-10-13 冻结；0.5.0 在 2026-10-14 由产品/API owner 批准添加配置源删除命令；0.6.0 于 2026-10-15 增加规则绑定范围读取；0.7.0 于 2026-10-16 按已批准方案增加逐 worker 协商观察；0.8.0 于 2026-10-16 按已批准的规则目录设计增加配置中心规则读取与有界刷新；0.9.0 于 2026-10-16 增加规则绑定观测状态与运行时加载观察；0.10.0 于 2026-10-17 增加本机首次初始化授权；0.11.0 于 2026-10-17 按已授权的推荐默认值增加监控源候选探测；0.12.0 按 owner 已授权的推荐默认值增加 monitoring source safe reads；0.13.0 按 owner 已授权的推荐默认值增加 monitoring source management commands；0.14.0 增加有界 HOST metrics query；0.15.0 增加 SQL-backed host-to-Reporter associations 与对应 audit action enum 扩展；0.16.0 增加 exact-binding historical rule-load observations；0.17.0 增加 Console-owned deployment guide readiness 与显式 Runtime Collector 公布地址读取；0.18.0 仅扩展 monitoring source operation reason 为 `source_in_use`，不改变 Collector/Agent Reporting/Metrics V2 wire；0.19.0 仅新增 Console 全局系统时区设置端点，既有 operation 的 wire 不变**。历史版本继续保留对应 schema；后续新增字段/enum 均须走明确兼容性评审。冻结范围是本文件 §9–23 与生成的 OpenAPI，不代表 Python 全部实现、生产部署或 E2E 已通过。
> 当前 machine contract 提供 **121** exchange examples 与 **156** media examples；成功/失败响应示例按 OpenAPI 与 runtime contract 同步校验。
> 不得再按本文旧末段“替换 gateway 页面不动”执行。

> 状态：**已冻结实现基线（0.18.0；监控源引用删除保护）；真实 provider/UI/E2E 验收仍开放**。当前规范入口仅为 §9–22 与生成的
> `docs/protocol/console-api.openapi.json`；§0–8 和 §「待确认」是历史讨论记录，不再构成待确认项或覆盖当前规范。
>
> 依据 `DASHBOARD_CONTROL_PLANE.md` §6.1「契约先行」：逐页用例与 machine contract 是
> Python 实现输入；各规则 codec、发布回执及运行时数据来源仍需与后端实现共同验收。

## 10. Console API 0.5.0 增量：配置源删除

0.5.0 仅扩展既有 `POST /api/v1/system/sources/commands` 判别联合，不改变 0.4.0 已有
register/update 请求、响应、授权或幂等语义。删除请求必须包含 `kind=delete`、唯一
`requestKey`、`sourceId` 与调用方读到的 `expectedRevision`；`Idempotency-Key` 必须与
`requestKey` 相等。所有请求仍须满足当前 admin + Origin + CSRF 策略。

- 仅当 source 存在且 revision 精确匹配时才删除；缺失返回持久 `rejected/not_found`，
  版本过期返回 `rejected/conflict`。
- 只要有 `console_rule_binding` 引用该 source，命令返回 `rejected/source_in_use`；不级联
  删除 binding、规则版本、发布计划或发布回执。数据库 `RESTRICT` 外键是并发下最终保护。
- 成功删除在同一 SQL transaction 中移除 source row（包含在线加密凭证）与探测快照；之后
  registry/read、credential resolver 与 source probe 均无法访问该 source。既有数据库备份/WAL
  的保留及销毁由部署备份策略负责，不将在线行删除误称为备份介质擦除。
- delete operation receipt 只保存 actor/session ownership、requestKey、keyed fingerprint、
  deletedSourceId 或有限 rejection、时间及审计关联；不得保留 endpoint、location、provider、
  credential ciphertext、credential reference 或明文。重放同一 key/同输入返回原结果；异输入
  或跨 register/update/delete 复用 key 拒绝为 `idempotency_conflict`。
- receipt 查询仍要求有效 admin 会话及原操作者。审计仅记录配置源目标 ID、action 和 outcome，
  不记录源配置或凭证。

本节是 0.5.0 source-delete 的 wire 与安全边界。Python migration/API/SQL 验收及 React 删除交互
分别按推进清单 T02.1 记录；契约冻结不表示这些实现或最终 E2E 已验收。

## 11. Console API 0.6.0 增量：规则绑定范围读取

0.6.0 新增 `GET /api/v2/rules/binding-scopes`。该读取仅为 Rules 页面提供环境与应用筛选项，
来源是 Console 持久化的完整规则绑定/配置源/发布目标事实，不读取 Metrics V2 Reporter，
也不修改既有 `/api/v1/observation/catalog` 的观测语义。

- 仅有效浏览器会话可读取；admin/view 均可读。响应采用 `no-store` 与 `Vary: Cookie`。
- 对完整、内部一致的绑定记录按 environment/app 去重并排序；当前没有任何绑定时返回成功的空
  `environments` 与 `applications`。上限与标识校验按生成 DTO/domain schema 执行。
- 缺少 scope authority、SQL 故障、目标/来源关系不一致或结果越界均返回脱敏
  `503 service_unavailable`；不得把故障伪装为空目录。
- 环境与应用目前以持久化标识作为显示名称；为允许首次无 Reporter、无既有绑定的配置，Rules
  页面可由管理员显式输入环境/应用标识，再创建第一个 binding。不会自动选择任意 scope。
- DTO 不含凭证、provider target body、规则正文或配置源连接信息。

本节冻结 wire 形状，不代表 Console runtime 数据库部署与浏览器到 Python E2E 已验收；定向证据
记录在推进清单与 `R-DASHBOARD-rules-scope-catalog.md`。

## 12. Console API 0.7.0 增量：逐 worker 协议协商观察

0.7.0 新增两个只读观察：`GET /api/v2/system/protocol-observations/agent-reporting?page&pageSize` 与
`GET /api/v2/system/protocol-observations/incident-events?page&pageSize`。它们保留每个已登记 worker 的
独立身份与各自协议事实，不聚合成可能丢失滚动升级差异的单值；旧 `GET /api/v1/system/protocols`
仍只呈现原有部署级协议边界。

- 两个读取都要求有效浏览器会话；每页最多 100 项，页码有界，未知或重复查询参数返回
  `400 invalid_request`。无有效会话返回 `401 unauthenticated`，权威 SQL 不可用返回
  `503 service_unavailable`。
- Agent Reporting 和 Incident Event 协商分别来自已认证 Runtime↔Collector hello/accept；一个协议的
  握手不能推断另一个协议兼容。已登记但未完成对应握手的 worker 必须显示 `unknown`，不按 Collector
  supported list 推断 Runtime 版本。
- 身份由 Reporter enrollment 与已认证证书绑定导出，只返回 environment/app/instance/process/reporter
  的安全标识；证书 subject/principal、PEM、私钥和凭证均不得进入响应。
- 当前已撤销 enrollment 不进入活动 worker 结果。版本混合必须按 worker 保留；不得使用 latest-wins、
  majority 或 fleet summary 折叠为单一 active version。

本节只冻结 Console read wire 与数据语义；它不替代实际 hello/accept 的认证、SQL durable commit、
跨语言 producer/collector 合同或 React→Python 浏览器验收。相关实现与协议证据见推进清单 §15.1197–§15.1208。

## 14. Console API 0.9.0 增量：规则绑定状态与运行时加载观察

0.9.0 在 0.8.0 之上只新增两个认证只读接口：
`GET /api/v2/rules/catalog/binding-states` 与
`GET /api/v2/rules/load-observations`。完整响应 schema、严格 query、错误响应与示例以生成的
`docs/protocol/console-api.openapi.json` 为准；0.8.0 machine contract 归档在
`docs/protocol/console-api-0.8.0.openapi.json`，既有 operation 必须逐字保持 wire 等价。

- 规则绑定状态来自 Console SQL 投影，不同步访问 Nacos/Consul。七态区分有规则、确认空数组、目标缺失、内容无效、不支持 profile、来源不可用、从未读取。目标缺失不是删除指令；失败时保留 last-known-good，只有 provider 确认的合法空数组可清除其当前规则投影。
- 运行时加载状态来自 Reporter enrollment 与 Collector durable current projection 的 SQL 联接；同一环境/app 的每个未撤销 enrollment 是每条匹配 binding 的预期目标。已撤销 enrollment 排除；没有活动 enrollment 是精确零，而不是“未知”。
- Collector `receivedAt` 是唯一新鲜度时钟；超过 90 秒（严格 `> 90s`）标 stale。运行时 `observedAt` 仅作为事件时间展示。分页排序固定为 `(bindingId, instanceId)`。
- 未知/未评审 profile 或不完整 membership 不能展示为未加载、unsupported 或未使用；精确 rule membership 只有在 Console 显式兼容 profile 且 membership 完整时才可声明。API 不返回证书身份、密钥、原始规则正文、原始异常或 provider payload。
- 0.9.0 仅扩展 Console 查询 API；Agent Reporting V1、Runtime Receipt V1、Metrics V2、Nacos/Consul provider wire 均不变。接口冻结不代表跨数据库、生产 provider 或浏览器验收已完成；闭环证据按推进清单 T03.4/T03.5 记录。

本增量于 **2026-10-16 由产品/API owner 批准**；冻结仅授权 API 0.9.0 实现，不代表发布或最终 E2E 已通过。

## 13. Console API 0.8.0 增量：配置中心规则目录

0.8.0 新增 `GET /api/v2/rules/catalog` 与 `POST /api/v2/rules/catalog/refresh`。前者从 Console SQL 投影分页读取已登记 Nacos / Consul 规则快照；后者对指定环境/应用范围执行有界 source refresh。Nacos/Consul 仍是规则内容权威源，Console SQL 仅保存可搜索的 last-known-good 读模型。刷新不发布、不写回或修正规则源内容。

- GET query 必须且只可使用 `environmentId`、可选 `appId`、可选 `kind`、可选 `search`、`page` 与 `pageSize`；拒绝未知/重复参数。admin/view 有效会话均可读，响应 `no-store` 且按 Cookie 区分。
- 响应明确 `coverage`、绑定总数及 current/stale/notRead 计数。只有范围内所有绑定都成功读取时，`total` 才是精确值；不完整时 `total: null`，不能将部分搜索结果或当前空页解释成“没有规则”。`hasMore` 只表示已确认 SQL 投影中是否还有下一页；partial 时不能推断未读来源。合法空 JSON rule array 是成功读取，贡献完整覆盖与精确零规则数。
- 每个规则条目绑定到 provider snapshot checksum、source revision/version 与 read timestamp。读取失败保留此前成功内容并标为 stale；从未读取的绑定标为 not_read；无原始异常、连接地址、凭证或规则以外的业务数据。
- POST body 只接受 `environmentId` 与可选 `appId`，需要有效 session、同源 Origin 与双提交 CSRF。admin/view 均可触发，因为这是只读 provider refresh；每次最多读取 24 个绑定、最多 8 个 provider 请求并行，下一次调用优先处理从未读/最久未尝试绑定。失败绑定与成功绑定互相隔离。
- 运行时实例是否加载规则、流量是否匹配规则属于不同数据事实；本目录不得从规则存在、发布回执或空请求量推断“有实例使用”或“无实例使用”。实例加载观察由后续独立运行时观察协议负责。

本节冻结 additive Console wire 与已批准的 source/SQL/UI 语义；Nacos/Consul live source readback、SQL dialect coverage 和 Rules 页面→Python 运行实例链路仍须按 T03.4 定向验收与 T07.1 完整 E2E 分开记录。

## 0. 范围与不做什么

**做**：控制台读写规则快照、读连接与指标状态的 HTTP 契约。

**不做**（原文 §2 已划界）：

- 不提供多租户、组织树、数据范围授权、多级审批；
- 不让浏览器直连 Nacos/Consul；连接源凭证可在控制台显式选择 `none`、`reference` 或 `direct`，由 Python Console 代理检查/保存，`direct` 凭证仅 write-only 提交并在服务端保护，任何读取/回执均不得回显明文或引用值；
- 不承诺长期历史与告警（§6.4，后续独立评审）。

现有 per-process Bearer admin token 与统一控制台的登录授权是**两套边界**，
不相互冒充（§2 末句）。

## 1. 最小权限

本节权限表是早期草案摘要，曾与当前角色/错误码合同不一致。当前逐 operation 权限以
§9 和生成 OpenAPI 的 `x-required-access` 为唯一机器事实；本产品目前只有 `admin`、`view`
两种角色，不提供独立授予 capability 的账号编辑能力。角色到 capability 的映射由服务端
session 投影固定派生。

| 当前 access 条件 | operation 范围 | 服务端行为 |
| --- | --- | --- |
| `metrics:view` | 指标、Fleet、实例及故障观测读取 | 拒绝时返回 `403 forbidden`，不返回空数组、零值或 Mock 数据 |
| `rules:write` | 规则草稿读取、候选校验与比较 | 拒绝时返回 `403 forbidden`；不得将拒绝伪装成空草稿或校验成功 |
| `admin` + `rules:write` | 创建规则 binding、执行规则变更命令 | 两个条件均须满足；view 不能写规则 |
| 无额外 capability | 已发布 binding/snapshot/version/publication/receipt/plan 与 publication target 读取；系统连接和协议摘要读取 | 仍要求有效登录 session；各自资源级授权及 operation 错误以 §9/OpenAPI 为准 |
| `admin` | 账号、审计、登记配置源及其操作回执 | view 不可读取或修改上述管理数据 |

`403 forbidden` 与「没有数据」是两件事。客户端必须按 operation 的稳定错误码呈现权限拒绝，
不得把拒绝投影成空图、空规则或零值；具体角色/capability 组合以生成 OpenAPI 的
`x-required-access` 为准。

## 2. 配置键映射（冻结项 1）

Dashboard 的表单草稿与配置中心的规则 JSON **不是同一层**，映射关系必须稳定：

| Dashboard 字段 | 配置中心 JSON 路径 | 备注 |
| --- | --- | --- |
| 规则类型 | `ruleType`（Flow / Degrade / System / Authority / ParamFlow） | 协议值，不本地化 |
| 生效范围 | `scope`（`application` / `resource`） | **协议值**；历史上曾写成中文「应用」「资源」，已修正 |
| 资源标识 | `resource` | 原样透传 |
| 阈值 | `thresholdType` + `threshold` | 保留原始单位字符串，不做单位换算 |
| 集群模式 | `clusterMode` + `clusterThreshold` | 关闭时字段不出现在 JSON 里 |
| 行为 | `flowBehavior` / `controlStrategy` | |
| 慢调用比例 | `slowRequestRatio` | 仅 Degrade |
| 参数例外 | `parameterExceptions` | 仅 ParamFlow |

映射表的**键**是代码常量（`features/rules/model/ruleDraft.ts` 的 `RuleDraft` 判别联合），
不是运行期拼出来的字符串。网关负责把 `RuleDraft` 转成对应后端的配置结构，
**页面不知道后端 schema**——这是「将来接 Nacos 与 Consul 双适配器」的前提。

## 3. 完整快照发布状态（冻结项 2）

写规则是**整体替换**，不是增量 patch。四态严格分离，前一态永远不能被表述成后一态
（§4.1：「前一个状态绝不能被 UI 文案合并为后一个状态」）：

| 状态 | 含义 | 失败的含义 |
| --- | --- | --- |
| `draft-validated` | 本地 schema 校验通过 | 草稿未通过校验，不允许发布 |
| `config-written` | 配置中心写入成功 | 未写入，实例仍持旧版本 |
| `read-back-matched` | 回读内容与提交一致 | 写入内容与回读**不一致**，必须停在此态并告警 |
| `instances-applied` | 已上报实例全部加载新版本 | 部分实例滞后，必须列出滞后实例 id 与版本 |

接口不回传聚合布尔值，而是回传**逐实例回执**（§5）。UI 不得把
「142 / 145 已生效」显示成「已生效」。

## 4. 指标口径（冻结项 4）

前端展示的每个数字都必须带 `scope`、`source`、采样时间、单位、聚合窗口、新鲜度
（§3.1）。具体口径：

| 指标 | 定义 | 禁止 |
| --- | --- | --- |
| HTTP QPS | 入站 HTTP 请求数在选定窗口的增量 / 秒 | 不得由累计值在浏览器端相减 |
| 资源调用率 | Sentinel entry 增量 / 秒 | 不得与 HTTP QPS 混称 |
| RT p95 | 同一时间窗内完成请求耗时的 95 分位 | 无 histogram 就不画 p95，不得用平均 RT 冒充 |
| TPS | 完成的**业务事务**数 / 秒 | 未接入时隐藏，不从 QPS 或 `succeeded` entry 猜测 |
| CPU / 内存 | 应用内实例的平均值百分比 | 不得标为服务器 CPU/内存 |

跨实例汇总只合并**同口径、同窗口、可识别实例身份**的数据，并显示已上报与未知实例数。

## 5. 实例生效回执（冻结项 5）

```jsonc
{
  "version": "v20260914-01",
  "instances": [
    { "id": "order-1", "loadedVersion": "v20260914-01", "appliedAt": "2026-09-14T14:32:18Z" },
    { "id": "order-2", "loadedVersion": "v20260913-02", "appliedAt": null }
  ]
}
```

滞后实例 `appliedAt` 为 `null`，UI 必须显示为滞后并可下钻。**部分生效不允许
被聚合成一个布尔值。**

## 6. 端点草案

所有端点以 `GET/POST /api/v1/...` 为前缀，认证走统一登录会话。

| 方法 | 路径 | 需要能力 | 说明 |
| --- | --- | --- | --- |
| GET | `/system/connections` | 无 | Nacos/Consul 连通性与能力边界 |
| GET | `/system/permissions` | 无 | 角色与能力声明 |
| GET | `/rules` | 无 | 规则摘要与版本 |
| GET | `/rules/snapshot` | 无 | 权威完整快照（`ruleType` + 资源 + 生效范围） |
| POST | `/rules/validate` | `rules:write` | 本地草稿的服务端校验 |
| POST | `/rules/publish` | `rules:write` | 完整快照写入 + 回读，返回四态进度 |
| GET | `/rules/applied` | 无 | 逐实例回执（§5） |
| POST | `/rules/rollback` | `rules:write` | 回滚到指定基线版本 |
| GET | `/metrics/query` | `metrics:view` | 按 app / resource / instance / window 查询 |

`POST /rules/publish` 的响应分两部分：同步返回 `config-written` 与
`read-back-matched`，实例生效通过轮询 `/rules/applied` 获取——**不在一个请求里等
实例加载**，那会把「控制面成功」和「数据面生效」这两个独立事实混成一件事。

## 7. 错误约定

| HTTP | `error.code` | 客户端处理 |
| --- | --- | --- |
| 400 | `invalid_request` / `current_password_invalid` | 请求、query 或 request-id 不符合协议；当前密码无效时按改密流程重新认证 |
| 401 | `unauthenticated` | 回登录页 |
| 403 | `forbidden` / `csrf_failed` / `bootstrap_unauthorized` | 按 operation 的拒绝原因呈现；不得投影成空数据或成功 |
| 404 | `not_found` | 仅对公开该错误的 operation 呈现目标不存在，不做跨资源 fallback |
| 409 | `conflict` / `idempotency_conflict` | 区分业务/目标冲突与 request-key 冲突；以 operation contract 为准 |
| 410 | `target_retired` | 清除已退役 incarnation 的指标与详情，不回退到另一实例 |
| 422 | `validation_failed` / `unsupported_profile` | 显示受控字段/语义问题并保留可修正草稿；不支持的 profile 不盲目重试 |
| 429 | `rate_limited` | 使用有界 `retryAfterMs` 展示冷却并禁止到期前重发 |
| 503 | `service_unavailable` / `dependency_unavailable` | 显示当前 authority 不可用，不回落到 Mock 或空成功 |

错误集合与状态码按 operation 区分；上表是当前全局错误形状摘要，不替代生成 OpenAPI
中的 `responses` / `x-allowed-error-codes`。规则发布回读不匹配属于 operation 的持久化
rejection reason，不伪装成可盲目重试的 HTTP `422`。

## 8. 五项决策（已定，改动需重开本节）

以下五项此前挂着「待后端确认」，会让 gateway 的实现细节无法落地。现逐项决策；
每条都写明**理由**与**推翻的条件**，方便后端不同意时直接指向该条。

### 8.1 配置中心的 Nacos / Consul 差异由**适配器吸收**，不进契约

**决策**：契约只暴露 `RuleDraft` 的统一形状；两侧后端的字段差异全部在
`core/api` 的 gateway 内部转换。页面与契约都不知道自己连的是哪种配置中心。

**理由**：§2 的映射表是**前端表达**到配置 JSON 的映射，不是某一家的 schema。
把两家差异暴露到契约里，页面就得分叉渲染两套字段——而这个差异对界面毫无价值。

**推翻条件**：若两家 schema 差异大到无法用一张映射表覆盖，则按 provider 分两张，
并在契约里显式声明 `provider` 字段。

### 8.2 历史中文 `scope` 值由 **gateway 读取时兼容**，不做数据迁移

**决策**：`RuleScope` 的协议值是 `application` / `resource`（`RULE_SCOPE` 已经如此）。
历史配置里流传过的 `"应用"` / `"资源"` 由 gateway 在**读取**时映射为协议值，
写入时一律用协议值。

**理由**：迁移配置中心里的存量数据需要停机窗口与回滚预案，代价远高于在读取端
兼容；而读取端兼容是一段有边界的纯函数，可以被测试覆盖。

**推翻条件**：若后端已在其它系统里做过一次全量迁移，则删掉兼容分支，避免两处映射。

### 8.3 回执的实例身份用 `instanceId`，`host` / `pid` 只作展示

**决策**：`/rules/applied` 每条回执带 `instanceId`；`host` 与 `pid` 是展示字段，
**不参与身份判定**。

**理由**：`host:pid` 组合在进程重启后含义漂移（pid 会变），用它当身份会让
「实例已生效」出现误判。`instanceId` 是 Sentinel 实例自带的稳定标识。

**推翻条件**：若采集端确实无法产出稳定 `instanceId`，则契约必须改为用
`host` + `port` 组合，并明确 pid 永不参与判定。

### 8.4 指标查询按**参数化**形态，接口字段不冻结

**决策**：`GET /metrics/query` 的**查询参数**冻结（`app` / `resource` /
`instance` / `window` / `scope`），**响应体**留给后端按实际指标后端适配，
但 §4 的口径（单位 / scope / source / 新鲜度）必须体现在响应里。

**理由**：指标后端未选定，冻结响应字段等于凭空设计它的 schema。口径是产品事实，
可以冻结；传输形状是实现细节，不该现在定死。

**推翻条件**：指标后端选定后补一份响应 schema，并在 §6 加一节示例。

### 8.5 乐观锁用 `version` 字段，不用独立的 `etag`

**决策**：`POST /rules/publish` 与 `/rules/rollback` 都带 `version`（当前生效的
快照版本），服务端发现不一致时返回 `409 version_conflict`。不引入 `If-Match` /
`etag`。

**理由**：规则快照的版本本身就有业务含义（页面上要显示「基准版本 v20260914-01」），
再加一个 etag 是同一份事实的第二个表示，且两者不一致时没人知道该信谁。

**推翻条件**：若服务端已用 HTTP 缓存语义管理并发，改为 `If-Match` 并保留 `version`
作为展示字段。

---

> **已作废的历史接线说明：**旧版 `HttpConsoleGateway`、`useConsoleGateway()` 与
> `fixtureGateway` 不代表当前实现，禁止按“装配处替换 gateway、页面不动”继续开发。
> 当前正式页面使用 feature-owned HTTP adapters 与共享 Console transport；demo 仅由
> HTTP boundary 的 MSW 拦截，live 由同一 adapters 请求 Python Console，不保留
> `FixtureGateway` 兼容路径。现行前端边界详见
> [页面能力设计 §13.2](Dashboard页面能力与接口设计.md#132-网关迁移现状与实现边界)。

## 9. F6 当前唯一执行决策（2026-10-07）

### 9.1 与旧草案的差异及主管归属

| 旧输入 | 当前决定 | 原因 / 落点 |
| --- | --- | --- |
| 默认演示 admin、只替换 gateway | 唯一身份 owner、异步页面与新 HTTP adapter；最终删除旧 gateway/bootstrap | 同步函数型 snapshot 不能来自 JSON；实际 App 不可继续演示认证 |
| 前端 gateway 吸收 Nacos/Consul schema | Python source addressing + rule codec profile；前端仅调用 Console | 配置源与规则格式正交；前端不访问厂商、不能把整组简化为首条 RuleDraft |
| 禁止网页写凭证 | 保留 none/reference/direct 显式选择；direct 仅一次写入和连接检查 | 用户已确认内网/K8s 可通过 Web 配置，不要求 KMS；读取始终禁止回显 |
| 固定 instanceId 足以证明加载 | instanceId + processEpoch / 本次进程 incarnation | 旧进程成功回执不能证明重启后的进程已加载 |
| 指标响应体不冻结 | 完整类型化 MetricBundle / 观测读模型，缺测及口径明确 | 所有正式读消费者必须能够解析和拒绝畸形响应，不能 unknown/as T |
| 所有对象共用 version 锁 | draft/account/source/plan 独立 revision；源 versionId/checksum/nativeRevision 独立 | Console 不可变内容身份和厂商写并发令牌不是同一事实 |
| /rules/publish 无明确目标 | /rulesets/{bindingId}/*，绑定环境/应用/源/profile | 防止跨配置项覆盖；回滚是新 publication，不恢复旧发布身份 |

本文为 Console 唯一通信合同入口；页面设计主管功能与内部分工，不再复制冻结字段表。后续 OpenAPI / JSON Schema 是本文指向的机器合同，必须从同一套 feature wire schemas 生成并通过正负样例检查；不是并行的第三套协议。源 JSON 采用显式 profile，既不按 Nacos/Consul 猜格式，也不将未知字段静默丢弃后发布。

### 9.2 共同 HTTP 及外部数据边界

- 根路径仍为 `/api/v1`。成功 JSON 直接返回具体 DTO，空成功 204；不添加 `{data,success}` 与裸 JSON 混合的第二套信封。请求底座显式 `parseEnvelope:false`，未知 JSON 经 strict schema 解码、显式 wire→model 映射和已有语义合同检查。
- JSON body 类型为 `application/json`；每对象仅接受定义字段。禁止函数、UI tone、译文单位、任意日志/traceback 或可执行 JSON。最大 body、字符串、数组、页容量有明确上限；越界不截断为看似完整快照。schema 只校验结构，权限、跨对象一致性、UTC 区间和发布原子性仍由业务合同承担。
- ID/revision/checksum 为有界字符串，版本和原生序号不做 JS Number 转换或字典序“更新”比较。所有绝对时间 wire 为 RFC3339 UTC `...Z`，内部模型可用 epoch 毫秒；持续时长 `stepMs/ttlMs` 为有界安全整数，不当作时间戳。相对 `range` 属 UI，HTTP 实际发送 `[from,to)`。
  当前机器合同将绝对时间规范为 `YYYY-MM-DDTHH:mm:ss.SSSZ`（1970–9999），非法日历/offset/本地时间拒绝；显式 mapper 不对持续时长或原生修订做转换。
- 列表 `items/page/pageSize/total`；默认和上限明确，稳定排序由后台实现。集合读取明确 bounded complete 或分页，不能把一页当完整目录。响应身份必须回核原 query/binding/profile/incarnation；数据缺失、权限拒绝、陈旧可信值和网络失败不合并为零值。
- 错误体唯一为 `error{code,requestId,issues?,retryAfterMs?}`，有限 code；其中 `code=rate_limited` 时 `retryAfterMs` 必须出现且为 `0..300000` 的有界整数，其它错误不得依赖该字段恢复。issues 只含稳定字段路径/分类和有界非敏感参数。不得反射输入、DSN、密码、引用值、厂商响应或 exception.message。网络、timeout、取消、协议错误为客户端独立错误，不能全部归为 config_center_unavailable。
  本轮机器合同中的每项 issue 仅有 `field/reason`，没有任意参数或原始输入；单端点按 status 收窄允许的 code。客户端重新构造有限错误，不将原始 body/cause 暴露给消费者。
- status：400 无效输入/JSON；401 认证失效；403 授权/CSRF/初始化引导不满足；404 权威不存在；409 修订或请求键冲突；410 权威目标已退役；422 语义/不支持 profile；429 有界限速；503 服务/依赖不可用。具体 endpoint 允许的 code/status 必须在机器合同穷尽，不用 status 猜业务 reason。
- 底座 HTTP client 自动重试 **0**，显式传递 AbortSignal。取消/timeout 只结束客户端观察，不撤销服务端已受理命令。GET 的用户重试和命令原操作核查分别由已有 workflow 管理，不添加全局写重放拦截器。

权限合同由生成 OpenAPI 的 `x-required-access` 对象逐 operation 声明，字段固定为 `role` 与 `capabilities`：`role` 为 `admin` 或 `null`，`capabilities` 是 `metrics:view` / `rules:write` 的有序唯一数组。它描述登录 Cookie 之外的服务端角色/能力门槛，不替代 `security` 中的 session/bootstrap/CSRF 要求，也不替代 binding、actor ownership、revision 等资源级授权。`null` 和空数组表示该 operation 没有额外角色/能力门槛；不能从 `x-semantic-rules` 的自然语言推断机器授权。当前 admin 角色导出 `metrics:view` 与 `rules:write`，view 导出 `metrics:view`；服务端仍须每请求基于当前身份执行授权。

运行时 schema 采用 Zod 4 的 strict object / 判别联合；以可转成 JSON Schema 的 JSON 类型定义 wire，使用官方 `toJSONSchema` 生成（[官方说明](https://zod.dev/json-schema)）。不使用 experimental fromJSONSchema、不以 unrepresentable:any 吞掉约束，不把 transform/refinement 自动导出当成完整语义合同。库精确版本在实际安装后记录；不是当前已装配的声明。

### 9.3 会话、初始化与凭证

首版角色仍只有 admin/view。admin 有 metrics:view 与 rules:write 并可管理账户/源/审计；view 仅观测和规则/版本/连接等允许的只读事实，没有管理命令。两者都可本人改密/注销。后台每请求按当前有效账号/会话修订授权，不能只相信此前返回的 capabilities。

账号登录名在 create、login 与初始化 admin 三个入口使用同一身份规则：先校验原始输入不超过 200 个 UTF-16 code units 且不含未配对 surrogate，再裁剪首尾 Unicode whitespace；裁剪后不得为空。展示字段保留裁剪后的大小写与字符形式。唯一身份按 `NFKC(trimmed).lower()` 计算，数据库保存其 UTF-8 字节的 SHA-256 小写十六进制值为 64 字符 `username_key` 并施加唯一约束；禁止大小写变体及 Unicode compatibility 变体形成重复账号。登录使用相同转换查找，不能只在创建端去重。Python 是 live 模式权威；浏览器 HTTP Mock 使用同一转换规则但不构成服务端证明。Unicode 数据表版本变化需要保留跨运行时契约向量测试。

会话为服务端 opaque HttpOnly Cookie，生产 Secure/SameSite，前端不保存 bearer/session cookie。sessionEpoch 是不可授权的所有权标识；登录、换会话、角色/状态变化后的旧数据资源必须清理。Session DTO 不含密码、Cookie、Token 或配置凭证。

状态改变需要会话绑定的 CSRF token + 精确 Origin 校验；token 只在传输适配器内存中，用固定响应/请求 header 交换，不进入页面模型、URL、localStorage、审计或操作 lookup。浏览器另持有同值的 HttpOnly、Secure、SameSite=Strict `__Host-sentinel_csrf` cookie（Path=/、无 Domain），服务端校验 cookie/header 双提交；它不授予身份。Bootstrap GET 仅在 nonce 缺失/格式非法时生成随机 nonce，否则复用；成功登录生成新 nonce 并将其摘要绑定到账户 session，注销核验该 session 摘要后同时清除两个 cookie。CSRF token 不是独立认证凭证。默认同源交付，若显式跨源，则精确 origins/credentials/exposed headers，禁止 wildcard credential CORS；loopback HTTP 仅验收/本机开发，生产必须按部署 TLS 边界保护凭证。

初始化不能仅靠“数据库未配置”让第一个匿名访问者抢占。部署启动生成或注入一次性 operator authorization code，操作者通过本系统 setup 的授权字段提交 `/system/bootstrap/authorize`；code 不在 URL、localStorage 或日志中回显，部署受控启动提示是独立安全通道。授权创建有时限 HttpOnly bootstrap-operator 会话，仅能检查/初始化/核查本人原请求；不是 admin 会话。授权失败/过期不能检查任意数据库或配置源。

`GET /system/bootstrap` 仅公开初始化是否完成/引导窗口是否开启及是否已有本请求的 operator grant；正式访问 owner 接收其明确投影。未授权时 setup 先呈现启动授权，不假装可执行完整四步。成功初始化关闭窗口，撤销 operator grant，不能再次使用 setup；仍可按受限恢复合同核查原请求结果，且不得回读其凭证。配置数据库暂时不可用不重新开启初始化。

部署持久化完成标记/引导状态必须在数据库以外也可判定，原子锁防两个请求、多个 worker 和重启重复初始化。数据库 credential 及 source direct credential 保存为保护后的服务器配置；本机/K8s 可使用持久 Secret 文件或部署密钥，不强制 KMS。readonly source record 只返回 authenticationMode/credentialConfigured，不返回用户名、密码、Token、引用值或解析内容；修改默认 keep，跨 provider 不复用旧秘密，replace 必须显式选择 none/reference/direct。

连接检查无规则/账号持久写入、不执行发布或驱动数据库 schema 迁移。Python 负责目标 allowlist、DNS/地址检查、连接时 pin、防重绑定/重定向、TLS/认证、有界 timeout；允许部署明确配置的内网/K8s 目标，不允许由任意输入绕过 SSRF 范围。检查失败仅返回稳定分类。

### 9.4 与正式 Port 对应的请求目录

下表是实施路径，不因表存在就勾选 F6.1；每个 DTO/请求/错误/样例都必须补齐后才能冻结。路径相对 `/api/v1`。write-only 密码/连接凭证仅在相应输入内；响应不含其副本。

| 能力 / Port 方法 | HTTP 路径 | 访问 / 结果 |
| --- | --- | --- |
| readBootstrap | GET /system/bootstrap | 公共最小引导事实；不可用不回未初始化 |
| authorizeSetup（前述引导新增） | POST /system/bootstrap/authorize | 一次性 operator code；有限重试/Origin/CSRF，授权非初始化 |
| readSession | GET /auth/me | 身份或明确 null；网络/解析错误不当 anonymous |
| login | POST /auth/login | write-only username/password；确认 SessionIdentity，仍独立 me 回读 |
| logout | POST /auth/logout | 精确 Origin + 当前会话 CSRF 校验后撤销；确认后清除 HttpOnly Cookie 并返回空 204；丢应答不推断已提交 |
| checkDatabase | POST /system/bootstrap/database-check | 有效 operator；类型化连接事实，非迁移 |
| checkSource（setup） | POST /system/bootstrap/source-check | 有效 operator；类型化连接事实，非登记/发布 |
| initialize | POST /system/bootstrap/initialize | operator + requestKey；安全 InitializationObservation |
| readInitialization | GET /system/bootstrap/operations/{requestKey} | 同 operator 原请求；非仅知道 key 就可读取 |
| listAccounts / readAccount | GET /accounts；GET /accounts/{accountId} | admin；Page<AccountRecord> / 明确目标 |
| mutateAccount | POST /accounts/commands | admin；create/status/role 判别联合、独立 account revision |
| readAccountOperation | GET /accounts/operations/{requestKey} | 本会话授权原操作；安全 AccountOperationObservation |
| changeOwnPassword | POST /auth/password | 当前会话选本人，不接目标 accountId；当前服务成功后固定返回 `reauthenticate` |
| 观察环境/应用目录（App 装配所需） | GET /observation/catalog | 有效会话；只用于有界环境/应用选择，不从一页实例推断目录 |
| readFleet | GET /fleet/overview | metrics:view；FleetSnapshot，摘要总数与本页分开 |
| readCatalog / readInstance | GET /instances；GET /instances/{instanceId} | metrics:view；环境/应用/窗口、详情 incarnation/scope 完整 query |
| readMetrics | GET /metrics/query | metrics:view；MetricBundle，显式 metrics/window/scope/step |
| readTimeline / readEvidence | GET /incidents；GET /incidents/{incidentId}/evidence | metrics:view；有界窗口/过滤/分页/明确事实身份 |
| readBindings | GET /rulesets | 会话；environment/app/kind/search/page/pageSize |
| readBindingRegistration | GET /rulesets/{bindingId}/registration-operations/{requestKey} | admin + `rules:write`；当前 admin session 重新授权，精确读取原 actor/binding/requestKey 的安全回执；`not_found` 不证明 POST 回滚，禁止自动重发 |
| readSnapshot | GET /rulesets/{bindingId}/snapshot | 会话；完整 RuleSetSnapshot、profile、来源及独立 revision |
| readDrafts / readDraft | GET /rulesets/{bindingId}/drafts；GET /rulesets/{bindingId}/drafts/{draftId} | `rules:write`（当前由 admin 唯一持有）；草稿内容及修订 |
| validateCandidate / compareCandidate | POST /rulesets/{bindingId}/validate；POST /rulesets/{bindingId}/diff | `rules:write`（当前仅 admin 持有）+ CSRF；两者均非幂等命令。validate 持久化校验 receipt/审计但不改规则源；diff 不产生持久化写入 |
| readVersions / readVersion | GET /rulesets/{bindingId}/versions；GET /rulesets/{bindingId}/versions/{versionId} | 会话；不可变完整版本；有界集合 |
| readPublications / readPublication | GET /rulesets/{bindingId}/publications；GET /rulesets/{bindingId}/publications/{publicationId} | 会话；受理/校验/写/回读分别返回 |
| readReceipts | GET /rulesets/{bindingId}/publications/{publicationId}/receipts | 会话；Page + 覆盖，processEpoch/desired/applied/status 不混淆 |
| readPlans | GET /rulesets/{bindingId}/plans | 会话；持久草案/执行事实，浏览器不调度 |
| readRulePublicationTarget | GET /rulesets/{bindingId}/publication-target | 会话；binding 精确配置中心目标及 target/source revision；未配置显式返回 null，不返回凭证 |
| mutateRuleSet | POST /rulesets/{bindingId}/commands | admin role + `rules:write`；7 种明确 command，不合并为万能 patch |
| readRuleOperation | GET /rulesets/{bindingId}/operations/{requestKey} | admin role + actor/绑定/原请求归属；无秘密，不能跨绑定读 |
| readConnections / readProtocols | GET /system/connections；GET /system/protocols | 会话；后台各自真实健康/协商事实，非 browser online |
| readAudit | GET /system/audit | admin；独立窗口与稳定排序 Page，不借 chart query |
| readSources | GET /system/sources | admin；readonly 无凭证 SourceRegistrySnapshot |
| checkSource（normal） | POST /system/sources/check | admin；有限输入、keep/replace、检查无登记副作用 |
| mutateSource | POST /system/sources/commands | admin；register/update 与独立 revision |
| readSourceOperation | GET /system/sources/operations/{requestKey} | admin 原操作；无 write-only 秘密 |

`GET /system/audit` 的每条记录仅含有界、脱敏的动作事实。计划创建和取消记录保留发起账号；由持久化 worker 执行的计划启用/恢复记录使用空 `actorId` 表示系统执行，并以计划 ID 为目标，不伪造浏览器账号或会话。与规则发布关联时，记录同时投影可空的 `environmentId`、`appId`、`bindingId` 与 `publicationId`；publication 深链必须携带这些明确身份，不能仅凭 binding 或当前筛选猜测环境/应用，也不得返回规则正文、凭证或原始异常。

规则命令 kind 为 save_draft/delete_draft/freeze_version/publish/create_plan/cancel_plan/configure_target，各自专有严格 body。目标配置使用已绑定的 sourceId、当前 sourceRevision 与 nullable expectedTargetRevision；Nacos 由管理员指定 namespace/group/dataId，Consul 指定 key，datacenter 由注册源事实确定。target 写入、幂等回执和审计同事务；命令/审计不存凭证或规则正文。删除草稿与取消计划使用原对象 revision；冻结引用确切草稿 revision/validationId/candidateChecksum；发布引用不可变 versionId/versionChecksum 和用户已确认的源基线；回滚复用 publish 创建新记录。计划含明确目标/恢复版、UTC 半开窗口/IANA timezone、重叠及当前 revision，后台重启恢复，不用前端 timer。

`POST /rulesets/{bindingId}/diff` 仅做非持久化比较，不构成 publish validation。请求 path/body binding、profile、kind 与当前快照必须精确一致，且 `baseVersionId`、`baseChecksum`、`sourceRevision` 必须仍匹配；基线变化或候选引用未知记录返回 409。`recordId: null` 表示新增，已知 identity 的规则值变化表示替换，候选省略基线 identity 表示删除。所有候选值先按五类 Sentinel typed rule 进行严格字段与领域校验；不接受未知字段。`candidateChecksum` 由服务端对已校验候选规则按输入顺序构造紧凑 UTF-8 JSON（对象键排序、禁止非有限数值）后计算 SHA-256，并以 `sha256:<lowercase hex>` 返回；客户端只将它作为 opaque 值保存/回传，不自行重算。该 digest 只标识本 Console 的规范化候选，不代表 Nacos/Consul codec 可写或可发布。

`sentinel-source-nacos` 的纯 `encode_rule_snapshot` 面向 Sentinel Python runtime `RuleSnapshot`，不等同于 Console 五类规则 API 的 profile codec。Console 现有共享 camel-case `rule_value_fields` 投影与 `SentinelRuleVersionJsonEncoder`，可将 immutable `RuleSetVersion` 编成不含 Console identity wrapper 的同类规则 JSON array；当前证据仅证明本地类型到 wire 字段的映射，不证明 Java SDK/RuleSource 解码兼容。Console `validate` route 已增加，但 production 尚未装配 profile validator/持久 validation receipt authority；Nacos conditional publish/read-back 与编码器到 provider worker 的 composition 尚未实现，不得将未装配状态宣称为 publishable 或接受 freeze/publish。

`POST /rulesets/{bindingId}/validate` 的 Python route 已拆为三个显式职责：`RuleSetSnapshotReader` 读取当前完整规则快照，`RuleCandidateProfileValidator` 对当前 binding/profile 做纯语义校验，`RuleValidationReceiptWriter` 在响应前持久化不可变 receipt。`SqlAlchemyRuleValidationReceiptStore` 实现 receipt reader/writer；receipt 与 `rules.validate` 审计行同事务提交，只存 candidate checksum、有限 issue code/字段路径、actor/request identity，不存规则正文或配置凭证。无 snapshot/profile validator/receipt writer 时安全返回 503，候选 baseline 过期返回 409。当前尚无 production provider profile validator 或 production startup composition，因此 route 存在和 SQLite migration 测试都不表示 Nacos/Consul 候选可发布；freeze 必须从持久化 receipt authority 再读取并核对 exact candidate。

账号接口错误矩阵按当前 Python 路由实际可达分支冻结：`listAccounts`、`readAccount` 与 `readAccountOperation` 为 `invalid_request`、`unauthenticated`、`forbidden`、`service_unavailable`；`mutateAccount` 另允许 `csrf_failed` 与 `idempotency_conflict`。账号路由当前没有 rate-limit 分支，因此不得在这些 operation 上声明 `rate_limited`；操作查询的未知 requestKey 是安全的 `not-found` 操作观察值，不是 HTTP `not_found`。V1 账号命令在单个 HTTP 请求内同步完成，成功 HTTP 响应仅返回最终 `completed` 或 `rejected` 回执；UI 的 `pending` 表示 HTTP 请求仍在途，不是账号 wire 回执。若响应丢失，客户端保持 `result-unknown` 并通过 operation lookup 核查最终回执；lookup 可返回 `not-found`、`completed` 或 `rejected`。
账号从 `active` 变为 `disabled` 时，服务端必须在同一数据库事务内撤销该账号全部现有 session；重新启用账号不会恢复或重新签发旧 session，旧 Cookie 仍须重新认证。此持久状态迁移属于账号命令的完成语义，不由前端模拟。

本人改密 `changeOwnPassword` 的错误集合为 `invalid_request`、`current_password_invalid`、`unauthenticated`、`csrf_failed`、`validation_failed`、`rate_limited`、`service_unavailable`；此路由按当前会话账号执行，没有 role-based `forbidden` 分支。

规则读取错误按权限能力拆分：binding/snapshot/version/publication/receipt/plan 读取为 `invalid_request`、`unauthenticated`、`not_found`、`rate_limited`、`service_unavailable`；draft collection/detail 与 command-operation lookup 另有 `forbidden`。publication-target 读取只会返回 `invalid_request`、`unauthenticated`、`service_unavailable`，未配置目标（包括不存在的 binding target）以 `target: null` 表示。`mutateRuleSet` 的 HTTP 错误集合为 `invalid_request`、`unauthenticated`、`forbidden`、`csrf_failed`、`idempotency_conflict`、`validation_failed`、`rate_limited`、`service_unavailable`；已授权且格式有效命令中的业务冲突/不存在/不支持/语义拒绝作为持久化 `202` `rejected` operation（有限 reason），不能伪装成可重试的 HTTP 409/404/422。HTTP 409 仅在 requestKey 冲突等明确 transport 前置条件触发时使用。

观测读取错误矩阵按具体目标语义区分：fleet、instance catalog、incident timeline/evidence 均可能返回 `invalid_request`、`unauthenticated`、`forbidden`、`not_found`、`rate_limited`、`service_unavailable`；instance detail 与 metrics query 另可返回 `target_retired`，表达 incarnation 已退役，不等同于普通 404。事件 timeline 的环境/应用等查询目标也可能在权威目录中不存在，因此必须声明 `not_found`。

登记配置源的 `checkRegisteredSource` 是 admin + CSRF 的非幂等探测，错误为 `invalid_request`、`unauthenticated`、`forbidden`、`csrf_failed`、`rate_limited`、`service_unavailable`；`mutateRegisteredSource` 是幂等命令，错误为 `invalid_request`、`unauthenticated`、`forbidden`、`csrf_failed`、`idempotency_conflict`、`validation_failed`、`rate_limited`、`service_unavailable`。客户端若收到含合法 `retryAfterMs` 的 `rate_limited`，来源检查 workflow 必须在单调时钟下保留绝对冷却截止时间；表单字段编辑、旧探测结果失效或 UI 重渲染不得重置该截止时间，且所有检查触发入口都必须在期限内阻止再次派发。该限制只在期限到达后解除，不进行自动重放。配置源 revision/provider 冲突作为已受理的 operation rejection 表达，不是 HTTP `conflict`；原操作查询另允许路径 key 非法时 `not_found`。

### 9.5 命令一致性、条件写与观测

支持核查的 setup/account/rules/source command 必须带请求键，HTTP `Idempotency-Key` 与 body requestKey 一致；它只是相关性，不是授权。服务端按 actor/operator + capability/目标 + kind 归属，保存原输入的服务端 keyed HMAC（不是可离线猜密码的裸哈希或原凭证 body）。同 key/同输入观察原操作，不重写；同 key/异输入 409。核查只返回原安全结果，不能给另一 actor、未授权 session 或外来 binding 偷看；同一 actor 重新认证后须重新检查当前权限，不能仅因 Cookie 已轮换就永久失去原操作核查路径，旧页面资源仍不得跨 sessionEpoch 复活。

规则绑定创建是同步 `201`，但仍提供独立的只读核查路径 `GET /api/v1/rulesets/{bindingId}/registration-operations/{requestKey}`，用于创建请求已发出、原 Cookie 轮换或响应无法确认后的安全恢复。服务端必须在查询中重新验证当前有效的 admin session，并以原 `actor + bindingId + requestKey` 精确匹配持久回执；同 actor 的新有效 admin session 可读取原安全回执，但不能读取其他 actor、错误 binding 或错误 requestKey 的事实。响应仅含 `completed` 与原 `RuleBinding` 安全视图，或 `not_found` 与 `binding: null`，不返回 target body、凭证或原 session hash。`not_found` 可能是可见性/提交结果未知，不表示创建已回滚，前端必须继续只读核查，不能因此解锁或自动重发 `POST`。原 `POST` 的幂等恢复仍严格要求原 actor、原 session 与相同 canonical fingerprint；此读权限不放宽写入幂等约束。

安全操作事实为 pending/not-found/completed/rejected；not-found 可能是可见性滞后，不证明未提交；前端不能因此解锁或重发。命令接口成功返回“操作事实”并不代表业务成功：rejected 明确有限 reason，completed 的 publication 仍有各阶段状态。尚未通过授权/shape/请求键一致性检查的请求直接 HTTP 错误，不创建伪已受理结果。幂等保存、业务持久化和审计须有事务/恢复路径，不能先写源再靠 browser 标已成功。

已发写请求收到畸形 JSON、错误 DTO、缺失/错误 Content-Type 或未按合同定义的错误体，也不证明事务未提交。adapter 必须把这种无法验证的应答归为未确定结果，原 requestKey 仍锁定；不能仅以本地 parser error 标“可重试”再发写。发送前的请求 Schema 校验错误则是可修正输入，二者必须有独立测试。

登录/改密不持久缓存密码请求或成功响应。本人改密只有当前会话 actor，确认 receipt 的 session policy 是服务端事实；未知结果不自动重放，也不能把 me 成功当成改密成功。登录仍独立回读 me 确认身份，失去应答不默认 admin。

配置源发布须在 Python 执行真实 conditional write/CAS + 回读；后端配置源能力不满足则拒绝发布，不用 process 内锁或先 get 再 unconditional put 假装多控制台安全。源版本/Console 记录分别持有，写成功、内容回读、runtime 加载独立。无法确认写结果时保留不确定状态/原请求核查；读回新源不抹除旧基线草稿。当前 Cluster quota runtime 不支持热更新的 profile 明确 restart_required，不算 applied。

指标/故障/系统健康来自独立 Console 观测读模型；保持已冻结 Agent Reporting V1 六类事件，绝不为填图临时新增 wire kind/塞 metrics。未采到 QPS/TPS/histogram/host 数据时显式 not_integrated/no_samples；初始化或规则写成功不能伪造图表点。开发 HTTP Mock 可用确定性独立模拟采集状态，但不得将其展示为真实 Python/Collector 接线证明。

### 9.6 后续退出条件（0.7.0 历史快照；当前以 §13 为准）

本节首段记录的是 0.7.0 生成物快照；当前规范与机器版本为 0.19.0，64 paths / 68 operations，新增规则目录内容以 §13 及当前 `console-api.openapi.json` 为准。

当前可生成机器入口为 `docs/protocol/console-api.openapi.json`：`npm run contract:generate` 从 feature runtime DTO/endpoint declarations 生成，`npm run contract:check` 拒绝漂移。冻结版本为 **0.7.0**（0.4.0–0.6.0 既有 wire 保持不变），生成物包含 **47 paths / 48 operations**、`x-contract-status=frozen`、`x-pending-capabilities=[]`，覆盖 authentication、bootstrap、accounts、own-password、metrics、fleet、instances、incidents、system-observation、system-sources、observation-catalog 和 rulesets。每个 operation 必须有 `x-required-access`，明确 `role` 与能力数组；它与 `security` 分离，后者定义 session/bootstrap/CSRF 凭据要求，前者定义会话之外的角色/能力门槛。声明 query 参数的 operation 另带 `x-query-policy`：未知参数和重复参数都必须拒绝，并以 `400 invalid_request` 返回；Python parser 按 URL 解码后的查询键检查，不能依赖框架默认的首值/末值选择。整数 query parameter 另带 `x-query-integer-encoding=canonical-decimal`：只接受 ASCII 十进制规范表示，不接受前导零（数值零仅写作 `0`），数值范围由该参数 schema 声明。`pending=[]` 只表示生成器声明的 endpoint family 已有 machine contract，不证明 Python 实现、真实数据或 E2E 已完成。204 无 JSON Schema，资源级约束仍列于 `x-semantic-rules`，不使用 `unrepresentable:any`。所有 Zod 字符串 `.max(n)` 同时生成 `maxLength: n` 和 `x-max-utf16-code-units: n`：标准 JSON Schema 的 `maxLength` 按 Unicode code points 计数，Console 前后端运行时则按 JavaScript/Python UTF-16 code units 限制；消费者必须同时执行标准约束与该扩展约束。初始化命令 ACK 不接受 not-found，原操作 lookup 可以返回 not-found，二者不得混用。

请求固定使用且必须恰好包含一个 `x-request-id`（客户端相关 ID，响应 header/body 对应一致）、内存态 `x-sentinel-csrf` 与命令 `idempotency-key`。缺失、重复或格式非法的 `x-request-id` 以 `400 invalid_request` 拒绝；错误响应不得回显非法值，使用服务端生成的 request ID。登录/注销通过当前会话事实核查未知结果，不建立幂等操作查询；账号、规则、源及初始化命令则要求原 requestKey。后台按当前 Cookie/Origin 授权，不相信 legacy x-user-id。传输 owner 是本次鉴权/引导观察 generation，不得直接用 React 的 checking/匿名显示状态拼接；App 装配须证明实际换会话的迟到请求、CSRF 切换及新的 Cookie 读回。

逐页 wire schemas / 完整 endpoints / OpenAPI / 正负样例 → 同一 foundation HTTP adapter + 未匹配 Console 请求拒绝的 MSW → App 正式 async DI / 删除旧路径 → mock 与受控 live 同实现 → Python 真实 DB/源/重启/权限 E2E。每步单独留证，不以 schema、HTTP 200、compile 或内部探针代替后续层。最终验收以执行清单 F6/F7/B0 为准。

## 15. Console API 0.10.0 增量：本机首次初始化授权

0.10.0 新增 `POST /api/v1/system/bootstrap/authorize-local`。请求严格为空对象 `{}`，成功响应为 `{authorized:true}` 并设置短时、HttpOnly、SameSite=Strict 的 bootstrap grant；该 grant 仅允许首次配置步骤，不创建也不代表管理员会话。

此路由仍要求精确允许的 `Origin`、CSRF cookie/header 双提交及有效 request ID。授权层同时要求部署明确判定允许本机免码路径、setup window 仍开放，并且真实连接 peer 是 loopback。部署只有在 bind host 是 loopback、所有允许的 Browser Origin 都是 loopback，且未配置可信反向代理时，才启用该路径。其他拓扑继续通过既有 `POST /api/v1/system/bootstrap/authorize` 提交部署生成的一次性 `operatorCode`；本机 endpoint 不接收或推断 operator code。

错误语义为 `400 invalid_request`、`403 forbidden`/`csrf_failed`、`409 conflict`（setup 已关闭）、`429 rate_limited`（含有界 `retryAfterMs`）和 `503 service_unavailable`。此新增不改变既有远程授权、初始化提交/回执、登录或 Console API 0.9.0 规则观察 wire。发行包的 key/path 初始化仍是独立安装运维事项；本机免码不意味着允许公网访问或绕过 Origin/CSRF/setup 状态门禁。

0.10.0 于 **2026-10-17 由产品/API owner 批准**。批准范围仅为 loopback 本机首次授权路由，不代表 Prometheus monitoring-source API 已冻结、Console wheel 发布或最终 E2E 已通过。

## 16. Console API 0.11.0 增量：监控源候选检查

0.11.0 新增 `POST /api/v2/monitoring/sources/check` 与
`GET /api/v2/monitoring/sources/checks/{checkId}`。这些操作只冻结一次只读候选检查和其短时回执查询；监控源目录、详情、保存/删除命令及 host metric query 仍需各自完成设计与后续兼容扩展，不由本增量假定已经实现。

- POST 仅 admin 可用，须精确 Origin 与 CSRF；输入严格由 profile/source candidate 与 credentials 组成。支持无认证、直接 Basic/Bearer，以及由部署侧 resolver 解出的 opaque credential reference。引用值永远不会作为 Prometheus 凭证发送；resolver 不存在或失败返回脱敏 `503 service_unavailable`。
- 候选固定为 `prometheus-compatible` + `node-exporter-v1`，不接收任意 PromQL；身份标签/精确 selector、抓取间隔、stale 阈值和 body 均有界。候选检查只对目标发只读请求，不写 source registry 或 Prometheus scrape 配置。
- 成功响应只含随机 `checkId`、source id/revision、候选 HMAC 指纹、检查/过期时间，以及有限 connection/queryApi/profile/identity 计数和错误类别；不会回显 endpoint、原始 label、异常文本、凭证、reference 或响应 body。SQL 回执只存这些安全字段、actor 与 session digest，TTL 为 10 分钟。
- GET 要求当前有效 admin session，且必须是创建该回执的同一 account 与同一浏览器 session；过期或不匹配返回 `not_found`。响应使用 `no-store` 与 `Vary: Cookie`。
- 该检查回执尚未被 source mutation 消费；在候选保存命令冻结并实现前，不得把探测成功当作配置已保存或监控数据已接入。

0.11.0 于 **2026-10-17 按产品 owner 已授权的推荐默认值冻结候选检查边界**。冻结只涵盖两个 operation 的 wire，不等于完整 T05.3、真实 Prometheus/Exporter 验收、PostgreSQL/MySQL migration 验收或浏览器 E2E 通过。

## 17. Console API 0.12.0 增量：安全监控源读取

0.12.0 保留 0.11.0 候选检查与回执 wire 不变，新增：
`GET /api/v2/monitoring/sources`（已登录的 admin/view 可读）与
`GET /api/v2/monitoring/sources/{sourceId}`（仅 admin 可读）。目录只返回有界的安全元数据，不返回 endpoint 或凭证；详情也只暴露 endpoint 的 scheme/authority，路径和认证材料始终 write-only。二者均 `no-store` 且 `Vary: Cookie`。

该增量让系统管理页面能从正式 SQL registry 读取监控源目录/编辑上下文，不代表保存、修改、停用、删除命令或 HOST 历史查询已接通；不存在来源时返回空目录是正常状态，来源不存在返回 `404 not_found`。命令幂等、revision 更新、依赖引用冲突与对应 UI 将由后续 additive API 增量冻结，不能把 candidate check 当作保存成功。

生成快照为 `docs/protocol/console-api-0.12.0.openapi.json`；0.11.0 历史快照 `docs/protocol/console-api-0.11.0.openapi.json` 仅保留原候选检查 API。

## 18. Console API 0.13.0 增量：监控源管理命令

0.13.0 在不改变 0.12.0 读取 DTO 与既有 operation wire 的前提下新增：

- `POST /api/v2/monitoring/sources/commands`：仅 admin；要求有效会话、同源 `Origin`、CSRF 与唯一 `Idempotency-Key`。请求是严格判别联合 `create | update | set-enabled | delete`。更新/启停/删除使用当前 `expectedRevision` 做 compare-and-swap；创建/更新必须提交当前操作者、当前浏览器会话创建的未过期成功检查回执，或明确指定跳过检查。跳过检查的已保存来源明确标记 `verified=false`；单独启停保留现有 endpoint、profile 和加密凭证，不需要将凭证重新输入或回显。
- `GET /api/v2/monitoring/sources/operations/{requestKey}`：仅原 account + 同一浏览器 session 可读；其他身份看到 `not_found`，不会泄露操作是否存在。回执可安全重试读取，不得因客户端超时换 key 重放写命令。

来源变更、探测回执消费、幂等操作记录和安全审计事件必须在同一 SQL transaction 中原子提交。重复相同 key 与相同 canonical 输入返回原结果且不重复副作用；相同 key 用于不同输入返回 `409 idempotency_conflict`。凭证以 write-only 形式输入，仅加密保存；响应、目录、操作回执和审计不得回显 endpoint 完整路径、秘密、密文或 credential reference。凭证更新必须显式指定 `keep | replace | clear`，不以省略字段猜测意图。

命令回执只包含 `completed | rejected`、requestKey、source ID/revision、enabled/verified 和有限拒绝原因；操作查询找不到或不属于当前会话时统一返回 `not_found`。版本冲突、来源缺失、检查缺失或候选不匹配均为安全拒绝，不泄漏 SQL/Provider 异常。此增量冻结 HTTP 线形及事务不变量，不代表三个 SQL 方言、真实 Prometheus、UI 管理工作流或最终 E2E 已通过。

生成快照为 `docs/protocol/console-api-0.13.0.openapi.json`；0.12.0 快照继续保留原安全读取 operation 集合作为不可变历史版本。

## 19. Console API 0.14.0 增量：HOST 指标查询

0.14.0 新增只读 `GET /api/v2/monitoring/sources/{sourceId}/host-metrics`，访问要求已登录且具备 `metrics:view`。请求只接受 `from`、`to`、`stepMs` 三个参数；时间区间为 UTC 半开区间 `[from,to)`，点数超过每序列 1,000 时在访问 provider 前拒绝。端点、凭证、selector 与 PromQL 只能来自服务端保存的监控源，不从浏览器接受。

响应最多包含 200 个稳定 host identity 和四类固定 metric：CPU busy ratio、memory used bytes、memory used ratio、Linux load1。每个 host 必须有四条 metric identity；各序列最多 1,000 个真实样本，并携带 unit、quality、reason。未采到的点必须保持缺口；`no_samples`、`partial`、`stale`、`not_integrated`、`unavailable` 不得折叠成零。响应只暴露配置的身份标签，不回传 Prometheus 其他标签、原始 provider 错误、endpoint、凭证或 PromQL。

HOST 与现有 PROCESS Metrics V2 是独立事实域：该 API 不推断应用 QPS/TPS，不写入 SQL 时间序列，不改变 PROCESS 的 metric denominator、scope 或 wire。Python 侧由固定 `node-exporter-v1` Prometheus Adapter 查询，保持部署管理的目标 allowlist/pinned transport、认证 secret resolver、固定 PromQL、查询超时与响应边界。当前接口定义和 focused test 通过不代表真实 Prometheus、Collector 部署引导、React 图表或完整 E2E 已验收。

生成快照为 `docs/protocol/console-api-0.14.0.openapi.json`；0.13.0 快照保持不可变。

## 20. Console API 0.16.0 增量：历史进程规则加载观察

新增只读 `GET /api/v2/rules/load-observation-history`，要求已登录。请求必须提供精确的 `environmentId`、`appId`、`bindingId`，可选 `instanceId`，并使用有界 `page`/`pageSize` 分页。只读 SQL Collector durable inbox，不同步访问 Nacos/Consul。

响应只包含已持久化的观察元数据、规则指纹和 Collector 收件时间，并将 process epoch 标注为 `superseded`、`revoked` 或 `no_current_epoch`。当前 epoch 的事件被排除；历史页与 `GET /api/v2/rules/load-observations` 的当前目标目录及计数严格分离。缺少 binding 时 coverage 为 partial；对存在的 binding，complete 且 total 为 0 仅表示保留的历史观察中没有记录，不代表没有实例或规则未加载。证书 principal、凭证、原始 body 和规则正文不出现在响应中。

本增量不修改既有当前态 API，不引入新事件存储或修改 Agent Reporting、Runtime Receipt、Metrics V2 wire。生成 OpenAPI 快照为 `docs/protocol/console-api.openapi.json`；旧版本历史快照不覆盖。

## 21. Console API 0.17.0 增量：部署引导目录

新增只读 `GET /api/v1/system/deployment-guides`。仅已登录的 `admin` 与 `view` 可读取；响应使用 `Cache-Control: no-store` 和 `Vary: Cookie`。接口返回 Console release 拥有的目录修订号、有限的 `existing | linux | kubernetes` 路径、当前路径 readiness，以及可选的 Runtime Collector 显式公布 HTTPS endpoint。

本版只冻结目录身份和 readiness 元数据：existing path 表示还需配置并验证已有 Prometheus 查询源；Linux/Kubernetes 当前为 `guide-only`，不声称已有已验证安装模板或可执行部署产物。页面说明由 React 本地化资源提供；经过版本固定、安全审查和 profile 验收的安装/配置 artifacts 才能在后续 additive API 版本中由服务端目录提供。Console 不远程安装 exporter、创建 Prometheus scrape target、修改 Kubernetes 或配置 Runtime。

Runtime Collector endpoint 仅来自部署者显式设置的 `SENTINEL_CONSOLE_RUNTIME_COLLECTOR_ADVERTISED_URL`，要求 HTTPS 且禁止 user-info、query、fragment；未配置时响应 `state=not_configured, endpoint=null`。不得从 Console/Collector bind 地址、`Host`/`Forwarded` 请求头、浏览器 localhost 或 Reporter 配置推断可达地址。该 endpoint 与 Prometheus 查询地址、Exporter scrape target 是不同字段与不同职责。

生成的 `docs/protocol/console-api.openapi.json` 包含 0.17.0 响应 schema 与未配置示例。API 接口与 DTO 的定向测试通过，不代表 Linux/Kubernetes 部署已经验收，也不关闭 T05.3/T05.4/T07.1。

## 22. Console API 0.18.0 增量：监控源删除引用保护

删除仍被 `console_host_instance_association` 引用的监控源，返回 durable
operation receipt：`status: "rejected"`、`reason: "source_in_use"`。源记录、关联、探测回执和版本均保持不变；操作回执与拒绝审计按常规事务持久化。前端提示管理员先移除主机实例关联再重试。0.17.0 的历史 OpenAPI 快照保持不变。

## 23. Console API 0.19.0 增量：管理员账号生命周期

`POST /api/v1/accounts/commands` 增加两个严格命令变体，仍要求 admin 会话、Origin、CSRF 和 header/body 相同的幂等键：

- `reset_password`: `{ kind, requestKey, accountId, revision, password }`。password 是只写的 8–32 UTF-16 码元；不要求目标旧密码或确认密码。创建账号、初始化管理员和所有新密码均采用 8–32 UTF-16 码元（含边界），不 trim 或 Unicode 归一化；连接凭证有独立长度限制。事务内校验目标版本并更新 Argon2id 摘要、撤销目标全部会话；不改变停用状态。登录发放会话时还会锁定并比对已校验密码摘要，拒绝跨重置竞态的旧凭证登录。
- `delete`: `{ kind, requestKey, accountId, revision }`。设置逻辑删除时间与 disabled，撤销全部会话。目录排除、详情返回 null、登录拒绝；用户名继续占用，审计、版本、发布和原操作回执保留。前端确认框输入账号名只是本地防误触，不进入命令 DTO。

内置账号拒绝管理命令，但当前 admin 可通过 `reset_password` 重置自己的密码；该事务会更新摘要并撤销目标账号的全部会话，成功后必须重新登录。自身 `delete` 返回 `self_operation`；内置账号仍不能停用或降级。本人也可继续通过 `/auth/password` 使用旧密码修改。最后有效管理员不能停用、降级或删除。目标删除后旧 revision 不能复活身份。事务串行化、CAS、HMAC 幂等摘要与审计沿用原通道；同键异密码是 409，相同命令读回原最终安全快照，不返回密码或哈希。

completed 回执沿用安全 AccountRecord；delete 回执为删除时的 disabled 快照，不表示其仍存在于目录。操作 lookup 可读回该原快照；账号读接口继续返回 null。数据库迁移 `0041_account_lifecycle` 增加 nullable tombstone 并扩展拒绝原因约束；既有账号不改变密码、状态或角色。OpenAPI 当前生产版本更新为 0.19.0。
