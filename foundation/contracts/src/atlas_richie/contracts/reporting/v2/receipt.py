"""Durable Metrics V2 receipt value and strict JSON codec."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from .error_codes import MetricsV2ErrorCode
from .metrics_v2_codec import METRICS_V2_MAX_SIZE_BYTES, METRICS_V2_PROTOCOL

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


@dataclass(frozen=True, slots=True)
class MetricsReceipt:
    """Collector proof that one exact Reporter body was durably accepted."""

    reporter_id: str
    startup_epoch: UUID
    sequence: int
    body_sha256: str
    received_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.reporter_id, str) or not self.reporter_id.strip():
            raise ValueError("reporter_id must not be blank")
        if self.reporter_id != self.reporter_id.strip() or len(self.reporter_id) > 200:
            raise ValueError("reporter_id must be a bounded trimmed identifier")
        if type(self.startup_epoch) is not UUID:
            raise ValueError("startup_epoch must be a UUID")
        if type(self.sequence) is not int or not 0 < self.sequence <= 2**53 - 1:
            raise ValueError("sequence must be a positive safe integer")
        if not isinstance(self.body_sha256, str) or not _SHA256_PATTERN.fullmatch(
            self.body_sha256
        ):
            raise ValueError("body_sha256 must be lowercase SHA-256 hex")
        if (
            not isinstance(self.received_at, datetime)
            or self.received_at.tzinfo is None
            or self.received_at.utcoffset() != UTC.utcoffset(self.received_at)
        ):
            raise ValueError("received_at must be timezone-aware UTC")


class MetricsReceiptProtocolError(ValueError):
    """Stable boundary error for malformed or mismatched durable receipts."""

    def __init__(self, code: MetricsV2ErrorCode | str) -> None:
        try:
            self.code = MetricsV2ErrorCode(code)
        except ValueError as error:
            raise RuntimeError(f"unregistered receipt error code: {code}") from error
        super().__init__(self.code.value)


def encode_metrics_receipt(receipt: MetricsReceipt) -> bytes:
    """Encode the strict durable ACK shape using deterministic UTF-8 JSON."""
    if not isinstance(receipt, MetricsReceipt):
        raise TypeError("receipt must be a MetricsReceipt")
    payload = json.dumps(
        {
            "protocol_version": METRICS_V2_PROTOCOL,
            "reporter_id": receipt.reporter_id,
            "startup_epoch": str(receipt.startup_epoch),
            "sequence": receipt.sequence,
            "body_sha256": receipt.body_sha256,
            "received_at": receipt.received_at.astimezone(UTC).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            ),
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(payload) > METRICS_V2_MAX_SIZE_BYTES:
        raise MetricsReceiptProtocolError(MetricsV2ErrorCode.RECEIPT_TOO_LARGE)
    return payload


def decode_metrics_receipt(payload: bytes | str) -> MetricsReceipt:
    """Decode strict ACK JSON and reject duplicates, unknown fields, or bad values."""
    try:
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        if not isinstance(raw, bytes) or len(raw) > METRICS_V2_MAX_SIZE_BYTES:
            raise MetricsReceiptProtocolError(MetricsV2ErrorCode.RECEIPT_TOO_LARGE)
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        required = {
            "protocol_version",
            "reporter_id",
            "startup_epoch",
            "sequence",
            "body_sha256",
            "received_at",
        }
        if type(decoded) is not dict or set(decoded) != required:
            raise MetricsReceiptProtocolError(MetricsV2ErrorCode.INVALID_RECEIPT_FIELDS)
        if decoded["protocol_version"] != METRICS_V2_PROTOCOL:
            raise MetricsReceiptProtocolError(
                MetricsV2ErrorCode.UNSUPPORTED_RECEIPT_PROTOCOL
            )
        if type(decoded["startup_epoch"]) is not str:
            raise MetricsReceiptProtocolError(MetricsV2ErrorCode.INVALID_RECEIPT_EPOCH)
        if type(decoded["sequence"]) is not int:
            raise MetricsReceiptProtocolError(
                MetricsV2ErrorCode.INVALID_RECEIPT_SEQUENCE
            )
        timestamp = decoded["received_at"]
        if type(timestamp) is not str or not _UTC_PATTERN.fullmatch(timestamp):
            raise MetricsReceiptProtocolError(MetricsV2ErrorCode.INVALID_RECEIPT_TIME)
        try:
            epoch = UUID(decoded["startup_epoch"])
            received_at = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
                tzinfo=UTC
            )
            receipt = MetricsReceipt(
                reporter_id=decoded["reporter_id"],
                startup_epoch=epoch,
                sequence=decoded["sequence"],
                body_sha256=decoded["body_sha256"],
                received_at=received_at,
            )
        except (TypeError, ValueError) as error:
            raise MetricsReceiptProtocolError(
                MetricsV2ErrorCode.INVALID_RECEIPT
            ) from error
        if str(epoch) != decoded["startup_epoch"]:
            raise MetricsReceiptProtocolError(MetricsV2ErrorCode.INVALID_RECEIPT_EPOCH)
        return receipt
    except MetricsReceiptProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise MetricsReceiptProtocolError(
            MetricsV2ErrorCode.INVALID_RECEIPT_JSON
        ) from error


def receipt_for_body(
    *,
    reporter_id: str,
    startup_epoch: UUID,
    sequence: int,
    body: bytes,
    received_at: datetime,
) -> MetricsReceipt:
    """Create a server-side receipt digest for the exact accepted bytes."""
    if not isinstance(body, bytes):
        raise TypeError("body must be bytes")
    return MetricsReceipt(
        reporter_id,
        startup_epoch,
        sequence,
        hashlib.sha256(body).hexdigest(),
        received_at,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MetricsReceiptProtocolError(MetricsV2ErrorCode.DUPLICATE_RECEIPT_KEY)
        result[key] = value
    return result


__all__ = [
    "MetricsReceipt",
    "MetricsReceiptProtocolError",
    "decode_metrics_receipt",
    "encode_metrics_receipt",
    "receipt_for_body",
]
