"""SQL-backed login throttling tests using disposable local SQLite only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import asyncio
import hashlib
import hmac
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, insert, select
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.applications import Starlette

from atlas_richie.sentinel_console.api.login import login_route
from atlas_richie.sentinel_console.application.login_ports import (
    LoginAuthorityUnavailable,
)
from atlas_richie.sentinel_console.application.login import Login
from atlas_richie.sentinel_console.domain.account_username import AccountUsername
from atlas_richie.sentinel_console.infrastructure.persistence import (
    login_attempt_limiter,
    login_credential_reader,
    login_session_writer,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuthenticationSessionRecord,
    LoginAttemptRecord,
)
from atlas_richie.sentinel_console.infrastructure.security.password_hash import (
    PasswordHashService,
)

_CLIENT_DIGEST = "a" * 64
_OTHER_CLIENT_DIGEST = "b" * 64
_ORIGIN = "https://console.test"
_CLIENT_IDENTITY_KEY = b"synthetic-limiter-hmac-key-material-32"
_CSRF = "csrf-token-for-sql-limiter-asgi-test-000001"
_POLICY = login_attempt_limiter.LoginAttemptLimitPolicy(
    failure_threshold=3,
    window=timedelta(minutes=5),
    block_duration=timedelta(minutes=2),
)


class LoginAttemptLimiterTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "attempts.sqlite"
        self.database_url = f"sqlite+aiosqlite:///{database_path}"
        self.engine = create_async_engine(self.database_url)
        await upgrade_database(self.engine)
        self.now = datetime(2026, 10, 9, 4, 0, tzinfo=UTC)
        self.limiter = login_attempt_limiter.SqlAlchemyLoginAttemptLimiter(
            self.engine, policy=_POLICY, clock=lambda: self.now
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temporary_directory.cleanup()

    async def test_failure_threshold_and_cooldown_persist_across_instances(
        self,
    ) -> None:
        self.assertIsNone(await self.limiter.retry_after_ms(_CLIENT_DIGEST))
        await self.limiter.record_failure(_CLIENT_DIGEST)
        await self.limiter.record_failure(_CLIENT_DIGEST)
        self.assertIsNone(await self.limiter.retry_after_ms(_CLIENT_DIGEST))

        await self.limiter.record_failure(_CLIENT_DIGEST)
        second_engine = create_async_engine(self.database_url)
        try:
            second_worker = login_attempt_limiter.SqlAlchemyLoginAttemptLimiter(
                second_engine, policy=_POLICY, clock=lambda: self.now
            )
            self.assertEqual(
                await second_worker.retry_after_ms(_CLIENT_DIGEST), 120_000
            )
            self.assertIsNone(await second_worker.retry_after_ms(_OTHER_CLIENT_DIGEST))

            self.now += timedelta(seconds=30)
            self.assertEqual(await second_worker.retry_after_ms(_CLIENT_DIGEST), 90_000)
            self.now += timedelta(seconds=90)
            self.assertIsNone(await second_worker.retry_after_ms(_CLIENT_DIGEST))
            await second_worker.record_failure(_CLIENT_DIGEST)
            self.assertIsNone(await self.limiter.retry_after_ms(_CLIENT_DIGEST))
        finally:
            await second_engine.dispose()

    async def test_success_clears_only_its_digest_and_stores_no_raw_identity(
        self,
    ) -> None:
        await self.limiter.record_failure(_CLIENT_DIGEST)
        await self.limiter.record_failure(_OTHER_CLIENT_DIGEST)
        await self.limiter.record_success(_CLIENT_DIGEST)

        async with self.engine.connect() as connection:
            rows = (
                await connection.execute(
                    select(LoginAttemptRecord.client_identity_digest)
                )
            ).scalars().all()
        self.assertEqual(rows, [_OTHER_CLIENT_DIGEST])

    async def test_concurrent_first_failures_are_serialized_by_sqlite_unique_key(
        self,
    ) -> None:
        second_engine = create_async_engine(self.database_url)
        second_limiter = login_attempt_limiter.SqlAlchemyLoginAttemptLimiter(
            second_engine, policy=_POLICY, clock=lambda: self.now
        )
        try:
            await asyncio.gather(
                *(
                    (self.limiter if index % 2 == 0 else second_limiter).record_failure(
                        _CLIENT_DIGEST
                    )
                    for index in range(8)
                )
            )
        finally:
            await second_engine.dispose()

        async with self.engine.connect() as connection:
            record = (
                await connection.execute(
                    select(
                        LoginAttemptRecord.failure_count,
                        LoginAttemptRecord.blocked_until_ms,
                    ).where(
                        LoginAttemptRecord.client_identity_digest == _CLIENT_DIGEST
                    )
                )
            ).one()
        self.assertEqual(record.failure_count, _POLICY.failure_threshold)
        self.assertIsNotNone(record.blocked_until_ms)

    async def test_expired_window_starts_a_new_failure_window(self) -> None:
        for _ in range(_POLICY.failure_threshold):
            await self.limiter.record_failure(_CLIENT_DIGEST)
        self.now += timedelta(minutes=7)
        self.assertIsNone(await self.limiter.retry_after_ms(_CLIENT_DIGEST))
        await self.limiter.record_failure(_CLIENT_DIGEST)
        self.assertIsNone(await self.limiter.retry_after_ms(_CLIENT_DIGEST))

    async def test_asgi_login_uses_database_limiter_before_credentials(self) -> None:
        password_hasher = PasswordHashService()
        username = AccountUsername("limiter-admin")
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="limiter-account-1",
                    username=username.value,
                    username_key=username.lookup_key,
                    password_hash=password_hasher.hash_password(
                        "synthetic-valid-password-012345"
                    ),
                    role_id="admin",
                    status="active",
                    built_in=False,
                    revision=1,
                    created_at=self.now,
                    updated_at=self.now,
                )
            )
        login = Login(
            credential_reader=login_credential_reader.SqlAlchemyLoginCredentialReader(
                self.engine
            ),
            session_writer=login_session_writer.SqlAlchemyLoginSessionWriter(
                self.engine
            ),
            attempt_limiter=login_attempt_limiter.SqlAlchemyLoginAttemptLimiter(
                self.engine,
                policy=login_attempt_limiter.LoginAttemptLimitPolicy(
                    failure_threshold=1,
                    window=timedelta(minutes=1),
                    block_duration=timedelta(minutes=1),
                ),
                clock=lambda: self.now,
            ),
            password_hasher=password_hasher,
            session_ttl=timedelta(hours=8),
            clock=lambda: self.now,
        )
        app = Starlette(
            routes=[
                login_route(login, frozenset({_ORIGIN}), _CLIENT_IDENTITY_KEY)
            ]
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=_ORIGIN
        ) as client:
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            rejected = await client.post(
                "/api/v1/auth/login",
                headers={
                    "origin": _ORIGIN,
                    "x-sentinel-csrf": _CSRF,
                    "x-request-id": "db-limiter-failure-1",
                },
                json={"username": username.value, "password": "wrong-password"},
            )
            limited = await client.post(
                "/api/v1/auth/login",
                headers={
                    "origin": _ORIGIN,
                    "x-sentinel-csrf": _CSRF,
                    "x-request-id": "db-limiter-blocked-1",
                },
                json={
                    "username": username.value,
                    "password": "synthetic-valid-password-012345",
                },
            )

        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()["error"]["code"], "rate_limited")
        self.assertEqual(limited.json()["error"]["retryAfterMs"], 60_000)
        expected_digest = hmac.new(
            _CLIENT_IDENTITY_KEY, b"127.0.0.1", hashlib.sha256
        ).hexdigest()
        async with self.engine.connect() as connection:
            stored_digest = (
                await connection.execute(
                    select(LoginAttemptRecord.client_identity_digest)
                )
            ).scalar_one()
            session_count = await connection.scalar(
                select(func.count()).select_from(AuthenticationSessionRecord)
            )
        self.assertEqual(stored_digest, expected_digest)
        self.assertEqual(session_count, 0)

    async def test_invalid_digest_policy_clock_and_database_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            await self.limiter.record_failure("127.0.0.1")
        with self.assertRaises(ValueError):
            login_attempt_limiter.LoginAttemptLimitPolicy(
                0, timedelta(minutes=1), timedelta(minutes=1)
            )

        naive_clock_limiter = login_attempt_limiter.SqlAlchemyLoginAttemptLimiter(
            self.engine,
            policy=_POLICY,
            clock=lambda: datetime(2026, 10, 9),
        )
        with self.assertRaises(ValueError):
            await naive_clock_limiter.record_failure(_CLIENT_DIGEST)

        unavailable_engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.temporary_directory.name}/missing/db.sqlite"
        )
        try:
            unavailable_limiter = (
                login_attempt_limiter.SqlAlchemyLoginAttemptLimiter(
                    unavailable_engine, policy=_POLICY, clock=lambda: self.now
                )
            )
            with self.assertRaises(LoginAuthorityUnavailable):
                await unavailable_limiter.record_failure(_CLIENT_DIGEST)
        finally:
            await unavailable_engine.dispose()

    async def test_insert_if_absent_compiles_for_supported_dialects(self) -> None:
        class _DialectProbe:
            def __init__(self, dialect) -> None:
                self.dialect = dialect
                self.statement = None

            async def execute(self, statement) -> None:
                self.statement = statement

        cases = (
            (postgresql.dialect(), "ON CONFLICT"),
            (mysql.dialect(), "ON DUPLICATE KEY UPDATE"),
            (sqlite.dialect(), "ON CONFLICT"),
        )
        for dialect, expected_sql in cases:
            with self.subTest(dialect=dialect.name):
                connection = _DialectProbe(dialect)
                await self.limiter._insert_if_absent(
                    connection, _CLIENT_DIGEST, int(self.now.timestamp() * 1000)
                )
                compiled = str(connection.statement.compile(dialect=dialect))
                self.assertIn(expected_sql, compiled)


if __name__ == "__main__":
    unittest.main()
