"""Canonical JSON-field projection for validated Sentinel rule values."""

from __future__ import annotations

from ..domain.rule_snapshots import (
    AuthorityRuleValue,
    ClusterRuleConfig,
    DegradeRuleValue,
    FlowRuleValue,
    ParamFlowItemValue,
    ParamFlowRuleValue,
    RuleValue,
    SystemRuleValue,
)


def rule_value_fields(rule: RuleValue) -> dict[str, object]:
    """Return the complete camel-case value fields without Console identity."""
    match rule:
        case FlowRuleValue():
            return _flow_fields(rule)
        case DegradeRuleValue():
            return _degrade_fields(rule)
        case SystemRuleValue():
            return _system_fields(rule)
        case AuthorityRuleValue():
            return _authority_fields(rule)
        case ParamFlowRuleValue():
            return _param_flow_fields(rule)
    raise ValueError("unsupported typed rule value")


def _flow_fields(rule: FlowRuleValue) -> dict[str, object]:
    body: dict[str, object] = {
        "resource": rule.resource,
        "limitApp": rule.limit_app,
        "grade": int(rule.grade),
        "count": rule.count,
        "strategy": int(rule.strategy),
        "controlBehavior": int(rule.control_behavior),
        "clusterMode": rule.cluster_mode,
    }
    optional = {
        "refResource": rule.ref_resource,
        "warmUpPeriodSec": rule.warm_up_period_sec,
        "maxQueueingTimeMs": rule.max_queueing_time_ms,
    }
    body.update({key: value for key, value in optional.items() if value is not None})
    if rule.cluster_config is not None:
        body["clusterConfig"] = _cluster_fields(rule.cluster_config)
    return body


def _cluster_fields(config: ClusterRuleConfig) -> dict[str, object]:
    return {
        "thresholdType": int(config.threshold_type),
        "fallbackToLocalWhenFail": config.fallback_to_local_when_fail,
        "sampleCount": config.sample_count,
        "windowIntervalMs": config.window_interval_ms,
    }


def _degrade_fields(rule: DegradeRuleValue) -> dict[str, object]:
    body: dict[str, object] = {
        "resource": rule.resource,
        "grade": int(rule.grade),
        "count": rule.count,
        "timeWindow": rule.time_window,
        "minRequestAmount": rule.min_request_amount,
        "statIntervalMs": rule.stat_interval_ms,
    }
    if rule.slow_ratio_threshold is not None:
        body["slowRatioThreshold"] = rule.slow_ratio_threshold
    return body


def _system_fields(rule: SystemRuleValue) -> dict[str, object]:
    return {
        "highestSystemLoad": rule.highest_system_load,
        "avgRt": rule.avg_rt,
        "maxThread": rule.max_thread,
        "qps": rule.qps,
        "highestCpuUsage": rule.highest_cpu_usage,
    }


def _authority_fields(rule: AuthorityRuleValue) -> dict[str, object]:
    return {
        "resource": rule.resource,
        "limitApp": rule.limit_app,
        "strategy": int(rule.strategy),
    }


def _param_flow_fields(rule: ParamFlowRuleValue) -> dict[str, object]:
    return {
        "resource": rule.resource,
        "grade": int(rule.grade),
        "count": rule.count,
        "durationInSec": rule.duration_in_sec,
        "paramIdx": rule.param_idx,
        "paramFlowItemList": [
            _parameter_item_fields(item) for item in rule.param_flow_item_list
        ],
    }


def _parameter_item_fields(item: ParamFlowItemValue) -> dict[str, object]:
    return {
        "classType": item.class_type,
        "object": item.object_value,
        "count": item.count,
    }


__all__ = ["rule_value_fields"]
