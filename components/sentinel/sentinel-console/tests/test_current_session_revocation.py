"""Session revocation persistence tests against isolated in-memory SQLite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import unittest
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import create_async_engine
from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.domain.session import SessionRevocationResult
from atlas_richie.sentinel_console.infrastructure.persistence import (
    current_session_reader,
    current_session_revoker,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuthenticationSessionRecord,
)


class CurrentSessionRevocationPersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        self.revoker = current_session_revoker.SqlAlchemyCurrentSessionRevoker(
            self.engine
        )
        self.reader = current_session_reader.SqlAlchemyCurrentSessionReader(self.engine)
        self.now = datetime.now(UTC)
        self.opaque_cookie = "synthetic-session-token-for-console-revoke-0001"
        self.csrf_token = "synthetic-csrf-token-for-console-revoke-00001"
        self.session_digest = hashlib.sha256(
            self.opaque_cookie.encode("ascii")
        ).hexdigest()
        self.csrf_digest = hashlib.sha256(
            self.csrf_token.encode("ascii")
        ).hexdigest()
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="account-revoke-1",
                    username="Logout Test",
                    username_key="1" * 64,
                    password_hash="$argon2id$synthetic-test-hash",
                    role_id="admin",
                    status="active",
                    revision=1,
                    created_at=self.now,
                    updated_at=self.now,
                )
            )
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=self.session_digest,
                    account_id="account-revoke-1",
                    session_epoch="epoch-revoke-1",
                    csrf_hash=self.csrf_digest,
                    created_at=self.now,
                    expires_at=self.now + timedelta(hours=1),
                    revoked_at=None,
                )
            )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_matching_csrf_revokes_and_reader_sees_anonymous(self) -> None:
        result = await self.revoker.revoke_active_session(
            self.session_digest, self.csrf_digest, datetime.now(UTC)
        )

        self.assertIs(result, SessionRevocationResult.REVOKED)
        self.assertIsNone(await self.reader.read_active_session(self.session_digest))
        async with self.engine.connect() as connection:
            revoked_at = await connection.scalar(
                select(AuthenticationSessionRecord.revoked_at).where(
                    AuthenticationSessionRecord.session_hash == self.session_digest
                )
            )
        self.assertIsNotNone(revoked_at)

    async def test_asgi_logout_revokes_sqlite_session_and_me_reads_anonymous(self) -> None:
        class _Initialized:
            async def is_initialized(self) -> bool:
                return True

        class _SetupWindow:
            async def is_setup_window_open(self) -> bool:
                return False

        class _OperatorVerifier:
            async def is_current_operator(self, opaque_session: str | None) -> bool:
                return False

        class _AccountDirectory:
            async def list_accounts(self, query):
                raise AssertionError("logout must not query accounts")

            async def read_account(self, account_id: str):
                raise AssertionError("logout must not query accounts")

        app = build_app(
            bootstrap_initialization_reader=_Initialized(),
            setup_window_reader=_SetupWindow(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=self.reader,
            current_session_revoker=self.revoker,
            account_directory_reader=_AccountDirectory(),
            allowed_browser_origins=frozenset({"https://console.test"}),
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://console.test"
        ) as client:
            client.cookies.set("sentinel_session", self.opaque_cookie)
            client.cookies.set("__Host-sentinel_csrf", self.csrf_token)
            logged_out = await client.post(
                "/api/v1/auth/logout",
                headers={
                    "origin": "https://console.test",
                    "x-request-id": "sqlite-logout-1",
                    "x-sentinel-csrf": self.csrf_token,
                },
            )
            identity = await client.get(
                "/api/v1/auth/me", headers={"x-request-id": "sqlite-me-after-logout-1"}
            )

        self.assertEqual(logged_out.status_code, 204)
        self.assertEqual(logged_out.content, b"")
        self.assertIsNone(identity.json())

    async def test_wrong_csrf_expired_and_unknown_session_do_not_revoke(self) -> None:
        wrong_csrf = hashlib.sha256(
            b"wrong csrf token value long enough"
        ).hexdigest()
        self.assertIs(
            await self.revoker.revoke_active_session(
                self.session_digest, wrong_csrf, datetime.now(UTC)
            ),
            SessionRevocationResult.CSRF_FAILED,
        )
        self.assertIsNotNone(
            await self.reader.read_active_session(self.session_digest)
        )

        self.assertIs(
            await self.revoker.revoke_active_session(
                "0" * 64, self.csrf_digest, datetime.now(UTC)
            ),
            SessionRevocationResult.UNAUTHENTICATED,
        )

        async with self.engine.begin() as connection:
            await connection.execute(
                update(AuthenticationSessionRecord)
                .where(
                    AuthenticationSessionRecord.session_hash == self.session_digest
                )
                .values(expires_at=self.now - timedelta(seconds=1))
            )
        self.assertIs(
            await self.revoker.revoke_active_session(
                self.session_digest, self.csrf_digest, datetime.now(UTC)
            ),
            SessionRevocationResult.UNAUTHENTICATED,
        )

    async def test_database_failure_maps_to_stable_authority_error(self) -> None:
        missing_path = (
            f"/private/tmp/no-such-console-revoke-db-{uuid4().hex}/console.db"
        )
        engine = create_async_engine(f"sqlite+aiosqlite:///{missing_path}")
        try:
            revoker = current_session_revoker.SqlAlchemyCurrentSessionRevoker(engine)
            with self.assertRaises(SessionAuthorityUnavailable):
                await revoker.revoke_active_session(
                    self.session_digest, self.csrf_digest, datetime.now(UTC)
                )
        finally:
            await engine.dispose()
