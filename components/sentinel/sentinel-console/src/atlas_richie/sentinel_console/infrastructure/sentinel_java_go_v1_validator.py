"""Strict compatibility adapters for the supported Java and Go V1 flow subset."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from ..application.rule_validation_ports import RuleCandidateProfileValidator
from ..domain.rule_bindings import RuleBinding, RuleKind
from ..domain.rule_candidates import RuleSetCandidate
from ..domain.rule_snapshots import (
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    FlowStrategy,
)
from ..domain.rule_validation import RuleValidationIssue, RuleValidationIssueCode


class SentinelJavaV1RuleCandidateValidator(RuleCandidateProfileValidator):
    """Validate the exact FlowRule subset implemented by the Java SDK adapter."""

    PROFILE_ID = "sentinel-java-v1"

    def validate_candidate(
        self,
        binding: RuleBinding,
        candidate: RuleSetCandidate,
    ) -> tuple[RuleValidationIssue, ...]:
        return _validate_flow_candidate(binding, candidate, self.PROFILE_ID)


class SentinelGoV1RuleCandidateValidator(RuleCandidateProfileValidator):
    """Validate the exact FlowRule subset implemented by the Go SDK adapter."""

    PROFILE_ID = "sentinel-go-v1"

    def validate_candidate(
        self,
        binding: RuleBinding,
        candidate: RuleSetCandidate,
    ) -> tuple[RuleValidationIssue, ...]:
        return _validate_flow_candidate(binding, candidate, self.PROFILE_ID)


class SentinelRustV1RuleCandidateValidator(RuleCandidateProfileValidator):
    """Validate the exact FlowRule subset implemented by the Rust adapter."""

    PROFILE_ID = "sentinel-rust-v1"

    def validate_candidate(
        self,
        binding: RuleBinding,
        candidate: RuleSetCandidate,
    ) -> tuple[RuleValidationIssue, ...]:
        return _validate_flow_candidate(binding, candidate, self.PROFILE_ID)


class SentinelRuleCandidateValidatorRegistry(RuleCandidateProfileValidator):
    """Dispatch only explicitly registered runtime profiles; unknown profiles deny."""

    def __init__(self, validators: tuple[RuleCandidateProfileValidator, ...]) -> None:
        profiles: dict[str, RuleCandidateProfileValidator] = {}
        for validator in validators:
            profile_id = getattr(validator, "PROFILE_ID", None)
            if not isinstance(profile_id, str) or not profile_id or profile_id in profiles:
                raise ValueError("rule candidate validator profile registry is invalid")
            profiles[profile_id] = validator
        self._validators = profiles

    def validate_candidate(
        self,
        binding: RuleBinding,
        candidate: RuleSetCandidate,
    ) -> tuple[RuleValidationIssue, ...]:
        validator = self._validators.get(candidate.profile)
        if validator is None:
            return (_issue(RuleValidationIssueCode.UNSUPPORTED_CAPABILITY, None, "profile"),)
        return validator.validate_candidate(binding, candidate)


def _validate_flow_candidate(
    binding: RuleBinding,
    candidate: RuleSetCandidate,
    profile_id: str,
) -> tuple[RuleValidationIssue, ...]:
    if candidate.profile != profile_id or binding.profile != profile_id:
        return (_issue(RuleValidationIssueCode.UNSUPPORTED_CAPABILITY, None, "profile"),)
    if candidate.kind is not binding.kind:
        return (_issue(RuleValidationIssueCode.CONFLICT, None, "kind"),)
    if candidate.kind is not RuleKind.FLOW:
        return (_issue(RuleValidationIssueCode.UNSUPPORTED_CAPABILITY, None, "kind"),)

    issues: list[RuleValidationIssue] = []
    resources: set[str] = set()
    for index, item in enumerate(candidate.rules):
        rule = item.rule
        if not isinstance(rule, FlowRuleValue):
            issues.append(_issue(RuleValidationIssueCode.UNSUPPORTED_CAPABILITY, index, f"rules[{index}]"))
            continue
        if rule.grade is not FlowGrade.QPS:
            issues.append(_issue(RuleValidationIssueCode.UNSUPPORTED_CAPABILITY, index, f"rules[{index}].grade"))
        if rule.strategy is not FlowStrategy.DIRECT:
            issues.append(_issue(RuleValidationIssueCode.UNSUPPORTED_CAPABILITY, index, f"rules[{index}].strategy"))
        if rule.control_behavior is not FlowControlBehavior.REJECT:
            issues.append(_issue(RuleValidationIssueCode.UNSUPPORTED_CAPABILITY, index, f"rules[{index}].controlBehavior"))
        if rule.limit_app != "default":
            issues.append(_issue(RuleValidationIssueCode.UNSUPPORTED_CAPABILITY, index, f"rules[{index}].limitApp"))
        try:
            resource_bytes = rule.resource.encode("utf-8", errors="strict")
            threshold = Decimal(str(rule.count))
        except (UnicodeEncodeError, InvalidOperation, ValueError):
            issues.append(_issue(RuleValidationIssueCode.VALIDATION, index, f"rules[{index}]"))
            continue
        if len(resource_bytes) > 200:
            issues.append(_issue(RuleValidationIssueCode.VALIDATION, index, f"rules[{index}].resource"))
        if rule.resource in resources:
            issues.append(_issue(RuleValidationIssueCode.VALIDATION, index, f"rules[{index}].resource"))
        resources.add(rule.resource)
        normalized_threshold = threshold.normalize()
        if threshold <= 0 or threshold > Decimal("1000000000") or normalized_threshold.as_tuple().exponent < -6:
            issues.append(_issue(RuleValidationIssueCode.VALIDATION, index, f"rules[{index}].count"))
        if rule.cluster_mode or rule.cluster_config is not None:
            issues.append(_issue(RuleValidationIssueCode.UNSUPPORTED_CAPABILITY, index, f"rules[{index}].clusterConfig"))
        if rule.ref_resource is not None:
            issues.append(_issue(RuleValidationIssueCode.UNSUPPORTED_CAPABILITY, index, f"rules[{index}].refResource"))
        if rule.warm_up_period_sec is not None:
            issues.append(_issue(RuleValidationIssueCode.UNSUPPORTED_CAPABILITY, index, f"rules[{index}].warmUpPeriodSec"))
        if rule.max_queueing_time_ms is not None:
            issues.append(_issue(RuleValidationIssueCode.UNSUPPORTED_CAPABILITY, index, f"rules[{index}].maxQueueingTimeMs"))
    return tuple(issues[:32])


def _issue(
    code: RuleValidationIssueCode,
    index: int | None,
    path: str,
) -> RuleValidationIssue:
    return RuleValidationIssue(code=code, record_index=index, path=path)


__all__ = [
    "SentinelGoV1RuleCandidateValidator",
    "SentinelJavaV1RuleCandidateValidator",
    "SentinelRustV1RuleCandidateValidator",
    "SentinelRuleCandidateValidatorRegistry",
]
