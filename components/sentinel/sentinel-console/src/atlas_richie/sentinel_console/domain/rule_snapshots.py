"""Immutable, typed authoritative rule snapshots and Sentinel rule values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import TypeAlias

from .rule_bindings import RuleBinding, RuleKind
from .utc_time import is_wire_utc_millisecond_instant
from .wire_numbers import is_safe_json_integer, is_safe_json_number
from .wire_strings import has_non_blank_wire_content, is_bounded_wire_text

_MAX_IDENTIFIER_UNITS = 200
_MAX_RESOURCE_UNITS = 512
_MAX_PARAM_ITEMS = 100
_MAX_RULES = 1_000


class FlowGrade(IntEnum):
    """Native Sentinel flow threshold grade codes."""

    THREAD = 0
    QPS = 1


class FlowStrategy(IntEnum):
    """Native Sentinel flow strategy codes."""

    DIRECT = 0
    RELATE = 1
    CHAIN = 2


class FlowControlBehavior(IntEnum):
    """Native Sentinel flow control behavior codes."""

    REJECT = 0
    WARM_UP = 1
    QUEUEING = 2


class DegradeGrade(IntEnum):
    """Native Sentinel circuit-breaker grade codes."""

    SLOW_REQUEST_RATIO = 0
    ERROR_RATIO = 1
    ERROR_COUNT = 2


class AuthorityStrategy(IntEnum):
    """Native Sentinel authority strategy codes."""

    WHITE_LIST = 0
    BLACK_LIST = 1


class ClusterThresholdType(IntEnum):
    """Native Sentinel cluster threshold distribution codes."""

    AVERAGE_LOCAL = 0
    GLOBAL = 1


class DisabledSystemThreshold(IntEnum):
    """Sentinel's native marker for a disabled system threshold."""

    DISABLED = -1


def _text(value: str, maximum: int, *, non_empty: bool = False) -> bool:
    return (
        is_bounded_wire_text(value, maximum)
        and (not non_empty or has_non_blank_wire_content(value))
    )


def _finite(value: int | float) -> bool:
    return is_safe_json_number(value)


def _positive(value: int | float) -> bool:
    return _finite(value) and value > 0


def _positive_integer(value: int | float) -> bool:
    return is_safe_json_integer(value) and value > 0


def _non_negative(value: int | float) -> bool:
    return _finite(value) and value >= 0


def _non_negative_integer(value: int | float) -> bool:
    return is_safe_json_integer(value) and value >= 0


@dataclass(frozen=True, slots=True)
class ClusterRuleConfig:
    """Cluster limiter fields for one Sentinel flow rule."""

    threshold_type: ClusterThresholdType
    fallback_to_local_when_fail: bool
    sample_count: int
    window_interval_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.threshold_type, ClusterThresholdType):
            raise ValueError("cluster threshold type is unsupported")
        if type(self.fallback_to_local_when_fail) is not bool:
            raise ValueError("cluster fallback flag must be boolean")
        if not _positive_integer(self.sample_count) or not _positive_integer(
            self.window_interval_ms
        ):
            raise ValueError("cluster window values must be positive integers")
        if (
            self.window_interval_ms < self.sample_count
            or self.window_interval_ms % self.sample_count != 0
        ):
            raise ValueError("cluster window must divide into whole samples")


@dataclass(frozen=True, slots=True)
class FlowRuleValue:
    """Validated native fields for one flow-control rule."""

    resource: str
    limit_app: str
    grade: FlowGrade
    count: int | float
    strategy: FlowStrategy
    control_behavior: FlowControlBehavior
    cluster_mode: bool
    ref_resource: str | None = None
    warm_up_period_sec: int | None = None
    max_queueing_time_ms: int | None = None
    cluster_config: ClusterRuleConfig | None = None

    @property
    def kind(self) -> RuleKind:
        return RuleKind.FLOW

    def __post_init__(self) -> None:
        if not _text(self.resource, _MAX_RESOURCE_UNITS, non_empty=True):
            raise ValueError("flow resource is invalid")
        if not _text(self.limit_app, _MAX_IDENTIFIER_UNITS, non_empty=True):
            raise ValueError("flow limit application is invalid")
        if not isinstance(self.grade, FlowGrade) or not isinstance(
            self.strategy, FlowStrategy
        ) or not isinstance(self.control_behavior, FlowControlBehavior):
            raise ValueError("flow rule code is unsupported")
        if not _positive(self.count) or (
            self.grade is FlowGrade.THREAD and not _positive_integer(self.count)
        ):
            raise ValueError("flow threshold is invalid")
        if type(self.cluster_mode) is not bool:
            raise ValueError("flow cluster mode must be boolean")
        if self.ref_resource is not None and not _text(
            self.ref_resource, _MAX_RESOURCE_UNITS, non_empty=True
        ):
            raise ValueError("flow reference resource is invalid")
        if self.strategy is not FlowStrategy.DIRECT and self.ref_resource is None:
            raise ValueError("related flow strategies require a reference resource")
        if self.warm_up_period_sec is not None and not _positive_integer(
            self.warm_up_period_sec
        ):
            raise ValueError("flow warm-up period must be a positive integer")
        if self.max_queueing_time_ms is not None and not _positive_integer(
            self.max_queueing_time_ms
        ):
            raise ValueError("flow queue time must be a positive integer")
        if (
            self.control_behavior is FlowControlBehavior.WARM_UP
            and self.warm_up_period_sec is None
        ):
            raise ValueError("warm-up behavior requires its period")
        if (
            self.control_behavior is FlowControlBehavior.QUEUEING
            and self.max_queueing_time_ms is None
        ):
            raise ValueError("queueing behavior requires its queue time")
        if self.cluster_mode and not isinstance(
            self.cluster_config, ClusterRuleConfig
        ):
            raise ValueError("cluster flow rule requires cluster configuration")


@dataclass(frozen=True, slots=True)
class DegradeRuleValue:
    """Validated native fields for one circuit-breaker rule."""

    resource: str
    grade: DegradeGrade
    count: int | float
    time_window: int
    min_request_amount: int
    stat_interval_ms: int
    slow_ratio_threshold: int | float | None = None

    @property
    def kind(self) -> RuleKind:
        return RuleKind.DEGRADE

    def __post_init__(self) -> None:
        if not _text(self.resource, _MAX_RESOURCE_UNITS, non_empty=True):
            raise ValueError("degrade resource is invalid")
        if not isinstance(self.grade, DegradeGrade) or not _positive(self.count):
            raise ValueError("degrade grade or threshold is invalid")
        if self.grade is DegradeGrade.ERROR_COUNT and not _positive_integer(
            self.count
        ):
            raise ValueError("error count threshold must be an integer")
        if self.grade is DegradeGrade.ERROR_RATIO and self.count > 1:
            raise ValueError("error ratio threshold must not exceed one")
        if not all(
            _positive_integer(value)
            for value in (
                self.time_window,
                self.min_request_amount,
                self.stat_interval_ms,
            )
        ):
            raise ValueError("degrade time and request amounts must be positive")
        if self.slow_ratio_threshold is not None and not (
            _positive(self.slow_ratio_threshold) and self.slow_ratio_threshold <= 1
        ):
            raise ValueError("slow ratio threshold must be in (0, 1]")
        if (
            self.grade is DegradeGrade.SLOW_REQUEST_RATIO
            and self.slow_ratio_threshold is None
        ):
            raise ValueError("slow request ratio rule requires its ratio threshold")


@dataclass(frozen=True, slots=True)
class SystemRuleValue:
    """Validated native system-protection thresholds; -1 means disabled."""

    highest_system_load: int | float
    avg_rt: int | float
    max_thread: int
    qps: int | float
    highest_cpu_usage: int | float

    @property
    def kind(self) -> RuleKind:
        return RuleKind.SYSTEM

    def __post_init__(self) -> None:
        values = (
            self.highest_system_load,
            self.avg_rt,
            self.max_thread,
            self.qps,
            self.highest_cpu_usage,
        )
        if not all(
            _finite(value)
            and (value == DisabledSystemThreshold.DISABLED or value >= 0)
            for value in values
        ):
            raise ValueError("system thresholds must be -1 or non-negative")
        if (
            self.max_thread != DisabledSystemThreshold.DISABLED
            and not _non_negative_integer(self.max_thread)
        ):
            raise ValueError("maximum thread threshold must be an integer")
        if (
            self.highest_cpu_usage != DisabledSystemThreshold.DISABLED
            and self.highest_cpu_usage > 1
        ):
            raise ValueError("CPU threshold must not exceed one")
        if all(value == DisabledSystemThreshold.DISABLED for value in values):
            raise ValueError("at least one system threshold must be enabled")


@dataclass(frozen=True, slots=True)
class AuthorityRuleValue:
    """Validated native caller allow/deny rule."""

    resource: str
    limit_app: str
    strategy: AuthorityStrategy

    @property
    def kind(self) -> RuleKind:
        return RuleKind.AUTHORITY

    def __post_init__(self) -> None:
        if not _text(self.resource, _MAX_RESOURCE_UNITS, non_empty=True):
            raise ValueError("authority resource is invalid")
        if not _text(self.limit_app, _MAX_IDENTIFIER_UNITS, non_empty=True):
            raise ValueError("authority caller list is invalid")
        if not isinstance(self.strategy, AuthorityStrategy):
            raise ValueError("authority strategy is unsupported")
        origins = tuple(origin.strip() for origin in self.limit_app.split(","))
        if (
            any(not origin for origin in origins)
            or len(set(origins)) != len(origins)
        ):
            raise ValueError("authority caller list must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class ParamFlowItemValue:
    """One exceptional parameter value and its threshold."""

    class_type: str
    object_value: str
    count: int | float

    def __post_init__(self) -> None:
        if not _text(self.class_type, _MAX_RESOURCE_UNITS, non_empty=True):
            raise ValueError("parameter class type is invalid")
        if not _text(self.object_value, _MAX_RESOURCE_UNITS, non_empty=True):
            raise ValueError("parameter exception value is invalid")
        if not _non_negative(self.count):
            raise ValueError("parameter exception count is invalid")


@dataclass(frozen=True, slots=True)
class ParamFlowRuleValue:
    """Validated native parameter-flow rule and bounded exception list."""

    resource: str
    grade: FlowGrade
    count: int | float
    duration_in_sec: int
    param_idx: int
    param_flow_item_list: tuple[ParamFlowItemValue, ...]

    @property
    def kind(self) -> RuleKind:
        return RuleKind.PARAM

    def __post_init__(self) -> None:
        if not _text(self.resource, _MAX_RESOURCE_UNITS, non_empty=True):
            raise ValueError("parameter-flow resource is invalid")
        if self.grade is not FlowGrade.QPS:
            raise ValueError("parameter-flow grade must be QPS")
        if not _positive(self.count) or not _positive_integer(self.duration_in_sec):
            raise ValueError("parameter-flow threshold is invalid")
        if not _non_negative_integer(self.param_idx):
            raise ValueError("parameter index must be a non-negative integer")
        if (
            not isinstance(self.param_flow_item_list, tuple)
            or len(self.param_flow_item_list) > _MAX_PARAM_ITEMS
            or any(
                not isinstance(item, ParamFlowItemValue)
                for item in self.param_flow_item_list
            )
        ):
            raise ValueError("parameter exception list exceeds its limit")
        keys = tuple(
            (item.class_type.strip(), item.object_value)
            for item in self.param_flow_item_list
        )
        if len(set(keys)) != len(keys):
            raise ValueError("parameter exception identities must be unique")


RuleValue: TypeAlias = (
    FlowRuleValue
    | DegradeRuleValue
    | SystemRuleValue
    | AuthorityRuleValue
    | ParamFlowRuleValue
)


@dataclass(frozen=True, slots=True)
class RuleRecord:
    """Management identity paired with one complete native Sentinel rule."""

    id: str
    rule: RuleValue

    def __post_init__(self) -> None:
        if not _text(self.id, _MAX_IDENTIFIER_UNITS, non_empty=True):
            raise ValueError("rule record identity is invalid")
        if not isinstance(
            self.rule,
            (
                FlowRuleValue,
                DegradeRuleValue,
                SystemRuleValue,
                AuthorityRuleValue,
                ParamFlowRuleValue,
            ),
        ):
            raise ValueError("rule record value is unsupported")


@dataclass(frozen=True, slots=True)
class RuleSetSnapshot:
    """Complete rule-source snapshot for one exact binding identity."""

    binding: RuleBinding
    version_id: str | None
    checksum: str
    source_revision: str | None
    as_of: datetime
    records: tuple[RuleRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.binding, RuleBinding):
            raise ValueError("rule snapshot binding is invalid")
        for value in (self.version_id, self.source_revision):
            if value is not None and not _text(
                value, _MAX_IDENTIFIER_UNITS, non_empty=True
            ):
                raise ValueError("rule snapshot revision identity is invalid")
        if not _text(self.checksum, _MAX_IDENTIFIER_UNITS, non_empty=True):
            raise ValueError("rule snapshot checksum is invalid")
        if not is_wire_utc_millisecond_instant(self.as_of):
            raise ValueError("rule snapshot time must be millisecond-precise UTC")
        if (
            not isinstance(self.records, tuple)
            or len(self.records) > _MAX_RULES
            or any(not isinstance(record, RuleRecord) for record in self.records)
        ):
            raise ValueError("rule snapshot must contain at most 1,000 typed records")
        if len({record.id for record in self.records}) != len(self.records):
            raise ValueError("rule snapshot record identities must be unique")
        if any(record.rule.kind is not self.binding.kind for record in self.records):
            raise ValueError("rule snapshot records must match the binding type")
