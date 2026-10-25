"""Compatibility adapter for the modeled rules supported by Sentinel Python v1."""

from __future__ import annotations

from ..application.rule_validation_ports import RuleCandidateProfileValidator
from ..domain.rule_bindings import RuleBinding, RuleKind
from ..domain.rule_candidates import RuleSetCandidate
from ..domain.rule_snapshots import (
    AuthorityRuleValue,
    DegradeRuleValue,
    DisabledSystemThreshold,
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    ParamFlowRuleValue,
    SystemRuleValue,
)
from ..domain.rule_validation import RuleValidationIssue, RuleValidationIssueCode


class SentinelPythonV1RuleCandidateValidator(RuleCandidateProfileValidator):
    """Adapt typed Sentinel rule candidates to Python runtime semantics.

    The adapter is independent of web frameworks, provider SDKs, and the
    Sentinel runtime package. Only semantics known to match this profile are
    approved; the application service persists returned issues as a
    non-publishable validation receipt.
    """

    PROFILE_ID = "sentinel-python-v1"

    def validate_candidate(
        self,
        binding: RuleBinding,
        candidate: RuleSetCandidate,
    ) -> tuple[RuleValidationIssue, ...]:
        """Return bounded, value-free issues for unsupported profile semantics."""
        issues: list[RuleValidationIssue] = []
        if candidate.profile != self.PROFILE_ID or binding.profile != self.PROFILE_ID:
            issues.append(
                self._issue(
                    RuleValidationIssueCode.UNSUPPORTED_CAPABILITY,
                    None,
                    "profile",
                )
            )
            return tuple(issues)

        if candidate.kind is not binding.kind:
            issues.append(
                self._issue(RuleValidationIssueCode.CONFLICT, None, "kind")
            )
            return tuple(issues)

        for index, item in enumerate(candidate.rules):
            rule = item.rule
            match rule:
                case FlowRuleValue():
                    issues.extend(self._validate_flow(index, rule))
                case DegradeRuleValue() | AuthorityRuleValue():
                    continue
                case SystemRuleValue():
                    issues.extend(self._validate_system(index, rule))
                case ParamFlowRuleValue():
                    issues.extend(self._validate_param(index, rule))
                case _:
                    issues.append(
                        self._issue(
                            RuleValidationIssueCode.UNSUPPORTED_CAPABILITY,
                            index,
                            f"rules[{index}]",
                        )
                    )
        return tuple(issues[:32])

    def _validate_flow(
        self, index: int, rule: FlowRuleValue
    ) -> tuple[RuleValidationIssue, ...]:
        issues: list[RuleValidationIssue] = []
        if rule.cluster_mode:
            issues.append(self._unsupported(index, "clusterConfig"))
        if (
            rule.grade is FlowGrade.THREAD
            and rule.control_behavior is FlowControlBehavior.WARM_UP
        ):
            issues.append(
                self._issue(
                    RuleValidationIssueCode.VALIDATION,
                    index,
                    f"rules[{index}].controlBehavior",
                )
            )
        return tuple(issues)

    def _validate_system(
        self, index: int, rule: SystemRuleValue
    ) -> tuple[RuleValidationIssue, ...]:
        unsupported_fields = (
            ("avgRt", rule.avg_rt),
            ("maxThread", rule.max_thread),
            ("qps", rule.qps),
        )
        return tuple(
            self._unsupported(index, field)
            for field, value in unsupported_fields
            if value != DisabledSystemThreshold.DISABLED
        )

    def _validate_param(
        self, index: int, rule: ParamFlowRuleValue
    ) -> tuple[RuleValidationIssue, ...]:
        if not rule.param_flow_item_list:
            return ()
        return (self._unsupported(index, "paramFlowItemList"),)

    @classmethod
    def _unsupported(cls, index: int, field: str) -> RuleValidationIssue:
        """Create a stable issue without exposing capability or rule values."""
        return cls._issue(
            RuleValidationIssueCode.UNSUPPORTED_CAPABILITY,
            index,
            f"rules[{index}].{field}",
        )

    @staticmethod
    def _issue(
        code: RuleValidationIssueCode,
        index: int | None,
        path: str,
    ) -> RuleValidationIssue:
        return RuleValidationIssue(code=code, record_index=index, path=path)


__all__ = ["SentinelPythonV1RuleCandidateValidator"]
