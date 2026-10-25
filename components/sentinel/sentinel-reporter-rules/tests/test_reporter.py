"""Focused lifecycle, queue, retry, and Repository integration checks."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from atlas_richie.sentinel.rules import (
    RuleRepository,
    RuleSnapshot,
    RuleTargetKind,
    RuleTargetProvenance,
    RuleVersion,
)
from atlas_richie.sentinel_reporter_rules import (
    RulePublicationReceiptProducer,
    RulePublicationReceiptReporter,
    RulePublicationReceiptReporterConfig,
    RuleReceiptDeliveryCode,
    RuleReceiptDeliveryError,
)


def _snapshot(revision: int) -> RuleSnapshot:
    provenance = RuleTargetProvenance(
        binding_id=f"binding-{revision}",
        publication_id=f"publication-{revision}",
        target_version_id=f"version-{revision}",
        publication_sequence=revision,
        rule_kind=RuleTargetKind.FLOW,
        profile_id="managed-v1",
        payload_sha256=f"{revision:064x}",
    )
    return RuleSnapshot(
        version=RuleVersion(epoch=1, revision=revision, checksum=f"{revision:064x}"),
        rules={},
        source_id="test",
        provenance=(provenance,),
    )


def test_reporter_configuration_rejects_unbounded_queue_and_invalid_retry() -> None:
    with pytest.raises(ValueError, match="max_pending"):
        RulePublicationReceiptReporterConfig(max_pending=4097)
    with pytest.raises(ValueError, match="retry delay"):
        RulePublicationReceiptReporterConfig(retry_base_seconds=2, retry_max_seconds=1)


class _RecordingTransport:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []
        self.closed = False

    async def send(self, payload: bytes) -> None:
        self.payloads.append(payload)

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_repository_apply_is_reported_and_close_is_idempotent() -> None:
    repository = RuleRepository()
    transport = _RecordingTransport()
    reporter = RulePublicationReceiptReporter(
        RulePublicationReceiptProducer(uuid4()), transport
    )
    await reporter.start(repository)

    assert repository.apply_snapshot(_snapshot(1))
    await reporter.drain()
    await reporter.aclose()
    await reporter.aclose()

    assert len(transport.payloads) == 1
    assert reporter.stats.accepted == reporter.stats.delivered == 1
    assert reporter.stats.pending == 0
    assert transport.closed


@pytest.mark.asyncio
async def test_retry_sends_exact_same_bytes_and_keeps_queue_order() -> None:
    repository = RuleRepository()
    payloads: list[bytes] = []
    sleeps: list[float] = []

    class RetryOnceTransport(_RecordingTransport):
        async def send(self, payload: bytes) -> None:
            payloads.append(payload)
            if len(payloads) == 1:
                raise RuleReceiptDeliveryError(
                    RuleReceiptDeliveryCode.TRANSPORT_UNAVAILABLE, retryable=True
                )

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    transport = RetryOnceTransport()
    reporter = RulePublicationReceiptReporter(
        RulePublicationReceiptProducer(uuid4()),
        transport,
        RulePublicationReceiptReporterConfig(
            max_attempts=2,
            retry_base_seconds=0.001,
            retry_max_seconds=0.001,
        ),
        sleep=record_sleep,
    )
    await reporter.start(repository)
    assert repository.apply_snapshot(_snapshot(1))
    await reporter.drain()
    await reporter.aclose()

    assert len(payloads) == 2
    assert payloads[0] == payloads[1]
    assert sleeps == [0.001]
    assert reporter.stats.retries == 1
    assert reporter.stats.delivered == 1


@pytest.mark.asyncio
async def test_full_queue_drops_whole_apply_batch_without_blocking_repository() -> None:
    repository = RuleRepository()
    started = asyncio.Event()
    release = asyncio.Event()

    class HeldTransport(_RecordingTransport):
        async def send(self, payload: bytes) -> None:
            self.payloads.append(payload)
            started.set()
            await release.wait()

    transport = HeldTransport()
    reporter = RulePublicationReceiptReporter(
        RulePublicationReceiptProducer(uuid4()),
        transport,
        RulePublicationReceiptReporterConfig(max_pending=1),
    )
    await reporter.start(repository)
    assert repository.apply_snapshot(_snapshot(1))
    await asyncio.wait_for(started.wait(), timeout=1)
    assert repository.apply_snapshot(_snapshot(2))
    assert reporter.stats.queue_full == 1
    assert reporter.stats.pending == 1

    release.set()
    await reporter.drain()
    await reporter.aclose()
    assert reporter.stats.delivered == 1


@pytest.mark.asyncio
async def test_permanent_failure_is_counted_and_later_receipts_continue() -> None:
    repository = RuleRepository()

    class RejectFirstTransport(_RecordingTransport):
        async def send(self, payload: bytes) -> None:
            self.payloads.append(payload)
            if len(self.payloads) == 1:
                raise RuleReceiptDeliveryError(
                    RuleReceiptDeliveryCode.PERMANENT_REMOTE, retryable=False
                )

    transport = RejectFirstTransport()
    reporter = RulePublicationReceiptReporter(
        RulePublicationReceiptProducer(uuid4()),
        transport,
        RulePublicationReceiptReporterConfig(max_attempts=1),
    )
    await reporter.start(repository)
    assert repository.apply_snapshot(_snapshot(1))
    assert repository.apply_snapshot(_snapshot(2))
    await reporter.drain()
    await reporter.aclose()

    assert len(transport.payloads) == 2
    assert reporter.stats.delivery_failed == 1
    assert reporter.stats.delivered == 1


@pytest.mark.asyncio
async def test_close_abandons_undelivered_memory_queue_with_visible_count() -> None:
    repository = RuleRepository()
    started = asyncio.Event()

    class NeverCompletesTransport(_RecordingTransport):
        async def send(self, payload: bytes) -> None:
            self.payloads.append(payload)
            started.set()
            await asyncio.Event().wait()

    transport = NeverCompletesTransport()
    reporter = RulePublicationReceiptReporter(
        RulePublicationReceiptProducer(uuid4()),
        transport,
        RulePublicationReceiptReporterConfig(shutdown_timeout_seconds=0.01),
    )
    await reporter.start(repository)
    assert repository.apply_snapshot(_snapshot(1))
    await asyncio.wait_for(started.wait(), timeout=1)
    await reporter.aclose()

    assert reporter.stats.abandoned_on_close == 1
    assert reporter.stats.pending == 0
    assert transport.closed


@pytest.mark.asyncio
async def test_post_close_repository_events_are_ignored() -> None:
    repository = RuleRepository()
    transport = _RecordingTransport()
    reporter = RulePublicationReceiptReporter(
        RulePublicationReceiptProducer(uuid4()), transport
    )
    await reporter.start(repository)
    await reporter.aclose()

    assert repository.apply_snapshot(_snapshot(1))
    assert reporter.stats.accepted == 0
    assert reporter.stats.pending == 0
