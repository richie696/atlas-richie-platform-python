# B0.1 — 规则激活计划列表读取验收

## 范围与风险

实现 OpenAPI operation `readRuleActivationPlans`：
`GET /api/v1/rulesets/{bindingId}/plans`。

| ID | 风险 | 断言 |
|---|---|---|
| PLN-01 | 读到其它 binding 的计划 | 路径 binding、集合 binding 与每个计划 binding 一致 |
| PLN-02 | 把客户端时间或推断状态当权威 | 原样保留服务端 activate/deactivate UTC 时刻、时区、有限生命周期状态及 publication ID |
| PLN-03 | 无效计划混入响应 | 版本与恢复版本不同，窗口严格递增，时区可由 Python IANA tzdb 解析，时间 UTC 毫秒精度 |
| PLN-04 | 集合过大、重复或错误采样 | 完整集合最多 1,000 条，ID 唯一，`asOf` 精确 |
| PLN-05 | 权限/authority 失败泄露 | session 先鉴权；未配置、404、429、503 均稳定映射且脱敏 |

## 设计边界

使用 Console-owned `RuleActivationPlanReader` 只读 Port；不在本切片实现计划创建、取消、执行 worker、Nacos/Consul 写回、数据库 schema 或自动调度。GOF 23 模式评估结论：当前是一条简单只读查询用例，不增加 GoF 模式。

## 实际结果（2026-10-09）

定向 Python 回归（包含发布/回执/版本/草稿/快照/binding/instance/incident/fleet 相邻合同）**85/85 passed**；前端 `npm run contract:check` 校验 OpenAPI **42 paths** 通过；Python `compileall`、相关 Python 文件 88 列检查和 `git diff --check` 通过。本记录不证明 scheduler persistence、配置中心发布或实例加载。
