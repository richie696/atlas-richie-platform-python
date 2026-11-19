"""容器无关的 web SPI（对位 Java `cn.richie696.component.web.core.spi`）。

本包是跨容器决策的唯一编程面：请求上下文、决策事件、拦截器与拦截器链。
具体防护算法在上级包，guard → 拦截器的适配见 `atlas_richie.web_protection.interceptors`。

模块划分与 Java 侧对齐：
- `context` —— 上下文契约
- `decision` —— 决策事件与事件出口
- `interceptor` —— 拦截器与拦截器链契约
- `attributes` —— 跨拦截器标志的 attribute 名
- `support` —— 默认实现（上下文实现 + 链实现）
"""

from __future__ import annotations

from .attributes import (
    CLIENT_IP_ATTRIBUTE,
    DECISION_ATTRIBUTE,
    GATEWAY_BYPASS_ATTRIBUTE,
    GATEWAY_ID_ATTRIBUTE,
    LOGIN_KEY_ATTRIBUTE,
    LONG_LIVED_ATTRIBUTE,
)
from .context import WebRequestContext
from .decision import WebDecisionSink, WebFilterDecision
from .interceptor import WebInterceptor, WebInterceptorChain
from .support import (
    DefaultWebInterceptorChain,
    MutableWebRequestContext,
    MutableWebRequestContextBuilder,
)

__all__ = [
    "CLIENT_IP_ATTRIBUTE",
    "DECISION_ATTRIBUTE",
    "DefaultWebInterceptorChain",
    "GATEWAY_BYPASS_ATTRIBUTE",
    "GATEWAY_ID_ATTRIBUTE",
    "LOGIN_KEY_ATTRIBUTE",
    "LONG_LIVED_ATTRIBUTE",
    "MutableWebRequestContext",
    "MutableWebRequestContextBuilder",
    "WebDecisionSink",
    "WebFilterDecision",
    "WebInterceptor",
    "WebInterceptorChain",
    "WebRequestContext",
]
