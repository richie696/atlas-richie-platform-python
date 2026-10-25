# B0.1 规则绑定目录读取 API 首切片验收

日期：2026-10-09  
状态：**Console 合同适配完成；生产规则 authority 未接入**

## 实现

- 按前端 `readRuleBindings` 合同增加 `GET /api/v1/rulesets`，支持环境、可选应用/规则类型/关键词与显式分页。
- 领域不可变值对象校验规则类型、标识长度、分页范围、过滤总数、唯一绑定 ID、精确环境/应用/类型匹配；应用用例要求返回页原样绑定请求 query。
- `location` 只作为脱敏展示事实；拒绝 URI user-info 和常见敏感 query 参数。wire DTO 不包含凭证、原始连接选项或规则正文。
- 仅要求有效浏览器 session；admin/view 均可读，匿名拒绝。缺少 authority 时返回稳定 `503 service_unavailable`，不选择隐式 fixture。
- 严格拒绝未知/重复/缺失参数、非 ASCII 十进制分页和越界输入；映射 `400/401/404/429/503`。
- Console app composition 通过可选 `RuleBindingDirectoryReader` 注入 authority；没有新增 GoF 模式或跨 feature 依赖。

## 验证

- `test_rule_bindings_api.py`：7 项合同测试，覆盖 admin/view、过滤与 query echo、重复/未知/缺失/越界查询、匿名/会话 authority 故障、缺失 reader、404/429/503、query mismatch fail-closed 与敏感 location 拒绝。
- 与 Incident timeline、Fleet overview 相邻 API 定向套件合计 **24 passed**；Python `compileall`、本切片 Python 文件 88 列检查、前端 `npm run contract:check`（42 paths）与 `git diff --check` 通过。

## 边界

该切片只定义并实现 Console HTTP/domain/application adapter；尚无 Nacos/Consul/持久化规则目录 authority，也不证明 UI 生产页面已接通。规则 snapshot、草稿、版本、校验、发布等后续接口不在本次范围。完整浏览器 E2E 留至里程碑验收。
