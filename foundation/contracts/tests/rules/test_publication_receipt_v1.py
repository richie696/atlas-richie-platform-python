"""Strict Rule Publication Receipt V1 contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from atlas_richie.contracts.rules.publication_receipt.v1 import (
    PublicationReceiptError,
    PublicationReceiptReason,
    PublicationReceiptState,
    RulePublicationReceiptV1,
    decode_rule_publication_receipt,
    encode_rule_publication_receipt,
)

_RECEIPT_ID = "3d6f0a82-39e2-4e57-a81e-029808927952"
_PROCESS_EPOCH = "590e8a11-e2fb-4cf9-9f01-8230f249875a"
_DIGEST = "0" * 64


def _receipt(
    *,
    state: PublicationReceiptState = PublicationReceiptState.APPLIED,
    reason: PublicationReceiptReason | None = None,
) -> RulePublicationReceiptV1:
    return RulePublicationReceiptV1(
        receipt_id=_RECEIPT_ID,
        process_epoch=_PROCESS_EPOCH,
        sequence=1,
        binding_id="binding-1",
        publication_id="publication-1",
        target_version_id="version-1",
        target_payload_sha256=_DIGEST,
        state=state,
        reason=reason,
        source_revision="revision-1",
        observed_at=datetime(2026, 10, 15, 2, 30, 45, 123000, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "receipt",
    (
        _receipt(),
        _receipt(state=PublicationReceiptState.PENDING),
        _receipt(state=PublicationReceiptState.UNKNOWN),
        _receipt(
            state=PublicationReceiptState.FAILED,
            reason=PublicationReceiptReason.APPLY_FAILED,
        ),
        _receipt(
            state=PublicationReceiptState.RESTART_REQUIRED,
            reason=PublicationReceiptReason.RESTART_REQUIRED,
        ),
    ),
)
def test_receipt_round_trip(receipt: RulePublicationReceiptV1) -> None:
    encoded = encode_rule_publication_receipt(receipt)

    assert decode_rule_publication_receipt(encoded) == receipt


@pytest.mark.parametrize(
    ("state", "reason"),
    (
        (PublicationReceiptState.FAILED, None),
        (PublicationReceiptState.FAILED, PublicationReceiptReason.RESTART_REQUIRED),
        (PublicationReceiptState.RESTART_REQUIRED, None),
        (PublicationReceiptState.APPLIED, PublicationReceiptReason.APPLY_FAILED),
        (PublicationReceiptState.PENDING, PublicationReceiptReason.SOURCE_UNAVAILABLE),
    ),
)
def test_state_reason_pairings_are_rejected(
    state: PublicationReceiptState, reason: PublicationReceiptReason | None
) -> None:
    with pytest.raises(ValueError):
        _receipt(state=state, reason=reason)


@pytest.mark.parametrize(
    "payload",
    (
        b'{"a":1,"a":2}',
        b"[]",
        b'{"protocol_version": NaN}',
        b"\xff",
    ),
)
def test_malformed_or_non_object_payloads_rejected_without_echo(payload: bytes) -> None:
    with pytest.raises(PublicationReceiptError):
        decode_rule_publication_receipt(payload)


def test_wire_time_requires_exact_utc_millisecond_form() -> None:
    encoded = encode_rule_publication_receipt(_receipt())
    invalid = encoded.replace(b"2026-10-15T02:30:45.123Z", b"2026-10-15T02:30:45+00:00")

    with pytest.raises(PublicationReceiptError):
        decode_rule_publication_receipt(invalid)
