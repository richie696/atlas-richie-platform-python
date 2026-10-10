"""Account command API and transaction tests against isolated SQLite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import unittest

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.account_commands import MutateAccount
from atlas_richie.sentinel_console.infrastructure.persistence.account_command_store import (
    SqlAlchemyAccountCommandStore,
)
from atlas_richie.sentinel_console.infrastructure.persistence.account_directory_reader import (
    SqlAlchemyAccountDirectoryReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.current_session_reader import (
    SqlAlchemyCurrentSessionReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.current_session_revoker import (
    SqlAlchemyCurrentSessionRevoker,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountOperationRecord,
    AccountRecord,
    AuditEventRecord,
    AuthenticationSessionRecord,
    ConsoleGuardRecord,
)
from atlas_richie.sentinel_console.infrastructure.security.password_hash import (
    PasswordHashService,
)

_ORIGIN = "https://console.test"
_NOW = datetime.now(UTC)
_ADMIN_COOKIE = "synthetic-admin-session-token-account-command-0001"
_ADMIN_CSRF = "synthetic-admin-csrf-token-account-command-0001"
_SECOND_ADMIN_COOKIE = "synthetic-second-admin-session-token-command-001"
_SECOND_ADMIN_CSRF = "synthetic-second-admin-csrf-token-command-001"
_VIEW_COOKIE = "synthetic-view-session-token-account-command-000001"
_VIEW_CSRF = "synthetic-view-csrf-token-account-command-000001"
_FINGERPRINT_KEY = b"synthetic-account-command-fingerprint-key-0000001"


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _SetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("test app should use the SQLite account directory")

    async def read_account(self, account_id: str):
        raise AssertionError("test app should use the SQLite account directory")


class AccountCommandApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        async with self.engine.begin() as connection:
            await connection.execute(
                update(ConsoleGuardRecord)
                .where(ConsoleGuardRecord.singleton_id == 1)
                .values(initialized=True, revision=1, initialized_at=_NOW)
            )
        self.hasher = PasswordHashService()
        self.store = SqlAlchemyAccountCommandStore(self.engine)
        self.service = MutateAccount(
            store=self.store,
            password_hasher=self.hasher,
            fingerprint_keys={"key-1": _FINGERPRINT_KEY},
            active_fingerprint_key_id="key-1",
        )
        self.app = self._build_app(self.service)

        await self._seed_identity(
            "admin-1", "admin-one", "admin", False, _ADMIN_COOKIE, _ADMIN_CSRF
        )
        await self._seed_identity(
            "admin-2", "admin-two", "admin", False,
            _SECOND_ADMIN_COOKIE, _SECOND_ADMIN_CSRF,
        )
        await self._seed_identity(
            "view-1", "view-one", "view", False, _VIEW_COOKIE, _VIEW_CSRF
        )

    def _build_app(self, service: MutateAccount):
        self.app = build_app(
            bootstrap_initialization_reader=_Initialized(),
            setup_window_reader=_SetupWindow(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=SqlAlchemyCurrentSessionReader(self.engine),
            current_session_revoker=SqlAlchemyCurrentSessionRevoker(self.engine),
            account_directory_reader=SqlAlchemyAccountDirectoryReader(self.engine),
            allowed_browser_origins=frozenset({_ORIGIN}),
            account_command_service=service,
        )
        return self.app

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _seed_identity(
        self,
        account_id: str,
        username: str,
        role_id: str,
        built_in: bool,
        session_token: str | None,
        csrf_nonce: str | None,
    ) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id=account_id,
                    username=username,
                    username_key=hashlib.sha256(username.encode()).hexdigest(),
                    password_hash=self.hasher.hash_password("synthetic-seed-password"),
                    role_id=role_id,
                    status="active",
                    built_in=built_in,
                    last_login_at=None,
                    revision=1,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            if session_token is not None and csrf_nonce is not None:
                await connection.execute(
                    insert(AuthenticationSessionRecord).values(
                        session_hash=hashlib.sha256(session_token.encode()).hexdigest(),
                        account_id=account_id,
                        session_epoch=f"epoch-{account_id}",
                        csrf_hash=hashlib.sha256(csrf_nonce.encode()).hexdigest(),
                        created_at=_NOW,
                        expires_at=_NOW + timedelta(hours=1),
                        revoked_at=None,
                    )
                )

    def _client(self, token: str, csrf: str) -> AsyncClient:
        client = AsyncClient(
            transport=ASGITransport(app=self.app), base_url=_ORIGIN
        )
        client.cookies.set("sentinel_session", token)
        client.cookies.set("__Host-sentinel_csrf", csrf)
        return client

    async def _command(
        self,
        client: AsyncClient,
        command: dict[str, object],
        request_key: str,
        request_id: str,
        csrf: str,
    ):
        return await client.post(
            "/api/v1/accounts/commands",
            headers={
                "origin": _ORIGIN,
                "x-request-id": request_id,
                "x-sentinel-csrf": csrf,
                "idempotency-key": request_key,
            },
            json=command,
        )

    async def test_create_is_idempotent_and_receipt_never_contains_password(
        self,
    ) -> None:
        password = "synthetic-account-password-12345"
        body = {
            "kind": "create",
            "requestKey": "create-user-1",
            "input": {
                "username": "New Operator",
                "password": password,
                "roleId": "view",
            },
        }
        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as client:
            created = await self._command(
                client, body, "create-user-1", "create-request-1", _ADMIN_CSRF
            )
            replay = await self._command(
                client, body, "create-user-1", "create-request-2", _ADMIN_CSRF
            )
            receipt = await client.get(
                "/api/v1/accounts/operations/create-user-1",
                headers={"x-request-id": "read-operation-1"},
            )
            status_changed = await self._command(
                client,
                {
                    "kind": "status",
                    "requestKey": "disable-created-user",
                    "accountId": created.json()["account"]["id"],
                    "revision": "1",
                    "status": "disabled",
                },
                "disable-created-user",
                "account-status-1",
                _ADMIN_CSRF,
            )
            original_receipt = await client.get(
                "/api/v1/accounts/operations/create-user-1",
                headers={"x-request-id": "read-operation-2"},
            )

        self.assertEqual(created.status_code, 200)
        self.assertEqual(replay.json(), created.json())
        self.assertEqual(receipt.json(), created.json())
        self.assertEqual(status_changed.json()["account"]["status"], "disabled")
        self.assertEqual(original_receipt.json(), created.json())
        self.assertEqual(created.json()["status"], "completed")
        self.assertEqual(created.json()["account"]["username"], "New Operator")
        self.assertNotIn(password, created.text)
        self.assertNotIn(password, replay.text)
        self.assertNotIn(password, receipt.text)
        async with self.engine.connect() as connection:
            stored_hash = await connection.scalar(
                select(AccountRecord.password_hash).where(
                    AccountRecord.username == "New Operator"
                )
            )
            operation_count = await connection.scalar(
                select(func.count()).select_from(AccountOperationRecord)
            )
            audit_count = await connection.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(AuditEventRecord.action == "accounts.create")
            )
        self.assertNotEqual(stored_hash, password)
        self.assertTrue(self.hasher.verify_password(stored_hash, password))
        self.assertEqual(operation_count, 2)
        self.assertEqual(audit_count, 1)

    async def test_reusing_key_for_changed_input_conflicts_without_second_write(
        self,
    ) -> None:
        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as client:
            first = await self._command(
                client,
                {
                    "kind": "create",
                    "requestKey": "same-key-1",
                    "input": {
                        "username": "One",
                        "password": "synthetic-password-0001",
                        "roleId": "view",
                    },
                },
                "same-key-1",
                "request-first-1",
                _ADMIN_CSRF,
            )
            conflict = await self._command(
                client,
                {
                    "kind": "create",
                    "requestKey": "same-key-1",
                    "input": {
                        "username": "Two",
                        "password": "synthetic-password-0002",
                        "roleId": "view",
                    },
                },
                "same-key-1",
                "request-second-1",
                _ADMIN_CSRF,
            )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "idempotency_conflict")
        async with self.engine.connect() as connection:
            total = await connection.scalar(
                select(func.count()).select_from(AccountRecord)
            )
        self.assertEqual(total, 4)

    async def test_retry_survives_fingerprint_key_rotation_when_old_key_is_retained(
        self,
    ) -> None:
        command = {
            "kind": "create",
            "requestKey": "rotated-key-operation",
            "input": {
                "username": "Rotation Retry",
                "password": "synthetic-password-rotation-0001",
                "roleId": "view",
            },
        }
        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as client:
            first = await self._command(
                client,
                command,
                "rotated-key-operation",
                "rotation-first-1",
                _ADMIN_CSRF,
            )

        rotated_service = MutateAccount(
            store=self.store,
            password_hasher=self.hasher,
            fingerprint_keys={
                "key-2": b"synthetic-rotated-fingerprint-key-000000000000",
                "key-1": _FINGERPRINT_KEY,
            },
            active_fingerprint_key_id="key-2",
        )
        self.app = self._build_app(rotated_service)
        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as client:
            replay = await self._command(
                client,
                command,
                "rotated-key-operation",
                "rotation-replay-1",
                _ADMIN_CSRF,
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json(), first.json())
        async with self.engine.connect() as connection:
            account_count = await connection.scalar(
                select(func.count()).select_from(AccountRecord)
            )
            fingerprint_key_id = await connection.scalar(
                select(AccountOperationRecord.fingerprint_key_id).where(
                    AccountOperationRecord.request_key == "rotated-key-operation"
                )
            )
        self.assertEqual(account_count, 4)
        self.assertEqual(fingerprint_key_id, "key-1")

    async def test_viewer_and_other_admin_cannot_mutate_or_read_another_actor_receipt(
        self,
    ) -> None:
        command = {
            "kind": "create",
            "requestKey": "owned-operation-1",
            "input": {
                "username": "Owned",
                "password": "synthetic-password-0003",
                "roleId": "view",
            },
        }
        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as admin:
            created = await self._command(
                admin, command, "owned-operation-1", "owner-write-1", _ADMIN_CSRF
            )
        async with self._client(_VIEW_COOKIE, _VIEW_CSRF) as viewer:
            denied = await self._command(
                viewer,
                {
                    "kind": "create",
                    "requestKey": "viewer-write-1",
                    "input": {
                        "username": "Denied",
                        "password": "synthetic-password-0004",
                        "roleId": "view",
                    },
                },
                "viewer-write-1",
                "viewer-write-request-1",
                _VIEW_CSRF,
            )
        async with self._client(
            _SECOND_ADMIN_COOKIE, _SECOND_ADMIN_CSRF
        ) as other_admin:
            hidden = await other_admin.get(
                "/api/v1/accounts/operations/owned-operation-1",
                headers={"x-request-id": "other-owner-read-1"},
            )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(
            hidden.json(),
            {"status": "not-found", "requestKey": "owned-operation-1"},
        )
        self.assertNotIn("Owned", hidden.text)

    async def test_status_role_conflict_builtin_and_last_admin_invariants(self) -> None:
        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as client:
            disabled = await self._command(
                client,
                {
                    "kind": "status",
                    "requestKey": "disable-admin-2",
                    "accountId": "admin-2",
                    "revision": "1",
                    "status": "disabled",
                },
                "disable-admin-2",
                "status-command-1",
                _ADMIN_CSRF,
            )
            demote_last = await self._command(
                client,
                {
                    "kind": "role",
                    "requestKey": "demote-last-admin",
                    "accountId": "admin-1",
                    "revision": "1",
                    "roleId": "view",
                },
                "demote-last-admin",
                "role-command-1",
                _ADMIN_CSRF,
            )
            await self._seed_identity(
                "builtin-1", "builtin-admin", "admin", True, None, None
            )
            builtin = await self._command(
                client,
                {
                    "kind": "status",
                    "requestKey": "disable-builtin",
                    "accountId": "builtin-1",
                    "revision": "1",
                    "status": "disabled",
                },
                "disable-builtin",
                "builtin-command-1",
                _ADMIN_CSRF,
            )
            stale = await self._command(
                client,
                {
                    "kind": "role",
                    "requestKey": "stale-role-change",
                    "accountId": "view-1",
                    "revision": "7",
                    "roleId": "admin",
                },
                "stale-role-change",
                "stale-command-1",
                _ADMIN_CSRF,
            )
            promote = await self._command(
                client,
                {
                    "kind": "role",
                    "requestKey": "promote-view",
                    "accountId": "view-1",
                    "revision": "1",
                    "roleId": "admin",
                },
                "promote-view",
                "promote-command-1",
                _ADMIN_CSRF,
            )
        self.assertEqual(disabled.json()["status"], "completed")
        self.assertEqual(disabled.json()["account"]["revision"], "2")
        self.assertEqual(demote_last.status_code, 200, demote_last.text)
        self.assertEqual(
            demote_last.json().get("reason"), "last_admin", demote_last.text
        )
        self.assertEqual(builtin.json()["reason"], "built_in")
        self.assertEqual(stale.json()["reason"], "conflict")
        self.assertEqual(promote.json()["account"]["roleId"], "admin")

    async def test_origin_csrf_and_duplicate_json_key_reject_before_write(self) -> None:
        async with self._client(_ADMIN_COOKIE, _ADMIN_CSRF) as client:
            wrong_origin = await client.post(
                "/api/v1/accounts/commands",
                headers={
                    "origin": "https://attacker.test",
                    "x-request-id": "wrong-origin-1",
                    "x-sentinel-csrf": _ADMIN_CSRF,
                    "idempotency-key": "bad-origin-key",
                },
                json={"kind": "create", "requestKey": "bad-origin-key", "input": {}},
            )
            bad_csrf = await self._command(
                client,
                {
                    "kind": "create",
                    "requestKey": "bad-csrf-key",
                    "input": {
                        "username": "Nope",
                        "password": "synthetic-password-0005",
                        "roleId": "view",
                    },
                },
                "bad-csrf-key",
                "bad-csrf-request-1",
                "different-csrf-token-value-000001",
            )
            duplicate_json = await client.post(
                "/api/v1/accounts/commands",
                headers={
                    "origin": _ORIGIN,
                    "x-request-id": "duplicate-json-1",
                    "x-sentinel-csrf": _ADMIN_CSRF,
                    "idempotency-key": "duplicate-json-key",
                    "content-type": "application/json",
                },
                content=(
                    '{"kind":"create","requestKey":"duplicate-json-key",'
                    '"requestKey":"different-key","input":{}}'
                ),
            )
            unpaired_surrogate_json = await client.post(
                "/api/v1/accounts/commands",
                headers={
                    "origin": _ORIGIN,
                    "x-request-id": "surrogate-json-1",
                    "x-sentinel-csrf": _ADMIN_CSRF,
                    "idempotency-key": "surrogate-json-key",
                    "content-type": "application/json",
                },
                content=(
                    '{"kind":"create","requestKey":"surrogate-json-key",'
                    '"input":{"username":"\\ud800",'
                    '"password":"synthetic-password-0005","roleId":"view"}}'
                ),
            )
        self.assertEqual(wrong_origin.status_code, 403)
        self.assertEqual(bad_csrf.status_code, 403)
        self.assertEqual(duplicate_json.status_code, 400)
        self.assertEqual(unpaired_surrogate_json.status_code, 400)
        async with self.engine.connect() as connection:
            operations = await connection.scalar(
                select(func.count()).select_from(AccountOperationRecord)
            )
        self.assertEqual(operations, 0)
