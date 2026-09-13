"""Atlas Richie Sentinel Cluster — Client 鉴权头管理 (M6.3.4).

中文
----
``X-Atlas-Cluster-Token`` HTTP 头 (1.0 shared secret 鉴权, 协议 §3):

- Client 端**永远**发送非空 secret (同步 facade 内部注入, 单测不直调).
- Secret 长度不限, 但**不**进入 log / 错误消息 / 异常 chain (避免泄露).
- 缺失 / 错误 secret → Server 401 + INTERNAL_ERROR (走 ClusterFailurePolicy 决策).

**反例** (1.0 拒绝):

- ❌ 把 secret 写进 error message (``f"auth failed: {secret}"``)
- ❌ 把 secret 写进日志 (``log.info(f"using secret {secret}")``)
- ❌ 把 secret 反射到异常属性 (``raise AuthError(secret=secret)``)

English
--------
``X-Atlas-Cluster-Token`` HTTP header (1.0 shared secret auth, protocol §3):

- Client **always** sends non-empty secret (sync facade injects internally;
  unit tests don't call directly).
- Secret length unconstrained, but **never** enters log / error message /
  exception chain (avoids leak).
- Missing / wrong secret → Server 401 + INTERNAL_ERROR (ClusterFailurePolicy
  decision path).

Anti-patterns (1.0 forbidden):

- ❌ Embedding secret in error message (``f"auth failed: {secret}"``)
- ❌ Embedding secret in log (``log.info(f"using secret {secret}")``)
- ❌ Reflecting secret in exception attribute (``raise AuthError(secret=secret)``)
"""

from __future__ import annotations

from ..errors import ClusterConfigError

# 协议 §3 (M6.3.4 决策) — 唯一鉴权 HTTP header
AUTH_HEADER_NAME = "X-Atlas-Cluster-Token"


def build_auth_header(secret: str) -> tuple[str, str]:
    """构造 ``(header_name, header_value)`` 元组, 供 HTTP request 注入.

    Args:
        secret: shared secret (1.0 跟 ``ClusterTokenConfig.auth_secret`` 配对)

    Returns:
        (header_name, header_value) — 配 ``StreamReader.write(...)`` 直接写出.

    Raises:
        ClusterConfigError: secret 非空字符串 (启动 fail-fast 配套)
    """
    if not isinstance(secret, str) or not secret:
        # 不带 secret 进 error 消息
        raise ClusterConfigError(
            "auth secret must be non-empty str", code="CONFIG_ERROR"
        )
    return (AUTH_HEADER_NAME, secret)


__all__ = ["AUTH_HEADER_NAME", "build_auth_header"]
