"""Strict, transport-neutral Rule Publication Receipt V1 contract."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

RULE_PUBLICATION_RECEIPT_V1 = "atlas-richie.sentinel.rule-publication-receipt/v1"
MAX_RULE_PUBLICATION_RECEIPT_BYTES = 16 * 1024
MAX_RULE_PUBLICATION_RECEIPT_SEQUENCE = 9_007_199_254_740_991

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_UTC_MILLISECOND_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_FIELDS = frozenset(
    {
        "protocol_version",
        "receipt_id",
        "process_epoch",
        "sequence",
        "binding_id",
        "publication_id",
        "target_version_id",
        "target_payload_sha256",
        "state",
        "reason",
        "source_revision",
        "observed_at",
    }
)


class PublicationReceiptState(StrEnum):
    """Runtime outcome for one exact publication target."""

    APPLIED = "applied"
    PENDING = "pending"
    FAILED = "failed"
    UNKNOWN = "unknown"
    RESTART_REQUIRED = "restart_required"


class PublicationReceiptReason(StrEnum):
    """Finite, sanitized explanations for terminal non-applied outcomes."""

    DECODE_REJECTED = "decode_rejected"
    DIGEST_MISMATCH = "digest_mismatch"
    APPLY_FAILED = "apply_failed"
    SOURCE_UNAVAILABLE = "source_unavailable"
    STALE_SEQUENCE = "stale_sequence"
    RESTART_REQUIRED = "restart_required"


class PublicationReceiptErrorCode(StrEnum):
    """Stable rejection codes that never contain request content."""

    BODY_SIZE = "body_size"
    INVALID_JSON = "invalid_json"
    DUPLICATE_FIELD = "duplicate_json_key"
    FIELD_SET = "fields"
    PROTOCOL_VERSION = "protocol_version"
    UUID = "uuid"
    IDENTIFIER = "identifier"
    SEQUENCE = "sequence"
    DIGEST = "digest"
    STATE = "state"
    REASON = "reason"
    SOURCE_REVISION = "source_revision"
    OBSERVED_AT = "observed_at"


class PublicationReceiptError(ValueError):
    """Safe contract failure containing only a stable error classification."""

    def __init__(self, code: PublicationReceiptErrorCode) -> None:
        if not isinstance(code, PublicationReceiptErrorCode):
            raise TypeError("receipt error code must use its enum")
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class RulePublicationReceiptV1:
    """Validated runtime-reported fact for an exact managed publication."""

    receipt_id: str
    process_epoch: str
    sequence: int
    binding_id: str
    publication_id: str
    target_version_id: str
    target_payload_sha256: str
    state: PublicationReceiptState
    reason: PublicationReceiptReason | None
    source_revision: str | None
    observed_at: datetime

    def __post_init__(self) -> None:
        _validate_uuid(self.receipt_id)
        _validate_uuid(self.process_epoch)
        for value in (self.binding_id, self.publication_id, self.target_version_id):
            if (
                not isinstance(value, str)
                or _IDENTIFIER_PATTERN.fullmatch(value) is None
            ):
                raise ValueError("receipt identifier is invalid")
        if (
            type(self.sequence) is not int
            or not 1 <= self.sequence <= MAX_RULE_PUBLICATION_RECEIPT_SEQUENCE
        ):
            raise ValueError("receipt sequence is invalid")
        if (
            not isinstance(self.target_payload_sha256, str)
            or _DIGEST_PATTERN.fullmatch(self.target_payload_sha256) is None
        ):
            raise ValueError("receipt target digest is invalid")
        if not isinstance(self.state, PublicationReceiptState):
            raise TypeError("receipt state must use PublicationReceiptState")
        if self.reason is not None and not isinstance(
            self.reason, PublicationReceiptReason
        ):
            raise TypeError("receipt reason must use PublicationReceiptReason")
        if self.state is PublicationReceiptState.FAILED:
            if self.reason in (None, PublicationReceiptReason.RESTART_REQUIRED):
                raise ValueError("failed receipt requires a failure reason")
        elif self.state is PublicationReceiptState.RESTART_REQUIRED:
            if self.reason is not PublicationReceiptReason.RESTART_REQUIRED:
                raise ValueError("restart-required receipt requires matching reason")
        elif self.reason is not None:
            raise ValueError("non-failure receipt cannot carry a reason")
        if self.source_revision is not None and (
            not isinstance(self.source_revision, str)
            or not 1 <= len(self.source_revision) <= 200
            or any(not 0x20 <= ord(char) <= 0x7E for char in self.source_revision)
        ):
            raise ValueError("receipt source revision is invalid")
        if (
            not isinstance(self.observed_at, datetime)
            or self.observed_at.tzinfo is None
        ):
            raise ValueError("receipt observation time must be timezone-aware")
        if (
            self.observed_at.utcoffset() is None
            or self.observed_at.utcoffset().total_seconds() != 0
        ):
            raise ValueError("receipt observation time must be UTC")
        if self.observed_at.microsecond % 1000 != 0:
            raise ValueError("receipt observation time must have millisecond precision")


def encode_rule_publication_receipt(value: RulePublicationReceiptV1) -> bytes:
    """Encode one validated receipt as bounded UTF-8 JSON."""
    if not isinstance(value, RulePublicationReceiptV1):
        raise TypeError("value must be RulePublicationReceiptV1")
    record = {
        "protocol_version": RULE_PUBLICATION_RECEIPT_V1,
        "receipt_id": value.receipt_id,
        "process_epoch": value.process_epoch,
        "sequence": value.sequence,
        "binding_id": value.binding_id,
        "publication_id": value.publication_id,
        "target_version_id": value.target_version_id,
        "target_payload_sha256": value.target_payload_sha256,
        "state": value.state.value,
        "reason": None if value.reason is None else value.reason.value,
        "source_revision": value.source_revision,
        "observed_at": value.observed_at.isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        ),
    }
    payload = json.dumps(record, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    if len(payload) > MAX_RULE_PUBLICATION_RECEIPT_BYTES:
        raise PublicationReceiptError(PublicationReceiptErrorCode.BODY_SIZE)
    return payload


def decode_rule_publication_receipt(payload: bytes) -> RulePublicationReceiptV1:
    """Strictly decode one UTF-8 receipt with exact keys and bounded values."""
    if (
        not isinstance(payload, bytes)
        or not 0 < len(payload) <= MAX_RULE_PUBLICATION_RECEIPT_BYTES
    ):
        raise PublicationReceiptError(PublicationReceiptErrorCode.BODY_SIZE)
    try:
        record = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_non_json_number,
        )
    except PublicationReceiptError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PublicationReceiptError(
            PublicationReceiptErrorCode.INVALID_JSON
        ) from None
    if not isinstance(record, dict) or frozenset(record) != _FIELDS:
        raise PublicationReceiptError(PublicationReceiptErrorCode.FIELD_SET)
    if record["protocol_version"] != RULE_PUBLICATION_RECEIPT_V1:
        raise PublicationReceiptError(PublicationReceiptErrorCode.PROTOCOL_VERSION)
    for field_name in ("receipt_id", "process_epoch"):
        try:
            _validate_uuid(record[field_name])
        except (TypeError, ValueError):
            raise PublicationReceiptError(PublicationReceiptErrorCode.UUID) from None
    identities = tuple(
        record[name] for name in ("binding_id", "publication_id", "target_version_id")
    )
    if any(
        not isinstance(value, str) or _IDENTIFIER_PATTERN.fullmatch(value) is None
        for value in identities
    ):
        raise PublicationReceiptError(PublicationReceiptErrorCode.IDENTIFIER)
    if (
        type(record["sequence"]) is not int
        or not 1 <= record["sequence"] <= MAX_RULE_PUBLICATION_RECEIPT_SEQUENCE
    ):
        raise PublicationReceiptError(PublicationReceiptErrorCode.SEQUENCE)
    digest = record["target_payload_sha256"]
    if not isinstance(digest, str) or _DIGEST_PATTERN.fullmatch(digest) is None:
        raise PublicationReceiptError(PublicationReceiptErrorCode.DIGEST)
    try:
        state = PublicationReceiptState(record["state"])
    except (TypeError, ValueError):
        raise PublicationReceiptError(PublicationReceiptErrorCode.STATE) from None
    try:
        reason = (
            None
            if record["reason"] is None
            else PublicationReceiptReason(record["reason"])
        )
    except (TypeError, ValueError):
        raise PublicationReceiptError(PublicationReceiptErrorCode.REASON) from None
    source_revision = record["source_revision"]
    if source_revision is not None and (
        not isinstance(source_revision, str)
        or not 1 <= len(source_revision) <= 200
        or any(not 0x20 <= ord(char) <= 0x7E for char in source_revision)
    ):
        raise PublicationReceiptError(PublicationReceiptErrorCode.SOURCE_REVISION)
    observed_at_text = record["observed_at"]
    if (
        not isinstance(observed_at_text, str)
        or _UTC_MILLISECOND_PATTERN.fullmatch(observed_at_text) is None
    ):
        raise PublicationReceiptError(PublicationReceiptErrorCode.OBSERVED_AT)
    try:
        observed_at = datetime.fromisoformat(observed_at_text)
    except ValueError:
        raise PublicationReceiptError(PublicationReceiptErrorCode.OBSERVED_AT) from None
    try:
        return RulePublicationReceiptV1(
            receipt_id=record["receipt_id"],
            process_epoch=record["process_epoch"],
            sequence=record["sequence"],
            binding_id=record["binding_id"],
            publication_id=record["publication_id"],
            target_version_id=record["target_version_id"],
            target_payload_sha256=digest,
            state=state,
            reason=reason,
            source_revision=source_revision,
            observed_at=observed_at,
        )
    except (TypeError, ValueError):
        raise PublicationReceiptError(PublicationReceiptErrorCode.REASON) from None


def _validate_uuid(value: str) -> None:
    if not isinstance(value, str):
        raise TypeError("UUID must be a string")
    parsed = UUID(value)
    if str(parsed) != value or parsed.version != 4:
        raise ValueError("UUID must be canonical UUID v4")


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PublicationReceiptError(PublicationReceiptErrorCode.DUPLICATE_FIELD)
        result[key] = value
    return result


def _reject_non_json_number(value: str) -> None:
    del value
    raise PublicationReceiptError(PublicationReceiptErrorCode.INVALID_JSON)
