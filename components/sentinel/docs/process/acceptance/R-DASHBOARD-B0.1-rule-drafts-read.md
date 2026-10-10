# B0.1 规则草稿读取 API 首切片验收

日期：2026-10-09  
状态：**Console 合同适配完成；生产草稿 authority 未接入**

## 契约范围

- `GET /api/v1/rulesets/{bindingId}/drafts`，仅 admin (`rules:write`) 可读；viewer 和匿名请求必须在 authority 调用前拒绝。
- 成功响应精确回显 bindingId，包含毫秒精度 UTC `asOf` 和至多 1,000 个草稿；所有 draft 都属于该绑定，ID 唯一。
- 每个草稿包含完整身份、kind/profile、基线版本/checksum、source revision、更新时间与完整 typed records；record 类型必须与 draft kind 相同。
- 响应禁止凭证、原始 provider connection options；缺失 authority 安全返回 503，不合成空草稿列表。

## 风险到测试

| 风险 | 验证 |
|---|---|
| 权限绕过 | admin 成功；view/匿名拒绝且 reader 未调用；Session authority 故障稳定 503 |
| 跨绑定/坏 authority 数据泄漏 | binding mismatch、重复 draft ID、超过 1,000 项、kind/record mismatch fail-closed |
| 协议字段或时间错位 | wire 与前端严格 DTO 字段、完整 RuleRecord、UTC 毫秒时间验证 |
| authority 失败信息泄漏 | not found / rate limited / unavailable 映射 404/429/503，响应不包含私有详情 |
| 默认路径制造假数据 | reader 缺失返回 503，不把空目录作为成功 |

## 验收边界

先运行草稿、rule snapshot、rule binding 的定向 Python API tests 及相关静态/协议检查；不运行完整浏览器 E2E（仅里程碑执行）。Reader test double 只证明 Console 合同，不证明生产存储或 Nacos/Consul。

## 实现与验证记录

- 新增领域不可变 `StoredRuleDraft` / `RuleDraftCollection`、窄 `RuleDraftReader` Port、只读用例和 `GET /api/v1/rulesets/{bindingId}/drafts`。
- API 只授予 `rules:write`（当前 admin）；view/匿名在访问 authority 前拒绝。集合 identity 必须与 path 一致，draft ID 唯一且绑定一致，记录类型与草稿 kind 一致，items/records 都最多 1,000 项；时间按 UTC 毫秒协议验证。
- 序列化复用完整 typed `RuleRecord` 投影；没有凭证字段或 mock fallback。生产 authority 未接入时返回 503。
- 草稿、规则快照、规则绑定、Incident timeline 与 Fleet overview 定向测试 **39 passed**；覆盖权限、无效/跨绑定 identity、重复草稿、上限、毫秒时间、五类规则快照回归以及 404/429/503。
- Console `compileall`、本切片及相关 Python 文件 88 列检查、前端 `npm run contract:check`（42 paths）与 `git diff --check` 均通过。无完整 E2E。
