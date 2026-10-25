"""M6.5.1 event_builder 单测 — fact → envelope 转换.

中文
----
验证 3 类 fact (activation / source health / slot exec) 经
``event_builder`` 翻译成 6 个 ``ReportingEventKind`` 之一 + per-kind
payload (4 fields RuleSourceActivatedPayload / 6 fields RuleSourceHealthPayload
成组可选 / 7 fields RuleExecPayload).

English
--------
Verify that the 3 internal fact types are translated to the 6 V1
ReportingEventKind + per-kind payload (matching the wire spec
``docs/protocol/上报协议-01-envelope-v1.md``).

Note: fact dataclass 内部表示用 ``epoch`` / ``revision`` / ``checksum``
3 独立字段 (不是 ``version`` dict), 跟 M6.1 frozen 内部 RuleSourceVersion
一致; event_builder 负责映射到 wire payload 的
``rule_version_epoch`` / ``rule_version_revision`` /
``rule_version_checksum`` 3 字段.
"""
from __future__ import annotations

import unittest

from atlas_richie.contracts.reporting.v1 import (
    ExecResult,
    HealthClass,
    ReasonClass,
    ReportingEventKind,
)

from atlas_richie.sentinel.reporting._identity import ReporterIdentity
from atlas_richie.sentinel.reporting.event_builder import (
    RuleSourceActivationFact,
    SlotExecFact,
    SourceHealthFact,
    build_rule_applied,
    build_rule_blocked,
    build_rule_failed,
    build_rule_source_activated,
    build_source_degraded,
    build_source_stale,
)

DUMMY_CHECKSUM = "sha256:" + "a" * 64
IDENTITY = ReporterIdentity(instance_id="550e8400-e29b-41d4-a716-446655440000", startup_epoch=0)


class RuleSourceActivatedTest(unittest.TestCase):
    def test_activation_to_envelope(self) -> None:
        fact = RuleSourceActivationFact(
            source_id="src-A",
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        envelope = build_rule_source_activated(
            identity=IDENTITY, sequence=0, fact=fact
        )
        self.assertEqual(envelope.event_kind, ReportingEventKind.RULE_SOURCE_ACTIVATED.value)
        self.assertEqual(envelope.instance_id, IDENTITY.instance_id)
        self.assertEqual(envelope.startup_epoch, IDENTITY.startup_epoch)
        self.assertEqual(envelope.sequence, 0)
        self.assertEqual(envelope.event_payload["source_id"], "src-A")
        self.assertEqual(envelope.event_payload["rule_version_epoch"], 1)
        self.assertEqual(envelope.event_payload["rule_version_checksum"], DUMMY_CHECKSUM)


class SourceStaleTest(unittest.TestCase):
    def test_stale_with_version(self) -> None:
        fact = SourceHealthFact(
            source_id="src-A",
            health_class=HealthClass.STALE.value,
            reason_class=ReasonClass.EMPTY_DATA_ID.value,
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
            reason_message="nacos data_id empty",
        )
        envelope = build_source_stale(identity=IDENTITY, sequence=0, fact=fact)
        self.assertEqual(envelope.event_kind, ReportingEventKind.RULE_SOURCE_STALE.value)
        self.assertEqual(envelope.event_payload["source_id"], "src-A")
        self.assertEqual(envelope.event_payload["health_class"], HealthClass.STALE.value)
        self.assertEqual(envelope.event_payload["reason_class"], ReasonClass.EMPTY_DATA_ID.value)
        self.assertEqual(envelope.event_payload["rule_version_epoch"], 1)

    def test_stale_without_version(self) -> None:
        # V1 协议 §5.2: 3 rule_version_* 字段成组可选, 全部省略 (无 last-known-good)
        fact = SourceHealthFact(
            source_id="src-A",
            health_class=HealthClass.DISCONNECTED.value,
            reason_class=ReasonClass.NETWORK_UNAVAILABLE.value,
            epoch=None,
            revision=None,
            checksum=None,
            reason_message="",
        )
        envelope = build_source_stale(identity=IDENTITY, sequence=0, fact=fact)
        self.assertEqual(envelope.event_kind, ReportingEventKind.RULE_SOURCE_STALE.value)
        # 3 rule_version_* 字段全部省略
        self.assertNotIn("rule_version_epoch", envelope.event_payload)
        self.assertNotIn("rule_version_revision", envelope.event_payload)
        self.assertNotIn("rule_version_checksum", envelope.event_payload)


class SourceDegradedTest(unittest.TestCase):
    def test_degraded_to_envelope(self) -> None:
        fact = SourceHealthFact(
            source_id="src-A",
            health_class=HealthClass.DEGRADED.value,
            reason_class=ReasonClass.DECODE_FAILED.value,
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
            reason_message="",
        )
        envelope = build_source_degraded(identity=IDENTITY, sequence=0, fact=fact)
        self.assertEqual(envelope.event_kind, ReportingEventKind.RULE_SOURCE_DEGRADED.value)
        self.assertEqual(envelope.event_payload["health_class"], HealthClass.DEGRADED.value)


class RuleAppliedTest(unittest.TestCase):
    def test_applied_to_envelope(self) -> None:
        fact = SlotExecFact(
            source_id="src-A",
            rule_id="flow:/api/v1/users",
            exec_result=ExecResult.APPLIED.value,
            failure_class=None,
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        envelope = build_rule_applied(identity=IDENTITY, sequence=0, fact=fact)
        self.assertEqual(envelope.event_kind, ReportingEventKind.RULE_APPLIED.value)
        self.assertEqual(envelope.event_payload["source_id"], "src-A")
        self.assertEqual(envelope.event_payload["rule_id"], "flow:/api/v1/users")
        self.assertEqual(envelope.event_payload["exec_result"], ExecResult.APPLIED.value)
        self.assertIsNone(envelope.event_payload["failure_class"])

    def test_applied_with_failure_class_rejected(self) -> None:
        # V1 协议 §5.3: APPLIED 必须 None failure_class
        fact = SlotExecFact(
            source_id="src-A",
            rule_id="flow:/api/v1/users",
            exec_result=ExecResult.APPLIED.value,
            failure_class=ReasonClass.DECODE_FAILED.value,
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        with self.assertRaises(ValueError):
            build_rule_applied(identity=IDENTITY, sequence=0, fact=fact)


class RuleBlockedTest(unittest.TestCase):
    def test_blocked_to_envelope(self) -> None:
        fact = SlotExecFact(
            source_id="src-A",
            rule_id="flow:/api/v1/users",
            exec_result=ExecResult.BLOCKED.value,
            failure_class=None,
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        envelope = build_rule_blocked(identity=IDENTITY, sequence=0, fact=fact)
        self.assertEqual(envelope.event_kind, ReportingEventKind.RULE_BLOCKED.value)
        self.assertEqual(envelope.event_payload["exec_result"], ExecResult.BLOCKED.value)


class RuleFailedTest(unittest.TestCase):
    def test_failed_to_envelope(self) -> None:
        fact = SlotExecFact(
            source_id="src-A",
            rule_id="flow:/api/v1/users",
            exec_result=ExecResult.FAILED.value,
            failure_class=ReasonClass.DECODE_FAILED.value,
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        envelope = build_rule_failed(identity=IDENTITY, sequence=0, fact=fact)
        self.assertEqual(envelope.event_kind, ReportingEventKind.RULE_FAILED.value)
        self.assertEqual(envelope.event_payload["exec_result"], ExecResult.FAILED.value)
        self.assertEqual(envelope.event_payload["failure_class"], ReasonClass.DECODE_FAILED.value)

    def test_failed_with_none_failure_class_rejected(self) -> None:
        # V1 协议 §5.3: FAILED 必填 failure_class (ReasonClass 枚举)
        fact = SlotExecFact(
            source_id="src-A",
            rule_id="flow:/api/v1/users",
            exec_result=ExecResult.FAILED.value,
            failure_class=None,
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        with self.assertRaises(ValueError):
            build_rule_failed(identity=IDENTITY, sequence=0, fact=fact)

    def test_failed_with_unknown_failure_class_rejected(self) -> None:
        fact = SlotExecFact(
            source_id="src-A",
            rule_id="flow:/api/v1/users",
            exec_result=ExecResult.FAILED.value,
            failure_class="EXCEPTION_TYPE",  # 不在 ReasonClass 7 冻结值
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        with self.assertRaises(ValueError):
            build_rule_failed(identity=IDENTITY, sequence=0, fact=fact)


class EnvelopeSchemaTest(unittest.TestCase):
    def test_seven_fields_present(self) -> None:
        # V1 协议 §3.2 7 字段 frozen
        fact = RuleSourceActivationFact(
            source_id="src-A",
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        envelope = build_rule_source_activated(identity=IDENTITY, sequence=0, fact=fact)
        from dataclasses import fields as dc_fields
        names = {f.name for f in dc_fields(envelope)}
        self.assertEqual(names, {
            "protocol_version", "event_kind", "event_payload",
            "instance_id", "startup_epoch", "sequence", "captured_at",
        })


if __name__ == "__main__":
    unittest.main()
