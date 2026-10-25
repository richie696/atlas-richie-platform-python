"""Console's strict provider-neutral Sentinel rule JSON profile encoder."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import unittest

from atlas_richie.sentinel_console.application.rule_publication_ports import (
    RulePublicationProfileUnsupported,
    RulePublicationValueUnsupported,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleKind
from atlas_richie.sentinel_console.domain.rule_snapshots import (
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
from atlas_richie.sentinel_console.domain.rule_versions import RuleSetVersion
from atlas_richie.sentinel_console.domain.rule_snapshots import RuleRecord
from atlas_richie.sentinel_console.infrastructure.sentinel_rule_version_encoder import (
    SentinelRuleVersionJsonEncoder,
)

_NOW = datetime(2026, 10, 9, 3, 0, tzinfo=UTC)
_PROFILE = "sentinel-rule-profile-v1"


def _version(
    kind: RuleKind,
    *records: RuleRecord,
    profile: str = _PROFILE,
) -> RuleSetVersion:
    return RuleSetVersion(
        id="version-1",
        binding_id="binding-1",
        kind=kind,
        profile=profile,
        base_version_id=None,
        checksum="checksum-1",
        name="Candidate",
        note="",
        created_at=_NOW,
        created_by_id="admin-1",
        records=tuple(records),
    )


class SentinelRuleVersionJsonEncoderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.encoder = SentinelRuleVersionJsonEncoder(_PROFILE)

    def test_encodes_all_five_rule_families_as_native_value_arrays(self) -> None:
        cases = (
            (
                _version(
                    RuleKind.FLOW,
                    RuleRecord(
                        "console-flow-id",
                        FlowRuleValue(
                            resource="/api/orders",
                            limit_app="default",
                            grade=FlowGrade.QPS,
                            count=120,
                            strategy=FlowStrategy.DIRECT,
                            control_behavior=FlowControlBehavior.QUEUEING,
                            cluster_mode=True,
                            max_queueing_time_ms=250,
                            cluster_config=ClusterRuleConfig(
                                ClusterThresholdType.GLOBAL,
                                True,
                                10,
                                1_000,
                            ),
                        ),
                    ),
                ),
                {
                    "resource": "/api/orders",
                    "limitApp": "default",
                    "grade": 1,
                    "count": 120,
                    "strategy": 0,
                    "controlBehavior": 2,
                    "clusterMode": True,
                    "maxQueueingTimeMs": 250,
                    "clusterConfig": {
                        "thresholdType": 1,
                        "fallbackToLocalWhenFail": True,
                        "sampleCount": 10,
                        "windowIntervalMs": 1_000,
                    },
                },
            ),
            (
                _version(
                    RuleKind.DEGRADE,
                    RuleRecord(
                        "console-degrade-id",
                        DegradeRuleValue(
                            resource="/api/payment",
                            grade=DegradeGrade.SLOW_REQUEST_RATIO,
                            count=800,
                            time_window=30,
                            min_request_amount=20,
                            stat_interval_ms=10_000,
                            slow_ratio_threshold=0.7,
                        ),
                    ),
                ),
                {
                    "resource": "/api/payment",
                    "grade": 0,
                    "count": 800,
                    "timeWindow": 30,
                    "minRequestAmount": 20,
                    "statIntervalMs": 10_000,
                    "slowRatioThreshold": 0.7,
                },
            ),
            (
                _version(
                    RuleKind.SYSTEM,
                    RuleRecord(
                        "console-system-id",
                        SystemRuleValue(-1, 150, 500, -1, 0.9),
                    ),
                ),
                {
                    "highestSystemLoad": -1,
                    "avgRt": 150,
                    "maxThread": 500,
                    "qps": -1,
                    "highestCpuUsage": 0.9,
                },
            ),
            (
                _version(
                    RuleKind.AUTHORITY,
                    RuleRecord(
                        "console-authority-id",
                        AuthorityRuleValue(
                            "/api/admin", "trusted-client,internal-job", AuthorityStrategy.BLACK_LIST
                        ),
                    ),
                ),
                {
                    "resource": "/api/admin",
                    "limitApp": "trusted-client,internal-job",
                    "strategy": 1,
                },
            ),
            (
                _version(
                    RuleKind.PARAM,
                    RuleRecord(
                        "console-param-id",
                        ParamFlowRuleValue(
                            resource="/api/search",
                            grade=FlowGrade.QPS,
                            count=12.5,
                            duration_in_sec=2,
                            param_idx=0,
                            param_flow_item_list=(
                                ParamFlowItemValue("java.lang.String", "vip", 3),
                            ),
                        ),
                    ),
                ),
                {
                    "resource": "/api/search",
                    "grade": 1,
                    "count": 12.5,
                    "durationInSec": 2,
                    "paramIdx": 0,
                    "paramFlowItemList": [
                        {"classType": "java.lang.String", "object": "vip", "count": 3}
                    ],
                },
            ),
        )

        for version, expected in cases:
            with self.subTest(kind=version.kind):
                body = self.encoder.encode_rule_version(version)
                self.assertIsInstance(body, bytes)
                self.assertEqual(json.loads(body), [expected])
                self.assertNotIn(b"console-", body)
                self.assertNotIn(b'"kind"', body)
                self.assertNotIn(b'"value"', body)

    def test_output_is_compact_deterministic_and_preserves_rule_order(self) -> None:
        first = RuleRecord(
            "a",
            FlowRuleValue(
                "/first", "default", FlowGrade.QPS, 1, FlowStrategy.DIRECT,
                FlowControlBehavior.REJECT, False,
            ),
        )
        second = RuleRecord(
            "b",
            FlowRuleValue(
                "/second", "default", FlowGrade.THREAD, 2, FlowStrategy.DIRECT,
                FlowControlBehavior.REJECT, False,
            ),
        )
        version = _version(RuleKind.FLOW, first, second)

        first_encoding = self.encoder.encode_rule_version(version)
        second_encoding = self.encoder.encode_rule_version(version)

        self.assertEqual(first_encoding, second_encoding)
        self.assertEqual(
            [item["resource"] for item in json.loads(first_encoding)],
            ["/first", "/second"],
        )
        self.assertNotIn(b" ", first_encoding)

    def test_rejects_unknown_profile_and_conditionally_inactive_fields(self) -> None:
        unsupported_profile = _version(
            RuleKind.FLOW,
            RuleRecord(
                "flow-1",
                FlowRuleValue(
                    "/api/orders", "default", FlowGrade.QPS, 1,
                    FlowStrategy.DIRECT, FlowControlBehavior.REJECT, False,
                ),
            ),
            profile="sentinel-python-next",
        )
        with self.assertRaises(RulePublicationProfileUnsupported):
            self.encoder.encode_rule_version(unsupported_profile)

        inactive_cluster = ClusterRuleConfig(
            ClusterThresholdType.GLOBAL, False, 10, 1_000
        )
        cluster_version = _version(
            RuleKind.FLOW,
            RuleRecord(
                "flow-2",
                FlowRuleValue(
                    "/api/orders", "default", FlowGrade.QPS, 1,
                    FlowStrategy.DIRECT, FlowControlBehavior.REJECT, False,
                    cluster_config=inactive_cluster,
                ),
            ),
        )
        with self.assertRaises(RulePublicationValueUnsupported):
            self.encoder.encode_rule_version(cluster_version)

    def test_encodes_only_supported_rust_flow_subset_using_rust_native_count_shape(self) -> None:
        encoder = SentinelRuleVersionJsonEncoder("sentinel-rust-v1")
        version = _version(
            RuleKind.FLOW,
            RuleRecord(
                "flow-rust",
                FlowRuleValue(
                    "GET /api/hello",
                    "default",
                    FlowGrade.QPS,
                    3,
                    FlowStrategy.DIRECT,
                    FlowControlBehavior.REJECT,
                    False,
                ),
            ),
            profile="sentinel-rust-v1",
        )

        self.assertEqual(
            json.loads(encoder.encode_rule_version(version)),
            [
                {
                    "resource": "GET /api/hello",
                    "limitApp": "default",
                    "grade": 1,
                    "count": 3,
                    "strategy": 0,
                    "controlBehavior": 0,
                    "clusterMode": False,
                }
            ],
        )

        unsupported = _version(
            RuleKind.FLOW,
            RuleRecord(
                "flow-rust-warmup",
                FlowRuleValue(
                    "GET /api/hello",
                    "default",
                    FlowGrade.QPS,
                    3,
                    FlowStrategy.DIRECT,
                    FlowControlBehavior.QUEUEING,
                    False,
                    max_queueing_time_ms=100,
                ),
            ),
            profile="sentinel-rust-v1",
        )
        with self.assertRaises(RulePublicationValueUnsupported):
            encoder.encode_rule_version(unsupported)

        irrelevant_ratio = _version(
            RuleKind.DEGRADE,
            RuleRecord(
                "degrade-1",
                DegradeRuleValue(
                    "/api/payment", DegradeGrade.ERROR_COUNT, 5, 30, 10, 1_000,
                    slow_ratio_threshold=0.8,
                ),
            ),
        )
        with self.assertRaises(RulePublicationValueUnsupported):
            self.encoder.encode_rule_version(irrelevant_ratio)

    def test_rejects_non_finite_corrupt_persisted_values(self) -> None:
        rule = FlowRuleValue(
            "/api/orders", "default", FlowGrade.QPS, 1, FlowStrategy.DIRECT,
            FlowControlBehavior.REJECT, False,
        )
        object.__setattr__(rule, "count", float("nan"))
        version = _version(RuleKind.FLOW, RuleRecord("flow-1", rule))

        with self.assertRaises(RulePublicationValueUnsupported):
            self.encoder.encode_rule_version(version)

    def test_requires_non_empty_profile_configuration(self) -> None:
        for value in ("", "  ", None):
            with self.subTest(profile=value):
                with self.assertRaises(ValueError):
                    SentinelRuleVersionJsonEncoder(value)

    def test_encodes_go_v1_flow_using_the_go_sdk_wire_fields(self) -> None:
        version = _version(
            RuleKind.FLOW,
            RuleRecord(
                "console-flow-id",
                FlowRuleValue(
                    resource="GET /api/hello",
                    limit_app="default",
                    grade=FlowGrade.QPS,
                    count=2,
                    strategy=FlowStrategy.DIRECT,
                    control_behavior=FlowControlBehavior.REJECT,
                    cluster_mode=False,
                ),
            ),
            profile="sentinel-go-v1",
        )
        encoded = SentinelRuleVersionJsonEncoder("sentinel-go-v1").encode_rule_version(version)
        self.assertEqual(
            json.loads(encoded),
            [{
                "resource": "GET /api/hello",
                "threshold": 2,
                "statIntervalInMs": 1000,
                "tokenCalculateStrategy": 0,
                "controlBehavior": 0,
                "relationStrategy": 0,
                "refResource": "",
            }],
        )

    def test_java_and_go_expand_only_exponent_numbers_not_resource_strings(self) -> None:
        for profile, threshold_field in (
            ("sentinel-java-v1", "count"),
            ("sentinel-go-v1", "threshold"),
        ):
            version = _version(
                RuleKind.FLOW,
                RuleRecord(
                    "console-flow-id",
                    FlowRuleValue(
                        resource="GET /api/t07/1e85",
                        limit_app="default",
                        grade=FlowGrade.QPS,
                        count=0.0000001,
                        strategy=FlowStrategy.DIRECT,
                        control_behavior=FlowControlBehavior.REJECT,
                        cluster_mode=False,
                    ),
                ),
                profile=profile,
            )

            encoded = SentinelRuleVersionJsonEncoder(profile).encode_rule_version(version)
            decoded = json.loads(encoded)[0]

            self.assertEqual(decoded["resource"], "GET /api/t07/1e85")
            self.assertEqual(decoded[threshold_field], 0.0000001)
            self.assertIn(b"0.0000001", encoded)
            self.assertIn(b"GET /api/t07/1e85", encoded)

    def test_one_worker_encoder_can_route_multiple_exact_runtime_profiles(self) -> None:
        encoder = SentinelRuleVersionJsonEncoder(
            "sentinel-java-v1, sentinel-go-v1"
        )
        rule = RuleRecord(
            "console-flow-id",
            FlowRuleValue(
                resource="GET /api/hello",
                limit_app="default",
                grade=FlowGrade.QPS,
                count=2,
                strategy=FlowStrategy.DIRECT,
                control_behavior=FlowControlBehavior.REJECT,
                cluster_mode=False,
            ),
        )

        java = encoder.encode_rule_version(
            _version(RuleKind.FLOW, rule, profile="sentinel-java-v1")
        )
        go = encoder.encode_rule_version(
            _version(RuleKind.FLOW, rule, profile="sentinel-go-v1")
        )

        self.assertEqual(json.loads(java)[0]["count"], 2)
        self.assertEqual(json.loads(go)[0]["threshold"], 2)
        self.assertNotIn(b"threshold", java)
        self.assertNotIn(b"count", go)

        with self.assertRaises(RulePublicationProfileUnsupported):
            encoder.encode_rule_version(
                _version(RuleKind.FLOW, rule, profile="sentinel-python-v1")
            )

    def test_rejects_ambiguous_profile_lists(self) -> None:
        for value in (
            "sentinel-java-v1,",
            ",sentinel-go-v1",
            "sentinel-go-v1,sentinel-go-v1",
        ):
            with self.subTest(profile=value), self.assertRaises(ValueError):
                SentinelRuleVersionJsonEncoder(value)

    def test_java_and_go_profiles_reject_values_outside_the_runtime_subset(self) -> None:
        for profile in ("sentinel-java-v1", "sentinel-go-v1"):
            version = _version(
                RuleKind.FLOW,
                RuleRecord(
                    "console-flow-id",
                    FlowRuleValue(
                        resource="GET /api/hello",
                        limit_app="default",
                        grade=FlowGrade.QPS,
                        count=2,
                        strategy=FlowStrategy.CHAIN,
                        control_behavior=FlowControlBehavior.REJECT,
                        cluster_mode=False,
                        ref_resource="parent",
                    ),
                ),
                profile=profile,
            )
            with self.subTest(profile=profile), self.assertRaises(RulePublicationValueUnsupported):
                SentinelRuleVersionJsonEncoder(profile).encode_rule_version(version)


if __name__ == "__main__":
    unittest.main()
