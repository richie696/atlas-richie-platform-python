"""Sentinel FlowRule(M2.1)。

中文
----
``FlowRule`` 是 Sentinel 最常用的规则:在窗口期内 QPS / 并发 / 等待
超时超阈值时拒绝。4 种 ``FlowScope`` 决定计数 / 限流的统计对象:

- ``DIRECT`` — 仅当前 Resource
- ``ORIGIN`` — 按 origin(调用方)分桶(``scope_reference`` 必填)
- ``ASSOCIATED_RESOURCE`` — 关联另一个 Resource(``scope_reference`` 必填)
- ``CALL_PATH`` — 按调用链分桶(M2.x 基础版只支持单跳)

设计要点:

- ``FlowGrade`` 决定计数量:``QPS``(时间窗内请求数)或 ``CONCURRENCY``
  (瞬时并发,无需时间窗)
- ``FlowBehavior`` 决定超限处理:``REJECT``(直接抛 ``FlowBlocked``)
  或 ``WARM_UP``(冷启动;CONCURRENCY 不接受)
- ``FlowControl`` 决定流量整形:``REJECT`` / ``WARM_UP`` / ``QUEUE``
  (排队;``max_queueing_time`` 必填)
- **frozen + slots**:构造时一次性校验,运行期不能改;**所有**字段
  必填,可选字段用 ``Optional`` 显式标注

English
--------
Sentinel FlowRule (M2.1).

``FlowRule`` is Sentinel's most-used rule: rejects when QPS /
concurrency / wait timeout exceed the threshold in the window. 4
``FlowScope``s decide what to count / limit:

- ``DIRECT`` — current Resource only.
- ``ORIGIN`` — bucket by origin (caller); ``scope_reference`` required.
- ``ASSOCIATED_RESOURCE`` — link to another Resource; ``scope_reference``
  required.
- ``CALL_PATH`` — bucket by call path (M2.x basic = single hop only).

Design points:

- ``FlowGrade`` — ``QPS`` (windowed count) or ``CONCURRENCY`` (in-flight).
- ``FlowBehavior`` — ``REJECT`` (raise ``FlowBlocked``) or ``WARM_UP``
  (cold start; CONCURRENCY not accepted).
- ``FlowControl`` — ``REJECT`` / ``WARM_UP`` / ``QUEUE`` (``max_queueing_time``
  required for QUEUE).
- **frozen + slots** — single-pass construction validation; immutable
  at runtime; optional fields explicitly ``Optional``."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Optional

from ..errors import SentinelConfigurationError
from .selector import ResourceSelector


class FlowGrade(StrEnum):
    """中文
    ----
    限流维度:``QPS`` 或 ``CONCURRENCY``。

    English
    --------
    Limit dimension: ``QPS`` or ``CONCURRENCY``.
    """

    QPS = "qps"
    CONCURRENCY = "concurrency"


class FlowBehavior(StrEnum):
    """中文
    ----
    超限行为:``REJECT``(默认,直接拒绝)或 ``WARM_UP``(冷启动,
    让系统从低 QPS 平滑爬升到阈值;``CONCURRENCY`` 模式下不合法)。

    English
    --------
    Overflow behavior: ``REJECT`` (default, direct reject) or
    ``WARM_UP`` (cold start; ramps from low QPS to threshold smoothly;
    not allowed with ``CONCURRENCY``).
    """

    REJECT = "reject"
    WARM_UP = "warm_up"


class FlowControl(StrEnum):
    """中文
    ----
    流量整形策略:``REJECT``(默认,直接拒)/ ``WARM_UP``(冷启动)/
    ``QUEUE``(等一段时间;``max_queueing_time`` 必填)。

    English
    --------
    Flow control strategy: ``REJECT`` (default) / ``WARM_UP`` (cold
    start) / ``QUEUE`` (wait up to ``max_queueing_time``).
    """

    REJECT = "reject"
    WARM_UP = "warm_up"
    QUEUE = "queue"


class FlowScope(StrEnum):
    """中文
    ----
    统计 / 限流对象。``ORIGIN`` / ``ASSOCIATED_RESOURCE`` /
    ``CALL_PATH`` 必须有 ``scope_reference``。

    English
    --------
    Counting / limiting target. ``ORIGIN`` / ``ASSOCIATED_RESOURCE`` /
    ``CALL_PATH`` require ``scope_reference``.
    """

    DIRECT = "direct"
    ORIGIN = "origin"
    ASSOCIATED_RESOURCE = "associated_resource"
    CALL_PATH = "call_path"


@dataclass(frozen=True, slots=True)
class FlowRule:
    """中文
    ----
    不可变 FlowRule。

    字段:

    - ``rule_id`` — 唯一 id
    - ``selector`` — 资源选择器
    - ``priority`` — 数字大 = 优先(同 scope 内)
    - ``grade`` — QPS 或 CONCURRENCY
    - ``threshold`` — 阈值(> 0,QPS 是 req/s,CONCURRENCY 是 in-flight)
    - ``behavior`` — 超限行为
    - ``control`` — 流量整形
    - ``scope`` — 统计对象
    - ``scope_reference`` — ORIGIN/ASSOCIATED_RESOURCE/CALL_PATH 时必填
      (origin 字符串 / 关联 Resource name / call_path 字符串)
    - ``max_queueing_time_ms`` — QUEUE 时必填(>= 0)
    - ``warm_up_period_sec`` — WARM_UP 时必填(> 0)

    构造校验(违反抛 ``SentinelConfigurationError``):

    - threshold > 0
    - WARM_UP 必须配 warm_up_period_sec
    - QUEUE 必须配 max_queueing_time_ms >= 0
    - CONCURRENCY 不接受 WARM_UP

    English
    --------
    Immutable FlowRule.

    Fields:

    - ``rule_id`` — unique id.
    - ``selector`` — resource selector.
    - ``priority`` — larger = wins (within scope).
    - ``grade`` — QPS or CONCURRENCY.
    - ``threshold`` — threshold (QPS = req/s, CONCURRENCY = in-flight).
    - ``behavior`` — overflow behavior.
    - ``control`` — flow control.
    - ``scope`` — counting target.
    - ``scope_reference`` — required for ORIGIN/ASSOCIATED_RESOURCE/CALL_PATH.
    - ``max_queueing_time_ms`` — required for QUEUE (>= 0).
    - ``warm_up_period_sec`` — required for WARM_UP (> 0).

    Construction validation (violations raise
    ``SentinelConfigurationError``):

    - threshold > 0.
    - WARM_UP requires warm_up_period_sec.
    - QUEUE requires max_queueing_time_ms >= 0.
    - CONCURRENCY rejects WARM_UP.
    """

    rule_id: str
    selector: ResourceSelector
    priority: int
    grade: FlowGrade
    threshold: float
    behavior: FlowBehavior
    control: FlowControl
    scope: FlowScope = FlowScope.DIRECT
    scope_reference: Optional[str] = None
    max_queueing_time_ms: int = 0
    warm_up_period_sec: float = 0.0

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.rule_id:
            errors.append("rule_id must be non-empty")
        if self.threshold <= 0:
            errors.append(f"threshold must be > 0 (got {self.threshold})")
        if self.control is FlowControl.WARM_UP and self.warm_up_period_sec <= 0:
            errors.append(
                f"WARM_UP requires warm_up_period_sec > 0 "
                f"(got {self.warm_up_period_sec})"
            )
        if self.control is FlowControl.QUEUE and self.max_queueing_time_ms < 0:
            errors.append(
                f"QUEUE requires max_queueing_time_ms >= 0 "
                f"(got {self.max_queueing_time_ms})"
            )
        if self.grade is FlowGrade.CONCURRENCY and self.behavior is FlowBehavior.WARM_UP:
            errors.append("CONCURRENCY does not accept WARM_UP")
        if self.scope in (FlowScope.ORIGIN, FlowScope.ASSOCIATED_RESOURCE, FlowScope.CALL_PATH):
            if not self.scope_reference:
                errors.append(
                    f"FlowScope.{self.scope.value} requires scope_reference"
                )
        if errors:
            raise SentinelConfigurationError(
                f"FlowRule {self.rule_id!r} validation failed: " + "; ".join(errors),
                field=f"flow.{self.rule_id}",
                reason="validation_failed",
                value=errors,
            )


__all__ = [
    "FlowGrade",
    "FlowBehavior",
    "FlowControl",
    "FlowScope",
    "FlowRule",
]
