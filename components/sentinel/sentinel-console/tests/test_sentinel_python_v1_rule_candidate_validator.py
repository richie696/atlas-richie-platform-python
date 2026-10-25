"""Sentinel Python v1 profile compatibility adapter contract tests."""

from __future__ import annotations

import unittest
from dataclasses import replace

from atlas_richie.sentinel_console.domain.rule_bindings import RuleBinding, RuleKind
from atlas_richie.sentinel_console.domain.rule_candidates import (
    CandidateRule,
    RuleSetCandidate,
)
from atlas_richie.sentinel_console.domain.rule_snapshots import (
    AuthorityRuleValue,
    AuthorityStrategy,
    ClusterRuleConfig,
    ClusterThresholdType,
    DegradeGrade,
    DegradeRuleValue,
    DisabledSystemThreshold,
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    FlowStrategy,
    ParamFlowItemValue,
    ParamFlowRuleValue,
    SystemRuleValue,
)
from atlas_richie.sentinel_console.domain.rule_validation import (
    RuleValidationIssueCode,
)
from atlas_richie.sentinel_console.infrastructure.sentinel_python_v1_validator import (
    SentinelPythonV1RuleCandidateValidator,
)

_PROFILE = SentinelPythonV1RuleCandidateValidator.PROFILE_ID


class SentinelPythonV1RuleCandidateValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = SentinelPythonV1RuleCandidateValidator()

    def test_accepts_each_of_the_five_modeled_rule_families(self) -> None:
        cases = (
            (
                RuleKind.FLOW,
                FlowRuleValue(
                    "orders",
                    "default",
                    FlowGrade.QPS,
                    10,
                    FlowStrategy.DIRECT,
                    FlowControlBehavior.REJECT,
                    False,
                ),
            ),
            (
                RuleKind.DEGRADE,
                DegradeRuleValue(
                    "orders",
                    DegradeGrade.ERROR_COUNT,
                    2,
                    5,
                    10,
                    1_000,
                ),
            ),
            (
                RuleKind.SYSTEM,
                SystemRuleValue(
                    DisabledSystemThreshold.DISABLED,
                    DisabledSystemThreshold.DISABLED,
                    DisabledSystemThreshold.DISABLED,
                    DisabledSystemThreshold.DISABLED,
                    0.8,
                ),
            ),
            (
                RuleKind.AUTHORITY,
                AuthorityRuleValue(
                    "orders", "trusted-service", AuthorityStrategy.WHITE_LIST
                ),
            ),
            (
                RuleKind.PARAM,
                ParamFlowRuleValue("orders", FlowGrade.QPS, 10, 1, 0, ()),
            ),
        )

        for kind, rule in cases:
            with self.subTest(kind=kind):
                binding = _binding(kind)
                candidate = _candidate(kind, rule)
                self.assertEqual(
                    self.validator.validate_candidate(binding, candidate), ()
                )

    def test_rejects_known_python_runtime_capability_gaps(self) -> None:
        cases = (
            (
                RuleKind.FLOW,
                FlowRuleValue(
                "orders",
                "default",
                FlowGrade.QPS,
                10,
                FlowStrategy.DIRECT,
                FlowControlBehavior.REJECT,
                True,
                cluster_config=ClusterRuleConfig(
                    ClusterThresholdType.GLOBAL, False, 10, 1_000
                ),
                ),
                ("rules[0].clusterConfig",),
                (RuleValidationIssueCode.UNSUPPORTED_CAPABILITY,),
            ),
            (
                RuleKind.FLOW,
                FlowRuleValue(
                "orders",
                "default",
                FlowGrade.THREAD,
                10,
                FlowStrategy.DIRECT,
                FlowControlBehavior.WARM_UP,
                False,
                warm_up_period_sec=10,
                ),
                ("rules[0].controlBehavior",),
                (RuleValidationIssueCode.VALIDATION,),
            ),
            (
                RuleKind.SYSTEM,
                SystemRuleValue(1, 1, 5, 10, 0.8),
                ("rules[0].avgRt", "rules[0].maxThread", "rules[0].qps"),
                (RuleValidationIssueCode.UNSUPPORTED_CAPABILITY,) * 3,
            ),
            (
                RuleKind.PARAM,
                ParamFlowRuleValue(
                    "orders",
                    FlowGrade.QPS,
                    10,
                    1,
                    0,
                    (ParamFlowItemValue("builtins.str", "vip", 20),),
                ),
                ("rules[0].paramFlowItemList",),
                (RuleValidationIssueCode.UNSUPPORTED_CAPABILITY,),
            ),
        )
        for kind, rule, expected_paths, expected_codes in cases:
            with self.subTest(kind=kind, paths=expected_paths):
                issues = self.validator.validate_candidate(
                    _binding(kind), _candidate(kind, rule)
                )
                self.assertEqual(
                    tuple(issue.path for issue in issues), expected_paths
                )
                self.assertEqual(
                    tuple(issue.code for issue in issues), expected_codes
                )

    def test_unknown_profile_is_non_publishable_and_fails_closed(self) -> None:
        binding = _binding(RuleKind.FLOW)
        candidate = replace(_candidate(RuleKind.FLOW, _flow()), profile="unknown-v2")

        issues = self.validator.validate_candidate(binding, candidate)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].code, RuleValidationIssueCode.UNSUPPORTED_CAPABILITY)
        self.assertEqual(issues[0].path, "profile")

    def test_binding_kind_mismatch_is_a_conflict(self) -> None:
        binding = _binding(RuleKind.DEGRADE)
        candidate = _candidate(RuleKind.FLOW, _flow())

        issues = self.validator.validate_candidate(binding, candidate)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].code, RuleValidationIssueCode.CONFLICT)
        self.assertEqual(issues[0].path, "kind")


def _binding(kind: RuleKind) -> RuleBinding:
    return RuleBinding(
        id="binding-1",
        environment_id="prod",
        app_id="checkout",
        kind=kind,
        profile=_PROFILE,
        source_id="config-main",
        source_label="Main config",
        location="sentinel/prod/rules",
    )


def _candidate(kind: RuleKind, rule, *additional_rules) -> RuleSetCandidate:
    return RuleSetCandidate(
        binding_id="binding-1",
        profile=_PROFILE,
        kind=kind,
        base_version_id="version-1",
        base_checksum="sha256:baseline",
        source_revision="revision-1",
        rules=tuple(
            CandidateRule(None, item)
            for item in (rule, *additional_rules)
        ),
    )


def _flow() -> FlowRuleValue:
    return FlowRuleValue(
        "orders",
        "default",
        FlowGrade.QPS,
        10,
        FlowStrategy.DIRECT,
        FlowControlBehavior.REJECT,
        False,
    )


if __name__ == "__main__":
    unittest.main()
