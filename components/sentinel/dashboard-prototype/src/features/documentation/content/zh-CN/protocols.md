---
title: 协议、标准与兼容性参考
summary: 区分行业接口、官方格式和本项目自己的契约。
prerequisite: 熟悉接入与观测的基础内容。
outcome: 知道每条链路的用途、认证方式和兼容边界。
---

## 复用的成熟接口

下面这些是业界已有的接口和机制，Sentinel 直接复用它们，没有另造一套。

| 接口或机制               | 用途         | 在哪用                     |
| :----------------------- | :----------- | :------------------------- |
| Nacos 配置 API / 客户端  | 读写配置     | 规则来源与发布             |
| Consul KV HTTP API       | 读写键值     | 规则来源与发布             |
| Prometheus HTTP 查询 API | 查询时序样本 | 主机监控                   |
| TLS / X.509 mTLS         | 双向身份认证 | Reporter 与 Collector 之间 |

> **提示** 这不代表任意 Sentinel Dashboard、Actuator、OTLP 或 exporter 都能直接接入。当前主机采集 profile 是 node-exporter-v1，以实际配置、解析和协商能力为准。

## 本项目自己的版本化契约

下面这些是本项目定义的协议，不是行业标准。它们各自有独立的版本号。

| 契约                                 | 用途                 | 关键内容                                        |
| :----------------------------------- | :------------------- | :---------------------------------------------- |
| Console API                          | 前后端 HTTP/JSON     | 以 OpenAPI 定义接口、DTO 与错误约定             |
| Reporting V1                         | 上报的基础信封       | 上报体的通用结构                                |
| Metrics V2                           | 指标快照与语义       | 指标定义、范围，以及持久回执                    |
| Rule Load Observation V1             | 报告实际加载了什么   | 来源修订号、字节摘要、规范化摘要、成员清单      |
| Rule Publication Receipt V1          | 精确关联一次发布     | 绑定标识、发布标识、目标版本标识、状态          |
| Managed Rule Publication Envelope V1 | 在原生规则外加元数据 | 封装层、载荷摘要；只有显式启用的 profile 才消费 |
| Incident Event V1                    | 独立发送故障事件     | 由 Collector 持久化供控制台查询                 |

## 原生数组与托管信封

原生数组就是配置中心里的 JSON 数组，每个元素一条规则。托管信封在外面套一层，加上绑定与发布标识，让运行时能把「这次加载」和「这次发布」关联起来。

两者不能混用。迁移前要确认全部消费者都支持目标格式。托管信封里的空数组表示权威的空规则集，这和原生规则里空数组的历史语义刻意不同。

> **提示** Runtime 必须按绑定显式启用 managed-envelope-v1；原生数组消费者不会自动解包。Console 读取到对象形态时仍会严格验证封装，并核对目标 binding，不能因此自动迁移 Runtime 的 profile。

## 兼容性从哪里来

兼容状态来自认证后的真实协商结果，不是配置文件里写的版本字符串。写上某个 profile 名不等于协商成功。

未知或未建模的字段一律拒绝，不会被静默忽略后写回配置中心。这是本项目的一条硬规则：宁可整个候选被拒，也不要让配置看起来生效而实际没保护。

## 这些协议之间的关系

下面这张表把每条契约放回链路：谁产生、谁消费、回答什么问题。看清这三条，就不会把「发布成功」当成「已经生效」。

1. 先分清这次要回答哪一类问题：控制台接口怎么用、指标口径是什么、还是这次发布和这次加载对不对得上。
2. 涉及托管发布时，分别核对 Console 的写入与回读结果、Runtime 的 Rule Publication Receipt V1，以及 Rule Load Observation V1 的加载事实。原生规则没有托管 publication_id，使用加载观察确认，不能要求它提供托管发布回执。
3. 涉及指标的，先确认 Metrics V2 的快照被 Collector 收下，再看查询窗口。Console 用 UTC 半开区间 `[from,to)`，Prometheus `query_range` 的 start 和 end 都含端点。
4. 涉及兼容性的，只看协议协商结果，不看配置文件里写的 profile 名。

| 协议                                 | 谁产生             | 谁消费                                                  | 回答什么问题                                                                        |
| :----------------------------------- | :----------------- | :------------------------------------------------------ | :---------------------------------------------------------------------------------- |
| Console API                          | Console 后端       | 浏览器里的前端                                          | 页面上每个读写动作走哪个接口、返回什么结构、什么错误                                |
| Reporting V1                         | 运行时 Reporter    | Collector                                               | 一次上报的通用信封长什么样，来源与周期怎么标识                                      |
| Metrics V2                           | 运行时 Reporter    | Collector 收下并持久化，Console 查询                    | 这个时间窗里的 QPS、RT、请求拦截率、CPU、内存各是多少，按什么口径                   |
| Rule Load Observation V1             | 运行时             | Collector 收下，Console 汇总                            | 某个进程实际加载了哪一版快照，摘要对不对，成员清单完整吗                            |
| Rule Publication Receipt V1          | Runtime（运行时）  | Collector 持久化并通过 durable outbox 交给 Console 投影 | 某次精确发布的运行时处理结果；以 binding_id、publication_id、target_version_id 关联 |
| Managed Rule Publication Envelope V1 | Console 加的封装层 | 只有显式启用该格式的 profile                            | 这次加载对应哪一次发布                                                              |
| Incident Event V1                    | 运行时独立发送     | Collector 持久化，Console 查询                          | 发生了什么样的资源压力或响应时间越界                                                |
| 协议协商                             | 连接建立时的双方   | Console 记录协商结果                                    | 当前真的支持哪个协议版本，兼容状态从协商结果来                                      |

> **提示** Managed Rule Publication Envelope V1 沿 Console → 配置中心 → Runtime 传播发布身份；Rule Publication Receipt V1 反向沿 Runtime → Collector → Console 返回处理结果。加载观察则独立说明运行时接受了什么快照。回执不是 Console 发给 Runtime 的指令；相同内容也可能对应不同的发布，不能只凭摘要推断是哪一次。

## 两种 envelope：不同方向，不同用途

envelope 只是封装的通称，不能省略协议名来判断用途。Agent Reporting Envelope V1 与 Managed Rule Publication Envelope V1 是两个独立合同，既不互相替代，也不嵌套成同一条发布协议。

| 合同与协议标识                                                                           | 链路                               | 用途与边界                                                                                                |
| :--------------------------------------------------------------------------------------- | :--------------------------------- | :-------------------------------------------------------------------------------------------------------- |
| Agent Reporting Envelope V1 / atlas-richie.reporting/v1                                  | Runtime Reporter → Collector       | 上报基础封装；不用于向配置中心发布规则，也不代表其他独立版本化上报协议都使用此格式。                      |
| Managed Rule Publication Envelope V1 / atlas-richie.sentinel.managed-rule-publication/v1 | Console → Nacos / Consul → Runtime | 封装原生规则与发布身份；后端 provider 适配器传输它，metadata-aware Runtime 读取它，不是 Reporter 事件包。 |

> **提示** 浏览器 → Console API 是页面操作入口，不是第三条浏览器直连配置中心的规则链路。凭证解析、发布并发控制、outbox、独立回读和审计留在后端。

## 托管规则读路径：三字段一致性与 fail-closed

共享生产合同 atlas-richie-contracts 定义并校验 managed envelope 的字段、协议版本、载荷结构及 payload_sha256。读取方使用该合同解包后，还必须将以下三项与目标 binding 的权威元数据逐一比对，再交给该 binding 的规则 profile 做语义解码。

任一项不匹配，Console 快照读路径即抛出 RuleSetSnapshotInvalid 并拒绝整份候选，不会继续按错误 profile 解码或把它当作成功读取的空规则集。即使 JSON 与摘要都合法，投到错误 binding 的 envelope 也不能通过。

| envelope 字段 | 必须匹配的 binding 事实               | 不匹配的结果           |
| :------------ | :------------------------------------ | :--------------------- |
| binding_id    | binding.id：目标绑定标识              | RuleSetSnapshotInvalid |
| rule_kind     | binding.kind：目标规则类型            | RuleSetSnapshotInvalid |
| profile_id    | binding.profile：目标规则解码 profile | RuleSetSnapshotInvalid |

> **提示** 这是一条生产合同消费边界，不是页面校验或 Console 按规则内容临时猜测 profile。封装中的身份字段和摘要也不能替代认证、授权或发布回执。
