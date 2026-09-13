"""Reporting integration 单元测试 (M6.5.3 + M6.5.4).

中文
----
覆盖 3 类 fact 跟 ``AgentReporter.emit()`` 的集成:

1. **RuleSourceActivation** fact 集成 emit (M6.1 frozen → ReportingEvent)
2. **Source health** 变化集成 emit (SourceHealthChange → ReportingEvent)
3. **Slot exec applied** 集成 emit (Outcome + RuleSnapshot → ReportingEvent)
4. **Slot exec failed** 集成 emit (failure_class 必填)

每个测试 1 个, 4 个总计. spec 要求 ≥ 4 个.

English
--------
Covers 3 fact categories' integration with ``AgentReporter.emit()``:

1. **RuleSourceActivation** fact integration emit (M6.1 frozen → ReportingEvent)
2. **Source health** change integration emit (SourceHealthChange → ReportingEvent)
3. **Slot exec applied** integration emit (Outcome + RuleSnapshot → ReportingEvent)
4. **Slot exec failed** integration emit (failure_class required)

1 test per scenario, 4 total. Spec requires ≥ 4.
"""

from __future__ import annotations

import unittest

from atlas_richie.sentinel.model.outcome import Outcome, OutcomeKind
from atlas_richie.sentinel.model.resource import Resource
from atlas_richie.sentinel.reporting import (
    AgentReporter,
    AgentReporterConfig,
    OverflowPolicy,
)
from atlas_richie.sentinel.reporting.config import (
    BATCH_MAX_BYTES,
    BATCH_MAX_EVENTS,
)
from atlas_richie.sentinel.reporting.integration.rule_source_activation import (
    activation_to_event,
)
from atlas_richie.sentinel.reporting.integration.slot_chain import (
    outcome_to_event,
)
from atlas_richie.sentinel.reporting.integration.source_health import (
    SourceHealthChange,
    health_change_to_event,
)
from atlas_richie.sentinel.rules.snapshot import RuleSnapshot, RuleVersion
from atlas_richie.sentinel.source._supervisor.activation import RuleSourceActivation


DUMMY_CHECKSUM = "0" * 64  # RuleVersion expects 64-char hex (no "sha256:" prefix)
RULE_VERSION = RuleVersion(epoch=1, revision=0, checksum=DUMMY_CHECKSUM)
SNAPSHOT = RuleSnapshot(version=RULE_VERSION, source_id="src-A")


def _make_config() -> AgentReporterConfig:
    return AgentReporterConfig(
        collector_address="127.0.0.1:18765",
        auth_token="0123456789abcdef",
        instance_id_persistence_path=None,
        outbox_max_size=100,
        outbox_overflow_policy=OverflowPolicy.DROP_OLDEST,
        batch_max_events=BATCH_MAX_EVENTS,
        batch_max_bytes=BATCH_MAX_BYTES,
        batch_send_interval_ns=100_000_000,
        max_contiguous_sequence=0,
        connect_timeout_ns=2_000_000_000,
        request_timeout_ns=2_000_000_000,
        reconnect_initial_ns=10_000_000,
        reconnect_max_ns=100_000_000,
        reconnect_jitter_ns=0,
    )


class RuleSourceActivationIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """RuleSourceActivation fact (M6.1 frozen) → ReportingEvent → emit."""

    async def test_activation_fact_emit(self) -> None:
        config = _make_config()
        reporter = AgentReporter(config)
        await reporter.start()
        try:
            fact = RuleSourceActivation(
                source_id="src-A",
                previous_source_id=None,
                version=RULE_VERSION,
                reason="initial",
            )
            event = activation_to_event(fact)
            self.assertIsNotNone(event)
            self.assertEqual(event.kind, "RULE_SOURCE_ACTIVATED")
            self.assertEqual(event.source_id, "src-A")
            seq = reporter.emit(event)
            # outbox 序列从 1 开始 (M6.5.1 协议 BUG 收口, sequence 1-based)
            self.assertEqual(seq, 1)
        finally:
            await reporter.aclose()


class SourceHealthIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Source health 变化 → ReportingEvent → emit."""

    async def test_stale_health_emit(self) -> None:
        config = _make_config()
        reporter = AgentReporter(config)
        await reporter.start()
        try:
            change = SourceHealthChange(
                source_id="src-A",
                health_class="stale",
                epoch=1,
                revision=0,
                checksum=DUMMY_CHECKSUM,
                reason_message="polling timeout",
            )
            event = health_change_to_event(change)
            self.assertIsNotNone(event)
            self.assertEqual(event.kind, "RULE_SOURCE_STALE")
            self.assertEqual(event.health_class, "stale")
            seq = reporter.emit(event)
            # outbox 序列从 1 开始 (M6.5.1 协议 BUG 收口, sequence 1-based)
            self.assertEqual(seq, 1)
        finally:
            await reporter.aclose()

    def test_healthy_no_event(self) -> None:
        """healthy 状态不产生 event (避免 noise)."""
        change = SourceHealthChange(
            source_id="src-A",
            health_class="healthy",
            epoch=1,
            revision=0,
            checksum=DUMMY_CHECKSUM,
            reason_message="all good",
        )
        with self.assertRaises(ValueError):
            health_change_to_event(change)


class SlotExecIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Slot chain 执行结果 → ReportingEvent → emit."""

    async def test_applied_slot_emit(self) -> None:
        config = _make_config()
        reporter = AgentReporter(config)
        await reporter.start()
        try:
            outcome = Outcome(
                resource=Resource(name="GET /api/users"),
                kind=OutcomeKind.SUCCEEDED,
            )
            event = outcome_to_event(outcome, SNAPSHOT)
            self.assertIsNotNone(event)
            self.assertEqual(event.kind, "RULE_APPLIED")
            self.assertEqual(event.exec_result, "APPLIED")
            self.assertIsNone(event.failure_class)
            seq = reporter.emit(event)
            # outbox 序列从 1 开始 (M6.5.1 协议 BUG 收口, sequence 1-based)
            self.assertEqual(seq, 1)
        finally:
            await reporter.aclose()

    async def test_failed_slot_emit_failure_class_required(self) -> None:
        config = _make_config()
        reporter = AgentReporter(config)
        await reporter.start()
        try:
            outcome = Outcome(
                resource=Resource(name="POST /api/checkout"),
                kind=OutcomeKind.FAILED,
                error=TimeoutError("timeout while calling downstream"),
            )
            event = outcome_to_event(outcome, SNAPSHOT)
            self.assertIsNotNone(event)
            self.assertEqual(event.kind, "RULE_FAILED")
            self.assertEqual(event.exec_result, "FAILED")
            # failure_class 由 _classify_failure(error_message) 推断 → "NETWORK_TIMEOUT"
            self.assertEqual(event.failure_class, "NETWORK_TIMEOUT")
            seq = reporter.emit(event)
            # outbox 序列从 1 开始 (M6.5.1 协议 BUG 收口, sequence 1-based)
            self.assertEqual(seq, 1)
        finally:
            await reporter.aclose()


if __name__ == "__main__":
    unittest.main()
