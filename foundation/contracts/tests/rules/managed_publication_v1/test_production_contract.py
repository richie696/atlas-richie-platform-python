"""Tests for the shared production managed-publication codec."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from atlas_richie.contracts.rules.managed_publication.v1 import (
    ManagedRulePublicationError,
    decode_managed_rule_publication,
    encode_managed_rule_publication,
)

_FIXTURES = Path(__file__).with_name("fixtures")


@pytest.mark.parametrize(
    ("fixture_name", "expected_payload"),
    (
        ("valid_empty_rules.json", b"[]"),
        (
            "valid_utf8_rules.json",
            '[{"resource":"订单","grade":1,"count":10}]'.encode(),
        ),
    ),
)
def test_production_codec_preserves_exact_native_payload_bytes(
    fixture_name: str, expected_payload: bytes
) -> None:
    publication = decode_managed_rule_publication(
        (_FIXTURES / fixture_name).read_bytes()
    )

    assert publication.rule_payload == expected_payload
    assert (
        hashlib.sha256(publication.rule_payload).hexdigest()
        == publication.payload_sha256
    )
    assert (
        decode_managed_rule_publication(encode_managed_rule_publication(publication))
        == publication
    )


def test_production_codec_rejects_all_invalid_shared_fixtures() -> None:
    fixture_paths = sorted(_FIXTURES.glob("invalid_*.json"))
    assert fixture_paths

    for fixture_path in fixture_paths:
        with pytest.raises(ManagedRulePublicationError):
            decode_managed_rule_publication(fixture_path.read_bytes())


def test_native_rule_array_is_not_implicitly_a_managed_envelope() -> None:
    with pytest.raises(ManagedRulePublicationError):
        decode_managed_rule_publication(b"[]")
