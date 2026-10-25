const n=`---
title: Rust 与其他语言：适配范围
summary: 分清受控互通演示与正式官方 SDK。
prerequisite: 已经理解原生规则与 Reporter 身份的概念。
outcome: 清楚接入一门新语言时，哪些是现成的、哪些要自己实现并验证。
---

## Rust demo 是什么，不是什么

仓库里的 Rust demo 是一个受控的运行时适配器验证：它用官方 sentinel-core 引擎、Nacos Rust SDK 和 Consul 文档化的 KV HTTP API，验证规则、指标和协议三方的互通。

它不是 Alibaba 官方发布的 Sentinel Rust 发行版，也不是生产就绪的包。README 明确写着它不主张「支持全部 Sentinel 规则类型与遥测契约」。

| 它是什么                              | 它不是什么                 |
| :------------------------------------ | :------------------------- |
| 用官方 sentinel-core 引擎跑 Flow 规则 | 官方发布的 Rust SDK        |
| 发送 Metrics V2 快照并等待持久回执    | 生产级运行时适配器         |
| 实现加载观察与发布回执协议            | 支持全部规则类型           |
| 受控环境下的可复现验证                | 任何环境都能直接部署的服务 |

## 配置与端点

Rust demo 的变量名和前两个不同：监听地址用 HTTP_ADDR，且 Nacos 地址是必填、没有默认值。

| 变量                | 默认值           | 说明                                        |
| :------------------ | :--------------- | :------------------------------------------ |
| HTTP_ADDR           | 127.0.0.1:18094  | 监听地址                                    |
| NACOS_SERVER_ADDR   | 无默认值，必填   | 和 Java 的 host:port 写法不同，这里是纯地址 |
| NACOS_DATA_ID       | 无默认值，必填   | Data ID                                     |
| NACOS_GROUP         | DEFAULT_GROUP    | 分组                                        |
| POLL_INTERVAL_MS    | 1000             | 轮询间隔，最小 100 毫秒                     |
| RULE_PROFILE_ID     | sentinel-rust-v1 | Rust 专用 profile                           |
| METRICS_CLIENT_CERT | 无默认值         | PEM 客户端证书                              |
| METRICS_CLIENT_KEY  | 无默认值         | PEM 客户端私钥                              |

> **提示** Rust demo 的 /rules 返回 JSON，其它两个 demo 返回纯文本键值行。写自动化脚本时不要假设三者格式一致。

## 明确不支持的能力

下面这些能力在当前 Rust 适配范围内没有被实现，而且遇到未知字段或未知语义时是整体拒绝候选，而不是忽略。

| 能力                | 当前状态                                     |
| :------------------ | :------------------------------------------- |
| 并发阈值            | 不支持                                       |
| 预热                | 不支持                                       |
| 排队等待            | 不支持                                       |
| 关联与调用链策略    | 不支持                                       |
| 集群流控            | 不支持                                       |
| 进程 CPU / 内存指标 | 标记为不可用，不用被禁用的 exporter 推断     |
| Prometheus exporter | 禁用：真实 Flow 路径会因标签基数不匹配而崩溃 |

> **提示** 未知或未建模的字段一律拒绝，而不是「忽略掉先跑起来」。这是有意的设计：忽略会让配置看起来生效了，实际保护完全没生效。

## 接入一门新语言要做什么

如果你的语言不在 Java、Go、Rust 之中，需要自己实现并验证下面这些环节。demo 的存在意义就是把这些环节的验收标准固定下来。

1. 实现规则执行器：明确资源命名、阈值计算与拒绝行为，并确认它覆盖的规则子集。
2. 实现配置监听：读到什么格式、非法快照怎么处理、是否保留上一份已应用的内容。
3. 实现资源与延迟计量边界：决定在哪个位置统计请求、哪种延迟算作 RT。
4. 先在没有流量的情况下验证读取与应用，确认内容能被正确解析和加载。
5. 再用固定响应和可控延迟的接口验证放行、拒绝和 RT 样本。
6. 最后验证独立 mTLS 身份、协议协商、持久回执，以及 Console 能不能读回这些事实。

## 跑通 Rust demo

Rust demo 的目录结构、变量名和端点路径都和前两个不同，照着 Java 或 Go 的命令跑会走不通。下面这份步骤按实际执行顺序排列。

1. 在 demo 目录执行 cargo run --locked。demo 读取 NACOS_SERVER_ADDR 和 NACOS_DATA_ID，这两个都没有默认值，缺失时进程直接启动失败。
2. 宿主没有 Rust 工具链时，用容器跑测试：docker run --rm -v "$PWD:/work" -w /work rust:1.89-slim cargo test --locked。这条命令不会连接或改动 Nacos、Consul、Collector 和任何用户服务。
3. 默认监听 127.0.0.1:18094。需要换地址时设置 HTTP_ADDR，它接受 host:port 形式，例如 HTTP_ADDR=127.0.0.1:18095。
4. 轮询周期由 POLL_INTERVAL_MS 控制，默认 1000 毫秒，最小 100 毫秒。填了小于 100 的值不会报错，而是回落到默认的 1000 毫秒。
5. 请求 /rules 确认已加载。它返回 JSON，不是 Java 和 Go 那种纯文本键值行；字段也比另外两个多，多出 profile_id、source_revision、membership_complete、member_fingerprints 和 last_failure，原生规则下 managed_publication 为 null。
6. last_failure 出现 validation_rejected 表示快照被校验拒绝，出现 source_unavailable 表示读来源失败。出现这两个值时，上一份可用快照仍然生效，不会被清空。
7. 延迟夹具是 /demo?delay_seconds=0..30，单位是秒并夹到 30；Java 和 Go 的 /api/delay?ms= 是毫秒并夹到 2000，路径名和单位都不通用。
8. 请求 /api/hello 与 /demo 进入的是同一个 GET /api/hello 资源，发布的 Flow 规则保护的是这两个入口。放行返回 200 JSON，拦截返回 429 JSON。

\`\`\`bash

cargo run --locked
docker run --rm -v "$PWD:/work" -w /work rust:1.89-slim cargo test --locked
\`\`\`

> **提示** Rust demo 先读到第一份有效快照才启动 HTTP 服务。初始快照读不到或被拒时进程直接退出，不会先监听端口再慢慢重试；之后轮询到非法快照则保留上一份可用快照，进程不会退出。
`;export{n as default};
