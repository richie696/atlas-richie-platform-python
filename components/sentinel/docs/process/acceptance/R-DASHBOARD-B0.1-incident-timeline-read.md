# B0.1 故障时间线读取 API 首切片

## 目标与边界

按前端 `readIncidentTimeline` 合同实现 `GET /api/v1/incidents`。本切片只读取由调用方注入的事件事实，不负责 Reporter/Collector 采集、持久化、事件归因、证据详情或写入操作。未装配读取 authority 时必须安全返回 `503 service_unavailable`，不得回退到 fixture。

## 测试矩阵

| 风险 | 测试 | 断言 |
|---|---|---|
| 授权边界 | admin/view、匿名、无权限、会话 authority 不可用 | 两个受支持角色可读；拒绝请求不调用事件 authority；稳定错误码 |
| 查询解析 | 缺参、未知/重复参数、无效枚举、越界 pageSize/cursor、无效窗口/scope | 返回 `400 invalid_request` 且 authority 未调用 |
| 事件事实 | 资源压力/RT/规则发布/规则生效四类结构化 caption | 类别与 fact 一致；时间/标识符/比例值满足约束 |
| 页面快照 | 全范围统计与过滤分页、严格时间排序、query echo | 统计独立于筛选/游标；分页不超过 pageSize；错误快照 fail-closed |
| authority 故障 | 未装配、目标不存在、限流、不可用、非法返回 | 分别映射 503/404/429/503；不泄漏异常详情 |

## 验证记录

- 状态：实现完成，定向验证通过。
- **证据：**`tests/test_incident_timeline_api.py` + Fleet/实例/观测目录相邻 API 套件 **31/31 passed**；Python Console 源码和新增测试 `compileall` 通过；修改的 Python 文件 88 列检查通过；前端 `npm run contract:check` 验证 OpenAPI 42 paths；`git diff --check` 通过。
- 日常验证按 `dashboard-prototype/docs/TESTING_CADENCE.md` 执行本切片及受影响的相邻 Python API 定向套件。
- 本记录不代表真实 Reporter/Collector、数据库、部署、React→Python 联调或浏览器里程碑 E2E 验收。
