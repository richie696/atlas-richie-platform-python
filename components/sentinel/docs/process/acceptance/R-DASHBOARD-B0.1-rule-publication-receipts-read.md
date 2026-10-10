# B0.1 — 发布回执分页读取验收

## 范围

实现 `GET /api/v1/rulesets/{bindingId}/publications/{publicationId}/receipts`，完全对齐 `console-api.openapi.json` 的 `readRulePublicationReceipts` operation。返回精确 publication 的分页实例回执，以及跨全量回执总体的状态计数和 inventory completeness 分母。

## 定向风险矩阵

| ID | 风险 | 断言 |
|---|---|---|
| REC-01 | 写回成功被误当成实例已加载 | `applied` 必须匹配 publication 的 target version/checksum、当前 process epoch 和 loaded process epoch，并具有 applied/report 时间 |
| REC-02 | 分页查询越权或错绑 | session 校验后才调用 authority；binding/publication/page/pageSize 必须精确回显 |
| REC-03 | 完整性分母被伪造 | expected/inventorySource 同时已知或同时未知；已知 expected 必须等于 total；状态总数必须精确等于 total |
| REC-04 | 页数据/聚合数据矛盾 | 当前页不越过 total，instance ID 页内唯一，页内各状态数不得超过全量状态计数 |
| REC-05 | 未知 incarnation 被当作应用成功 | processEpoch 缺失只允许 unknown，且加载身份与观察时间字段为空 |
| REC-06 | authority/输入错误泄露内部事实 | 覆盖非法或重复 query、未配置 reader、publication 不存在、限流/不可用；稳定 HTTP 错误且不泄露异常正文 |

## 设计边界

- `RulePublicationReceiptReader` 是 Console 用例拥有的只读 Port，不依赖具体 DB、Reporter、Collector 或配置中心。
- 用例先通过现有 publication detail reader 读取权威目标版本/校验和，再读取对应分页；结果必须绑定同一个 publication。
- 不把当前页计数当总体计数；分页 DTO 保留服务端全量 counters 和 expected population 事实。
- 本切片不增加持久化 schema、生产 adapter、Reporter 写入协议或真实集群数据。

## 证据边界

定向测试证明 domain/use-case/ASGI 合同；OpenAPI 对位证明 wire shape。以上均不证明生产 inventory/receipt authority、数据库持久化、Collector/Reporter ingest 或真实 instance load。完整跨层验收留在 milestone E2E。

## 实际结果（2026-10-09）

- `pytest test_rule_publications_api.py test_rule_versions_api.py test_rule_drafts_api.py test_rule_set_snapshot_api.py test_rule_bindings_api.py test_instance_catalog_api.py test_incident_timeline_api.py test_fleet_overview_api.py -q`：**80 passed**。
- 前端 `npm run contract:check`：OpenAPI **42 paths** 校验通过，覆盖 `readRulePublicationReceipts` 已声明的分页路由。
- Python `compileall`、本次变更涉及 Python 文件 88 列检查、`git diff --check` 通过。
- 本轮没有运行完整 Console 套件、浏览器 E2E、真实数据库、Collector/Reporter 或配置中心。
