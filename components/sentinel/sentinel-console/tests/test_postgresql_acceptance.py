"""Opt-in PostgreSQL migration and last-administrator concurrency acceptance."""

from __future__ import annotations

import asyncio
import hashlib
import os
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
from atlas_richie.sentinel_console.infrastructure.persistence.base import ConsoleBase
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    _migration_lock_identity,
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
from bootstrap_database_acceptance_support import (
    assert_bootstrap_retries_are_deduplicated_and_actor_bound,
    assert_competing_bootstrap_initializations_are_serialized,
    assert_first_run_http_persists_on_real_database,
    assert_sql_identity_http_persists_credentials_and_sessions,
    assert_sql_login_cooldown_serializes_across_processes,
    assert_sql_login_cooldown_shared_across_app_instances,
    assert_two_uvicorn_workers_serve_sql_login_cooldown,
)
from rule_activation_plan_consul_database_acceptance import (
    assert_real_consul_publication_completes_before_plan_association,
)
from rule_activation_plan_consul_preflight_acceptance import (
    assert_consul_restore_preflight_blocks_external_change,
)
from rule_activation_plan_database_acceptance import (
    assert_activation_recovers_completed_publication_after_lost_association,
    assert_cancel_racing_activation_claim_preserves_started_publication,
    assert_independent_plan_workers_fence_and_recover,
)
from rule_activation_plan_nacos_database_acceptance import (
    assert_real_nacos_publication_completes_before_plan_association,
)
from rule_binding_registration_database_acceptance import (
    assert_competing_same_key_registrations_are_idempotent,
)
from rule_publication_consul_database_acceptance import (
    assert_consul_process_termination_recovers_after_real_write,
    assert_sql_activation_plan_publishes_and_restores_to_disposable_consul,
    assert_sql_outbox_publishes_to_disposable_consul,
)
from rule_publication_nacos_database_acceptance import (
    assert_sql_outbox_publishes_create_only_to_disposable_nacos,
)
from rule_publication_receipt_database_acceptance import (
    assert_runtime_publication_receipt_persistence,
)
from rule_publication_receipt_outbox_database_acceptance import (
    assert_rule_publication_receipt_outbox_round_trip,
)
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

_DATABASE_URL_ENV = "SENTINEL_CONSOLE_TEST_POSTGRES_URL"
_DATABASE_URL = os.environ.get(_DATABASE_URL_ENV)


def _validated_test_database_url(value: str | None) -> str | None:
    if value is None:
        return None
    url = make_url(value)
    if (
        url.drivername != "postgresql+psycopg"
        or not url.database
        or not url.database.startswith("sentinel_console_test_")
        or url.host not in {"127.0.0.1", "localhost", "postgres"}
    ):
        raise ValueError(
            f"{_DATABASE_URL_ENV} must target an isolated "
            "sentinel_console_test_* database"
        )
    return value


_DATABASE_URL = _validated_test_database_url(_DATABASE_URL)


class _RedactedDatabaseUrl(str):
    """Keep disposable database credentials out of failure tracebacks."""

    def __repr__(self) -> str:
        return "<redacted database URL>"


class AcceptanceDatabaseUrlRedactionTests(unittest.TestCase):
    def test_database_url_repr_is_redacted(self) -> None:
        value = _RedactedDatabaseUrl(
            "postgresql+psycopg://user:synthetic-password@127.0.0.1/"
            "sentinel_console_test_redaction"
        )

        self.assertEqual(repr(value), "<redacted database URL>")


@unittest.skipUnless(
    _DATABASE_URL, f"set {_DATABASE_URL_ENV} to run PostgreSQL acceptance"
)
class PostgreSQLConsoleAcceptanceTest(unittest.IsolatedAsyncioTestCase):
    """Exercise the real PostgreSQL DDL and serialized account mutation path."""

    async def asyncSetUp(self) -> None:
        assert _DATABASE_URL is not None
        self.engine = create_async_engine(_DATABASE_URL, pool_size=5)
        # All acceptance cases share one disposable database; reset it before
        # each case so the first-run scenario cannot inherit a prior guard row.
        async with self.engine.begin() as connection:
            await connection.run_sync(ConsoleBase.metadata.drop_all)
            await connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        await upgrade_database(self.engine)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_runtime_migrations_are_serialized_across_worker_engines(
        self,
    ) -> None:
        """Concurrent fresh workers must not race PostgreSQL Alembic DDL."""
        assert _DATABASE_URL is not None
        async with self.engine.begin() as connection:
            await connection.run_sync(ConsoleBase.metadata.drop_all)
            await connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        second_worker_engine = create_async_engine(_DATABASE_URL, pool_size=1)
        try:
            self.assertEqual(
                _migration_lock_identity(self.engine),
                _migration_lock_identity(second_worker_engine),
            )
            await asyncio.gather(
                upgrade_database(self.engine),
                upgrade_database(second_worker_engine),
            )
            async with self.engine.connect() as connection:
                revision = await connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
            self.assertIsInstance(revision, str)
            self.assertTrue(revision)
        finally:
            await second_worker_engine.dispose()

    async def test_competing_bootstrap_initializations_are_serialized(self) -> None:
        await assert_competing_bootstrap_initializations_are_serialized(
            self.engine, "postgresql"
        )

    async def test_bootstrap_retries_are_deduplicated_and_actor_bound(self) -> None:
        await assert_bootstrap_retries_are_deduplicated_and_actor_bound(
            self.engine, "postgresql"
        )

    async def test_sql_identity_http_persists_credentials_and_sessions(self) -> None:
        await assert_sql_identity_http_persists_credentials_and_sessions(
            self.engine, "postgresql"
        )

    async def test_sql_login_cooldown_is_shared_across_app_instances(self) -> None:
        assert _DATABASE_URL is not None
        await assert_sql_login_cooldown_shared_across_app_instances(
            self.engine, _DATABASE_URL
        )

    async def test_sql_login_cooldown_serializes_across_processes(self) -> None:
        assert _DATABASE_URL is not None
        await assert_sql_login_cooldown_serializes_across_processes(
            self.engine, _DATABASE_URL
        )

    async def test_two_uvicorn_workers_serve_postgresql_login_cooldown_over_http(
        self,
    ) -> None:
        assert _DATABASE_URL is not None
        await assert_two_uvicorn_workers_serve_sql_login_cooldown(
            self, self.engine, _DATABASE_URL, "postgresql"
        )

    async def test_z_full_first_run_http_path_persists_setup(self) -> None:
        await assert_first_run_http_persists_on_real_database(self.engine, "postgresql")

    async def test_concurrent_rule_binding_retries_are_idempotent(self) -> None:
        await assert_competing_same_key_registrations_are_idempotent(
            self.engine, "postgresql"
        )

    async def test_independent_activation_plan_workers_fence_and_recover(self) -> None:
        assert _DATABASE_URL is not None
        await assert_independent_plan_workers_fence_and_recover(
            self, self.engine, _DATABASE_URL
        )

    async def test_activation_recovers_completed_publication_after_lost_association(
        self,
    ) -> None:
        assert _DATABASE_URL is not None
        await assert_activation_recovers_completed_publication_after_lost_association(
            self, self.engine, _DATABASE_URL
        )

    async def test_cancel_racing_activation_claim_preserves_started_publication(
        self,
    ) -> None:
        assert _DATABASE_URL is not None
        await assert_cancel_racing_activation_claim_preserves_started_publication(
            self, self.engine, _DATABASE_URL
        )

    async def test_rule_publication_receipt_store_round_trip(self) -> None:
        await assert_runtime_publication_receipt_persistence(
            self, self.engine, "postgresql"
        )

    async def test_rule_publication_receipt_durable_outbox_round_trip(self) -> None:
        await assert_rule_publication_receipt_outbox_round_trip(
            self, self.engine, "postgresql"
        )

    @unittest.skipUnless(
        os.environ.get("SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE") == "1",
        "set SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 to start disposable Consul",
    )
    async def test_sql_rule_outbox_publishes_to_disposable_consul(self) -> None:
        await assert_sql_outbox_publishes_to_disposable_consul(self.engine)

    @unittest.skipUnless(
        os.environ.get("SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE") == "1",
        "set SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 to start disposable Consul",
    )
    async def test_consul_process_termination_recovers_after_real_write(self) -> None:
        assert _DATABASE_URL is not None
        await assert_consul_process_termination_recovers_after_real_write(
            self.engine, _DATABASE_URL
        )

    @unittest.skipUnless(
        os.environ.get("SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE") == "1",
        "set SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 to start disposable Consul",
    )
    async def test_sql_activation_plan_publishes_and_restores_to_disposable_consul(
        self,
    ) -> None:
        await assert_sql_activation_plan_publishes_and_restores_to_disposable_consul(
            self.engine
        )

    @unittest.skipUnless(
        os.environ.get("SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE") == "1",
        "set SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 to start disposable Consul",
    )
    async def test_consul_restore_preflight_blocks_prior_external_change(self) -> None:
        await assert_consul_restore_preflight_blocks_external_change(self.engine)

    @unittest.skipUnless(
        os.environ.get("SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE") == "1",
        "set SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 to start disposable Consul",
    )
    async def test_real_consul_publication_completes_before_plan_association(
        self,
    ) -> None:
        assert _DATABASE_URL is not None
        await asyncio.wait_for(
            assert_real_consul_publication_completes_before_plan_association(
                self.engine, _DATABASE_URL
            ),
            timeout=150,
        )

    @unittest.skipUnless(
        os.environ.get("SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE") == "1",
        "set SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE=1 to start disposable Nacos",
    )
    async def test_real_nacos_publication_completes_before_plan_association(
        self,
    ) -> None:
        assert _DATABASE_URL is not None
        await asyncio.wait_for(
            assert_real_nacos_publication_completes_before_plan_association(
                self.engine, _RedactedDatabaseUrl(_DATABASE_URL)
            ),
            timeout=180,
        )

    @unittest.skipUnless(
        os.environ.get("SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE") == "1",
        "set SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE=1 to start disposable Nacos",
    )
    async def test_sql_rule_outbox_creates_config_in_disposable_nacos(self) -> None:
        await assert_sql_outbox_publishes_create_only_to_disposable_nacos(self.engine)

    async def test_migration_and_last_admin_mutations_serialize(self) -> None:
        async with self.engine.begin() as connection:
            initialized = await connection.scalar(
                select(ConsoleGuardRecord.initialized).where(
                    ConsoleGuardRecord.singleton_id == 1
                )
            )
        self.assertIs(initialized, False)

        # Alembic must safely recognize the already-applied head revision.
        await upgrade_database(self.engine)

        test_suffix = uuid4().hex
        account_ids = (str(uuid4()), str(uuid4()))
        request_keys = (
            f"pg-last-admin-{test_suffix}-a",
            f"pg-last-admin-{test_suffix}-b",
        )
        request_ids = (
            f"pg-request-{test_suffix}-a",
            f"pg-request-{test_suffix}-b",
        )
        tokens = (f"pg-session-{test_suffix}-a", f"pg-session-{test_suffix}-b")
        csrf_values = (f"pg-csrf-{test_suffix}-a", f"pg-csrf-{test_suffix}-b")
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
                username = f"pg-admin-{test_suffix}-{index}"
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

        trigger_suffix = uuid4().hex
        function_name = f"sentinel_test_delay_role_{trigger_suffix}"
        trigger_name = f"sentinel_test_delay_role_{trigger_suffix}"
        async with self.engine.begin() as connection:
            await connection.exec_driver_sql(
                f'''CREATE FUNCTION "{function_name}"() RETURNS trigger
                    LANGUAGE plpgsql AS $$ BEGIN
                    IF OLD.role_id = 'admin' AND NEW.role_id = 'view' THEN
                        PERFORM pg_sleep(0.15);
                    END IF;
                    RETURN NEW;
                    END; $$'''
            )
            await connection.exec_driver_sql(
                f'''CREATE TRIGGER "{trigger_name}" BEFORE UPDATE OF role_id
                    ON console_account FOR EACH ROW
                    EXECUTE FUNCTION "{function_name}"()'''
            )

        try:
            service = MutateAccount(
                store=account_command_store.SqlAlchemyAccountCommandStore(self.engine),
                password_hasher=hasher,
                fingerprint_keys={"test-key": b"p" * 32},
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
                asyncio.create_task(demote_own_admin_role(index)) for index in range(2)
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
                    f'DROP TRIGGER IF EXISTS "{trigger_name}" ON console_account'
                )
                await connection.exec_driver_sql(
                    f'DROP FUNCTION IF EXISTS "{function_name}"()'
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
