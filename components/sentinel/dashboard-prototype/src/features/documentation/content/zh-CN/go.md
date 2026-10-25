---
title: Go：接入官方 Sentinel SDK
summary: 使用 Go 原生字段，不要直接复制 Java 的 JSON。
prerequisite: Go 1.23 或更高版本；仓库里有一个可运行的 Go demo。
outcome: 规则加载成功、请求产生拒绝，并接入观测上报。
---

## 依赖与运行

demo 使用官方 sentinel-golang 与 Nacos Go SDK，同样是互操作演示。启动方式是先跑测试再直接运行。

```bash

go test ./...
go run .
```

> **提示** demo 默认监听 127.0.0.1:18082，可用 DEMO_PORT 与 DEMO_BIND_HOST 覆盖。启动成功打印 go-demo listening on host; rule source key=…。

## 配置项：地址拆成了两个变量

Go 侧把地址拆成了主机和端口两个变量，和 Java 的写法不一样。这是跨语言接入最常见的第一个坑。

| 变量                 | 默认值                                   | 说明                                                   |
| :------------------- | :--------------------------------------- | :----------------------------------------------------- |
| NACOS_SERVER_ADDR    | 127.0.0.1                                | 只填主机名，不要带端口                                 |
| NACOS_SERVER_PORT    | 8848                                     | 端口单独一个变量                                       |
| NACOS_NAMESPACE      | public                                   | namespace ID                                           |
| NACOS_GROUP          | DEFAULT_GROUP                            | 分组                                                   |
| NACOS_DATA_ID        | sentinel-e2e-20261017-go-flow-rules.json | Data ID                                                |
| NACOS_USERNAME       | nacos                                    | 账号                                                   |
| NACOS_PASSWORD       | 无默认值                                 | 开启鉴权时必填                                         |
| NACOS_AUTH_ENABLED   | true                                     | 设为 false 可跳过账号密码                              |
| RULE_SOURCE_PROVIDER | nacos                                    | nacos 或 consul；留空也按 nacos 处理，其它值启动即报错 |
| RULE_SOURCE_PROFILE  | native-array-v1                          | 或 managed-envelope-v1                                 |
| RULE_BINDING_ID      | 无默认值                                 | 托管信封与加载观察必填                                 |
| RULE_PROFILE_ID      | sentinel-go-v1                           | 必须与控制台绑定一致                                   |

> **提示** 三种语言的 RULE_SOURCE_PROVIDER 留空时都回落 nacos；填了无法识别的值则启动即报错。

## 写一条规则

Go SDK 的规则字段和 Java 不一样。资源名同样是 GET /api/hello。

```json
[
  {
    "resource": "GET /api/hello",
    "threshold": 3,
    "tokenCalculateStrategy": 0,
    "controlBehavior": 0,
    "relationStrategy": 0,
    "statIntervalInMs": 1000
  }
]
```

| 字段                   | 必须取的值     | 含义                                                |
| :--------------------- | :------------- | :-------------------------------------------------- |
| resource               | 与埋点逐字一致 | 被保护的资源                                        |
| threshold              | 正数           | 阈值                                                |
| statIntervalInMs       | 1000           | 统计窗口，固定一秒。这是当前 profile 唯一支持的窗口 |
| tokenCalculateStrategy | 0              | 计算策略。0 表示直接                                |
| relationStrategy       | 0              | 关联策略。0 表示按当前资源                          |
| controlBehavior        | 0              | 控制行为。0 表示立即拒绝                            |

> **提示** Go 的阈值字段叫 threshold 而不是 count。直接把 Java 的规则 JSON 抄过去，字段名对不上，整份快照会被拒。

## 连接 Reporter

Go 使用 PEM 格式的证书与私钥，不是 PKCS#12。这是 Java 与 Go、Rust 之间最容易踩的第二个坑。

| 变量                  | 说明                    |
| :-------------------- | :---------------------- |
| METRICS_COLLECTOR_URL | Collector 的 HTTPS 地址 |
| METRICS_REPORTER_ID   | 已登记的 Reporter 标识  |
| METRICS_CLIENT_CERT   | PEM 客户端证书          |
| METRICS_CLIENT_KEY    | PEM 客户端私钥          |
| METRICS_COLLECTOR_CA  | Collector 的 CA 包      |

> **提示** Java 用 METRICS_CLIENT_PKCS12 和 METRICS_CLIENT_PKCS12_PASSWORD；Go 和 Rust 用 METRICS_CLIENT_CERT 和 METRICS_CLIENT_KEY。两套变量名不通用。

## 三步验证

Go demo 的 /rules 在尚未加载到有效快照时返回 503 并给出 rules_loaded=false，这本身就是一个有用的信号。

1. 请求 /rules，确认 rules_loaded=true 且 rule_count 大于零。
2. 请求 /api/hello 验证 429 blocked by Sentinel。
3. 请求 /api/delay?ms=250 产生一个延迟样本，用来验证 RT 指标。
4. 回到控制台确认实例加载状态与总览指标。

## 常见失败点

Go demo 的失败点和 Java 大体相似，但触发原因集中在两个地方：地址的写法不同，规则字段名不同。下面这张表按「现象 → 原因 → 怎么处理」列出常见几类问题。

| 现象                                            | 原因                                                                                                                       | 怎么处理                                                                                               |
| :---------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------- |
| 连不上 Nacos，客户端反复重试                    | NACOS_SERVER_ADDR 误填成 127.0.0.1:8848；Go 侧这个变量只认主机名，端口是独立变量                                           | 拆成两个变量：NACOS_SERVER_ADDR=127.0.0.1 与 NACOS_SERVER_PORT=8848                                    |
| 整份规则快照被拒，控制台侧仍显示上一份内容      | Go 的阈值字段叫 threshold 而不是 count；直接复制 Java 的规则 JSON 会因未知字段被整体拒绝                                   | 改用 Go 字段名：threshold、statIntervalInMs、tokenCalculateStrategy、relationStrategy、controlBehavior |
| /rules 返回 503 和 rules_loaded=false           | 还没有读到有效快照，这是启动阶段的正常状态，不是故障                                                                       | 等一个轮询周期再请求；持续 503 再回头查地址、凭证与 Data ID                                            |
| 加载状态显示未知                                | RULE_PROFILE_ID 必须与控制台绑定一致，Go 是 sentinel-go-v1；托管信封还需要 RULE_BINDING_ID                                 | 对齐 profile 与绑定标识；用 managed-envelope-v1 时确认信封内写的 profile 就是同一个值                  |
| 指标始终为空                                    | Go 用 PEM 三件套：METRICS_CLIENT_CERT、METRICS_CLIENT_KEY、METRICS_COLLECTOR_CA；写成 Java 的 METRICS_CLIENT_PKCS12 不生效 | 换成 PEM 三件套，并确认 METRICS_COLLECTOR_URL 已设置、地址是 https                                     |
| 启动即退出，报 unsupported RULE_SOURCE_PROVIDER | 只接受精确的 nacos 或 consul，不做大小写和别名归一                                                                         | 改成精确值；改用 Consul 时同时给出 CONSUL_URL 与 CONSUL_KEY                                            |

> **提示** Go demo 的 /rules 在没有有效快照时返回 503，这是判断「读到没有」的最直接信号，不要把它当成服务异常。

## 官方延伸阅读

- [Sentinel Go](https://sentinelguard.io/zh-cn/docs/golang/flow-control.html)
