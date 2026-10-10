"""Opt-in MySQL migration compatibility acceptance."""

from __future__ import annotations

import asyncio
import hashlib
import os
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from bootstrap_database_acceptance_support import (
    assert_bootstrap_retries_are_deduplicated_and_actor_bound,
    assert_competing_bootstrap_initializations_are_serialized,
    assert_first_run_http_persists_on_real_database,
    assert_sql_identity_http_persists_credentials_and_sessions,
)
from rule_activation_plan_database_acceptance import (
    assert_cancel_racing_activation_claim_preserves_started_publication,
    assert_independent_plan_workers_fence_and_recover,
)
from rule_binding_registration_database_acceptance import (
    assert_competing_same_key_registrations_are_idempotent,
)
from rule_publication_receipt_database_acceptance import (
    assert_runtime_publication_receipt_persistence,
)
from rule_publication_consul_database_acceptance import (
    assert_sql_outbox_publishes_to_disposable_consul,
)
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.account_commands import (
    AccountCommandActor,
    AccountCommandKind,
    AccountCommandReason,
    AccountMutation,
    AccountOperationStatus,
    MutateAccount,
)
from atlas_richie.sentinel_console.domain.session import AccountRole
from atlas_richie.sentinel_console.infrastructure.persistence import (
    account_command_store,
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

_DATABASE_URL_ENV = "SENTINEL_CONSOLE_TEST_MYSQL_URL"
_DATABASE_URL = os.environ.get(_DATABASE_URL_ENV)


def _validated_test_database_url(value: str | None) -> str | None:
    if value is None:
        return None
    url = make_url(value)
    if (
        url.drivername != "mysql+asyncmy"
        or not url.database
        or not url.database.startswith("sentinel_console_test_")
        or url.host not in {"127.0.0.1", "localhost", "mysql"}
    ):
        raise ValueError(
            f"{_DATABASE_URL_ENV} must target an isolated "
            "sentinel_console_test_* database"
        )
    return value


_DATABASE_URL = _validated_test_database_url(_DATABASE_URL)


@unittest.skipUnless(
    _DATABASE_URL, f"set {_DATABASE_URL_ENV} to run MySQL acceptance"
)
class MySQLConsoleMigrationAcceptanceTest(unittest.IsolatedAsyncioTestCase):
    """Exercise current migrations on a real, disposable MySQL server."""

    async def asyncSetUp(self) -> None:
        assert _DATABASE_URL is not None
        self.engine = create_async_engine(_DATABASE_URL, pool_size=5)
        await upgrade_database(self.engine)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_competing_bootstrap_initializations_are_serialized(self) -> None:
        await assert_competing_bootstrap_initializations_are_serialized(
            self.engine, "mysql"
        )

    async def test_bootstrap_retries_are_deduplicated_and_actor_bound(self) -> None:
        await assert_bootstrap_retries_are_deduplicated_and_actor_bound(
            self.engine, "mysql"
        )

    async def test_sql_identity_http_persists_credentials_and_sessions(self) -> None:
        await assert_sql_identity_http_persists_credentials_and_sessions(
            self.engine, "mysql"
        )

    async def test_z_full_first_run_http_path_persists_setup(self) -> None:
        await assert_first_run_http_persists_on_real_database(self.engine, "mysql")

    async def test_concurrent_rule_binding_retries_are_idempotent(self) -> None:
        await assert_competing_same_key_registrations_are_idempotent(
            self.engine, "mysql"
        )

    async def test_independent_activation_plan_workers_fence_and_recover(self) -> None:
        assert _DATABASE_URL is not None
        await assert_independent_plan_workers_fence_and_recover(
            self, self.engine, _DATABASE_URL
        )

    async def test_cancel_racing_activation_claim_preserves_started_publication(self) -> None:
        assert _DATABASE_URL is not None
        await assert_cancel_racing_activation_claim_preserves_started_publication(
            self, self.engine, _DATABASE_URL
        )

    async def test_rule_publication_receipt_store_round_trip(self) -> None:
        await assert_runtime_publication_receipt_persistence(
            self, self.engine, "mysql"
        )

    @unittest.skipUnless(
        os.environ.get("SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE") == "1",
        "set SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 to start disposable Consul",
    )
    async def test_sql_rule_outbox_publishes_to_disposable_consul(self) -> None:
        await assert_sql_outbox_publishes_to_disposable_consul(self.engine)

    async def test_migration_is_repeatable_and_revision_storage_is_wide_enough(
        self,
    ) -> None:
        async with self.engine.begin() as connection:
            initialized = await connection.scalar(
                select(ConsoleGuardRecord.initialized).where(
                    ConsoleGuardRecord.singleton_id == 1
                )
            )
            version_length = await connection.scalar(
                text(
                    "SELECT character_maximum_length "
                    "FROM information_schema.columns "
                    "WHERE table_schema = DATABASE() "
                    "AND table_name = 'alembic_version' "
                    "AND column_name = 'version_num'"
                )
            )
            guard_autoincrement = await connection.scalar(
                text(
                    "SELECT extra = 'auto_increment' "
                    "FROM information_schema.columns "
                    "WHERE table_schema = DATABASE() "
                    "AND table_name = 'console_guard' "
                    "AND column_name = 'singleton_id'"
                )
            )
            lease_precision_rows = (
                await connection.execute(
                    text(
                        "SELECT table_name, column_name, datetime_precision "
                        "FROM information_schema.columns "
                        "WHERE table_schema = DATABASE() AND "
                        "((table_name = 'console_rule_operation' AND "
                        "column_name = 'work_lease_expires_at') OR "
                        "(table_name = 'console_rule_activation_plan' AND "
                        "column_name = 'claim_lease_expires_at'))"
                    )
                )
            ).all()
        self.assertIs(initialized, False)
        self.assertEqual(version_length, 128)
        self.assertFalse(guard_autoincrement)
        self.assertEqual(
            {
                (table_name, column_name): precision
                for table_name, column_name, precision in lease_precision_rows
            },
            {
                ("console_rule_operation", "work_lease_expires_at"): 3,
                (
                    "console_rule_activation_plan",
                    "claim_lease_expires_at",
                ): 3,
            },
        )

        await upgrade_database(self.engine)

    async def test_concurrent_last_admin_mutations_are_serialized(self) -> None:
        test_suffix = uuid4().hex
        account_ids = (str(uuid4()), str(uuid4()))
        request_keys = (
            f"mysql-last-admin-{test_suffix}-a",
            f"mysql-last-admin-{test_suffix}-b",
        )
        request_ids = (
            f"mysql-request-{test_suffix}-a",
            f"mysql-request-{test_suffix}-b",
        )
        tokens = (
            f"mysql-session-{test_suffix}-a",
            f"mysql-session-{test_suffix}-b",
        )
        csrf_values = (
            f"mysql-csrf-{test_suffix}-a",
            f"mysql-csrf-{test_suffix}-b",
        )
        now = datetime.now(UTC)
        hasher = PasswordHashService()
        actors = tuple(
            AccountCommandActor(
                account_id=account_id,
                session_digest=hashlib.sha256(token.encode("ascii")).hexdigest(),
                csrf_digest=hashlib.sha256(csrf.encode("ascii")).hexdigest(),
            )
            for account_id, token, csrf in zip(account_ids, tokens, csrf_values)
        )

        async with self.engine.begin() as connection:
            await connection.execute(
                update(ConsoleGuardRecord)
                .where(ConsoleGuardRecord.singleton_id == 1)
                .values(initialized=True, revision=1, initialized_at=now)
            )
            for index, account_id in enumerate(account_ids):
                username = f"mysql-admin-{test_suffix}-{index}"
                await connection.execute(
                    insert(AccountRecord).values(
                        account_id=account_id,
                        username=username,
                        username_key=hashlib.sha256(username.encode()).hexdigest(),
                        password_hash=hasher.hash_password("synthetic-test-password"),
                        role_id=AccountRole.ADMIN.value,
                        status="active",
                        built_in=False,
                        last_login_at=None,
                        revision=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await connection.execute(
                    insert(AuthenticationSessionRecord).values(
                        session_hash=hashlib.sha256(tokens[index].encode()).hexdigest(),
                        account_id=account_id,
                        session_epoch=str(uuid4()),
                        csrf_hash=hashlib.sha256(
                            csrf_values[index].encode()
                        ).hexdigest(),
                        created_at=now,
                        expires_at=now + timedelta(hours=1),
                        revoked_at=None,
                    )
                )

        trigger_name = f"sentinel_test_delay_role_{uuid4().hex}"
        async with self.engine.begin() as connection:
            await connection.exec_driver_sql(
                f'''CREATE TRIGGER `{trigger_name}` BEFORE UPDATE ON console_account
                    FOR EACH ROW
                    BEGIN
                        IF OLD.role_id = 'admin' AND NEW.role_id = 'view' THEN
                            DO SLEEP(0.15);
                        END IF;
                    END'''
            )

        try:
            service = MutateAccount(
                store=account_command_store.SqlAlchemyAccountCommandStore(
                    self.engine
                ),
                password_hasher=hasher,
                fingerprint_keys={"test-key": b"m" * 32},
                active_fingerprint_key_id="test-key",
            )
            start = asyncio.Event()

            async def demote_own_admin_role(index: int):
                await start.wait()
                return await service.execute(
                    actor=actors[index],
                    command=AccountMutation(
                        request_key=request_keys[index],
                        kind=AccountCommandKind.ROLE,
                        account_id=account_ids[index],
                        expected_revision=1,
                        role_id=AccountRole.VIEW,
                    ),
                    request_id=request_ids[index],
                    now=now,
                )

            tasks = [
                asyncio.create_task(demote_own_admin_role(index))
                for index in range(2)
            ]
            start.set()
            results = await asyncio.gather(*tasks)
            self.assertCountEqual(
                [(result.status, result.reason) for result in results],
                [
                    (AccountOperationStatus.COMPLETED, None),
                    (AccountOperationStatus.REJECTED, AccountCommandReason.LAST_ADMIN),
                ],
            )
            async with self.engine.begin() as connection:
                active_admins = await connection.scalar(
                    select(func.count())
                    .select_from(AccountRecord)
                    .where(
                        AccountRecord.status == "active",
                        AccountRecord.role_id == AccountRole.ADMIN.value,
                    )
                )
            self.assertEqual(active_admins, 1)
        finally:
            async with self.engine.begin() as connection:
                await connection.exec_driver_sql(
                    f"DROP TRIGGER IF EXISTS `{trigger_name}`"
                )
                await connection.execute(
                    AccountOperationRecord.__table__.delete().where(
                        AccountOperationRecord.request_key.in_(request_keys)
                    )
                )
                await connection.execute(
                    AuditEventRecord.__table__.delete().where(
                        AuditEventRecord.request_id.in_(request_ids)
                    )
                )
                await connection.execute(
                    AuthenticationSessionRecord.__table__.delete().where(
                        AuthenticationSessionRecord.account_id.in_(account_ids)
                    )
                )
                await connection.execute(
                    AccountRecord.__table__.delete().where(
                        AccountRecord.account_id.in_(account_ids)
                    )
                )
                await connection.execute(
                    update(ConsoleGuardRecord)
                    .where(ConsoleGuardRecord.singleton_id == 1)
                    .values(initialized=False, revision=0, initialized_at=None)
                )

