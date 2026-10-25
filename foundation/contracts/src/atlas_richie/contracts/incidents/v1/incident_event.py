"""Immutable values for Sentinel Incident Event Protocol V1."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

INCIDENT_EVENT_PROTOCOL_V1 = "atlas-richie.incident-events/v1"
MAX_INCIDENT_EVENT_BODY_BYTES = 16 * 1024
_MAX_SAFE_NUMBER = 2**53 - 1
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


class IncidentSeverity(StrEnum):
    """Finite urgency classifications accepted by Incident Event V1."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class ResourcePressureMetric(StrEnum):
    """Ratio metrics with an explicit runtime threshold."""

    CPU_RATIO = "cpu_ratio"
    MEMORY_RATIO = "memory_ratio"


class IncidentFactKind(StrEnum):
    """V1 fact discriminators; adding values requires a new protocol version."""

    RESOURCE_PRESSURE = "resource_pressure"
    RESPONSE_TIME = "response_time"


class IncidentProtocolErrorCode(StrEnum):
    """Stable strict-codec rejection categories."""

    PAYLOAD_TOO_LARGE = "payload_too_large"
    INVALID_JSON = "invalid_json"
    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    INVALID_EVENT = "invalid_event"
    INVALID_RECEIPT = "invalid_receipt"


class IncidentProtocolError(ValueError):
    """Safe protocol error with no raw body or user-controlled message."""

    def __init__(self, code: IncidentProtocolErrorCode) -> None:
        if not isinstance(code, IncidentProtocolErrorCode):
            raise TypeError("incident protocol error code must use its enum")
        self.code = code
        super().__init__(code.value)


def _is_utc_instant(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() == UTC.utcoffset(value)
    )


def _is_finite_nonnegative(value: object) -> bool:
    if type(value) is int:
        return 0 <= value <= _MAX_SAFE_NUMBER
    return (
        type(value) is float and math.isfinite(value) and 0 <= value <= _MAX_SAFE_NUMBER
    )


def _canonical_uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True, slots=True)
class ResourcePressureFact:
    """One process CPU or memory threshold crossing."""

    metric: ResourcePressureMetric
    value: float
    threshold: float

    def __post_init__(self) -> None:
        if not isinstance(self.metric, ResourcePressureMetric):
            raise TypeError("resource pressure metric must use its enum")
        if not _is_finite_nonnegative(self.value) or not 0 <= self.value <= 1:
            raise ValueError("resource pressure value must be a finite ratio")
        if not _is_finite_nonnegative(self.threshold) or not 0 <= self.threshold <= 1:
            raise ValueError("resource pressure threshold must be a finite ratio")
        if self.value <= self.threshold:
            raise ValueError("resource pressure value must exceed its threshold")


@dataclass(frozen=True, slots=True)
class ResponseTimeFact:
    """One process p95 latency threshold crossing in milliseconds."""

    p95_ms: float
    threshold_ms: float

    def __post_init__(self) -> None:
        if not _is_finite_nonnegative(self.p95_ms) or not _is_finite_nonnegative(
            self.threshold_ms
        ):
            raise ValueError("response-time values must be finite and non-negative")
        if self.p95_ms <= self.threshold_ms:
            raise ValueError("response-time value must exceed its threshold")


IncidentFactV1 = ResourcePressureFact | ResponseTimeFact


@dataclass(frozen=True, slots=True)
class IncidentEventV1:
    """An authenticated Reporter-scoped incident fact, excluding runtime scope."""

    event_id: UUID
    process_epoch: UUID
    occurred_at: datetime
    severity: IncidentSeverity
    fact: IncidentFactV1

    def __post_init__(self) -> None:
        if type(self.event_id) is not UUID or type(self.process_epoch) is not UUID:
            raise ValueError("incident event identities must be UUID values")
        if not _is_utc_instant(self.occurred_at):
            raise ValueError("incident occurrence time must be UTC-aware")
        if not isinstance(self.severity, IncidentSeverity):
            raise TypeError("incident severity must use its enum")
        if not isinstance(self.fact, (ResourcePressureFact, ResponseTimeFact)):
            raise TypeError("incident fact must use a supported value")


@dataclass(frozen=True, slots=True)
class IncidentEventReceiptV1:
    """Durable acknowledgement for exact Incident Event V1 request bytes."""

    event_id: UUID
    body_sha256: str
    received_at: datetime

    def __post_init__(self) -> None:
        if type(self.event_id) is not UUID:
            raise ValueError("incident receipt event identity must be a UUID")
        if not isinstance(self.body_sha256, str) or not _DIGEST_PATTERN.fullmatch(
            self.body_sha256
        ):
            raise ValueError("incident receipt digest must be lowercase SHA-256")
        if not _is_utc_instant(self.received_at):
            raise ValueError("incident receipt time must be UTC-aware")


def encode_incident_event(event: IncidentEventV1) -> bytes:
    """Encode one event as deterministic, bounded UTF-8 JSON."""
    if not isinstance(event, IncidentEventV1):
        raise TypeError("event must be an IncidentEventV1")
    payload = {
        "protocol_version": INCIDENT_EVENT_PROTOCOL_V1,
        "event_id": str(event.event_id),
        "process_epoch": str(event.process_epoch),
        "occurred_at": _encode_timestamp(event.occurred_at),
        "severity": event.severity.value,
        "fact": _encode_fact(event.fact),
    }
    return _encode_json(payload, IncidentProtocolErrorCode.INVALID_EVENT)


def decode_incident_event(payload: bytes | str) -> IncidentEventV1:
    """Strictly decode V1, rejecting duplicate/unknown/mistyped JSON fields."""
    body = _decode_json(payload)
    if body.get("protocol_version") != INCIDENT_EVENT_PROTOCOL_V1:
        raise IncidentProtocolError(IncidentProtocolErrorCode.UNSUPPORTED_PROTOCOL)
    if set(body) != {
        "protocol_version",
        "event_id",
        "process_epoch",
        "occurred_at",
        "severity",
        "fact",
    }:
        raise IncidentProtocolError(IncidentProtocolErrorCode.INVALID_EVENT)
    try:
        return IncidentEventV1(
            event_id=_decode_uuid(body["event_id"]),
            process_epoch=_decode_uuid(body["process_epoch"]),
            occurred_at=_decode_timestamp(body["occurred_at"]),
            severity=IncidentSeverity(body["severity"]),
            fact=_decode_fact(body["fact"]),
        )
    except (KeyError, TypeError, ValueError):
        raise IncidentProtocolError(IncidentProtocolErrorCode.INVALID_EVENT) from None


def encode_incident_receipt(receipt: IncidentEventReceiptV1) -> bytes:
    """Encode one durable event receipt."""
    if not isinstance(receipt, IncidentEventReceiptV1):
        raise TypeError("receipt must be an IncidentEventReceiptV1")
    return _encode_json(
        {
            "protocol_version": INCIDENT_EVENT_PROTOCOL_V1,
            "event_id": str(receipt.event_id),
            "body_sha256": receipt.body_sha256,
            "received_at": _encode_timestamp(receipt.received_at),
        },
        IncidentProtocolErrorCode.INVALID_RECEIPT,
    )


def decode_incident_receipt(payload: bytes | str) -> IncidentEventReceiptV1:
    """Strictly decode a Collector durable acknowledgement."""
    body = _decode_json(payload)
    if body.get("protocol_version") != INCIDENT_EVENT_PROTOCOL_V1:
        raise IncidentProtocolError(IncidentProtocolErrorCode.UNSUPPORTED_PROTOCOL)
    if set(body) != {
        "protocol_version",
        "event_id",
        "body_sha256",
        "received_at",
    }:
        raise IncidentProtocolError(IncidentProtocolErrorCode.INVALID_RECEIPT)
    try:
        return IncidentEventReceiptV1(
            event_id=_decode_uuid(body["event_id"]),
            body_sha256=body["body_sha256"],
            received_at=_decode_timestamp(body["received_at"]),
        )
    except (KeyError, TypeError, ValueError):
        raise IncidentProtocolError(IncidentProtocolErrorCode.INVALID_RECEIPT) from None


def _encode_fact(fact: IncidentFactV1) -> dict[str, object]:
    if isinstance(fact, ResourcePressureFact):
        return {
            "kind": IncidentFactKind.RESOURCE_PRESSURE.value,
            "metric": fact.metric.value,
            "value": fact.value,
            "threshold": fact.threshold,
        }
    return {
        "kind": IncidentFactKind.RESPONSE_TIME.value,
        "p95_ms": fact.p95_ms,
        "threshold_ms": fact.threshold_ms,
    }


def _decode_fact(value: object) -> IncidentFactV1:
    if type(value) is not dict:
        raise ValueError("incident fact must be an object")
    kind = IncidentFactKind(value.get("kind"))
    if kind is IncidentFactKind.RESOURCE_PRESSURE:
        if set(value) != {"kind", "metric", "value", "threshold"}:
            raise ValueError("resource-pressure fact fields are invalid")
        pressure, threshold = _decode_breach_numbers(
            value["value"], value["threshold"], ratio=True
        )
        return ResourcePressureFact(
            metric=ResourcePressureMetric(value["metric"]),
            value=pressure,
            threshold=threshold,
        )
    if set(value) != {"kind", "p95_ms", "threshold_ms"}:
        raise ValueError("response-time fact fields are invalid")
    p95_ms, threshold_ms = _decode_breach_numbers(
        value["p95_ms"], value["threshold_ms"], ratio=False
    )
    return ResponseTimeFact(p95_ms=p95_ms, threshold_ms=threshold_ms)


def _decode_json(payload: bytes | str) -> dict[str, object]:
    if isinstance(payload, str):
        try:
            raw = payload.encode("utf-8")
        except UnicodeEncodeError:
            raise IncidentProtocolError(
                IncidentProtocolErrorCode.INVALID_JSON
            ) from None
    elif isinstance(payload, bytes):
        raw = payload
    else:
        raise TypeError("incident protocol payload must be bytes or str")
    if len(raw) > MAX_INCIDENT_EVENT_BODY_BYTES:
        raise IncidentProtocolError(IncidentProtocolErrorCode.PAYLOAD_TOO_LARGE)
    if not raw:
        raise IncidentProtocolError(IncidentProtocolErrorCode.INVALID_JSON)
    try:
        decoded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_float=Decimal,
            parse_constant=_reject_constant,
        )
    except IncidentProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise IncidentProtocolError(IncidentProtocolErrorCode.INVALID_JSON) from None
    if type(decoded) is not dict:
        raise IncidentProtocolError(IncidentProtocolErrorCode.INVALID_EVENT)
    return decoded


def _encode_json(payload: dict[str, object], error: IncidentProtocolErrorCode) -> bytes:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise IncidentProtocolError(error) from None
    if len(encoded) > MAX_INCIDENT_EVENT_BODY_BYTES:
        raise IncidentProtocolError(IncidentProtocolErrorCode.PAYLOAD_TOO_LARGE)
    return encoded


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise IncidentProtocolError(IncidentProtocolErrorCode.INVALID_JSON)
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise IncidentProtocolError(IncidentProtocolErrorCode.INVALID_JSON)


def _decode_uuid(value: object) -> UUID:
    if not isinstance(value, str) or not _canonical_uuid(value):
        raise ValueError("UUID must be canonical")
    return UUID(value)


def _decode_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP_PATTERN.fullmatch(value):
        raise ValueError("timestamp is not canonical UTC")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _encode_timestamp(value: datetime) -> str:
    if not _is_utc_instant(value):
        raise ValueError("timestamp must be UTC-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _decode_breach_numbers(
    value: object, threshold: object, *, ratio: bool
) -> tuple[float, float]:
    exact_value = _decode_exact_number(value, ratio=ratio)
    exact_threshold = _decode_exact_number(threshold, ratio=ratio)
    if exact_value <= exact_threshold:
        raise ValueError("incident value must exceed its threshold")
    projected_value = float(exact_value)
    projected_threshold = float(exact_threshold)
    if not projected_value > projected_threshold:
        raise ValueError("incident value must remain above threshold after projection")
    return projected_value, projected_threshold


def _decode_exact_number(value: object, *, ratio: bool) -> Decimal:
    if type(value) is int:
        exact = Decimal(value)
    elif isinstance(value, Decimal):
        exact = value
    else:
        raise ValueError("number must be a JSON number")
    if not exact.is_finite() or not 0 <= exact <= _MAX_SAFE_NUMBER:
        raise ValueError("number must be finite, non-negative, and safe")
    if ratio and exact > 1:
        raise ValueError("ratio must not exceed one")
    return exact


__all__ = [
    "INCIDENT_EVENT_PROTOCOL_V1",
    "MAX_INCIDENT_EVENT_BODY_BYTES",
    "IncidentEventReceiptV1",
    "IncidentEventV1",
    "IncidentFactKind",
    "IncidentProtocolError",
    "IncidentProtocolErrorCode",
    "IncidentSeverity",
    "ResourcePressureFact",
    "ResourcePressureMetric",
    "ResponseTimeFact",
    "decode_incident_event",
    "decode_incident_receipt",
    "encode_incident_event",
    "encode_incident_receipt",
]
