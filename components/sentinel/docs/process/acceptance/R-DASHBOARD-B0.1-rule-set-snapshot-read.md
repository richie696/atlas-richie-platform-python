# B0.1 规则权威快照读取 API 首切片验收

日期：2026-10-09  
状态：**Console 合同适配完成；生产规则 authority 未接入**

## 实现

- 依据 `readRuleSetSnapshot` 合同增加 `GET /api/v1/rulesets/{bindingId}/snapshot`。
- 以 frozen/slots dataclass 和有限 `IntEnum` 建模 Sentinel 五类完整规则值；包括阈值编码、正/非负有限数、warm-up/排队、cluster window、熔断阈值、系统禁用标记、authority caller 去重、参数例外去重与 100 项上限。
- Snapshot 固定绑定身份、nullable version/source revision、checksum、UTC aware `asOf` 和最多 1,000 条完整规则；record ID 唯一，规则 kind 必须与绑定 kind 相同。
- 只读 `RuleSetSnapshotReader` Port 与 `ReadRuleSetSnapshot` 用例校验精确 bindingId。Route 负责 session、路径输入与稳定错误映射；缺少 authority 时返回 503，不伪造空快照。
- Serializer 将内部 typed DTO 映射为 OpenAPI camelCase 五类联合结构，不包含凭证或原始 provider connection options。

## 验证

- Snapshot/绑定目录及 Incident timeline、Fleet overview 定向 API 套件 **32 passed**。包括 admin/view、匿名/Session authority 故障、五类规则序列化、binding mismatch、规则类别/数量/重复 identity/毫秒精度不变量、invalid input 与 404/429/503。
- Console 源码/测试 `compileall`、新增及相关 Python 文件 88 列检查、React `npm run contract:check`（42 paths）、`git diff --check` 均通过。

## 边界

没有生产规则源 adapter、DB 持久化、Nacos/Consul 快照回读、React→Python live 页验收；reader 未注入时安全返回 503。该切片不包含草稿、版本、校验、发布命令，也不执行完整浏览器 E2E；后者保留到里程碑。
