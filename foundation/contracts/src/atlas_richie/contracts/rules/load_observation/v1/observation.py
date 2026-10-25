"""Strict transport-neutral Rule Load Observation V1 contract.

The event records runtime-observed active rule snapshots independently from
managed publication receipts. Authentication, enrollment, durable storage and
freshness decisions belong to the Collector/Console services.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

RULE_LOAD_OBSERVATION_V1 = "atlas-richie.sentinel.rule-load-observation/v1"
MAX_RULE_LOAD_OBSERVATION_BYTES = 512 * 1024
MAX_RULE_LOAD_OBSERVATION_MEMBERS = 8_192
MAX_RULE_LOAD_OBSERVATION_SEQUENCE = 9_007_199_254_740_991

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_UTC_MILLISECOND_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_EVENT_FIELDS = frozenset(
    {
        "protocol_version",
        "observation_id",
        "process_epoch",
        "sequence",
        "binding_id",
        "profile_id",
        "event_kind",
        "active_snapshot",
        "attempt",
        "observed_at",
    }
)
_SNAPSHOT_FIELDS = frozenset(
    {
        "source_revision",
        "source_bytes_sha256",
        "canonical_rules_sha256",
        "membership_complete",
        "members",
    }
)
_ATTEMPT_FIELDS = frozenset(
    {
        "source_revision",
        "source_bytes_sha256",
        "canonical_rules_sha256",
        "failure_reason",
    }
)
_MEMBER_FIELDS = frozenset({"rule_kind", "fingerprint_sha256"})


class RuleKind(StrEnum):
    """Rule families represented by profile-owned member fingerprints."""

    FLOW = "flow"
    DEGRADE = "degrade"
    PARAM_FLOW = "param_flow"
    SYSTEM = "system"
    AUTHORITY = "authority"


class RuleLoadEventKind(StrEnum):
    """V1 observation event types."""

    SNAPSHOT_APPLIED = "snapshot_applied"
    SNAPSHOT_FAILED = "snapshot_failed"
    HEARTBEAT = "heartbeat"


class RuleLoadFailureReason(StrEnum):
    """Stable, sanitized reasons for a failed candidate load."""

    SOURCE_UNAVAILABLE = "source_unavailable"
    DECODE_REJECTED = "decode_rejected"
    PROFILE_UNSUPPORTED = "profile_unsupported"
    VALIDATION_REJECTED = "validation_rejected"
    APPLY_FAILED = "apply_failed"


class RuleLoadObservationErrorCode(StrEnum):
    """Stable codec error classifications without request data."""

    BODY_SIZE = "body_size"
    INVALID_JSON = "invalid_json"
    DUPLICATE_FIELD = "duplicate_json_key"
    FIELD_SET = "fields"
    PROTOCOL_VERSION = "protocol_version"
    UUID = "uuid"
    IDENTIFIER = "identifier"
    SEQUENCE = "sequence"
    EVENT_KIND = "event_kind"
    SNAPSHOT = "snapshot"
    ATTEMPT = "attempt"
    MEMBER = "member"
    OBSERVED_AT = "observed_at"


class RuleLoadObservationError(ValueError):
    """Safe protocol failure carrying only a stable error classification."""

    def __init__(self, code: RuleLoadObservationErrorCode) -> None:
        if not isinstance(code, RuleLoadObservationErrorCode):
            raise TypeError("rule-load error code must use its enum")
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class RuleLoadMemberFingerprint:
    """Profile-canonical digest for one member of an applied rule snapshot.

    The profile specification owns canonicalization. The digest is not a
    provider revision, publication identity, or raw rule payload.
    """

    rule_kind: RuleKind
    fingerprint_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.rule_kind, RuleKind):
            raise TypeError("rule kind must use RuleKind")
        if (
            not isinstance(self.fingerprint_sha256, str)
            or _DIGEST_PATTERN.fullmatch(self.fingerprint_sha256) is None
        ):
            raise ValueError("member fingerprint must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class RuleLoadSnapshotV1:
    """One snapshot confirmed active by the runtime after successful apply."""

    source_revision: str | None
    source_bytes_sha256: str | None
    canonical_rules_sha256: str
    membership_complete: bool
    members: tuple[RuleLoadMemberFingerprint, ...]

    def __post_init__(self) -> None:
        _validate_source_revision(self.source_revision)
        _validate_optional_digest(self.source_bytes_sha256)
        _validate_digest(self.canonical_rules_sha256)
        if type(self.membership_complete) is not bool:
            raise ValueError("membership_complete must be boolean")
        if not isinstance(self.members, tuple) or len(self.members) > MAX_RULE_LOAD_OBSERVATION_MEMBERS:
            raise ValueError("snapshot members exceed the V1 bound")
        if any(not isinstance(item, RuleLoadMemberFingerprint) for item in self.members):
            raise TypeError("snapshot members contain an invalid value")
        identities = tuple((item.rule_kind, item.fingerprint_sha256) for item in self.members)
        if identities != tuple(sorted(set(identities), key=lambda item: (item[0].value, item[1]))):
            raise ValueError("snapshot members must be unique and sorted")
        if not self.membership_complete and self.members:
            raise ValueError("incomplete membership must not claim member fingerprints")


@dataclass(frozen=True, slots=True)
class RuleLoadAttemptV1:
    """Metadata for a rejected candidate; never contains raw rule content."""

    source_revision: str | None
    source_bytes_sha256: str | None
    canonical_rules_sha256: str | None
    failure_reason: RuleLoadFailureReason

    def __post_init__(self) -> None:
        _validate_source_revision(self.source_revision)
        _validate_optional_digest(self.source_bytes_sha256)
        _validate_optional_digest(self.canonical_rules_sha256)
        if not isinstance(self.failure_reason, RuleLoadFailureReason):
            raise TypeError("failure_reason must use RuleLoadFailureReason")


@dataclass(frozen=True, slots=True)
class RuleLoadObservationV1:
    """Runtime-observed active rule state for one enrolled binding/process."""

    observation_id: str
    process_epoch: str
    sequence: int
    binding_id: str
    profile_id: str
    event_kind: RuleLoadEventKind
    active_snapshot: RuleLoadSnapshotV1 | None
    attempt: RuleLoadAttemptV1 | None
    observed_at: datetime

    def __post_init__(self) -> None:
        _validate_uuid(self.observation_id)
        _validate_uuid(self.process_epoch)
        for value in (self.binding_id, self.profile_id):
            if not isinstance(value, str) or _IDENTIFIER_PATTERN.fullmatch(value) is None:
                raise ValueError("rule-load identity is invalid")
        if type(self.sequence) is not int or not 1 <= self.sequence <= MAX_RULE_LOAD_OBSERVATION_SEQUENCE:
            raise ValueError("rule-load sequence is invalid")
        if not isinstance(self.event_kind, RuleLoadEventKind):
            raise TypeError("event_kind must use RuleLoadEventKind")
        if self.active_snapshot is not None and not isinstance(self.active_snapshot, RuleLoadSnapshotV1):
            raise TypeError("active_snapshot must use RuleLoadSnapshotV1 or None")
        if self.attempt is not None and not isinstance(self.attempt, RuleLoadAttemptV1):
            raise TypeError("attempt must use RuleLoadAttemptV1 or None")
        if self.event_kind is RuleLoadEventKind.SNAPSHOT_APPLIED:
            if self.active_snapshot is None or self.attempt is not None:
                raise ValueError("applied observation requires only active_snapshot")
        elif self.event_kind is RuleLoadEventKind.SNAPSHOT_FAILED:
            if self.attempt is None:
                raise ValueError("failed observation requires attempt metadata")
        elif self.attempt is not None:
            raise ValueError("heartbeat cannot contain a failed attempt")
        if not isinstance(self.observed_at, datetime) or self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be a timezone-aware UTC instant")
        if self.observed_at.utcoffset() is None or self.observed_at.utcoffset().total_seconds() != 0:
            raise ValueError("observed_at must be UTC")
        if self.observed_at.microsecond % 1000 != 0:
            raise ValueError("observed_at must have millisecond precision")


def encode_rule_load_observation(value: RuleLoadObservationV1) -> bytes:
    """Encode one observation as deterministic bounded UTF-8 JSON."""
    if not isinstance(value, RuleLoadObservationV1):
        raise TypeError("value must be RuleLoadObservationV1")
    record = {
        "protocol_version": RULE_LOAD_OBSERVATION_V1,
        "observation_id": value.observation_id,
        "process_epoch": value.process_epoch,
        "sequence": value.sequence,
        "binding_id": value.binding_id,
        "profile_id": value.profile_id,
        "event_kind": value.event_kind.value,
        "active_snapshot": _encode_snapshot(value.active_snapshot),
        "attempt": _encode_attempt(value.attempt),
        "observed_at": value.observed_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    payload = json.dumps(record, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    if len(payload) > MAX_RULE_LOAD_OBSERVATION_BYTES:
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.BODY_SIZE)
    return payload


def decode_rule_load_observation(payload: bytes) -> RuleLoadObservationV1:
    """Strictly decode one observation; reject unknown/duplicate fields."""
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_RULE_LOAD_OBSERVATION_BYTES:
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.BODY_SIZE)
    try:
        record = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_non_json_number,
        )
    except RuleLoadObservationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.INVALID_JSON) from None
    if not isinstance(record, dict) or frozenset(record) != _EVENT_FIELDS:
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.FIELD_SET)
    if record["protocol_version"] != RULE_LOAD_OBSERVATION_V1:
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.PROTOCOL_VERSION)
    try:
        _validate_uuid(record["observation_id"])
        _validate_uuid(record["process_epoch"])
    except (TypeError, ValueError):
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.UUID) from None
    if any(
        not isinstance(record[name], str) or _IDENTIFIER_PATTERN.fullmatch(record[name]) is None
        for name in ("binding_id", "profile_id")
    ):
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.IDENTIFIER)
    if type(record["sequence"]) is not int or not 1 <= record["sequence"] <= MAX_RULE_LOAD_OBSERVATION_SEQUENCE:
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.SEQUENCE)
    try:
        event_kind = RuleLoadEventKind(record["event_kind"])
    except (TypeError, ValueError):
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.EVENT_KIND) from None
    active_snapshot = _decode_snapshot(record["active_snapshot"])
    attempt = _decode_attempt(record["attempt"])
    observed_at_text = record["observed_at"]
    if not isinstance(observed_at_text, str) or _UTC_MILLISECOND_PATTERN.fullmatch(observed_at_text) is None:
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.OBSERVED_AT)
    try:
        observed_at = datetime.fromisoformat(observed_at_text)
        return RuleLoadObservationV1(
            observation_id=record["observation_id"],
            process_epoch=record["process_epoch"],
            sequence=record["sequence"],
            binding_id=record["binding_id"],
            profile_id=record["profile_id"],
            event_kind=event_kind,
            active_snapshot=active_snapshot,
            attempt=attempt,
            observed_at=observed_at,
        )
    except (TypeError, ValueError):
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.ATTEMPT) from None


def _encode_snapshot(value: RuleLoadSnapshotV1 | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "source_revision": value.source_revision,
        "source_bytes_sha256": value.source_bytes_sha256,
        "canonical_rules_sha256": value.canonical_rules_sha256,
        "membership_complete": value.membership_complete,
        "members": [
            {"rule_kind": member.rule_kind.value, "fingerprint_sha256": member.fingerprint_sha256}
            for member in value.members
        ],
    }


def _encode_attempt(value: RuleLoadAttemptV1 | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "source_revision": value.source_revision,
        "source_bytes_sha256": value.source_bytes_sha256,
        "canonical_rules_sha256": value.canonical_rules_sha256,
        "failure_reason": value.failure_reason.value,
    }


def _decode_snapshot(value: object) -> RuleLoadSnapshotV1 | None:
    if value is None:
        return None
    if not isinstance(value, dict) or frozenset(value) != _SNAPSHOT_FIELDS:
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.SNAPSHOT)
    members_value = value["members"]
    if not isinstance(members_value, list) or len(members_value) > MAX_RULE_LOAD_OBSERVATION_MEMBERS:
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.MEMBER)
    members: list[RuleLoadMemberFingerprint] = []
    try:
        for item in members_value:
            if not isinstance(item, dict) or frozenset(item) != _MEMBER_FIELDS:
                raise ValueError("member fields")
            members.append(
                RuleLoadMemberFingerprint(
                    rule_kind=RuleKind(item["rule_kind"]),
                    fingerprint_sha256=item["fingerprint_sha256"],
                )
            )
        return RuleLoadSnapshotV1(
            source_revision=value["source_revision"],
            source_bytes_sha256=value["source_bytes_sha256"],
            canonical_rules_sha256=value["canonical_rules_sha256"],
            membership_complete=value["membership_complete"],
            members=tuple(members),
        )
    except (TypeError, ValueError):
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.MEMBER) from None


def _decode_attempt(value: object) -> RuleLoadAttemptV1 | None:
    if value is None:
        return None
    if not isinstance(value, dict) or frozenset(value) != _ATTEMPT_FIELDS:
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.ATTEMPT)
    try:
        return RuleLoadAttemptV1(
            source_revision=value["source_revision"],
            source_bytes_sha256=value["source_bytes_sha256"],
            canonical_rules_sha256=value["canonical_rules_sha256"],
            failure_reason=RuleLoadFailureReason(value["failure_reason"]),
        )
    except (TypeError, ValueError):
        raise RuleLoadObservationError(RuleLoadObservationErrorCode.ATTEMPT) from None


def _validate_uuid(value: object) -> None:
    if not isinstance(value, str):
        raise TypeError("UUID must be a string")
    parsed = UUID(value)
    if str(parsed) != value or parsed.version != 4:
        raise ValueError("UUID must be canonical UUID v4")


def _validate_digest(value: object) -> None:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError("digest must be lowercase SHA-256")


def _validate_optional_digest(value: object) -> None:
    if value is not None:
        _validate_digest(value)


def _validate_source_revision(value: object) -> None:
    if value is not None and (
        not isinstance(value, str)
        or not 1 <= len(value) <= 200
        or any(not 0x20 <= ord(character) <= 0x7E for character in value)
    ):
        raise ValueError("source revision is invalid")


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RuleLoadObservationError(RuleLoadObservationErrorCode.DUPLICATE_FIELD)
        result[key] = value
    return result


def _reject_non_json_number(value: str) -> None:
    raise RuleLoadObservationError(RuleLoadObservationErrorCode.INVALID_JSON)


__all__ = [
    "MAX_RULE_LOAD_OBSERVATION_BYTES",
    "MAX_RULE_LOAD_OBSERVATION_MEMBERS",
    "RULE_LOAD_OBSERVATION_V1",
    "RuleKind",
    "RuleLoadAttemptV1",
    "RuleLoadEventKind",
    "RuleLoadFailureReason",
    "RuleLoadMemberFingerprint",
    "RuleLoadObservationError",
    "RuleLoadObservationErrorCode",
    "RuleLoadObservationV1",
    "RuleLoadSnapshotV1",
    "decode_rule_load_observation",
    "encode_rule_load_observation",
]
