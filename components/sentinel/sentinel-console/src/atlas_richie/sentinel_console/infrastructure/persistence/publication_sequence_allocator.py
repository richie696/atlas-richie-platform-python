"""Allocate monotonic publication sequences inside the caller's SQL transaction."""

from __future__ import annotations

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from ...domain.wire_numbers import MAX_SAFE_JSON_INTEGER
from .models import RuleBindingPublicationSequenceRecord, RulePublicationRecord


class SqlAlchemyPublicationSequenceAllocator:
    """Serialize sequence allocation through a durable per-binding counter row."""

    async def next(self, connection, binding_id: str) -> int:
        """Return the next sequence; caller owns and commits the transaction."""
        if not isinstance(binding_id, str) or not binding_id.strip():
            raise ValueError("publication binding identity is invalid")
        counter_result = await connection.execute(
            select(RuleBindingPublicationSequenceRecord.last_sequence)
            .where(RuleBindingPublicationSequenceRecord.binding_id == binding_id)
            .with_for_update()
        )
        if counter_result.scalar_one_or_none() is None:
            prior_sequence = await connection.scalar(
                select(func.max(RulePublicationRecord.publication_sequence)).where(
                    RulePublicationRecord.binding_id == binding_id
                )
            )
            try:
                async with connection.begin_nested():
                    await connection.execute(
                        insert(RuleBindingPublicationSequenceRecord).values(
                            binding_id=binding_id,
                            last_sequence=prior_sequence or 0,
                        )
                    )
            except IntegrityError:
                # Another transaction established the counter while this one waited.
                pass

        updated = await connection.execute(
            update(RuleBindingPublicationSequenceRecord)
            .where(RuleBindingPublicationSequenceRecord.binding_id == binding_id)
            .values(
                last_sequence=RuleBindingPublicationSequenceRecord.last_sequence + 1
            )
        )
        if updated.rowcount != 1:
            raise RuntimeError("publication sequence authority is unavailable")
        sequence = await connection.scalar(
            select(RuleBindingPublicationSequenceRecord.last_sequence).where(
                RuleBindingPublicationSequenceRecord.binding_id == binding_id
            )
        )
        if type(sequence) is not int or not 1 <= sequence <= MAX_SAFE_JSON_INTEGER:
            raise RuntimeError("publication sequence authority is invalid")
        return sequence
