"""Validate and durably accept authenticated Rule Publication Receipt V1 facts."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from atlas_richie.contracts.rules.publication_receipt import (
    RulePublicationReceiptV1,
    decode_rule_publication_receipt,
)

from .metrics_ingest_ports import VerifiedMetricsPeer
from .publication_receipt_ingest_ports import (
    PublicationReceiptInboxPort,
    PublicationReceiptIngestError,
    PublicationReceiptIngestErrorCode,
)


class IngestRulePublicationReceipt:
    """Keep strict wire parsing separate from SQL authority and persistence."""

    def __init__(
        self,
        inbox: PublicationReceiptInboxPort,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._inbox = inbox
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self, peer: VerifiedMetricsPeer | None, body: bytes
    ) -> RulePublicationReceiptV1:
        """Accept exact body bytes only after trusted SQL storage commits."""
        if peer is None or not isinstance(peer, VerifiedMetricsPeer):
            raise PublicationReceiptIngestError(
                PublicationReceiptIngestErrorCode.IDENTITY_NOT_ENROLLED
            )
        receipt = decode_rule_publication_receipt(body)
        received_at = self._clock()
        if (
            not isinstance(received_at, datetime)
            or received_at.tzinfo is None
            or received_at.utcoffset() != UTC.utcoffset(received_at)
        ):
            raise RuntimeError("Collector clock must return an aware UTC instant")
        await self._inbox.accept(
            peer=peer,
            receipt=receipt,
            body=body,
            body_sha256=hashlib.sha256(body).hexdigest(),
            received_at=received_at.astimezone(UTC),
        )
        return receipt


__all__ = ["IngestRulePublicationReceipt"]
