"""出站 OAuth 端点的显式安全策略。
----
组件所有 HTTP 出口在请求前必须经过一个 `OAuthEndpointPolicy` 校验器。
没有 `None` 直通分支 —— 想要绕过校验的做法在框架层就被堵死。

提供两种开箱即用实现：

- `HttpsOnlyEndpointPolicy`（**默认**）：公网/默认网络用，仅允许
  `https://` 且拒绝带 userinfo / fragment 的 URI。
- `AllowHttpEndpointPolicy`（**显式 opt-in**）：单元测试或受信任内
  网部署用；`http://` 也允许，但同样拒绝 userinfo / fragment。

**为什么是 Protocol 不是 None 检查**：策略实例是组件依赖的一部分，
通过构造函数注入。把 `validate` 抽象成 Protocol 让单元测试可注入
Fakes，并把"必须校验"这件事写进类型契约。

English
--------
Explicit security policy for outbound OAuth endpoints.

Every HTTP egress the component makes must pass an
`OAuthEndpointPolicy` validator before the request is sent. There is
no `None`-passthrough: any attempt to bypass the check is blocked at
the framework level.

Two implementations ship in the box:

- `HttpsOnlyEndpointPolicy` (**default**): public / default network;
  only `https://` is allowed, and URIs with userinfo / fragment are
  rejected.
- `AllowHttpEndpointPolicy` (**explicit opt-in**): unit tests or
  trusted-internal-network deployments; `http://` is allowed, but
  userinfo / fragment are still rejected.

**Why a Protocol, not a `None` check:** the policy instance is a
component dependency, injected through the constructor. Abstracting
`validate` as a Protocol lets unit tests inject fakes and writes the
"must validate" contract into the type signature.
"""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlsplit

from .errors import OAuthConfigurationError


class OAuthEndpointPolicy(Protocol):
    """中文
    ----
    出站端点校验的端口协议。组件在发起请求前调用
    `validate(endpoint)`，不通过则抛 `OAuthConfigurationError`。

    English
    --------
    Validate an OAuth endpoint before the component makes a request.
    """

    def validate(self, endpoint: str) -> None:
        """中文
        ----
        不安全时抛 `OAuthConfigurationError`；安全时静默返回。

        English
        --------
        Raise a portable configuration error when an endpoint is
        unsafe.
        """


class HttpsOnlyEndpointPolicy:
    """中文
    ----
    公网默认策略：仅允许 `https://`，拒绝带 userinfo / fragment
    的 URI。

    English
    --------
    Public-network default that blocks credential-bearing and
    fragment URIs.
    """

    def validate(self, endpoint: str) -> None:
        parsed = urlsplit(endpoint)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise OAuthConfigurationError("OAuth endpoint must use HTTPS and include a host")
        if parsed.username or parsed.password or parsed.fragment:
            raise OAuthConfigurationError("OAuth endpoint must not contain credentials or a fragment")


class AllowHttpEndpointPolicy:
    """中文
    ----
    显式 opt-in 的测试 / 受信任内网策略：`http://` 也允许，但
    userinfo / fragment 仍被拒绝。

    English
    --------
    Explicit test or trusted-network policy; never the component
    default.
    """

    def validate(self, endpoint: str) -> None:
        parsed = urlsplit(endpoint)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise OAuthConfigurationError("OAuth endpoint must be an absolute HTTP(S) URI")
        if parsed.username or parsed.password or parsed.fragment:
            raise OAuthConfigurationError("OAuth endpoint must not contain credentials or a fragment")
