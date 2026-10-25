# Sentinel 协议与 Console API 索引

本目录保留早期已冻结的协议、Console HTTP API 机器合同，以及后续设计决策。
`protocols/` 是现有独立运行时协议的另一个历史目录；通过下表找到对应权威文件，
新增索引不移动协议、不改变 wire，也不把提案视为已冻结实现。

| 边界 | 规范与决策 | 生产合同或验证入口 |
| --- | --- | --- |
| 浏览器 → Console | [Console API 契约](../contract/Console-API-契约.md)、[当前 OpenAPI](console-api.openapi.json) | React feature DTO 生成；`npm run contract:check` 与 Console HTTP 运行时测试 |
| Agent Reporting Envelope V1 | [Envelope](reporting-protocol-01-envelope-v1.md)、[Transport](reporting-protocol-02-transport-v1.md)、[冻结记录](reporting-protocol-03-freeze-record-v1.md) | `foundation/contracts/.../reporting/v1/` |
| Metrics Reporting V2 | [已接受的冻结 ADR](ADR-SEN-020-metrics-v2-freeze.md)；[早期提案](reporting-protocol-04-metrics-v2-proposal.md)仅供设计溯源 | [生产错误码](../../../../foundation/contracts/src/atlas_richie/contracts/reporting/v2/error_codes.py)、[跨语言夹具验证](../../../../foundation/contracts/tools/test_metrics_v2_conformance.sh) |
| Cluster Token V1 | [英文协议](cluster-token-protocol-v1.md)、[中文协议](集群令牌协议-v1.md) | `foundation/contracts/.../cluster/v1/` |
| 规则目录与运行时 profile | [规则目录读取](RULE_CATALOG_READ_V1.md)、[Flow profile](SENTINEL-FLOW-RUNTIME-PROFILE-V1.md) | Console 只读配置中心；Runtime profile 决定支持的规则语义 |
| 规则发布与运行时事实 | [独立运行时协议索引](../protocols/README.md) | Managed Publication、加载观察、发布回执和故障事件分别版本化 |

Agent Reporting Envelope 与 Managed Rule Publication Envelope 是两种不同的封装。
前者属于上报链路；后者沿 Console → Nacos/Consul → Runtime 传递规则和发布身份。
浏览器只调用 Console API，不直接连接配置中心。Managed envelope 的生产读路径要求
`binding_id`、`rule_kind`、`profile_id` 均与目标 binding 一致，否则拒绝快照。

## OpenAPI 归档与兼容门禁

现有归档版本：0.8.0、0.10.0、0.11.0、0.12.0、0.13.0、0.14.0、0.17.0、0.18.0。
0.19.0 的当前文件是 `console-api.openapi.json`，由源码生成。

**0.9.0、0.15.0、0.16.0 的原始快照缺失。** 截至 2026-10-25，当前仓库所有可达 Git
历史没有对应版本归档；`console-api.openapi.json` 的历史提交只能找到 0.4.0-draft 和
0.19.0。完整恢复需要当时的 Git 对象、CI artifact 或其他有可核验来源的原始文件。
不能复制新版、删除路径或重写版本号后冒充历史快照。该缺口仍未关闭。

`test_historical_contract_compatibility.py` 检查所有实际存在的归档。旧字段、响应状态、
请求变体、参数、枚举项、语义规则和约束必须保留；缺失时立即失败。已批准的例外由
operation ID + 精确 schema 路径 + 精确值白名单限定：§23 的新口令边界和账号生命周期、
已存在的审计动作扩展，以及 §22 的 `source_in_use`。不能把所有新增内容一律投影掉。
