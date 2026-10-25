"""Strict wire tests for durable Metrics V2 acknowledgements."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from atlas_richie.contracts.reporting.v2 import (
    MetricsReceipt,
    MetricsReceiptProtocolError,
    decode_metrics_receipt,
    encode_metrics_receipt,
    receipt_for_body,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "receipts"
_SCHEMA = (
    Path(__file__).parents[3]
    / "schemas"
    / "reporting"
    / "metrics-v2-receipt.schema.json"
)


def test_ack_round_trip_binds_exact_request_body_and_identity() -> None:
    body = b"a"
    receipt = receipt_for_body(
        reporter_id="reporter-a",
        startup_epoch=UUID("7aaafa02-b778-40bc-b516-e008f25a19ef"),
        sequence=7,
        body=body,
        received_at=datetime(2026, 10, 14, 2, 3, 4, 123456, tzinfo=UTC),
    )

    encoded = encode_metrics_receipt(receipt)
    assert receipt.body_sha256 == sha256(body).hexdigest()
    assert decode_metrics_receipt(encoded) == receipt
    assert decode_metrics_receipt((_FIXTURES / "valid_ack.json").read_bytes())


@pytest.mark.parametrize(
    "payload",
    [
        b'{"protocol_version":"atlas-richie.metrics/v2","protocol_version":"atlas-richie.metrics/v2"}',
        b'{"protocol_version":"atlas-richie.metrics/v2","reporter_id":"reporter-a","startup_epoch":"7aaafa02-b778-40bc-b516-e008f25a19ef","sequence":7,"body_sha256":"CA978112CA1BBDCAFAC231B39A23DC4DA786EFF8147C4E72B9807785AFEE48BB","received_at":"2026-10-14T02:03:04.123456Z"}',
        b'{"protocol_version":"atlas-richie.metrics/v2","reporter_id":"reporter-a","startup_epoch":"7aaafa02-b778-40bc-b516-e008f25a19ef","sequence":7,"body_sha256":"ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb","received_at":"2026-10-14T02:03:04.123456+00:00"}',
    ],
)
def test_malformed_or_noncanonical_ack_is_rejected(payload: bytes) -> None:
    with pytest.raises(MetricsReceiptProtocolError):
        decode_metrics_receipt(payload)


def test_ack_requires_exact_fields_and_rejects_server_identity_mismatch_shape() -> None:
    value = json.loads((_FIXTURES / "valid_ack.json").read_bytes())
    value["client_certificate_principal"] = "not-an-authority"
    with pytest.raises(MetricsReceiptProtocolError, match="invalid_receipt_fields"):
        decode_metrics_receipt(json.dumps(value))


def test_invalid_shared_ack_fixture_is_rejected() -> None:
    with pytest.raises(MetricsReceiptProtocolError, match="invalid_receipt"):
        decode_metrics_receipt((_FIXTURES / "invalid_ack_digest.json").read_bytes())


def test_value_rejects_non_utc_or_unsafe_receipt_identity() -> None:
    args = {
        "reporter_id": "reporter-a",
        "startup_epoch": UUID("7aaafa02-b778-40bc-b516-e008f25a19ef"),
        "sequence": 7,
        "body_sha256": "a" * 64,
        "received_at": datetime(2026, 10, 14, tzinfo=UTC),
    }
    with pytest.raises(ValueError, match="safe integer"):
        MetricsReceipt(**{**args, "sequence": 2**53})


def test_receipt_schema_is_machine_readable() -> None:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "protocol_version",
        "reporter_id",
        "startup_epoch",
        "sequence",
        "body_sha256",
        "received_at",
    ]
