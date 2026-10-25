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
_INVALID_FIXTURE_EXPECTATIONS = json.loads(
    (Path(__file__).parent / "fixture-rejections.json").read_text()
)


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
    with pytest.raises(MetricsV2ProtocolError) as caught:
        decode_metrics_snapshot((_FIXTURES / name).read_bytes())
    assert caught.value.code.value == error_code


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


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("counters", "invalid_counter"),
        ("histograms", "invalid_histogram"),
        ("gauges", "invalid_gauge"),
    ],
)
@pytest.mark.parametrize("mutation", ["unknown", "missing"])
def test_nested_field_failures_use_registered_codes(field, code, mutation):
    value = json.loads((_FIXTURES / "valid_full.json").read_text())
    if mutation == "unknown":
        value[field][0]["unapproved"] = True
    else:
        del value[field][0]["name"]
    with pytest.raises(MetricsV2ProtocolError) as caught:
        decode_metrics_snapshot(json.dumps(value))
    assert caught.value.code.value == code
