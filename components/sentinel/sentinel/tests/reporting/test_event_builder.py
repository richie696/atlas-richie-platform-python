"""``event_builder`` 单元测试 (M6.5.3 + M6.5.4).

中文
----
覆盖 6 类 event 各自的 fact → envelope 翻译:

1. **RuleSourceActivation** fact → ``RULE_SOURCE_ACTIVATED`` envelope
2. **Source health stale** → ``RULE_SOURCE_STALE`` envelope (3 rule_version_*
   成组可选)
3. **Source health degraded** → ``RULE_SOURCE_DEGRADED`` envelope
4. **Slot exec applied** → ``RULE_APPLIED`` envelope (failure_class=None)
5. **Slot exec blocked** → ``RULE_BLOCKED`` envelope (failure_class=None)
6. **Slot exec failed** → ``RULE_FAILED`` envelope (failure_class 必填)

每个测试 1 个, 加 2 个 schema 校验测试 = 8 个. spec 要求 ≥ 4 个.

English
--------
Covers 6 event kinds' fact → envelope translation:

1. **RuleSourceActivation** fact → ``RULE_SOURCE_ACTIVATED`` envelope
2. **Source health stale** → ``RULE_SOURCE_STALE`` envelope (3
   rule_version_* group optional)
3. **Source health degraded** → ``RULE_SOURCE_DEGRADED`` envelope
4. **Slot exec applied** → ``RULE_APPLIED`` envelope (failure_class=None)
5. **Slot exec blocked** → ``RULE_BLOCKED`` envelope (failure_class=None)
6. **Slot exec failed** → ``RULE_FAILED`` envelope (failure_class required)

1 test per kind + 2 schema validation tests = 8 tests. Spec requires
≥ 4.
"""

from __future__ import annotations

import unittest

from atlas_richie.contracts.reporting.v1 import (
    PROTOCOL_VERSION,
    decode_envelope,
    encode_envelope,
)

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
from atlas_richie.sentinel.reporting.reporter import ReporterIdentity


IDENTITY = ReporterIdentity(
    instance_id="00000000-0000-4000-8000-000000000001",
    startup_epoch=12345,
)
DUMMY_CHECKSUM = "sha256:" + "0" * 64


class RuleSourceActivatedTest(unittest.TestCase):
    """RuleSourceActivation fact → RULE_SOURCE_ACTIVATED envelope."""

    def test_activation_to_envelope(self) -> None:
        fact = RuleSourceActivationFact(
            source_id="src-A",
            reason="initial",
            previous_source_id=None,
            priority=10,
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        envelope = build_rule_source_activated(
            identity=IDENTITY, sequence=0, fact=fact
        )
        self.assertEqual(envelope.event_kind, "rule_source_activated")
        self.assertEqual(envelope.instance_id, IDENTITY.instance_id)
        self.assertEqual(envelope.startup_epoch, IDENTITY.startup_epoch)
        self.assertEqual(envelope.sequence, 0)
        # payload 字段校验
        self.assertEqual(envelope.event_payload["source_id"], "src-A")
        self.assertEqual(envelope.event_payload["reason"], "initial")
        self.assertIsNone(envelope.event_payload["previous_source_id"])
        self.assertEqual(envelope.event_payload["priority"], 10)
        self.assertEqual(envelope.event_payload["rule_version_epoch"], 1)
        self.assertEqual(envelope.event_payload["rule_version_checksum"], DUMMY_CHECKSUM)
        # wire 序列化 round-trip
        raw = encode_envelope(envelope)
        decoded = decode_envelope(raw)
        self.assertEqual(decoded.event_kind, envelope.event_kind)
        self.assertEqual(decoded.event_payload, envelope.event_payload)


class SourceStaleTest(unittest.TestCase):
    """Source health stale → RULE_SOURCE_STALE envelope (3 rule_version_* 成组可选)."""

    def test_stale_with_version(self) -> None:
        fact = SourceHealthFact(
            source_id="src-A",
            health_class="stale",
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
            reason_message="source polling timeout",
        )
        envelope = build_source_stale(
            identity=IDENTITY, sequence=0, fact=fact
        )
        self.assertEqual(envelope.event_kind, "rule_source_stale")
        self.assertEqual(envelope.event_payload["source_id"], "src-A")
        self.assertEqual(envelope.event_payload["health_class"], "stale")
        self.assertEqual(envelope.event_payload["reason_message"], "source polling timeout")
        # 3 rule_version_* 字段都填了
        self.assertEqual(envelope.event_payload["rule_version_epoch"], 1)
        self.assertEqual(envelope.event_payload["rule_version_revision"], 0)
        self.assertEqual(envelope.event_payload["rule_version_checksum"], DUMMY_CHECKSUM)

    def test_stale_without_version(self) -> None:
        """首次加载失败: 3 rule_version_* 字段全 None (协议 §5.2 成组可选)."""
        fact = SourceHealthFact(
            source_id="src-A",
            health_class="stale",
            epoch=None,
            revision=None,
            checksum=None,
            reason_message="no last-known-good snapshot",
        )
        envelope = build_source_stale(
            identity=IDENTITY, sequence=0, fact=fact
        )
        # 3 字段全省略 (协议 §5.2)
        self.assertNotIn("rule_version_epoch", envelope.event_payload)
        self.assertNotIn("rule_version_revision", envelope.event_payload)
        self.assertNotIn("rule_version_checksum", envelope.event_payload)


class SourceDegradedTest(unittest.TestCase):
    """Source health degraded → RULE_SOURCE_DEGRADED envelope."""

    def test_degraded_to_envelope(self) -> None:
        fact = SourceHealthFact(
            source_id="src-B",
            health_class="degraded",
            epoch=2,
            revision=1,
            checksum=DUMMY_CHECKSUM,
            reason_message="partial snapshot loaded",
        )
        envelope = build_source_degraded(
            identity=IDENTITY, sequence=0, fact=fact
        )
        self.assertEqual(envelope.event_kind, "rule_source_degraded")
        self.assertEqual(envelope.event_payload["source_id"], "src-B")
        self.assertEqual(envelope.event_payload["health_class"], "degraded")
        # wire 序列化
        raw = encode_envelope(envelope)
        decoded = decode_envelope(raw)
        self.assertEqual(decoded.event_kind, "rule_source_degraded")


class RuleAppliedTest(unittest.TestCase):
    """Slot exec applied → RULE_APPLIED (failure_class=None)."""

    def test_applied_to_envelope(self) -> None:
        fact = SlotExecFact(
            resource="GET /api/users",
            rule_id="flow-rate-limit",
            exec_result="applied",
            failure_class=None,  # APPLIED 必须 None
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        envelope = build_rule_applied(
            identity=IDENTITY, sequence=0, fact=fact
        )
        self.assertEqual(envelope.event_kind, "rule_applied")
        self.assertEqual(envelope.event_payload["resource"], "GET /api/users")
        self.assertEqual(envelope.event_payload["rule_id"], "flow-rate-limit")
        self.assertEqual(envelope.event_payload["exec_result"], "applied")
        self.assertIsNone(envelope.event_payload["failure_class"])

    def test_applied_with_failure_class_rejected(self) -> None:
        """APPLIED + failure_class != None → 协议错 (协议 §5.3)."""
        fact = SlotExecFact(
            resource="r",
            rule_id="rule",
            exec_result="applied",
            failure_class="timeout",  # 错的
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        with self.assertRaises(ValueError) as cm:
            build_rule_applied(identity=IDENTITY, sequence=0, fact=fact)
        self.assertIn("failure_class=None", str(cm.exception))


class RuleBlockedTest(unittest.TestCase):
    """Slot exec blocked → RULE_BLOCKED (failure_class=None)."""

    def test_blocked_to_envelope(self) -> None:
        fact = SlotExecFact(
            resource="GET /api/orders",
            rule_id="flow-rate-limit",
            exec_result="blocked",
            failure_class=None,  # BLOCKED 必须 None
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        envelope = build_rule_blocked(
            identity=IDENTITY, sequence=0, fact=fact
        )
        self.assertEqual(envelope.event_kind, "rule_blocked")
        self.assertEqual(envelope.event_payload["exec_result"], "blocked")
        self.assertIsNone(envelope.event_payload["failure_class"])


class RuleFailedTest(unittest.TestCase):
    """Slot exec failed → RULE_FAILED (failure_class 必填)."""

    def test_failed_to_envelope(self) -> None:
        fact = SlotExecFact(
            resource="POST /api/checkout",
            rule_id="degrade-cb",
            exec_result="failed",
            failure_class="timeout",  # FAILED 必填
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        envelope = build_rule_failed(
            identity=IDENTITY, sequence=0, fact=fact
        )
        self.assertEqual(envelope.event_kind, "rule_failed")
        self.assertEqual(envelope.event_payload["exec_result"], "failed")
        self.assertEqual(envelope.event_payload["failure_class"], "timeout")

    def test_failed_with_none_failure_class_rejected(self) -> None:
        """FAILED + failure_class=None → 协议错 (协议 §5.3)."""
        fact = SlotExecFact(
            resource="r",
            rule_id="rule",
            exec_result="failed",
            failure_class=None,  # 错的
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        with self.assertRaises(ValueError) as cm:
            build_rule_failed(identity=IDENTITY, sequence=0, fact=fact)
        self.assertIn("failure_class", str(cm.exception))

    def test_failed_with_unknown_failure_class_rejected(self) -> None:
        """FAILED + failure_class 不在 ReasonClass 7 值 → 协议错."""
        fact = SlotExecFact(
            resource="r",
            rule_id="rule",
            exec_result="failed",
            failure_class="made_up_reason",  # 错的
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        with self.assertRaises(ValueError) as cm:
            build_rule_failed(identity=IDENTITY, sequence=0, fact=fact)
        self.assertIn("ReasonClass", str(cm.exception))


class EnvelopeSchemaTest(unittest.TestCase):
    """envelope 7 字段 (协议 §3.2) 全部齐全 + protocol_version 正确."""

    def test_seven_fields_present(self) -> None:
        fact = SlotExecFact(
            resource="r",
            rule_id="rule",
            exec_result="applied",
            failure_class=None,
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
        )
        envelope = build_rule_applied(
            identity=IDENTITY, sequence=0, fact=fact
        )
        # 7 字段齐全
        for field_name in (
            "protocol_version",
            "event_kind",
            "event_payload",
            "instance_id",
            "startup_epoch",
            "sequence",
            "captured_at",
        ):
            self.assertTrue(
                hasattr(envelope, field_name),
                f"envelope missing field {field_name}",
            )
        # protocol_version 正确
        self.assertEqual(envelope.protocol_version, PROTOCOL_VERSION)
        # captured_at 格式 (ISO 8601 UTC microsecond)
        self.assertTrue(envelope.captured_at.endswith("Z"))
        self.assertIn(".", envelope.captured_at)
