"""Shared candidate fixtures for managed rule publication envelope V1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pytest

_FIXTURES = Path(__file__).with_name("fixtures")
_PROTOCOL_VERSION = "atlas-richie.sentinel.managed-rule-publication/v1"
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
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_RULE_KINDS = frozenset({"flow", "degrade", "system", "authority", "param"})
_MAX_PAYLOAD_BYTES = 512 * 1024
_MAX_RULE_PAYLOAD_BYTES = 500 * 1024
_MAX_SEQUENCE = 9_007_199_254_740_991


class EnvelopeRejected(ValueError):
    """Stable test-only rejection for malformed candidate envelopes."""


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EnvelopeRejected("duplicate_json_key")
        result[key] = value
    return result


def validate_candidate(payload: bytes) -> tuple[dict[str, object], bytes]:
    """Validate a draft envelope and return the parsed record and exact rule bytes."""
    if not isinstance(payload, bytes) or not 0 < len(payload) <= _MAX_PAYLOAD_BYTES:
        raise EnvelopeRejected("payload_size")
    try:
        decoded = payload.decode("utf-8", errors="strict")
        envelope = json.loads(
            decoded,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                EnvelopeRejected("non_json_number")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EnvelopeRejected("invalid_json") from error
    if not isinstance(envelope, dict) or frozenset(envelope) != _FIELDS:
        raise EnvelopeRejected("fields")
    if envelope["protocol_version"] != _PROTOCOL_VERSION:
        raise EnvelopeRejected("protocol_version")
    for field in ("binding_id", "publication_id", "target_version_id", "profile_id"):
        value = envelope[field]
        if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
            raise EnvelopeRejected(field)
    sequence = envelope["publication_sequence"]
    if type(sequence) is not int or not 1 <= sequence <= _MAX_SEQUENCE:
        raise EnvelopeRejected("publication_sequence")
    rule_kind = envelope["rule_kind"]
    if not isinstance(rule_kind, str) or rule_kind not in _RULE_KINDS:
        raise EnvelopeRejected("rule_kind")
    digest = envelope["payload_sha256"]
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise EnvelopeRejected("payload_sha256")
    rule_payload = envelope["rule_payload"]
    if not isinstance(rule_payload, str):
        raise EnvelopeRejected("rule_payload")
    try:
        rule_bytes = rule_payload.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise EnvelopeRejected("rule_payload_utf8") from error
    if len(rule_bytes) > _MAX_RULE_PAYLOAD_BYTES:
        raise EnvelopeRejected("rule_payload_size")
    try:
        rules = json.loads(
            rule_bytes.decode("utf-8"),
            object_pairs_hook=_object_without_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                EnvelopeRejected("non_json_number")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EnvelopeRejected("rule_payload_json") from error
    if not isinstance(rules, list) or any(not isinstance(rule, dict) for rule in rules):
        raise EnvelopeRejected("rule_payload_shape")
    actual_digest = hashlib.sha256(rule_bytes).hexdigest()
    if actual_digest != digest:
        raise EnvelopeRejected("payload_sha256_mismatch")
    return envelope, rule_bytes


@pytest.mark.parametrize(
    "fixture_name",
    ("valid_empty_rules.json", "valid_utf8_rules.json"),
)
def test_valid_shared_fixtures_preserve_exact_inner_utf8_bytes(fixture_name: str):
    record, rule_bytes = validate_candidate((_FIXTURES / fixture_name).read_bytes())

    assert record["protocol_version"] == _PROTOCOL_VERSION
    assert hashlib.sha256(rule_bytes).hexdigest() == record["payload_sha256"]
    if fixture_name == "valid_empty_rules.json":
        assert rule_bytes == b"[]"
    else:
        assert rule_bytes == '[{"resource":"订单","grade":1,"count":10}]'.encode()


def test_invalid_shared_fixtures_are_rejected():
    fixture_paths = sorted(_FIXTURES.glob("invalid_*.json"))
    assert fixture_paths
    for fixture_path in fixture_paths:
        with pytest.raises(EnvelopeRejected):
            validate_candidate(fixture_path.read_bytes())


def test_native_array_is_not_implicitly_treated_as_managed_envelope():
    with pytest.raises(EnvelopeRejected):
        validate_candidate(b"[]")
