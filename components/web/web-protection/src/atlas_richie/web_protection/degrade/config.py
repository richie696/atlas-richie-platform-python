"""降级配置契约（对位 Java `DegradeProperties` 及其 `Fallback` / `RouteFallback`）。

Java 侧是 Spring `@ConfigurationProperties`（yml 绑定）；Python 侧改为**普通
dataclass**——配置来源（yml / Nacos / 环境变量）由业务方自己决定，组件只提供
数据形状。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class Fallback:
    """全局兜底响应（对位 Java `DegradeProperties.Fallback`）。"""

    status: int = 503
    code: str = "DEGRADED"
    msg: str = "服务降级中 ({reason})"
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RouteFallback:
    """按接口粒度的降级响应（对位 Java `DegradeProperties.RouteFallback`）。

    `pattern` 是 Ant 风格路径（例：`/api/v1/orders/**`）。

    `4.7.4 Java 的 `fallbackBean` / `fallbackMethod`（反射调 Spring Bean 生成
    响应体）**未移植**——Python 侧没有等价的「按 bean 名反射」惯例，需要动态响应
    体时直接注册一个 `DegradeStrategy` 即可。
    """

    pattern: str
    status: int = 503
    code: str = "DEGRADED"
    msg: str = "服务降级中 ({reason})"
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DegradeConfig:
    """降级配置（对位 Java `DegradeProperties`）。

    `4.7.5 Java 的 `enabled` 开关在 Python 侧**不存在**——是否启用由「是否把
    `DegradeEvaluator` 交给适配层」决定，不需要额外布尔位。
    """

    fallback: Fallback = field(default_factory=Fallback)
    routes: Mapping[str, RouteFallback] = field(default_factory=dict)
    route_rules: tuple[RouteFallback, ...] = ()


__all__ = ["DegradeConfig", "Fallback", "RouteFallback"]
