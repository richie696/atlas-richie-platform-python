"""Decode provider-native Sentinel rule values into Console domain values."""

from __future__ import annotations

import math
from enum import IntEnum
from typing import TypeVar

from ..domain.rule_bindings import RuleKind
from ..domain.rule_snapshots import (
    AuthorityRuleValue,
    AuthorityStrategy,
    ClusterRuleConfig,
    ClusterThresholdType,
    DegradeGrade,
    DegradeRuleValue,
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    FlowStrategy,
    ParamFlowItemValue,
    ParamFlowRuleValue,
    RuleValue,
    SystemRuleValue,
)

_EnumType = TypeVar("_EnumType", bound=IntEnum)


class InvalidRuleValueShape(ValueError):
    """A provider rule is not in the exact supported native wire shape."""


def parse_rule_value(kind: RuleKind, value: object) -> RuleValue:
    """Parse one native Sentinel rule value using the Console's strict schema."""
    if not isinstance(kind, RuleKind):
        raise InvalidRuleValueShape("rule kind is unsupported")
    match kind:
        case RuleKind.FLOW:
            return _flow_rule(value)
        case RuleKind.DEGRADE:
            return _degrade_rule(value)
        case RuleKind.SYSTEM:
            return _system_rule(value)
        case RuleKind.AUTHORITY:
            return _authority_rule(value)
        case RuleKind.PARAM:
            return _param_rule(value)
    raise InvalidRuleValueShape("rule kind is unsupported")


def _flow_rule(value: object) -> FlowRuleValue:
    data = _object(
        value,
        required={
            "resource",
            "limitApp",
            "grade",
            "count",
            "strategy",
            "controlBehavior",
            "clusterMode",
        },
        optional={
            "refResource",
            "warmUpPeriodSec",
            "maxQueueingTimeMs",
            "clusterConfig",
        },
    )
    cluster = data.get("clusterConfig")
    return FlowRuleValue(
        resource=_string(data["resource"]),
        limit_app=_string(data["limitApp"]),
        grade=_enum(FlowGrade, data["grade"]),
        count=_number(data["count"]),
        strategy=_enum(FlowStrategy, data["strategy"]),
        control_behavior=_enum(FlowControlBehavior, data["controlBehavior"]),
        cluster_mode=_boolean(data["clusterMode"]),
        ref_resource=_optional_string(data, "refResource"),
        warm_up_period_sec=_optional_integer(data, "warmUpPeriodSec"),
        max_queueing_time_ms=_optional_integer(data, "maxQueueingTimeMs"),
        cluster_config=_cluster_config(cluster) if cluster is not None else None,
    )


def _cluster_config(value: object) -> ClusterRuleConfig:
    data = _object(
        value,
        required={
            "thresholdType",
            "fallbackToLocalWhenFail",
            "sampleCount",
            "windowIntervalMs",
        },
    )
    return ClusterRuleConfig(
        _enum(ClusterThresholdType, data["thresholdType"]),
        _boolean(data["fallbackToLocalWhenFail"]),
        _integer(data["sampleCount"]),
        _integer(data["windowIntervalMs"]),
    )


def _degrade_rule(value: object) -> DegradeRuleValue:
    data = _object(
        value,
        required={
            "resource",
            "grade",
            "count",
            "timeWindow",
            "minRequestAmount",
            "statIntervalMs",
        },
        optional={"slowRatioThreshold"},
    )
    return DegradeRuleValue(
        resource=_string(data["resource"]),
        grade=_enum(DegradeGrade, data["grade"]),
        count=_number(data["count"]),
        time_window=_integer(data["timeWindow"]),
        min_request_amount=_integer(data["minRequestAmount"]),
        stat_interval_ms=_integer(data["statIntervalMs"]),
        slow_ratio_threshold=(
            _number(data["slowRatioThreshold"])
            if "slowRatioThreshold" in data
            else None
        ),
    )


def _system_rule(value: object) -> SystemRuleValue:
    data = _object(
        value,
        required={
            "highestSystemLoad",
            "avgRt",
            "maxThread",
            "qps",
            "highestCpuUsage",
        },
    )
    return SystemRuleValue(
        _number(data["highestSystemLoad"]),
        _number(data["avgRt"]),
        _integer(data["maxThread"]),
        _number(data["qps"]),
        _number(data["highestCpuUsage"]),
    )


def _authority_rule(value: object) -> AuthorityRuleValue:
    data = _object(value, required={"resource", "limitApp", "strategy"})
    return AuthorityRuleValue(
        _string(data["resource"]),
        _string(data["limitApp"]),
        _enum(AuthorityStrategy, data["strategy"]),
    )


def _param_rule(value: object) -> ParamFlowRuleValue:
    data = _object(
        value,
        required={
            "resource",
            "grade",
            "count",
            "durationInSec",
            "paramIdx",
            "paramFlowItemList",
        },
    )
    items = data["paramFlowItemList"]
    if not isinstance(items, list) or len(items) > 100:
        raise InvalidRuleValueShape("parameter-flow exception list is invalid")
    return ParamFlowRuleValue(
        _string(data["resource"]),
        _enum(FlowGrade, data["grade"]),
        _number(data["count"]),
        _integer(data["durationInSec"]),
        _integer(data["paramIdx"]),
        tuple(_param_item(item) for item in items),
    )


def _param_item(value: object) -> ParamFlowItemValue:
    data = _object(value, required={"classType", "object", "count"})
    return ParamFlowItemValue(
        _string(data["classType"]),
        _string(data["object"]),
        _number(data["count"]),
    )


def _object(
    value: object,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise InvalidRuleValueShape("rule value must be an object")
    allowed = required | (optional or set())
    if not required.issubset(value) or not set(value).issubset(allowed):
        raise InvalidRuleValueShape("rule value fields do not match the contract")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise InvalidRuleValueShape("rule text field is invalid")
    return value


def _optional_string(data: dict[str, object], key: str) -> str | None:
    return _string(data[key]) if key in data else None


def _optional_integer(data: dict[str, object], key: str) -> int | None:
    return _integer(data[key]) if key in data else None


def _number(value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidRuleValueShape("rule numeric field is invalid")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("rule numeric field must be finite")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise InvalidRuleValueShape("rule integer field is invalid")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise InvalidRuleValueShape("rule boolean field is invalid")
    return value


def _enum(enum_type: type[_EnumType], value: object) -> _EnumType:
    code = _integer(value)
    try:
        return enum_type(code)
    except ValueError:
        raise ValueError("rule enum value is unsupported") from None


__all__ = ["InvalidRuleValueShape", "parse_rule_value"]
