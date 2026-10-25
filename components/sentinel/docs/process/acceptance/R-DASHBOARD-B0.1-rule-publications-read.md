# B0.1 — 规则发布记录读取验收

## 范围

实现规则绑定范围内发布记录列表及单条详情：

- `GET /api/v1/rulesets/{bindingId}/publications`
- `GET /api/v1/rulesets/{bindingId}/publications/{publicationId}`

发布对象仅表达校验、配置写入和回读三个独立阶段；本切片不执行配置中心写入，不推断实例已加载，也不接入持久化 adapter。

## 定向验收矩阵

| ID | 风险 | 验证 | 预期 |
|---|---|---|---|
| PUB-01 | 三阶段被混为单一成功 | 构造 awaiting/running/succeeded/failed/unknown 组合 | 严格执行状态不变量，合法阶段原样返回 |
| PUB-02 | 路径错绑/错 ID | authority 返回其它 binding/publication | fail-closed，不返回外部对象 |
| PUB-03 | 未授权访问 | 匿名读取列表/详情 | 401 且 Reader 不调用 |
| PUB-04 | 非法路径 | 空或超限 binding/publication ID | 400 且 Reader 不调用 |
| PUB-05 | 权威故障 | Reader 未注入、NotFound、限流、不可用 | 503/404/429/503 稳定映射，不泄露内部消息 |
| PUB-06 | 不可信集合/阶段事实 | 重复 ID、跨 binding、数量超限、阶段矛盾/非 UTC 毫秒 | 值对象拒绝并映射为安全不可用 |

## 证据

- 定向 Python 测试：规则发布、版本、草稿列表/详情、规则快照/绑定、Incident timeline 与 Fleet overview **61/61 passed**。
- 前端 `npm run contract:check`：OpenAPI **42 paths** 对位通过；新增列表/详情路径已存在于合同文件。
- 该验证未执行完整 Console 套件或浏览器 E2E；本切片没有写入配置中心，也没有真实发布 authority、生产持久化 adapter 或实例回执。因此它只证明 API/domain 读取合同，不证明发布链路完成。
