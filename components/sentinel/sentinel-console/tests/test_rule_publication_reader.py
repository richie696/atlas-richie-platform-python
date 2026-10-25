"""SQL projection tests for binding-scoped publication facts."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from atlas_richie.sentinel_console.application.rule_publication_ports import (
    RulePublicationConflict,
    RulePublicationNotFound,
)
from atlas_richie.sentinel_console.domain.rule_publications import (
    PublicationPhase,
    PublicationPhaseName,
    PublicationReason,
    PublicationReceiptState,
    PublicationStage,
    RulePublication,
    RulePublicationReceipt,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    RulePublicationRecord,
    RuleSetVersionRecord,
    RuleValidationReceiptRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_reader import (
    SqlAlchemyRulePublicationReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_receipt_store import (
    SqlAlchemyRulePublicationReceiptStore,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_store import (
    SqlAlchemyRulePublicationStore,
)
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import create_async_engine

_NOW = datetime(2026, 10, 9, 8, 0, 0, 123000, tzinfo=UTC)


class SqlAlchemyRulePublicationReaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        self.reader = SqlAlchemyRulePublicationReader(self.engine)
        self.store = SqlAlchemyRulePublicationStore(self.engine)
        self.receipt_store = SqlAlchemyRulePublicationReceiptStore(self.engine)
        await self._seed_version("version-1", "binding-a", _NOW)
        await self._seed_publication(
            publication_id="publication-a",
            binding_id="binding-a",
            version_id="version-1",
            created_at=_NOW,
            validation_state="succeeded",
            validation_observed_at=_NOW,
            validation_reason=None,
            write_state="unknown",
            write_observed_at=_NOW,
            write_reason="unknown",
            read_back_state="awaiting",
            read_back_observed_at=None,
            read_back_reason=None,
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _seed_version(self, version_id: str, binding_id: str, now) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="admin-1",
                    username="admin",
                    username_key="synthetic-username-key",
                    password_hash="$argon2id$synthetic-hash",
                    role_id="admin",
                    status="active",
                    built_in=True,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            await connection.execute(
                insert(RuleValidationReceiptRecord).values(
                    validation_id=f"validation-{version_id}",
                    binding_id=binding_id,
                    profile="sentinel-profile-v1",
                    base_checksum="sha256:base",
                    candidate_checksum="sha256:candidate",
                    is_publishable=True,
                    issues=[],
                    actor_account_id="admin-1",
                    request_id=f"request-{version_id}",
                    created_at=now,
                )
            )
            await connection.execute(
                insert(RuleSetVersionRecord).values(
                    version_id=version_id,
                    binding_id=binding_id,
                    kind="flow",
                    profile="sentinel-profile-v1",
                    base_version_id=None,
                    checksum="sha256:candidate",
                    name="test version",
                    note="",
                    validation_id=f"validation-{version_id}",
                    records=[],
                    created_at=now,
                    created_by_account_id="admin-1",
                )
            )

    async def _seed_publication(self, **values) -> None:
        async with self.engine.begin() as connection:
            current = await connection.execute(
                select(func.max(RulePublicationRecord.publication_sequence)).where(
                    RulePublicationRecord.binding_id == values["binding_id"]
                )
            )
            next_sequence = (current.scalar_one_or_none() or 0) + 1
            await connection.execute(
                insert(RulePublicationRecord).values(
                    target_version_id=values["version_id"],
                    target_checksum="sha256:candidate",
                    publication_sequence=next_sequence,
                    base_version_id=None,
                    **{
                        key: value
                        for key, value in values.items()
                        if key != "version_id"
                    },
                )
            )

    async def test_history_reconstructs_phase_facts_without_collapsing_unknown(self):
        result = await self.reader.read_rule_publications("binding-a")

        self.assertEqual(result.binding_id, "binding-a")
        self.assertEqual(len(result.items), 1)
        publication = result.items[0]
        self.assertEqual(publication.id, "publication-a")
        self.assertEqual(publication.validation.state, PublicationStage.SUCCEEDED)
        self.assertEqual(
            publication.configuration_write.state, PublicationStage.UNKNOWN
        )
        self.assertEqual(
            publication.configuration_write.reason, PublicationReason.UNKNOWN
        )
        self.assertEqual(publication.read_back.state, PublicationStage.AWAITING)

    async def test_detail_is_scoped_to_binding_and_missing_is_not_found(self):
        result = await self.reader.read_rule_publication("binding-a", "publication-a")
        self.assertEqual(result.binding_id, "binding-a")

        with self.assertRaises(RulePublicationNotFound):
            await self.reader.read_rule_publication("binding-b", "publication-a")

    async def test_empty_binding_has_authoritative_empty_history(self):
        result = await self.reader.read_rule_publications("binding-empty")
        self.assertEqual(result.items, ())

    async def test_create_checks_immutable_version_then_persists_new_attempt(self):
        publication = _new_publication("publication-new")

        await self.store.create_rule_publication(publication)
        loaded = await self.reader.read_rule_publication("binding-a", publication.id)
        self.assertEqual(loaded, replace(publication, publication_sequence=2))
        with self.assertRaises(RulePublicationConflict):
            await self.store.create_rule_publication(publication)

    async def test_payload_checksum_is_immutable_idempotent_and_internal(self):
        digest = "a" * 64
        await self.store.ensure_rule_publication_payload_checksum(
            "binding-a", "publication-a", digest
        )
        await self.store.ensure_rule_publication_payload_checksum(
            "binding-a", "publication-a", digest
        )
        async with self.engine.connect() as connection:
            persisted = await connection.scalar(
                select(RulePublicationRecord.target_payload_checksum).where(
                    RulePublicationRecord.binding_id == "binding-a",
                    RulePublicationRecord.publication_id == "publication-a",
                )
            )
        self.assertEqual(persisted, digest)
        with self.assertRaises(RulePublicationConflict):
            await self.store.ensure_rule_publication_payload_checksum(
                "binding-a", "publication-a", "b" * 64
            )
        with self.assertRaises(RulePublicationNotFound):
            await self.store.ensure_rule_publication_payload_checksum(
                "binding-a", "missing-publication", digest
            )

    async def test_phase_transition_is_monotonic_binding_scoped_and_durable(self):
        publication = _new_publication("publication-transition")
        await self.store.create_rule_publication(publication)

        running = await self.store.advance_rule_publication_phase(
            "binding-a",
            publication.id,
            PublicationPhaseName.VALIDATION,
            expected_state=PublicationStage.AWAITING,
            next_phase=PublicationPhase(PublicationStage.RUNNING, _NOW, None),
        )
        self.assertEqual(running.validation.state, PublicationStage.RUNNING)

        validated = await self.store.advance_rule_publication_phase(
            "binding-a",
            publication.id,
            PublicationPhaseName.VALIDATION,
            expected_state=PublicationStage.RUNNING,
            next_phase=PublicationPhase(
                PublicationStage.SUCCEEDED, _NOW + timedelta(milliseconds=1), None
            ),
        )
        self.assertEqual(validated.validation.state, PublicationStage.SUCCEEDED)

        writing = await self.store.advance_rule_publication_phase(
            "binding-a",
            publication.id,
            PublicationPhaseName.CONFIGURATION_WRITE,
            expected_state=PublicationStage.AWAITING,
            next_phase=PublicationPhase(PublicationStage.RUNNING, _NOW, None),
        )
        self.assertEqual(writing.configuration_write.state, PublicationStage.RUNNING)
        with self.assertRaises(RulePublicationConflict):
            await self.store.advance_rule_publication_phase(
                "binding-a",
                publication.id,
                PublicationPhaseName.CONFIGURATION_WRITE,
                expected_state=PublicationStage.AWAITING,
                next_phase=PublicationPhase(PublicationStage.RUNNING, _NOW, None),
            )
        with self.assertRaises(RulePublicationNotFound):
            await self.store.advance_rule_publication_phase(
                "binding-other",
                publication.id,
                PublicationPhaseName.VALIDATION,
                expected_state=PublicationStage.SUCCEEDED,
                next_phase=PublicationPhase(PublicationStage.RUNNING, _NOW, None),
            )

        persisted = await self.reader.read_rule_publication("binding-a", publication.id)
        self.assertEqual(persisted, writing)

    async def test_create_rejects_cross_binding_or_wrong_checksum_versions(self):
        with self.assertRaises(RulePublicationConflict):
            await self.store.create_rule_publication(
                _new_publication("publication-wrong-checksum", checksum="sha256:wrong")
            )
        with self.assertRaises(RulePublicationConflict):
            await self.store.create_rule_publication(
                _new_publication("publication-cross-binding", binding_id="binding-b")
            )

    async def test_receipt_store_records_latest_and_reads_full_page_counters(self):
        await self._record_receipt(
            _receipt("instance-c", PublicationReceiptState.FAILED)
        )
        await self._record_receipt(
            _receipt("instance-a", PublicationReceiptState.APPLIED)
        )
        await self._record_receipt(
            _receipt("instance-b", PublicationReceiptState.PENDING)
        )

        first = await self.receipt_store.read_rule_publication_receipts(
            "binding-a", "publication-a", page=1, page_size=2
        )
        self.assertEqual(first.total, 3)
        self.assertEqual(first.expected, None)
        self.assertEqual(first.inventory_source, None)
        self.assertEqual((first.applied, first.pending, first.failed), (1, 1, 1))
        self.assertEqual(
            [item.instance_id for item in first.items], ["instance-a", "instance-b"]
        )
        first.validate_for(
            await self.reader.read_rule_publication("binding-a", "publication-a")
        )

        second = await self.receipt_store.read_rule_publication_receipts(
            "binding-a", "publication-a", page=2, page_size=2
        )
        self.assertEqual([item.instance_id for item in second.items], ["instance-c"])
        empty = await self.receipt_store.read_rule_publication_receipts(
            "binding-a", "publication-a", page=4, page_size=1
        )
        self.assertEqual(empty.total, 3)
        self.assertEqual(empty.items, ())

    async def test_receipt_store_is_idempotent_and_rejects_stale_or_wrong_facts(self):
        initial = _receipt("instance-a", PublicationReceiptState.PENDING)
        await self._record_receipt(initial)
        await self._record_receipt(initial)

        with self.assertRaises(RulePublicationConflict):
            await self._record_receipt(
                _receipt(
                    "instance-a",
                    PublicationReceiptState.FAILED,
                    last_report_at=_NOW,
                )
            )
        with self.assertRaises(RulePublicationConflict):
            await self._record_receipt(
                _receipt(
                    "instance-a",
                    PublicationReceiptState.FAILED,
                    target_version_id="another-version",
                    last_report_at=_NOW + timedelta(milliseconds=1),
                )
            )

        newer = _receipt(
            "instance-a",
            PublicationReceiptState.FAILED,
            last_report_at=_NOW + timedelta(milliseconds=2),
        )
        await self._record_receipt(newer)
        persisted = await self.receipt_store.read_rule_publication_receipts(
            "binding-a", "publication-a", page=1, page_size=10
        )
        self.assertEqual(persisted.items, (newer,))

    async def test_receipt_store_rejects_publication_outside_exact_binding(self):
        receipt = _receipt("instance-a", PublicationReceiptState.PENDING)

        with self.assertRaises(RulePublicationNotFound):
            await self.receipt_store.record_rule_publication_receipt(
                "binding-other", "publication-a", receipt
            )
        with self.assertRaises(RulePublicationNotFound):
            await self.receipt_store.record_rule_publication_receipt(
                "binding-a", "publication-missing", receipt
            )

    async def test_receipts_remain_scoped_to_publication_when_version_bytes_match(self):
        await self._seed_publication(
            publication_id="publication-b",
            binding_id="binding-a",
            version_id="version-1",
            created_at=_NOW + timedelta(milliseconds=1),
            validation_state="succeeded",
            validation_observed_at=_NOW,
            validation_reason=None,
            write_state="unknown",
            write_observed_at=_NOW,
            write_reason="unknown",
            read_back_state="awaiting",
            read_back_observed_at=None,
            read_back_reason=None,
        )
        first = _receipt("instance-a", PublicationReceiptState.PENDING)
        second = _receipt(
            "instance-a",
            PublicationReceiptState.FAILED,
            last_report_at=_NOW + timedelta(milliseconds=2),
        )

        await self.receipt_store.record_rule_publication_receipt(
            "binding-a", "publication-a", first
        )
        await self.receipt_store.record_rule_publication_receipt(
            "binding-a", "publication-b", second
        )

        first_page = await self.receipt_store.read_rule_publication_receipts(
            "binding-a", "publication-a", page=1, page_size=10
        )
        second_page = await self.receipt_store.read_rule_publication_receipts(
            "binding-a", "publication-b", page=1, page_size=10
        )
        self.assertEqual(first_page.items, (first,))
        self.assertEqual(second_page.items, (second,))

    async def _record_receipt(self, receipt: RulePublicationReceipt) -> None:
        await self.receipt_store.record_rule_publication_receipt(
            "binding-a", "publication-a", receipt
        )


def _new_publication(
    publication_id: str,
    *,
    binding_id: str = "binding-a",
    checksum: str = "sha256:candidate",
) -> RulePublication:
    return RulePublication(
        id=publication_id,
        binding_id=binding_id,
        target_version_id="version-1",
        target_checksum=checksum,
        base_version_id=None,
        created_at=_NOW,
        validation=PublicationPhase(PublicationStage.AWAITING, None, None),
        configuration_write=PublicationPhase(PublicationStage.AWAITING, None, None),
        read_back=PublicationPhase(PublicationStage.AWAITING, None, None),
    )


def _receipt(
    instance_id: str,
    state: PublicationReceiptState,
    *,
    target_version_id: str = "version-1",
    last_report_at: datetime | None = None,
) -> RulePublicationReceipt:
    reported_at = last_report_at or _NOW + timedelta(milliseconds=1)
    if state is PublicationReceiptState.APPLIED:
        return RulePublicationReceipt(
            instance_id=instance_id,
            process_epoch="process-1",
            loaded_process_epoch="process-1",
            target_version_id=target_version_id,
            loaded_version_id=target_version_id,
            loaded_checksum="sha256:candidate",
            applied_at=reported_at,
            last_report_at=reported_at,
            state=state,
        )
    return RulePublicationReceipt(
        instance_id=instance_id,
        process_epoch="process-1",
        loaded_process_epoch=None,
        target_version_id=target_version_id,
        loaded_version_id=None,
        loaded_checksum=None,
        applied_at=None,
        last_report_at=reported_at,
        state=state,
    )


if __name__ == "__main__":
    unittest.main()
