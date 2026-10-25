"""Strict Managed Rule Publication Envelope V1 values and codec."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

MANAGED_RULE_PUBLICATION_V1 = "atlas-richie.sentinel.managed-rule-publication/v1"
MAX_MANAGED_RULE_ENVELOPE_BYTES = 512 * 1024
MAX_MANAGED_RULE_PAYLOAD_BYTES = 500 * 1024
MAX_PUBLICATION_SEQUENCE = 9_007_199_254_740_991

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = frozenset(
    {
        "protocol_version",
        "binding_id",
        "publication_id",
        "target_version_id",
        "publication_sequence",
        "rule_kind",
        "profile_id",
        "payload_sha256",
        "rule_payload",
    }
)


class ManagedRuleKind(StrEnum):
    """Finite managed-rule payload categories."""

    FLOW = "flow"
    DEGRADE = "degrade"
    SYSTEM = "system"
    AUTHORITY = "authority"
    PARAM = "param"


class ManagedRulePublicationErrorCode(StrEnum):
    """Safe, finite envelope decoding failure classifications."""

    PAYLOAD_SIZE = "payload_size"
    INVALID_JSON = "invalid_json"
    DUPLICATE_FIELD = "duplicate_json_key"
    FIELD_SET = "fields"
    PROTOCOL_VERSION = "protocol_version"
    IDENTIFIER = "identifier"
    SEQUENCE = "publication_sequence"
    RULE_KIND = "rule_kind"
    PAYLOAD_DIGEST = "payload_sha256"
    INNER_PAYLOAD = "rule_payload"
    INNER_PAYLOAD_SIZE = "rule_payload_size"
    INNER_PAYLOAD_JSON = "rule_payload_json"
    INNER_PAYLOAD_SHAPE = "rule_payload_shape"
    DIGEST_MISMATCH = "payload_sha256_mismatch"


class ManagedRulePublicationError(ValueError):
    """Protocol rejection without retaining or echoing the raw request."""

    def __init__(self, code: ManagedRulePublicationErrorCode) -> None:
        if not isinstance(code, ManagedRulePublicationErrorCode):
            raise TypeError("managed rule error code must use its enum")
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class ManagedRulePublicationV1:
    """Validated identities and the exact native JSON array bytes."""

    binding_id: str
    publication_id: str
    target_version_id: str
    publication_sequence: int
    rule_kind: ManagedRuleKind
    profile_id: str
    payload_sha256: str
    rule_payload: bytes

    def __post_init__(self) -> None:
        for value in (
            self.binding_id,
            self.publication_id,
            self.target_version_id,
            self.profile_id,
        ):
            if (
                not isinstance(value, str)
                or _IDENTIFIER_PATTERN.fullmatch(value) is None
            ):
                raise ValueError("managed rule publication identifier is invalid")
        if (
            type(self.publication_sequence) is not int
            or not 1 <= self.publication_sequence <= MAX_PUBLICATION_SEQUENCE
        ):
            raise ValueError("managed rule publication sequence is invalid")
        if not isinstance(self.rule_kind, ManagedRuleKind):
            raise TypeError("managed rule kind must use its enum")
        if (
            not isinstance(self.rule_payload, bytes)
            or len(self.rule_payload) > MAX_MANAGED_RULE_PAYLOAD_BYTES
        ):
            raise ValueError("managed rule payload size is invalid")
        if _SHA256_PATTERN.fullmatch(self.payload_sha256) is None:
            raise ValueError("managed rule payload digest is invalid")
        if hashlib.sha256(self.rule_payload).hexdigest() != self.payload_sha256:
            raise ValueError("managed rule payload digest does not match")
        rules = _decode_inner_rules(self.rule_payload)
        if not isinstance(rules, list) or any(
            not isinstance(rule, dict) for rule in rules
        ):
            raise ValueError("managed rule payload must be an array of objects")


def encode_managed_rule_publication(value: ManagedRulePublicationV1) -> bytes:
    """Encode one validated envelope as bounded UTF-8 JSON."""
    if not isinstance(value, ManagedRulePublicationV1):
        raise TypeError("value must be ManagedRulePublicationV1")
    body = json.dumps(
        {
            "protocol_version": MANAGED_RULE_PUBLICATION_V1,
            "binding_id": value.binding_id,
            "publication_id": value.publication_id,
            "target_version_id": value.target_version_id,
            "publication_sequence": value.publication_sequence,
            "rule_kind": value.rule_kind.value,
            "profile_id": value.profile_id,
            "payload_sha256": value.payload_sha256,
            "rule_payload": value.rule_payload.decode("utf-8", errors="strict"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(body) > MAX_MANAGED_RULE_ENVELOPE_BYTES:
        raise ManagedRulePublicationError(ManagedRulePublicationErrorCode.PAYLOAD_SIZE)
    return body


def decode_managed_rule_publication(payload: bytes) -> ManagedRulePublicationV1:
    """Strictly validate an envelope and preserve exact inner payload bytes."""
    if (
        not isinstance(payload, bytes)
        or not 0 < len(payload) <= MAX_MANAGED_RULE_ENVELOPE_BYTES
    ):
        raise ManagedRulePublicationError(ManagedRulePublicationErrorCode.PAYLOAD_SIZE)
    try:
        text = payload.decode("utf-8", errors="strict")
        record = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_non_json_number,
        )
    except ManagedRulePublicationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ManagedRulePublicationError(
            ManagedRulePublicationErrorCode.INVALID_JSON
        ) from None
    if not isinstance(record, dict) or frozenset(record) != _FIELDS:
        raise ManagedRulePublicationError(ManagedRulePublicationErrorCode.FIELD_SET)
    if record["protocol_version"] != MANAGED_RULE_PUBLICATION_V1:
        raise ManagedRulePublicationError(
            ManagedRulePublicationErrorCode.PROTOCOL_VERSION
        )
    identifiers = tuple(
        record[field]
        for field in ("binding_id", "publication_id", "target_version_id", "profile_id")
    )
    if any(
        not isinstance(value, str) or _IDENTIFIER_PATTERN.fullmatch(value) is None
        for value in identifiers
    ):
        raise ManagedRulePublicationError(ManagedRulePublicationErrorCode.IDENTIFIER)
    sequence = record["publication_sequence"]
    if type(sequence) is not int or not 1 <= sequence <= MAX_PUBLICATION_SEQUENCE:
        raise ManagedRulePublicationError(ManagedRulePublicationErrorCode.SEQUENCE)
    try:
        rule_kind = ManagedRuleKind(record["rule_kind"])
    except (TypeError, ValueError):
        raise ManagedRulePublicationError(
            ManagedRulePublicationErrorCode.RULE_KIND
        ) from None
    digest = record["payload_sha256"]
    if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
        raise ManagedRulePublicationError(
            ManagedRulePublicationErrorCode.PAYLOAD_DIGEST
        )
    rule_payload = record["rule_payload"]
    if not isinstance(rule_payload, str):
        raise ManagedRulePublicationError(ManagedRulePublicationErrorCode.INNER_PAYLOAD)
    try:
        rule_payload_bytes = rule_payload.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise ManagedRulePublicationError(
            ManagedRulePublicationErrorCode.INNER_PAYLOAD
        ) from None
    if len(rule_payload_bytes) > MAX_MANAGED_RULE_PAYLOAD_BYTES:
        raise ManagedRulePublicationError(
            ManagedRulePublicationErrorCode.INNER_PAYLOAD_SIZE
        )
    rules = _decode_inner_rules(rule_payload_bytes)
    if not isinstance(rules, list) or any(not isinstance(rule, dict) for rule in rules):
        raise ManagedRulePublicationError(
            ManagedRulePublicationErrorCode.INNER_PAYLOAD_SHAPE
        )
    actual_digest = hashlib.sha256(rule_payload_bytes).hexdigest()
    if actual_digest != digest:
        raise ManagedRulePublicationError(
            ManagedRulePublicationErrorCode.DIGEST_MISMATCH
        )
    try:
        return ManagedRulePublicationV1(
            binding_id=record["binding_id"],
            publication_id=record["publication_id"],
            target_version_id=record["target_version_id"],
            publication_sequence=sequence,
            rule_kind=rule_kind,
            profile_id=record["profile_id"],
            payload_sha256=digest,
            rule_payload=rule_payload_bytes,
        )
    except (TypeError, ValueError):
        raise ManagedRulePublicationError(
            ManagedRulePublicationErrorCode.INNER_PAYLOAD_SHAPE
        ) from None


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ManagedRulePublicationError(
                ManagedRulePublicationErrorCode.DUPLICATE_FIELD
            )
        result[key] = value
    return result


def _reject_non_json_number(value: str) -> None:
    raise ManagedRulePublicationError(ManagedRulePublicationErrorCode.INVALID_JSON)


def _decode_inner_rules(payload: bytes) -> object:
    try:
        return json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_non_json_number,
        )
    except ManagedRulePublicationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ManagedRulePublicationError(
            ManagedRulePublicationErrorCode.INNER_PAYLOAD_JSON
        ) from None


__all__ = [
    "MANAGED_RULE_PUBLICATION_V1",
    "MAX_MANAGED_RULE_ENVELOPE_BYTES",
    "MAX_MANAGED_RULE_PAYLOAD_BYTES",
    "MAX_PUBLICATION_SEQUENCE",
    "ManagedRuleKind",
    "ManagedRulePublicationError",
    "ManagedRulePublicationErrorCode",
    "ManagedRulePublicationV1",
    "decode_managed_rule_publication",
    "encode_managed_rule_publication",
]
