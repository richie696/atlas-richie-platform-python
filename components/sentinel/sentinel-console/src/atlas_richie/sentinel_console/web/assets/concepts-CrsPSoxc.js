const n=`---
title: 规则、绑定、实例和数据源
summary: 分清配置内容、运行事实与监控数据。
prerequisite: 已读过界面地图，知道每个页面大概管什么。
outcome: 理解配置中心、Console 数据库、Collector 与 Prometheus 各自的职责，知道一句话能证明什么、不能证明什么。
---

## Sentinel 在本系统中的位置

本系统把规则管理、业务流控执行和运行观测分成不同的职责：Console 负责管理规则与展示事实，Nacos / Consul 保存规则，接入服务中的 Sentinel Runtime 执行限流；Collector 和 Prometheus 分别承接应用上报与主机监控。真正放行或拦截业务请求的是 Runtime，不是 Dashboard。

\`\`\`mermaid
flowchart TB
  operator[运维人员] --> web[React 控制台] --> api[Console API]
  api --> consoleDb[(Console 数据库)]
  api --> publisher[规则校验与发布]
  publisher --> config[(Nacos / Consul)]
  request[业务请求] --> runtime[Sentinel Runtime]
  config --> runtime
  runtime --> decision{放行 / 拒绝} --> response[业务响应]
  runtime --> collector[Collector] --> telemetryDb[(观测存储)]
  collector --> api
  hostAgent[主机采集器] --> prometheus[(Prometheus)] --> api

  classDef control fill:#203b49,stroke:#5e9fc4,color:#e8f1f7,stroke-width:1.5px
  classDef storage fill:#173b43,stroke:#4db7a0,color:#e8f1f7,stroke-width:1.5px
  classDef execution fill:#1c493a,stroke:#54c99b,color:#e8f1f7,stroke-width:1.5px
  classDef outcome fill:#4a3f2b,stroke:#d1a958,color:#f4e7c4,stroke-width:1.5px
  class operator,web,api,publisher control
  class consoleDb,config,collector,telemetryDb,hostAgent,prometheus storage
  class request,runtime,response execution
  class decision outcome
\`\`\`

规则发布信封沿 Console → 配置中心 → Runtime 传递规则及发布身份；上报协议则沿 Runtime → Collector → Console 返回指标和运行事实。两者是不同的协议和方向。浏览器只调用 Console API，不直接连接 Nacos、Consul、Collector 或 Prometheus。

## 四个角色各存什么

初学者最容易把下面四者混在一起。它们分别回答四个不同的问题，任何一个都不能替另一个回答。

| 组件           | 存什么                                                 | 谁是权威 | 回答的问题                 |
| :------------- | :----------------------------------------------------- | :------- | :------------------------- |
| Nacos / Consul | 正在生效的规则内容                                     | 权威     | 配置中心里现在是什么       |
| Console 数据库 | 账号、角色、来源登记、绑定、草稿、版本、发布记录、审计 | 权威     | 谁做了什么、留下了哪个版本 |
| Collector      | 收到的上报：加载观察、指标快照、发布回执               | 权威     | 运行时上报了什么           |
| Prometheus     | 主机资源时序样本                                       | 权威     | 这台机器过去一小时的使用率 |

> **提示** 配置中心自己的数据库不能替代 Console 数据库。配置中心存规则内容，Console 数据库存账号、版本和审计，两者互不备份。

## 一次规则改动的完整链路

规则从你写下到业务进程生效，中间有六段路。每一段都可能被单独检查，也都可能单独失败。

1. 起草：编辑草稿。草稿存在 Console 数据库里，不会碰配置中心。
2. 校验：服务端按绑定 profile 检查这份草稿能不能发布。这是一次只读评估，不写任何东西。
3. 固化：把草稿冻结成一个不可变版本。版本一旦创建就不能改。
4. 发布：把选中的版本整体写入配置中心。这是整体替换，不是增量补丁。
5. 回读：发布后独立地从配置中心读回来，比对内容是否一致。
6. 加载：业务进程下一次轮询拿到新内容并上报加载观察。控制台据此显示这个实例到底加载了哪一版。

> **提示** 回读一致不等于实例已加载，实例已加载不等于请求真的被拦截。这三件事必须分别验证。

## 三种验证不能互相替代

下面这张表是本文最重要的一张。它解释了为什么「规则页显示有规则」经常和「线上真的生效了」对不上。

| 验证方式       | 证明了什么                     | 不能证明什么                 |
| :------------- | :----------------------------- | :--------------------------- |
| 读到规则       | 配置中心里现在有这份内容       | 任何进程已经加载它           |
| 实例加载观察   | 某个认证过的进程接受了这份快照 | 它加载的是你刚刚发布的那一版 |
| 业务请求被拒绝 | 限流器真的在运行时起作用       | 其它资源或其它实例也在生效   |
| 发布回执       | 一次托管发布到达了运行时       | 当前状态仍然是这一版         |

## 环境和实例不是自动扫出来的

环境来自登记与绑定的作用域。控制台不会扫描你的全部服务器然后列出「有哪些环境」——这样既慢又危险。你登记了什么，它才有什么。

一个应用可以有多个实例：多个 worker 可以分别登记为 Dashboard 实例。进程级、宿主机级、容器级是三种不同的采集范围，任何一个都不能借用另一个的数据来填补空白。

## 一条请求在系统里的完整路径

下面这条路径把请求从客户端到控制台曲线串了一遍。每一段都可能被单独验证，也都可能单独断掉，断掉的位置决定了界面上看到的是空、未知，还是一个看起来正常其实偏低的数字。

1. 客户端发起请求。请求先到达业务进程；进程里没有对应的 Sentinel 埋点时，这次请求既不会进入限流器，也不会产生任何指标。
2. 业务代码产生一个 Sentinel entry。这个 entry 记录了资源名、耗时、是否被拦截，以及是否通过埋点计入了业务事务计数。后面的所有统计都以 entry 为起点。
3. entry 进入规则匹配。运行时按绑定选定的 profile 认识规则字段，只对 profile 支持的规则类型和字段生效——\`sentinel-python-v1\` 支持全部五类规则，\`sentinel-java-v1\`、\`sentinel-go-v1\`、\`sentinel-rust-v1\` 当前都只支持 Flow。
4. 匹配结果是放行或拒绝。放行的 entry 继续走完业务逻辑；被拒绝的 entry 立即返回。阻塞原因只会是 FLOW、CIRCUIT_OPEN、SYSTEM、PARAM_FLOW、AUTHORITY 之一。
5. 请求结束后，Reporter 把这一段的完成数、拦截数、业务事务数和延迟直方图上报给 Collector。Reporter 跑在业务进程里，证书私钥不经过控制台。
6. Collector 接收上报并持久化，同时保存加载观察与发布回执。上报失败不影响业务请求，但会在控制台的采样覆盖上留下缺口。
7. 控制台查询时向 Collector 取指标快照，按观测窗口聚合成曲线。主机资源指标走的是 Prometheus 查询后端，与 Reporter 上报的数据是两条独立链路。
8. 被拒绝的请求，业务侧才看得到失败。控制台上的曲线是同一批 entry 的另一种视角，两者应当对得上；对不上时先查上报链路，再谈阈值。

> **提示** 这条路径上有多个彼此独立的判断点：请求是否进入限流器、规则是否匹配、是否被拒绝、Reporter 是否上报成功、Collector 是否持久化、查询是否覆盖了这段窗口。其中只有「被拒绝」能被业务请求直接证明，因为它会变成一个真实的失败响应。其余每一段都要靠各自的观测点来证明：加载观察证明运行时接受了快照，采样覆盖证明上报到了，曲线证明查询到了。任何一段断了，控制台都会显示为空或未知，而不是显示成零。
`;export{n as default};
