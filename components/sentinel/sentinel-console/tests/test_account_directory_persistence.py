"""Safe account directory queries against isolated in-memory SQLite."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest

from sqlalchemy import event, insert, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.account_directory_ports import (
    AccountDirectoryAuthorityUnavailable,
    AccountDirectoryQuery,
)
from atlas_richie.sentinel_console.infrastructure.persistence.account_directory_reader import (
    SqlAlchemyAccountDirectoryReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import AccountRecord


class AccountDirectoryPersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        self.reader = SqlAlchemyAccountDirectoryReader(self.engine)
        now = datetime.now(UTC)
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord),
                [
                    {
                        "account_id": "account-1", "username": "Admin One",
                        "username_key": "1" * 64, "password_hash": "$argon2id$secret",
                        "role_id": "admin", "status": "active", "built_in": True,
                        "last_login_at": now, "revision": 1, "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "account_id": "account-2", "username": "View Two",
                        "username_key": "2" * 64, "password_hash": "$argon2id$secret",
                        "role_id": "view", "status": "disabled", "built_in": False,
                        "last_login_at": None, "revision": 2, "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "account_id": "account-3", "username": "Admin Three",
                        "username_key": "3" * 64, "password_hash": "$argon2id$secret",
                        "role_id": "admin", "status": "active", "built_in": False,
                        "last_login_at": None, "revision": 4, "created_at": now,
                        "updated_at": now,
                    },
                ],
            )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_pagination_status_and_search_are_applied(self) -> None:
        first = await self.reader.list_accounts(AccountDirectoryQuery(1, 1, "Admin", None))
        second = await self.reader.list_accounts(AccountDirectoryQuery(2, 1, "Admin", None))
        disabled = await self.reader.list_accounts(
            AccountDirectoryQuery(1, 100, "", "disabled")
        )
        out_of_range = await self.reader.list_accounts(
            AccountDirectoryQuery(3, 1, "Admin", None)
        )
        wildcard = await self.reader.list_accounts(
            AccountDirectoryQuery(1, 100, "%", None)
        )
        self.assertEqual((first.total, len(first.items)), (2, 1))
        self.assertEqual((second.total, len(second.items)), (2, 1))
        self.assertNotEqual(first.items[0].account_id, second.items[0].account_id)
        self.assertEqual([item.account_id for item in disabled.items], ["account-2"])
        self.assertEqual((out_of_range.total, out_of_range.items), (2, ()))
        self.assertEqual(wildcard.items, ())

    async def test_pagination_total_rows_and_admin_facts_share_one_statement(self) -> None:
        statements: list[str] = []

        def record_statement(
            _connection, _cursor, statement, _parameters, _context, _many
        ):
            if statement.lstrip().lower().startswith(("select", "with")):
                statements.append(statement)

        event.listen(self.engine.sync_engine, "before_cursor_execute", record_statement)
        try:
            page = await self.reader.list_accounts(
                AccountDirectoryQuery(1, 1, "Admin", None)
            )
        finally:
            event.remove(
                self.engine.sync_engine, "before_cursor_execute", record_statement
            )

        self.assertEqual(len(statements), 1)
        self.assertEqual(page.total, 2)
        self.assertEqual(len(page.items), 1)

    async def test_last_active_admin_is_derived_and_detail_is_safe(self) -> None:
        admin_page = await self.reader.list_accounts(AccountDirectoryQuery(1, 100, "", None))
        admin_facts = [item for item in admin_page.items if item.role_id == "admin"]
        self.assertTrue(all(not item.last_active_admin for item in admin_facts))
        item = await self.reader.read_account("account-1")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertFalse(item.last_active_admin)
        self.assertFalse(hasattr(item, "password_hash"))

    async def test_builtin_account_must_remain_an_active_admin(self) -> None:
        with self.assertRaises(IntegrityError):
            async with self.engine.begin() as connection:
                await connection.execute(
                    update(AccountRecord)
                    .where(AccountRecord.account_id == "account-2")
                    .values(built_in=True)
                )

    async def test_only_remaining_active_admin_is_marked(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                update(AccountRecord)
                .where(AccountRecord.account_id == "account-3")
                .values(status="disabled")
            )
        page = await self.reader.list_accounts(AccountDirectoryQuery(1, 100, "", None))
        admin_items = [item for item in page.items if item.role_id == "admin"]
        self.assertEqual(
            [item.account_id for item in admin_items if item.last_active_admin],
            ["account-1"],
        )

    async def test_database_failure_maps_to_stable_authority_error(self) -> None:
        unavailable_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            reader = SqlAlchemyAccountDirectoryReader(unavailable_engine)
            with self.assertRaises(AccountDirectoryAuthorityUnavailable):
                await reader.list_accounts(AccountDirectoryQuery(1, 20, "", None))
        finally:
            await unavailable_engine.dispose()
