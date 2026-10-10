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
