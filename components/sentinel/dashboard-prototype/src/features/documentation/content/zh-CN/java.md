---
title: Java：从官方 SDK 到控制台可见
summary: 两步接入：规则执行和运行观测。
prerequisite: JDK 17 或更高版本、Maven 3.9 或更高版本；仓库里有一个可运行的 Java demo。
outcome: 规则真的被拦截，并且控制台能看到指标与加载观察。
---

## 依赖与运行

demo 使用官方 Sentinel Java Core 与 Nacos 客户端。它是互操作演示，不是生产级运行时适配器。

构建与启动命令如下。官方 README 给的是 classes 加 classpath 的方式，不产出可直接运行的 jar。

```bash

mvn -q package dependency:build-classpath -Dmdep.outputFile=target/classpath.txt
java -cp "target/classes:$(cat target/classpath.txt)" io.atlasrichie.sentinel.demo.JavaSentinelDemo
```

> **提示** demo 默认监听 127.0.0.1:18081，可用 DEMO_PORT 与 DEMO_BIND_HOST 覆盖。启动成功会打印 java-demo listening on host:port; rule source=…。

## 配置全部走环境变量

这个 demo 没有配置文件，application.properties 或 yml 都不存在。所有配置通过环境变量传入。下面是与规则来源相关的部分。

| 变量                 | 默认值                                     | 说明                                                  |
| :------------------- | :----------------------------------------- | :---------------------------------------------------- |
| NACOS_SERVER_ADDR    | 127.0.0.1:8848                             | 注意是主机和端口合一                                  |
| NACOS_NAMESPACE      | public                                     | namespace ID                                          |
| NACOS_GROUP          | DEFAULT_GROUP                              | 分组                                                  |
| NACOS_DATA_ID        | sentinel-e2e-20261017-java-flow-rules.json | Data ID                                               |
| NACOS_USERNAME       | nacos                                      | 账号                                                  |
| NACOS_PASSWORD       | 无默认值                                   | 开启鉴权时必填，只能通过 secret manager 或 shell 注入 |
| NACOS_AUTH_ENABLED   | true                                       | 设为 false 可跳过账号密码                             |
| RULE_SOURCE_PROVIDER | nacos                                      | nacos 或 consul；留空也按 nacos 处理                  |
| RULE_SOURCE_PROFILE  | native-array-v1                            | 或 managed-envelope-v1，其它值启动即报错              |
| RULE_BINDING_ID      | 无默认值                                   | 托管信封与加载观察必填                                |
| RULE_PROFILE_ID      | sentinel-java-v1                           | 必须与控制台绑定上的 profile 一致                     |

> **提示** 改用 Consul 时配置项换成 CONSUL_URL、CONSUL_KEY、CONSUL_DATACENTER、CONSUL_TOKEN。URL 里不能带令牌或查询参数；令牌只放在 X-Consul-Token 请求头。

## 写一条规则

配置中心里就是同类型的 JSON 数组。Java demo 里的资源名是 GET /api/hello，规则的 resource 必须与它逐字一致才会命中。

```json
[
  {
    "resource": "GET /api/hello",
    "grade": 1,
    "count": 3,
    "strategy": 0,
    "controlBehavior": 0,
    "limitApp": "default"
  }
]
```

| 字段            | 必须取的值     | 含义                                                  |
| :-------------- | :------------- | :---------------------------------------------------- |
| resource        | 与埋点逐字一致 | 被保护的资源                                          |
| grade           | 1              | 阈值类型。1 表示 QPS；0 表示并发，当前 profile 不支持 |
| count           | 正数           | 阈值。QPS 时是时间窗内请求数                          |
| strategy        | 0              | 匹配策略。0 表示按当前资源直接匹配                    |
| controlBehavior | 0              | 控制行为。0 表示立即拒绝                              |
| limitApp        | default        | 调用来源。default 表示不区分来源                      |

> **提示** 这些字段不是「建议值」而是硬约束：Java 适配器在校验阶段就会拒绝整个快照。多写一个 clusterMode、warmUpPeriodSec 或 maxQueueingTimeMs，整份规则都会被拒，而不是被忽略。

## 连接 Reporter

只有设置 METRICS_COLLECTOR_URL 才启用上报。Java 使用 PKCS#12 格式的客户端身份，这是它和 Go、Rust 最大的差别。

1. 先在 Console 侧登记证书指纹：用 sentinel-console metrics-reporter enroll，并带上 principal、证书 SHA-256 指纹、reporter-id、environment-id、app-id、instance-id、process-id。
2. 私钥永远不要交给 Console 或 Collector。
3. 用 bearer token 或自定义身份头替代 mTLS 是不被接受的。
4. 启用加载观察还需要 RULE_BINDING_ID 与 RULE_PROFILE_ID=sentinel-java-v1。

| 变量                           | 说明                                                |
| :----------------------------- | :-------------------------------------------------- |
| METRICS_COLLECTOR_URL          | Collector 的 HTTPS 地址，必须是 https，否则启动报错 |
| METRICS_REPORTER_ID            | 已在 Console 登记过的 Reporter 标识                 |
| METRICS_CLIENT_PKCS12          | PKCS#12 客户端身份文件路径                          |
| METRICS_CLIENT_PKCS12_PASSWORD | PKCS#12 密码，由 secret manager 供给                |
| METRICS_COLLECTOR_CA           | 校验 Collector 服务端的 CA 包                       |

> **提示** demo 的上报队列有界且在内存里，进程崩溃可能丢失尚未送达的回执。这不是生产级 SDK 的可靠性保证。

## 三步验证

验证分三层：读到规则、实例加载、请求被拒。每一层都有明确的观测点。

1. 读规则：请求 /rules，确认输出里有 rules_loaded=true 和 rule_count。这一步只证明内容可读。
2. 看加载：等一个轮询周期后，规则页的实例使用情况应显示该实例已加载。这一步证明进程接受了快照。
3. 看拦截：连续请求 /api/hello，前几次返回 200 hello from Java Sentinel，超过阈值后返回 429 blocked by Sentinel。
4. 看指标：总览与实时监控出现 HTTP QPS 与请求拦截率。

> **提示** 规则每秒轮询一次。改完配置中心的内容，最多等一秒再查；立刻去读很可能读到旧值。

## 常见失败点

下面这张表按「现象 → 原因 → 怎么处理」列出 Java demo 最常遇到的几类问题。demo 是互操作演示，它的失败模式比生产适配器更集中：配置项写错会在启动阶段直接退出，而不是退化成降级行为。

| 现象                                                    | 原因                                                                                                                         | 怎么处理                                                                                                             |
| :------------------------------------------------------ | :--------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------- |
| 启动即退出，报 NACOS_PASSWORD is required               | NACOS_AUTH_ENABLED 默认是 true，鉴权开启时 NACOS_PASSWORD 没有默认值                                                         | 由 secret manager 或 shell 注入 NACOS_PASSWORD；本地无鉴权环境显式设 NACOS_AUTH_ENABLED=false                        |
| 启动即退出，报 unsupported RULE_SOURCE_PROVIDER         | RULE_SOURCE_PROVIDER 只接受 nacos 或 consul，不做大小写和别名归一                                                            | 写成精确的小写 nacos 或 consul；改用 Consul 时补上 CONSUL_URL 与 CONSUL_KEY                                          |
| 读不到规则：启动就退出，或 /rules 里 rules_loaded=false | NACOS_SERVER_ADDR 必须 host:port 合一，填成 127.0.0.1 连不上；NACOS_NAMESPACE、NACOS_GROUP、NACOS_DATA_ID 任一不匹配也读到空 | 地址写成带端口的形式，并逐一核对 namespace、group 与 Data ID                                                         |
| 规则已加载但请求始终放行，请求拦截率恒为零              | 规则的 resource 与埋点不一致；Java demo 的埋点固定是 GET /api/hello                                                          | resource 改成与埋点逐字一致的字符串，不用路径前缀，也不带查询串                                                      |
| 加载状态显示未知或与本地不一致                          | RULE_PROFILE_ID 必须与控制台绑定上的 profile 一致，Java 是 sentinel-java-v1；托管信封还要求 RULE_BINDING_ID 对得上           | 对齐绑定上的 profile、RULE_PROFILE_ID 与 RULE_BINDING_ID；用 managed-envelope-v1 时确认信封内写的 profile 是同一个值 |
| 控制台看不到任何指标                                    | 没有设置 METRICS_COLLECTOR_URL 时上报根本不启用；地址不是 https 也会被拒绝                                                   | 设置 METRICS_COLLECTOR_URL 并确认是 https；METRICS_REPORTER_ID 必须是已在 Console 登记过的标识                       |
| 上报时报证书相关错误                                    | Java 用 PKCS#12：METRICS_CLIENT_PKCS12 指向的文件不存在，或 METRICS_CLIENT_PKCS12_PASSWORD 不对                              | 确认 PKCS#12 路径与密码；Go 和 Rust 的 PEM 变量在 Java 侧无效，两套变量名不通用                                      |

> **提示** 这张表只覆盖 demo 自身的配置问题。规则本身被拒、指标口径对不上之类的判断，分别看「写一条规则」和指标口径那两节。

## 官方延伸阅读

- [Sentinel Java](https://sentinelguard.io/en-us/docs/introduction.html)
