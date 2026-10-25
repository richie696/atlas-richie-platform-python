# B0.1 故障事件证据读取 API 首切片

## 目标与边界

按前端 `readIncidentEvidence` 合同实现 `GET /api/v1/incidents/{incidentId}/evidence`。查询必须将事件 ID、环境、应用/实例 scope、时间窗口和 severity/category filters 绑定为一个精确 identity。事件缺失或不匹配过滤条件时统一返回 404。证据只承载结构化观测事实；关联规则身份由 authority 精确提供，禁止从标题、caption 或时间相近性推断。此切片不执行写操作，也不声明根因。

## 测试矩阵

| 风险 | 测试 | 断言 |
|---|---|---|
| 授权边界 | admin/view 与匿名 | 两种角色允许读取；匿名请求不触达 evidence authority |
| 请求 identity | path ID、scope、窗口、过滤器缺失/非法/不一致 | 非法 query 返回 400；path/query 的事件不一致 fail-closed |
| 事件可见性 | 不存在或不满足 scope/window/severity/category 的事件 | 一律 404，不透露过滤外事件是否存在 |
| 证据完整性 | complete/partial/unavailable、facts 数量与重复 ID | 状态、事实条数、时间及结构化事实满足约束 |
| 导航关系 | related rule 与 event publication/version/app identity | 仅返回精确匹配的权威关联；不可推断关联 |
| authority 故障 | 未装配、限流、不可用、错误 query echo | 503/429/503；不泄漏底层异常 |

## 验证记录

- 状态：实现完成，定向验证通过。
- **证据：**与 timeline、Fleet、实例/观测目录相邻 route 定向测试 **36/36 passed**；Python Console 源码与新增测试 `compileall` 通过；涉及 Python 文件 88 列检查通过；前端 `npm run contract:check` 验证 OpenAPI 42 paths；`git diff --check` 通过。
- **生产组合补齐：**`SQLAlchemyIncidentEventAdapter` 同时实现 `IncidentEvidenceReader`；`identity_composition` 默认将其装配为 timeline 与 evidence authority。Evidence 读取只返回仍在保留期内且满足完整 query identity 的精确事件；其自身 caption 作为唯一已持久事实，完整性为 `partial`，关联规则保持 `null`，不推断或伪造上下文。
- **本轮复验：**SQLite SQL 持久化、精确 evidence 查询/筛选外 404、API 及默认 composition 定向测试 **26 passed**；compileall 与目标文件 `git diff --check` 通过。Ruff 未安装，未验证。
- **数据库方言复验：**将 exact evidence read 加入 `test_incident_event_dialect_acceptance.py` 后，隔离 MySQL 8.4.11 和 PostgreSQL disposable wrappers 分别 **2 passed**；wrapper 正常退出并清理本轮自有容器。该测试读取真实 SQL rows，校验完整 query identity 和 partial 事件事实。
- 执行 `dashboard-prototype/docs/TESTING_CADENCE.md` 的日常切片策略，仅运行 evidence、timeline 和相邻 observations route 定向测试。
- 不代表独立相邻指标事实、规则关联 authority、生产服务部署、前后端 live 联调或浏览器里程碑 E2E 验收；evidence 当前只提供事件自身的 partial 证据。SQLite/MySQL/PostgreSQL disposable SQL 路径已定向验证，但不是生产数据库部署或保留策略验收。
