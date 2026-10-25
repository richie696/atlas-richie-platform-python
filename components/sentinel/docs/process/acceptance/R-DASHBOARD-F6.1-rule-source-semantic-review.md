# F6.1 规则生命周期与配置源操作语义复核

日期：2026-10-12  
状态：局部复核完成；不表示 Console API 冻结或 F6.1 关闭。

## 范围与证据

本记录只覆盖规则绑定/生命周期和配置源登记操作的页面合同、前端 runtime operation schemas、生成 OpenAPI、Python parser/DTO/routes 与持久化操作 authority。没有改 wire schema、路径、状态码或 OpenAPI 产物；没有运行浏览器、完整 E2E、外部配置中心或生产服务。

审阅依据：

- 页面需求：[Dashboard页面能力与接口设计.md](../../Dashboard页面能力与接口设计.md) §4、§7。
- 唯一 Console 合同：[CONSOLE_API_CONTRACT.md](../../CONSOLE_API_CONTRACT.md) §9.4–§9.6。
- 机器合同：[console-api.openapi.json](../../protocol/console-api.openapi.json)，由前端 feature runtime schemas 生成。
- 前端运行时定义：`dashboard-prototype/src/features/rules/api/ruleSetContract.ts`、`ruleSetWire.ts`、`sourceRegistrationContract.ts`、`sourceRegistrationWire.ts`、两个 feature HTTP adapters。
- Python 实现：规则绑定 parser/routes、rule mutation store；配置源 parser、check/command/operation routes、registered source store。

## 发现与修正

### 同账号重新认证后不能核查原操作

合同 §9.5 明确要求：核查时重新验证当前 actor/session 权限；同一 actor 重新认证后不能仅因 Cookie 轮换就永久失去原操作核查路径。规则 operation lookup 和配置源 operation lookup 的 route 都会读取当前有效 session 并检查 admin；但 SQL authority 之前还要求 operation 行的 `session_hash` 等于这次 session digest，因此同一个 admin 换发新会话也只能收到 `not_found`。这比合同更严格，且打断“请求已提交但响应丢失后的安全核查”。

已修正为：

- 操作查询仍须通过当前有效 session 校验，并在当前账号权限已降为 `view` 时拒绝。
- 查询 operation 行按 `actor_account_id + binding_id（规则）+ request_key` 归属；配置源按 `actor_account_id + request_key` 归属。
- 不再将原始 session hash 作为回执可见性的额外限制。
- **写命令的相同 key 重放仍保持原 actor/session 与原始输入指纹约束**；本次没有放宽 mutate/replay 的授权。

回归覆盖同 actor 新 session 成功读回、另一 admin actor 不可读取、同账号权限降为 view 后拒绝。修改未改变 public DTO、route 或 OpenAPI。

## 对位结果

| 面 | 结果 |
| --- | --- |
| 规则 binding create/read | `POST/GET /api/v1/rulesets`、严格 Nacos/Consul target union、source ID/revision/provider 对位；写请求先校验 admin/Origin/CSRF/header-body requestKey，source provider/revision 由 authority 原子验证。201 创建 binding 不写规则正文。 |
| 规则 lifecycle | 当前 feature contracts/OpenAPI path-method 与 Python route registry 对位；规则命令、候选校验/差异与 read DTO 保持分离。规则操作核查当前登录 actor/admin 并精确限定 binding/key。 |
| 配置源管理 | `GET sources` 仅返回脱敏登记事实；`POST check` 是受 CSRF 保护的非幂等探测；`POST commands` 是带幂等键的 register/update；operation GET 返回脱敏 pending/completed/rejected/not_found。直接凭证/引用不进入读取或安全操作回执。 |
| 状态及错误边界 | 规则绑定注册缺少/重复/与 body 不一致的幂等头由 Python 返回 409 `idempotency_conflict`；配置源命令的格式错误/缺失或重复 header 按其合同返回 422 `validation_failed`，合法但与 body 不同返回 409 `idempotency_conflict`。相同 operation 的业务冲突通过其持久拒绝事实，不混为 HTTP transport conflict。 |
| 权限 | 已发布规则事实读取要求登录；编辑草稿、规则候选写入/校验需要 `rules:write`；创建 binding 与规则命令还要求 admin。配置源目录、探测、mutation 和 operation lookup 需要 admin。Python API 测试覆盖 viewer、匿名、CSRF、幂等和未装配 authority 的拒绝。 |

## 需要 API owner 在全局签字前明确

`createRuleBinding` 是同步 `201` 命令：同一 actor、同一 session、同 key/同 payload 可恢复原绑定，但该 operation 没有单独的 receipt lookup endpoint。若响应丢失且 admin 重新认证，当前重试依然受原 session 约束；目录 GET 可以观察目标是否存在，却不能证明该目标由哪一个原请求创建。需要 owner 在冻结 Console wire 前决定保留该边界、允许同 actor 新 session 精确恢复，还是为绑定注册增加安全的原操作查询。这里不自行新增路径或放宽写重放。

除此以外，仍须完成 F6.1 的 Console API owner 对全页面合同的最终审阅/签字，并依治理将 OpenAPI 从 `draft-partial` 转为正式冻结状态；本局部复核不替代这些决定。

## 验证

- 最终聚焦合同/持久化/API 回归（rule/source stores、commands、binding/source routes、OpenAPI parity/runtime coverage）：**115 passed, 2 skipped**。
- 初次回归的两项降权 fixture 尝试降权唯一 built-in admin，触发 DB 不变量；fixture 已改为先解除 built-in 标记，再验证当前 admin 权限撤销。最终聚焦回归通过。
- 先前只读对位运行：规则绑定、binding OpenAPI、配置源 command/registry/check 和 OpenAPI parity **65 passed**；前端 `npm run contract:check` 通过（43 paths，`draft-partial`）；`npm run test:http:focused -- 'RULE|SOURCE|BINDING|F6\\.1|OPERATION-ERROR-MATRIX'` **43 passed**。
- 本轮涉及的源码与测试 `git diff --check` 通过。尝试 Ruff 检查但环境未安装 Ruff（`Failed to spawn: ruff`），因此 lint 未验证；本子任务未改中央 checklist。

## 结论

规则与配置源 operation 的机器对位在上述局部范围通过；重新认证的 operation lookup 实现漂移已修正。唯一未决的本范围 API 语义是同步 binding-registration 在原 session 丢失后如何安全恢复；需 owner 决定，不因局部测试通过而视为已冻结。F6.1 继续开放。
