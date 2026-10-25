"""Language-neutral frozen fixtures exercised by the Python Metrics V2 codec."""

import json
from pathlib import Path

import pytest
from atlas_richie.contracts.reporting.v2.metrics_v2_codec import (
    MetricsV2ProtocolError,
    decode_metrics_snapshot,
)

_FIXTURES = Path(__file__).parent / "fixtures"
_SCHEMA = Path(__file__).parents[3] / "schemas" / "reporting" / "metrics-v2.schema.json"
_INVALID_FIXTURE_EXPECTATIONS = {
    "invalid_duplicate_key.json": "duplicate_json_key",
    "invalid_unknown_field.json": "invalid_snapshot_fields",
    "invalid_wrong_type.json": "invalid_startup_epoch",
    "invalid_wrong_protocol_version.json": "unsupported_protocol",
    "invalid_http_histogram_profile.json": "invalid_histogram_boundaries",
    "invalid_too_many_records.json": "too_many_records",
    "invalid_payload_too_large.json": "payload_too_large",
    "invalid_unknown_enum.json": "invalid_counter_name",
    "invalid_explicit_null_resource.json": "invalid_resource",
    "invalid_histogram_counts.json": "invalid_histogram",
    "invalid_histogram_total_noncanonical.json": "invalid_histogram",
    "invalid_surrogate_resource.json": "invalid_resource",
    "invalid_gauge_float_overflow.json": "invalid_gauge_value",
    "invalid_gauge_unavailable_has_value.json": "invalid_gauge",
    "invalid_empty_histogram_statistics.json": "invalid_histogram",
    "invalid_impossible_timestamp.json": "invalid_captured_at",
    "invalid_capture_elapsed_noncanonical.json": "invalid_capture_elapsed_ns",
    "invalid_safe_integer_overflow.json": "invalid_startup_epoch",
    "invalid_duplicate_counter_identity.json": "duplicate_counter",
    "invalid_duplicate_histogram_identity.json": "duplicate_histogram",
    "invalid_duplicate_gauge_identity.json": "duplicate_gauge",
    "invalid_unsorted_histogram_boundaries.json": "invalid_histogram",
    "invalid_trailing_json_value.json": "invalid_json",
}


@pytest.mark.parametrize(
    "name",
    [
        "valid_minimal.json",
        "valid_full.json",
        "valid_large_histogram_total.json",
        "valid_empty_http_histogram.json",
    ],
)
def test_valid_frozen_fixture_decodes(name: str) -> None:
    snapshot = decode_metrics_snapshot((_FIXTURES / name).read_bytes())

    assert snapshot.reporter_id


@pytest.mark.parametrize(
    ("name", "error_code"), sorted(_INVALID_FIXTURE_EXPECTATIONS.items())
)
def test_invalid_frozen_fixture_is_rejected(name: str, error_code: str) -> None:
    with pytest.raises(MetricsV2ProtocolError, match=error_code):
        decode_metrics_snapshot((_FIXTURES / name).read_bytes())


def test_every_invalid_json_fixture_has_an_explicit_python_assertion() -> None:
    discovered = {path.name for path in _FIXTURES.glob("invalid_*.json")}

    assert discovered == set(_INVALID_FIXTURE_EXPECTATIONS)


def test_machine_schema_freezes_protocol_epoch_and_http_histogram_profile() -> None:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    properties = schema["properties"]
    histogram = schema["$defs"]["histogram"]["properties"]

    assert properties["protocol_version"]["const"] == "atlas-richie.metrics/v2"
    assert properties["startup_epoch"]["$ref"] == "#/$defs/uuid"
    assert schema["$defs"]["uuid"]["pattern"] == (
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    assert histogram["boundaries_ns"]["const"] == [
        1_000_000,
        5_000_000,
        10_000_000,
        25_000_000,
        50_000_000,
        100_000_000,
        250_000_000,
        500_000_000,
        1_000_000_000,
        2_000_000_000,
        5_000_000_000,
        10_000_000_000,
    ]
    assert histogram["bucket_counts"]["minItems"] == 13
    assert histogram["bucket_counts"]["maxItems"] == 13
