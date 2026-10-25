# R-DASHBOARD-F4.31–F4.33 本人修改密码验收记录

日期：2026-10-09  
状态：**定向逻辑与隔离 API 测试通过；页面与真实 Console 验收未完成**

## 已验证

- 前端运行 `npm run test:logic:focused -- 'PASSWORD-(VALIDATE|OWNER|OUTCOME)'`：**6/6 passed**。覆盖本人 session owner、viewer 本人改密、未知/过期/匿名/换账号/换 session 拒绝；确认字段仅本地且请求不含 `accountId`；pending 单飞；已知拒绝可修正；timeout、5xx、取消、无效回执属于 unknown 且不自动重放；密码不进入 workflow snapshot。
- 前端新增实际 `OwnPasswordPage` SSR 渲染验证：三种 locale 均只呈现当前/新/确认三个 password 输入，确认 `autoComplete` 语义分别为 `current-password` / `new-password` / `new-password`；页面使用传入的 session username，不渲染 account ID 或账号目标选择。`node --test --test-name-pattern='F4.31-PASSWORD-PAGE-RENDER' tests/i18n/catalog.test.mjs`：**1/1 passed**；本轮 `npm run check:fast` 通过。
- Python Console 运行 `PYTHONPATH=src:tests:/private/tmp/sentinel-console-deps.viomBu:/Users/richie696/Projects/workspace/atlas-richie-platform-python/components/sentinel/sentinel/.venv/lib/python3.12/site-packages /private/tmp/sentinel-console-account-identity-env-20261007/bin/python -m unittest discover -s tests -p 'test_own_password.py' -v`：**5/5 passed**（Python 3.12.14）。覆盖 admin/view 只能改本人、错误当前密码无写入/审计、输入与 Origin/CSRF 拒绝、成功 Argon2id/撤销所有 session/安全回执，以及事务失败回滚。数据库仅为隔离 SQLite。

## 未完成边界

Codex 内置浏览器本轮没有可访问标签；CUA 报告设备锁屏，因此没有正式 mounted 页面交互证据。SSR 只验证服务端生成的字段语义，不覆盖浏览器 autocomplete 行为、键盘、可见错误与成功态、URL/storage 不含密码及会话过期后的页面表现，仍需 IAB 专项检查。未运行 Chrome、Edge 或 CDP；`tests/e2e/password.e2e.test.mjs` 的 probe 不是正式页面证据。Python `build_app` 生产装配、PostgreSQL/MySQL 事务行为和真实浏览器到 Python 的跨层路径仍未验收。

因此 F4.31–F4.33 不勾选。本记录只保存本轮可复现的 focused 证据；完整 E2E 留给里程碑节点。

## 2026-10-11 补充：本人改密的冲突错误边界

F4.32 的早期任务文字提到“冲突”，但当前权威页面协议、OpenAPI 和 Python route error set 对 `changeOwnPassword` 均未定义 `409 conflict`；该命令也没有客户端可提交的目标 revision 或 operation lookup key。故当前实现不新增猜测性 409 UI/恢复行为。`createCommandResource` 的通用 `409` 状态能力不意味着每个 command endpoint 都支持冲突。若并发改密未来需要独立冲突语义，应先冻结服务端错误码、原子判定与恢复规则，再同步扩展页面与协议。

同日补充正式 `OwnPasswordPage` SSR 三语错误投影：`current_password_invalid`、`validation_failed`、`rate_limited`、`unauthenticated`、`csrf_failed`、`service_unavailable` 均映射到冻结文案，并断言合成原始异常消息不渲染。定向 `F4.31-PASSWORD-PAGE-RENDER` **1/1 passed**；该 SSR 证据仍不替代页面 mounted、计时器/键盘或 Python live 验收。

## 2026-10-09 补充：当前密码错误的前后端合同对齐

- **问题：**React 页面已预留 HTTP 400 “当前密码不正确”提示，但 Python 将错误当前密码与 session 失效都映射为 401 `unauthenticated`，导致已登录用户无法得到正确的可修正反馈。
- **实现：**应用用例新增 `OwnPasswordCurrentPasswordInvalid`，仅当 session 对应的账号存在但当前密码验证失败时抛出；API 映射为 HTTP 400 `current_password_invalid`。未找到/失效 session 以及变更期间授权失效仍为 HTTP 401 `unauthenticated`。Console 错误目录、本人改密 endpoint、OpenAPI 与三语错误呈现均已同步；页面根据稳定 error code 映射提示，不再按所有 400 猜作当前密码错误。
- **验证：**Python `tests/test_own_password.py` **6 passed**，包括错误密码不改哈希、不撤 session、不写 audit，以及未知 session 仍为 401；前端 `OWN-PASSWORD-ERROR` HTTP/MSW 合同 **1/1 passed**，验证错误后保留可信 session 并可显式重提；`node --test tests/i18n/catalog.test.mjs` **18/18 passed**，三语真实页面 SSR 确认当前密码错误显示正确的可修正文案而非 session 过期提示。`npm run contract:generate` 更新 43-path OpenAPI；`npm run check:fast` 通过。
- **边界：**SSR 不等于 mounted 浏览器交互；Mock 登录密码不代表真实密码持久行为。改密专用 rate limit、PostgreSQL/MySQL、部署组合及浏览器到 Python E2E 仍未完成，因此 F4.31–F4.33、B0.2 均不据此勾选。

## 2026-10-09 补充：改密失败限速

- **职责/设计：**`ChangeOwnPassword` 持有失败累计、封锁检查与恢复规则；它消费最小 attempt-limiter Port。SQL adapter 复用既有数据库锁定与部署配置的窗口策略。改密 attempt key 由 account ID 通过独立用途前缀及部署 HMAC key 派生，表内不落原始用户名/账号 ID，改密桶与登录来源 IP 桶互不影响。未发现适用 GoF 模式：这是同步用例中的一个单一策略依赖，不需要代理、装饰器或责任链。
- **风险→本地验证：**

  | 风险 | 验证 | 当前证据 |
  | --- | --- | --- |
  | 错误当前密码可无限触发 Argon2 校验 | 隔离 SQLite/ASGI：两次错误后 429；被限请求不再调用 verifier | `test_wrong_password_is_rate_limited_per_account` |
  | 一个账号限速错误影响另一个账号 | 同一测试在 admin 桶封锁后仍允许 view 本人完成改密 | 同上 |
  | 限流状态不可用时静默放行 | 隔离 SQLite/ASGI 删除 attempt 表后执行改密，断言返回 503 且不运行密码 verifier | `test_rate_limit_authority_failure_fails_closed`；真实 PG/MySQL 故障仍未验 |
  | HTTP 与 OpenAPI 错误码不一致 | API 429 带 `rate_limited` 与有界 `retryAfterMs`；机器合同现有 429 schema 保持一致 | own-password ASGI 测试及 generated OpenAPI route parity |

- **验证：**`PYTHONPATH=src .venv/bin/pytest -q tests/test_own_password.py tests/test_identity_composition.py tests/test_login_attempt_limiter.py tests/test_console_openapi_route_parity.py`：**22 passed**。另 `npm run contract:check` 验证 OpenAPI 43 paths，改密操作已有 429 schema；Python `compileall` 与 `git diff --check` 通过。SQLite 仅证明本地 SQL 路径；不证明 PostgreSQL/MySQL 锁语义、多 worker 部署或迁移/生产配置。
- **边界：**复用现有 `SENTINEL_CONSOLE_LOGIN_FAILURE_THRESHOLD`、`SENTINEL_CONSOLE_LOGIN_FAILURE_WINDOW_SECONDS`、`SENTINEL_CONSOLE_LOGIN_BLOCK_DURATION_SECONDS` 配置，改密和登录计数桶彼此隔离但策略参数相同；尚无单独改密策略开关。前端 transport 已声明 rate_limited 并保留输入/冷却流程，但本补充未运行 mounted React 或最终浏览器 E2E。F4.31–F4.33 与 B0.2 仍保持未勾。

## 2026-10-10 补充：本人改密密码长度上限

- **问题与修复：**Python API 与 write-only secret schema 的上限是 1024 UTF-16 单元，而本人改密本地校验原先仅检查最小长度。现将该上限集中命名并由 identity 密码策略和共享 wire schema 共用；当前/新密码超限都返回结构化本地问题，三语提示展示从策略常量插值的 12–1024 范围。
- **验证：**密码逻辑 focused **1 passed**；HTTP schema focused **1 passed**，明确断言超长输入不会调用 transport；i18n catalog/runtime producer **2 passed**；`npm run check:fast` 通过。
- **边界：**已安装 Astryx `TextInput` 的公开 API 没有原生 `maxLength`，所以 UI 在提交时校验，不做不受支持的 prop 转发或 DOM 操作；未运行 mounted 浏览器或最终 E2E，F4.31–F4.33 仍未勾选。

## 2026-10-12 补充：本人改密页面 mounted IAB 目标隔离

- **环境：**Codex 内置浏览器中的 `127.0.0.1:5173` 本地 Mock，当前 session 为 `viewer`。
- **验证：**通过会话菜单进入“修改密码”，页面显示“为账号 viewer 设置新的登录密码”，仅有当前密码、新密码、确认新密码和提交按钮，无目标账号选择。随后直接打开带 `account=account-admin` 的站内改密 URL，页面仍说明目标是当前 session 的 `viewer`，表单结构不变。没有填写或提交任何密码。
- **边界：**只证明 mounted 页面目标由当前 session 决定，不证明 input DOM 的 autocomplete 属性、键盘/焦点、提交状态、失败/成功清理或 Python live 接口。密码变更属于凭证操作，本轮不代用户填入/提交；完整 E2E 仍后置，F4.31–F4.33 不勾选。

## 2026-10-12 补充：本人改密定向测试复核与匿名深链边界

- **复核命令与结果：**Dashboard `npm run test:logic:focused -- 'PASSWORD-'` **9/9 passed**；`npm run test:http:focused -- 'OWN-PASSWORD'` **2/2 passed**；`node --test --test-name-pattern='F4.31-PASSWORD-PAGE-RENDER' tests/i18n/catalog.test.mjs` **1/1 passed**。Console `.venv/bin/pytest -q tests/test_own_password.py` **10 passed**，覆盖隔离 SQLite/ASGI 下的错误密码不变更、账户级限速、成功后撤销会话及重新认证、CSRF/Origin、事务失败、UTF-16 边界和脱敏回执等。
- **IAB 只读检查：**新建临时内置浏览器标签直接打开本地 `#/change-password` 深链；匿名状态被应用重定向到 `#/login?returnTo=change-password...`，登录表单可见。没有输入或提交凭证，未造成改密副作用；临时标签已关闭。
- **结论与边界：**本轮仅使用合成测试身份和内存 SQLite，没有访问真实账户、外部配置中心或真实数据库。逻辑、HTTP Mock、页面 SSR 与 Python ASGI 证据均通过；IAB 只证明匿名深链守卫，不能证明认证态本人改密表单的 mounted 键盘/焦点、反馈/清理时序，亦不构成 React→Python live API / PostgreSQL / MySQL 验收。完整 E2E 仍按计划留到全部实现收口后。故 F4.32/F4.33 保持开放，不以本轮定向测试提前关闭。

## 2026-10-12 补充：本人改密 429 冷却与前端保密聚焦复核

- **实现修正：**确认 `OwnPasswordPage` 原先只显示通用限流错误、未读取 `retryAfterMs`，因此服务端 429 后按钮仍可立即人工提交，与 §12.1 协议不符。现由本人改密 workflow 按单调时钟持有有界冷却截止时间，冷却期间即使绕过 UI 直接调用 workflow 也拒绝派发；独立 Hook 投影剩余秒数，页面三语展示冷却提示并禁用提交按钮。编辑表单不会清除冷却，冷却到期后仍须用户显式提交，不自动重发。workflow 不持久化冷却或密码。
- **本轮实际验证：**在 `components/sentinel/dashboard-prototype` 执行 `npm run test:logic:focused -- 'F4[.]32-PASSWORD|PASSWORD-'` **10 passed**（有界冷却、修改输入不解除冷却、截止前不派发、到期后显式提交）；`node --test --test-name-pattern='F4.31-PASSWORD-PAGE-RENDER' tests/i18n/catalog.test.mjs` **1 passed**（三语实际 `OwnPasswordPage` SSR；限流倒计时文案及 disabled 提交按钮）；`npm run test:http:focused -- 'OWN-PASSWORD|PASSWORD'` **3 passed**；`npm run typecheck`、改动文件 ESLint、`npm run i18n:check`、目标 Prettier check 与 `git diff --check` 均通过。i18n 资源已为三语增加倒计时及复数形式。
- **浏览器/保密证据边界：**尝试读取 Codex CUA 状态，当前 `browsers=[]`，因此本轮没有认证态 mounted IAB 页面。既有 SSR 证明字段类型与 `autocomplete` 属性；既有密码 E2E 源码包含 URL/storage 检查，但本轮没有执行 CDP/Chrome/Edge，也没有把未执行测试记作通过。没有输入或提交真实密码，没有启动 Python 服务或访问持久数据库。
- **结论：**F4.32 的 rate-limit UI/workflow 缺口已用定向自动测试覆盖；已知拒绝保留可修正输入、成功确认后清空、unknown 不重放仍由既有逻辑测试覆盖。F4.33 的浏览器键盘/焦点、实际 DOM autocomplete、URL/localStorage/sessionStorage 泄漏扫描、失败/成功清理与认证态 mounted 生命周期，以及 React→Python/PG/MySQL 路径仍缺本轮页面证据；F4.32/F4.33 继续保持开放，完整 E2E 仍按计划最后执行。

## 2026-10-12 补充：本人改密错误分类与 HTTP 敏感字段合同

- **风险→证据：**稳定拒绝不能误判为写入结果未知，服务错误/不可确认回执又不能被当作安全失败而重放；原始服务端诊断与密码字段不得进入 workflow snapshot 或 URL/请求头。
- **改动：**逻辑合同逐一锁定 `current_password_invalid`/400、`validation_failed`/422、`rate_limited`/429 为已知错误；拒绝本身不触发自动请求，snapshot 保留稳定 code/status 而不包含原始错误或密码，只有显式后续提交才会再 dispatch。HTTP 合同检查固定 POST path 无 query、密码不在 URL/headers、body 仅含 `currentPassword` / `newPassword`；5xx 维持 `result-unknown` 且阻止第二次派发。
- **验证：**Dashboard `npm run test:logic:focused -- 'PASSWORD-OUTCOME'` **4 passed**；`npm run test:http:focused -- 'PASSWORD-HTTP'` **2 passed**。仅使用合成密码和 MSW/内存 session。
- **边界：**这是逻辑与受控 HTTP adapter 合同，不证明浏览器历史/storage、键盘/焦点、实际 autocomplete、表单 DOM 成功清理或 Python live Cookie/CSRF/持久事务；没有访问真实服务或数据库，也未运行浏览器。F4.32/F4.33 继续开放，最终 E2E 仍留到实现收口后。

## 2026-10-12 补充：内置浏览器改密表单键盘顺序

- **环境：**仅打开项目已有的本地 Vite `127.0.0.1:5175`，没有停止或修改该进程。Codex IAB 中进入 `#/change-password` 后看到正式本人改密页及当前登录名说明；URL 不带账号或密码 query。
- **验证：**按 Tab 顺序实际聚焦到“当前密码”→“新密码”→“确认新密码”→“保存新密码”。静态源码核对 `PasswordFields` 为当前密码 `current-password`、新/确认密码 `new-password`，`TextField` 将 `autoComplete` 透传给 Astryx `TextInput`。没有输入、修改或提交任何密码；临时 IAB 标签已关闭。
- **空表单恢复：**重新打开隔离的本地 `5175` IAB 标签，保持三个字段为空点击“保存新密码”，页面明确提示“请输入当前密码”，没有进入成功态；未填入任何凭证，操作后关闭临时标签。
- **边界：**键盘次序为本地 mounted 交互证据；autocomplete 这里只核对应用传参/组件 adapter，未检查浏览器最终 DOM 属性或密码管理器行为，也未验证错误/成功后清理和 Python live。F4.33 及 F4.31–F4.33 完整闭环仍开放；完整 E2E 保留在最终阶段。
