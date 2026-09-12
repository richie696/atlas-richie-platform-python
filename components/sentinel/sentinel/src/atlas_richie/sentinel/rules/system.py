"""Sentinel SystemRule(M2.4)。

中文
----
``SystemRule`` 是进程级自适应保护,触发整服务 503。它**不**通过
``ResourceSelector`` 匹配资源,而是基于全局阈值(CPU/load/event-loop
lag/in-flight QPS)。Engine 在入口级(Slot 0 / Order 0 或最高
优先级)直接评估;M2.4 把 Order 定为 400(在 Authority 之后、Flow
之前)。

设计要点:

- **不继承 ResourceRule**(M0 DESIGN ADR-SEN-015 明确):SystemRule
  是入口级规则,**不**伪装成 ResourceRule
- **2 种 strategy**:
  - ``DIRECT`` — 任一硬阈值触发
  - ``ADAPTIVE_CAPACITY`` — Little's Law:``estimated_capacity =
    max(1, completed_qps * min_stable_rt)`` 估算可承受量
- **资源类型 filter** (PLANNING §M2.4 Exit Criteria):只对 ``INBOUND``
  资源生效;``INTERNAL`` / ``OUTBOUND`` 不触发 SystemSlot
- **阈值可关**:``max_cpu_usage`` / ``max_load`` / ``max_event_loop_lag_ms``
  / ``max_in_flight_qps`` 任一为 ``None`` 表示不检查该指标
- **metric sampler 失败 → fail-safe**:见 ``SystemMetricSampler`` Port

English
--------
Sentinel SystemRule (M2.4).

``SystemRule`` is process-level adaptive protection; on trigger the
whole service returns 503. It does **not** match via
``ResourceSelector``; instead it uses global thresholds (CPU/load/
event-loop-lag/in-flight QPS). The Engine evaluates at the entry
level; M2.4 sets Order to 400 (after Authority, before Flow).

Design points:

- **Does not inherit ResourceRule** (M0 DESIGN ADR-SEN-015): SystemRule
  is entry-level, **not** disguised as ResourceRule.
- **2 strategies**:
  - ``DIRECT`` — any hard threshold triggers.
  - ``ADAPTIVE_CAPACITY`` — Little's Law: ``estimated_capacity =
    max(1, completed_qps * min_stable_rt)``.
- **Resource-kind filter** (PLANNING §M2.4 Exit Criteria): only
  fires on ``INBOUND`` resources; ``INTERNAL`` / ``OUTBOUND`` skip.
- **Thresholds can be disabled**: any of ``max_cpu_usage`` /
  ``max_load`` / ``max_event_loop_lag_ms`` / ``max_in_flight_qps``
  = ``None`` skips that metric.
- **metric sampler fail-safe**: see ``SystemMetricSampler`` Port."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from ..errors import SentinelConfigurationError


class SystemStrategy(StrEnum):
    """中文
    ----
    SystemRule 触发策略。

    English
    --------
    SystemRule trigger strategy.
    """

    DIRECT = "direct"                       # 任一硬阈值触发
    ADAPTIVE_CAPACITY = "adaptive_capacity" # Little's Law 估算可承受量


@dataclass(frozen=True, slots=True)
class SystemRule:
    """中文
    ----
    不可变 SystemRule(**不**继承 ResourceRule,ADR-SEN-015)。

    字段:

    - ``rule_id`` — 唯一 id
    - ``priority`` — 同 strategy 内优先级
    - ``strategy`` — DIRECT / ADAPTIVE_CAPACITY
    - ``max_cpu_usage`` — CPU 占用 0..1(DIRECT;None = 不查)
    - ``max_load`` — 1 分钟 load(DIRECT;None = 不查)
    - ``max_event_loop_lag_ms`` — asyncio event loop 滞后 ms(DIRECT)
    - ``max_in_flight_qps`` — 全局在飞 QPS(DIRECT;None = 不查)
    - ``min_stable_rt_ms`` — ADAPTIVE_CAPACITY 公式里的"最小稳定 RT"
    - ``max_concurrent_adaptive`` — ADAPTIVE_CAPACITY 公式里
      ``estimated_capacity`` 的上限(默认 1000)

    构造校验(违反抛 ``SentinelConfigurationError``):

    - rule_id 非空
    - DIRECT: 至少一个 max_* 非 None
    - ADAPTIVE_CAPACITY: min_stable_rt_ms > 0

    English
    --------
    Immutable SystemRule (**not** subclass of ResourceRule,
    ADR-SEN-015).

    Fields:

    - ``rule_id`` — unique id.
    - ``priority`` — priority within strategy.
    - ``strategy`` — DIRECT / ADAPTIVE_CAPACITY.
    - ``max_cpu_usage`` — CPU 0..1 (DIRECT; ``None`` = skip).
    - ``max_load`` — 1-min load (DIRECT; ``None`` = skip).
    - ``max_event_loop_lag_ms`` — asyncio event loop lag ms (DIRECT).
    - ``max_in_flight_qps`` — global in-flight QPS (DIRECT;
      ``None`` = skip).
    - ``min_stable_rt_ms`` — ADAPTIVE_CAPACITY formula's "min stable
      RT".
    - ``max_concurrent_adaptive`` — ADAPTIVE_CAPACITY
      ``estimated_capacity`` ceiling (default 1000).

    Construction validation (violations raise
    ``SentinelConfigurationError``):

    - rule_id non-empty.
    - DIRECT: at least one max_* non-None.
    - ADAPTIVE_CAPACITY: min_stable_rt_ms > 0.
    """

    rule_id: str
    priority: int
    strategy: SystemStrategy
    max_cpu_usage: Optional[float] = None
    max_load: Optional[float] = None
    max_event_loop_lag_ms: Optional[float] = None
    max_in_flight_qps: Optional[float] = None
    min_stable_rt_ms: float = 1.0
    max_concurrent_adaptive: int = 1000

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.rule_id:
            errors.append("rule_id must be non-empty")
        if self.strategy is SystemStrategy.DIRECT:
            if all(
                v is None
                for v in (
                    self.max_cpu_usage,
                    self.max_load,
                    self.max_event_loop_lag_ms,
                    self.max_in_flight_qps,
                )
            ):
                errors.append("DIRECT strategy requires at least one max_* threshold")
            for name, v in (
                ("max_cpu_usage", self.max_cpu_usage),
                ("max_load", self.max_load),
                ("max_event_loop_lag_ms", self.max_event_loop_lag_ms),
                ("max_in_flight_qps", self.max_in_flight_qps),
            ):
                if v is not None and v < 0:
                    errors.append(f"{name} must be >= 0 (got {v})")
        elif self.strategy is SystemStrategy.ADAPTIVE_CAPACITY:
            if self.min_stable_rt_ms <= 0:
                errors.append(
                    f"ADAPTIVE_CAPACITY requires min_stable_rt_ms > 0 "
                    f"(got {self.min_stable_rt_ms})"
                )
        if self.max_concurrent_adaptive < 1:
            errors.append(
                f"max_concurrent_adaptive must be >= 1 (got {self.max_concurrent_adaptive})"
            )
        if errors:
            raise SentinelConfigurationError(
                f"SystemRule {self.rule_id!r} validation failed: " + "; ".join(errors),
                field=f"system.{self.rule_id}",
                reason="validation_failed",
                value=errors,
            )


__all__ = ["SystemStrategy", "SystemRule"]
