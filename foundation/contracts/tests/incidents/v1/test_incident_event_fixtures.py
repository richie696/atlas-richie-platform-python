"""Language-neutral Incident Event V1 shared fixture conformance."""

from __future__ import annotations

from pathlib import Path

import pytest
from atlas_richie.contracts.incidents.v1 import (
    IncidentProtocolError,
    decode_incident_event,
    decode_incident_receipt,
    encode_incident_event,
)

_FIXTURES = Path(__file__).with_name("fixtures")


@pytest.mark.parametrize(
    "fixture_name",
    (
        "resource-pressure.json",
        "response-time.json",
        "response-time-max-safe.json",
    ),
)
def test_valid_shared_fixture_decodes_and_reencodes_exactly(fixture_name: str):
    payload = (_FIXTURES / fixture_name).read_bytes()

    event = decode_incident_event(payload)

    assert encode_incident_event(event) == payload.rstrip(b"\n")


def test_invalid_shared_event_fixtures_are_rejected():
    fixture_paths = sorted(_FIXTURES.glob("invalid-*.json"))
    assert fixture_paths
    for fixture_path in fixture_paths:
        with pytest.raises(IncidentProtocolError):
            decode_incident_event(fixture_path.read_bytes())


def test_receipt_shared_fixtures_are_validated():
    receipts = _FIXTURES / "receipts"
    valid_receipt = (receipts / "valid.json").read_bytes()
    assert decode_incident_receipt(valid_receipt)

    invalid_receipt = (receipts / "invalid-digest.json").read_bytes()
    with pytest.raises(IncidentProtocolError):
        decode_incident_receipt(invalid_receipt)
