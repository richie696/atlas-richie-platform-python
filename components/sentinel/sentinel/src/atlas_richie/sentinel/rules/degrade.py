"""Sentinel DegradeRule(M2.2)。

中文
----
``DegradeRule`` 通过降级策略(熔断 + 异常 / 慢调用计数)保护 Resource;
M2.2 复用 M0 阶段的 ``primitives.CircuitBreaker`` 状态机,**不**自己重
实现。

4 种 ``DegradeStrategy``:

- ``SLOW_CALL_RATIO`` — 慢调用比例 > ``slow_call_ratio_threshold`` +
  ``slow_call_threshold_ms`` 才打开
- ``ERROR_RATIO`` — 异常比例 > ``error_ratio_threshold``(0..1)
- ``ERROR_COUNT`` — 异常绝对值 >= ``error_count_threshold``
- ``SLOW_CALL_COUNT`` — 慢调用绝对值 >= ``slow_call_count_threshold``

设计要点:

- ``minimum_request_count`` 不足时不打开(防止冷启动假阳性)
- HALF_OPEN 探测成功数 = ``half_open_probe_count`` 才恢复(默认 1)
- 强制 open / close / reset 只通过管理 API(M2.2 占位,DegradeSlot
  暴露 ``force_open`` / ``force_close`` / ``force_reset`` 同步方法)
- ``slow_call_threshold_ms`` 单调时间窗内单次响应 > 该值视为慢

English
--------
Sentinel DegradeRule (M2.2).

``DegradeRule`` protects a Resource via degrade strategies (circuit
breaking + error / slow call counting). M2.2 reuses M0's
``primitives.CircuitBreaker`` state machine; **does not** reimplement
it.

4 ``DegradeStrategy``s:

- ``SLOW_CALL_RATIO`` — slow-call ratio > ``slow_call_ratio_threshold``
  + ``slow_call_threshold_ms`` triggers.
- ``ERROR_RATIO`` — error ratio > ``error_ratio_threshold`` (0..1).
- ``ERROR_COUNT`` — error count >= ``error_count_threshold``.
- ``SLOW_CALL_COUNT`` — slow-call count >= ``slow_call_count_threshold``.

Design points:

- ``minimum_request_count`` — gating; under this, breaker does not open.
- HALF_OPEN probe success = ``half_open_probe_count`` to close
  (default 1).
- Force open / close / reset only via admin API (M2.2 placeholder;
  DegradeSlot exposes ``force_open`` / ``force_close`` / ``force_reset``
  sync methods).
- ``slow_call_threshold_ms`` — single response time > this in window =
  slow call."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..errors import SentinelConfigurationError
from ..primitives.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)
from .selector import ResourceSelector


class DegradeStrategy(StrEnum):
    """中文
    ----
    降级策略。

    English
    --------
    Degrade strategy.
    """

    SLOW_CALL_RATIO = "slow_call_ratio"
    ERROR_RATIO = "error_ratio"
    ERROR_COUNT = "error_count"
    SLOW_CALL_COUNT = "slow_call_count"


@dataclass(frozen=True, slots=True)
class DegradeRule:
    """中文
    ----
    不可变 DegradeRule。

    字段:

    - ``rule_id``, ``selector``, ``priority`` — 与 FlowRule 共享
    - ``strategy`` — 4 种降级策略
    - ``slow_call_threshold_ms`` — SLOW_CALL_RATIO / SLOW_CALL_COUNT 必填
    - ``slow_call_ratio_threshold`` — SLOW_CALL_RATIO 必填,0..1
    - ``error_count_threshold`` — ERROR_COUNT 必填
    - ``error_ratio_threshold`` — ERROR_RATIO 必填,0..1
    - ``minimum_request_count`` — 触发前的最小请求数(默认 5)
    - ``stat_window_ms`` — 统计窗口(默认 1000ms)
    - ``recovery_timeout_ms`` — OPEN → HALF_OPEN 的等待时间
    - ``half_open_probe_count`` — HALF_OPEN 探测成功数才恢复(默认 1)

    构造校验:对应 strategy 必填字段缺失 / 非法范围 → 抛
    ``SentinelConfigurationError``。

    English
    --------
    Immutable DegradeRule.

    Fields:

    - ``rule_id``, ``selector``, ``priority`` — shared with FlowRule.
    - ``strategy`` — 4 strategies.
    - ``slow_call_threshold_ms`` — required for SLOW_CALL_RATIO /
      SLOW_CALL_COUNT.
    - ``slow_call_ratio_threshold`` — required for SLOW_CALL_RATIO,
      0..1.
    - ``error_count_threshold`` — required for ERROR_COUNT.
    - ``error_ratio_threshold`` — required for ERROR_RATIO, 0..1.
    - ``minimum_request_count`` — gating; default 5.
    - ``stat_window_ms`` — stat window; default 1000ms.
    - ``recovery_timeout_ms`` — OPEN → HALF_OPEN wait.
    - ``half_open_probe_count`` — HALF_OPEN successes to close;
      default 1.

    Construction validation: missing required fields for the chosen
    strategy or out-of-range values raise ``SentinelConfigurationError``.
    """

    rule_id: str
    selector: ResourceSelector
    priority: int
    strategy: DegradeStrategy
    slow_call_threshold_ms: int = 0
    slow_call_ratio_threshold: float = 0.0
    error_count_threshold: int = 0
    error_ratio_threshold: float = 0.0
    minimum_request_count: int = 5
    stat_window_ms: int = 1000
    recovery_timeout_ms: int = 5000
    half_open_probe_count: int = 1

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.rule_id:
            errors.append("rule_id must be non-empty")
        if self.minimum_request_count < 0:
            errors.append(
                f"minimum_request_count must be >= 0 (got {self.minimum_request_count})"
            )
        if self.stat_window_ms <= 0:
            errors.append(f"stat_window_ms must be > 0 (got {self.stat_window_ms})")
        if self.recovery_timeout_ms <= 0:
            errors.append(
                f"recovery_timeout_ms must be > 0 (got {self.recovery_timeout_ms})"
            )
        if self.half_open_probe_count < 1:
            errors.append(
                f"half_open_probe_count must be >= 1 (got {self.half_open_probe_count})"
            )
        if self.strategy is DegradeStrategy.SLOW_CALL_RATIO:
            if self.slow_call_threshold_ms <= 0:
                errors.append("SLOW_CALL_RATIO requires slow_call_threshold_ms > 0")
            if not 0.0 <= self.slow_call_ratio_threshold <= 1.0:
                errors.append(
                    f"slow_call_ratio_threshold must be in [0,1] "
                    f"(got {self.slow_call_ratio_threshold})"
                )
        elif self.strategy is DegradeStrategy.ERROR_RATIO:
            if not 0.0 <= self.error_ratio_threshold <= 1.0:
                errors.append(
                    f"error_ratio_threshold must be in [0,1] "
                    f"(got {self.error_ratio_threshold})"
                )
        elif self.strategy is DegradeStrategy.ERROR_COUNT:
            if self.error_count_threshold <= 0:
                errors.append("ERROR_COUNT requires error_count_threshold > 0")
        elif self.strategy is DegradeStrategy.SLOW_CALL_COUNT:
            if self.slow_call_threshold_ms <= 0:
                errors.append("SLOW_CALL_COUNT requires slow_call_threshold_ms > 0")
            if self.error_count_threshold <= 0:  # reuse as slow_call_count_threshold
                errors.append("SLOW_CALL_COUNT requires slow_call_count_threshold > 0")
        if errors:
            raise SentinelConfigurationError(
                f"DegradeRule {self.rule_id!r} validation failed: " + "; ".join(errors),
                field=f"degrade.{self.rule_id}",
                reason="validation_failed",
                value=errors,
            )

    def to_circuit_breaker_config(self) -> CircuitBreakerConfig:
        """中文
        ----
        映射到 M0 ``CircuitBreakerConfig``;M2.2 用最贴近的现有参数:

        - failure_threshold = error_count_threshold
        - failure_rate_threshold = error_ratio_threshold
        - sliding_window_size = max(1, stat_window_ms // 100)
        - open_duration = recovery_timeout_ms / 1000
        - minimum_calls = minimum_request_count
        - half_open_max_calls = half_open_probe_count

        慢调用 + 慢比例 通过 ``on_call_recorded`` 钩子另算
        (M2.2 简化:直接用异常率)。

        English
        --------
        Map to M0 ``CircuitBreakerConfig``; M2.2 uses the closest
        existing parameters:

        - failure_threshold = error_count_threshold
        - failure_rate_threshold = error_ratio_threshold
        - sliding_window_size = max(1, stat_window_ms // 100)
        - open_duration = recovery_timeout_ms / 1000
        - minimum_calls = minimum_request_count
        - half_open_max_calls = half_open_probe_count

        Slow-call + slow-ratio are tracked separately via
        ``on_call_recorded`` hook (M2.2 simplification: use error
        rate directly).
        """
        return CircuitBreakerConfig(
            failure_threshold=max(1, self.error_count_threshold),
            failure_rate_threshold=self.error_ratio_threshold,
            sliding_window_size=max(1, self.stat_window_ms // 100),
            open_duration=max(0.001, self.recovery_timeout_ms / 1000.0),
            minimum_calls=max(1, self.minimum_request_count),
            half_open_max_calls=max(1, self.half_open_probe_count),
        )


__all__ = [
    "DegradeStrategy",
    "DegradeRule",
    "CircuitBreaker",  # re-export for downstream
    "CircuitBreakerConfig",
    "CircuitState",
]
