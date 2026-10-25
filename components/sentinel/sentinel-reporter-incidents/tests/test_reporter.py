from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

import pytest
from atlas_richie.contracts.incidents.v1 import (
    IncidentEventReceiptV1,
    IncidentEventV1,
    IncidentSeverity,
    ResponseTimeFact,
    encode_incident_event,
    encode_incident_receipt,
)

from atlas_richie.sentinel_reporter_incidents import (
    IncidentEventReporter,
    IncidentPermanentRemoteError,
    IncidentRemoteErrorCode,
    IncidentReporterConfig,
    IncidentReporterError,
    IncidentReporterErrorCode,
    IncidentRetryableRemoteError,
    IncidentTransportUnavailableError,
)

_EVENT_ID = UUID("0c79e702-95b7-4d22-8fdc-f5057e5b1090")
_EPOCH = UUID("3cf8a5b6-0126-45d7-9639-39159fc6b92e")


def _event() -> IncidentEventV1:
    return IncidentEventV1(
        event_id=_EVENT_ID,
        process_epoch=_EPOCH,
        occurred_at=datetime(2026, 10, 15, tzinfo=UTC),
        severity=IncidentSeverity.WARNING,
        fact=ResponseTimeFact(p95_ms=125.0, threshold_ms=100.0),
    )


class _Transport:
    def __init__(self, outcomes: list[bytes | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.payloads: list[bytes] = []
        self.closed = False

    async def send(self, payload: bytes) -> bytes:
        self.payloads.append(payload)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def aclose(self) -> None:
        self.closed = True


def _receipt_body(payload: bytes, event_id: UUID = _EVENT_ID) -> bytes:
    return encode_incident_receipt(
        IncidentEventReceiptV1(
            event_id=event_id,
            body_sha256=hashlib.sha256(payload).hexdigest(),
            received_at=datetime(2026, 10, 15, 0, 0, 1, tzinfo=UTC),
        )
    )


@pytest.mark.asyncio
async def test_report_returns_only_exact_durable_ack_and_closes_owned_transport() -> (
    None
):
    payload = encode_incident_event(_event())
    transport = _Transport([_receipt_body(payload)])
    reporter = IncidentEventReporter(transport)

    receipt = await reporter.report(_event())
    await reporter.aclose()

    assert receipt.event_id == _EVENT_ID
    assert receipt.body_sha256 == hashlib.sha256(transport.payloads[0]).hexdigest()
    assert len(transport.payloads) == 1
    assert transport.closed is True


@pytest.mark.asyncio
async def test_report_retries_with_byte_identical_body_then_accepts_durable_ack() -> (
    None
):
    class _RetryTransport(_Transport):
        async def send(self, payload: bytes) -> bytes:
            self.payloads.append(payload)
            if len(self.payloads) == 1:
                raise IncidentTransportUnavailableError()
            return _receipt_body(payload)

    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    transport = _RetryTransport([])
    reporter = IncidentEventReporter(
        transport,
        IncidentReporterConfig(max_attempts=2, retry_base_seconds=0.01),
        sleep=sleep,
    )
    receipt = await reporter.report(_event())

    assert receipt.event_id == _EVENT_ID
    assert len(transport.payloads) == 2
    assert transport.payloads[0] == transport.payloads[1]
    assert delays == [0.01]


@pytest.mark.asyncio
async def test_report_retries_transient_remote_status_with_same_body_and_is_bounded():
    class _TransientRemoteTransport(_Transport):
        async def send(self, payload: bytes) -> bytes:
            self.payloads.append(payload)
            if len(self.payloads) <= 2:
                raise IncidentRetryableRemoteError(
                    status_code=503,
                    remote_code=IncidentRemoteErrorCode.SERVICE_UNAVAILABLE,
                )
            return _receipt_body(payload)

    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    transport = _TransientRemoteTransport([])
    reporter = IncidentEventReporter(
        transport,
        IncidentReporterConfig(
            max_attempts=3,
            retry_base_seconds=0.01,
            retry_max_seconds=0.02,
        ),
        sleep=sleep,
    )

    receipt = await reporter.report(_event())

    assert receipt.event_id == _EVENT_ID
    assert len(transport.payloads) == 3
    assert transport.payloads[0] == transport.payloads[1] == transport.payloads[2]
    assert delays == [0.01, 0.02]


@pytest.mark.asyncio
async def test_report_does_not_retry_permanent_remote_idempotency_conflict():
    conflict = IncidentPermanentRemoteError(
        status_code=409,
        remote_code=IncidentRemoteErrorCode.IDEMPOTENCY_CONFLICT,
    )
    transport = _Transport([conflict, _receipt_body(encode_incident_event(_event()))])
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    reporter = IncidentEventReporter(
        transport,
        IncidentReporterConfig(max_attempts=5, retry_base_seconds=0.01),
        sleep=sleep,
    )

    with pytest.raises(IncidentPermanentRemoteError) as raised:
        await reporter.report(_event())

    assert raised.value.status_code == 409
    assert raised.value.remote_code is IncidentRemoteErrorCode.IDEMPOTENCY_CONFLICT
    assert len(transport.payloads) == 1
    assert delays == []


@pytest.mark.asyncio
async def test_report_rejects_ack_for_another_event_without_retry() -> None:
    event = _event()
    payload = encode_incident_event(event)
    transport = _Transport(
        [_receipt_body(payload, UUID("3d33ad73-9a61-4090-b603-7eae645a3fe4"))]
    )
    reporter = IncidentEventReporter(transport)

    with pytest.raises(IncidentReporterError) as raised:
        await reporter.report(event)

    assert raised.value.code is IncidentReporterErrorCode.RECEIPT_MISMATCH
    assert len(transport.payloads) == 1


@pytest.mark.asyncio
async def test_report_exhaustion_redacts_transport_exception() -> None:
    transport = _Transport([OSError("secret-bearing transport detail")])
    reporter = IncidentEventReporter(
        transport,
        IncidentReporterConfig(max_attempts=1),
    )

    with pytest.raises(IncidentReporterError) as raised:
        await reporter.report(_event())

    assert raised.value.code is IncidentReporterErrorCode.TRANSPORT_UNAVAILABLE
    assert "secret-bearing" not in str(raised.value)


def test_reporter_config_rejects_unbounded_or_invalid_retry_settings() -> None:
    with pytest.raises(ValueError):
        IncidentReporterConfig(max_attempts=0)
    with pytest.raises(ValueError):
        IncidentReporterConfig(retry_base_seconds=0)
    with pytest.raises(ValueError):
        IncidentReporterConfig(retry_base_seconds=2, retry_max_seconds=1)
