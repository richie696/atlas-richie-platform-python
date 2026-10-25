"""Strict JSON codec for the frozen Metrics Reporting V2 snapshot contract."""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeVar, cast
from uuid import UUID

from .error_codes import MetricsV2ErrorCode
from .metrics_v2 import (
    HTTP_REQUEST_DURATION_BOUNDARIES_NS,
    MAX_DECIMAL_INTEGER_DIGITS,
    MAX_HISTOGRAM_BOUNDARIES,
    MAX_IDENTIFIER_LENGTH,
    MAX_SAFE_INTEGER,
    CounterName,
    CounterReading,
    GaugeName,
    GaugeQuality,
    GaugeReading,
    HistogramName,
    HistogramReading,
    MetricsSnapshot,
)

METRICS_V2_PROTOCOL = "atlas-richie.metrics/v2"
METRICS_V2_MAX_SIZE_BYTES = 64 * 1024
METRICS_V2_MAX_RECORDS = 256
METRICS_V2_MAX_ACTIVE_RESOURCES = 256
METRICS_V2_CADENCE_SECONDS = 1
_EnumValue = TypeVar("_EnumValue", bound=StrEnum)
_UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
_DECIMAL_INTEGER_PATTERN = re.compile(
    rf"^(?:0|[1-9][0-9]{{0,{MAX_DECIMAL_INTEGER_DIGITS - 1}}})$"
)


class MetricsV2ProtocolError(ValueError):
    """Stable boundary failure for malformed frozen V2 snapshots."""

    def __init__(self, code: MetricsV2ErrorCode | str) -> None:
        try:
            self.code = MetricsV2ErrorCode(code)
        except ValueError as error:
            raise RuntimeError(f"unregistered Metrics V2 error code: {code}") from error
        super().__init__(self.code.value)


def encode_metrics_snapshot(snapshot: MetricsSnapshot) -> bytes:
    """Encode a typed snapshot as bounded deterministic UTF-8 JSON."""
    if not isinstance(snapshot, MetricsSnapshot):
        raise TypeError("snapshot must be a MetricsSnapshot")
    _validate_record_count(snapshot)
    payload = json.dumps(
        _snapshot_object(snapshot),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    _validate_size(payload)
    return payload


def decode_metrics_snapshot(payload: bytes | str) -> MetricsSnapshot:
    """Decode strict UTF-8 JSON, rejecting duplicate/unknown/mistyped fields."""
    if isinstance(payload, str):
        try:
            raw = payload.encode("utf-8")
        except UnicodeEncodeError as error:
            raise MetricsV2ProtocolError("invalid_utf8") from error
    elif isinstance(payload, bytes):
        raw = payload
    else:
        raise TypeError("payload must be bytes or str")
    _validate_size(raw)
    try:
        decoded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except MetricsV2ProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise MetricsV2ProtocolError("invalid_json") from error
    if type(decoded) is not dict:
        raise MetricsV2ProtocolError("invalid_snapshot_object")
    decoded_object = cast(dict[str, object], decoded)
    if (
        _require_string(decoded_object.get("protocol_version"), "protocol_version")
        != METRICS_V2_PROTOCOL
    ):
        raise MetricsV2ProtocolError("unsupported_protocol")
    body = _require_object(
        decoded_object,
        {
            "protocol_version",
            "reporter_id",
            "startup_epoch",
            "sequence",
            "captured_at",
            "capture_elapsed_ns",
            "counters",
            "histograms",
            "gauges",
        },
        "snapshot",
    )
    counters = tuple(_decode_counter(item) for item in _require_array(body["counters"]))
    histograms = tuple(
        _decode_histogram(item) for item in _require_array(body["histograms"])
    )
    gauges = tuple(_decode_gauge(item) for item in _require_array(body["gauges"]))
    _validate_unique_reading_identities(counters, histograms, gauges)
    try:
        snapshot = MetricsSnapshot(
            reporter_id=_require_string(body["reporter_id"], "reporter_id"),
            startup_epoch=_require_uuid(body["startup_epoch"], "startup_epoch"),
            sequence=_require_integer(body["sequence"], "sequence", 1),
            captured_at=_decode_timestamp(body["captured_at"]),
            capture_elapsed_ns=_require_decimal_integer(
                body["capture_elapsed_ns"], "capture_elapsed_ns"
            ),
            counters=counters,
            histograms=histograms,
            gauges=gauges,
        )
    except MetricsV2ProtocolError:
        raise
    except (TypeError, ValueError) as error:
        raise MetricsV2ProtocolError("invalid_snapshot") from error
    _validate_record_count(snapshot)
    return snapshot


def _snapshot_object(snapshot: MetricsSnapshot) -> dict[str, object]:
    return {
        "protocol_version": METRICS_V2_PROTOCOL,
        "reporter_id": snapshot.reporter_id,
        "startup_epoch": str(snapshot.startup_epoch),
        "sequence": snapshot.sequence,
        "captured_at": snapshot.captured_at.astimezone(UTC).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        ),
        "capture_elapsed_ns": str(snapshot.capture_elapsed_ns),
        "counters": [_counter_object(item) for item in snapshot.counters],
        "histograms": [_histogram_object(item) for item in snapshot.histograms],
        "gauges": [_gauge_object(item) for item in snapshot.gauges],
    }


def _counter_object(reading: CounterReading) -> dict[str, object]:
    result: dict[str, object] = {"name": reading.name.value, "value": reading.value}
    if reading.resource is not None:
        result["resource"] = reading.resource
    return result


def _histogram_object(reading: HistogramReading) -> dict[str, object]:
    result: dict[str, object] = {
        "name": reading.name.value,
        "boundaries_ns": list(reading.boundaries_ns),
        "bucket_counts": list(reading.bucket_counts),
        "sample_count": reading.sample_count,
        "total_ns": str(reading.total_ns),
        "min_ns": reading.min_ns,
        "max_ns": reading.max_ns,
    }
    if reading.resource is not None:
        result["resource"] = reading.resource
    return result


def _gauge_object(reading: GaugeReading) -> dict[str, object]:
    return {
        "name": reading.name.value,
        "value": reading.value,
        "quality": reading.quality.value,
    }


def _decode_counter(value: object) -> CounterReading:
    body = _require_object(
        value, {"name", "value", "resource"}, "counter", {"resource"}
    )
    try:
        return CounterReading(
            name=_enum_value(CounterName, body["name"], "counter_name"),
            value=_require_integer(body["value"], "counter_value", 0),
            resource=_optional_identifier(body, "resource"),
        )
    except MetricsV2ProtocolError:
        raise
    except (TypeError, ValueError) as error:
        raise MetricsV2ProtocolError("invalid_counter") from error


def _decode_histogram(value: object) -> HistogramReading:
    required = {
        "name",
        "boundaries_ns",
        "bucket_counts",
        "sample_count",
        "total_ns",
        "min_ns",
        "max_ns",
        "resource",
    }
    body = _require_object(value, required, "histogram", {"resource"})
    boundaries = _require_array(body["boundaries_ns"])
    if len(boundaries) > MAX_HISTOGRAM_BOUNDARIES:
        raise MetricsV2ProtocolError("too_many_histogram_boundaries")
    decoded_boundaries = tuple(
        _require_integer(item, "histogram_boundary", 1) for item in boundaries
    )
    if decoded_boundaries != HTTP_REQUEST_DURATION_BOUNDARIES_NS:
        raise MetricsV2ProtocolError("invalid_histogram_boundaries")
    try:
        return HistogramReading(
            name=_enum_value(HistogramName, body["name"], "histogram_name"),
            boundaries_ns=decoded_boundaries,
            bucket_counts=tuple(
                _require_integer(item, "histogram_bucket_count", 0)
                for item in _require_array(body["bucket_counts"])
            ),
            sample_count=_require_integer(body["sample_count"], "sample_count", 0),
            total_ns=_require_decimal_integer(body["total_ns"], "histogram_total"),
            min_ns=_optional_integer(body["min_ns"], "histogram_minimum"),
            max_ns=_optional_integer(body["max_ns"], "histogram_maximum"),
            resource=_optional_identifier(body, "resource"),
        )
    except MetricsV2ProtocolError:
        raise
    except (TypeError, ValueError) as error:
        raise MetricsV2ProtocolError("invalid_histogram") from error


def _decode_gauge(value: object) -> GaugeReading:
    body = _require_object(value, {"name", "value", "quality"}, "gauge")
    name = _enum_value(GaugeName, body["name"], "gauge_name")
    quality = _enum_value(GaugeQuality, body["quality"], "gauge_quality")
    reading_value = body["value"]
    if reading_value is None:
        numeric_value = None
    elif type(reading_value) is int:
        numeric_value = _require_integer(reading_value, "gauge_value", 0)
    elif type(reading_value) is float:
        if (
            not math.isfinite(reading_value)
            or reading_value < 0
            or reading_value > MAX_SAFE_INTEGER
        ):
            raise MetricsV2ProtocolError("invalid_gauge_value")
        numeric_value = reading_value
    else:
        raise MetricsV2ProtocolError("invalid_gauge_value")
    try:
        return GaugeReading(name, numeric_value, quality)
    except (TypeError, ValueError) as error:
        raise MetricsV2ProtocolError("invalid_gauge") from error


def _require_object(
    value: object,
    allowed: set[str],
    context: str,
    optional: set[str] | None = None,
) -> dict[str, object]:
    if type(value) is not dict:
        raise MetricsV2ProtocolError(f"invalid_{context}_object")
    object_value = cast(dict[str, object], value)
    keys = set(object_value)
    optional_keys = optional or set()
    if keys - allowed or (allowed - optional_keys) - keys:
        # Nested record field failures use their already-frozen generic code.
        # Only the snapshot has a separate *_fields code in MetricsV2ErrorCode.
        code = (
            "invalid_snapshot_fields" if context == "snapshot" else f"invalid_{context}"
        )
        raise MetricsV2ProtocolError(code)
    return object_value


def _require_array(value: object) -> list[object]:
    if type(value) is not list:
        raise MetricsV2ProtocolError("invalid_array")
    return cast(list[object], value)


def _require_string(value: object, context: str) -> str:
    if not isinstance(value, str) or any(
        0xD800 <= ord(character) <= 0xDFFF for character in value
    ):
        raise MetricsV2ProtocolError(f"invalid_{context}")
    return value


def _require_uuid(value: object, context: str) -> UUID:
    text = _require_string(value, context)
    try:
        parsed = UUID(text)
    except ValueError as error:
        raise MetricsV2ProtocolError(f"invalid_{context}") from error
    if str(parsed) != text:
        raise MetricsV2ProtocolError(f"invalid_{context}")
    return parsed


def _optional_identifier(body: dict[str, object], field_name: str) -> str | None:
    if field_name not in body:
        return None
    value = _require_string(body[field_name], field_name)
    if (
        not value.strip()
        or value != value.strip()
        or len(value) > MAX_IDENTIFIER_LENGTH
        or "\r" in value
        or "\n" in value
    ):
        raise MetricsV2ProtocolError(f"invalid_{field_name}")
    return value


def _require_integer(value: object, context: str, minimum: int) -> int:
    if type(value) is not int or not minimum <= value <= MAX_SAFE_INTEGER:
        raise MetricsV2ProtocolError(f"invalid_{context}")
    return value


def _optional_integer(value: object, context: str) -> int | None:
    if value is None:
        return None
    return _require_integer(value, context, 0)


def _require_decimal_integer(value: object, context: str) -> int:
    if not isinstance(value, str) or not _DECIMAL_INTEGER_PATTERN.fullmatch(value):
        raise MetricsV2ProtocolError(f"invalid_{context}")
    return int(value)


def _enum_value(enum_type: type[_EnumValue], value: object, context: str) -> _EnumValue:
    try:
        return enum_type(_require_string(value, context))
    except ValueError as error:
        raise MetricsV2ProtocolError(f"invalid_{context}") from error


def _decode_timestamp(value: object) -> datetime:
    timestamp = _require_string(value, "captured_at")
    if not _UTC_TIMESTAMP_PATTERN.fullmatch(timestamp):
        raise MetricsV2ProtocolError("invalid_captured_at")
    try:
        parsed = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=UTC
        )
    except ValueError as error:
        raise MetricsV2ProtocolError("invalid_captured_at") from error
    return parsed


def _validate_record_count(snapshot: MetricsSnapshot) -> None:
    record_count = (
        len(snapshot.counters) + len(snapshot.histograms) + len(snapshot.gauges)
    )
    if record_count > METRICS_V2_MAX_RECORDS:
        raise MetricsV2ProtocolError("too_many_records")


def _validate_unique_reading_identities(
    counters: tuple[CounterReading, ...],
    histograms: tuple[HistogramReading, ...],
    gauges: tuple[GaugeReading, ...],
) -> None:
    counter_identities = tuple((item.name, item.resource) for item in counters)
    if len(set(counter_identities)) != len(counter_identities):
        raise MetricsV2ProtocolError("duplicate_counter")
    histogram_identities = tuple((item.name, item.resource) for item in histograms)
    if len(set(histogram_identities)) != len(histogram_identities):
        raise MetricsV2ProtocolError("duplicate_histogram")
    gauge_identities = tuple(item.name for item in gauges)
    if len(set(gauge_identities)) != len(gauge_identities):
        raise MetricsV2ProtocolError("duplicate_gauge")


def _validate_size(payload: bytes) -> None:
    if len(payload) > METRICS_V2_MAX_SIZE_BYTES:
        raise MetricsV2ProtocolError("payload_too_large")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MetricsV2ProtocolError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise MetricsV2ProtocolError("invalid_json_number")


__all__ = [
    "METRICS_V2_MAX_RECORDS",
    "METRICS_V2_MAX_SIZE_BYTES",
    "METRICS_V2_PROTOCOL",
    "MetricsV2ProtocolError",
    "decode_metrics_snapshot",
    "encode_metrics_snapshot",
]
