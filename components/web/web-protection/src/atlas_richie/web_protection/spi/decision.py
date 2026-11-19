"""过滤决策事件载荷（对位 Java `WebFilterDecision`）。

Java 侧是「拦截器做出 deny / short-circuit 决策时发布的事件」，供下游
HookBus 订阅并通知业务方。

关键非琐碎细节：
- 多个 deny 同时发生时，以**先触发者**为准（拦截器链短路天然保证）。
- 被拒请求不计 success metric（对位 Java）。
- 事件既写进 ctx attribute（唯一交棒通道），也可投递到 `WebDecisionSink`；
  二选一或同时使用都可以。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class WebFilterDecision:
    """决策事件载荷；四字段与 Java `WebFilterDecision` 逐字对应。"""

    interceptor: str
    key: str | None
    status: int
    reason: str

    @property
    def is_deny(self) -> bool:
        """是否为 deny 决策（4xx / 5xx）。"""
        return self.status >= 400

    @classmethod
    def rate_limit_deny(
        cls, interceptor: str, key: str | None, status: int
    ) -> "WebFilterDecision":
        """限流拒绝事件的便捷工厂。"""
        return cls(interceptor, key, status, "rate_limit.exceeded")

    @classmethod
    def circuit_breaker_deny(
        cls, interceptor: str, key: str | None, status: int
    ) -> "WebFilterDecision":
        """熔断拒绝事件的便捷工厂。"""
        return cls(interceptor, key, status, "circuit_breaker.open")


@runtime_checkable
class WebDecisionSink(Protocol):
    """决策事件出口（对位 Java `HookBus`）。"""

    def publish(self, decision: WebFilterDecision) -> None:
        """投递一个决策事件；实现方需自行保证不抛异常中断请求。"""
        ...


__all__ = ["WebDecisionSink", "WebFilterDecision"]
