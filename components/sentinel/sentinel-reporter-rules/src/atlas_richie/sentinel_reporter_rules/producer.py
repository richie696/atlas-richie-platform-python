"""Map successfully applied managed targets to immutable Receipt V1 facts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from uuid import UUID, uuid4

from atlas_richie.contracts.rules.publication_receipt import (
    MAX_RULE_PUBLICATION_RECEIPT_SEQUENCE,
    PublicationReceiptState,
    RulePublicationReceiptV1,
    encode_rule_publication_receipt,
)
from atlas_richie.sentinel.rules import RuleSnapshotAppliedEvent


class RulePublicationReceiptProducer:
    """Create exact per-target receipts from committed Sentinel apply events.

    The producer has no transport or persistence dependency. It owns the
    process-epoch sequence and stable values for one observed apply event;
    callers retain and retry the returned encoded bytes unchanged.
    """

    __slots__ = (
        "_clock",
        "_epoch",
        "_lock",
        "_next_sequence",
        "_receipt_id_factory",
    )

    def __init__(
        self,
        process_epoch: UUID,
        *,
        clock: Callable[[], datetime] | None = None,
        receipt_id_factory: Callable[[], UUID] = uuid4,
        initial_sequence: int = 0,
    ) -> None:
        if type(process_epoch) is not UUID:
            raise TypeError("process_epoch must be a UUID")
        if not callable(receipt_id_factory):
            raise TypeError("receipt_id_factory must be callable")
        if (
            type(initial_sequence) is not int
            or not 0 <= initial_sequence <= MAX_RULE_PUBLICATION_RECEIPT_SEQUENCE
        ):
            raise ValueError("initial_sequence is outside the safe integer range")
        self._epoch = process_epoch
        self._clock = clock or (lambda: datetime.now(UTC))
        self._receipt_id_factory = receipt_id_factory
        self._next_sequence = initial_sequence
        self._lock = Lock()

    @property
    def last_sequence(self) -> int:
        """Return the last assigned sequence for this process epoch."""
        with self._lock:
            return self._next_sequence

    def for_applied_event(self, event: RuleSnapshotAppliedEvent) -> tuple[bytes, ...]:
        """Encode one `applied` Receipt V1 for every committed target provenance.

        An event without managed target provenance produces no receipts. The
        event is emitted only after the repository atomically swaps rules and
        provenance, so this producer cannot report an unapplied candidate as
        applied.
        """
        if not isinstance(event, RuleSnapshotAppliedEvent):
            raise TypeError("event must be RuleSnapshotAppliedEvent")
        if not event.provenance:
            return ()
        with self._lock:
            observed_at = _utc_millisecond(self._clock())
            payloads: list[bytes] = []
            next_sequence = self._next_sequence
            receipt_ids: set[UUID] = set()
            for provenance in event.provenance:
                receipt_id = self._receipt_id_factory()
                if type(receipt_id) is not UUID:
                    raise TypeError("receipt_id_factory must return a UUID")
                if receipt_id in receipt_ids:
                    raise ValueError("receipt_id_factory returned a duplicate UUID")
                receipt_ids.add(receipt_id)
                next_sequence += 1
                receipt = RulePublicationReceiptV1(
                    receipt_id=str(receipt_id),
                    process_epoch=str(self._epoch),
                    sequence=next_sequence,
                    binding_id=provenance.binding_id,
                    publication_id=provenance.publication_id,
                    target_version_id=provenance.target_version_id,
                    target_payload_sha256=provenance.payload_sha256,
                    state=PublicationReceiptState.APPLIED,
                    reason=None,
                    source_revision=None,
                    observed_at=observed_at,
                )
                payloads.append(encode_rule_publication_receipt(receipt))
            self._next_sequence = next_sequence
            return tuple(payloads)


def _utc_millisecond(value: datetime) -> datetime:
    """Normalize the injected clock to the wire contract's UTC millisecond."""
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("receipt clock must return a timezone-aware datetime")
    if value.utcoffset() is None:
        raise ValueError("receipt clock must return a timezone-aware datetime")
    utc_value = value.astimezone(UTC)
    return utc_value.replace(microsecond=(utc_value.microsecond // 1000) * 1000)


__all__ = ["RulePublicationReceiptProducer"]
