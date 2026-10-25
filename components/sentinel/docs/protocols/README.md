# 独立运行时协议索引

这些协议拥有独立版本和用途，不能当作同一种 envelope 解码。

| 协议 | 方向与职责 | 规范 |
| --- | --- | --- |
| Managed Rule Publication Envelope V1 | Console → 配置中心 → Runtime；携带原生规则数组、精确发布 tuple、序号和校验和 | [规则发布封装](MANAGED_RULE_PUBLICATION_ENVELOPE_V1.md) |
| Rule Publication Receipt V1 | Runtime → Collector → Console outbox 投影；精确确认某次发布已应用 | [发布回执](RULE_PUBLICATION_RECEIPT_V1.md) |
| Rule Load Observation V1 | Runtime → Collector；报告进程当前加载的规则快照，兼容原生与托管规则 | [加载观察](RULE_LOAD_OBSERVATION_V1.md) |
| Incident Event Protocol V1 | Runtime → Collector 持久化 → Console；独立故障事件链路 | [故障事件](INCIDENT_EVENT_PROTOCOL.md) |

生产合同位于 `foundation/contracts/src/atlas_richie/contracts/`；字段、校验、身份和
持久化 ACK 的精确定义以相应版本规范及生产合同为准。历史设计稿、已实现、已冻结和
验收通过是不同状态；各协议正文保留自己的批准与证据边界。

Managed envelope 在读取时必须与目标 binding 的 `binding_id`、`rule_kind`、`profile_id`
同时匹配，任一不一致即 `RuleSetSnapshotInvalid`，保留既有 last-known-good 行为。
此校验属于 `atlas-richie-contracts` 生产合同，不是浏览器的临时判断。

Agent Reporting Envelope V1 与 Metrics Reporting V2 在
[另一协议索引](../protocol/README.md)中。前端通过 Console HTTP API 管理来源、
规则与监控，不直接访问 Nacos、Consul、Collector 或 Prometheus。
