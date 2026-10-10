"""Persist and read the latest instance outcomes for rule publications."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import case, func, insert, select, true, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_publication_ports import (
    RulePublicationAuthorityUnavailable,
    RulePublicationConflict,
    RulePublicationDetailReader,
    RulePublicationNotFound,
    RulePublicationReceiptReader,
    RulePublicationReceiptWriter,
)
from ...domain.rule_publications import (
    PublicationReceiptState,
    RulePublication,
    RulePublicationReceipt,
    RulePublicationReceiptPage,
)
from .models import RulePublicationRecord, RulePublicationReceiptRecord
from .rule_publication_mapping import publication_from_row
from .rule_publication_receipt_mapping import (
    publication_receipt_from_row,
    publication_receipt_values,
)


class SqlAlchemyRulePublicationReceiptStore(
    RulePublicationReceiptReader, RulePublicationReceiptWriter
):
    """Own current receipt snapshots and exact-publication receipt paging."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record_rule_publication_receipt(
        self,
        binding_id: str,
        publication_id: str,
        receipt: RulePublicationReceipt,
    ) -> None:
        """Persist one Collector-timestamped snapshot without accepting stale data."""
        if not isinstance(receipt, RulePublicationReceipt):
            raise ValueError("publication receipt is invalid")
        try:
            async with self._engine.begin() as connection:
                publication_result = await connection.execute(
                    select(RulePublicationRecord.__table__)
                    .where(
                        RulePublicationRecord.binding_id == binding_id,
                        RulePublicationRecord.publication_id == publication_id,
                    )
                )
                publication_row = publication_result.mappings().one_or_none()
                if publication_row is None:
                    raise RulePublicationNotFound(
                        "rule publication does not exist"
                    )
                publication = publication_from_row(publication_row)
                if receipt.target_version_id != publication.target_version_id:
                    raise RulePublicationConflict(
                        "runtime receipt targets another publication version"
                    )
                if (
                    receipt.state is PublicationReceiptState.APPLIED
                    and receipt.loaded_checksum != publication.target_checksum
                ):
                    raise RulePublicationConflict(
                        "runtime receipt checksum does not match publication"
                    )

                receipt_table = RulePublicationReceiptRecord.__table__
                key = (
                    RulePublicationReceiptRecord.publication_id == publication_id,
                    RulePublicationReceiptRecord.instance_id == receipt.instance_id,
                )
                current_result = await connection.execute(
                    select(receipt_table).where(*key).with_for_update()
                )
                current_row = current_result.mappings().one_or_none()
                values = publication_receipt_values(
                    binding_id, publication_id, receipt
                )
                if current_row is None:
                    await connection.execute(insert(receipt_table).values(**values))
                else:
                    current = publication_receipt_from_row(current_row)
                    if current == receipt:
                        return
                    if (
                        receipt.last_report_at is None
                        or (
                            current.last_report_at is not None
                            and receipt.last_report_at <= current.last_report_at
                        )
                    ):
                        raise RulePublicationConflict(
                            "runtime receipt is stale or conflicts at the same time"
                        )
                    changed = await connection.execute(
                        update(receipt_table)
                        .where(*key)
                        .values(**values)
                    )
                    if changed.rowcount != 1:
                        raise RulePublicationConflict(
                            "runtime receipt changed while being updated"
                        )
        except (RulePublicationNotFound, RulePublicationConflict):
            raise
        except IntegrityError:
            try:
                async with self._engine.connect() as connection:
                    duplicate_result = await connection.execute(
                        select(RulePublicationReceiptRecord.__table__).where(
                            RulePublicationReceiptRecord.publication_id
                            == publication_id,
                            RulePublicationReceiptRecord.instance_id
                            == receipt.instance_id,
                        )
                    )
                    duplicate_row = duplicate_result.mappings().one_or_none()
                if (
                    duplicate_row is not None
                    and duplicate_row["binding_id"] == binding_id
                    and publication_receipt_from_row(duplicate_row) == receipt
                ):
                    return
            except SQLAlchemyError:
                raise RulePublicationAuthorityUnavailable(
                    "runtime publication receipt could not be reconciled"
                ) from None
            except (KeyError, TypeError, ValueError):
                raise RulePublicationAuthorityUnavailable(
                    "persisted runtime publication receipt is invalid"
                ) from None
            raise RulePublicationConflict(
                "runtime receipt identity already exists or is invalid"
            ) from None
        except (KeyError, TypeError, ValueError):
            raise RulePublicationAuthorityUnavailable(
                "persisted runtime publication receipt is invalid"
            ) from None
        except SQLAlchemyError:
            raise RulePublicationAuthorityUnavailable(
                "runtime publication receipt could not be persisted"
            ) from None

    async def read_rule_publication_receipts(
        self,
        binding_id: str,
        publication_id: str,
        page: int,
        page_size: int,
    ) -> RulePublicationReceiptPage:
        """Return stable instance ordering and full-population status counters."""
        receipt_table = RulePublicationReceiptRecord.__table__
        filters = (
            RulePublicationReceiptRecord.binding_id == binding_id,
            RulePublicationReceiptRecord.publication_id == publication_id,
        )
        counts = (
            select(
                func.count().label("total"),
                _count_state(receipt_table, PublicationReceiptState.APPLIED).label(
                    "applied"
                ),
                _count_state(receipt_table, PublicationReceiptState.PENDING).label(
                    "pending"
                ),
                _count_state(receipt_table, PublicationReceiptState.FAILED).label(
                    "failed"
                ),
                _count_state(receipt_table, PublicationReceiptState.UNKNOWN).label(
                    "unknown"
                ),
                _count_state(
                    receipt_table, PublicationReceiptState.RESTART_REQUIRED
                ).label("restart_required"),
            )
            .where(*filters)
            .subquery()
        )
        page_rows = (
            select(receipt_table)
            .where(*filters)
            .order_by(RulePublicationReceiptRecord.instance_id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .subquery()
        )
        try:
            async with self._engine.connect() as connection:
                rows = (
                    await connection.execute(
                        select(counts, page_rows)
                        .select_from(counts.outerjoin(page_rows, true()))
                        .order_by(page_rows.c.instance_id.asc())
                    )
                ).mappings().all()
        except SQLAlchemyError:
            raise RulePublicationAuthorityUnavailable(
                "runtime publication receipts are unavailable"
            ) from None
        try:
            first = rows[0]
            items = tuple(
                publication_receipt_from_row(row)
                for row in rows
                if row["instance_id"] is not None
            )
            return RulePublicationReceiptPage(
                publication_id=publication_id,
                binding_id=binding_id,
                page=page,
                page_size=page_size,
                as_of=_now(),
                total=int(first["total"]),
                expected=None,
                inventory_source=None,
                applied=int(first["applied"] or 0),
                pending=int(first["pending"] or 0),
                failed=int(first["failed"] or 0),
                unknown=int(first["unknown"] or 0),
                restart_required=int(first["restart_required"] or 0),
                items=items,
            )
        except (KeyError, TypeError, ValueError, IndexError):
            raise RulePublicationAuthorityUnavailable(
                "persisted runtime publication receipts are invalid"
            ) from None


def _count_state(table, state: PublicationReceiptState):
    return func.coalesce(
        func.sum(case((table.c.state == state.value, 1), else_=0)), 0
    )


def _now() -> datetime:
    value = datetime.now(UTC)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


__all__ = ["SqlAlchemyRulePublicationReceiptStore"]
