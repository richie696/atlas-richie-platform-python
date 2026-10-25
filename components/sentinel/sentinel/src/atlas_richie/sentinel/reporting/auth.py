"""Atlas Richie Sentinel — Agent Reporting V1 auth header (M6.5.x).

中文
----
``X-Atlas-Reporting-Token`` 头管理 (协议 transport §5.1):

- Header 名常量: ``X_ATLAS_REPORTING_TOKEN_HEADER = "X-Atlas-Reporting-Token"``
- 每次 HTTP 请求都必须带, 缺失或鉴权错 Server 返 401 + ``AUTH_FAILED``
- 本模块只做"把 token 渲染成 header 字节" + "sanitize 换行 / 不可见
  字符防 header injection", 不做网络调用

**不**做 token 持久化 (1.0 由调用方负责构造 ``AgentReporterConfig`` 时
传入, 跟 Java ``atlas-richie-cache`` 的 token 模式一致).

English
--------
``X-Atlas-Reporting-Token`` header management (protocol transport §5.1):

- Header name constant: ``X_ATLAS_REPORTING_TOKEN_HEADER =
  "X-Atlas-Reporting-Token"``
- Required on every HTTP request; missing or invalid causes Server
  to return 401 + ``AUTH_FAILED``
- This module only renders the token into header bytes and sanitizes
  CR/LF / invisible chars to prevent header injection; no network call.

Does **not** persist the token (1.0 caller is responsible for passing
it via ``AgentReporterConfig``, matching Java ``atlas-richie-cache``
token mode).
"""

from __future__ import annotations

from ..errors import SentinelConfigurationError

# 协议 transport §5.1 强制 header 名
X_ATLAS_REPORTING_TOKEN_HEADER: str = "X-Atlas-Reporting-Token"


def _sanitize_token(token: str) -> str:
    """防 HTTP header injection: 拒绝 CR / LF / NUL 等不可见字符.

    中文
    ----
    token 在 HTTP header 里传输, 任何 ``\\r`` / ``\\n`` / ``\\x00`` /
    其它控制字符都可能被中间件 (proxy / load balancer) 解释为
    header 终止 / 注入新 header. Reporter 永不把这种 token 发出.

    English
    --------
    Tokens travel in HTTP headers; any ``\\r`` / ``\\n`` / ``\\x00`` /
    other control chars could be interpreted by middleware (proxy /
    load balancer) as a header terminator / new-header injection.
    Reporter never sends such a token.
    """
    for ch in token:
        code = ord(ch)
        if code < 0x20 or code == 0x7F:
            raise SentinelConfigurationError(
                f"auth_token contains forbidden control char (0x{code:02X}); "
                f"refusing to render header to prevent HTTP header injection",
                field="auth_token",
                reason="forbidden control char",
                value=f"<{len(token)} chars, control=0x{code:02X}>",
            )
    return token


def render_auth_header_value(token: str) -> str:
    """Render ``auth_token`` → header value 字符串 (不带字段名).

    中文
    ----
    给 transport 层拼装 request 时使用:
    ``b"X-Atlas-Reporting-Token: " + value.encode("utf-8") + b"\\r\\n"``

    Raises:
        SentinelConfigurationError: token 含不可见字符 (header
            injection 防护)
    """
    if not isinstance(token, str) or not token:
        raise SentinelConfigurationError(
            f"auth_token must be non-empty str, got "
            f"{type(token).__name__} len={len(token or '')}",
            field="auth_token",
            reason="empty / wrong type",
            value=type(token).__name__,
        )
    return _sanitize_token(token)


__all__ = [
    "X_ATLAS_REPORTING_TOKEN_HEADER",
    "render_auth_header_value",
]
