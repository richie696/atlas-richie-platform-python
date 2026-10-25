"""Strict serialization contract tests for Incident Event Protocol V1."""

from __future__ import annotations

import hashlib
import unittest
from datetime import UTC, datetime
from uuid import UUID

from atlas_richie.contracts.incidents.v1 import (
    INCIDENT_EVENT_PROTOCOL_V1,
    IncidentEventReceiptV1,
    IncidentEventV1,
    IncidentProtocolError,
    IncidentProtocolErrorCode,
    IncidentSeverity,
    ResourcePressureFact,
    ResourcePressureMetric,
    ResponseTimeFact,
    decode_incident_event,
    decode_incident_receipt,
    encode_incident_event,
    encode_incident_receipt,
)

_EVENT_ID = UUID("0df0768b-fbc4-42f6-852a-2de2f146e204")
_EPOCH = UUID("cf5991b7-c790-465a-a385-3eaf99d11e5d")
_OCCURRED_AT = datetime(2026, 10, 15, 1, 2, 3, 456789, tzinfo=UTC)


class IncidentEventProtocolTests(unittest.TestCase):
    def test_round_trips_resource_pressure_and_response_time(self):
        events = (
            IncidentEventV1(
                event_id=_EVENT_ID,
                process_epoch=_EPOCH,
                occurred_at=_OCCURRED_AT,
                severity=IncidentSeverity.WARNING,
                fact=ResourcePressureFact(ResourcePressureMetric.CPU_RATIO, 0.91, 0.85),
            ),
            IncidentEventV1(
                event_id=_EVENT_ID,
                process_epoch=_EPOCH,
                occurred_at=_OCCURRED_AT,
                severity=IncidentSeverity.CRITICAL,
                fact=ResponseTimeFact(220.5, 200.0),
            ),
        )

        for event in events:
            body = encode_incident_event(event)
            assert decode_incident_event(body) == event
            assert body == encode_incident_event(event)
            assert b"environment" not in body
            assert b"traceback" not in body

    def test_receipt_binds_event_to_exact_request_body_digest(self):
        body = encode_incident_event(_resource_event())
        receipt = IncidentEventReceiptV1(
            event_id=_EVENT_ID,
            body_sha256=hashlib.sha256(body).hexdigest(),
            received_at=_OCCURRED_AT,
        )

        encoded = encode_incident_receipt(receipt)

        assert decode_incident_receipt(encoded) == receipt
        assert INCIDENT_EVENT_PROTOCOL_V1.encode() in encoded

    def test_rejects_unsupported_duplicate_unknown_and_nonfinite_data(self):
        invalid_bodies = (
            (
                b'{"protocol_version":"wrong"}',
                IncidentProtocolErrorCode.UNSUPPORTED_PROTOCOL,
            ),
            (
                b'{"protocol_version":"x","protocol_version":"y"}',
                IncidentProtocolErrorCode.INVALID_JSON,
            ),
            (
                b'{"protocol_version":"atlas-richie.incident-events/v1","event_id":"0df0768b-fbc4-42f6-852a-2de2f146e204","process_epoch":"cf5991b7-c790-465a-a385-3eaf99d11e5d","occurred_at":"2026-10-15T01:02:03.456789Z","severity":"warning","fact":{"kind":"resource_pressure","metric":"cpu_ratio","value":0.9,"threshold":0.8,"message":"raw"}}',
                IncidentProtocolErrorCode.INVALID_EVENT,
            ),
            (
                b'{"protocol_version":"atlas-richie.incident-events/v1","event_id":"0df0768b-fbc4-42f6-852a-2de2f146e204","process_epoch":"cf5991b7-c790-465a-a385-3eaf99d11e5d","occurred_at":"2026-10-15T01:02:03.456789Z","severity":"warning","fact":{"kind":"resource_pressure","metric":"cpu_ratio","value":NaN,"threshold":0.8}}',
                IncidentProtocolErrorCode.INVALID_JSON,
            ),
        )
        for body, code in invalid_bodies:
            with self.subTest(code=code):
                with self.assertRaises(IncidentProtocolError) as error:
                    decode_incident_event(body)
                self.assertIs(error.exception.code, code)

    def test_rejects_noncanonical_or_out_of_range_values_at_construction(self):
        with self.assertRaises(ValueError):
            ResourcePressureFact(ResourcePressureMetric.CPU_RATIO, 1.01, 0.8)
        with self.assertRaises(ValueError):
            ResponseTimeFact(float("inf"), 100)
        with self.assertRaises(ValueError):
            IncidentEventV1(
                _EVENT_ID,
                _EPOCH,
                _OCCURRED_AT.replace(tzinfo=None),
                IncidentSeverity.INFO,
                _resource_event().fact,
            )


def _resource_event() -> IncidentEventV1:
    return IncidentEventV1(
        event_id=_EVENT_ID,
        process_epoch=_EPOCH,
        occurred_at=_OCCURRED_AT,
        severity=IncidentSeverity.WARNING,
        fact=ResourcePressureFact(ResourcePressureMetric.MEMORY_RATIO, 0.92, 0.9),
    )
