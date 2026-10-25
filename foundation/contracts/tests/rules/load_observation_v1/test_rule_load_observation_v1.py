"""Strict Rule Load Observation V1 contract and schema tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest

from atlas_richie.contracts.rules.load_observation.v1 import (
    MAX_RULE_LOAD_OBSERVATION_BYTES,
    RuleKind,
    RuleLoadAttemptV1,
    RuleLoadEventKind,
    RuleLoadFailureReason,
    RuleLoadMemberFingerprint,
    RuleLoadObservationError,
    RuleLoadObservationV1,
    RuleLoadSnapshotV1,
    decode_rule_load_observation,
    encode_rule_load_observation,
)

_OBSERVATION_ID = "3d6f0a82-39e2-4e57-a81e-029808927952"
_PROCESS_EPOCH = "590e8a11-e2fb-4cf9-9f01-8230f249875a"
_DIGEST_A = "0" * 64
_DIGEST_B = "1" * 64
_OBSERVED_AT = datetime(2026, 10, 16, 2, 30, 45, 123000, tzinfo=UTC)
_SCHEMA_PATH = (
    Path(__file__).parents[3]
    / "schemas"
    / "rules"
    / "rule-load-observation-v1.schema.json"
)
_FIXTURES_PATH = Path(__file__).parent / "fixtures"


def _active_snapshot() -> RuleLoadSnapshotV1:
    return RuleLoadSnapshotV1(
        source_revision="provider-revision-7",
        source_bytes_sha256=_DIGEST_A,
        canonical_rules_sha256=_DIGEST_B,
        membership_complete=True,
        members=(
            RuleLoadMemberFingerprint(RuleKind.FLOW, _DIGEST_A),
            RuleLoadMemberFingerprint(RuleKind.FLOW, _DIGEST_B),
        ),
    )


def _observation(
    *,
    kind: RuleLoadEventKind = RuleLoadEventKind.SNAPSHOT_APPLIED,
    active_snapshot: RuleLoadSnapshotV1 | None = None,
    attempt: RuleLoadAttemptV1 | None = None,
) -> RuleLoadObservationV1:
    return RuleLoadObservationV1(
        observation_id=_OBSERVATION_ID,
        process_epoch=_PROCESS_EPOCH,
        sequence=1,
        binding_id="binding-1",
        profile_id="sentinel-python-v1",
        event_kind=kind,
        active_snapshot=_active_snapshot() if active_snapshot is None and kind is RuleLoadEventKind.SNAPSHOT_APPLIED else active_snapshot,
        attempt=attempt,
        observed_at=_OBSERVED_AT,
    )


@pytest.mark.parametrize(
    "value",
    (
        _observation(),
        _observation(kind=RuleLoadEventKind.HEARTBEAT),
        _observation(
            kind=RuleLoadEventKind.SNAPSHOT_FAILED,
            active_snapshot=_active_snapshot(),
            attempt=RuleLoadAttemptV1(
                source_revision="provider-revision-8",
                source_bytes_sha256=_DIGEST_B,
                canonical_rules_sha256=None,
                failure_reason=RuleLoadFailureReason.DECODE_REJECTED,
            ),
        ),
    ),
)
def test_observation_round_trip_and_json_schema(value: RuleLoadObservationV1) -> None:
    encoded = encode_rule_load_observation(value)
    decoded = decode_rule_load_observation(encoded)
    assert decoded == value

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(json.loads(encoded))


@pytest.mark.parametrize(
    "fixture_path",
    sorted(_FIXTURES_PATH.glob("valid_*.json")),
    ids=lambda path: path.name,
)
def test_shared_positive_fixtures_decode_and_match_schema(fixture_path: Path) -> None:
    fixture = fixture_path.read_bytes()
    observation = decode_rule_load_observation(fixture)
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator(schema).validate(json.loads(fixture))
    assert json.loads(encode_rule_load_observation(observation)) == json.loads(fixture)


@pytest.mark.parametrize(
    "fixture_path",
    sorted(_FIXTURES_PATH.glob("invalid_*.json")),
    ids=lambda path: path.name,
)
def test_shared_negative_fixtures_are_rejected(fixture_path: Path) -> None:
    fixture = fixture_path.read_bytes()

    with pytest.raises(RuleLoadObservationError):
        decode_rule_load_observation(fixture)


def test_failed_load_keeps_active_snapshot_separate_from_candidate() -> None:
    observation = _observation(
        kind=RuleLoadEventKind.SNAPSHOT_FAILED,
        active_snapshot=_active_snapshot(),
        attempt=RuleLoadAttemptV1(
            source_revision="provider-revision-8",
            source_bytes_sha256=_DIGEST_B,
            canonical_rules_sha256=None,
            failure_reason=RuleLoadFailureReason.DECODE_REJECTED,
        ),
    )

    encoded = json.loads(encode_rule_load_observation(observation))

    assert encoded["active_snapshot"]["source_revision"] == "provider-revision-7"
    assert encoded["attempt"]["source_revision"] == "provider-revision-8"
    assert "resource" not in json.dumps(encoded).lower()


@pytest.mark.parametrize(
    "payload",
    (
        b'{"x":1,"x":2}',
        b"[]",
        b'{"protocol_version":NaN}',
        b"\xff",
    ),
)
def test_malformed_json_rejected(payload: bytes) -> None:
    with pytest.raises(RuleLoadObservationError):
        decode_rule_load_observation(payload)


def test_body_size_limit_is_enforced() -> None:
    with pytest.raises(RuleLoadObservationError):
        decode_rule_load_observation(b" " * (MAX_RULE_LOAD_OBSERVATION_BYTES + 1))


def test_unknown_field_and_wrong_protocol_rejected() -> None:
    value = json.loads(encode_rule_load_observation(_observation()))
    value["raw_rules"] = "must not be accepted"
    with pytest.raises(RuleLoadObservationError):
        decode_rule_load_observation(json.dumps(value).encode())

    value.pop("raw_rules")
    value["protocol_version"] = "atlas-richie.sentinel.rule-load-observation/v2"
    with pytest.raises(RuleLoadObservationError):
        decode_rule_load_observation(json.dumps(value).encode())


def test_incomplete_membership_cannot_claim_partial_fingerprints() -> None:
    with pytest.raises(ValueError):
        RuleLoadSnapshotV1(
            source_revision=None,
            source_bytes_sha256=None,
            canonical_rules_sha256=_DIGEST_A,
            membership_complete=False,
            members=(RuleLoadMemberFingerprint(RuleKind.FLOW, _DIGEST_B),),
        )


def test_applied_and_failed_invariant_and_observed_timestamp() -> None:
    with pytest.raises(ValueError):
        _observation(
            kind=RuleLoadEventKind.SNAPSHOT_APPLIED,
            active_snapshot=None,
            attempt=RuleLoadAttemptV1(
                None, None, None, RuleLoadFailureReason.SOURCE_UNAVAILABLE
            ),
        )
    with pytest.raises(ValueError):
        _observation(
            kind=RuleLoadEventKind.SNAPSHOT_FAILED,
            active_snapshot=_active_snapshot(),
        )

    with pytest.raises(ValueError):
        RuleLoadObservationV1(
            observation_id=_OBSERVATION_ID,
            process_epoch=_PROCESS_EPOCH,
            sequence=1,
            binding_id="binding-1",
            profile_id="sentinel-python-v1",
            event_kind=RuleLoadEventKind.HEARTBEAT,
            active_snapshot=None,
            attempt=None,
            observed_at=datetime(2026, 10, 16, 2, 30, 45, 123456, tzinfo=UTC),
        )
