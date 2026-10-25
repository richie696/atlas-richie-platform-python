"""Java/Go rule candidate profile validation contracts."""

from __future__ import annotations

import unittest

from atlas_richie.sentinel_console.domain.rule_bindings import RuleBinding, RuleKind
from atlas_richie.sentinel_console.domain.rule_candidates import CandidateRule, RuleSetCandidate
from atlas_richie.sentinel_console.domain.rule_snapshots import (
    ClusterRuleConfig,
    ClusterThresholdType,
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    FlowStrategy,
)
from atlas_richie.sentinel_console.domain.rule_validation import RuleValidationIssueCode
from atlas_richie.sentinel_console.infrastructure.sentinel_java_go_v1_validator import (
    SentinelGoV1RuleCandidateValidator,
    SentinelJavaV1RuleCandidateValidator,
    SentinelRustV1RuleCandidateValidator,
    SentinelRuleCandidateValidatorRegistry,
)


class SentinelJavaGoV1RuleCandidateValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = SentinelRuleCandidateValidatorRegistry(
            (
                SentinelJavaV1RuleCandidateValidator(),
                SentinelGoV1RuleCandidateValidator(),
                SentinelRustV1RuleCandidateValidator(),
            )
        )

    def test_accepts_exact_shared_direct_qps_reject_flow_subset(self) -> None:
        for profile in ("sentinel-java-v1", "sentinel-go-v1", "sentinel-rust-v1"):
            with self.subTest(profile=profile):
                binding, candidate = _candidate(profile, _flow())
                self.assertEqual(self.registry.validate_candidate(binding, candidate), ())

    def test_rejects_unsupported_flow_semantics_without_values(self) -> None:
        cases = (
            (_flow(grade=FlowGrade.THREAD), "rules[0].grade"),
            (_flow(strategy=FlowStrategy.CHAIN, ref_resource="parent"), "rules[0].strategy"),
            (_flow(control_behavior=FlowControlBehavior.QUEUEING, max_queueing_time_ms=250), "rules[0].controlBehavior"),
            (_flow(limit_app="other-service"), "rules[0].limitApp"),
            (_flow(cluster_mode=True, cluster_config=ClusterRuleConfig(ClusterThresholdType.GLOBAL, False, 10, 1000)), "rules[0].clusterConfig"),
        )
        for profile in ("sentinel-java-v1", "sentinel-go-v1", "sentinel-rust-v1"):
            for rule, expected_path in cases:
                with self.subTest(profile=profile, path=expected_path):
                    binding, candidate = _candidate(profile, rule)
                    issues = self.registry.validate_candidate(binding, candidate)
                    self.assertIn(expected_path, tuple(issue.path for issue in issues))
                    self.assertTrue(all(issue.code is RuleValidationIssueCode.UNSUPPORTED_CAPABILITY for issue in issues))
                    self.assertNotIn("other-service", repr(issues))

    def test_unknown_profile_and_non_flow_binding_fail_closed(self) -> None:
        binding, candidate = _candidate("sentinel-java-v1", _flow())
        unknown = RuleSetCandidate(
            binding_id=candidate.binding_id,
            profile="sentinel-unknown-v9",
            kind=candidate.kind,
            base_version_id=candidate.base_version_id,
            base_checksum=candidate.base_checksum,
            source_revision=candidate.source_revision,
            rules=candidate.rules,
        )
        self.assertEqual(self.registry.validate_candidate(binding, unknown)[0].path, "profile")

        other_kind = RuleBinding(
            id=binding.id,
            environment_id=binding.environment_id,
            app_id=binding.app_id,
            kind=RuleKind.DEGRADE,
            profile=binding.profile,
            source_id=binding.source_id,
            source_label=binding.source_label,
            location=binding.location,
        )
        self.assertEqual(self.registry.validate_candidate(other_kind, candidate)[0].code, RuleValidationIssueCode.CONFLICT)


def _candidate(profile: str, rule: FlowRuleValue) -> tuple[RuleBinding, RuleSetCandidate]:
    binding = RuleBinding(
        id="binding-1",
        environment_id="e2e",
        app_id="java-go-demo",
        kind=RuleKind.FLOW,
        profile=profile,
        source_id="source-1",
        source_label="Nacos",
        location="public/DEFAULT_GROUP/flow-rules.json",
    )
    candidate = RuleSetCandidate(
        binding_id=binding.id,
        profile=profile,
        kind=RuleKind.FLOW,
        base_version_id=None,
        base_checksum="sha256:baseline",
        source_revision="revision-1",
        rules=(CandidateRule(None, rule),),
    )
    return binding, candidate


def _flow(**overrides: object) -> FlowRuleValue:
    values: dict[str, object] = {
        "resource": "GET /api/hello",
        "limit_app": "default",
        "grade": FlowGrade.QPS,
        "count": 1,
        "strategy": FlowStrategy.DIRECT,
        "control_behavior": FlowControlBehavior.REJECT,
        "cluster_mode": False,
    }
    values.update(overrides)
    return FlowRuleValue(**values)  # type: ignore[arg-type]
