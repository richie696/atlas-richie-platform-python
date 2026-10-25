# B0.1 单条规则草稿读取 API 首切片验收

日期：2026-10-09  
状态：**Console 合同适配完成；生产草稿 detail authority 未接入**

## 契约范围与测试矩阵

| 风险 | 定向验证 |
|---|---|
| 草稿跨绑定泄漏 | admin 对匹配 bindingId/draftId 读取成功；reader 返回任一身份不匹配时 fail-closed 503；authority 缺失返回 503 |
| 权限绕过 | viewer 403、匿名 401，且 reader 未被调用；Session authority 故障返回 503 |
| 路径输入绕过 | bindingId/draftId 均限制非空和 UTF-16 最大长度，非法输入在访问 reader 前返回 400 |
| 草稿 wire 漂移 | 完整 typed draft records、nullable base/source revision、UTC 毫秒时间、复用集合投影 |
| authority 信息泄漏 | not-found / rate-limited / unavailable 返回稳定 404/429/503，不反射原始错误 |

## 验收边界

本切片仅证明 Console API/领域边界适配；真实 DB 查询和生产装配仍未验证。运行详情、集合、snapshot、binding 相关定向套件；完整浏览器 E2E 留到里程碑。

## 实现与验证记录

- 新增独立的 `RuleDraftDetailReader` Port、`ReadRuleDraft` 用例和 `GET /api/v1/rulesets/{bindingId}/drafts/{draftId}`；复用 `StoredRuleDraft` 与 `stored_rule_draft_body` 投影，不重复定义规则内容模型。
- admin 可读；view/匿名拒绝，权限判断先于 authority；两个 path ID 都校验。authority 返回的 bindingId/draftId 任一不匹配时 fail-closed；not-found/rate-limited/unavailable 分别映射为 404/429/503。
- 草稿 detail、草稿集合、snapshot、binding、Incident timeline 与 Fleet overview 定向 API 套件 **42 passed**。覆盖身份错配、权限、坏路径、缺失/失败 authority、完整规则字段及错误脱敏。
- Console `compileall`、本切片涉及 Python 文件 88 列检查、`npm run contract:check`（42 paths）、`git diff --check` 通过。没有运行浏览器 E2E。
