# Console API 契约（草案 v0.1）

> 状态：**草案，待后端确认**。本文冻结前端与控制面服务之间**必须一致**的部分，
> 让 gateway 替换 fixture 时不需要改页面。§「待确认」列出尚未与后端对齐的项。
>
> 依据 `DASHBOARD_CONTROL_PLANE.md` §6.1「契约先行」：先冻结配置键映射、完整快照
> 发布状态、最小权限、指标口径与实例生效回执。

## 0. 范围与不做什么

**做**：控制台读写规则快照、读连接与指标状态的 HTTP 契约。

**不做**（原文 §2 已划界）：

- 不提供多租户、组织树、数据范围授权、多级审批；
- 不做连接凭证的网页写入——地址与写凭证由部署配置管理；
- 不承诺长期历史与告警（§6.4，后续独立评审）。

现有 per-process Bearer admin token 与统一控制台的登录授权是**两套边界**，
不相互冒充（§2 末句）。

## 1. 最小权限

沿用已落地的 `core/session`：`metrics:view` 与 `rules:write` 两项，**可独立授予**。

| 能力 | 允许 | 服务端行为 |
| --- | --- | --- |
| `metrics:view` | 指标查询、趋势图、实例指标详情 | 无此能力时返回 `403`，**不返回空数组或 0 值** |
| `rules:write` | 快照读取、草稿校验、发布、回滚 | 无此能力时读取快照仍允许，写操作全部 `403` |

登录用户**始终可读**规则摘要、版本与规则源健康状态，不要求任何能力。

`403` 与「没有数据」是两件事：`403` 必须在响应体里带 `error.code = "capability_denied"`，
客户端据此区分「无权」与「确实为空」。把无权渲染成空图就是用 0 值伪装无流量。

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
| 400 | `validation_failed` | 显示字段级问题，保留草稿 |
| 401 | `unauthenticated` | 回登录页 |
| 403 | `capability_denied` | 隐藏对应入口，不显示空数据 |
| 409 | `version_conflict` | 提示基准版本已变，要求重新拉取后再提交 |
| 422 | `readback_mismatch` | 停在 `read-back-matched` 之前，**不重试写** |
| 503 | `config_center_unavailable` | 显示配置中心不可用，区别于「规则为空」 |

`422 readback_mismatch` 不自动重试：写入成功但回读不一致时，重试可能放大不一致。

## 8. 待确认（需后端对齐后才能冻结）

1. 配置中心的**真实 schema**与 §2 映射表是否逐字段一致——Nacos 与 Consul 两侧
   的差异由适配器吸收还是由契约暴露？
2. `scope` 曾以中文作为协议值流通，历史数据如何迁移到 `application` / `resource`？
3. 回执的实例身份来自哪个字段（`instanceId` 还是 `host:pid`）？
4. 指标后端的查询接口形态未定；契约先按参数化查询占位，§4 的口径不因后端形态改变。
5. 草稿的乐观锁用 `version` 还是独立的 `etag`。

在 1~3 确认前，gateway 继续读 fixture，但**页面侧的键映射与状态机已经按本文冻结**——
契约先行要冻结的是这些跨边界的约定，不是先造一个假的服务端。