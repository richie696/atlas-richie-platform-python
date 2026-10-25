"""Contract tests for mapping applied target provenance to Receipt V1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from atlas_richie.contracts.rules.publication_receipt import (
    PublicationReceiptState,
    decode_rule_publication_receipt,
)
from atlas_richie.sentinel.rules import (
    RuleRepository,
    RuleSnapshot,
    RuleSnapshotAppliedEvent,
    RuleTargetKind,
    RuleTargetProvenance,
    RuleVersion,
)
from atlas_richie.sentinel_reporter_rules import RulePublicationReceiptProducer


def _provenance(suffix: str) -> RuleTargetProvenance:
    return RuleTargetProvenance(
        binding_id=f"binding-{suffix}",
        publication_id=f"publication-{suffix}",
        target_version_id=f"version-{suffix}",
        publication_sequence=1,
        rule_kind=RuleTargetKind.FLOW,
        profile_id="managed-v1",
        payload_sha256=(suffix[0] * 64),
    )


def _event(*provenance: RuleTargetProvenance) -> RuleSnapshotAppliedEvent:
    return RuleSnapshotAppliedEvent(
        version=RuleVersion(epoch=1, revision=2, checksum="a" * 64),
        rule_count=3,
        at_ns=42,
        provenance=tuple(provenance),
    )


def test_producer_preserves_exact_target_tuple_and_digest() -> None:
    epoch = uuid4()
    observed_at = datetime(2026, 10, 15, 1, 2, 3, 123456, tzinfo=UTC)
    producer = RulePublicationReceiptProducer(
        epoch,
        clock=lambda: observed_at,
        receipt_id_factory=iter((uuid4(), uuid4())).__next__,
    )

    payloads = producer.for_applied_event(_event(_provenance("a"), _provenance("b")))
    receipts = tuple(decode_rule_publication_receipt(payload) for payload in payloads)

    assert len(receipts) == 2
    assert [item.sequence for item in receipts] == [1, 2]
    assert all(item.process_epoch == str(epoch) for item in receipts)
    assert all(item.state is PublicationReceiptState.APPLIED for item in receipts)
    assert all(item.observed_at.microsecond == 123000 for item in receipts)
    assert [
        (
            item.binding_id,
            item.publication_id,
            item.target_version_id,
            item.target_payload_sha256,
        )
        for item in receipts
    ] == [
        ("binding-a", "publication-a", "version-a", "a" * 64),
        ("binding-b", "publication-b", "version-b", "b" * 64),
    ]
    assert producer.last_sequence == 2


def test_unmanaged_event_produces_no_receipt_or_sequence_gap() -> None:
    producer = RulePublicationReceiptProducer(uuid4())

    assert producer.for_applied_event(_event()) == ()
    assert producer.last_sequence == 0


def test_invalid_receipt_id_does_not_partially_advance_sequence() -> None:
    identifiers = iter((uuid4(), "not-a-uuid"))
    producer = RulePublicationReceiptProducer(
        uuid4(),
        receipt_id_factory=lambda: next(identifiers),  # type: ignore[arg-type]
    )

    with pytest.raises(TypeError, match="receipt_id_factory"):
        producer.for_applied_event(_event(_provenance("a"), _provenance("b")))

    assert producer.last_sequence == 0


def test_sequence_continues_across_apply_events() -> None:
    producer = RulePublicationReceiptProducer(uuid4())

    first = decode_rule_publication_receipt(
        producer.for_applied_event(_event(_provenance("a")))[0]
    )
    second = decode_rule_publication_receipt(
        producer.for_applied_event(_event(_provenance("b")))[0]
    )

    assert (first.sequence, second.sequence) == (1, 2)


def test_producer_rejects_naive_clock_without_advancing_sequence() -> None:
    producer = RulePublicationReceiptProducer(
        uuid4(), clock=lambda: datetime(2026, 10, 15, tzinfo=UTC).replace(tzinfo=None)
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        producer.for_applied_event(_event(_provenance("a")))

    assert producer.last_sequence == 0


def test_producer_rejects_non_event_input() -> None:
    producer = RulePublicationReceiptProducer(uuid4())

    with pytest.raises(TypeError, match="RuleSnapshotAppliedEvent"):
        producer.for_applied_event(None)  # type: ignore[arg-type]


def test_repository_apply_event_emits_receipt_after_atomic_rules_and_provenance_swap() -> (
    None
):
    producer = RulePublicationReceiptProducer(uuid4())
    repository = RuleRepository()
    captured: list[bytes] = []
    repository.subscribe(
        lambda event: captured.extend(producer.for_applied_event(event))
    )
    snapshot = RuleSnapshot(
        version=RuleVersion(epoch=1, revision=1, checksum="b" * 64),
        rules={},
        source_id="nacos-prod",
        provenance=(_provenance("a"),),
    )

    assert repository.apply_snapshot(snapshot)

    applied = repository.current_snapshot
    assert applied is not None
    assert applied.provenance == snapshot.provenance
    receipt = decode_rule_publication_receipt(captured[0])
    assert receipt.binding_id == applied.provenance[0].binding_id
    assert receipt.publication_id == applied.provenance[0].publication_id
    assert receipt.target_version_id == applied.provenance[0].target_version_id
    assert receipt.target_payload_sha256 == applied.provenance[0].payload_sha256


def test_clock_normalization_handles_non_utc_offsets() -> None:
    producer = RulePublicationReceiptProducer(
        uuid4(),
        clock=lambda: datetime(2026, 10, 15, 9, 0, tzinfo=timezone(timedelta(hours=8))),
    )

    receipt = decode_rule_publication_receipt(
        producer.for_applied_event(_event(_provenance("a")))[0]
    )

    assert receipt.observed_at == datetime(2026, 10, 15, 1, 0, tzinfo=UTC)
