"""SQLAlchemy session lookup tests against isolated in-memory SQLite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import unittest
from uuid import uuid4

from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.infrastructure.persistence import (
    current_session_reader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuthenticationSessionRecord,
)


class CurrentSessionPersistenceIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        self.reader = current_session_reader.SqlAlchemyCurrentSessionReader(self.engine)
        self.now = datetime.now(UTC)
        self.opaque_cookie = "synthetic-session-token-for-console-read-0001"
        self.session_digest = hashlib.sha256(
            self.opaque_cookie.encode("ascii")
        ).hexdigest()
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="account-9",
                    username="View Operator",
                    username_key="9" * 64,
                    password_hash="$argon2id$synthetic-test-hash",
                    role_id="view",
                    status="active",
                    revision=1,
                    created_at=self.now,
                    updated_at=self.now,
                )
            )
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=self.session_digest,
                    account_id="account-9",
                    session_epoch="epoch-9",
                    csrf_hash="c" * 64,
                    created_at=self.now,
                    expires_at=self.now + timedelta(hours=1),
                    revoked_at=None,
                )
            )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_current_session_reads_only_safe_account_projection(self) -> None:
        session = await self.reader.read_active_session(self.session_digest)

        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.account_id, "account-9")
        self.assertEqual(session.username, "View Operator")
        self.assertEqual(session.role_id, "view")
        self.assertEqual(session.session_epoch, "epoch-9")
        self.assertFalse(hasattr(session, "password_hash"))
        self.assertFalse(hasattr(session, "csrf_hash"))

    async def test_next_session_read_observes_a_committed_role_change(self) -> None:
        before = await self.reader.read_active_session(self.session_digest)
        self.assertIsNotNone(before)
        assert before is not None
        self.assertEqual(before.role_id, "view")

        async with self.engine.begin() as connection:
            await connection.execute(
                update(AccountRecord)
                .where(AccountRecord.account_id == "account-9")
                .values(role_id="admin")
            )

        after = await self.reader.read_active_session(self.session_digest)
        self.assertIsNotNone(after)
        assert after is not None
        self.assertEqual(after.role_id, "admin")
        self.assertEqual(after.session_epoch, before.session_epoch)

    async def test_expired_revoked_and_disabled_sessions_are_not_active(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                update(AuthenticationSessionRecord)
                .where(
                    AuthenticationSessionRecord.session_hash == self.session_digest
                )
                .values(expires_at=self.now - timedelta(seconds=1))
            )
        self.assertIsNone(await self.reader.read_active_session(self.session_digest))

        async with self.engine.begin() as connection:
            await connection.execute(
                update(AuthenticationSessionRecord)
                .where(
                    AuthenticationSessionRecord.session_hash == self.session_digest
                )
                .values(
                    expires_at=self.now + timedelta(hours=1), revoked_at=self.now
                )
            )
        self.assertIsNone(await self.reader.read_active_session(self.session_digest))

        async with self.engine.begin() as connection:
            await connection.execute(
                update(AuthenticationSessionRecord)
                .where(
                    AuthenticationSessionRecord.session_hash == self.session_digest
                )
                .values(revoked_at=None)
            )
            await connection.execute(
                update(AccountRecord)
                .where(AccountRecord.account_id == "account-9")
                .values(status="disabled")
            )
        self.assertIsNone(await self.reader.read_active_session(self.session_digest))

    async def test_database_failure_maps_to_stable_authority_error(self) -> None:
        missing_path = f"/private/tmp/no-such-console-db-{uuid4().hex}/console.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{missing_path}")
        try:
            reader = current_session_reader.SqlAlchemyCurrentSessionReader(engine)
            with self.assertRaises(SessionAuthorityUnavailable):
                await reader.read_active_session(self.session_digest)
        finally:
            await engine.dispose()
