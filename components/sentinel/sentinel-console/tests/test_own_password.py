"""Own-password API and transaction tests against isolated SQLite."""

from __future__ import annotations

import hashlib
import unittest
from datetime import UTC, datetime, timedelta

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.change_own_password import (
    ChangeOwnPassword,
)
from atlas_richie.sentinel_console.infrastructure.persistence.current_session_reader import (
    SqlAlchemyCurrentSessionReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.login_attempt_limiter import (
    LoginAttemptLimitPolicy,
    SqlAlchemyLoginAttemptLimiter,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuditEventRecord,
    AuthenticationSessionRecord,
    ConsoleGuardRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.own_password_credential_reader import (
    SqlAlchemyOwnPasswordCredentialReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.own_password_writer import (
    SqlAlchemyOwnPasswordWriter,
)
from atlas_richie.sentinel_console.infrastructure.security.password_hash import (
    PasswordHashService,
)
from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import create_async_engine

_ORIGIN = "https://console.test"
_NOW = datetime.now(UTC)
_ADMIN_COOKIE = "synthetic-own-password-admin-session-token-001"
_ADMIN_CSRF = "synthetic-own-password-admin-csrf-token-0001"
_SECOND_COOKIE = "synthetic-own-password-second-session-token-0001"
_SECOND_CSRF = "synthetic-own-password-second-csrf-token-00001"
_VIEW_COOKIE = "synthetic-own-password-view-session-token-00001"
_VIEW_CSRF = "synthetic-own-password-view-csrf-token-00001"
_INITIAL_PLACEHOLDER = "synthetic-initial-password-00001"


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _SetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _TrackingPasswordHasher:
    def __init__(self) -> None:
        self._delegate = PasswordHashService()
        self.verify_calls = 0
        self.hash_calls = 0

    def hash_password(self, password: str) -> str:
        self.hash_calls += 1
        return self._delegate.hash_password(password)

    def verify_password(self, encoded_hash: str, candidate: str) -> bool:
        self.verify_calls += 1
        return self._delegate.verify_password(encoded_hash, candidate)


class OwnPasswordApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        self.hasher = _TrackingPasswordHasher()
        self.initial_password = "synthetic-initial-password-00001"
        self.initial_hash = self.hasher.hash_password(self.initial_password)
        async with self.engine.begin() as connection:
            await connection.execute(
                update(ConsoleGuardRecord)
                .where(ConsoleGuardRecord.singleton_id == 1)
                .values(initialized=True, revision=1, initialized_at=_NOW)
            )
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="admin-1",
                    username="admin-one",
                    username_key=hashlib.sha256(b"admin-one").hexdigest(),
                    password_hash=self.initial_hash,
                    role_id="admin",
                    status="active",
                    built_in=False,
                    last_login_at=None,
                    revision=1,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await self._insert_session(connection, _ADMIN_COOKIE, _ADMIN_CSRF)
            await self._insert_session(connection, _SECOND_COOKIE, _SECOND_CSRF)
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="view-1",
                    username="view-one",
                    username_key=hashlib.sha256(b"view-one").hexdigest(),
                    password_hash=self.initial_hash,
                    role_id="view",
                    status="active",
                    built_in=False,
                    last_login_at=None,
                    revision=1,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await self._insert_session(
                connection, _VIEW_COOKIE, _VIEW_CSRF, account_id="view-1"
            )

        self.service = ChangeOwnPassword(
            reader=SqlAlchemyOwnPasswordCredentialReader(self.engine),
            writer=SqlAlchemyOwnPasswordWriter(self.engine),
            password_hasher=self.hasher,
            attempt_limiter=SqlAlchemyLoginAttemptLimiter(
                self.engine,
                policy=LoginAttemptLimitPolicy(
                    failure_threshold=2,
                    window=timedelta(minutes=5),
                    block_duration=timedelta(minutes=10),
                ),
            ),
            attempt_hmac_key=b"synthetic-own-password-limit-key-0001",
        )
        self.app = build_app(
            bootstrap_initialization_reader=_Initialized(),
            setup_window_reader=_SetupWindow(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=SqlAlchemyCurrentSessionReader(self.engine),
            current_session_revoker=_UnusedSessionRevoker(),
            account_directory_reader=_UnusedAccountDirectoryReader(),
            allowed_browser_origins=frozenset({_ORIGIN}),
            own_password_service=self.service,
        )

    async def _insert_session(
        self,
        connection,
        token: str,
        csrf: str,
        *,
        account_id: str = "admin-1",
        stored_csrf: str | None = None,
    ) -> None:
        async with connection.begin_nested():
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=hashlib.sha256(token.encode()).hexdigest(),
                    account_id=account_id,
                    session_epoch=f"epoch-{account_id}-{token[-4:]}",
                    csrf_hash=hashlib.sha256(
                        (stored_csrf or csrf).encode()
                    ).hexdigest(),
                    created_at=_NOW,
                    expires_at=_NOW + timedelta(hours=1),
                    revoked_at=None,
                )
            )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    def _client(self, token: str, csrf: str) -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=self.app), base_url=_ORIGIN)
        client.cookies.set("sentinel_session", token)
        client.cookies.set("__Host-sentinel_csrf", csrf)
        return client

    def _headers(self, csrf: str, request_id: str) -> dict[str, str]:
        return {
            "origin": _ORIGIN,
            "x-request-id": request_id,
            "x-sentinel-csrf": csrf,
            "content-type": "application/json",
        }

    async def _change(
        self,
        client: AsyncClient,
        *,
        csrf: str = _ADMIN_CSRF,
        request_id: str = "change-password-1",
        current_password: str = _INITIAL_PLACEHOLDER,
        new_password: str = "synthetic-new-password-00001",
    ):
        return await client.post(
            "/api/v1/auth/password",
            headers=self._headers(csrf, request_id),
            json={"currentPassword": current_password, "newPassword": new_password},
        )

    async def test_change_hashes_password_revokes_all_sessions_and_audits_safely(
        self,
    ) -> None:
        new_password = "synthetic-new-password-00001"
        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as client:
            response = await self._change(client, new_password=new_password)
            identity = await client.get(
                "/api/v1/auth/me", headers={"x-request-id": "after-password-change"}
            )

        self.assertEqual(response.status_code, 200)
        assert_openapi_response("changeOwnPassword", response)
        self.assertEqual(response.json(), {"sessionDisposition": "reauthenticate"})
        self.assertEqual(identity.json(), None)
        self.assertIn('sentinel_session="";', response.headers["set-cookie"])
        self.assertNotIn(self.initial_password, response.text)
        self.assertNotIn(new_password, response.text)
        async with self.engine.connect() as connection:
            stored_hash = await connection.scalar(
                select(AccountRecord.password_hash).where(
                    AccountRecord.account_id == "admin-1"
                )
            )
            revisions = await connection.scalar(
                select(AccountRecord.revision).where(
                    AccountRecord.account_id == "admin-1"
                )
            )
            active_sessions = await connection.scalar(
                select(func.count())
                .select_from(AuthenticationSessionRecord)
                .where(
                    AuthenticationSessionRecord.account_id == "admin-1",
                    AuthenticationSessionRecord.revoked_at.is_(None),
                )
            )
            audit = (
                await connection.execute(
                    select(AuditEventRecord.action, AuditEventRecord.outcome)
                )
            ).one()
        self.assertNotEqual(stored_hash, new_password)
        self.assertTrue(
            self.hasher._delegate.verify_password(stored_hash, new_password)
        )
        self.assertFalse(
            self.hasher._delegate.verify_password(stored_hash, self.initial_password)
        )
        self.assertEqual(revisions, 2)
        self.assertEqual(active_sessions, 0)
        self.assertEqual(tuple(audit), ("auth.password.change", "completed"))

    async def test_wrong_current_password_does_not_mutate_or_audit(self) -> None:
        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as client:
            response = await self._change(
                client, current_password="synthetic-wrong-password-00001"
            )
        self.assertEqual(response.status_code, 400)
        assert_openapi_response("changeOwnPassword", response)
        self.assertEqual(response.json()["error"]["code"], "current_password_invalid")
        async with self.engine.connect() as connection:
            stored_hash = await connection.scalar(
                select(AccountRecord.password_hash).where(
                    AccountRecord.account_id == "admin-1"
                )
            )
            active_sessions = await connection.scalar(
                select(func.count())
                .select_from(AuthenticationSessionRecord)
                .where(
                    AuthenticationSessionRecord.account_id == "admin-1",
                    AuthenticationSessionRecord.revoked_at.is_(None),
                )
            )
            audit_count = await connection.scalar(
                select(func.count()).select_from(AuditEventRecord)
            )
        self.assertEqual(stored_hash, self.initial_hash)
        self.assertEqual(active_sessions, 2)
        self.assertEqual(audit_count, 0)

    async def test_wrong_password_is_rate_limited_per_account(self) -> None:
        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as client:
            first = await self._change(
                client,
                request_id="password-wrong-one",
                current_password="synthetic-wrong-password-00001",
            )
            second = await self._change(
                client,
                request_id="password-wrong-two",
                current_password="synthetic-wrong-password-00001",
            )
            calls_after_failures = self.hasher.verify_calls
            blocked = await self._change(
                client,
                request_id="password-blocked",
                current_password=self.initial_password,
            )

        self.assertEqual(first.status_code, 400)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["error"]["code"], "rate_limited")
        self.assertEqual(blocked.json()["error"]["retryAfterMs"], 300_000)
        self.assertEqual(self.hasher.verify_calls, calls_after_failures)

        async with self._client(_VIEW_COOKIE, _VIEW_CSRF) as client:
            other_account = await self._change(
                client,
                csrf=_VIEW_CSRF,
                current_password=self.initial_password,
                new_password="synthetic-view-new-password-0002",
                request_id="view-password-not-blocked",
            )
        self.assertEqual(other_account.status_code, 200)

    async def test_rate_limit_authority_failure_fails_closed(self) -> None:
        async with self.engine.begin() as connection:
            await connection.exec_driver_sql("DROP TABLE console_login_attempt")

        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as client:
            response = await self._change(client, request_id="password-limit-down")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertEqual(self.hasher.verify_calls, 0)
        self.assertEqual(self.hasher.hash_calls, 1)

    async def test_missing_session_remains_unauthenticated(self) -> None:
        async with self._client(
            "unknown-own-password-session-0001", _ADMIN_CSRF
        ) as client:
            response = await self._change(client)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthenticated")

    async def test_view_role_can_change_only_its_own_password(self) -> None:
        new_password = "synthetic-view-new-password-0001"
        async with self._client(_VIEW_COOKIE, _VIEW_CSRF) as client:
            response = await self._change(
                client,
                csrf=_VIEW_CSRF,
                current_password=self.initial_password,
                new_password=new_password,
            )
        self.assertEqual(response.status_code, 200)
        async with self.engine.connect() as connection:
            stored_hash = await connection.scalar(
                select(AccountRecord.password_hash).where(
                    AccountRecord.account_id == "view-1"
                )
            )
        self.assertTrue(
            self.hasher._delegate.verify_password(stored_hash, new_password)
        )

    async def test_origin_shape_and_password_validation_fail_before_hash_work(
        self,
    ) -> None:
        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as client:
            wrong_origin = await client.post(
                "/api/v1/auth/password",
                headers={
                    **self._headers(_ADMIN_CSRF, "wrong-password-origin"),
                    "origin": "https://attacker.test",
                },
                json={
                    "currentPassword": self.initial_password,
                    "newPassword": "synthetic-new-password-00001",
                },
            )
            invalid_new_password = await self._change(client, new_password="too-short")
            extra_field = await client.post(
                "/api/v1/auth/password",
                headers=self._headers(_ADMIN_CSRF, "password-extra-field"),
                json={
                    "currentPassword": self.initial_password,
                    "newPassword": "synthetic-new-password-00001",
                    "accountId": "admin-1",
                },
            )
            duplicate_json = await client.post(
                "/api/v1/auth/password",
                headers=self._headers(_ADMIN_CSRF, "password-duplicate-json"),
                content=(
                    '{"currentPassword":"secret","currentPassword":"other",'
                    '"newPassword":"synthetic-new-password-00001"}'
                ),
            )
        self.assertEqual(wrong_origin.status_code, 403)
        self.assertEqual(invalid_new_password.status_code, 422)
        self.assertEqual(extra_field.status_code, 400)
        self.assertEqual(duplicate_json.status_code, 400)
        self.assertEqual(self.hasher.verify_calls, 0)
        self.assertEqual(self.hasher.hash_calls, 1)

    async def test_password_utf16_limit_accepts_exact_supplementary_boundary(self):
        new_password = "😀" * 512
        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as client:
            response = await self._change(client, new_password=new_password)

        self.assertEqual(response.status_code, 200)
        assert_openapi_response("changeOwnPassword", response)
        async with self.engine.connect() as connection:
            stored_hash = await connection.scalar(
                select(AccountRecord.password_hash).where(
                    AccountRecord.account_id == "admin-1"
                )
            )
        self.assertTrue(
            self.hasher._delegate.verify_password(stored_hash, new_password)
        )

    async def test_password_utf16_overflow_and_unpaired_surrogate_fail_before_hashing(
        self,
    ):
        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as client:
            overflow = await self._change(
                client,
                request_id="password-utf16-overflow",
                new_password=("😀" * 512) + "a",
            )
            unpaired_surrogate = await client.post(
                "/api/v1/auth/password",
                headers=self._headers(_ADMIN_CSRF, "password-unpaired-surrogate"),
                content=(
                    b'{"currentPassword":"synthetic-initial-password-00001",'
                    b'"newPassword":"synthetic-password-\\ud800"}'
                ),
            )

        self.assertEqual(overflow.status_code, 422)
        self.assertEqual(overflow.json()["error"]["code"], "validation_failed")
        assert_openapi_response("changeOwnPassword", overflow)
        self.assertEqual(unpaired_surrogate.status_code, 400)
        self.assertEqual(unpaired_surrogate.json()["error"]["code"], "invalid_request")
        assert_openapi_response("changeOwnPassword", unpaired_surrogate)
        self.assertEqual(self.hasher.verify_calls, 0)
        self.assertEqual(self.hasher.hash_calls, 1)

    async def test_persisted_csrf_mismatch_fails_and_database_error_rolls_back(
        self,
    ) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                update(AuthenticationSessionRecord)
                .where(
                    AuthenticationSessionRecord.session_hash
                    == hashlib.sha256(_ADMIN_COOKIE.encode()).hexdigest()
                )
                .values(
                    csrf_hash=hashlib.sha256(
                        b"different-persisted-csrf-value-0001"
                    ).hexdigest()
                )
            )
        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as client:
            csrf_mismatch = await self._change(client)
        self.assertEqual(csrf_mismatch.status_code, 403)
        self.assertEqual(self.hasher.verify_calls, 0)
        self.assertEqual(self.hasher.hash_calls, 1)

        async with self.engine.begin() as connection:
            await connection.execute(
                update(AuthenticationSessionRecord)
                .where(
                    AuthenticationSessionRecord.session_hash
                    == hashlib.sha256(_ADMIN_COOKIE.encode()).hexdigest()
                )
                .values(csrf_hash=hashlib.sha256(_ADMIN_CSRF.encode()).hexdigest())
            )
            await connection.exec_driver_sql("DROP TABLE console_audit_event")
        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as client:
            unavailable = await self._change(
                client,
                csrf=_ADMIN_CSRF,
                request_id="password-db-failure",
            )
        self.assertEqual(unavailable.status_code, 503)
        self.assertNotIn("console_audit_event", unavailable.text)
        async with self.engine.connect() as connection:
            stored_hash = await connection.scalar(
                select(AccountRecord.password_hash).where(
                    AccountRecord.account_id == "admin-1"
                )
            )
            active_sessions = await connection.scalar(
                select(func.count())
                .select_from(AuthenticationSessionRecord)
                .where(
                    AuthenticationSessionRecord.account_id == "admin-1",
                    AuthenticationSessionRecord.revoked_at.is_(None),
                )
            )
        self.assertEqual(stored_hash, self.initial_hash)
        self.assertEqual(active_sessions, 2)


class _UnusedSessionRevoker:
    async def revoke_current_session(self, *args, **kwargs):
        raise AssertionError("own-password route must not use logout authority")


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("own-password tests do not read the account directory")

    async def read_account(self, account_id: str):
        raise AssertionError("own-password tests do not read the account directory")
