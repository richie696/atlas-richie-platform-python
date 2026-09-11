"""可移植的 OAuth 失败分类，错误信息绝不携带凭据或令牌。
----
所有异常均派生自 `atlas_richie.contracts.PlatformError`，业务代码可以
用 `except OAuthError` 一并捕获 OAuth 组件内部发生的所有可预期失败。

**设计原则：错误信息不含敏感数据**

- 不回显 access_token / refresh_token / client_secret。
- 远程 `error` 字段在 `_safe_error_code` 处做了白名单过滤，只保留 RFC
  6749 §5.2 / §4.1.2.1 注册过的标准错误码，其他一律归并为通用
  `oauth_endpoint_error`。
- HTTP 状态码（`status_code`）是仅有的诊断信号之一，与错误码搭配使用。

**子类型语义（与业务侧的对齐）**：

- `OAuthConfigurationError`：调用方在拼装请求前就提供了不安全或不
  一致的值（如空字符串、错误格式的 resource URI）。归类为"用户错"。
- `OAuthProtocolError`：远端 OAuth 端点（authorization server、token
  endpoint、userinfo、metadata、introspection…）返回的协议层响应不
  合规（缺字段、类型不对、`expires_in` 非法、scope 不是空格分隔
  字符串等）。归类为"对端错"。
- `OAuthEndpointError`：HTTP 层成功握手但 OAuth 业务层拒绝（错误
  码 + 非 2xx 状态码）。携带 `error` + `status_code` 字段供调用方
  决定重试 / 报错策略。
- `OAuthResourceMismatch`：调用方尝试用 `OAuthTokenManager` 跨越
  已绑定 `ResourceIndicator` 的边界 —— 这是租户隔离的硬错误，
  重试无意义。
- `OAuthTokenValidationError`：本地（JWT/DPoP 校验）或远端
  （introspection 兜底）的 access token 验证失败。

English
--------
Portable OAuth failure categories that never carry credentials or tokens.

All exceptions derive from `atlas_richie.contracts.PlatformError`, so
business code can `except OAuthError` to catch every expected failure
the OAuth component raises.

**Design principle: error messages carry no sensitive data.**

- Access tokens, refresh tokens, and client secrets are never echoed.
- Remote `error` values pass through `_safe_error_code` (RFC 6749
  §5.2 / §4.1.2.1 whitelist); anything else collapses to the generic
  `oauth_endpoint_error`.
- The HTTP status code (`status_code`) is the only diagnostic signal
  exposed alongside the error code.

**Subtype semantics:**

- `OAuthConfigurationError`: caller supplied an unsafe or inconsistent
  value before request assembly (blank string, malformed resource
  URI, ...). Category: user error.
- `OAuthProtocolError`: a remote OAuth endpoint (authorization
  server, token, userinfo, metadata, introspection, ...) returned a
  malformed protocol-level payload (missing field, wrong type,
  illegal `expires_in`, scope not space-delimited, ...). Category:
  peer error.
- `OAuthEndpointError`: HTTP handshake succeeded but the OAuth
  business layer rejected the request (error code + non-2xx status).
  Carries `error` + `status_code` for caller-driven retry / report
  policy.
- `OAuthResourceMismatch`: caller attempted to cross a bound
  `ResourceIndicator` boundary via `OAuthTokenManager`. A hard
  tenant-isolation error; retry is meaningless.
- `OAuthTokenValidationError`: local (JWT/DPoP verification) or
  remote (introspection fallback) access-token validation failed.
"""

from atlas_richie.contracts import PlatformError


class OAuthError(PlatformError):
    """中文
    ----
    OAuth 组件所有可预期失败的根异常。

    English
    --------
    Base class for expected OAuth component failures.
    """


class OAuthConfigurationError(OAuthError):
    """中文
    ----
    调用方在拼装请求前就提供了不安全或不一致的值。

    English
    --------
    A caller configured an unsafe or inconsistent OAuth value.
    """


class OAuthProtocolError(OAuthError):
    """中文
    ----
    远端 OAuth 端点（authorization server / token / userinfo /
    metadata / introspection）返回的协议层响应不合规。

    English
    --------
    An OAuth peer produced a malformed protocol response.
    """


class OAuthEndpointError(OAuthError):
    """中文
    ----
    HTTP 握手成功但 OAuth 业务层拒绝（错误码 + 非 2xx）。携带
    `error` 与 `status_code` 供调用方决策。

    English
    --------
    An OAuth endpoint rejected a request without exposing sensitive
    body data.
    """

    def __init__(self, error: str, status_code: int) -> None:
        super().__init__(f"OAuth endpoint rejected the request: {error} (HTTP {status_code})")
        self.error = error
        self.status_code = status_code


class OAuthResourceMismatch(OAuthError):
    """中文
    ----
    跨 `ResourceIndicator` 边界使用 token —— 租户隔离的硬错误。

    English
    --------
    A caller attempted to use a token outside of its bound resource.
    """


class OAuthTokenValidationError(OAuthError):
    """中文
    ----
    本地（JWT/DPoP 校验）或远端（introspection 兜底）access token
    验证失败。

    English
    --------
    An access token failed local or remote resource-server validation.
    """
