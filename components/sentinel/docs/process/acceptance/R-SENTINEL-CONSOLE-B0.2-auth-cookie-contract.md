# B0.2 身份 Cookie 协议常量归一化（2026-10-09，局部）

## 目标与边界

让 Console 身份和 bootstrap HTTP adapter 对 `sentinel_session` 与 `__Host-sentinel_csrf` 使用同一协议常量 owner，避免 route 之间发生 Cookie 名称漂移。本切片不改变 Cookie 值、Secure/HttpOnly/SameSite/Path 属性、Origin/CSRF 校验或身份工作流。

## 实现

- `api.browser_security` 是 `SESSION_COOKIE_NAME` 与 `CSRF_COOKIE_NAME` 的唯一生产定义。
- login、logout、session、account directory、system observation 与 bootstrap adapters 导入并使用该定义。
- `bootstrap_browser_security` 复用同一 CSRF 常量；没有引入新的 service、基类或 GoF 模式。
- 修正 bootstrap request-id 测试对随机 UUID 使用宽泛子串断言的问题，改为精确验证非法输入不回显且服务端 fallback 是有效 UUID。

## 验证

在 `components/sentinel/sentinel-console` 执行：

```text
.venv/bin/python -m pytest -q tests/test_login_api.py tests/test_session_api.py tests/test_logout_api.py tests/test_bootstrap_api.py tests/test_bootstrap_authorize_api.py tests/test_account_directory_api.py tests/test_account_commands.py tests/test_own_password.py
.venv/bin/python -m pytest -q tests/test_system_connections_api.py tests/test_system_audit_api.py tests/test_system_protocols_api.py
74 passed across both focused invocations (57 + 17)
```

另执行：

- `.venv/bin/python -m compileall -q` 覆盖本次变更的 API 模块与 bootstrap 测试：通过。
- 搜索生产 API 源码中 Cookie 字面值：两个名称均只在 `api.browser_security` 定义。
- `git diff --check`：通过。

本包没有配置或安装 Ruff，本切片不声称 Ruff 门禁通过。测试使用 ASGI 与隔离 SQLite，不访问外部数据库、Nacos、Consul 或生产服务。

## 未覆盖

- PostgreSQL/MySQL 驱动、生产 ingress/TLS/cookie domain 与实际浏览器跨源行为。
- React→Python 最终 E2E、浏览器 session expiry/revocation、Cookie 与 CSRF 联调。
- B0.2 整体任务仍未完成；此记录只证明 Cookie 常量统一与相邻 API 回归。
