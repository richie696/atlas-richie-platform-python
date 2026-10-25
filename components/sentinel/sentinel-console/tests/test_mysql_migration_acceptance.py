"""Opt-in MySQL migration compatibility acceptance."""

from __future__ import annotations

import asyncio
import hashlib
import os
import ssl
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from atlas_richie.sentinel_console.application.account_commands import (
    AccountCommandActor,
    AccountCommandKind,
    AccountMutation,
    AccountOperationStatus,
    MutateAccount,
)
from atlas_richie.sentinel_console.application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseCheckResult,
    BootstrapDatabaseFailureReason,
    BootstrapDatabaseKind,
)
from atlas_richie.sentinel_console.domain.session import AccountRole
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_connector import (
    BootstrapDatabaseConnector,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_targets import (
    BootstrapDatabaseTargetPolicy,
    BootstrapDatabaseTargetRule,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    account_command_store,
    identity_composition,
    login_attempt_configuration,
)
from atlas_richie.sentinel_console.infrastructure.persistence.base import ConsoleBase
from atlas_richie.sentinel_console.infrastructure.persistence.current_session_reader import (
    SqlAlchemyCurrentSessionReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    _MYSQL_MIGRATION_LOCK_PREFIX,
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
from atlas_richie.sentinel_console.infrastructure.security.account_command_keys import (
    AccountCommandKeyConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.security.client_identity_key import (
    ClientIdentityKeyConfiguration,
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
from httpx import ASGITransport, AsyncClient
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
_CONSOLE_ORIGIN = "https://console.acceptance.invalid"


class _ClosedSetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


@unittest.skipUnless(_DATABASE_URL, f"set {_DATABASE_URL_ENV} to run MySQL acceptance")
class MySQLConsoleMigrationAcceptanceTest(unittest.IsolatedAsyncioTestCase):
    """Exercise current migrations on a real, disposable MySQL server."""

    async def asyncSetUp(self) -> None:
        assert _DATABASE_URL is not None
        self.engine = create_async_engine(_DATABASE_URL, pool_size=5)
        # The suite shares one disposable database; each test starts from the
        # same uninitialized schema and migration revision.
        async with self.engine.begin() as connection:
            await connection.run_sync(ConsoleBase.metadata.drop_all)
            await connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        await upgrade_database(self.engine)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_competing_bootstrap_initializations_are_serialized(self) -> None:
        await assert_competing_bootstrap_initializations_are_serialized(
            self.engine, "mysql"
        )

    async def test_runtime_migrations_are_serialized_across_worker_engines(
        self,
    ) -> None:
        """Concurrent fresh workers must not race Alembic schema creation."""
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

    async def test_mysql_migration_lock_is_exclusive_across_connections(self) -> None:
        """The MySQL lock used by startup must serialize independent workers."""
        assert _DATABASE_URL is not None
        second_worker_engine = create_async_engine(_DATABASE_URL, pool_size=1)
        lock_name = (
            _MYSQL_MIGRATION_LOCK_PREFIX
            + f"{_migration_lock_identity(self.engine):016x}"
        )
        try:
            async with (
                self.engine.connect() as first,
                second_worker_engine.connect() as second,
            ):
                first_id = await first.scalar(text("SELECT CONNECTION_ID()"))
                second_id = await second.scalar(text("SELECT CONNECTION_ID()"))
                self.assertNotEqual(first_id, second_id)
                self.assertEqual(
                    1,
                    await first.scalar(
                        text("SELECT GET_LOCK(:lock_name, 0)"),
                        {"lock_name": lock_name},
                    ),
                )
                self.assertEqual(
                    0,
                    await second.scalar(
                        text("SELECT GET_LOCK(:lock_name, 0)"),
                        {"lock_name": lock_name},
                    ),
                )
                self.assertEqual(
                    1,
                    await first.scalar(
                        text("SELECT RELEASE_LOCK(:lock_name)"),
                        {"lock_name": lock_name},
                    ),
                )
                self.assertEqual(
                    1,
                    await second.scalar(
                        text("SELECT GET_LOCK(:lock_name, 0)"),
                        {"lock_name": lock_name},
                    ),
                )
                await second.scalar(
                    text("SELECT RELEASE_LOCK(:lock_name)"),
                    {"lock_name": lock_name},
                )
        finally:
            await second_worker_engine.dispose()

    async def test_bootstrap_retries_are_deduplicated_and_actor_bound(self) -> None:
        await assert_bootstrap_retries_are_deduplicated_and_actor_bound(
            self.engine, "mysql"
        )

    async def test_sql_identity_http_persists_credentials_and_sessions(self) -> None:
        await assert_sql_identity_http_persists_credentials_and_sessions(
            self.engine, "mysql"
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

    async def test_two_uvicorn_workers_serve_mysql_login_cooldown_over_http(
        self,
    ) -> None:
        """Exercise the deployed CLI, worker factory, runtime locator, and SQL limiter."""
        assert _DATABASE_URL is not None
        await assert_two_uvicorn_workers_serve_sql_login_cooldown(
            self, self.engine, _DATABASE_URL, "mysql"
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
        await assert_runtime_publication_receipt_persistence(self, self.engine, "mysql")

    async def test_rule_publication_receipt_durable_outbox_round_trip(self) -> None:
        await assert_rule_publication_receipt_outbox_round_trip(
            self, self.engine, "mysql"
        )

    @unittest.skipUnless(
        os.environ.get("SENTINEL_E2E_MYSQL_HOST") == "127.0.0.1"
        and os.environ.get("SENTINEL_E2E_MYSQL_PORT")
        and os.environ.get("SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE"),
        "requires the loopback-only TLS disposable MySQL acceptance harness",
    )
    async def test_real_mysql_bootstrap_connector_classifies_read_only_probe(
        self,
    ) -> None:
        assert _DATABASE_URL is not None
        database_url = make_url(_DATABASE_URL)
        host = os.environ["SENTINEL_E2E_MYSQL_HOST"]
        port = int(os.environ["SENTINEL_E2E_MYSQL_PORT"])
        certificate = os.environ["SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE"]
        policy = BootstrapDatabaseTargetPolicy(
            [
                BootstrapDatabaseTargetRule.create(
                    BootstrapDatabaseKind.MYSQL,
                    "127.0.0.1/32",
                    frozenset({port}),
                )
            ]
        )
        checker = BootstrapDatabaseConnector(
            policy,
            mysql_ssl_context=ssl.create_default_context(cafile=certificate),
        )

        async def check(password: str, target_host: str = host):
            return await checker.check(
                BootstrapDatabaseCandidate(
                    kind=BootstrapDatabaseKind.MYSQL,
                    host=target_host,
                    port=port,
                    database=database_url.database,
                    username=database_url.username,
                    password=password,
                )
            )

        reachable = await check(database_url.password or "")
        self.assertEqual(reachable, BootstrapDatabaseCheckResult(reachable=True))

        rejected = await check("synthetic-invalid-mysql-password")
        self.assertEqual(
            rejected,
            BootstrapDatabaseCheckResult(
                reachable=False,
                reason=BootstrapDatabaseFailureReason.AUTHENTICATION,
            ),
        )

        denied_by_policy = await check(
            database_url.password or "", target_host="192.0.2.123"
        )
        self.assertEqual(
            denied_by_policy,
            BootstrapDatabaseCheckResult(
                reachable=False,
                reason=BootstrapDatabaseFailureReason.CONNECTION,
            ),
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
                self.engine, _DATABASE_URL
            ),
            timeout=180,
        )

    @unittest.skipUnless(
        os.environ.get("SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE") == "1",
        "set SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE=1 to start disposable Nacos",
    )
    async def test_sql_rule_outbox_creates_config_in_disposable_nacos(self) -> None:
        await assert_sql_outbox_publishes_create_only_to_disposable_nacos(self.engine)

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
            timestamp_precision_rows = (
                await connection.execute(
                    text(
                        "SELECT table_name, column_name, datetime_precision "
                        "FROM information_schema.columns "
                        "WHERE table_schema = DATABASE() AND "
                        "((table_name = 'console_rule_operation' AND "
                        "column_name = 'work_lease_expires_at') OR "
                        "(table_name = 'console_rule_activation_plan' AND "
                        "column_name = 'claim_lease_expires_at') OR "
                        "(table_name = 'console_rule_publication' AND "
                        "column_name IN ('created_at', "
                        "'validation_observed_at', 'write_observed_at', "
                        "'read_back_observed_at')))"
                    )
                )
            ).all()
            precision_rounding = (
                await connection.execute(
                    text(
                        "SELECT "
                        "CAST('2026-10-13 03:12:36.900000' AS DATETIME) "
                        "AS second_precision, "
                        "CAST('2026-10-13 03:12:36.900000' AS DATETIME(3)) "
                        "AS millisecond_precision"
                    )
                )
            ).one()
        self.assertIs(initialized, False)
        self.assertEqual(version_length, 128)
        self.assertFalse(guard_autoincrement)
        self.assertEqual(
            precision_rounding.second_precision,
            datetime(2026, 10, 13, 3, 12, 37),
        )
        self.assertEqual(
            precision_rounding.millisecond_precision,
            datetime(2026, 10, 13, 3, 12, 36, 900_000),
        )
        self.assertEqual(
            {
                (table_name, column_name): precision
                for table_name, column_name, precision in timestamp_precision_rows
            },
            {
                ("console_rule_operation", "work_lease_expires_at"): 3,
                (
                    "console_rule_activation_plan",
                    "claim_lease_expires_at",
                ): 3,
                ("console_rule_publication", "created_at"): 3,
                ("console_rule_publication", "validation_observed_at"): 3,
                ("console_rule_publication", "write_observed_at"): 3,
                ("console_rule_publication", "read_back_observed_at"): 3,
            },
        )

        await upgrade_database(self.engine)

    async def test_concurrent_last_admin_mutations_are_serialized(self) -> None:
        test_suffix = uuid4().hex
        account_ids = (str(uuid4()), str(uuid4()))
        request_keys = (
            f"mysql-last-admin-{test_suffix}-a",
            f"mysql-last-admin-{test_suffix}-b",
            f"mysql-last-admin-{test_suffix}-stale-revision",
        )
        request_ids = (
            f"mysql-request-{test_suffix}-a",
            f"mysql-request-{test_suffix}-b",
            f"mysql-request-{test_suffix}-stale-revision",
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
                f"""CREATE TRIGGER `{trigger_name}` BEFORE UPDATE ON console_account
                    FOR EACH ROW
                    BEGIN
                        IF OLD.role_id = 'admin' AND NEW.role_id = 'view' THEN
                            DO SLEEP(0.15);
                        END IF;
                    END"""
            )

        try:
            app = identity_composition.build_sql_identity_app(
                self.engine,
                attempt_limit=login_attempt_configuration.LoginAttemptLimitConfiguration(
                    5, 300, 300
                ),
                account_command_keys=AccountCommandKeyConfiguration(
                    "acceptance-v1", {"acceptance-v1": b"m" * 32}
                ),
                client_identity_key=ClientIdentityKeyConfiguration(b"c" * 32),
                session_ttl=timedelta(hours=1),
                setup_window_reader=_ClosedSetupWindow(),
                allowed_browser_origins=frozenset({_CONSOLE_ORIGIN}),
            )
            start = asyncio.Event()

            async def demote_own_admin_role(index: int) -> dict[str, object]:
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url=_CONSOLE_ORIGIN,
                ) as client:
                    client.cookies.set(
                        "sentinel_session",
                        tokens[index],
                        domain="console.acceptance.invalid",
                        path="/",
                    )
                    client.cookies.set(
                        "__Host-sentinel_csrf",
                        csrf_values[index],
                        domain="console.acceptance.invalid",
                        path="/",
                    )
                    await start.wait()
                    response = await client.post(
                        "/api/v1/accounts/commands",
                        json={
                            "kind": "role",
                            "requestKey": request_keys[index],
                            "accountId": account_ids[index],
                            "revision": "1",
                            "roleId": "view",
                        },
                        headers={
                            "origin": _CONSOLE_ORIGIN,
                            "x-request-id": request_ids[index],
                            "x-sentinel-csrf": csrf_values[index],
                            "idempotency-key": request_keys[index],
                        },
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    receipt = response.json()
                    self.assertEqual(receipt.get("requestKey"), request_keys[index])
                    return receipt

            tasks = [
                asyncio.create_task(demote_own_admin_role(index)) for index in range(2)
            ]
            start.set()
            results = await asyncio.gather(*tasks)
            self.assertCountEqual(
                [(result.get("status"), result.get("reason")) for result in results],
                [
                    ("completed", None),
                    ("rejected", "last_admin"),
                ],
            )
            rejected_index = next(
                index
                for index, result in enumerate(results)
                if result.get("reason") == "last_admin"
            )
            demoted_index = next(
                index
                for index, result in enumerate(results)
                if result.get("status") == "completed"
            )
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url=_CONSOLE_ORIGIN
            ) as client:
                client.cookies.set(
                    "sentinel_session",
                    tokens[rejected_index],
                    domain="console.acceptance.invalid",
                    path="/",
                )
                client.cookies.set(
                    "__Host-sentinel_csrf",
                    csrf_values[rejected_index],
                    domain="console.acceptance.invalid",
                    path="/",
                )
                reread = await client.get(
                    f"/api/v1/accounts/operations/{request_keys[rejected_index]}",
                    headers={"x-request-id": f"{request_ids[rejected_index]}-readback"},
                )
                self.assertEqual(reread.status_code, 200, reread.text)
                self.assertEqual(reread.json(), results[rejected_index])
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url=_CONSOLE_ORIGIN
            ) as client:
                client.cookies.set(
                    "sentinel_session",
                    tokens[rejected_index],
                    domain="console.acceptance.invalid",
                    path="/",
                )
                client.cookies.set(
                    "__Host-sentinel_csrf",
                    csrf_values[rejected_index],
                    domain="console.acceptance.invalid",
                    path="/",
                )
                stale = await client.post(
                    "/api/v1/accounts/commands",
                    json={
                        "kind": "status",
                        "requestKey": request_keys[2],
                        "accountId": account_ids[demoted_index],
                        "revision": "1",
                        "status": "disabled",
                    },
                    headers={
                        "origin": _CONSOLE_ORIGIN,
                        "x-request-id": request_ids[2],
                        "x-sentinel-csrf": csrf_values[rejected_index],
                        "idempotency-key": request_keys[2],
                    },
                )
                self.assertEqual(stale.status_code, 200, stale.text)
                self.assertEqual(
                    stale.json(),
                    {
                        "status": "rejected",
                        "requestKey": request_keys[2],
                        "reason": "conflict",
                    },
                )
                stale_receipt = await client.get(
                    f"/api/v1/accounts/operations/{request_keys[2]}",
                    headers={"x-request-id": f"{request_ids[2]}-readback"},
                )
                self.assertEqual(stale_receipt.status_code, 200, stale_receipt.text)
                self.assertEqual(stale_receipt.json(), stale.json())
            async with self.engine.begin() as connection:
                active_admins = await connection.scalar(
                    select(func.count())
                    .select_from(AccountRecord)
                    .where(
                        AccountRecord.status == "active",
                        AccountRecord.role_id == AccountRole.ADMIN.value,
                    )
                )
                persisted_roles = set(
                    (
                        await connection.execute(
                            select(
                                AccountRecord.account_id, AccountRecord.role_id
                            ).where(AccountRecord.account_id.in_(account_ids))
                        )
                    ).all()
                )
                persisted_operations = await connection.scalar(
                    select(func.count())
                    .select_from(AccountOperationRecord)
                    .where(AccountOperationRecord.request_key.in_(request_keys))
                )
                persisted_audits = await connection.scalar(
                    select(func.count())
                    .select_from(AuditEventRecord)
                    .where(AuditEventRecord.request_id.in_(request_ids))
                )
            self.assertEqual(active_admins, 1)
            self.assertEqual(
                persisted_roles,
                {
                    (account_ids[demoted_index], "view"),
                    (account_ids[rejected_index], "admin"),
                },
            )
            self.assertEqual(persisted_operations, 3)
            self.assertEqual(persisted_audits, 3)
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

    async def test_disabled_account_sessions_do_not_revive_after_reenable(self) -> None:
        suffix = uuid4().hex
        # AccountRecord.account_id is a canonical UUID with a 36-character
        # database limit; keep descriptive prefixes in usernames, not IDs.
        admin_id = str(uuid4())
        account_id = str(uuid4())
        admin_token = f"mysql-status-admin-session-{suffix}"
        admin_csrf = f"mysql-status-admin-csrf-{suffix}"
        target_token = f"mysql-status-target-session-{suffix}"
        target_csrf = f"mysql-status-target-csrf-{suffix}"
        request_keys = (f"mysql-disable-{suffix}", f"mysql-enable-{suffix}")
        request_ids = (
            f"mysql-disable-request-{suffix}",
            f"mysql-enable-request-{suffix}",
        )
        now = datetime.now(UTC)
        hasher = PasswordHashService()
        async with self.engine.connect() as connection:
            original_guard = (
                await connection.execute(
                    select(
                        ConsoleGuardRecord.initialized,
                        ConsoleGuardRecord.revision,
                        ConsoleGuardRecord.initialized_at,
                    ).where(ConsoleGuardRecord.singleton_id == 1)
                )
            ).one()

        try:
            async with self.engine.begin() as connection:
                await connection.execute(
                    update(ConsoleGuardRecord)
                    .where(ConsoleGuardRecord.singleton_id == 1)
                    .values(
                        initialized=True,
                        revision=1,
                        initialized_at=now,
                    )
                )
                for identity, username, role, token, csrf in (
                    (
                        admin_id,
                        f"status-admin-{suffix}",
                        "admin",
                        admin_token,
                        admin_csrf,
                    ),
                    (
                        account_id,
                        f"status-viewer-{suffix}",
                        "view",
                        target_token,
                        target_csrf,
                    ),
                ):
                    await connection.execute(
                        insert(AccountRecord).values(
                            account_id=identity,
                            username=username,
                            username_key=hashlib.sha256(username.encode()).hexdigest(),
                            password_hash=hasher.hash_password(
                                "synthetic-test-password"
                            ),
                            role_id=role,
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
                            session_hash=hashlib.sha256(token.encode()).hexdigest(),
                            account_id=identity,
                            session_epoch=str(uuid4()),
                            csrf_hash=hashlib.sha256(csrf.encode()).hexdigest(),
                            created_at=now,
                            expires_at=now + timedelta(hours=1),
                            revoked_at=None,
                        )
                    )

            service = MutateAccount(
                store=account_command_store.SqlAlchemyAccountCommandStore(self.engine),
                password_hasher=hasher,
                fingerprint_keys={"test-key": b"s" * 32},
                active_fingerprint_key_id="test-key",
            )
            actor = AccountCommandActor(
                account_id=admin_id,
                session_digest=hashlib.sha256(admin_token.encode()).hexdigest(),
                csrf_digest=hashlib.sha256(admin_csrf.encode()).hexdigest(),
            )
            for request_key, request_id, expected_revision, status in (
                (request_keys[0], request_ids[0], 1, "disabled"),
                (request_keys[1], request_ids[1], 2, "active"),
            ):
                result = await service.execute(
                    actor=actor,
                    command=AccountMutation(
                        request_key=request_key,
                        kind=AccountCommandKind.STATUS,
                        account_id=account_id,
                        expected_revision=expected_revision,
                        status=status,
                    ),
                    request_id=request_id,
                    now=now,
                )
                self.assertEqual(result.status, AccountOperationStatus.COMPLETED)

            target_digest = hashlib.sha256(target_token.encode()).hexdigest()
            async with self.engine.connect() as connection:
                revoked_at = await connection.scalar(
                    select(AuthenticationSessionRecord.revoked_at).where(
                        AuthenticationSessionRecord.session_hash == target_digest
                    )
                )
            active_session = await SqlAlchemyCurrentSessionReader(
                self.engine
            ).read_active_session(target_digest)
            self.assertIsNotNone(revoked_at)
            self.assertIsNone(active_session)
        finally:
            async with self.engine.begin() as connection:
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
                        AuthenticationSessionRecord.account_id.in_(
                            (admin_id, account_id)
                        )
                    )
                )
                await connection.execute(
                    AccountRecord.__table__.delete().where(
                        AccountRecord.account_id.in_((admin_id, account_id))
                    )
                )
                await connection.execute(
                    update(ConsoleGuardRecord)
                    .where(ConsoleGuardRecord.singleton_id == 1)
                    .values(
                        initialized=original_guard.initialized,
                        revision=original_guard.revision,
                        initialized_at=original_guard.initialized_at,
                    )
                )
