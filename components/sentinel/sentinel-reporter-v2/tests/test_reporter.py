from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

import pytest
from atlas_richie.contracts.reporting.v2 import (
    MAX_SAFE_INTEGER,
    MetricsReceipt,
    decode_metrics_snapshot,
    encode_metrics_receipt,
)
from atlas_richie.sentinel.engine.sentinel_engine import SentinelEngine
from atlas_richie.sentinel.metrics.registry import MetricRegistry
from atlas_richie.sentinel.metrics.snapshot import MetricSnapshot
from atlas_richie.sentinel.model.resource import Resource
from atlas_richie.sentinel.reporting import (
    MetricCapture,
    MetricCaptureSource,
    MetricsCaptureAdapter,
    MetricsReportingBuffer,
)
from atlas_richie.sentinel_reporter_v2 import (
    MetricsReporterErrorCode,
    MetricsTransportError,
    MetricsV2Reporter,
    MetricsV2ReporterConfig,
    ReporterFlushResult,
)

_EPOCH = UUID("7aaafa02-b778-40bc-b516-e008f25a19ef")
_NOW = datetime(2026, 10, 14, 2, 3, 4, tzinfo=UTC)


class _Clock:
    def utc_now(self):
        return _NOW

    def monotonic_ns(self):
        return 1_000_000_123


class _TimelineClock:
    def __init__(self, values):
        self._values = iter(values)

    def utc_now(self):
        return _NOW

    def monotonic_ns(self):
        return next(self._values)


class _Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    async def send(self, payload: bytes) -> bytes:
        self.payloads.append(payload)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response(payload)


def _valid_ack(payload: bytes, *, sequence: int = 1) -> bytes:
    snapshot = decode_metrics_snapshot(payload)
    return encode_metrics_receipt(
        MetricsReceipt(
            snapshot.reporter_id,
            snapshot.startup_epoch,
            sequence,
            sha256(payload).hexdigest(),
            _NOW,
        )
    )


def _capture(name="POST /orders", admitted=3, blocked=1):
    return MetricCapture(
        MetricCaptureSource.ENTRY,
        MetricSnapshot(
            at_ns=1,
            labels={"resource": name},
            admitted=admitted,
            blocked=blocked,
        ),
    )


def _reporter(transport, *, max_attempts=3, buffer=None):
    return MetricsV2Reporter(
        MetricsV2ReporterConfig("reporter-a", max_attempts=max_attempts),
        transport,
        clock=_Clock(),
        buffer=buffer,
        startup_epoch=_EPOCH,
    )


@pytest.mark.asyncio
async def test_acknowledges_only_exact_receipt_and_advances_sequence() -> None:
    transport = _Transport([lambda payload: _valid_ack(payload)])
    reporter = _reporter(transport)
    assert reporter.try_enqueue(_capture()) is True

    outcome = await reporter.flush_once()

    assert outcome is ReporterFlushResult.ACKNOWLEDGED
    assert reporter.next_sequence == 2
    assert len(transport.payloads) == 1
    assert decode_metrics_snapshot(transport.payloads[0]).sequence == 1


@pytest.mark.asyncio
async def test_uncertain_failure_retries_identical_bytes_and_identity() -> None:
    transport = _Transport(
        [
            MetricsTransportError(MetricsReporterErrorCode.TRANSPORT_UNAVAILABLE),
            lambda payload: _valid_ack(payload),
        ]
    )
    reporter = _reporter(transport)
    reporter.try_enqueue(_capture())

    assert await reporter.flush_once() is ReporterFlushResult.RETRY_PENDING
    assert reporter.next_sequence == 1
    assert reporter.retry_delay_seconds() == 0.25
    assert await reporter.flush_once() is ReporterFlushResult.ACKNOWLEDGED
    assert transport.payloads[0] == transport.payloads[1]
    assert decode_metrics_snapshot(transport.payloads[1]).sequence == 1
    assert reporter.next_sequence == 2


@pytest.mark.asyncio
async def test_mismatched_receipt_is_not_treated_as_durable_ack() -> None:
    transport = _Transport([lambda payload: _valid_ack(payload, sequence=9)])
    reporter = _reporter(transport, max_attempts=1)
    reporter.try_enqueue(_capture())

    assert await reporter.flush_once() is ReporterFlushResult.DROPPED_AFTER_RETRIES
    assert reporter.next_sequence == 2
    assert reporter.dropped_after_retries == 1


@pytest.mark.parametrize("mismatch", ("reporter", "epoch", "sequence", "digest"))
@pytest.mark.asyncio
async def test_receipt_identity_mismatch_never_acknowledges_payload(mismatch) -> None:
    def mismatched_ack(payload):
        snapshot = decode_metrics_snapshot(payload)
        return encode_metrics_receipt(
            MetricsReceipt(
                reporter_id=(
                    "reporter-other" if mismatch == "reporter" else snapshot.reporter_id
                ),
                startup_epoch=(
                    UUID("c026816b-a286-4f9b-a030-6d198b2f0522")
                    if mismatch == "epoch"
                    else snapshot.startup_epoch
                ),
                sequence=snapshot.sequence + (1 if mismatch == "sequence" else 0),
                body_sha256=(
                    "0" * 64 if mismatch == "digest" else sha256(payload).hexdigest()
                ),
                received_at=_NOW,
            )
        )

    transport = _Transport([mismatched_ack])
    reporter = _reporter(transport, max_attempts=1)
    reporter.try_enqueue(_capture())

    assert await reporter.flush_once() is ReporterFlushResult.DROPPED_AFTER_RETRIES
    assert reporter.retry_count == 1
    assert reporter.last_error_type == "MetricsReceiptMismatchError"
    assert reporter.next_sequence == 2


@pytest.mark.asyncio
async def test_monotonic_capture_window_is_relative_and_regression_fails_closed() -> (
    None
):
    transport = _Transport([lambda payload: _valid_ack(payload)])
    reporter = MetricsV2Reporter(
        MetricsV2ReporterConfig("reporter-a"),
        transport,
        clock=_TimelineClock((100, 350)),
        startup_epoch=_EPOCH,
    )
    reporter.try_enqueue(_capture())

    assert await reporter.flush_once() is ReporterFlushResult.ACKNOWLEDGED
    snapshot = decode_metrics_snapshot(transport.payloads[0])
    assert snapshot.capture_elapsed_ns == 250

    regressing_transport = _Transport([])
    regressing_reporter = MetricsV2Reporter(
        MetricsV2ReporterConfig("reporter-a"),
        regressing_transport,
        clock=_TimelineClock((500, 499)),
        startup_epoch=_EPOCH,
    )
    regressing_reporter.try_enqueue(_capture())
    with pytest.raises(RuntimeError, match="monotonic clock regressed"):
        await regressing_reporter.flush_once()
    assert regressing_transport.payloads == []
    assert regressing_reporter.next_sequence == 1


@pytest.mark.asyncio
async def test_sequence_exhaustion_never_wraps_or_sends() -> None:
    transport = _Transport([])
    reporter = _reporter(transport)
    reporter._next_sequence = MAX_SAFE_INTEGER + 1
    reporter.try_enqueue(_capture())

    with pytest.raises(RuntimeError, match="sequence is exhausted"):
        await reporter.flush_once()

    assert transport.payloads == []
    assert reporter.next_sequence == MAX_SAFE_INTEGER + 1


@pytest.mark.asyncio
async def test_capture_window_over_ten_seconds_is_preserved_for_collector_rebaseline() -> (
    None
):
    transport = _Transport([lambda payload: _valid_ack(payload)])
    elapsed_ns = 10_000_000_001
    reporter = MetricsV2Reporter(
        MetricsV2ReporterConfig("reporter-a"),
        transport,
        clock=_TimelineClock((100, 100 + elapsed_ns)),
        startup_epoch=_EPOCH,
    )
    reporter.try_enqueue(_capture())

    assert await reporter.flush_once() is ReporterFlushResult.ACKNOWLEDGED
    assert (
        decode_metrics_snapshot(transport.payloads[0]).capture_elapsed_ns == elapsed_ns
    )


@pytest.mark.asyncio
async def test_capture_enqueue_is_local_and_capacity_rejection_is_explicit() -> None:
    transport = _Transport([])
    buffer = MetricsReportingBuffer(capacity=1)
    reporter = _reporter(transport, buffer=buffer)

    assert reporter.try_enqueue(_capture()) is True
    assert reporter.try_enqueue(_capture("GET /ready")) is False
    assert transport.payloads == []
    with pytest.raises(TypeError, match="MetricCapture"):
        reporter.try_enqueue("not-a-capture")


@pytest.mark.asyncio
async def test_engine_entry_reaches_local_port_without_network_io() -> None:
    transport = _Transport([lambda payload: _valid_ack(payload)])
    reporter = _reporter(transport)
    capture_adapter = MetricsCaptureAdapter(reporter)
    registry = MetricRegistry(sink=capture_adapter.metric_sink)
    engine = SentinelEngine(metric_registry=registry)

    async with engine, engine.entry(Resource("orders")):
        pass

    assert transport.payloads == []
    assert reporter.pending_count > 0
    assert await reporter.flush_once() is ReporterFlushResult.ACKNOWLEDGED
    assert len(transport.payloads) == 1


@pytest.mark.asyncio
async def test_257th_active_resource_is_rejected_and_counted_without_eviction() -> None:
    reporter = _reporter(_Transport([]))

    for index in range(256):
        assert reporter.try_enqueue(_capture(f"resource-{index:03}")) is True

    assert reporter.try_enqueue(_capture("resource-overflow")) is False
    assert reporter.rejected_resource_count == 1
    assert reporter.try_enqueue(_capture("resource-000", admitted=9)) is True
    assert reporter.rejected_resource_count == 1


@pytest.mark.asyncio
async def test_all_retries_are_bounded_then_report_explicit_drop() -> None:
    transport = _Transport(
        [
            MetricsTransportError(MetricsReporterErrorCode.TRANSPORT_UNAVAILABLE),
            MetricsTransportError(MetricsReporterErrorCode.TRANSPORT_UNAVAILABLE),
        ]
    )
    reporter = _reporter(transport, max_attempts=2)
    reporter.try_enqueue(_capture())

    assert await reporter.flush_once() is ReporterFlushResult.RETRY_PENDING
    assert await reporter.flush_once() is ReporterFlushResult.DROPPED_AFTER_RETRIES
    assert reporter.dropped_after_retries == 1
    assert reporter.next_sequence == 2


def test_retry_configuration_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="retry delay bounds"):
        MetricsV2ReporterConfig("reporter-a", retry_base_seconds=float("nan"))
