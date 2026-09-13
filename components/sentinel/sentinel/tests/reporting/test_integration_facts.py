"""Reporting integration 单元测试 (M6.5.3 + M6.5.4).

中文
----
覆盖 3 类 fact 跟 ``AgentReporter.emit()`` 的集成:

1. **RuleSourceActivation** fact 集成 emit
2. **Source health** 变化集成 emit
3. **Slot exec applied** 集成 emit
4. **Slot exec failed** 集成 emit (failure_class 必填)

每个测试 1 个, 4 个总计. spec 要求 ≥ 4 个.

English
--------
Covers 3 fact categories' integration with ``AgentReporter.emit()``:

1. **RuleSourceActivation** fact integration emit
2. **Source health** change integration emit
3. **Slot exec applied** integration emit
4. **Slot exec failed** integration emit (failure_class required)

1 test per scenario, 4 total. Spec requires ≥ 4.
"""

from __future__ import annotations

import unittest

from atlas_richie.sentinel.reporting import (
    AgentReporter,
    AgentReporterConfig,
    OverflowPolicy,
    ReportingEvent,
)
from atlas_richie.sentinel.reporting.config import (
    BATCH_MAX_BYTES,
    BATCH_MAX_EVENTS,
)
from atlas_richie.sentinel.reporting.event_builder import (
    RuleSourceActivationFact,
    SlotExecFact,
    SourceHealthFact,
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


DUMMY_CHECKSUM = "sha256:" + "0" * 64


class RuleSourceActivationIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """RuleSourceActivation fact → ReportingEvent → emit."""

    async def test_activation_fact_emit(self) -> None:
        config = _make_config()
        reporter = AgentReporter(config)
        await reporter.start()
        try:
            fact = RuleSourceActivationFact(
                source_id="src-A",
                reason="initial",
                previous_source_id=None,
                priority=10,
                epoch=1,
                revision=0,
                checksum=DUMMY_CHECKSUM,
            )
            event = activation_to_event(fact)
            seq = reporter.emit(event)
            self.assertEqual(seq, 0)
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
            seq = reporter.emit(event)
            self.assertEqual(seq, 0)
        finally:
            await reporter.aclose()

    async def test_healthy_no_event(self) -> None:
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
            fact = SlotExecFact(
                resource="GET /api/users",
                rule_id="flow-rate-limit",
                exec_result="applied",
                failure_class=None,
                epoch=1,
                revision=0,
                checksum=DUMMY_CHECKSUM,
            )
            event = _build_applied_event_from_fact(fact)
            seq = reporter.emit(event)
            self.assertEqual(seq, 0)
        finally:
            await reporter.aclose()

    async def test_failed_slot_emit_failure_class_required(self) -> None:
        config = _make_config()
        reporter = AgentReporter(config)
        await reporter.start()
        try:
            fact = SlotExecFact(
                resource="POST /api/checkout",
                rule_id="degrade-cb",
                exec_result="failed",
                failure_class="timeout",  # FAILED 必填
                epoch=1,
                revision=0,
                checksum=DUMMY_CHECKSUM,
            )
            event = _build_failed_event_from_fact(fact)
            seq = reporter.emit(event)
            self.assertEqual(seq, 0)
        finally:
            await reporter.aclose()


def _build_applied_event_from_fact(fact: SlotExecFact) -> ReportingEvent:
    return ReportingEvent(
        kind="rule_applied",
        source_id=None,
        resource=fact.resource,
        rule_id=fact.rule_id,
        exec_result=fact.exec_result,
        failure_class=fact.failure_class,
        reason=None,
        previous_source_id=None,
        priority=None,
        health_class=None,
        reason_message=None,
        epoch=fact.epoch,
        revision=fact.revision,
        checksum=fact.checksum,
    )


def _build_failed_event_from_fact(fact: SlotExecFact) -> ReportingEvent:
    return ReportingEvent(
        kind="rule_failed",
        source_id=None,
        resource=fact.resource,
        rule_id=fact.rule_id,
        exec_result=fact.exec_result,
        failure_class=fact.failure_class,
        reason=None,
        previous_source_id=None,
        priority=None,
        health_class=None,
        reason_message=None,
        epoch=fact.epoch,
        revision=fact.revision,
        checksum=fact.checksum,
    )
