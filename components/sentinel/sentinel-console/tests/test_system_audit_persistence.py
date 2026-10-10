"""SQLite adapter tests for deterministic, bounded audit reads."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.system_audit_ports import (
    SystemAuditAuthorityUnavailable,
)
from atlas_richie.sentinel_console.domain.system_audit import (
    AuditAction,
    AuditQuery,
    AuditResult,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuditEventRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    system_audit_reader,
)

_START = datetime(2026, 10, 8, 0, 0, tzinfo=UTC)
_END = datetime(2026, 10, 9, 0, 0, tzinfo=UTC)
_AS_OF = datetime(2026, 10, 9, 1, 0, tzinfo=UTC)


class SystemAuditPersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        self.reader = system_audit_reader.SqlAlchemySystemAuditReader(
            self.engine, clock=lambda: _AS_OF
        )
        async with self.engine.begin() as connection:
            for account_id in ("admin-1", "admin-2"):
                await connection.execute(
                    insert(AccountRecord).values(
                        account_id=account_id,
                        username=account_id,
                        username_key=account_id,
                        password_hash="$argon2id$synthetic-hash",
                        role_id="admin",
                        status="active",
                        built_in=False,
                        revision=1,
                        created_at=_START,
                        updated_at=_START,
                    )
                )
            await connection.execute(
                insert(AuditEventRecord),
                [
                    _event(
                        "event-a",
                        "admin-1",
                        "accounts.create",
                        "completed",
                        "target-1",
                        _START,
                    ),
                    _event(
                        "event-b",
                        "admin-1",
                        "accounts.role",
                        "rejected",
                        "target-2",
                        _START,
                    ),
                    _event(
                        "event-c",
                        "admin-2",
                        "auth.password.change",
                        "accepted",
                        "admin-2",
                        datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
                    ),
                    _event(
                        "event-end",
                        "admin-1",
                        "accounts.status",
                        "completed",
                        "target-3",
                        _END,
                    ),
                    _event(
                        "event-future",
                        "admin-1",
                        "accounts.status",
                        "completed",
                        "target-4",
                        datetime(2026, 10, 9, 2, 0, tzinfo=UTC),
                    ),
                ],
            )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_reads_stable_pages_with_half_open_range(self) -> None:
        first = await self.reader.read_system_audit(_query(page=1, page_size=2))
        second = await self.reader.read_system_audit(_query(page=2, page_size=2))

        self.assertEqual(first.total, 3)
        self.assertEqual([item.id for item in first.items], ["event-c", "event-b"])
        self.assertEqual([item.id for item in second.items], ["event-a"])
        self.assertEqual(first.items[0].result, AuditResult.UNKNOWN)
        self.assertEqual(first.items[0].action, AuditAction.PASSWORD_CHANGE)
        self.assertEqual(first.items[0].occurred_at.tzinfo, UTC)
        self.assertEqual(first.items[0].request_id, "request-event-c")
        self.assertEqual(first.as_of, _AS_OF)

    async def test_filters_actor_action_and_result_in_storage_query(self) -> None:
        page = await self.reader.read_system_audit(
            _query(
                actor_id="admin-1",
                action=AuditAction.ACCOUNT_CREATE,
                result=AuditResult.SUCCESS,
            )
        )

        self.assertEqual(page.total, 1)
        self.assertEqual([item.id for item in page.items], ["event-a"])

    async def test_unsupported_persisted_action_fails_closed(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AuditEventRecord).values(
                    **_event(
                        "event-unknown",
                        "admin-1",
                        "accounts.password-export",
                        "completed",
                        "target-5",
                        datetime(2026, 10, 8, 15, 0, tzinfo=UTC),
                    )
                )
            )

        with self.assertRaises(SystemAuditAuthorityUnavailable):
            await self.reader.read_system_audit(_query())

    async def test_projects_every_supported_writer_action_and_system_actor(self) -> None:
        events = (
            ("system-init", None, "system.bootstrap.initialize"),
            ("rule-validate", "admin-1", "rules.validate"),
            ("source-register", "admin-1", "configuration.source.register"),
            ("source-update", "admin-1", "configuration.source.update"),
            ("draft-save", "admin-1", "rules.save_draft"),
            ("draft-delete", "admin-1", "rules.delete_draft"),
            ("version-freeze", "admin-1", "rules.freeze_version"),
            ("rule-publish", "admin-1", "rules.publish"),
            ("plan-create", "admin-1", "rules.create_plan"),
            ("plan-cancel", "admin-1", "rules.cancel_plan"),
            ("plan-activate", None, "rules.activation_plan.activate"),
            ("plan-restore", None, "rules.activation_plan.restore"),
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AuditEventRecord),
                [
                    _event(
                        event_id,
                        actor_id,
                        action,
                        "completed",
                        "target-1",
                        datetime(2026, 10, 8, 13, 0, tzinfo=UTC),
                    )
                    for event_id, actor_id, action in events
                ],
            )

        page = await self.reader.read_system_audit(_query(page_size=100))

        records_by_id = {record.id: record for record in page.items}
        self.assertEqual(page.total, 15)
        self.assertIsNone(records_by_id["system-init"].actor_id)
        self.assertEqual(
            records_by_id["system-init"].action,
            AuditAction.SYSTEM_INITIALIZE,
        )
        self.assertEqual(
            records_by_id["rule-validate"].action,
            AuditAction.RULE_VALIDATE,
        )
        self.assertEqual(
            records_by_id["source-register"].action,
            AuditAction.SOURCE_REGISTER,
        )
        self.assertEqual(
            records_by_id["plan-cancel"].action,
            AuditAction.PLAN_CANCEL,
        )
        self.assertIsNone(records_by_id["plan-activate"].actor_id)
        self.assertEqual(
            records_by_id["plan-activate"].action,
            AuditAction.PLAN_ACTIVATE,
        )
        self.assertIsNone(records_by_id["plan-restore"].actor_id)
        self.assertEqual(
            records_by_id["plan-restore"].action,
            AuditAction.PLAN_RESTORE,
        )

    async def test_filters_system_plan_actions_without_fabricating_actor(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AuditEventRecord).values(
                    **_event(
                        "plan-activate-filtered",
                        None,
                        "rules.activation_plan.activate",
                        "completed",
                        "plan-1",
                        datetime(2026, 10, 8, 15, 0, tzinfo=UTC),
                    )
                )
            )

        page = await self.reader.read_system_audit(
            _query(action=AuditAction.PLAN_ACTIVATE)
        )

        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].id, "plan-activate-filtered")
        self.assertIsNone(page.items[0].actor_id)

    async def test_null_identity_fails_closed_instead_of_fabricating_ids(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AuditEventRecord).values(
                    **_event(
                        "event-null-actor",
                        None,
                        "accounts.create",
                        "completed",
                        "target-6",
                        datetime(2026, 10, 8, 15, 0, tzinfo=UTC),
                    )
                )
            )

        with self.assertRaises(SystemAuditAuthorityUnavailable):
            await self.reader.read_system_audit(_query())


def _event(
    event_id: str,
    actor_id: str | None,
    action: str,
    outcome: str,
    target_id: str | None,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "request_id": f"request-{event_id}",
        "actor_account_id": actor_id,
        "action": action,
        "outcome": outcome,
        "target_kind": "account",
        "target_id": target_id,
        "created_at": created_at,
    }


def _query(
    *,
    page: int = 1,
    page_size: int = 20,
    actor_id: str = "",
    action: AuditAction | None = None,
    result: AuditResult | None = None,
) -> AuditQuery:
    return AuditQuery(_START, _END, actor_id, action, result, page, page_size)
