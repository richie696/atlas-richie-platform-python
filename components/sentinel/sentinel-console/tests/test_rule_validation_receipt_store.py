"""Durable validation receipt and audit persistence integration tests."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.rule_validation_ports import (
    RuleValidationAuthorityUnavailable,
)
from atlas_richie.sentinel_console.domain.rule_validation import (
    RuleCandidateValidationReceipt,
    RuleValidationIssue,
    RuleValidationIssueCode,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuditEventRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    rule_validation_receipt_store,
)


class RuleValidationReceiptStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        self.store = rule_validation_receipt_store.SqlAlchemyRuleValidationReceiptStore(
            self.engine
        )
        now = datetime(2026, 10, 9, 1, 0, tzinfo=UTC)
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="account-1",
                    username="Admin",
                    username_key="a" * 64,
                    password_hash="$argon2id$redacted-test-hash",
                    role_id="admin",
                    status="active",
                    built_in=True,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
            )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_receipt_and_audit_are_durable_and_safe(self) -> None:
        issue = RuleValidationIssue(
            RuleValidationIssueCode.UNSUPPORTED_CAPABILITY,
            0,
            "rules[0].clusterConfig",
        )
        receipt = RuleCandidateValidationReceipt(
            "binding-1",
            "sentinel-rule-profile-v1",
            "sha256:baseline",
            "sha256:candidate",
            "validation-1",
            False,
            (issue,),
        )
        created_at = datetime(2026, 10, 9, 1, 0, 1, 123000, tzinfo=UTC)
        await self.store.record_validation(
            receipt,
            actor_id="account-1",
            request_id="validation-request-1",
            created_at=created_at,
        )

        self.assertEqual(await self.store.read_validation("validation-1"), receipt)
        self.assertIsNone(await self.store.read_validation("unknown-validation"))
        async with self.engine.connect() as connection:
            audit = (
                await connection.execute(
                    select(AuditEventRecord.__table__).where(
                        AuditEventRecord.action == "rules.validate"
                    )
                )
            ).mappings().one()
        self.assertEqual(audit["actor_account_id"], "account-1")
        self.assertEqual(audit["request_id"], "validation-request-1")
        self.assertEqual(audit["target_id"], "binding-1")

    async def test_duplicate_id_fails_without_replacing_receipt(self) -> None:
        receipt = RuleCandidateValidationReceipt(
            "binding-1",
            "sentinel-rule-profile-v1",
            "sha256:baseline",
            "sha256:candidate",
            "validation-1",
            True,
            (),
        )
        metadata = {
            "actor_id": "account-1",
            "request_id": "validation-request-1",
            "created_at": datetime(2026, 10, 9, 1, 0, tzinfo=UTC),
        }
        await self.store.record_validation(receipt, **metadata)
        with self.assertRaises(RuleValidationAuthorityUnavailable):
            await self.store.record_validation(receipt, **metadata)
        self.assertEqual(await self.store.read_validation("validation-1"), receipt)
        async with self.engine.connect() as connection:
            count = await connection.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(
                    AuditEventRecord.action == "rules.validate"
                )
            )
        self.assertEqual(count, 1)

    async def test_database_failure_is_mapped_to_stable_unavailable(self) -> None:
        unavailable_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            unavailable_store = (
                rule_validation_receipt_store.SqlAlchemyRuleValidationReceiptStore(
                    unavailable_engine
                )
            )
            with self.assertRaises(RuleValidationAuthorityUnavailable):
                await unavailable_store.read_validation("validation-1")
        finally:
            await unavailable_engine.dispose()


if __name__ == "__main__":
    unittest.main()
