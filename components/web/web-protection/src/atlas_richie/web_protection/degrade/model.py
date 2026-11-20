"""降级契约（对位 Java `web.core.degrade` 的 `Trigger` / `DegradeStrategy` / `DegradeResult`）。

纯契约，零依赖：策略实现方只需要懂「触发条件 → 命中判定 → 响应体生成」三件事。

`4.7.1 `Trigger` 是**非交互性**触发条件：它只表示「本轮可能触发降级」，是否真降级
由 `DegradeStrategy.matches()` 决定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable


class Trigger(str, Enum):
    """降级触发条件（对位 Java `Trigger` 枚举）。

    - `EXCEPTION`：业务执行抛异常
    - `HIGH_LATENCY`：执行耗时超阈值（由 `degrade.latencyMs` 判定）
    - `CUSTOM`：业务自定义触发（ctx attribute `degrade.manual=true`）
    """

    EXCEPTION = "EXCEPTION"
    HIGH_LATENCY = "HIGH_LATENCY"
    CUSTOM = "CUSTOM"

    @property
    def reason(self) -> str:
        """占位符 `{reason}` 的取值：枚举名小写，下划线换连字符。

        对位 Java `Trigger.name().toLowerCase().replace('_', '-')`。
        """
        return self.value.lower().replace("_", "-")


@dataclass(frozen=True, slots=True)
class DegradeResult:
    """降级响应结果（对位 Java `DegradeResult` record）。

    不可变；承载降级时回写给客户端的：HTTP 状态码 / 响应 body / 附加响应头 /
    策略名。

    `4.7.2 body 序列化约定：业务方在策略里直接生成字符串，本组件不强制任何
    JSON 库——但校验规则与 Java 一致（状态码必须在 HTTP 区间，body 与策略名
    不可为空）。
    """

    status: int
    body: str
    strategy_name: str
    headers: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.body is None:
            raise ValueError("body must not be None")
        if self.strategy_name is None:
            raise ValueError("strategy_name must not be None")
        if self.status < 100 or self.status > 599:
            raise ValueError(f"status out of HTTP range: {self.status}")
        if self.headers is None:
            object.__setattr__(self, "headers", {})

    @classmethod
    def of(cls, status: int, body: str, strategy_name: str) -> "DegradeResult":
        """无附加 header 的构造（对位 Java `DegradeResult.of(status, body, strategyName)`）。"""
        return cls(status=status, body=body, strategy_name=strategy_name)

    @classmethod
    def of_with_headers(
        cls,
        status: int,
        body: str,
        strategy_name: str,
        headers: Mapping[str, str] | None = None,
    ) -> "DegradeResult":
        """带 header 的构造（对位 Java 四参 `of`）。"""
        return cls(status=status, body=body, strategy_name=strategy_name, headers=headers)


@runtime_checkable
class DegradeStrategy(Protocol):
    """降级策略 SPI（对位 Java `DegradeStrategy`）。

    `4.7.3 实现应是**无状态**且线程安全的对象（注册表单例持有）。
    """

    def name(self) -> str:
        """策略名（注册表内唯一），建议小写中划线命名（例：`default-stub`）。"""
        ...

    def triggers(self) -> frozenset[Trigger]:
        """本策略响应哪些触发条件（空集合等价于「永不触发」）。"""
        ...

    def order(self) -> int:
        """顺序值（越小越靠前）。

        建议：`MIN_VALUE/2` 全局兜底、`0` 默认、`MAX_VALUE/2` 仅作诊断。
        """
        ...

    def matches(self, trigger: Trigger | None) -> bool:
        """是否匹配本轮触发（trigger 为 None 表示「未触发任何条件」）。"""
        ...

    def build(self, trigger: Trigger, ctx: Mapping[str, Any]) -> DegradeResult:
        """生成降级响应。

        `ctx` 的 key 可能包含：`path` / `exception` / `exceptionType` /
        `exceptionMessage` / `latencyMs` / `trigger`。
        """
        ...


__all__ = ["DegradeResult", "DegradeStrategy", "Trigger"]
