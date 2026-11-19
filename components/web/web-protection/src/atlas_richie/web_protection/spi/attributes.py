"""决策事件与跨拦截器标志的 attribute 名（对位 Java 同名常量）。

Java 侧这些常量分散在各个拦截器里，本模块集中定义，取值与 Java 完全一致，
便于跨语言排查同一个请求上下文。

- 决策事件：Java 每个拦截器各有一个专属名字，彼此不冲突。Python 侧刻意
  收敛为一个统一 attribute —— BACKLOG 明确要求「统一决策事件」，且 Python
  尚无 HookBus，attribute 是唯一的交棒通道。需要区分来源时读载荷里的
  `interceptor` 字段即可。
- 网关身份：与 Java 逐字一致。Java 侧网关身份不可关闭（硬编码），Python
  侧保留可配置（默认头名与 Java 契约一致）。
- 长连接标志：与 Java 逐字一致。
- Python 专有：Java 的 ctx 没有客户端 IP 与登录 key 两个概念（都由适配层
  算），故单列。
"""

from __future__ import annotations

# 决策事件：deny 时写入 ctx 的载荷（`WebFilterDecision`）。
DECISION_ATTRIBUTE = "platform.web.filter-decision"

# 网关身份标志（写入方见网关拦截器，读取方见签名拦截器）。
GATEWAY_BYPASS_ATTRIBUTE = "platform.web.gateway-bypass"

# 网关实例 ID（写入方见网关拦截器）。
GATEWAY_ID_ATTRIBUTE = "platform.web.gateway-id"

# 长连接路径标志（写入方见长连接拦截器，读取方见各请求级拦截器）。
LONG_LIVED_ATTRIBUTE = "platform.web.long-lived"

# 客户端 IP（适配层写入，限流拦截器读取）。
CLIENT_IP_ATTRIBUTE = "platform.web.client-ip"

# 登录跟踪 key（适配层写入，登录锁定拦截器读取）。
LOGIN_KEY_ATTRIBUTE = "platform.web.login-key"

__all__ = [
    "CLIENT_IP_ATTRIBUTE",
    "DECISION_ATTRIBUTE",
    "GATEWAY_BYPASS_ATTRIBUTE",
    "GATEWAY_ID_ATTRIBUTE",
    "LOGIN_KEY_ATTRIBUTE",
    "LONG_LIVED_ATTRIBUTE",
]
