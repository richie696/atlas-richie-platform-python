# B0.1 — 规则版本读取接口验收

## 范围

实现规则绑定下不可变版本的完整列表和单条读取：

- `GET /api/v1/rulesets/{bindingId}/versions`
- `GET /api/v1/rulesets/{bindingId}/versions/{versionId}`

版本事实由宿主权威 Reader 提供。Console 只验证会话、路径身份、版本/规则值对象边界和绑定归属并序列化；本切片不实现持久化适配器、草稿冻结、发布或 Nacos/Consul 读写。

## 定向验收矩阵

| ID | 风险 | 验证 | 预期 |
|---|---|---|---|
| VERS-01 | 完整列表错绑 | Reader 返回版本及 `asOf`，请求固定 binding | 200；列表版本和规则记录完整，时间为 UTC 毫秒格式 |
| VERS-02 | 会话权限越界 | 匿名访问列表/详情 | 401，Reader 不调用 |
| VERS-03 | binding/version 路径非法 | 提交空/超长身份 | 400，Reader 不调用 |
| VERS-04 | 详情 ID 或 binding 不匹配 | Reader 返回别的 ID/绑定版本 | 不泄露对象，稳定 503 |
| VERS-05 | 权威缺失/错误 | Reader 未注入、NotFound、限流、不可用 | 分别 503/404/429/503，响应不含内部异常文本 |
| VERS-06 | 不可信版本对象 | 重复版本、跨 binding、错误 RuleKind、超界/非毫秒时间 | 领域构造或读取校验拒绝 |

## 证据

- Python 定向测试：`uv run --project components/sentinel/sentinel-console pytest components/sentinel/sentinel-console/tests/test_rule_versions_api.py components/sentinel/sentinel-console/tests/test_rule_drafts_api.py components/sentinel/sentinel-console/tests/test_rule_set_snapshot_api.py components/sentinel/sentinel-console/tests/test_rule_bindings_api.py components/sentinel/sentinel-console/tests/test_incident_timeline_api.py components/sentinel/sentinel-console/tests/test_fleet_overview_api.py -q`，**51 passed**。
- Console 源码 `compileall` 通过；本切片 Python 文件 88 列检查通过；前端 `npm run contract:check` 核对 OpenAPI **42 paths** 通过。
- 文档更新后 `git diff --check` 通过。

这些证据不代替生产存储、完整 Console 回归或 Python/React 浏览器 E2E；这些仍按推进清单中的对应里程碑验收。
