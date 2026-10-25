"""SQLite-local schema tests; these are not PostgreSQL/MySQL acceptance."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import unittest

from alembic.script import ScriptDirectory
from sqlalchemy import insert, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.errors import BootstrapAuthorityUnavailable
from atlas_richie.sentinel_console.domain.account_username import AccountUsername
from atlas_richie.sentinel_console.infrastructure.persistence.bootstrap_initialization_reader import (
    SqlAlchemyBootstrapInitializationReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence import migrations
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AccountOperationRecord,
    AuditEventRecord,
    AuthenticationSessionRecord,
    ConsoleGuardRecord,
    InitializationOperationRecord,
)


class PersistenceFoundationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_migration_creates_identity_and_audit_tables_and_singleton_guard(self) -> None:
        async with self.engine.connect() as connection:
            names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())

        self.assertTrue(
            {
                "alembic_version",
                "console_guard",
                "console_account",
                "console_session",
                "console_login_attempt",
                "console_initialization_operation",
                "console_account_operation",
                "console_audit_event",
            }.issubset(names)
        )
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(ConsoleGuardRecord.initialized, ConsoleGuardRecord.revision)
                )
            ).one()
        self.assertEqual(tuple(row), (False, 0))

    async def test_migration_is_idempotent_at_head(self) -> None:
        async with self.engine.connect() as connection:
            revision_before = (
                await connection.exec_driver_sql("SELECT version_num FROM alembic_version")
            ).scalar_one()
        await upgrade_database(self.engine)
        async with self.engine.connect() as connection:
            revision_after = (
                await connection.exec_driver_sql("SELECT version_num FROM alembic_version")
            ).scalar_one()

        migration_head = ScriptDirectory(
            str(Path(migrations.__file__).parent)
        ).get_current_head()
        self.assertEqual(revision_before, migration_head)
        self.assertEqual(revision_after, revision_before)

    async def test_database_constraints_reject_duplicate_login_key_and_unknown_role(self) -> None:
        now = datetime.now(UTC)
        first_username = AccountUsername("Admin")
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="a-0001",
                    username=first_username.value,
                    username_key=first_username.lookup_key,
                    password_hash="$argon2id$test-hash",
                    role_id="admin",
                    status="active",
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
            )

        with self.assertRaises(IntegrityError):
            compatibility_variant = AccountUsername("Ａdmin")
            self.assertEqual(compatibility_variant.lookup_key, first_username.lookup_key)
            async with self.engine.begin() as connection:
                await connection.execute(
                    insert(AccountRecord).values(
                        account_id="a-0002",
                        username=compatibility_variant.value,
                        username_key=compatibility_variant.lookup_key,
                        password_hash="$argon2id$test-hash",
                        role_id="view",
                        status="active",
                        revision=1,
                        created_at=now,
                        updated_at=now,
                    )
                )

        with self.assertRaises(IntegrityError):
            async with self.engine.begin() as connection:
                await connection.execute(
                    insert(AccountRecord).values(
                    account_id="a-0003",
                    username="operator",
                    username_key=AccountUsername("operator").lookup_key,
                        password_hash="$argon2id$test-hash",
                        role_id="owner",
                        status="active",
                        revision=1,
                        created_at=now,
                        updated_at=now,
                    )
                )

    async def test_persisted_models_exclude_plaintext_credentials_and_request_bodies(self) -> None:
        account_fields = set(AccountRecord.__table__.columns.keys())
        session_fields = set(AuthenticationSessionRecord.__table__.columns.keys())
        operation_fields = set(InitializationOperationRecord.__table__.columns.keys())
        account_operation_fields = set(AccountOperationRecord.__table__.columns.keys())
        audit_fields = set(AuditEventRecord.__table__.columns.keys())

        self.assertIn("password_hash", account_fields)
        self.assertIn("built_in", account_fields)
        self.assertIn("last_login_at", account_fields)
        self.assertEqual(AccountRecord.__table__.c.username_key.type.length, 64)
        self.assertNotIn("password", account_fields)
        self.assertIn(
            "ck_console_account_builtin_admin_active",
            {constraint.name for constraint in AccountRecord.__table__.constraints},
        )
        self.assertIn("session_hash", session_fields)
        self.assertNotIn("session_token", session_fields)
        self.assertIn("input_digest", operation_fields)
        self.assertNotIn("input_body", operation_fields)
        self.assertIn("fingerprint_key_id", account_operation_fields)
        self.assertIn("fingerprint_digest", account_operation_fields)
        self.assertNotIn("password", account_operation_fields)
        self.assertNotIn("input_body", account_operation_fields)
        self.assertNotIn("traceback", audit_fields)
        self.assertNotIn("request_body", audit_fields)

    async def test_initialization_reader_tracks_guard_and_missing_guard_fails_closed(self) -> None:
        reader = SqlAlchemyBootstrapInitializationReader(self.engine)
        self.assertFalse(await reader.is_initialized())

        async with self.engine.begin() as connection:
            await connection.execute(
                ConsoleGuardRecord.__table__.update()
                .where(ConsoleGuardRecord.singleton_id == 1)
                .values(initialized=True)
            )
        self.assertTrue(await reader.is_initialized())

        async with self.engine.begin() as connection:
            await connection.execute(ConsoleGuardRecord.__table__.delete())
        with self.assertRaises(BootstrapAuthorityUnavailable):
            await reader.is_initialized()
