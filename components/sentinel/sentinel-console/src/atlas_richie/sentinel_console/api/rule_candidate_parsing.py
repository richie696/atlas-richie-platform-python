"""Strict JSON parsing for typed rule candidates."""

from __future__ import annotations

import math
from enum import IntEnum
from typing import TypeVar

from ..domain.rule_bindings import RuleKind
from ..domain.rule_candidates import CandidateRule, RuleSetCandidate
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
    SystemRuleValue,
)

_EnumType = TypeVar("_EnumType", bound=IntEnum)


class InvalidCandidateShape(ValueError):
    """The request body does not have the exact published JSON shape."""


def parse_rule_candidate(body: dict[str, object] | None) -> RuleSetCandidate:
    """Parse a strict complete candidate and validate each Sentinel rule value."""
    if body is None:
        raise InvalidCandidateShape("candidate body must be an object")
    data = _object(
        body,
        required={
            "bindingId",
            "profile",
            "kind",
            "baseVersionId",
            "baseChecksum",
            "sourceRevision",
            "rules",
        },
    )
    kind_value = _string(data["kind"])
    try:
        kind = RuleKind(kind_value)
    except ValueError as exc:
        raise InvalidCandidateShape("candidate kind is unsupported") from exc
    raw_rules = data["rules"]
    if not isinstance(raw_rules, list) or len(raw_rules) > 1_000:
        raise InvalidCandidateShape("candidate rules must be a bounded array")
    return RuleSetCandidate(
        binding_id=_string(data["bindingId"]),
        profile=_string(data["profile"]),
        kind=kind,
        base_version_id=_nullable_string(data["baseVersionId"]),
        base_checksum=_string(data["baseChecksum"]),
        source_revision=_nullable_string(data["sourceRevision"]),
        rules=tuple(_candidate_rule(item) for item in raw_rules),
    )


def _candidate_rule(value: object) -> CandidateRule:
    data = _object(value, required={"recordId", "rule"})
    record_id = _nullable_string(data["recordId"])
    rule = _object(data["rule"], required={"kind", "value"})
    rule_kind = _string(rule["kind"])
    raw = rule["value"]
    match rule_kind:
        case "flow":
            return CandidateRule(record_id, _flow_rule(raw))
        case "degrade":
            return CandidateRule(record_id, _degrade_rule(raw))
        case "system":
            return CandidateRule(record_id, _system_rule(raw))
        case "authority":
            return CandidateRule(record_id, _authority_rule(raw))
        case "param":
            return CandidateRule(record_id, _param_rule(raw))
    raise InvalidCandidateShape("candidate rule kind is unsupported")


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
        raise InvalidCandidateShape("parameter-flow exception list is invalid")
    parsed_items = tuple(_param_item(item) for item in items)
    return ParamFlowRuleValue(
        _string(data["resource"]),
        _enum(FlowGrade, data["grade"]),
        _number(data["count"]),
        _integer(data["durationInSec"]),
        _integer(data["paramIdx"]),
        parsed_items,
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
        raise InvalidCandidateShape("candidate values must be objects")
    allowed = required | (optional or set())
    if not required.issubset(value) or not set(value).issubset(allowed):
        raise InvalidCandidateShape("candidate object fields do not match the contract")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise InvalidCandidateShape("candidate text field is invalid")
    return value


def _nullable_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _optional_string(data: dict[str, object], key: str) -> str | None:
    return _string(data[key]) if key in data else None


def _optional_integer(data: dict[str, object], key: str) -> int | None:
    return _integer(data[key]) if key in data else None


def _number(value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidCandidateShape("candidate numeric field is invalid")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("candidate numeric field must be finite")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise InvalidCandidateShape("candidate integer field is invalid")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise InvalidCandidateShape("candidate boolean field is invalid")
    return value


def _enum(enum_type: type[_EnumType], value: object) -> _EnumType:
    code = _integer(value)
    try:
        return enum_type(code)
    except ValueError:
        raise ValueError("candidate enum value is unsupported") from None
