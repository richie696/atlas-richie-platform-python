"""Encode one Console rule version as a native same-kind Sentinel JSON array."""

from __future__ import annotations

import json
import re

from ..application.rule_publication_ports import (
    RulePublicationProfileUnsupported,
    RulePublicationValueUnsupported,
)
from ..application.rule_value_projection import rule_value_fields
from ..domain.rule_snapshots import (
    DegradeGrade,
    DegradeRuleValue,
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    FlowStrategy,
)
from ..domain.rule_versions import RuleSetVersion


class SentinelRuleVersionJsonEncoder:
    """Project typed Console values into the configured native Sentinel profile.

    Console record IDs and API discriminators are management metadata, so only
    the rule value object is included in the provider-facing array.
    """

    def __init__(self, profile_id: str) -> None:
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise ValueError("Sentinel rule encoder profile identity is invalid")
        profile_ids = tuple(profile.strip() for profile in profile_id.split(","))
        if (
            any(not profile for profile in profile_ids)
            or len(set(profile_ids)) != len(profile_ids)
        ):
            raise ValueError("Sentinel rule encoder profile identity is invalid")
        self._profile_ids = frozenset(profile_ids)

    def encode_rule_version(self, version: RuleSetVersion) -> bytes:
        """Return compact UTF-8 JSON preserving the immutable version order."""
        if not isinstance(version, RuleSetVersion):
            raise ValueError("Sentinel rule encoder version is invalid")
        if version.profile not in self._profile_ids:
            raise RulePublicationProfileUnsupported(
                "rule version profile is not supported by this encoder"
            )

        try:
            values = []
            for record in version.records:
                _validate_profile_semantics(record.rule)
                values.append(_profile_fields(version.profile, record.rule))
            encoded = json.dumps(
                values,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            if version.profile in {
                "sentinel-java-v1",
                "sentinel-go-v1",
                "sentinel-rust-v1",
            }:
                encoded = _expand_exponent_numbers(encoded)
            return encoded.encode("utf-8")
        except RulePublicationValueUnsupported:
            raise
        except (TypeError, ValueError):
            raise RulePublicationValueUnsupported(
                "rule version contains a value outside the supported profile"
            ) from None


def _validate_profile_semantics(rule: object) -> None:
    """Reject populated fields whose conditions make them inactive on wire."""
    if isinstance(rule, FlowRuleValue):
        if not rule.cluster_mode and rule.cluster_config is not None:
            raise RulePublicationValueUnsupported(
                "disabled cluster flow rule cannot carry cluster configuration"
            )
    elif isinstance(rule, DegradeRuleValue):
        if (
            rule.slow_ratio_threshold is not None
            and rule.grade is not DegradeGrade.SLOW_REQUEST_RATIO
        ):
            raise RulePublicationValueUnsupported(
                "slow ratio threshold requires the slow request ratio grade"
            )


def _profile_fields(profile_id: str, rule: object) -> dict[str, object]:
    """Encode finite cross-language profiles without Console-only fields."""
    if profile_id == "sentinel-go-v1":
        if not isinstance(rule, FlowRuleValue) or not _is_direct_qps_reject(rule):
            raise RulePublicationValueUnsupported(
                "rule is outside the supported sentinel-go-v1 flow subset"
            )
        return {
            "resource": rule.resource,
            "threshold": rule.count,
            "statIntervalInMs": 1000,
            "tokenCalculateStrategy": 0,
            "controlBehavior": 0,
            "relationStrategy": 0,
            "refResource": "",
        }
    if profile_id in {"sentinel-java-v1", "sentinel-rust-v1"}:
        if not isinstance(rule, FlowRuleValue) or not _is_direct_qps_reject(rule):
            raise RulePublicationValueUnsupported("rule is outside the supported flow subset")
    return rule_value_fields(rule)  # type: ignore[arg-type]


def _is_direct_qps_reject(rule: FlowRuleValue) -> bool:
    return (
        rule.grade is FlowGrade.QPS
        and rule.strategy is FlowStrategy.DIRECT
        and rule.control_behavior is FlowControlBehavior.REJECT
        and rule.limit_app == "default"
        and not rule.cluster_mode
        and rule.cluster_config is None
        and rule.ref_resource is None
        and rule.warm_up_period_sec is None
        and rule.max_queueing_time_ms is None
    )


_EXPONENT_NUMBER = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?[eE][+-]?[0-9]+')


def _expand_exponent_numbers(encoded: str) -> str:
    """Expand exponent-form JSON number tokens without changing JSON strings."""
    from decimal import Decimal

    expanded: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(encoded):
        char = encoded[index]
        if in_string:
            expanded.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            expanded.append(char)
            index += 1
            continue

        match = _EXPONENT_NUMBER.match(encoded, index)
        previous_is_boundary = index == 0 or encoded[index - 1] in " \t\r\n:,["
        end = match.end() if match is not None else index
        next_is_boundary = end == len(encoded) or encoded[end] in " \t\r\n,]}"
        if match is not None and previous_is_boundary and next_is_boundary:
            expanded.append(format(Decimal(match.group(0)), "f"))
            index = end
            continue

        expanded.append(char)
        index += 1

    return "".join(expanded)


__all__ = ["SentinelRuleVersionJsonEncoder"]
